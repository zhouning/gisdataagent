"""Tests for skill dependency graph."""
import unittest
from unittest.mock import patch, MagicMock
from data_agent.skill_dependency_graph import (
    build_skill_graph, _detect_cycle, get_dependents,
    get_execution_order, validate_dependency, update_dependencies,
    get_dependencies,
)


class TestSkillDependencyGraph(unittest.TestCase):

    def _mock_skills(self):
        return {
            1: {"name": "skill-a", "depends_on": []},
            2: {"name": "skill-b", "depends_on": [1]},
            3: {"name": "skill-c", "depends_on": [1, 2]},
        }

    def test_detect_no_cycle(self):
        skills = self._mock_skills()
        self.assertFalse(_detect_cycle(skills))

    def test_detect_cycle(self):
        skills = {
            1: {"name": "a", "depends_on": [2]},
            2: {"name": "b", "depends_on": [1]},
        }
        self.assertTrue(_detect_cycle(skills))

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_build_graph(self, mock_load):
        mock_load.return_value = self._mock_skills()
        graph = build_skill_graph("testuser")
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertFalse(graph["has_cycle"])
        self.assertTrue(len(graph["edges"]) >= 2)

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_get_dependents(self, mock_load):
        mock_load.return_value = self._mock_skills()
        deps = get_dependents(1, "testuser")
        self.assertIn(2, deps)
        self.assertIn(3, deps)

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_get_dependencies(self, mock_load):
        mock_load.return_value = self._mock_skills()
        deps = get_dependencies(3, "testuser")
        self.assertIn(1, deps)
        self.assertIn(2, deps)

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_get_dependencies_missing(self, mock_load):
        mock_load.return_value = self._mock_skills()
        deps = get_dependencies(99, "testuser")
        self.assertEqual(deps, [])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_execution_order(self, mock_load):
        mock_load.return_value = self._mock_skills()
        waves = get_execution_order([1, 2, 3], "testuser")
        self.assertEqual(waves[0], [1])
        self.assertIn(2, waves[1])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_execution_order_cycle(self, mock_load):
        mock_load.return_value = {
            1: {"name": "a", "depends_on": [2]},
            2: {"name": "b", "depends_on": [1]},
        }
        waves = get_execution_order([1, 2], "testuser")
        # Cycle: remaining dumped in last wave
        self.assertTrue(len(waves) >= 1)

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_validate_self_dependency(self, mock_load):
        mock_load.return_value = self._mock_skills()
        result = validate_dependency(1, 1, "testuser")
        self.assertFalse(result["valid"])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_validate_cycle(self, mock_load):
        mock_load.return_value = {
            1: {"name": "a", "depends_on": [2]},
            2: {"name": "b", "depends_on": []},
        }
        # Adding 2 -> 1 would create cycle
        result = validate_dependency(2, 1, "testuser")
        self.assertFalse(result["valid"])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_validate_ok(self, mock_load):
        mock_load.return_value = self._mock_skills()
        result = validate_dependency(2, 1, "testuser")
        self.assertTrue(result["valid"])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_validate_missing_dep(self, mock_load):
        mock_load.return_value = self._mock_skills()
        result = validate_dependency(1, 99, "testuser")
        self.assertFalse(result["valid"])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_validate_missing_skill(self, mock_load):
        mock_load.return_value = self._mock_skills()
        result = validate_dependency(99, 1, "testuser")
        self.assertFalse(result["valid"])

    @patch("data_agent.skill_dependency_graph.get_engine")
    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_update_dependencies_ok(self, mock_load, mock_engine):
        mock_load.return_value = self._mock_skills()
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        result = update_dependencies(2, [1], "testuser")
        self.assertEqual(result["status"], "ok")

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_update_dependencies_missing(self, mock_load):
        mock_load.return_value = self._mock_skills()
        result = update_dependencies(99, [1], "testuser")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.skill_dependency_graph.get_engine")
    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_update_dependencies_cycle(self, mock_load, mock_engine):
        mock_load.return_value = {
            1: {"name": "a", "depends_on": [2]},
            2: {"name": "b", "depends_on": []},
        }
        mock_engine.return_value = MagicMock()
        result = update_dependencies(2, [1], "testuser")
        self.assertEqual(result["status"], "error")
        self.assertIn("循环", result["message"])

    def test_detect_cycle_empty(self):
        self.assertFalse(_detect_cycle({}))

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_build_graph_empty(self, mock_load):
        mock_load.return_value = {}
        graph = build_skill_graph("testuser")
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])
        self.assertFalse(graph["has_cycle"])

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_execution_order_partial(self, mock_load):
        mock_load.return_value = self._mock_skills()
        # Only request subset
        waves = get_execution_order([2, 3], "testuser")
        # skill 2 depends on 1 which is not in subset, so in_degree for 2 = 0
        self.assertTrue(len(waves) >= 1)


if __name__ == "__main__":
    unittest.main()
