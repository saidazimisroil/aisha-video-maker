#!/usr/bin/env python3
"""pipeline.py - Reusable pptx -> narrated video pipeline.

This is the refactored core that used to live in ``make_video.py``. Every step is
parameterized by a *working directory* so it can run against a per-session folder
(the web app) or a single shared ``build/`` dir (the CLI).

Two deliberate changes from the original CLI version make it server-safe:

* **Cross-platform tool discovery.** ``soffice``/``ffmpeg``/``ffprobe`` are found
  via ``shutil.which`` first (they are on PATH in the Docker image and on Linux),
  with the old Windows ``Program Files`` / WinGet fallbacks kept for local dev.
* **Exceptions instead of process exit.** The reused steps ``raise PipelineError``
  rather than calling ``sys.exit`` so a background worker can catch the failure,
  record it on the session, and keep serving. The CLI wraps these and prints.

Pipeline:
  1. parse_script  - split narration on lines that are exactly '---'.
  2. render_slides - LibreOffice pptx->pdf, PyMuPDF pdf->png (one PNG per slide).
  3. validate      - #parts == #slides and every part <= 1000 chars (Aisha limit).
  4. synthesize    - per-slide TTS via the Aisha API, download the audio.
  5. audio_duration- probe each clip's length with ffprobe.
  6. assemble      - hold each slide for its audio length, then concatenate.
"""

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import requests

BASE = "https://back.aisha.group"
TTS_POST_URL = BASE + "/api/v1/tts/post/"
TTS_STATUS_URL = BASE + "/api/v1/tts/status/{id}/"
CHAR_LIMIT = 1000

# Status-code -> human message (wording mirrored from aisha-tts-panel.html).
POST_ERRORS = {
    400: "Request fields invalid: check transcript, language, model or speed.",
    401: "Authentication required for a custom voice.",
    402: "Insufficient balance on the AIsha account.",
    503: "TTS service is temporarily unavailable. Try again shortly.",
}
STATUS_ERRORS = {
    403: "You do not have permission for this record.",
    404: "No TTS record found with that id.",
}

# Long-running subprocess ceilings (seconds) so a wedged tool can't hang a worker.
SOFFICE_TIMEOUT = 180
FFMPEG_TIMEOUT = 600


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class PipelineError(RuntimeError):
    """A recoverable, user-facing pipeline failure (bad input, API error, etc.).

    The web worker catches this and records ``str(e)`` on the session; the CLI
    prints it and exits. The message is meant to be shown to a human.
    """


class ToolNotFound(PipelineError):
    """A required native binary (soffice/ffmpeg/ffprobe) was not found."""


# --------------------------------------------------------------------------- #
# Tool discovery (cross-platform: Linux/Docker via PATH, Windows fallbacks)
# --------------------------------------------------------------------------- #
def find_executable(name, extra_paths=()):
    """Find an executable on PATH, falling back to known install locations."""
    found = shutil.which(name)
    if found:
        return found
    for p in extra_paths:
        if Path(p).exists():
            return str(p)
    return None


def find_soffice():
    """Locate LibreOffice. On Linux/Docker it is ``soffice`` on PATH; on Windows
    fall back to the standard install dirs."""
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    exe = find_executable("soffice", candidates) or find_executable("libreoffice")
    if not exe:
        raise ToolNotFound(
            "LibreOffice (soffice) not found. On the server it must be installed "
            "in the image; locally: winget install TheDocumentFoundation.LibreOffice")
    return exe


def _winget_glob(filename):
    """Search WinGet's package install tree for a freshly-installed exe.
    winget often needs a shell restart before its shims land on PATH; this lets
    the script work immediately after install. Windows-only."""
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not root.exists():
        return None
    matches = sorted(root.rglob(filename))
    return str(matches[0]) if matches else None


def find_tool(name):
    """Find ffmpeg/ffprobe. PATH first (Linux/Docker), then WinGet on Windows."""
    exe = find_executable(name)
    if not exe and platform.system() == "Windows":
        exe = _winget_glob(name + ".exe")
    if not exe:
        raise ToolNotFound(
            f"{name} not found on PATH. On the server it must be installed in the "
            f"image; locally (Windows): winget install Gyan.FFmpeg (then a new shell).")
    return exe


def media_url(path):
    """Mirror of the HTML mediaUrl(): prefix relative paths with BASE."""
    if not path:
        return ""
    return path if path.startswith("http") else BASE + path


# --------------------------------------------------------------------------- #
# Step 1: parse script
# --------------------------------------------------------------------------- #
def parse_script(script_path):
    """Split narration text into per-slide parts on lines that are exactly '---'."""
    text = Path(script_path).read_text(encoding="utf-8")
    segments, current = [], []
    for line in text.splitlines():
        if line.strip() == "---":
            segments.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    segments.append("\n".join(current).strip())
    # Drop empty segments produced by stray/leading/trailing separators.
    segments = [s for s in segments if s]
    if not segments:
        raise PipelineError(
            "Script is empty after parsing. Add narration text, separating each "
            "slide with a line containing only '---'.")
    return segments


