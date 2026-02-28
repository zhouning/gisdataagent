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
    expand_hierarchy,
    generate_semantic_filters,
    register_semantic_domain,
    discover_column_equivalences,
    export_semantic_model,
    T_SEMANTIC_REGISTRY,
    T_SEMANTIC_SOURCES,
    T_SEMANTIC_DOMAINS,
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

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_db_still_resolves_static(self, mock_engine):
        """Without DB, should still resolve static catalog matches."""
        result = resolve_semantic_context("分析面积分布")
        self.assertIn("matched_columns", result)
        self.assertIn("spatial_ops", result)
        # Should match AREA domain from static catalog
        static_hints = result["matched_columns"].get("_static_hints", [])
        domains = [h["semantic_domain"] for h in static_hints]
        self.assertIn("AREA", domains)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_region_match_huadong(self, mock_engine):
        result = resolve_semantic_context("华东地区的数据分析")
        self.assertIsNotNone(result["region_filter"])
        self.assertEqual(result["region_filter"]["name"], "华东")
        self.assertIn("上海市", result["region_filter"]["provinces"])

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_region_match_dongbei(self, mock_engine):
        result = resolve_semantic_context("东北区域土地利用")
        self.assertIsNotNone(result["region_filter"])
        self.assertEqual(result["region_filter"]["name"], "东北")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_region_match(self, mock_engine):
        result = resolve_semantic_context("分析这个表")
        self.assertIsNone(result["region_filter"])

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_spatial_op_buffer(self, mock_engine):
        result = resolve_semantic_context("做一个500米缓冲区分析")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("buffer", ops)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_spatial_op_clip(self, mock_engine):
        result = resolve_semantic_context("裁剪这个数据")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("clip", ops)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_spatial_op_heatmap(self, mock_engine):
        result = resolve_semantic_context("生成热力图")
        ops = [o["operation"] for o in result["spatial_ops"]]
        self.assertIn("heatmap", ops)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_metric_density(self, mock_engine):
        result = resolve_semantic_context("计算密度分布")
        metrics = [m["metric"] for m in result["metric_hints"]]
        self.assertIn("density", metrics)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_metric_coverage(self, mock_engine):
        result = resolve_semantic_context("林地覆盖率是多少")
        metrics = [m["metric"] for m in result["metric_hints"]]
        self.assertIn("coverage", metrics)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_multiple_matches(self, mock_engine):
        """A complex query should match multiple things."""
        result = resolve_semantic_context("华北地区耕地面积的密度分析，用缓冲区方法")
        # Should match: region (华北), domain (面积+AREA), op (缓冲区), metric (密度)
        self.assertIsNotNone(result["region_filter"])
        self.assertGreater(len(result["spatial_ops"]), 0)
        self.assertGreater(len(result["metric_hints"]), 0)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_matches(self, mock_engine):
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

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_register_annotation_no_db(self, mock_engine):
        result = register_semantic_annotation("test", "col1", "AREA")
        self.assertEqual(result["status"], "error")
        self.assertIn("not configured", result["message"])

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_register_source_no_db(self, mock_engine):
        result = register_source_metadata("test")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_describe_semantic_no_db(self, mock_engine):
        result = describe_table_semantic("test")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_list_sources_no_db(self, mock_engine):
        result = list_semantic_sources()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_auto_register_no_db(self, mock_engine):
        result = auto_register_table("test", "admin")
        self.assertEqual(result["status"], "error")


class TestRegisterAnnotationValidation(unittest.TestCase):
    """Test input validation for register_semantic_annotation."""

    @patch("data_agent.semantic_layer.get_engine", return_value=MagicMock())
    def test_invalid_json(self, mock_engine):
        result = register_semantic_annotation("t", "c", "AREA", aliases_json="not json")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["message"])

    @patch("data_agent.semantic_layer.get_engine", return_value=MagicMock())
    def test_non_array_json(self, mock_engine):
        result = register_semantic_annotation("t", "c", "AREA", aliases_json='{"a":1}')
        self.assertEqual(result["status"], "error")
        self.assertIn("JSON array", result["message"])


