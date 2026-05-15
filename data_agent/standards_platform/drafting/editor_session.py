"""Clause editor session — acquire/heartbeat/release/save/break_lock.

All five operations open their own transaction on the singleton engine
returned by data_agent.db_engine.get_engine() and emit raw SQL against
std_clause and agent_audit_log.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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


def _now_utc():
    return datetime.now(timezone.utc)


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


def save_clause(clause_id: str, user_id: str, *,
                if_match_checksum: str,
                body_md: str, body_html: str | None,
                data_elements: list[dict] | None = None) -> dict:
    """Optimistic save. Verifies If-Match checksum and lock ownership.

    If data_elements is provided, diff against existing rows where
    defined_by_clause_id = clause_id (by code) and apply
    insert/update/delete in the same transaction.
    """
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            SELECT checksum, body_md, lock_holder, lock_expires_at,
                   document_version_id
              FROM std_clause WHERE id=:c FOR UPDATE
        """), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        if row.checksum != if_match_checksum:
            raise ConflictError(server_checksum=row.checksum or "",
                                server_body_md=row.body_md or "")
        if (row.lock_holder != user_id
                or row.lock_expires_at is None
                or row.lock_expires_at < _now_utc()):
            raise LockError("lock no longer held")
        new_chk = compute_checksum(body_md)
        updated = conn.execute(text("""
            UPDATE std_clause
               SET body_md=:b, body_html=:h, checksum=:k,
                   updated_at=now(), updated_by=:u
             WHERE id=:c
            RETURNING checksum, updated_at
        """), {"c": clause_id, "u": user_id, "b": body_md,
               "h": body_html, "k": new_chk}).first()

        de_summary = None
        if data_elements is not None:
            de_summary = _diff_data_elements(
                conn, clause_id=clause_id,
                version_id=str(row.document_version_id),
                new_elements=data_elements)

        out = {"checksum": updated.checksum, "updated_at": updated.updated_at}
        if de_summary is not None:
            out["data_elements"] = de_summary
        return out


def release_lock(clause_id: str, user_id: str) -> None:
    """Idempotent release. No-op if user no longer holds the lock."""
    eng = get_engine()
    if eng is None:
        return
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_clause
               SET lock_holder=NULL, lock_expires_at=NULL
             WHERE id=:c AND lock_holder=:u
        """), {"c": clause_id, "u": user_id})


def break_lock(clause_id: str, admin_user_id: str) -> dict:
    """Admin force-break of a clause lock. Writes agent_audit_log entry."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT lock_holder FROM std_clause WHERE id=:c FOR UPDATE"
        ), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        previous_holder = row.lock_holder
        conn.execute(text(
            "UPDATE std_clause SET lock_holder=NULL, lock_expires_at=NULL "
            "WHERE id=:c"
        ), {"c": clause_id})
        meta = {"clause_id": clause_id, "previous_holder": previous_holder}
        conn.execute(text(
            "INSERT INTO agent_audit_log (username, action, details) "
            "VALUES (:u, 'std_clause.lock.break', CAST(:m AS jsonb))"
        ), {"u": admin_user_id, "m": json.dumps(meta)})
        logger.info("clause %s lock broken by %s (was held by %s)",
                    clause_id, admin_user_id, previous_holder)
        return {"previous_holder": previous_holder}


def _diff_data_elements(conn, *, clause_id: str, version_id: str,
                        new_elements: list[dict]) -> dict:
    """Insert/update/delete std_data_element rows attached to clause_id.

    Returns {"inserted": n, "updated": n, "deleted": n}.
    """
    existing = {r.code: r for r in conn.execute(text(
        "SELECT id, code, name_zh, datatype, definition, obligation "
        "FROM std_data_element WHERE defined_by_clause_id=:c"
    ), {"c": clause_id}).fetchall()}

    new_by_code: dict[str, dict] = {}
    for el in new_elements:
        code = (el.get("code") or "").strip()
        if not code:
            continue
        new_by_code[code] = el

    inserted = 0
    updated_n = 0
    deleted = 0

    for code, el in new_by_code.items():
        if code in existing:
            old = existing[code]
            if (old.name_zh != (el.get("name_zh") or "")
                    or (old.datatype or "") != (el.get("datatype") or "")
                    or (old.definition or "") != (el.get("definition") or "")
                    or old.obligation != el.get("obligation", "optional")):
                conn.execute(text("""
                    UPDATE std_data_element
                       SET name_zh=:n, datatype=:t, definition=:d,
                           obligation=:o
                     WHERE id=:i
                """), {"i": old.id,
                       "n": el.get("name_zh", ""),
                       "t": el.get("datatype") or None,
                       "d": el.get("definition") or None,
                       "o": el.get("obligation", "optional")})
                updated_n += 1
        else:
            conn.execute(text("""
                INSERT INTO std_data_element
                  (document_version_id, code, name_zh, datatype, definition,
                   obligation, defined_by_clause_id)
                VALUES (:v, :c, :n, :t, :d, :o, :cl)
            """), {"v": version_id, "c": code,
                   "n": el.get("name_zh", ""),
                   "t": el.get("datatype") or None,
                   "d": el.get("definition") or None,
                   "o": el.get("obligation", "optional"),
                   "cl": clause_id})
            inserted += 1

    for code, old in existing.items():
        if code not in new_by_code:
            conn.execute(text(
                "DELETE FROM std_data_element WHERE id=:i"
            ), {"i": old.id})
            deleted += 1

    return {"inserted": inserted, "updated": updated_n, "deleted": deleted}
