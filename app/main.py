"""main.py - FastAPI service for Aisha Video Maker.

API-only (the UI is a separate static site on Vercel/Netlify), so CORS is enabled
from ``AISHA_ALLOWED_ORIGINS``. The flow mirrors Aisha's own async TTS model:
``POST /api/sessions`` returns immediately with a session id, the job runs on the
background worker, and the UI polls ``/api/sessions/{id}/status`` until the video
is ready at ``/api/sessions/{id}/video``.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app import sessions
from app.jobs import QueueFull, manager
from app.pipeline import find_soffice, find_tool
from app.schemas import (
    ALLOWED_HEIGHTS,
    FPS_MAX,
    FPS_MIN,
    HEIGHT_TO_WIDTH,
    SPEED_MAX,
    SPEED_MIN,
    CreateSessionResponse,
    HealthResponse,
    Language,
    Mood,
    SessionList,
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
    sessions.sessions_root()  # ensure the storage dir exists
    swept = sessions.sweep_interrupted()
    if swept:
        log.info("Swept %d interrupted session(s) to FAILED.", swept)
    removed = sessions.cleanup_old()
    if removed:
        log.info("Cleaned up %d old session(s).", removed)
    manager.start()
    yield


app = FastAPI(title="Aisha Video Maker", version="1.0.0", lifespan=lifespan)

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
# Create a session (upload + enqueue)
# --------------------------------------------------------------------------- #
@app.post("/api/sessions", response_model=CreateSessionResponse, status_code=202)
async def create_session(
    pptx: UploadFile = File(...),
    script: str = Form(...),
    language: Language = Form(Language(settings.default_language)),
    mood: Mood = Form(Mood(settings.default_mood)),
    height: int = Form(settings.default_height),
    fps: int = Form(settings.default_fps),
    dpi: int = Form(settings.default_dpi),
    speed: float = Form(settings.default_speed),
):
    # --- validate options ------------------------------------------------ #
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

    # --- validate upload basics ----------------------------------------- #
    name = (pptx.filename or "").lower()
    if not name.endswith(".pptx"):
        raise HTTPException(400, "Please upload a .pptx PowerPoint file.")

    # --- back-pressure before we allocate a folder ---------------------- #
    if manager.queue_depth() >= settings.max_queue:
        raise HTTPException(
            429, "The server is busy. Please try again in a few minutes.")

    # --- lazy retention so the ephemeral disk can't fill ---------------- #
    try:
        sessions.cleanup_old()
    except Exception:  # noqa: BLE001
        log.exception("cleanup_old failed (continuing)")

    options = {
        "language": language.value,
        "mood": mood.value,
        "height": height,
        "width": HEIGHT_TO_WIDTH[height],
        "fps": fps,
        "dpi": dpi,
        "speed": speed,
    }
    session_id = sessions.new_session(options)
    d = sessions.session_dir(session_id)

    # --- stream the upload to disk with a running size cap -------------- #
    dest = d / "input.pptx"
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
                        413,
                        f"File too large (limit {settings.max_upload_mb} MB).")
                fh.write(chunk)
    except HTTPException:
        sessions.delete_session(session_id)
        raise
    finally:
        await pptx.close()

    # Magic-byte check (a renamed non-pptx slips past the extension check).
    with dest.open("rb") as fh:
        if fh.read(4) != PPTX_MAGIC:
            sessions.delete_session(session_id)
            raise HTTPException(400, "That file is not a valid .pptx presentation.")

    (d / "script.txt").write_text(script, encoding="utf-8")

    # --- enqueue --------------------------------------------------------- #
    try:
        manager.submit(session_id)
    except QueueFull as e:
        sessions.delete_session(session_id)
        raise HTTPException(429, str(e))

    log.info("Created session %s (%s)", session_id, options)
    return CreateSessionResponse(session_id=session_id, status=sessions.PENDING)


# --------------------------------------------------------------------------- #
# Status / list / delete
# --------------------------------------------------------------------------- #
def _require_meta(session_id: str) -> dict:
    try:
        meta = sessions.read_meta(session_id)
    except ValueError:
        raise HTTPException(400, "Invalid session id.")
    if not meta:
        raise HTTPException(404, "Session not found.")
    return meta


@app.get("/api/sessions/{session_id}/status", response_model=StatusResponse)
def get_status(session_id: str):
    meta = _require_meta(session_id)
    return StatusResponse(
        session_id=session_id,
        status=meta.get("status"),
        slide_count=meta.get("slide_count"),
        progress=meta.get("progress"),
        has_output=sessions.has_output(session_id),
        error=meta.get("error"),
        output=meta.get("output"),
    )


@app.get("/api/sessions", response_model=SessionList)
def list_all():
    results = sessions.list_sessions()
    return SessionList(count=len(results), results=results)


@app.delete("/api/sessions/{session_id}")
def delete_one(session_id: str):
    _require_meta(session_id)
    sessions.delete_session(session_id)
    return {"deleted": session_id}


# --------------------------------------------------------------------------- #
# Video download / stream (range-enabled via FileResponse)
# --------------------------------------------------------------------------- #
@app.get("/api/sessions/{session_id}/video")
def get_video(session_id: str, download: bool = False):
    _require_meta(session_id)
    path = sessions.output_path(session_id)
    if not path.exists():
        raise HTTPException(404, "The video is not ready yet.")
    headers = None
    if download:
        headers = {"Content-Disposition": f'attachment; filename="{session_id}.mp4"'}
    return FileResponse(path, media_type="video/mp4", headers=headers)
