import React, { useState } from "react";
import StrategyPane from "./derive/StrategyPane";
import LinkTable from "./derive/LinkTable";
import DeriveStatusSummary from "./derive/DeriveStatusSummary";
import RerunButton from "./derive/RerunButton";

interface Props {
  versionId: string | null;
  userRole: string;
}

export default function DeriveSubTab({versionId, userRole}: Props) {
  const isAdmin = userRole === "admin";
  const [strategy, setStrategy] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

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
      </div>
    </div>
  );
}
