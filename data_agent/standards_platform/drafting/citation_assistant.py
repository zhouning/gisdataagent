"""Orchestrate the 3 citation sources and the LLM rerank."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from ...observability import get_logger
from . import citation_sources as _cs
from . import citation_rerank as _rr

logger = get_logger("standards_platform.drafting.citation_assistant")

_DEFAULT_SOURCES = frozenset({"pgvector", "kb", "web"})


def _embed_query(query: str) -> list[float]:
    """Embed the query via the project's embedding gateway."""
    try:
        from ...embedding_gateway import get_embeddings
        vecs = get_embeddings([query])
        if vecs and len(vecs) == 1 and len(vecs[0]) == 768:
            return list(vecs[0])
    except Exception as e:
        logger.warning("embed_query failed: %s", e)
    return [0.0] * 768


def search_citations(*, clause_id: str, query: str,
                     sources: set[str] | None = None,
                     top_k: int = 20) -> list[_cs.Candidate]:
    src = sources or _DEFAULT_SOURCES
    if not query or not query.strip():
        return []

    candidates: list[_cs.Candidate] = []
    futures: dict = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if "pgvector" in src:
            emb = _embed_query(query)
            futures[pool.submit(_cs.search_pgvector, emb)] = "pgvector"
        if "kb" in src:
            futures[pool.submit(_cs.search_kb, query)] = "kb"
        if "web" in src:
            futures[pool.submit(_cs.search_web, query)] = "web"
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                got = fut.result() or []
                logger.info("source %s returned %d candidates", name, len(got))
                candidates.extend(got)
            except Exception as e:
                logger.warning("source %s failed: %s", name, e)

    if not candidates:
        return []
    return _rr.rerank(query, candidates, top_k=top_k)
