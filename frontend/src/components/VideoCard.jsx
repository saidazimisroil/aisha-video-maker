import { useState } from "react";
import { deleteSession, videoUrl } from "../api/endpoints.js";
import { fmtDate, fmtDuration } from "../lib/format.js";
import Badge from "./Badge.jsx";
import TitleEditor from "./TitleEditor.jsx";

// One row in the Video History list: inline-renamable title, status/kind badges, metadata,
// and Open (inline player) / Download / Delete actions.
export default function VideoCard({ s, onChanged }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(s.title);
  const [busy, setBusy] = useState(false);

  const del = async () => {
    if (!window.confirm("Delete this video? This cannot be undone.")) return;
    setBusy(true);
    try {
      await deleteSession(s.session_id);
      onChanged && onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <li>
      <div className="spread">
        <div style={{ minWidth: 0 }}>
          <TitleEditor id={s.session_id} title={title} onRenamed={setTitle} />
          <div className="audio-meta">
            <Badge status={s.status} />
            <Badge kind={s.kind} />
            {s.slide_count != null && <span>{s.slide_count} slides</span>}
            {s.duration != null && <span>{fmtDuration(s.duration)}</span>}
            <span>{fmtDate(s.created_at)}</span>
          </div>
        </div>
        <div className="row-actions">
          {s.has_output && (
            <button className="btn sm" onClick={() => setOpen((o) => !o)}>
              {open ? "Hide" : "Open"}
            </button>
          )}
          {s.has_output && (
            <a className="btn sm" href={videoUrl(s.session_id, true)}>
              Download
            </a>
          )}
          <button className="btn sm danger" disabled={busy} onClick={del}>
            Delete
          </button>
        </div>
      </div>
      {open && s.has_output && (
        <video className="video" controls src={videoUrl(s.session_id)} />
      )}
      {s.status === "FAILED" && s.error && <p className="error small mt">{s.error}</p>}
    </li>
  );
}
