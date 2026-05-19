import React, { useEffect, useState } from "react";
import { Strategy, listDeriveStrategies } from "../standardsApi";

interface Props {
  selectedStrategy: string | null;
  onSelect: (name: string) => void;
}

export default function StrategyPane({selectedStrategy, onSelect}: Props) {
  const [strategies, setStrategies] = useState<Strategy[]>([]);

  useEffect(() => {
    listDeriveStrategies().then(r => setStrategies(r.strategies))
      .catch(() => setStrategies([]));
  }, []);

  return (
    <div style={{padding: 8, borderRight: "1px solid #eee", overflow: "auto"}}>
      <h4>派生 Strategy</h4>
      {strategies.map(s => (
        <button key={s.name}
                onClick={() => s.status === "active" && onSelect(s.name)}
                disabled={s.status !== "active"}
                style={{display: "block", width: "100%", textAlign: "left",
                        padding: 6, marginBottom: 4,
                        background: selectedStrategy === s.name ? "#cef" :
                                    s.status === "active" ? "#fff" : "#f0f0f0",
                        border: "1px solid #ddd", borderRadius: 4,
                        cursor: s.status === "active" ? "pointer" : "not-allowed",
                        opacity: s.status === "active" ? 1 : 0.5}}>
          <div style={{fontSize: 12, fontWeight: 500}}>
            {s.status === "active" ? "✓" : "🔒"} {s.name}
          </div>
          <div style={{fontSize: 11, color: "#666", marginTop: 2}}>
            {s.description}
          </div>
        </button>
      ))}
    </div>
  );
}
