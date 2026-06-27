import { useState } from "react";
import { reusePrepare, reuseBuild, videoUrl } from "../api/endpoints.js";
import { useJobStatus } from "../hooks/useJobStatus.js";
import ProgressBar from "../components/ProgressBar.jsx";
import SlidePairTable from "../components/SlidePairTable.jsx";
import AudioPicker from "../components/AudioPicker.jsx";
import { fmtDuration, fmtSize } from "../lib/format.js";

// Wizard: upload pptx → (worker renders slides) → pair each slide with an existing audio →
// build the video from those clips (no TTS spent) → done.
export default function BuildFromAudio() {
  const [step, setStep] = useState("upload"); // upload | preparing | pairing | building | done | error
  const [sessionId, setSessionId] = useState(null);
  const [slideCount, setSlideCount] = useState(0);
  const [pairs, setPairs] = useState([]); // index i -> chosen record for slide i+1
  const [picking, setPicking] = useState(null); // slide number whose picker is open
  const [fileHint, setFileHint] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const polling = step === "preparing" || step === "building";

  const job = useJobStatus(sessionId, {
    enabled: polling,
    onDone: (meta) => {
      if (meta.status === "AWAITING_PAIRS") {
        setSlideCount(meta.slide_count || 0);
        setPairs(Array(meta.slide_count || 0).fill(undefined));
        setStep("pairing");
      } else if (meta.status === "SUCCESS") {
        setStep("done");
      } else if (meta.status === "FAILED") {
        setError(meta.error || "Something went wrong.");
        setStep("error");
      }
    },
  });

  const upload = async (e) => {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.target);
    if (!fd.get("pptx") || !fd.get("pptx").name) {
      setError("Please choose a .pptx file.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await reusePrepare(fd);
      setSessionId(res.session_id);
      setStep("preparing");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const choose = (record) => {
    const n = picking;
    setPairs((prev) => {
      const next = [...prev];
      next[n - 1] = {
        slide_index: n,
        audio_id: record.id,
        audio_url: record.audio_url,
        transcript: record.transcript,
      };
      return next;
    });
  };

  const allChosen = slideCount > 0 && pairs.length === slideCount && pairs.every(Boolean);

  const build = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const payload = pairs.map((p) => ({
        slide_index: p.slide_index,
        audio_id: p.audio_id,
        audio_url: p.audio_url,
      }));
      await reuseBuild(sessionId, payload);
      setStep("building");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setStep("upload");
    setSessionId(null);
    setSlideCount(0);
    setPairs([]);
    setPicking(null);
    setFileHint("");
    setError(null);
  };

  return (
    <div>
      <h1 className="page-head">Build From Audio</h1>
      <p className="page-sub">
        Reuse audios you already generated — pair each slide with an existing clip and stitch a
        video. No new narration is synthesized, so it costs no TTS balance.
      </p>

      {step === "upload" && (
        <form className="card" onSubmit={upload}>
          <div className="field">
            <label htmlFor="title">Title <small>(optional, e.g. “lesson 55”)</small></label>
            <input type="text" id="title" name="title" maxLength={120} placeholder="Untitled presentation" />
          </div>
          <div className="field">
            <label htmlFor="pptx">Presentation (.pptx)</label>
            <input
              type="file"
              id="pptx"
              name="pptx"
              accept=".pptx"
              required
              onChange={(e) => {
                const f = e.target.files[0];
                setFileHint(f ? `${f.name} · ${fmtSize(f.size)}` : "");
              }}
            />
            <small className="hint">{fileHint}</small>
          </div>
          <div className="grid2">
            <div className="field">
              <label htmlFor="height">Resolution</label>
              <select id="height" name="height" defaultValue="720">
                <option value="480">854 × 480 (SD)</option>
                <option value="720">1280 × 720 (HD)</option>
                <option value="1080">1920 × 1080 (Full HD)</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="fps">Frame rate</label>
              <input type="number" id="fps" name="fps" defaultValue={12} min={6} max={30} />
            </div>
          </div>
          <button type="submit" className="btn primary" disabled={submitting}>
            {submitting ? "Uploading…" : "Upload & render slides"}
          </button>
          {error && <p className="error mt">{error}</p>}
        </form>
      )}

      {step === "preparing" && (
        <div className="card">
          <ProgressBar status={job.status} progress={job.progress} />
          <p className="muted small mt">Rendering your slides so you can pair them with audios…</p>
        </div>
      )}

      {step === "pairing" && (
        <div className="card">
          <div className="spread" style={{ marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Pair each slide with an audio</h2>
            <span className="muted small">
              {pairs.filter(Boolean).length}/{slideCount} chosen
            </span>
          </div>
          <SlidePairTable
            sessionId={sessionId}
            slideCount={slideCount}
            pairs={pairs}
            onPick={(n) => setPicking(n)}
          />
          <div className="row mt">
            <button className="btn primary" disabled={!allChosen || submitting} onClick={build}>
              {submitting ? "Starting…" : "Build video"}
            </button>
            <button className="btn" onClick={reset}>
              Start over
            </button>
            {!allChosen && (
              <span className="muted small">Choose an audio for every slide to continue.</span>
            )}
          </div>
          {error && <p className="error mt">{error}</p>}
        </div>
      )}

      {step === "building" && (
        <div className="card">
          <ProgressBar status={job.status} progress={job.progress} />
          <p className="muted small mt">Fetching your audios and assembling the video…</p>
        </div>
      )}

      {step === "done" && (
        <div className="card">
          <h2>✅ Your presentation is ready</h2>
          <video className="video" controls src={videoUrl(sessionId)} />
          <p className="muted small">
            {slideCount} slide(s)
            {job.output?.duration != null && ` · ${fmtDuration(job.output.duration)}`} · no TTS
            balance spent
          </p>
          <div className="row">
            <a className="btn primary" href={videoUrl(sessionId, true)}>
              Download
            </a>
            <button className="btn" onClick={reset}>
              Build another
            </button>
          </div>
        </div>
      )}

      {step === "error" && (
        <div className="card">
          <h2>❌ Something went wrong</h2>
          <p className="error">{error}</p>
          <button className="btn" onClick={reset}>
            Start over
          </button>
        </div>
      )}

      {picking != null && (
        <AudioPicker slideIndex={picking} onPick={choose} onClose={() => setPicking(null)} />
      )}
    </div>
  );
}
