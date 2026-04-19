"""Tests for @SubAgent mention routing."""
import unittest
from unittest.mock import patch, MagicMock


class TestMentionRegistry(unittest.TestCase):
    """Tests for mention_registry.py target aggregation."""

    def test_pipeline_targets_always_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("General", handles)
        self.assertIn("Governance", handles)
        self.assertIn("Optimization", handles)

    def test_pipeline_target_shape(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        general = next(t for t in registry if t["handle"] == "General")
        self.assertEqual(general["type"], "pipeline")
        self.assertIn("allowed_roles", general)
        self.assertIn("description", general)
        self.assertEqual(general["required_state_keys"], [])

    def test_sub_agent_targets_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("DataVisualization", handles)
        self.assertIn("DataProcessing", handles)
        self.assertIn("GovExploration", handles)

    def test_sub_agent_has_required_state(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        viz = next(t for t in registry if t["handle"] == "DataVisualization")
        self.assertEqual(viz["type"], "sub_agent")
        self.assertIn("processed_data", viz["required_state_keys"])

    def test_builtin_skill_targets(self):
        from data_agent.mention_registry import build_registry
        with patch("data_agent.mention_registry.list_builtin_skills", return_value=[
            {"name": "thematic-mapping", "description": "专题图制作", "type": "builtin_skill"},
        ]):
            registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("thematic-mapping", handles)

    @patch("data_agent.mention_registry.list_custom_skills")
    def test_custom_skill_targets(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "skill_name": "SoilExpert", "description": "土壤分析",
             "owner_username": "testuser", "is_shared": False},
        ]
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("SoilExpert", handles)

    def test_lookup_by_handle_case_insensitive(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "general")
        self.assertIsNotNone(result)
        self.assertEqual(result["handle"], "General")

    def test_lookup_unknown_returns_none(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "NonExistentAgent")
        self.assertIsNone(result)

    def test_handle_uniqueness(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = [t["handle"] for t in registry]
        self.assertEqual(len(handles), len(set(h.lower() for h in handles)))
