import React, { useState } from "react";
import IngestSubTab from "./standards/IngestSubTab";
import AnalyzeSubTab from "./standards/AnalyzeSubTab";
import DraftSubTab from "./standards/DraftSubTab";
import ReviewSubTab from "./standards/ReviewSubTab";
import PublishSubTab from "./standards/PublishSubTab";
import DeriveSubTab from "./standards/DeriveSubTab";
import MarketSubTab from "./standards/MarketSubTab";

type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive"
  | "market";

interface Props {
  userRole?: string;
  username?: string;
}

export default function StandardsTab({userRole = "", username = ""}: Props) {
  const [sub, setSub] = useState<Sub>("ingest");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const isAdmin = userRole === "admin";
  const enabled: Set<Sub> = new Set([
    "ingest", "analyze", "draft", "review", "publish", "derive", "market",
  ]);

  return (
    <div style={{display:"flex", flexDirection:"column", height:"100%"}}>
      <div style={{display:"flex", gap:4, padding:"7px 8px", borderBottom:"1px solid #dbe3ea", background:"#f8fafc", overflowX:"auto", flexShrink:0}}>
        {(["ingest","analyze","draft","review","publish","derive","market"] as Sub[]).map(k => (
          <button key={k}
            onClick={()=>setSub(k)}
            disabled={!enabled.has(k)}
            style={{padding:"4px 8px", fontSize:11,
              background: sub===k ? "#1464a5" : "#fff",
              color: sub===k ? "#fff" : "#444",
              border:"1px solid #cbd5e1", borderRadius:6,
              opacity: enabled.has(k) ? 1 : 0.4,
              cursor: enabled.has(k) ? "pointer" : "not-allowed",
              whiteSpace:"nowrap", flex:"0 0 auto"}}>
            {({ingest:"采集", analyze:"分析", draft:"起草",
               review:"审定", publish:"发布", derive:"派生",
               market:"市场"} as Record<Sub,string>)[k]}
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
        {sub==="market" &&
          <MarketSubTab
            selectedVersionId={selectedVersionId}
            onSelectVersion={setSelectedVersionId}/>}
      </div>
    </div>
  );
}
