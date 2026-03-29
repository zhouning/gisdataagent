"""Tests for context_manager module"""
import pytest
from data_agent.context_manager import ContextManager, ContextBlock, ContextProvider


class MockProvider(ContextProvider):
    def __init__(self, blocks):
        self.blocks = blocks

    def get_context(self, task_type, step, user_context):
        return self.blocks


def test_context_manager_token_budget():
    mgr = ContextManager(max_tokens=100)
    mgr.register_provider("mock", MockProvider([
        ContextBlock("source1", "a" * 200, 50, 1.0),
        ContextBlock("source2", "b" * 200, 40, 0.9),
        ContextBlock("source3", "c" * 200, 30, 0.8),
    ]))

    selected = mgr.prepare("test", "step1", {})
    assert len(selected) == 2
    assert selected[0].source == "source1"
    assert selected[1].source == "source2"


def test_context_manager_relevance_sort():
    mgr = ContextManager(max_tokens=1000)
    mgr.register_provider("mock", MockProvider([
        ContextBlock("low", "content", 10, 0.5),
        ContextBlock("high", "content", 10, 0.9),
        ContextBlock("medium", "content", 10, 0.7),
    ]))

    selected = mgr.prepare("test", "step1", {})
    assert selected[0].source == "high"
    assert selected[1].source == "medium"
    assert selected[2].source == "low"


def test_context_manager_format():
    mgr = ContextManager()
    blocks = [
        ContextBlock("source1", "content1", 10, 1.0),
        ContextBlock("source2", "content2", 10, 0.9),
    ]
    formatted = mgr.format_context(blocks)
    assert "[source1]" in formatted
    assert "content1" in formatted
    assert "[source2]" in formatted
