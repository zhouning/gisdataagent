import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../../../../i18n";
import { PublishedVersion, listPublishedVersions } from "../standardsApi";

interface VersionRow extends PublishedVersion {}

interface Props {
  selectedVersionId: string | null;
  onSelect: (vid: string) => void;
}

export default function VersionPickerPane({selectedVersionId, onSelect}: Props) {
  const { t } = useTranslation();
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    listPublishedVersions().then(r => {
      setVersions(r.versions);
      setErr(null);
    }).catch((e: any) => setErr(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  return (
    <div style={{padding: 8, borderInlineEnd: "1px solid #eee", overflow: "auto"}}>
      <div style={{display: "flex", justifyContent: "space-between",
                   alignItems: "center", marginBottom: 8}}>
        <h4 style={{margin: 0}}>{t("standards.publish.releasedVersions")}</h4>
        <button onClick={refresh} style={{fontSize: 11}}>{t("standards.publish.refresh")}</button>
      </div>
      {loading && <div style={{color: "#888"}}>{t("standards.publish.loading")}</div>}
      {err && <div style={{color: "#c33", fontSize: 11}}>{err}</div>}
      {!loading && versions.length === 0 && (
        <div style={{color: "#888", fontSize: 12}}>{t("standards.publish.noReleasedVersions")}</div>
      )}
      {versions.map(v => (
        <button key={v.id} onClick={() => onSelect(v.id)}
                style={{display: "block", width: "100%", textAlign: "start",
                        padding: 6, marginBottom: 4,
                        background: selectedVersionId === v.id ? "#cef" : "#f8f8f8",
                        border: "1px solid #ddd", borderRadius: 4,
                        fontSize: 12}}>
          <div>{v.version_label}</div>
          <div style={{fontSize: 11, color: "#666"}}>
            {v.released_at ? formatDate(v.released_at, {dateStyle: "medium", timeStyle: "medium"}) : "-"}
          </div>
        </button>
      ))}
    </div>
  );
}
