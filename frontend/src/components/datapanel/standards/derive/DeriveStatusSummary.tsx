import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import { getDeriveStatus, DerivationStatusByStrategy } from "../standardsApi";

interface Props {
  versionId: string | null;
  refreshTick: number;
}

export default function DeriveStatusSummary({versionId, refreshTick}: Props) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<DerivationStatusByStrategy>({});

  useEffect(() => {
    if (!versionId) { setStatus({}); return; }
    getDeriveStatus(versionId).then(r => setStatus(r.strategies))
      .catch(() => setStatus({}));
  }, [versionId, refreshTick]);

  return (
    <div style={{marginBottom: 12, padding: 8,
                 border: "1px solid #ddd", borderRadius: 4,
                 background: "#fafafa"}}>
      <div style={{fontSize: 12, fontWeight: 500, marginBottom: 6}}>
        {t("standards.derive.summary.title")}
      </div>
      {Object.keys(status).length === 0 && (
        <div style={{fontSize: 11, color: "#888"}}>{t("standards.derive.summary.empty")}</div>
      )}
      {Object.entries(status).map(([s, counts]) => (
        <div key={s} style={{fontSize: 11, marginBottom: 4}}>
          <div style={{fontWeight: 500}}>{s}</div>
          <div style={{display: "flex", gap: 8, marginTop: 2}}>
            <span style={{color: "#0a7"}}>{t("standards.derive.summary.count", {status: t("standards.derive.status.active"), count: formatNumber(counts.active)})}</span>
            <span style={{color: "#f80"}}>{t("standards.derive.summary.count", {status: t("standards.derive.status.stale"), count: formatNumber(counts.stale)})}</span>
            {counts.failed > 0 && (
              <span style={{color: "#c33"}}>{t("standards.derive.summary.count", {status: t("standards.derive.status.failed"), count: formatNumber(counts.failed)})}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
