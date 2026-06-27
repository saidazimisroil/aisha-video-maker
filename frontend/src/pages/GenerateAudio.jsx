import { useState } from "react";
import { createTts, audioStreamUrl } from "../api/endpoints.js";
import { snippet, fmtDate } from "../lib/format.js";

// The Aisha TTS limit — one clip is at most this many characters (mirrors the backend
// CHAR_LIMIT). The textarea hard-caps input and the counter shows progress toward it.
const CHAR_LIMIT = 1000;

export default function GenerateAudio() {
  const [transcript, setTranscript] = useState("");
  const [language, setLanguage] = useState("uz");
  const [mood, setMood] = useState("Neutral");
  const [speed, setSpeed] = useState(0.75);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [clips, setClips] = useState([]); // this session's generations, newest first

  const count = transcript.length;
  const over = count > CHAR_LIMIT;
  const empty = transcript.trim().length === 0;
  const isUz = language === "uz";

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (empty) {
      setError("Please enter some text to generate audio.");
      return;
    }
    if (over) {
      setError(`The text is ${count} characters, over the ${CHAR_LIMIT}-character limit.`);
      return;
    }
    setLoading(true);
    try {
      const body = { transcript, language };
      if (isUz) {
        body.mood = mood;
        body.speed = Number(speed);
      }
      const rec = await createTts(body);
      setClips((prev) => [{ ...rec, _key: rec.id || `c${prev.length}-${Date.now()}` }, ...prev]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="page-head">Generate Audio</h1>
      <p className="page-sub">
        Turn text into speech with the Aisha TTS voices — up to {CHAR_LIMIT} characters per
        clip. Each generation spends a little of your account balance.
      </p>

      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="transcript">Text</label>
          <textarea
            id="transcript"
            value={transcript}
            maxLength={CHAR_LIMIT}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="Type the text you want to turn into speech…"
          />
          <small className={"hint" + (over ? " error" : "")}>
            {count} / {CHAR_LIMIT} characters
          </small>
        </div>

        <div className="grid2">
          <div className="field">
            <label htmlFor="language">Language</label>
            <select
              id="language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="uz">Uzbek (uz)</option>
              <option value="en">English (en)</option>
              <option value="ru">Russian (ru)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="mood">Mood <small>(uz only)</small></label>
            <select
              id="mood"
              value={mood}
              disabled={!isUz}
              onChange={(e) => setMood(e.target.value)}
            >
              <option>Neutral</option>
              <option>Cheerful</option>
              <option>Happy</option>
              <option>Sad</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="speed">Speech speed <small>(uz only)</small></label>
            <input
              type="number"
              id="speed"
              value={speed}
              min={0.5}
              max={2}
              step={0.05}
              disabled={!isUz}
              onChange={(e) => setSpeed(e.target.value)}
            />
            <small className="hint">1.0 = normal · lower = slower. Default 0.75.</small>
          </div>
        </div>

        <button type="submit" className="btn primary" disabled={loading || empty || over}>
          {loading ? "Generating…" : "Generate audio"}
        </button>
        {error && <p className="error mt">{error}</p>}
      </form>

      {clips.length > 0 && (
        <div className="card mt">
          <h2>Generated this session</h2>
          <ul className="list">
            {clips.map((c) => (
              <li className="audio-row" key={c._key}>
                <p className="transcript">{snippet(c.transcript)}</p>
                <div className="audio-meta">
                  {c.language && <span>🌐 {c.language}</span>}
                  {c.created_at && <span>{fmtDate(c.created_at)}</span>}
                  {c.id && <span className="muted">#{c.id}</span>}
                </div>
                {c.audio_url ? (
                  <>
                    <audio controls src={audioStreamUrl(c.audio_url)} />
                    <div className="row mt">
                      <a className="btn sm" href={audioStreamUrl(c.audio_url)} download>
                        Download
                      </a>
                    </div>
                  </>
                ) : (
                  <p className="muted small">Audio not available.</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
