import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import BalanceCard from "./BalanceCard.jsx";

const LINKS = [
  { to: "/", icon: "📊", label: "Overview", end: true },
  { to: "/create", icon: "🎬", label: "Create Video" },
  { to: "/tts", icon: "🔊", label: "Generate Audio" },
  { to: "/audios", icon: "🎧", label: "Audio Library" },
  { to: "/build", icon: "🧩", label: "Build From Audio" },
  { to: "/history", icon: "🗂️", label: "Video History" },
];

const ROLE_LABEL = { user: "User", admin: "Admin", super_admin: "Super admin" };

export default function Sidebar() {
  const { user, isAdmin, logout } = useAuth();

  return (
    <aside className="sidebar">
      <div className="brand">
        🎬 Aisha Studio
        <small>Video maker dashboard</small>
      </div>
      {LINKS.map((l) => (
        <NavLink
          key={l.to}
          to={l.to}
          end={l.end}
          className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}
        >
          <span className="ico">{l.icon}</span>
          {l.label}
        </NavLink>
      ))}
      {isAdmin && (
        // Plain anchor: /admin is outside the app's router layout (its own surface).
        <a className="nav-link" href="/admin">
          <span className="ico">🔐</span>
          Admin
        </a>
      )}

      <BalanceCard />

      {user && (
        <div className="sidebar-user">
          <div className="su-name">{user.username}</div>
          <div className="su-role muted small">{ROLE_LABEL[user.role] || user.role}</div>
          <button className="btn sm mt" onClick={logout} style={{ width: "100%" }}>
            Log out
          </button>
        </div>
      )}

      <div className="sidebar-foot">
        Powered by the{" "}
        <a href="https://space.aisha.group/documentation" target="_blank" rel="noopener">
          Aisha TTS API
        </a>
        .
      </div>
    </aside>
  );
}
