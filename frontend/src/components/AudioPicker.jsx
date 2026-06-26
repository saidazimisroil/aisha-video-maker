import AudioBrowser from "./AudioBrowser.jsx";

// Modal overlay that lets the user pick one audio from their Aisha history for a slide.
export default function AudioPicker({ slideIndex, onPick, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Pick an audio for slide {slideIndex}</h2>
          <button className="btn sm" onClick={onClose}>
            ✕ Close
          </button>
        </div>
        <AudioBrowser
          onPick={(record) => {
            onPick(record);
            onClose();
          }}
        />
      </div>
    </div>
  );
}
