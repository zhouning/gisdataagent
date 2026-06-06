"""Repository tests for market subscriptions."""
from __future__ import annotations

import uuid

import pytest

from data_agent.standards_platform.market import subscriptions
from data_agent.standards_platform.tests.test_market_catalog import (
    _delete_document,
    _seed_document,
    _seed_version,
)


def _user(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_subscribe_creates_active_subscription(engine):
    token = f"subs-create-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    user = _user("alice")
    try:
        sub = subscriptions.subscribe(
            version_id=version_id,
            subscriber_user_id=user,
        )
        rows = subscriptions.list_subscriptions(subscriber_user_id=user)

        assert sub["status"] == "active"
        assert sub["source_version_id"] == version_id
        assert len(rows) == 1
        assert rows[0]["id"] == sub["id"]
        assert rows[0]["has_update"] is False
    finally:
        _delete_document(engine, doc_id)


def test_subscribe_rejects_non_released_version(engine):
    token = f"subs-draft-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="draft")
    try:
        with pytest.raises(ValueError, match="version must be released"):
            subscriptions.subscribe(
                version_id=version_id,
                subscriber_user_id=_user("alice"),
            )
    finally:
        _delete_document(engine, doc_id)


def test_list_subscriptions_is_scoped_to_user(engine):
    token = f"subs-scope-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    user_a = _user("alice")
    user_b = _user("bob")
    try:
        sub_a = subscriptions.subscribe(
            version_id=version_id,
            subscriber_user_id=user_a,
        )
        subscriptions.subscribe(
            version_id=version_id,
            subscriber_user_id=user_b,
        )

        rows = subscriptions.list_subscriptions(subscriber_user_id=user_a)

        assert [row["id"] for row in rows] == [sub_a["id"]]
    finally:
        _delete_document(engine, doc_id)


def test_list_subscriptions_marks_newer_released_version(engine):
    token = f"subs-update-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    v1 = _seed_version(engine, doc_id, label="v1.0", status="released")
    user = _user("alice")
    try:
        subscriptions.subscribe(version_id=v1, subscriber_user_id=user)
        v2 = _seed_version(engine, doc_id, label="v1.1", status="released")

        row = subscriptions.list_subscriptions(subscriber_user_id=user)[0]

        assert row["latest_version_id"] == v2
        assert row["last_seen_version_id"] == v1
        assert row["has_update"] is True
    finally:
        _delete_document(engine, doc_id)


def test_mark_seen_clears_update_flag(engine):
    token = f"subs-seen-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    v1 = _seed_version(engine, doc_id, label="v1.0", status="released")
    user = _user("alice")
    try:
        sub = subscriptions.subscribe(version_id=v1, subscriber_user_id=user)
        v2 = _seed_version(engine, doc_id, label="v1.1", status="released")

        updated = subscriptions.mark_seen(
            subscription_id=sub["id"],
            subscriber_user_id=user,
        )
        row = subscriptions.list_subscriptions(subscriber_user_id=user)[0]

        assert updated["last_seen_version_id"] == v2
        assert row["has_update"] is False
    finally:
        _delete_document(engine, doc_id)


def test_unsubscribe_cancels_subscription(engine):
    token = f"subs-cancel-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, label="v1.0", status="released")
    user = _user("alice")
    try:
        sub = subscriptions.subscribe(
            version_id=version_id,
            subscriber_user_id=user,
        )
        cancelled = subscriptions.unsubscribe(
            subscription_id=sub["id"],
            subscriber_user_id=user,
        )

        assert cancelled["status"] == "cancelled"
        assert subscriptions.list_subscriptions(subscriber_user_id=user) == []
    finally:
        _delete_document(engine, doc_id)
