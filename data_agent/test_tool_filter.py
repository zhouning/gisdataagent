"""
Tests for dynamic tool filtering (v7.5.6).
Tests IntentToolPredicate, TOOL_CATEGORIES, and integration with ContextVar.
"""
import unittest
from unittest.mock import MagicMock, patch
from contextvars import copy_context

from data_agent.tool_filter import (
    IntentToolPredicate, CORE_TOOLS, TOOL_CATEGORIES, VALID_CATEGORIES,
    intent_tool_predicate,
)
from data_agent.user_context import current_tool_categories


def _mock_tool(name: str) -> MagicMock:
    """Create a mock BaseTool with the given name."""
    t = MagicMock()
    t.name = name
    return t


class TestIntentToolPredicate(unittest.TestCase):
    """Test the IntentToolPredicate callable."""

    def setUp(self):
        self.pred = IntentToolPredicate()
        # Reset ContextVar to default (empty set) before each test
        current_tool_categories.set(set())

    def tearDown(self):
        # Always reset to prevent leaking into subsequent tests
        current_tool_categories.set(set())

    def test_no_categories_allows_all(self):
        """Empty categories → no filtering, all tools pass."""
        current_tool_categories.set(set())
        self.assertTrue(self.pred(_mock_tool("create_buffer")))
        self.assertTrue(self.pred(_mock_tool("create_iot_stream")))
        self.assertTrue(self.pred(_mock_tool("nonexistent_tool")))

    def test_core_always_pass(self):
        """Core tools pass regardless of active categories."""
        current_tool_categories.set({"streaming_iot"})
        for name in CORE_TOOLS:
            self.assertTrue(self.pred(_mock_tool(name)), f"Core tool {name} should pass")

    def test_spatial_allows_matching(self):
        """spatial_processing category allows matching tools."""
        current_tool_categories.set({"spatial_processing"})
        self.assertTrue(self.pred(_mock_tool("create_buffer")))
        self.assertTrue(self.pred(_mock_tool("perform_clustering")))
        self.assertTrue(self.pred(_mock_tool("batch_geocode")))

    def test_spatial_blocks_unmatched(self):
        """spatial_processing blocks tools from other categories."""
        current_tool_categories.set({"spatial_processing"})
        self.assertFalse(self.pred(_mock_tool("create_iot_stream")))
        self.assertFalse(self.pred(_mock_tool("build_knowledge_graph")))
        self.assertFalse(self.pred(_mock_tool("create_team")))

    def test_multiple_categories_union(self):
        """Multiple categories allow union of their tools."""
        current_tool_categories.set({"poi_location", "remote_sensing"})
        self.assertTrue(self.pred(_mock_tool("search_nearby_poi")))
        self.assertTrue(self.pred(_mock_tool("download_dem")))
        self.assertFalse(self.pred(_mock_tool("create_iot_stream")))
        self.assertFalse(self.pred(_mock_tool("create_team")))

    def test_unknown_category_ignored(self):
        """Unknown category names don't crash, just allow core only."""
        current_tool_categories.set({"nonexistent_category"})
        self.assertTrue(self.pred(_mock_tool("query_database")))  # core
        self.assertFalse(self.pred(_mock_tool("create_buffer")))  # not core, not in unknown cat

    def test_singleton_works(self):
        """Module-level singleton behaves identically."""
        current_tool_categories.set({"remote_sensing"})
        self.assertTrue(intent_tool_predicate(_mock_tool("download_lulc")))
        self.assertFalse(intent_tool_predicate(_mock_tool("create_team")))

    def test_readonly_context_ignored(self):
        """readonly_context parameter is accepted but not used."""
        current_tool_categories.set({"spatial_processing"})
        self.assertTrue(self.pred(_mock_tool("create_buffer"), readonly_context=MagicMock()))


