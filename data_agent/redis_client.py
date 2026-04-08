"""
Unified Redis client — shared connection for all modules (v20.0).

Provides async and sync clients, distributed lock, and graceful degradation.
Reuses the redis.asyncio dependency already present for stream_engine.py.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

from .observability import get_logger

logger = get_logger("redis_client")

try:
    import redis as redis_sync_lib
    import redis.asyncio as redis_async_lib
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_async_redis: Optional[object] = None
_sync_redis: Optional[object] = None
_redis_url: str = ""


async def get_redis():
    """Get or create shared async Redis connection. Returns None if unavailable."""
    global _async_redis, _redis_url
    if not HAS_REDIS:
        return None
    if _async_redis is not None:
        return _async_redis
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        _async_redis = redis_async_lib.from_url(url, decode_responses=True)
        await _async_redis.ping()
        _redis_url = url
        logger.info("Redis async client connected: %s", url.split("@")[-1])
        return _async_redis
    except Exception as e:
        logger.warning("Redis async connection failed: %s", e)
        _async_redis = None
        return None


def get_redis_sync():
    """Get or create shared sync Redis connection. Returns None if unavailable."""
    global _sync_redis
    if not HAS_REDIS:
        return None
    if _sync_redis is not None:
        try:
            _sync_redis.ping()
            return _sync_redis
        except Exception:
            _sync_redis = None
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        _sync_redis = redis_sync_lib.from_url(url, decode_responses=True)
        _sync_redis.ping()
        return _sync_redis
    except Exception as e:
        logger.debug("Redis sync connection failed: %s", e)
        _sync_redis = None
        return None


async def close_redis() -> None:
    """Close Redis connections on shutdown."""
    global _async_redis, _sync_redis
    if _async_redis:
        try:
            await _async_redis.aclose()
        except Exception:
            pass
        _async_redis = None
    if _sync_redis:
        try:
            _sync_redis.close()
        except Exception:
            pass
        _sync_redis = None
    logger.info("Redis connections closed")


def check_redis_health() -> dict:
    """Check Redis connectivity (sync). Used by health.py."""
    if not HAS_REDIS:
        return {"status": "unconfigured", "detail": "redis package not installed"}
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return {"status": "unconfigured", "detail": "REDIS_URL not set"}
    try:
        r = get_redis_sync()
        if r and r.ping():
            info = r.info("server")
            return {
                "status": "ok",
                "version": info.get("redis_version", "unknown"),
                "url": url.split("@")[-1],
            }
        return {"status": "error", "detail": "ping failed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def reset_redis() -> None:
    """Reset singletons — for testing only."""
    global _async_redis, _sync_redis
    _async_redis = None
    _sync_redis = None


# ---------------------------------------------------------------------------
# Distributed Lock
# ---------------------------------------------------------------------------


class RedisLock:
    """Distributed lock using Redis SETNX + TTL.

    Usage:
        async with RedisLock("my-lock", ttl=10):
            # critical section
    """

    def __init__(self, name: str, ttl: int = 10):
        self.key = f"lock:{name}"
        self.ttl = ttl
        self._token = uuid.uuid4().hex
        self._acquired = False

    async def acquire(self, timeout: float = 10.0) -> bool:
        """Try to acquire the lock within timeout seconds."""
        r = await get_redis()
        if not r:
            # No Redis — always succeed (single-node fallback)
            self._acquired = True
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await r.set(self.key, self._token, nx=True, ex=self.ttl):
                self._acquired = True
                return True
            await _sleep(0.05)
        return False

    async def release(self) -> None:
        """Release the lock (only if we own it)."""
        if not self._acquired:
            return
        r = await get_redis()
        if not r:
            self._acquired = False
            return
        # Lua script for atomic check-and-delete
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            await r.eval(script, 1, self.key, self._token)
        except Exception:
            pass
        self._acquired = False

    async def __aenter__(self):
        acquired = await self.acquire()
        if not acquired:
            raise TimeoutError(f"Could not acquire lock '{self.key}'")
        return self

    async def __aexit__(self, *args):
        await self.release()


async def _sleep(seconds: float):
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)
