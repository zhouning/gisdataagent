"""Tests for the code exporter module (code_exporter.py)."""
import ast
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.code_exporter import (
    TOOL_IMPORT_MAP,
    NON_EXPORTABLE_TOOLS,
    PIPELINE_LABELS,
    COMPLEX_TOOLS,
    API_KEY_TOOLS,
    generate_python_script,
    save_script_to_file,
    _build_header,
    _build_imports,
    _build_step,
    _format_arg_value,
    _check_path_chain,
)


class TestToolImportMap(unittest.TestCase):
    """Verify TOOL_IMPORT_MAP coverage and correctness."""

    def test_all_entries_are_strings(self):
        for name, imp in TOOL_IMPORT_MAP.items():
            self.assertIsInstance(name, str)
            self.assertIsInstance(imp, str)
            self.assertTrue(imp.startswith("from "), f"Bad import for {name}: {imp}")

    def test_no_duplicate_keys(self):
        keys = list(TOOL_IMPORT_MAP.keys())
        self.assertEqual(len(keys), len(set(keys)))

    def test_non_exportable_not_in_import_map(self):
        for tool in NON_EXPORTABLE_TOOLS:
            self.assertNotIn(tool, TOOL_IMPORT_MAP,
                             f"{tool} is NON_EXPORTABLE but in TOOL_IMPORT_MAP")

    def test_minimum_coverage(self):
        # Should have at least 30 tools mapped
        self.assertGreaterEqual(len(TOOL_IMPORT_MAP), 30)


class TestNonExportableTools(unittest.TestCase):
    """Verify NON_EXPORTABLE_TOOLS constant."""

    def test_expected_members(self):
        expected = {"save_memory", "recall_memories", "list_memories",
                    "delete_memory", "get_usage_summary", "query_audit_log"}
        self.assertTrue(expected.issubset(NON_EXPORTABLE_TOOLS))

    def test_all_are_strings(self):
        for tool in NON_EXPORTABLE_TOOLS:
            self.assertIsInstance(tool, str)


