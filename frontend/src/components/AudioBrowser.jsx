import { useEffect, useState } from "react";
import { listAudios } from "../api/endpoints.js";
import AudioRow from "./AudioRow.jsx";

// Reusable browser over the Aisha TTS history: search box + language filter + paging. Used
// standalone on the Audio Library page and, with `onPick`, inside the pairing picker. The
// upstream count is unknown, so paging is "Prev/Next" — Next is disabled once a short page
// (fewer than `limit` rows) comes back.
const LANGS = [
  { v: "", label: "All languages" },
  { v: "uz", label: "Uzbek" },
  { v: "en", label: "English" },
  { v: "ru", label: "Russian" },
];

export default function AudioBrowser({ onPick, pickedId }) {
  const limit = 12;
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [language, setLanguage] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAudios({ page, limit, search, language })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [page, search, language]);

  const applySearch = (e) => {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  };

  const results = data?.results || [];
  const canNext = results.length === limit;

  return (
    <div>
      <form className="row" onSubmit={applySearch} style={{ marginBottom: 14 }}>
        <input
          type="text"
          placeholder="Search transcript…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ flex: 1, minWidth: 160 }}
        />
        <select
          value={language}
          onChange={(e) => {
            setPage(1);
            setLanguage(e.target.value);
          }}
          style={{ width: "auto" }}
        >
          {LANGS.map((l) => (
            <option key={l.v} value={l.v}>
              {l.label}
            </option>
          ))}
        </select>
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading audios…</p>}
      {!loading && !error && results.length === 0 && (
        <p className="muted">No audios found in your Aisha history for this filter.</p>
      )}

      <ul className="list">
        {results.map((r, i) => (
          <AudioRow
            key={r.id || r.audio_url || i}
            record={r}
            onPick={onPick}
            picked={pickedId != null && String(pickedId) === String(r.id)}
          />
        ))}
      </ul>

      <div className="pager">
        <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          ← Prev
        </button>
        <span className="muted small">Page {page}</span>
        <button className="btn sm" disabled={!canNext} onClick={() => setPage(page + 1)}>
          Next →
        </button>
      </div>
    </div>
  );
}
