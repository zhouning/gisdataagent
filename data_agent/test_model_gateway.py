"""Tests for model_gateway module"""
import pytest
from data_agent.model_gateway import ModelRegistry, ModelRouter


def test_model_registry_list():
    models = ModelRegistry.list_models()
    assert len(models) == 3
    assert any(m["name"] == "gemini-2.5-flash" for m in models)


def test_router_task_capability_match():
    router = ModelRouter()
    result = router.route(task_type="classification", quality_requirement="fast")
    assert result == "gemini-2.0-flash"


def test_router_context_size_filter():
    router = ModelRouter()
    result = router.route(context_tokens=500000, quality_requirement="standard")
    assert result == "gemini-2.5-flash"


def test_router_fallback_when_no_match():
    router = ModelRouter()
    result = router.route(task_type="nonexistent_capability")
    assert result == "gemini-2.5-flash"
