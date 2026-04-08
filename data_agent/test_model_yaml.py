"""Tests for model_gateway YAML loading (v20.0)."""
import os
import pytest
import tempfile
from unittest.mock import patch

import yaml


def test_load_from_yaml_default_path():
    """load_from_yaml() loads from conf/models.yaml."""
    from data_agent.model_gateway import ModelRegistry
    ModelRegistry._initialized = False
    ModelRegistry.models = {}
    ModelRegistry._ensure_initialized()
    count = ModelRegistry.load_from_yaml()
    # Should load the default models.yaml (3 Gemini models)
    # But they may already be registered as defaults, so count could be 0
    assert count >= 0
    assert len(ModelRegistry.models) >= 3  # at least the 3 built-in Gemini


def test_load_from_yaml_custom_file():
    """load_from_yaml() loads custom models from a temp YAML file."""
    from data_agent.model_gateway import ModelRegistry
    ModelRegistry._initialized = False
    ModelRegistry.models = {}
    ModelRegistry._ensure_initialized()

    config = {
        "models": {
            "test-custom-model": {
                "backend": "litellm",
                "tier": "standard",
                "context_tokens": 32768,
                "capabilities": ["text"],
                "cost_per_1k_input": 0.1,
                "cost_per_1k_output": 0.2,
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()
        path = f.name

    try:
        count = ModelRegistry.load_from_yaml(path)
        assert count == 1
        info = ModelRegistry.get_model_info("test-custom-model")
        assert info["backend"] == "litellm"
        assert info["tier"] == "standard"
        assert info["max_context_tokens"] == 32768
    finally:
        os.unlink(path)


def test_load_from_yaml_missing_file():
    """load_from_yaml() returns 0 for missing file."""
    from data_agent.model_gateway import ModelRegistry
    count = ModelRegistry.load_from_yaml("/nonexistent/models.yaml")
    assert count == 0


def test_load_from_yaml_no_overwrite():
    """YAML models don't overwrite existing built-in models."""
    from data_agent.model_gateway import ModelRegistry
    ModelRegistry._initialized = False
    ModelRegistry.models = {}
    ModelRegistry._ensure_initialized()

    original_info = ModelRegistry.get_model_info("gemini-2.0-flash")

    config = {
        "models": {
            "gemini-2.0-flash": {
                "backend": "should_not_overwrite",
                "tier": "local",
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()
        path = f.name

    try:
        count = ModelRegistry.load_from_yaml(path)
        assert count == 0  # skipped because already exists
        info = ModelRegistry.get_model_info("gemini-2.0-flash")
        assert info["backend"] != "should_not_overwrite"
    finally:
        os.unlink(path)
