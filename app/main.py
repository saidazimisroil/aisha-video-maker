"""main.py - FastAPI service for Aisha Video Maker.

API-only (the React dashboard is a separate static build), so CORS is enabled from
``AISHA_ALLOWED_ORIGINS``. Three job flows are exposed:

* **Create** (``POST /api/sessions``) — pptx + script → synthesize → assemble.
* **Build from existing audios** — ``POST /api/sessions/reuse/prepare`` renders the slides,
  the UI fetches thumbnails (``/slides/{n}.png``) and pairs each with a clip from the audio
  library, then ``POST /api/sessions/{id}/reuse/build`` stitches the video (no TTS spent).
* **Audio library** — ``GET /api/audios`` proxies the account's Aisha TTS history and
  ``GET /api/audios/stream`` proxies a clip's bytes so the browser can preview it without
  ever seeing the API key.

All job metadata lives in SQLite (db.py); the UI polls ``/status`` and lists ``/api/sessions``.
"""

import logging
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app import aisha, db, sessions
from app.config import settings
from app.jobs import QueueFull, manager
from app.jobs import REUSE_BUILD, REUSE_PREPARE, TTS
from app.pipeline import find_soffice, find_tool
from app.schemas import (
    ALLOWED_HEIGHTS,
    FPS_MAX,
    FPS_MIN,
    HEIGHT_TO_WIDTH,
    SPEED_MAX,
    SPEED_MIN,
    AccountResponse,
    AudioList,
    CreateSessionResponse,
    HealthResponse,
    Language,
    Mood,
    RenameRequest,
    ReuseBuildRequest,
    SessionList,
    StatsResponse,
    StatusResponse,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("aisha.main")

PPTX_MAGIC = b"PK\x03\x04"  # pptx is a zip container
CHUNK = 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    sessions.sessions_root()       # ensure the storage dir exists
    db.init_db()                   # open the connection + create tables
    migrated = db.migrate_legacy_meta()
    if migrated:
        log.info("Imported %d legacy session(s) into SQLite.", migrated)
    swept = sessions.sweep_interrupted()
    if swept:
        log.info("Swept %d interrupted session(s) to FAILED.", swept)
    removed = sessions.cleanup_old()
    if removed:
        log.info("Cleaned up %d old session(s).", removed)
    manager.start()
    yield


app = FastAPI(title="Aisha Video Maker", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse)
def healthz():
    def present(finder, *args):
        try:
            finder(*args)
            return True
        except Exception:
            return False

    soffice = present(find_soffice)
    ffmpeg = present(find_tool, "ffmpeg")
    ffprobe = present(find_tool, "ffprobe")
    return HealthResponse(
        ok=soffice and ffmpeg and ffprobe,
        soffice=soffice, ffmpeg=ffmpeg, ffprobe=ffprobe,
        queue_depth=manager.queue_depth(),
    )


# --------------------------------------------------------------------------- #
# Shared upload helpers
# --------------------------------------------------------------------------- #
def _check_pptx_name(pptx: UploadFile) -> None:
    if not (pptx.filename or "").lower().endswith(".pptx"):
        raise HTTPException(400, "Please upload a .pptx PowerPoint file.")


def _backpressure() -> None:
    if manager.queue_depth() >= settings.max_queue:
        raise HTTPException(429, "The server is busy. Please try again in a few minutes.")


async def _stream_pptx(session_id: str, pptx: UploadFile) -> None:
    """Stream the upload to ``input.pptx`` with a running size cap + magic-byte check.
    Deletes the just-created session and raises HTTPException on any rejection."""
    dest = sessions.session_dir(session_id) / "input.pptx"
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await pptx.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        413, f"File too large (limit {settings.max_upload_mb} MB).")
                fh.write(chunk)
    except HTTPException:
        sessions.delete_session(session_id)
        raise
    finally:
        await pptx.close()

    with dest.open("rb") as fh:
        if fh.read(4) != PPTX_MAGIC:
            sessions.delete_session(session_id)
            raise HTTPException(400, "That file is not a valid .pptx presentation.")


def _clean_title(title: str | None) -> str | None:
    title = (title or "").strip()
    return title[:120] or None


