import React, { useEffect, useState, useRef } from "react";
import { listDocuments, uploadDocument, listVersions,
         StdDocumentSummary } from "./standardsApi";

interface Props { onPickVersion: (vid: string)=>void; }

export default function IngestSubTab({onPickVersion}: Props) {
  const [docs, setDocs] = useState<StdDocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string|null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => listDocuments().then(r=>setDocs(r.documents)).catch(e=>setErr(String(e)));
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
    const r = await listVersions(docId);
    if (r.versions.length) onPickVersion(r.versions[0].id);
  };

  return (
    <div style={{padding:12}}>
      <div style={{display:"flex", gap:8, alignItems:"center", marginBottom:12}}>
        <input type="file" ref={fileRef} accept=".docx,.xmi,.pdf"/>
        <button onClick={onUpload} disabled={busy}
          style={{padding:"4px 10px"}}>上传</button>
        {busy && <span>处理中…</span>}
        {err && <span style={{color:"red"}}>{err}</span>}
      </div>
      <table style={{width:"100%", borderCollapse:"collapse"}}>
        <thead><tr style={{background:"#f4f4f4"}}>
          <th>编号</th><th>标题</th><th>类型</th><th>状态</th><th>操作</th>
        </tr></thead>
        <tbody>
          {docs.map(d=>(
            <tr key={d.id} style={{borderBottom:"1px solid #eee"}}>
              <td>{d.doc_code}</td><td>{d.title}</td>
              <td>{d.source_type}</td><td>{d.status}</td>
              <td><button onClick={()=>pickFirstVersion(d.id)}>查看条款</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
