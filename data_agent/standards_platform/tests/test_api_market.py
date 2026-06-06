"""API tests for /api/std/market/* endpoints."""
from __future__ import annotations

import uuid

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_clause,
    _seed_document,
    _seed_version,
)


def test_market_catalog_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    r = _client().get("/api/std/market/standards")

    assert r.status_code == 401


def test_market_diff_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    r = _client().get(
        "/api/std/market/diff"
        f"?source_version_id={uuid.uuid4()}&target_version_id={uuid.uuid4()}"
    )

    assert r.status_code == 401


def test_market_catalog_rejects_invalid_pagination(monkeypatch):
    _auth_user(monkeypatch, role="viewer")

    bad_limit = _client().get("/api/std/market/standards?limit=bad")
    bad_offset = _client().get("/api/std/market/standards?offset=bad")
    negative_offset = _client().get("/api/std/market/standards?offset=-1")
    zero_limit = _client().get("/api/std/market/standards?limit=0")

    assert bad_limit.status_code == 400
    assert bad_offset.status_code == 400
    assert negative_offset.status_code == 400
    assert zero_limit.status_code == 400


def test_market_catalog_happy_path(monkeypatch, engine):
    token = f"api-catalog-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, status="released")
    try:
        _auth_user(monkeypatch, role="viewer")
        r = _client().get(f"/api/std/market/standards?query={token}")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["version_id"] == version_id
        assert body["items"][0]["asset_counts"]["clauses"] == 0
    finally:
        _delete_document(engine, doc_id)


def test_market_diff_requires_both_version_ids(monkeypatch):
    _auth_user(monkeypatch, role="viewer")

    r = _client().get("/api/std/market/diff")

    assert r.status_code == 400
    assert r.json() == {
        "error": "source_version_id and target_version_id required"
    }


def test_market_diff_missing_version_404(monkeypatch, fresh_clause):
    _, _, version_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    r = _client().get(
        "/api/std/market/diff"
        f"?source_version_id={version_id}&target_version_id={uuid.uuid4()}"
    )

    assert r.status_code == 404
    assert r.json() == {"error": "version not found"}


def test_market_diff_happy_path(monkeypatch, engine):
    token = f"api-diff-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    source = _seed_version(engine, doc_id, label="v1.0", status="released")
    target = _seed_version(engine, doc_id, label="v1.1", status="released")
    _seed_clause(engine, doc_id, source, "1", clause_no="1",
                 heading="Old", body_md="old")
    _seed_clause(engine, doc_id, target, "1", clause_no="1",
                 heading="Old", body_md="new")
    try:
        _auth_user(monkeypatch, role="viewer")
        r = _client().get(
            "/api/std/market/diff"
            f"?source_version_id={source}&target_version_id={target}"
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_version_id"] == source
        assert body["target_version_id"] == target
        assert body["summary"]["changed"] == 1
        assert body["changes"][0]["change_type"] == "changed"
    finally:
        _delete_document(engine, doc_id)
