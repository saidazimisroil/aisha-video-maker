import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  listUsers, createUser, updateUser, deleteUser, resetUserPassword,
} from "../../api/endpoints.js";
import { useAuth } from "../../context/AuthContext.jsx";
import Pagination from "../../components/Pagination.jsx";
import { fmtDate } from "../../lib/format.js";

const LIMIT = 20;
const ROLES = [
  { value: "user", label: "Normal user" },
  { value: "admin", label: "Admin" },
  { value: "super_admin", label: "Super admin" },
];
const ROLE_LABEL = {
  user: "User",
  admin: "Admin",
  super_admin: "Super admin",
};

export default function AdminUsers() {
  const { user: me, isSuperAdmin, logout } = useAuth();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [data, setData] = useState({ results: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showCreate, setShowCreate] = useState(false);
  const [editUser, setEditUser] = useState(null); // super_admin: role/active
  const [resetUser, setResetUser] = useState(null); // super_admin: new password

  const load = useCallback(() => {
    setLoading(true);
    listUsers({ page, limit: LIMIT, search })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(load, [load]);

  const applySearch = (e) => {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  };

  const remove = async (u) => {
    if (!window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    try {
      await deleteUser(u.id);
      load();
    } catch (e) {
      alert(e.message);
    }
  };

  return (
    <div className="admin-shell">
      <div className="spread">
        <div>
          <h1 className="page-head">User Management</h1>
          <p className="page-sub">
            {isSuperAdmin
              ? "Create, edit, and remove users, and renew passwords."
              : "View users and create new accounts."}
          </p>
        </div>
        <div className="row-actions">
          <span className="muted small">
            {me.username} · {ROLE_LABEL[me.role] || me.role}
          </span>
          <Link className="btn sm" to="/">App</Link>
          <button className="btn sm" onClick={logout}>Log out</button>
        </div>
      </div>

      <div className="card">
        <div className="spread">
          <form className="row" onSubmit={applySearch}>
            <input
              type="text"
              placeholder="Search username…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ maxWidth: 260 }}
            />
            <button className="btn sm" type="submit">Search</button>
          </form>
          <button className="btn primary sm" onClick={() => setShowCreate(true)}>
            + Create user
          </button>
        </div>

        {error && <p className="error mt">{error}</p>}
        {loading ? (
          <p className="muted mt">Loading…</p>
        ) : data.results.length === 0 ? (
          <p className="muted mt">No users found.</p>
        ) : (
          <ul className="list mt">
            {data.results.map((u) => (
              <li key={u.id}>
                <div className="spread">
                  <div style={{ minWidth: 0 }}>
                    <strong>{u.username}</strong>
                    <div className="audio-meta">
                      <span className={"badge role-" + u.role}>
                        {ROLE_LABEL[u.role] || u.role}
                      </span>
                      {!u.is_active && <span className="badge FAILED">DISABLED</span>}
                      {u.last_login_at && <span>last login {fmtDate(u.last_login_at)}</span>}
                      <span>created {fmtDate(u.created_at)}</span>
                    </div>
                  </div>
                  {isSuperAdmin && (
                    <div className="row-actions">
                      <button className="btn sm" onClick={() => setResetUser(u)}>
                        Reset password
                      </button>
                      <button className="btn sm" onClick={() => setEditUser(u)}>
                        Edit
                      </button>
                      {u.id !== me.id && (
                        <button className="btn sm danger" onClick={() => remove(u)}>
                          Delete
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <Pagination page={page} limit={LIMIT} total={data.count} onPage={setPage} />
      </div>

      {showCreate && (
        <CreateUserModal
          canSetRole={isSuperAdmin}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            setPage(1);
            setSearch("");
            setSearchInput("");
            load();
          }}
        />
      )}
      {editUser && (
        <EditUserModal
          user={editUser}
          onClose={() => setEditUser(null)}
          onSaved={() => {
            setEditUser(null);
            load();
          }}
        />
      )}
      {resetUser && (
        <ResetPasswordModal
          user={resetUser}
          onClose={() => setResetUser(null)}
          onDone={() => setResetUser(null)}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Modals
// --------------------------------------------------------------------------- //
function Modal({ title, children, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="spread">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn sm" onClick={onClose}>✕</button>
        </div>
        <div className="mt">{children}</div>
      </div>
    </div>
  );
}

function CreateUserModal({ canSetRole, onClose, onCreated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const valid = username.trim().length >= 3 && password.length >= 8;

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = { username: username.trim(), password };
      if (canSetRole) body.role = role;
      await createUser(body);
      onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Create user" onClose={onClose}>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="cu-username">Username</label>
          <input
            id="cu-username"
            type="text"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <small className="hint">Letters, digits, and . _ - · at least 3 characters.</small>
        </div>
        <div className="field">
          <label htmlFor="cu-password">Password</label>
          <input
            id="cu-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <small className="hint">At least 8 characters.</small>
        </div>
        {canSetRole ? (
          <div className="field">
            <label htmlFor="cu-role">Role</label>
            <select id="cu-role" value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>
        ) : (
          <p className="hint">New accounts are created as normal users.</p>
        )}

        <button type="submit" className="btn primary" disabled={busy || !valid}>
          {busy ? "Creating…" : "Create user"}
        </button>
        {error && <p className="error mt">{error}</p>}
      </form>
    </Modal>
  );
}

function EditUserModal({ user, onClose, onSaved }) {
  const [role, setRole] = useState(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await updateUser(user.id, { role, is_active: isActive });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Edit ${user.username}`} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="eu-role">Role</label>
          <select id="eu-role" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="row" style={{ alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              style={{ width: "auto" }}
            />
            Account active
          </label>
          <small className="hint">Disabling a user revokes their active sessions.</small>
        </div>

        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        {error && <p className="error mt">{error}</p>}
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose, onDone }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await resetUserPassword(user.id, password);
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Reset password — ${user.username}`} onClose={onClose}>
      {done ? (
        <div>
          <p>
            Password updated. Share the new password with the user securely — it can't be
            viewed again here. Their existing sessions have been signed out.
          </p>
          <button className="btn primary mt" onClick={onDone}>Done</button>
        </div>
      ) : (
        <form onSubmit={submit}>
          <p className="hint">
            Set a new password for this user. The current password can't be viewed (passwords
            are stored hashed) — you can only replace it.
          </p>
          <div className="field">
            <label htmlFor="rp-password">New password</label>
            <input
              id="rp-password"
              type="password"
              autoFocus
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <small className="hint">At least 8 characters.</small>
          </div>
          <button type="submit" className="btn primary" disabled={busy || password.length < 8}>
            {busy ? "Updating…" : "Set new password"}
          </button>
          {error && <p className="error mt">{error}</p>}
        </form>
      )}
    </Modal>
  );
}
