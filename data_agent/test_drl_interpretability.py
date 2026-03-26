"""Tests for DRL interpretability module."""
import unittest
from unittest.mock import patch, MagicMock
import numpy as np


class TestDRLInterpretability(unittest.TestCase):

    def test_parcel_feature_names(self):
        from data_agent.drl_interpretability import PARCEL_FEATURE_NAMES, GLOBAL_FEATURE_NAMES
        self.assertEqual(len(PARCEL_FEATURE_NAMES), 6)
        self.assertEqual(len(GLOBAL_FEATURE_NAMES), 8)

    def test_get_scenario_feature_summary(self):
        from data_agent.drl_interpretability import get_scenario_feature_summary
        s = get_scenario_feature_summary("farmland_optimization")
        self.assertIn("slope", s["key_features"])
        self.assertIn("description", s)

    def test_get_scenario_feature_summary_unknown(self):
        from data_agent.drl_interpretability import get_scenario_feature_summary
        s = get_scenario_feature_summary("unknown_scenario")
        self.assertIn("key_features", s)

    @patch("data_agent.drl_interpretability.MaskablePPO", create=True)
    def test_explain_missing_model(self, mock_ppo_cls):
        """When model file doesn't exist, should return error."""
        mock_ppo_cls.load.side_effect = FileNotFoundError("not found")
        # We need to import after patching
        from data_agent.drl_interpretability import explain_drl_decision
        result = explain_drl_decision("/nonexistent/model.zip")
        self.assertEqual(result["status"], "error")

    def test_generate_importance_chart(self):
        from data_agent.drl_interpretability import _generate_importance_chart
        import tempfile, os
        features = [("slope", 35.0), ("area", 25.0), ("contiguity", 20.0), ("type", 20.0)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _generate_importance_chart(features, tmpdir)
            if path:  # matplotlib may not be available
                self.assertTrue(os.path.exists(path))
                self.assertTrue(path.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