class TestRegisterSourceValidation(unittest.TestCase):
    """Test input validation for register_source_metadata."""

    @patch("data_agent.semantic_layer.get_engine", return_value=MagicMock())
    def test_invalid_synonyms_json(self, mock_engine):
        result = register_source_metadata("t", synonyms_json="bad")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["message"])


class TestEnsureSemanticTablesNoDB(unittest.TestCase):
    """Test startup initialization with no DB."""

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_engine):
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


class TestHierarchyMatching(unittest.TestCase):
    """Test LAND_USE hierarchy matching."""

    def test_catalog_has_hierarchy(self):
        catalog = _load_catalog()
        lu = catalog["domains"]["LAND_USE"]
        self.assertIn("hierarchy", lu)
        self.assertIn("农用地", lu["hierarchy"])
        self.assertIn("建设用地", lu["hierarchy"])
        self.assertIn("未利用地", lu["hierarchy"])

    def test_match_child_cropland(self):
        """'耕地' should match as a child of 农用地."""
        from data_agent.semantic_layer import _match_hierarchy
        catalog = _load_catalog()
        lu = catalog["domains"]["LAND_USE"]
        result = _match_hierarchy("统计耕地面积", lu)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "child")
        self.assertEqual(result["name"], "耕地")
        self.assertEqual(result["code_prefix"], "01")
        self.assertEqual(result["parent"], "农用地")

    def test_match_parent_agricultural(self):
        """'农用地' should match as parent, returning all children."""
        from data_agent.semantic_layer import _match_hierarchy
        catalog = _load_catalog()
        lu = catalog["domains"]["LAND_USE"]
        result = _match_hierarchy("统计农用地面积", lu)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "parent")
        self.assertEqual(result["name"], "农用地")
        self.assertGreater(len(result["children"]), 0)
        child_names = [c["name"] for c in result["children"]]
        self.assertIn("耕地", child_names)
        self.assertIn("林地", child_names)

    def test_match_child_forest(self):
        """'林地' should match as child with code_prefix 03."""
        from data_agent.semantic_layer import _match_hierarchy
        catalog = _load_catalog()
        lu = catalog["domains"]["LAND_USE"]
        result = _match_hierarchy("林地覆盖率", lu)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "林地")
        self.assertEqual(result["code_prefix"], "03")

    def test_no_hierarchy_match(self):
        """Non-land-use text should not match hierarchy."""
        from data_agent.semantic_layer import _match_hierarchy
        catalog = _load_catalog()
        lu = catalog["domains"]["LAND_USE"]
        result = _match_hierarchy("查看天气预报", lu)
        self.assertIsNone(result)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_includes_hierarchy(self, mock_engine):
        """resolve_semantic_context should include hierarchy_matches."""
        result = resolve_semantic_context("统计耕地面积分布")
        self.assertIn("hierarchy_matches", result)
        self.assertGreater(len(result["hierarchy_matches"]), 0)
        h = result["hierarchy_matches"][0]
        self.assertEqual(h["domain"], "LAND_USE")
        self.assertEqual(h["name"], "耕地")

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_parent_includes_children(self, mock_engine):
        """Parent match should list all child categories."""
        result = resolve_semantic_context("分析农用地结构")
        self.assertIn("hierarchy_matches", result)
        h = result["hierarchy_matches"][0]
        self.assertEqual(h["level"], "parent")
        child_names = [c["name"] for c in h["children"]]
        self.assertIn("耕地", child_names)

    def test_prompt_with_child_hierarchy(self):
        """build_context_prompt should output hierarchy child info."""
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "hierarchy_matches": [{
                "domain": "LAND_USE",
                "level": "child",
                "parent": "农用地",
                "name": "耕地",
                "code_prefix": "01",
                "aliases": ["耕地"],
            }],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("耕地", prompt)
        self.assertIn("01*", prompt)
        self.assertIn("农用地", prompt)

    def test_prompt_with_parent_hierarchy(self):
        """build_context_prompt should output hierarchy parent with all children."""
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "hierarchy_matches": [{
                "domain": "LAND_USE",
                "level": "parent",
                "parent": "农用地",
                "name": "农用地",
                "children": [
                    {"name": "耕地", "code_prefix": "01"},
                    {"name": "园地", "code_prefix": "02"},
                    {"name": "林地", "code_prefix": "03"},
                ],
            }],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("农用地", prompt)
        self.assertIn("耕地[01*]", prompt)
        self.assertIn("林地[03*]", prompt)


