import React, { useEffect, useRef, useState } from "react";
import { ChevronRight, FileText, RefreshCw, Upload } from "lucide-react";
import { listDocuments, uploadDocument, listVersions, StdDocumentSummary } from "./standardsApi";

interface Props { onPickVersion: (vid: string) => void; }

/** Standards entry point. The same version picker is used for documents and
 * structure-only customer model candidates, so the action is deliberately
 * named "选择版本" rather than the old, misleading "查看条款". */
export default function IngestSubTab({ onPickVersion }: Props) {
  const [docs, setDocs] = useState<StdDocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    setLoading(true);
    setErr(null);
    listDocuments()
      .then(result => setDocs(result.documents))
      .catch(error => setErr(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { refresh(); }, []);

  const onUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      await uploadDocument(file, "national");
      await refresh();
      if (fileRef.current) fileRef.current.value = "";
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const pickFirstVersion = async (document: StdDocumentSummary) => {
    setErr(null);
    try {
      const result = await listVersions(document.id);
      if (result.versions.length) {
        onPickVersion(result.versions[0].id);
      } else {
        setErr(`${document.doc_code} 尚未创建版本`);
      }
    } catch (error) {
      setErr(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div style={{ padding: 12, minHeight: "100%", background: "#f8fafc", color: "#17212b" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 15, fontWeight: 650 }}>
            <FileText size={17} color="#1464a5" />
            标准文档与候选模型
          </div>
          <div style={{ marginTop: 4, color: "#64748b", fontSize: 12, lineHeight: 1.45 }}>
            选择一个文档版本后，可在「派生」中查看数据模型和关系。
          </div>
        </div>
        <button onClick={refresh} disabled={loading || busy} title="刷新文档列表" aria-label="刷新文档列表" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 30, border: "1px solid #cbd5e1", borderRadius: 6, background: "#fff", color: "#475569", cursor: loading || busy ? "not-allowed" : "pointer" }}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
        </button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, padding: 10, marginBottom: 12, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8 }}>
        <input type="file" ref={fileRef} accept=".docx,.xmi,.pdf" style={{ flex: "1 1 180px", minWidth: 0, color: "#475569", fontSize: 12 }} />
        <button onClick={onUpload} disabled={busy} style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 11px", border: "none", borderRadius: 6, background: busy ? "#94a3b8" : "#1464a5", color: "#fff", fontSize: 12, cursor: busy ? "not-allowed" : "pointer", whiteSpace: "nowrap" }}>
          <Upload size={13} />
          {busy ? "上传中…" : "上传文档"}
        </button>
      </div>

      {err && <div role="alert" style={{ marginBottom: 10, padding: "8px 10px", border: "1px solid #fecaca", borderRadius: 6, background: "#fff1f2", color: "#b42318", fontSize: 12 }}>{err}</div>}

      <div style={{ display: "grid", gap: 8 }}>
        {loading && <div style={{ padding: 24, textAlign: "center", color: "#64748b", fontSize: 12 }}>正在读取标准文档…</div>}
        {!loading && docs.map(document => {
          const isCandidate = document.doc_code === "DMT-GIS-DATA-MODEL" || document.source_type === "draft";
          return (
            <article key={document.id} style={{ padding: 11, background: "#fff", border: isCandidate ? "1px solid #b8d8f2" : "1px solid #e2e8f0", borderRadius: 8, boxShadow: isCandidate ? "0 2px 8px rgba(20,100,165,0.08)" : "none" }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <strong style={{ color: "#17212b", fontSize: 13 }}>{document.title}</strong>
                    {isCandidate && <span style={{ padding: "2px 5px", borderRadius: 4, background: "#fff4d6", color: "#8a5a15", fontSize: 10 }}>候选模型</span>}
                  </div>
                  <div style={{ marginTop: 5, color: "#64748b", fontFamily: "Menlo, Consolas, monospace", fontSize: 10, overflowWrap: "anywhere" }}>{document.doc_code}</div>
                  <div style={{ marginTop: 5, color: "#94a3b8", fontSize: 11 }}>{document.source_type} · {document.status}</div>
                </div>
                <button onClick={() => pickFirstVersion(document)} style={{ display: "inline-flex", alignItems: "center", gap: 3, flex: "0 0 auto", padding: "6px 8px", border: "1px solid #b8d8f2", borderRadius: 6, background: "#f4f9fe", color: "#1464a5", fontSize: 11, cursor: "pointer", whiteSpace: "nowrap" }}>
                  选择版本 <ChevronRight size={13} />
                </button>
              </div>
            </article>
          );
        })}
        {!loading && docs.length === 0 && <div style={{ padding: 28, textAlign: "center", color: "#64748b", background: "#fff", border: "1px dashed #cbd5e1", borderRadius: 8, fontSize: 12 }}>暂无标准文档</div>}
      </div>
    </div>
  );
}
