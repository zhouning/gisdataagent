"""
Tests for Pipeline SSE Streaming (v9.5.4).

Tests StreamEvent dataclass, run_pipeline_streaming generator,
and SSE REST endpoint.
"""

import asyncio
import json
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# TestStreamEvent
# ---------------------------------------------------------------------------

class TestStreamEvent(unittest.TestCase):

    def test_create_text_chunk(self):
        from data_agent.pipeline_runner import StreamEvent
        e = StreamEvent(type="text_chunk", data="Hello")
        self.assertEqual(e.type, "text_chunk")
        self.assertEqual(e.data, "Hello")
        self.assertIsInstance(e.timestamp, float)

    def test_create_tool_call(self):
        from data_agent.pipeline_runner import StreamEvent
        e = StreamEvent(type="tool_call", data='{"tool": "ffi"}')
        self.assertEqual(e.type, "tool_call")
        parsed = json.loads(e.data)
        self.assertEqual(parsed["tool"], "ffi")

    def test_create_final(self):
        from data_agent.pipeline_runner import StreamEvent
        e = StreamEvent(type="final", data='{"text": "done"}')
        self.assertEqual(e.type, "final")

    def test_create_error(self):
        from data_agent.pipeline_runner import StreamEvent
        e = StreamEvent(type="error", data="Something went wrong")
        self.assertEqual(e.type, "error")

    def test_timestamp_auto_set(self):
        from data_agent.pipeline_runner import StreamEvent
        before = time.time()
        e = StreamEvent(type="test")
        after = time.time()
        self.assertGreaterEqual(e.timestamp, before)
        self.assertLessEqual(e.timestamp, after)


# ---------------------------------------------------------------------------
# TestRunPipelineStreaming
# ---------------------------------------------------------------------------

class TestRunPipelineStreaming(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.pipeline_runner.Runner")
    async def test_yields_text_chunk(self, mock_runner_cls):
        from data_agent.pipeline_runner import run_pipeline_streaming, StreamEvent
        from google.adk.sessions import InMemorySessionService

        # Create mock events
        text_event = MagicMock()
        text_event.author = "TestAgent"
        text_event.content = MagicMock()
        text_part = MagicMock()
        text_part.text = "Analysis result"
        text_part.function_call = None
        text_part.function_response = None
        text_event.content.parts = [text_part]
        text_event.usage_metadata = None

        async def mock_events(*args, **kwargs):
            yield text_event

        mock_runner = MagicMock()
        mock_runner.run_async = mock_events
        mock_runner_cls.return_value = mock_runner

        session_service = InMemorySessionService()
        events = []
        async for e in run_pipeline_streaming(
            agent=MagicMock(),
            session_service=session_service,
            user_id="test",
            session_id="s1",
            prompt="test",
        ):
            events.append(e)

        types_found = [e.type for e in events]
        self.assertIn("agent_transfer", types_found)
        self.assertIn("text_chunk", types_found)
        self.assertIn("final", types_found)

    @patch("data_agent.pipeline_runner.Runner")
    async def test_yields_tool_call(self, mock_runner_cls):
        from data_agent.pipeline_runner import run_pipeline_streaming

        # Create mock events with function call
        tool_event = MagicMock()
        tool_event.author = "AnalysisAgent"
        tool_event.content = MagicMock()
        tool_part = MagicMock()
        tool_part.text = None
        tool_part.function_call = MagicMock()
        tool_part.function_call.name = "ffi"
        tool_part.function_call.args = {"data_path": "test.shp"}
        tool_part.function_response = None
        tool_event.content.parts = [tool_part]
        tool_event.usage_metadata = None

        async def mock_events(*args, **kwargs):
            yield tool_event

        mock_runner = MagicMock()
        mock_runner.run_async = mock_events
        mock_runner_cls.return_value = mock_runner

        from google.adk.sessions import InMemorySessionService
        session_service = InMemorySessionService()

        events = []
        async for e in run_pipeline_streaming(
            agent=MagicMock(),
            session_service=session_service,
            user_id="test",
            session_id="s1",
            prompt="test",
        ):
            events.append(e)

        tool_events = [e for e in events if e.type == "tool_call"]
        self.assertEqual(len(tool_events), 1)
        data = json.loads(tool_events[0].data)
        self.assertEqual(data["tool"], "ffi")

    @patch("data_agent.pipeline_runner.Runner")
    async def test_yields_error_on_exception(self, mock_runner_cls):
        from data_agent.pipeline_runner import run_pipeline_streaming

        async def mock_events(*args, **kwargs):
            raise RuntimeError("Pipeline crashed")
            yield  # noqa — make it a generator

        mock_runner = MagicMock()
        mock_runner.run_async = mock_events
        mock_runner_cls.return_value = mock_runner

        from google.adk.sessions import InMemorySessionService
        session_service = InMemorySessionService()

        events = []
        async for e in run_pipeline_streaming(
            agent=MagicMock(),
            session_service=session_service,
            user_id="test",
            session_id="s1",
            prompt="test",
        ):
            events.append(e)

        error_events = [e for e in events if e.type == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("Pipeline crashed", error_events[0].data)


# ---------------------------------------------------------------------------
# TestSSEEndpointRoute
# ---------------------------------------------------------------------------

class TestSSEEndpointRoute(unittest.TestCase):

    def test_route_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/pipeline/stream", paths)

    def test_route_count(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 271)


if __name__ == "__main__":
    unittest.main()
