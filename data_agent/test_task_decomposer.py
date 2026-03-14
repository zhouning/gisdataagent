"""
Tests for Intelligent Task Decomposition (v9.0.4).

Tests TaskNode, TaskGraph (DAG, topological sort, cycle detection, waves),
decompose_task, parse_decomposition, and build_parallel_execution_plan.
"""

import json
import unittest
from unittest.mock import patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# TestTaskNode
# ---------------------------------------------------------------------------

class TestTaskNode(unittest.TestCase):

    def test_create(self):
        from data_agent.task_decomposer import TaskNode
        node = TaskNode(id="t1", description="Explore data")
        self.assertEqual(node.id, "t1")
        self.assertEqual(node.description, "Explore data")
        self.assertEqual(node.status, "pending")
        self.assertEqual(node.dependencies, [])

    def test_with_deps(self):
        from data_agent.task_decomposer import TaskNode
        node = TaskNode(id="t2", description="Process", dependencies=["t1"])
        self.assertEqual(node.dependencies, ["t1"])

    def test_hashable(self):
        from data_agent.task_decomposer import TaskNode
        node = TaskNode(id="t1", description="test")
        s = {node}
        self.assertEqual(len(s), 1)


# ---------------------------------------------------------------------------
# TestTaskGraph
# ---------------------------------------------------------------------------

class TestTaskGraph(unittest.TestCase):

    def _make_graph(self, nodes_data):
        from data_agent.task_decomposer import TaskGraph, TaskNode
        g = TaskGraph()
        for d in nodes_data:
            g.add_node(TaskNode(**d))
        return g

    def test_add_and_get(self):
        from data_agent.task_decomposer import TaskGraph, TaskNode
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="test"))
        self.assertEqual(g.node_count, 1)
        self.assertIsNotNone(g.get_node("t1"))
        self.assertIsNone(g.get_node("t99"))

    def test_no_cycle_linear(self):
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
            {"id": "t3", "description": "C", "dependencies": ["t2"]},
        ])
        self.assertFalse(g.has_cycle())

    def test_cycle_detection(self):
        g = self._make_graph([
            {"id": "t1", "description": "A", "dependencies": ["t3"]},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
            {"id": "t3", "description": "C", "dependencies": ["t2"]},
        ])
        self.assertTrue(g.has_cycle())

    def test_no_cycle_diamond(self):
        g = self._make_graph([
            {"id": "t1", "description": "Start"},
            {"id": "t2", "description": "Left", "dependencies": ["t1"]},
            {"id": "t3", "description": "Right", "dependencies": ["t1"]},
            {"id": "t4", "description": "End", "dependencies": ["t2", "t3"]},
        ])
        self.assertFalse(g.has_cycle())

    def test_topological_sort_linear(self):
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
            {"id": "t3", "description": "C", "dependencies": ["t2"]},
        ])
        order = g.topological_sort()
        self.assertEqual(order, ["t1", "t2", "t3"])

    def test_topological_sort_raises_on_cycle(self):
        g = self._make_graph([
            {"id": "t1", "description": "A", "dependencies": ["t2"]},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
        ])
        with self.assertRaises(ValueError):
            g.topological_sort()


# ---------------------------------------------------------------------------
# TestExecutionWaves
# ---------------------------------------------------------------------------

class TestExecutionWaves(unittest.TestCase):

    def _make_graph(self, nodes_data):
        from data_agent.task_decomposer import TaskGraph, TaskNode
        g = TaskGraph()
        for d in nodes_data:
            g.add_node(TaskNode(**d))
        return g

    def test_single_wave(self):
        """All independent tasks → single wave."""
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B"},
            {"id": "t3", "description": "C"},
        ])
        waves = g.get_execution_waves()
        self.assertEqual(len(waves), 1)
        self.assertEqual(len(waves[0]), 3)

    def test_sequential_waves(self):
        """Linear chain → one task per wave."""
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
            {"id": "t3", "description": "C", "dependencies": ["t2"]},
        ])
        waves = g.get_execution_waves()
        self.assertEqual(len(waves), 3)
        self.assertEqual(waves[0], ["t1"])
        self.assertEqual(waves[1], ["t2"])
        self.assertEqual(waves[2], ["t3"])

    def test_diamond_waves(self):
        """Diamond: t1 → (t2, t3) → t4."""
        g = self._make_graph([
            {"id": "t1", "description": "Start"},
            {"id": "t2", "description": "Left", "dependencies": ["t1"]},
            {"id": "t3", "description": "Right", "dependencies": ["t1"]},
            {"id": "t4", "description": "End", "dependencies": ["t2", "t3"]},
        ])
        waves = g.get_execution_waves()
        self.assertEqual(len(waves), 3)
        self.assertEqual(waves[0], ["t1"])
        self.assertIn("t2", waves[1])
        self.assertIn("t3", waves[1])
        self.assertEqual(waves[2], ["t4"])

    def test_cycle_raises(self):
        g = self._make_graph([
            {"id": "t1", "description": "A", "dependencies": ["t2"]},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
        ])
        with self.assertRaises(ValueError):
            g.get_execution_waves()


# ---------------------------------------------------------------------------
# TestParseDecomposition
# ---------------------------------------------------------------------------

