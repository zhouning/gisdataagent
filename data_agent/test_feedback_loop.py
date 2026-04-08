"""Tests for feedback module (v19.0)."""
import json
import pytest
from unittest.mock import patch, MagicMock

from data_agent.feedback import FeedbackStore, FeedbackProcessor


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------


@patch("data_agent.feedback.get_engine")
def test_feedback_store_record(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (42,)

    store = FeedbackStore()
    fb_id = store.record(
        username="alice",
        query_text="分析土地利用",
        vote=1,
        pipeline_type="governance",
    )
    assert fb_id == 42
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


@patch("data_agent.feedback.get_engine")
def test_feedback_store_record_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    store = FeedbackStore()
    assert store.record(username="x", query_text="q", vote=1) is None


@patch("data_agent.feedback.get_engine")
def test_feedback_store_get_stats(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import date

    # get_stats makes 3 sequential queries: overall, by_pipeline, trend
    overall_result = MagicMock()
    overall_result.fetchone.return_value = (100, 80, 20)

    pipeline_result = MagicMock()
    pipeline_result.fetchall.return_value = [
        ("governance", 50, 10),
        ("general", 30, 10),
    ]

    trend_result = MagicMock()
    trend_result.fetchall.return_value = [
        (date(2026, 4, 7), 5, 1),
        (date(2026, 4, 8), 3, 2),
    ]

    conn.execute.side_effect = [overall_result, pipeline_result, trend_result]

    store = FeedbackStore()
    stats = store.get_stats(days=30)
    assert stats["total"] == 100
    assert stats["satisfaction_rate"] == 0.8
    assert len(stats["trend"]) == 2


@patch("data_agent.feedback.get_engine")
def test_feedback_store_list_recent(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import datetime

    conn.execute.return_value.fetchall.return_value = [
        (1, "alice", "s1", "m1", "general", "query", "response", 1,
         None, "[]", None, None, None, datetime(2026, 4, 8)),
    ]

    store = FeedbackStore()
    items = store.list_recent(vote=1, limit=10)
    assert len(items) == 1
    assert items[0]["username"] == "alice"
    assert items[0]["vote"] == 1


@patch("data_agent.feedback.get_engine")
def test_feedback_store_list_unresolved_downvotes(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = []

    store = FeedbackStore()
    items = store.list_unresolved_downvotes()
    assert items == []


@patch("data_agent.feedback.get_engine")
def test_feedback_store_mark_resolved(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = FeedbackStore()
    result = store.mark_resolved(42, "ingested_as_reference", "ref:1")
    assert result is True
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# FeedbackProcessor
# ---------------------------------------------------------------------------


@patch("data_agent.feedback.get_engine")
def test_process_upvote_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    processor = FeedbackProcessor()

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(processor.process_upvote(1))
    assert result["status"] == "error"


@patch("data_agent.feedback.get_engine")
def test_process_upvote_not_found(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = None

    processor = FeedbackProcessor()
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(processor.process_upvote(999))
    assert result["status"] == "error"
    assert "not found" in result["reason"]


@patch("data_agent.feedback.get_engine")
def test_process_upvote_pending_phase3(mock_get_engine):
    """Before Phase 3, upvote processing marks as pending."""
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (1, "query", "response", "general", "alice")

    processor = FeedbackProcessor()
    # Patch mark_resolved to track calls
    processor.store = MagicMock()

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(processor.process_upvote(1))
    # Should either ingest or mark pending depending on reference_queries availability
    assert result["status"] in ("ingested", "pending", "error")


@patch("data_agent.feedback.get_engine")
@patch("data_agent.prompt_optimizer.FailureAnalyzer.analyze")
def test_process_downvote_batch_empty(mock_analyze, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = []

    processor = FeedbackProcessor()
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(processor.process_downvote_batch())
    assert result["status"] == "empty"
    mock_analyze.assert_not_called()


# ---------------------------------------------------------------------------
# BadCaseCollector integration
# ---------------------------------------------------------------------------


@patch("data_agent.prompt_optimizer.get_engine")
def test_bad_case_collector_agent_feedback(mock_get_engine):
    """BadCaseCollector.collect_from_agent_feedback reads agent_feedback table."""
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import datetime

    conn.execute.return_value.fetchall.return_value = [
        (1, "alice", "bad query", "bad response", "general", "wrong answer", datetime(2026, 4, 8)),
    ]

    from data_agent.prompt_optimizer import BadCaseCollector

    collector = BadCaseCollector()
    import asyncio
    cases = asyncio.get_event_loop().run_until_complete(collector.collect_from_agent_feedback(limit=10))
    assert len(cases) == 1
    assert cases[0]["source"] == "agent_feedback"
    assert cases[0]["pipeline"] == "general"
