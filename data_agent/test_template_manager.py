"""Tests for the template manager module (template_manager.py)."""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.template_manager import (
    ensure_templates_table,
    save_as_template,
    list_templates,
    get_template,
    delete_template,
    share_template,
    generate_plan_from_template,
    _filter_tool_sequence,
    _increment_use_count,
)


# --- Sample tool logs for testing ---
SAMPLE_LOG = [
    {
        "step": 1, "agent_name": "DataExploration",
        "tool_name": "describe_geodataframe",
        "args": {"file_path": "uploads/admin/test.shp"},
        "output_path": None, "result_summary": "7 checks passed",
        "duration": 1.5, "is_error": False,
    },
    {
        "step": 2, "agent_name": "DataProcessing",
        "tool_name": "perform_clustering",
        "args": {"file_path": "test.shp", "eps": 500, "min_samples": 5},
        "output_path": "clustering_abc.shp", "result_summary": "3 clusters",
        "duration": 2.0, "is_error": False,
    },
    {
        "step": 3, "agent_name": "DataVisualization",
        "tool_name": "generate_choropleth",
        "args": {"file_path": "clustering_abc.shp", "value_column": "cluster_id"},
        "output_path": "choropleth_abc.html", "result_summary": "",
        "duration": 1.0, "is_error": False,
    },
]


class TestFilterToolSequence(unittest.TestCase):
    """Test _filter_tool_sequence helper."""

    def test_filters_errors(self):
        log = [
            {"tool_name": "describe_geodataframe", "is_error": False},
            {"tool_name": "perform_clustering", "is_error": True},
        ]
        result = _filter_tool_sequence(log)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_name"], "describe_geodataframe")

    def test_filters_non_exportable(self):
        log = [
            {"tool_name": "describe_geodataframe", "is_error": False},
            {"tool_name": "save_memory", "is_error": False},
            {"tool_name": "list_templates", "is_error": False},
        ]
        result = _filter_tool_sequence(log)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_name"], "describe_geodataframe")

    def test_empty_log(self):
        self.assertEqual(_filter_tool_sequence([]), [])

    def test_all_filtered(self):
        log = [
            {"tool_name": "save_memory", "is_error": False},
            {"tool_name": "bad_tool", "is_error": True},
        ]
        result = _filter_tool_sequence(log)
        self.assertEqual(result, [])


class TestGeneratePlan(unittest.TestCase):
    """Test generate_plan_from_template."""

    def test_output_has_numbered_steps(self):
        template = {
            "name": "选址分析",
            "description": "标准化选址分析流程",
            "source_query": "分析和平村土地布局",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        self.assertIn("1.", plan)
        self.assertIn("2.", plan)
        self.assertIn("3.", plan)

    def test_includes_tool_names(self):
        template = {
            "name": "测试",
            "description": "",
            "source_query": "",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        self.assertIn("describe_geodataframe", plan)
        self.assertIn("perform_clustering", plan)
        self.assertIn("generate_choropleth", plan)

    def test_omits_file_path_args(self):
        template = {
            "name": "测试",
            "description": "",
            "source_query": "",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        # file_path should be omitted from plan params
        self.assertNotIn("uploads/admin/test.shp", plan)

    def test_includes_non_path_args(self):
        template = {
            "name": "测试",
            "description": "",
            "source_query": "",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        # eps and min_samples should be included
        self.assertIn("eps=500", plan)
        self.assertIn("min_samples=5", plan)

    def test_includes_template_metadata(self):
        template = {
            "name": "选址分析",
            "description": "标准化选址分析流程",
            "source_query": "分析和平村土地布局",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        self.assertIn("选址分析", plan)
        self.assertIn("标准化选址分析流程", plan)
        self.assertIn("分析和平村土地布局", plan)

    def test_includes_agent_names(self):
        template = {
            "name": "测试",
            "description": "",
            "source_query": "",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        self.assertIn("DataExploration", plan)
        self.assertIn("DataProcessing", plan)

    def test_empty_sequence(self):
        template = {
            "name": "空模板",
            "description": "",
            "source_query": "",
            "tool_sequence": [],
        }
        plan = generate_plan_from_template(template)
        self.assertIn("空模板", plan)
        self.assertIn("注意事项", plan)

    def test_value_column_included(self):
        template = {
            "name": "测试",
            "description": "",
            "source_query": "",
            "tool_sequence": SAMPLE_LOG,
        }
        plan = generate_plan_from_template(template)
        self.assertIn("value_column=cluster_id", plan)


class TestSaveTemplate(unittest.TestCase):
    """Test save_as_template input validation."""

    def test_empty_name_error(self):
        result = save_as_template("", "desc", SAMPLE_LOG, "general", "GENERAL")
        self.assertEqual(result["status"], "error")
        self.assertIn("不能为空", result["message"])

    def test_whitespace_name_error(self):
        result = save_as_template("   ", "desc", SAMPLE_LOG, "general", "GENERAL")
        self.assertEqual(result["status"], "error")

    def test_empty_log_error(self):
        result = save_as_template("test", "desc", [], "general", "GENERAL")
        self.assertEqual(result["status"], "error")
        self.assertIn("没有可保存的", result["message"])

    def test_all_error_log(self):
        log = [{"tool_name": "bad", "is_error": True}]
        result = save_as_template("test", "desc", log, "general", "GENERAL")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_error(self, mock_engine):
        result = save_as_template("test", "desc", SAMPLE_LOG, "general", "GENERAL")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库未配置", result["message"])


class TestListTemplates(unittest.TestCase):
    """Test list_templates without DB."""

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_error(self, mock_engine):
        result = list_templates()
        self.assertEqual(result["status"], "error")


class TestDeleteTemplate(unittest.TestCase):
    """Test delete_template input validation."""

    def test_invalid_id_zero(self):
        result = delete_template(0)
        self.assertEqual(result["status"], "error")
        self.assertIn("无效", result["message"])

    def test_invalid_id_negative(self):
        result = delete_template(-1)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_error(self, mock_engine):
        result = delete_template(1)
        self.assertEqual(result["status"], "error")


class TestShareTemplate(unittest.TestCase):
    """Test share_template input validation."""

    def test_invalid_id(self):
        result = share_template(0)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_error(self, mock_engine):
        result = share_template(1)
        self.assertEqual(result["status"], "error")


class TestEnsureTable(unittest.TestCase):
    """Test ensure_templates_table doesn't crash without DB."""

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_engine):
        # Should not raise
        ensure_templates_table()


class TestGetTemplate(unittest.TestCase):
    """Test get_template without DB."""

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_returns_none(self, mock_engine):
        result = get_template(1)
        self.assertIsNone(result)


class TestIncrementUseCount(unittest.TestCase):
    """Test _increment_use_count doesn't crash without DB."""

    @patch("data_agent.template_manager.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_engine):
        # Should not raise
        _increment_use_count(1)


if __name__ == "__main__":
    unittest.main()
