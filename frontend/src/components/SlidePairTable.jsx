import { slideUrl } from "../api/endpoints.js";
import { snippet } from "../lib/format.js";

// One row per rendered slide: a thumbnail + the audio currently paired with it + a button to
// pick/change that audio. `pairs[i]` is the chosen record for slide i+1 (or undefined).
export default function SlidePairTable({ sessionId, slideCount, pairs, onPick }) {
  return (
    <div>
      {Array.from({ length: slideCount }, (_, i) => {
        const n = i + 1;
        const p = pairs[i];
        return (
          <div className="pair-row" key={n}>
            <img src={slideUrl(sessionId, n)} alt={`Slide ${n}`} loading="lazy" />
            <div>
              <div className="small muted">Slide {n}</div>
              {p ? (
                <div className="pair-chosen">
                  🎧 {snippet(p.transcript, 90) || `audio #${p.audio_id || ""}`}
                </div>
              ) : (
                <div className="muted small">No audio chosen yet</div>
              )}
            </div>
            <button className="btn sm" onClick={() => onPick(n)}>
              {p ? "Change" : "Pick audio"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
