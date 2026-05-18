"""API tests for /api/std/reviews/rounds/* endpoints."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def test_start_round_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "rev1",
    })
    assert resp.status_code == 201, resp.text
    rid = resp.json()["round_id"]
    try:
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert v[0] == "review"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_start_round_when_version_not_draft(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='approved' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "rev1"})
    assert resp.status_code == 409
    assert resp.json()["current_status"] == "approved"


def test_start_round_when_open_round_exists(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r1 = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "rev1"}).json()["round_id"]
    try:
        resp = _client().post("/api/std/reviews/rounds", json={
            "document_version_id": ver_id, "reviewer_user_id": "rev2"})
        assert resp.status_code == 409
        assert resp.json()["round_id"] == r1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": r1})


def test_list_rounds_filter_by_reviewer(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "rev-X"}).json()["round_id"]
    try:
        resp = _client().get("/api/std/reviews/rounds?reviewer_user_id=rev-X")
        assert resp.status_code == 200
        rounds = resp.json()["rounds"]
        assert any(r["id"] == rid for r in rounds)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_approved_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "admin"}).json()["round_id"]
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version_status"] == "approved"
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert v[0] == "approved"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_rejected_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "admin"}).json()["round_id"]
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "rejected"})
        assert resp.status_code == 200
        assert resp.json()["version_status"] == "draft"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_gating_blocks_when_pending_ref(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "admin"}).json()["round_id"]
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text) VALUES "
                "(:i, :s, 'std_clause', :s, 'cite')"
            ), {"i": ref_id, "s": cid})
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 409
        assert resp.json()["pending_refs"] >= 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_by_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "rev1"}).json()["round_id"]
    try:
        # Switch identity to non-reviewer
        _auth_user(monkeypatch, username="someone_else", role="standard_reviewer")
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
