"""Citation candidate sources — pgvector / knowledge_base / web_snapshot.

All three functions return list[Candidate]. They are intended to be
called in parallel by citation_assistant.search_citations.
"""
from __future__ import annotations

import math
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
    # pgvector cosine on a zero vector yields NaN (0/0); refuse rather than
    # produce JSON-incompatible NaN scores. Caller (citation_assistant)
    # treats empty result as "skip pgvector".
    if not any(x != 0.0 for x in query_embedding):
        logger.warning("search_pgvector: zero query embedding, skipping")
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
    out: list[Candidate] = []
    for r in rows:
        score = float(r["base_score"]) if r["base_score"] is not None else 0.0
        if math.isnan(score) or math.isinf(score):
            score = 0.0
        out.append({
            "kind": r["kind"],
            "target_id": r["target_id"],
            "target_url": None,
            "snippet": r["snippet"] or "",
            "base_score": score,
            "extra": dict(r["extra"]) if r["extra"] else {},
        })
    return out


def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    """Wrap data_agent.knowledge_base.search_kb()."""
    try:
        from ...knowledge_base import search_kb as _kb_search
    except Exception as e:
        logger.warning("knowledge_base import failed: %s", e)
        return []
    kb_id_env = os.getenv("STANDARDS_KB_ID")
    kwargs: dict = {"top_k": top_k}
    if kb_id_env:
        try:
            kwargs["kb_id"] = int(kb_id_env)
        except ValueError:
            pass
    try:
        chunks = _kb_search(query, **kwargs)
    except Exception as e:
        logger.warning("knowledge_base.search_kb failed: %s", e)
        return []
    out: list[Candidate] = []
    for ch in chunks or []:
        title = (
            (ch.get("metadata") or {}).get("title")
            or ch.get("doc_id")
            or "(无标题)"
        )
        out.append({
            "kind": "kb_chunk",
            "target_id": str(ch.get("chunk_id") or ""),
            "target_url": None,
            "snippet": (ch.get("content") or "")[:500],
            "base_score": float(ch.get("score") or 0.0),
            "extra": {"kb_id": ch.get("kb_id"), "title": title},
        })
    return out


def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search std_web_snapshot.extracted_text via ILIKE for any token in the query.

    Simple substring matching; no FTS index dependency. The snippet is
    the first ~500 chars of the matched extracted_text (a window around the first
    match would be better but is deferred).
    """
    eng = get_engine()
    if eng is None:
        return []
    tokens = [t for t in query.split() if t.strip()]
    if not tokens:
        return []
    # Build OR-ed ILIKE conditions
    pattern_clauses = " OR ".join(
        f"extracted_text ILIKE :p{i}" for i in range(len(tokens))
    )
    params = {f"p{i}": f"%{tok}%" for i, tok in enumerate(tokens)}
    params["k"] = top_k
    sql = f"""
        SELECT id::text AS id, url, LEFT(extracted_text, 500) AS snippet
          FROM std_web_snapshot
         WHERE {pattern_clauses}
         ORDER BY fetched_at DESC
         LIMIT :k
    """
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [{
        "kind": "web_snapshot",
        "target_id": r["id"],
        "target_url": r["url"],
        "snippet": r["snippet"] or "",
        "base_score": 0.5,  # neutral; rerank will refine
        "extra": {},
    } for r in rows]
