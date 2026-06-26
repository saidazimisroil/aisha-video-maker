"""jobs.py - Background job processing: a single worker thread draining a queue.

Why one in-process worker (not Celery/Redis): a free-tier box is a single small instance, so
an external broker would be a second paid service for no benefit. More importantly,
LibreOffice + a libx264 encode can exceed 512 MB if two run at once, so we *want* strict
serial execution. One daemon thread pulling a FIFO queue gives exactly concurrency = 1, and
job state lives in SQLite (db.py) so a status poll just reads a row.

The worker handles three kinds of work, dispatched by the ``action`` carried on the queue:

* ``tts``           - the classic flow: render → synthesize narration → assemble.
* ``reuse_prepare`` - the first half of "build from existing audios": render the slides only,
                      then pause in ``AWAITING_PAIRS`` so the user can pick an audio per slide.
* ``reuse_build``   - the second half: download the chosen (already-synthesized) audios,
                      assemble, and discard them. No TTS is called, so no balance is spent.

In every flow the synthesized/downloaded audio and the render intermediates are purged once
``output.mp4`` exists — the Aisha TTS history is the durable audio store, not our disk.
"""

import logging
import queue
import shutil
import threading

from app import db, sessions
from app.config import settings
from app.pipeline import (
    PipelineError,
    assemble,
    audio_duration,
    download_audio,
    find_tool,
    media_url,
    parse_script,
    render_slides,
    synthesize,
    validate,
)

log = logging.getLogger("aisha.jobs")

# Queue actions.
TTS = "tts"
REUSE_PREPARE = "reuse_prepare"
REUSE_BUILD = "reuse_build"


class QueueFull(RuntimeError):
    """Raised by :meth:`JobManager.submit` when too many jobs are already waiting."""