# --------------------------------------------------------------------------- #
# Create a session (upload + enqueue) — classic TTS flow
# --------------------------------------------------------------------------- #
@app.post("/api/sessions", response_model=CreateSessionResponse, status_code=202)
async def create_session(
    pptx: UploadFile = File(...),
    script: str = Form(...),
    title: str = Form(None),
    language: Language = Form(Language(settings.default_language)),
    mood: Mood = Form(Mood(settings.default_mood)),
    height: int = Form(settings.default_height),
    fps: int = Form(settings.default_fps),
    dpi: int = Form(settings.default_dpi),
    speed: float = Form(settings.default_speed),
):
    if height not in ALLOWED_HEIGHTS:
        raise HTTPException(400, f"height must be one of {ALLOWED_HEIGHTS}.")
    if not (FPS_MIN <= fps <= FPS_MAX):
        raise HTTPException(400, f"fps must be between {FPS_MIN} and {FPS_MAX}.")
    if not (72 <= dpi <= 300):
        raise HTTPException(400, "dpi must be between 72 and 300.")
    if not (speed == 0 or SPEED_MIN <= speed <= SPEED_MAX):
        raise HTTPException(
            400, f"speed must be 0 (default) or between {SPEED_MIN} and {SPEED_MAX}.")
    if not script or not script.strip():
        raise HTTPException(400, "The narration script is empty.")
    _check_pptx_name(pptx)
    _backpressure()
    _safe_cleanup()

    options = {
        "language": language.value, "mood": mood.value,
        "height": height, "width": HEIGHT_TO_WIDTH[height],
        "fps": fps, "dpi": dpi, "speed": speed,
    }
    session_id = sessions.new_session(options, kind="tts", title=_clean_title(title))
    await _stream_pptx(session_id, pptx)
    (sessions.session_dir(session_id) / "script.txt").write_text(script, encoding="utf-8")

    try:
        manager.submit(session_id, action=TTS)
    except QueueFull as e:
        sessions.delete_session(session_id)
        raise HTTPException(429, str(e))

    log.info("Created TTS session %s (%s)", session_id, options)
    return CreateSessionResponse(session_id=session_id, status=sessions.PENDING, kind="tts")


# --------------------------------------------------------------------------- #
# Build from existing audios — two-step (prepare → pair → build)
# --------------------------------------------------------------------------- #
@app.post("/api/sessions/reuse/prepare", response_model=CreateSessionResponse,
          status_code=202)
async def reuse_prepare(
    pptx: UploadFile = File(...),
    title: str = Form(None),
    height: int = Form(settings.default_height),
    fps: int = Form(settings.default_fps),
    dpi: int = Form(settings.default_dpi),
):
    if height not in ALLOWED_HEIGHTS:
        raise HTTPException(400, f"height must be one of {ALLOWED_HEIGHTS}.")
    if not (FPS_MIN <= fps <= FPS_MAX):
        raise HTTPException(400, f"fps must be between {FPS_MIN} and {FPS_MAX}.")
    if not (72 <= dpi <= 300):
        raise HTTPException(400, "dpi must be between 72 and 300.")
    _check_pptx_name(pptx)
    _backpressure()
    _safe_cleanup()

    options = {"height": height, "width": HEIGHT_TO_WIDTH[height], "fps": fps, "dpi": dpi}
    session_id = sessions.new_session(options, kind="reuse", title=_clean_title(title))
    await _stream_pptx(session_id, pptx)

    try:
        manager.submit(session_id, action=REUSE_PREPARE)
    except QueueFull as e:
        sessions.delete_session(session_id)
        raise HTTPException(429, str(e))

    log.info("Created reuse session %s (prepare)", session_id)
    return CreateSessionResponse(
        session_id=session_id, status=sessions.PENDING, kind="reuse")


@app.post("/api/sessions/{session_id}/reuse/build",
          response_model=CreateSessionResponse, status_code=202)
def reuse_build(session_id: str, body: ReuseBuildRequest):
    meta = _require_session(session_id)
    if meta.get("kind") != "reuse":
        raise HTTPException(400, "This session is not a 'build from audios' presentation.")
    if meta.get("status") != sessions.AWAITING_PAIRS:
        raise HTTPException(
            409, "This presentation is not ready for pairing (or is already building).")

    slide_count = meta.get("slide_count")
    if slide_count and len(body.pairs) != slide_count:
        raise HTTPException(
            400, f"You picked {len(body.pairs)} audio(s) but the presentation has "
                 f"{slide_count} slide(s); they must match one-to-one.")
    _backpressure()

    db.insert_reuse_pairs(session_id, [p.model_dump() for p in body.pairs])
    try:
        manager.submit(session_id, action=REUSE_BUILD)
    except QueueFull as e:
        raise HTTPException(429, str(e))

    log.info("Reuse session %s: building (%d pairs)", session_id, len(body.pairs))
    return CreateSessionResponse(
        session_id=session_id, status=sessions.PENDING, kind="reuse")


