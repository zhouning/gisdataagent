import React, { useEffect, useState } from "react";
import { getVersionClauses, getVersionDataElements, getVersionTerms,
         getSimilar, StdClause, StdDataElement } from "./standardsApi";

interface Props { versionId: string | null; }

export default function AnalyzeSubTab({versionId}: Props) {
  const [clauses, setClauses] = useState<StdClause[]>([]);
  const [des, setDes] = useState<StdDataElement[]>([]);
  const [terms, setTerms] = useState<any[]>([]);
  const [similar, setSimilar] = useState<any[]>([]);

  useEffect(()=>{
    if (!versionId) return;
    Promise.all([
      getVersionClauses(versionId).then(r=>setClauses(r.clauses)),
      getVersionDataElements(versionId).then(r=>setDes(r.data_elements)),
      getVersionTerms(versionId).then(r=>setTerms(r.terms)),
      getSimilar(versionId).then(r=>setSimilar(r.hits)).catch(()=>setSimilar([])),
    ]);
  }, [versionId]);

  if (!versionId) return <div style={{padding:24, color:"#888"}}>
    请在"采集"Tab 选择一个文档查看条款。</div>;

  return (
    <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, padding:12}}>
      <div>
        <h4>条款树（{clauses.length}）</h4>
        <ul style={{maxHeight:280, overflow:"auto"}}>
          {clauses.map(c=>(
            <li key={c.id}><b>{c.clause_no}</b> {c.heading}
              <div style={{color:"#666", fontSize:12, marginLeft:8}}>{c.body_md?.slice(0,80)}</div>
            </li>
          ))}
        </ul>
        <h4>术语（{terms.length}）</h4>
        <ul style={{maxHeight:120, overflow:"auto"}}>
          {terms.map((t:any)=>(<li key={t.id}>{t.term_code} — {t.name_zh}</li>))}
        </ul>
      </div>
      <div>
        <h4>数据元（{des.length}）</h4>
        <table style={{width:"100%", fontSize:13}}>
          <thead><tr><th>code</th><th>name_zh</th><th>datatype</th><th>oblig.</th></tr></thead>
          <tbody>
            {des.map(d=>(<tr key={d.id}><td>{d.code}</td><td>{d.name_zh}</td>
              <td>{d.datatype}</td><td>{d.obligation}</td></tr>))}
          </tbody>
        </table>
        <h4>相似条款（{similar.length}）</h4>
        <ul style={{maxHeight:160, overflow:"auto"}}>
          {similar.map((h:any,i:number)=>(
            <li key={i}>v={h.document_version_id.slice(0,8)} sim={h.similarity.toFixed(3)}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
