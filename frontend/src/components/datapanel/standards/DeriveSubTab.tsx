import React, { useState } from "react";
import StrategyPane from "./derive/StrategyPane";
import LinkTable from "./derive/LinkTable";
import DeriveStatusSummary from "./derive/DeriveStatusSummary";
import RerunButton from "./derive/RerunButton";
import DataModelPreviewModal from "./derive/DataModelPreviewModal";
import BatchRollbackPanel from "./derive/BatchRollbackPanel";
import OutboxDeadLetterPanel from "./derive/OutboxDeadLetterPanel";

interface Props {
  versionId: string | null;
  userRole: string;
}

export default function DeriveSubTab({versionId, userRole}: Props) {
  const isAdmin = userRole === "admin";
  const [strategy, setStrategy] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [dataModelOpen, setDataModelOpen] = useState(false);

  return (
    <div style={{display: "grid", gridTemplateColumns: "20% 60% 20%",
                 height: "100%"}}>
      <StrategyPane
        selectedStrategy={strategy}
        onSelect={setStrategy}
      />
      <LinkTable
        versionId={versionId}
        strategy={strategy}
        refreshTick={refreshTick}
      />
      <div style={{padding: 8, borderLeft: "1px solid #eee"}}>
        <DeriveStatusSummary
          versionId={versionId}
          refreshTick={refreshTick}
        />
        <RerunButton
          versionId={versionId}
          isAdmin={isAdmin}
          onCompleted={() => setRefreshTick(t => t + 1)}
        />
        {isAdmin && (
          <BatchRollbackPanel
            versionId={versionId}
            onRollbackComplete={() => setRefreshTick(t => t + 1)}
          />
        )}
        {isAdmin && (
          <OutboxDeadLetterPanel
            refreshTick={refreshTick}
            onRetryComplete={() => setRefreshTick(t => t + 1)}
          />
        )}
        {versionId && (
          <button
            onClick={() => setDataModelOpen(true)}
            style={{
              marginTop: 8, padding: "6px 10px", fontSize: 12,
              width: "100%", background: "#fff",
              border: "1px solid #007aff", color: "#007aff",
              borderRadius: 4, cursor: "pointer",
            }}>
            📐 查看数据模型 (CDM/LDM/PDM/DDL)
          </button>
        )}
        {dataModelOpen && versionId && (
          <DataModelPreviewModal
            versionId={versionId}
            onClose={() => setDataModelOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