@app.get("/api/sessions/{session_id}/slides/{n}.png")
def get_slide(session_id: str, n: int):
    """Serve a rendered slide thumbnail (1-based) for the reuse pairing UI."""
    _require_session(session_id)
    if n < 1:
        raise HTTPException(404, "No such slide.")
    path = sessions.slide_path(session_id, n)
    if not path.exists():
        raise HTTPException(404, "Slide not available.")
    return FileResponse(path, media_type="image/png")


# --------------------------------------------------------------------------- #
# Audio library (proxied Aisha TTS history)
# --------------------------------------------------------------------------- #
@app.get("/api/audios", response_model=AudioList)
def list_audios(page: int = 1, limit: int = None, search: str = None,
                language: str = None):
    limit = limit or settings.audio_page_size
    try:
        data = aisha.list_tts(page=page, limit=limit, search=search, language=language)
    except requests.RequestException as e:
        log.warning("Audio library fetch failed: %s", e)
        raise HTTPException(502, "Could not reach the Aisha audio service.")
    return AudioList(**data)


@app.get("/api/audios/stream")
def stream_audio(url: str):
    """Proxy a clip's bytes (server-side key) so the browser can preview it."""
    try:
        content, ctype = aisha.fetch_audio_bytes(url)
    except ValueError:
        raise HTTPException(400, "Invalid or disallowed audio url.")
    except requests.RequestException as e:
        log.warning("Audio stream fetch failed: %s", e)
        raise HTTPException(502, "Could not fetch the audio clip.")
    return Response(content=content, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=3600"})


# --------------------------------------------------------------------------- #
# Status / list / rename / delete
# --------------------------------------------------------------------------- #
def _require_session(session_id: str) -> dict:
    try:
        meta = sessions.read_session(session_id)
    except ValueError:
        raise HTTPException(400, "Invalid session id.")
    if not meta:
        raise HTTPException(404, "Session not found.")
    return meta


def _safe_cleanup() -> None:
    try:
        sessions.cleanup_old()
    except Exception:  # noqa: BLE001
        log.exception("cleanup_old failed (continuing)")


@app.get("/api/sessions/{session_id}/status", response_model=StatusResponse)
def get_status(session_id: str):
    meta = _require_session(session_id)
    return StatusResponse(
        session_id=session_id,
        status=meta.get("status"),
        title=meta.get("title"),
        kind=meta.get("kind", "tts"),
        slide_count=meta.get("slide_count"),
        progress=meta.get("progress"),
        has_output=sessions.has_output(session_id),
        error=meta.get("error"),
        output=meta.get("output"),
    )


@app.get("/api/sessions", response_model=SessionList)
def list_all(page: int = 1, limit: int = 20, status: str = None, search: str = None):
    results, total = sessions.list_sessions(
        page=page, limit=limit, status=status, search=search)
    return SessionList(count=total, page=page, limit=limit, results=results)


@app.patch("/api/sessions/{session_id}")
def rename_session(session_id: str, body: RenameRequest):
    _require_session(session_id)
    title = body.title.strip()[:120]
    if not title:
        raise HTTPException(400, "Title cannot be empty.")
    sessions.set_title(session_id, title)
    return {"session_id": session_id, "title": title}


@app.delete("/api/sessions/{session_id}")
def delete_one(session_id: str):
    _require_session(session_id)
    sessions.delete_session(session_id)
    return {"deleted": session_id}


# --------------------------------------------------------------------------- #
# Dashboard: stats + account balance
# --------------------------------------------------------------------------- #
@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    s = db.stats()
    s["queue_depth"] = manager.queue_depth()
    return StatsResponse(**s)


@app.get("/api/account", response_model=AccountResponse)
def get_account():
    bal = aisha.get_balance()
    if not bal:
        return AccountResponse(available=False)
    return AccountResponse(available=True, balance=bal.get("balance"), raw=bal.get("raw"))


# --------------------------------------------------------------------------- #
# Video download / stream (range-enabled via FileResponse)
# --------------------------------------------------------------------------- #
@app.get("/api/sessions/{session_id}/video")
def get_video(session_id: str, download: bool = False):
    _require_session(session_id)
    path = sessions.output_path(session_id)
    if not path.exists():
        raise HTTPException(404, "The video is not ready yet.")
    headers = None
    if download:
        headers = {"Content-Disposition": f'attachment; filename="{session_id}.mp4"'}
    return FileResponse(path, media_type="video/mp4", headers=headers)
