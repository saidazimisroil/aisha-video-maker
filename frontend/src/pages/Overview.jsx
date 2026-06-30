import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats, listSessions } from "../api/endpoints.js";
import StatCard from "../components/StatCard.jsx";
import VideoCard from "../components/VideoCard.jsx";
import { fmtDuration } from "../lib/format.js";

export default function Overview() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [err, setErr] = useState(null);

  const load = () => {
    getStats().then(setStats).catch((e) => setErr(e.message));
    listSessions({ page: 1, limit: 5 })
      .then((d) => setRecent(d.results))
      .catch(() => {});
  };
  useEffect(load, []);

  return (
    <div>
      <h1 className="page-head">Overview</h1>
      <p className="page-sub">Your video studio at a glance.</p>
      {err && <p className="error">{err}</p>}

      <div className="stat-grid">
        <StatCard value={stats ? stats.total : "—"} label="Videos & presentations" />
        <StatCard
          value={stats ? stats.by_status?.SUCCESS || 0 : "—"}
          label="Completed"
          tone="ok"
        />
        <StatCard
          value={stats ? fmtDuration(stats.total_duration) || "0s" : "—"}
          label="Total runtime"
          tone="accent"
        />
        <StatCard value={stats ? stats.total_slides : "—"} label="Slides rendered" />
        <StatCard value={stats ? stats.queue_depth : "—"} label="Jobs in queue" />
      </div>

      <div className="card">
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Recent</h2>
          <Link to="/history" className="btn sm">
            View all
          </Link>
        </div>
        {recent.length ? (
          <ul className="list">
            {recent.map((s) => (
              <VideoCard key={s.session_id} s={s} onChanged={load} />
            ))}
          </ul>
        ) : (
          <p className="muted">
            No videos yet. <Link to="/create">Create your first one →</Link>
          </p>
        )}
      </div>
    </div>
  );
}
