import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { readAuth, writeAuth, setOnUnauthorized } from "../api/client.js";
import { login as apiLogin, logout as apiLogout, getMe } from "../api/endpoints.js";

// Holds the current session ({ token, expiresAt, user }) and exposes login/logout plus role
// helpers. The token+expiry persist in localStorage (via client.js) so a refresh keeps you
// logged in; a setTimeout enforces the 24h auto-logout, and any 401 clears the session too.
const AuthContext = createContext(null);

function notExpired(auth) {
  return !!(auth && auth.expiresAt && new Date(auth.expiresAt).getTime() > Date.now());
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    const a = readAuth();
    return notExpired(a) ? a : null;
  });
  const [loading, setLoading] = useState(true);
  const timer = useRef(null);

  const clear = useCallback(() => {
    writeAuth(null);
    setAuth(null);
  }, []);

  // On first load, confirm a persisted token is still valid server-side (it may have been
  // revoked, expired, or the server restarted) before trusting it.
  useEffect(() => {
    let cancelled = false;
    const a = readAuth();
    if (!notExpired(a)) {
      writeAuth(null);
      setLoading(false);
      return;
    }
    getMe()
      .then((user) => !cancelled && setAuth({ ...a, user }))
      .catch(() => !cancelled && clear())
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [clear]);

  // 24h auto-logout: (re)schedule a timer to fire at the token's expiry.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!auth || !auth.expiresAt) return;
    const ms = new Date(auth.expiresAt).getTime() - Date.now();
    if (ms <= 0) {
      clear();
      return;
    }
    timer.current = setTimeout(clear, ms);
    return () => clearTimeout(timer.current);
  }, [auth, clear]);

  // Any 401 bubbling up from the API layer logs us out here as well.
  useEffect(() => {
    setOnUnauthorized(() => setAuth(null));
    return () => setOnUnauthorized(null);
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await apiLogin(username, password);
    const next = { token: res.token, expiresAt: res.expires_at, user: res.user };
    writeAuth(next);
    setAuth(next);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      /* best-effort; clear locally regardless */
    }
    clear();
  }, [clear]);

  const user = auth ? auth.user : null;
  const role = user ? user.role : null;
  const value = {
    user,
    role,
    loading,
    isAuthenticated: !!auth,
    isAdmin: role === "admin" || role === "super_admin",
    isSuperAdmin: role === "super_admin",
    login,
    logout,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
