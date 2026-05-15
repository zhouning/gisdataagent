import React, { useState } from "react";
import ClauseTree from "./draft/ClauseTree";
import ClauseEditor from "./draft/ClauseEditor";
import ClauseMeta from "./draft/ClauseMeta";
import { StdClause } from "./standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
}

export default function DraftSubTab({versionId, isAdmin}: Props) {
  const [selected, setSelected] = useState<StdClause | null>(null);
  const [lockExp, setLockExp] = useState<string | null>(null);
  const [lastSaved, setLastSaved] = useState<string | null>(null);

  if (!versionId) {
    return <div style={{padding: 24, color: "#888"}}>
      请先在「分析」选择一个文档版本
    </div>;
  }

  return (
    <div style={{display: "grid",
                 gridTemplateColumns: "25% 50% 25%",
                 height: "100%"}}>
      <div style={{borderRight: "1px solid #eee"}}>
        <ClauseTree versionId={versionId}
                    selectedId={selected?.id ?? null}
                    onSelect={setSelected}/>
      </div>
      <div style={{borderRight: "1px solid #eee"}}>
        <ClauseEditor clause={selected}
                      isAdmin={isAdmin}
                      onLockChange={setLockExp}
                      onSaved={setLastSaved}/>
      </div>
      <div>
        <ClauseMeta clause={selected}
                    lockExpiresAt={lockExp}
                    lastSavedAt={lastSaved}/>
      </div>
    </div>
  );
}
