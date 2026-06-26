import { audioStreamUrl } from "../api/endpoints.js";
import { fmtDate, snippet } from "../lib/format.js";
import Badge from "./Badge.jsx";

// One TTS-history record: transcript preview, metadata, an inline preview player (streamed
// server-side so the API key is never exposed) and, in the picker, a "Use this" button.
export default function AudioRow({ record, onPick, picked }) {
  const hasAudio = !!record.audio_url;
  return (
    <li className="audio-row">
      <div className="spread">
        <p className="transcript">{snippet(record.transcript) || <em className="muted">No transcript</em>}</p>
        {onPick && (
          <button
            className={"btn sm" + (picked ? "" : " primary")}
            disabled={!hasAudio}
            onClick={() => onPick(record)}
          >
            {picked ? "Picked ✓" : "Use this"}
          </button>
        )}
      </div>
      <div className="audio-meta">
        {record.language && <span>🌐 {record.language}</span>}
        {record.status && <Badge status={record.status} />}
        {record.created_at && <span>{fmtDate(record.created_at)}</span>}
        {record.id && <span className="muted">#{record.id}</span>}
      </div>
      {hasAudio ? (
        <audio controls preload="none" src={audioStreamUrl(record.audio_url)} />
      ) : (
        <p className="muted small">Audio not available for preview.</p>
      )}
    </li>
  );
}
