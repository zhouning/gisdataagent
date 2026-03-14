"""
Tests for Agent Lifecycle Hooks (v9.0.6).

Tests before/after callbacks, ProgressTracker, and attach_lifecycle_hooks.
"""

import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callback_context(state=None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_agent(name="TestAgent"):
    agent = MagicMock()
    agent.name = name
    return agent


# ---------------------------------------------------------------------------
# TestProgressTracker
# ---------------------------------------------------------------------------

class TestProgressTracker(unittest.TestCase):

    def test_init(self):
        from data_agent.agent_hooks import ProgressTracker
        pt = ProgressTracker("optimization")
        self.assertEqual(pt.pipeline_type, "optimization")
        self.assertEqual(len(pt.expected), 5)
        self.assertEqual(pt.completed, [])

    def test_update_progress(self):
        from data_agent.agent_hooks import ProgressTracker
        pt = ProgressTracker("optimization")
        result = pt.update("DataExploration")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["current_agent"], "DataExploration")
        self.assertAlmostEqual(result["percent"], 20.0)

    def test_full_completion(self):
        from data_agent.agent_hooks import ProgressTracker
        pt = ProgressTracker("governance")
        pt.update("GovExploration")
        pt.update("GovProcessing")
        result = pt.update("GovernanceReporter")
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["percent"], 100.0)

    def test_unknown_pipeline(self):
        from data_agent.agent_hooks import ProgressTracker
        pt = ProgressTracker("custom")
        self.assertEqual(pt.expected, [])
        result = pt.update("CustomAgent")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["percent"], 100.0)

    def test_no_duplicate_completion(self):
        from data_agent.agent_hooks import ProgressTracker
        pt = ProgressTracker("general")
        pt.update("GeneralProcessing")
        pt.update("GeneralProcessing")  # duplicate
        self.assertEqual(len(pt.completed), 1)


# ---------------------------------------------------------------------------
# TestBeforeCallback
# ---------------------------------------------------------------------------

