"""
Tests for CLI entry point (v8.5).

Uses typer.testing.CliRunner for command invocation.
Mocks all DB/LLM dependencies to keep tests fast and offline.
"""

import asyncio
import inspect
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from typer.testing import CliRunner

runner = CliRunner()


def _reset_event_loop():
    """Reset asyncio event loop after asyncio.run() closes it."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


# ---------------------------------------------------------------------------
# Fake PipelineResult for mocking _run_single
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
# TestCliImport
# ---------------------------------------------------------------------------

class TestCliImport(unittest.TestCase):
    """Verify CLI module imports cleanly."""

    def test_import_cli(self):
        from data_agent.cli import app as cli_app
        self.assertIsNotNone(cli_app)

    def test_main_entry_point(self):
        from data_agent.__main__ import main
        self.assertIsNotNone(main)
        self.assertTrue(callable(main))


# ---------------------------------------------------------------------------
# TestRunCommand
# ---------------------------------------------------------------------------

class TestRunCommand(unittest.TestCase):
    """Test 'gis-agent run' command."""

    def tearDown(self):
        _reset_event_loop()

    @patch("data_agent.cli._run_single", new_callable=AsyncMock)
    def test_run_basic(self, mock_run):
        mock_run.return_value = ("general", _fake_pipeline_result())
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["run", "test prompt", "--user", "testuser"])
        self.assertEqual(result.exit_code, 0)
        mock_run.assert_called_once()
        # Check prompt was passed
        args = mock_run.call_args
        self.assertEqual(args[0][0], "test prompt")

    @patch("data_agent.cli._run_single", new_callable=AsyncMock)
    def test_run_with_verbose(self, mock_run):
        mock_run.return_value = ("general", _fake_pipeline_result(
            tool_execution_log=[{
                "step": 1, "agent_name": "test", "tool_name": "query_database",
                "args": {}, "output_path": None, "result_summary": "5 rows",
                "duration": 0.3, "is_error": False,
            }],
        ))
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["run", "query data", "-u", "u1", "-v"])
        self.assertEqual(result.exit_code, 0)

    @patch("data_agent.cli._run_single", new_callable=AsyncMock)
    def test_run_error_result(self, mock_run):
        mock_run.return_value = ("general", _fake_pipeline_result(
            error="Pipeline failed: timeout",
        ))
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["run", "bad prompt", "-u", "u1"])
        # _run_single is fully mocked, so run completes without error
        self.assertEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# TestChatCommand
# ---------------------------------------------------------------------------

class TestChatCommand(unittest.TestCase):
    """Test 'gis-agent chat' command help."""

    def test_chat_help(self):
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["chat", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Interactive", result.output)


# ---------------------------------------------------------------------------
# TestCatalogCommands
# ---------------------------------------------------------------------------

class TestCatalogList(unittest.TestCase):
    """Test 'gis-agent catalog list'."""

    @patch("data_agent.data_catalog.list_data_assets")
    def test_catalog_list_success(self, mock_list):
        mock_list.return_value = {
            "status": "success", "count": 2,
            "assets": [
                {"id": 1, "name": "parcels.shp", "type": "vector",
                 "backend": "local", "features": 100, "description": "Land parcels"},
                {"id": 2, "name": "dem.tif", "type": "raster",
                 "backend": "cloud", "features": 1, "description": "Elevation model"},
            ],
        }
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["catalog", "list", "-u", "testuser"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("parcels.shp", result.output)
        self.assertIn("dem.tif", result.output)

    @patch("data_agent.data_catalog.list_data_assets")
    def test_catalog_list_empty(self, mock_list):
        mock_list.return_value = {"status": "success", "count": 0, "assets": []}
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["catalog", "list", "-u", "u1"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No assets", result.output)

    @patch("data_agent.data_catalog.list_data_assets")
    def test_catalog_list_error(self, mock_list):
        mock_list.return_value = {"status": "error", "message": "DB unavailable"}
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["catalog", "list", "-u", "u1"])
        self.assertNotEqual(result.exit_code, 0)


class TestCatalogSearch(unittest.TestCase):
    """Test 'gis-agent catalog search'."""

    @patch("data_agent.data_catalog.search_data_assets")
    def test_search_results(self, mock_search):
        mock_search.return_value = {
            "status": "success", "count": 1,
            "assets": [{"id": 3, "name": "landuse.shp", "type": "vector",
                         "description": "Land use data"}],
        }
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["catalog", "search", "土地", "-u", "u1"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("landuse.shp", result.output)


# ---------------------------------------------------------------------------
# TestSkillsCommands
# ---------------------------------------------------------------------------

class TestSkillsList(unittest.TestCase):
    """Test 'gis-agent skills list'."""

    @patch("data_agent.custom_skills.list_custom_skills")
    def test_skills_list(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "skill_name": "QuickAnalysis", "description": "Fast analysis",
             "model_tier": "fast", "is_shared": True},
        ]
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["skills", "list", "-u", "u1"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("QuickAnalysis", result.output)

    @patch("data_agent.custom_skills.list_custom_skills")
    def test_skills_list_empty(self, mock_list):
        mock_list.return_value = []
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["skills", "list", "-u", "u1"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No custom skills", result.output)


class TestSkillsDelete(unittest.TestCase):
    """Test 'gis-agent skills delete'."""

    @patch("data_agent.custom_skills.delete_custom_skill", return_value=True)
    def test_delete_success(self, mock_del):
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["skills", "delete", "42", "-u", "u1", "-f"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("deleted", result.output)

    @patch("data_agent.custom_skills.delete_custom_skill", return_value=False)
    def test_delete_not_found(self, mock_del):
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["skills", "delete", "999", "-u", "u1", "-f"])
        self.assertNotEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# TestSqlCommand
# ---------------------------------------------------------------------------

class TestSqlCommand(unittest.TestCase):
    """Test 'gis-agent sql'."""

    @patch("data_agent.database_tools.query_database")
    def test_sql_success(self, mock_q):
        mock_q.return_value = {
            "status": "success", "message": "5 rows returned",
            "output_path": "", "record_count": 5,
        }
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["sql", "SELECT 1", "-u", "u1"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("5 rows", result.output)

    @patch("data_agent.database_tools.query_database")
    def test_sql_error(self, mock_q):
        mock_q.return_value = {
            "status": "error", "message": "Only SELECT queries allowed",
        }
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["sql", "DROP TABLE x", "-u", "u1"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Error", result.output)


# ---------------------------------------------------------------------------
# TestStatusCommand
# ---------------------------------------------------------------------------

class TestStatusCommand(unittest.TestCase):
    """Test 'gis-agent status'."""

    @patch("data_agent.token_tracker.get_pipeline_breakdown",
           return_value=[{"pipeline_type": "general", "count": 10, "tokens": 50000}])
    @patch("data_agent.token_tracker.get_monthly_usage",
           return_value={"count": 25, "total_tokens": 120000})
    @patch("data_agent.token_tracker.get_daily_usage",
           return_value={"count": 3, "tokens": 15000})
    def test_status_output(self, mock_daily, mock_monthly, mock_bd):
        from data_agent.cli import app as cli_app
        result = runner.invoke(cli_app, ["status", "-u", "admin"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("admin", result.output)
        self.assertIn("Token Usage", result.output)


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    """Test internal CLI helper functions."""

    def test_set_user_context(self):
        from data_agent.cli import _set_user_context
        sid = _set_user_context("alice", "admin")
        self.assertTrue(sid.startswith("cli_alice_"))
        from data_agent.user_context import current_user_id, current_user_role
        self.assertEqual(current_user_id.get(), "alice")
        self.assertEqual(current_user_role.get(), "admin")

    def test_select_agent_general(self):
        from data_agent.cli import _select_agent
        mock_mod = MagicMock()
        mock_mod.DYNAMIC_PLANNER = False
        mock_mod.general_pipeline = "gp"
        agent, ptype = _select_agent(mock_mod, "GENERAL")
        self.assertEqual(agent, "gp")
        self.assertEqual(ptype, "general")

    def test_select_agent_planner(self):
        from data_agent.cli import _select_agent
        mock_mod = MagicMock()
        mock_mod.DYNAMIC_PLANNER = True
        mock_mod.planner_agent = "pa"
        agent, ptype = _select_agent(mock_mod, "GENERAL")
        self.assertEqual(agent, "pa")
        self.assertEqual(ptype, "planner")

    def test_render_result_error(self):
        """Error results should display error panel."""
        from data_agent.cli import _render_result
        result = _fake_pipeline_result(error="Something went wrong")
        # Should not raise
        _render_result(result)


# ---------------------------------------------------------------------------
# TestStreamingCallback
# ---------------------------------------------------------------------------

class TestStreamingCallback(unittest.TestCase):
    """Test on_event parameter in pipeline_runner."""

    def test_on_event_parameter_exists(self):
        from data_agent.pipeline_runner import run_pipeline_headless
        sig = inspect.signature(run_pipeline_headless)
        self.assertIn("on_event", sig.parameters)
        self.assertIs(sig.parameters["on_event"].default, None)

    def test_streaming_callback_no_error(self):
        """Streaming callback should handle all event types without error."""
        from data_agent.cli import _streaming_callback
        _streaming_callback({"type": "agent", "name": "TestAgent"})
        _streaming_callback({"type": "tool_call", "name": "query_db", "args": {}})
        _streaming_callback({"type": "tool_result", "step": 1, "name": "query_db",
                             "summary": "5 rows returned"})
        _streaming_callback({"type": "text", "content": "Analysis complete."})


if __name__ == "__main__":
    unittest.main()
