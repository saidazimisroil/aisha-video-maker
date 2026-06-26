import { useEffect, useState } from "react";
import { renameSession } from "../api/endpoints.js";

// Inline-editable title. Click the text to edit; Enter/blur saves (PATCH), Esc cancels.
export default function TitleEditor({ id, title, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(title || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => setVal(title || ""), [title]);

  const save = async () => {
    setEditing(false);
    const t = val.trim();
    if (!t || t === (title || "")) {
      setVal(title || "");
      return;
    }
    setSaving(true);
    try {
      const r = await renameSession(id, t);
      onRenamed && onRenamed(r.title);
    } catch {
      setVal(title || "");
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <span className="title-editor">
        <input
          autoFocus
          value={val}
          maxLength={120}
          onChange={(e) => setVal(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") {
              setVal(title || "");
              setEditing(false);
            }
          }}
        />
      </span>
    );
  }
  return (
    <span className="editable-title" title="Click to rename" onClick={() => setEditing(true)}>
      {title || "Untitled"}
      {saving && " …"}
    </span>
  );
}
