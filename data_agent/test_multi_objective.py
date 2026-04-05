"""Tests for Multi-Objective Optimization (v12.0.1, Design Pattern Ch14).

Covers ParetoFrontier, compute_objectives, and multi-objective tool.
"""
import unittest
from unittest.mock import patch, MagicMock

import numpy as np


class TestParetoFrontier(unittest.TestCase):
    def test_empty_frontier(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier()
        self.assertEqual(pf.size, 0)
        self.assertEqual(pf.get_frontier(), [])

    def test_add_single_solution(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier()
        added = pf.add_solution([0.5, 0.8, 0.9], {"run": 1})
        self.assertTrue(added)
        self.assertEqual(pf.size, 1)

    def test_dominated_not_added(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier(maximize=[True, True])
        pf.add_solution([0.8, 0.9])  # better in both
        added = pf.add_solution([0.5, 0.5])  # dominated
        self.assertFalse(added)
        self.assertEqual(pf.size, 1)

    def test_dominating_replaces(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier(maximize=[True, True])
        pf.add_solution([0.5, 0.5], {"id": "old"})
        pf.add_solution([0.8, 0.9], {"id": "new"})  # dominates old
        self.assertEqual(pf.size, 1)
        self.assertEqual(pf.get_frontier()[0]["metadata"]["id"], "new")

    def test_non_dominated_coexist(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier(maximize=[True, True])
        pf.add_solution([0.9, 0.3])  # good slope, poor contiguity
        pf.add_solution([0.3, 0.9])  # poor slope, good contiguity
        self.assertEqual(pf.size, 2)  # neither dominates the other

    def test_minimize_direction(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier(maximize=[False, True])  # minimize first, maximize second
        pf.add_solution([0.2, 0.8])  # low first (good), high second (good)
        added = pf.add_solution([0.5, 0.5])  # higher first (worse), lower second (worse)
        self.assertFalse(added)  # dominated

    def test_clear(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier()
        pf.add_solution([0.5, 0.5])
        pf.clear()
        self.assertEqual(pf.size, 0)

    def test_get_frontier_format(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier()
        pf.add_solution([0.5, 0.8], {"run": 1})
        result = pf.get_frontier()
        self.assertEqual(len(result), 1)
        self.assertIn("objectives", result[0])
        self.assertIn("metadata", result[0])
        self.assertEqual(result[0]["objectives"], [0.5, 0.8])

    def test_large_frontier(self):
        from data_agent.drl_engine import ParetoFrontier
        pf = ParetoFrontier(maximize=[True, True])
        # Add many non-dominated solutions on a curve
        for i in range(20):
            x = i / 20.0
            y = 1.0 - x
            pf.add_solution([x, y])
        # All should be non-dominated (they trade off perfectly)
        self.assertEqual(pf.size, 20)


class TestComputeObjectives(unittest.TestCase):
    def test_with_mock_env(self):
        from data_agent.drl_engine import compute_objectives
        mock_env = MagicMock()
        mock_env.avg_farmland_slope = 15.0
        mock_env.contiguity = 0.75
        mock_env.n_farmland = 100
        mock_env.initial_n_farmland_count = 100

        objectives = compute_objectives(mock_env)
        self.assertEqual(len(objectives), 3)
        self.assertEqual(objectives[0], -15.0)  # negated slope
        self.assertEqual(objectives[1], 0.75)   # contiguity
        self.assertEqual(objectives[2], 1.0)    # perfect balance

    def test_with_deviation(self):
        from data_agent.drl_engine import compute_objectives
        mock_env = MagicMock()
        mock_env.avg_farmland_slope = 10.0
        mock_env.contiguity = 0.5
        mock_env.n_farmland = 90
        mock_env.initial_n_farmland_count = 100

        objectives = compute_objectives(mock_env)
        self.assertAlmostEqual(objectives[2], 0.9)  # 10% deviation


class TestMultiObjectiveTool(unittest.TestCase):
    def test_tool_exists(self):
        from data_agent.toolsets.analysis_tools import _SYNC_FUNCS
        func_names = [f.__name__ for f in _SYNC_FUNCS]
        self.assertIn("drl_multi_objective", func_names)

    def test_tool_count(self):
        from data_agent.toolsets.analysis_tools import _SYNC_FUNCS
        self.assertEqual(len(_SYNC_FUNCS), 3)  # ffi + drl_multi_objective + list_drl_scenarios


if __name__ == "__main__":
    unittest.main()
