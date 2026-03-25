"""Tests for llm_causal.py — LLM-based causal inference (Angle B).

All Gemini calls are mocked via ``data_agent.llm_causal._client``.
Each test class covers one public tool function; helper and toolset tests
are at the bottom.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
#  Helpers to build mock Gemini responses
# ---------------------------------------------------------------------------

def _mock_gemini_response(text: str,
                          prompt_tokens: int = 100,
                          candidates_tokens: int = 200) -> MagicMock:
    """Create a mock Gemini response object matching the real structure."""
    resp = MagicMock()
    resp.text = text
    resp.usage_metadata.prompt_token_count = prompt_tokens
    resp.usage_metadata.candidates_token_count = candidates_tokens
    return resp


# ---------------------------------------------------------------------------
#  Sample LLM JSON payloads (reused across tests)
# ---------------------------------------------------------------------------

_SAMPLE_DAG_JSON = json.dumps({
    "nodes": [
        {"name": "城市绿地面积", "type": "exposure"},
        {"name": "PM2.5浓度", "type": "outcome"},
        {"name": "人口密度", "type": "confounder"},
        {"name": "工业排放", "type": "confounder"},
        {"name": "植被净化效应", "type": "mediator"},
    ],
    "edges": [
        {"from": "城市绿地面积", "to": "植被净化效应", "mechanism": "植被吸附颗粒物"},
        {"from": "植被净化效应", "to": "PM2.5浓度", "mechanism": "降低大气悬浮颗粒"},
        {"from": "城市绿地面积", "to": "PM2.5浓度", "mechanism": "直接降低浓度"},
        {"from": "人口密度", "to": "PM2.5浓度", "mechanism": "人类活动排放"},
        {"from": "工业排放", "to": "PM2.5浓度", "mechanism": "直接排放"},
        {"from": "人口密度", "to": "城市绿地面积", "mechanism": "建设用地挤占"},
    ],
    "explanation": "城市绿地面积通过直接和间接(植被净化)两条路径影响PM2.5浓度。",
    "identification_strategy": "IV + 空间断点回归",
}, ensure_ascii=False)

_SAMPLE_COUNTERFACTUAL_JSON = json.dumps({
    "counterfactual_chain": [
        {
            "step": 1,
            "cause": "退耕还林政策实施",
            "effect": "坡耕地转为林地",
            "mechanism": "政策补贴激励农户退耕",
            "time_lag": "1-2年",
        },
        {
            "step": 2,
            "cause": "坡耕地转为林地",
            "effect": "植被覆盖率提升",
            "mechanism": "树木自然生长",
            "time_lag": "3-5年",
        },
        {
            "step": 3,
            "cause": "植被覆盖率提升",
            "effect": "土壤侵蚀减少",
            "mechanism": "根系固土、冠层截雨",
            "time_lag": "1-3年",
        },
    ],
    "estimated_effect": {
        "direction": "positive",
        "magnitude": "large",
        "description": "植被覆盖率提升约20-30个百分点",
    },
    "confidence": "high",
    "key_assumptions": ["政策持续执行", "气候条件稳定"],
    "sensitivity_factors": [
        {"factor": "降水量变化", "impact": "降水异常会影响植被恢复速度"},
    ],
    "analogous_cases": ["三北防护林工程"],
}, ensure_ascii=False)

_SAMPLE_MECHANISM_JSON = json.dumps({
    "mechanism_explanation": "PSM结果表明城市绿地对房价有显著正向因果效应。",
    "causal_pathway": [
        {"from": "绿地面积", "to": "环境质量", "mechanism": "降噪、净化空气"},
        {"from": "环境质量", "to": "房价", "mechanism": "宜居性溢价"},
    ],
    "alternative_explanations": ["区位选择偏差", "遗漏变量偏误"],
    "limitations": ["横截面数据无法排除逆因果", "匹配变量可能不充分"],
    "suggested_robustness_checks": [
        {"check": "Rosenbaum bounds", "reason": "检验隐藏偏差敏感性", "method": "rbounds R包"},
    ],
    "confidence_assessment": {
        "level": "medium",
        "reasoning": "PSM ATE显著但ATT置信区间较宽",
    },
}, ensure_ascii=False)

_SAMPLE_SCENARIOS_JSON = json.dumps({
    "scenarios": [
        {
            "name": "城市扩张加速",
            "description": "建设用地年增速提升至5%",
            "parameter_modifications": {"建设用地增速": "5%/年"},
            "expected_direction": "negative",
            "expected_magnitude": "large",
            "reasoning": "绿地减少导致PM2.5升高",
            "world_model_scenario": "urban_sprawl",
            "time_horizon": "中期",
        },
        {
            "name": "生态修复",
            "description": "新增城市森林2000公顷",
            "parameter_modifications": {"城市森林面积": "+2000公顷"},
            "expected_direction": "positive",
            "expected_magnitude": "moderate",
            "reasoning": "植被增加吸附颗粒物",
            "world_model_scenario": "ecological_restoration",
            "time_horizon": "长期",
        },
        {
            "name": "维持现状",
            "description": "保持当前城市发展速率不变",
            "parameter_modifications": {},
            "expected_direction": "neutral",
            "expected_magnitude": "small",
            "reasoning": "无显著变化",
            "world_model_scenario": "baseline",
            "time_horizon": "短期",
        },
    ],
}, ensure_ascii=False)


# ===================================================================
#  Test 1: construct_causal_dag
# ===================================================================

class TestConstructCausalDAG(unittest.TestCase):
    """Tests for ``construct_causal_dag``."""

    @patch("data_agent.llm_causal._render_dag_plot", return_value="/tmp/fake_dag.png")
    @patch("data_agent.llm_causal._client")
    def test_basic_dag(self, mock_client, _mock_plot):
        """Valid DAG response: nodes, edges, dag_plot_path, mermaid_diagram."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_DAG_JSON}\n```"
        )

        from data_agent.llm_causal import construct_causal_dag
        result = json.loads(construct_causal_dag(
            question="城市绿地面积对PM2.5浓度的因果影响",
            domain="urban_geography",
        ))

        self.assertEqual(result["status"], "success")
        self.assertGreater(len(result["nodes"]), 0)
        self.assertGreater(len(result["edges"]), 0)
        self.assertIn("dag_plot_path", result)
        self.assertIn("mermaid_diagram", result)
        self.assertTrue(result["mermaid_diagram"].startswith("graph TD"))
        # Verify classified node types
        self.assertIsInstance(result["confounders"], list)
        self.assertIn("人口密度", result["confounders"])
        self.assertIsInstance(result["mediators"], list)
        self.assertIn("植被净化效应", result["mediators"])
        # Token usage propagated
        self.assertIn("token_usage", result)
        self.assertEqual(result["token_usage"]["input_tokens"], 100)
        self.assertEqual(result["token_usage"]["output_tokens"], 200)

    @patch("data_agent.llm_causal._render_dag_plot", return_value="/tmp/fake_dag.png")
    @patch("data_agent.llm_causal._client")
    def test_dag_with_context_file(self, mock_client, _mock_plot):
        """When context_file is provided, data summary appears in the prompt."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_DAG_JSON}\n```"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_data.csv")
            import pandas as pd
            df = pd.DataFrame({
                "green_area": [100, 200, 300],
                "pm25": [35.0, 28.0, 22.0],
                "population": [5000, 8000, 12000],
            })
            df.to_csv(csv_path, index=False)

            with patch("data_agent.llm_causal._resolve_path", return_value=csv_path):
                from data_agent.llm_causal import construct_causal_dag
                result = json.loads(construct_causal_dag(
                    question="绿地对PM2.5的影响",
                    context_file=csv_path,
                ))

            self.assertEqual(result["status"], "success")

            # Verify data summary was included in the prompt
            call_args = mock_client.models.generate_content.call_args
            prompt_text = call_args.kwargs.get("contents") or call_args[1].get("contents") or call_args[0][1] if len(call_args[0]) > 1 else ""
            # The prompt is passed as 'contents' keyword; extract it
            # call signature: _client.models.generate_content(model=..., contents=prompt, config=...)
            actual_prompt = call_args.kwargs.get("contents", "")
            if not actual_prompt and call_args.args:
                actual_prompt = str(call_args.args)
            self.assertIn("green_area", str(actual_prompt) + str(call_args))

    @patch("data_agent.llm_causal._client")
    def test_dag_error_handling(self, mock_client):
        """When LLM raises an exception, return JSON with status=error."""
        mock_client.models.generate_content.side_effect = RuntimeError("API quota exceeded")

        from data_agent.llm_causal import construct_causal_dag
        result = json.loads(construct_causal_dag(
            question="测试错误处理",
        ))

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        self.assertIn("API quota exceeded", result["error"])

    @patch("data_agent.llm_causal._render_dag_plot", return_value="/tmp/fake_dag.png")
    @patch("data_agent.llm_causal._client")
    def test_dag_geofm_flag(self, mock_client, _mock_plot):
        """use_geofm_embedding flag is passed through to result."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_DAG_JSON}\n```"
        )

        from data_agent.llm_causal import construct_causal_dag
        result = json.loads(construct_causal_dag(
            question="绿地面积与NDVI",
            use_geofm_embedding=True,
        ))

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["use_geofm_embedding"])


