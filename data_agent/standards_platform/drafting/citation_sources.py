"""Citation candidate sources — pgvector / knowledge_base / web_snapshot.

All three functions return list[Candidate]. They are intended to be
called in parallel by citation_assistant.search_citations.
"""
from __future__ import annotations

import os
from typing import TypedDict

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.drafting.citation_sources")


class Candidate(TypedDict):
    kind: str            # 'std_clause' | 'std_data_element' | 'std_term'
                         # | 'kb_chunk' | 'web_snapshot'
    target_id: str | None
    target_url: str | None
    snippet: str
    base_score: float
    extra: dict


def search_pgvector(query_embedding: list[float], *,
                    top_k_per_table: int = 10) -> list[Candidate]:
    """Cosine search over std_clause / std_data_element / std_term."""
    eng = get_engine()
    if eng is None:
        return []
    emb_lit = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"
    sql = """
        SELECT kind, target_id, snippet, base_score, extra FROM (
        (SELECT 'std_clause' AS kind, id::text AS target_id,
                LEFT(COALESCE(heading,'') || ' ' || COALESCE(body_md,''), 500) AS snippet,
                1 - (embedding <=> CAST(:e AS vector)) AS base_score,
                jsonb_build_object(
                    'clause_no', clause_no,
                    'document_version_id', document_version_id::text,
                    'document_id', document_id::text
                ) AS extra
           FROM std_clause WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        UNION ALL
        (SELECT 'std_data_element' AS kind, id::text,
                LEFT(COALESCE(name_zh,'') || ' ' || COALESCE(definition,''), 500),
                1 - (embedding <=> CAST(:e AS vector)),
                jsonb_build_object('code', code,
                    'document_version_id', document_version_id::text)
           FROM std_data_element WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        UNION ALL
        (SELECT 'std_term' AS kind, id::text,
                LEFT(COALESCE(name_zh,'') || ' ' || COALESCE(definition,''), 500),
                1 - (embedding <=> CAST(:e AS vector)),
                jsonb_build_object('term_code', term_code,
                    'document_version_id', document_version_id::text)
           FROM std_term WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        ) AS u
        ORDER BY base_score DESC
    """
    with eng.connect() as conn:
        rows = conn.execute(text(sql), {"e": emb_lit,
                                        "k": top_k_per_table}).mappings().all()
    return [{
        "kind": r["kind"],
        "target_id": r["target_id"],
        "target_url": None,
        "snippet": r["snippet"] or "",
        "base_score": float(r["base_score"]),
        "extra": dict(r["extra"]) if r["extra"] else {},
    } for r in rows]


def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    """Wrap data_agent.knowledge_base.search_kb()."""
    raise NotImplementedError


def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search std_web_snapshot.body via ILIKE for the query terms."""
    raise NotImplementedError
