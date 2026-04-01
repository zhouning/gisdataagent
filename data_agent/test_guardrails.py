"""
Tests for Agent Guardrails (v9.5.3).

Tests InputLengthGuard, SQLInjectionGuard, OutputSanitizer,
HallucinationGuard, and attach_guardrails().
"""

import os
import unittest
from unittest.mock import MagicMock, AsyncMock

from google.genai import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callback_context(events=None):
    """Create a mock CallbackContext with session.events."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.events = events if events is not None else []
    return ctx


def _make_event(text: str, role="user"):
    """Create a mock event with text content."""
    event = MagicMock()
    event.content = types.Content(
        role=role,
        parts=[types.Part(text=text)],
    )
    return event


# ---------------------------------------------------------------------------
# TestInputLengthGuard
# ---------------------------------------------------------------------------

class TestInputLengthGuard(unittest.IsolatedAsyncioTestCase):

    async def test_accepts_short_input(self):
        from data_agent.guardrails import input_length_guard

        ctx = _make_callback_context([_make_event("Hello world")])
        result = await input_length_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNone(result)

    async def test_rejects_long_input(self):
        from data_agent.guardrails import input_length_guard

        long_text = "x" * 60_000
        ctx = _make_callback_context([_make_event(long_text)])
        result = await input_length_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("过长", result.parts[0].text)

    async def test_disabled_via_env(self):
        import importlib
        import data_agent.guardrails

        os.environ["GUARDRAILS_DISABLED"] = "1"
        try:
            importlib.reload(data_agent.guardrails)
            from data_agent.guardrails import input_length_guard

            long_text = "x" * 60_000
            ctx = _make_callback_context([_make_event(long_text)])
            result = await input_length_guard(agent=MagicMock(), callback_context=ctx)
            self.assertIsNone(result)
        finally:
            os.environ.pop("GUARDRAILS_DISABLED", None)
            importlib.reload(data_agent.guardrails)


# ---------------------------------------------------------------------------
# TestSQLInjectionGuard
# ---------------------------------------------------------------------------

class TestSQLInjectionGuard(unittest.IsolatedAsyncioTestCase):

    async def test_accepts_safe_input(self):
        from data_agent.guardrails import sql_injection_guard

        ctx = _make_callback_context([_make_event("SELECT * FROM users WHERE id=1")])
        result = await sql_injection_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNone(result)

    async def test_rejects_union_select(self):
        from data_agent.guardrails import sql_injection_guard

        ctx = _make_callback_context([_make_event("1' UNION SELECT * FROM passwords--")])
        result = await sql_injection_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("SQL 注入", result.parts[0].text)

    async def test_rejects_drop_table(self):
        from data_agent.guardrails import sql_injection_guard

        ctx = _make_callback_context([_make_event("'; DROP TABLE users;--")])
        result = await sql_injection_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)

    async def test_rejects_or_1_equals_1(self):
        from data_agent.guardrails import sql_injection_guard

        ctx = _make_callback_context([_make_event("admin' OR 1=1--")])
        result = await sql_injection_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# TestOutputSanitizer
# ---------------------------------------------------------------------------

class TestOutputSanitizer(unittest.IsolatedAsyncioTestCase):

    async def test_no_redaction_for_clean_output(self):
        from data_agent.guardrails import output_sanitizer

        ctx = _make_callback_context([_make_event("Analysis complete", role="model")])
        result = await output_sanitizer(agent=MagicMock(), callback_context=ctx)
        self.assertIsNone(result)

    async def test_redacts_api_key(self):
        from data_agent.guardrails import output_sanitizer

        ctx = _make_callback_context([
            _make_event("API_KEY=sk-abc123def456ghi789jkl", role="model")
        ])
        result = await output_sanitizer(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("REDACTED", result.parts[0].text)
        self.assertNotIn("sk-abc123", result.parts[0].text)

    async def test_redacts_password(self):
        from data_agent.guardrails import output_sanitizer

        ctx = _make_callback_context([
            _make_event("password=MySecretPass123", role="model")
        ])
        result = await output_sanitizer(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("PASSWORD_REDACTED", result.parts[0].text)

    async def test_redacts_bearer_token(self):
        from data_agent.guardrails import output_sanitizer

        ctx = _make_callback_context([
            _make_event("Bearer: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", role="model")
        ])
        result = await output_sanitizer(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("TOKEN_REDACTED", result.parts[0].text)


# ---------------------------------------------------------------------------
# TestHallucinationGuard
# ---------------------------------------------------------------------------

class TestHallucinationGuard(unittest.IsolatedAsyncioTestCase):

    async def test_no_warning_for_clean_output(self):
        from data_agent.guardrails import hallucination_guard

        ctx = _make_callback_context([_make_event("Analysis complete", role="model")])
        result = await hallucination_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNone(result)

    async def test_warns_on_example_com_url(self):
        from data_agent.guardrails import hallucination_guard

        ctx = _make_callback_context([
            _make_event("See https://example.com/data.csv", role="model")
        ])
        result = await hallucination_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("可疑 URL", result.parts[-1].text)

    async def test_warns_on_nonexistent_file_path(self):
        from data_agent.guardrails import hallucination_guard

        ctx = _make_callback_context([
            _make_event("Output saved to C:/nonexistent/file.shp", role="model")
        ])
        result = await hallucination_guard(agent=MagicMock(), callback_context=ctx)
        self.assertIsNotNone(result)
        self.assertIn("文件路径可能不存在", result.parts[-1].text)

    async def test_no_warning_for_existing_file(self):
        from data_agent.guardrails import hallucination_guard
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            ctx = _make_callback_context([
                _make_event(f"Output saved to {tmp_path}", role="model")
            ])
            result = await hallucination_guard(agent=MagicMock(), callback_context=ctx)
            # Should not warn since file exists
            self.assertIsNone(result)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# TestAttachGuardrails
# ---------------------------------------------------------------------------

class TestAttachGuardrails(unittest.TestCase):

    def test_attaches_to_llm_agent(self):
        from google.adk.agents import LlmAgent
        from data_agent.guardrails import attach_guardrails

        agent = LlmAgent(name="TestAgent", instruction="Test", model="gemini-2.0-flash")
        attach_guardrails(agent)

        self.assertIsNotNone(agent.before_agent_callback)
        self.assertIsNotNone(agent.after_agent_callback)
        self.assertIsInstance(agent.before_agent_callback, list)
        self.assertIsInstance(agent.after_agent_callback, list)
        self.assertEqual(len(agent.before_agent_callback), 2)  # 2 input guards
        self.assertEqual(len(agent.after_agent_callback), 2)  # 2 output guards

    def test_preserves_existing_callbacks(self):
        from google.adk.agents import LlmAgent
        from data_agent.guardrails import attach_guardrails

        async def existing_before(**kwargs):
            pass

        async def existing_after(**kwargs):
            pass

        agent = LlmAgent(
            name="TestAgent",
            instruction="Test",
            model="gemini-2.0-flash",
            before_agent_callback=existing_before,
            after_agent_callback=existing_after,
        )
        attach_guardrails(agent)

        self.assertIsInstance(agent.before_agent_callback, list)
        self.assertIsInstance(agent.after_agent_callback, list)
        self.assertEqual(len(agent.before_agent_callback), 3)  # 2 guards + 1 existing
        self.assertEqual(len(agent.after_agent_callback), 3)  # 2 guards + 1 existing
        self.assertIn(existing_before, agent.before_agent_callback)
        self.assertIn(existing_after, agent.after_agent_callback)

    def test_recurses_into_sub_agents(self):
        from google.adk.agents import LlmAgent, SequentialAgent
        from data_agent.guardrails import attach_guardrails

        sub1 = LlmAgent(name="Sub1", instruction="Test", model="gemini-2.0-flash")
        sub2 = LlmAgent(name="Sub2", instruction="Test", model="gemini-2.0-flash")
        parent = SequentialAgent(name="Parent", sub_agents=[sub1, sub2])

        attach_guardrails(parent)

        # Parent (SequentialAgent) should not have callbacks
        self.assertIsNone(getattr(parent, "before_agent_callback", None))
        self.assertIsNone(getattr(parent, "after_agent_callback", None))

        # Sub-agents should have callbacks
        self.assertIsNotNone(sub1.before_agent_callback)
        self.assertIsNotNone(sub1.after_agent_callback)
        self.assertIsNotNone(sub2.before_agent_callback)
        self.assertIsNotNone(sub2.after_agent_callback)

    def test_disabled_via_env(self):
        from google.adk.agents import LlmAgent
        import importlib
        import data_agent.guardrails

        os.environ["GUARDRAILS_DISABLED"] = "1"
        try:
            importlib.reload(data_agent.guardrails)
            from data_agent.guardrails import attach_guardrails as ag

            agent = LlmAgent(name="TestAgent", instruction="Test", model="gemini-2.0-flash")
            ag(agent)

            # Should not attach any callbacks
            self.assertIsNone(getattr(agent, "before_agent_callback", None))
            self.assertIsNone(getattr(agent, "after_agent_callback", None))
        finally:
            os.environ.pop("GUARDRAILS_DISABLED", None)
            importlib.reload(data_agent.guardrails)


# ===========================================================================
# D-4: Tool-Level Policy Engine Tests (v16.0)
# ===========================================================================

import json
import tempfile
from unittest.mock import patch, MagicMock

from data_agent.guardrails import (
    GuardrailPolicy,
    GuardrailDecision,
    GuardrailEngine,
    GuardrailsPlugin,
    evaluate_policy,
)


class TestGuardrailDecisionD4:
    def test_to_dict(self):
        d = GuardrailDecision("deny", "viewer", "delete_*", "不允许删除")
        assert d.to_dict()["effect"] == "deny"
        assert d.to_dict()["matched_pattern"] == "delete_*"


class TestGuardrailEngineLoading:
    def test_loads_default_policies(self):
        engine = GuardrailEngine()
        assert len(engine.policies) >= 3

    def test_loads_from_custom_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("policies:\n  - role: tester\n    effect: deny\n    tools: ['foo']\n    reason: test\n")
            path = f.name
        try:
            engine = GuardrailEngine(policy_path=path)
            assert len(engine.policies) == 1
            assert engine.policies[0].role == "tester"
        finally:
            os.unlink(path)

    def test_missing_file_graceful(self):
        engine = GuardrailEngine(policy_path="/nonexistent/path.yaml")
        assert len(engine.policies) == 0

    def test_reload(self):
        engine = GuardrailEngine()
        count_before = len(engine.policies)
        engine.reload()
        assert len(engine.policies) == count_before


class TestGuardrailEngineEvaluation:
    def setUp(self):
        self.engine = GuardrailEngine()

    def test_admin_bypass(self):
        engine = GuardrailEngine()
        assert engine.evaluate("admin", "delete_user_file").effect == "allow"

    def test_admin_bypass_any(self):
        engine = GuardrailEngine()
        assert engine.evaluate("admin", "totally_destructive").effect == "allow"

    def test_viewer_denied_delete(self):
        engine = GuardrailEngine()
        assert engine.evaluate("viewer", "delete_user_file").effect == "deny"

    def test_viewer_denied_import(self):
        engine = GuardrailEngine()
        assert engine.evaluate("viewer", "import_to_postgis").effect == "deny"

    def test_viewer_denied_share(self):
        engine = GuardrailEngine()
        assert engine.evaluate("viewer", "share_table").effect == "deny"

    def test_viewer_allowed_read(self):
        engine = GuardrailEngine()
        assert engine.evaluate("viewer", "describe_geodataframe").effect == "allow"

    def test_analyst_confirm_import(self):
        engine = GuardrailEngine()
        assert engine.evaluate("analyst", "import_to_postgis").effect == "require_confirmation"

    def test_analyst_allowed_analysis(self):
        engine = GuardrailEngine()
        assert engine.evaluate("analyst", "spatial_autocorrelation").effect == "allow"

    def test_global_deny_raw_sql(self):
        engine = GuardrailEngine()
        for role in ("viewer", "analyst"):
            assert engine.evaluate(role, "execute_raw_sql").effect == "deny"

    def test_admin_allowed_raw_sql(self):
        engine = GuardrailEngine()
        assert engine.evaluate("admin", "execute_raw_sql").effect == "allow"

    def test_glob_pattern(self):
        engine = GuardrailEngine()
        assert engine.evaluate("viewer", "delete_data_asset").effect == "deny"
        assert engine.evaluate("viewer", "delete_memory").effect == "deny"

    def test_unknown_tool_allowed(self):
        engine = GuardrailEngine()
        assert engine.evaluate("analyst", "some_new_tool").effect == "allow"

    def test_decision_has_reason(self):
        engine = GuardrailEngine()
        d = engine.evaluate("viewer", "delete_user_file")
        assert len(d.reason) > 0


class TestGuardrailsPluginD4:
    def test_deny_blocks_tool(self):
        import asyncio
        engine = GuardrailEngine()
        plugin = GuardrailsPlugin(engine=engine)
        tool = MagicMock()
        tool.name = "delete_user_file"

        async def _run():
            with patch("data_agent.user_context.current_user_role") as mock_role:
                mock_role.get.return_value = "viewer"
                return await plugin.before_tool_callback(
                    tool=tool, tool_args={}, tool_context=MagicMock())

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result is not None
        parsed = json.loads(result)
        assert parsed["status"] == "blocked"

    def test_allow_passes_through(self):
        import asyncio
        engine = GuardrailEngine()
        plugin = GuardrailsPlugin(engine=engine)
        tool = MagicMock()
        tool.name = "describe_geodataframe"

        async def _run():
            with patch("data_agent.user_context.current_user_role") as mock_role:
                mock_role.get.return_value = "viewer"
                return await plugin.before_tool_callback(
                    tool=tool, tool_args={}, tool_context=MagicMock())

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result is None

    def test_admin_bypass_in_plugin(self):
        import asyncio
        engine = GuardrailEngine()
        plugin = GuardrailsPlugin(engine=engine)
        tool = MagicMock()
        tool.name = "delete_user_file"

        async def _run():
            with patch("data_agent.user_context.current_user_role") as mock_role:
                mock_role.get.return_value = "admin"
                return await plugin.before_tool_callback(
                    tool=tool, tool_args={}, tool_context=MagicMock())

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result is None


class TestPluginStackD4:
    @patch.dict(os.environ, {"GUARDRAILS_POLICY_ENABLED": "true"})
    def test_in_stack(self):
        from data_agent.plugins import build_plugin_stack
        plugins = build_plugin_stack()
        type_names = [type(p).__name__ for p in plugins]
        assert "GuardrailsPlugin" in type_names

    @patch.dict(os.environ, {"GUARDRAILS_POLICY_ENABLED": "false"})
    def test_disabled(self):
        from data_agent.plugins import build_plugin_stack
        plugins = build_plugin_stack()
        type_names = [type(p).__name__ for p in plugins]
        assert "GuardrailsPlugin" not in type_names


class TestConvenienceD4:
    def test_evaluate_policy_viewer(self):
        assert evaluate_policy("viewer", "delete_user_file").effect == "deny"

    def test_evaluate_policy_admin(self):
        assert evaluate_policy("admin", "delete_user_file").effect == "allow"


if __name__ == "__main__":
    unittest.main()
