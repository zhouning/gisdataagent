"""API tests for /api/std/publish/* endpoints."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


@pytest.fixture
def fresh_approved_version(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='approved' WHERE id=:v"
        ), {"v": ver_id})
    return cid, doc_id, ver_id


@pytest.fixture
def fresh_released_version(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released', "
            "released_at=now() WHERE id=:v"
        ), {"v": ver_id})
    return cid, doc_id, ver_id


def test_publish_happy(monkeypatch, engine, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post(f"/api/std/publish/versions/{ver_id}")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    try:
        assert body["status"] == "released"
        assert body["released_at"] is not None
        assert body["outbox_event_id"]
        with engine.connect() as c:
            v = c.execute(text(
                "SELECT status FROM std_document_version WHERE id=:i"
            ), {"i": ver_id}).first()[0]
        assert v == "released"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_outbox WHERE id=:i"),
                         {"i": body["outbox_event_id"]})


def test_publish_non_approved_409(monkeypatch, fresh_clause):
    cid, doc_id, ver_id = fresh_clause  # 'draft'
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post(f"/api/std/publish/versions/{ver_id}")
    assert resp.status_code == 409
    assert "approved" in resp.json()["error"]


def test_publish_non_admin_403(monkeypatch, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    _auth_user(monkeypatch, username="alice", role="standard_editor")
    resp = _client().post(f"/api/std/publish/versions/{ver_id}")
    assert resp.status_code == 403


def test_publish_missing_404(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post(f"/api/std/publish/versions/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_fork_happy(monkeypatch, engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/publish/fork", json={
        "source_version_id": ver_id,
        "new_label": "v1.1",
    })
    assert resp.status_code == 201, resp.text
    new_vid = resp.json()["new_version_id"]
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT version_label, status, supersedes_version_id "
                "FROM std_document_version WHERE id=:i"
            ), {"i": new_vid}).first()
        assert row[0] == "v1.1"
        assert row[1] == "draft"
        assert str(row[2]) == ver_id
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_document_version WHERE id=:i"
            ), {"i": new_vid})


def test_fork_from_non_released_409(monkeypatch, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/publish/fork", json={
        "source_version_id": ver_id, "new_label": "v1.1",
    })
    assert resp.status_code == 409


def test_fork_dup_label_409(monkeypatch, engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    _auth_user(monkeypatch, username="admin", role="admin")
    new_vid = _client().post("/api/std/publish/fork", json={
        "source_version_id": ver_id, "new_label": "v1.1",
    }).json()["new_version_id"]
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE std_document_version SET status='released' WHERE id=:i"
            ), {"i": ver_id})
        resp = _client().post("/api/std/publish/fork", json={
            "source_version_id": ver_id, "new_label": "v1.1",
        })
        assert resp.status_code == 409
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_document_version WHERE id=:i"
            ), {"i": new_vid})


def test_list_versions_filter(monkeypatch, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().get(f"/api/std/publish/versions?document_id={doc_id}")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert any(v["id"] == ver_id for v in versions)


def test_publish_timeline(monkeypatch, engine, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    _auth_user(monkeypatch, username="admin", role="admin")
    out = _client().post(f"/api/std/publish/versions/{ver_id}").json()
    try:
        resp = _client().get(f"/api/std/publish/timeline/{ver_id}")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "published"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_outbox WHERE id=:i"),
                         {"i": out["outbox_event_id"]})
