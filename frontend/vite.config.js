import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev we leave VITE_API_BASE unset and proxy the API to the local backend, so the
// browser talks to the same origin (no CORS) and <audio>/<video>/<img> src URLs that point
// at /api/... just work. In production set VITE_API_BASE to the deployed backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/healthz": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
