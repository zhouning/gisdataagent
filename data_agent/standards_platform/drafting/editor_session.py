"""Clause editor session — acquire/heartbeat/release/save/break_lock.

All five operations open their own transaction on the singleton engine
returned by data_agent.db_engine.get_engine() and emit raw SQL against
std_clause and agent_audit_log.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.drafting.editor_session")


class LockError(Exception):
    """Raised when the caller cannot hold or no longer holds the lock."""

    def __init__(self, message: str, *, holder: str | None = None,
                 expires_at: Any | None = None):
        super().__init__(message)
        self.holder = holder
        self.expires_at = expires_at


class ConflictError(Exception):
    """Optimistic concurrency conflict on save (If-Match mismatch)."""

    def __init__(self, server_checksum: str, server_body_md: str):
        super().__init__("checksum mismatch")
        self.server_checksum = server_checksum
        self.server_body_md = server_body_md


def compute_checksum(body_md: str) -> str:
    """Truncated SHA-256 hex of the markdown body. 16 chars = 64 bits."""
    return hashlib.sha256(body_md.encode("utf-8")).hexdigest()[:16]


_DEFAULT_TTL_MIN = 15


def acquire_lock(clause_id: str, user_id: str,
                 *, ttl_minutes: int = _DEFAULT_TTL_MIN) -> dict:
    """Atomically acquire or renew the edit lock on a clause.

    On first acquire of a clause whose checksum is NULL (P0 backfill case),
    we lazily compute and persist the checksum from the current body_md.
    """
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            SELECT body_md, checksum FROM std_clause WHERE id=:c FOR UPDATE
        """), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        body_md = row.body_md or ""
        checksum = row.checksum or compute_checksum(body_md)

        updated = conn.execute(text("""
            UPDATE std_clause
               SET lock_holder=:u,
                   lock_expires_at=now() + (:ttl || ' minutes')::interval,
                   checksum=:chk
             WHERE id=:c
               AND (lock_holder IS NULL
                    OR lock_holder=:u
                    OR lock_expires_at < now())
            RETURNING body_md, body_html, checksum, lock_expires_at
        """), {"c": clause_id, "u": user_id, "ttl": str(ttl_minutes),
               "chk": checksum}).first()
        if updated is None:
            held = conn.execute(text(
                "SELECT lock_holder, lock_expires_at FROM std_clause "
                "WHERE id=:c"
            ), {"c": clause_id}).first()
            raise LockError("clause is locked by another user",
                            holder=held.lock_holder if held else None,
                            expires_at=held.lock_expires_at if held else None)
        return {
            "body_md": updated.body_md or "",
            "body_html": updated.body_html,
            "checksum": updated.checksum,
            "lock_expires_at": updated.lock_expires_at,
            "lock_token": user_id,
        }


def heartbeat(clause_id: str, user_id: str,
              *, ttl_minutes: int = _DEFAULT_TTL_MIN) -> dict:
    """Extend the lock TTL. Raises LockError if lock no longer held."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            UPDATE std_clause
               SET lock_expires_at = now() + (:ttl || ' minutes')::interval
             WHERE id=:c
               AND lock_holder=:u
               AND (lock_expires_at IS NULL OR lock_expires_at >= now())
            RETURNING lock_expires_at
        """), {"c": clause_id, "u": user_id, "ttl": str(ttl_minutes)}).first()
        if row is None:
            raise LockError("lock no longer held")
        return {"lock_expires_at": row.lock_expires_at}
