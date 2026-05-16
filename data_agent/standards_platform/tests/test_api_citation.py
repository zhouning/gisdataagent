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
                "confidence, inserted_by FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert str(row.source_clause_id) == cid
        assert str(row.target_clause_id) == target_clause
        assert row.citation_text == "test snippet"
        assert float(row.confidence) == 0.85
        assert row.inserted_by == "admin"
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


# ---------------------------------------------------------------------------
# Wave 3 v1 fixes: Fix #3 (target FK dispatch) + Fix #4 (empty text guard)
# + Fix #5 (inserted_by / verification_status)
# ---------------------------------------------------------------------------

import uuid as _uuid_mod


def _seed_data_element(engine, version_id):
    de_id = str(_uuid_mod.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, "
            "name_zh, code) VALUES (:i, :v, '测试要素', :c)"
        ), {"i": de_id, "v": version_id, "c": f"DE-W3-{de_id[:6]}"})
    return de_id


def _seed_term(engine, version_id):
    t_id = str(_uuid_mod.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_term (id, document_version_id, term_code, "
            "name_zh, definition) VALUES (:i, :v, :tc, '测试术语', '定义')"
        ), {"i": t_id, "v": version_id, "tc": f"TC-W3-{t_id[:6]}"})
    return t_id


def test_citation_insert_data_element_target(monkeypatch, engine, fresh_clause):
    """Fix #3: target_kind=std_data_element writes target_data_element_id,
    not target_clause_id."""
    cid, _, vid = fresh_clause
    de_id = _seed_data_element(engine, vid)
    _auth_user(monkeypatch, username="admin", role="admin")
    ref_id = None
    try:
        r = _client().post("/api/std/citation/insert", json={
            "clause_id": cid,
            "candidate": {
                "kind": "std_data_element",
                "target_id": de_id,
                "snippet": "数据要素引用",
                "extra": {"confidence": 0.85},
            },
        })
        assert r.status_code == 200, r.text
        ref_id = r.json()["ref_id"]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_clause_id, target_data_element_id, "
                "target_term_id, inserted_by, verified_by, verification_status "
                "FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "std_data_element"
        assert row[1] is None
        assert str(row[2]) == de_id
        assert row[3] is None
        assert row[4] == "admin"      # inserted_by populated (Fix #5)
        assert row[5] is None         # verified_by NULL (Fix #5)
        assert row[6] == "pending"    # verification_status default (Fix #5)
    finally:
        with engine.begin() as c:
            # ON DELETE CASCADE from std_data_element → std_reference
            c.execute(text("DELETE FROM std_data_element WHERE id=:i"), {"i": de_id})


def test_citation_insert_term_target(monkeypatch, engine, fresh_clause):
    """Fix #3: target_kind=std_term writes target_term_id."""
    cid, _, vid = fresh_clause
    t_id = _seed_term(engine, vid)
    _auth_user(monkeypatch, username="admin", role="admin")
    try:
        r = _client().post("/api/std/citation/insert", json={
            "clause_id": cid,
            "candidate": {
                "kind": "std_term",
                "target_id": t_id,
                "snippet": "术语引用",
                "extra": {"confidence": 0.75},
            },
        })
        assert r.status_code == 200, r.text
        ref_id = r.json()["ref_id"]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_term_id, target_clause_id "
                "FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "std_term"
        assert str(row[1]) == t_id
        assert row[2] is None
    finally:
        with engine.begin() as c:
            # ON DELETE CASCADE from std_term → std_reference
            c.execute(text("DELETE FROM std_term WHERE id=:i"), {"i": t_id})


def test_citation_insert_clause_target_still_works(monkeypatch, engine, fresh_clause):
    """Regression: target_kind=std_clause still works post-fix."""
    cid, _, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    ref_id = None
    try:
        r = _client().post("/api/std/citation/insert", json={
            "clause_id": cid,
            "candidate": {
                "kind": "std_clause",
                "target_id": cid,  # self-reference for test purposes
                "snippet": "条款引用",
                "extra": {"confidence": 0.9},
            },
        })
        assert r.status_code == 200, r.text
        ref_id = r.json()["ref_id"]
    finally:
        if ref_id:
            with engine.begin() as c:
                c.execute(text("DELETE FROM std_reference WHERE id=:i"), {"i": ref_id})


def test_citation_insert_empty_text_rejected(monkeypatch, fresh_clause):
    """Fix #4: empty citation_text returns 400."""
    cid, _, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_clause",
            "target_id": cid,
            "snippet": "",
            "extra": {"confidence": 0.5},
        },
    })
    assert r.status_code == 400
    assert "citation_text" in r.json().get("error", "")


def test_citation_insert_whitespace_text_rejected(monkeypatch, fresh_clause):
    """Fix #4: whitespace-only citation_text returns 400."""
    cid, _, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_clause",
            "target_id": cid,
            "snippet": "   \n\t",
            "extra": {"confidence": 0.5},
        },
    })
    assert r.status_code == 400


def test_citation_insert_kb_chunk_target(monkeypatch, engine, fresh_clause):
    """Regression: kb_chunk candidate maps to target_kind=internet_search and
    is accepted with NULL target_url (Wave 3 migration 077)."""
    cid, _, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "kb_chunk",
            "target_id": "kb-chunk-uuid",
            "target_url": None,
            "snippet": "知识库片段引用",
            "extra": {"confidence": 0.7},
        },
    })
    assert resp.status_code == 200, resp.text
    ref_id = resp.json()["ref_id"]
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_url, target_clause_id "
                "FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "internet_search"
        assert row[1] is None
        assert row[2] is None
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_reference WHERE id=:i"
            ), {"i": ref_id})


def test_citation_insert_web_snapshot_target(monkeypatch, engine, fresh_clause):
    """Regression: web_snapshot target writes target_url and snapshot_id."""
    cid, _, _ = fresh_clause
    snap_id = str(_uuid_mod.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_web_snapshot (id, url, http_status, "
            "extracted_text) VALUES (:i, 'https://example.com/x', 200, "
            "'snippet')"
        ), {"i": snap_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    ref_id = None
    try:
        r = _client().post("/api/std/citation/insert", json={
            "clause_id": cid,
            "candidate": {
                "kind": "web_snapshot",
                "target_id": snap_id,
                "target_url": "https://example.com/x",
                "snippet": "网页引用",
                "extra": {"confidence": 0.6},
            },
        })
        assert r.status_code == 200, r.text
        ref_id = r.json()["ref_id"]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_url, snapshot_id "
                "FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "web_snapshot"
        assert row[1] == "https://example.com/x"
        assert str(row[2]) == snap_id
    finally:
        if ref_id:
            with engine.begin() as c:
                c.execute(text("DELETE FROM std_reference WHERE id=:i"), {"i": ref_id})
        with engine.begin() as c:
            c.execute(text("DELETE FROM std_web_snapshot WHERE id=:i"), {"i": snap_id})
