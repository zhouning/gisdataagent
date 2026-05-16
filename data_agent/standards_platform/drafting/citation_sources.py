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
    raise NotImplementedError


def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    """Wrap data_agent.knowledge_base.search_kb()."""
    raise NotImplementedError


def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search std_web_snapshot.body via ILIKE for the query terms."""
    raise NotImplementedError
