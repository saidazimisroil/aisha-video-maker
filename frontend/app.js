"use strict";

// Backend base URL comes from config.js (window.API_BASE).
const API = (window.API_BASE || "").replace(/\/+$/, "");
const POLL_MS = 2500;

// ---- element refs ---------------------------------------------------------
const $ = (id) => document.getElementById(id);
const views = {
  upload: $("view-upload"),
  progress: $("view-progress"),
  result: $("view-result"),
};
const form = $("form");
const pptxInput = $("pptx");
const scriptInput = $("script");
const heightSel = $("height");
let pollTimer = null;

// ---- view switching -------------------------------------------------------
function show(view) {
  for (const [name, el] of Object.entries(views)) el.hidden = name !== view;
}

// ---- helpers --------------------------------------------------------------
function fmtSize(bytes) {
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function countParts() {
  const text = scriptInput.value;
  if (!text.trim()) return 0;
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

function updatePartsCount() {
  const n = countParts();
  $("parts-count").textContent = n ? `Detected ${n} narration part(s).` : "";
}

function overallPct(status, progress) {
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

const PHASE_LABEL = {
  PENDING: "Queued…",
  RENDERING: "Rendering slides…",
  SYNTHESIZING: "Generating narration…",
  ASSEMBLING: "Assembling video…",
};

// ---- create + poll --------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  $("upload-error").hidden = true;

  if (!pptxInput.files.length) return;

  const fd = new FormData();
  fd.append("pptx", pptxInput.files[0]);
  fd.append("script", scriptInput.value);
  fd.append("language", $("language").value);
  fd.append("mood", $("mood").value);
  fd.append("height", heightSel.value);
  fd.append("fps", $("fps").value);
  fd.append("speed", $("speed").value);

  const btn = $("submit-btn");
  btn.disabled = true;
  btn.textContent = "Uploading…";
  try {
    const res = await fetch(`${API}/api/sessions`, { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `Upload failed (${res.status}).`);
    startPolling(body.session_id);
  } catch (err) {
    const el = $("upload-error");
    el.textContent = err.message;
    el.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Create video";
  }
});

function startPolling(sessionId) {
  show("progress");
  $("progress-phase").textContent = "Starting…";
  $("progress-fill").style.width = "3%";
  $("progress-message").textContent = "";
  poll(sessionId);
  pollTimer = setInterval(() => poll(sessionId), POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function poll(sessionId) {
  let res;
  try {
    res = await fetch(`${API}/api/sessions/${sessionId}/status`);
  } catch (err) {
    // No response at all (offline / DNS / reset) — transient, keep polling.
    return;
  }

  // 404/410 means the session is gone for good: it expired, or the server was
  // restarted and its ephemeral disk was wiped. Stop and tell the user instead
  // of polling a vanished session forever.
  if (res.status === 404 || res.status === 410) {
    stopPolling();
    showResult(
      sessionId,
      { error: "This video session has expired or is no longer available. Please create the video again." },
      true
    );
    return;
  }

  // Other non-OK (e.g. 5xx) — treat as transient and keep polling.
  if (!res.ok) return;

  let meta;
  try {
    meta = await res.json();
  } catch (err) {
    return; // malformed body — transient, keep polling
  }

  const { status, progress } = meta;
  $("progress-fill").style.width = overallPct(status, progress) + "%";
  $("progress-phase").textContent = PHASE_LABEL[status] || status;
  $("progress-message").textContent = (progress && progress.message) || "";

  if (status === "SUCCESS") {
    stopPolling();
    showResult(sessionId, meta);
    loadHistory();
  } else if (status === "FAILED") {
    stopPolling();
    showResult(sessionId, meta, true);
    loadHistory();
  }
}

function showResult(sessionId, meta, failed = false) {
  show("result");
  const errEl = $("result-error");
  const videoEl = $("result-video");
  if (failed) {
    $("result-title").textContent = "❌ Something went wrong";
    videoEl.hidden = true;
    $("download-link").style.display = "none";
    $("result-meta").textContent = "";
    errEl.textContent = meta.error || "The video could not be created.";
    errEl.hidden = false;
    return;
  }
  $("result-title").textContent = "✅ Your video is ready";
  errEl.hidden = true;
  videoEl.hidden = false;
  videoEl.src = `${API}/api/sessions/${sessionId}/video`;
  const dl = $("download-link");
  dl.style.display = "";
  dl.href = `${API}/api/sessions/${sessionId}/video?download=1`;
  const out = meta.output || {};
  $("result-meta").textContent =
    out.duration != null
      ? `${meta.slide_count} slide(s) · ${out.duration}s total`
      : "";
}

$("again-btn").addEventListener("click", () => {
  show("upload");
  form.reset();
  updatePartsCount();
  updateFileHint();
  updateResHint();
});

// ---- history --------------------------------------------------------------
async function loadHistory() {
  let data;
  try {
    const res = await fetch(`${API}/api/sessions`);
    if (!res.ok) return;
    data = await res.json();
  } catch {
    return;
  }
  $("history-count").textContent = data.count ? `(${data.count})` : "";
  const list = $("history-list");
  list.innerHTML = "";
  if (!data.results.length) {
    list.innerHTML = '<li class="muted small">No videos yet.</li>';
    return;
  }
  for (const s of data.results) {
    const li = document.createElement("li");
    const when = s.created_at ? new Date(s.created_at).toLocaleString() : "";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<span class="badge ${s.status}">${s.status}</span>
      <span class="muted small">${when}${
        s.slide_count ? " · " + s.slide_count + " slides" : ""
      }</span>`;
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (s.has_output) {
      const open = document.createElement("button");
      open.className = "btn";
      open.textContent = "Open";
      open.onclick = () =>
        showResult(s.session_id, { slide_count: s.slide_count, output: {} });
      actions.appendChild(open);
    }
    const del = document.createElement("button");
    del.className = "btn";
    del.textContent = "Delete";
    del.onclick = async () => {
      await fetch(`${API}/api/sessions/${s.session_id}`, { method: "DELETE" });
      loadHistory();
    };
    actions.appendChild(del);
    li.appendChild(meta);
    li.appendChild(actions);
    list.appendChild(li);
  }
}

// ---- live hints -----------------------------------------------------------
function updateFileHint() {
  const f = pptxInput.files[0];
  $("file-hint").textContent = f ? `${f.name} · ${fmtSize(f.size)}` : "";
}
function updateResHint() {
  $("res-hint").textContent =
    heightSel.value === "1080" ? "Full HD uses more memory; slower on free hosting." : "";
}

scriptInput.addEventListener("input", updatePartsCount);
pptxInput.addEventListener("change", updateFileHint);
heightSel.addEventListener("change", updateResHint);

// ---- init -----------------------------------------------------------------
updateResHint();
loadHistory();
