import {
  apiUrl, qs, apiGet, apiPostJson, apiPostForm, apiPatch, apiDelete,
} from "./client.js";

// ---- Videos / history -----------------------------------------------------
export const listSessions = (params) => apiGet(`/api/sessions${qs(params)}`);
export const getStatus = (id) => apiGet(`/api/sessions/${id}/status`);
export const renameSession = (id, title) => apiPatch(`/api/sessions/${id}`, { title });
export const deleteSession = (id) => apiDelete(`/api/sessions/${id}`);
export const createVideo = (formData) => apiPostForm(`/api/sessions`, formData);

// ---- Build from existing audios ------------------------------------------
export const reusePrepare = (formData) =>
  apiPostForm(`/api/sessions/reuse/prepare`, formData);
export const reuseBuild = (id, pairs) =>
  apiPostJson(`/api/sessions/${id}/reuse/build`, { pairs });
export const slideUrl = (id, n) => apiUrl(`/api/sessions/${id}/slides/${n}.png`);

// ---- Audio library --------------------------------------------------------
export const listAudios = (params) => apiGet(`/api/audios${qs(params)}`);
export const audioStreamUrl = (url) =>
  apiUrl(`/api/audios/stream?url=${encodeURIComponent(url)}`);

// ---- Text to speech (single clip, ≤1000 chars) ---------------------------
export const createTts = (body) => apiPostJson(`/api/tts`, body);

// ---- Dashboard ------------------------------------------------------------
export const getStats = () => apiGet(`/api/stats`);
export const getAccount = () => apiGet(`/api/account`);

// ---- Media URLs -----------------------------------------------------------
export const videoUrl = (id, download) =>
  apiUrl(`/api/sessions/${id}/video${download ? "?download=1" : ""}`);
