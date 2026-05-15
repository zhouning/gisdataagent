import React, { useEffect, useState } from "react";
import { getVersionClauses, StdClause } from "../standardsApi";

interface Props {
  versionId: string;
  selectedId: string | null;
  onSelect: (c: StdClause) => void;
}

export default function ClauseTree({versionId, selectedId, onSelect}: Props) {
  const [items, setItems] = useState<StdClause[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getVersionClauses(versionId)
      .then(r => setItems(r.clauses))
      .catch(e => setErr(String(e)));
  }, [versionId]);

  if (err) return <div style={{padding: 12, color: "red"}}>{err}</div>;

  return (
    <div style={{padding: 8, overflow: "auto", height: "100%"}}>
      <h4 style={{marginTop: 0}}>条款（{items.length}）</h4>
      <ul style={{listStyle: "none", padding: 0, margin: 0}}>
        {items.map(c => (
          <li key={c.id}
              onClick={() => onSelect(c)}
              style={{
                padding: "6px 8px",
                cursor: "pointer",
                background: c.id === selectedId ? "#e6f7ee" : "transparent",
                borderLeft: c.id === selectedId ? "3px solid #0a7" : "3px solid transparent",
                fontSize: 13,
              }}>
            <b>{c.clause_no || "?"}</b>{" "}
            <span style={{color: "#666"}}>{c.heading || "(无标题)"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
