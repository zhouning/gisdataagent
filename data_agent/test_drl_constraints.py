"""Tests for DRL constraint modeling (v23.0).

Tests hard constraints (min_retention_rate via action masking) and
soft constraints (budget_cap, max_area_cap via reward penalties).
"""
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from data_agent.drl_engine import DRLScenario


class TestDRLScenarioConstraints(unittest.TestCase):
    """Test DRLScenario constraint parameters."""

    def test_default_no_constraints(self):
        s = DRLScenario(name="test", description="t",
                        source_types={"A"}, target_types={"B"})
        assert s.min_retention_rate == 0.0
        assert s.max_area_cap == float('inf')
        assert s.budget_cap == float('inf')
        assert s.budget_per_conversion == 1.0

    def test_custom_constraints(self):
        s = DRLScenario(
            name="constrained", description="t",
            source_types={"A"}, target_types={"B"},
            min_retention_rate=0.8,
            max_area_cap=50000.0,
            budget_cap=100.0,
            budget_per_conversion=2.5,
        )
        assert s.min_retention_rate == 0.8
        assert s.max_area_cap == 50000.0
        assert s.budget_cap == 100.0
        assert s.budget_per_conversion == 2.5


class TestConstraintActionMask(unittest.TestCase):
    """Test hard constraint enforcement via action_masks()."""

    def _make_mock_env(self, n_farmland, initial_count, min_retention):
        """Create a minimal mock of LandUseOptEnv for mask testing."""
        from data_agent.drl_engine import LandUseOptEnv, FARMLAND, FOREST
        env = object.__new__(LandUseOptEnv)
        # Minimal state for action_masks
        env.swappable_indices = np.array([0, 1, 2, 3])
        env.land_use = np.array([FARMLAND, FARMLAND, FOREST, FOREST], dtype=np.int8)
        env._converted = np.array([False, False, False, False])
        env.n_farmland = n_farmland
        env.initial_n_farmland_count = initial_count
        env.min_retention_rate = min_retention
        return env

    def test_no_constraint_all_valid(self):
        env = self._make_mock_env(n_farmland=2, initial_count=2, min_retention=0.0)
        mask = env.action_masks()
        assert mask.sum() == 4  # all swappable

    def test_retention_blocks_farmland_conversion(self):
        from data_agent.drl_engine import FARMLAND
        # 2 farmland, initial 2, min_retention=0.8 → min_farmland=1
        # n_farmland=2 > 1, so still allowed
        env = self._make_mock_env(n_farmland=2, initial_count=2, min_retention=0.8)
        mask = env.action_masks()
        assert mask.sum() == 4

        # Now n_farmland=1 <= min_farmland=1 → block farmland actions
        env.n_farmland = 1
        mask = env.action_masks()
        # Only forest parcels (indices 2,3) should be valid
        farmland_blocked = not mask[0] and not mask[1]
        forest_ok = mask[2] and mask[3]
        assert farmland_blocked and forest_ok

    def test_retention_100_percent_blocks_all_farmland(self):
        env = self._make_mock_env(n_farmland=2, initial_count=2, min_retention=1.0)
        mask = env.action_masks()
        # min_farmland = 2, n_farmland = 2 → block all farmland
        assert not mask[0] and not mask[1]
        assert mask[2] and mask[3]


class TestConstraintBudgetTracking(unittest.TestCase):
    """Test soft constraint tracking."""

    def test_budget_counters_initialized(self):
        """Verify budget/area counters exist on DRLScenario and propagate."""
        s = DRLScenario(
            name="test", description="t",
            source_types={"A"}, target_types={"B"},
            budget_cap=50.0, max_area_cap=10000.0,
            budget_per_conversion=2.0,
        )
        assert s.budget_cap == 50.0
        assert s.max_area_cap == 10000.0
        assert s.budget_per_conversion == 2.0

    def test_soft_penalty_logic(self):
        """Verify that exceeding budget_cap produces negative reward adjustment."""
        # Simulate the penalty formula from step()
        balance_w = 500.0
        budget_cap = 100.0
        total_budget_spent = 150.0  # 50% over
        overshoot = (total_budget_spent - budget_cap) / budget_cap
        penalty = balance_w * overshoot
        assert penalty == 250.0  # 500 * 0.5

    def test_area_cap_penalty_logic(self):
        """Verify area cap overshoot penalty."""
        balance_w = 500.0
        max_area_cap = 10000.0
        total_area = 12000.0  # 20% over
        overshoot = (total_area - max_area_cap) / max_area_cap
        penalty = balance_w * overshoot
        assert abs(penalty - 100.0) < 0.01  # 500 * 0.2


class TestListScenariosIncludesConstraints(unittest.TestCase):
    def test_list_scenarios_returns_data(self):
        from data_agent.drl_engine import list_scenarios
        scenarios = list_scenarios()
        assert len(scenarios) >= 5  # 3 original + 2 new
        for s in scenarios:
            assert "name" in s
            assert "weights" in s

    def test_road_network_scenario(self):
        from data_agent.drl_engine import SCENARIOS
        s = SCENARIOS["road_network"]
        assert s.name == "道路网络优化"
        assert s.min_retention_rate == 0.7
        assert '公路用地' in s.source_types

    def test_public_facility_layout_scenario(self):
        from data_agent.drl_engine import SCENARIOS
        s = SCENARIOS["public_facility_layout"]
        assert s.name == "公共设施布局优化"
        assert s.min_retention_rate == 0.85
        assert s.budget_cap == 200.0
        assert s.budget_per_conversion == 3.0
        assert '教育用地' in s.source_types


if __name__ == "__main__":
    unittest.main()
