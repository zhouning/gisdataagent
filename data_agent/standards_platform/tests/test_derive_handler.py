"""API tests for /api/std/derive/* endpoints."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _seed_bound_element(engine, ver_id):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, :c, '名', 'string', 'optional', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}"})
    return eid


def _cleanup(engine, ver_id):
    with engine.connect() as c:
        hint_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_semantic_hints WHERE std_version_id=:v"
        ), {"v": ver_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link WHERE source_version_id=:v"
        ), {"v": ver_id}).fetchall()]
    with engine.begin() as conn:
        if hint_ids:
            conn.execute(text(
                "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
            ), {"ids": hint_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})


def test_list_strategies(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().get("/api/std/derive/strategies")
    assert resp.status_code == 200
    strats = resp.json()["strategies"]
    names = {s["name"] for s in strats}
    assert "to_semantic_hint" in names
    active = [s for s in strats if s["status"] == "active"]
    coming = [s for s in strats if s["status"] == "coming_soon"]
    # Wave 8: to_data_model activated → 6/6 active, 0 coming_soon.
    assert len(active) == 6
    assert len(coming) == 0
    assert {s["name"] for s in active} == {
        "to_semantic_hint", "to_value_semantics", "to_synonym",
        "to_qc_rule", "to_defect_code", "to_data_model",
    }


def test_list_links_with_version_filter(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    _auth_user(monkeypatch, username="admin", role="admin")
    # Need to actually run a derivation first to have links to list
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released', "
            "released_at=now() WHERE id=:v"
        ), {"v": ver_id})
    rerun = _client().post(f"/api/std/derive/rerun/{ver_id}", json={})
    assert rerun.status_code == 200
    try:
        resp = _client().get(
            f"/api/std/derive/links?version_id={ver_id}&strategy=to_semantic_hint"
        )
        assert resp.status_code == 200
        links = resp.json()["links"]
        assert len(links) == 1
        assert links[0]["status"] == "active"
    finally:
        _cleanup(engine, ver_id)


def test_rerun_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    try:
        resp = _client().post(f"/api/std/derive/rerun/{ver_id}", json={})
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert results["to_semantic_hint"]["ok"] is True
        assert results["to_semantic_hint"]["new"] == 1
    finally:
        _cleanup(engine, ver_id)


def test_rerun_non_released_409(monkeypatch, fresh_clause):
    cid, doc_id, ver_id = fresh_clause  # 'draft'
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post(f"/api/std/derive/rerun/{ver_id}", json={})
    assert resp.status_code == 409
    assert resp.json()["current_status"] == "draft"


def test_rerun_non_admin_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="alice", role="standard_editor")
    resp = _client().post(f"/api/std/derive/rerun/{ver_id}", json={})
    assert resp.status_code == 403


def test_status_aggregation(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    _client().post(f"/api/std/derive/rerun/{ver_id}", json={})
    try:
        resp = _client().get(f"/api/std/derive/status/{ver_id}")
        assert resp.status_code == 200
        body = resp.json()["strategies"]
        assert "to_semantic_hint" in body
        assert body["to_semantic_hint"]["active"] == 1
    finally:
        _cleanup(engine, ver_id)
