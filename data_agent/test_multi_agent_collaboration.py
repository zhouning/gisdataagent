"""
Tests for S-5: Multi-Agent Collaboration — Task decomposition, coordination, aggregation.

Extends test_multi_agent.py with deeper integration tests.
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Task decomposition: verify agent toolset specialization
# ---------------------------------------------------------------------------

class TestTaskDecomposition:
    """Each specialized agent must have the right toolsets for its domain."""

    def _get_toolset_names(self, agent):
        return [type(t).__name__ for t in agent.tools]

    def test_data_engineer_has_cleaning_tools(self):
        from data_agent.agent import data_engineer_agent
        names = self._get_toolset_names(data_engineer_agent)
        assert "DataCleaningToolset" in names
        assert "GovernanceToolset" in names
        assert "PrecisionToolset" in names

    def test_data_engineer_has_operator_toolset(self):
        from data_agent.agent import data_engineer_agent
        names = self._get_toolset_names(data_engineer_agent)
        assert "OperatorToolset" in names

    def test_analyst_has_analysis_tools(self):
        from data_agent.agent import analyst_agent
        names = self._get_toolset_names(analyst_agent)
        assert "AnalysisToolset" in names or "SpatialStatisticsToolset" in names
        assert "CausalInferenceToolset" in names
        assert "WorldModelToolset" in names

    def test_analyst_has_drl_tools(self):
        from data_agent.agent import analyst_agent
        names = self._get_toolset_names(analyst_agent)
        assert "DreamerToolset" in names or "AdvancedAnalysisToolset" in names

    def test_visualizer_has_viz_tools(self):
        from data_agent.agent import visualizer_agent
        names = self._get_toolset_names(visualizer_agent)
        assert "VisualizationToolset" in names
        assert "ChartToolset" in names

    def test_remote_sensing_has_rs_tools(self):
        from data_agent.agent import remote_sensing_agent
        names = self._get_toolset_names(remote_sensing_agent)
        assert "RemoteSensingToolset" in names
        assert "WatershedToolset" in names

    def test_no_cross_domain_tools(self):
        """Specialized agents should NOT have each other's primary toolsets."""
        from data_agent.agent import data_engineer_agent, analyst_agent, visualizer_agent

        engineer_names = self._get_toolset_names(data_engineer_agent)
        assert "CausalInferenceToolset" not in engineer_names
        assert "ChartToolset" not in engineer_names

        analyst_names = self._get_toolset_names(analyst_agent)
        assert "DataCleaningToolset" not in analyst_names
        assert "ChartToolset" not in analyst_names

        viz_names = self._get_toolset_names(visualizer_agent)
        assert "CausalInferenceToolset" not in viz_names
        assert "DataCleaningToolset" not in viz_names


# ---------------------------------------------------------------------------
# Coordination: verify workflow composition and sequencing
# ---------------------------------------------------------------------------

class TestCoordination:
    """Multi-agent workflows must enforce correct execution order."""

    def test_full_analysis_order(self):
        """FullAnalysis: DataEngineer → Analyst → Visualizer."""
        from data_agent.agent import full_analysis_workflow
        agents = full_analysis_workflow.sub_agents
        assert agents[0].output_key == "prepared_data"
        assert agents[1].output_key == "analysis_result"
        assert agents[2].output_key == "visualization_output"

    def test_rs_analysis_order(self):
        """RSAnalysis: RemoteSensing → Visualizer."""
        from data_agent.agent import rs_analysis_workflow
        agents = rs_analysis_workflow.sub_agents
        assert agents[0].output_key == "rs_analysis"
        assert agents[1].output_key == "visualization_output"

    def test_peer_transfer_disabled(self):
        """All specialized agents must block peer-to-peer transfer."""
        from data_agent.agent import (
            data_engineer_agent, analyst_agent,
            visualizer_agent, remote_sensing_agent,
        )
        for agent in [data_engineer_agent, analyst_agent,
                      visualizer_agent, remote_sensing_agent]:
            assert agent.disallow_transfer_to_peers is True, \
                f"{agent.name} should have disallow_transfer_to_peers=True"

    def test_workflow_agents_are_independent_instances(self):
        """ADK one-parent: workflow sub_agents must differ from standalone instances."""
        from data_agent.agent import (
            full_analysis_workflow, data_engineer_agent,
            analyst_agent, visualizer_agent,
        )
        for sub in full_analysis_workflow.sub_agents:
            assert sub is not data_engineer_agent
            assert sub is not analyst_agent
            assert sub is not visualizer_agent


# ---------------------------------------------------------------------------
# Aggregation: verify output keys feed into downstream agents
# ---------------------------------------------------------------------------

class TestResultAggregation:
    """Output keys must be compatible across the pipeline."""

    def test_data_engineer_output_matches_analyst_expectation(self):
        """DataEngineer outputs 'prepared_data' which Analyst can consume."""
        from data_agent.agent import full_analysis_workflow
        engineer = full_analysis_workflow.sub_agents[0]
        assert engineer.output_key == "prepared_data"

    def test_analyst_output_matches_visualizer_expectation(self):
        """Analyst outputs 'analysis_result' which Visualizer can consume."""
        from data_agent.agent import full_analysis_workflow
        analyst = full_analysis_workflow.sub_agents[1]
        assert analyst.output_key == "analysis_result"

    def test_all_workflow_output_keys_unique(self):
        """Within a single workflow, no two agents can share output_key."""
        from data_agent.agent import full_analysis_workflow, rs_analysis_workflow
        for wf in [full_analysis_workflow, rs_analysis_workflow]:
            keys = [a.output_key for a in wf.sub_agents]
            assert len(keys) == len(set(keys)), \
                f"Duplicate output_keys in {wf.name}: {keys}"

    def test_planner_coordinator_supplement(self):
        """Planner instruction should reference new agent names."""
        from data_agent.prompts import get_prompt
        supplement = get_prompt("multi_agent", "coordinator_supplement")
        assert "DataEngineerAgent" in supplement
        assert "AnalystAgent" in supplement
        assert "VisualizerAgent" in supplement
        assert "RemoteSensingAgent" in supplement
        assert "FullAnalysis" in supplement
        assert "RSAnalysis" in supplement


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and robustness checks."""

    def test_factory_with_empty_tools(self):
        """Factory should work even with overridden empty tools list."""
        from data_agent.agent import _make_data_engineer
        agent = _make_data_engineer("EmptyToolsTest", tools=[])
        assert agent.name == "EmptyToolsTest"
        assert agent.tools == []

    def test_factory_custom_model(self):
        """Factory should accept model override."""
        from data_agent.agent import _make_analyst
        agent = _make_analyst("CustomModel", model="gemini-2.0-flash")
        assert "flash" in str(agent.model).lower() or "gemini" in str(agent.model).lower()

    def test_full_analysis_has_correct_description(self):
        from data_agent.agent import full_analysis_workflow
        assert "端到端" in full_analysis_workflow.description or "准备" in full_analysis_workflow.description

    def test_rs_analysis_has_correct_description(self):
        from data_agent.agent import rs_analysis_workflow
        assert "遥感" in rs_analysis_workflow.description or "RS" in rs_analysis_workflow.description