class TestGenerateScript(unittest.TestCase):
    """Test generate_python_script with various inputs."""

    def test_empty_log_produces_valid_script(self):
        script = generate_python_script(tool_log=[])
        self.assertIn("GIS Data Agent", script)
        self.assertIn("分析完成", script)
        # Should be valid Python
        ast.parse(script)

    def test_single_tool_step(self):
        log = [{
            "step": 1,
            "agent_name": "DataExploration",
            "tool_name": "describe_geodataframe",
            "args": {"file_path": "uploads/admin/test.shp"},
            "output_path": None,
            "result_summary": "7 checks passed",
            "duration": 1.5,
            "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("describe_geodataframe", script)
        self.assertIn("from data_agent.toolsets.exploration_tools import describe_geodataframe", script)
        self.assertIn('r"uploads/admin/test.shp"', script)
        self.assertIn("result_1", script)
        ast.parse(script)

    def test_multi_step_sequencing(self):
        log = [
            {
                "step": 1, "agent_name": "DataExploration",
                "tool_name": "describe_geodataframe",
                "args": {"file_path": "test.shp"},
                "output_path": None, "result_summary": "",
                "duration": 1.0, "is_error": False,
            },
            {
                "step": 2, "agent_name": "DataProcessing",
                "tool_name": "perform_clustering",
                "args": {"file_path": "test.shp", "eps": 500, "min_samples": 5},
                "output_path": "clustering_abc.shp", "result_summary": "",
                "duration": 2.0, "is_error": False,
            },
        ]
        script = generate_python_script(tool_log=log)
        self.assertIn("result_1", script)
        self.assertIn("result_2", script)
        # Step 1 should come before step 2
        idx1 = script.index("result_1")
        idx2 = script.index("result_2")
        self.assertLess(idx1, idx2)
        ast.parse(script)

    def test_error_calls_commented_out(self):
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "perform_clustering",
            "args": {"file_path": "bad.shp"},
            "output_path": None, "result_summary": "File not found",
            "duration": 0.5, "is_error": True,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("[失败，已跳过]", script)
        self.assertNotIn("result_1 = perform_clustering", script)
        ast.parse(script)

    def test_non_exportable_tools_skipped(self):
        log = [{
            "step": 1, "agent_name": "GeneralProcessing",
            "tool_name": "save_memory",
            "args": {"memory_type": "region", "key": "test"},
            "output_path": None, "result_summary": "",
            "duration": 0.2, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("[跳过]", script)
        self.assertNotIn("result_1 = save_memory", script)
        ast.parse(script)

    def test_file_paths_use_raw_strings(self):
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "create_buffer",
            "args": {"file_path": r"uploads\admin\test.shp", "distance": 100},
            "output_path": None, "result_summary": "",
            "duration": 1.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn('r"uploads\\admin\\test.shp"', script)
        ast.parse(script)

    def test_header_has_metadata(self):
        script = generate_python_script(
            tool_log=[],
            pipeline_type="governance",
            user_message="检查数据质量",
            uploaded_files=["test.shp"],
            intent="GOVERNANCE",
        )
        self.assertIn("检查数据质量", script)
        self.assertIn("GOVERNANCE", script)
        self.assertIn("test.shp", script)
        self.assertIn("数据治理管线", script)

    def test_unknown_tool_handled(self):
        """Tools not in TOOL_IMPORT_MAP should still generate calls."""
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "some_future_tool_xyz",
            "args": {"in_features": "test.shp"},
            "output_path": None, "result_summary": "",
            "duration": 1.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("some_future_tool_xyz", script)
        self.assertIn("result_1", script)
        ast.parse(script)

    def test_with_tool_descriptions(self):
        descs = {
            "perform_clustering": {
                "method": "空间聚类分析（DBSCAN）",
                "params": {"file_path": "数据文件"},
            }
        }
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "perform_clustering",
            "args": {"file_path": "test.shp"},
            "output_path": None, "result_summary": "",
            "duration": 1.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log, tool_descriptions=descs)
        self.assertIn("空间聚类分析", script)
        ast.parse(script)


class TestFormatArgValue(unittest.TestCase):
    """Test _format_arg_value helper."""

    def test_none(self):
        self.assertEqual(_format_arg_value("x", None), "None")

    def test_bool(self):
        self.assertEqual(_format_arg_value("x", True), "True")
        self.assertEqual(_format_arg_value("x", False), "False")

    def test_int(self):
        self.assertEqual(_format_arg_value("x", 42), "42")

    def test_float(self):
        self.assertEqual(_format_arg_value("x", 3.14), "3.14")

    def test_path_arg(self):
        result = _format_arg_value("file_path", "uploads/test.shp")
        self.assertTrue(result.startswith('r"'))

    def test_string_repr(self):
        result = _format_arg_value("name", "hello world")
        self.assertEqual(result, "'hello world'")


class TestSaveFile(unittest.TestCase):
    """Test save_script_to_file."""

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = "# test script\nprint('hello')\n"
            path = save_script_to_file(script, tmpdir)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.endswith(".py"))
            self.assertIn("analysis_script_", os.path.basename(path))

    def test_utf8_encoding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = "# 中文注释\nprint('你好')\n"
            path = save_script_to_file(script, tmpdir)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("中文注释", content)

    def test_creates_directory_if_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested", "dir")
            script = "print('test')\n"
            path = save_script_to_file(script, subdir)
            self.assertTrue(os.path.exists(path))


class TestDataFlowChaining(unittest.TestCase):
    """Test output-to-input path substitution (data flow tracing)."""

    def test_output_chained_to_next_input(self):
        """Step 2 should use result_1 when its file_path matches step 1's output_path."""
        log = [
            {
                "step": 1, "agent_name": "DataProcessing",
                "tool_name": "create_buffer",
                "args": {"file_path": "test.shp", "distance": 500},
                "output_path": "uploads/admin/buffer_abc.shp",
                "result_summary": "", "duration": 1.0, "is_error": False,
            },
            {
                "step": 2, "agent_name": "DataProcessing",
                "tool_name": "perform_clustering",
                "args": {"file_path": "uploads/admin/buffer_abc.shp", "eps": 300},
                "output_path": None, "result_summary": "", "duration": 1.0, "is_error": False,
            },
        ]
        script = generate_python_script(tool_log=log)
        # Step 2 should reference result_1
        self.assertIn("result_1,", script)
        # The chaining comment should appear
        self.assertIn("来自前序步骤的输出", script)
        ast.parse(script)

    def test_no_chain_when_no_output_path(self):
        """No chaining when step 1 has output_path=None."""
        log = [
            {
                "step": 1, "agent_name": "DataExploration",
                "tool_name": "describe_geodataframe",
                "args": {"file_path": "test.shp"},
                "output_path": None,
                "result_summary": "", "duration": 1.0, "is_error": False,
            },
            {
                "step": 2, "agent_name": "DataProcessing",
                "tool_name": "create_buffer",
                "args": {"file_path": "test.shp", "distance": 500},
                "output_path": None, "result_summary": "", "duration": 1.0, "is_error": False,
            },
        ]
        script = generate_python_script(tool_log=log)
        # Step 2 should use the literal path, not chain
        self.assertIn('r"test.shp"', script)
        self.assertNotIn("来自前序步骤的输出", script)
        ast.parse(script)

    def test_basename_matching(self):
        """Chain should match on basename when full paths differ."""
        log = [
            {
                "step": 1, "agent_name": "DataProcessing",
                "tool_name": "create_buffer",
                "args": {"file_path": "test.shp", "distance": 500},
                "output_path": "uploads/admin/buffer_abc.shp",
                "result_summary": "", "duration": 1.0, "is_error": False,
            },
            {
                "step": 2, "agent_name": "DataProcessing",
                "tool_name": "perform_clustering",
                "args": {"file_path": "buffer_abc.shp", "eps": 300},
                "output_path": None, "result_summary": "", "duration": 1.0, "is_error": False,
            },
        ]
        script = generate_python_script(tool_log=log)
        self.assertIn("result_1,", script)
        ast.parse(script)

    def test_check_path_chain_helper(self):
        """Test _check_path_chain directly."""
        path_map = {
            "uploads/admin/buffer_abc.shp": "result_1",
            "buffer_abc.shp": "result_1",
        }
        # Exact match
        self.assertEqual(_check_path_chain("file_path", "uploads/admin/buffer_abc.shp", path_map), "result_1")
        # Basename match
        self.assertEqual(_check_path_chain("file_path", "buffer_abc.shp", path_map), "result_1")
        # No match
        self.assertIsNone(_check_path_chain("file_path", "other.shp", path_map))
        # Non-string value
        self.assertIsNone(_check_path_chain("eps", 500, path_map))
        # Empty path_map
        self.assertIsNone(_check_path_chain("file_path", "test.shp", None))


class TestComplexToolWarnings(unittest.TestCase):
    """Test warnings for DRL, geocoding, and ArcPy tools."""

    def test_drl_model_warning(self):
        log = [{
            "step": 1, "agent_name": "DataAnalysis",
            "tool_name": "drl_model",
            "args": {"data_path": "test.shp"},
            "output_path": None, "result_summary": "", "duration": 5.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("WARNING", script)
        self.assertIn("PyTorch", script)
        ast.parse(script)

    def test_geocoding_api_key_warning(self):
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "batch_geocode",
            "args": {"file_path": "test.xlsx", "address_column": "addr"},
            "output_path": None, "result_summary": "", "duration": 3.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("GAODE_API_KEY", script)
        self.assertIn("IMPORTANT", script)
        ast.parse(script)

    def test_api_key_check_in_setup(self):
        """Setup block should include API key check when geocoding tools are used."""
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "search_nearby_poi",
            "args": {"lng": 116.4, "lat": 39.9, "keywords": "school"},
            "output_path": None, "result_summary": "", "duration": 1.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn('os.environ.get("GAODE_API_KEY")', script)
        ast.parse(script)

    def test_no_api_key_check_without_geocoding(self):
        """Setup block should NOT include API key check when no geocoding tools are used."""
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "create_buffer",
            "args": {"file_path": "test.shp", "distance": 500},
            "output_path": None, "result_summary": "", "duration": 1.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertNotIn("GAODE_API_KEY", script)
        ast.parse(script)

    def test_complex_and_api_warnings_parseable(self):
        """Scripts with both complex and API warnings should be valid Python."""
        log = [
            {
                "step": 1, "agent_name": "DataProcessing",
                "tool_name": "batch_geocode",
                "args": {"file_path": "test.xlsx", "address_column": "addr"},
                "output_path": "geocoded.shp", "result_summary": "", "duration": 3.0, "is_error": False,
            },
            {
                "step": 2, "agent_name": "DataAnalysis",
                "tool_name": "drl_model",
                "args": {"data_path": "geocoded.shp"},
                "output_path": None, "result_summary": "", "duration": 10.0, "is_error": False,
            },
        ]
        script = generate_python_script(tool_log=log)
        self.assertIn("WARNING", script)
        self.assertIn("GAODE_API_KEY", script)
        # Should also chain geocoded.shp → result_1
        self.assertIn("result_1,", script)
        ast.parse(script)


class TestArcpyImportMap(unittest.TestCase):
    """Verify ArcPy tools have TOOL_IMPORT_MAP entries."""

    def test_arcpy_tools_in_map(self):
        arcpy_tools = [
            "arcpy_buffer", "arcpy_clip", "arcpy_dissolve",
            "arcpy_project", "arcpy_check_geometry",
            "arcpy_repair_geometry", "arcpy_slope",
            "arcpy_zonal_statistics",
        ]
        for tool in arcpy_tools:
            self.assertIn(tool, TOOL_IMPORT_MAP, f"{tool} missing from TOOL_IMPORT_MAP")

    def test_arcpy_import_generates_correctly(self):
        log = [{
            "step": 1, "agent_name": "DataProcessing",
            "tool_name": "arcpy_buffer",
            "args": {"in_features": "test.shp", "buffer_distance": "100 Meters"},
            "output_path": None, "result_summary": "", "duration": 2.0, "is_error": False,
        }]
        script = generate_python_script(tool_log=log)
        self.assertIn("from data_agent.arcpy_tools import arcpy_buffer", script)
        ast.parse(script)


if __name__ == "__main__":
    unittest.main()
