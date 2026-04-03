"""Tests for Fusion v2.0 — Explainability module.

Covers: add_explainability_fields, generate_quality_heatmap,
        generate_lineage_trace, explain_decision, _classify_quality
"""

import json
import os
import shutil
import tempfile
import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon


def _make_test_gdf(n: int = 5, with_confidence: bool = False) -> gpd.GeoDataFrame:
    """Create a small test GeoDataFrame."""
    data = {
        "ID": list(range(1, n + 1)),
        "VALUE": [float(i * 10) for i in range(1, n + 1)],
    }
    if with_confidence:
        # Vary confidence: low, medium, high
        confidences = [0.1, 0.2, 0.5, 0.8, 0.95][:n]
        data["_fusion_confidence"] = confidences

    geom = [Point(120 + i * 0.01, 30 + i * 0.01) for i in range(n)]
    return gpd.GeoDataFrame(data, geometry=geom, crs="EPSG:4326")


def _make_polygon_gdf(n: int = 5, with_confidence: bool = False) -> gpd.GeoDataFrame:
    """Create a test GeoDataFrame with polygons."""
    data = {"ID": list(range(1, n + 1))}
    if with_confidence:
        data["_fusion_confidence"] = [0.1, 0.4, 0.6, 0.85, 0.99][:n]

    geom = [
        Polygon([(120 + i * 0.01, 30), (120 + i * 0.01 + 0.01, 30),
                 (120 + i * 0.01 + 0.01, 30.01), (120 + i * 0.01, 30.01)])
        for i in range(n)
    ]
    return gpd.GeoDataFrame(data, geometry=geom, crs="EPSG:4326")


class TestAddExplainabilityFields(unittest.TestCase):
    """Test add_explainability_fields."""

    def test_basic_injection(self):
        from data_agent.fusion.explainability import (
            add_explainability_fields,
            COL_CONFIDENCE, COL_SOURCES, COL_CONFLICTS, COL_METHOD,
        )
        gdf = _make_test_gdf()
        meta = {"strategy": "spatial_join", "sources": ["/data/a.geojson", "/data/b.csv"]}
        result = add_explainability_fields(gdf, meta)

        self.assertIn(COL_CONFIDENCE, result.columns)
        self.assertIn(COL_SOURCES, result.columns)
        self.assertIn(COL_CONFLICTS, result.columns)
        self.assertIn(COL_METHOD, result.columns)
        self.assertEqual(result[COL_CONFIDENCE].iloc[0], 1.0)
        self.assertEqual(result[COL_METHOD].iloc[0], "spatial_join")
        # Sources should be basenames
        sources = json.loads(result[COL_SOURCES].iloc[0])
        self.assertEqual(sources, ["a.geojson", "b.csv"])

    def test_does_not_overwrite_existing_confidence(self):
        from data_agent.fusion.explainability import add_explainability_fields, COL_CONFIDENCE
        gdf = _make_test_gdf(with_confidence=True)
        meta = {"strategy": "overlay", "sources": []}
        result = add_explainability_fields(gdf, meta)
        # Should preserve existing confidence values
        self.assertAlmostEqual(result[COL_CONFIDENCE].iloc[0], 0.1)

    def test_empty_gdf(self):
        from data_agent.fusion.explainability import add_explainability_fields
        gdf = gpd.GeoDataFrame(columns=["ID", "geometry"])
        meta = {"strategy": "test", "sources": []}
        result = add_explainability_fields(gdf, meta)
        self.assertTrue(result.empty)

    def test_missing_metadata_keys(self):
        from data_agent.fusion.explainability import add_explainability_fields, COL_METHOD
        gdf = _make_test_gdf(n=2)
        result = add_explainability_fields(gdf, {})
        self.assertEqual(result[COL_METHOD].iloc[0], "unknown")


