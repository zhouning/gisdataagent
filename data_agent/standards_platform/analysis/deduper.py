"""Similar-clause lookup across versions via pgvector cosine similarity."""
from __future__ import annotations

from sqlalchemy import text
from ...db_engine import get_engine


def find_similar_clauses(*, version_id: str, top_k: int = 10,
                         min_similarity: float = 0.8) -> list[dict]:
    eng = get_engine()
    if eng is None:
        return []
    with eng.connect() as conn:
        rows = conn.execute(text("""
            WITH src AS (
              SELECT id, embedding FROM std_clause
              WHERE document_version_id = :v AND embedding IS NOT NULL
            )
            SELECT s.id AS source_clause_id, t.id AS target_clause_id,
                   t.document_version_id, t.body_md,
                   1 - (s.embedding <=> t.embedding) AS similarity
            FROM src s
            JOIN std_clause t ON t.document_version_id <> :v
                               AND t.embedding IS NOT NULL
            WHERE 1 - (s.embedding <=> t.embedding) >= :thr
            ORDER BY similarity DESC
            LIMIT :k
        """), {"v": version_id, "thr": min_similarity, "k": top_k}).mappings().all()
        return [dict(r) for r in rows]
