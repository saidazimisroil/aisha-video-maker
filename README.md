# AIsha Video Maker

Turn a **.pptx** presentation plus a **per-slide narration script** into a narrated
**.mp4** video. Each slide stays on screen for exactly as long as its narration audio
plays, then advances to the next slide.

It runs two ways from one shared pipeline (`app/pipeline.py`):

- **CLI** — `make_video.py` for a single video on your machine.
- **Web app** — a FastAPI backend (`app/`) with per-session storage + a static
  frontend (`frontend/`), built to deploy on free hosting.

## How it works

1. **Parse** the narration — each slide's text is separated by a line containing only `---`.
2. **Render** every slide to a PNG (LibreOffice converts pptx→pdf; PyMuPDF rasterizes
   pdf→png — no PowerPoint needed).
3. **Validate** that the number of script parts equals the number of slides, and that no
   part exceeds the **1000-character** AIsha API limit.
4. **Synthesize** each slide's narration via the AIsha TTS API (Uzbek · Gulnoza ·
   Neutral by default) and download the audio.
5. **Assemble** the video with ffmpeg: each slide is held for the length of its audio
   (`-loop 1 … -shortest`), then all segments are concatenated in order.

---

## Project layout

```
app/
  main.py        FastAPI routes, CORS, /healthz, startup hooks
  pipeline.py    the shared pptx→video pipeline (cross-platform)
  jobs.py        single background worker (serial jobs, OOM-safe)
  sessions.py    per-session folders, meta.json, id validation, cleanup
  config.py      env-driven settings (fail-fast if AISHA_API_KEY missing)
  schemas.py     request/response models
frontend/        static UI (deploy on Vercel/Netlify) — edit config.js
make_video.py    CLI entry point (imports app/pipeline.py)
build_video.py   re-stitch from already-synthesized audio (no TTS cost)
Dockerfile       backend image (LibreOffice + ffmpeg baked in)
render.yaml      Render.com Blueprint
data/sessions/   created at runtime — one folder per video (gitignored)
```

Each video gets its own folder so many run independently:

```
data/sessions/{session_id}/
  input.pptx  script.txt  meta.json
  slides/   audio/   segments/   output.mp4
```

---

## A) Run the CLI

Install the toolchain (Windows, via winget):

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install TheDocumentFoundation.LibreOffice
```

Open a **new** terminal so `python`, `ffmpeg`, and `soffice` are on PATH, then:

```powershell
pip install -r requirements.txt
$env:AISHA_API_KEY = "your_X-Api-Key_here"
python make_video.py presentation.pptx script.txt --out output.mp4
```

### Script format (`script.txt`)

```
salom, darsimiz shu...
---
shunday davom etamiz...
---
darsimiz tugadi.
```

Three slides → three narration parts. The number of parts must match the number of
slides in the pptx.

### CLI options

| Flag | Default | Meaning |
|------|---------|---------|
| `--out` | `output.mp4` | Output video path |
| `--mood` | `Neutral` | `Neutral` / `Cheerful` / `Happy` / `Sad` (uz/Gulnoza) |
| `--language` | `uz` | `uz` / `en` / `ru` |
| `--speed` | `0.75` | Speech rate (uz only): `0` = API default, or `0.5`–`2.0` |
| `--fps` | `24` | Output frame rate |
| `--width` / `--height` | `1920` / `1080` | Output resolution (slide letterboxed to fit) |
| `--dpi` | `150` | Slide render quality |
| `--api-key` | — | API key (alternative to `AISHA_API_KEY` env var) |
| `--keep` | off | Keep the `build/` working directory for inspection |

---

## B) Run the web app locally

```powershell
pip install -r requirements.txt
copy .env.example .env          # then edit .env and set AISHA_API_KEY
uvicorn app.main:app --reload   # serves http://localhost:8000
```

Check `http://localhost:8000/healthz` → `{"ok": true, "soffice": true, ...}` (it must
find LibreOffice + ffmpeg). Interactive API docs are at `http://localhost:8000/docs`.

Then open the frontend: edit `frontend/config.js` so
`window.API_BASE = "http://localhost:8000"` and open `frontend/index.html` (any static
server works, e.g. `python -m http.server 5500` inside `frontend/`).

### API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sessions` | multipart: `pptx` file + `script` text + options → `{session_id, status}` |
| `GET` | `/api/sessions/{id}/status` | poll: `{status, progress, slide_count, error, has_output}` |
| `GET` | `/api/sessions/{id}/video` | the finished mp4 (`?download=1` to force download) |
| `GET` | `/api/sessions` | list past sessions |
| `DELETE` | `/api/sessions/{id}` | delete a session |
| `GET` | `/healthz` | tool presence + queue depth |

Status flow: `PENDING → RENDERING → SYNTHESIZING → ASSEMBLING → SUCCESS | FAILED`.

---

## C) Deploy

The backend **must** be a container/VM host (Render, Railway, Fly.io) because it runs
LibreOffice + ffmpeg — that rules out serverless (Vercel/Netlify functions). The
**frontend** is plain static files and goes on Vercel/Netlify.

### Backend → Render.com (free, Docker)

1. Push this repo to GitHub.
2. Render → **New + → Blueprint** → pick the repo (`render.yaml` is detected).
3. Set the secrets in the dashboard:
   - `AISHA_API_KEY` — your AIsha X-Api-Key.
   - `AISHA_ALLOWED_ORIGINS` — your frontend URL (e.g. `https://aisha-video.vercel.app`).
4. Deploy, then hit `https://<app>.onrender.com/healthz`.

The same `Dockerfile` works on Railway/Fly.io if you prefer.

### Frontend → Vercel / Netlify (static)

1. Set the project's **root directory** to `frontend/`.
2. Edit `frontend/config.js` → `window.API_BASE = "https://<app>.onrender.com"`.
3. No build command — it's static. Deploy.
4. Add that frontend origin to the backend's `AISHA_ALLOWED_ORIGINS`.

### Free-tier caveats (important)

- **Ephemeral storage.** Render's free disk does **not** persist — generated videos are
  lost on every redeploy/restart and after the ~15-min idle spin-down. **Download your
  video right after it's made.** For durability, use a paid plan + a mounted disk
  (uncomment the `disks:` block in `render.yaml`) or upload finished videos to object
  storage (S3/R2).
- **Memory.** Free tier is ~512 MB. Jobs run **one at a time** and default to **720p**
  to stay within it. 1080p is opt-in and heavier — bump to a larger instance if it OOMs.
- **Cold starts.** A free instance spins down when idle; the first request after that
  takes ~1 min while it wakes.
- **Cost.** Every video spends your AIsha balance against the one server-side key — gate
  access (Render access control / a shared secret) if the deployment is public.

## Notes

- Slides are captured in their final static layout — animations/transitions inside a
  slide are not reproduced.
- `build_video.py` re-stitches a video from already-synthesized audio without calling the
  TTS API (so it costs no balance) — handy if a run paid for audio but failed at assembly.
