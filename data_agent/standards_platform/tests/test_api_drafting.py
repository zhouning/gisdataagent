"""API smoke tests for drafting endpoints."""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform.drafting.editor_session import acquire_lock
from data_agent.standards_platform.tests.test_api_standards import (
    _client,
    _auth_user,
)


def _get_engine_or_skip():
    """Load .env if needed, return engine or pytest.skip."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def _seed_clause():
    """Insert a throwaway document/version/clause and return (clause_id, doc_id)."""
    eng = _get_engine_or_skip()
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-API-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, doc_id


@pytest.fixture
def fresh_clause():
    cid, did = _seed_clause()
    yield cid
    with _get_engine_or_skip().begin() as c:
        c.execute(text("DELETE FROM std_document WHERE id=:d"), {"d": did})


def test_post_lock_returns_200(monkeypatch, fresh_clause):
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock")
    assert r.status_code == 200
    body = r.json()
    assert body["body_md"] == "hello"
    assert body["checksum"]


def test_post_lock_returns_423_when_held(monkeypatch, fresh_clause):
    acquire_lock(fresh_clause, "alice")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock")
    assert r.status_code == 423
    assert r.json()["holder"] == "alice"


def test_put_clause_save_happy(monkeypatch, fresh_clause):
    a = acquire_lock(fresh_clause, "admin")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().put(f"/api/std/clauses/{fresh_clause}",
                      headers={"If-Match": a["checksum"]},
                      json={"body_md": "new", "body_html": "<p>new</p>"})
    assert r.status_code == 200
    assert r.json()["checksum"] != a["checksum"]


def test_put_clause_returns_409_on_checksum_mismatch(monkeypatch, fresh_clause):
    acquire_lock(fresh_clause, "admin")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().put(f"/api/std/clauses/{fresh_clause}",
                      headers={"If-Match": "0000000000000000"},
                      json={"body_md": "x", "body_html": None})
    assert r.status_code == 409
    assert r.json()["server_body_md"] == "hello"


def test_post_break_admin_only(monkeypatch, fresh_clause):
    acquire_lock(fresh_clause, "alice")
    # As an analyst → 403
    _auth_user(monkeypatch, username="u", role="analyst")
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock/break")
    assert r.status_code == 403
    # As admin → 200
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock/break")
    assert r.status_code == 200
    assert r.json()["previous_holder"] == "alice"


def test_get_clause_elements_returns_only_owned(monkeypatch, fresh_clause):
    """clause-scoped elements returns only data_elements with defined_by_clause_id matching."""
    from data_agent.db_engine import get_engine
    from sqlalchemy import text

    # Insert a few data_elements with this clause as defined_by_clause_id
    eng = get_engine()
    with eng.begin() as conn:
        # Get the version_id from the clause
        vid = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": fresh_clause}).scalar()
        # Insert 2 elements attached to this clause
        for code in ("FOO", "BAR"):
            conn.execute(text(
                "INSERT INTO std_data_element (document_version_id, code, "
                "name_zh, defined_by_clause_id) VALUES (:v, :c, :n, :cl)"
            ), {"v": vid, "c": code, "n": f"name-{code}", "cl": fresh_clause})
        # Insert one un-attached element (different clause_id = NULL)
        conn.execute(text(
            "INSERT INTO std_data_element (document_version_id, code, name_zh) "
            "VALUES (:v, 'OTHER', 'name-other')"
        ), {"v": vid})

    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().get(f"/api/std/clauses/{fresh_clause}/elements")
    assert r.status_code == 200
    body = r.json()
    codes = sorted(e["code"] for e in body["data_elements"])
    assert codes == ["BAR", "FOO"]
    # Verify embedding is excluded
    assert "embedding" not in body["data_elements"][0]
