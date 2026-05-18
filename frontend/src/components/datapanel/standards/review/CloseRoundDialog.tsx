import React, { useEffect, useState } from "react";
import { GatingPrecheck, closeReviewPrecheck, closeReviewRound } from "../standardsApi";

interface Props {
  roundId: string;
  isReviewer: boolean;
  onClosed: () => void;
}

export default function CloseRoundDialog({roundId, isReviewer, onClosed}: Props) {
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
      alert(`关闭失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{padding: 8, borderLeft: "1px solid #eee"}}>
      <h4>关闭审定</h4>
      {pre && (
        <div style={{fontSize: 12, marginBottom: 8}}>
          <div>待审引用: {pre.pending_refs}</div>
          <div>未决评论: {pre.open_comments}</div>
          <div style={{color: pre.blocking ? "#c33" : "#0a7"}}>
            {pre.blocking ? "⛔ 阻塞中" : "✓ 通过"}
          </div>
        </div>
      )}
      {isReviewer && (
        <>
          <div style={{margin: "8px 0"}}>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "approved"}
                     onChange={() => setOutcome("approved")}/> 通过
            </label>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "rejected"}
                     onChange={() => setOutcome("rejected")}/> 驳回
            </label>
          </div>
          <button onClick={submit}
                  disabled={busy || (outcome === "approved" && !!pre?.blocking)}
                  style={{width: "100%", padding: 6, background: "#0a7",
                          color: "#fff", border: "none", borderRadius: 4}}>
            关闭 Round
          </button>
        </>
      )}
    </div>
  );
}
