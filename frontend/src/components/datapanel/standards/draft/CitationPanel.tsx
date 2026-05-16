import React, { useState } from "react";
import {
  citationSearch, citationInsert, CitationCandidate,
} from "../standardsApi";

interface Props {
  clauseId: string;
  onClose: () => void;
  onInsert: (refId: string) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  pgvector: "本库", kb: "知识库", web: "网页快照",
};

function confidenceBadge(c: number | undefined): string {
  if (c === undefined) return "⚪";
  if (c >= 0.8) return "🟢";
  if (c >= 0.6) return "🟡";
  return "🔴";
}

export default function CitationPanel({clauseId, onClose, onInsert}: Props) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<Record<string, boolean>>({
    pgvector: true, kb: true, web: false,
  });
  const [results, setResults] = useState<CitationCandidate[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const onSearch = async () => {
    setErr(null); setBusy(true);
    try {
      const enabled = Object.keys(sources).filter(k => sources[k]);
      const r = await citationSearch(clauseId, query, enabled);
      setResults(r.candidates);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onPickInsert = async (c: CitationCandidate) => {
    try {
      const r = await citationInsert(clauseId, c);
      onInsert(r.ref_id);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0, width: 360,
      background: "#fff", borderLeft: "1px solid #ccc", zIndex: 10,
      display: "flex", flexDirection: "column", color: "#222",
    }}>
      <div style={{padding: 8, borderBottom: "1px solid #ddd",
                   display: "flex", alignItems: "center", gap: 8}}>
        <strong style={{flex: 1}}>引用助手</strong>
        <button onClick={onClose}>×</button>
      </div>
      <div style={{padding: 8, borderBottom: "1px solid #eee"}}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSearch(); }}
          placeholder="搜索词、字段代码、标准号..."
          style={{width: "100%", padding: 4, marginBottom: 6,
                  border: "1px solid #ccc", borderRadius: 3}}
          disabled={busy}
          autoFocus
        />
        <div style={{display: "flex", gap: 8, fontSize: 12,
                     marginBottom: 6}}>
          {(["pgvector","kb","web"] as const).map(k => (
            <label key={k} style={{cursor: "pointer"}}>
              <input type="checkbox"
                     checked={sources[k]}
                     onChange={(e) => setSources({
                       ...sources, [k]: e.target.checked
                     })}/>
              {" "}{SOURCE_LABELS[k]}
            </label>
          ))}
        </div>
        <button onClick={onSearch} disabled={busy || !query.trim()}>
          {busy ? "搜索中..." : "搜索"}
        </button>
      </div>
      {err && <div style={{padding: 8, color: "red", fontSize: 12}}>{err}</div>}
      <div style={{flex: 1, overflow: "auto", padding: 8}}>
        {results.length === 0 && !busy && (
          <div style={{color: "#888", fontSize: 13}}>暂无结果</div>
        )}
        {results.map((c, i) => {
          const conf = c.extra?.confidence as number | undefined;
          return (
            <div key={i} style={{
              padding: 8, marginBottom: 8, border: "1px solid #eee",
              borderRadius: 4, fontSize: 13,
            }}>
              <div style={{fontSize: 11, color: "#666", marginBottom: 4}}>
                {confidenceBadge(conf)}{" "}
                {conf !== undefined ? conf.toFixed(2) : "?"}{" · "}
                <code>{c.kind}</code>
                {c.extra?.clause_no && ` · ${c.extra.clause_no}`}
                {c.extra?.code && ` · ${c.extra.code}`}
              </div>
              <div style={{whiteSpace: "pre-wrap"}}>
                {c.snippet.slice(0, 200)}{c.snippet.length > 200 ? "…" : ""}
              </div>
              <button onClick={() => onPickInsert(c)}
                      style={{marginTop: 6, fontSize: 12,
                              padding: "2px 8px"}}>
                插入
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
