"""API smoke tests for citation endpoints."""
from __future__ import annotations

import uuid

from sqlalchemy import text
from unittest.mock import patch

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def test_search_citations_returns_200(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    fake_cands = [{"kind": "std_clause", "target_id": "c1",
                   "target_url": None, "snippet": "x", "base_score": 0.9,
                   "extra": {"confidence": 0.95}}]
    _auth_user(monkeypatch, username="admin", role="admin")
    with patch("data_agent.standards_platform.drafting.citation_assistant"
               ".search_citations", return_value=fake_cands):
        r = _client().post("/api/std/citation/search",
                           json={"clause_id": cid,
                                 "query": "行政区"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["kind"] == "std_clause"


def test_search_citations_validates_query_required(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post("/api/std/citation/search",
                       json={"clause_id": cid, "query": ""})
    assert r.status_code == 400


def test_insert_citation_creates_std_reference(monkeypatch, engine, fresh_clause):
    cid, doc_id, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    cand = {"kind": "std_clause", "target_id": str(uuid.uuid4()),
            "target_url": None, "snippet": "test snippet",
            "base_score": 0.8, "extra": {"confidence": 0.85}}
    # The target_id must exist for the FK; insert a real one.
    target_doc = str(uuid.uuid4())
    target_ver = str(uuid.uuid4())
    target_clause = cand["target_id"]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": target_doc, "c": f"T-TGT-{target_doc[:6]}"})
        c.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": target_ver, "d": target_doc})
        c.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', '')"
        ), {"i": target_clause, "d": target_doc, "v": target_ver})
    try:
        r = _client().post("/api/std/citation/insert",
                           json={"clause_id": cid,
                                 "candidate": cand})
        assert r.status_code == 200
        ref_id = r.json()["ref_id"]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT source_clause_id, target_clause_id, citation_text, "
                "confidence, verified_by FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert str(row.source_clause_id) == cid
        assert str(row.target_clause_id) == target_clause
        assert row.citation_text == "test snippet"
        assert float(row.confidence) == 0.85
        assert row.verified_by == "admin"
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM std_document WHERE id=:d"),
                      {"d": target_doc})


def test_insert_citation_rejects_invalid_kind(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    cand = {"kind": "totally_bogus", "target_id": "x",
            "target_url": None, "snippet": "...",
            "base_score": 0.5, "extra": {}}
    r = _client().post("/api/std/citation/insert",
                       json={"clause_id": cid, "candidate": cand})
    assert r.status_code == 400
