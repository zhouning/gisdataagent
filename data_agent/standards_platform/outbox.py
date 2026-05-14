"""Outbox primitives — at-least-once event delivery backed by std_outbox table.

Safe for multi-worker deployment via SELECT ... FOR UPDATE SKIP LOCKED.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterable

from sqlalchemy import text

from ..db_engine import get_engine
from ..observability import get_logger

logger = get_logger("standards_platform.outbox")

# Allowed event types — mirror std_outbox CHECK constraint.
EVENT_TYPES = frozenset({
    "extract_requested", "structure_requested", "embed_requested",
    "dedupe_requested", "web_snapshot_requested", "version_released",
    "clause_updated", "derivation_requested", "invalidation_needed",
})


def enqueue(event_type: str, payload: dict) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type!r}")
    evt_id = str(uuid.uuid4())
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.connect() as conn:
        conn.execute(text(
            "INSERT INTO std_outbox (id, event_type, payload) "
            "VALUES (:i, :e, CAST(:p AS jsonb))"
        ), {"i": evt_id, "e": event_type,
            "p": json.dumps(payload, ensure_ascii=False)})
        conn.commit()
    return evt_id


def claim_batch(limit: int = 10) -> list[dict]:
    """Atomically claim up to `limit` pending events that are due."""
    eng = get_engine()
    if eng is None:
        return []
    with eng.connect() as conn:
        rows = conn.execute(text("""
            UPDATE std_outbox
               SET status = 'in_flight'
             WHERE id IN (
                 SELECT id FROM std_outbox
                  WHERE status = 'pending'
                    AND next_attempt_at <= now()
                  ORDER BY next_attempt_at
                  LIMIT :lim
                  FOR UPDATE SKIP LOCKED
             )
         RETURNING id, event_type, payload, attempts
        """), {"lim": limit}).mappings().all()
        conn.commit()
        return [{**dict(r), "id": str(r["id"])} for r in rows]


def complete(evt_id: str) -> None:
    eng = get_engine()
    if eng is None:
        return
    with eng.connect() as conn:
        conn.execute(text(
            "UPDATE std_outbox SET status='done', processed_at=now() WHERE id=:i"
        ), {"i": evt_id})
        conn.commit()


def fail(evt_id: str, error: str, *, max_attempts: int = 5) -> None:
    """Increment attempts; schedule retry with exponential backoff; or mark failed."""
    eng = get_engine()
    if eng is None:
        return
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT attempts FROM std_outbox WHERE id=:i FOR UPDATE"
        ), {"i": evt_id}).first()
        if row is None:
            return
        attempts = row.attempts + 1
        if attempts >= max_attempts:
            conn.execute(text("""
                UPDATE std_outbox
                   SET status='failed', attempts=:a, last_error=:e,
                       processed_at=now()
                 WHERE id=:i
            """), {"i": evt_id, "a": attempts, "e": error[:2000]})
        else:
            # Exponential backoff: 2^attempts * 30s, capped at 1h.
            conn.execute(text("""
                UPDATE std_outbox
                   SET status='pending', attempts=:a, last_error=:e,
                       next_attempt_at = now() + (LEAST(3600, POWER(2, :a) * 30) || ' seconds')::interval
                 WHERE id=:i
            """), {"i": evt_id, "a": attempts, "e": error[:2000]})
        conn.commit()
