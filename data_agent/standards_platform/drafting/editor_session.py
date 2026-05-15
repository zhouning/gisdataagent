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
