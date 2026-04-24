"""
Reference Query Library — curated + auto-ingested verified queries (v19.0).

Provides embedding-based search for NL2SQL few-shot injection and
ContextEngine enrichment via ReferenceQueryProvider.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np
from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id
from .observability import get_logger

logger = get_logger("reference_queries")


class ReferenceQueryStore:
    """CRUD + embedding search for agent_reference_queries."""

    def add(
        self,
        query_text: str,
        description: str = "",
        response_summary: str = "",
        tags: Optional[list[str]] = None,
        pipeline_type: Optional[str] = None,
        task_type: Optional[str] = None,
        source: str = "manual",
        feedback_id: Optional[int] = None,
        created_by: Optional[str] = None,
        domain_id: Optional[str] = None,
    ) -> Optional[int]:
        """Add a reference query with auto-computed embedding. Returns id."""
        engine = get_engine()
        if not engine:
            return None

        # Compute embedding
        embedding = self._embed(query_text)

        # Dedup check: if very similar query exists (cosine > 0.92), skip
        if embedding:
            existing = self.search(query_text, top_k=1, _embedding=embedding)
            if existing and existing[0].get("score", 0) > 0.92:
                logger.info("Skipping duplicate reference query (score=%.3f)", existing[0]["score"])
                return existing[0]["id"]

        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO agent_reference_queries
                            (query_text, description, response_summary, tags,
                             pipeline_type, task_type, source, feedback_id,
                             embedding, created_by, domain_id)
                        VALUES
                            (:query, :desc, :resp, :tags::jsonb,
                             :pipe, :task, :source, :fb_id,
                             :emb, :creator, :domain_id)
                        RETURNING id
                    """),
                    {
                        "query": query_text,
                        "desc": description,
                        "resp": response_summary,
                        "tags": json.dumps(tags or []),
                        "pipe": pipeline_type,
                        "task": task_type,
                        "source": source,
                        "fb_id": feedback_id,
                        "emb": embedding,
                        "creator": created_by or current_user_id.get("system"),
                        "domain_id": domain_id,
                    },
                ).fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception as e:
            logger.warning("Failed to add reference query: %s", e)
            return None

    def get(self, ref_id: int) -> Optional[dict]:
        engine = get_engine()
        if not engine:
            return None
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT id, query_text, description, response_summary,
                               tags, pipeline_type, task_type, source,
                               feedback_id, use_count, success_count,
                               verified_by, verified_at, created_by,
                               created_at, updated_at
                        FROM agent_reference_queries WHERE id = :id
                    """),
                    {"id": ref_id},
                ).fetchone()
                if not row:
                    return None
                return self._row_to_dict(row)
        except Exception as e:
            logger.warning("Failed to get reference query: %s", e)
            return None

    def update(self, ref_id: int, **fields) -> bool:
        engine = get_engine()
        if not engine:
            return False
        allowed = {"description", "response_summary", "tags", "pipeline_type",
                    "task_type", "verified_by"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clauses = []
        params: dict = {"id": ref_id}
        for k, v in updates.items():
            if k == "tags":
                set_clauses.append(f"{k} = :{k}::jsonb")
                params[k] = json.dumps(v)
            else:
                set_clauses.append(f"{k} = :{k}")
                params[k] = v
        set_clauses.append("updated_at = NOW()")
        # Mark verified_at if verified_by is being set
        if "verified_by" in updates:
            set_clauses.append("verified_at = NOW()")
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(f"UPDATE agent_reference_queries SET {', '.join(set_clauses)} WHERE id = :id"),
                    params,
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("Failed to update reference query: %s", e)
            return False

    def delete(self, ref_id: int) -> bool:
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM agent_reference_queries WHERE id = :id"),
                    {"id": ref_id},
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("Failed to delete reference query: %s", e)
            return False

    def list(
        self,
        pipeline_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        engine = get_engine()
        if not engine:
            return []
        clauses = ["1=1"]
        params: dict = {"lim": limit, "off": offset}
        if pipeline_type:
            clauses.append("pipeline_type = :pipe")
            params["pipe"] = pipeline_type
        if source:
            clauses.append("source = :src")
            params["src"] = source
        where = " AND ".join(clauses)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT id, query_text, description, response_summary,
                               tags, pipeline_type, task_type, source,
                               feedback_id, use_count, success_count,
                               verified_by, verified_at, created_by,
                               created_at, updated_at
                        FROM agent_reference_queries
                        WHERE {where}
                        ORDER BY use_count DESC, created_at DESC
                        LIMIT :lim OFFSET :off
                    """),
                    params,
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to list reference queries: %s", e)
            return []

    def search(
        self,
        query: str,
        top_k: int = 5,
        pipeline_type: Optional[str] = None,
        task_type: Optional[str] = None,
        _embedding: Optional[list[float]] = None,
    ) -> list[dict]:
        """Embedding-based search for similar reference queries."""
        engine = get_engine()
        if not engine:
            return []

        query_emb = _embedding or self._embed(query)
        if not query_emb:
            return []

        clauses = ["embedding IS NOT NULL"]
        params: dict = {}
        if pipeline_type:
            clauses.append("pipeline_type = :pipe")
            params["pipe"] = pipeline_type
        if task_type:
            clauses.append("task_type = :task")
            params["task"] = task_type
        where = " AND ".join(clauses)

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT id, query_text, description, response_summary,
                               tags, pipeline_type, task_type, source,
                               feedback_id, use_count, success_count,
                               embedding
                        FROM agent_reference_queries
                        WHERE {where}
                    """),
                    params,
                ).fetchall()

            if not rows:
                return []

            # Cosine similarity ranking (replicates knowledge_base._cosine_search pattern)
            query_vec = np.array(query_emb, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return []

            scored = []
            for row in rows:
                emb = row[11]  # embedding column
                if not emb:
                    continue
                emb_vec = np.array(emb, dtype=np.float32)
                emb_norm = np.linalg.norm(emb_vec)
                if emb_norm == 0:
                    continue
                sim = float(np.dot(query_vec, emb_vec) / (query_norm * emb_norm))
                scored.append((sim, row))

            scored.sort(key=lambda x: x[0], reverse=True)

            return [
                {
                    "id": r[0],
                    "query_text": r[1],
                    "description": r[2],
                    "response_summary": r[3],
                    "tags": r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]"),
                    "pipeline_type": r[5],
                    "task_type": r[6],
                    "source": r[7],
                    "use_count": r[9],
                    "success_count": r[10],
                    "score": round(score, 4),
                }
                for score, r in scored[:top_k]
            ]
        except Exception as e:
            logger.warning("Failed to search reference queries: %s", e)
            return []

    def increment_use_count(self, ref_id: int, success: bool = True) -> None:
        engine = get_engine()
        if not engine:
            return
        try:
            with engine.connect() as conn:
                if success:
                    conn.execute(
                        text("""
                            UPDATE agent_reference_queries
                            SET use_count = use_count + 1,
                                success_count = success_count + 1,
                                updated_at = NOW()
                            WHERE id = :id
                        """),
                        {"id": ref_id},
                    )
                else:
                    conn.execute(
                        text("""
                            UPDATE agent_reference_queries
                            SET use_count = use_count + 1, updated_at = NOW()
                            WHERE id = :id
                        """),
                        {"id": ref_id},
                    )
                conn.commit()
        except Exception as e:
            logger.warning("Failed to increment use count: %s", e)

    def stats(self) -> dict:
        engine = get_engine()
        if not engine:
            return {"total": 0}
        try:
            with engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT COUNT(*),
                           COUNT(*) FILTER (WHERE source = 'auto'),
                           COUNT(*) FILTER (WHERE source = 'manual'),
                           COUNT(*) FILTER (WHERE source = 'seed')
                    FROM agent_reference_queries
                """)).fetchone()
                return {
                    "total": row[0] if row else 0,
                    "auto": row[1] if row else 0,
                    "manual": row[2] if row else 0,
                    "seed": row[3] if row else 0,
                }
        except Exception as e:
            logger.warning("Failed to get ref query stats: %s", e)
            return {"total": 0}

    # --- Helpers ---

    @staticmethod
    def _embed(text_str: str) -> Optional[list[float]]:
        try:
            from .knowledge_base import _get_embeddings

            embeddings = _get_embeddings([text_str])
            if embeddings and embeddings[0]:
                return embeddings[0]
        except Exception as e:
            logger.debug("Embedding failed: %s", e)
        return None

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row[0],
            "query_text": row[1],
            "description": row[2],
            "response_summary": row[3],
            "tags": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
            "pipeline_type": row[5],
            "task_type": row[6],
            "source": row[7],
            "feedback_id": row[8],
            "use_count": row[9],
            "success_count": row[10],
            "verified_by": row[11],
            "verified_at": row[12].isoformat() if row[12] else None,
            "created_by": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
            "updated_at": row[15].isoformat() if row[15] else None,
        }