class TestToolCategories(unittest.TestCase):
    """Test TOOL_CATEGORIES and CORE_TOOLS definitions."""

    def test_eight_categories_defined(self):
        """Should have exactly 8 categories."""
        self.assertEqual(len(TOOL_CATEGORIES), 8)

    def test_valid_categories_matches(self):
        """VALID_CATEGORIES should match TOOL_CATEGORIES keys."""
        self.assertEqual(VALID_CATEGORIES, frozenset(TOOL_CATEGORIES.keys()))

    def test_expected_categories_exist(self):
        """All expected category names are present."""
        expected = {
            "spatial_processing", "poi_location", "remote_sensing",
            "database_management", "quality_audit", "streaming_iot",
            "collaboration", "advanced_analysis",
        }
        self.assertEqual(set(TOOL_CATEGORIES.keys()), expected)

    def test_categories_are_frozensets(self):
        """Each category value is a frozenset of strings."""
        for cat, tools in TOOL_CATEGORIES.items():
            self.assertIsInstance(tools, frozenset, f"Category {cat}")
            for tool_name in tools:
                self.assertIsInstance(tool_name, str, f"Tool in {cat}")

    def test_core_tools_are_strings(self):
        """CORE_TOOLS contains only strings."""
        for name in CORE_TOOLS:
            self.assertIsInstance(name, str)

    def test_core_has_essential_tools(self):
        """Core tools include essential exploration and DB tools."""
        self.assertIn("describe_geodataframe", CORE_TOOLS)
        self.assertIn("query_database", CORE_TOOLS)
        self.assertIn("list_tables", CORE_TOOLS)

    def test_categories_non_empty(self):
        """Each category has at least one tool."""
        for cat, tools in TOOL_CATEGORIES.items():
            self.assertGreater(len(tools), 0, f"Category {cat} is empty")


class TestClassifyIntentToolCats(unittest.TestCase):
    """Test classify_intent extended return value parsing."""

    @patch("data_agent.intent_router._router_client")
    def test_parses_tools_field(self, mock_client):
        """classify_intent parses TOOLS: field from response."""
        mock_resp = MagicMock()
        mock_resp.text = "GENERAL|缓冲区分析|TOOLS:spatial_processing"
        mock_resp.usage_metadata.prompt_token_count = 50
        mock_resp.usage_metadata.candidates_token_count = 10
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("创建缓冲区")
        self.assertEqual(intent, "GENERAL")
        self.assertEqual(cats, {"spatial_processing"})

    @patch("data_agent.intent_router._router_client")
    def test_multiple_tools(self, mock_client):
        """classify_intent parses multiple tool categories."""
        mock_resp = MagicMock()
        mock_resp.text = "GENERAL|POI和热力图|TOOLS:poi_location,spatial_processing"
        mock_resp.usage_metadata.prompt_token_count = 50
        mock_resp.usage_metadata.candidates_token_count = 10
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("搜索POI并生成热力图")
        self.assertEqual(intent, "GENERAL")
        self.assertEqual(cats, {"poi_location", "spatial_processing"})

    @patch("data_agent.intent_router._router_client")
    def test_tools_all_returns_empty(self, mock_client):
        """TOOLS:all returns empty set (no filtering)."""
        mock_resp = MagicMock()
        mock_resp.text = "AMBIGUOUS|不确定|TOOLS:all"
        mock_resp.usage_metadata.prompt_token_count = 50
        mock_resp.usage_metadata.candidates_token_count = 10
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("你好")
        self.assertEqual(intent, "AMBIGUOUS")
        self.assertEqual(cats, set())

    @patch("data_agent.intent_router._router_client")
    def test_no_tools_field_returns_empty(self, mock_client):
        """Old-format response without TOOLS: returns empty set."""
        mock_resp = MagicMock()
        mock_resp.text = "GENERAL|简单查询"
        mock_resp.usage_metadata.prompt_token_count = 50
        mock_resp.usage_metadata.candidates_token_count = 10
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("查看地图")
        self.assertEqual(intent, "GENERAL")
        self.assertEqual(cats, set())

    @patch("data_agent.intent_router._router_client")
    def test_error_returns_empty_cats(self, mock_client):
        """API error returns 4-tuple with empty set."""
        mock_client.models.generate_content.side_effect = Exception("API down")

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("test")
        self.assertEqual(intent, "GENERAL")
        self.assertEqual(cats, set())

    @patch("data_agent.intent_router._router_client")
    def test_governance_with_tools(self, mock_client):
        """GOVERNANCE intent with quality_audit tools."""
        mock_resp = MagicMock()
        mock_resp.text = "GOVERNANCE|数据质检|TOOLS:quality_audit"
        mock_resp.usage_metadata.prompt_token_count = 50
        mock_resp.usage_metadata.candidates_token_count = 10
        mock_client.models.generate_content.return_value = mock_resp

        from data_agent.app import classify_intent
        intent, reason, tokens, cats = classify_intent("检查拓扑")
        self.assertEqual(intent, "GOVERNANCE")
        self.assertEqual(cats, {"quality_audit"})


if __name__ == "__main__":
    unittest.main()
