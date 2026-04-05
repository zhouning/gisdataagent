"""
Tests for Parallel Pipeline Execution (v9.0.2).

Tests ParallelDataIngestion, SemanticPreFetch agent, planner workflow
parallelization, and _make_semantic_prefetch factory.
"""

import unittest


def _model_name(model):
    """Extract model name string from a Gemini object or pass through strings."""
    return model.model if hasattr(model, 'model') else model


# ---------------------------------------------------------------------------
# Optimization Pipeline — ParallelDataIngestion
# ---------------------------------------------------------------------------

class TestParallelDataIngestion(unittest.TestCase):
    """Verify ParallelDataIngestion wraps DataExploration + SemanticPreFetch."""

    def test_is_parallel_agent(self):
        from google.adk.agents import ParallelAgent
        from data_agent.agent import parallel_data_ingestion
        self.assertIsInstance(parallel_data_ingestion, ParallelAgent)

    def test_name(self):
        from data_agent.agent import parallel_data_ingestion
        self.assertEqual(parallel_data_ingestion.name, "ParallelDataIngestion")

    def test_has_two_sub_agents(self):
        from data_agent.agent import parallel_data_ingestion
        self.assertEqual(len(parallel_data_ingestion.sub_agents), 2)

    def test_sub_agent_names(self):
        from data_agent.agent import parallel_data_ingestion
        names = [a.name for a in parallel_data_ingestion.sub_agents]
        self.assertEqual(names, ["DataExploration", "SemanticPreFetch"])

    def test_exploration_has_data_profile_output(self):
        from data_agent.agent import parallel_data_ingestion
        exploration = parallel_data_ingestion.sub_agents[0]
        self.assertEqual(exploration.output_key, "data_profile")

    def test_prefetch_has_semantic_context_output(self):
        from data_agent.agent import parallel_data_ingestion
        prefetch = parallel_data_ingestion.sub_agents[1]
        self.assertEqual(prefetch.output_key, "semantic_context")


# ---------------------------------------------------------------------------
# SemanticPreFetch Agent
# ---------------------------------------------------------------------------

class TestSemanticPreFetchAgent(unittest.TestCase):
    """Verify SemanticPreFetch agent configuration."""

    def test_is_llm_agent(self):
        from google.adk.agents import LlmAgent
        from data_agent.agent import semantic_prefetch_agent
        self.assertIsInstance(semantic_prefetch_agent, LlmAgent)

    def test_uses_fast_model(self):
        from data_agent.agent import semantic_prefetch_agent, MODEL_FAST
        self.assertEqual(_model_name(semantic_prefetch_agent.model), MODEL_FAST)

    def test_output_key(self):
        from data_agent.agent import semantic_prefetch_agent
        self.assertEqual(semantic_prefetch_agent.output_key, "semantic_context")

    def test_has_semantic_tools(self):
        """SemanticPreFetch should have SemanticLayerToolset and DataLakeToolset."""
        from data_agent.agent import semantic_prefetch_agent
        from data_agent.toolsets import SemanticLayerToolset, DataLakeToolset
        toolset_types = [type(t) for t in semantic_prefetch_agent.tools]
        self.assertIn(SemanticLayerToolset, toolset_types)
        self.assertIn(DataLakeToolset, toolset_types)


# ---------------------------------------------------------------------------
# DataEngineering Structure
# ---------------------------------------------------------------------------

class TestDataEngineeringStructure(unittest.TestCase):
    """Verify DataEngineering now uses ParallelDataIngestion → DataProcessing."""

    def test_data_engineering_sub_agents(self):
        from data_agent.agent import data_engineering_agent
        names = [a.name for a in data_engineering_agent.sub_agents]
        self.assertEqual(names, ["ParallelDataIngestion", "DataProcessing"])

    def test_first_sub_is_parallel(self):
        from google.adk.agents import ParallelAgent
        from data_agent.agent import data_engineering_agent
        self.assertIsInstance(data_engineering_agent.sub_agents[0], ParallelAgent)

    def test_second_sub_is_llm(self):
        from google.adk.agents import LlmAgent
        from data_agent.agent import data_engineering_agent
        self.assertIsInstance(data_engineering_agent.sub_agents[1], LlmAgent)


