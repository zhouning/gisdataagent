"""Tests for Fusion v2.0 — Temporal Alignment module.

Covers: TemporalAligner — detect, standardize, interpolate,
        time windows, event sequences, change detection, validation, pre_align.
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon


def _make_temporal_gdf(n: int = 5) -> gpd.GeoDataFrame:
    """Create GeoDataFrame with a timestamp column."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    data = {
        "ID": list(range(1, n + 1)),
        "VALUE": [float(i * 10) for i in range(1, n + 1)],
        "timestamp": [base + timedelta(hours=i) for i in range(n)],
    }
    geom = [Point(120 + i * 0.01, 30 + i * 0.01) for i in range(n)]
    return gpd.GeoDataFrame(data, geometry=geom, crs="EPSG:4326")


def _make_string_date_gdf() -> gpd.GeoDataFrame:
    """Create GeoDataFrame with string date column."""
    data = {
        "ID": [1, 2, 3],
        "VALUE": [10, 20, 30],
        "date": ["2024-01-01", "2024-06-15", "2024-12-31"],
    }
    geom = [Point(120 + i * 0.01, 30) for i in range(3)]
    return gpd.GeoDataFrame(data, geometry=geom, crs="EPSG:4326")


class TestDetectTemporalColumns(unittest.TestCase):
    """Test TemporalAligner.detect_temporal_columns."""

    def test_detects_datetime_column(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        cols = ta.detect_temporal_columns(gdf)
        self.assertIn("timestamp", cols)

    def test_detects_string_date_column(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_string_date_gdf()
        cols = ta.detect_temporal_columns(gdf)
        self.assertIn("date", cols)

    def test_no_temporal_columns(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({"ID": [1], "VALUE": [10]},
                               geometry=[Point(0, 0)], crs="EPSG:4326")
        cols = ta.detect_temporal_columns(gdf)
        self.assertEqual(cols, [])

    def test_chinese_column_names(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({
            "ID": [1, 2],
            "采集时间": ["2024-01-01", "2024-06-15"],
        }, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326")
        cols = ta.detect_temporal_columns(gdf)
        self.assertIn("采集时间", cols)


class TestStandardizeTimestamps(unittest.TestCase):
    """Test TemporalAligner.standardize_timestamps."""

    def test_standardize_datetime(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        result = ta.standardize_timestamps(gdf, "timestamp")
        self.assertIn("_std_timestamp", result.columns)
        self.assertEqual(result["_std_timestamp"].notna().sum(), 5)

    def test_standardize_string_dates(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_string_date_gdf()
        result = ta.standardize_timestamps(gdf, "date")
        self.assertIn("_std_timestamp", result.columns)
        self.assertEqual(result["_std_timestamp"].notna().sum(), 3)

    def test_missing_column_warns(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        result = ta.standardize_timestamps(gdf, "nonexistent")
        self.assertNotIn("_std_timestamp", result.columns)

    def test_mixed_formats(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({
            "ID": [1, 2, 3],
            "date": ["2024-01-01", "2024/06/15", "20241231"],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4326")
        result = ta.standardize_timestamps(gdf, "date")
        parsed = result["_std_timestamp"].notna().sum()
        self.assertGreaterEqual(parsed, 2)  # At least ISO and slash format


class TestInterpolateTemporal(unittest.TestCase):
    """Test TemporalAligner.interpolate_temporal."""

    def test_nearest_interpolation(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        gdf = ta.standardize_timestamps(gdf, "timestamp")
        ref = datetime(2024, 1, 1, 2, 30, tzinfo=timezone.utc)
        result = ta.interpolate_temporal([gdf], ref, method="nearest")
        self.assertEqual(len(result), 1)
        self.assertGreater(len(result[0]), 0)

    def test_linear_interpolation(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        gdf = ta.standardize_timestamps(gdf, "timestamp")
        ref = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
        result = ta.interpolate_temporal([gdf], ref, method="linear")
        self.assertEqual(len(result), 1)

    def test_no_temporal_column(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({"ID": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        ref = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = ta.interpolate_temporal([gdf], ref)
        self.assertEqual(len(result[0]), 1)  # Unchanged


class TestDetectChanges(unittest.TestCase):
    """Test TemporalAligner.detect_changes."""

    def test_id_based_changes(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()

        gdf_t1 = gpd.GeoDataFrame({
            "FID": [1, 2, 3],
            "AREA": [100.0, 200.0, 300.0],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4326")

        gdf_t2 = gpd.GeoDataFrame({
            "FID": [2, 3, 4],
            "AREA": [200.0, 500.0, 400.0],  # ID=3 modified (300→500)
        }, geometry=[Point(1, 1), Point(2, 2), Point(3, 3)], crs="EPSG:4326")

        result = ta.detect_changes(gdf_t1, gdf_t2, id_column="FID")
        changes = result["_change_type"].value_counts().to_dict()
        self.assertEqual(changes.get("added", 0), 1)    # FID=4
        self.assertEqual(changes.get("removed", 0), 1)  # FID=1
        self.assertEqual(changes.get("modified", 0), 1)  # FID=3

    def test_no_changes(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({
            "FID": [1, 2],
            "AREA": [100.0, 200.0],
        }, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326")
        result = ta.detect_changes(gdf, gdf.copy(), id_column="FID")
        self.assertTrue((result["_change_type"] == "unchanged").all())


class TestValidateTemporalConsistency(unittest.TestCase):
    """Test TemporalAligner.validate_temporal_consistency."""

    def test_consistent_data(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        gdf = ta.standardize_timestamps(gdf, "timestamp")
        report = ta.validate_temporal_consistency(gdf)
        self.assertTrue(report["is_consistent"])
        self.assertEqual(report["parsed_count"], 5)

    def test_missing_column(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.GeoDataFrame({"ID": [1]}, geometry=[Point(0, 0)])
        report = ta.validate_temporal_consistency(gdf)
        self.assertFalse(report["is_consistent"])

    def test_with_nulls(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gdf = gpd.GeoDataFrame({
            "ID": [1, 2, 3],
            "_std_timestamp": [base, pd.NaT, base + timedelta(hours=2)],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        report = ta.validate_temporal_consistency(gdf)
        self.assertFalse(report["is_consistent"])
        self.assertTrue(any("null" in issue for issue in report["issues"]))

    def test_with_duplicates(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gdf = gpd.GeoDataFrame({
            "ID": [1, 2, 3],
            "_std_timestamp": [base, base, base + timedelta(hours=1)],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        report = ta.validate_temporal_consistency(gdf)
        self.assertTrue(any("duplicate" in issue for issue in report["issues"]))


class TestPreAlign(unittest.TestCase):
    """Test TemporalAligner.pre_align integration method."""

    def test_auto_detect_and_standardize(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        aligned_data = [("vector", gdf)]
        config = {}  # auto-detect
        result_data, log = ta.pre_align(aligned_data, [], config)
        self.assertEqual(len(result_data), 1)
        self.assertTrue(any("Auto-detected" in entry or "No temporal" in entry for entry in log))

    def test_explicit_column(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = _make_temporal_gdf()
        aligned_data = [("vector", gdf)]
        config = {"time_column": "timestamp"}
        result_data, log = ta.pre_align(aligned_data, [], config)
        self.assertTrue(any("Standardized" in entry for entry in log))

    def test_non_vector_skipped(self):
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        aligned_data = [("raster", "some_raster_data")]
        config = {"time_column": "timestamp"}
        result_data, log = ta.pre_align(aligned_data, [], config)
        self.assertEqual(result_data[0][1], "some_raster_data")


if __name__ == "__main__":
    unittest.main()
