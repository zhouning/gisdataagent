"""
Tests for Agent Plugins (v9.0.1).

Tests CostGuardPlugin, GISToolRetryPlugin, ProvenancePlugin,
and the build_plugin_stack() assembly function.
"""

import os
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callback_context(state=None):
    """Create a mock CallbackContext with a state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_tool_context(state=None):
    """Create a mock ToolContext with a state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.agent_name = "TestAgent"
    ctx.invocation_id = "inv_001"
    return ctx


def _make_tool(name="test_tool"):
    """Create a mock tool."""
    tool = MagicMock()
    tool.name = name
    return tool


def _make_llm_response(prompt_tokens=100, output_tokens=50):
    """Create a mock LlmResponse with usage_metadata."""
    resp = MagicMock()
    resp.usage_metadata = MagicMock()
    resp.usage_metadata.prompt_token_count = prompt_tokens
    resp.usage_metadata.candidates_token_count = output_tokens
    return resp


# ---------------------------------------------------------------------------
# TestCostGuardPlugin
# ---------------------------------------------------------------------------

class TestCostGuardPlugin(unittest.IsolatedAsyncioTestCase):
    """Test token budget control plugin."""

    def test_init_defaults(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin()
        self.assertEqual(p.name, "cost_guard")
        self.assertEqual(p.warn_threshold, 50000)
        self.assertEqual(p.abort_threshold, 200000)

    def test_init_custom_thresholds(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(warn_threshold=1000, abort_threshold=5000)
        self.assertEqual(p.warn_threshold, 1000)
        self.assertEqual(p.abort_threshold, 5000)

    @patch.dict(os.environ, {"COST_GUARD_WARN": "2000", "COST_GUARD_ABORT": "8000"})
    def test_init_from_env(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin()
        self.assertEqual(p.warn_threshold, 2000)
        self.assertEqual(p.abort_threshold, 8000)

    async def test_after_model_accumulates_tokens(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(warn_threshold=99999, abort_threshold=99999)
        ctx = _make_callback_context()
        resp = _make_llm_response(100, 50)

        result = await p.after_model_callback(callback_context=ctx, llm_response=resp)
        self.assertIsNone(result)
        self.assertEqual(ctx.state[CostGuardPlugin.STATE_KEY], 150)

        # Second call accumulates
        await p.after_model_callback(callback_context=ctx, llm_response=resp)
        self.assertEqual(ctx.state[CostGuardPlugin.STATE_KEY], 300)

    async def test_before_model_allows_under_threshold(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(abort_threshold=1000)
        ctx = _make_callback_context({CostGuardPlugin.STATE_KEY: 500})

        result = await p.before_model_callback(callback_context=ctx, llm_request=MagicMock())
        self.assertIsNone(result)

    async def test_before_model_aborts_over_threshold(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(abort_threshold=1000)
        ctx = _make_callback_context({CostGuardPlugin.STATE_KEY: 1500})

        result = await p.before_model_callback(callback_context=ctx, llm_request=MagicMock())
        self.assertIsNotNone(result)
        self.assertIn("budget exceeded", result.content.parts[0].text)

    async def test_warn_logging(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(warn_threshold=100, abort_threshold=99999)
        ctx = _make_callback_context()
        resp = _make_llm_response(80, 30)

        with patch("data_agent.plugins.logger") as mock_logger:
            await p.after_model_callback(callback_context=ctx, llm_response=resp)
            mock_logger.warning.assert_called_once()
            self.assertTrue(p._warned)


# ---------------------------------------------------------------------------
# TestGISToolRetryPlugin
# ---------------------------------------------------------------------------

class TestGISToolRetryPlugin(unittest.IsolatedAsyncioTestCase):
    """Test GIS-specific tool retry plugin."""

    def test_init(self):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin()
        self.assertEqual(p.name, "gis_tool_retry")
        self.assertEqual(p.max_retries, 2)
        self.assertFalse(p.throw_exception_if_retry_exceeded)

    async def test_extract_error_detects_status_error(self):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin()
        result = {"status": "error", "message": "Connection failed"}
        error = await p.extract_error_from_result(
            tool=_make_tool(), tool_args={},
            tool_context=_make_tool_context(), result=result,
        )
        self.assertEqual(error, result)

    async def test_extract_error_ignores_success(self):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin()
        result = {"status": "success", "message": "OK"}
        error = await p.extract_error_from_result(
            tool=_make_tool(), tool_args={},
            tool_context=_make_tool_context(), result=result,
        )
        self.assertIsNone(error)

    @patch("data_agent.plugins.GISToolRetryPlugin._record_failure")
    async def test_on_tool_error_records_failure(self, mock_record):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin(max_retries=1)
        tool = _make_tool("query_database")
        ctx = _make_tool_context()
        ctx._retry_count = 0  # Ensure retry_count is an int, not MagicMock
        error = Exception("timeout")

        result = await p.on_tool_error_callback(
            tool=tool, tool_args={}, tool_context=ctx, error=error,
        )
        mock_record.assert_called_once_with("query_database", "timeout")
        # Should return reflection guidance (retry #1)
        self.assertIsNotNone(result)

    @patch("data_agent.plugins.GISToolRetryPlugin._record_failure")
    async def test_after_tool_records_soft_error(self, mock_record):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin(max_retries=1)
        tool = _make_tool("buffer_analysis")
        ctx = _make_tool_context()
        result = {"status": "error", "message": "Invalid geometry"}

        await p.after_tool_callback(
            tool=tool, tool_args={}, tool_context=ctx, result=result,
        )
        mock_record.assert_called_once_with("buffer_analysis", "Invalid geometry")


# ---------------------------------------------------------------------------
# TestProvenancePlugin
# ---------------------------------------------------------------------------

class TestProvenancePlugin(unittest.IsolatedAsyncioTestCase):
    """Test decision audit trail plugin."""

    def test_init(self):
        from data_agent.plugins import ProvenancePlugin
        p = ProvenancePlugin()
        self.assertEqual(p.name, "provenance")

    async def test_after_agent_records_entry(self):
        from data_agent.plugins import ProvenancePlugin
        p = ProvenancePlugin()
        ctx = _make_callback_context()
        agent = MagicMock()
        agent.name = "DataExplorer"

        result = await p.after_agent_callback(agent=agent, callback_context=ctx)
        self.assertIsNone(result)
        trail = ctx.state[ProvenancePlugin.STATE_KEY]
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0]["type"], "agent")
        self.assertEqual(trail[0]["agent"], "DataExplorer")
        self.assertIn("timestamp", trail[0])

    async def test_after_tool_records_entry(self):
        from data_agent.plugins import ProvenancePlugin
        p = ProvenancePlugin()
        ctx = _make_tool_context()
        tool = _make_tool("clip_geometry")

        result = await p.after_tool_callback(
            tool=tool, tool_args={"input_path": "data.shp"},
            tool_context=ctx, result={"status": "success"},
        )
        self.assertIsNone(result)
        trail = ctx.state[ProvenancePlugin.STATE_KEY]
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0]["type"], "tool")
        self.assertEqual(trail[0]["tool"], "clip_geometry")
        self.assertFalse(trail[0]["is_error"])

    async def test_after_tool_detects_error(self):
        from data_agent.plugins import ProvenancePlugin
        p = ProvenancePlugin()
        ctx = _make_tool_context()
        tool = _make_tool("query_db")

        await p.after_tool_callback(
            tool=tool, tool_args={},
            tool_context=ctx, result={"status": "error", "message": "fail"},
        )
        trail = ctx.state[ProvenancePlugin.STATE_KEY]
        self.assertTrue(trail[0]["is_error"])

    async def test_trail_accumulates(self):
        from data_agent.plugins import ProvenancePlugin
        p = ProvenancePlugin()
        ctx = _make_callback_context()
        for name in ["AgentA", "AgentB", "AgentC"]:
            agent = MagicMock()
            agent.name = name
            await p.after_agent_callback(agent=agent, callback_context=ctx)
        trail = ctx.state[ProvenancePlugin.STATE_KEY]
        self.assertEqual(len(trail), 3)
        self.assertEqual([e["agent"] for e in trail], ["AgentA", "AgentB", "AgentC"])


# ---------------------------------------------------------------------------
# TestBuildPluginStack
# ---------------------------------------------------------------------------

class TestBuildPluginStack(unittest.TestCase):
    """Test plugin stack assembly."""

    def test_default_stack(self):
        from data_agent.plugins import build_plugin_stack
        plugins = build_plugin_stack()
        names = [p.name for p in plugins]
        self.assertIn("cost_guard", names)
        self.assertIn("gis_tool_retry", names)
        self.assertIn("provenance", names)

    @patch.dict(os.environ, {
        "COST_GUARD_ENABLED": "false",
        "TOOL_RETRY_ENABLED": "false",
        "PROVENANCE_ENABLED": "false",
        "GUARDRAILS_POLICY_ENABLED": "false",
    })
    def test_all_disabled(self):
        from data_agent.plugins import build_plugin_stack
        plugins = build_plugin_stack()
        self.assertEqual(len(plugins), 0)

    @patch.dict(os.environ, {
        "COST_GUARD_ENABLED": "true",
        "TOOL_RETRY_ENABLED": "false",
        "PROVENANCE_ENABLED": "true",
    })
    def test_partial_stack(self):
        from data_agent.plugins import build_plugin_stack
        plugins = build_plugin_stack()
        names = [p.name for p in plugins]
        self.assertIn("cost_guard", names)
        self.assertNotIn("gis_tool_retry", names)
        self.assertIn("provenance", names)


# ---------------------------------------------------------------------------
# TestPipelineResultProvenance
# ---------------------------------------------------------------------------

class TestPipelineResultProvenance(unittest.TestCase):
    """Test PipelineResult includes provenance_trail field."""

    def test_provenance_trail_field(self):
        from data_agent.pipeline_runner import PipelineResult
        result = PipelineResult()
        self.assertEqual(result.provenance_trail, [])

    def test_provenance_trail_with_data(self):
        from data_agent.pipeline_runner import PipelineResult
        trail = [{"type": "agent", "agent": "Explorer", "timestamp": 1}]
        result = PipelineResult(provenance_trail=trail)
        self.assertEqual(len(result.provenance_trail), 1)
        self.assertEqual(result.provenance_trail[0]["agent"], "Explorer")


# ---------------------------------------------------------------------------
# TestPluginBaseClass
# ---------------------------------------------------------------------------

class TestPluginBaseClass(unittest.TestCase):
    """Verify all plugins are proper BasePlugin subclasses."""

    def test_cost_guard_is_base_plugin(self):
        from data_agent.plugins import CostGuardPlugin
        from google.adk.plugins.base_plugin import BasePlugin
        self.assertTrue(issubclass(CostGuardPlugin, BasePlugin))

    def test_gis_retry_is_reflect_plugin(self):
        from data_agent.plugins import GISToolRetryPlugin
        from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin
        self.assertTrue(issubclass(GISToolRetryPlugin, ReflectAndRetryToolPlugin))

    def test_provenance_is_base_plugin(self):
        from data_agent.plugins import ProvenancePlugin
        from google.adk.plugins.base_plugin import BasePlugin
        self.assertTrue(issubclass(ProvenancePlugin, BasePlugin))


if __name__ == "__main__":
    unittest.main()
