#!/usr/bin/env python3
"""make_video.py - CLI: turn a .pptx + per-slide narration script into a video.

This is the command-line front end. All the heavy lifting now lives in
``app/pipeline.py`` so the web service and the CLI share one implementation;
this file just parses arguments, wires the steps together, and prints progress.
``build_video.py`` imports the re-exported helpers below, so it keeps working.

Usage:
  set AISHA_API_KEY=your_key_here
  python make_video.py presentation.pptx script.txt --out output.mp4
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Re-export the pipeline so existing callers (e.g. build_video.py: `import
# make_video as mv; mv.render_slides(...)`) keep resolving these names.
from app.pipeline import (  # noqa: F401
    CHAR_LIMIT,
    PipelineError,
    ToolNotFound,
    assemble,
    audio_duration,
    find_soffice,
    find_tool,
    media_url,
    parse_script,
    render_slides,
    synthesize,
    validate,
)


def die(msg, code=1):
    """CLI-only failure: print and exit. The library raises PipelineError instead."""
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(code)


def main():
    parser = argparse.ArgumentParser(
        description="Turn a .pptx + per-slide narration script into a narrated video.")
    parser.add_argument("pptx", help="Path to the .pptx presentation.")
    parser.add_argument("script", help="Path to the narration script (parts split by '---').")
    parser.add_argument("--out", default="output.mp4", help="Output video path.")
    parser.add_argument("--mood", default="Neutral",
                        choices=["Neutral", "Cheerful", "Happy", "Sad"],
                        help="TTS mood (uz/Gulnoza).")
    parser.add_argument("--language", default="uz", choices=["uz", "en", "ru"])
    parser.add_argument("--speed", type=float, default=0.75,
                        help="TTS speech rate, uz only (0 = API default, or 0.5-2.0).")
    parser.add_argument("--fps", type=int, default=24, help="Output frame rate.")
    parser.add_argument("--width", type=int, default=1920, help="Output width.")
    parser.add_argument("--height", type=int, default=1080, help="Output height.")
    parser.add_argument("--dpi", type=int, default=150, help="Slide render DPI.")
    parser.add_argument("--api-key", default=None,
                        help="AIsha API key (else env AISHA_API_KEY).")
    parser.add_argument("--build-dir", default="build",
                        help="Working directory for intermediates.")
    parser.add_argument("--keep", action="store_true",
                        help="Keep the build directory after finishing.")
    args = parser.parse_args()

    pptx_path = Path(args.pptx)
    script_path = Path(args.script)
    if not pptx_path.exists():
        die(f"PPTX not found: {pptx_path}")
    if not script_path.exists():
        die(f"Script not found: {script_path}")

    api_key = args.api_key or os.environ.get("AISHA_API_KEY", "").strip()
    if not api_key:
        die("No API key. Set AISHA_API_KEY env var or pass --api-key.")

    build_dir = Path(args.build_dir)
    out_path = Path(args.out)

    try:
        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")

        # 1. parse
        segments = parse_script(script_path)
        print(f"Parsed {len(segments)} narration part(s) from {script_path.name}.")

        # 2. render
        print("Rendering slides with LibreOffice...")
        png_paths, (w, h) = render_slides(pptx_path, build_dir, dpi=args.dpi)
        print(f"  -> {len(png_paths)} slide(s) rendered at {w}x{h}px")

        # 3. validate
        validate(segments, len(png_paths))

        # 4. synthesize
        def on_synth(done, total):
            print(f"Synthesized slide {done}/{total}.")

        audio_paths = synthesize(segments, api_key, build_dir / "audio",
                                 mood=args.mood, language=args.language,
                                 speed=args.speed, progress_cb=on_synth)

        # 5. durations (report)
        durations = [audio_duration(ffprobe, a) for a in audio_paths]

        # 6. assemble
        def on_seg(done, total):
            print(f"Built segment {done}/{total}.")

        assemble(png_paths, audio_paths, out_path, build_dir, ffmpeg,
                 fps=args.fps, width=args.width, height=args.height,
                 progress_cb=on_seg)
    except PipelineError as e:
        die(str(e))

    # 7. report
    total = sum(durations)
    print("\n" + "=" * 48)
    print(f"Done -> {out_path.resolve()}")
    print(f"Total duration: {total:.1f}s across {len(png_paths)} slide(s)")
    for i, d in enumerate(durations, start=1):
        print(f"  slide {i:02d}: {d:6.1f}s")
    print("=" * 48)

    if not args.keep:
        shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
