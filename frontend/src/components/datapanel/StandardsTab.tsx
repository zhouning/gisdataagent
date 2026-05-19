import React, { useState } from "react";
import IngestSubTab from "./standards/IngestSubTab";
import AnalyzeSubTab from "./standards/AnalyzeSubTab";
import DraftSubTab from "./standards/DraftSubTab";
import ReviewSubTab from "./standards/ReviewSubTab";
import PublishSubTab from "./standards/PublishSubTab";
import DeriveSubTab from "./standards/DeriveSubTab";

type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive";

interface Props {
  userRole?: string;
  username?: string;
}

export default function StandardsTab({userRole = "", username = ""}: Props) {
  const [sub, setSub] = useState<Sub>("ingest");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const isAdmin = userRole === "admin";
  const enabled: Set<Sub> = new Set([
    "ingest", "analyze", "draft", "review", "publish", "derive",
  ]);

  return (
    <div style={{display:"flex", flexDirection:"column", height:"100%"}}>
      <div style={{display:"flex", gap:8, padding:8, borderBottom:"1px solid #eee"}}>
        {(["ingest","analyze","draft","review","publish","derive"] as Sub[]).map(k => (
          <button key={k}
            onClick={()=>setSub(k)}
            disabled={!enabled.has(k)}
            style={{padding:"4px 10px",
              background: sub===k ? "#0a7" : "transparent",
              color: sub===k ? "#fff" : "#444",
              border:"1px solid #ccc", borderRadius:4,
              opacity: enabled.has(k) ? 1 : 0.4,
              cursor: enabled.has(k) ? "pointer" : "not-allowed"}}>
            {({ingest:"采集", analyze:"分析", draft:"起草",
               review:"审定", publish:"发布", derive:"派生"} as Record<Sub,string>)[k]}
          </button>
        ))}
      </div>
      <div style={{flex:1, overflow:"auto"}}>
        {sub==="ingest" &&
          <IngestSubTab onPickVersion={(vid)=>{
            setSelectedVersionId(vid);
            setSub("analyze");
          }} />}
        {sub==="analyze" &&
          <AnalyzeSubTab versionId={selectedVersionId}/>}
        {sub==="draft" &&
          <DraftSubTab versionId={selectedVersionId} isAdmin={isAdmin} />}
        {sub==="review" &&
          <ReviewSubTab versionId={selectedVersionId}
                         userRole={userRole} username={username}/>}
        {sub==="publish" &&
          <PublishSubTab
            selectedVersionId={selectedVersionId}
            onSelectVersion={setSelectedVersionId}
            userRole={userRole}
            username={username}/>}
        {sub==="derive" &&
          <DeriveSubTab
            versionId={selectedVersionId}
            userRole={userRole}/>}
      </div>
    </div>
  );
}
