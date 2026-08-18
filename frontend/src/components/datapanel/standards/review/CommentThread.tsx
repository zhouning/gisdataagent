import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import { ReviewComment, listReviewComments, postReviewComment,
         resolveReviewComment } from "../standardsApi";

interface Props {
  roundId: string;
  clauseId: string;
  isReviewer: boolean;
  onChanged?: () => void;
}

export default function CommentThread({roundId, clauseId, isReviewer,
                                      onChanged}: Props) {
  const { t } = useTranslation();
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [draft, setDraft] = useState("");
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    listReviewComments(roundId, clauseId).then(r => setComments(r.comments));
  };
  useEffect(refresh, [roundId, clauseId]);

  const post = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await postReviewComment(roundId, clauseId, draft.trim(),
                              replyTo ?? undefined);
      setDraft("");
      setReplyTo(null);
      refresh();
      onChanged?.();
    } catch (e: any) {
      alert(t("standards.review.comments.postFailed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (id: string,
                         resolution: 'accepted' | 'rejected' | 'duplicate') => {
    try {
      await resolveReviewComment(id, resolution);
      refresh();
      onChanged?.();
    } catch (e: any) {
      alert(t("standards.review.comments.resolveFailed", {message: e.message}));
    }
  };

  return (
    <div style={{padding: 8}}>
      <h4>{t("standards.review.comments.title", {
        count: formatNumber(comments.filter(c => c.resolution === "open").length),
      })}</h4>
      {comments.map(c => (
        <div key={c.id}
             style={{padding: 6, marginBottom: 4,
                      marginInlineStart: c.parent_comment_id ? 16 : 0,
                      background: c.resolution === "open" ? "#fff8e8" : "#f5f5f5",
                      border: "1px solid #ddd", borderRadius: 4}}>
          <div style={{fontSize: 11, color: "#666"}}>
            {c.author_user_id} · {t(`standards.review.comments.resolution.${c.resolution}`, {defaultValue: c.resolution})}
          </div>
          <div style={{fontSize: 12, whiteSpace: "pre-wrap"}}>{c.body_md}</div>
          {isReviewer && c.resolution === "open" && (
            <div style={{display: "flex", gap: 4, marginTop: 4}}>
              <button onClick={() => resolve(c.id, "accepted")}
                      style={{fontSize: 11}}>{t("standards.review.comments.accept")}</button>
              <button onClick={() => resolve(c.id, "rejected")}
                      style={{fontSize: 11}}>{t("standards.review.comments.reject")}</button>
              <button onClick={() => resolve(c.id, "duplicate")}
                      style={{fontSize: 11}}>{t("standards.review.comments.duplicate")}</button>
              <button onClick={() => setReplyTo(c.id)}
                      style={{fontSize: 11}}>{t("standards.review.comments.reply")}</button>
            </div>
          )}
        </div>
      ))}
      {isReviewer && (
        <div style={{marginTop: 8}}>
          {replyTo && (
            <div style={{fontSize: 11, color: "#666"}}>
              {t("standards.review.comments.replyingTo", {id: replyTo.slice(0, 8)})}{" "}
              <button onClick={() => setReplyTo(null)}>{t("standards.review.comments.cancel")}</button>
            </div>
          )}
          <textarea value={draft} onChange={e => setDraft(e.target.value)}
                    placeholder={t("standards.review.comments.placeholder")}
                    rows={3} style={{width: "100%", boxSizing: "border-box"}}/>
          <button onClick={post} disabled={busy || !draft.trim()}
                  style={{padding: 6, background: "#0a7", color: "#fff",
                          border: "none", borderRadius: 4}}>
            {busy ? t("standards.review.comments.posting") : t("standards.review.comments.post")}
          </button>
        </div>
      )}
    </div>
  );
}
