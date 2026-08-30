import React, { useState } from "react";
import { ArrowRight, Network } from "lucide-react";
import StrategyPane from "./derive/StrategyPane";
import LinkTable from "./derive/LinkTable";
import DeriveStatusSummary from "./derive/DeriveStatusSummary";
import RerunButton from "./derive/RerunButton";
import BatchRollbackPanel from "./derive/BatchRollbackPanel";
import OutboxDeadLetterPanel from "./derive/OutboxDeadLetterPanel";

interface Props {
  versionId: string | null;
  userRole: string;
}

/**
 * Derivation is deliberately a vertical workflow. The data panel is only
 * about 340px wide by default; the previous 20/60/20 grid made every control
 * unreadable and hid the model action in a narrow right rail.
 */
export default function DeriveSubTab({ versionId, userRole }: Props) {
  const isAdmin = userRole === "admin";
  const [strategy, setStrategy] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const refresh = () => setRefreshTick(tick => tick + 1);
  const openUnifiedModelWorkbench = () => {
    if (!versionId) return;
    window.dispatchEvent(new CustomEvent("gda-workspace-update", {
      detail: { tab: "models", versionId },
    }));
  };

  return (
    <div style={{ minHeight: "100%", padding: 10, background: "#f8fafc", color: "#17212b", boxSizing: "border-box" }}>
      <section style={{ padding: 12, marginBottom: 10, background: "#fff", border: "1px solid #dbe7f1", borderRadius: 9, boxShadow: "0 2px 8px rgba(15, 70, 110, 0.06)" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <div>
            <div style={{ color: "#1464a5", fontSize: 15, fontWeight: 650 }}>派生结果</div>
            <div style={{ marginTop: 4, color: "#64748b", fontSize: 11, lineHeight: 1.45 }}>
              当前版本的派生状态和记录；模型统一在数据模型工作台中查看。
            </div>
          </div>
          {versionId && <span style={{ padding: "3px 6px", borderRadius: 4, background: "#eef6ff", color: "#1464a5", fontFamily: "Menlo, Consolas, monospace", fontSize: 10 }} title={versionId}>已选版本 · {versionId.slice(0, 8)}…</span>}
        </div>

        <button onClick={openUnifiedModelWorkbench} disabled={!versionId} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, width: "100%", padding: "10px 12px", border: "none", borderRadius: 7, background: versionId ? "#1464a5" : "#cbd5e1", color: "#fff", fontSize: 13, fontWeight: 600, cursor: versionId ? "pointer" : "not-allowed", boxShadow: versionId ? "0 3px 8px rgba(20,100,165,0.24)" : "none" }}>
          <Network size={15} aria-hidden="true" />
          在数据模型工作台打开
          <ArrowRight size={14} aria-hidden="true" />
        </button>
        {!versionId && <div style={{ marginTop: 7, color: "#b45309", fontSize: 11 }}>请先在「采集」中选择一个文档版本。</div>}

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 7, marginTop: 9 }}>
          <RerunButton versionId={versionId} isAdmin={isAdmin} onCompleted={refresh} />
          <DeriveStatusSummary versionId={versionId} refreshTick={refreshTick} />
        </div>
      </section>

      <details open={false} style={{ marginBottom: 10, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8 }}>
        <summary style={{ padding: "9px 11px", color: "#334155", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>派生记录 <span style={{ color: "#94a3b8", fontWeight: 400 }}>（{strategy ? strategy : "全部策略"}）</span></summary>
        <div style={{ borderTop: "1px solid #eef2f6" }}>
          <LinkTable versionId={versionId} strategy={strategy} refreshTick={refreshTick} />
        </div>
      </details>

      <details open={showAdvanced} onToggle={event => setShowAdvanced((event.currentTarget as HTMLDetailsElement).open)} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8 }}>
        <summary style={{ padding: "9px 11px", color: "#64748b", cursor: "pointer", fontSize: 12 }}>高级治理操作</summary>
        <div style={{ padding: "0 9px 9px", borderTop: "1px solid #eef2f6" }}>
          <div style={{ marginTop: 9, padding: 8, background: "#f8fafc", borderRadius: 6 }}>
            <div style={{ marginBottom: 5, color: "#475569", fontSize: 11, fontWeight: 600 }}>策略目录</div>
            <StrategyPane selectedStrategy={strategy} onSelect={setStrategy} />
          </div>
          {isAdmin && <BatchRollbackPanel versionId={versionId} onRollbackComplete={refresh} />}
          {isAdmin && <OutboxDeadLetterPanel refreshTick={refreshTick} onRetryComplete={refresh} />}
        </div>
      </details>
    </div>
  );
}
