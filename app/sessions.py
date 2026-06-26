"""sessions.py - Per-session storage: layout, meta.json I/O, id validation, cleanup.

Every video lives in its own folder ``{data}/sessions/{session_id}/`` holding its
own ``input.pptx``, ``script.txt``, ``slides/``, ``audio/``, ``segments/`` and
``output.mp4`` — so many videos are organized fully independently. The job's
status and metadata live in ``meta.json`` inside that folder, which doubles as
the source of truth a status poll reads.

``session_dir`` rejects any id that is not exactly 32 hex chars. Because that is
the only function that maps an id to a path, it is the single chokepoint that
guarantees a request can never reach a file outside ``sessions/`` (no user
string is ever path-joined).
"""

import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from app.config import settings

# Job lifecycle states.
PENDING = "PENDING"
RENDERING = "RENDERING"
SYNTHESIZING = "SYNTHESIZING"
ASSEMBLING = "ASSEMBLING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
# States that mean "a worker was mid-run" — swept to FAILED on startup.
IN_FLIGHT = {RENDERING, SYNTHESIZING, ASSEMBLING}
# Non-terminal states left over from a previous instance. The job queue is
# in-process (jobs.py), so on restart it is empty: a PENDING job will never be
# picked up and an IN_FLIGHT job has no worker running it. Both are swept to
# FAILED on startup so the UI never polls a job that can never progress.
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


def _meta_path(session_id: str) -> Path:
    return session_dir(session_id) / "meta.json"


def read_meta(session_id: str) -> Optional[dict]:
    path = _meta_path(session_id)
    if not path.exists():
        return None
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_meta(session_id: str, meta: dict) -> None:
    """Atomically write meta.json (tmp file + os.replace) so a reader never sees half."""
    import json
    meta["updated_at"] = _now()
    path = _meta_path(session_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def update_meta(session_id: str, **changes) -> dict:
    meta = read_meta(session_id) or {}
    meta.update(changes)
    write_meta(session_id, meta)
    return meta


def set_status(session_id: str, status: str, **changes) -> dict:
    return update_meta(session_id, status=status, **changes)


def set_progress(session_id: str, phase: str, current: int, total: int,
                 message: str = "") -> dict:
    return update_meta(
        session_id,
        progress={"phase": phase, "current": current, "total": total,
                  "message": message},
    )


def new_session(options: dict) -> str:
    """Create a fresh session folder + initial meta.json. Returns the session id."""
    session_id = uuid.uuid4().hex
    d = sessions_root() / session_id
    for sub in ("", "slides", "audio", "segments"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "created_at": _now(),
        "updated_at": _now(),
        "status": PENDING,
        "options": options,
        "slide_count": None,
        "slide_size": None,
        "progress": {"phase": PENDING, "current": 0, "total": 0, "message": "Queued"},
        "output": None,
        "error": None,
    }
    write_meta(session_id, meta)
    return session_id


def output_path(session_id: str) -> Path:
    return session_dir(session_id) / "output.mp4"


def has_output(session_id: str) -> bool:
    return output_path(session_id).exists()


def list_sessions() -> List[dict]:
    """Return per-session summaries, newest first."""
    out = []
    for child in sessions_root().iterdir():
        if not child.is_dir() or not _valid_id(child.name):
            continue
        meta = read_meta(child.name)
        if not meta:
            continue
        out.append({
            "session_id": meta.get("session_id", child.name),
            "created_at": meta.get("created_at"),
            "status": meta.get("status"),
            "slide_count": meta.get("slide_count"),
            "has_output": (child / "output.mp4").exists(),
            "error": meta.get("error"),
        })
    out.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return out


def delete_session(session_id: str) -> None:
    shutil.rmtree(session_dir(session_id), ignore_errors=True)


def _created_at(session_id: str) -> datetime:
    meta = read_meta(session_id) or {}
    raw = meta.get("created_at")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    # Fallback to directory mtime.
    ts = session_dir(session_id).stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def cleanup_old(max_age_hours: Optional[int] = None,
                max_count: Optional[int] = None) -> int:
    """Delete sessions older than ``max_age_hours`` and trim to the newest
    ``max_count``. Returns how many were removed. Keeps the ephemeral disk from
    filling between restarts."""
    max_age_hours = settings.session_max_age_hours if max_age_hours is None else max_age_hours
    max_count = settings.session_max_count if max_count is None else max_count

    ids = [c.name for c in sessions_root().iterdir()
           if c.is_dir() and _valid_id(c.name)]
    dated = sorted(((sid, _created_at(sid)) for sid in ids),
                   key=lambda t: t[1], reverse=True)  # newest first

    removed = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    keep = []
    for sid, created in dated:
        if created < cutoff:
            delete_session(sid)
            removed += 1
        else:
            keep.append(sid)
    # Trim by count (keep is already newest-first).
    for sid in keep[max_count:]:
        delete_session(sid)
        removed += 1
    return removed


def sweep_interrupted() -> int:
    """Mark any session left queued or mid-run (from a previous instance) as
    FAILED so the UI never polls a job that can never progress — the in-process
    queue is empty after a restart, so PENDING jobs are orphaned just like
    IN_FLIGHT ones. Returns how many were swept."""
    swept = 0
    for child in sessions_root().iterdir():
        if not child.is_dir() or not _valid_id(child.name):
            continue
        meta = read_meta(child.name)
        if meta and meta.get("status") in UNRESUMABLE:
            set_status(child.name, FAILED,
                       error="The server restarted before this video finished. "
                             "Please create the video again.")
            swept += 1
    return swept
