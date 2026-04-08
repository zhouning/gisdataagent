"""Tests for redis_client module (v20.0)."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from data_agent.redis_client import (
    check_redis_health,
    get_redis_sync,
    RedisLock,
    reset_redis,
    HAS_REDIS,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_redis()
    yield
    reset_redis()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@patch.dict("os.environ", {"REDIS_URL": ""})
def test_health_no_url():
    reset_redis()
    result = check_redis_health()
    assert result["status"] == "unconfigured"


@patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"})
def test_health_connected():
    if not HAS_REDIS:
        pytest.skip("redis not installed")
    reset_redis()
    result = check_redis_health()
    # Should connect to local Redis (installed by user)
    assert result["status"] == "ok"
    assert "version" in result


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


@patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"})
def test_get_redis_sync():
    if not HAS_REDIS:
        pytest.skip("redis not installed")
    reset_redis()
    r = get_redis_sync()
    assert r is not None
    assert r.ping() is True


@patch.dict("os.environ", {"REDIS_URL": ""})
def test_get_redis_sync_no_url():
    reset_redis()
    r = get_redis_sync()
    assert r is None


# ---------------------------------------------------------------------------
# Distributed Lock
# ---------------------------------------------------------------------------


def test_redis_lock_no_redis():
    """Without Redis, lock always succeeds (single-node fallback)."""
    import asyncio

    async def _test():
        with patch("data_agent.redis_client.get_redis", new_callable=AsyncMock, return_value=None):
            lock = RedisLock("test-lock", ttl=5)
            acquired = await lock.acquire()
            assert acquired is True
            await lock.release()

    asyncio.get_event_loop().run_until_complete(_test())


@patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"})
def test_redis_lock_acquire_release():
    """Test actual Redis lock acquire and release."""
    if not HAS_REDIS:
        pytest.skip("redis not installed")
    import asyncio

    async def _test():
        from data_agent.redis_client import get_redis
        r = await get_redis()
        if not r:
            pytest.skip("Redis not available")

        lock = RedisLock("test-v20-lock", ttl=5)
        acquired = await lock.acquire(timeout=2)
        assert acquired is True

        # Key should exist in Redis
        val = await r.get("lock:test-v20-lock")
        assert val is not None

        await lock.release()

        # Key should be gone
        val = await r.get("lock:test-v20-lock")
        assert val is None

    asyncio.get_event_loop().run_until_complete(_test())


@patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"})
def test_redis_lock_context_manager():
    if not HAS_REDIS:
        pytest.skip("redis not installed")
    import asyncio

    async def _test():
        from data_agent.redis_client import get_redis
        r = await get_redis()
        if not r:
            pytest.skip("Redis not available")

        async with RedisLock("test-ctx-lock", ttl=5):
            val = await r.get("lock:test-ctx-lock")
            assert val is not None

        # After context exit, lock released
        val = await r.get("lock:test-ctx-lock")
        assert val is None

    asyncio.get_event_loop().run_until_complete(_test())
