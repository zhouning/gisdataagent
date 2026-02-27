"""Tests for the Spatial Semantic Layer."""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.semantic_layer import (
    _load_catalog,
    _match_aliases,
    resolve_semantic_context,
    build_context_prompt,
    auto_register_table,
    register_semantic_annotation,
    register_source_metadata,
    describe_table_semantic,
    list_semantic_sources,
    ensure_semantic_tables,
    T_SEMANTIC_REGISTRY,
    T_SEMANTIC_SOURCES,
)


class TestCatalogLoading(unittest.TestCase):
    """Test YAML catalog loading and caching."""

    def test_load_catalog_returns_dict(self):
        catalog = _load_catalog()
        self.assertIsInstance(catalog, dict)

    def test_catalog_has_domains(self):
        catalog = _load_catalog()
        self.assertIn("domains", catalog)
        self.assertIn("AREA", catalog["domains"])
        self.assertIn("SLOPE", catalog["domains"])
        self.assertIn("LAND_USE", catalog["domains"])

    def test_catalog_has_region_groups(self):
        catalog = _load_catalog()
        self.assertIn("region_groups", catalog)
        self.assertIn("华东", catalog["region_groups"])
        self.assertIn("东北", catalog["region_groups"])

    def test_catalog_has_spatial_operations(self):
        catalog = _load_catalog()
        self.assertIn("spatial_operations", catalog)
        self.assertIn("buffer", catalog["spatial_operations"])
        self.assertIn("clip", catalog["spatial_operations"])

    def test_catalog_has_metric_templates(self):
        catalog = _load_catalog()
        self.assertIn("metric_templates", catalog)
        self.assertIn("density", catalog["metric_templates"])

    def test_domain_structure(self):
        catalog = _load_catalog()
        area = catalog["domains"]["AREA"]
        self.assertIn("description", area)
        self.assertIn("common_aliases", area)
        self.assertIsInstance(area["common_aliases"], list)
        self.assertGreater(len(area["common_aliases"]), 0)

    def test_catalog_cached(self):
        """Second call should return same object (cached)."""
        c1 = _load_catalog()
        c2 = _load_catalog()
        self.assertIs(c1, c2)


class TestAliasMatching(unittest.TestCase):
    """Test synonym matching algorithm."""

    def test_exact_match(self):
        score = _match_aliases("area", ["area", "zmj", "面积"])
        self.assertEqual(score, 1.0)

    def test_exact_match_case_insensitive(self):
        score = _match_aliases("AREA", ["area", "zmj"])
        self.assertEqual(score, 1.0)

    def test_substring_match(self):
        score = _match_aliases("分析和平村各地类的面积分布", ["面积", "area"])
        self.assertEqual(score, 0.7)

    def test_substring_match_chinese(self):
        score = _match_aliases("查看坡度数据", ["坡度", "slope"])
        self.assertEqual(score, 0.7)

    def test_no_match(self):
        score = _match_aliases("天气预报", ["area", "zmj", "面积"])
        self.assertEqual(score, 0.0)

    def test_short_alias_ignored(self):
        """Single-char aliases should not substring match."""
        score = _match_aliases("xyz", ["x"])
        self.assertEqual(score, 0.0)  # "x" is len=1, skipped in substring

    def test_exact_single_char(self):
        """Single-char alias can exact match."""
        score = _match_aliases("x", ["x", "lng"])
        self.assertEqual(score, 1.0)

    def test_empty_aliases(self):
        score = _match_aliases("test", [])
        self.assertEqual(score, 0.0)

    def test_empty_text(self):
        score = _match_aliases("", ["area"])
        self.assertEqual(score, 0.0)


class TestResolveSemanticContext(unittest.TestCase):
    """Test the core resolution function (static catalog part, no DB)."""

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_no_db_still_resolves_static(self, mock_url):
        """Without DB, should still resolve static catalog matches."""
        result = resolve_semantic_context("分析面积分布")
        self.assertIn("matched_columns", result)
        self.assertIn("spatial_ops", result)
        # Should match AREA domain from static catalog
        static_hints = result["matched_columns"].get("_static_hints", [])
        domains = [h["semantic_domain"] for h in static_hints]
        self.assertIn("AREA", domains)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_region_match_huadong(self, mock_url):
        result = resolve_semantic_context("华东地区的数据分析")
        self.assertIsNotNone(result["region_filter"])
        self.assertEqual(result["region_filter"]["name"], "华东")
        self.assertIn("上海市", result["region_filter"]["provinces"])

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_region_match_dongbei(self, mock_url):
        result = resolve_semantic_context("东北区域土地利用")
        self.assertIsNotNone(result["region_filter"])
        self.assertEqual(result["region_filter"]["name"], "东北")

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_no_region_match(self, mock_url):
        result = resolve_semantic_context("分析这个表")
        self.assertIsNone(result["region_filter"])

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_spatial_op_buffer(self, mock_url):
        result = resolve_semantic_context("做一个500米缓冲区分析")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("buffer", ops)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_spatial_op_clip(self, mock_url):
        result = resolve_semantic_context("裁剪这个数据")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("clip", ops)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_spatial_op_heatmap(self, mock_url):
        result = resolve_semantic_context("生成热力图")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("heatmap", ops)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_metric_density(self, mock_url):
        result = resolve_semantic_context("计算密度分布")
        metrics = [m["metric"] for m in result["metric_hints"]]
        self.assertIn("density", metrics)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_metric_coverage(self, mock_url):
        result = resolve_semantic_context("林地覆盖率是多少")
        metrics = [m["metric"] for m in result["metric_hints"]]
        self.assertIn("coverage", metrics)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_multiple_matches(self, mock_url):
        """A complex query should match multiple things."""
        result = resolve_semantic_context("华北地区耕地面积的密度分析，用缓冲区方法")
        # Should match: region (华北), domain (面积+AREA), op (缓冲区), metric (密度)
        self.assertIsNotNone(result["region_filter"])
        self.assertGreater(len(result["spatial_ops"]), 0)
        self.assertGreater(len(result["metric_hints"]), 0)

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_no_matches(self, mock_url):
        result = resolve_semantic_context("你好")
        self.assertEqual(len(result["sources"]), 0)
        self.assertEqual(len(result["spatial_ops"]), 0)
        self.assertIsNone(result["region_filter"])


