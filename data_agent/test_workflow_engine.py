"""
Tests for workflow engine (v5.4 + v8.0.3 DAG).
Tests CRUD, execution, webhook, scheduler, DAG engine, and API route registration.
"""

import asyncio
import json
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass, field


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
        """Should have 44 routes (37 existing + 7 workflow)."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 191)

    def test_dag_status_route(self):
        """DAG live status route should be registered."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/workflows/{id:int}/runs/{run_id:int}/status", paths)

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


# ---------------------------------------------------------------------------
# Fake PipelineResult for DAG execution tests
# ---------------------------------------------------------------------------

@dataclass
class _FakePipelineResult:
    report_text: str = "Analysis done."
    generated_files: list = field(default_factory=list)
    tool_execution_log: list = field(default_factory=list)
    pipeline_type: str = "general"
    intent: str = "GENERAL"
    total_input_tokens: int = 10
    total_output_tokens: int = 20
    duration_seconds: float = 0.5
    error: str = None


# ---------------------------------------------------------------------------
# TestIsDagWorkflow
# ---------------------------------------------------------------------------

class TestIsDagWorkflow(unittest.TestCase):
    """Test _is_dag_workflow detection."""

    def test_sequential_returns_false(self):
        from data_agent.workflow_engine import _is_dag_workflow
        steps = [
            {"step_id": "a", "prompt": "x"},
            {"step_id": "b", "prompt": "y", "depends_on": []},
        ]
        self.assertFalse(_is_dag_workflow(steps))

    def test_dag_returns_true(self):
        from data_agent.workflow_engine import _is_dag_workflow
        steps = [
            {"step_id": "a", "prompt": "x"},
            {"step_id": "b", "prompt": "y", "depends_on": ["a"]},
        ]
        self.assertTrue(_is_dag_workflow(steps))


# ---------------------------------------------------------------------------
# TestTopologicalSort
# ---------------------------------------------------------------------------

class TestTopologicalSort(unittest.TestCase):
    """Test Kahn's algorithm topological sort."""

    def test_linear_chain(self):
        """A → B → C produces 3 single-element layers."""
        from data_agent.workflow_engine import _topological_sort
        steps = [
            {"step_id": "a"},
            {"step_id": "b", "depends_on": ["a"]},
            {"step_id": "c", "depends_on": ["b"]},
        ]
        layers = _topological_sort(steps)
        self.assertEqual(len(layers), 3)
        self.assertEqual(layers[0][0]["step_id"], "a")
        self.assertEqual(layers[1][0]["step_id"], "b")
        self.assertEqual(layers[2][0]["step_id"], "c")

    def test_diamond_dag(self):
        """Diamond: A → B,C → D produces 3 layers, middle has 2 nodes."""
        from data_agent.workflow_engine import _topological_sort
        steps = [
            {"step_id": "a"},
            {"step_id": "b", "depends_on": ["a"]},
            {"step_id": "c", "depends_on": ["a"]},
            {"step_id": "d", "depends_on": ["b", "c"]},
        ]
        layers = _topological_sort(steps)
        self.assertEqual(len(layers), 3)
        mid_ids = sorted(s["step_id"] for s in layers[1])
        self.assertEqual(mid_ids, ["b", "c"])
        self.assertEqual(layers[2][0]["step_id"], "d")

    def test_parallel_roots(self):
        """Multiple roots with no dependencies → single layer."""
        from data_agent.workflow_engine import _topological_sort
        steps = [
            {"step_id": "x"},
            {"step_id": "y"},
            {"step_id": "z"},
        ]
        layers = _topological_sort(steps)
        self.assertEqual(len(layers), 1)
        self.assertEqual(len(layers[0]), 3)

    def test_cycle_detection(self):
        """Cycle A → B → A should raise ValueError."""
        from data_agent.workflow_engine import _topological_sort
        steps = [
            {"step_id": "a", "depends_on": ["b"]},
            {"step_id": "b", "depends_on": ["a"]},
        ]
        with self.assertRaises(ValueError) as ctx:
            _topological_sort(steps)
        self.assertIn("Cycle", str(ctx.exception))

    def test_single_node(self):
        """Single node → one layer."""
        from data_agent.workflow_engine import _topological_sort
        layers = _topological_sort([{"step_id": "only"}])
        self.assertEqual(len(layers), 1)

    def test_missing_dependency_ignored(self):
        """Dependency on non-existent step is ignored gracefully."""
        from data_agent.workflow_engine import _topological_sort
        steps = [
            {"step_id": "a", "depends_on": ["ghost"]},
            {"step_id": "b"},
        ]
        layers = _topological_sort(steps)
        # Both should be in first layer since 'ghost' is ignored
        self.assertEqual(len(layers), 1)
        self.assertEqual(len(layers[0]), 2)


