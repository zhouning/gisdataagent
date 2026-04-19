"""Tests for @SubAgent mention routing."""
import unittest
from unittest.mock import patch, MagicMock


class TestMentionRegistry(unittest.TestCase):
    """Tests for mention_registry.py target aggregation."""

    def test_pipeline_targets_always_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("General", handles)
        self.assertIn("Governance", handles)
        self.assertIn("Optimization", handles)

    def test_pipeline_target_shape(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        general = next(t for t in registry if t["handle"] == "General")
        self.assertEqual(general["type"], "pipeline")
        self.assertIn("allowed_roles", general)
        self.assertIn("description", general)
        self.assertEqual(general["required_state_keys"], [])

    def test_sub_agent_targets_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("DataVisualization", handles)
        self.assertIn("DataProcessing", handles)
        self.assertIn("GovExploration", handles)

    def test_sub_agent_has_required_state(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        viz = next(t for t in registry if t["handle"] == "DataVisualization")
        self.assertEqual(viz["type"], "sub_agent")
        self.assertIn("processed_data", viz["required_state_keys"])

    def test_builtin_skill_targets(self):
        from data_agent.mention_registry import build_registry
        with patch("data_agent.mention_registry.list_builtin_skills", return_value=[
            {"name": "thematic-mapping", "description": "专题图制作", "type": "builtin_skill"},
        ]):
            registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("thematic-mapping", handles)

    @patch("data_agent.mention_registry.list_custom_skills")
    def test_custom_skill_targets(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "skill_name": "SoilExpert", "description": "土壤分析",
             "owner_username": "testuser", "is_shared": False},
        ]
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("SoilExpert", handles)

    def test_lookup_by_handle_case_insensitive(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "general")
        self.assertIsNotNone(result)
        self.assertEqual(result["handle"], "General")

    def test_lookup_unknown_returns_none(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "NonExistentAgent")
        self.assertIsNone(result)

    def test_handle_uniqueness(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = [t["handle"] for t in registry]
        self.assertEqual(len(handles), len(set(h.lower() for h in handles)))


class TestMentionParser(unittest.TestCase):
    """Tests for mention_parser.py leading @handle extraction."""

    def test_leading_mention_extracted(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@DataVisualization 把刚才结果做热力图")
        self.assertEqual(result["handle"], "DataVisualization")
        self.assertEqual(result["remaining"], "把刚才结果做热力图")

    def test_no_mention_returns_none(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("请帮我分析这个数据")
        self.assertIsNone(result)

    def test_non_leading_mention_ignored(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("请帮我 @DataVisualization 画图")
        self.assertIsNone(result)

    def test_mention_with_hyphen(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@thematic-mapping 生成专题图")
        self.assertEqual(result["handle"], "thematic-mapping")
        self.assertEqual(result["remaining"], "生成专题图")

    def test_mention_only_no_text(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@General")
        self.assertEqual(result["handle"], "General")
        self.assertEqual(result["remaining"], "")

    def test_mention_with_extra_spaces(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("  @Governance  检查拓扑错误  ")
        self.assertEqual(result["handle"], "Governance")
        self.assertEqual(result["remaining"], "检查拓扑错误")

    def test_resolve_valid_mention(self):
        from data_agent.mention_parser import parse_mention, resolve_mention
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@General 查询数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertEqual(target["type"], "pipeline")

    def test_resolve_unknown_mention_returns_none(self):
        from data_agent.mention_parser import parse_mention, resolve_mention
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@UnknownAgent 做点什么")
        target = resolve_mention(parsed, registry)
        self.assertIsNone(target)


class TestMentionDispatch(unittest.TestCase):
    """Tests for RBAC enforcement and state validation in mention dispatch."""

    def test_viewer_blocked_from_governance_mention(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="viewer1", role="viewer")
        parsed = parse_mention("@Governance 检查数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertNotIn("viewer", target["allowed_roles"])

    def test_viewer_allowed_general_mention(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="viewer1", role="viewer")
        parsed = parse_mention("@General 查询数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertIn("viewer", target["allowed_roles"])

    def test_sub_agent_state_check_missing(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@DataVisualization 画热力图")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertIn("processed_data", target["required_state_keys"])

    def test_unknown_mention_fallback(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@FakeAgent 做点什么")
        target = resolve_mention(parsed, registry)
        self.assertIsNone(target)


class TestMentionTargetsAPI(unittest.TestCase):
    """Tests for GET /api/chat/mention-targets endpoint."""

    def _run_async(self, coro):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def _make_request(self):
        req = MagicMock()
        req.cookies = {}
        req.query_params = {}
        req.path_params = {}
        req.method = "GET"
        return req

    def _make_user(self, identifier="testuser", role="analyst"):
        user = MagicMock()
        user.identifier = identifier
        user.metadata = {"role": role}
        return user

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mention_targets
        resp = self._run_async(_api_mention_targets(self._make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_returns_targets(self, mock_user):
        mock_user.return_value = self._make_user(role="admin")
        from data_agent.frontend_api import _api_mention_targets
        with patch("data_agent.mention_registry.list_custom_skills", return_value=[]):
            resp = self._run_async(_api_mention_targets(self._make_request()))
        self.assertEqual(resp.status_code, 200)
        import json
        body = json.loads(resp.body)
        self.assertIn("targets", body)
        handles = [t["handle"] for t in body["targets"]]
        self.assertIn("General", handles)
        self.assertIn("DataVisualization", handles)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_viewer_sees_allowed_flag(self, mock_user):
        mock_user.return_value = self._make_user(role="viewer")
        from data_agent.frontend_api import _api_mention_targets
        with patch("data_agent.mention_registry.list_custom_skills", return_value=[]):
            resp = self._run_async(_api_mention_targets(self._make_request()))
        import json
        body = json.loads(resp.body)
        gov = next((t for t in body["targets"] if t["handle"] == "Governance"), None)
        self.assertIsNotNone(gov)
        self.assertFalse(gov["allowed"])