# ---------------------------------------------------------------------------
# NL2SQL few-shot helper
# ---------------------------------------------------------------------------


def fetch_nl2sql_few_shots(query: str, top_k: int = 3, domain_id: Optional[str] = None) -> str:
    """Fetch reference queries as NL2SQL few-shot examples.

    Domain-priority search: same domain first, then global fallback.
    Returns formatted prompt section or empty string.
    """
    try:
        store = ReferenceQueryStore()
        hits = []
        # Priority 1: same domain
        if domain_id:
            domain_hits = store.search(query, top_k=top_k, task_type="nl2sql")
            hits = [h for h in domain_hits if h.get("domain_id") == domain_id]
        # Priority 2: global fallback
        if len(hits) < top_k:
            remaining = top_k - len(hits)
            all_hits = store.search(query, top_k=top_k + 5, task_type="nl2sql")
            seen_ids = {h["id"] for h in hits}
            for h in all_hits:
                if h["id"] not in seen_ids:
                    hits.append(h)
                    if len(hits) >= top_k:
                        break
        if not hits:
            return ""
        lines = ["参考查询示例:"]
        for h in hits:
            lines.append(f"- 问: {h['query_text']}")
            if h.get("response_summary"):
                lines.append(f"  SQL: {h['response_summary']}")
        return "\n".join(lines)
    except Exception:
        return ""
