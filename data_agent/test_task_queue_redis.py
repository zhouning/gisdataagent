"""Tests for task_queue Redis backend (v20.0)."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from data_agent.task_queue import TaskQueue, TaskJob, reset_task_queue, _RK_QUEUE, _RK_JOB


@pytest.fixture(autouse=True)
def _reset():
    reset_task_queue()
    yield
    reset_task_queue()


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# Redis backend submit
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
@patch("data_agent.redis_client.get_redis_sync")
def test_submit_redis_backend(mock_redis_sync, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    mock_redis = MagicMock()
    mock_redis_sync.return_value = mock_redis

    tq = TaskQueue(max_concurrent=3)
    tq._use_redis = True
    tq._redis = mock_redis

    job_id = tq.submit("alice", "分析土地利用", "general", priority=3)
    assert job_id is not None

    # Verify Redis HSET was called for job data
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert f"{_RK_JOB}{job_id}" == call_args[0][0]

    # Verify Redis ZADD was called for queue
    mock_redis.zadd.assert_called_once()
    zadd_args = mock_redis.zadd.call_args
    assert zadd_args[0][0] == _RK_QUEUE


@patch("data_agent.task_queue.get_engine")
def test_submit_memory_fallback(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    tq = TaskQueue(max_concurrent=3)
    tq._use_redis = False

    job_id = tq.submit("alice", "test query", "general")
    assert job_id is not None
    assert not tq._pending.empty()


# ---------------------------------------------------------------------------
# Redis backend get_status
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
def test_get_status_from_redis(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    mock_redis = MagicMock()
    job_data = {"job_id": "abc123", "status": "completed", "user_id": "alice"}
    mock_redis.hget.return_value = json.dumps(job_data)

    tq = TaskQueue()
    tq._use_redis = True
    tq._redis = mock_redis

    # Not in memory, should check Redis
    result = tq.get_status("abc123")
    assert result is not None
    assert result["job_id"] == "abc123"
    mock_redis.hget.assert_called_once_with(f"{_RK_JOB}abc123", "data")


@patch("data_agent.task_queue.get_engine")
def test_get_status_memory_first(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    tq = TaskQueue()
    tq._use_redis = True
    tq._redis = MagicMock()

    # Add job to memory
    job = TaskJob(job_id="mem123", user_id="bob", prompt="test")
    tq._jobs["mem123"] = job

    result = tq.get_status("mem123")
    assert result is not None
    assert result["job_id"] == "mem123"
    # Redis should NOT be called since job is in memory
    tq._redis.hget.assert_not_called()


# ---------------------------------------------------------------------------
# Redis fallback on error
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
def test_submit_redis_error_falls_back(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    mock_redis = MagicMock()
    mock_redis.hset.side_effect = Exception("Redis down")

    tq = TaskQueue()
    tq._use_redis = True
    tq._redis = mock_redis

    # Should not raise, falls back to memory
    job_id = tq.submit("alice", "test", "general")
    assert job_id is not None
    assert not tq._pending.empty()


# ---------------------------------------------------------------------------
# Queue stats
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
def test_queue_stats(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    tq = TaskQueue()
    tq.submit("alice", "q1", "general")
    tq.submit("alice", "q2", "governance")

    stats = tq.queue_stats
    assert stats["total"] == 2
    assert stats["by_status"]["queued"] == 2


# ---------------------------------------------------------------------------
# Init Redis
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
@patch("data_agent.redis_client.get_redis_sync")
def test_init_redis_success(mock_redis_sync, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    mock_redis_sync.return_value = MagicMock()

    tq = TaskQueue()
    tq._init_redis()
    assert tq._use_redis is True


@patch("data_agent.task_queue.get_engine")
@patch("data_agent.redis_client.get_redis_sync", return_value=None)
def test_init_redis_unavailable(mock_redis_sync, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    tq = TaskQueue()
    tq._init_redis()
    assert tq._use_redis is False


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@patch("data_agent.task_queue.get_engine")
def test_cancel_queued_job(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    tq = TaskQueue()
    job_id = tq.submit("alice", "test", "general")
    assert tq.cancel(job_id) is True
    assert tq._jobs[job_id].status == "cancelled"
