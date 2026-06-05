"""API tests for Standards Platform outbox admin routes."""
from __future__ import annotations

from unittest.mock import patch

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)


def test_list_outbox_events_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    resp = _client().get("/api/std/outbox/events")

    assert resp.status_code == 401


def test_list_outbox_events_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().get("/api/std/outbox/events")

    assert resp.status_code == 403


def test_list_outbox_events_returns_events_and_counts(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    event = {
        "id": "evt-1",
        "event_type": "derive_requested",
        "status": "failed",
        "attempts": 5,
        "last_error": "boom",
        "payload": {"version_id": "v1"},
        "created_at": "2026-06-05T00:00:00+00:00",
        "processed_at": None,
        "next_attempt_at": "2026-06-05T00:00:00+00:00",
    }
    with patch(
        "data_agent.api.standards_routes._outbox_admin.list_events",
        return_value=[event],
    ) as list_events, patch(
        "data_agent.api.standards_routes._outbox_admin.get_counts",
        return_value={"pending": 0, "in_flight": 0, "done": 0, "failed": 1},
    ):
        resp = _client().get(
            "/api/std/outbox/events?status=failed&event_type=derive_requested"
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "events": [event],
        "counts": {"pending": 0, "in_flight": 0, "done": 0, "failed": 1},
    }
    list_events.assert_called_once_with(
        status="failed", event_type="derive_requested", limit=50, offset=0
    )


def test_list_outbox_events_rejects_invalid_limit(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().get("/api/std/outbox/events?limit=0")

    assert resp.status_code == 400
    assert resp.json()["error"] == "limit must be between 1 and 200"


def test_retry_outbox_event_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().post("/api/std/outbox/events/evt-1/retry")

    assert resp.status_code == 403


def test_retry_outbox_event_returns_result(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    with patch(
        "data_agent.api.standards_routes._outbox_admin.retry_event",
        return_value={"id": "evt-1", "status": "retried"},
    ) as retry:
        resp = _client().post("/api/std/outbox/events/evt-1/retry")

    assert resp.status_code == 200
    assert resp.json() == {"result": {"id": "evt-1", "status": "retried"}}
    retry.assert_called_once_with("evt-1", by_user="admin")


def test_retry_outbox_events_bulk(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {
        "retried": [{"id": "evt-1", "status": "retried"}],
        "skipped": [
            {
                "id": "evt-2",
                "status": "skipped",
                "reason": "status done is not retryable",
            }
        ],
    }
    with patch(
        "data_agent.api.standards_routes._outbox_admin.retry_events",
        return_value=result,
    ) as retry:
        resp = _client().post(
            "/api/std/outbox/events/retry",
            json={"event_ids": ["evt-1", "evt-2"]},
        )

    assert resp.status_code == 200
    assert resp.json() == result
    retry.assert_called_once_with(["evt-1", "evt-2"], by_user="admin")


def test_retry_outbox_events_bulk_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().post(
        "/api/std/outbox/events/retry",
        json={"event_ids": ["evt-1"]},
    )

    assert resp.status_code == 403


def test_retry_outbox_events_rejects_malformed_json(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post(
        "/api/std/outbox/events/retry",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid JSON body"


def test_retry_outbox_events_rejects_empty_bulk(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/outbox/events/retry", json={"event_ids": []})

    assert resp.status_code == 400
    assert resp.json()["error"] == "event_ids must be a non-empty list"


def test_retry_outbox_events_rejects_non_string_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post(
        "/api/std/outbox/events/retry",
        json={"event_ids": ["evt-1", 2]},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "event_ids must contain non-empty strings"
