"""
Structured Feedback Loop — collect, learn, and improve (v19.0).

FeedbackStore: CRUD operations on agent_feedback table.
FeedbackProcessor: Auto-ingests upvotes as reference queries,
                   batches downvotes through FailureAnalyzer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id
from .observability import get_logger

logger = get_logger("feedback")


# ---------------------------------------------------------------------------
# FeedbackStore — CRUD
# ---------------------------------------------------------------------------


class FeedbackStore:
    """Persistent storage for user feedback on agent responses."""

    def record(
        self,
        username: str,
        query_text: str,
        vote: int,
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
        pipeline_type: Optional[str] = None,
        response_text: Optional[str] = None,
        issue_description: Optional[str] = None,
        issue_tags: Optional[list[str]] = None,
        context_snapshot: Optional[dict] = None,
    ) -> Optional[int]:
        """Record a feedback entry. Returns feedback id or None."""
        engine = get_engine()
        if not engine:
            logger.warning("No database — feedback not saved")
            return None
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO agent_feedback
                            (username, session_id, message_id, pipeline_type,
                             query_text, response_text, vote,
                             issue_description, issue_tags, context_snapshot)
                        VALUES
                            (:username, :session_id, :message_id, :pipeline_type,
                             :query_text, :response_text, :vote,
                             :issue_desc, :issue_tags::jsonb, :ctx::jsonb)
                        RETURNING id
                    """),
                    {
                        "username": username,
                        "session_id": session_id,
                        "message_id": message_id,
                        "pipeline_type": pipeline_type,
                        "query_text": query_text,
                        "response_text": response_text,
                        "vote": vote,
                        "issue_desc": issue_description,
                        "issue_tags": json.dumps(issue_tags or []),
                        "ctx": json.dumps(context_snapshot) if context_snapshot else None,
                    },
                ).fetchone()
                conn.commit()
                fb_id = row[0] if row else None
                logger.info("Feedback recorded: id=%s vote=%s user=%s", fb_id, vote, username)
                return fb_id
        except Exception as e:
            logger.warning("Failed to record feedback: %s", e)
            return None

    def get_stats(self, days: int = 30) -> dict:
        """Get feedback statistics for the last N days.

        Returns: {total, upvotes, downvotes, satisfaction_rate,
                  by_pipeline: {pipeline: {up, down}},
                  trend: [{date, up, down}]}
        """
        engine = get_engine()
        if not engine:
            return {"total": 0, "upvotes": 0, "downvotes": 0, "satisfaction_rate": 0.0,
                    "by_pipeline": {}, "trend": []}
        try:
            with engine.connect() as conn:
                # Overall counts
                row = conn.execute(
                    text("""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE vote = 1) AS up,
                            COUNT(*) FILTER (WHERE vote = -1) AS down
                        FROM agent_feedback
                        WHERE created_at >= NOW() - make_interval(days => :d)
                    """),
                    {"d": days},
                ).fetchone()
                total = row[0] if row else 0
                up = row[1] if row else 0
                down = row[2] if row else 0
                rate = round(up / total, 4) if total > 0 else 0.0

                # By pipeline
                pipe_rows = conn.execute(
                    text("""
                        SELECT pipeline_type,
                               COUNT(*) FILTER (WHERE vote = 1) AS up,
                               COUNT(*) FILTER (WHERE vote = -1) AS down
                        FROM agent_feedback
                        WHERE created_at >= NOW() - make_interval(days => :d)
                        GROUP BY pipeline_type
                    """),
                    {"d": days},
                ).fetchall()
                by_pipeline = {
                    r[0] or "unknown": {"up": r[1], "down": r[2]}
                    for r in pipe_rows
                }

                # Daily trend
                trend_rows = conn.execute(
                    text("""
                        SELECT DATE(created_at) AS d,
                               COUNT(*) FILTER (WHERE vote = 1) AS up,
                               COUNT(*) FILTER (WHERE vote = -1) AS down
                        FROM agent_feedback
                        WHERE created_at >= NOW() - make_interval(days => :d)
                        GROUP BY DATE(created_at)
                        ORDER BY d
                    """),
                    {"d": days},
                ).fetchall()
                trend = [
                    {"date": r[0].isoformat() if r[0] else "", "up": r[1], "down": r[2]}
                    for r in trend_rows
                ]

                return {
                    "total": total,
                    "upvotes": up,
                    "downvotes": down,
                    "satisfaction_rate": rate,
                    "by_pipeline": by_pipeline,
                    "trend": trend,
                }
        except Exception as e:
            logger.warning("Failed to get feedback stats: %s", e)
            return {"total": 0, "upvotes": 0, "downvotes": 0, "satisfaction_rate": 0.0,
                    "by_pipeline": {}, "trend": []}

    def list_recent(
        self,
        vote: Optional[int] = None,
        resolved: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List recent feedback entries."""
        engine = get_engine()
        if not engine:
            return []
        try:
            clauses = ["1=1"]
            params: dict = {"lim": limit}
            if vote is not None:
                clauses.append("vote = :vote")
                params["vote"] = vote
            if resolved is not None:
                if resolved:
                    clauses.append("resolved_at IS NOT NULL")
                else:
                    clauses.append("resolved_at IS NULL")
            where = " AND ".join(clauses)
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT id, username, session_id, message_id, pipeline_type,
                               query_text, response_text, vote, issue_description,
                               issue_tags, resolved_at, resolution_action,
                               resolution_ref, created_at
                        FROM agent_feedback
                        WHERE {where}
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    params,
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "username": r[1],
                        "session_id": r[2],
                        "message_id": r[3],
                        "pipeline_type": r[4],
                        "query_text": r[5],
                        "response_text": r[6],
                        "vote": r[7],
                        "issue_description": r[8],
                        "issue_tags": r[9] if isinstance(r[9], list) else json.loads(r[9] or "[]"),
                        "resolved_at": r[10].isoformat() if r[10] else None,
                        "resolution_action": r[11],
                        "resolution_ref": r[12],
                        "created_at": r[13].isoformat() if r[13] else None,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Failed to list feedback: %s", e)
            return []

    def list_unresolved_downvotes(self, limit: int = 50) -> list[dict]:
        """Shortcut for unresolved downvotes."""
        return self.list_recent(vote=-1, resolved=False, limit=limit)

    def mark_resolved(
        self,
        feedback_id: int,
        action: str,
        ref: str = "",
    ) -> bool:
        """Mark a feedback entry as resolved."""
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(
                    text("""
                        UPDATE agent_feedback
                        SET resolved_at = NOW(),
                            resolution_action = :action,
                            resolution_ref = :ref
                        WHERE id = :id
                    """),
                    {"id": feedback_id, "action": action, "ref": ref},
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("Failed to mark feedback resolved: %s", e)
            return False


# ---------------------------------------------------------------------------
# FeedbackProcessor — learning pipeline
# ---------------------------------------------------------------------------


class FeedbackProcessor:
    """Processes feedback into learning signals."""

    def __init__(self):
        self.store = FeedbackStore()

    async def process_upvote(self, feedback_id: int) -> dict:
        """Extract upvoted query as reference query.

        1. Fetch the feedback row
        2. Check for duplicates via embedding cosine similarity (>0.92 = skip)
        3. Insert into agent_reference_queries
        4. Mark feedback as resolved
        """
        engine = get_engine()
        if not engine:
            return {"status": "error", "reason": "no database"}

        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT id, query_text, response_text, pipeline_type, username
                        FROM agent_feedback WHERE id = :id
                    """),
                    {"id": feedback_id},
                ).fetchone()
                if not row:
                    return {"status": "error", "reason": "feedback not found"}

                query_text = row[1]
                response_text = row[2] or ""
                pipeline_type = row[3]
                username = row[4]

            # Try to use ReferenceQueryStore if available
            try:
                from .reference_queries import ReferenceQueryStore

                rq_store = ReferenceQueryStore()
                ref_id = rq_store.add(
                    query_text=query_text,
                    description=f"Auto-extracted from upvote by {username}",
                    response_summary=response_text[:500],
                    pipeline_type=pipeline_type,
                    source="auto",
                    feedback_id=feedback_id,
                    created_by=username,
                )
                self.store.mark_resolved(feedback_id, "ingested_as_reference", str(ref_id))
                return {"status": "ingested", "reference_query_id": ref_id}
            except ImportError:
                # Phase 3 not yet implemented — just mark resolved
                self.store.mark_resolved(feedback_id, "ingested_as_reference", "pending_phase3")
                return {"status": "pending", "reason": "reference_queries module not available"}
        except Exception as e:
            logger.warning("process_upvote failed: %s", e)
            return {"status": "error", "reason": str(e)}

    async def process_downvote_batch(self, limit: int = 50) -> dict:
        """Batch-process unresolved downvotes through FailureAnalyzer.

        1. Pull unresolved downvotes
        2. Convert to BadCaseCollector format
        3. Call FailureAnalyzer.analyze()
        4. Mark as resolved
        """
        downvotes = self.store.list_unresolved_downvotes(limit=limit)
        if not downvotes:
            return {"status": "empty", "processed": 0}

        # Convert to bad case format
        bad_cases = [
            {
                "source": "user_feedback",
                "id": dv["id"],
                "pipeline": dv.get("pipeline_type", "unknown"),
                "details": {
                    "query": dv.get("query_text", ""),
                    "response": dv.get("response_text", "")[:500],
                    "issue": dv.get("issue_description", ""),
                },
                "created_at": dv.get("created_at"),
            }
            for dv in downvotes
        ]

        try:
            from .prompt_optimizer import FailureAnalyzer

            analyzer = FailureAnalyzer()
            analysis = await analyzer.analyze(bad_cases)

            # Mark all as resolved
            for dv in downvotes:
                self.store.mark_resolved(
                    dv["id"], "prompt_optimized", json.dumps(analysis.get("root_causes", []))[:200]
                )

            return {
                "status": "processed",
                "processed": len(downvotes),
                "patterns": len(analysis.get("patterns", [])),
                "root_causes": analysis.get("root_causes", []),
            }
        except Exception as e:
            logger.warning("process_downvote_batch failed: %s", e)
            return {"status": "error", "reason": str(e), "processed": 0}
