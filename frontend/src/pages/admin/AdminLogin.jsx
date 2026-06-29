import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.jsx";

// Login surface for the admin area (rendered at /admin when not yet signed in). It shares the
// same credential system as /login; role gating (must be admin/super_admin) happens in
// AdminArea once the session is established.
export default function AdminLogin() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
      // AdminArea re-renders from auth state and decides what to show next.
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <h1>🔐 Admin Console</h1>
        <p className="page-sub">Administrator sign-in.</p>

        <div className="field">
          <label htmlFor="admin-username">Username</label>
          <input
            id="admin-username"
            type="text"
            autoFocus
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="admin-password">Password</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button
          type="submit"
          className="btn primary"
          disabled={busy || !username.trim() || !password}
        >
          {busy ? "Signing in…" : "Log in"}
        </button>
        {error && <p className="error mt">{error}</p>}
        <p className="hint mt">
          <Link to="/login">← Back to app login</Link>
        </p>
      </form>
    </div>
  );
}
