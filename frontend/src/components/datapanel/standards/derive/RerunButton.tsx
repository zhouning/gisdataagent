import React, { useState } from "react";
import { rerunDerivation } from "../standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
  onCompleted: () => void;
}

export default function RerunButton({versionId, isAdmin, onCompleted}: Props) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const rerun = async () => {
    if (!versionId) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await rerunDerivation(versionId);
      const summary = Object.entries(r.results)
        .map(([k, v]: [string, any]) => v.ok
          ? `${k}: +${v.new ?? 0} new / ${v.staled ?? 0} stale`
          : `${k}: 失败 — ${v.error}`)
        .join("; ");
      setMsg(summary || "无 active strategy");
      onCompleted();
    } catch (e: any) {
      setMsg(`失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button onClick={rerun}
              disabled={!versionId || !isAdmin || busy}
              title={!isAdmin ? "仅 admin 可重派生" :
                     !versionId ? "请先选版本" : ""}
              style={{padding: "6px 16px", width: "100%",
                      background: (versionId && isAdmin) ? "#06c" : "#ddd",
                      color: "#fff", border: "none", borderRadius: 4,
                      cursor: (versionId && isAdmin) ? "pointer" : "not-allowed"}}>
        {busy ? "重派生中…" : "重派生"}
      </button>
      {msg && (
        <div style={{marginTop: 8, padding: 6, fontSize: 11,
                     background: "#f5f5f5", border: "1px solid #ddd",
                     borderRadius: 3}}>
          {msg}
        </div>
      )}
    </div>
  );
}
