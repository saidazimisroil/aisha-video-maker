// Small presentation helpers shared across pages. The narration-part counter and the
// progress-percentage logic are ported verbatim from the old vanilla app.js so the
// behaviour is unchanged.

export function fmtSize(bytes) {
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString();
}

export function fmtDuration(seconds) {
  if (seconds == null) return "";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m ? `${m}m ${r}s` : `${r}s`;
}

export function countParts(text) {
  if (!text || !text.trim()) return 0;
  // Mirror the backend: split on lines that are exactly '---', drop empties.
  return text
    .split(/\r?\n/)
    .reduce(
      (acc, line) => {
        if (line.trim() === "---") acc.push("");
        else acc[acc.length - 1] += line;
        return acc;
      },
      [""]
    )
    .map((s) => s.trim())
    .filter(Boolean).length;
}

export function overallPct(status, progress) {
  const p = progress || {};
  const frac = p.total > 0 ? p.current / p.total : 0;
  switch (status) {
    case "PENDING": return 3;
    case "RENDERING": return 6;
    case "SYNTHESIZING": return 10 + frac * 50;
    case "ASSEMBLING": return 60 + frac * 35;
    case "SUCCESS": return 100;
    default: return 0;
  }
}

export const PHASE_LABEL = {
  PENDING: "Queued…",
  RENDERING: "Rendering slides…",
  SYNTHESIZING: "Generating narration…",
  ASSEMBLING: "Assembling video…",
  AWAITING_PAIRS: "Slides ready",
  SUCCESS: "Done",
  FAILED: "Failed",
};

export function snippet(text, n = 140) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n).trimEnd() + "…" : text;
}
