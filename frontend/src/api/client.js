// Backend base URL. In dev this is empty and Vite proxies /api to the local backend; in
// production set VITE_API_BASE to the deployed backend URL (e.g. the Render service).
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

export function apiUrl(path) {
  return `${API_BASE}${path}`;
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
  return handle(await fetch(apiUrl(path)));
}

export async function apiPostJson(path, body) {
  return handle(
    await fetch(apiUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function apiPostForm(path, formData) {
  return handle(await fetch(apiUrl(path), { method: "POST", body: formData }));
}

export async function apiPatch(path, body) {
  return handle(
    await fetch(apiUrl(path), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function apiDelete(path) {
  return handle(await fetch(apiUrl(path), { method: "DELETE" }));
}
