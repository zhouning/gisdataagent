"""Tests for the observability module — structured logging + Prometheus metrics."""
import json
import logging
import os
import unittest
from unittest.mock import patch

from data_agent.observability import (
    setup_logging,
    get_logger,
    JsonFormatter,
    pipeline_runs,
    pipeline_duration,
    tool_calls,
    auth_events,
    generate_latest,
    CONTENT_TYPE_LATEST,
)


class TestSetupLogging(unittest.TestCase):
    """Test setup_logging with different LOG_LEVEL and LOG_FORMAT."""

    def setUp(self):
        # Reset the configured flag so setup_logging re-runs
        import data_agent.observability as obs
        obs._CONFIGURED = False
        # Remove existing handlers to avoid duplicates
        root = logging.getLogger("data_agent")
        root.handlers.clear()

    def tearDown(self):
        import data_agent.observability as obs
        obs._CONFIGURED = False
        root = logging.getLogger("data_agent")
        root.handlers.clear()

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG", "LOG_FORMAT": "text"})
    def test_text_format_debug_level(self):
        logger = setup_logging()
        self.assertEqual(logger.name, "data_agent")
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(len(logger.handlers), 1)
        self.assertNotIsInstance(logger.handlers[0].formatter, JsonFormatter)

    @patch.dict(os.environ, {"LOG_LEVEL": "WARNING", "LOG_FORMAT": "json"})
    def test_json_format_warning_level(self):
        logger = setup_logging()
        self.assertEqual(logger.level, logging.WARNING)
        self.assertIsInstance(logger.handlers[0].formatter, JsonFormatter)

    @patch.dict(os.environ, {}, clear=False)
    def test_default_info_text(self):
        # Remove LOG_LEVEL/LOG_FORMAT if set
        os.environ.pop("LOG_LEVEL", None)
        os.environ.pop("LOG_FORMAT", None)
        logger = setup_logging()
        self.assertEqual(logger.level, logging.INFO)

    def test_idempotent(self):
        """Calling setup_logging twice should not add duplicate handlers."""
        import data_agent.observability as obs
        obs._CONFIGURED = False
        setup_logging()
        setup_logging()  # second call should be no-op
        root = logging.getLogger("data_agent")
        self.assertEqual(len(root.handlers), 1)


class TestGetLogger(unittest.TestCase):
    """Test get_logger returns child loggers."""

    def test_child_namespace(self):
        logger = get_logger("test_module")
        self.assertEqual(logger.name, "data_agent.test_module")

    def test_different_children(self):
        a = get_logger("alpha")
        b = get_logger("beta")
        self.assertNotEqual(a.name, b.name)


