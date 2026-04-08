"""Tests for context_engine module (v19.0)."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from data_agent.context_engine import (
    ContextBlock,
    ContextProvider,
    ContextEngine,
    SemanticLayerProvider,
    KnowledgeBaseProvider,
    KnowledgeGraphProvider,
    ReferenceQueryProvider,
    SuccessStoryProvider,
    MetricDefinitionProvider,
    get_context_engine,
    reset_context_engine,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class StubProvider(ContextProvider):
    """Configurable test provider."""

    def __init__(self, name_="stub", blocks=None, task_types=None, should_fail=False):
        self.name = name_
        self.supports_task_types = task_types
        self._blocks = blocks or []
        self._should_fail = should_fail
        self.call_count = 0

    def get_context(self, query, task_type, user_context, query_embedding=None):
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("provider failure")
        return self._blocks


@pytest.fixture(autouse=True)
def _reset():
    reset_context_engine()
    yield
    reset_context_engine()


def _make_block(provider="test", source="src", content="hello", tokens=10, score=0.5):
    return ContextBlock(
        provider=provider,
        source=source,
        content=content,
        token_count=tokens,
        relevance_score=score,
    )


# ---------------------------------------------------------------------------
# Registration & listing
# ---------------------------------------------------------------------------


def test_register_and_list_providers():
    engine = ContextEngine()
    p1 = StubProvider("alpha")
    p2 = StubProvider("beta", task_types={"qc", "governance"})
    engine.register_provider(p1)
    engine.register_provider(p2)

    info = engine.list_providers()
    names = {p["name"] for p in info}
    assert names == {"alpha", "beta"}
    beta_info = [p for p in info if p["name"] == "beta"][0]
    assert set(beta_info["supports_task_types"]) == {"qc", "governance"}


def test_register_overwrites_same_name():
    engine = ContextEngine()
    engine.register_provider(StubProvider("dup", blocks=[_make_block(score=0.1)]))
    engine.register_provider(StubProvider("dup", blocks=[_make_block(score=0.9)]))
    blocks = engine.prepare("test query")
    assert len(blocks) == 1
    assert blocks[0].relevance_score == 0.9


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


def test_token_budget_truncation():
    engine = ContextEngine(max_tokens=100)
    engine.register_provider(
        StubProvider(
            "big",
            blocks=[
                _make_block(tokens=50, score=1.0, source="a"),
                _make_block(tokens=40, score=0.9, source="b"),
                _make_block(tokens=30, score=0.8, source="c"),
            ],
        )
    )
    selected = engine.prepare("query")
    # 50 + 40 = 90 ≤ 100; 90 + 30 = 120 > 100
    assert len(selected) == 2
    assert selected[0].source == "a"
    assert selected[1].source == "b"


def test_token_budget_override():
    engine = ContextEngine(max_tokens=1000)
    engine.register_provider(
        StubProvider(
            "p",
            blocks=[_make_block(tokens=50, source="x")],
        )
    )
    # Override to 30 — block of 50 tokens won't fit
    selected = engine.prepare("query", token_budget=30)
    assert len(selected) == 0


# ---------------------------------------------------------------------------
# Relevance sorting
# ---------------------------------------------------------------------------


def test_blocks_sorted_by_relevance():
    engine = ContextEngine()
    engine.register_provider(
        StubProvider(
            "p",
            blocks=[
                _make_block(score=0.3, source="low"),
                _make_block(score=0.9, source="high"),
                _make_block(score=0.6, source="mid"),
            ],
        )
    )
    selected = engine.prepare("query")
    assert [b.source for b in selected] == ["high", "mid", "low"]


# ---------------------------------------------------------------------------
# Task-type filtering
# ---------------------------------------------------------------------------


def test_task_type_filter_excludes_provider():
    engine = ContextEngine()
    engine.register_provider(
        StubProvider("qc_only", blocks=[_make_block(source="qc_block")], task_types={"qc"})
    )
    engine.register_provider(
        StubProvider("general", blocks=[_make_block(source="gen_block")])
    )
    # general task type — qc_only should be excluded
    selected = engine.prepare("query", task_type="general")
    sources = {b.source for b in selected}
    assert "gen_block" in sources
    assert "qc_block" not in sources


def test_task_type_filter_includes_matching_provider():
    engine = ContextEngine()
    engine.register_provider(
        StubProvider("qc_only", blocks=[_make_block(source="qc_block")], task_types={"qc"})
    )
    selected = engine.prepare("query", task_type="qc")
    assert any(b.source == "qc_block" for b in selected)


# ---------------------------------------------------------------------------
# Provider error handling
# ---------------------------------------------------------------------------


def test_provider_failure_non_fatal():
    engine = ContextEngine()
    engine.register_provider(StubProvider("failing", should_fail=True))
    engine.register_provider(
        StubProvider("working", blocks=[_make_block(source="ok")])
    )
    selected = engine.prepare("query")
    assert len(selected) == 1
    assert selected[0].source == "ok"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_hit():
    engine = ContextEngine(cache_ttl=60.0)
    provider = StubProvider("p", blocks=[_make_block(source="cached")])
    engine.register_provider(provider)

    result1 = engine.prepare("same query", "general")
    result2 = engine.prepare("same query", "general")
    assert provider.call_count == 1  # second call served from cache
    assert len(result2) == 1


def test_cache_miss_different_query():
    engine = ContextEngine(cache_ttl=60.0)
    provider = StubProvider("p", blocks=[_make_block()])
    engine.register_provider(provider)

    engine.prepare("query A")
    engine.prepare("query B")
    assert provider.call_count == 2


def test_cache_invalidation():
    engine = ContextEngine(cache_ttl=60.0)
    provider = StubProvider("p", blocks=[_make_block()])
    engine.register_provider(provider)

    engine.prepare("query")
    assert provider.call_count == 1

    engine.invalidate_cache()
    engine.prepare("query")
    assert provider.call_count == 2


def test_cache_expiry():
    engine = ContextEngine(cache_ttl=0.1)  # 100ms TTL
    provider = StubProvider("p", blocks=[_make_block()])
    engine.register_provider(provider)

    engine.prepare("query")
    assert provider.call_count == 1

    time.sleep(0.15)  # wait for expiry
    engine.prepare("query")
    assert provider.call_count == 2


# ---------------------------------------------------------------------------
# Empty query
# ---------------------------------------------------------------------------


def test_empty_query_returns_empty():
    engine = ContextEngine()
    engine.register_provider(StubProvider("p", blocks=[_make_block()]))
    assert engine.prepare("") == []
    assert engine.prepare(None) == []  # type: ignore


# ---------------------------------------------------------------------------
# Format context
# ---------------------------------------------------------------------------


def test_format_context():
    engine = ContextEngine()
    blocks = [
        _make_block(provider="kb", source="doc1", content="first"),
        _make_block(provider="sem", source="layer", content="second"),
    ]
    text = engine.format_context(blocks)
    assert "[kb:doc1]" in text
    assert "first" in text
    assert "[sem:layer]" in text
    assert "second" in text


def test_format_context_empty():
    engine = ContextEngine()
    assert engine.format_context([]) == ""


# ---------------------------------------------------------------------------
# Built-in providers (unit tests with mocks)
# ---------------------------------------------------------------------------


@patch("data_agent.semantic_layer.resolve_semantic_context")
def test_semantic_layer_provider(mock_resolve):
    mock_resolve.return_value = {
        "sources": [{"table_name": "dltb", "confidence": 0.9}],
        "matched_columns": {"dlmc": "地类名称"},
    }
    provider = SemanticLayerProvider()
    blocks = provider.get_context("土地利用", "general", {})
    assert len(blocks) == 1
    assert blocks[0].provider == "semantic_layer"
    assert "dltb" in blocks[0].content


@patch("data_agent.semantic_layer.resolve_semantic_context")
def test_semantic_layer_provider_empty(mock_resolve):
    mock_resolve.return_value = {}
    provider = SemanticLayerProvider()
    blocks = provider.get_context("random", "general", {})
    assert blocks == []


@patch("data_agent.knowledge_base.search_kb")
def test_knowledge_base_provider(mock_search):
    mock_search.return_value = [
        {"chunk_id": 1, "content": "kb content here", "score": 0.85, "doc_id": 10, "chunk_index": 0},
    ]
    provider = KnowledgeBaseProvider()
    blocks = provider.get_context("query", "general", {})
    assert len(blocks) == 1
    assert blocks[0].provider == "knowledge_base"
    assert blocks[0].relevance_score == 0.85


@patch("data_agent.knowledge_base.search_kb")
def test_knowledge_base_provider_no_results(mock_search):
    mock_search.return_value = []
    provider = KnowledgeBaseProvider()
    blocks = provider.get_context("query", "general", {})
    assert blocks == []


def test_knowledge_graph_provider_no_assets():
    """KG provider with no asset_ids returns graph stats or empty."""
    with patch("data_agent.knowledge_graph.GeoKnowledgeGraph") as MockKG:
        mock_graph = MagicMock()
        mock_stats = MagicMock()
        mock_stats.node_count = 0
        mock_graph.get_stats.return_value = mock_stats
        MockKG.return_value = mock_graph

        provider = KnowledgeGraphProvider()
        blocks = provider.get_context("query", "general", {})
        assert blocks == []


def test_reference_query_provider_import_error():
    """Before Phase 3, reference_queries module doesn't exist — should return []."""
    provider = ReferenceQueryProvider()
    # Temporarily make import fail
    with patch.dict("sys.modules", {"data_agent.reference_queries": None}):
        blocks = provider.get_context("query", "general", {})
    # Should gracefully return empty (ImportError or other)
    assert isinstance(blocks, list)


def test_success_story_provider_import_error():
    """Before Phase 2, feedback module doesn't exist — should return []."""
    provider = SuccessStoryProvider()
    with patch.dict("sys.modules", {"data_agent.feedback": None}):
        blocks = provider.get_context("query", "general", {})
    assert isinstance(blocks, list)


def test_metric_definition_provider_import_error():
    """Before Phase 4, semantic_model module doesn't exist — should return []."""
    provider = MetricDefinitionProvider()
    with patch.dict("sys.modules", {"data_agent.semantic_model": None}):
        blocks = provider.get_context("query", "general", {})
    assert isinstance(blocks, list)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_context_engine_singleton():
    """get_context_engine() returns same instance."""
    e1 = get_context_engine()
    e2 = get_context_engine()
    assert e1 is e2
    assert len(e1.providers) == 6  # all 6 built-in providers


def test_reset_context_engine():
    e1 = get_context_engine()
    reset_context_engine()
    e2 = get_context_engine()
    assert e1 is not e2
