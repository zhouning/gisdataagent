import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { patchReferenceStatus } from "../standardsApi";

interface ReferenceRow {
  id: string;
  citation_text: string;
  verification_status: 'pending' | 'approved' | 'rejected';
  target_kind: string;
}

interface Props {
  reference: ReferenceRow;
  roundId: string;
  onUpdated: () => void;
}

export default function ReferenceAuditCard({reference, roundId, onUpdated}: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  const decide = async (status: 'approved' | 'rejected') => {
    setBusy(true);
    try {
      await patchReferenceStatus(reference.id, roundId, status);
      onUpdated();
    } catch (e: any) {
      alert(t("standards.review.references.updateFailed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  const badge = t(`standards.review.references.status.${reference.verification_status}`);

  return (
    <div style={{padding: 8, marginBottom: 6,
                  border: "1px solid #ddd", borderRadius: 4}}>
      <div style={{fontSize: 11, color: "#666"}}>
        {badge} · {reference.target_kind}
      </div>
      <div style={{fontSize: 12, margin: "4px 0"}}>
        {reference.citation_text}
      </div>
      {reference.verification_status === "pending" && (
        <div style={{display: "flex", gap: 6}}>
          <button onClick={() => decide("approved")} disabled={busy}
                  style={{flex: 1, padding: 4, background: "#0a7",
                          color: "#fff", border: "none", borderRadius: 3}}>
            {t("standards.review.references.approve")}
          </button>
          <button onClick={() => decide("rejected")} disabled={busy}
                  style={{flex: 1, padding: 4, background: "#c33",
                          color: "#fff", border: "none", borderRadius: 3}}>
            {t("standards.review.references.reject")}
          </button>
        </div>
      )}
    </div>
  );
}
