"""API tests for market listing review endpoints."""
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


def test_market_listing_endpoints_require_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    list_response = _client().get("/api/std/market/listings")
    submit_response = _client().post(
        "/api/std/market/listings",
        json={"version_id": str(uuid.uuid4())},
    )
    review_response = _client().post(
        f"/api/std/market/listings/{uuid.uuid4()}/review",
        json={"decision": "approved"},
    )

    assert list_response.status_code == 401
    assert submit_response.status_code == 401
    assert review_response.status_code == 401


def test_market_listing_role_gates(monkeypatch):
    _auth_user(monkeypatch, role="viewer")

    list_response = _client().get("/api/std/market/listings")
    submit_response = _client().post(
        "/api/std/market/listings",
        json={"version_id": str(uuid.uuid4())},
    )
    review_response = _client().post(
        f"/api/std/market/listings/{uuid.uuid4()}/review",
        json={"decision": "approved"},
    )

    assert list_response.status_code == 403
    assert submit_response.status_code == 403
    assert review_response.status_code == 403


def test_market_listing_submit_and_approve_flow(monkeypatch, engine):
    token = f"api-listing-flow-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user(monkeypatch, username="editor-a", role="standard_editor")
        submitted = _client().post(
            "/api/std/market/listings",
            json={"version_id": version_id, "notes": "ready"},
        )

        _auth_user(monkeypatch, username="admin-a", role="admin")
        queue = _client().get("/api/std/market/listings?status=submitted")

        _auth_user(monkeypatch, username="viewer-a", role="viewer")
        hidden_catalog = _client().get(f"/api/std/market/standards?query={token}")

        listing_id = submitted.json()["id"]
        _auth_user(monkeypatch, username="admin-a", role="admin")
        approved = _client().post(
            f"/api/std/market/listings/{listing_id}/review",
            json={"decision": "approved", "review_notes": "ok"},
        )

        _auth_user(monkeypatch, username="viewer-a", role="viewer")
        visible_catalog = _client().get(
            f"/api/std/market/standards?query={token}"
        )

        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["status"] == "submitted"
        assert queue.status_code == 200
        assert queue.json()["total"] >= 1
        assert listing_id in {item["id"] for item in queue.json()["items"]}
        assert hidden_catalog.status_code == 200
        assert hidden_catalog.json()["total"] == 0
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["reviewed_by"] == "admin-a"
        assert visible_catalog.status_code == 200
        assert visible_catalog.json()["total"] == 1
        assert visible_catalog.json()["items"][0]["market_status"] == "approved"
    finally:
        _delete_document(engine, doc_id)


def test_market_listing_submit_rejects_missing_and_nonreleased(
    monkeypatch, engine
):
    token = f"api-listing-bad-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    draft_id = _seed_version(engine, doc_id, label="v1.0", status="draft")
    try:
        _auth_user(monkeypatch, username="editor-a", role="standard_editor")
        missing = _client().post("/api/std/market/listings", json={})
        missing_version = _client().post(
            "/api/std/market/listings",
            json={"version_id": str(uuid.uuid4())},
        )
        nonreleased = _client().post(
            "/api/std/market/listings",
            json={"version_id": draft_id},
        )

        assert missing.status_code == 400
        assert missing_version.status_code == 404
        assert nonreleased.status_code == 409
    finally:
        _delete_document(engine, doc_id)


def test_market_listing_review_rejects_invalid_decision_and_missing(
    monkeypatch,
):
    _auth_user(monkeypatch, username="admin-a", role="admin")

    invalid = _client().post(
        f"/api/std/market/listings/{uuid.uuid4()}/review",
        json={"decision": "withdrawn"},
    )
    missing = _client().post(
        f"/api/std/market/listings/{uuid.uuid4()}/review",
        json={"decision": "approved"},
    )

    assert invalid.status_code == 400
    assert missing.status_code == 404