class TestEquivalenceMatching(unittest.TestCase):
    """Test column equivalence mappings."""

    def test_catalog_has_equivalences(self):
        catalog = _load_catalog()
        self.assertIn("equivalences", catalog)
        self.assertGreater(len(catalog["equivalences"]), 0)

    def test_dlbm_dlmc_equivalence(self):
        from data_agent.semantic_layer import _match_equivalences
        catalog = _load_catalog()
        matched_cols = {
            "test_table": [{"column_name": "dlbm", "semantic_domain": "LAND_USE"}]
        }
        equivs = _match_equivalences(matched_cols, catalog)
        self.assertGreater(len(equivs), 0)
        eq = equivs[0]
        self.assertIn("dlbm", eq["columns"])
        self.assertIn("dlmc", eq["columns"])

    def test_no_equivalence_for_unknown_column(self):
        from data_agent.semantic_layer import _match_equivalences
        catalog = _load_catalog()
        matched_cols = {
            "test_table": [{"column_name": "random_col", "semantic_domain": "AREA"}]
        }
        equivs = _match_equivalences(matched_cols, catalog)
        self.assertEqual(len(equivs), 0)

    def test_prompt_with_equivalence(self):
        """build_context_prompt should output equivalence info."""
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "equivalences": [{
                "columns": ["dlbm", "dlmc"],
                "relationship": "code_name",
                "description": "地类编码 ↔ 地类名称",
            }],
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("dlbm", prompt)
        self.assertIn("dlmc", prompt)
        self.assertIn("地类编码", prompt)


class TestSemanticCache(unittest.TestCase):
    """Test TTL cache behavior."""

    def test_invalidate_clears_sources(self):
        from data_agent.semantic_layer import invalidate_semantic_cache
        import data_agent.semantic_layer as sl
        sl._sources_cache = ["fake"]
        sl._sources_cache_time = 999
        invalidate_semantic_cache()
        self.assertIsNone(sl._sources_cache)
        self.assertEqual(sl._sources_cache_time, 0)

    def test_invalidate_clears_specific_table(self):
        from data_agent.semantic_layer import invalidate_semantic_cache
        import data_agent.semantic_layer as sl
        sl._registry_cache = {"tbl_a": ([], 1), "tbl_b": ([], 1)}
        invalidate_semantic_cache("tbl_a")
        self.assertNotIn("tbl_a", sl._registry_cache)
        self.assertIn("tbl_b", sl._registry_cache)
        # cleanup
        sl._registry_cache.clear()

    def test_invalidate_all_clears_registry(self):
        from data_agent.semantic_layer import invalidate_semantic_cache
        import data_agent.semantic_layer as sl
        sl._registry_cache = {"tbl_a": ([], 1), "tbl_b": ([], 1)}
        invalidate_semantic_cache()
        self.assertEqual(len(sl._registry_cache), 0)


# ============================================================================
# NEW TESTS: Semantic Layer Enhancement (Phase 1)
# ============================================================================

class TestFuzzyMatchingEnhanced(unittest.TestCase):
    """Test fuzzy matching via SequenceMatcher."""

    def test_fuzzy_close_match(self):
        """slope_deg vs slope_dg should fuzzy match."""
        score = _match_aliases("slope_dg", ["slope_deg", "坡度"], fuzzy=True)
        self.assertGreater(score, 0.0)

    def test_fuzzy_no_false_positive(self):
        """Completely different strings should not fuzzy match."""
        score = _match_aliases("天气预报", ["面积", "area", "zmj"], fuzzy=True)
        self.assertEqual(score, 0.0)

    def test_fuzzy_disabled(self):
        score = _match_aliases("slope_dg", ["slope_deg"], fuzzy=False)
        self.assertEqual(score, 0.0)

    def test_short_strings_skip_fuzzy(self):
        """Aliases shorter than 3 chars should not trigger fuzzy matching."""
        score = _match_aliases("xy", ["xz"], fuzzy=True)
        self.assertEqual(score, 0.0)


