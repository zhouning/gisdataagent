import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import { GatingPrecheck, closeReviewPrecheck, closeReviewRound } from "../standardsApi";

interface Props {
  roundId: string;
  isReviewer: boolean;
  onClosed: () => void;
}

export default function CloseRoundDialog({roundId, isReviewer, onClosed}: Props) {
  const { t } = useTranslation();
  const [pre, setPre] = useState<GatingPrecheck | null>(null);
  const [outcome, setOutcome] = useState<'approved' | 'rejected'>("approved");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    closeReviewPrecheck(roundId).then(setPre).catch(() => setPre(null));
  }, [roundId]);

  const submit = async () => {
    setBusy(true);
    try {
      await closeReviewRound(roundId, outcome);
      onClosed();
    } catch (e: any) {
      alert(t("standards.review.close.failed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{padding: 8, borderInlineStart: "1px solid #eee"}}>
      <h4>{t("standards.review.close.title")}</h4>
      {pre && (
        <div style={{fontSize: 12, marginBottom: 8}}>
          <div>{t("standards.review.close.pendingReferences")}: {formatNumber(pre.pending_refs)}</div>
          <div>{t("standards.review.close.openComments")}: {formatNumber(pre.open_comments)}</div>
          <div style={{color: pre.blocking ? "#c33" : "#0a7"}}>
            {pre.blocking ? t("standards.review.close.blocked") : t("standards.review.close.passed")}
          </div>
        </div>
      )}
      {isReviewer && (
        <>
          <div style={{margin: "8px 0"}}>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "approved"}
                     onChange={() => setOutcome("approved")}/> {t("standards.review.close.approved")}
            </label>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "rejected"}
                     onChange={() => setOutcome("rejected")}/> {t("standards.review.close.rejected")}
            </label>
          </div>
          <button onClick={submit}
                  disabled={busy || (outcome === "approved" && !!pre?.blocking)}
                  style={{width: "100%", padding: 6, background: "#0a7",
                          color: "#fff", border: "none", borderRadius: 4}}>
            {busy ? t("standards.review.close.closing") : t("standards.review.close.closeRound")}
          </button>
        </>
      )}
    </div>
  );
}
