"""Tests for DataCleaningToolset (v14.5)."""
import json
import unittest
from unittest.mock import patch, MagicMock

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point


def _make_gdf(**extra_cols):
    """Helper: build a small test GeoDataFrame."""
    data = {"geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]}
    data.update(extra_cols)
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


class TestFillNullValues(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/test_out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_fill_default(self, mock_load, mock_out):
        gdf = _make_gdf(name=[None, "B", None])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import fill_null_values
            result = json.loads(fill_null_values("/test.shp", "name", "default", "未知"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["null_filled"], 2)

    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_fill_mean(self, mock_load, mock_out):
        gdf = _make_gdf(value=[10.0, None, 30.0])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import fill_null_values
            result = json.loads(fill_null_values("/test.shp", "value", "mean"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["null_filled"], 1)

    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_field_not_exists(self, mock_load):
        mock_load.return_value = _make_gdf(name=["A", "B", "C"])
        from data_agent.toolsets.data_cleaning_tools import fill_null_values
        result = json.loads(fill_null_values("/test.shp", "nonexistent"))
        self.assertEqual(result["status"], "error")

    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_no_nulls(self, mock_load):
        mock_load.return_value = _make_gdf(name=["A", "B", "C"])
        from data_agent.toolsets.data_cleaning_tools import fill_null_values
        result = json.loads(fill_null_values("/test.shp", "name"))
        self.assertEqual(result["null_count"], 0)


class TestMapFieldCodes(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_basic_mapping(self, mock_load, mock_out):
        gdf = _make_gdf(code=["1", "2", "3"])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import map_field_codes
            result = json.loads(map_field_codes(
                "/test.shp", "code",
                '{"1": "0101", "2": "0201"}',
                "keep",
            ))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mapped_count"], 2)

    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_invalid_json(self, mock_load):
        mock_load.return_value = _make_gdf(code=["1", "2", "3"])
        from data_agent.toolsets.data_cleaning_tools import map_field_codes
        result = json.loads(map_field_codes("/test.shp", "code", "not json"))
        self.assertEqual(result["status"], "error")


class TestRenameFields(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_rename(self, mock_load, mock_out):
        gdf = _make_gdf(old_name=["A", "B", "C"])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import rename_fields
            result = json.loads(rename_fields("/test.shp", '{"old_name": "DLMC"}'))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["renamed"], {"old_name": "DLMC"})

    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_rename_nonexistent(self, mock_load):
        mock_load.return_value = _make_gdf(name=["A", "B", "C"])
        from data_agent.toolsets.data_cleaning_tools import rename_fields
        result = json.loads(rename_fields("/test.shp", '{"nonexistent": "new"}'))
        self.assertEqual(result["status"], "error")


class TestCastFieldType(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_to_string(self, mock_load, mock_out):
        gdf = _make_gdf(num=[1, 2, 3])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import cast_field_type
            result = json.loads(cast_field_type("/test.shp", "num", "string"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["to_type"], "string")

    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_to_float_with_errors(self, mock_load, mock_out):
        gdf = _make_gdf(val=["1.5", "abc", "3.0"])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import cast_field_type
            result = json.loads(cast_field_type("/test.shp", "val", "float"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["conversion_failures"], 1)


class TestClipOutliers(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_clip_strategy(self, mock_load, mock_out):
        gdf = _make_gdf(area=[100.0, 5000.0, 200.0])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import clip_outliers
            result = json.loads(clip_outliers("/test.shp", "area", "50", "1000", "clip"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["outliers_affected"], 1)

    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_remove_strategy(self, mock_load, mock_out):
        gdf = _make_gdf(area=[100.0, 5000.0, 200.0])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import clip_outliers
            result = json.loads(clip_outliers("/test.shp", "area", "50", "1000", "remove"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["remaining_rows"], 2)


class TestStandardizeCrs(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_already_correct(self, mock_load, mock_out):
        gdf = _make_gdf(name=["A", "B", "C"])
        mock_load.return_value = gdf
        from data_agent.toolsets.data_cleaning_tools import standardize_crs
        result = json.loads(standardize_crs("/test.shp", "EPSG:4326"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("已是目标坐标系", result.get("message", ""))


class TestAddMissingFields(unittest.TestCase):
    @patch("data_agent.toolsets.data_cleaning_tools._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_adds_fields(self, mock_load, mock_out):
        gdf = _make_gdf(BSM=["001", "002", "003"])
        mock_load.return_value = gdf
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.toolsets.data_cleaning_tools import add_missing_fields
            result = json.loads(add_missing_fields("/test.shp", "dltb_2023"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("DLBM", result["added_fields"])
        self.assertIn("TBMJ", result["added_fields"])
        self.assertGreater(len(result["added_fields"]), 20)

    @patch("data_agent.toolsets.data_cleaning_tools._load_spatial_data")
    def test_unknown_standard(self, mock_load):
        mock_load.return_value = _make_gdf()
        from data_agent.toolsets.data_cleaning_tools import add_missing_fields
        result = json.loads(add_missing_fields("/test.shp", "nonexistent"))
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
