import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../api/client.js";

// Poll a session's status every 2.5s until it reaches a terminal/pause state. Ported from
// the old app.js poll(): a network error or 5xx is transient (keep polling); 404/410 means
// the session is gone for good (stop, mark expired). AWAITING_PAIRS is a pause state for the
// "build from audios" flow, so we stop there too and let the page take over.
const POLL_MS = 2500;
const STOP_STATES = new Set(["SUCCESS", "FAILED", "AWAITING_PAIRS"]);

const EMPTY = {
  status: null, progress: null, error: null, hasOutput: false,
  slideCount: null, title: null, kind: null, output: null, expired: false,
};

export function useJobStatus(sessionId, { enabled = true, onDone } = {}) {
  const [state, setState] = useState(EMPTY);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!sessionId || !enabled) return;
    setState(EMPTY);
    let cancelled = false;
    let timer = null;
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };

    const tick = async () => {
      let res;
      try {
        res = await fetch(apiUrl(`/api/sessions/${sessionId}/status`));
      } catch {
        return; // offline / reset — transient
      }
      if (res.status === 404 || res.status === 410) {
        if (!cancelled) {
          stop();
          setState((s) => ({
            ...s, expired: true, status: "FAILED",
            error: "This session has expired or is no longer available.",
          }));
        }
        return;
      }
      if (!res.ok) return; // 5xx — transient
      let meta;
      try {
        meta = await res.json();
      } catch {
        return; // malformed — transient
      }
      if (cancelled) return;
      const next = {
        status: meta.status, progress: meta.progress, error: meta.error,
        hasOutput: meta.has_output, slideCount: meta.slide_count,
        title: meta.title, kind: meta.kind, output: meta.output, expired: false,
      };
      setState(next);
      if (STOP_STATES.has(meta.status)) {
        stop();
        if (onDoneRef.current) onDoneRef.current(meta);
      }
    };

    tick();
    timer = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      stop();
    };
  }, [sessionId, enabled]);

  return state;
}
