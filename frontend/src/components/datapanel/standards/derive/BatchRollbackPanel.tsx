import React, { useMemo, useState } from "react";
import { Plus, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import {
  rollbackDerivationsBatch,
  BatchRollbackResult,
} from "../standardsApi";

interface Props {
  versionId: string | null;
  onRollbackComplete: () => void;
}

const MAX_BATCH_ROLLBACK_IDS = 50;

const parseIds = (value: string) => Array.from(new Set(
  value.split(/[\s,;]+/).map(v => v.trim()).filter(Boolean),
));

const messageOf = (value: unknown) =>
  value instanceof Error ? value.message : String(value);

export default function BatchRollbackPanel({
  versionId,
  onRollbackComplete,
}: Props) {
  const { t } = useTranslation();
  const [idsText, setIdsText] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchRollbackResult | null>(null);

  const versionIds = useMemo(() => parseIds(idsText), [idsText]);
  const tooManyIds = versionIds.length > MAX_BATCH_ROLLBACK_IDS;

  const summarizeStrategies = (item: BatchRollbackResult["rolled_back"][number]) => {
    const entries = Object.entries(item.by_strategy);
    if (entries.length === 0) {
      return t(`standards.derive.rollback.status.${item.status}`, {defaultValue: item.status});
    }
    return entries
      .map(([strategy, summary]) => t("standards.derive.rollback.strategySummary", {
        strategy,
        links: formatNumber(summary.links_marked),
        downstream: formatNumber(summary.downstream_marked),
      }))
      .join("; ");
  };

  const addCurrent = () => {
    if (!versionId) return;
    const next = Array.from(new Set([...versionIds, versionId]));
    setIdsText(next.join("\n"));
    setError(null);
  };

  const rollback = async () => {
    if (versionIds.length === 0 || tooManyIds) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await rollbackDerivationsBatch(
        versionIds,
        reason.trim() || undefined,
      );
      setResult(r);
      onRollbackComplete();
    } catch (e) {
      setError(t("standards.derive.rollback.failed", {message: messageOf(e)}));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{
      marginTop: 12, padding: 8, border: "1px solid #ddd",
      borderRadius: 4, background: "#fafafa", fontSize: 11,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        gap: 8, alignItems: "center", marginBottom: 6,
      }}>
        <div style={{fontSize: 12, fontWeight: 500}}>{t("standards.derive.rollback.title")}</div>
        <button
          type="button"
          onClick={addCurrent}
          disabled={!versionId || busy}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: 11, padding: "3px 7px", border: "1px solid #ccc",
            borderRadius: 3, background: "#fff",
            color: !versionId || busy ? "#888" : "#222",
            cursor: !versionId || busy ? "not-allowed" : "pointer",
            whiteSpace: "nowrap",
          }}>
          <Plus size={12} aria-hidden="true" />
          {t("standards.derive.rollback.addCurrent")}
        </button>
      </div>

      <textarea
        value={idsText}
        onChange={e => setIdsText(e.currentTarget.value)}
        placeholder={t("standards.derive.rollback.idsPlaceholder")}
        rows={4}
        disabled={busy}
        style={{
          width: "100%", boxSizing: "border-box", fontSize: 11,
          padding: 6, border: "1px solid #ccc", borderRadius: 3,
          resize: "vertical", minHeight: 74,
        }}
      />
      <input
        value={reason}
        onChange={e => setReason(e.currentTarget.value)}
        placeholder={t("standards.derive.rollback.reasonPlaceholder")}
        disabled={busy}
        style={{
          width: "100%", boxSizing: "border-box", marginTop: 6,
          fontSize: 11, padding: 5, border: "1px solid #ccc",
          borderRadius: 3,
        }}
      />
      {tooManyIds && (
        <div
          role="status"
          style={{
            marginTop: 6, color: "#a33", lineHeight: 1.35,
            overflowWrap: "anywhere",
          }}>
          {t("standards.derive.rollback.tooMany", {
            max: formatNumber(MAX_BATCH_ROLLBACK_IDS),
            count: formatNumber(versionIds.length),
          })}
        </div>
      )}
      <button
        type="button"
        onClick={rollback}
        disabled={busy || versionIds.length === 0 || tooManyIds}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: 5, width: "100%", marginTop: 6, padding: "5px 8px",
          fontSize: 11, border: "none", borderRadius: 4,
          background: versionIds.length > 0 && !tooManyIds ? "#b42318" : "#ddd",
          color: "#fff",
          cursor: busy || versionIds.length === 0 || tooManyIds
            ? "not-allowed" : "pointer",
        }}>
        <RotateCcw size={12} aria-hidden="true" />
        {busy
          ? t("standards.derive.rollback.running")
          : t("standards.derive.rollback.action", {count: formatNumber(versionIds.length)})}
      </button>

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 6, color: "#c33", lineHeight: 1.35,
            overflowWrap: "anywhere",
          }}>
          {error}
        </div>
      )}
      {result && (
        <div role="status" style={{marginTop: 8}}>
          <div style={{color: "#075", marginBottom: 4}}>
            {t("standards.derive.rollback.result", {
              rolledBack: formatNumber(result.rolled_back.length),
              skipped: formatNumber(result.skipped.length),
            })}
          </div>
          <div style={{
            maxHeight: 180, overflow: "auto", borderTop: "1px solid #e6e6e6",
          }}>
            {result.rolled_back.map(item => (
              <div
                key={`ok-${item.version_id}`}
                style={{padding: "5px 0", borderBottom: "1px solid #eee"}}>
                <div style={{fontFamily: "monospace", overflowWrap: "anywhere"}}>
                  {item.version_id}
                </div>
                <div style={{color: item.status === "rolled_back" ? "#075" : "#777"}}>
                  {summarizeStrategies(item)}
                </div>
              </div>
            ))}
            {result.skipped.map(item => (
              <div
                key={`skip-${item.version_id}`}
                style={{padding: "5px 0", borderBottom: "1px solid #eee"}}>
                <div style={{fontFamily: "monospace", overflowWrap: "anywhere"}}>
                  {item.version_id}
                </div>
                <div style={{color: "#a33"}}>{item.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