class TestExpandHierarchy(unittest.TestCase):
    """Test expand_hierarchy for static LAND_USE domain."""

    def test_expand_agricultural(self):
        results = expand_hierarchy("LAND_USE", "农用地")
        self.assertGreaterEqual(len(results), 3)
        prefixes = [r["code_prefix"] for r in results]
        self.assertIn("01", prefixes)
        self.assertIn("03", prefixes)

    def test_expand_child_cropland(self):
        results = expand_hierarchy("LAND_USE", "耕地")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["code_prefix"], "01")
        self.assertEqual(results[0]["name"], "耕地")

    def test_expand_construction(self):
        results = expand_hierarchy("LAND_USE", "建设用地")
        self.assertGreaterEqual(len(results), 3)
        prefixes = [r["code_prefix"] for r in results]
        self.assertIn("05", prefixes)

    def test_expand_no_match(self):
        results = expand_hierarchy("LAND_USE", "太空基地")
        self.assertEqual(len(results), 0)

    def test_expand_unknown_domain(self):
        results = expand_hierarchy("NONEXISTENT", "test")
        self.assertEqual(len(results), 0)


class TestGenerateSemanticFilters(unittest.TestCase):
    """Test SQL filter generation from resolved context."""

    def test_child_filter(self):
        ctx = {
            "hierarchy_matches": [{
                "domain": "LAND_USE", "level": "child",
                "parent": "农用地", "name": "耕地", "code_prefix": "01",
            }],
        }
        result = generate_semantic_filters(ctx)
        self.assertEqual(len(result["sql_filters"]), 1)
        self.assertIn("dlbm LIKE '01%'", result["sql_filters"][0]["sql"])

    def test_parent_filter_or_conditions(self):
        ctx = {
            "hierarchy_matches": [{
                "domain": "LAND_USE", "level": "parent",
                "parent": "农用地", "name": "农用地",
                "children": [
                    {"name": "耕地", "code_prefix": "01"},
                    {"name": "林地", "code_prefix": "03"},
                    {"name": "草地", "code_prefix": "04"},
                ],
            }],
        }
        result = generate_semantic_filters(ctx)
        self.assertEqual(len(result["sql_filters"]), 1)
        sql = result["sql_filters"][0]["sql"]
        self.assertIn("01%", sql)
        self.assertIn("03%", sql)
        self.assertIn("04%", sql)
        self.assertIn(" OR ", sql)

    def test_region_sql(self):
        ctx = {
            "region_filter": {
                "name": "华东",
                "provinces": ["上海市", "浙江省", "江苏省"],
            },
        }
        result = generate_semantic_filters(ctx)
        self.assertIn("xzqmc IN", result["region_sql"])
        self.assertIn("'上海市'", result["region_sql"])

    def test_empty_context_no_filters(self):
        result = generate_semantic_filters({})
        self.assertEqual(result["sql_filters"], [])
        self.assertEqual(result["region_sql"], "")


class TestResolveIncludesSQLFilters(unittest.TestCase):
    """Test that resolve_semantic_context now includes sql_filters."""

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_has_sql_filters(self, _):
        result = resolve_semantic_context("统计耕地面积")
        self.assertIn("sql_filters", result)
        self.assertIsInstance(result["sql_filters"], list)
        self.assertTrue(len(result["sql_filters"]) > 0)

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_resolve_has_region_sql(self, _):
        result = resolve_semantic_context("华东地区")
        self.assertIn("region_sql", result)
        self.assertIn("xzqmc IN", result["region_sql"])


