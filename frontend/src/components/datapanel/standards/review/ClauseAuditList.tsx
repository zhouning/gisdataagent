import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { StdClause, getVersionClauses } from "../standardsApi";

interface Props {
  versionId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function ClauseAuditList({versionId, selectedId, onSelect}: Props) {
  const { t } = useTranslation();
  const [clauses, setClauses] = useState<StdClause[]>([]);

  useEffect(() => {
    getVersionClauses(versionId).then(r => setClauses(r.clauses));
  }, [versionId]);

  return (
    <div style={{padding: 8, borderInlineEnd: "1px solid #eee", overflow: "auto"}}>
      <h4>{t("standards.review.clauses")}</h4>
      {clauses.map(c => (
        <button key={c.id} onClick={() => onSelect(c.id)}
                style={{display: "block", width: "100%", textAlign: "start",
                        padding: 6, marginBottom: 2,
                        background: selectedId === c.id ? "#cef" : "transparent",
                        border: "1px solid #ddd", borderRadius: 4,
                        fontSize: 12}}>
          {c.clause_no || c.ordinal_path} {c.heading || ""}
        </button>
      ))}
    </div>
  );
}