class JobManager:
    def __init__(self, max_queue: int = None):
        self.max_queue = settings.max_queue if max_queue is None else max_queue
        self._q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- public API ------------------------------------------------------- #
    def start(self) -> None:
        """Launch the worker thread once (idempotent)."""
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run_forever, name="job-worker", daemon=True)
            self._worker.start()
            log.info("Job worker started (max_queue=%d)", self.max_queue)

    def submit(self, session_id: str, action: str = TTS) -> None:
        """Enqueue a unit of work, or raise QueueFull if saturated."""
        if self._q.qsize() >= self.max_queue:
            raise QueueFull(
                "The server is busy processing other videos. Please try again "
                "in a few minutes.")
        sessions.set_status(session_id, sessions.PENDING)
        self._q.put((session_id, action))

    def queue_depth(self) -> int:
        return self._q.qsize()

    # -- worker ----------------------------------------------------------- #
    def _run_forever(self) -> None:
        while True:
            session_id, action = self._q.get()
            try:
                self._dispatch(session_id, action)
            except PipelineError as e:
                log.warning("Session %s (%s) failed: %s", session_id, action, e)
                sessions.set_status(session_id, sessions.FAILED, error=str(e))
            except Exception:  # noqa: BLE001 - never let the worker die
                log.exception("Session %s (%s) crashed", session_id, action)
                sessions.set_status(
                    session_id, sessions.FAILED,
                    error="An unexpected error occurred while making the video.")
            finally:
                self._q.task_done()

    def _dispatch(self, session_id: str, action: str) -> None:
        if action == REUSE_PREPARE:
            self._process_reuse_prepare(session_id)
        elif action == REUSE_BUILD:
            self._process_reuse_build(session_id)
        else:
            self._process_tts(session_id)

    # -- flows ------------------------------------------------------------ #
    def _process_tts(self, session_id: str) -> None:
        d = sessions.session_dir(session_id)
        meta = sessions.read_session(session_id) or {}
        opts = meta.get("options", {})
        log.info("Session %s: starting TTS (%s)", session_id, opts)

        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")

        # 1. Render slides (early, so a count/limit mismatch surfaces fast).
        sessions.set_status(session_id, sessions.RENDERING)
        sessions.set_progress(session_id, sessions.RENDERING, 0, 0, "Rendering slides")
        png_paths, size = render_slides(
            d / "input.pptx", d, dpi=opts.get("dpi", settings.default_dpi))
        self._guard_slide_count(len(png_paths))
        sessions.update_meta(session_id, slide_count=len(png_paths),
                             slide_size=list(size))

        # 2. Parse + validate narration against the rendered slide count.
        segments = parse_script(d / "script.txt")
        validate(segments, len(png_paths))

        # 3. Synthesize narration.
        sessions.set_status(session_id, sessions.SYNTHESIZING)
        sessions.set_progress(session_id, sessions.SYNTHESIZING, 0, len(segments),
                              "Generating narration")

        def on_synth(done, total):
            sessions.set_progress(session_id, sessions.SYNTHESIZING, done, total,
                                  f"Generating narration {done}/{total}")

        audio_paths = synthesize(
            segments, settings.aisha_api_key, d / "audio",
            mood=opts.get("mood", settings.default_mood),
            language=opts.get("language", settings.default_language),
            speed=opts.get("speed", settings.default_speed),
            poll_interval=settings.tts_poll_interval,
            poll_max=settings.tts_poll_max,
            progress_cb=on_synth,
        )
        durations = [audio_duration(ffprobe, a) for a in audio_paths]

        # 4. Assemble + finish.
        self._assemble_and_finish(session_id, d, png_paths, audio_paths, durations,
                                  opts, ffmpeg)

    def _process_reuse_prepare(self, session_id: str) -> None:
        """Render the slides for a 'build from existing audios' job, then await pairing."""
        d = sessions.session_dir(session_id)
        meta = sessions.read_session(session_id) or {}
        opts = meta.get("options", {})
        log.info("Session %s: preparing reuse (rendering slides)", session_id)

        sessions.set_status(session_id, sessions.RENDERING)
        sessions.set_progress(session_id, sessions.RENDERING, 0, 0, "Rendering slides")
        png_paths, size = render_slides(
            d / "input.pptx", d, dpi=opts.get("dpi", settings.default_dpi))
        self._guard_slide_count(len(png_paths))

        sessions.set_status(
            session_id, sessions.AWAITING_PAIRS,
            slide_count=len(png_paths), slide_size=list(size),
            progress={"phase": sessions.AWAITING_PAIRS, "current": 0,
                      "total": len(png_paths),
                      "message": "Slides ready — choose an audio for each slide"})
        log.info("Session %s: AWAITING_PAIRS (%d slides)", session_id, len(png_paths))

    def _process_reuse_build(self, session_id: str) -> None:
        """Download the chosen existing audios, assemble, then discard the audio."""
        d = sessions.session_dir(session_id)
        meta = sessions.read_session(session_id) or {}
        opts = meta.get("options", {})
        audio_dir = d / "audio"
        log.info("Session %s: building from existing audios", session_id)

        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")
        headers = {"X-Api-Key": settings.aisha_api_key}

        try:
            pairs = db.get_reuse_pairs(session_id)
            png_paths = [sessions.slide_path(session_id, p["slide_index"]) for p in pairs]
            missing = [p["slide_index"] for p, png in zip(pairs, png_paths)
                       if not png.exists()]
            if missing:
                raise PipelineError(
                    "The rendered slides are no longer available; please start the "
                    "presentation over.")
            slide_count = meta.get("slide_count") or len(png_paths)
            if len(pairs) != slide_count:
                raise PipelineError(
                    f"You picked {len(pairs)} audio(s) but the presentation has "
                    f"{slide_count} slide(s); they must match one-to-one.")

            # Download each chosen clip (no synthesis -> no balance spent).
            sessions.set_status(session_id, sessions.ASSEMBLING)
            sessions.set_progress(session_id, sessions.ASSEMBLING, 0, len(pairs),
                                  "Fetching audio")
            audio_dir.mkdir(parents=True, exist_ok=True)
            audio_paths = []
            for idx, pair in enumerate(pairs, start=1):
                audio_paths.append(
                    download_audio(media_url(pair["audio_url"]), audio_dir, idx, headers))
                sessions.set_progress(session_id, sessions.ASSEMBLING, idx, len(pairs),
                                      f"Fetching audio {idx}/{len(pairs)}")
            durations = [audio_duration(ffprobe, a) for a in audio_paths]

            self._assemble_and_finish(session_id, d, png_paths, audio_paths, durations,
                                      opts, ffmpeg)
        finally:
            # Downloaded clips are disposable (re-fetchable from Aisha) — never keep them,
            # even on failure. (On success purge_working_files already removed them.)
            shutil.rmtree(audio_dir, ignore_errors=True)

    # -- shared tail ------------------------------------------------------ #
    def _assemble_and_finish(self, session_id, d, png_paths, audio_paths, durations,
                             opts, ffmpeg) -> None:
        sessions.set_status(session_id, sessions.ASSEMBLING)
        sessions.set_progress(session_id, sessions.ASSEMBLING, 0, len(png_paths),
                              "Assembling video")

        def on_seg(done, total):
            sessions.set_progress(session_id, sessions.ASSEMBLING, done, total,
                                  f"Assembling video {done}/{total}")

        assemble(
            png_paths, audio_paths, sessions.output_path(session_id), d, ffmpeg,
            fps=opts.get("fps", settings.default_fps),
            width=opts.get("width", settings.default_width),
            height=opts.get("height", settings.default_height),
            progress_cb=on_seg,
        )

        total = round(sum(durations), 2)
        sessions.set_status(
            session_id, sessions.SUCCESS,
            progress={"phase": sessions.SUCCESS, "current": len(png_paths),
                      "total": len(png_paths), "message": "Done"},
            output={"path": "output.mp4", "duration": total,
                    "per_slide": [round(x, 2) for x in durations]},
            error=None,
        )
        # We don't keep audio/intermediates after a video is made — only output.mp4.
        sessions.purge_working_files(session_id)
        log.info("Session %s: SUCCESS (%.1fs)", session_id, total)

    def _guard_slide_count(self, n: int) -> None:
        if n > settings.max_slides:
            raise PipelineError(
                f"The presentation has {n} slides, over the "
                f"{settings.max_slides}-slide limit for this server.")


# Module-level singleton, started by the FastAPI app on startup.
manager = JobManager()
