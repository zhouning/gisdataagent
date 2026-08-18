import React from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../../../../i18n";
import { StdClause } from "../standardsApi";

interface Props {
  clause: StdClause | null;
  lockExpiresAt?: string | null;
  lastSavedAt?: string | null;
}

export default function ClauseMeta({clause, lockExpiresAt, lastSavedAt}: Props) {
  const { t } = useTranslation();
  if (!clause) {
    return <div style={{padding: 12, color: "#888"}}>{t("standards.draft.meta.selectClause")}</div>;
  }
  return (
    <div style={{padding: 12, fontSize: 13, lineHeight: 1.6}}>
      <h4 style={{marginTop: 0}}>{t("standards.draft.meta.title")}</h4>
      <div><b>{t("standards.draft.meta.number")}:</b> {clause.clause_no || "-"}</div>
      <div><b>{t("standards.draft.meta.heading")}:</b> {clause.heading || "-"}</div>
      <div><b>{t("standards.draft.meta.kind")}:</b> {t(`standards.draft.kinds.${clause.kind}`, {defaultValue: clause.kind})}</div>
      <div><b>{t("standards.draft.meta.path")}:</b> <code>{clause.ordinal_path}</code></div>
      <hr style={{margin: "12px 0", border: 0, borderTop: "1px solid #eee"}}/>
      {lockExpiresAt && (
        <div><b>{t("standards.draft.meta.lockExpires")}:</b> {formatDate(lockExpiresAt, {hour: "numeric", minute: "2-digit", second: "2-digit"})}</div>
      )}
      {lastSavedAt && (
        <div><b>{t("standards.draft.meta.lastSaved")}:</b> {formatDate(lastSavedAt, {dateStyle: "medium", timeStyle: "medium"})}</div>
      )}
    </div>
  );
}
