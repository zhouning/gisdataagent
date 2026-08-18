import React, { useEffect, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { listDocuments, uploadDocument, listVersions,
         StdDocumentSummary } from "./standardsApi";

interface Props { onPickVersion: (vid: string)=>void; }

export default function IngestSubTab({onPickVersion}: Props) {
  const { t } = useTranslation();
  const [docs, setDocs] = useState<StdDocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string|null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => listDocuments()
    .then(r => { setDocs(r.documents); setErr(null); })
    .catch(e => setErr(String(e)));
  useEffect(()=>{ refresh(); }, []);

  const onUpload = async () => {
    const f = fileRef.current?.files?.[0]; if (!f) return;
    setBusy(true); setErr(null);
    try {
      await uploadDocument(f, "national");
      await refresh();
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  const pickFirstVersion = async (docId: string) => {
    try {
      const r = await listVersions(docId);
      if (r.versions.length) onPickVersion(r.versions[0].id);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div style={{padding:12}}>
      <div style={{display:"flex", gap:8, alignItems:"center", marginBottom:12}}>
        <input type="file" ref={fileRef} accept=".docx,.xmi,.pdf"/>
        <button onClick={onUpload} disabled={busy}
          style={{padding:"4px 10px"}}>{t("standards.ingest.upload")}</button>
        {busy && <span>{t("standards.ingest.processing")}</span>}
        {err && <span style={{color:"red"}}>{t("standards.ingest.error", {message: err})}</span>}
      </div>
      <table style={{width:"100%", borderCollapse:"collapse"}}>
        <thead><tr style={{background:"#f4f4f4"}}>
          <th>{t("standards.ingest.table.code")}</th><th>{t("standards.ingest.table.title")}</th><th>{t("standards.ingest.table.type")}</th><th>{t("standards.ingest.table.status")}</th><th>{t("standards.ingest.table.actions")}</th>
        </tr></thead>
        <tbody>
          {docs.map(d=>(
            <tr key={d.id} style={{borderBottom:"1px solid #eee"}}>
              <td>{d.doc_code}</td><td>{d.title}</td>
              <td>{t(`standards.ingest.sourceTypes.${d.source_type}`, {defaultValue: d.source_type})}</td>
              <td>{t(`standards.status.${d.status}`, {defaultValue: d.status})}</td>
              <td><button onClick={()=>pickFirstVersion(d.id)}>{t("standards.ingest.viewClauses")}</button></td>
            </tr>
          ))}
          {docs.length === 0 && !busy && (
            <tr><td colSpan={5} style={{padding: 16, textAlign: "center", color: "#888"}}>{t("standards.ingest.empty")}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
