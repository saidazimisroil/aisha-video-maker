#!/usr/bin/env python3
"""
build_video.py - Assemble the narrated video from ALREADY-SYNTHESIZED audio.

Use this when build/audio/slide_*.wav already exist (e.g. a previous run paid
for TTS but failed later, or you just want to re-stitch with different fps/size).
It NEVER calls the AIsha TTS API, so it costs no account balance.

Slide images in build/slides/ are reused if present; otherwise pass --pptx to
(re)render them with LibreOffice. Audio and slides are paired by their
zero-padded index: slide_01.wav <-> slide_01.png, slide_02.* <-> slide_02.*, ...

All heavy lifting (tool discovery, slide rendering, duration probing, ffmpeg
assembly) is reused from make_video.py - this file is just a TTS-free entry point.

Usage:
  python build_video.py --out output.mp4
  python build_video.py --pptx presentation.pptx --out output.mp4   # re-render slides too
  python build_video.py --build-dir build --width 1280 --height 720
"""

import argparse
from pathlib import Path

import make_video as mv

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac")


def find_indexed(directory, exts):
    """Return files named slide_NN.<ext> in `directory`, sorted by their index."""
    if not directory.exists():
        return []
    files = [p for p in directory.iterdir()
             if p.is_file()
             and p.stem.lower().startswith("slide_")
             and p.suffix.lower() in exts]
    # Zero-padded names (slide_01..slide_15) sort correctly as plain strings.
    return sorted(files, key=lambda p: p.stem)


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the video from already-synthesized audio "
                    "(no TTS API calls, no account balance spent).")
    parser.add_argument("--out", default="output.mp4", help="Output video path.")
    parser.add_argument("--build-dir", default="build",
                        help="Working directory holding audio/ and slides/.")
    parser.add_argument("--pptx", default=None,
                        help="Re-render slides from this .pptx if build/slides is empty.")
    parser.add_argument("--fps", type=int, default=24, help="Output frame rate.")
    parser.add_argument("--width", type=int, default=1920, help="Output width.")
    parser.add_argument("--height", type=int, default=1080, help="Output height.")
    parser.add_argument("--dpi", type=int, default=150,
                        help="Slide render DPI (only used with --pptx).")
    args = parser.parse_args()

    build_dir = Path(args.build_dir)
    out_path = Path(args.out)

    ffmpeg = mv.find_tool("ffmpeg")
    ffprobe = mv.find_tool("ffprobe")

    # Audio must already exist - this command never synthesizes.
    audio_paths = find_indexed(build_dir / "audio", AUDIO_EXTS)
    if not audio_paths:
        mv.die(f"No audio found in {build_dir / 'audio'}. "
               f"Expected slide_01.wav, slide_02.wav, ... "
               f"(run make_video.py first to synthesize them).")
    print(f"Found {len(audio_paths)} audio file(s) in {build_dir / 'audio'}.")

    # Reuse existing slide PNGs; only render from --pptx if they are missing.
    png_paths = find_indexed(build_dir / "slides", (".png",))
    if png_paths:
        print(f"Reusing {len(png_paths)} slide image(s) from {build_dir / 'slides'}.")
    elif args.pptx:
        png_paths, _ = mv.render_slides(Path(args.pptx), build_dir, dpi=args.dpi)
    else:
        mv.die(f"No slide images in {build_dir / 'slides'} and no --pptx given "
               f"to render them. Pass --pptx presentation.pptx.")

    if len(png_paths) != len(audio_paths):
        mv.die(f"Have {len(png_paths)} slide image(s) but {len(audio_paths)} audio "
               f"file(s); they must match one-to-one by index.")

    durations = [mv.audio_duration(ffprobe, a) for a in audio_paths]

    mv.assemble(png_paths, audio_paths, out_path, build_dir, ffmpeg,
                fps=args.fps, width=args.width, height=args.height)

    total = sum(durations)
    print("\n" + "=" * 48)
    print(f"Done -> {out_path.resolve()}")
    print(f"Total duration: {total:.1f}s across {len(png_paths)} slide(s)")
    for i, d in enumerate(durations, start=1):
        print(f"  slide {i:02d}: {d:6.1f}s")
    print("=" * 48)


if __name__ == "__main__":
    main()
