"""API tests for market organization access controls."""
from __future__ import annotations

import uuid

from data_agent.standards_platform.tests.test_api_standards import _client
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_document,
    _seed_version,
)


def _auth_user_with_org(monkeypatch, *, username: str, role: str,
                        org_id: str | None = None):
    class U:
        pass
    u = U()
    u.identifier = username
    u.metadata = {"role": role}
    if org_id is not None:
        u.metadata["org_id"] = org_id
    monkeypatch.setattr("data_agent.api.helpers._get_user_from_request",
                        lambda r: u)


def _submit_and_approve(monkeypatch, version_id: str, *,
                        visibility_scope: str,
                        owner_org_id: str | None = None,
                        allowed_org_ids: list[str] | None = None) -> dict:
    _auth_user_with_org(
        monkeypatch, username="editor-a", role="standard_editor",
        org_id=owner_org_id or "org-a",
    )
    payload = {
        "version_id": version_id,
        "visibility_scope": visibility_scope,
        "allowed_org_ids": allowed_org_ids or [],
    }
    if owner_org_id is not None:
        payload["owner_org_id"] = owner_org_id
    submitted = _client().post("/api/std/market/listings", json=payload)
    assert submitted.status_code == 201, submitted.text

    _auth_user_with_org(monkeypatch, username="admin-a", role="admin",
                        org_id="ops")
    approved = _client().post(
        f"/api/std/market/listings/{submitted.json()['id']}/review",
        json={"decision": "approved"},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_market_catalog_filters_by_user_org_metadata(monkeypatch, engine):
    token = f"api-org-filter-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        listing = _submit_and_approve(
            monkeypatch,
            version_id,
            visibility_scope="organization",
            owner_org_id="org-a",
        )

        _auth_user_with_org(monkeypatch, username="viewer-a", role="viewer",
                            org_id="org-a")
        owner_org = _client().get(f"/api/std/market/standards?query={token}")

        _auth_user_with_org(monkeypatch, username="viewer-b", role="viewer",
                            org_id="org-b")
        other_org = _client().get(f"/api/std/market/standards?query={token}")

        assert listing["owner_org_id"] == "org-a"
        assert owner_org.status_code == 200
        assert owner_org.json()["total"] == 1
        assert other_org.status_code == 200
        assert other_org.json()["total"] == 0
    finally:
        _delete_document(engine, doc_id)


def test_market_catalog_allows_additional_org_ids(monkeypatch, engine):
    token = f"api-org-allowed-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _submit_and_approve(
            monkeypatch,
            version_id,
            visibility_scope="organization",
            owner_org_id="org-a",
            allowed_org_ids=["org-b"],
        )

        _auth_user_with_org(monkeypatch, username="viewer-b", role="viewer",
                            org_id="org-b")
        response = _client().get(f"/api/std/market/standards?query={token}")

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["allowed_org_ids"] == ["org-b"]
    finally:
        _delete_document(engine, doc_id)


def test_market_submit_defaults_owner_org_from_metadata(monkeypatch, engine):
    token = f"api-org-default-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        _auth_user_with_org(monkeypatch, username="editor-a",
                            role="standard_editor", org_id="org-a")
        response = _client().post(
            "/api/std/market/listings",
            json={
                "version_id": version_id,
                "visibility_scope": "organization",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["owner_org_id"] == "org-a"
    finally:
        _delete_document(engine, doc_id)


def test_market_visibility_patch_changes_catalog_access(monkeypatch, engine):
    token = f"api-org-patch-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        listing = _submit_and_approve(
            monkeypatch,
            version_id,
            visibility_scope="public",
            owner_org_id="org-a",
        )

        _auth_user_with_org(monkeypatch, username="viewer-b", role="viewer",
                            org_id="org-b")
        before = _client().get(f"/api/std/market/standards?query={token}")

        _auth_user_with_org(monkeypatch, username="admin-a", role="admin",
                            org_id="ops")
        patched = _client().patch(
            f"/api/std/market/listings/{listing['id']}/visibility",
            json={
                "visibility_scope": "organization",
                "owner_org_id": "org-a",
                "allowed_org_ids": [],
            },
        )

        _auth_user_with_org(monkeypatch, username="viewer-b", role="viewer",
                            org_id="org-b")
        other_org = _client().get(f"/api/std/market/standards?query={token}")

        _auth_user_with_org(monkeypatch, username="viewer-a", role="viewer",
                            org_id="org-a")
        owner_org = _client().get(f"/api/std/market/standards?query={token}")

        assert before.json()["total"] == 1
        assert patched.status_code == 200, patched.text
        assert patched.json()["visibility_scope"] == "organization"
        assert other_org.json()["total"] == 0
        assert owner_org.json()["total"] == 1
    finally:
        _delete_document(engine, doc_id)


def test_market_visibility_patch_is_admin_only_and_validates_scope(monkeypatch):
    listing_id = str(uuid.uuid4())
    _auth_user_with_org(monkeypatch, username="viewer-a", role="viewer",
                        org_id="org-a")
    forbidden = _client().patch(
        f"/api/std/market/listings/{listing_id}/visibility",
        json={"visibility_scope": "public"},
    )

    _auth_user_with_org(monkeypatch, username="admin-a", role="admin",
                        org_id="ops")
    invalid = _client().patch(
        f"/api/std/market/listings/{listing_id}/visibility",
        json={"visibility_scope": "partner"},
    )
    missing = _client().patch(
        f"/api/std/market/listings/{listing_id}/visibility",
        json={"visibility_scope": "public"},
    )

    assert forbidden.status_code == 403
    assert invalid.status_code == 400
    assert missing.status_code == 404
