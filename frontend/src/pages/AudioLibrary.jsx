import AudioBrowser from "../components/AudioBrowser.jsx";

export default function AudioLibrary() {
  return (
    <div>
      <h1 className="page-head">Audio Library</h1>
      <p className="page-sub">
        Every clip your Aisha account has ever generated. Preview any of them here, then reuse
        them on the <strong>Build From Audio</strong> page to make a video without spending
        TTS balance again.
      </p>
      <div className="card">
        <AudioBrowser />
      </div>
    </div>
  );
}
