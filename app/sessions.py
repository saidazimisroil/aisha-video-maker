"""sessions.py - Per-session storage: folder layout, id validation, file cleanup.

Each video still lives in its own folder ``{data}/sessions/{session_id}/`` holding the
uploaded ``input.pptx``, ``script.txt``, working ``slides/``/``audio/``/``segments/`` and the
final ``output.mp4``. What changed: the job's *metadata* (status, progress, options, output,
title, …) now lives in SQLite (``db.py``), not in a ``meta.json`` file. This module keeps
owning the **filesystem** and stays the single id→path chokepoint.

``session_dir`` rejects any id that is not exactly 32 hex chars. Because that is the only
function mapping an id to a path, it guarantees a request can never reach a file outside
``sessions/`` (no user string is ever path-joined).

After a video succeeds we no longer keep its audio (or other intermediates) on disk — the
Aisha TTS history is the durable audio store, and ``output.mp4`` is all we need. See
``purge_working_files``.
"""

import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from app import db
from app.config import settings

# Job lifecycle states.
PENDING = "PENDING"
RENDERING = "RENDERING"
SYNTHESIZING = "SYNTHESIZING"
ASSEMBLING = "ASSEMBLING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
# Reuse flow: slides are rendered and the job is paused waiting for the user to pick which
# existing audio pairs with each slide. This survives a restart (slides are on disk), so it
# is deliberately NOT swept to FAILED.
AWAITING_PAIRS = "AWAITING_PAIRS"

# States that mean "a worker was mid-run" — swept to FAILED on startup.
IN_FLIGHT = {RENDERING, SYNTHESIZING, ASSEMBLING}
# Non-terminal states left over from a previous instance. The job queue is in-process
# (jobs.py), so on restart it is empty: a PENDING job will never be picked up and an
# IN_FLIGHT job has no worker. Both are swept to FAILED. AWAITING_PAIRS is excluded — it is
# a user-action-pending state whose inputs persist on disk.
UNRESUMABLE = IN_FLIGHT | {PENDING}

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sessions_root() -> Path:
    root = settings.sessions_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_id(session_id: str) -> bool:
    return bool(_ID_RE.match(session_id or ""))


def session_dir(session_id: str) -> Path:
    """Return the session's directory, validating the id first (path-traversal guard)."""
    if not _valid_id(session_id):
        raise ValueError("Invalid session id.")
    return sessions_root() / session_id


# --------------------------------------------------------------------------- #
# Metadata (delegated to the SQLite DB)
# --------------------------------------------------------------------------- #
def read_session(session_id: str) -> Optional[dict]:
    """Return the session's metadata (meta.json-shaped dict) or None if unknown."""
    if not _valid_id(session_id):
        raise ValueError("Invalid session id.")
    return db.get_session(session_id)


# Backwards-compatible alias for the old name.
read_meta = read_session


def update_meta(session_id: str, **changes) -> Optional[dict]:
    db.update_session(session_id, **changes)
    return db.get_session(session_id)


def set_status(session_id: str, status: str, **changes) -> Optional[dict]:
    db.set_status(session_id, status, **changes)
    return db.get_session(session_id)


def set_progress(session_id: str, phase: str, current: int, total: int,
                 message: str = "") -> None:
    db.set_progress(session_id, phase, current, total, message)


def set_title(session_id: str, title: str) -> None:
    db.set_title(session_id, title)


def new_session(options: dict, kind: str = "tts", title: Optional[str] = None) -> str:
    """Create a fresh session folder + initial DB row. Returns the session id."""
    session_id = uuid.uuid4().hex
    d = sessions_root() / session_id
    for sub in ("", "slides", "audio", "segments"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    db.insert_session({
        "id": session_id,
        "title": title,
        "kind": kind,
        "status": PENDING,
        "created_at": _now(),
        "updated_at": _now(),
        "options": options,
        "progress": {"phase": PENDING, "current": 0, "total": 0, "message": "Queued"},
        "has_output": 0,
    })
    return session_id


def output_path(session_id: str) -> Path:
    return session_dir(session_id) / "output.mp4"


def has_output(session_id: str) -> bool:
    return output_path(session_id).exists()


def slide_path(session_id: str, n: int) -> Path:
    """Path to a rendered slide PNG (1-based), used by the reuse pairing UI."""
    return session_dir(session_id) / "slides" / f"slide_{int(n):02d}.png"


def list_sessions(page: int = 1, limit: int = 20, status: Optional[str] = None,
                  search: Optional[str] = None) -> Tuple[List[dict], int]:
    """Return (summaries, total_matching), newest first, paginated/filterable."""
    return db.list_sessions(page=page, limit=limit, status=status, search=search)


def delete_session(session_id: str) -> None:
    """Remove both the on-disk folder and the DB row."""
    shutil.rmtree(session_dir(session_id), ignore_errors=True)
    db.delete_session(session_id)


# --------------------------------------------------------------------------- #
# Working-file cleanup (we don't keep audio after a video is made)
# --------------------------------------------------------------------------- #
def purge_working_files(session_id: str, keep=("output.mp4",)) -> None:
    """Delete every file/dir in the session folder except ``keep``.

    Called once a video is finished so the synthesized/downloaded audio, the rendered
    slides, the ffmpeg segments and the source pptx/pdf do not linger on disk. The Aisha
    TTS history is the durable audio store; ``output.mp4`` is all we keep.
    """
    try:
        d = session_dir(session_id)
    except ValueError:
        return
    keep_set = set(keep)
    if not d.exists():
        return
    for child in d.iterdir():
        if child.name in keep_set:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Retention / startup hygiene (driven by the DB)
# --------------------------------------------------------------------------- #
def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def cleanup_old(max_age_hours: Optional[int] = None,
                max_count: Optional[int] = None) -> int:
    """Delete sessions older than ``max_age_hours`` and trim to the newest ``max_count``.
    Returns how many were removed. Keeps the ephemeral disk from filling between restarts."""
    from datetime import timedelta

    max_age_hours = settings.session_max_age_hours if max_age_hours is None else max_age_hours
    max_count = settings.session_max_count if max_count is None else max_count

    removed = 0

    # Reap abandoned "build from audios" uploads (rendered, never paired) on their own,
    # shorter timer so they don't squat the disk waiting on a user who walked away.
    reuse_cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.reuse_prepare_ttl_hours)
    for sid in db.stale_reuse_prepares(reuse_cutoff.isoformat()):
        delete_session(sid)
        removed += 1

    dated = db.all_ids_by_age()  # newest first
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    keep = []
    for sid, created in dated:
        if _parse(created) < cutoff:
            delete_session(sid)
            removed += 1
        else:
            keep.append(sid)
    for sid in keep[max_count:]:
        delete_session(sid)
        removed += 1
    return removed


def sweep_interrupted() -> int:
    """Mark any session left queued or mid-run (from a previous instance) as FAILED so the
    UI never polls a job that can never progress. AWAITING_PAIRS is intentionally spared."""
    swept = 0
    for sid in db.ids_with_status(UNRESUMABLE):
        set_status(sid, FAILED,
                   error="The server restarted before this video finished. "
                         "Please create the video again.")
        swept += 1
    return swept