class TestGenerateQualityHeatmap(unittest.TestCase):
    """Test generate_quality_heatmap."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.tmp):
            shutil.rmtree(self.tmp)

    def test_generates_file(self):
        from data_agent.fusion.explainability import generate_quality_heatmap
        from unittest.mock import patch
        gdf = _make_polygon_gdf(with_confidence=True)
        # Mock _generate_output_path at the gis_processors level (deferred import)
        mock_path = os.path.join(self.tmp, "heatmap.geojson")
        with patch("data_agent.gis_processors._generate_output_path", return_value=mock_path):
            result = generate_quality_heatmap(gdf, self.tmp)
        self.assertTrue(os.path.exists(result))
        # Verify output is valid GeoJSON
        loaded = gpd.read_file(result)
        self.assertIn("_quality_level", loaded.columns)
        self.assertEqual(len(loaded), 5)

    def test_quality_levels_correct(self):
        from data_agent.fusion.explainability import generate_quality_heatmap
        from unittest.mock import patch
        gdf = _make_polygon_gdf(with_confidence=True)
        mock_path = os.path.join(self.tmp, "heatmap.geojson")
        with patch("data_agent.gis_processors._generate_output_path", return_value=mock_path):
            result = generate_quality_heatmap(gdf, self.tmp)
        loaded = gpd.read_file(result)
        levels = loaded["_quality_level"].tolist()
        # 0.1 → low, 0.4 → medium, 0.6 → medium, 0.85 → high, 0.99 → high
        self.assertEqual(levels[0], "low")
        self.assertEqual(levels[1], "medium")
        self.assertEqual(levels[2], "medium")
        self.assertEqual(levels[3], "high")
        self.assertEqual(levels[4], "high")

    def test_empty_gdf_returns_empty(self):
        from data_agent.fusion.explainability import generate_quality_heatmap
        gdf = gpd.GeoDataFrame(columns=["_fusion_confidence", "geometry"])
        result = generate_quality_heatmap(gdf, self.tmp)
        self.assertEqual(result, "")

    def test_missing_confidence_column(self):
        from data_agent.fusion.explainability import generate_quality_heatmap
        gdf = _make_test_gdf()
        result = generate_quality_heatmap(gdf, self.tmp)
        self.assertEqual(result, "")


class TestGenerateLineageTrace(unittest.TestCase):
    """Test generate_lineage_trace."""

    def test_basic_trace(self):
        from data_agent.fusion.explainability import generate_lineage_trace
        from data_agent.fusion.models import FusionSource

        sources = [
            FusionSource(file_path="/data/a.geojson", data_type="vector", row_count=100, crs="EPSG:4326"),
            FusionSource(file_path="/data/b.csv", data_type="tabular", row_count=50),
        ]
        trace = generate_lineage_trace(
            sources=sources,
            strategy="attribute_join",
            alignment_log=["CRS unified to EPSG:4326"],
            row_count=80,
            duration_s=1.5,
        )
        self.assertEqual(trace["strategy"], "attribute_join")
        self.assertEqual(len(trace["sources"]), 2)
        self.assertEqual(trace["sources"][0]["file"], "a.geojson")
        self.assertEqual(trace["output_rows"], 80)
        self.assertIn("timestamp", trace)

    def test_with_temporal_and_conflict(self):
        from data_agent.fusion.explainability import generate_lineage_trace
        trace = generate_lineage_trace(
            sources=["file_a.shp"],
            strategy="spatial_join",
            alignment_log=[],
            row_count=10,
            duration_s=0.5,
            temporal_log=["Standardized timestamps to UTC"],
            conflict_summary={"resolved": 3, "strategy": "source_priority"},
        )
        self.assertIn("temporal_alignment", trace)
        self.assertIn("conflict_resolution", trace)
        self.assertEqual(trace["conflict_resolution"]["resolved"], 3)

    def test_string_sources(self):
        from data_agent.fusion.explainability import generate_lineage_trace
        trace = generate_lineage_trace(
            sources=["a.geojson", "b.geojson"],
            strategy="overlay",
            alignment_log=[],
            row_count=0,
            duration_s=0.1,
        )
        self.assertEqual(trace["sources"][0]["file"], "a.geojson")


class TestExplainDecision(unittest.TestCase):
    """Test explain_decision."""

    def test_basic_explanation(self):
        from data_agent.fusion.explainability import explain_decision
        row = {
            "_fusion_confidence": 0.85,
            "_fusion_sources": '["a.geojson", "b.csv"]',
            "_fusion_method": "spatial_join",
            "_fusion_conflicts": "{}",
        }
        text = explain_decision(row)
        self.assertIn("a.geojson", text)
        self.assertIn("spatial_join", text)
        self.assertIn("0.85", text)
        self.assertIn("high", text)

    def test_with_conflicts(self):
        from data_agent.fusion.explainability import explain_decision
        row = {
            "_fusion_confidence": 0.5,
            "_fusion_sources": '["src1.shp"]',
            "_fusion_method": "overlay",
            "_fusion_conflicts": '{"area": "conflict_detail"}',
        }
        text = explain_decision(row)
        self.assertIn("冲突", text)

    def test_missing_columns(self):
        from data_agent.fusion.explainability import explain_decision
        text = explain_decision({})
        self.assertIn("unknown", text)

    def test_list_sources(self):
        from data_agent.fusion.explainability import explain_decision
        row = {
            "_fusion_confidence": 0.9,
            "_fusion_sources": ["a.shp", "b.shp"],
            "_fusion_method": "nearest_join",
            "_fusion_conflicts": {},
        }
        text = explain_decision(row)
        self.assertIn("a.shp", text)


class TestClassifyQuality(unittest.TestCase):
    """Test _classify_quality helper."""

    def test_levels(self):
        from data_agent.fusion.explainability import _classify_quality
        self.assertEqual(_classify_quality(0.0), "low")
        self.assertEqual(_classify_quality(0.29), "low")
        self.assertEqual(_classify_quality(0.3), "medium")
        self.assertEqual(_classify_quality(0.69), "medium")
        self.assertEqual(_classify_quality(0.7), "high")
        self.assertEqual(_classify_quality(1.0), "high")


if __name__ == "__main__":
    unittest.main()
