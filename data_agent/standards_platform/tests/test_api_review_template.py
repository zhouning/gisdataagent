"""API tests for /api/std/reviews/template/{version_id}."""
from __future__ import annotations

import uuid

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)


def test_review_template_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    r = _client().get(f"/api/std/reviews/template/{uuid.uuid4()}")

    assert r.status_code == 401


def test_review_template_missing_version_404(monkeypatch, engine):
    _auth_user(monkeypatch, role="viewer")

    r = _client().get(f"/api/std/reviews/template/{uuid.uuid4()}")

    assert r.status_code == 404
    assert r.json() == {"error": "version not found"}


def test_review_template_happy_path(monkeypatch, fresh_clause):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    r = _client().get(f"/api/std/reviews/template/{ver_id}")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_id"] == "default_review_v1"
    assert body["version_id"] == ver_id
    assert body["version_status"] == "draft"
    assert [step["id"] for step in body["steps"]] == [
        "draft",
        "start_review",
        "audit_references",
        "resolve_comments",
        "close_round",
        "approved",
    ]
    assert body["summary"]["open_round_id"] is None


def test_review_template_route_coexists_with_round_routes(
    monkeypatch, fresh_clause
):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    rounds = _client().get("/api/std/reviews/rounds")
    template = _client().get(f"/api/std/reviews/template/{ver_id}")

    assert rounds.status_code == 200
    assert "rounds" in rounds.json()
    assert template.status_code == 200
    assert template.json()["version_id"] == ver_id
