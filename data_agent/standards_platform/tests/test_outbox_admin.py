"""Tests for admin outbox dead-letter operations."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform import outbox as ob
from data_agent.standards_platform import outbox_admin


@pytest.fixture
def clean_outbox(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_outbox"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_outbox"))


def _event(payload: dict | None = None,
           event_type: str = "derivation_requested") -> str:
    return ob.enqueue(event_type, payload or {"version_id": str(uuid.uuid4())})


def _set_status(engine, event_id: str, status: str, *, attempts: int = 0,
                last_error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_outbox "
            "SET status=:s, attempts=:a, last_error=:e, next_attempt_at=now() "
            "WHERE id=:i"
        ), {"s": status, "a": attempts, "e": last_error, "i": event_id})


def _row(engine, event_id: str):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT status, attempts, last_error, next_attempt_at "
            "FROM std_outbox WHERE id=:i"
        ), {"i": event_id}).mappings().first()


def _db_now(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT clock_timestamp()")).scalar()


def _audit_count(engine, *, event_id: str,
                 action: str = "std_outbox.retry") -> int:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM agent_audit_log "
            "WHERE action=:a AND details->>'event_id'=:i"
        ), {"a": action, "i": event_id}).scalar()


def test_list_events_filters_failed_newest_first(clean_outbox):
    old_id = _event({"order": "old"}, "extract_requested")
    new_id = _event({"order": "new"}, "derivation_requested")
    pending_id = _event({"order": "pending"}, "embed_requested")
    _set_status(clean_outbox, old_id, "failed", attempts=5, last_error="old")
    _set_status(clean_outbox, new_id, "failed", attempts=5, last_error="new")
    _set_status(clean_outbox, pending_id, "pending")

    events = outbox_admin.list_events(status="failed", limit=10, offset=0)

    assert [e["id"] for e in events] == [new_id, old_id]
    assert events[0]["event_type"] == "derivation_requested"
    assert events[0]["payload"] == {"order": "new"}
    assert events[0]["last_error"] == "new"


def test_list_events_filters_by_event_type(clean_outbox):
    keep_id = _event({"kind": "keep"}, "derivation_requested")
    skip_id = _event({"kind": "skip"}, "extract_requested")
    _set_status(clean_outbox, keep_id, "failed", attempts=5)
    _set_status(clean_outbox, skip_id, "failed", attempts=5)

    events = outbox_admin.list_events(
        status="failed", event_type="derivation_requested", limit=10, offset=0
    )

    assert [e["id"] for e in events] == [keep_id]


def test_get_counts_includes_zero_statuses(clean_outbox):
    failed_id = _event()
    _set_status(clean_outbox, failed_id, "failed", attempts=5)

    counts = outbox_admin.get_counts()

    assert counts["failed"] == 1
    assert counts["pending"] == 0
    assert counts["in_flight"] == 0
    assert counts["done"] == 0


def test_retry_failed_event_resets_to_pending(clean_outbox):
    event_id = _event({"retry": "failed"})
    _set_status(clean_outbox, event_id, "failed", attempts=5,
                last_error="boom")

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {"id": event_id, "status": "retried"}
    assert row["status"] == "pending"
    assert row["attempts"] == 5
    assert row["last_error"] == "boom"
    assert row["next_attempt_at"] <= _db_now(clean_outbox)


def test_retry_failed_event_writes_audit(clean_outbox):
    event_id = _event({"retry": "audit"})
    _set_status(clean_outbox, event_id, "failed", attempts=5,
                last_error="boom")

    result = outbox_admin.retry_event(event_id, by_user="admin")

    assert result == {"id": event_id, "status": "retried"}
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT username, action, details "
            "FROM agent_audit_log "
            "WHERE action='std_outbox.retry' "
            "AND details->>'event_id'=:i "
            "ORDER BY created_at DESC "
            "LIMIT 1"
        ), {"i": event_id}).mappings().first()
    assert row is not None
    assert row["username"] == "admin"
    assert row["details"]["event_id"] == event_id
    assert row["details"]["event_type"] == "derivation_requested"
    assert row["details"]["previous_status"] == "failed"


def test_retry_in_flight_event_resets_to_pending(clean_outbox):
    event_id = _event({"retry": "in_flight"})
    _set_status(clean_outbox, event_id, "in_flight", attempts=2,
                last_error="stuck")

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {"id": event_id, "status": "retried"}
    assert row["status"] == "pending"
    assert row["attempts"] == 2


def test_retry_done_event_is_skipped(clean_outbox):
    event_id = _event({"retry": "done"})
    _set_status(clean_outbox, event_id, "done", attempts=0)

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {
        "id": event_id,
        "status": "skipped",
        "reason": "status done is not retryable",
    }
    assert row["status"] == "done"


def test_retry_done_event_does_not_write_audit(clean_outbox):
    event_id = _event({"retry": "no-audit"})
    _set_status(clean_outbox, event_id, "done", attempts=0)
    before = _audit_count(clean_outbox, event_id=event_id)

    result = outbox_admin.retry_event(event_id, by_user="admin")

    assert result["status"] == "skipped"
    assert _audit_count(clean_outbox, event_id=event_id) == before


def test_retry_missing_event_is_skipped(clean_outbox):
    missing_id = str(uuid.uuid4())

    result = outbox_admin.retry_event(missing_id, by_user="admin")

    assert result == {
        "id": missing_id,
        "status": "skipped",
        "reason": "not found",
    }


def test_retry_malformed_event_id_is_skipped(clean_outbox):
    result = outbox_admin.retry_event("not-a-uuid", by_user="admin")

    assert result == {
        "id": "not-a-uuid",
        "status": "skipped",
        "reason": "not found",
    }


def test_retry_events_returns_mixed_results(clean_outbox):
    failed_id = _event({"bulk": "failed"})
    done_id = _event({"bulk": "done"})
    missing_id = str(uuid.uuid4())
    _set_status(clean_outbox, failed_id, "failed", attempts=5)
    _set_status(clean_outbox, done_id, "done")

    result = outbox_admin.retry_events(
        [failed_id, done_id, missing_id], by_user="admin"
    )

    assert result["retried"] == [{"id": failed_id, "status": "retried"}]
    assert result["skipped"] == [
        {"id": done_id, "status": "skipped",
         "reason": "status done is not retryable"},
        {"id": missing_id, "status": "skipped", "reason": "not found"},
    ]


def test_retry_events_skips_later_duplicate_ids(clean_outbox):
    failed_id = _event({"bulk": "duplicate"})
    _set_status(clean_outbox, failed_id, "failed", attempts=5)

    result = outbox_admin.retry_events(
        [failed_id, failed_id], by_user="admin"
    )
    row = _row(clean_outbox, failed_id)

    assert result["retried"] == [{"id": failed_id, "status": "retried"}]
    assert result["skipped"] == [
        {"id": failed_id, "status": "skipped", "reason": "duplicate id"},
    ]
    assert row["status"] == "pending"
