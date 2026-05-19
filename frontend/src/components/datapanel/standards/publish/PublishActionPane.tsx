import React, { useState } from "react";
import { publishVersion } from "../standardsApi";

interface Props {
  versionId: string | null;
  versionStatus: string | null;  // 'draft' | 'review' | 'approved' | 'released' | etc.
  isAdmin: boolean;
  onPublished: () => void;
  onForkClick: () => void;
}

export default function PublishActionPane({
  versionId, versionStatus, isAdmin, onPublished, onForkClick,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const doPublish = async () => {
    if (!versionId) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await publishVersion(versionId);
      setMsg(`已发布 (released_at=${r.released_at})`);
      onPublished();
    } catch (e: any) {
      setMsg(`失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!versionId) {
    return (
      <div style={{padding: 24, color: "#888"}}>
        请在左侧选择一个版本
      </div>
    );
  }

  const canPublish = isAdmin && versionStatus === "approved";
  const canFork = isAdmin && versionStatus === "released";

  return (
    <div style={{padding: 16}}>
      <div style={{marginBottom: 12, fontSize: 13}}>
        当前状态: <span style={{
          padding: "2px 8px", borderRadius: 3,
          background: versionStatus === "released" ? "#0a7" :
                      versionStatus === "approved" ? "#fb0" : "#aaa",
          color: "#fff", fontSize: 11,
        }}>{versionStatus}</span>
      </div>
      {msg && (
        <div style={{padding: 8, marginBottom: 8, fontSize: 12,
                     background: "#f5f5f5", border: "1px solid #ddd",
                     borderRadius: 3}}>
          {msg}
        </div>
      )}
      <div style={{padding: 12, marginBottom: 8,
                   border: "1px solid #ddd", borderRadius: 4}}>
        <div style={{fontSize: 13, marginBottom: 8}}>
          <strong>发布</strong>: 把 approved 版本冻结为 released
        </div>
        <button onClick={doPublish}
                disabled={!canPublish || busy}
                title={!canPublish ? "仅 admin 可对 approved 版本发布" : ""}
                style={{padding: "6px 16px",
                        background: canPublish ? "#0a7" : "#ddd",
                        color: "#fff", border: "none", borderRadius: 4,
                        cursor: canPublish ? "pointer" : "not-allowed"}}>
          {busy ? "发布中…" : "发布"}
        </button>
      </div>
      <div style={{padding: 12, border: "1px solid #ddd",
                   borderRadius: 4}}>
        <div style={{fontSize: 13, marginBottom: 8}}>
          <strong>Fork 新版本</strong>: 从 released 版本派生新 draft
        </div>
        <button onClick={onForkClick}
                disabled={!canFork}
                title={!canFork ? "仅 admin 可对 released 版本 fork" : ""}
                style={{padding: "6px 16px",
                        background: canFork ? "#06c" : "#ddd",
                        color: "#fff", border: "none", borderRadius: 4,
                        cursor: canFork ? "pointer" : "not-allowed"}}>
          Fork
        </button>
      </div>
    </div>
  );
}
