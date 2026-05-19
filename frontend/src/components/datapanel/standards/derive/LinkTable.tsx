import React, { useEffect, useState } from "react";
import { DerivedLink, listDeriveLinks } from "../standardsApi";

interface Props {
  versionId: string | null;
  strategy: string | null;
  refreshTick: number;
}

const STATUS_COLORS: Record<string, string> = {
  active: "#0a7", stale: "#f80", failed: "#c33",
  pending: "#aaa", overridden: "#999", superseded: "#888",
};

export default function LinkTable({versionId, strategy, refreshTick}: Props) {
  const [links, setLinks] = useState<DerivedLink[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!versionId) { setLinks([]); return; }
    setLoading(true);
    listDeriveLinks({version_id: versionId,
                     strategy: strategy ?? undefined})
      .then(r => setLinks(r.links))
      .catch(() => setLinks([]))
      .finally(() => setLoading(false));
  }, [versionId, strategy, refreshTick]);

  if (!versionId) {
    return (
      <div style={{padding: 24, color: "#888"}}>
        请选择一个版本以查看派生 link
      </div>
    );
  }

  return (
    <div style={{padding: 8, overflow: "auto"}}>
      <h4>派生 Link ({links.length})</h4>
      {loading && <div style={{color: "#888"}}>加载中…</div>}
      {!loading && links.length === 0 && (
        <div style={{color: "#888", fontSize: 12}}>无派生记录</div>
      )}
      <table style={{width: "100%", borderCollapse: "collapse", fontSize: 12}}>
        <thead>
          <tr style={{background: "#f5f5f5"}}>
            <th style={{padding: 4, textAlign: "left"}}>Source</th>
            <th style={{padding: 4, textAlign: "left"}}>Target</th>
            <th style={{padding: 4, textAlign: "left"}}>Strategy</th>
            <th style={{padding: 4, textAlign: "left"}}>Status</th>
            <th style={{padding: 4, textAlign: "left"}}>Generated</th>
          </tr>
        </thead>
        <tbody>
          {links.map(l => (
            <tr key={l.id} style={{borderBottom: "1px solid #eee"}}>
              <td style={{padding: 4, fontFamily: "monospace"}}>
                {l.source_kind}:{l.source_id.slice(0,8)}…
              </td>
              <td style={{padding: 4, fontFamily: "monospace"}}>
                {l.target_kind}:{l.target_id.slice(0,8)}…
              </td>
              <td style={{padding: 4}}>{l.derivation_strategy}</td>
              <td style={{padding: 4}}>
                <span style={{
                  padding: "1px 6px", borderRadius: 3, color: "#fff",
                  background: STATUS_COLORS[l.status] || "#666",
                  fontSize: 11,
                }}>{l.status}</span>
                {l.stale_reason && (
                  <div style={{fontSize: 10, color: "#888"}}>
                    {l.stale_reason}
                  </div>
                )}
              </td>
              <td style={{padding: 4, fontSize: 11}}>
                {l.generated_at && new Date(l.generated_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