class TestBuildContextPrompt(unittest.TestCase):
    """Test prompt builder."""

    def test_empty_resolution(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
        }
        prompt = build_context_prompt(resolved)
        self.assertEqual(prompt, "")

    def test_with_source(self):
        resolved = {
            "sources": [{"table_name": "heping_8000", "display_name": "和平村",
                         "geometry_type": "Polygon", "srid": 4490, "description": "地块数据"}],
            "matched_columns": {
                "heping_8000": [
                    {"column_name": "zmj", "semantic_domain": "AREA",
                     "aliases": ["面积"], "unit": "亩", "description": "面积",
                     "is_geometry": False, "confidence": 0.7},
                ]
            },
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("[语义上下文]", prompt)
        self.assertIn("heping_8000", prompt)
        self.assertIn("和平村", prompt)
        self.assertIn("zmj", prompt)
        self.assertIn("面积", prompt)
        self.assertIn("SRID=4490", prompt)

    def test_with_region(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": {"name": "华东", "provinces": ["上海市", "江苏省"]},
            "metric_hints": [],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("华东", prompt)
        self.assertIn("上海市", prompt)

    def test_with_spatial_op(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [{"operation": "buffer", "tool_name": "create_buffer"}],
            "region_filter": None,
            "metric_hints": [],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("create_buffer", prompt)

    def test_with_metric(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [{"metric": "density", "description": "密度 = 数量 / 面积",
                              "pattern": "COUNT(*) / area", "unit": "个/km²"}],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("密度", prompt)
        self.assertIn("COUNT(*) / area", prompt)


class TestCRUDToolsNoDB(unittest.TestCase):
    """Test CRUD tool functions when DB is not configured."""

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_register_annotation_no_db(self, mock_url):
        result = register_semantic_annotation("test", "col1", "AREA")
        self.assertEqual(result["status"], "error")
        self.assertIn("not configured", result["message"])

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_register_source_no_db(self, mock_url):
        result = register_source_metadata("test")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_describe_semantic_no_db(self, mock_url):
        result = describe_table_semantic("test")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_list_sources_no_db(self, mock_url):
        result = list_semantic_sources()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_auto_register_no_db(self, mock_url):
        result = auto_register_table("test", "admin")
        self.assertEqual(result["status"], "error")


class TestRegisterAnnotationValidation(unittest.TestCase):
    """Test input validation for register_semantic_annotation."""

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value="postgresql://x")
    def test_invalid_json(self, mock_url):
        result = register_semantic_annotation("t", "c", "AREA", aliases_json="not json")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["message"])

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value="postgresql://x")
    def test_non_array_json(self, mock_url):
        result = register_semantic_annotation("t", "c", "AREA", aliases_json='{"a":1}')
        self.assertEqual(result["status"], "error")
        self.assertIn("JSON array", result["message"])


class TestRegisterSourceValidation(unittest.TestCase):
    """Test input validation for register_source_metadata."""

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value="postgresql://x")
    def test_invalid_synonyms_json(self, mock_url):
        result = register_source_metadata("t", synonyms_json="bad")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["message"])


class TestEnsureSemanticTablesNoDB(unittest.TestCase):
    """Test startup initialization with no DB."""

    @patch("data_agent.semantic_layer.get_db_connection_url", return_value=None)
    def test_no_db_graceful(self, mock_url):
        """Should not raise when DB is not configured."""
        ensure_semantic_tables()  # should return silently


class TestCatalogDomainCompleteness(unittest.TestCase):
    """Verify all expected domains exist in catalog."""

    def test_all_15_domains(self):
        catalog = _load_catalog()
        expected = {
            "AREA", "SLOPE", "ELEVATION", "LAND_USE", "NAME",
            "ADMIN_CODE", "POPULATION", "OWNERSHIP", "PERIMETER",
            "LONGITUDE", "LATITUDE", "ADDRESS", "CATEGORY", "ID", "ASPECT",
        }
        actual = set(catalog["domains"].keys())
        self.assertEqual(expected, actual)

    def test_all_7_regions(self):
        catalog = _load_catalog()
        expected = {"华东", "华南", "华北", "华中", "西南", "西北", "东北"}
        actual = set(catalog["region_groups"].keys())
        self.assertEqual(expected, actual)

    def test_all_8_operations(self):
        catalog = _load_catalog()
        expected = {"buffer", "clip", "overlay", "distance",
                    "clustering", "heatmap", "choropleth", "tessellation"}
        actual = set(catalog["spatial_operations"].keys())
        self.assertEqual(expected, actual)

    def test_all_4_metrics(self):
        catalog = _load_catalog()
        expected = {"density", "fragmentation", "coverage", "concentration"}
        actual = set(catalog["metric_templates"].keys())
        self.assertEqual(expected, actual)


class TestTableConstants(unittest.TestCase):
    """Verify table name constants."""

    def test_registry_table_name(self):
        self.assertEqual(T_SEMANTIC_REGISTRY, "agent_semantic_registry")

    def test_sources_table_name(self):
        self.assertEqual(T_SEMANTIC_SOURCES, "agent_semantic_sources")


if __name__ == "__main__":
    unittest.main()
