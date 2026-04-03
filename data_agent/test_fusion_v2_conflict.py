"""Tests for Fusion v2.0 — Conflict Resolution module.

Covers: ConflictResolver — detect, resolve (6 strategies),
        confidence scoring, source annotation, resolve_and_annotate.
"""

import json
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


def _make_conflict_gdf() -> gpd.GeoDataFrame:
    """Create GeoDataFrame simulating merge with _left/_right suffix conflicts."""
    return gpd.GeoDataFrame({
        "ID": [1, 2, 3],
        "AREA_left": [100.0, 200.0, 300.0],
        "AREA_right": [100.0, 250.0, 350.0],  # Row 1,2 conflict
        "NAME_left": ["A", "B", "C"],
        "NAME_right": ["A", "B2", "C"],  # Row 1 conflict
    }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4326")


class TestDetectConflicts(unittest.TestCase):
    """Test ConflictResolver.detect_conflicts."""

    def test_detects_conflicts(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        gdf = _make_conflict_gdf()
        source_columns = {
            "AREA": ["AREA_left", "AREA_right"],
            "NAME": ["NAME_left", "NAME_right"],
        }
        conflicts = cr.detect_conflicts(gdf, source_columns)
        self.assertIn("AREA", conflicts)
        self.assertEqual(len(conflicts["AREA"]), 2)  # Rows 1, 2
        self.assertIn("NAME", conflicts)
        self.assertEqual(len(conflicts["NAME"]), 1)  # Row 1

    def test_no_conflicts(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        gdf = gpd.GeoDataFrame({
            "VAL_left": [1.0, 2.0],
            "VAL_right": [1.0, 2.0],
        }, geometry=[Point(0, 0), Point(1, 1)])
        conflicts = cr.detect_conflicts(gdf, {"VAL": ["VAL_left", "VAL_right"]})
        self.assertEqual(conflicts, {})


class TestResolveStrategies(unittest.TestCase):
    """Test individual resolution strategies."""

    def test_source_priority(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(
            strategy="source_priority",
            source_priorities={"AREA_left": 10, "AREA_right": 5},
        )
        gdf = _make_conflict_gdf()
        source_columns = {"AREA": ["AREA_left", "AREA_right"]}
        conflicts = cr.detect_conflicts(gdf, source_columns)
        result = cr.resolve_attribute_conflicts(gdf, conflicts, source_columns)
        # Priority higher for _left, so _left values should win
        self.assertEqual(result.at[1, "AREA"], 200.0)
        self.assertEqual(result.at[2, "AREA"], 300.0)

    def test_voting_numeric(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(strategy="voting")
        gdf = gpd.GeoDataFrame({
            "V_left": [10.0],
            "V_right": [20.0],
        }, geometry=[Point(0, 0)])
        source_columns = {"V": ["V_left", "V_right"]}
        conflicts = cr.detect_conflicts(gdf, source_columns)
        result = cr.resolve_attribute_conflicts(gdf, conflicts, source_columns)
        self.assertAlmostEqual(result.at[0, "V"], 15.0)  # Mean of 10 and 20

    def test_voting_categorical(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(strategy="voting")
        gdf = gpd.GeoDataFrame({
            "src0_TYPE": ["residential", "commercial", "residential"],
            "src1_TYPE": ["residential", "industrial", "industrial"],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        source_columns = {"TYPE": ["src0_TYPE", "src1_TYPE"]}
        conflicts = cr.detect_conflicts(gdf, source_columns)
        result = cr.resolve_attribute_conflicts(gdf, conflicts, source_columns)
        # Row 1: commercial vs industrial → both count 1, picks first (commercial or industrial)
        self.assertIn(result.at[1, "TYPE"], ["commercial", "industrial"])

    def test_latest_wins(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(
            strategy="latest_wins",
            source_metadata={
                "AREA_left": {"timestamp": "2024-01-01"},
                "AREA_right": {"timestamp": "2024-06-01"},
            },
        )
        gdf = _make_conflict_gdf()
        source_columns = {"AREA": ["AREA_left", "AREA_right"]}
        conflicts = cr.detect_conflicts(gdf, source_columns)
        result = cr.resolve_attribute_conflicts(gdf, conflicts, source_columns)
        # Right is more recent
        self.assertEqual(result.at[1, "AREA"], 250.0)

    def test_user_defined_resolver(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        def my_resolver(col, values):
            return max(values.values())
        cr = ConflictResolver(strategy="user_defined", user_resolver=my_resolver)
        gdf = _make_conflict_gdf()
        source_columns = {"AREA": ["AREA_left", "AREA_right"]}
        conflicts = cr.detect_conflicts(gdf, source_columns)
        result = cr.resolve_attribute_conflicts(gdf, conflicts, source_columns)
        self.assertEqual(result.at[1, "AREA"], 250.0)  # max(200, 250)
        self.assertEqual(result.at[2, "AREA"], 350.0)  # max(300, 350)


class TestConfidenceScoring(unittest.TestCase):
    """Test ConflictResolver.compute_confidence_scores."""

    def test_base_confidence(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(
            source_metadata={
                "src1": {"timeliness": 0.9, "precision": 0.8, "completeness": 0.7},
            }
        )
        gdf = gpd.GeoDataFrame({"V": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
        result = cr.compute_confidence_scores(gdf)
        self.assertIn("_fusion_confidence", result.columns)
        self.assertGreater(result["_fusion_confidence"].iloc[0], 0)

    def test_conflict_lowers_confidence(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(
            source_metadata={"s1": {"timeliness": 0.8, "precision": 0.8, "completeness": 0.8}},
        )
        gdf = gpd.GeoDataFrame({"V": [1, 2, 3]}, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        conflict_map = {"V": [0, 1]}
        result = cr.compute_confidence_scores(gdf, conflict_map)
        # Conflicting rows should have lower confidence
        self.assertLess(result.at[0, "_fusion_confidence"], result.at[2, "_fusion_confidence"])

    def test_no_metadata_defaults(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        gdf = gpd.GeoDataFrame({"V": [1]}, geometry=[Point(0, 0)])
        result = cr.compute_confidence_scores(gdf)
        self.assertAlmostEqual(result["_fusion_confidence"].iloc[0], 0.8)


class TestSourceAnnotation(unittest.TestCase):
    """Test ConflictResolver.annotate_sources."""

    def test_annotate(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        gdf = gpd.GeoDataFrame({
            "AREA": [200.0, 300.0],
            "AREA_left": [200.0, 300.0],
            "AREA_right": [250.0, 350.0],
        }, geometry=[Point(0, 0), Point(1, 1)])
        source_columns = {"AREA": ["AREA_left", "AREA_right"]}
        result = cr.annotate_sources(gdf, source_columns)
        self.assertIn("_source_AREA", result.columns)


class TestResolveAndAnnotate(unittest.TestCase):
    """Test high-level resolve_and_annotate."""

    def test_full_pipeline(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(strategy="voting")
        gdf = _make_conflict_gdf()
        result, summary = cr.resolve_and_annotate(gdf, [])
        self.assertIn("_fusion_confidence", result.columns)
        self.assertGreater(summary.get("conflicts_found", 0), 0)

    def test_no_conflicts(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        gdf = gpd.GeoDataFrame({"V": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
        result, summary = cr.resolve_and_annotate(gdf, [])
        self.assertEqual(summary["conflicts_found"], 0)

    def test_invalid_strategy_defaults(self):
        from data_agent.fusion.conflict_resolver import ConflictResolver
        cr = ConflictResolver(strategy="invalid_strategy")
        self.assertEqual(cr.strategy, "source_priority")


if __name__ == "__main__":
    unittest.main()
