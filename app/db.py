"""db.py - SQLite persistence: the single source of truth for video/presentation jobs.

History used to be a scan of ``meta.json`` files, one per session folder. That made
listing, filtering, pagination and stats O(folders) and impossible to query. This module
replaces ``meta.json`` with a small SQLite database at ``{DATA_DIR}/aisha.db`` while the
per-session *folder* keeps owning only the working files and the final ``output.mp4``.

Concurrency model: one process (Docker runs ``uvicorn --workers 1``), one background job
worker thread (jobs.py, concurrency=1) plus FastAPI's request threadpool. A single shared
connection (``check_same_thread=False``) guarded by a re-entrant lock around *every* access
is the simplest correct model — WAL + a short busy timeout keep it snappy. Scaling to
multiple processes would need a real DB; that is documented, not supported here.

The DB is the source of truth for metadata; ``sessions.py`` still owns the filesystem and
the id→path validation chokepoint. ``get_session`` returns a dict shaped like the old
``meta.json`` (including ``session_id`` and a reconstructed ``output``) so existing call
sites in ``jobs.py``/``main.py`` change as little as possible.
"""

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import settings

log = logging.getLogger("aisha.db")

# Columns whose Python value is a dict/list and is stored as a JSON string.
_JSON_COLS = {"options", "slide_size", "per_slide", "progress"}
# Every column on the sessions table (id is the 32-hex session id == folder name).
_COLS = (
    "id", "title", "kind", "status", "created_at", "updated_at",
    "options", "slide_count", "slide_size", "duration", "per_slide",
    "error", "progress", "has_output",
)
_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_CONN: Optional[sqlite3.Connection] = None
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Connection / schema
# --------------------------------------------------------------------------- #
def get_conn() -> sqlite3.Connection:
    """Return the shared connection, creating + initialising it on first use."""
    global _CONN
    with _LOCK:
        if _CONN is None:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(settings.db_file), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            _init_schema(conn)
            _CONN = conn
        return _CONN


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            title       TEXT,
            kind        TEXT NOT NULL DEFAULT 'tts',
            status      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            options     TEXT,
            slide_count INTEGER,
            slide_size  TEXT,
            duration    REAL,
            per_slide   TEXT,
            error       TEXT,
            progress    TEXT,
            has_output  INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_status  ON sessions(status);

        CREATE TABLE IF NOT EXISTS reuse_pairs (
            session_id  TEXT NOT NULL,
            slide_index INTEGER NOT NULL,
            audio_id    TEXT,
            audio_url   TEXT NOT NULL,
            PRIMARY KEY (session_id, slide_index),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


def init_db() -> None:
    """Idempotent: ensure the connection + schema exist (called from app lifespan)."""
    get_conn()


# --------------------------------------------------------------------------- #
# Row <-> dict marshalling
# --------------------------------------------------------------------------- #
def _encode(col: str, value):
    if col in _JSON_COLS and value is not None and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if col == "has_output":
        return 1 if value else 0
    return value


def _decode_row(row: sqlite3.Row) -> dict:
    """Turn a sessions row into the meta.json-shaped dict the app expects."""
    d = dict(row)
    for col in _JSON_COLS:
        raw = d.get(col)
        d[col] = json.loads(raw) if raw else None
    d["has_output"] = bool(d.get("has_output"))
    # Aliases / reconstructed fields for backward compatibility with old meta.json.
    d["session_id"] = d["id"]
    if d["has_output"] or d.get("duration") is not None:
        d["output"] = {
            "path": "output.mp4",
            "duration": d.get("duration"),
            "per_slide": d.get("per_slide"),
        }
    else:
        d["output"] = None
    return d


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def insert_session(row: dict) -> None:
    """Insert a brand-new session row. Missing columns fall back to sensible defaults."""
    now = _now()
    full = {
        "id": row["id"],
        "title": row.get("title"),
        "kind": row.get("kind", "tts"),
        "status": row.get("status", "PENDING"),
        "created_at": row.get("created_at", now),
        "updated_at": row.get("updated_at", now),
        "options": row.get("options"),
        "slide_count": row.get("slide_count"),
        "slide_size": row.get("slide_size"),
        "duration": row.get("duration"),
        "per_slide": row.get("per_slide"),
        "error": row.get("error"),
        "progress": row.get("progress"),
        "has_output": row.get("has_output", 0),
    }
    cols = list(_COLS)
    values = [_encode(c, full[c]) for c in cols]
    placeholders = ",".join("?" for _ in cols)
    with _LOCK:
        conn = get_conn()
        conn.execute(
            f"INSERT OR REPLACE INTO sessions ({','.join(cols)}) VALUES ({placeholders})",
            values,
        )
        conn.commit()


def update_session(session_id: str, **changes) -> None:
    """Update arbitrary columns. ``output`` may be passed as a dict and is decomposed
    into ``duration``/``per_slide``/``has_output``. ``updated_at`` is always bumped."""
    # Decompose a meta-style output dict so old call sites keep working.
    output = changes.pop("output", None)
    if isinstance(output, dict):
        changes.setdefault("duration", output.get("duration"))
        changes.setdefault("per_slide", output.get("per_slide"))
        changes.setdefault("has_output", 1)

    changes = {k: v for k, v in changes.items() if k in _COLS and k != "id"}
    changes["updated_at"] = _now()
    sets = ", ".join(f"{c}=?" for c in changes)
    values = [_encode(c, v) for c, v in changes.items()]
    values.append(session_id)
    with _LOCK:
        conn = get_conn()
        conn.execute(f"UPDATE sessions SET {sets} WHERE id=?", values)
        conn.commit()


def set_status(session_id: str, status: str, **changes) -> None:
    update_session(session_id, status=status, **changes)


def set_progress(session_id: str, phase: str, current: int, total: int,
                 message: str = "") -> None:
    update_session(session_id, progress={
        "phase": phase, "current": current, "total": total, "message": message})


def set_title(session_id: str, title: str) -> None:
    update_session(session_id, title=title)


def set_output(session_id: str, duration: float, per_slide: list) -> None:
    update_session(session_id, duration=duration, per_slide=per_slide, has_output=1)


def delete_session(session_id: str) -> None:
    with _LOCK:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()


def insert_reuse_pairs(session_id: str, pairs: List[dict]) -> None:
    """Replace the slide↔audio mapping for a reuse job."""
    rows = [
        (session_id, int(p["slide_index"]), p.get("audio_id"), p["audio_url"])
        for p in pairs
    ]
    with _LOCK:
        conn = get_conn()
        conn.execute("DELETE FROM reuse_pairs WHERE session_id=?", (session_id,))
        conn.executemany(
            "INSERT INTO reuse_pairs (session_id, slide_index, audio_id, audio_url) "
            "VALUES (?,?,?,?)", rows)
        conn.commit()


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def get_session(session_id: str) -> Optional[dict]:
    with _LOCK:
        cur = get_conn().execute("SELECT * FROM sessions WHERE id=?", (session_id,))
        row = cur.fetchone()
    return _decode_row(row) if row else None


def get_reuse_pairs(session_id: str) -> List[dict]:
    with _LOCK:
        cur = get_conn().execute(
            "SELECT slide_index, audio_id, audio_url FROM reuse_pairs "
            "WHERE session_id=? ORDER BY slide_index", (session_id,))
        return [dict(r) for r in cur.fetchall()]


def list_sessions(page: int = 1, limit: int = 20, status: Optional[str] = None,
                  search: Optional[str] = None) -> Tuple[List[dict], int]:
    """Return (summaries, total_matching). Newest first, paginated and filterable."""
    page = max(1, page)
    limit = max(1, min(limit, 200))
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if search:
        where.append("(title LIKE ? OR id LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    with _LOCK:
        conn = get_conn()
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM sessions{clause}", params).fetchone()["n"]
        rows = conn.execute(
            "SELECT id, title, kind, status, created_at, updated_at, slide_count, "
            f"duration, has_output, error FROM sessions{clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit]).fetchall()

    summaries = []
    for r in rows:
        d = dict(r)
        d["session_id"] = d["id"]
        d["has_output"] = bool(d["has_output"])
        summaries.append(d)
    return summaries, total


def all_ids_by_age() -> List[Tuple[str, str]]:
    """Return (id, created_at) for every session, newest first (drives cleanup)."""
    with _LOCK:
        rows = get_conn().execute(
            "SELECT id, created_at FROM sessions ORDER BY created_at DESC").fetchall()
    return [(r["id"], r["created_at"]) for r in rows]


def ids_with_status(statuses) -> List[str]:
    statuses = list(statuses)
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    with _LOCK:
        rows = get_conn().execute(
            f"SELECT id FROM sessions WHERE status IN ({placeholders})",
            statuses).fetchall()
    return [r["id"] for r in rows]


def stale_reuse_prepares(cutoff_iso: str) -> List[str]:
    """Ids of 'build from audios' jobs that have been waiting to be paired longer than the
    cutoff. They get their own (shorter) retention so an abandoned upload is reaped early."""
    with _LOCK:
        rows = get_conn().execute(
            "SELECT id FROM sessions WHERE status='AWAITING_PAIRS' AND created_at < ?",
            (cutoff_iso,)).fetchall()
    return [r["id"] for r in rows]


def stats() -> dict:
    """Aggregate counts for the Overview page."""
    with _LOCK:
        conn = get_conn()
        total = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        by_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM sessions GROUP BY status")}
        by_kind = {r["kind"]: r["n"] for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM sessions GROUP BY kind")}
        agg = conn.execute(
            "SELECT COALESCE(SUM(duration),0) AS dur, COALESCE(SUM(slide_count),0) AS sl "
            "FROM sessions WHERE has_output=1").fetchone()
    return {
        "total": total,
        "by_status": by_status,
        "by_kind": by_kind,
        "total_duration": round(agg["dur"], 2),
        "total_slides": agg["sl"],
    }


# --------------------------------------------------------------------------- #
# One-time migration from legacy meta.json folders
# --------------------------------------------------------------------------- #
def migrate_legacy_meta() -> int:
    """Import any pre-existing ``{sessions}/{id}/meta.json`` into the DB.

    Idempotent via ``INSERT OR IGNORE`` (an already-imported id is left untouched), so it
    is safe to run on every startup. Returns the number of rows newly inserted.
    """
    root = settings.sessions_root
    if not root.exists():
        return 0
    inserted = 0
    with _LOCK:
        conn = get_conn()
        for child in root.iterdir():
            if not child.is_dir() or not _ID_RE.match(child.name):
                continue
            meta_path = child / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            output = meta.get("output") or {}
            row = {
                "id": meta.get("session_id", child.name),
                "title": meta.get("title"),
                "kind": meta.get("kind", "tts"),
                "status": meta.get("status", "SUCCESS"),
                "created_at": meta.get("created_at", _now()),
                "updated_at": meta.get("updated_at", _now()),
                "options": meta.get("options"),
                "slide_count": meta.get("slide_count"),
                "slide_size": meta.get("slide_size"),
                "duration": output.get("duration"),
                "per_slide": output.get("per_slide"),
                "error": meta.get("error"),
                "progress": meta.get("progress"),
                "has_output": 1 if (child / "output.mp4").exists() else 0,
            }
            cols = list(_COLS)
            values = [_encode(c, row.get(c)) for c in cols]
            placeholders = ",".join("?" for _ in cols)
            cur = conn.execute(
                f"INSERT OR IGNORE INTO sessions ({','.join(cols)}) "
                f"VALUES ({placeholders})", values)
            inserted += cur.rowcount or 0
        conn.commit()
    if inserted:
        log.info("Migrated %d legacy session(s) from meta.json into SQLite.", inserted)
    return inserted
