import React, { useState } from "react";
import { forkVersion } from "../standardsApi";

interface Props {
  sourceVersionId: string;
  open: boolean;
  onClose: () => void;
  onForked: (newVid: string) => void;
}

export default function ForkDialog({sourceVersionId, open, onClose, onForked}: Props) {
  const [label, setLabel] = useState("v1.1");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await forkVersion(sourceVersionId, label);
      onForked(r.new_version_id);
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
                 background: "rgba(0,0,0,0.4)", zIndex: 1000,
                 display: "flex", alignItems: "center", justifyContent: "center"}}>
      <div style={{padding: 16, background: "#fff", borderRadius: 6,
                   width: 360, maxWidth: "90vw"}}>
        <h4 style={{marginTop: 0}}>Fork 新版本</h4>
        <div style={{fontSize: 12, color: "#666", marginBottom: 8}}>
          源版本: {sourceVersionId.slice(0, 8)}…
        </div>
        <label style={{display: "block", fontSize: 12, marginBottom: 4}}>
          新版本号 (例如 v1.1, v2.0)
        </label>
        <input value={label} onChange={e => setLabel(e.target.value)}
               style={{width: "100%", padding: 6, boxSizing: "border-box",
                       border: "1px solid #ccc", borderRadius: 3}}/>
        {err && (
          <div style={{color: "#c33", fontSize: 11, marginTop: 6}}>
            {err}
          </div>
        )}
        <div style={{marginTop: 12, display: "flex", gap: 8,
                     justifyContent: "flex-end"}}>
          <button onClick={onClose} disabled={busy}
                  style={{padding: "6px 12px"}}>取消</button>
          <button onClick={submit} disabled={busy || !label.trim()}
                  style={{padding: "6px 12px", background: "#06c",
                          color: "#fff", border: "none", borderRadius: 3}}>
            {busy ? "Fork 中…" : "确认 Fork"}
          </button>
        </div>
      </div>
    </div>
  );
}