def parse_script_text(text):
    """Same as parse_script but from an in-memory string (web upload)."""
    segments, current = [], []
    for line in text.splitlines():
        if line.strip() == "---":
            segments.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    segments.append("\n".join(current).strip())
    segments = [s for s in segments if s]
    if not segments:
        raise PipelineError(
            "Script is empty after parsing. Add narration text, separating each "
            "slide with a line containing only '---'.")
    return segments


# --------------------------------------------------------------------------- #
# Step 2: render slides
# --------------------------------------------------------------------------- #
def render_slides(pptx_path, build_dir, dpi=150):
    """Render every slide of ``pptx_path`` to a PNG under ``build_dir/slides``.

    Returns ``(png_paths, (width, height))``.
    """
    build_dir = Path(build_dir)
    slides_dir = build_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    soffice = find_soffice()

    # LibreOffice needs a writable user profile. In a container $HOME may be '/'
    # (read-only) or unset, which makes soffice silently hang/fail. Point it at a
    # per-session profile dir so concurrent runs also can't fight over a lock.
    # Use Path.as_uri() so the file:// URI is correct on both Windows
    # (file:///C:/...) and Linux (file:///app/...); it requires an absolute path.
    profile = (build_dir / "lo_profile").resolve()
    profile.mkdir(parents=True, exist_ok=True)

    # pptx -> pdf
    try:
        result = subprocess.run(
            [soffice, f"-env:UserInstallation={profile.as_uri()}",
             "--headless", "--convert-to", "pdf",
             "--outdir", str(build_dir), str(pptx_path)],
            capture_output=True, text=True, timeout=SOFFICE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise PipelineError(
            f"LibreOffice timed out after {SOFFICE_TIMEOUT}s converting the pptx.")

    pdf_path = build_dir / (Path(pptx_path).stem + ".pdf")
    if not pdf_path.exists():
        raise PipelineError(
            "LibreOffice failed to produce a PDF from the presentation.\n"
            + (result.stdout or "") + (result.stderr or ""))

    # pdf -> png via PyMuPDF (no poppler dependency)
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise PipelineError("PyMuPDF not installed. Run: pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    png_paths = []
    size = None
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix)
        out = slides_dir / f"slide_{i:02d}.png"
        pix.save(str(out))
        png_paths.append(out)
        if size is None:
            size = (pix.width, pix.height)
    doc.close()
    if not png_paths:
        raise PipelineError("No slides were rendered from the presentation.")
    return png_paths, size


# --------------------------------------------------------------------------- #
# Step 3: validate
# --------------------------------------------------------------------------- #
def validate(segments, slide_count):
    """Ensure #parts == #slides and no part exceeds the API character limit."""
    if len(segments) != slide_count:
        raise PipelineError(
            f"Your script has {len(segments)} narration part(s) but the "
            f"presentation has {slide_count} slide(s). They must match — separate "
            f"each slide's narration with a line containing only '---'.")
    for idx, seg in enumerate(segments, start=1):
        if len(seg) > CHAR_LIMIT:
            raise PipelineError(
                f"Slide {idx}'s narration is {len(seg)} characters, over the "
                f"{CHAR_LIMIT}-character limit. Shorten it or split that slide.")


# --------------------------------------------------------------------------- #
# Step 4: synthesize audio
# --------------------------------------------------------------------------- #
def synthesize(segments, api_key, audio_dir, mood="Neutral", language="uz",
               model="Gulnoza", speed=0.75, poll_interval=3, poll_max=40,
               progress_cb=None):
    """Synthesize each narration part to an audio file under ``audio_dir``.

    ``progress_cb(done, total)`` is called after each slide finishes (if given)
    so the worker can report "synthesizing 4/15".
    """
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    headers = {"X-Api-Key": api_key}
    audio_paths = []
    total = len(segments)

    for idx, transcript in enumerate(segments, start=1):
        # Per the Aisha docs, model/mood/speed apply only to the uz (Gulnoza)
        # stream; en/ru must not send them.
        data = {"transcript": transcript, "language": language}
        if language == "uz":
            data["model"] = model
            data["mood"] = mood
            data["speed"] = speed

        try:
            resp = requests.post(TTS_POST_URL, headers=headers, data=data, timeout=120)
        except requests.RequestException as e:
            raise PipelineError(f"Slide {idx}: could not reach the TTS service ({e}).")
        body = _safe_json(resp)

        if resp.status_code == 201:
            audio_remote = body.get("audio_path")
        elif resp.status_code == 202:
            audio_remote = _poll_status(body.get("id"), headers,
                                        poll_interval, poll_max)
        else:
            msg = POST_ERRORS.get(resp.status_code,
                                  f"Unexpected response ({resp.status_code}).")
            raise PipelineError(
                f"Slide {idx}: {msg}\n"
                f"{json.dumps(body, ensure_ascii=False)}")

        if not audio_remote:
            raise PipelineError(
                f"Slide {idx}: the TTS API returned no audio path.\n"
                f"{json.dumps(body, ensure_ascii=False)}")

        local = _download_audio(media_url(audio_remote), audio_dir, idx, headers)
        audio_paths.append(local)
        if progress_cb:
            progress_cb(idx, total)
    return audio_paths


def _safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}