class TestBeforeCallback(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.agent_hooks._ensure_metrics")
    async def test_records_start_time(self, mock_metrics):
        from data_agent.agent_hooks import before_pipeline_agent
        # Ensure mocked metrics
        import data_agent.agent_hooks as hooks
        hooks._agent_invocations = MagicMock()

        ctx = _make_callback_context({"__pipeline_type__": "general"})
        agent = _make_agent("GeneralProcessing")

        result = await before_pipeline_agent(agent=agent, callback_context=ctx)
        self.assertIsNone(result)
        self.assertIn("__agent_start_GeneralProcessing__", ctx.state)
        self.assertIsInstance(ctx.state["__agent_start_GeneralProcessing__"], float)

    @patch("data_agent.agent_hooks._ensure_metrics")
    async def test_increments_counter(self, mock_metrics):
        from data_agent.agent_hooks import before_pipeline_agent
        import data_agent.agent_hooks as hooks
        mock_counter = MagicMock()
        hooks._agent_invocations = mock_counter

        ctx = _make_callback_context({"__pipeline_type__": "optimization"})
        agent = _make_agent("DataExploration")

        await before_pipeline_agent(agent=agent, callback_context=ctx)
        mock_counter.labels.assert_called_once_with(
            agent_name="DataExploration", pipeline_type="optimization"
        )
        mock_counter.labels().inc.assert_called_once()


# ---------------------------------------------------------------------------
# TestAfterCallback
# ---------------------------------------------------------------------------

class TestAfterCallback(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.agent_hooks._ensure_metrics")
    async def test_records_duration(self, mock_metrics):
        from data_agent.agent_hooks import after_pipeline_agent
        import data_agent.agent_hooks as hooks
        hooks._agent_duration = MagicMock()

        start = time.time() - 2.5
        ctx = _make_callback_context({
            "__pipeline_type__": "general",
            "__agent_start_GeneralViz__": start,
        })
        agent = _make_agent("GeneralViz")

        result = await after_pipeline_agent(agent=agent, callback_context=ctx)
        self.assertIsNone(result)
        hooks._agent_duration.labels.assert_called_once_with(
            agent_name="GeneralViz", pipeline_type="general"
        )
        # Duration should be ~2.5s
        call_args = hooks._agent_duration.labels().observe.call_args
        observed = call_args[0][0]
        self.assertGreater(observed, 2.0)

    @patch("data_agent.agent_hooks._ensure_metrics")
    async def test_tracks_completed_agents(self, mock_metrics):
        from data_agent.agent_hooks import after_pipeline_agent, _COMPLETED_KEY
        import data_agent.agent_hooks as hooks
        hooks._agent_duration = MagicMock()

        ctx = _make_callback_context({
            "__pipeline_type__": "optimization",
            "__agent_start_DataExploration__": time.time(),
        })
        agent = _make_agent("DataExploration")

        await after_pipeline_agent(agent=agent, callback_context=ctx)
        self.assertIn("DataExploration", ctx.state[_COMPLETED_KEY])


# ---------------------------------------------------------------------------
# TestAttachLifecycleHooks
# ---------------------------------------------------------------------------

class TestAttachLifecycleHooks(unittest.TestCase):

    def test_attaches_to_llm_agents(self):
        from data_agent.agent_hooks import attach_lifecycle_hooks
        from google.adk.agents import LlmAgent

        # Create mock LlmAgent
        agent = MagicMock(spec=LlmAgent)
        agent.name = "TestLlmAgent"
        agent.before_agent_callback = None
        agent.after_agent_callback = None
        agent.sub_agents = []

        attach_lifecycle_hooks(agent, "general")

        # Callbacks should be set
        self.assertIsNotNone(agent.before_agent_callback)
        self.assertIsNotNone(agent.after_agent_callback)

    def test_skips_non_llm_agents(self):
        from data_agent.agent_hooks import attach_lifecycle_hooks
        from google.adk.agents import SequentialAgent

        agent = MagicMock(spec=SequentialAgent)
        agent.name = "SeqAgent"
        agent.sub_agents = []

        attach_lifecycle_hooks(agent, "general")
        # SequentialAgent should NOT get callbacks
        # (no before_agent_callback set)

    def test_recurses_sub_agents(self):
        from data_agent.agent_hooks import attach_lifecycle_hooks
        from google.adk.agents import LlmAgent, SequentialAgent

        child1 = MagicMock(spec=LlmAgent)
        child1.name = "Child1"
        child1.before_agent_callback = None
        child1.after_agent_callback = None
        child1.sub_agents = []

        child2 = MagicMock(spec=LlmAgent)
        child2.name = "Child2"
        child2.before_agent_callback = None
        child2.after_agent_callback = None
        child2.sub_agents = []

        parent = MagicMock(spec=SequentialAgent)
        parent.name = "Parent"
        parent.sub_agents = [child1, child2]

        attach_lifecycle_hooks(parent, "optimization")

        # Both children should have callbacks
        self.assertIsNotNone(child1.before_agent_callback)
        self.assertIsNotNone(child2.after_agent_callback)

    def test_preserves_existing_callbacks(self):
        from data_agent.agent_hooks import attach_lifecycle_hooks, before_pipeline_agent
        from google.adk.agents import LlmAgent

        existing_before = MagicMock()
        agent = MagicMock(spec=LlmAgent)
        agent.name = "AgentWithCallback"
        agent.before_agent_callback = existing_before
        agent.after_agent_callback = None
        agent.sub_agents = []

        attach_lifecycle_hooks(agent, "general")

        # Should be a list with our hook + existing
        self.assertIsInstance(agent.before_agent_callback, list)
        self.assertEqual(len(agent.before_agent_callback), 2)
        self.assertEqual(agent.before_agent_callback[0], before_pipeline_agent)
        self.assertEqual(agent.before_agent_callback[1], existing_before)


if __name__ == "__main__":
    unittest.main()
