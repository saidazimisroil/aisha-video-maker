# Aisha Video Maker — backend image (FastAPI + LibreOffice + ffmpeg).
#
# The pipeline shells out to LibreOffice (pptx -> pdf) and ffmpeg (video), so the
# image bakes both in. We install libreoffice-impress + core ONLY (not the full
# `libreoffice` metapackage, which drags in Writer/Calc/Base + a JRE) and skip
# Java entirely — pptx -> pdf works without it. Cyrillic/Uzbek glyphs need fonts,
# so Noto/DejaVu/Liberation are installed too. Expect a ~700 MB–1 GB image; that
# is the LibreOffice floor.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress \
        libreoffice-core \
        fonts-dejavu \
        fonts-liberation \
        fonts-noto \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# HOME must be writable for LibreOffice's profile (backstop to the per-session
# UserInstallation the pipeline already passes). PYTHONUNBUFFERED -> live logs.
ENV HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# One worker on purpose: jobs run serially (a single background thread) to stay
# inside free-tier RAM. Shell form so Render's injected $PORT is honored.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
