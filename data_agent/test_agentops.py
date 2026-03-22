"""Tests for AgentOps enhancements — cost management, HITL, eval history."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestCostCalculation(unittest.TestCase):
    """Test USD cost calculation."""

    def test_calculate_cost_gemini_flash(self):
        from data_agent.token_tracker import calculate_cost_usd
        cost = calculate_cost_usd(1000, 500, "gemini-2.5-flash")
        # input: 1000 * 0.15/1M = 0.00015, output: 500 * 0.60/1M = 0.0003
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=6)

    def test_calculate_cost_gemini_pro(self):
        from data_agent.token_tracker import calculate_cost_usd
        cost = calculate_cost_usd(10000, 5000, "gemini-2.5-pro")
        expected = (10000 * 1.25 + 5000 * 5.00) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=6)

    def test_calculate_cost_unknown_model(self):
        from data_agent.token_tracker import calculate_cost_usd
        cost = calculate_cost_usd(1000, 1000, "unknown-model-xyz")
        # Should use _default pricing
        expected = (1000 * 0.50 + 1000 * 2.00) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=6)

    def test_zero_tokens(self):
        from data_agent.token_tracker import calculate_cost_usd
        cost = calculate_cost_usd(0, 0, "gemini-2.5-flash")
        self.assertEqual(cost, 0.0)

    def test_model_pricing_has_defaults(self):
        from data_agent.token_tracker import MODEL_PRICING
        self.assertIn("_default", MODEL_PRICING)
        self.assertIn("gemini-2.5-flash", MODEL_PRICING)
        self.assertIn("gemini-2.5-pro", MODEL_PRICING)
        self.assertIn("gpt-4o", MODEL_PRICING)


class TestCostGuardUSD(unittest.TestCase):
    """Test CostGuard USD-based budget control."""

    def test_cost_guard_has_usd_abort(self):
        from data_agent.plugins import CostGuardPlugin
        p = CostGuardPlugin(usd_abort=1.0)
        self.assertEqual(p.usd_abort, 1.0)

    def test_cost_guard_usd_from_env(self):
        from data_agent.plugins import CostGuardPlugin
        with patch.dict(os.environ, {"COST_GUARD_USD_ABORT": "0.50"}):
            p = CostGuardPlugin()
            self.assertEqual(p.usd_abort, 0.50)

    def test_cost_guard_has_cost_key(self):
        from data_agent.plugins import CostGuardPlugin
        self.assertTrue(hasattr(CostGuardPlugin, "COST_KEY"))
        self.assertEqual(CostGuardPlugin.COST_KEY, "__cost_guard_usd__")


class TestEstimateCost(unittest.TestCase):
    """Test pipeline cost estimation."""

    @patch("data_agent.token_tracker.get_engine", return_value=None)
    def test_estimate_no_db(self, _):
        from data_agent.token_tracker import estimate_pipeline_cost
        result = estimate_pipeline_cost("general")
        self.assertEqual(result["estimated_tokens"], 0)
        self.assertEqual(result["estimated_cost_usd"], 0.0)


class TestHITLDecisionTracking(unittest.TestCase):
    """Test HITL decision DB persistence."""

    def test_get_risk_registry(self):
        from data_agent.hitl_approval import get_risk_registry
        registry = get_risk_registry()
        self.assertIsInstance(registry, list)
        self.assertGreater(len(registry), 0)
        # Check structure
        first = registry[0]
        self.assertIn("tool_name", first)
        self.assertIn("level", first)
        self.assertIn("level_value", first)
        self.assertIn("description", first)

    def test_risk_registry_levels(self):
        from data_agent.hitl_approval import get_risk_registry
        registry = get_risk_registry()
        levels = {r["level"] for r in registry}
        self.assertTrue(levels.issubset({"LOW", "MEDIUM", "HIGH", "CRITICAL"}))

    @patch("data_agent.db_engine.get_engine", return_value=None)
    def test_get_hitl_stats_no_db(self, _):
        from data_agent.hitl_approval import get_hitl_stats
        stats = get_hitl_stats()
        self.assertEqual(stats["total"], 0)
        self.assertIn("approval_rate", stats)
        self.assertIn("by_risk_level", stats)
        self.assertIn("recent_decisions", stats)

    @patch("data_agent.db_engine.get_engine", return_value=None)
    def test_record_hitl_decision_no_db(self, _):
        from data_agent.hitl_approval import record_hitl_decision
        # Should not raise
        record_hitl_decision("admin", "import_to_postgis", "CRITICAL", "APPROVE")


class TestEvalHistory(unittest.TestCase):
    """Test evaluation history tracking."""

    @patch("data_agent.eval_history.get_engine", return_value=None)
    def test_record_no_db(self, _):
        from data_agent.eval_history import record_eval_result
        result = record_eval_result("general", 0.85, 0.9, "PASS", num_tests=3)
        self.assertIsNone(result)

    @patch("data_agent.eval_history.get_engine", return_value=None)
    def test_get_history_no_db(self, _):
        from data_agent.eval_history import get_eval_history
        result = get_eval_history()
        self.assertEqual(result, [])

    @patch("data_agent.eval_history.get_engine", return_value=None)
    def test_get_trend_no_db(self, _):
        from data_agent.eval_history import get_eval_trend
        result = get_eval_trend("general")
        self.assertEqual(result, [])

    @patch("data_agent.eval_history.get_engine", return_value=None)
    def test_compare_no_db(self, _):
        from data_agent.eval_history import compare_eval_runs
        result = compare_eval_runs("abc", "def")
        self.assertIn("error", result)


class TestAPIRoutes(unittest.TestCase):
    """Test new API route registration."""

    def test_hitl_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/hitl/stats", paths)
        self.assertIn("/api/hitl/risk-registry", paths)

    def test_cost_route_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/cost/estimate", paths)

    def test_eval_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/eval/history", paths)
        self.assertIn("/api/eval/trend", paths)


if __name__ == "__main__":
    unittest.main()
