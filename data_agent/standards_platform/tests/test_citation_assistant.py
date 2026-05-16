"""Unit test for citation_assistant.search_citations."""
from __future__ import annotations

from unittest.mock import patch
from data_agent.standards_platform.drafting.citation_assistant import (
    search_citations,
)


def test_assistant_orchestrates_three_sources():
    fake_pgvec = [{"kind": "std_clause", "target_id": "p1",
                   "target_url": None, "snippet": "pg snippet",
                   "base_score": 0.9, "extra": {}}]
    fake_kb = [{"kind": "kb_chunk", "target_id": "k1",
                "target_url": None, "snippet": "kb snippet",
                "base_score": 0.7, "extra": {}}]
    fake_web = [{"kind": "web_snapshot", "target_id": "w1",
                 "target_url": "https://x", "snippet": "web snippet",
                 "base_score": 0.5, "extra": {}}]

    with patch("data_agent.standards_platform.drafting.citation_assistant"
               "._embed_query", return_value=[0.0] * 768), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_pgvector", return_value=fake_pgvec), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_kb", return_value=fake_kb), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_web", return_value=fake_web), \
         patch("data_agent.standards_platform.drafting.citation_rerank"
               ".rerank", side_effect=lambda q, c, top_k=20: c):
        out = search_citations(clause_id="dummy", query="行政区",
                               sources={"pgvector", "kb", "web"})
    kinds = sorted(c["kind"] for c in out)
    assert kinds == ["kb_chunk", "std_clause", "web_snapshot"]
