import { useEffect, useState } from "react";
import { listSessions } from "../api/endpoints.js";
import VideoCard from "../components/VideoCard.jsx";
import Pagination from "../components/Pagination.jsx";

const STATUSES = ["", "SUCCESS", "FAILED", "AWAITING_PAIRS", "ASSEMBLING", "SYNTHESIZING"];
const LIMIT = 15;

export default function VideoHistory() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    listSessions({ page, limit: LIMIT, status, search })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [page, status, search]);

  const applySearch = (e) => {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  };

  const results = data?.results || [];

  return (
    <div>
      <h1 className="page-head">Video History</h1>
      <p className="page-sub">Everything you've made — search, rename, replay, or delete.</p>

      <div className="card">
        <form className="row" onSubmit={applySearch} style={{ marginBottom: 14 }}>
          <input
            type="text"
            placeholder="Search by title…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            style={{ flex: 1, minWidth: 160 }}
          />
          <select
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
            style={{ width: "auto" }}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "All statuses"}
              </option>
            ))}
          </select>
          <button className="btn" type="submit">
            Search
          </button>
        </form>

        {error && <p className="error">{error}</p>}
        {loading && <p className="muted">Loading…</p>}
        {!loading && !error && results.length === 0 && (
          <p className="muted">No videos match this filter.</p>
        )}

        <ul className="list">
          {results.map((s) => (
            <VideoCard key={s.session_id} s={s} onChanged={load} />
          ))}
        </ul>

        <Pagination page={page} limit={LIMIT} total={data?.count || 0} onPage={setPage} />
      </div>
    </div>
  );
}
