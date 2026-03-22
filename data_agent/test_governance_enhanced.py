"""Tests for enhanced governance tools (v14.5 P0 治理深化)."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, Polygon


def _make_gdf(**extra_cols):
    data = {"geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]}
    data.update(extra_cols)
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


def _make_polygon_gdf(**extra_cols):
    polys = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
    ]
    data = {"geometry": polys}
    data.update(extra_cols)
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# Enhanced check_field_standards
# ---------------------------------------------------------------------------

class TestEnhancedFieldStandards(unittest.TestCase):
    @patch("data_agent.gis_processors.gpd.read_file")
    def test_missing_mandatory_fields(self, mock_read):
        """M fields not in data should be flagged."""
        mock_read.return_value = _make_gdf(BSM=["001", "002", "003"], YSDM=["a", "b", "c"])
        from data_agent.gis_processors import check_field_standards
        result = check_field_standards("/test.shp", "dltb_2023")
        self.assertIn("DLBM", result.get("missing_mandatory", []))
        self.assertIn("TBMJ", result.get("missing_mandatory", []))

    @patch("data_agent.gis_processors.gpd.read_file")
    def test_mandatory_nulls(self, mock_read):
        """M fields with null values should be caught."""
        mock_read.return_value = _make_gdf(
            BSM=["001", None, "003"], YSDM=["a", "b", "c"],
            DLBM=["0101", "0102", None],
        )
        from data_agent.gis_processors import check_field_standards
        result = check_field_standards("/test.shp", "dltb_2023")
        null_fields = [m["field"] for m in result.get("mandatory_nulls", [])]
        self.assertIn("BSM", null_fields)
        self.assertIn("DLBM", null_fields)

    @patch("data_agent.gis_processors.gpd.read_file")
    def test_type_mismatch(self, mock_read):
        """Numeric field stored as string should be flagged."""
        mock_read.return_value = _make_gdf(
            BSM=["001", "002", "003"],
            TBMJ=["abc", "def", "ghi"],  # should be numeric
        )
        from data_agent.gis_processors import check_field_standards
        result = check_field_standards("/test.shp", "dltb_2023")
        type_issues = [t["field"] for t in result.get("type_mismatches", [])]
        self.assertIn("TBMJ", type_issues)

    @patch("data_agent.gis_processors.gpd.read_file")
    def test_compliance_rate(self, mock_read):
        mock_read.return_value = _make_gdf(BSM=["001", "002", "003"])
        from data_agent.gis_processors import check_field_standards
        result = check_field_standards("/test.shp", "dltb_2023")
        self.assertIn("compliance_rate", result)
        self.assertIsInstance(result["compliance_rate"], float)

    @patch("data_agent.gis_processors.gpd.read_file")
    def test_length_violations(self, mock_read):
        long_name = "A" * 100  # 100 chars, exceeds max_length 60
        mock_read.return_value = _make_gdf(
            BSM=["001", "002", "003"],
            QSDWMC=["正常", "正常", long_name],
        )
        from data_agent.gis_processors import check_field_standards
        result = check_field_standards("/test.shp", "dltb_2023")
        length_fields = [lv["field"] for lv in result.get("length_violations", [])]
        self.assertIn("QSDWMC", length_fields)


# ---------------------------------------------------------------------------
# Formula validation
# ---------------------------------------------------------------------------

class TestValidateFieldFormulas(unittest.TestCase):
    @patch("data_agent.toolsets.governance_tools.gpd.read_file")
    def test_formula_pass(self, mock_read):
        mock_read.return_value = _make_polygon_gdf(
            TBMJ=[100.0, 200.0, 300.0],
            KCMJ=[10.0, 20.0, 30.0],
            TBDLMJ=[90.0, 180.0, 270.0],
        )
        from data_agent.toolsets.governance_tools import validate_field_formulas
        result = json.loads(validate_field_formulas("/test.shp", standard_id="dltb_2023"))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["all_pass"])

    @patch("data_agent.toolsets.governance_tools.gpd.read_file")
    def test_formula_fail(self, mock_read):
        mock_read.return_value = _make_polygon_gdf(
            TBMJ=[100.0, 200.0, 300.0],
            KCMJ=[10.0, 20.0, 30.0],
            TBDLMJ=[90.0, 999.0, 270.0],  # second row wrong
        )
        from data_agent.toolsets.governance_tools import validate_field_formulas
        result = json.loads(validate_field_formulas("/test.shp", standard_id="dltb_2023"))
        self.assertFalse(result["all_pass"])
        self.assertEqual(result["results"][0]["violations"], 1)

    @patch("data_agent.toolsets.governance_tools.gpd.read_file")
    def test_formula_missing_fields(self, mock_read):
        mock_read.return_value = _make_polygon_gdf(TBMJ=[100.0, 200.0, 300.0])
        from data_agent.toolsets.governance_tools import validate_field_formulas
        result = json.loads(validate_field_formulas("/test.shp", standard_id="dltb_2023"))
        self.assertEqual(result["results"][0]["status"], "skip")


# ---------------------------------------------------------------------------
# Gap Matrix
# ---------------------------------------------------------------------------

class TestGapMatrix(unittest.TestCase):
    @patch("data_agent.toolsets.governance_tools.gpd.read_file")
    def test_gap_matrix_basic(self, mock_read):
        mock_read.return_value = _make_polygon_gdf(
            BSM=["001", "002", "003"],
            DLBM=["0101", "0102", "0103"],
            EXTRA_COL=["x", "y", "z"],
        )
        from data_agent.toolsets.governance_tools import generate_gap_matrix
        result = json.loads(generate_gap_matrix("/test.shp", "dltb_2023"))
        self.assertEqual(result["status"], "ok")
        summary = result["summary"]
        self.assertEqual(summary["total_standard_fields"], 30)
        self.assertGreater(summary["missing"], 0)
        self.assertGreater(summary["extra"], 0)
        statuses = [m["status"] for m in result["matrix"]]
        self.assertIn("present", statuses)
        self.assertIn("missing", statuses)
        self.assertIn("extra", statuses)

    def test_gap_matrix_unknown_standard(self):
        from data_agent.toolsets.governance_tools import generate_gap_matrix
        result = json.loads(generate_gap_matrix("/test.shp", "nonexistent"))
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# Governance Plan
# ---------------------------------------------------------------------------

class TestGovernancePlan(unittest.TestCase):
    @patch("data_agent.utils._load_spatial_data")
    @patch("data_agent.gis_processors.gpd.read_file")
    def test_plan_generates_steps(self, mock_gpd_read, mock_load):
        gdf = _make_polygon_gdf(BSM=["001", "002", "003"])
        mock_load.return_value = gdf
        mock_gpd_read.return_value = gdf
        from data_agent.toolsets.governance_tools import generate_governance_plan
        result = json.loads(generate_governance_plan("/test.shp", "dltb_2023"))
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["step_count"], 0)
        tools = [s["tool"] for s in result["governance_steps"]]
        self.assertIn("add_missing_fields", tools)


# ---------------------------------------------------------------------------
# Batch Profile
# ---------------------------------------------------------------------------

class TestBatchProfile(unittest.TestCase):
    @patch("data_agent.toolsets.exploration_tools.describe_geodataframe")
    @patch("data_agent.toolsets.exploration_tools._resolve_path", return_value="/test_dir")
    @patch("os.walk")
    @patch("os.path.isdir", return_value=True)
    def test_batch_basic(self, mock_isdir, mock_walk, mock_resolve, mock_describe):
        mock_walk.return_value = [
            ("/test_dir", [], ["a.shp", "b.geojson", "c.csv"]),
        ]
        mock_describe.return_value = {
            "status": "success",
            "summary": {
                "num_features": 100, "crs": "EPSG:4326",
                "data_health": {"severity": "pass", "warnings": []},
            },
        }
        from data_agent.toolsets.exploration_tools import batch_profile_datasets
        result = json.loads(batch_profile_datasets("/test_dir"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["file_count"], 3)
        self.assertEqual(result["summary"]["total_records"], 300)

    @patch("data_agent.toolsets.exploration_tools._resolve_path", return_value="/empty_dir")
    @patch("os.walk", return_value=[("/empty_dir", [], [])])
    @patch("os.path.isdir", return_value=True)
    def test_batch_empty_dir(self, mock_isdir, mock_walk, mock_resolve):
        from data_agent.toolsets.exploration_tools import batch_profile_datasets
        result = json.loads(batch_profile_datasets("/empty_dir"))
        self.assertEqual(result["file_count"], 0)


# ---------------------------------------------------------------------------
# Standard Registry formulas
# ---------------------------------------------------------------------------

class TestStandardFormulas(unittest.TestCase):
    def test_dltb_has_formulas(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        self.assertIsNotNone(std)
        self.assertGreater(len(std.formulas), 0)
        self.assertIn("TBDLMJ", std.formulas[0]["expr"])

    def test_code_mapping_load(self):
        from data_agent.standard_registry import StandardRegistry
        mapping = StandardRegistry.get_code_mapping("clcd_to_gbt21010")
        self.assertIsNotNone(mapping)
        self.assertIn("mapping", mapping)
        self.assertEqual(mapping["mapping"]["1"], "0103")  # 耕地→旱地


if __name__ == "__main__":
    unittest.main()
