import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../../../../i18n";
import { publishVersion } from "../standardsApi";

interface Props {
  versionId: string | null;
  versionStatus: string | null;  // 'draft' | 'review' | 'approved' | 'released' | etc.
  isAdmin: boolean;
  onPublished: () => void;
  onForkClick: () => void;
}

export default function PublishActionPane({
  versionId, versionStatus, isAdmin, onPublished, onForkClick,
}: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const doPublish = async () => {
    if (!versionId) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await publishVersion(versionId);
      setMsg(t("standards.publish.publishedAt", {
        time: formatDate(r.released_at, {dateStyle: "medium", timeStyle: "medium"}),
      }));
      onPublished();
    } catch (e: any) {
      setMsg(t("standards.publish.failed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  if (!versionId) {
    return (
      <div style={{padding: 24, color: "#888"}}>
        {t("standards.publish.selectVersion")}
      </div>
    );
  }

  const canPublish = isAdmin && versionStatus === "approved";
  const canFork = isAdmin && versionStatus === "released";

  return (
    <div style={{padding: 16}}>
      <div style={{marginBottom: 12, fontSize: 13}}>
        {t("standards.publish.currentStatus")}: <span style={{
          padding: "2px 8px", borderRadius: 3,
          background: versionStatus === "released" ? "#0a7" :
                      versionStatus === "approved" ? "#fb0" : "#aaa",
          color: "#fff", fontSize: 11,
        }}>{t(`standards.status.${versionStatus}`, {defaultValue: versionStatus ?? "-"})}</span>
      </div>
      {msg && (
        <div style={{padding: 8, marginBottom: 8, fontSize: 12,
                     background: "#f5f5f5", border: "1px solid #ddd",
                     borderRadius: 3}}>
          {msg}
        </div>
      )}
      <div style={{padding: 12, marginBottom: 8,
                   border: "1px solid #ddd", borderRadius: 4}}>
        <div style={{fontSize: 13, marginBottom: 8}}>
          <strong>{t("standards.publish.publish")}</strong>: {t("standards.publish.publishDescription")}
        </div>
        <button onClick={doPublish}
                disabled={!canPublish || busy}
                title={!canPublish ? t("standards.publish.publishAdminOnly") : ""}
                style={{padding: "6px 16px",
                        background: canPublish ? "#0a7" : "#ddd",
                        color: "#fff", border: "none", borderRadius: 4,
                        cursor: canPublish ? "pointer" : "not-allowed"}}>
          {busy ? t("standards.publish.publishing") : t("standards.publish.publish")}
        </button>
      </div>
      <div style={{padding: 12, border: "1px solid #ddd",
                   borderRadius: 4}}>
        <div style={{fontSize: 13, marginBottom: 8}}>
          <strong>{t("standards.publish.forkNew")}</strong>: {t("standards.publish.forkDescription")}
        </div>
        <button onClick={onForkClick}
                disabled={!canFork}
                title={!canFork ? t("standards.publish.forkAdminOnly") : ""}
                style={{padding: "6px 16px",
                        background: canFork ? "#06c" : "#ddd",
                        color: "#fff", border: "none", borderRadius: 4,
                        cursor: canFork ? "pointer" : "not-allowed"}}>
          {t("standards.publish.fork")}
        </button>
      </div>
    </div>
  );
}
