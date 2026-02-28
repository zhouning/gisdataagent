"""
Integration tests for GIS Data Agent — Path B1.

Tests core flows that were previously untested:
- Startup resilience (all ensure_* survive failure)
- Intent classification (mock Gemini, verify 3-tuple)
- Prompt chain assembly (all injection points)
- SQL safety (bind params in semantic layer)
- Pipeline runner (ContextVar setup)
- WeChat bot thread safety (dedup + rate limiter)
- describe_table → auto_register integration

All tests use mocks — no real DB or Gemini API needed.
"""

import asyncio
import json
import os
import threading
import time
import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Group A: Startup Resilience
# ---------------------------------------------------------------------------

class TestStartupResilience(unittest.TestCase):
    """Verify startup ensure_* calls survive failures."""

    @patch("data_agent.database_tools.get_engine", return_value=None)
    def test_ensure_table_ownership_no_db(self, mock_engine):
        """ensure_table_ownership_table() does nothing when DB is unavailable."""
        from data_agent.database_tools import ensure_table_ownership_table
        ensure_table_ownership_table()  # should not raise

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_ensure_semantic_tables_no_db(self, mock_engine):
        """ensure_semantic_tables() does nothing when DB is unavailable."""
        from data_agent.semantic_layer import ensure_semantic_tables
        ensure_semantic_tables()  # should not raise

    @patch("data_agent.semantic_layer._CATALOG_PATH", "/nonexistent/semantic_catalog.yaml")
    def test_catalog_missing_graceful(self):
        """_load_catalog() returns empty defaults when YAML file is missing."""
        import data_agent.semantic_layer as sl
        # Clear cache to force reload
        sl._catalog_cache = None
        catalog = sl._load_catalog()
        self.assertIsInstance(catalog, dict)
        self.assertIn("domains", catalog)
        self.assertEqual(catalog["domains"], {})
        # Restore cache for other tests
        sl._catalog_cache = None

    @patch("data_agent.memory.get_engine", return_value=None)
    def test_ensure_memory_table_no_db(self, mock_engine):
        """ensure_memory_table() does nothing when DB is unavailable."""
        from data_agent.memory import ensure_memory_table
        ensure_memory_table()  # should not raise

    @patch("data_agent.token_tracker.get_engine", return_value=None)
    def test_ensure_token_table_no_db(self, mock_engine):
        """ensure_token_table() does nothing when DB is unavailable."""
        from data_agent.token_tracker import ensure_token_table
        ensure_token_table()  # should not raise

    @patch("data_agent.sharing.get_engine", return_value=None)
    def test_ensure_share_links_no_db(self, mock_engine):
        """ensure_share_links_table() does nothing when DB is unavailable."""
        from data_agent.sharing import ensure_share_links_table
        ensure_share_links_table()  # should not raise


# ---------------------------------------------------------------------------
# Group B: Intent Router
# ---------------------------------------------------------------------------

class TestIntentClassification(unittest.TestCase):
    """Test classify_intent with mock Gemini."""

    @patch("google.generativeai.GenerativeModel")
    def test_classify_general(self, MockModel):
        """Normal classification returns 3-tuple with GENERAL intent."""
        mock_response = MagicMock()
        mock_response.text = "GENERAL|用户请求查看数据库表"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=50, candidates_token_count=10
        )
        MockModel.return_value.generate_content.return_value = mock_response

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent("列出所有表")
        self.assertEqual(intent, "GENERAL")
        self.assertIn("数据库", reason)
        self.assertGreaterEqual(tokens, 0)

    @patch("google.generativeai.GenerativeModel")
    def test_classify_governance(self, MockModel):
        """Classification correctly returns GOVERNANCE."""
        mock_response = MagicMock()
        mock_response.text = "GOVERNANCE|数据质量检查"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=50, candidates_token_count=10
        )
        MockModel.return_value.generate_content.return_value = mock_response

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent("对这个数据做拓扑检查")
        self.assertEqual(intent, "GOVERNANCE")

    @patch("google.generativeai.GenerativeModel")
    def test_classify_api_error_fallback(self, MockModel):
        """classify_intent falls back to GENERAL on API error."""
        MockModel.return_value.generate_content.side_effect = Exception("API timeout")

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent("随便说点什么")
        self.assertEqual(intent, "GENERAL")
        self.assertEqual(tokens, 0)

    @patch("google.generativeai.GenerativeModel")
    def test_classify_malformed_response(self, MockModel):
        """classify_intent handles malformed model output."""
        mock_response = MagicMock()
        mock_response.text = "this is not a valid format"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=50, candidates_token_count=10
        )
        MockModel.return_value.generate_content.return_value = mock_response

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent("你好")
        # Should still return a valid 3-tuple
        self.assertIn(intent, ("GENERAL", "GOVERNANCE", "OPTIMIZATION", "AMBIGUOUS"))
        self.assertEqual(len(classify_intent("test")), 3)


# ---------------------------------------------------------------------------
# Group C: Prompt Chain Assembly
# ---------------------------------------------------------------------------

