import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import {
  ReviewTemplate,
  ReviewTemplateStepStatus,
  getReviewTemplate,
} from "../standardsApi";

interface Props {
  versionId: string;
  refreshKey: number;
}

const statusColor: Record<ReviewTemplateStepStatus, {
  bg: string; fg: string; border: string;
}> = {
  done: {bg: "#ecfdf5", fg: "#047857", border: "#a7f3d0"},
  active: {bg: "#eff6ff", fg: "#1d4ed8", border: "#bfdbfe"},
  blocked: {bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca"},
  pending: {bg: "#f8fafc", fg: "#64748b", border: "#e2e8f0"},
};

function Chip({label, value}: {label: string; value: React.ReactNode}) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      minHeight: 22, padding: "2px 8px", border: "1px solid #e5e7eb",
      borderRadius: 4, background: "#fff", fontSize: 12, color: "#374151",
      whiteSpace: "nowrap",
    }}>
      <span style={{color: "#6b7280"}}>{label}</span>
      <strong style={{fontWeight: 600}}>{value}</strong>
    </span>
  );
}

export default function ReviewTemplatePanel({versionId, refreshKey}: Props) {
  const { t } = useTranslation();
  const [template, setTemplate] = useState<ReviewTemplate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getReviewTemplate(versionId)
      .then(t => { if (alive) setTemplate(t); })
      .catch((e: any) => {
        if (alive) {
          setTemplate(null);
          setError(e?.message || "");
        }
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [versionId, refreshKey]);

  const stale = template !== null && template.version_id !== versionId;

  if (loading && (!template || stale)) {
    return (
      <div style={panelStyle}>
        <div style={{fontSize: 13, color: "#6b7280"}}>{t("standards.review.template.loading")}</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={panelStyle}>
        <div style={{fontSize: 13, color: "#b91c1c"}}>
          {t("standards.review.template.loadFailed", {message: error || t("errors.unknown")})}
        </div>
      </div>
    );
  }

  if (!template) {
    return null;
  }

  const {summary} = template;
  const roundStatus = (value: string | null) => value
    ? t(`standards.review.round.status.${value}`, {defaultValue: value})
    : "";
  const roundOutcome = (value: string | null) => value
    ? t(`standards.review.round.outcome.${value}`, {defaultValue: value})
    : "";
  return (
    <div style={panelStyle}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, marginBottom: 8,
      }}>
        <div style={{fontSize: 14, fontWeight: 650, color: "#111827"}}>
          {t("standards.review.template.title")}
        </div>
        <div style={{
          display: "flex", flexWrap: "wrap", justifyContent: "flex-end",
          gap: 6,
        }}>
          <Chip label={t("standards.review.template.version")} value={t(`standards.status.${template.version_status}`, {defaultValue: template.version_status})}/>
          <Chip label={t("standards.review.template.round")} value={
            summary.open_round_id
              ? t("standards.review.template.openRound", {id: summary.open_round_id.slice(0, 8)})
              : summary.latest_round_status
                ? `${roundStatus(summary.latest_round_status)} ${roundOutcome(summary.latest_round_outcome)}`
                : t("standards.review.template.none")
          }/>
          <Chip label={t("standards.review.template.reviewer")} value={summary.reviewer_user_id || t("standards.review.template.unassigned")}/>
          <Chip label={t("standards.review.template.pendingReferences")} value={formatNumber(summary.pending_refs)}/>
          <Chip label={t("standards.review.template.openComments")} value={formatNumber(summary.open_comments)}/>
        </div>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
        gap: 6,
      }}>
        {template.steps.map(step => {
          const colors = statusColor[step.status];
          return (
            <div key={step.id}
                 style={{
                   minHeight: 72, padding: 8, borderRadius: 4,
                   border: `1px solid ${colors.border}`,
                   background: colors.bg, boxSizing: "border-box",
                   display: "flex", flexDirection: "column",
                   justifyContent: "space-between", gap: 6,
                 }}>
              <div style={{
                display: "flex", alignItems: "flex-start",
                justifyContent: "space-between", gap: 6,
              }}>
                <div style={{
                  fontSize: 13, fontWeight: 650, color: "#111827",
                  lineHeight: 1.25,
                }}>
                  {step.label}
                </div>
                <span style={{
                  flex: "0 0 auto", padding: "1px 6px", borderRadius: 4,
                  background: "#fff", color: colors.fg,
                  border: `1px solid ${colors.border}`, fontSize: 11,
                  lineHeight: "18px",
                }}>
                  {t(`standards.review.template.stepStatus.${step.status}`)}
                </span>
              </div>
              <div style={{fontSize: 11, color: "#4b5563", lineHeight: 1.25}}>
                {step.role}
              </div>
            </div>
          );
        })}
      </div>
      {summary.blocking && (
        <div style={{
          marginTop: 8, padding: "6px 8px", borderRadius: 4,
          border: "1px solid #fecaca", background: "#fef2f2",
          color: "#991b1b", fontSize: 12,
        }}>
          {t("standards.review.template.blockedSummary", {
            references: formatNumber(summary.pending_refs),
            comments: formatNumber(summary.open_comments),
          })}
        </div>
      )}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  padding: 10,
  borderBottom: "1px solid #e5e7eb",
  background: "#f9fafb",
  boxSizing: "border-box",
};
