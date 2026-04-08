"""Tests for context_manager backward compatibility shim (v19.0)."""
import pytest
from unittest.mock import patch

from data_agent.context_manager import ContextManager, ContextBlock, ContextProvider
from data_agent.context_engine import reset_context_engine


class MockLegacyProvider(ContextProvider):
    """Legacy-style provider using old signature."""
    name = "mock_legacy"

    def get_context(self, query, task_type, user_context, query_embedding=None):
        return [
            ContextBlock(
                provider="mock_legacy",
                source="src1",
                content="legacy content",
                token_count=20,
                relevance_score=0.8,
            )
        ]


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_context_engine()
    yield
    reset_context_engine()


@patch("data_agent.knowledge_base._get_embeddings", return_value=[])
@patch("data_agent.semantic_layer.resolve_semantic_context", return_value={})
def test_context_manager_legacy_prepare(_mock_sem, _mock_emb):
    """Legacy (task_type, step, user_context) signature still works."""
    mgr = ContextManager(max_tokens=100_000)
    mgr.register_provider("mock_legacy", MockLegacyProvider())
    selected = mgr.prepare("test", "step1", {"query": "hello"})
    # Should get at least the mock block
    mock_blocks = [b for b in selected if b.provider == "mock_legacy"]
    assert len(mock_blocks) == 1
    assert mock_blocks[0].source == "src1"


@patch("data_agent.knowledge_base._get_embeddings", return_value=[])
@patch("data_agent.semantic_layer.resolve_semantic_context", return_value={})
def test_context_manager_format(_mock_sem, _mock_emb):
    mgr = ContextManager()
    blocks = [
        ContextBlock(
            provider="test", source="source1", content="content1",
            token_count=10, relevance_score=1.0,
        ),
        ContextBlock(
            provider="test", source="source2", content="content2",
            token_count=10, relevance_score=0.9,
        ),
    ]
    formatted = mgr.format_context(blocks)
    assert "source1" in formatted
    assert "content1" in formatted
    assert "source2" in formatted
