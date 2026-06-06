"""Admin-safe std_outbox listing, counts, and retry operations."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import text

from ..db_engine import get_engine
from ..observability import get_logger

logger = get_logger("standards_platform.outbox_admin")

STATUSES = frozenset({"pending", "in_flight", "done", "failed"})
RETRYABLE_STATUSES = frozenset({"failed", "in_flight"})


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _validate_list_args(status: str | None, limit: int, offset: int) -> None:
    if status is not None and status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError("offset must be an integer")
    if offset < 0:
        raise ValueError("offset must be non-negative")


def _row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in row.items()}


def list_events(status: str | None = None,
                event_type: str | None = None,
                limit: int = 50,
                offset: int = 0) -> list[dict]:
    """List outbox events with admin filters, newest first."""
    _validate_list_args(status, limit, offset)
    eng = get_engine()
    if eng is None:
        return []

    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status is not None:
        clauses.append("status = :status")
        params["status"] = status
    if event_type is not None:
        clauses.append("event_type = :event_type")
        params["event_type"] = event_type
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with eng.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, event_type, payload, created_at, processed_at,
                   attempts, last_error, next_attempt_at, status
              FROM std_outbox
              {where}
             ORDER BY created_at DESC, id DESC
             LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return [_row_to_event(dict(row)) for row in rows]


def get_counts() -> dict[str, int]:
    """Return counts for all std_outbox statuses, including zeroes."""
    counts = {status: 0 for status in ("pending", "in_flight", "done", "failed")}
    eng = get_engine()
    if eng is None:
        return counts

    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, COUNT(*) AS n FROM std_outbox GROUP BY status"
        )).mappings().all()

    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    return counts


def retry_event(event_id: str, by_user: str) -> dict:
    """Reset one failed or in-flight event back to pending."""
    event_id_str = str(event_id)
    try:
        event_uuid = UUID(event_id_str)
    except ValueError:
        return {"id": event_id_str, "status": "skipped", "reason": "not found"}

    eng = get_engine()
    if eng is None:
        return {"id": event_id_str, "status": "skipped", "reason": "not found"}

    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT event_type, status FROM std_outbox WHERE id=:id FOR UPDATE"
        ), {"id": str(event_uuid)}).mappings().first()
        if row is None:
            return {"id": event_id_str, "status": "skipped",
                    "reason": "not found"}

        status = str(row["status"])
        if status not in RETRYABLE_STATUSES:
            return {
                "id": event_id_str,
                "status": "skipped",
                "reason": f"status {status} is not retryable",
            }

        conn.execute(text(
            "UPDATE std_outbox "
            "SET status='pending', next_attempt_at=now() "
            "WHERE id=:id"
        ), {"id": str(event_uuid)})
        audit_details = {
            "event_id": event_id_str,
            "event_type": str(row["event_type"]),
            "previous_status": status,
        }
        conn.execute(text(
            "INSERT INTO agent_audit_log (username, action, details) "
            "VALUES (:u, 'std_outbox.retry', CAST(:d AS jsonb))"
        ), {"u": by_user,
            "d": json.dumps(audit_details, ensure_ascii=False)})

    logger.info("retried std_outbox event id=%s by_user=%s", event_id_str,
                by_user)
    return {"id": event_id_str, "status": "retried"}


def retry_events(event_ids: Iterable[str], by_user: str) -> dict:
    """Retry events in input order, grouping retried and skipped results."""
    retried: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for event_id in event_ids:
        event_id_str = str(event_id)
        if event_id_str in seen:
            skipped.append({
                "id": event_id_str,
                "status": "skipped",
                "reason": "duplicate id",
            })
            continue

        seen.add(event_id_str)
        result = retry_event(event_id_str, by_user=by_user)
        if result["status"] == "retried":
            retried.append(result)
        else:
            skipped.append(result)

    return {"retried": retried, "skipped": skipped}