# ---------------------------------------------------------------------------
# TestEvaluateCondition
# ---------------------------------------------------------------------------

class TestEvaluateCondition(unittest.TestCase):
    """Test condition expression evaluation."""

    def test_none_check(self):
        from data_agent.workflow_engine import _evaluate_condition
        outputs = {"step1": {"error": None}}
        self.assertTrue(_evaluate_condition("{step1.error} == None", outputs))

    def test_error_present(self):
        from data_agent.workflow_engine import _evaluate_condition
        outputs = {"step1": {"error": "timeout"}}
        self.assertFalse(_evaluate_condition("{step1.error} == None", outputs))

    def test_status_check(self):
        from data_agent.workflow_engine import _evaluate_condition
        outputs = {"step1": {"status": "completed"}}
        self.assertTrue(_evaluate_condition('{step1.status} == "completed"', outputs))

    def test_compound_expression(self):
        from data_agent.workflow_engine import _evaluate_condition
        outputs = {
            "a": {"status": "completed"},
            "b": {"error": None},
        }
        result = _evaluate_condition('{a.status} == "completed" and {b.error} == None', outputs)
        self.assertTrue(result)

    def test_malformed_expression_fail_open(self):
        """Unparseable expression should return True (fail-open)."""
        from data_agent.workflow_engine import _evaluate_condition
        self.assertTrue(_evaluate_condition("this is garbage!!!", {}))

    def test_empty_expression(self):
        from data_agent.workflow_engine import _evaluate_condition
        self.assertTrue(_evaluate_condition("", {}))
        self.assertTrue(_evaluate_condition("  ", {}))


# ---------------------------------------------------------------------------
# TestSubstituteParamsDag
# ---------------------------------------------------------------------------

class TestSubstituteParamsDag(unittest.TestCase):
    """Test enhanced parameter substitution with node references."""

    def test_node_output_substitution(self):
        from data_agent.workflow_engine import _substitute_params_dag
        outputs = {"step1": {"report_text": "Found 42 records"}}
        result = _substitute_params_dag("Previous: {step1.output}", {}, outputs)
        self.assertEqual(result, "Previous: Found 42 records")

    def test_node_files_substitution(self):
        from data_agent.workflow_engine import _substitute_params_dag
        outputs = {"step1": {"files": ["/tmp/a.csv", "/tmp/b.geojson"]}}
        result = _substitute_params_dag("Files: {step1.files}", {}, outputs)
        self.assertEqual(result, "Files: /tmp/a.csv, /tmp/b.geojson")

    def test_mixed_params_and_outputs(self):
        from data_agent.workflow_engine import _substitute_params_dag
        outputs = {"load": {"report_text": "100 rows loaded"}}
        params = {"threshold": "50"}
        result = _substitute_params_dag(
            "Data: {load.output}, threshold={threshold}", params, outputs
        )
        self.assertEqual(result, "Data: 100 rows loaded, threshold=50")

    def test_output_truncation(self):
        """Node output should be truncated to 2000 chars."""
        from data_agent.workflow_engine import _substitute_params_dag
        long_text = "x" * 5000
        outputs = {"s1": {"report_text": long_text}}
        result = _substitute_params_dag("{s1.output}", {}, outputs)
        self.assertEqual(len(result), 2000)