class TestBuildContextPromptEnhanced(unittest.TestCase):
    """Test enhanced build_context_prompt with SQL hints and confidence."""

    def test_sql_filter_in_prompt(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "hierarchy_matches": [{
                "domain": "LAND_USE", "level": "child",
                "parent": "农用地", "name": "耕地", "code_prefix": "01",
            }],
            "sql_filters": [{"description": "筛选耕地", "sql": "dlbm LIKE '01%'", "column_hint": "dlbm"}],
            "region_sql": "",
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("SQL筛选提示", prompt)
        self.assertIn("dlbm LIKE '01%'", prompt)

    def test_region_sql_in_prompt(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": {"name": "华东", "provinces": ["上海市"]},
            "metric_hints": [],
            "sql_filters": [],
            "region_sql": "xzqmc IN ('上海市')",
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("区域筛选", prompt)
        self.assertIn("xzqmc IN", prompt)

    def test_confidence_markers(self):
        resolved = {
            "sources": [],
            "matched_columns": {
                "_static_hints": [
                    {"semantic_domain": "SLOPE", "confidence": 0.5, "description": "坡度"},
                    {"semantic_domain": "AREA", "confidence": 0.1, "description": "面积"},
                ],
            },
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "sql_filters": [],
            "region_sql": "",
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("[高置信]", prompt)
        self.assertIn("[低置信]", prompt)

    def test_custom_domain_tag(self):
        resolved = {
            "sources": [],
            "matched_columns": {},
            "spatial_ops": [],
            "region_filter": None,
            "metric_hints": [],
            "hierarchy_matches": [{
                "domain": "SOIL_TYPE", "level": "child",
                "parent": "土壤", "name": "黑土", "code_prefix": "S01",
                "source": "custom",
            }],
            "sql_filters": [],
            "region_sql": "",
        }
        prompt = build_context_prompt(resolved)
        self.assertIn("[自定义域]", prompt)


class TestRegisterSemanticDomainTool(unittest.TestCase):
    """Test custom domain registration tool."""

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_db_error(self, _):
        result = register_semantic_domain("TEST_DOMAIN")
        self.assertEqual(result["status"], "error")
        self.assertIn("not configured", result["message"])

    def test_invalid_children_json(self):
        with patch("data_agent.semantic_layer.get_engine", return_value=None):
            result = register_semantic_domain("TEST", children_json="not json")
            self.assertEqual(result["status"], "error")

    def test_non_array_children(self):
        with patch("data_agent.semantic_layer.get_engine", return_value=MagicMock()):
            result = register_semantic_domain("TEST", children_json='{"a":1}')
            self.assertEqual(result["status"], "error")
            self.assertIn("JSON arrays", result["message"])


class TestDiscoverColumnEquivalences(unittest.TestCase):
    """Test column equivalence auto-discovery."""

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_no_db_error(self, _):
        result = discover_column_equivalences("test_table")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.semantic_layer.get_engine")
    @patch("data_agent.semantic_layer._inject_user_context")
    def test_discovers_dm_mc_pair(self, _ctx, mock_engine):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.return_value = [
            ("dlbm",), ("dlmc",), ("area",), ("geom",),
        ]

        result = discover_column_equivalences("land_parcels")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["equivalences"]), 1)
        self.assertEqual(result["equivalences"][0]["columns"], ["dlbm", "dlmc"])

    @patch("data_agent.semantic_layer.get_engine")
    @patch("data_agent.semantic_layer._inject_user_context")
    def test_discovers_multiple_pairs(self, _ctx, mock_engine):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.return_value = [
            ("dlbm",), ("dlmc",), ("xzqdm",), ("xzqmc",), ("area",),
        ]

        result = discover_column_equivalences("land_parcels")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["equivalences"]), 2)

    @patch("data_agent.semantic_layer.get_engine")
    @patch("data_agent.semantic_layer._inject_user_context")
    def test_no_pairs_found(self, _ctx, mock_engine):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.return_value = [
            ("id",), ("area",), ("geom",),
        ]

        result = discover_column_equivalences("simple_table")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["equivalences"]), 0)


class TestExportSemanticModel(unittest.TestCase):
    """Test semantic model export."""

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_export_without_db(self, _):
        result = export_semantic_model()
        self.assertEqual(result["status"], "success")
        model = result["model"]
        self.assertGreater(len(model["static_catalog"]["domains"]), 10)
        self.assertEqual(len(model["db_sources"]), 0)
        self.assertIn("语义模型概览", result["message"])

    @patch("data_agent.semantic_layer.get_engine", return_value=None)
    def test_export_summary_format(self, _):
        result = export_semantic_model(format="summary")
        self.assertIn("静态域", result["message"])
        self.assertIn("区域组", result["message"])


class TestDomainTableConstant(unittest.TestCase):
    """Verify new table constant exists."""

    def test_domains_table_name(self):
        self.assertEqual(T_SEMANTIC_DOMAINS, "agent_semantic_domains")


if __name__ == "__main__":
    unittest.main()
