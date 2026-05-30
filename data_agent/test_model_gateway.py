"""
Tests for unified model gateway — online/offline LLM support.

Covers:
- ModelRegistry: built-in models, registration, online/offline filtering
- create_model: Gemini vs LiteLlm backend selection
- ModelRouter: routing with offline preference
"""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestModelRegistryBuiltins(unittest.TestCase):
    """Built-in model catalog."""

    def setUp(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def tearDown(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def test_has_gemini_models(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry._ensure_initialized()
        self.assertIn("gemini-2.5-flash", ModelRegistry.models)
        self.assertIn("gemini-2.5-pro", ModelRegistry.models)
        self.assertIn("gemini-2.0-flash", ModelRegistry.models)

    def test_has_gemma_local_model(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry._ensure_initialized()
        self.assertIn("gemma-3-4b", ModelRegistry.models)
        info = ModelRegistry.models["gemma-3-4b"]
        self.assertEqual(info["backend"], "lm_studio")
        self.assertFalse(info["online"])
        self.assertEqual(info["cost_per_1k_input"], 0.0)

    def test_has_deepseek_models(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry._ensure_initialized()
        self.assertIn("deepseek-v4-flash", ModelRegistry.models)
        self.assertIn("deepseek-v4-pro", ModelRegistry.models)
        flash = ModelRegistry.models["deepseek-v4-flash"]
        pro = ModelRegistry.models["deepseek-v4-pro"]
        self.assertEqual(flash["backend"], "deepseek")
        self.assertEqual(flash["tier"], "fast")
        self.assertTrue(flash["online"])
        self.assertGreater(flash["cost_per_1k_input"], 0.0)
        self.assertGreater(flash["cost_per_1k_output"], 0.0)
        self.assertEqual(flash["max_context_tokens"], 1_000_000)
        self.assertEqual(flash["api_base"], "https://api.deepseek.com")
        self.assertEqual(flash["api_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(flash["model_id"], "openai/deepseek-v4-flash")
        self.assertEqual(pro["backend"], "deepseek")
        self.assertEqual(pro["tier"], "premium")
        self.assertTrue(pro["online"])
        self.assertGreater(pro["cost_per_1k_input"], 0.0)
        self.assertGreater(pro["cost_per_1k_output"], 0.0)
        self.assertEqual(pro["max_context_tokens"], 1_000_000)
        self.assertEqual(pro["api_base"], "https://api.deepseek.com")
        self.assertEqual(pro["api_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(pro["model_id"], "openai/deepseek-v4-pro")

    def test_gemini_models_are_online(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry._ensure_initialized()
        for name in ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"]:
            self.assertTrue(ModelRegistry.models[name]["online"])
            self.assertEqual(ModelRegistry.models[name]["backend"], "gemini")

    def test_list_models_returns_all(self):
        from data_agent.model_gateway import ModelRegistry
        models = ModelRegistry.list_models()
        names = [m["name"] for m in models]
        self.assertIn("gemini-2.5-flash", names)
        self.assertIn("gemma-3-4b", names)
        self.assertTrue(len(models) >= 4)

    def test_list_models_online_only(self):
        from data_agent.model_gateway import ModelRegistry
        models = ModelRegistry.list_models(online_only=True)
        for m in models:
            self.assertTrue(m["online"])

    def test_list_models_offline_only(self):
        from data_agent.model_gateway import ModelRegistry
        models = ModelRegistry.list_models(offline_only=True)
        for m in models:
            self.assertFalse(m["online"])
        names = [m["name"] for m in models]
        self.assertIn("gemma-3-4b", names)


class TestModelRegistration(unittest.TestCase):
    """Dynamic model registration."""

    def setUp(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def tearDown(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def test_register_custom_model(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.register_model(
            "openai/gpt-4o",
            backend="litellm",
            tier="premium",
            online=True,
            max_context_tokens=128_000,
        )
        info = ModelRegistry.get_model_info("openai/gpt-4o")
        self.assertEqual(info["backend"], "litellm")
        self.assertEqual(info["tier"], "premium")
        self.assertTrue(info["online"])

    def test_register_ollama_model(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.register_model(
            "ollama/llama3",
            backend="litellm",
            tier="local",
            api_base="http://localhost:11434",
        )
        info = ModelRegistry.get_model_info("ollama/llama3")
        self.assertEqual(info["api_base"], "http://localhost:11434")
        self.assertFalse(info["online"])  # ollama auto-detected as offline

    def test_unregister_model(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.register_model("test-model", backend="litellm")
        ModelRegistry.unregister_model("test-model")
        self.assertEqual(ModelRegistry.get_model_info("test-model"), {})

    def test_get_offline_models(self):
        from data_agent.model_gateway import ModelRegistry
        offline = ModelRegistry.get_offline_models()
        self.assertIn("gemma-3-4b", offline)
        self.assertNotIn("gemini-2.5-flash", offline)

    def test_get_online_models(self):
        from data_agent.model_gateway import ModelRegistry
        online = ModelRegistry.get_online_models()
        self.assertIn("gemini-2.5-flash", online)
        self.assertNotIn("gemma-3-4b", online)

    @patch.dict(os.environ, {"LM_STUDIO_MODEL": "qwen3-8b"})
    def test_env_var_auto_registers_lm_studio_model(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()
        ModelRegistry._ensure_initialized()
        self.assertIn("qwen3-8b", ModelRegistry.models)
        self.assertEqual(ModelRegistry.models["qwen3-8b"]["backend"], "lm_studio")


class TestCreateModel(unittest.TestCase):
    """create_model() factory backend selection."""

    def setUp(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def tearDown(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    @patch("data_agent.model_gateway._create_gemini_model")
    def test_gemini_model_uses_gemini_backend(self, mock_create):
        from data_agent.model_gateway import create_model
        mock_create.return_value = MagicMock()
        create_model("gemini-2.5-flash")
        mock_create.assert_called_once_with("gemini-2.5-flash")

    @patch("data_agent.model_gateway._create_lm_studio_model")
    def test_lm_studio_model_uses_lm_studio_backend(self, mock_create):
        from data_agent.model_gateway import create_model
        mock_create.return_value = MagicMock()
        create_model("gemma-3-4b")
        mock_create.assert_called_once()

    @patch("data_agent.model_gateway._create_deepseek_model")
    def test_deepseek_model_uses_deepseek_backend(self, mock_create):
        from data_agent.model_gateway import create_model
        mock_create.return_value = MagicMock()
        create_model("deepseek-v4-flash")
        mock_create.assert_called_once()

    @patch("google.adk.models.lite_llm.LiteLlm")
    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False)
    def test_create_deepseek_model_sets_openai_compat_env(self, mock_litellm):
        from data_agent.model_gateway import _create_deepseek_model
        _create_deepseek_model("deepseek-v4-flash", {
            "api_base": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_id": "openai/deepseek-v4-flash",
        })
        self.assertEqual(os.environ["OPENAI_API_BASE"], "https://api.deepseek.com")
        self.assertEqual(os.environ["OPENAI_API_KEY"], "test-key")
        mock_litellm.assert_called_once_with(model="openai/deepseek-v4-flash")

    def test_create_deepseek_model_requires_dedicated_api_key(self):
        from data_agent.model_gateway import _create_deepseek_model
        with patch.dict(os.environ, {"OPENAI_API_KEY": "stale-key"}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY not set"):
                _create_deepseek_model("deepseek-v4-flash", {
                    "api_base": "https://api.deepseek.com",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model_id": "openai/deepseek-v4-flash",
                })
            self.assertNotIn("OPENAI_API_KEY", os.environ)

    @patch("data_agent.model_gateway._create_litellm_model")
    def test_litellm_prefix_uses_litellm_backend(self, mock_create):
        from data_agent.model_gateway import ModelRegistry, create_model
        ModelRegistry.register_model("openai/gpt-4o", backend="litellm")
        mock_create.return_value = MagicMock()
        create_model("openai/gpt-4o")
        mock_create.assert_called_once()


class TestBackendDetection(unittest.TestCase):
    """_detect_backend() inference from model name."""

    def test_gemini_prefix_detected(self):
        from data_agent.model_gateway import _detect_backend
        self.assertEqual(_detect_backend("gemini-2.5-flash"), "gemini")

    def test_deepseek_prefix_detected(self):
        from data_agent.model_gateway import _detect_backend
        self.assertEqual(_detect_backend("deepseek-v4-flash"), "deepseek")

    def test_openai_prefix_detected(self):
        from data_agent.model_gateway import _detect_backend
        self.assertEqual(_detect_backend("openai/gpt-4o"), "litellm")

    def test_ollama_prefix_detected(self):
        from data_agent.model_gateway import _detect_backend
        self.assertEqual(_detect_backend("ollama/llama3"), "litellm")

    def test_unknown_defaults_to_env_var(self):
        from data_agent.model_gateway import _detect_backend
        with patch.dict(os.environ, {"MODEL_BACKEND": "litellm"}):
            self.assertEqual(_detect_backend("my-custom-model"), "litellm")


class TestModelRouter(unittest.TestCase):
    """ModelRouter with online/offline support."""

    def setUp(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def tearDown(self):
        from data_agent.model_gateway import ModelRegistry
        ModelRegistry.reset()

    def test_route_standard_returns_gemini(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        result = router.route(quality_requirement="standard")
        self.assertIn("gemini", result)

    def test_route_local_returns_offline_model(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        result = router.route(quality_requirement="local")
        self.assertEqual(result, "gemma-3-4b")

    def test_route_prefer_offline(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        result = router.route(prefer_offline=True)
        self.assertEqual(result, "gemma-3-4b")

    def test_route_with_task_type(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        result = router.route(task_type="planning", quality_requirement="premium")
        self.assertEqual(result, "gemini-2.5-pro")

    def test_route_budget_filter(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        # Very low budget should exclude premium
        result = router.route(budget_per_call_usd=0.001)
        self.assertNotEqual(result, "gemini-2.5-pro")

    def test_route_fallback_when_no_match(self):
        from data_agent.model_gateway import ModelRouter
        router = ModelRouter()
        result = router.route(task_type="nonexistent_capability")
        # Should fallback gracefully
        self.assertIsNotNone(result)


class TestAgentIntegration(unittest.TestCase):
    """agent.py _create_model_with_retry delegates to create_model."""

    @patch("data_agent.model_gateway.create_model")
    def test_create_model_with_retry_delegates(self, mock_create):
        mock_create.return_value = MagicMock()
        from data_agent.agent import _create_model_with_retry
        _create_model_with_retry("gemini-2.5-flash")
        mock_create.assert_called_once_with("gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
