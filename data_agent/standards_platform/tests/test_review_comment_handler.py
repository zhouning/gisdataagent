"""API tests for /api/std/reviews/.../comments + resolve."""
from __future__ import annotations

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _start_round(client, version_id, reviewer="admin"):
    return client.post("/api/std/reviews/rounds", json={
        "document_version_id": version_id,
        "reviewer_user_id": reviewer}).json()["round_id"]


def test_post_comment_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "needs work"})
        assert resp.status_code == 201, resp.text
        cmts = _client().get(
            f"/api/std/reviews/rounds/{rid}/comments").json()["comments"]
        assert any(c["body_md"] == "needs work" for c in cmts)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_threaded_reply(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        c1 = _client().post(
            f"/api/std/reviews/rounds/{rid}/comments",
            json={"clause_id": cid, "body_md": "q?"}).json()["comment_id"]
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "reply!",
                                    "parent_comment_id": c1})
        assert resp.status_code == 201
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_resolve_comment(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        c1 = _client().post(
            f"/api/std/reviews/rounds/{rid}/comments",
            json={"clause_id": cid, "body_md": "foo"}).json()["comment_id"]
        resp = _client().post(f"/api/std/reviews/comments/{c1}/resolve",
                              json={"resolution": "accepted"})
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "accepted"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_comment_empty_body_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "   "})
        assert resp.status_code == 400
        assert "body_md" in resp.json()["error"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_comment_parent_in_different_round_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid1 = _start_round(_client(), ver_id)
    try:
        # close round 1 then start round 2, putting a parent in round 1
        c_in_r1 = _client().post(
            f"/api/std/reviews/rounds/{rid1}/comments",
            json={"clause_id": cid, "body_md": "in r1"}
        ).json()["comment_id"]
        _client().post(f"/api/std/reviews/comments/{c_in_r1}/resolve",
                       json={"resolution": "accepted"})
        _client().post(f"/api/std/reviews/rounds/{rid1}/close",
                       json={"outcome": "rejected"})  # back to draft
        rid2 = _start_round(_client(), ver_id)
        try:
            resp = _client().post(
                f"/api/std/reviews/rounds/{rid2}/comments",
                json={"clause_id": cid, "body_md": "x",
                      "parent_comment_id": c_in_r1})
            assert resp.status_code == 400
            assert "parent" in resp.json()["error"]
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                             {"i": rid2})
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid1})


def test_post_comment_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id, reviewer="rev1")
    try:
        _auth_user(monkeypatch, username="someone", role="standard_reviewer")
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "x"})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
