import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ReviewRound, listReviewRounds, startReviewRound } from "../standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
  onSelect: (round: ReviewRound | null) => void;
  onChanged?: () => void;
}

export default function RoundSelector({versionId, isAdmin, onSelect,
                                      onChanged}: Props) {
  const { t } = useTranslation();
  const [rounds, setRounds] = useState<ReviewRound[]>([]);
  const [reviewerInput, setReviewerInput] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    if (!versionId) return;
    listReviewRounds({version_id: versionId}).then(r => setRounds(r.rounds));
  };

  useEffect(refresh, [versionId]);

  const start = async () => {
    if (!versionId || !reviewerInput.trim()) return;
    setBusy(true);
    try {
      await startReviewRound(versionId, reviewerInput.trim());
      setReviewerInput("");
      refresh();
      onChanged?.();
    } catch (e: any) {
      alert(t("standards.review.round.startFailed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{padding: 8, borderInlineEnd: "1px solid #eee"}}>
      <h4>{t("standards.review.round.title")}</h4>
      {rounds.length === 0 && <div style={{color: "#888"}}>{t("standards.review.round.empty")}</div>}
      {rounds.map(r => (
        <button key={r.id} onClick={() => onSelect(r)}
                style={{display: "block", width: "100%", textAlign: "start",
                        padding: 6, marginBottom: 4,
                        background: r.status === "open" ? "#fffceb" : "#f0f0f0",
                        border: "1px solid #ccc", borderRadius: 4}}>
          <div style={{fontSize: 12}}>
            {t(`standards.review.round.status.${r.status}`, {defaultValue: r.status})}{" "}
            {r.outcome ? `(${t(`standards.review.round.outcome.${r.outcome}`, {defaultValue: r.outcome})})` : ""}
          </div>
          <div style={{fontSize: 11, color: "#666"}}>
            {t("standards.review.round.reviewer")}: {r.reviewer_user_id}
          </div>
        </button>
      ))}
      {isAdmin && versionId && (
        <div style={{marginTop: 12, paddingTop: 12, borderTop: "1px dashed #ccc"}}>
          <input value={reviewerInput}
                 onChange={e => setReviewerInput(e.target.value)}
                 placeholder={t("standards.review.round.reviewerPlaceholder")}
                 style={{width: "100%", padding: 4, boxSizing: "border-box"}}/>
          <button onClick={start} disabled={busy || !reviewerInput.trim()}
                  style={{marginTop: 4, width: "100%", padding: 6,
                          background: "#0a7", color: "#fff",
                          border: "none", borderRadius: 4,
                          cursor: busy ? "wait" : "pointer"}}>
            {busy ? t("standards.review.round.starting") : t("standards.review.round.start")}
          </button>
        </div>
      )}
    </div>
  );
}
