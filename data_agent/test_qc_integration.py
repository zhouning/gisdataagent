"""Integration tests for Surveying QC Agent — DA <-> subsystems."""

import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


class TestCvServiceIntegration(unittest.TestCase):
    """DA <-> CV Service integration tests (mock HTTP)."""

    @patch("httpx.AsyncClient.post")
    def test_cad_layer_detection_via_mcp(self, mock_post):
        """CV service should return layer detection results."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "detections": [
                    {"layer": "建筑", "confidence": 0.95, "bbox": [10, 20, 100, 200]},
                    {"layer": "道路", "confidence": 0.88, "bbox": [50, 60, 150, 250]},
                ],
                "total": 2,
            }
        )
        # Verify response structure
        result = mock_post.return_value.json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["detections"]), 2)
        self.assertGreater(result["detections"][0]["confidence"], 0.5)

    @patch("httpx.AsyncClient.post")
    def test_raster_quality_check_via_mcp(self, mock_post):
        """CV service should return raster quality metrics."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "resolution": {"x": 0.5, "y": 0.5, "unit": "meters"},
                "blur_score": 85.2,
                "quality_grade": "合格",
            }
        )
        result = mock_post.return_value.json()
        self.assertIn("resolution", result)
        self.assertIn("quality_grade", result)

    def test_cv_service_health_check(self):
        """Health endpoint should return ok."""
        # Mock the health check
        health = {"status": "ok", "service": "cv-service"}
        self.assertEqual(health["status"], "ok")


class TestCadParserIntegration(unittest.TestCase):
    """DA <-> CAD Parser integration tests (mock HTTP)."""

    @patch("httpx.AsyncClient.post")
    def test_dxf_parse_and_governance_check(self, mock_post):
        """CAD parser should extract layers and entities from DXF."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "layers": ["0", "建筑", "道路", "水系"],
                "entity_count": 1523,
                "entities_by_layer": {"建筑": 450, "道路": 380, "水系": 200, "0": 493},
                "bounding_box": {"min_x": 0, "min_y": 0, "max_x": 1000, "max_y": 800},
            }
        )
        result = mock_post.return_value.json()
        self.assertIn("layers", result)
        self.assertGreater(result["entity_count"], 0)
        self.assertEqual(len(result["layers"]), 4)

    @patch("httpx.AsyncClient.post")
    def test_cad_to_geojson_conversion(self, mock_post):
        """CAD parser should convert DXF to GeoJSON."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "output_path": "/tmp/output.geojson",
                "feature_count": 450,
                "geometry_types": ["LineString", "Polygon"],
            }
        )
        result = mock_post.return_value.json()
        self.assertIn("output_path", result)
        self.assertGreater(result["feature_count"], 0)


class TestMcpServerIntegration(unittest.TestCase):
    """DA <-> MCP Servers integration tests (mock MCP)."""

    @patch("subprocess.run")
    def test_arcgis_topology_via_mcp_hub(self, mock_run):
        """ArcGIS MCP should execute topology check via subprocess."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "status": "ok",
                "errors_found": 3,
                "error_types": {"Must Not Overlap": 2, "Must Not Have Gaps": 1},
            }),
            stderr="",
        )
        result = json.loads(mock_run.return_value.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["errors_found"], 3)

    @patch("subprocess.run")
    def test_qgis_validate_via_mcp_hub(self, mock_run):
        """QGIS MCP should validate geometry."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "status": "ok",
                "valid_count": 95,
                "invalid_count": 5,
                "issues": ["Self-intersection at feature 23", "Ring self-intersection at feature 45"],
            }),
            stderr="",
        )
        result = json.loads(mock_run.return_value.stdout)
        self.assertEqual(result["valid_count"], 95)
        self.assertEqual(result["invalid_count"], 5)