def _poll_status(tts_id, headers, interval, max_attempts):
    if tts_id is None:
        raise PipelineError("Async TTS response (202) had no id to poll.")
    url = TTS_STATUS_URL.format(id=tts_id)
    for _ in range(1, max_attempts + 1):
        time.sleep(interval)
        try:
            resp = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as e:
            raise PipelineError(f"Polling TTS id {tts_id} failed: {e}")
        if resp.status_code != 200:
            msg = STATUS_ERRORS.get(resp.status_code,
                                    f"Unexpected status response ({resp.status_code}).")
            raise PipelineError(f"Polling id {tts_id}: {msg}")
        body = _safe_json(resp)
        status = body.get("status")
        if status == "SUCCESS":
            return body.get("audio_path")
        if status == "FAILED":
            raise PipelineError(f"TTS job {tts_id} FAILED on the server.")
    raise PipelineError(
        f"TTS job {tts_id} did not finish within {interval * max_attempts}s.")


def download_audio(url, audio_dir, idx, headers):
    """Public wrapper: download one already-synthesized clip to ``audio_dir/slide_NN.<ext>``.

    Used by the "build from existing audios" flow, which pairs slides with clips already in
    the Aisha TTS history (no new synthesis, no balance spent)."""
    return _download_audio(url, audio_dir, idx, headers)


def _download_audio(url, audio_dir, idx, headers):
    try:
        resp = requests.get(url, headers=headers, timeout=120)
    except requests.RequestException as e:
        raise PipelineError(f"Could not download audio for slide {idx}: {e}")
    if resp.status_code != 200:
        raise PipelineError(
            f"Could not download audio for slide {idx} ({resp.status_code}): {url}")
    # Infer extension from URL or content-type.
    ext = Path(url.split("?")[0]).suffix or _ext_from_content_type(
        resp.headers.get("Content-Type", ""))
    out = Path(audio_dir) / f"slide_{idx:02d}{ext or '.mp3'}"
    out.write_bytes(resp.content)
    return out


def _ext_from_content_type(ct):
    return {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
    }.get(ct.split(";")[0].strip().lower(), "")


# --------------------------------------------------------------------------- #
# Step 5: durations
# --------------------------------------------------------------------------- #
def audio_duration(ffprobe, path):
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise PipelineError(f"Could not read duration of {path}: {result.stderr}")


# --------------------------------------------------------------------------- #
# Step 6: assemble video
# --------------------------------------------------------------------------- #
def even(n):
    return n if n % 2 == 0 else n - 1


def assemble(png_paths, audio_paths, out_path, build_dir, ffmpeg, fps,
             width, height, progress_cb=None):
    """Build one mp4 segment per slide (held for its audio length) then concat.

    ``progress_cb(done, total)`` fires after each segment is encoded.
    """
    build_dir = Path(build_dir)
    width, height = even(width), even(height)
    seg_dir = build_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    total = len(png_paths)

    # Scale slide to fit WxH, then pad (letterbox) to exact WxH.
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"fps={fps},format=yuv420p")

    for idx, (png, audio) in enumerate(zip(png_paths, audio_paths), start=1):
        seg = seg_dir / f"seg_{idx:02d}.mp4"
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", str(png),
            "-i", str(audio),
            "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-vf", vf,
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-pix_fmt", "yuv420p",
            str(seg),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise PipelineError(f"ffmpeg timed out building segment {idx}.")
        if not seg.exists():
            raise PipelineError(f"ffmpeg failed building segment {idx}:\n{result.stderr}")
        segments.append(seg)
        if progress_cb:
            progress_cb(idx, total)

    # Concat all segments.
    concat_file = build_dir / "concat.txt"
    # Paths must be relative to the concat file's own directory (build_dir),
    # since ffmpeg's concat demuxer resolves them there, not against the cwd.
    concat_file.write_text(
        "".join(f"file '{s.relative_to(build_dir).as_posix()}'\n" for s in segments),
        encoding="utf-8")

    # Copy the (identical-param) video losslessly but RE-ENCODE audio. A plain
    # "-c copy" concat splices each segment's AAC priming samples and produces a
    # non-monotonic audio DTS at every boundary; strict players (browsers) then
    # drop the audio track. Re-encoding with regenerated timestamps avoids that.
    cmd = [ffmpeg, "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0",
           "-i", str(concat_file),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           str(out_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise PipelineError("ffmpeg timed out concatenating the segments.")

    if not Path(out_path).exists():
        # Fallback: full re-encode concat if stream-copy failed.
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
               "-i", str(concat_file),
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
               "-pix_fmt", "yuv420p", str(out_path)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise PipelineError("ffmpeg timed out concatenating the segments.")
        if not Path(out_path).exists():
            raise PipelineError(f"ffmpeg failed concatenating:\n{result.stderr}")
