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


if __name__ == "__main__":
    unittest.main()
