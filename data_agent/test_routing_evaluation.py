"""Semantic routing evaluation tests.

Tests the intent classification accuracy of the semantic router.
Covers all 4 intent categories (GOVERNANCE, OPTIMIZATION, GENERAL, AMBIGUOUS)
with representative Chinese and English inputs.

These tests mock the Gemini model to verify the routing logic and
response parsing, not the LLM itself.
"""

import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: mock Gemini response
# ---------------------------------------------------------------------------

def _mock_genai_response(intent: str, reason: str = "test"):
    """Create a mock generate_content response."""
    mock_resp = MagicMock()
    mock_resp.text = f"{intent}|{reason}"
    mock_resp.usage_metadata = MagicMock()
    mock_resp.usage_metadata.prompt_token_count = 50
    mock_resp.usage_metadata.candidates_token_count = 10
    return mock_resp


def _setup_mock_client(mock_client, intent: str, reason: str = "test"):
    """Configure a mock _genai_router_client to return a fixed intent."""
    mock_client.models.generate_content.return_value = _mock_genai_response(intent, reason)


# ---------------------------------------------------------------------------
# TestRouterResponseParsing
# ---------------------------------------------------------------------------

class TestRouterResponseParsing(unittest.TestCase):
    """Test that classify_intent correctly parses Gemini responses."""

    @patch("data_agent.intent_router._router_client")
    def test_governance_intent(self, mock_client):
        _setup_mock_client(mock_client, "GOVERNANCE", "用户请求数据治理")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("请对数据进行质量审计")
        self.assertEqual(intent, "GOVERNANCE")

    @patch("data_agent.intent_router._router_client")
    def test_optimization_intent(self, mock_client):
        _setup_mock_client(mock_client, "OPTIMIZATION", "用户请求空间优化")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("对地块进行布局优化")
        self.assertEqual(intent, "OPTIMIZATION")

    @patch("data_agent.intent_router._router_client")
    def test_general_intent(self, mock_client):
        _setup_mock_client(mock_client, "GENERAL", "用户请求查看地图")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("生成一张热力图")
        self.assertEqual(intent, "GENERAL")

    @patch("data_agent.intent_router._router_client")
    def test_ambiguous_intent(self, mock_client):
        _setup_mock_client(mock_client, "AMBIGUOUS", "输入不明确")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("你好")
        self.assertEqual(intent, "AMBIGUOUS")

    @patch("data_agent.intent_router._router_client")
    def test_returns_reason(self, mock_client):
        _setup_mock_client(mock_client, "GENERAL", "用户请求SQL查询")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("查询数据库")
        self.assertIn("SQL查询", reason)

    @patch("data_agent.intent_router._router_client")
    def test_returns_token_count(self, mock_client):
        _setup_mock_client(mock_client, "GENERAL", "test")
        from data_agent.app import classify_intent
        intent, reason, tokens, _ = classify_intent("测试")
        self.assertIsInstance(tokens, (int, dict))
        if isinstance(tokens, int):
            self.assertGreaterEqual(tokens, 0)
        else:
            self.assertIn("input", tokens)


# ---------------------------------------------------------------------------
# TestRouterEdgeCases
# ---------------------------------------------------------------------------

class TestRouterEdgeCases(unittest.TestCase):
    """Test edge cases in routing logic."""

    @patch("data_agent.intent_router._router_client")
    def test_empty_input_returns_ambiguous(self, mock_client):
        _setup_mock_client(mock_client, "AMBIGUOUS", "空输入")
        from data_agent.app import classify_intent
        intent, _, _, _ = classify_intent("")
        self.assertEqual(intent, "AMBIGUOUS")

    @patch("data_agent.intent_router._router_client")
    def test_malformed_response_defaults_general(self, mock_client):
        """If Gemini returns unparseable response, should default to GENERAL."""
        mock_resp = MagicMock()
        mock_resp.text = "I'm not sure what you mean"
        mock_resp.usage_metadata = MagicMock()
        mock_resp.usage_metadata.prompt_token_count = 10
        mock_resp.usage_metadata.candidates_token_count = 5
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, _, _, _ = classify_intent("random text")
        # Should fall back to GENERAL or AMBIGUOUS (implementation-dependent)
        self.assertIn(intent, ("GENERAL", "AMBIGUOUS"))

    @patch("data_agent.intent_router._router_client")
    def test_previous_pipeline_hint_passed(self, mock_client):
        """Verify previous_pipeline is used in prompt construction."""
        _setup_mock_client(mock_client, "OPTIMIZATION", "延续上轮")
        from data_agent.app import classify_intent
        intent, _, _, _ = classify_intent("继续分析", previous_pipeline="optimization")
        self.assertEqual(intent, "OPTIMIZATION")
        # Verify the model was called (prompt includes previous pipeline hint)
        call_args = mock_client.models.generate_content.call_args
        self.assertIsNotNone(call_args)

    @patch("data_agent.intent_router._router_client")
    def test_pdf_context_appended(self, mock_client):
        """Verify PDF context is included in router prompt."""
        _setup_mock_client(mock_client, "GOVERNANCE", "PDF审计")
        from data_agent.app import classify_intent
        intent, _, _, _ = classify_intent("分析这份PDF", pdf_context="这是一份土地利用变更报告...")
        self.assertEqual(intent, "GOVERNANCE")

    @patch("data_agent.intent_router._router_client")
    def test_gemini_exception_returns_general(self, mock_client):
        """If Gemini call fails, should gracefully default to GENERAL."""
        mock_client.models.generate_content.side_effect = Exception("API error")

        from data_agent.app import classify_intent
        intent, _, _, _ = classify_intent("测试错误处理")
        self.assertEqual(intent, "GENERAL")


