"""Aisha Video Maker — web application package.

Holds the reusable pipeline (``app.pipeline``) plus the FastAPI service
(``app.main``) and its supporting modules. The CLI entry points
(``make_video.py`` / ``build_video.py``) import the pipeline from here so there
is a single source of truth for the slide-rendering / TTS / ffmpeg logic.
"""
