"""jobs.py - Background job processing: a single worker thread draining a queue.

Why one in-process worker (not Celery/Redis): a free-tier box is a single small
instance, so an external broker would be a second paid service for no benefit.
More importantly, LibreOffice + a libx264 encode can exceed 512 MB if two run at
once, so we *want* strict serial execution. One daemon thread pulling a FIFO
queue gives exactly concurrency = 1, and job state lives in each session's
``meta.json`` so a status poll just reads a file.
"""

import logging
import queue
import threading

from app.config import settings
from app.pipeline import (
    PipelineError,
    assemble,
    audio_duration,
    find_tool,
    parse_script,
    render_slides,
    synthesize,
    validate,
)
from app import sessions

log = logging.getLogger("aisha.jobs")


class QueueFull(RuntimeError):
    """Raised by :meth:`JobManager.submit` when too many jobs are already waiting."""


class JobManager:
    def __init__(self, max_queue: int = None):
        self.max_queue = settings.max_queue if max_queue is None else max_queue
        self._q: "queue.Queue[str]" = queue.Queue()
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

    def submit(self, session_id: str) -> None:
        """Enqueue a session for processing, or raise QueueFull if saturated."""
        if self._q.qsize() >= self.max_queue:
            raise QueueFull(
                "The server is busy processing other videos. Please try again "
                "in a few minutes.")
        sessions.set_status(session_id, sessions.PENDING)
        self._q.put(session_id)

    def queue_depth(self) -> int:
        return self._q.qsize()

    # -- worker ----------------------------------------------------------- #
    def _run_forever(self) -> None:
        while True:
            session_id = self._q.get()
            try:
                self._process(session_id)
            except PipelineError as e:
                log.warning("Session %s failed: %s", session_id, e)
                sessions.set_status(session_id, sessions.FAILED, error=str(e))
            except Exception as e:  # noqa: BLE001 - never let the worker die
                log.exception("Session %s crashed", session_id)
                sessions.set_status(
                    session_id, sessions.FAILED,
                    error="An unexpected error occurred while making the video.")
            finally:
                self._q.task_done()

    def _process(self, session_id: str) -> None:
        d = sessions.session_dir(session_id)
        meta = sessions.read_meta(session_id) or {}
        opts = meta.get("options", {})
        log.info("Session %s: starting (%s)", session_id, opts)

        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")

        # 1. Render slides (early, so a count/limit mismatch surfaces fast).
        sessions.set_status(session_id, sessions.RENDERING)
        sessions.set_progress(session_id, sessions.RENDERING, 0, 0,
                              "Rendering slides")
        png_paths, size = render_slides(
            d / "input.pptx", d, dpi=opts.get("dpi", settings.default_dpi))

        if len(png_paths) > settings.max_slides:
            raise PipelineError(
                f"The presentation has {len(png_paths)} slides, over the "
                f"{settings.max_slides}-slide limit for this server.")

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

        # 4. Assemble the video.
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

        # 5. Done.
        sessions.set_status(
            session_id, sessions.SUCCESS,
            progress={"phase": sessions.SUCCESS, "current": len(png_paths),
                      "total": len(png_paths), "message": "Done"},
            output={"path": "output.mp4", "duration": round(sum(durations), 2),
                    "per_slide": [round(x, 2) for x in durations]},
            error=None,
        )
        log.info("Session %s: SUCCESS (%.1fs)", session_id, sum(durations))


# Module-level singleton, started by the FastAPI app on startup.
manager = JobManager()