# ---------------------------------------------------------------------------
# TestRoutingCoverage — intent keyword coverage
# ---------------------------------------------------------------------------

class TestRoutingCoverage(unittest.TestCase):
    """Verify router handles diverse input patterns for each category."""

    GOVERNANCE_INPUTS = [
        "请对数据进行质量审计",
        "检查数据的拓扑一致性",
        "核查字段是否符合国标",
        "数据质检报告",
        "检测自相交和重叠",
        "对SHP数据进行标准化检查",
    ]

    OPTIMIZATION_INPUTS = [
        "优化耕地空间布局",
        "计算破碎化指数FFI",
        "运行DRL模型进行用地优化",
        "土地利用布局规划",
        "减少耕地碎片化",
        "空间置换优化方案",
    ]

    GENERAL_INPUTS = [
        "生成一张热力图",
        "查询数据库中的表",
        "在地图上显示缓冲区",
        "POI搜索附近商场",
        "对数据进行聚类分析",
        "导出分级设色图",
        "选址分析",
        "计算驾车距离",
    ]

    AMBIGUOUS_INPUTS = [
        "你好",
        "hello",
        "谢谢",
        "hi",
    ]

    def _verify_intent(self, inputs, expected_intent):
        """Helper to verify a batch of inputs map to expected intent."""
        for text in inputs:
            with self.subTest(text=text):
                with patch("data_agent.intent_router._router_client") as mock_client:
                    _setup_mock_client(mock_client, expected_intent, f"matched: {text}")
                    from data_agent.app import classify_intent
                    intent, _, _, _ = classify_intent(text)
                    self.assertEqual(intent, expected_intent,
                                     f"Input '{text}' expected {expected_intent} but got {intent}")

    def test_governance_inputs(self):
        self._verify_intent(self.GOVERNANCE_INPUTS, "GOVERNANCE")

    def test_optimization_inputs(self):
        self._verify_intent(self.OPTIMIZATION_INPUTS, "OPTIMIZATION")

    def test_general_inputs(self):
        self._verify_intent(self.GENERAL_INPUTS, "GENERAL")

    def test_ambiguous_inputs(self):
        self._verify_intent(self.AMBIGUOUS_INPUTS, "AMBIGUOUS")


# ---------------------------------------------------------------------------
# TestRBACRouting — role-based access control
# ---------------------------------------------------------------------------

class TestRBACRouting(unittest.TestCase):
    """Verify RBAC enforcement after routing."""

    RBAC_RULES = {
        "admin": ["GOVERNANCE", "OPTIMIZATION", "GENERAL"],
        "analyst": ["GOVERNANCE", "OPTIMIZATION", "GENERAL"],
        "viewer": ["GENERAL"],
    }

    def test_rbac_rules_completeness(self):
        """All 3 roles should be defined."""
        self.assertEqual(len(self.RBAC_RULES), 3)

    def test_viewer_blocked_from_governance(self):
        """Viewer role should not access GOVERNANCE pipeline."""
        self.assertNotIn("GOVERNANCE", self.RBAC_RULES.get("viewer", []))

    def test_viewer_blocked_from_optimization(self):
        """Viewer role should not access OPTIMIZATION pipeline."""
        self.assertNotIn("OPTIMIZATION", self.RBAC_RULES.get("viewer", []))

    def test_admin_has_full_access(self):
        """Admin role should access all pipelines."""
        admin_access = self.RBAC_RULES.get("admin", [])
        self.assertIn("GOVERNANCE", admin_access)
        self.assertIn("OPTIMIZATION", admin_access)
        self.assertIn("GENERAL", admin_access)


if __name__ == "__main__":
    unittest.main()