class TestJsonFormatter(unittest.TestCase):
    """Test JsonFormatter output structure."""

    def test_json_output(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="data_agent.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["logger"], "data_agent.test")
        self.assertEqual(parsed["msg"], "hello world")
        self.assertIn("ts", parsed)

    def test_json_with_exception(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="data_agent.err",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="fail",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        self.assertIn("exception", parsed)
        self.assertIn("ValueError", parsed["exception"])


class TestMetrics(unittest.TestCase):
    """Test Prometheus counters and histograms."""

    def test_pipeline_counter_increments(self):
        before = pipeline_runs.labels(pipeline="test_pipe", status="success")._value.get()
        pipeline_runs.labels(pipeline="test_pipe", status="success").inc()
        after = pipeline_runs.labels(pipeline="test_pipe", status="success")._value.get()
        self.assertEqual(after, before + 1)

    def test_tool_calls_counter(self):
        before = tool_calls.labels(tool_name="test_tool", status="success")._value.get()
        tool_calls.labels(tool_name="test_tool", status="success").inc()
        after = tool_calls.labels(tool_name="test_tool", status="success")._value.get()
        self.assertEqual(after, before + 1)

    def test_auth_events_counter(self):
        before = auth_events.labels(event_type="test_login")._value.get()
        auth_events.labels(event_type="test_login").inc()
        after = auth_events.labels(event_type="test_login")._value.get()
        self.assertEqual(after, before + 1)

    def test_pipeline_duration_histogram(self):
        pipeline_duration.labels(pipeline="test_pipe").observe(1.5)
        # Should not raise — histogram accepts float observations


class TestMetricsEndpoint(unittest.TestCase):
    """Test that generate_latest produces valid Prometheus output."""

    def test_generate_latest_output(self):
        output = generate_latest()
        self.assertIsInstance(output, bytes)
        text = output.decode("utf-8")
        # Should contain at least one of our metric names
        self.assertIn("agent_pipeline_runs_total", text)

    def test_content_type(self):
        self.assertIn("text/plain", CONTENT_TYPE_LATEST)


# =====================================================================
# v14.5 Phase 1 Observability Tests
# =====================================================================

class TestExtendedMetrics(unittest.TestCase):
    """Verify all v14.5 extended metrics exist and are importable."""

    def test_llm_metrics(self):
        from data_agent.observability import llm_calls, llm_duration, llm_input_tokens, llm_output_tokens
        self.assertIsNotNone(llm_calls)
        self.assertIsNotNone(llm_duration)
        self.assertIsNotNone(llm_input_tokens)
        self.assertIsNotNone(llm_output_tokens)

    def test_tool_metrics(self):
        from data_agent.observability import tool_duration, tool_retries, tool_output_bytes
        self.assertIsNotNone(tool_duration)
        self.assertIsNotNone(tool_retries)
        self.assertIsNotNone(tool_output_bytes)

    def test_pipeline_intent_metrics(self):
        from data_agent.observability import intent_classification, intent_duration, pipeline_steps
        self.assertIsNotNone(intent_classification)
        self.assertIsNotNone(intent_duration)
        self.assertIsNotNone(pipeline_steps)

    def test_cache_metrics(self):
        from data_agent.observability import cache_operations
        self.assertIsNotNone(cache_operations)

    def test_circuit_breaker_metrics(self):
        from data_agent.observability import cb_state, cb_trips
        self.assertIsNotNone(cb_state)
        self.assertIsNotNone(cb_trips)

    def test_http_metrics(self):
        from data_agent.observability import http_requests, http_duration
        self.assertIsNotNone(http_requests)
        self.assertIsNotNone(http_duration)


class TestRecordFunctions(unittest.TestCase):
    """Verify convenience recording functions don't raise."""

    def test_record_llm_call(self):
        from data_agent.observability import record_llm_call
        record_llm_call("test_agent", "gemini-2.0-flash", 500, 100, 1.5)

    def test_record_tool_execution(self):
        from data_agent.observability import record_tool_execution
        record_tool_execution("describe_geodataframe", "explorer", 2.5, 1024, "success")

    def test_record_intent(self):
        from data_agent.observability import record_intent
        record_intent("GOVERNANCE", "zh", 0.3)

    def test_record_cache_op(self):
        from data_agent.observability import record_cache_op
        record_cache_op("semantic_sources", "hit")
        record_cache_op("semantic_sources", "miss")

    def test_record_circuit_breaker(self):
        from data_agent.observability import record_circuit_breaker
        record_circuit_breaker("check_topology", "closed")
        record_circuit_breaker("check_topology", "open", tripped=True)


class TestPathNormalization(unittest.TestCase):
    """Verify URL path normalization."""

    def test_numeric_id(self):
        from data_agent.observability import _normalize_path
        self.assertEqual(_normalize_path("/api/skills/123"), "/api/skills/{id}")

    def test_nested_ids(self):
        from data_agent.observability import _normalize_path
        self.assertEqual(_normalize_path("/api/kb/5/documents/10"), "/api/kb/{id}/documents/{id}")

    def test_no_id(self):
        from data_agent.observability import _normalize_path
        self.assertEqual(_normalize_path("/api/virtual-sources"), "/api/virtual-sources")

    def test_uuid_path(self):
        from data_agent.observability import _normalize_path
        result = _normalize_path("/api/tasks/550e8400-e29b-41d4-a716-446655440000")
        self.assertIn("{uuid}", result)


class TestObservabilityMiddleware(unittest.IsolatedAsyncioTestCase):
    """Test HTTP observability middleware."""

    async def test_non_api_path_skipped(self):
        from data_agent.observability import ObservabilityMiddleware
        from unittest.mock import AsyncMock

        app = AsyncMock()
        middleware = ObservabilityMiddleware(app)
        scope = {"type": "http", "path": "/assets/style.css", "method": "GET"}
        await middleware(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    async def test_non_http_passthrough(self):
        from data_agent.observability import ObservabilityMiddleware
        from unittest.mock import AsyncMock

        app = AsyncMock()
        middleware = ObservabilityMiddleware(app)
        scope = {"type": "websocket", "path": "/ws"}
        await middleware(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    async def test_api_path_records_metrics(self):
        from data_agent.observability import ObservabilityMiddleware
        from unittest.mock import AsyncMock

        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b""})

        middleware = ObservabilityMiddleware(fake_app)
        scope = {"type": "http", "path": "/api/virtual-sources", "method": "GET"}
        sent_msgs = []

        async def capture_send(msg):
            sent_msgs.append(msg)

        await middleware(scope, AsyncMock(), capture_send)
        self.assertEqual(len(sent_msgs), 2)


if __name__ == "__main__":
    unittest.main()
