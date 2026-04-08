"""Tests for Redis cache migration (v20.0)."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from data_agent.context_engine import ContextEngine, ContextBlock, reset_context_engine


@pytest.fixture(autouse=True)
def _reset():
    reset_context_engine()
    yield
    reset_context_engine()


# ---------------------------------------------------------------------------
# ContextEngine Redis cache
# ---------------------------------------------------------------------------


def test_context_engine_cache_writes_to_redis():
    """When Redis is available, cache writes go to Redis."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # cache miss

    class StubProvider:
        name = "stub"
        supports_task_types = None
        def get_context(self, query, task_type, user_context, query_embedding=None):
            return [ContextBlock(provider="stub", source="s", content="hello",
                                 token_count=5, relevance_score=0.8)]

    with patch("data_agent.redis_client.get_redis_sync", return_value=mock_redis):
        engine = ContextEngine(cache_ttl=60)
        engine.register_provider(StubProvider())
        blocks = engine.prepare("test query")
        assert len(blocks) == 1

        # Verify Redis setex was called
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0].startswith("context:cache:")


def test_context_engine_cache_reads_from_redis():
    """Cache hit from Redis when memory cache is empty."""
    cached_data = json.dumps([{
        "provider": "stub", "source": "s", "content": "cached",
        "token_count": 5, "relevance_score": 0.8,
        "compressible": True, "metadata": {},
    }])
    mock_redis = MagicMock()
    mock_redis.get.return_value = cached_data

    with patch("data_agent.redis_client.get_redis_sync", return_value=mock_redis):
        engine = ContextEngine(cache_ttl=60)
        # No providers registered — if we get results, they came from cache
        blocks = engine.prepare("test query")
        assert len(blocks) == 1
        assert blocks[0].content == "cached"


def test_context_engine_invalidate_clears_redis():
    """invalidate_cache() clears both memory and Redis."""
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = ["context:cache:abc", "context:cache:def"]

    with patch("data_agent.redis_client.get_redis_sync", return_value=mock_redis):
        engine = ContextEngine()
        engine._cache["key"] = (time.time(), [])
        engine.invalidate_cache()

        assert len(engine._cache) == 0
        mock_redis.scan_iter.assert_called_once()
        assert mock_redis.delete.call_count == 2


def test_context_engine_cache_no_redis_fallback():
    """Without Redis, memory cache still works."""
    with patch("data_agent.redis_client.get_redis_sync", return_value=None):
        engine = ContextEngine(cache_ttl=60)

        class StubProvider:
            name = "stub"
            supports_task_types = None
            call_count = 0
            def get_context(self, query, task_type, user_context, query_embedding=None):
                self.call_count += 1
                return [ContextBlock(provider="stub", source="s", content="ok",
                                     token_count=5, relevance_score=0.8)]

        p = StubProvider()
        engine.register_provider(p)

        engine.prepare("same query")
        engine.prepare("same query")
        assert p.call_count == 1  # second call from memory cache


# ---------------------------------------------------------------------------
# semantic_layer Redis cache
# ---------------------------------------------------------------------------


@patch("data_agent.semantic_layer.get_engine")
def test_semantic_invalidate_clears_redis(mock_get_engine):
    """invalidate_semantic_cache() deletes Redis keys."""
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = []

    with patch("data_agent.redis_client.get_redis_sync", return_value=mock_redis):
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
        mock_redis.delete.assert_called_with("semantic:sources")


@patch("data_agent.semantic_layer.get_engine")
def test_semantic_invalidate_no_redis(mock_get_engine):
    """invalidate_semantic_cache() works without Redis (memory only)."""
    with patch("data_agent.redis_client.get_redis_sync", return_value=None):
        from data_agent.semantic_layer import invalidate_semantic_cache
        # Should not raise
        invalidate_semantic_cache()
