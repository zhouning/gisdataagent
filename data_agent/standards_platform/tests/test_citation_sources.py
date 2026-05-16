"""Unit tests for citation_sources."""
from __future__ import annotations

import pytest
from data_agent.standards_platform.drafting.citation_sources import (
    Candidate, search_pgvector, search_kb, search_web,
)


def test_candidate_typed_dict_shape():
    c: Candidate = {
        "kind": "std_clause", "target_id": "abc",
        "target_url": None, "snippet": "x", "base_score": 0.5, "extra": {}
    }
    assert c["kind"] == "std_clause"
