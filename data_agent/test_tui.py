"""
Tests for TUI module (v8.5.3).

Uses Textual's App.run_test() for headless widget testing.
Mocks all DB/LLM dependencies to keep tests fast and offline.
"""

import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Fake PipelineResult (shared with test_cli.py)
# ---------------------------------------------------------------------------

def _fake_pipeline_result(**kwargs):
    from data_agent.pipeline_runner import PipelineResult
    defaults = {
        "report_text": "Test analysis report.",
        "generated_files": [],
        "tool_execution_log": [],
        "pipeline_type": "general",
        "intent": "GENERAL",
        "total_input_tokens": 100,
        "total_output_tokens": 200,
        "duration_seconds": 1.5,
        "error": None,
    }
    defaults.update(kwargs)
    return PipelineResult(**defaults)


# ---------------------------------------------------------------------------
# TestTUIImport
# ---------------------------------------------------------------------------

class TestTUIImport(unittest.TestCase):
    """Verify TUI module imports cleanly."""

    def test_import_tui(self):
        from data_agent.tui import GISAgentApp
        self.assertIsNotNone(GISAgentApp)

    def test_instantiate_app(self):
        from data_agent.tui import GISAgentApp
        app = GISAgentApp(user="testuser", role="analyst")
        self.assertEqual(app.user, "testuser")
        self.assertEqual(app.role, "analyst")
        self.assertFalse(app.verbose)


# ---------------------------------------------------------------------------
# TestTUICompose — async tests via Textual run_test()
# ---------------------------------------------------------------------------

class TestTUICompose(unittest.IsolatedAsyncioTestCase):
    """Test widget tree composition."""

    async def test_all_panel_ids_present(self):
        from data_agent.tui import GISAgentApp
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            assert app.query_one("#chat-panel") is not None
            assert app.query_one("#report-panel") is not None
            assert app.query_one("#status-panel") is not None
            assert app.query_one("#chat-log") is not None
            assert app.query_one("#report-log") is not None
            assert app.query_one("#status-log") is not None
            assert app.query_one("#chat-input") is not None

    async def test_headers_present(self):
        from data_agent.tui import GISAgentApp
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            report_header = app.query_one("#report-header")
            status_header = app.query_one("#status-header")
            # Static widgets contain text
            self.assertIsNotNone(report_header)
            self.assertIsNotNone(status_header)


# ---------------------------------------------------------------------------
# TestTUICommands
# ---------------------------------------------------------------------------

class TestTUICommands(unittest.IsolatedAsyncioTestCase):
    """Test slash command handling."""

    async def test_help_command(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            app._handle_command("/help")
            # chat-log should have content (help text)
            log = app.query_one("#chat-log", RichLog)
            self.assertTrue(len(log.lines) > 0)

    async def test_verbose_toggle(self):
        from data_agent.tui import GISAgentApp
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            self.assertFalse(app.verbose)
            app._handle_command("/verbose")
            self.assertTrue(app.verbose)
            app._handle_command("/verbose")
            self.assertFalse(app.verbose)

    async def test_unknown_command(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            app._handle_command("/foobar")
            log = app.query_one("#chat-log", RichLog)
            self.assertTrue(len(log.lines) > 0)

    async def test_clear_command(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            # Write something first
            app._write_chat("test message")
            chat_log = app.query_one("#chat-log", RichLog)
            self.assertTrue(len(chat_log.lines) > 0)
            # Clear
            app.action_clear_panels()
            # After clear, line count should be 0
            self.assertEqual(len(chat_log.lines), 0)

    async def test_sql_no_args(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            app._handle_command("/sql")
            log = app.query_one("#chat-log", RichLog)
            self.assertTrue(len(log.lines) > 0)


# ---------------------------------------------------------------------------
# TestTUIStatus
# ---------------------------------------------------------------------------

class TestTUIStatus(unittest.IsolatedAsyncioTestCase):
    """Test /status command rendering."""

    @patch("data_agent.token_tracker.get_pipeline_breakdown",
           return_value=[{"pipeline_type": "general", "count": 5, "tokens": 30000}])
    @patch("data_agent.token_tracker.get_monthly_usage",
           return_value={"count": 20, "total_tokens": 80000})
    @patch("data_agent.token_tracker.get_daily_usage",
           return_value={"count": 3, "tokens": 10000})
    @patch("data_agent.cli._set_user_context", return_value="cli_test_abc")
    @patch("data_agent.cli._load_env")
    async def test_status_renders_table(self, mock_env, mock_ctx,
                                         mock_daily, mock_monthly, mock_bd):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="admin", role="admin")
        async with app.run_test() as pilot:
            app._show_status()
            status_log = app.query_one("#status-log", RichLog)
            # Should have written at least the token table
            self.assertTrue(len(status_log.lines) > 0)


# ---------------------------------------------------------------------------
# TestTUIHelpers
# ---------------------------------------------------------------------------

class TestTUIHelpers(unittest.IsolatedAsyncioTestCase):
    """Test helper write methods."""

    async def test_write_chat(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            app._write_chat("[bold]Hello[/bold]")
            log = app.query_one("#chat-log", RichLog)
            self.assertTrue(len(log.lines) > 0)

    async def test_write_status(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            app._write_status("[green]OK[/green]")
            log = app.query_one("#status-log", RichLog)
            self.assertTrue(len(log.lines) > 0)

    async def test_render_pipeline_result_error(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            result = _fake_pipeline_result(error="Something went wrong")
            app._render_pipeline_result(result)
            report_log = app.query_one("#report-log", RichLog)
            self.assertTrue(len(report_log.lines) > 0)

    async def test_render_pipeline_result_success(self):
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            result = _fake_pipeline_result(
                report_text="# Analysis\n\nData shows 10 parcels.",
                generated_files=["output/map_abc.html"],
            )
            app._render_pipeline_result(result)
            report_log = app.query_one("#report-log", RichLog)
            self.assertTrue(len(report_log.lines) > 0)


# ---------------------------------------------------------------------------
# TestTUIEventCallback
# ---------------------------------------------------------------------------

class TestTUIEventCallback(unittest.IsolatedAsyncioTestCase):
    """Test that on_event types are handled without error."""

    async def test_write_all_event_types(self):
        """Simulating what tui_event_callback does internally."""
        from data_agent.tui import GISAgentApp
        from textual.widgets import RichLog
        app = GISAgentApp(user="test", role="analyst")
        async with app.run_test() as pilot:
            # Simulate the 4 event types going to their panels
            app._write_status("[dim cyan]Agent: TestAgent[/dim cyan]")
            app._write_status("[dim]>> query_database()[/dim]")
            app._write_status("[dim]   #1 [green]ok[/green] 5 rows[/dim]")
            app._write_report("Analysis text chunk.")

            status_log = app.query_one("#status-log", RichLog)
            report_log = app.query_one("#report-log", RichLog)
            self.assertTrue(len(status_log.lines) > 0)
            self.assertTrue(len(report_log.lines) > 0)


if __name__ == "__main__":
    unittest.main()
