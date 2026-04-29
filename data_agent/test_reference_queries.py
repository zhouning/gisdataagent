"""Tests for reference_queries module (v19.0)."""
import json
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from data_agent.reference_queries import ReferenceQueryStore, fetch_nl2sql_few_shots


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.get_engine")
@patch("data_agent.knowledge_base._get_embeddings", return_value=[[0.1] * 768])
def test_add_reference_query(mock_emb, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    # search returns empty (no duplicates)
    conn.execute.return_value.fetchall.return_value = []
    # insert returns id
    conn.execute.return_value.fetchone.return_value = (1,)

    store = ReferenceQueryStore()
    ref_id = store.add(
        query_text="统计耕地面积",
        description="test",
        response_summary="SELECT SUM(area) FROM dltb WHERE dlmc='耕地'",
        pipeline_type="general",
        source="manual",
    )
    assert ref_id is not None


@patch("data_agent.reference_queries.get_engine")
def test_add_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    store = ReferenceQueryStore()
    assert store.add(query_text="test") is None


@patch("data_agent.reference_queries.get_engine")
def test_get_reference_query(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import datetime

    conn.execute.return_value.fetchone.return_value = (
        1, "query", "desc", "response", "[]", "general", "nl2sql",
        "manual", None, 5, 3, None, None, "alice",
        datetime(2026, 4, 8), datetime(2026, 4, 8),
    )

    store = ReferenceQueryStore()
    item = store.get(1)
    assert item is not None
    assert item["query_text"] == "query"
    assert item["use_count"] == 5


@patch("data_agent.reference_queries.get_engine")
def test_get_not_found(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = None

    store = ReferenceQueryStore()
    assert store.get(999) is None


@patch("data_agent.reference_queries.get_engine")
def test_update(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = ReferenceQueryStore()
    assert store.update(1, description="updated") is True
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


@patch("data_agent.reference_queries.get_engine")
def test_update_no_valid_fields(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = ReferenceQueryStore()
    assert store.update(1, invalid_field="x") is False


@patch("data_agent.reference_queries.get_engine")
def test_delete(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = ReferenceQueryStore()
    assert store.delete(1) is True


@patch("data_agent.reference_queries.get_engine")
def test_list(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = []

    store = ReferenceQueryStore()
    items = store.list(pipeline_type="general")
    assert items == []


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.get_engine")
@patch("data_agent.knowledge_base._get_embeddings")
def test_search(mock_emb, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    # Create a normalized embedding
    vec = np.random.randn(768).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_emb.return_value = [vec.tolist()]

    conn.execute.return_value.fetchall.return_value = [
        (1, "similar query", "desc", "response", "[]", "general", "nl2sql",
         "manual", None, 3, 2, vec.tolist()),
    ]

    store = ReferenceQueryStore()
    results = store.search("test query", top_k=3)
    assert len(results) == 1
    assert results[0]["id"] == 1
    assert results[0]["score"] > 0.9  # same vector, should be ~1.0


@patch("data_agent.reference_queries.get_engine")
@patch("data_agent.knowledge_base._get_embeddings", return_value=[])
def test_search_no_embedding(mock_emb, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = ReferenceQueryStore()
    results = store.search("test")
    assert results == []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.get_engine")
def test_stats(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (10, 5, 3, 2)

    store = ReferenceQueryStore()
    s = store.stats()
    assert s["total"] == 10
    assert s["auto"] == 5


# ---------------------------------------------------------------------------
# NL2SQL few-shot
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.get_engine")
@patch("data_agent.knowledge_base._get_embeddings")
def test_fetch_nl2sql_few_shots(mock_emb, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    vec = np.random.randn(768).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_emb.return_value = [vec.tolist()]

    conn.execute.return_value.fetchall.return_value = [
        (1, "统计耕地面积", "", "SELECT SUM(zmj) FROM dltb WHERE dlmc='耕地'",
         "[]", "general", "nl2sql", "manual", None, 5, 3, vec.tolist()),
    ]

    result = fetch_nl2sql_few_shots("统计林地面积")
    assert "参考查询示例" in result
    assert "统计耕地面积" in result


@patch("data_agent.reference_queries.get_engine")
@patch("data_agent.knowledge_base._get_embeddings", return_value=[])
def test_fetch_nl2sql_few_shots_empty(mock_emb, mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    result = fetch_nl2sql_few_shots("test")
    assert result == ""


# ---------------------------------------------------------------------------
# Increment use count
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.get_engine")
def test_increment_use_count(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = ReferenceQueryStore()
    store.increment_use_count(1, success=True)
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# NL2SQL pattern seeding
# ---------------------------------------------------------------------------


@patch("data_agent.reference_queries.ReferenceQueryStore.add")
def test_seed_nl2sql_patterns_calls_add_twice(mock_add):
    mock_add.return_value = 99
    from data_agent.seed_nl2sql_patterns import seed_nl2sql_patterns
    result = seed_nl2sql_patterns(created_by="tester")
    assert mock_add.call_count == 2
    assert result == [99, 99]
    for call in mock_add.call_args_list:
        assert call.kwargs["task_type"] == "nl2sql"
        assert call.kwargs["source"] == "benchmark_pattern"


@patch("data_agent.reference_queries.ReferenceQueryStore.add")
def test_seed_nl2sql_patterns_sql_shapes(mock_add):
    mock_add.return_value = 1
    from data_agent.seed_nl2sql_patterns import seed_nl2sql_patterns
    seed_nl2sql_patterns(created_by="tester")
    sqls = [call.kwargs["response_summary"] for call in mock_add.call_args_list]
    assert any("ST_DWithin" in sql and '"Floor" > 30' in sql for sql in sqls)
    assert any("SUM(ST_Area(ST_Intersection" in sql and "/ 10000.0" in sql for sql in sqls)


@patch("data_agent.reference_queries.ReferenceQueryStore.add", side_effect=[1, 2, 1, 2])
def test_seed_nl2sql_patterns_is_idempotent_via_store(mock_add):
    from data_agent.seed_nl2sql_patterns import seed_nl2sql_patterns
    first = seed_nl2sql_patterns(created_by="tester")
    second = seed_nl2sql_patterns(created_by="tester")
    assert first == [1, 2]
    assert second == [1, 2]
