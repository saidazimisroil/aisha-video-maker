import { useState } from "react";
import { createVideo, videoUrl } from "../api/endpoints.js";
import { useJobStatus } from "../hooks/useJobStatus.js";
import ProgressBar from "../components/ProgressBar.jsx";
import { countParts, fmtDuration, fmtSize } from "../lib/format.js";

export default function CreateVideo() {
  const [sessionId, setSessionId] = useState(null);
  const [script, setScript] = useState("");
  const [fileHint, setFileHint] = useState("");
  const [resHint, setResHint] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const job = useJobStatus(sessionId, { enabled: !!sessionId });

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.target);
    if (!fd.get("pptx") || !fd.get("pptx").name) {
      setError("Please choose a .pptx file.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await createVideo(fd);
      setSessionId(res.session_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setSessionId(null);
    setScript("");
    setFileHint("");
    setResHint("");
    setError(null);
  };

  // ---- Result / progress view ----
  if (sessionId) {
    const done = job.status === "SUCCESS";
    const failed = job.status === "FAILED";
    return (
      <div>
        <h1 className="page-head">Create Video</h1>
        <p className="page-sub">{job.title || "Your video"}</p>
        <div className="card">
          {!done && !failed && <ProgressBar status={job.status} progress={job.progress} />}
          {done && (
            <>
              <h2>✅ Your video is ready</h2>
              <video className="video" controls src={videoUrl(sessionId)} />
              <p className="muted small">
                {job.slideCount} slide(s)
                {job.output?.duration != null && ` · ${fmtDuration(job.output.duration)}`}
              </p>
              <div className="row">
                <a className="btn primary" href={videoUrl(sessionId, true)}>
                  Download
                </a>
                <button className="btn" onClick={reset}>
                  Make another
                </button>
              </div>
            </>
          )}
          {failed && (
            <>
              <h2>❌ Something went wrong</h2>
              <p className="error">{job.error || "The video could not be created."}</p>
              <button className="btn" onClick={reset}>
                Try again
              </button>
            </>
          )}
          {!done && !failed && (
            <p className="muted small mt">
              This can take a few minutes. You can keep working in other tabs.
            </p>
          )}
        </div>
      </div>
    );
  }

  // ---- Form view ----
  const parts = countParts(script);
  return (
    <div>
      <h1 className="page-head">Create Video</h1>
      <p className="page-sub">Turn a PowerPoint + narration script into a narrated video.</p>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="title">Title <small>(optional, e.g. “lesson 4”)</small></label>
          <input type="text" id="title" name="title" maxLength={120} placeholder="Untitled video" />
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

        <div className="field">
          <label htmlFor="script">Narration script</label>
          <textarea
            id="script"
            name="script"
            required
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder={"Slide 1 narration…\n---\nSlide 2 narration…\n---\nSlide 3 narration…"}
          />
          <small className="hint">
            Separate each slide's narration with a line containing only <code>---</code>. The
            number of parts must equal the number of slides.{" "}
            {parts > 0 && <strong>Detected {parts} narration part(s).</strong>}
          </small>
        </div>

        <div className="grid2">
          <div className="field">
            <label htmlFor="language">Language</label>
            <select id="language" name="language" defaultValue="uz">
              <option value="uz">Uzbek (uz)</option>
              <option value="en">English (en)</option>
              <option value="ru">Russian (ru)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="mood">Mood <small>(uz only)</small></label>
            <select id="mood" name="mood" defaultValue="Neutral">
              <option>Neutral</option>
              <option>Cheerful</option>
              <option>Happy</option>
              <option>Sad</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="height">Resolution</label>
            <select
              id="height"
              name="height"
              defaultValue="720"
              onChange={(e) =>
                setResHint(
                  e.target.value === "1080"
                    ? "Full HD uses more memory; slower on free hosting."
                    : ""
                )
              }
            >
              <option value="480">854 × 480 (SD)</option>
              <option value="720">1280 × 720 (HD)</option>
              <option value="1080">1920 × 1080 (Full HD)</option>
            </select>
            <small className="hint">{resHint}</small>
          </div>
          <div className="field">
            <label htmlFor="fps">Frame rate</label>
            <input type="number" id="fps" name="fps" defaultValue={12} min={6} max={30} />
          </div>
          <div className="field">
            <label htmlFor="speed">Speech speed <small>(uz only)</small></label>
            <input type="number" id="speed" name="speed" defaultValue={0.75} min={0.5} max={2} step={0.05} />
            <small className="hint">1.0 = normal · lower = slower. Default 0.75.</small>
          </div>
        </div>

        <button type="submit" className="btn primary" disabled={submitting}>
          {submitting ? "Uploading…" : "Create video"}
        </button>
        {error && <p className="error mt">{error}</p>}
      </form>
    </div>
  );
}
