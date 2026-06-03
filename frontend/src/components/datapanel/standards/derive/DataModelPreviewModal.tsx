import React, { useEffect, useState } from "react";
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

const TABS: { key: TabKey; label: string }[] = [
  { key: "pdm", label: "PDM (物理层)" },
  { key: "ddl", label: "DDL" },
  { key: "ldm", label: "LDM (逻辑层)" },
  { key: "cdm", label: "CDM (概念层)" },
];

/** Wave 8 — preview the to_data_model strategy's snapshot for a version.
 * Shows three-layer JSON and copy-pasteable PostgreSQL DDL. */
export default function DataModelPreviewModal({ versionId, onClose }: Props) {
  const [payload, setPayload] = useState<DataModelPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("pdm");
  const [copyHint, setCopyHint] = useState<string>("");

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
      setCopyHint("已复制");
      setTimeout(() => setCopyHint(""), 1500);
    } catch {
      setCopyHint("复制失败");
      setTimeout(() => setCopyHint(""), 1500);
    }
  };

  const renderBody = () => {
    if (error) {
      return (
        <div style={{ padding: 16, color: "#c33", fontSize: 13 }}>
          加载失败：{error}
          <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
            提示：to_data_model 派生还未运行过这个版本时会返回 404。请先在
            派生面板点「重新派生」，再重新打开本窗口。
          </div>
        </div>
      );
    }
    if (!payload) {
      return <div style={{ padding: 16, color: "#888" }}>加载中...</div>;
    }

    if (tab === "ddl") {
      return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #eee",
                         display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={onCopyDdl} style={{ padding: "4px 12px" }}>
              复制
            </button>
            <a href={getDataModelDdlDownloadUrl(versionId)}
               style={{ padding: "4px 12px",
                        background: "#007aff", color: "#fff",
                        textDecoration: "none", borderRadius: 4 }}>
              下载 .sql
            </a>
            <a href={getDataModelXmiDownloadUrl(versionId)}
               style={{ padding: "4px 12px",
                        background: "#2f6f4e", color: "#fff",
                        textDecoration: "none", borderRadius: 4 }}>
              下载 XMI
            </a>
            {copyHint && (
              <span style={{ color: "#0a7", fontSize: 12 }}>{copyHint}</span>
            )}
          </div>
          <pre style={{ flex: 1, overflow: "auto", padding: 12, margin: 0,
                         background: "#f7f7f7", fontSize: 12,
                         fontFamily: "Menlo, Consolas, monospace",
                         whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
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
                     fontFamily: "Menlo, Consolas, monospace" }}>
        {JSON.stringify(data, null, 2)}
      </pre>
    );
  };

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
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
            <div style={{ fontSize: 14, fontWeight: 500 }}>数据模型预览</div>
            {payload && (
              <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                {payload.stats.entity_count} 实体 ·{" "}
                {payload.stats.attribute_count} 属性 ·{" "}
                {payload.stats.constraint_count} 约束 · 生成于{" "}
                {payload.generated_at?.slice(0, 19).replace("T", " ")}
                {" "}· {payload.derived_status}
              </div>
            )}
          </div>
          <button onClick={onClose}
                  style={{ background: "transparent", border: "none",
                           fontSize: 20, cursor: "pointer", color: "#666" }}>
            ×
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #eee",
                       background: "#fafafa" }}>
          {TABS.map(t => (
            <button key={t.key}
                    onClick={() => setTab(t.key)}
                    style={{
                      padding: "8px 16px", fontSize: 12,
                      border: "none", borderBottom:
                        tab === t.key ? "2px solid #007aff" : "2px solid transparent",
                      background: "transparent",
                      color: tab === t.key ? "#007aff" : "#333",
                      fontWeight: tab === t.key ? 500 : 400,
                      cursor: "pointer",
                    }}>
              {t.label}
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