# ---------------------------------------------------------------------------
# TestLiveRunStatus
# ---------------------------------------------------------------------------

class TestLiveRunStatus(unittest.TestCase):
    """Test in-memory live status tracking."""

    def setUp(self):
        from data_agent import workflow_engine
        self._module = workflow_engine
        # Clear live status before each test
        self._module._live_run_status.clear()

    def test_update_and_get(self):
        from data_agent.workflow_engine import _update_live_status, get_live_run_status
        _update_live_status(999, "step_a", "running")
        status = get_live_run_status(999)
        self.assertIsNotNone(status)
        self.assertEqual(status["nodes"]["step_a"]["status"], "running")

    def test_not_found(self):
        from data_agent.workflow_engine import get_live_run_status
        self.assertIsNone(get_live_run_status(12345))

    def test_eviction(self):
        """When exceeding MAX entries, oldest should be evicted."""
        from data_agent.workflow_engine import _update_live_status, _LIVE_STATUS_MAX
        for i in range(_LIVE_STATUS_MAX + 5):
            _update_live_status(i, "s", "running")
        self.assertLessEqual(len(self._module._live_run_status), _LIVE_STATUS_MAX + 1)


# ---------------------------------------------------------------------------
# TestExecuteWorkflowDAG
# ---------------------------------------------------------------------------

