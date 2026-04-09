"""Tests for model configuration manager and Gemma 4 support (v23.0)."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestGemma4Registration(unittest.TestCase):
    """Verify Gemma 4 31B is properly registered in ModelRegistry."""

    def test_gemma4_in_builtins(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()
        ModelRegistry._ensure_initialized()
        info = ModelRegistry.get_model_info("gemma-4-31b-it")
        assert info["backend"] == "gemini"
        assert info["tier"] == "standard"
        assert info["online"] is True
        assert info["max_context_tokens"] == 256_000

    def test_detect_backend_gemma_prefix(self):
        from data_agent.model_gateway import _detect_backend
        assert _detect_backend("gemma-4-31b-it") == "gemini"
        assert _detect_backend("gemma-3-4b") == "gemini"

    def test_detect_backend_gemini_unchanged(self):
        from data_agent.model_gateway import _detect_backend
        assert _detect_backend("gemini-2.5-flash") == "gemini"

    def test_detect_backend_litellm_slash(self):
        from data_agent.model_gateway import _detect_backend
        assert _detect_backend("openai/gpt-4o") == "litellm"

    @patch("data_agent.model_gateway._create_gemini_model")
    def test_create_model_gemma4_uses_gemini_backend(self, mock_create):
        from data_agent.model_gateway import create_model, ModelRegistry
        ModelRegistry.reset()
        mock_create.return_value = MagicMock()
        create_model("gemma-4-31b-it")
        mock_create.assert_called_once_with("gemma-4-31b-it")

    def test_gemma4_listed_in_online_models(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()
        ModelRegistry._ensure_initialized()
        online = ModelRegistry.get_online_models()
        assert "gemma-4-31b-it" in online


class TestLiteLlmExtraParams(unittest.TestCase):
    """Verify extra_headers and extra_body are stored in registry."""

    def test_extra_params_stored(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()
        ModelRegistry._ensure_initialized()
        ModelRegistry.register_model(
            "test-vllm-model",
            backend="litellm",
            extra_headers={"Authorization": "Bearer xxx"},
            extra_body={"enable_thinking": True},
        )
        info = ModelRegistry.get_model_info("test-vllm-model")
        assert info["extra_headers"] == {"Authorization": "Bearer xxx"}
        assert info["extra_body"] == {"enable_thinking": True}

    def test_model_id_override(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()
        ModelRegistry._ensure_initialized()
        ModelRegistry.register_model(
            "gemma-vllm",
            backend="litellm",
            model_id="openai/google/gemma-4-31B-it",
        )
        info = ModelRegistry.get_model_info("gemma-vllm")
        assert info["model_id"] == "openai/google/gemma-4-31B-it"


class TestModelConfigManager(unittest.TestCase):
    """Test ModelConfigManager with env var fallback (no DB)."""

    def test_load_env_fallback(self):
        from data_agent.model_config import ModelConfigManager
        mgr = ModelConfigManager()
        with patch.dict(os.environ, {"MODEL_FAST": "gemma-4-31b-it"}):
            mgr.load()
            assert mgr.get_tier_model("fast") == "gemma-4-31b-it"

    def test_default_values(self):
        from data_agent.model_config import ModelConfigManager
        mgr = ModelConfigManager()
        mgr.load()
        assert mgr.get_tier_model("standard") == os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
        assert mgr.get_router_model() == os.environ.get("ROUTER_MODEL", "gemini-2.0-flash")

    def test_set_tier_updates_cache(self):
        from data_agent.model_config import ModelConfigManager
        mgr = ModelConfigManager()
        mgr.load()
        # DB persist will fail (no engine), but cache should update
        mgr.set_tier_model("fast", "gemma-4-31b-it", "admin")
        assert mgr.get_tier_model("fast") == "gemma-4-31b-it"

    def test_set_router_updates_cache(self):
        from data_agent.model_config import ModelConfigManager
        mgr = ModelConfigManager()
        mgr.load()
        mgr.set_router_model("gemma-4-31b-it", "admin")
        assert mgr.get_router_model() == "gemma-4-31b-it"

    @patch("data_agent.model_config.ModelConfigManager._get_engine", return_value=None)
    def test_get_full_config(self, _):
        from data_agent.model_config import ModelConfigManager
        mgr = ModelConfigManager()
        mgr.load()
        config = mgr.get_full_config()
        assert "tiers" in config
        assert "router_model" in config
        assert "available_models" in config
        assert len(config["available_models"]) >= 4  # at least builtins


class TestIntentRouterConfigurable(unittest.TestCase):
    """Verify intent router reads model from config."""

    def test_get_router_model_default(self):
        from data_agent.intent_router import _get_router_model
        model = _get_router_model()
        assert isinstance(model, str)
        assert len(model) > 0

    @patch("data_agent.model_config.get_config_manager")
    def test_get_router_model_from_config(self, mock_mgr):
        mock_mgr.return_value.get_router_model.return_value = "gemma-4-31b-it"
        from data_agent.intent_router import _get_router_model
        model = _get_router_model()
        assert model == "gemma-4-31b-it"


class TestAgentTierIntegration(unittest.TestCase):
    """Verify agent.py reads from ModelConfigManager."""

    def test_get_model_config_returns_available_models(self):
        from data_agent.agent import get_model_config
        config = get_model_config()
        assert "tiers" in config
        # Should have available_models from ModelConfigManager
        if "available_models" in config:
            assert len(config["available_models"]) >= 4

    def test_get_tier_map_returns_dict(self):
        from data_agent.agent import _get_tier_map
        tier_map = _get_tier_map()
        assert "fast" in tier_map
        assert "standard" in tier_map
        assert "premium" in tier_map


if __name__ == "__main__":
    unittest.main()
