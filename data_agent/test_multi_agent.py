"""Tests for S-5: Multi-Agent Collaboration."""
import pytest
from unittest.mock import patch


class TestMultiAgentPrompts:
    """Verify multi_agent.yaml prompt loading."""

    def test_data_engineer_prompt_exists(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("multi_agent", "data_engineer_instruction")
        assert "数据工程专家" in prompt or "数据准备" in prompt
        assert len(prompt) > 50

    def test_analyst_prompt_exists(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("multi_agent", "analyst_instruction")
        assert "分析" in prompt
        assert len(prompt) > 50

    def test_visualizer_prompt_exists(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("multi_agent", "visualizer_instruction")
        assert "可视化" in prompt
        assert len(prompt) > 50

    def test_remote_sensing_prompt_exists(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("multi_agent", "remote_sensing_instruction")
        assert "遥感" in prompt
        assert len(prompt) > 50

    def test_coordinator_supplement_exists(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("multi_agent", "coordinator_supplement")
        assert "DataEngineerAgent" in prompt
        assert "FullAnalysis" in prompt

    def test_prompt_version(self):
        from data_agent.prompts import get_prompt_version
        version = get_prompt_version("multi_agent")
        assert version == "1.0.0"


class TestAgentFactories:
    """Verify factory functions create valid agents."""

    def test_data_engineer_factory(self):
        from data_agent.agent import _make_data_engineer
        agent = _make_data_engineer("TestDataEngineer")
        assert agent.name == "TestDataEngineer"
        assert agent.output_key == "prepared_data"
        assert agent.disallow_transfer_to_peers is True

    def test_analyst_factory(self):
        from data_agent.agent import _make_analyst
        agent = _make_analyst("TestAnalyst")
        assert agent.name == "TestAnalyst"
        assert agent.output_key == "analysis_result"
        assert agent.disallow_transfer_to_peers is True

    def test_visualizer_factory(self):
        from data_agent.agent import _make_visualizer_agent
        agent = _make_visualizer_agent("TestViz")
        assert agent.name == "TestViz"
        assert agent.output_key == "visualization_output"
        assert agent.disallow_transfer_to_peers is True

    def test_remote_sensing_factory(self):
        from data_agent.agent import _make_remote_sensing
        agent = _make_remote_sensing("TestRS")
        assert agent.name == "TestRS"
        assert agent.output_key == "rs_analysis"
        assert agent.disallow_transfer_to_peers is True

    def test_factory_independence(self):
        """ADK one-parent constraint: two factory calls produce distinct instances."""
        from data_agent.agent import _make_data_engineer
        a1 = _make_data_engineer("Agent1")
        a2 = _make_data_engineer("Agent2")
        assert a1 is not a2
        assert a1.name != a2.name

    def test_factory_override(self):
        from data_agent.agent import _make_analyst
        agent = _make_analyst("OverrideTest", output_key="custom_output")
        assert agent.output_key == "custom_output"


class TestStandaloneAgents:
    """Verify standalone agent instances."""

    def test_data_engineer_agent_exists(self):
        from data_agent.agent import data_engineer_agent
        assert data_engineer_agent.name == "DataEngineerAgent"

    def test_analyst_agent_exists(self):
        from data_agent.agent import analyst_agent
        assert analyst_agent.name == "AnalystAgent"

    def test_visualizer_agent_exists(self):
        from data_agent.agent import visualizer_agent
        assert visualizer_agent.name == "VisualizerAgent"

    def test_remote_sensing_agent_exists(self):
        from data_agent.agent import remote_sensing_agent
        assert remote_sensing_agent.name == "RemoteSensingAgent"


class TestMultiAgentWorkflows:
    """Verify multi-agent workflow compositions."""

    def test_full_analysis_workflow_structure(self):
        from data_agent.agent import full_analysis_workflow
        assert full_analysis_workflow.name == "FullAnalysis"
        sub_names = [a.name for a in full_analysis_workflow.sub_agents]
        assert len(sub_names) == 3
        assert sub_names[0] == "FADataEngineer"
        assert sub_names[1] == "FAAnalyst"
        assert sub_names[2] == "FAVisualizer"

    def test_rs_analysis_workflow_structure(self):
        from data_agent.agent import rs_analysis_workflow
        assert rs_analysis_workflow.name == "RSAnalysis"
        sub_names = [a.name for a in rs_analysis_workflow.sub_agents]
        assert len(sub_names) == 2
        assert sub_names[0] == "RSRemoteSensing"
        assert sub_names[1] == "RSVisualizer"


class TestPlannerIntegration:
    """Verify new agents are integrated into planner."""

    def test_planner_has_specialized_agents(self):
        from data_agent.agent import planner_agent
        sub_names = [a.name for a in planner_agent.sub_agents]
        assert "PlannerExplorer" in sub_names
        assert "PlannerProcessor" in sub_names
        assert "PlannerAnalyzer" in sub_names
        assert "PlannerVisualizer" in sub_names
        assert "PlannerReporter" in sub_names

    def test_planner_has_5_sub_agents(self):
        from data_agent.agent import planner_agent
        sub_names = [a.name for a in planner_agent.sub_agents]
        assert len(sub_names) == 5

    def test_planner_retains_original_sub_agents(self):
        from data_agent.agent import planner_agent
        sub_names = [a.name for a in planner_agent.sub_agents]
        # Original 5 Planner* agents
        assert "PlannerExplorer" in sub_names
        assert "PlannerProcessor" in sub_names
        assert "PlannerAnalyzer" in sub_names
        assert "PlannerVisualizer" in sub_names
        assert "PlannerReporter" in sub_names
        assert len(sub_names) == 5

    def test_planner_has_operator_toolset(self):
        """Planner should have OperatorToolset for semantic operators."""
        from data_agent.agent import planner_agent
        from data_agent.toolsets.operator_tools import OperatorToolset
        tool_types = [type(t).__name__ for t in planner_agent.tools]
        assert "OperatorToolset" in tool_types


class TestOutputKeyUniqueness:
    """All agents must have unique output_keys to avoid context collision."""

    def test_unique_output_keys(self):
        from data_agent.agent import (
            data_engineer_agent, analyst_agent,
            visualizer_agent, remote_sensing_agent,
            planner_explorer, planner_processor,
            planner_analyzer, planner_visualizer,
            planner_reporter, planner_agent,
        )
        agents = [
            data_engineer_agent, analyst_agent,
            visualizer_agent, remote_sensing_agent,
            planner_explorer, planner_processor,
            planner_analyzer, planner_visualizer,
            planner_reporter, planner_agent,
        ]
        output_keys = [a.output_key for a in agents]
        assert len(output_keys) == len(set(output_keys)), \
            f"Duplicate output_keys: {[k for k in output_keys if output_keys.count(k) > 1]}"


class TestModelTiering:
    """Verify model tier assignments."""

    def test_data_engineer_uses_standard(self):
        from data_agent.agent import data_engineer_agent
        model_name = str(data_engineer_agent.model)
        assert "flash" in model_name.lower() or "gemini" in model_name.lower()

    def test_analyst_uses_standard(self):
        from data_agent.agent import analyst_agent
        model_name = str(analyst_agent.model)
        assert "flash" in model_name.lower() or "gemini" in model_name.lower()
