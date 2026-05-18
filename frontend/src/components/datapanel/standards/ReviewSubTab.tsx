import React, { useEffect, useState } from "react";
import { ReviewRound } from "./standardsApi";
import RoundSelector from "./review/RoundSelector";
import ClauseAuditList from "./review/ClauseAuditList";
import ReferenceAuditCard from "./review/ReferenceAuditCard";
import CommentThread from "./review/CommentThread";
import CloseRoundDialog from "./review/CloseRoundDialog";

interface Props {
  versionId: string | null;
  userRole: string;
  username: string;
}

interface ReferenceRow {
  id: string;
  citation_text: string;
  verification_status: 'pending' | 'approved' | 'rejected';
  target_kind: string;
}

export default function ReviewSubTab({versionId, userRole, username}: Props) {
  const [round, setRound] = useState<ReviewRound | null>(null);
  const [clauseId, setClauseId] = useState<string | null>(null);
  const [refs, setRefs] = useState<ReferenceRow[]>([]);
  const [refsTick, setRefsTick] = useState(0);

  const isAdmin = userRole === "admin";
  const isReviewer = round !== null && (
    userRole === "admin" || round.reviewer_user_id === username
  );

  useEffect(() => {
    if (!round || !clauseId) { setRefs([]); return; }
    fetch(`/api/std/clauses/${clauseId}/references`)
      .then(r => r.ok ? r.json() : {references: []})
      .then(j => setRefs(j.references || []))
      .catch(() => setRefs([]));
  }, [round, clauseId, refsTick]);

  if (!versionId) {
    return <div style={{padding: 24, color: "#888"}}>
      请先在「分析」选择一个文档版本
    </div>;
  }

  const pendingCount = refs.filter(r => r.verification_status === "pending").length;

  return (
    <div style={{display: "grid",
                  gridTemplateColumns: "20% 25% 35% 20%",
                  height: "100%"}}>
      <RoundSelector versionId={versionId} isAdmin={isAdmin}
                     onSelect={setRound}/>
      {round ? (
        <>
          <ClauseAuditList versionId={versionId}
                            selectedId={clauseId}
                            onSelect={setClauseId}/>
          <div style={{padding: 8, overflow: "auto"}}>
            {clauseId && (
              <>
                <h4>引用 ({pendingCount} 待审)</h4>
                {refs.length === 0 && <div style={{color:"#888"}}>无引用</div>}
                {refs.map(r => (
                  <ReferenceAuditCard
                    key={r.id} reference={r} roundId={round.id}
                    onUpdated={() => setRefsTick(t => t + 1)}/>
                ))}
                <CommentThread roundId={round.id} clauseId={clauseId}
                               isReviewer={isReviewer}/>
              </>
            )}
          </div>
          <CloseRoundDialog roundId={round.id} isReviewer={isReviewer}
                            onClosed={() => setRound(null)}/>
        </>
      ) : (
        <div style={{gridColumn: "2 / 5", padding: 24, color: "#888"}}>
          请选择一个 round
        </div>
      )}
    </div>
  );
}
