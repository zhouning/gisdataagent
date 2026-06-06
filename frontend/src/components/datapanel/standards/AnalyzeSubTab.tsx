import React, { useEffect, useMemo, useState } from "react";
import {
  getSimilar,
  getVersionClauses,
  getVersionDataElements,
  getVersionImpactGraph,
  getVersionTerms,
  ImpactGraphEdge,
  ImpactGraphResult,
  StdClause,
  StdDataElement,
} from "./standardsApi";

interface Props { versionId: string | null; }

const edgeTypeLabel = (edgeType: string) => {
  if (edgeType === "derives") return "派生";
  if (edgeType === "references") return "引用";
  if (edgeType === "similar_clause") return "相似条款";
  return edgeType;
};

const shortId = (value?: string | null) => value ? value.slice(0, 8) : "-";
const compactText = (value: string, max = 96) =>
  value.length > max ? `${value.slice(0, max)}...` : value;

const similarKey = (hit: any, index: number) =>
  `${hit.source_clause_id ?? index}:${hit.target_clause_id ?? ""}:` +
  `${hit.document_version_id ?? ""}`;

export default function AnalyzeSubTab({versionId}: Props) {
  const [clauses, setClauses] = useState<StdClause[]>([]);
  const [des, setDes] = useState<StdDataElement[]>([]);
  const [terms, setTerms] = useState<any[]>([]);
  const [similar, setSimilar] = useState<any[]>([]);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [impactGraph, setImpactGraph] = useState<ImpactGraphResult | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState<string | null>(null);

  useEffect(()=>{
    let cancelled = false;
    if (!versionId) {
      setClauses([]);
      setDes([]);
      setTerms([]);
      setSimilar([]);
      setAnalysisLoading(false);
      setAnalysisError(null);
      return () => { cancelled = true; };
    }

    setClauses([]);
    setDes([]);
    setTerms([]);
    setSimilar([]);
    setAnalysisLoading(true);
    setAnalysisError(null);
    Promise.all([
      getVersionClauses(versionId).then(r=>r.clauses),
      getVersionDataElements(versionId).then(r=>r.data_elements),
      getVersionTerms(versionId).then(r=>r.terms),
      getSimilar(versionId).then(r=>r.hits).catch(()=>[]),
    ])
      .then(([nextClauses, nextDataElements, nextTerms, nextSimilar]) => {
        if (cancelled) return;
        setClauses(nextClauses);
        setDes(nextDataElements);
        setTerms(nextTerms);
        setSimilar(nextSimilar);
        setAnalysisLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        setClauses([]);
        setDes([]);
        setTerms([]);
        setSimilar([]);
        setAnalysisLoading(false);
        setAnalysisError(err instanceof Error ? err.message : String(err));
      });

    return () => { cancelled = true; };
  }, [versionId]);

  useEffect(()=>{
    let cancelled = false;
    if (!versionId) {
      setImpactGraph(null);
      setImpactError(null);
      setImpactLoading(false);
      return () => { cancelled = true; };
    }

    setImpactLoading(true);
    setImpactError(null);
    getVersionImpactGraph(versionId)
      .then(result => {
        if (!cancelled) setImpactGraph(result);
      })
      .catch(err => {
        if (!cancelled) {
          setImpactGraph(null);
          setImpactError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setImpactLoading(false);
      });

    return () => { cancelled = true; };
  }, [versionId]);

  const nodeLabels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const node of impactGraph?.nodes ?? []) {
      labels.set(node.id, node.label || node.id);
    }
    return labels;
  }, [impactGraph]);

  const edgesByType = useMemo(() => {
    const grouped: Record<string, ImpactGraphEdge[]> = {};
    for (const edge of impactGraph?.edges ?? []) {
      if (!grouped[edge.edge_type]) grouped[edge.edge_type] = [];
      grouped[edge.edge_type].push(edge);
    }
    return grouped;
  }, [impactGraph]);

  if (!versionId) return <div style={{padding:24, color:"#888"}}>
    请在"采集"Tab 选择一个文档查看条款。
  </div>;

  const summary = impactGraph?.summary;
  const byType = summary?.by_edge_type ?? {};

  return (
    <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, padding:12}}>
      {analysisLoading && (
        <div style={{gridColumn:"1 / -1", color:"#666", fontSize:13}}>
          分析数据加载中...
        </div>
      )}
      {analysisError && (
        <div role="alert" style={{gridColumn:"1 / -1", color:"#b00020", fontSize:13}}>
          分析数据加载失败: {analysisError}
        </div>
      )}
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
            <li key={similarKey(h, i)}>
              v={shortId(h.document_version_id)} sim={Number(h.similarity).toFixed(3)}
            </li>
          ))}
        </ul>
      </div>

      <div style={{gridColumn:"1 / -1", borderTop:"1px solid #ddd", paddingTop:10}}>
        <h4 style={{marginBottom:8}}>跨标准影响图谱</h4>
        {impactLoading && <div style={{color:"#666", fontSize:13}}>影响图谱加载中...</div>}
        {impactError && <div style={{color:"#b00020", fontSize:13}}>影响图谱加载失败: {impactError}</div>}
        {!impactLoading && !impactError && (
          <>
            <div style={{display:"flex", gap:8, flexWrap:"wrap", marginBottom:8, fontSize:13}}>
              <span>节点: <b>{summary?.node_count ?? 0}</b></span>
              <span>边: <b>{summary?.edge_count ?? 0}</b></span>
              <span>跨版本: <b>{summary?.cross_version_edge_count ?? 0}</b></span>
              <span>派生: <b>{byType.derives ?? 0}</b></span>
              <span>引用: <b>{byType.references ?? 0}</b></span>
              <span>相似: <b>{byType.similar_clause ?? 0}</b></span>
            </div>
            <div style={{maxHeight:220, overflow:"auto", border:"1px solid #e0e0e0", padding:8}}>
              {(impactGraph?.edges.length ?? 0) === 0 && (
                <div style={{color:"#888", fontSize:13}}>暂无影响关系</div>
              )}
              {Object.entries(edgesByType).map(([edgeType, edges]) => (
                <div key={edgeType} style={{marginBottom:10}}>
                  <div style={{fontSize:12, color:"#666", fontWeight:600, marginBottom:4}}>
                    {edgeTypeLabel(edgeType)} ({edges.length})
                  </div>
                  {edges.map(edge => {
                    const sourceLabel = nodeLabels.get(edge.source) ?? edge.source;
                    const targetLabel = nodeLabels.get(edge.target) ?? edge.target;
                    return (
                      <div
                        key={edge.id}
                        title={`${sourceLabel} -> ${targetLabel}`}
                        style={{
                          fontSize:12, padding:"3px 0", borderTop:"1px solid #f0f0f0",
                          lineHeight:1.35, overflowWrap:"anywhere",
                        }}>
                        <b>{edgeTypeLabel(edge.edge_type)}</b>{" "}
                        {compactText(sourceLabel)} {"->"} {compactText(targetLabel)}
                        {edge.status ? <span style={{color:"#666"}}> [{edge.status}]</span> : null}
                        {typeof edge.score === "number" ? <span style={{color:"#666"}}> score={edge.score.toFixed(3)}</span> : null}
                        {edge.metadata?.cross_version ? <span style={{color:"#666"}}> 跨版本</span> : null}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
