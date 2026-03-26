"""Tests for DefectTaxonomy — 缺陷分类法."""

import unittest
from data_agent.standard_registry import (
    DefectTaxonomy,
    DefectType,
    DefectCategory,
    SeverityLevel,
)


class TestDefectTaxonomyLoading(unittest.TestCase):
    """Test taxonomy loads correctly from YAML."""

    @classmethod
    def setUpClass(cls):
        DefectTaxonomy.reset()

    def test_all_defects_loaded(self):
        defects = DefectTaxonomy.all_defects()
        self.assertGreaterEqual(len(defects), 28, "Should load at least 28 defect types")

    def test_all_categories_loaded(self):
        cats = DefectTaxonomy.all_categories()
        self.assertEqual(len(cats), 5)
        cat_ids = {c.id for c in cats}
        self.assertEqual(cat_ids, {
            "format_error", "precision_deviation", "topology_error",
            "info_missing", "norm_violation",
        })

    def test_severity_levels_loaded(self):
        levels = DefectTaxonomy.all_severity_levels()
        self.assertEqual(len(levels), 3)
        codes = {s.code for s in levels}
        self.assertEqual(codes, {"A", "B", "C"})

    def test_severity_weights(self):
        self.assertEqual(DefectTaxonomy.get_severity_weight("A"), 12)
        self.assertEqual(DefectTaxonomy.get_severity_weight("B"), 4)
        self.assertEqual(DefectTaxonomy.get_severity_weight("C"), 1)
        self.assertEqual(DefectTaxonomy.get_severity_weight("X"), 1)  # unknown


class TestDefectTaxonomyQueries(unittest.TestCase):
    """Test query methods."""

    def test_get_by_code(self):
        d = DefectTaxonomy.get_by_code("FMT-001")
        self.assertIsNotNone(d)
        self.assertEqual(d.code, "FMT-001")
        self.assertEqual(d.category, "format_error")
        self.assertTrue(d.auto_fixable)

    def test_get_by_code_not_found(self):
        d = DefectTaxonomy.get_by_code("NONEXIST-999")
        self.assertIsNone(d)

    def test_get_by_category(self):
        fmt_defects = DefectTaxonomy.get_by_category("format_error")
        self.assertGreaterEqual(len(fmt_defects), 5)
        for d in fmt_defects:
            self.assertEqual(d.category, "format_error")

    def test_get_by_severity(self):
        critical = DefectTaxonomy.get_by_severity("A")
        self.assertGreater(len(critical), 0)
        for d in critical:
            self.assertEqual(d.severity, "A")

    def test_get_auto_fixable(self):
        fixable = DefectTaxonomy.get_auto_fixable()
        self.assertGreater(len(fixable), 0)
        for d in fixable:
            self.assertTrue(d.auto_fixable)
            self.assertNotEqual(d.fix_strategy, "")

    def test_get_for_product_cad(self):
        cad_defects = DefectTaxonomy.get_for_product("CAD")
        self.assertGreater(len(cad_defects), 5)
        for d in cad_defects:
            self.assertIn("CAD", d.product_types)

    def test_get_for_product_3d_model(self):
        model_defects = DefectTaxonomy.get_for_product("3D_MODEL")
        self.assertGreater(len(model_defects), 0)

    def test_get_for_product_nonexistent(self):
        result = DefectTaxonomy.get_for_product("NONEXIST")
        self.assertEqual(len(result), 0)


class TestDefectTaxonomyScoring(unittest.TestCase):
    """Test quality score computation."""

    def test_perfect_score(self):
        result = DefectTaxonomy.compute_quality_score([], total_items=100)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["grade"], "优秀")

    def test_minor_defects(self):
        # 3 minor (C) defects: weight = 3*1 = 3, score = 100 - 3/100*100 = 97
        result = DefectTaxonomy.compute_quality_score(
            ["NRM-001", "NRM-002", "FMT-006"], total_items=100
        )
        self.assertEqual(result["score"], 97.0)
        self.assertEqual(result["grade"], "优秀")

    def test_major_defects(self):
        # 2 major (B) defects: weight = 2*4 = 8, score = 92
        result = DefectTaxonomy.compute_quality_score(
            ["FMT-001", "PRE-004"], total_items=100
        )
        self.assertEqual(result["score"], 92.0)
        self.assertEqual(result["grade"], "优秀")

    def test_critical_defects(self):
        # 1 critical (A): weight = 12, score = 88
        result = DefectTaxonomy.compute_quality_score(
            ["PRE-001"], total_items=100
        )
        self.assertEqual(result["score"], 88.0)
        self.assertEqual(result["grade"], "良好")

    def test_mixed_defects(self):
        # 1A(12) + 2B(8) + 3C(3) = 23, score = 77
        result = DefectTaxonomy.compute_quality_score(
            ["TOP-005", "FMT-001", "MIS-002", "NRM-001", "NRM-002", "FMT-006"],
            total_items=100,
        )
        self.assertEqual(result["score"], 77.0)
        self.assertEqual(result["grade"], "良好")
        self.assertEqual(result["severity_counts"]["A"], 1)
        self.assertEqual(result["severity_counts"]["B"], 2)
        self.assertEqual(result["severity_counts"]["C"], 3)

    def test_failing_score(self):
        # Many critical defects
        codes = ["PRE-001", "PRE-002", "TOP-005", "FMT-004", "MIS-001"]
        result = DefectTaxonomy.compute_quality_score(codes, total_items=100)
        self.assertLess(result["score"], 60)
        self.assertEqual(result["grade"], "不合格")

    def test_zero_total_items(self):
        result = DefectTaxonomy.compute_quality_score(["FMT-001"], total_items=0)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["grade"], "不合格")


class TestDefectTaxonomySummary(unittest.TestCase):
    """Test summary output."""

    def test_list_summary(self):
        summary = DefectTaxonomy.list_summary()
        self.assertGreater(len(summary), 0)
        first = summary[0]
        self.assertIn("code", first)
        self.assertIn("category", first)
        self.assertIn("severity", first)
        self.assertIn("name", first)
        self.assertIn("auto_fixable", first)
        self.assertIn("product_types", first)


class TestDefectTaxonomyReset(unittest.TestCase):
    """Test reset functionality."""

    def test_reset_and_reload(self):
        DefectTaxonomy.reset()
        self.assertEqual(len(DefectTaxonomy._defects), 0)
        # Should auto-reload on next query
        defects = DefectTaxonomy.all_defects()
        self.assertGreater(len(defects), 0)


if __name__ == "__main__":
    unittest.main()
