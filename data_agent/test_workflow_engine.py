"""
Tests for workflow engine (v5.4).
Tests CRUD, execution, webhook, scheduler, and API route registration.
"""

import asyncio
import json
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# TestEnsureWorkflowTables
# ---------------------------------------------------------------------------

class TestEnsureWorkflowTables(unittest.TestCase):
    """Test table creation and graceful degradation."""

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_eng):
        """When DB is not configured, should not raise."""
        from data_agent.workflow_engine import ensure_workflow_tables
        ensure_workflow_tables()  # should not raise

    @patch("data_agent.workflow_engine.get_engine")
    def test_creates_tables(self, mock_eng):
        """Should execute CREATE TABLE statements."""
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.workflow_engine import ensure_workflow_tables
        ensure_workflow_tables()

        calls = mock_conn.execute.call_args_list
        sql_texts = [str(c[0][0].text) if hasattr(c[0][0], 'text') else str(c[0][0]) for c in calls]
        sql_combined = " ".join(sql_texts)
        self.assertIn("agent_workflows", sql_combined)
        self.assertIn("agent_workflow_runs", sql_combined)

    @patch("data_agent.workflow_engine.get_engine")
    def test_db_error_graceful(self, mock_eng):
        """DB error during table creation should not raise."""
        mock_eng.return_value.connect.side_effect = Exception("DB down")
        from data_agent.workflow_engine import ensure_workflow_tables
        ensure_workflow_tables()  # should not raise


# ---------------------------------------------------------------------------
# TestWorkflowCRUD
# ---------------------------------------------------------------------------

class TestWorkflowCRUD(unittest.TestCase):
    """Test create, get, list, update, delete operations."""

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_create_no_db(self, mock_eng, mock_user):
        """Create returns None when DB is unavailable."""
        from data_agent.workflow_engine import create_workflow
        result = create_workflow("test", "desc", [])
        self.assertIsNone(result)

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_get_no_db(self, mock_eng, mock_user):
        """Get returns None when DB is unavailable."""
        from data_agent.workflow_engine import get_workflow
        result = get_workflow(1)
        self.assertIsNone(result)

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_list_no_db(self, mock_eng):
        """List returns empty list when DB is unavailable."""
        from data_agent.workflow_engine import list_workflows
        result = list_workflows()
        self.assertEqual(result, [])

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_update_no_db(self, mock_eng, mock_user):
        """Update returns False when DB is unavailable."""
        from data_agent.workflow_engine import update_workflow
        result = update_workflow(1, workflow_name="new")
        self.assertFalse(result)

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_delete_no_db(self, mock_eng, mock_user):
        """Delete returns False when DB is unavailable."""
        from data_agent.workflow_engine import delete_workflow
        result = delete_workflow(1)
        self.assertFalse(result)

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine")
    def test_create_no_user(self, mock_eng, mock_user):
        """Create returns None when no user context."""
        mock_user.get.return_value = None
        mock_eng.return_value = MagicMock()
        from data_agent.workflow_engine import create_workflow
        result = create_workflow("test")
        self.assertIsNone(result)

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine")
    def test_update_filters_invalid_fields(self, mock_eng, mock_user):
        """Update should ignore fields not in allowed set."""
        mock_user.get.return_value = "testuser"
        from data_agent.workflow_engine import update_workflow
        result = update_workflow(1, invalid_field="value")
        self.assertFalse(result)

    @patch("data_agent.workflow_engine.current_user_id")
    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_delete_no_user(self, mock_eng, mock_user):
        """Delete returns False when no user context."""
        mock_user.get.return_value = None
        mock_eng.return_value = MagicMock()
        from data_agent.workflow_engine import delete_workflow
        result = delete_workflow(1)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestSubstituteParams
# ---------------------------------------------------------------------------

class TestSubstituteParams(unittest.TestCase):
    """Test parameter substitution in prompts."""

    def test_basic_substitution(self):
        from data_agent.workflow_engine import _substitute_params
        result = _substitute_params("分析 {data_file} 的质量", {"data_file": "parcels.shp"})
        self.assertEqual(result, "分析 parcels.shp 的质量")

    def test_multiple_params(self):
        from data_agent.workflow_engine import _substitute_params
        result = _substitute_params(
            "从 {input} 导出 {format}",
            {"input": "data.csv", "format": "geojson"},
        )
        self.assertEqual(result, "从 data.csv 导出 geojson")

    def test_no_params(self):
        from data_agent.workflow_engine import _substitute_params
        result = _substitute_params("固定文本", {})
        self.assertEqual(result, "固定文本")

    def test_missing_param(self):
        from data_agent.workflow_engine import _substitute_params
        result = _substitute_params("加载 {missing}", {})
        self.assertEqual(result, "加载 {missing}")


# ---------------------------------------------------------------------------
# TestGetAgentForPipeline
# ---------------------------------------------------------------------------

