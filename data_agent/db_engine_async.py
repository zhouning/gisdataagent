"""
Async database engine — asyncpg connection pool singleton (v18.0).

Provides a high-performance async connection pool for use in Starlette/ASGI
route handlers.  Falls back gracefully when credentials are unavailable.

Usage::

    pool = await get_async_pool()
    rows = await fetch_async("SELECT * FROM t WHERE id = $1", id)
    await execute_async("INSERT INTO t (name) VALUES ($1)", name)

The pool is created lazily on first call and reused for the process lifetime.
Call ``close_async_pool()`` during shutdown.
"""
import asyncio
import os
from typing import Any

import asyncpg

from .user_context import current_user_id, current_user_role

_async_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


def _build_dsn() -> str | None:
    """Build a PostgreSQL DSN from environment variables."""
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE")
    if not all([user, password, db]):
        return None
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def get_async_pool() -> asyncpg.Pool | None:
    """Return a singleton asyncpg connection pool.

    Pool settings: min_size=5, max_size=20, command_timeout=60s.
    Returns None if database credentials are not configured.
    """
    global _async_pool
    if _async_pool is not None:
        return _async_pool

    async with _pool_lock:
        # Double-check after acquiring lock
        if _async_pool is not None:
            return _async_pool

        dsn = _build_dsn()
        if not dsn:
            return None

        _async_pool = await asyncpg.create_pool(
            dsn,
            min_size=int(os.environ.get("ASYNC_POOL_MIN", "5")),
            max_size=int(os.environ.get("ASYNC_POOL_MAX", "20")),
            command_timeout=60,
            max_inactive_connection_lifetime=300,
        )
        return _async_pool


async def close_async_pool():
    """Close the async connection pool during shutdown."""
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


async def _inject_user_context_async(conn: asyncpg.Connection):
    """Inject RLS user context into an async connection."""
    uid = current_user_id.get("anonymous")
    role = current_user_role.get("viewer")
    await conn.execute(
        "SELECT set_config('app.current_user', $1, true)", uid
    )
    await conn.execute(
        "SELECT set_config('app.current_user_role', $1, true)", role
    )


async def fetch_async(query: str, *args, inject_user: bool = False) -> list[asyncpg.Record]:
    """Execute a query and return all rows.

    Args:
        query: SQL with $1, $2 positional placeholders.
        *args: Parameter values.
        inject_user: If True, inject RLS user context before query.

    Returns list of asyncpg.Record objects (dict-like access).
    """
    pool = await get_async_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        if inject_user:
            await _inject_user_context_async(conn)
        return await conn.fetch(query, *args)


async def fetchrow_async(query: str, *args, inject_user: bool = False) -> asyncpg.Record | None:
    """Execute a query and return the first row, or None."""
    pool = await get_async_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        if inject_user:
            await _inject_user_context_async(conn)
        return await conn.fetchrow(query, *args)


async def fetchval_async(query: str, *args, column: int = 0,
                         inject_user: bool = False) -> Any:
    """Execute a query and return a single value."""
    pool = await get_async_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        if inject_user:
            await _inject_user_context_async(conn)
        return await conn.fetchval(query, *args, column=column)


async def execute_async(query: str, *args, inject_user: bool = False) -> str:
    """Execute a query without returning rows (INSERT/UPDATE/DELETE).

    Returns command tag string (e.g. 'INSERT 0 1').
    """
    pool = await get_async_pool()
    if pool is None:
        return ""
    async with pool.acquire() as conn:
        if inject_user:
            await _inject_user_context_async(conn)
        return await conn.execute(query, *args)


async def get_async_pool_status() -> dict | None:
    """Return async pool statistics for monitoring."""
    if _async_pool is None:
        return None
    return {
        "size": _async_pool.get_size(),
        "free_size": _async_pool.get_idle_size(),
        "min_size": _async_pool.get_min_size(),
        "max_size": _async_pool.get_max_size(),
    }
