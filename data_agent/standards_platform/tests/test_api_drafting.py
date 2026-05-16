"""API smoke tests for drafting endpoints."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.drafting.editor_session import acquire_lock
from data_agent.standards_platform.tests.test_api_standards import (
    _client,
    _auth_user,
)


def test_post_lock_returns_200(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{cid}/lock")
    assert r.status_code == 200
    body = r.json()
    assert body["body_md"] == "hello"
    assert body["checksum"]


def test_post_lock_returns_423_when_held(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    acquire_lock(cid, "alice")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{cid}/lock")
    assert r.status_code == 423
    assert r.json()["holder"] == "alice"


def test_put_clause_save_happy(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    a = acquire_lock(cid, "admin")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().put(f"/api/std/clauses/{cid}",
                      headers={"If-Match": a["checksum"]},
                      json={"body_md": "new", "body_html": "<p>new</p>"})
    assert r.status_code == 200
    assert r.json()["checksum"] != a["checksum"]


def test_put_clause_returns_409_on_checksum_mismatch(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    acquire_lock(cid, "admin")
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().put(f"/api/std/clauses/{cid}",
                      headers={"If-Match": "0000000000000000"},
                      json={"body_md": "x", "body_html": None})
    assert r.status_code == 409
    assert r.json()["server_body_md"] == "hello"


def test_post_break_admin_only(monkeypatch, fresh_clause):
    cid, doc_id, _ = fresh_clause
    acquire_lock(cid, "alice")
    # As an analyst → 403
    _auth_user(monkeypatch, username="u", role="analyst")
    r = _client().post(f"/api/std/clauses/{cid}/lock/break")
    assert r.status_code == 403
    # As admin → 200
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post(f"/api/std/clauses/{cid}/lock/break")
    assert r.status_code == 200
    assert r.json()["previous_holder"] == "alice"


def test_get_clause_elements_returns_only_owned(monkeypatch, engine, fresh_clause):
    """clause-scoped elements returns only data_elements with defined_by_clause_id matching."""
    cid, doc_id, _ = fresh_clause
    # Insert a few data_elements with this clause as defined_by_clause_id
    with engine.begin() as conn:
        # Get the version_id from the clause
        vid = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": cid}).scalar()
        # Insert 2 elements attached to this clause
        for code in ("FOO", "BAR"):
            conn.execute(text(
                "INSERT INTO std_data_element (document_version_id, code, "
                "name_zh, defined_by_clause_id) VALUES (:v, :c, :n, :cl)"
            ), {"v": vid, "c": code, "n": f"name-{code}", "cl": cid})
        # Insert one un-attached element (different clause_id = NULL)
        conn.execute(text(
            "INSERT INTO std_data_element (document_version_id, code, name_zh) "
            "VALUES (:v, 'OTHER', 'name-other')"
        ), {"v": vid})

    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().get(f"/api/std/clauses/{cid}/elements")
    assert r.status_code == 200
    body = r.json()
    codes = sorted(e["code"] for e in body["data_elements"])
    assert codes == ["BAR", "FOO"]
    # Verify embedding is excluded
    assert "embedding" not in body["data_elements"][0]
