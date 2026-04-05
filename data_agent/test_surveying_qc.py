"""Tests for surveying QC features — report generator, precision tools, standards."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestReportTemplates(unittest.TestCase):
    """Test report template system."""

    def test_list_templates(self):
        from data_agent.report_generator import list_report_templates
        templates = list_report_templates()
        self.assertGreaterEqual(len(templates), 3)
        ids = [t["id"] for t in templates]
        self.assertIn("surveying_qc", ids)
        self.assertIn("data_quality", ids)
        self.assertIn("governance", ids)

    def test_generate_structured_report_md(self):
        from data_agent.report_generator import generate_structured_report
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_structured_report(
                template_id="data_quality",
                section_data={
                    "数据集概览": "测试数据集，包含100条记录。",
                    "质量评估": "完整性 95%，拓扑无错误。",
                    "问题清单": "发现2处属性缺失。",
                    "改进建议": "补全缺失属性。",
                },
                title="测试数据质量报告",
                output_format="md",
                output_dir=tmp,
            )
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(path.endswith(".md"))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("测试数据质量报告", content)
            self.assertIn("测试数据集", content)

    def test_generate_structured_report_docx(self):
        from data_agent.report_generator import generate_structured_report
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_structured_report(
                template_id="surveying_qc",
                section_data={
                    "项目概况": "XX市1:500地形图质量检查",
                    "检查依据": "GB/T 24356-2023",
                    "数据审查结果": "数据完整，格式规范",
                },
                output_format="docx",
                output_dir=tmp,
            )
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(path.endswith(".docx"))

    def test_unknown_template_raises(self):
        from data_agent.report_generator import generate_structured_report
        with self.assertRaises(ValueError):
            generate_structured_report("nonexistent_template", {})


class TestReportToolset(unittest.TestCase):
    """Test ReportToolset registration."""

    def test_toolset_in_registry(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("ReportToolset", TOOLSET_NAMES)

    def test_tool_count(self):
        from data_agent.toolsets.report_tools import ReportToolset
        ts = ReportToolset()
        tools = asyncio.run(ts.get_tools())
        self.assertEqual(len(tools), 3)
        names = [t.name for t in tools]
        self.assertIn("list_report_templates", names)
        self.assertIn("generate_quality_report", names)
        self.assertIn("export_analysis_report", names)


class TestPrecisionToolset(unittest.TestCase):
    """Test PrecisionToolset registration."""

    def test_toolset_in_registry(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("PrecisionToolset", TOOLSET_NAMES)

    def test_tool_count(self):
        from data_agent.toolsets.precision_tools import PrecisionToolset
        ts = PrecisionToolset()
        tools = asyncio.run(ts.get_tools())
        self.assertEqual(len(tools), 5)
        names = [t.name for t in tools]
        self.assertIn("compare_coordinates", names)
        self.assertIn("check_topology_integrity", names)
        self.assertIn("check_edge_matching", names)
        self.assertIn("precision_score", names)

    @patch("data_agent.gis_processors.get_user_upload_dir", return_value="/tmp")
    def test_precision_score_nonexistent_file(self, _):
        from data_agent.toolsets.precision_tools import precision_score
        result = precision_score("/nonexistent/file.shp")
        self.assertIn("不存在", result)

    @patch("data_agent.gis_processors.get_user_upload_dir", return_value="/tmp")
    def test_topology_integrity_nonexistent(self, _):
        from data_agent.toolsets.precision_tools import check_topology_integrity
        result = check_topology_integrity("/nonexistent/file.shp")
        self.assertIn("不存在", result)


class TestSurveyingStandard(unittest.TestCase):
    """Test GB/T 24356 standard definition."""

    def test_standard_file_exists(self):
        path = os.path.join(os.path.dirname(__file__), "standards", "gb_t_24356.yaml")
        self.assertTrue(os.path.isfile(path))

    def test_standard_loadable(self):
        import yaml
        path = os.path.join(os.path.dirname(__file__), "standards", "gb_t_24356.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["id"], "gb_t_24356")
        self.assertIn("quality_elements", data)
        self.assertIn("defect_codes", data)
        self.assertIn("quality_grades", data)
        self.assertIn("product_types", data)
        self.assertIn("sop_workflow", data)

    def test_quality_elements_weights(self):
        import yaml
        path = os.path.join(os.path.dirname(__file__), "standards", "gb_t_24356.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        weights = sum(e["weight"] for e in data["quality_elements"])
        self.assertAlmostEqual(weights, 1.0, places=2)

    def test_sop_workflow_steps(self):
        import yaml
        path = os.path.join(os.path.dirname(__file__), "standards", "gb_t_24356.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        steps = data["sop_workflow"]
        self.assertGreaterEqual(len(steps), 8)
        # Verify sequential step numbers
        for i, step in enumerate(steps):
            self.assertEqual(step["step"], i + 1)


class TestSurveyingQCSkill(unittest.TestCase):
    """Test surveying-qc skill definition."""

    def test_skill_directory_exists(self):
        skill_dir = os.path.join(os.path.dirname(__file__), "skills", "surveying-qc")
        self.assertTrue(os.path.isdir(skill_dir))

    def test_skill_yaml_exists(self):
        path = os.path.join(os.path.dirname(__file__), "skills", "surveying-qc", "SKILL.yaml")
        self.assertTrue(os.path.isfile(path))

    def test_skill_md_exists(self):
        path = os.path.join(os.path.dirname(__file__), "skills", "surveying-qc", "SKILL.md")
        self.assertTrue(os.path.isfile(path))

    def test_skill_yaml_loadable(self):
        import yaml
        path = os.path.join(os.path.dirname(__file__), "skills", "surveying-qc", "SKILL.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["name"], "surveying-qc")
        self.assertEqual(data["pattern"], "inversion")
        self.assertIn("GovernanceToolset", data["toolsets"])
        self.assertIn("PrecisionToolset", data["toolsets"])
        self.assertIn("ReportToolset", data["toolsets"])


if __name__ == "__main__":
    unittest.main()
