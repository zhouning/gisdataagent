import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Strategy, listDeriveStrategies } from "../standardsApi";

interface Props {
  selectedStrategy: string | null;
  onSelect: (name: string) => void;
}

export default function StrategyPane({selectedStrategy, onSelect}: Props) {
  const { t } = useTranslation();
  const [strategies, setStrategies] = useState<Strategy[]>([]);

  useEffect(() => {
    listDeriveStrategies().then(r => setStrategies(r.strategies))
      .catch(() => setStrategies([]));
  }, []);

  return (
    <div style={{padding: 8, borderInlineEnd: "1px solid #eee", overflow: "auto"}}>
      <h4>{t("standards.derive.strategy.title")}</h4>
      {strategies.map(s => (
        <button key={s.name}
                onClick={() => s.status === "active" && onSelect(s.name)}
                disabled={s.status !== "active"}
                style={{display: "block", width: "100%", textAlign: "start",
                        padding: 6, marginBottom: 4,
                        background: selectedStrategy === s.name ? "#cef" :
                                    s.status === "active" ? "#fff" : "#f0f0f0",
                        border: "1px solid #ddd", borderRadius: 4,
                        cursor: s.status === "active" ? "pointer" : "not-allowed",
                        opacity: s.status === "active" ? 1 : 0.5}}>
          <div style={{fontSize: 12, fontWeight: 500}}>
            {s.name} · {t(`standards.derive.strategy.status.${s.status}`)}
          </div>
          <div style={{fontSize: 11, color: "#666", marginTop: 2}}>
            {s.description}
          </div>
        </button>
      ))}
    </div>
  );
}
