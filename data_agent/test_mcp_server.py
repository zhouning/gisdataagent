"""Tests for the MCP Server and Tool Registry."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.mcp_tool_registry import (
    _wrap_tool,
    TOOL_DEFINITIONS,
    register_all_tools,
)


# ---------------------------------------------------------------------------
# TestWrapTool
# ---------------------------------------------------------------------------

class TestWrapTool(unittest.TestCase):
    """Test the _wrap_tool wrapper factory."""

    def test_dict_result_to_json(self):
        def sample() -> dict:
            return {"status": "success", "count": 3}

        wrapped = _wrap_tool(sample)
        result = wrapped()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["count"], 3)

    def test_str_result_passthrough(self):
        def sample() -> str:
            return "/path/to/output.shp"

        wrapped = _wrap_tool(sample)
        result = wrapped()
        self.assertEqual(result, "/path/to/output.shp")

    def test_exception_to_error_json(self):
        def sample():
            raise ValueError("test error")

        wrapped = _wrap_tool(sample)
        result = wrapped()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "error")
        self.assertIn("test error", parsed["message"])

    def test_preserves_name(self):
        def my_tool(x: int) -> str:
            """My docstring."""
            return str(x)

        wrapped = _wrap_tool(my_tool)
        self.assertEqual(wrapped.__name__, "my_tool")
        self.assertEqual(wrapped.__doc__, "My docstring.")

    def test_preserves_input_annotations(self):
        def my_tool(file_path: str, eps: float = 500) -> dict:
            return {"result": file_path}

        wrapped = _wrap_tool(my_tool)
        ann = wrapped.__annotations__
        self.assertEqual(ann.get("file_path"), str)
        self.assertEqual(ann.get("eps"), float)
        # Return type always forced to str (wrapper serializes dicts)
        self.assertEqual(ann.get("return"), str)

    def test_fixes_problematic_return_type(self):
        """dict[str, any] (lowercase any) should be replaced with str."""
        def my_tool(file_path: str) -> dict[str, any]:
            return {"status": "ok"}

        wrapped = _wrap_tool(my_tool)
        self.assertEqual(wrapped.__annotations__["return"], str)

    def test_non_serializable_dict_value(self):
        """dict with non-JSON-serializable values should use default=str."""
        import datetime

        def sample() -> dict:
            return {"time": datetime.datetime(2024, 1, 1)}

        wrapped = _wrap_tool(sample)
        result = wrapped()
        parsed = json.loads(result)
        self.assertIn("2024", parsed["time"])

    def test_args_forwarded(self):
        def sample(a: int, b: str = "x") -> dict:
            return {"a": a, "b": b}

        wrapped = _wrap_tool(sample)
        result = json.loads(wrapped(42, b="y"))
        self.assertEqual(result["a"], 42)
        self.assertEqual(result["b"], "y")


# ---------------------------------------------------------------------------
# TestToolDefinitions
# ---------------------------------------------------------------------------

class TestToolDefinitions(unittest.TestCase):
    """Test TOOL_DEFINITIONS metadata integrity."""

    def test_all_have_required_keys(self):
        for defn in TOOL_DEFINITIONS:
            self.assertIn("name", defn, f"Missing 'name' in {defn}")
            self.assertIn("description", defn, f"Missing 'description' in {defn}")
            self.assertTrue(defn["name"].strip(), "Empty tool name")
            self.assertTrue(defn["description"].strip(), "Empty description")

    def test_no_duplicate_names(self):
        names = [d["name"] for d in TOOL_DEFINITIONS]
        self.assertEqual(len(names), len(set(names)), f"Duplicate names: {names}")

    def test_minimum_tool_count(self):
        self.assertGreaterEqual(len(TOOL_DEFINITIONS), 25)

    def test_annotations_present(self):
        for defn in TOOL_DEFINITIONS:
            ann = defn.get("annotations")
            self.assertIsNotNone(ann, f"No annotations for {defn['name']}")

    def test_categories_covered(self):
        """Ensure tools from all 5 categories are present."""
        names = {d["name"] for d in TOOL_DEFINITIONS}
        # Exploration
        self.assertIn("describe_geodataframe", names)
        # Processing
        self.assertIn("perform_clustering", names)
        # Geocoding
        self.assertIn("batch_geocode", names)
        # Visualization
        self.assertIn("generate_choropleth", names)
        # Database
        self.assertIn("query_database", names)


# ---------------------------------------------------------------------------
# TestRegistration
# ---------------------------------------------------------------------------

class TestRegistration(unittest.TestCase):
    """Test register_all_tools with a mock FastMCP server."""

    @patch("data_agent.mcp_tool_registry._get_tool_functions")
    def test_registers_all_tools(self, mock_get_fns):
        # Provide a fake function for every definition
        fake_fns = {}
        for defn in TOOL_DEFINITIONS:
            fn = MagicMock()
            fn.__name__ = defn["name"]
            fn.__doc__ = "test"
            fn.__annotations__ = {}
            fn.__module__ = "test"
            fn.__qualname__ = defn["name"]
            fn.__wrapped__ = None
            fn.__dict__ = {}
            fake_fns[defn["name"]] = fn
        mock_get_fns.return_value = fake_fns

        mock_server = MagicMock()
        count = register_all_tools(mock_server)

        self.assertEqual(count, len(TOOL_DEFINITIONS))
        self.assertEqual(mock_server.add_tool.call_count, len(TOOL_DEFINITIONS))

    @patch("data_agent.mcp_tool_registry._get_tool_functions")
    def test_skips_missing_function(self, mock_get_fns):
        mock_get_fns.return_value = {}  # No functions available
        mock_server = MagicMock()
        count = register_all_tools(mock_server)
        self.assertEqual(count, 0)
        mock_server.add_tool.assert_not_called()

    @patch("data_agent.mcp_tool_registry._get_tool_functions")
    def test_add_tool_called_with_correct_args(self, mock_get_fns):
        # Just provide one tool
        fn = MagicMock()
        fn.__name__ = "describe_geodataframe"
        fn.__doc__ = "test doc"
        fn.__annotations__ = {"file_path": str, "return": dict}
        fn.__module__ = "test"
        fn.__qualname__ = "describe_geodataframe"
        fn.__wrapped__ = None
        fn.__dict__ = {}
        mock_get_fns.return_value = {"describe_geodataframe": fn}

        mock_server = MagicMock()
        register_all_tools(mock_server)

        call_args = mock_server.add_tool.call_args_list[0]
        self.assertEqual(call_args.kwargs["name"], "describe_geodataframe")
        self.assertIn("数据画像", call_args.kwargs["description"])


# ---------------------------------------------------------------------------
# TestLifespan
# ---------------------------------------------------------------------------

class TestLifespan(unittest.TestCase):
    """Test the MCP server lifespan context manager."""

    def test_sets_context_vars(self):
        from data_agent.mcp_server import gis_lifespan
        from data_agent.user_context import current_user_id, current_session_id, current_user_role

        with patch.dict(os.environ, {"MCP_USER": "test_user", "MCP_ROLE": "admin"}):
            mock_server = MagicMock()
            with gis_lifespan(mock_server):
                self.assertEqual(current_user_id.get(), "test_user")
                self.assertEqual(current_session_id.get(), "mcp_test_user")
                self.assertEqual(current_user_role.get(), "admin")

    def test_default_values(self):
        from data_agent.mcp_server import gis_lifespan
        from data_agent.user_context import current_user_id, current_user_role

        env = {k: v for k, v in os.environ.items() if k not in ("MCP_USER", "MCP_ROLE")}
        with patch.dict(os.environ, env, clear=True):
            mock_server = MagicMock()
            with gis_lifespan(mock_server):
                self.assertEqual(current_user_id.get(), "mcp_user")
                self.assertEqual(current_user_role.get(), "analyst")

    def test_creates_upload_dir(self):
        from data_agent.mcp_server import gis_lifespan

        with patch.dict(os.environ, {"MCP_USER": "test_mcp_dir"}):
            mock_server = MagicMock()
            with gis_lifespan(mock_server):
                upload_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "uploads", "test_mcp_dir"
                )
                self.assertTrue(os.path.isdir(upload_dir))

        # Cleanup
        upload_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "uploads", "test_mcp_dir"
        )
        if os.path.isdir(upload_dir):
            os.rmdir(upload_dir)


# ---------------------------------------------------------------------------
# TestResources
# ---------------------------------------------------------------------------

class TestResources(unittest.TestCase):
    """Test MCP resource functions."""

    def test_tool_catalog_returns_markdown(self):
        from data_agent.mcp_server import tool_catalog

        result = tool_catalog()
        self.assertIn("# GIS Analysis Tools", result)
        self.assertIn("describe_geodataframe", result)
        self.assertIn("Total:", result)

    def test_server_status_returns_valid_json(self):
        from data_agent.mcp_server import server_status

        result = server_status()
        parsed = json.loads(result)
        self.assertEqual(parsed["server"], "GIS Data Agent MCP")
        self.assertIn("tool_count", parsed)
        self.assertIsInstance(parsed["tool_count"], int)
        self.assertGreater(parsed["tool_count"], 0)


if __name__ == "__main__":
    unittest.main()
