# AIsha Video Maker

Turn a **.pptx** presentation plus a **per-slide narration script** into a narrated
**.mp4** video. Each slide stays on screen for exactly as long as its narration audio
plays, then advances to the next slide.

It runs two ways from one shared pipeline (`app/pipeline.py`):

- **CLI** — `make_video.py` for a single video on your machine.
- **Dashboard web app** — a FastAPI backend (`app/`) with a **SQLite** history DB + a
  **React (Vite)** dashboard (`frontend/`), built to deploy on free hosting.

The dashboard does more than create videos:

- **Create Video** — the classic pptx + narration → narrated video flow.
- **Audio Library** — browse every clip your Aisha account has ever generated (the backend
  proxies the Aisha TTS history) and preview any of them in-browser.
- **Build From Audio** — reuse those existing clips: upload a pptx, pair each slide with an
  audio you already made, and stitch a video **without spending any TTS balance**.
- **Video History** — all your videos/presentations in SQLite: search, rename
  (e.g. “lesson 4”, “lesson 55”), replay, download, or delete.
- **Overview** — totals (videos, runtime, slides) and the Aisha balance, when available.

Audio is **not** kept on disk: a clip is downloaded only while a video is being assembled and
then discarded. Your durable audio store is the Aisha TTS history itself, which the Audio
Library reads live — so everything you ever synthesize is reusable later for free.

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
  jobs.py        single background worker (tts / reuse_prepare / reuse_build)
  sessions.py    per-session folders, id validation, working-file cleanup
  db.py          SQLite history (source of truth) + legacy meta.json migration
  aisha.py       Aisha client: TTS-history proxy, audio stream, balance probe
  config.py      env-driven settings (fail-fast if AISHA_API_KEY missing)
  schemas.py     request/response models
frontend/        React + Vite dashboard (deploy on Vercel/Netlify) — VITE_API_BASE
make_video.py    CLI entry point (imports app/pipeline.py)
build_video.py   re-stitch from already-synthesized audio (no TTS cost)
Dockerfile       backend image (LibreOffice + ffmpeg baked in)
render.yaml      Render.com Blueprint
data/aisha.db    SQLite history DB (created at runtime, gitignored)
data/sessions/   created at runtime — one folder per video (gitignored)
```

Job metadata (status, progress, title, options, output) lives in **SQLite** (`data/aisha.db`);
the per-session folder only holds the working files and the final video. Once a video
succeeds, the audio/slides/segments are purged and **only `output.mp4` remains**:

```
data/sessions/{session_id}/
  output.mp4            # all that survives a finished job
  (input.pptx, slides/, audio/, segments/ exist only while the job runs)
```

On first start the backend imports any pre-existing `meta.json` folders from the old version
into SQLite, so your history carries over.

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

**Backend** (FastAPI):

```powershell
pip install -r requirements.txt
copy .env.example .env          # then edit .env and set AISHA_API_KEY
uvicorn app.main:app --reload   # serves http://localhost:8000
```

Check `http://localhost:8000/healthz` → `{"ok": true, "soffice": true, ...}` (it must
find LibreOffice + ffmpeg). Interactive API docs are at `http://localhost:8000/docs`.

**Frontend** (React + Vite — needs Node 18+):

```powershell
cd frontend
npm install
npm run dev                     # serves http://localhost:5173
```

In dev the Vite server proxies `/api` to `http://localhost:8000`, so leave `VITE_API_BASE`
empty (no CORS setup needed). Open `http://localhost:5173`.

### API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sessions` | multipart: `pptx` + `script` + `title` + options → create a video |
| `GET` | `/api/sessions/{id}/status` | poll: `{status, progress, title, kind, output, …}` |
| `GET` | `/api/sessions/{id}/video` | the finished mp4 (`?download=1` to force download) |
| `GET` | `/api/sessions` | history: `?page&limit&status&search` (newest first) |
| `PATCH` | `/api/sessions/{id}` | rename: `{title}` |
| `DELETE` | `/api/sessions/{id}` | delete a session |
| `GET` | `/api/audios` | proxy the Aisha TTS history: `?page&limit&search&language` |
| `GET` | `/api/audios/stream?url=` | proxy a clip's bytes for in-browser preview (key hidden) |
| `POST` | `/api/sessions/reuse/prepare` | build-from-audio step 1: upload pptx, render slides |
| `GET` | `/api/sessions/{id}/slides/{n}.png` | a rendered slide thumbnail (for pairing) |
| `POST` | `/api/sessions/{id}/reuse/build` | step 2: `{pairs:[{slide_index,audio_id,audio_url}]}` |
| `GET` | `/api/stats` | dashboard totals |
| `GET` | `/api/account` | best-effort Aisha balance (`{available:false}` if unknown) |
| `GET` | `/healthz` | tool presence + queue depth |

Status flows:
- Create: `PENDING → RENDERING → SYNTHESIZING → ASSEMBLING → SUCCESS | FAILED`.
- Build from audio: `PENDING → RENDERING → AWAITING_PAIRS → (pick audios) → ASSEMBLING → SUCCESS`.

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

### Frontend → Vercel / Netlify (build)

The dashboard is a Vite app, so it now has a build step.

1. Set the project's **root directory** to `frontend/`.
2. **Build command** `npm run build`, **output directory** `dist`, install `npm install`.
3. Add an env var `VITE_API_BASE = https://<app>.onrender.com` (the backend URL).
4. Deploy, then add that frontend origin to the backend's `AISHA_ALLOWED_ORIGINS`.

### Free-tier caveats (important)

- **Ephemeral storage.** Render's free disk does **not** persist — generated videos **and
  the SQLite history (`aisha.db`)** are lost on every redeploy/restart and after the ~15-min
  idle spin-down. **Download your video right after it's made.** For durable history, use a
  paid plan + a mounted disk (uncomment the `disks:` block in `render.yaml`) so `DATA_DIR`
  survives. Note your **audio** is always safe regardless — it lives in the Aisha TTS
  history, not on this disk, so the Audio Library and Build-From-Audio keep working.
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
  TTS API (so it costs no balance) — the CLI counterpart of the dashboard's **Build From
  Audio** page, handy if a run paid for audio but failed at assembly.
- The dashboard's **Build From Audio** flow renders the slides first, then lets you pick a
  clip from your Aisha history for each slide before assembling — no new TTS is synthesized.
