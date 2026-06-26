import { overallPct, PHASE_LABEL } from "../lib/format.js";

export default function ProgressBar({ status, progress }) {
  const pct = overallPct(status, progress);
  const phase = PHASE_LABEL[status] || status || "Starting…";
  return (
    <div>
      <div className="spread">
        <strong>{phase}</strong>
        <span className="muted small">{Math.round(pct)}%</span>
      </div>
      <div className="progressbar">
        <div className="progressbar-fill" style={{ width: pct + "%" }} />
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {(progress && progress.message) || ""}
      </p>
    </div>
  );
}
