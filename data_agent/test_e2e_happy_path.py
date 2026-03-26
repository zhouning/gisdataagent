"""End-to-end happy-path tests for the three pipelines.

Uses mock LLM responses to test the full pipeline flow without
requiring actual API keys or database connections.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


class TestE2EGeneral(unittest.TestCase):
    """E2E test: General pipeline happy path."""

    def test_pipeline_runner_import(self):
        """Verify pipeline_runner module imports correctly."""
        from data_agent.pipeline_runner import PipelineResult
        fields = PipelineResult.__dataclass_fields__
        self.assertIn("report_text", fields)
        self.assertIn("generated_files", fields)
        self.assertIn("tool_execution_log", fields)

    def test_intent_classification_general(self):
        """Verify general queries are classified correctly."""
        from data_agent.intent_router import classify_intent
        with patch("data_agent.intent_router._router_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = "GENERAL|general_query|TOOLS:all"
            mock_resp.usage_metadata = None
            mock_client.models.generate_content.return_value = mock_resp
            result = classify_intent("显示上海市的地图")
            # classify_intent returns a 5-tuple: (intent, reason, tokens, tool_cats, lang)
            self.assertEqual(result[0], "GENERAL")

    def test_intent_classification_optimization(self):
        """Verify optimization queries are classified correctly."""
        from data_agent.intent_router import classify_intent
        with patch("data_agent.intent_router._router_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = "OPTIMIZATION|land_use|TOOLS:all"
            mock_resp.usage_metadata = None
            mock_client.models.generate_content.return_value = mock_resp
            result = classify_intent("优化这块区域的土地利用")
            self.assertEqual(result[0], "OPTIMIZATION")

    def test_intent_classification_governance(self):
        """Verify governance queries are classified correctly."""
        from data_agent.intent_router import classify_intent
        with patch("data_agent.intent_router._router_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = "GOVERNANCE|quality_check|TOOLS:quality_audit"
            mock_resp.usage_metadata = None
            mock_client.models.generate_content.return_value = mock_resp
            result = classify_intent("检查数据质量")
            self.assertEqual(result[0], "GOVERNANCE")


class TestE2ETaskDecomposition(unittest.TestCase):
    """E2E test: Task decomposition for multi-step queries."""

    def test_should_decompose_complex(self):
        from data_agent.intent_router import should_decompose
        self.assertTrue(should_decompose("首先加载数据，然后计算缓冲区，最后生成热力图"))

    def test_should_decompose_simple(self):
        from data_agent.intent_router import should_decompose
        self.assertFalse(should_decompose("显示地图"))


class TestE2EMemoryExtraction(unittest.TestCase):
    """E2E test: Memory extraction pipeline."""

    @patch("data_agent.memory.get_engine", return_value=None)
    def test_extract_facts_import(self, _):
        """Verify memory extraction functions are importable."""
        from data_agent.memory import extract_facts_from_conversation
        self.assertTrue(callable(extract_facts_from_conversation))


class TestE2ESkillDependencyGraph(unittest.TestCase):
    """E2E test: Skill dependency graph."""

    @patch("data_agent.skill_dependency_graph._load_skills_with_deps")
    def test_full_graph_workflow(self, mock_load):
        """Test complete workflow: build -> validate -> execute order."""
        mock_load.return_value = {
            1: {"name": "ingestion", "depends_on": []},
            2: {"name": "analysis", "depends_on": [1]},
            3: {"name": "report", "depends_on": [2]},
        }
        from data_agent.skill_dependency_graph import (
            build_skill_graph, validate_dependency, get_execution_order
        )

        # Build graph
        graph = build_skill_graph("testuser")
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertFalse(graph["has_cycle"])

        # Validate adding valid dependency
        result = validate_dependency(3, 1, "testuser")
        self.assertTrue(result["valid"])

        # Get execution order
        waves = get_execution_order([1, 2, 3], "testuser")
        self.assertEqual(waves[0], [1])  # ingestion first


class TestE2EOutputSchemas(unittest.TestCase):
    """E2E test: Output schema validation."""

    def test_quality_report_schema(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        result = validate_skill_output({
            "verdict": "pass", "pass_rate": 0.9,
            "findings": [], "recommendations": [], "summary": "OK"
        }, "quality_report")
        self.assertTrue(result["valid"])


class TestE2EDRLInterpretability(unittest.TestCase):
    """E2E test: DRL explainability."""

    def test_scenario_summary(self):
        from data_agent.drl_interpretability import get_scenario_feature_summary
        result = get_scenario_feature_summary("farmland_optimization")
        self.assertIn("slope", result["key_features"])


if __name__ == "__main__":
    unittest.main()