# ---------------------------------------------------------------------------
# Full Pipeline Integration
# ---------------------------------------------------------------------------

class TestPipelineWithParallel(unittest.TestCase):
    """Verify data_pipeline structure with parallel ingestion."""

    def test_pipeline_stage_names(self):
        from data_agent.agent import data_pipeline
        names = [a.name for a in data_pipeline.sub_agents]
        self.assertEqual(names, [
            "DataEngineering", "AnalysisQualityLoop",
            "DataVisualization", "DataSummary",
        ])

    def test_pipeline_still_has_four_stages(self):
        from data_agent.agent import data_pipeline
        self.assertEqual(len(data_pipeline.sub_agents), 4)


# ---------------------------------------------------------------------------
# Planner Workflow Parallelization
# ---------------------------------------------------------------------------

class TestPlannerParallelWorkflow(unittest.TestCase):
    """Verify planner's ExploreAndProcess uses parallel ingestion."""

    def test_explore_process_has_parallel_first(self):
        from google.adk.agents import ParallelAgent
        from data_agent.agent import explore_process_workflow
        first = explore_process_workflow.sub_agents[0]
        self.assertIsInstance(first, ParallelAgent)
        self.assertEqual(first.name, "WFParallelIngestion")

    def test_wf_parallel_has_explorer_and_prefetch(self):
        from data_agent.agent import explore_process_workflow
        parallel = explore_process_workflow.sub_agents[0]
        names = [a.name for a in parallel.sub_agents]
        self.assertEqual(names, ["WFExplorer", "WFSemanticPreFetch"])

    def test_wf_processor_still_present(self):
        from data_agent.agent import explore_process_workflow
        self.assertEqual(explore_process_workflow.sub_agents[1].name, "WFProcessor")


# ---------------------------------------------------------------------------
# SemanticPreFetch Factory
# ---------------------------------------------------------------------------

class TestSemanticPreFetchFactory(unittest.TestCase):
    """Verify _make_semantic_prefetch factory function."""

    def test_creates_named_agent(self):
        from data_agent.agent import _make_semantic_prefetch
        agent = _make_semantic_prefetch("TestPrefetch")
        self.assertEqual(agent.name, "TestPrefetch")

    def test_output_key(self):
        from data_agent.agent import _make_semantic_prefetch
        agent = _make_semantic_prefetch("PF1")
        self.assertEqual(agent.output_key, "semantic_context")

    def test_disallow_transfer(self):
        from data_agent.agent import _make_semantic_prefetch
        agent = _make_semantic_prefetch("PF2")
        self.assertTrue(agent.disallow_transfer_to_peers)

    def test_factory_creates_distinct_instances(self):
        from data_agent.agent import _make_semantic_prefetch
        a1 = _make_semantic_prefetch("PF_A")
        a2 = _make_semantic_prefetch("PF_B")
        self.assertIsNot(a1, a2)
        self.assertNotEqual(a1.name, a2.name)


# ---------------------------------------------------------------------------
# Agent Hooks compatibility — ParallelAgent in attach_lifecycle_hooks
# ---------------------------------------------------------------------------

class TestHooksWithParallelAgent(unittest.TestCase):
    """Verify attach_lifecycle_hooks skips ParallelAgent but processes children."""

    def test_hooks_skip_parallel_agent(self):
        from unittest.mock import MagicMock
        from google.adk.agents import LlmAgent, ParallelAgent
        from data_agent.agent_hooks import attach_lifecycle_hooks

        child1 = MagicMock(spec=LlmAgent)
        child1.name = "C1"
        child1.before_agent_callback = None
        child1.after_agent_callback = None
        child1.sub_agents = []

        child2 = MagicMock(spec=LlmAgent)
        child2.name = "C2"
        child2.before_agent_callback = None
        child2.after_agent_callback = None
        child2.sub_agents = []

        parallel = MagicMock(spec=ParallelAgent)
        parallel.name = "TestParallel"
        parallel.sub_agents = [child1, child2]

        attach_lifecycle_hooks(parallel, "optimization")

        # Children should get callbacks, ParallelAgent itself should not
        self.assertIsNotNone(child1.before_agent_callback)
        self.assertIsNotNone(child2.after_agent_callback)


if __name__ == "__main__":
    unittest.main()
