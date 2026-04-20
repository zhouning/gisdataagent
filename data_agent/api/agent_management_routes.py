"""
Agent Management API — alias/display_name/pin/hide for @mention targets.
"""
from typing import Optional
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from .helpers import _get_user_from_request, _set_user_context

logger = get_logger("agent_management")


def list_aliases_for_user(user_id: str) -> list[dict]:
    """Return all alias records for a user."""
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT handle, aliases, display_name, pinned, hidden
                FROM agent_aliases
                WHERE user_id = :user_id
            """), {"user_id": user_id})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_aliases_for_user failed: %s", e)
        return []


def upsert_alias(
    user_id: str,
    handle: str,
    aliases: Optional[list[str]] = None,
    display_name: Optional[str] = None,
) -> None:
    """Insert or update alias/display_name for (user_id, handle)."""
    engine = get_engine()
    if engine is None:
        return
    aliases = aliases or []
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_aliases (user_id, handle, aliases, display_name, updated_at)
                VALUES (:user_id, :handle, :aliases, :display_name, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    aliases = EXCLUDED.aliases,
                    display_name = EXCLUDED.display_name,
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "aliases": aliases,
                "display_name": display_name,
            })
    except Exception as e:
        logger.error("upsert_alias failed: %s", e)
        raise


def set_flag(user_id: str, handle: str, flag: str, value: bool) -> None:
    """Set pinned or hidden flag for a handle. flag must be 'pinned' or 'hidden'."""
    if flag not in ("pinned", "hidden"):
        raise ValueError(f"Invalid flag: {flag}")
    engine = get_engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT INTO agent_aliases (user_id, handle, {flag}, updated_at)
                VALUES (:user_id, :handle, :value, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    {flag} = EXCLUDED.{flag},
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "value": value,
            })
    except Exception as e:
        logger.error("set_flag failed: %s", e)
        raise
