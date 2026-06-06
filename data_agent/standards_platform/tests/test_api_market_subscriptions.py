"""API tests for market subscription endpoints."""
from __future__ import annotations

import uuid

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_document,
    _seed_version,
)


def test_market_subscriptions_require_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    r = _client().get("/api/std/market/subscriptions")

    assert r.status_code == 401


def test_market_subscribe_happy_path(monkeypatch, engine):
    token = f"api-sub-create-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user(monkeypatch, username="alice", role="viewer")
        r = _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": version_id},
        )
        listed = _client().get("/api/std/market/subscriptions")

        assert r.status_code == 201, r.text
        assert r.json()["source_version_id"] == version_id
        assert listed.status_code == 200
        assert listed.json()["subscriptions"][0]["source_version_id"] == version_id
    finally:
        _delete_document(engine, doc_id)


def test_market_subscribe_rejects_missing_and_nonreleased(
    monkeypatch, engine
):
    token = f"api-sub-bad-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    draft_id = _seed_version(engine, doc_id, label="v1.0", status="draft")
    try:
        _auth_user(monkeypatch, username="alice", role="viewer")
        missing_body = _client().post("/api/std/market/subscriptions", json={})
        missing_version = _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": str(uuid.uuid4())},
        )
        nonreleased = _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": draft_id},
        )

        assert missing_body.status_code == 400
        assert missing_version.status_code == 404
        assert nonreleased.status_code == 409
    finally:
        _delete_document(engine, doc_id)


def test_market_subscriptions_are_current_user_scoped(monkeypatch, engine):
    token = f"api-sub-scope-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user(monkeypatch, username="alice", role="viewer")
        _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": version_id},
        )
        _auth_user(monkeypatch, username="bob", role="viewer")
        listed = _client().get("/api/std/market/subscriptions")

        assert listed.status_code == 200
        assert listed.json()["subscriptions"] == []
    finally:
        _delete_document(engine, doc_id)


def test_market_subscription_mark_seen(monkeypatch, engine):
    token = f"api-sub-seen-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    v1 = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user(monkeypatch, username="alice", role="viewer")
        sub = _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": v1},
        ).json()
        v2 = _seed_version(engine, doc_id, label="v1.1", status="released")

        marked = _client().post(
            f"/api/std/market/subscriptions/{sub['id']}/mark-seen"
        )
        listed = _client().get("/api/std/market/subscriptions")

        assert marked.status_code == 200
        assert marked.json()["last_seen_version_id"] == v2
        assert listed.json()["subscriptions"][0]["has_update"] is False
    finally:
        _delete_document(engine, doc_id)


def test_market_subscription_delete(monkeypatch, engine):
    token = f"api-sub-delete-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user(monkeypatch, username="alice", role="viewer")
        sub = _client().post(
            "/api/std/market/subscriptions",
            json={"version_id": version_id},
        ).json()

        deleted = _client().delete(
            f"/api/std/market/subscriptions/{sub['id']}"
        )
        listed = _client().get("/api/std/market/subscriptions")

        assert deleted.status_code == 200
        assert deleted.json()["status"] == "cancelled"
        assert listed.json()["subscriptions"] == []
    finally:
        _delete_document(engine, doc_id)
