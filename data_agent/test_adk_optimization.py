"""Tests for ADK architecture optimizations (2.1, 2.2, 2.3).

Verifies:
- AgentTool wrapping of knowledge_agent (2.1)
- LoopAgent quality checking loop (2.2)
- Sub-workflow packaging for Planner (2.3)
"""
import unittest
from unittest.mock import MagicMock


class TestAgentToolKnowledge(unittest.TestCase):
    """Tests for AgentTool wrapping of knowledge_agent (2.1)."""

    def test_knowledge_tool_is_agent_tool(self):
        """knowledge_tool should be an AgentTool instance."""
        from google.adk.tools import AgentTool
        from data_agent.agent import knowledge_tool
        self.assertIsInstance(knowledge_tool, AgentTool)

    def test_pipeline_has_parallel_data_ingestion(self):
        """data_pipeline should contain ParallelDataIngestion inside DataEngineering."""
        from google.adk.agents import ParallelAgent
        from data_agent.agent import data_pipeline
        data_eng = data_pipeline.sub_agents[0]
        self.assertEqual(data_eng.name, "DataEngineering")
        parallel = data_eng.sub_agents[0]
        self.assertIsInstance(parallel, ParallelAgent)
        self.assertEqual(parallel.name, "ParallelDataIngestion")

    def test_processing_agent_has_knowledge_tool(self):
        """data_processing_agent should have knowledge_tool in its tools."""
        from data_agent.agent import data_processing_agent, knowledge_tool
        self.assertIn(knowledge_tool, data_processing_agent.tools)


class TestAnalysisQualityLoop(unittest.TestCase):
    """Tests for LoopAgent quality checking (2.2)."""

    def test_loop_agent_type(self):
        """analysis_quality_loop should be a LoopAgent."""
        from google.adk.agents import LoopAgent
        from data_agent.agent import analysis_quality_loop
        self.assertIsInstance(analysis_quality_loop, LoopAgent)

    def test_loop_max_iterations(self):
        """LoopAgent should have max_iterations=3."""
        from data_agent.agent import analysis_quality_loop
        self.assertEqual(analysis_quality_loop.max_iterations, 3)

    def test_loop_sub_agents(self):
        """LoopAgent should contain DataAnalysis and QualityChecker."""
        from data_agent.agent import analysis_quality_loop
        names = [a.name for a in analysis_quality_loop.sub_agents]
        self.assertEqual(names, ["DataAnalysis", "QualityChecker"])

    def test_quality_checker_has_approve_tool(self):
        """QualityChecker should have approve_quality in its tools."""
        from data_agent.agent import quality_checker_agent
        from data_agent.utils import approve_quality
        self.assertIn(approve_quality, quality_checker_agent.tools)

    def test_approve_quality_sets_escalate(self):
        """approve_quality should set tool_context.actions.escalate = True."""
        from data_agent.utils import approve_quality
        mock_ctx = MagicMock()
        mock_ctx.actions.escalate = False
        result = approve_quality("test pass", mock_ctx)
        self.assertTrue(mock_ctx.actions.escalate)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["verdict"], "test pass")

    def test_loop_in_data_pipeline(self):
        """data_pipeline should contain AnalysisQualityLoop (not raw DataAnalysis)."""
        from data_agent.agent import data_pipeline
        sub_names = [a.name for a in data_pipeline.sub_agents]
        self.assertIn("AnalysisQualityLoop", sub_names)
        self.assertNotIn("DataAnalysis", sub_names)


class TestSubWorkflows(unittest.TestCase):
    """Tests for sub-workflow packaging (2.3)."""

    def test_explore_process_workflow_structure(self):
        """ExploreAndProcess should be Sequential with ParallelIngestion + Processor."""
        from google.adk.agents import SequentialAgent, ParallelAgent
        from data_agent.agent import explore_process_workflow
        self.assertIsInstance(explore_process_workflow, SequentialAgent)
        self.assertEqual(len(explore_process_workflow.sub_agents), 2)
        names = [a.name for a in explore_process_workflow.sub_agents]
        self.assertEqual(names, ["WFParallelIngestion", "WFProcessor"])
        # First sub-agent should be a ParallelAgent
        self.assertIsInstance(explore_process_workflow.sub_agents[0], ParallelAgent)

    def test_analyze_viz_workflow_structure(self):
        """AnalyzeAndVisualize should be a SequentialAgent with 2 sub-agents."""
        from google.adk.agents import SequentialAgent
        from data_agent.agent import analyze_viz_workflow
        self.assertIsInstance(analyze_viz_workflow, SequentialAgent)
        self.assertEqual(len(analyze_viz_workflow.sub_agents), 2)
        names = [a.name for a in analyze_viz_workflow.sub_agents]
        self.assertEqual(names, ["WFAnalyzer", "WFVisualizer"])

    def test_planner_has_13_sub_agents(self):
        """Planner should have 5 standalone + 2 workflows + 4 specialized + 2 multi-agent workflows."""
        from data_agent.agent import planner_agent
        self.assertEqual(len(planner_agent.sub_agents), 13)

    def test_planner_includes_workflows(self):
        """Planner sub_agents should include the workflow agents."""
        from data_agent.agent import planner_agent
        names = [a.name for a in planner_agent.sub_agents]
        self.assertIn("ExploreAndProcess", names)
        self.assertIn("AnalyzeAndVisualize", names)

    def test_factory_creates_distinct_instances(self):
        """Factory functions should produce separate agent instances."""
        from data_agent.agent import (
            planner_explorer, explore_process_workflow,
        )
        wf_parallel = explore_process_workflow.sub_agents[0]  # WFParallelIngestion
        wf_explorer = wf_parallel.sub_agents[0]  # WFExplorer inside parallel
        # Different name
        self.assertNotEqual(planner_explorer.name, wf_explorer.name)
        # Different object
        self.assertIsNot(planner_explorer, wf_explorer)


class TestFactoryFunctions(unittest.TestCase):
    """Tests for planner agent factory functions."""

    def test_make_planner_explorer(self):
        from data_agent.agent import _make_planner_explorer
        agent = _make_planner_explorer("TestExplorer")
        self.assertEqual(agent.name, "TestExplorer")
        self.assertTrue(agent.disallow_transfer_to_peers)

    def test_make_planner_processor(self):
        from data_agent.agent import _make_planner_processor
        agent = _make_planner_processor("TestProcessor")
        self.assertEqual(agent.name, "TestProcessor")
        self.assertTrue(agent.disallow_transfer_to_peers)

    def test_make_planner_analyzer(self):
        from data_agent.agent import _make_planner_analyzer
        agent = _make_planner_analyzer("TestAnalyzer")
        self.assertEqual(agent.name, "TestAnalyzer")
        self.assertTrue(agent.disallow_transfer_to_peers)

    def test_make_planner_visualizer(self):
        from data_agent.agent import _make_planner_visualizer
        agent = _make_planner_visualizer("TestVisualizer")
        self.assertEqual(agent.name, "TestVisualizer")
        self.assertTrue(agent.disallow_transfer_to_peers)

    def test_factory_override(self):
        """Factory should accept overrides."""
        from data_agent.agent import _make_planner_explorer, MODEL_PREMIUM
        agent = _make_planner_explorer("CustomExplorer", model=MODEL_PREMIUM)
        self.assertEqual(agent.model, MODEL_PREMIUM)


if __name__ == "__main__":
    unittest.main()