class TestGetAgentForPipeline(unittest.TestCase):
    """Test pipeline_type → agent mapping."""

    def test_known_types(self):
        from data_agent.workflow_engine import _get_agent_for_pipeline
        module = MagicMock()
        module.general_pipeline = "gp"
        module.governance_pipeline = "gov"
        module.data_pipeline = "dp"
        module.planner_agent = "pa"

        self.assertEqual(_get_agent_for_pipeline(module, "general"), "gp")
        self.assertEqual(_get_agent_for_pipeline(module, "governance"), "gov")
        self.assertEqual(_get_agent_for_pipeline(module, "optimization"), "dp")
        self.assertEqual(_get_agent_for_pipeline(module, "planner"), "pa")

    def test_unknown_type(self):
        from data_agent.workflow_engine import _get_agent_for_pipeline
        module = MagicMock()
        result = _get_agent_for_pipeline(module, "nonexistent")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestExecuteWorkflow
# ---------------------------------------------------------------------------

class TestExecuteWorkflow(unittest.TestCase):
    """Test workflow execution logic."""

    @patch("data_agent.workflow_engine.get_workflow", return_value=None)
    def test_workflow_not_found(self, mock_get):
        from data_agent.workflow_engine import execute_workflow
        result = asyncio.run(execute_workflow(999))
        self.assertEqual(result["status"], "failed")
        self.assertIn("not found", result["error"])

    @patch("data_agent.workflow_engine.get_workflow")
    def test_empty_steps(self, mock_get):
        mock_get.return_value = {
            "workflow_name": "test",
            "owner_username": "user1",
            "steps": [],
            "parameters": {},
            "webhook_url": None,
        }
        from data_agent.workflow_engine import execute_workflow
        result = asyncio.run(execute_workflow(1))
        self.assertEqual(result["status"], "failed")
        self.assertIn("no steps", result["error"])


# ---------------------------------------------------------------------------
# TestSendWebhook
# ---------------------------------------------------------------------------

class TestSendWebhook(unittest.TestCase):
    """Test webhook sending."""

    def test_empty_url(self):
        from data_agent.workflow_engine import send_webhook
        result = asyncio.run(send_webhook("", {}))
        self.assertFalse(result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_successful_webhook(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        from data_agent.workflow_engine import send_webhook
        result = asyncio.run(
            send_webhook("https://example.com/hook", {"status": "ok"})
        )
        self.assertTrue(result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    def test_failed_webhook(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        from data_agent.workflow_engine import send_webhook
        result = asyncio.run(
            send_webhook("https://example.com/hook", {"status": "ok"})
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestWorkflowScheduler
# ---------------------------------------------------------------------------

class TestWorkflowScheduler(unittest.TestCase):
    """Test scheduler start/stop/sync."""

    def test_start_without_apscheduler(self):
        """Should handle ImportError gracefully."""
        from data_agent.workflow_engine import WorkflowScheduler
        scheduler = WorkflowScheduler()
        with patch.dict("sys.modules", {"apscheduler.schedulers.asyncio": None}):
            scheduler.start()  # should not raise

    def test_stop_no_scheduler(self):
        """Stop without start should not raise."""
        from data_agent.workflow_engine import WorkflowScheduler
        scheduler = WorkflowScheduler()
        scheduler.stop()  # should not raise

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_sync_jobs_no_db(self, mock_eng):
        """sync_jobs with no DB should not raise."""
        from data_agent.workflow_engine import WorkflowScheduler
        scheduler = WorkflowScheduler()
        scheduler._scheduler = MagicMock()
        scheduler.sync_jobs()


# ---------------------------------------------------------------------------
# TestWorkflowRuns
# ---------------------------------------------------------------------------

class TestWorkflowRuns(unittest.TestCase):
    """Test execution history retrieval."""

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    def test_no_db(self, mock_eng):
        from data_agent.workflow_engine import get_workflow_runs
        result = get_workflow_runs(1)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# TestWorkflowAPI
# ---------------------------------------------------------------------------

class TestWorkflowAPI(unittest.TestCase):
    """Test API route registration."""

    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]

        self.assertIn("/api/workflows", paths)
        self.assertIn("/api/workflows/{id:int}", paths)
        self.assertIn("/api/workflows/{id:int}/execute", paths)
        self.assertIn("/api/workflows/{id:int}/runs", paths)

    def test_route_count(self):
        """Should have 36 routes (29 existing + 7 workflow)."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 38)

    def test_workflow_methods(self):
        """Verify HTTP methods for workflow routes."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        wf_routes = [r for r in routes if r.path.startswith("/api/workflows")]
        methods = set()
        for r in wf_routes:
            for m in r.methods:
                methods.add(m)
        self.assertIn("GET", methods)
        self.assertIn("POST", methods)
        self.assertIn("PUT", methods)
        self.assertIn("DELETE", methods)


if __name__ == "__main__":
    unittest.main()
