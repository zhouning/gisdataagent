"""API tests for PATCH /api/std/reviews/references/{ref_id}/status."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _seed_pending_ref(engine, clause_id):
    ref_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_reference (id, source_clause_id, target_kind, "
            "target_clause_id, citation_text) VALUES "
            "(:i, :s, 'std_clause', :s, 'cite')"
        ), {"i": ref_id, "s": clause_id})
    return ref_id


def _start_round(client, version_id, reviewer="admin"):
    return client.post("/api/std/reviews/rounds", json={
        "document_version_id": version_id,
        "reviewer_user_id": reviewer}).json()["round_id"]


def test_patch_ref_approved(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(
            f"/api/std/reviews/references/{ref_id}/status",
            json={"verification_status": "approved", "round_id": rid})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "approved"
        assert body["verified_by"] == "admin"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_rejected(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(
            f"/api/std/reviews/references/{ref_id}/status",
            json={"verification_status": "rejected", "round_id": rid})
        assert resp.status_code == 200
        assert resp.json()["verification_status"] == "rejected"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_pending_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(
            f"/api/std/reviews/references/{ref_id}/status",
            json={"verification_status": "pending", "round_id": rid})
        assert resp.status_code == 400
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id, reviewer="rev1")
    try:
        _auth_user(monkeypatch, username="someone", role="standard_reviewer")
        resp = _client().patch(
            f"/api/std/reviews/references/{ref_id}/status",
            json={"verification_status": "approved", "round_id": rid})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_closed_round_409(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        # approve the ref first so we can close cleanly
        _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                        json={"verification_status": "approved", "round_id": rid})
        _client().post(f"/api/std/reviews/rounds/{rid}/close",
                       json={"outcome": "approved"})
        # now attempt patch on closed round; need a 2nd ref
        ref2 = _seed_pending_ref(engine, cid)
        resp = _client().patch(
            f"/api/std/reviews/references/{ref2}/status",
            json={"verification_status": "rejected", "round_id": rid})
        assert resp.status_code == 409
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
