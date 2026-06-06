"""Repository tests for Standards Platform market listing review."""
from __future__ import annotations

import uuid

import pytest

from data_agent.standards_platform.market import catalog, listings
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_document,
    _seed_version,
)


def test_submit_listing_creates_submitted_row_for_released_version(engine):
    token = f"listing-submit-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        listing = listings.submit_listing(
            version_id=version_id,
            submitted_by="editor-a",
            notes="ready",
        )

        assert listing["version_id"] == version_id
        assert listing["document_id"] == doc_id
        assert listing["status"] == "submitted"
        assert listing["submitted_by"] == "editor-a"
        assert listing["notes"] == "ready"
        assert listing["reviewed_by"] is None
    finally:
        _delete_document(engine, doc_id)


def test_submit_listing_rejects_non_released_version(engine):
    token = f"listing-draft-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    draft_id = _seed_version(engine, doc_id, label="v1.0", status="draft")
    try:
        with pytest.raises(ValueError, match="version must be released"):
            listings.submit_listing(
                version_id=draft_id,
                submitted_by="editor-a",
            )
    finally:
        _delete_document(engine, doc_id)


def test_submitted_listing_is_hidden_until_approved(engine):
    token = f"listing-visible-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        assert catalog.list_market_standards(query=token)["total"] == 1

        listing = listings.submit_listing(
            version_id=version_id,
            submitted_by="editor-a",
        )
        submitted_catalog = catalog.list_market_standards(query=token)
        approved = listings.review_listing(
            listing_id=listing["id"],
            decision="approved",
            reviewed_by="admin-a",
            review_notes="ok",
        )
        approved_catalog = catalog.list_market_standards(query=token)

        assert submitted_catalog["total"] == 0
        assert approved["status"] == "approved"
        assert approved["reviewed_by"] == "admin-a"
        assert approved_catalog["total"] == 1
        assert approved_catalog["items"][0]["market_status"] == "approved"
        assert approved_catalog["items"][0]["market_listing_id"] == listing["id"]
    finally:
        _delete_document(engine, doc_id)


def test_rejected_listing_stays_hidden_and_records_review(engine):
    token = f"listing-reject-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    try:
        listing = listings.submit_listing(
            version_id=version_id,
            submitted_by="editor-a",
        )
        rejected = listings.review_listing(
            listing_id=listing["id"],
            decision="rejected",
            reviewed_by="admin-a",
            review_notes="missing owner info",
        )
        catalog_result = catalog.list_market_standards(query=token)

        assert rejected["status"] == "rejected"
        assert rejected["review_notes"] == "missing owner info"
        assert catalog_result["total"] == 0
    finally:
        _delete_document(engine, doc_id)


def test_list_listings_supports_status_filter(engine):
    token_a = f"listing-filter-a-{uuid.uuid4().hex[:8]}"
    token_b = f"listing-filter-b-{uuid.uuid4().hex[:8]}"
    doc_a = _seed_document(engine, token_a)
    doc_b = _seed_document(engine, token_b)
    version_a = _seed_version(engine, doc_a, label="v1.0", status="released")
    version_b = _seed_version(engine, doc_b, label="v1.0", status="released")
    try:
        submitted = listings.submit_listing(
            version_id=version_a,
            submitted_by="editor-a",
        )
        approved = listings.submit_listing(
            version_id=version_b,
            submitted_by="editor-b",
        )
        listings.review_listing(
            listing_id=approved["id"],
            decision="approved",
            reviewed_by="admin-a",
        )

        result = listings.list_listings(status="submitted")
        ids = {item["id"] for item in result["items"]}

        assert submitted["id"] in ids
        assert approved["id"] not in ids
    finally:
        _delete_document(engine, doc_a)
        _delete_document(engine, doc_b)
