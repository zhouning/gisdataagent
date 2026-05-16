"""Unit tests for citation_sources."""
from __future__ import annotations

import pytest
import uuid
from sqlalchemy import text as _sql
from data_agent.db_engine import get_engine
from dotenv import load_dotenv as _ld
import os as _os
_ld(_os.path.join(_os.path.dirname(__file__), "..", "..", ".env"))

from data_agent.standards_platform.drafting.citation_sources import (
    Candidate, search_pgvector, search_kb, search_web,
)


def test_candidate_typed_dict_shape():
    c: Candidate = {
        "kind": "std_clause", "target_id": "abc",
        "target_url": None, "snippet": "x", "base_score": 0.5, "extra": {}
    }
    assert c["kind"] == "std_clause"


@pytest.fixture
def db():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def test_search_pgvector_returns_clause_matches(db):
    """Insert a clause with a synthetic embedding, search with the same
    embedding, expect that clause as the top hit."""
    doc_id = str(uuid.uuid4()); ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    # Use a 768-dim embedding: all 0.1, except first dim = 1.0
    emb = "[" + ",".join(["1.0"] + ["0.1"] * 767) + "]"
    with db.begin() as c:
        c.execute(_sql(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'test')"
        ), {"i": doc_id, "c": f"T-PGV-{doc_id[:6]}"})
        c.execute(_sql(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        c.execute(_sql(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md, embedding) "
            "VALUES (:i, :d, :v, CAST('1' AS ltree), '1', 'clause', "
            "'pgvector test', CAST(:e AS vector))"
        ), {"i": cid, "d": doc_id, "v": ver_id, "e": emb})

    try:
        # Same embedding → cosine 1.0
        results = search_pgvector([1.0] + [0.1] * 767, top_k_per_table=5)
        clause_hits = [r for r in results if r["target_id"] == cid]
        assert len(clause_hits) == 1
        assert clause_hits[0]["kind"] == "std_clause"
        assert clause_hits[0]["base_score"] > 0.99  # near-perfect cosine
        assert "pgvector test" in clause_hits[0]["snippet"]
    finally:
        with db.begin() as c:
            c.execute(_sql("DELETE FROM std_document WHERE id=:d"),
                      {"d": doc_id})
