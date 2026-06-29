// Backend base URL. In dev this is empty and Vite proxies /api to the local backend; in
// production set VITE_API_BASE to the deployed backend URL (e.g. the Render service).
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

// Persisted auth blob: { token, expiresAt, user }. client.js owns the storage read/write so the
// token can be read synchronously (e.g. to sign media URLs) without importing React state.
const AUTH_KEY = "aisha_auth";

export function readAuth() {
  try {
    return JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
  } catch {
    return null;
  }
}

export function writeAuth(auth) {
  try {
    if (auth) localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
    else localStorage.removeItem(AUTH_KEY);
  } catch {
    /* storage unavailable (private mode) — auth just won't persist */
  }
}

function getToken() {
  const a = readAuth();
  return a && a.token ? a.token : null;
}

// Registered by AuthContext so a 401 from anywhere clears state + bounces to /login.
let onUnauthorized = null;
export function setOnUnauthorized(cb) {
  onUnauthorized = cb;
}

function authHeaders(extra) {
  const headers = { ...(extra || {}) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function apiUrl(path) {
  return `${API_BASE}${path}`;
}

// Like apiUrl but signs the URL with ?token= so the browser can load gated media via
// <img>/<video>/<audio> and download links, which can't send an Authorization header.
export function authedUrl(path) {
  const token = getToken();
  if (!token) return apiUrl(path);
  const sep = path.includes("?") ? "&" : "?";
  return `${apiUrl(path)}${sep}token=${encodeURIComponent(token)}`;
}

export function qs(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, v);
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function handle(res) {
  if (!res.ok) {
    if (res.status === 401) {
      writeAuth(null);
      if (onUnauthorized) onUnauthorized();
    }
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Request failed (${res.status}).`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res;
}

export async function apiGet(path) {
  return handle(await fetch(apiUrl(path), { headers: authHeaders() }));
}

export async function apiPostJson(path, body) {
  return handle(
    await fetch(apiUrl(path), {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    })
  );
}

export async function apiPostForm(path, formData) {
  return handle(
    await fetch(apiUrl(path), {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    })
  );
}

export async function apiPatch(path, body) {
  return handle(
    await fetch(apiUrl(path), {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    })
  );
}

export async function apiDelete(path) {
  return handle(
    await fetch(apiUrl(path), { method: "DELETE", headers: authHeaders() })
  );
}
