import React, { useState } from "react";
import IngestSubTab from "./standards/IngestSubTab";
import AnalyzeSubTab from "./standards/AnalyzeSubTab";
import DraftSubTab from "./standards/DraftSubTab";

type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive";

export default function StandardsTab() {
  const [sub, setSub] = useState<Sub>("ingest");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  return (
    <div style={{display:"flex", flexDirection:"column", height:"100%"}}>
      <div style={{display:"flex", gap:8, padding:8, borderBottom:"1px solid #eee"}}>
        {(["ingest","analyze","draft","review","publish","derive"] as Sub[]).map(k => (
          <button key={k}
            onClick={()=>setSub(k)}
            disabled={k!=="ingest" && k!=="analyze" && k!=="draft"}
            style={{padding:"4px 10px",
              background: sub===k ? "#0a7" : "transparent",
              color: sub===k ? "#fff" : "#444",
              border:"1px solid #ccc", borderRadius:4,
              opacity: (k!=="ingest" && k!=="analyze" && k!=="draft") ? 0.4 : 1,
              cursor: (k!=="ingest" && k!=="analyze" && k!=="draft") ? "not-allowed" : "pointer"}}>
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
          <DraftSubTab versionId={selectedVersionId} isAdmin={true /* TODO: real role from session */} />}
      </div>
    </div>
  );
}
