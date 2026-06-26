import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/", icon: "📊", label: "Overview", end: true },
  { to: "/create", icon: "🎬", label: "Create Video" },
  { to: "/audios", icon: "🎧", label: "Audio Library" },
  { to: "/build", icon: "🧩", label: "Build From Audio" },
  { to: "/history", icon: "🗂️", label: "Video History" },
];

export default function Sidebar() {
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
