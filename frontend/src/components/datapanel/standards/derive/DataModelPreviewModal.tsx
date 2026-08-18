import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDate, formatNumber } from "../../../../i18n";
import {
  DataModelPayload,
  getDataModel,
  getDataModelDdlDownloadUrl,
  getDataModelXmiDownloadUrl,
} from "../standardsApi";

interface Props {
  versionId: string;
  onClose: () => void;
}

type TabKey = "pdm" | "ddl" | "cdm" | "ldm";

const TABS: TabKey[] = ["pdm", "ddl", "ldm", "cdm"];

/** Wave 8 — preview the to_data_model strategy's snapshot for a version.
 * Shows three-layer JSON and copy-pasteable PostgreSQL DDL. */
export default function DataModelPreviewModal({ versionId, onClose }: Props) {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<DataModelPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("pdm");
  const [copyHint, setCopyHint] = useState<"copied" | "failed" | "">("");

  useEffect(() => {
    setError(null); setPayload(null);
    getDataModel(versionId).then(setPayload).catch(e => {
      setError(typeof e?.message === "string" ? e.message : String(e));
    });
  }, [versionId]);

  const onCopyDdl = async () => {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload.ddl_postgresql);
      setCopyHint("copied");
      setTimeout(() => setCopyHint(""), 1500);
    } catch {
      setCopyHint("failed");
      setTimeout(() => setCopyHint(""), 1500);
    }
  };

  const renderBody = () => {
    if (error) {
      return (
        <div style={{ padding: 16, color: "#c33", fontSize: 13 }}>
          {t("standards.derive.dataModel.loadFailed", {message: error})}
          <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
            {t("standards.derive.dataModel.notGeneratedHint")}
          </div>
        </div>
      );
    }
    if (!payload) {
      return <div style={{ padding: 16, color: "#888" }}>{t("standards.derive.dataModel.loading")}</div>;
    }

    if (tab === "ddl") {
      return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #eee",
                         display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={onCopyDdl} style={{ padding: "4px 12px" }}>
              {t("standards.derive.dataModel.copy")}
            </button>
            <a href={getDataModelDdlDownloadUrl(versionId)}
               style={{ padding: "4px 12px",
                        background: "#007aff", color: "#fff",
                        textDecoration: "none", borderRadius: 4 }}>
              {t("standards.derive.dataModel.downloadSql")}
            </a>
            <a href={getDataModelXmiDownloadUrl(versionId)}
               style={{ padding: "4px 12px",
                        background: "#2f6f4e", color: "#fff",
                        textDecoration: "none", borderRadius: 4 }}>
              {t("standards.derive.dataModel.downloadXmi")}
            </a>
            {copyHint && (
              <span style={{ color: copyHint === "failed" ? "#c33" : "#0a7", fontSize: 12 }}>
                {t(`standards.derive.dataModel.${copyHint}`)}
              </span>
            )}
          </div>
          <pre style={{ flex: 1, overflow: "auto", padding: 12, margin: 0,
                         background: "#f7f7f7", fontSize: 12,
                         fontFamily: "Menlo, Consolas, monospace",
                         whiteSpace: "pre-wrap", wordBreak: "break-word",
                         direction: "ltr", textAlign: "left" }}>
            {payload.ddl_postgresql}
          </pre>
        </div>
      );
    }

    const data = (payload as any)[tab];
    return (
      <pre style={{ overflow: "auto", padding: 12, margin: 0,
                     background: "#f7f7f7", fontSize: 12,
                     height: "100%",
                     fontFamily: "Menlo, Consolas, monospace",
                     direction: "ltr", textAlign: "left" }}>
        {JSON.stringify(data, null, 2)}
      </pre>
    );
  };

  return (
    <div style={{
      position: "fixed", inset: 0,
      background: "rgba(0,0,0,0.5)", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 9999,
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()}
           style={{ background: "#fff", borderRadius: 8,
                    width: "min(960px, 90vw)", height: "min(640px, 85vh)",
                    display: "flex", flexDirection: "column",
                    overflow: "hidden",
                    boxShadow: "0 10px 30px rgba(0,0,0,0.3)" }}>

        {/* Header */}
        <div style={{ padding: 12, borderBottom: "1px solid #eee",
                       display: "flex", justifyContent: "space-between",
                       alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{t("standards.derive.dataModel.title")}</div>
            {payload && (
              <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                {t("standards.derive.dataModel.stats", {
                  entities: formatNumber(payload.stats.entity_count),
                  attributes: formatNumber(payload.stats.attribute_count),
                  constraints: formatNumber(payload.stats.constraint_count),
                  generatedAt: payload.generated_at
                    ? formatDate(payload.generated_at, {dateStyle: "medium", timeStyle: "medium"})
                    : "-",
                  status: t(`standards.derive.status.${payload.derived_status}`, {defaultValue: payload.derived_status}),
                })}
              </div>
            )}
          </div>
          <button onClick={onClose} aria-label={t("standards.derive.dataModel.close")}
                  style={{ background: "transparent", border: "none",
                           fontSize: 20, cursor: "pointer", color: "#666" }}>
            ×
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #eee",
                       background: "#fafafa" }}>
          {TABS.map(tabKey => (
            <button key={tabKey}
                    onClick={() => setTab(tabKey)}
                    style={{
                      padding: "8px 16px", fontSize: 12,
                      border: "none", borderBottom:
                        tab === tabKey ? "2px solid #007aff" : "2px solid transparent",
                      background: "transparent",
                      color: tab === tabKey ? "#007aff" : "#333",
                      fontWeight: tab === tabKey ? 500 : 400,
                      cursor: "pointer",
                    }}>
              {t(`standards.derive.dataModel.tabs.${tabKey}`)}
            </button>
          ))}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: "hidden",
                       display: "flex", flexDirection: "column" }}>
          {renderBody()}
        </div>
      </div>
    </div>
  );
}