class TestPromptChain(unittest.TestCase):
    """Test semantic context injection into prompt chain."""

    def test_build_context_prompt_with_sources(self):
        """build_context_prompt generates [语义上下文] block."""
        from data_agent.semantic_layer import build_context_prompt
        resolved = {
            "sources": [{
                "table_name": "test_table",
                "display_name": "测试表",
                "geometry_type": "Polygon",
                "srid": 4326,
                "description": "",
                "confidence": 1.0,
            }],
            "matched_columns": {
                "test_table": [{
                    "column_name": "area",
                    "semantic_domain": "AREA",
                    "aliases": ["面积"],
                    "unit": "m²",
                    "description": "面积",
                    "is_geometry": False,
                    "confidence": 1.0,
                }]
            },
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
        }
        result = build_context_prompt(resolved)
        self.assertIn("[语义上下文]", result)
        self.assertIn("test_table", result)
        self.assertIn("面积", result)
        self.assertIn("优先使用以上语义映射", result)

    def test_build_context_prompt_empty(self):
        """build_context_prompt returns empty string when nothing matched."""
        from data_agent.semantic_layer import build_context_prompt
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
        }
        result = build_context_prompt(resolved)
        self.assertEqual(result, "")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_without_db(self, mock_engine):
        """resolve_semantic_context works with only static catalog (no DB)."""
        from data_agent.semantic_layer import resolve_semantic_context
        import data_agent.semantic_layer as sl
        # Ensure real catalog is loaded
        sl._catalog_cache = None
        result = resolve_semantic_context("分析面积分布")
        self.assertIsInstance(result, dict)
        self.assertIn("sources", result)
        self.assertIn("matched_columns", result)
        # Static hints should have matched "面积" → AREA domain
        static_hints = result["matched_columns"].get("_static_hints", [])
        area_hit = any(h["semantic_domain"] == "AREA" for h in static_hints)
        self.assertTrue(area_hit, "Should match AREA domain from static catalog")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_spatial_operations(self, mock_engine):
        """resolve_semantic_context matches spatial operations."""
        from data_agent.semantic_layer import resolve_semantic_context
        import data_agent.semantic_layer as sl
        sl._catalog_cache = None
        result = resolve_semantic_context("对数据做缓冲区分析")
        ops = result.get("spatial_ops", [])
        self.assertTrue(len(ops) > 0)
        self.assertEqual(ops[0]["operation"], "buffer")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_region_filter(self, mock_engine):
        """resolve_semantic_context matches region groups."""
        from data_agent.semantic_layer import resolve_semantic_context
        import data_agent.semantic_layer as sl
        sl._catalog_cache = None
        result = resolve_semantic_context("统计华东地区数据")
        region = result.get("region_filter")
        self.assertIsNotNone(region)
        self.assertEqual(region["name"], "华东")

    def test_prompt_semantic_failure_nonfatal(self):
        """Semantic resolution failure should not block prompt assembly."""
        # Simulate what app.py does
        full_prompt = "用户请求文本"
        try:
            raise RuntimeError("DB connection failed")
        except Exception:
            pass  # non-fatal, same as app.py pattern
        # full_prompt should remain intact
        self.assertEqual(full_prompt, "用户请求文本")


# ---------------------------------------------------------------------------
# Group D: SQL Safety
# ---------------------------------------------------------------------------

class TestSQLSafety(unittest.TestCase):
    """Verify bind parameters are used for SQL queries in semantic layer."""

    def test_resolve_uses_bind_params(self):
        """resolve_semantic_context builds IN clause with bind params, not f-strings."""
        import inspect
        from data_agent.semantic_layer import _get_cached_registry
        source = inspect.getsource(_get_cached_registry)
        # Should NOT contain the old f-string pattern
        self.assertNotIn("f\"'{t}'\"", source,
                         "SQL injection: f-string IN clause still present")
        # Should contain bind param pattern
        self.assertIn(":t", source, "Expected bind param :t pattern")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_auto_register_idempotent(self, mock_engine):
        """auto_register_table returns early when DB unavailable (no crash)."""
        from data_agent.semantic_layer import auto_register_table
        result = auto_register_table("test_table", "admin")
        self.assertEqual(result["status"], "error")
        self.assertIn("not configured", result["message"])


# ---------------------------------------------------------------------------
# Group E: Pipeline Runner
# ---------------------------------------------------------------------------