class TestExecuteWorkflowDAG(unittest.TestCase):
    """Test DAG workflow execution with mocked pipeline runner."""

    def _run(self, coro):
        return asyncio.run(coro)

    @patch("data_agent.workflow_engine.get_workflow", return_value=None)
    def test_workflow_not_found(self, mock_get):
        from data_agent.workflow_engine import execute_workflow_dag
        result = self._run(execute_workflow_dag(999))
        self.assertEqual(result["status"], "failed")
        self.assertIn("not found", result["error"])

    @patch("data_agent.workflow_engine.get_workflow")
    def test_empty_steps(self, mock_get):
        mock_get.return_value = {
            "workflow_name": "test", "owner_username": "u",
            "steps": [], "parameters": {}, "webhook_url": None,
        }
        from data_agent.workflow_engine import execute_workflow_dag
        result = self._run(execute_workflow_dag(1))
        self.assertEqual(result["status"], "failed")
        self.assertIn("no steps", result["error"])

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_linear_dag_execution(self, mock_get, mock_eng):
        """Linear DAG A → B should execute both nodes."""
        mock_get.return_value = {
            "workflow_name": "linear", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "step a"},
                {"step_id": "b", "pipeline_type": "general", "prompt": "step b", "depends_on": ["a"]},
            ],
            "parameters": {}, "webhook_url": None,
        }
        fake = _FakePipelineResult()
        with patch("data_agent.pipeline_runner.run_pipeline_headless",
                    new_callable=AsyncMock, return_value=fake) as mock_run:
            from data_agent.workflow_engine import execute_workflow_dag
            result = self._run(execute_workflow_dag(1, run_by="tester"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["step_results"]), 2)
        self.assertEqual(mock_run.call_count, 2)

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_parallel_execution(self, mock_get, mock_eng):
        """A → (B, C) → D: B and C should run in same layer."""
        mock_get.return_value = {
            "workflow_name": "parallel", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "load"},
                {"step_id": "b", "pipeline_type": "general", "prompt": "analyze", "depends_on": ["a"]},
                {"step_id": "c", "pipeline_type": "general", "prompt": "visualize", "depends_on": ["a"]},
                {"step_id": "d", "pipeline_type": "general", "prompt": "summarize", "depends_on": ["b", "c"]},
            ],
            "parameters": {}, "webhook_url": None,
        }
        fake = _FakePipelineResult()
        with patch("data_agent.pipeline_runner.run_pipeline_headless",
                    new_callable=AsyncMock, return_value=fake):
            from data_agent.workflow_engine import execute_workflow_dag
            result = self._run(execute_workflow_dag(1, run_by="tester"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["step_results"]), 4)

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_failure_isolation(self, mock_get, mock_eng):
        """If A fails, B (depends on A) is skipped, but C (independent) still runs."""
        mock_get.return_value = {
            "workflow_name": "iso", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "fail here"},
                {"step_id": "b", "pipeline_type": "general", "prompt": "depends a", "depends_on": ["a"]},
                {"step_id": "c", "pipeline_type": "general", "prompt": "independent"},
            ],
            "parameters": {}, "webhook_url": None,
        }
        fail_result = _FakePipelineResult(error="boom")
        ok_result = _FakePipelineResult()

        async def _side_effect(**kwargs):
            if "fail here" in kwargs.get("prompt", ""):
                return fail_result
            return ok_result

        with patch("data_agent.pipeline_runner.run_pipeline_headless",
                    new_callable=AsyncMock, side_effect=_side_effect):
            from data_agent.workflow_engine import execute_workflow_dag
            result = self._run(execute_workflow_dag(1, run_by="tester"))

        statuses = {r["step_id"]: r["status"] for r in result["step_results"]}
        self.assertEqual(statuses["a"], "failed")
        self.assertEqual(statuses["b"], "skipped")
        self.assertEqual(statuses["c"], "completed")

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_condition_true(self, mock_get, mock_eng):
        """Condition node evaluating True → downstream runs."""
        mock_get.return_value = {
            "workflow_name": "cond", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "load data"},
                {"step_id": "check", "pipeline_type": "condition",
                 "condition": "{a.status} == \"completed\"", "depends_on": ["a"]},
                {"step_id": "b", "pipeline_type": "general", "prompt": "process",
                 "depends_on": ["check"]},
            ],
            "parameters": {}, "webhook_url": None,
        }
        fake = _FakePipelineResult()
        with patch("data_agent.pipeline_runner.run_pipeline_headless",
                    new_callable=AsyncMock, return_value=fake):
            from data_agent.workflow_engine import execute_workflow_dag
            result = self._run(execute_workflow_dag(1, run_by="tester"))
        statuses = {r["step_id"]: r["status"] for r in result["step_results"]}
        self.assertEqual(statuses["b"], "completed")

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_condition_false_skips_downstream(self, mock_get, mock_eng):
        """Condition node evaluating False → downstream is skipped."""
        mock_get.return_value = {
            "workflow_name": "cond_f", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "load"},
                {"step_id": "gate", "pipeline_type": "condition",
                 "condition": "{a.error} != None", "depends_on": ["a"]},
                {"step_id": "b", "pipeline_type": "general", "prompt": "should skip",
                 "depends_on": ["gate"]},
            ],
            "parameters": {}, "webhook_url": None,
        }
        fake = _FakePipelineResult()  # no error
        with patch("data_agent.pipeline_runner.run_pipeline_headless",
                    new_callable=AsyncMock, return_value=fake):
            from data_agent.workflow_engine import execute_workflow_dag
            result = self._run(execute_workflow_dag(1, run_by="tester"))
        statuses = {r["step_id"]: r["status"] for r in result["step_results"]}
        self.assertEqual(statuses["b"], "skipped")

    @patch("data_agent.workflow_engine.get_engine", return_value=None)
    @patch("data_agent.workflow_engine.get_workflow")
    def test_cycle_error(self, mock_get, mock_eng):
        """Cyclic DAG should return failed status."""
        mock_get.return_value = {
            "workflow_name": "cycle", "owner_username": "u",
            "steps": [
                {"step_id": "a", "pipeline_type": "general", "prompt": "x", "depends_on": ["b"]},
                {"step_id": "b", "pipeline_type": "general", "prompt": "y", "depends_on": ["a"]},
            ],
            "parameters": {}, "webhook_url": None,
        }
        from data_agent.workflow_engine import execute_workflow_dag
        result = self._run(execute_workflow_dag(1, run_by="tester"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("Cycle", result["error"])
