"""API tests for Standards Platform batch rollback."""
from __future__ import annotations

from unittest.mock import patch

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)


def test_batch_rollback_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1"]})

    assert resp.status_code == 401


def test_batch_rollback_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1"]})

    assert resp.status_code == 403


def test_batch_rollback_rejects_malformed_json(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post(
        "/api/std/derive/rollback",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid JSON body"


def test_batch_rollback_rejects_invalid_json_encoding(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post(
        "/api/std/derive/rollback",
        content=b"\xff",
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid JSON body"


def test_batch_rollback_rejects_empty_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": []})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must be a non-empty list"


def test_batch_rollback_rejects_non_string_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1", 2]})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must contain non-empty strings"


def test_batch_rollback_rejects_too_many_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    version_ids = [f"v-{i}" for i in range(51)]

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": version_ids})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must contain at most 50 ids"


def test_batch_rollback_admin_delegates(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {
        "rolled_back": [{"version_id": "v1", "status": "rolled_back",
                         "by_strategy": {}}],
        "skipped": [{"version_id": "v2", "reason": "not found"}],
    }
    with patch(
        "data_agent.api.standards_routes._link_repo.rollback_versions",
        return_value=result,
    ) as rollback:
        resp = _client().post(
            "/api/std/derive/rollback",
            json={"version_ids": ["v1", "v2"], "reason": "ops rollback"},
        )

    assert resp.status_code == 200
    assert resp.json() == result
    rollback.assert_called_once_with(
        version_ids=["v1", "v2"],
        by_user="admin",
        reason="ops rollback",
    )


def test_batch_rollback_default_reason(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {"rolled_back": [], "skipped": []}
    with patch(
        "data_agent.api.standards_routes._link_repo.rollback_versions",
        return_value=result,
    ) as rollback:
        resp = _client().post("/api/std/derive/rollback",
                              json={"version_ids": ["v1"]})

    assert resp.status_code == 200
    rollback.assert_called_once_with(
        version_ids=["v1"],
        by_user="admin",
        reason="batch rollback by admin",
    )


def test_batch_rollback_non_string_reason_uses_default(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {"rolled_back": [], "skipped": []}
    with patch(
        "data_agent.api.standards_routes._link_repo.rollback_versions",
        return_value=result,
    ) as rollback:
        resp = _client().post(
            "/api/std/derive/rollback",
            json={"version_ids": ["v1"], "reason": 123},
        )

    assert resp.status_code == 200
    rollback.assert_called_once_with(
        version_ids=["v1"],
        by_user="admin",
        reason="batch rollback by admin",
    )