# ===================================================================
#  Test 2: counterfactual_reasoning
# ===================================================================

class TestCounterfactualReasoning(unittest.TestCase):
    """Tests for ``counterfactual_reasoning``."""

    @patch("data_agent.llm_causal._render_counterfactual_chain", return_value="/tmp/fake_chain.png")
    @patch("data_agent.llm_causal._client")
    def test_basic_counterfactual(self, mock_client, _mock_chain_plot):
        """Valid counterfactual chain: chain, estimated_effect, chain_plot_path."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_COUNTERFACTUAL_JSON}\n```"
        )

        from data_agent.llm_causal import counterfactual_reasoning
        result = json.loads(counterfactual_reasoning(
            question="如果2010年没有实施退耕还林政策,黄土高原植被覆盖会如何变化?",
            treatment_description="退耕还林政策",
        ))

        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["counterfactual_chain"], list)
        self.assertEqual(len(result["counterfactual_chain"]), 3)
        self.assertEqual(result["n_steps"], 3)
        self.assertIn("estimated_effect", result)
        self.assertEqual(result["estimated_effect"]["direction"], "positive")
        self.assertEqual(result["estimated_effect"]["magnitude"], "large")
        self.assertIn("chain_plot_path", result)
        self.assertEqual(result["confidence"], "high")
        self.assertIsInstance(result["key_assumptions"], list)
        self.assertGreater(len(result["key_assumptions"]), 0)

    @patch("data_agent.llm_causal._render_counterfactual_chain", return_value="/tmp/fake_chain.png")
    @patch("data_agent.llm_causal._client")
    def test_with_spatial_context(self, mock_client, _mock_chain_plot):
        """spatial_context appears in the prompt sent to Gemini."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_COUNTERFACTUAL_JSON}\n```"
        )

        from data_agent.llm_causal import counterfactual_reasoning
        result = json.loads(counterfactual_reasoning(
            question="如果增加城市绿地面积,PM2.5如何变化?",
            spatial_context="上海松江区",
        ))

        self.assertEqual(result["status"], "success")

        # Verify spatial context was included in the prompt
        call_args = mock_client.models.generate_content.call_args
        prompt_sent = str(call_args)
        self.assertIn("上海松江区", prompt_sent)

    @patch("data_agent.llm_causal._render_counterfactual_chain", return_value="/tmp/fake_chain.png")
    @patch("data_agent.llm_causal._client")
    def test_with_time_range(self, mock_client, _mock_chain_plot):
        """time_range appears in the prompt sent to Gemini."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_COUNTERFACTUAL_JSON}\n```"
        )

        from data_agent.llm_causal import counterfactual_reasoning
        result = json.loads(counterfactual_reasoning(
            question="退耕还林效果",
            time_range="2010-2023",
        ))

        self.assertEqual(result["status"], "success")
        call_args = mock_client.models.generate_content.call_args
        self.assertIn("2010-2023", str(call_args))


# ===================================================================
#  Test 3: explain_causal_mechanism
# ===================================================================

class TestExplainCausalMechanism(unittest.TestCase):
    """Tests for ``explain_causal_mechanism``."""

    @patch("data_agent.llm_causal._client")
    def test_psm_explanation(self, mock_client):
        """Feed a PSM result JSON, verify mechanism_explanation and causal_pathway."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_MECHANISM_JSON}\n```"
        )

        psm_result = json.dumps({
            "status": "ok",
            "ate": 15000,
            "att": 14500,
            "ci_lower": 12000,
            "ci_upper": 17000,
            "method": "psm",
        })

        from data_agent.llm_causal import explain_causal_mechanism
        result = json.loads(explain_causal_mechanism(
            statistical_result=psm_result,
            method_name="PSM",
            question="城市绿地对房价的因果效应",
            domain="urban_geography",
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_method"], "PSM")
        self.assertIn("mechanism_explanation", result)
        self.assertTrue(len(result["mechanism_explanation"]) > 0)
        self.assertIsInstance(result["causal_pathway"], list)
        self.assertGreater(len(result["causal_pathway"]), 0)
        # Each pathway entry has from/to/mechanism
        for p in result["causal_pathway"]:
            self.assertIn("from", p)
            self.assertIn("to", p)
            self.assertIn("mechanism", p)
        self.assertIsInstance(result["alternative_explanations"], list)
        self.assertIsInstance(result["limitations"], list)
        self.assertIsInstance(result["suggested_robustness_checks"], list)
        self.assertIn("confidence_assessment", result)
        self.assertIn("level", result["confidence_assessment"])

    @patch("data_agent.llm_causal._client")
    def test_did_explanation(self, mock_client):
        """Feed a DiD result JSON, verify similar structure."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_MECHANISM_JSON}\n```"
        )

        did_result = json.dumps({
            "status": "ok",
            "coefficient": -8.2,
            "p_value": 0.003,
            "method": "did",
            "effect_direction": "negative",
        })

        from data_agent.llm_causal import explain_causal_mechanism
        result = json.loads(explain_causal_mechanism(
            statistical_result=did_result,
            method_name="DiD",
            question="限行政策对PM2.5的效应",
            domain="climate",
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_method"], "DiD")
        self.assertIn("mechanism_explanation", result)
        self.assertIn("causal_pathway", result)
        self.assertIn("token_usage", result)

    @patch("data_agent.llm_causal._client")
    def test_auto_detect_method(self, mock_client):
        """When method_name is empty, auto-detect from statistical_result."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_MECHANISM_JSON}\n```"
        )

        granger_result = json.dumps({
            "status": "ok",
            "method": "granger",
            "granger_f_stat": 5.67,
            "p_value": 0.02,
        })

        from data_agent.llm_causal import explain_causal_mechanism
        result = json.loads(explain_causal_mechanism(
            statistical_result=granger_result,
            method_name="",  # empty — should auto-detect
            question="NDVI与降水的因果关系",
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_method"], "granger")

    @patch("data_agent.llm_causal._client")
    def test_mechanism_error_handling(self, mock_client):
        """LLM failure returns status=error."""
        mock_client.models.generate_content.side_effect = ConnectionError("timeout")

        from data_agent.llm_causal import explain_causal_mechanism
        result = json.loads(explain_causal_mechanism(
            statistical_result='{"method":"psm","ate":100}',
            method_name="PSM",
        ))

        self.assertEqual(result["status"], "error")
        self.assertIn("timeout", result["error"])


# ===================================================================
#  Test 4: generate_what_if_scenarios
# ===================================================================

class TestGenerateScenarios(unittest.TestCase):
    """Tests for ``generate_what_if_scenarios``."""

    @patch("data_agent.llm_causal._client")
    def test_basic_scenarios(self, mock_client):
        """Mock LLM returning 3 scenarios, verify structure."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_SCENARIOS_JSON}\n```"
        )

        from data_agent.llm_causal import generate_what_if_scenarios
        result = json.loads(generate_what_if_scenarios(
            base_context="上海市松江区城市发展现状",
            n_scenarios=3,
            target_variable="PM2.5浓度",
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["n_generated"], 3)
        self.assertEqual(result["target_variable"], "PM2.5浓度")
        self.assertIsInstance(result["scenarios"], list)
        self.assertEqual(len(result["scenarios"]), 3)

        for scenario in result["scenarios"]:
            self.assertIn("name", scenario)
            self.assertIn("description", scenario)
            self.assertIn("world_model_scenario", scenario)
            self.assertIn(scenario["world_model_scenario"], {
                "urban_sprawl", "ecological_restoration",
                "agricultural_intensification", "climate_adaptation", "baseline",
            })

    @patch("data_agent.llm_causal._client")
    def test_scenario_constraint(self, mock_client):
        """constraint appears in the prompt sent to Gemini."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_SCENARIOS_JSON}\n```"
        )

        from data_agent.llm_causal import generate_what_if_scenarios
        result = json.loads(generate_what_if_scenarios(
            base_context="黄土高原退耕还林",
            target_variable="植被覆盖率",
            constraint="保持耕地面积不减少",
        ))

        self.assertEqual(result["status"], "success")
        call_args = mock_client.models.generate_content.call_args
        self.assertIn("保持耕地面积不减少", str(call_args))

    @patch("data_agent.llm_causal._client")
    def test_scenario_n_clamped(self, mock_client):
        """n_scenarios is clamped to [1, 8]."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{_SAMPLE_SCENARIOS_JSON}\n```"
        )

        from data_agent.llm_causal import generate_what_if_scenarios

        # Request 20 — should be clamped to 8
        result = json.loads(generate_what_if_scenarios(
            base_context="测试",
            n_scenarios=20,
            target_variable="X",
        ))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["n_requested"], 8)

        # Request 0 — should be clamped to 1
        result = json.loads(generate_what_if_scenarios(
            base_context="测试",
            n_scenarios=0,
            target_variable="X",
        ))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["n_requested"], 1)

    @patch("data_agent.llm_causal._client")
    def test_invalid_world_model_scenario_corrected(self, mock_client):
        """Invalid world_model_scenario values are corrected to 'baseline'."""
        bad_scenarios = json.dumps({
            "scenarios": [
                {
                    "name": "test",
                    "description": "desc",
                    "parameter_modifications": {},
                    "expected_direction": "positive",
                    "expected_magnitude": "small",
                    "reasoning": "test",
                    "world_model_scenario": "INVALID_VALUE",
                    "time_horizon": "短期",
                },
            ]
        })
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            f"```json\n{bad_scenarios}\n```"
        )

        from data_agent.llm_causal import generate_what_if_scenarios
        result = json.loads(generate_what_if_scenarios(
            base_context="test", target_variable="X",
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scenarios"][0]["world_model_scenario"], "baseline")


# ===================================================================
#  Test 5: LLMCausalToolset
# ===================================================================

class TestLLMCausalToolset(unittest.TestCase):
    """Tests for the ADK toolset wrapper."""

    @patch("data_agent.llm_causal._client", new_callable=MagicMock)
    def test_toolset_registration(self, _mock_client):
        """Instantiate toolset and verify 4 tools returned."""
        import asyncio
        from data_agent.toolsets.llm_causal_tools import LLMCausalToolset

        toolset = LLMCausalToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        self.assertEqual(len(tools), 4)

    @patch("data_agent.llm_causal._client", new_callable=MagicMock)
    def test_tool_names(self, _mock_client):
        """Tool function names match the expected set."""
        import asyncio
        from data_agent.toolsets.llm_causal_tools import LLMCausalToolset

        toolset = LLMCausalToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        names = {t.name for t in tools}

        expected = {
            "construct_causal_dag",
            "counterfactual_reasoning",
            "explain_causal_mechanism",
            "generate_what_if_scenarios",
        }
        self.assertEqual(names, expected)


# ===================================================================
#  Test 6: _parse_llm_json helper
# ===================================================================

class TestHelpers(unittest.TestCase):
    """Tests for ``_parse_llm_json`` internal helper."""

    def test_parse_llm_json_fenced(self):
        """Parse JSON wrapped in ```json ... ``` fences."""
        from data_agent.llm_causal import _parse_llm_json

        text = '这是LLM输出\n```json\n{"key": "value", "n": 42}\n```\n后续文本'
        result = _parse_llm_json(text)
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["n"], 42)

    def test_parse_llm_json_fenced_no_lang_tag(self):
        """Parse JSON wrapped in ``` ... ``` fences (no json tag)."""
        from data_agent.llm_causal import _parse_llm_json

        text = '```\n{"a": 1}\n```'
        result = _parse_llm_json(text)
        self.assertEqual(result["a"], 1)

    def test_parse_llm_json_xml_tags(self):
        """Parse JSON wrapped in <json>...</json> tags."""
        from data_agent.llm_causal import _parse_llm_json

        text = '解释部分\n<json>{"nodes": [1, 2, 3]}</json>\n结尾'
        result = _parse_llm_json(text)
        self.assertEqual(result["nodes"], [1, 2, 3])

    def test_parse_llm_json_raw(self):
        """Parse raw JSON string without wrappers."""
        from data_agent.llm_causal import _parse_llm_json

        text = '{"status": "ok", "data": [1, 2]}'
        result = _parse_llm_json(text)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], [1, 2])

    def test_parse_llm_json_raw_with_surrounding_text(self):
        """Parse JSON embedded in surrounding text without fences."""
        from data_agent.llm_causal import _parse_llm_json

        text = '分析结果如下 {"result": true, "count": 5} 以上是分析结果'
        result = _parse_llm_json(text)
        self.assertTrue(result["result"])
        self.assertEqual(result["count"], 5)

    def test_parse_llm_json_invalid(self):
        """Non-JSON string raises ValueError."""
        from data_agent.llm_causal import _parse_llm_json

        with self.assertRaises(ValueError):
            _parse_llm_json("这段文本没有任何JSON内容")

    def test_parse_llm_json_invalid_no_braces(self):
        """String without braces raises ValueError."""
        from data_agent.llm_causal import _parse_llm_json

        with self.assertRaises(ValueError):
            _parse_llm_json("plain text with no json at all")


# ===================================================================
#  Test 7: _nodes_to_mermaid helper
# ===================================================================

class TestMermaidGeneration(unittest.TestCase):
    """Tests for ``_nodes_to_mermaid`` diagram generation."""

    def test_basic_mermaid(self):
        """Generate Mermaid diagram from simple nodes/edges."""
        from data_agent.llm_causal import _nodes_to_mermaid

        nodes = [
            {"name": "X", "type": "exposure"},
            {"name": "Y", "type": "outcome"},
            {"name": "Z", "type": "confounder"},
        ]
        edges = [
            {"from": "X", "to": "Y", "mechanism": "直接效应"},
            {"from": "Z", "to": "X", "mechanism": "混淆"},
            {"from": "Z", "to": "Y", "mechanism": "混淆"},
        ]

        mermaid = _nodes_to_mermaid(nodes, edges)

        self.assertIn("graph TD", mermaid)
        # All nodes present
        self.assertIn('"X"', mermaid)
        self.assertIn('"Y"', mermaid)
        self.assertIn('"Z"', mermaid)
        # Edges present with mechanism labels
        self.assertIn("-->|直接效应|", mermaid)

    def test_mermaid_empty(self):
        """Empty nodes/edges produce minimal diagram."""
        from data_agent.llm_causal import _nodes_to_mermaid

        mermaid = _nodes_to_mermaid([], [])
        self.assertIn("graph TD", mermaid)

    def test_mermaid_long_mechanism_truncated(self):
        """Mechanism text longer than 15 chars is truncated."""
        from data_agent.llm_causal import _nodes_to_mermaid

        nodes = [{"name": "A", "type": "exposure"}, {"name": "B", "type": "outcome"}]
        edges = [{"from": "A", "to": "B", "mechanism": "这是一个非常非常长的因果机制描述文本"}]

        mermaid = _nodes_to_mermaid(nodes, edges)
        # Should contain truncated text with "..."
        self.assertIn("...", mermaid)


# ===================================================================
#  Test 8: _call_gemini helper
# ===================================================================

class TestCallGemini(unittest.TestCase):
    """Tests for ``_call_gemini`` helper."""

    @patch("data_agent.llm_causal._client")
    def test_call_returns_text_and_usage(self, mock_client):
        """_call_gemini returns (text, usage_dict) tuple."""
        mock_client.models.generate_content.return_value = _mock_gemini_response(
            "test response text", prompt_tokens=50, candidates_tokens=80
        )

        from data_agent.llm_causal import _call_gemini
        text, usage = _call_gemini("gemini-2.5-flash", "test prompt")

        self.assertEqual(text, "test response text")
        self.assertEqual(usage["input_tokens"], 50)
        self.assertEqual(usage["output_tokens"], 80)

    @patch("data_agent.llm_causal._client")
    def test_call_no_usage_metadata(self, mock_client):
        """When usage_metadata is None, usage dict is empty."""
        resp = MagicMock()
        resp.text = "response"
        resp.usage_metadata = None

        mock_client.models.generate_content.return_value = resp

        from data_agent.llm_causal import _call_gemini
        text, usage = _call_gemini("gemini-2.5-flash", "test")

        self.assertEqual(text, "response")
        self.assertEqual(usage, {})

    @patch("data_agent.llm_causal._client")
    def test_call_none_text(self, mock_client):
        """When response.text is None, return empty string."""
        resp = MagicMock()
        resp.text = None
        resp.usage_metadata = None

        mock_client.models.generate_content.return_value = resp

        from data_agent.llm_causal import _call_gemini
        text, usage = _call_gemini("gemini-2.5-flash", "test")

        self.assertEqual(text, "")


# ===================================================================
#  Test 9: DAG rendering (mocked matplotlib I/O)
# ===================================================================

class TestDAGRendering(unittest.TestCase):
    """Test ``_render_dag_plot`` produces a PNG file."""

    @patch("data_agent.llm_causal._generate_output_path")
    @patch("data_agent.llm_causal._configure_fonts")
    def test_render_dag_creates_png(self, _mock_fonts, mock_gen_path):
        """_render_dag_plot writes a PNG file to the generated path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test_dag.png")
            mock_gen_path.return_value = out_path

            from data_agent.llm_causal import _render_dag_plot

            nodes = [
                {"name": "A", "type": "exposure"},
                {"name": "B", "type": "outcome"},
                {"name": "C", "type": "confounder"},
            ]
            edges = [
                {"from": "A", "to": "B", "mechanism": "direct"},
                {"from": "C", "to": "A", "mechanism": "confound"},
                {"from": "C", "to": "B", "mechanism": "confound"},
            ]

            result_path = _render_dag_plot(nodes, edges)

            self.assertEqual(result_path, out_path)
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)

    @patch("data_agent.llm_causal._generate_output_path")
    @patch("data_agent.llm_causal._configure_fonts")
    def test_render_counterfactual_chain_creates_png(self, _mock_fonts, mock_gen_path):
        """_render_counterfactual_chain writes a PNG file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test_chain.png")
            mock_gen_path.return_value = out_path

            from data_agent.llm_causal import _render_counterfactual_chain

            chain = [
                {"step": 1, "cause": "政策", "effect": "退耕", "mechanism": "激励", "time_lag": "1年"},
                {"step": 2, "cause": "退耕", "effect": "绿化", "mechanism": "自然恢复", "time_lag": "3年"},
            ]

            result_path = _render_counterfactual_chain(chain)

            self.assertEqual(result_path, out_path)
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)

    def test_render_counterfactual_empty_chain(self):
        """Empty chain returns empty string, no file."""
        from data_agent.llm_causal import _render_counterfactual_chain

        result = _render_counterfactual_chain([])
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