class TestParseDecomposition(unittest.TestCase):

    def test_valid_json(self):
        from data_agent.task_decomposer import _parse_decomposition
        text = '[{"id": "t1", "description": "A", "agent_hint": "", "dependencies": []}]'
        result = _parse_decomposition(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "t1")

    def test_json_in_markdown(self):
        from data_agent.task_decomposer import _parse_decomposition
        text = '```json\n[{"id": "t1", "description": "分析数据", "dependencies": []}]\n```'
        result = _parse_decomposition(text)
        self.assertEqual(len(result), 1)

    def test_invalid_raises(self):
        from data_agent.task_decomposer import _parse_decomposition
        with self.assertRaises(ValueError):
            _parse_decomposition("no json here")

    def test_empty_array_raises(self):
        from data_agent.task_decomposer import _parse_decomposition
        with self.assertRaises(ValueError):
            _parse_decomposition("[]")


# ---------------------------------------------------------------------------
# TestDecomposeTask
# ---------------------------------------------------------------------------

class TestDecomposeTask(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.task_decomposer._call_llm", new_callable=AsyncMock)
    async def test_successful_decomposition(self, mock_llm):
        from data_agent.task_decomposer import decompose_task
        mock_llm.return_value = json.dumps([
            {"id": "t1", "description": "探查数据", "agent_hint": "DataExploration", "dependencies": []},
            {"id": "t2", "description": "处理数据", "agent_hint": "DataProcessing", "dependencies": ["t1"]},
        ])
        graph = await decompose_task("分析土地利用数据")
        self.assertEqual(graph.node_count, 2)
        self.assertFalse(graph.has_cycle())

    @patch("data_agent.task_decomposer._call_llm", new_callable=AsyncMock)
    async def test_fallback_on_llm_error(self, mock_llm):
        from data_agent.task_decomposer import decompose_task
        mock_llm.side_effect = Exception("API error")
        graph = await decompose_task("分析数据")
        self.assertEqual(graph.node_count, 1)
        self.assertEqual(graph.nodes["t1"].description, "分析数据")

    @patch("data_agent.task_decomposer._call_llm", new_callable=AsyncMock)
    async def test_fallback_on_parse_error(self, mock_llm):
        from data_agent.task_decomposer import decompose_task
        mock_llm.return_value = "This is not JSON at all"
        graph = await decompose_task("分析数据")
        self.assertEqual(graph.node_count, 1)

    @patch("data_agent.task_decomposer._call_llm", new_callable=AsyncMock)
    async def test_cycle_removal(self, mock_llm):
        from data_agent.task_decomposer import decompose_task
        mock_llm.return_value = json.dumps([
            {"id": "t1", "description": "A", "dependencies": ["t2"]},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
        ])
        graph = await decompose_task("test")
        # Cycle should be removed
        self.assertFalse(graph.has_cycle())

    @patch("data_agent.task_decomposer._call_llm", new_callable=AsyncMock)
    async def test_custom_agents(self, mock_llm):
        from data_agent.task_decomposer import decompose_task
        mock_llm.return_value = json.dumps([
            {"id": "t1", "description": "Custom task", "agent_hint": "CustomAgent", "dependencies": []},
        ])
        graph = await decompose_task("test", available_agents=["CustomAgent"])
        self.assertEqual(graph.node_count, 1)
        # Check the prompt included custom agents
        call_args = mock_llm.call_args[0][0]
        self.assertIn("CustomAgent", call_args)


# ---------------------------------------------------------------------------
# TestBuildParallelExecutionPlan
# ---------------------------------------------------------------------------

class TestBuildParallelExecutionPlan(unittest.TestCase):

    def _make_graph(self, nodes_data):
        from data_agent.task_decomposer import TaskGraph, TaskNode
        g = TaskGraph()
        for d in nodes_data:
            g.add_node(TaskNode(**d))
        return g

    def test_returns_task_nodes(self):
        from data_agent.task_decomposer import build_parallel_execution_plan, TaskNode
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B", "dependencies": ["t1"]},
        ])
        waves = build_parallel_execution_plan(g)
        self.assertEqual(len(waves), 2)
        self.assertIsInstance(waves[0][0], TaskNode)
        self.assertEqual(waves[0][0].id, "t1")
        self.assertEqual(waves[1][0].id, "t2")

    def test_parallel_wave(self):
        from data_agent.task_decomposer import build_parallel_execution_plan
        g = self._make_graph([
            {"id": "t1", "description": "A"},
            {"id": "t2", "description": "B"},
            {"id": "t3", "description": "C"},
        ])
        waves = build_parallel_execution_plan(g)
        self.assertEqual(len(waves), 1)
        self.assertEqual(len(waves[0]), 3)


# ---------------------------------------------------------------------------
# TestRemoveCycles
# ---------------------------------------------------------------------------

class TestRemoveCycles(unittest.TestCase):

    def test_simple_cycle_broken(self):
        from data_agent.task_decomposer import TaskGraph, TaskNode, _remove_cycles
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="A", dependencies=["t2"]))
        g.add_node(TaskNode(id="t2", description="B", dependencies=["t1"]))
        _remove_cycles(g)
        self.assertFalse(g.has_cycle())

    def test_no_cycle_unchanged(self):
        from data_agent.task_decomposer import TaskGraph, TaskNode, _remove_cycles
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="A"))
        g.add_node(TaskNode(id="t2", description="B", dependencies=["t1"]))
        _remove_cycles(g)
        self.assertEqual(g.nodes["t2"].dependencies, ["t1"])


if __name__ == "__main__":
    unittest.main()
