"""
Tests for Phase 2: Session Persistence + Analysis Explainability.

- TestAsyncDbUrl: Verifies async DB URL construction.
- TestSessionServiceFactory: Verifies _create_session_service() fallback logic.
- TestToolDescriptions: Verifies TOOL_DESCRIPTIONS coverage and structure.
- TestFormatToolExplanation: Verifies human-readable formatting.
"""
import unittest
import os
from unittest.mock import patch
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


class TestAsyncDbUrl(unittest.TestCase):
    """Tests for get_async_db_url() in database_tools.py."""

    def test_returns_asyncpg_url(self):
        from data_agent.database_tools import get_async_db_url
        url = get_async_db_url()
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("postgresql+asyncpg://"))

    def test_preserves_credentials(self):
        from data_agent.database_tools import get_async_db_url, get_db_connection_url
        sync = get_db_connection_url()
        async_url = get_async_db_url()
        # Only the scheme prefix should differ
        self.assertEqual(
            async_url.replace("postgresql+asyncpg://", ""),
            sync.replace("postgresql://", ""),
        )

    @patch.dict(os.environ, {"POSTGRES_USER": "", "POSTGRES_PASSWORD": "", "POSTGRES_DATABASE": ""}, clear=False)
    def test_returns_none_when_no_credentials(self):
        from data_agent.database_tools import get_async_db_url
        self.assertIsNone(get_async_db_url())


class TestSessionServiceFactory(unittest.TestCase):
    """Tests for _create_session_service() fallback behavior."""

    def test_returns_session_service(self):
        """Should return some session service (DB or InMemory)."""
        from data_agent.app import session_service
        self.assertIsNotNone(session_service)

    def test_session_service_has_create_session(self):
        """Session service should have create_session method."""
        from data_agent.app import session_service
        self.assertTrue(hasattr(session_service, 'create_session'))

    def test_session_service_has_get_session(self):
        """Session service should have get_session method."""
        from data_agent.app import session_service
        self.assertTrue(hasattr(session_service, 'get_session'))


class TestToolDescriptions(unittest.TestCase):
    """Tests for TOOL_DESCRIPTIONS coverage and structure."""

    @classmethod
    def setUpClass(cls):
        from data_agent.app import TOOL_DESCRIPTIONS, TOOL_LABELS
        cls.descriptions = TOOL_DESCRIPTIONS
        cls.labels = TOOL_LABELS

    def test_descriptions_not_empty(self):
        self.assertGreater(len(self.descriptions), 30)

    def test_all_entries_have_method(self):
        for name, desc in self.descriptions.items():
            self.assertIn("method", desc, f"{name} missing 'method' key")
            self.assertIsInstance(desc["method"], str, f"{name} 'method' is not str")

    def test_all_entries_have_params(self):
        for name, desc in self.descriptions.items():
            self.assertIn("params", desc, f"{name} missing 'params' key")
            self.assertIsInstance(desc["params"], dict, f"{name} 'params' is not dict")

    def test_core_tools_covered(self):
        """Key tools from all pipelines should have descriptions."""
        required = [
            "describe_geodataframe", "check_topology", "query_database",
            "reproject_spatial_data", "batch_geocode", "perform_clustering",
            "create_buffer", "generate_choropleth", "ffi", "drl_model",
        ]
        for tool in required:
            self.assertIn(tool, self.descriptions, f"Missing description for {tool}")

    def test_method_names_are_chinese(self):
        """All method names should contain Chinese characters."""
        import re
        for name, desc in self.descriptions.items():
            has_chinese = bool(re.search(r'[\u4e00-\u9fff]', desc["method"]))
            self.assertTrue(has_chinese, f"{name} method '{desc['method']}' has no Chinese chars")


class TestFormatToolExplanation(unittest.TestCase):
    """Tests for _format_tool_explanation() output format."""

    @classmethod
    def setUpClass(cls):
        from data_agent.app import _format_tool_explanation
        cls._fmt = staticmethod(_format_tool_explanation)

    def fmt(self, tool_name, args):
        return self._fmt(tool_name, args)

    def test_known_tool_shows_method_name(self):
        result = self.fmt("perform_clustering", {"file_path": "test.shp", "eps": 500})
        self.assertIn("DBSCAN", result)
        self.assertIn("**", result)  # bold marker

    def test_known_tool_shows_param_labels(self):
        result = self.fmt("create_buffer", {"file_path": "test.shp", "distance": 1000})
        self.assertIn("缓冲", result)

    def test_unknown_tool_falls_back_to_raw(self):
        result = self.fmt("unknown_tool_xyz", {"a": 1, "b": 2})
        self.assertIn("a", result)
        self.assertIn("1", result)

    def test_long_path_shortened(self):
        long_path = "D:\\adk\\data_agent\\uploads\\admin\\very_long_filename_test.shp"
        result = self.fmt("describe_geodataframe", {"file_path": long_path})
        # Should show basename, not full path
        self.assertIn("very_long_filename_test.shp", result)
        self.assertNotIn("D:\\adk\\data_agent\\uploads", result)

    def test_long_value_truncated(self):
        huge = "x" * 300
        result = self.fmt("query_database", {"sql_query": huge})
        self.assertLessEqual(len(result), 500)
        self.assertIn("...", result)

    def test_none_args_handled(self):
        result = self.fmt("describe_geodataframe", None)
        self.assertIsInstance(result, str)

    def test_empty_args_handled(self):
        result = self.fmt("describe_geodataframe", {})
        self.assertIn("**", result)  # Should still show method name


if __name__ == "__main__":
    unittest.main()
