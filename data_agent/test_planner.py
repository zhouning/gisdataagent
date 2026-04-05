"""
Tests for Dynamic Planner agent hierarchy.

- TestPlannerHierarchy: Verifies agent structure, sub-agents, tools, callbacks.
- TestModelTiering: Verifies model tier assignments.
- TestQualityGate: Verifies output file quality validation.
- TestPlanConfirmation: Verifies plan generation prompt exists.
- TestFeatureFlag: Verifies DYNAMIC_PLANNER env var parsing.
"""
import unittest
import os
import tempfile
from unittest.mock import patch
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


def _model_name(model):
    """Extract model name string from a Gemini object or pass through strings."""
    return model.model if hasattr(model, 'model') else model


class TestPlannerHierarchy(unittest.TestCase):
    """Tests for the Planner agent and its sub-agents (5 standalone + 2 workflows)."""

    @classmethod
    def setUpClass(cls):
        from data_agent.agent import planner_agent
        cls.planner = planner_agent

    def test_planner_has_5_sub_agents(self):
        self.assertEqual(len(self.planner.sub_agents), 5)

    def test_sub_agent_names(self):
        names = {a.name for a in self.planner.sub_agents}
        self.assertEqual(names, {
            "PlannerExplorer", "PlannerProcessor",
            "PlannerAnalyzer", "PlannerVisualizer", "PlannerReporter",
        })

    def test_peers_transfer_disabled(self):
        from google.adk.agents import LlmAgent
        for agent in self.planner.sub_agents:
            if isinstance(agent, LlmAgent):
                self.assertTrue(agent.disallow_transfer_to_peers,
                                f"{agent.name} should have disallow_transfer_to_peers=True")

    def test_output_keys(self):
        from google.adk.agents import LlmAgent
        expected = {"data_profile", "processed_data", "analysis_report",
                    "visualizations", "final_report"}
        actual = {a.output_key for a in self.planner.sub_agents if isinstance(a, LlmAgent)}
        self.assertEqual(actual, expected)

    def test_self_correction_on_key_agents(self):
        for name in ["PlannerExplorer", "PlannerProcessor", "PlannerAnalyzer"]:
            agent = next(a for a in self.planner.sub_agents if a.name == name)
            self.assertIsNotNone(agent.after_tool_callback,
                                 f"{name} should have after_tool_callback")

    def test_visualizer_no_self_correction(self):
        viz = next(a for a in self.planner.sub_agents if a.name == "PlannerVisualizer")
        self.assertIsNone(viz.after_tool_callback)

    def test_reporter_no_tools(self):
        reporter = next(a for a in self.planner.sub_agents if a.name == "PlannerReporter")
        self.assertEqual(len(reporter.tools), 0)

    def _run_async(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_planner_has_memory_tools(self):
        from google.adk.tools.base_toolset import BaseToolset
        tool_names = set()
        for t in self.planner.tools:
            if isinstance(t, BaseToolset):
                tools = self._run_async(t.get_tools())
                tool_names.update(ft.name for ft in tools)
            else:
                tool_names.add(t.__name__)
        self.assertIn("save_memory", tool_names)
        self.assertIn("recall_memories", tool_names)

    def test_planner_model(self):
        from data_agent.agent import MODEL_STANDARD
        self.assertEqual(_model_name(self.planner.model), MODEL_STANDARD)

    def test_planner_output_key(self):
        self.assertEqual(self.planner.output_key, "planner_summary")

    def test_explorer_tool_count(self):
        from google.adk.tools.base_toolset import BaseToolset
        explorer = next(a for a in self.planner.sub_agents if a.name == "PlannerExplorer")
        total = 0
        for t in explorer.tools:
            if isinstance(t, BaseToolset):
                tools = self._run_async(t.get_tools())
                total += len(tools)
            else:
                total += 1
        self.assertGreaterEqual(total, 9)

    def test_processor_tool_count(self):
        from google.adk.tools.base_toolset import BaseToolset
        processor = next(a for a in self.planner.sub_agents if a.name == "PlannerProcessor")
        total = 0
        for t in processor.tools:
            if isinstance(t, BaseToolset):
                tools = self._run_async(t.get_tools())
                total += len(tools)
            else:
                total += 1
        self.assertGreaterEqual(total, 19)

    def test_analyzer_has_ffi_and_drl(self):
        from google.adk.tools.base_toolset import BaseToolset
        analyzer = next(a for a in self.planner.sub_agents if a.name == "PlannerAnalyzer")
        tool_names = set()
        for t in analyzer.tools:
            if isinstance(t, BaseToolset):
                tools = self._run_async(t.get_tools())
                tool_names.update(ft.name for ft in tools)
            else:
                tool_names.add(t.__name__)
        self.assertIn("ffi", tool_names)
        self.assertIn("drl_model", tool_names)


class TestLegacyPipelinesPreserved(unittest.TestCase):
    """Ensure legacy pipelines still exist for backward compatibility."""

    def test_data_pipeline_exists(self):
        from data_agent.agent import data_pipeline
        self.assertIsNotNone(data_pipeline)

    def test_governance_pipeline_exists(self):
        from data_agent.agent import governance_pipeline
        self.assertIsNotNone(governance_pipeline)

    def test_general_pipeline_exists(self):
        from data_agent.agent import general_pipeline
        self.assertIsNotNone(general_pipeline)

    def test_root_agent_is_data_pipeline(self):
        from data_agent.agent import root_agent, data_pipeline
        self.assertIs(root_agent, data_pipeline)


class TestFeatureFlag(unittest.TestCase):
    """Test DYNAMIC_PLANNER environment variable parsing."""

    def _parse_flag(self):
        return os.environ.get("DYNAMIC_PLANNER", "true").lower() in ("true", "1", "yes")

    @patch.dict(os.environ, {"DYNAMIC_PLANNER": "false"})
    def test_flag_false(self):
        self.assertFalse(self._parse_flag())

    @patch.dict(os.environ, {"DYNAMIC_PLANNER": "true"})
    def test_flag_true(self):
        self.assertTrue(self._parse_flag())

    @patch.dict(os.environ, {"DYNAMIC_PLANNER": "0"})
    def test_flag_zero(self):
        self.assertFalse(self._parse_flag())

    @patch.dict(os.environ, {"DYNAMIC_PLANNER": "1"})
    def test_flag_one(self):
        self.assertTrue(self._parse_flag())

    @patch.dict(os.environ, {}, clear=False)
    def test_flag_default_true(self):
        """Default is true when env var not set."""
        os.environ.pop("DYNAMIC_PLANNER", None)
        self.assertTrue(self._parse_flag())


class TestModelTiering(unittest.TestCase):
    """Verify model tiering is correctly applied to planner agents."""

    @classmethod
    def setUpClass(cls):
        from data_agent.agent import (
            planner_agent, MODEL_FAST, MODEL_STANDARD, MODEL_PREMIUM
        )
        cls.planner = planner_agent
        cls.MODEL_FAST = MODEL_FAST
        cls.MODEL_STANDARD = MODEL_STANDARD
        cls.MODEL_PREMIUM = MODEL_PREMIUM

    def _get_agent(self, name):
        return next(a for a in self.planner.sub_agents if a.name == name)

    def test_explorer_uses_fast_model(self):
        self.assertEqual(_model_name(self._get_agent("PlannerExplorer").model), self.MODEL_FAST)

    def test_processor_uses_standard_model(self):
        self.assertEqual(_model_name(self._get_agent("PlannerProcessor").model), self.MODEL_STANDARD)

    def test_analyzer_uses_standard_model(self):
        self.assertEqual(_model_name(self._get_agent("PlannerAnalyzer").model), self.MODEL_STANDARD)

    def test_visualizer_uses_standard_model(self):
        self.assertEqual(_model_name(self._get_agent("PlannerVisualizer").model), self.MODEL_STANDARD)

    def test_reporter_uses_premium_model(self):
        self.assertEqual(_model_name(self._get_agent("PlannerReporter").model), self.MODEL_PREMIUM)

    def test_planner_root_uses_standard_model(self):
        self.assertEqual(_model_name(self.planner.model), self.MODEL_STANDARD)

    def test_model_constants_are_strings(self):
        self.assertIsInstance(self.MODEL_FAST, str)
        self.assertIsInstance(self.MODEL_STANDARD, str)
        self.assertIsInstance(self.MODEL_PREMIUM, str)

    def test_model_constants_are_distinct(self):
        models = {self.MODEL_FAST, self.MODEL_STANDARD, self.MODEL_PREMIUM}
        self.assertEqual(len(models), 3, "All three model tiers should be distinct")


class TestQualityGate(unittest.TestCase):
    """Verify quality gate output file validation."""

    def _check(self, response):
        from data_agent.agent import _quality_gate_check
        return _quality_gate_check(response)

    def test_pass_on_no_files(self):
        status, msg = self._check({"result": "操作完成，共处理 10 条记录"})
        self.assertEqual(status, "pass")

    def test_pass_on_nonexistent_path(self):
        status, msg = self._check({"result": "输出: C:\\nonexistent\\fake.shp"})
        self.assertEqual(status, "pass")

    def test_critical_on_zero_byte_file(self):
        with tempfile.NamedTemporaryFile(suffix='.shp', delete=False) as f:
            tmp = f.name
        try:
            status, msg = self._check({"result": f"输出文件: {tmp}"})
            self.assertEqual(status, "critical")
            self.assertIn("0字节", msg)
        finally:
            os.unlink(tmp)

    def test_warning_on_small_html(self):
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w') as f:
            f.write("<html></html>")
            tmp = f.name
        try:
            status, msg = self._check({"result": f"地图: {tmp}"})
            self.assertEqual(status, "warning")
            self.assertIn("不完整", msg)
        finally:
            os.unlink(tmp)

    def test_pass_on_dict_without_paths(self):
        status, msg = self._check({"result": "查询返回 5 行数据"})
        self.assertEqual(status, "pass")


class TestPlanConfirmation(unittest.TestCase):
    """Verify plan generation prompt exists in prompts.yaml."""

    def test_plan_prompt_exists(self):
        import yaml
        with open(os.path.join(os.path.dirname(__file__), 'prompts.yaml'), encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        self.assertIn('plan_generation_prompt', prompts)

    def test_plan_prompt_has_placeholders(self):
        import yaml
        with open(os.path.join(os.path.dirname(__file__), 'prompts.yaml'), encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        template = prompts['plan_generation_prompt']
        self.assertIn('{intent}', template)
        self.assertIn('{user_text}', template)
        self.assertIn('{files_info}', template)

    def test_planner_instruction_has_plan_rule(self):
        import yaml
        with open(os.path.join(os.path.dirname(__file__), 'prompts.yaml'), encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        instruction = prompts['planner_instruction']
        self.assertIn('分析方案', instruction)


class TestReflectionLoops(unittest.TestCase):
    """Tests for v7.1.6 reflection loop expansion to Governance and General pipelines."""

    def test_governance_has_report_loop(self):
        from data_agent.agent import governance_pipeline
        from google.adk.agents import LoopAgent
        loop_agents = [a for a in governance_pipeline.sub_agents if isinstance(a, LoopAgent)]
        self.assertEqual(len(loop_agents), 1)
        self.assertEqual(loop_agents[0].name, "GovernanceReportLoop")

    def test_governance_loop_contains_checker(self):
        from data_agent.agent import governance_pipeline
        from google.adk.agents import LoopAgent
        loop = [a for a in governance_pipeline.sub_agents if isinstance(a, LoopAgent)][0]
        names = [a.name for a in loop.sub_agents]
        self.assertIn("GovernanceReporter", names)
        self.assertIn("GovernanceChecker", names)

    def test_governance_loop_max_iterations(self):
        from data_agent.agent import governance_pipeline
        from google.adk.agents import LoopAgent
        loop = [a for a in governance_pipeline.sub_agents if isinstance(a, LoopAgent)][0]
        self.assertEqual(loop.max_iterations, 3)

    def test_general_has_summary_loop(self):
        from data_agent.agent import general_pipeline
        from google.adk.agents import LoopAgent
        loop_agents = [a for a in general_pipeline.sub_agents if isinstance(a, LoopAgent)]
        self.assertEqual(len(loop_agents), 1)
        self.assertEqual(loop_agents[0].name, "GeneralSummaryLoop")

    def test_general_loop_contains_checker(self):
        from data_agent.agent import general_pipeline
        from google.adk.agents import LoopAgent
        loop = [a for a in general_pipeline.sub_agents if isinstance(a, LoopAgent)][0]
        names = [a.name for a in loop.sub_agents]
        self.assertIn("GeneralSummary", names)
        self.assertIn("GeneralResultChecker", names)

    def test_general_loop_max_iterations(self):
        from data_agent.agent import general_pipeline
        from google.adk.agents import LoopAgent
        loop = [a for a in general_pipeline.sub_agents if isinstance(a, LoopAgent)][0]
        self.assertEqual(loop.max_iterations, 3)

    def test_checker_prompts_exist(self):
        from data_agent.prompts import get_prompt
        gov = get_prompt("general", "governance_checker_instruction")
        self.assertIn("审计方法", gov)
        gen = get_prompt("general", "general_result_checker_instruction")
        self.assertIn("approve_quality", gen)

    def test_all_three_pipelines_have_loops(self):
        """All 3 pipelines (optimization, governance, general) should have LoopAgent."""
        from data_agent.agent import data_pipeline, governance_pipeline, general_pipeline
        from google.adk.agents import LoopAgent

        def has_loop(pipeline):
            return any(isinstance(a, LoopAgent) for a in pipeline.sub_agents)

        self.assertTrue(has_loop(data_pipeline), "Optimization pipeline missing LoopAgent")
        self.assertTrue(has_loop(governance_pipeline), "Governance pipeline missing LoopAgent")
        self.assertTrue(has_loop(general_pipeline), "General pipeline missing LoopAgent")


if __name__ == "__main__":
    unittest.main()