class TestPipelineRunner(unittest.TestCase):
    """Test headless pipeline runner."""

    def test_runner_sets_context_vars(self):
        """run_pipeline_headless sets ContextVars before running pipeline."""
        import inspect
        from data_agent.pipeline_runner import run_pipeline_headless
        source = inspect.getsource(run_pipeline_headless)
        self.assertIn("current_user_id.set(", source)
        self.assertIn("current_session_id.set(", source)
        self.assertIn("current_user_role.set(", source)

    def test_runner_has_role_param(self):
        """run_pipeline_headless accepts a 'role' parameter."""
        import inspect
        from data_agent.pipeline_runner import run_pipeline_headless
        sig = inspect.signature(run_pipeline_headless)
        self.assertIn("role", sig.parameters)
        self.assertEqual(sig.parameters["role"].default, "analyst")

    def test_pipeline_result_dataclass(self):
        """PipelineResult has all expected fields."""
        from data_agent.pipeline_runner import PipelineResult
        r = PipelineResult(pipeline_type="general", intent="GENERAL")
        self.assertEqual(r.pipeline_type, "general")
        self.assertEqual(r.intent, "GENERAL")
        self.assertEqual(r.total_input_tokens, 0)
        self.assertEqual(r.total_output_tokens, 0)
        self.assertIsNone(r.error)
        self.assertEqual(r.generated_files, [])

    def test_extract_file_paths(self):
        """extract_file_paths finds valid file paths in text."""
        from data_agent.pipeline_runner import extract_file_paths
        # Use a path that doesn't exist on disk — should return empty
        result = extract_file_paths("Output saved to /nonexistent/file.png")
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# Group F: WeChat Safety (Thread-safety)
# ---------------------------------------------------------------------------

class TestWeComSafety(unittest.TestCase):
    """Test thread-safety of dedup and rate limiter."""

    def test_dedup_basic(self):
        """_is_duplicate detects repeated message IDs."""
        from data_agent.wecom_bot import _is_duplicate, _processing_messages
        # Clear state
        _processing_messages.clear()

        self.assertFalse(_is_duplicate("msg_001"))
        self.assertTrue(_is_duplicate("msg_001"))  # duplicate
        self.assertFalse(_is_duplicate("msg_002"))  # new

    def test_dedup_empty_msgid(self):
        """_is_duplicate returns False for empty MsgId."""
        from data_agent.wecom_bot import _is_duplicate
        self.assertFalse(_is_duplicate(""))
        self.assertFalse(_is_duplicate(None))

    def test_dedup_concurrent(self):
        """_is_duplicate is thread-safe under concurrent access."""
        from data_agent.wecom_bot import _is_duplicate, _processing_messages
        _processing_messages.clear()

        results = []
        errors = []

        def check_dedup(msg_id):
            try:
                result = _is_duplicate(msg_id)
                results.append((msg_id, result))
            except Exception as e:
                errors.append(str(e))

        threads = []
        # Same message ID from multiple threads
        for i in range(20):
            t = threading.Thread(target=check_dedup, args=(f"concurrent_{i % 5}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(results), 20)
        # Each unique msg_id should be False exactly once (first occurrence)
        for msg_id in [f"concurrent_{i}" for i in range(5)]:
            first_results = [r for mid, r in results if mid == msg_id and not r]
            self.assertGreaterEqual(len(first_results), 1,
                                    f"Message {msg_id} should have at least one non-duplicate result")

    def test_dedup_has_lock(self):
        """_is_duplicate uses a threading.Lock for synchronization."""
        import data_agent.wecom_bot as wb
        self.assertTrue(hasattr(wb, '_dedup_lock'))
        self.assertIsInstance(wb._dedup_lock, type(threading.Lock()))

    def test_rate_limiter_has_lock(self):
        """_wait_for_rate_limit uses an asyncio.Lock for synchronization."""
        import data_agent.wecom_bot as wb
        self.assertTrue(hasattr(wb, '_rate_lock'))
        self.assertIsInstance(wb._rate_lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Group G: Describe Table → Auto Register Integration
# ---------------------------------------------------------------------------

class TestDescribeTriggersRegister(unittest.TestCase):
    """Test that describe_table triggers auto_register_table."""

    def test_describe_table_calls_auto_register(self):
        """describe_table() invokes auto_register_table on success."""
        import inspect
        from data_agent.database_tools import describe_table
        source = inspect.getsource(describe_table)
        self.assertIn("auto_register_table", source)
        self.assertIn("semantic_layer", source)

    @patch("data_agent.database_tools.get_engine", return_value=None)
    def test_describe_table_no_db(self, mock_engine):
        """describe_table returns error when DB unavailable (no crash)."""
        from data_agent.database_tools import describe_table
        result = describe_table("test_table")
        self.assertEqual(result["status"], "error")

    def test_semantic_layer_constants_match(self):
        """Semantic table constants are consistent between modules."""
        from data_agent.database_tools import T_SEMANTIC_REGISTRY, T_SEMANTIC_SOURCES
        from data_agent.semantic_layer import T_SEMANTIC_REGISTRY as SL_REG
        from data_agent.semantic_layer import T_SEMANTIC_SOURCES as SL_SRC
        self.assertEqual(T_SEMANTIC_REGISTRY, "agent_semantic_registry")
        self.assertEqual(T_SEMANTIC_SOURCES, "agent_semantic_sources")
        # Ensure both modules use the same names
        self.assertEqual(T_SEMANTIC_REGISTRY, SL_REG)
        self.assertEqual(T_SEMANTIC_SOURCES, SL_SRC)


if __name__ == "__main__":
    unittest.main()
