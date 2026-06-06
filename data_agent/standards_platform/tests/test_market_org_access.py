"""Repository tests for market organization access controls."""
from __future__ import annotations

import uuid

import pytest

from data_agent.standards_platform.market import catalog, listings
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_document,
    _seed_version,
)


def _approved_listing(
    engine,
    token: str,
    *,
    visibility_scope: str,
    owner_org_id: str | None = None,
    allowed_org_ids: list[str] | None = None,
    submitted_by: str = "editor-a",
) -> tuple[str, str, dict]:
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    listing = listings.submit_listing(
        version_id=version_id,
        submitted_by=submitted_by,
        visibility_scope=visibility_scope,
        owner_org_id=owner_org_id,
        allowed_org_ids=allowed_org_ids or [],
    )
    approved = listings.review_listing(
        listing_id=listing["id"],
        decision="approved",
        reviewed_by="admin-a",
    )
    return doc_id, version_id, approved


def test_public_listing_is_visible_to_any_org(engine):
    token = f"org-public-{uuid.uuid4().hex[:8]}"
    doc_id, _, listing = _approved_listing(
        engine, token, visibility_scope="public", owner_org_id="org-a",
    )
    try:
        result = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )

        assert result["total"] == 1
        assert result["items"][0]["market_listing_id"] == listing["id"]
        assert result["items"][0]["visibility_scope"] == "public"
    finally:
        _delete_document(engine, doc_id)


def test_organization_listing_is_visible_to_owner_org_and_admin(engine):
    token = f"org-owner-{uuid.uuid4().hex[:8]}"
    doc_id, _, _ = _approved_listing(
        engine, token, visibility_scope="organization", owner_org_id="org-a",
    )
    try:
        owner_org = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-a",
            viewer_role="viewer",
            viewer_org_id="org-a",
        )
        other_org = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )
        admin = catalog.list_market_standards(
            query=token,
            viewer_user_id="admin-a",
            viewer_role="admin",
            viewer_org_id="org-b",
        )

        assert owner_org["total"] == 1
        assert other_org["total"] == 0
        assert admin["total"] == 1
    finally:
        _delete_document(engine, doc_id)


def test_allowed_org_ids_grant_catalog_access(engine):
    token = f"org-allowed-{uuid.uuid4().hex[:8]}"
    doc_id, _, _ = _approved_listing(
        engine,
        token,
        visibility_scope="organization",
        owner_org_id="org-a",
        allowed_org_ids=["org-b"],
    )
    try:
        result = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )

        assert result["total"] == 1
        assert result["items"][0]["allowed_org_ids"] == ["org-b"]
    finally:
        _delete_document(engine, doc_id)


def test_private_listing_is_visible_to_submitter_owner_and_admin(engine):
    token = f"org-private-{uuid.uuid4().hex[:8]}"
    doc_id, _, _ = _approved_listing(
        engine,
        token,
        visibility_scope="private",
        owner_org_id="org-a",
        submitted_by="editor-a",
    )
    try:
        submitter = catalog.list_market_standards(
            query=token,
            viewer_user_id="editor-a",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )
        owner = catalog.list_market_standards(
            query=token,
            viewer_user_id="market-admin",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )
        other = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )
        admin = catalog.list_market_standards(
            query=token,
            viewer_user_id="admin-a",
            viewer_role="admin",
            viewer_org_id="org-b",
        )

        assert submitter["total"] == 1
        assert owner["total"] == 1
        assert other["total"] == 0
        assert admin["total"] == 1
    finally:
        _delete_document(engine, doc_id)


def test_update_listing_visibility_changes_catalog_access(engine):
    token = f"org-update-{uuid.uuid4().hex[:8]}"
    doc_id, _, listing = _approved_listing(
        engine, token, visibility_scope="public", owner_org_id="org-a",
    )
    try:
        assert catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )["total"] == 1

        updated = listings.update_listing_visibility(
            listing_id=listing["id"],
            visibility_scope="organization",
            owner_org_id="org-a",
            allowed_org_ids=[],
        )

        org_b = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-b",
            viewer_role="viewer",
            viewer_org_id="org-b",
        )
        org_a = catalog.list_market_standards(
            query=token,
            viewer_user_id="viewer-a",
            viewer_role="viewer",
            viewer_org_id="org-a",
        )

        assert updated["visibility_scope"] == "organization"
        assert org_b["total"] == 0
        assert org_a["total"] == 1
    finally:
        _delete_document(engine, doc_id)


def test_invalid_organization_visibility_requires_owner_org(engine):
    token = f"org-invalid-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        with pytest.raises(ValueError, match="owner_org_id required"):
            listings.submit_listing(
                version_id=version_id,
                submitted_by="editor-a",
                visibility_scope="organization",
            )
    finally:
        _delete_document(engine, doc_id)