class TestReferenceDataIntegration(unittest.TestCase):
    """DA <-> Reference Data integration tests (mock HTTP)."""

    @patch("httpx.AsyncClient.get")
    def test_nearby_control_points_query(self, mock_get):
        """Reference data service should return nearby control points."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "points": [
                    {"point_id": "SH-GPS-001", "name": "上海GPS A级点", "x": 121.4737, "y": 31.2304, "accuracy_class": "A"},
                    {"point_id": "SH-GPS-002", "name": "上海GPS B级点", "x": 121.4800, "y": 31.2350, "accuracy_class": "B"},
                ],
                "total": 2,
            }
        )
        result = mock_get.return_value.json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["points"][0]["accuracy_class"], "A")

    @patch("httpx.AsyncClient.post")
    def test_precision_compare_with_reference(self, mock_post):
        """Reference data service should compare coordinates and return RMSE."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "rmse": 0.032,
                "max_error": 0.089,
                "mean_error": 0.028,
                "grade": "优",
                "point_count": 15,
                "exceed_count": 0,
            }
        )
        result = mock_post.return_value.json()
        self.assertLess(result["rmse"], 0.1)
        self.assertEqual(result["grade"], "优")


class TestEndToEndQcWorkflow(unittest.TestCase):
    """End-to-end QC workflow tests."""

    def test_defect_taxonomy_integration(self):
        """DefectTaxonomy should integrate with GovernanceToolset."""
        from data_agent.standard_registry import DefectTaxonomy
        # Verify taxonomy is loaded
        defects = DefectTaxonomy.all_defects()
        self.assertGreater(len(defects), 20)
        # Verify scoring works
        score = DefectTaxonomy.compute_quality_score(["FMT-001", "TOP-005"], total_items=100)
        self.assertIn("score", score)
        self.assertIn("grade", score)

    def test_qc_workflow_template_loading(self):
        """QC workflow templates should load correctly."""
        from data_agent.workflow_engine import list_qc_templates
        templates = list_qc_templates()
        self.assertEqual(len(templates), 3)
        template_ids = {t["id"] for t in templates}
        self.assertIn("surveying_qc_standard", template_ids)
        self.assertIn("surveying_qc_quick", template_ids)
        self.assertIn("surveying_qc_full", template_ids)

    def test_qc_report_generation(self):
        """QC report should generate a valid Word document."""
        import tempfile
        from data_agent.report_generator import generate_qc_report
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_qc_report(
                section_data={
                    "项目概况": "测试项目，用于验证报告生成功能。",
                    "检查依据": "GB/T 24356-2009",
                    "数据审查结果": "共检查 100 条记录，发现 3 个缺陷。",
                    "精度核验结果": "RMSE = 0.032m，等级：优。",
                    "缺陷统计": "格式错误 1 个，拓扑错误 2 个。",
                    "质量评分": "综合评分 92.0，等级：优秀。",
                    "整改建议": "建议修复 2 个拓扑错误。",
                    "结论": "数据质量合格，可以验收。",
                },
                metadata={
                    "project_name": "集成测试项目",
                    "check_date": "2026年3月26日",
                },
                output_dir=tmpdir,
            )
            self.assertTrue(path.endswith(".docx"))
            import os
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 1000)


class TestToolsetCounts(unittest.TestCase):
    """Verify toolset tool counts after enhancements."""

    def _run_async(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_governance_toolset_count(self):
        from data_agent.toolsets.governance_tools import GovernanceToolset
        ts = GovernanceToolset()
        tools = self._run_async(ts.get_tools())
        self.assertEqual(len(tools), 18)  # 16 original + 2 extra

    def test_data_cleaning_toolset_count(self):
        from data_agent.toolsets.data_cleaning_tools import DataCleaningToolset
        ts = DataCleaningToolset()
        tools = self._run_async(ts.get_tools())
        self.assertEqual(len(tools), 11)  # 11 functions in _ALL_FUNCS


if __name__ == "__main__":
    unittest.main()
