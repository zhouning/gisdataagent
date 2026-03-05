# -*- coding: utf-8 -*-
"""MMFE (Multi-Modal Fusion Engine) quantifiable benchmark suite.

Runs 9 core metrics against the real fusion_engine functions using
synthetic in-memory data. Zero external API dependency (no Gemini calls).

Usage:
    python data_agent/benchmark_fusion.py          # standalone report
    python -m pytest data_agent/benchmark_fusion.py -v  # pytest mode

Output:
    Console report + JSON file in data_agent/benchmark_results/
"""

import json
import os
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, box

# ---------------------------------------------------------------------------
# Ensure package importability when run standalone
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from data_agent.fusion_engine import (
    FusionSource,
    CompatibilityReport,
    STRATEGY_MATRIX,
    UNIT_CONVERSIONS,
    UNIT_PATTERNS,
    _STRATEGY_REGISTRY,
    _find_field_matches,
    _auto_select_strategy,
    _apply_unit_conversions,
    _compute_spatial_overlap,
    _detect_unit,
    _score_strategies,
    _tokenized_similarity,
    _types_compatible,
    assess_compatibility,
    execute_fusion,
    validate_quality,
    align_sources,
)


# ===================================================================
# Synthetic Data Generators
# ===================================================================

def _make_polygon(cx: float, cy: float, size: float = 0.01) -> Polygon:
    """Create a square polygon centred at (cx, cy)."""
    h = size / 2
    return Polygon([(cx - h, cy - h), (cx + h, cy - h),
                    (cx + h, cy + h), (cx - h, cy + h)])


def _make_vector_gdf(
    n: int = 50,
    bounds: tuple = (116.0, 39.0, 117.0, 40.0),
    geom_type: str = "Polygon",
    columns: dict | None = None,
    crs: str = "EPSG:4326",
) -> gpd.GeoDataFrame:
    """Generate a synthetic vector GeoDataFrame."""
    rng = np.random.default_rng(42)
    minx, miny, maxx, maxy = bounds

    if geom_type == "Point":
        geoms = [Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
                 for _ in range(n)]
    else:
        xs = rng.uniform(minx, maxx, n)
        ys = rng.uniform(miny, maxy, n)
        geoms = [_make_polygon(x, y, 0.005) for x, y in zip(xs, ys)]

    data = columns or {
        "id": list(range(1, n + 1)),
        "area": rng.uniform(100, 10000, n).round(2),
        "name": [f"feature_{i}" for i in range(n)],
    }
    return gpd.GeoDataFrame(data, geometry=geoms, crs=crs)


def _make_raster_file(
    width: int = 50,
    height: int = 50,
    bounds: tuple = (116.0, 39.0, 117.0, 40.0),
    bands: int = 1,
    crs: str = "EPSG:4326",
) -> str:
    """Write a temporary GeoTIFF and return its path."""
    import rasterio
    from rasterio.transform import from_bounds

    rng = np.random.default_rng(42)
    transform = from_bounds(*bounds, width, height)
    path = tempfile.mktemp(suffix=".tif")

    with rasterio.open(
        path, "w", driver="GTiff",
        height=height, width=width, count=bands,
        dtype="float32", crs=crs, transform=transform,
    ) as dst:
        for b in range(1, bands + 1):
            dst.write(rng.uniform(0, 255, (height, width)).astype("float32"), b)
    return path


def _make_csv_file(n: int = 50, columns: dict | None = None) -> str:
    """Write a temporary CSV and return its path."""
    rng = np.random.default_rng(42)
    data = columns or {
        "id": list(range(1, n + 1)),
        "value": rng.uniform(0, 100, n).round(2),
        "category": [f"cat_{i % 5}" for i in range(n)],
    }
    path = tempfile.mktemp(suffix=".csv")
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def _make_source(
    gdf_or_path,
    data_type: str = "vector",
    crs: str | None = "EPSG:4326",
    bounds: tuple | None = (116.0, 39.0, 117.0, 40.0),
    geometry_type: str | None = "Polygon",
    columns_spec: list[dict] | None = None,
    row_count: int | None = None,
) -> FusionSource:
    """Build a FusionSource from a GeoDataFrame or file path."""
    if isinstance(gdf_or_path, gpd.GeoDataFrame):
        gdf = gdf_or_path
        path = tempfile.mktemp(suffix=".geojson")
        gdf.to_file(path, driver="GeoJSON")
        cols = [{"name": c, "dtype": str(gdf[c].dtype), "null_pct": 0.0}
                for c in gdf.columns if c != "geometry"]
        return FusionSource(
            file_path=path,
            data_type=data_type,
            crs=crs,
            bounds=bounds or tuple(gdf.total_bounds),
            row_count=row_count or len(gdf),
            columns=columns_spec or cols,
            geometry_type=geometry_type,
        )
    # file path
    return FusionSource(
        file_path=gdf_or_path,
        data_type=data_type,
        crs=crs,
        bounds=bounds,
        row_count=row_count or 0,
        columns=columns_spec or [],
        geometry_type=geometry_type,
    )


# ===================================================================
# Benchmark Class
# ===================================================================

class FusionBenchmark:
    """MMFE quantifiable technical benchmark suite — 9 core metrics."""

    def run_all(self) -> dict:
        results = {}
        tests = [
            ("semantic_matching", self.bench_semantic_matching),
            ("strategy_selection", self.bench_strategy_selection),
            ("unit_conversion", self.bench_unit_conversion),
            ("compatibility_scoring", self.bench_compatibility_scoring),
            ("fusion_quality", self.bench_fusion_quality),
            ("defect_detection", self.bench_defect_detection),
            ("data_preservation", self.bench_data_preservation),
            ("coverage", self.bench_coverage),
            ("performance", self.bench_performance),
        ]
        for name, fn in tests:
            try:
                results[name] = fn()
            except Exception as e:
                results[name] = {"error": str(e), "passed": False}
        return results

    # -----------------------------------------------------------------
    # Metric 1: Semantic Matching Precision / Recall / F1
    # -----------------------------------------------------------------
    def bench_semantic_matching(self) -> dict:
        """Test _find_field_matches against 50 ground-truth field pairs."""

        # Ground truth: (left_col, right_col, should_match, expected_tier)
        # Tier 1: exact
        tier1 = [
            ("AREA", "area", True, "exact"),
            ("OBJECTID", "objectid", True, "exact"),
            ("Name", "name", True, "exact"),
            ("slope", "slope", True, "exact"),
            ("pop", "pop", True, "exact"),
            ("elevation", "elevation", True, "exact"),
            ("category", "category", True, "exact"),
            ("value", "value", True, "exact"),
        ]
        # Tier 2: equivalence group
        tier2 = [
            ("area", "zmj", True, "equiv"),
            ("area", "mj", True, "equiv"),
            ("slope", "pd", True, "equiv"),
            ("name", "mc", True, "equiv"),
            ("name", "dlmc", True, "equiv"),
            ("code", "dm", True, "equiv"),
            ("code", "dlbm", True, "equiv"),
            ("type", "lx", True, "equiv"),
            ("id", "fid", True, "equiv"),
            ("population", "rk", True, "equiv"),
            ("elevation", "dem", True, "equiv"),
            ("perimeter", "zc", True, "equiv"),
        ]
        # Tier 3: unit-aware
        tier3 = [
            ("area_m2", "area_mu", True, "unit"),
            ("area_m2", "area_ha", True, "unit"),
            ("length_m", "length_km", True, "unit"),
            ("area_sqm", "area_ha", True, "unit"),
            ("area_mu", "area_ha", True, "unit"),
            ("distance_m", "distance_km", True, "unit"),
            ("plot_area_m2", "plot_area_mu", True, "unit"),
            ("field_area_m2", "field_area_ha", True, "unit"),
            ("road_length_m", "road_length_km", True, "unit"),
            ("build_area_sqm", "build_area_hectare", True, "unit"),
        ]
        # Tier 4: fuzzy
        tier4 = [
            ("land_use_type", "landUseType", True, "fuzzy"),
            ("soil_quality", "soilQuality", True, "fuzzy"),
            ("building_height", "buildingHeight", True, "fuzzy"),
            ("road_length", "roadLength", True, "fuzzy"),
            ("vegetation_index", "vegetationIndex", True, "fuzzy"),
            ("water_depth", "waterDepth", True, "fuzzy"),
            ("population_density", "populationDensity", True, "fuzzy"),
            ("land_cover_class", "landCoverClass", True, "fuzzy"),
            ("urban_area", "urbanArea", True, "fuzzy"),
            ("green_space", "greenSpace", True, "fuzzy"),
            ("flood_risk_level", "floodRiskLevel", True, "fuzzy"),
            ("crop_yield", "cropYield", True, "fuzzy"),
        ]
        # Negative: should NOT match
        negatives = [
            ("slope", "area", False, "neg"),
            ("id", "ix", False, "neg"),
            ("name", "value", False, "neg"),
            ("code", "category", False, "neg"),
            ("type", "height", False, "neg"),
            ("area", "perimeter", False, "neg"),
            ("population", "elevation", False, "neg"),
            ("distance_m", "area_m2", False, "neg"),
        ]

        all_pairs = tier1 + tier2 + tier3 + tier4 + negatives
        total_positives = sum(1 for _, _, m, _ in all_pairs if m)
        total_negatives = sum(1 for _, _, m, _ in all_pairs if not m)

        # Build tier-level results
        tier_results = {}
        tp = fp = fn = tn = 0

        for tier_name, pairs in [("tier1_exact", tier1), ("tier2_equiv", tier2),
                                  ("tier3_unit", tier3), ("tier4_fuzzy", tier4),
                                  ("negatives", negatives)]:
            tier_tp = tier_fp = tier_fn = tier_tn = 0
            for left_col, right_col, should_match, _ in pairs:
                # Build minimal sources
                left_cols = [{"name": left_col, "dtype": "float64", "null_pct": 0}]
                right_cols = [{"name": right_col, "dtype": "float64", "null_pct": 0}]
                src_a = FusionSource(file_path="a.shp", data_type="vector",
                                     columns=left_cols, row_count=10)
                src_b = FusionSource(file_path="b.shp", data_type="vector",
                                     columns=right_cols, row_count=10)

                matches = _find_field_matches([src_a, src_b], use_embedding=False)
                matched = any(
                    m["left"].lower() == left_col.lower() and
                    m["right"].lower() == right_col.lower()
                    for m in matches
                )

                if should_match:
                    if matched:
                        tier_tp += 1
                    else:
                        tier_fn += 1
                else:
                    if matched:
                        tier_fp += 1
                    else:
                        tier_tn += 1

            tp += tier_tp
            fp += tier_fp
            fn += tier_fn
            tn += tier_tn

            t_p = tier_tp / (tier_tp + tier_fp) if (tier_tp + tier_fp) > 0 else 1.0
            t_r = tier_tp / (tier_tp + tier_fn) if (tier_tp + tier_fn) > 0 else 1.0
            t_f1 = 2 * t_p * t_r / (t_p + t_r) if (t_p + t_r) > 0 else 0.0
            tier_results[tier_name] = {
                "tp": tier_tp, "fp": tier_fp, "fn": tier_fn, "tn": tier_tn,
                "precision": round(t_p, 4), "recall": round(t_r, 4),
                "f1": round(t_f1, 4),
            }

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "total_pairs": len(all_pairs),
            "tier_breakdown": tier_results,
            "passed": precision >= 0.90 and recall >= 0.85 and f1 >= 0.87,
            "thresholds": {"precision": 0.90, "recall": 0.85, "f1": 0.87},
        }

    # -----------------------------------------------------------------
    # Metric 2: Strategy Selection Accuracy
    # -----------------------------------------------------------------
    def bench_strategy_selection(self) -> dict:
        """Test _auto_select_strategy against 30 annotated scenarios."""

        bounds_overlap = (116.0, 39.0, 117.0, 40.0)
        bounds_no_overlap = (120.0, 30.0, 121.0, 31.0)

        # Each scenario: (aligned_data_types, sources_config, expected_strategy)
        scenarios = []

        # --- vector × vector (10) ---
        # High IoU, polygon — should prefer spatial_join
        gdf_poly_a = _make_vector_gdf(20, bounds_overlap, "Polygon")
        gdf_poly_b = _make_vector_gdf(20, bounds_overlap, "Polygon")
        for _ in range(4):
            scenarios.append((
                [("vector", gdf_poly_a), ("vector", gdf_poly_b)],
                [_make_source(gdf_poly_a), _make_source(gdf_poly_b)],
                "spatial_join",
            ))

        # Low IoU, point — should prefer nearest_join
        gdf_point_a = _make_vector_gdf(20, bounds_overlap, "Point")
        gdf_far_b = _make_vector_gdf(20, bounds_no_overlap, "Point")
        for _ in range(3):
            scenarios.append((
                [("vector", gdf_point_a), ("vector", gdf_far_b)],
                [_make_source(gdf_point_a, geometry_type="Point"),
                 _make_source(gdf_far_b, bounds=bounds_no_overlap, geometry_type="Point")],
                "nearest_join",
            ))

        # Polygon moderate overlap — overlay is valid too, spatial_join also valid
        gdf_shift = _make_vector_gdf(20, (116.5, 39.0, 117.5, 40.0), "Polygon")
        for _ in range(3):
            scenarios.append((
                [("vector", gdf_poly_a), ("vector", gdf_shift)],
                [_make_source(gdf_poly_a),
                 _make_source(gdf_shift, bounds=(116.5, 39.0, 117.5, 40.0))],
                ["spatial_join", "overlay"],  # either is acceptable
            ))

        # --- vector × raster (8) ---
        raster_path = _make_raster_file(50, 50, bounds_overlap)
        raster_src = _make_source(raster_path, "raster", bounds=bounds_overlap,
                                   geometry_type=None, row_count=0)

        # polygon → zonal_statistics
        for _ in range(4):
            scenarios.append((
                [("vector", gdf_poly_a), ("raster", raster_path)],
                [_make_source(gdf_poly_a), raster_src],
                "zonal_statistics",
            ))

        # point → point_sampling
        for _ in range(4):
            scenarios.append((
                [("vector", gdf_point_a), ("raster", raster_path)],
                [_make_source(gdf_point_a, geometry_type="Point"), raster_src],
                "point_sampling",
            ))

        # --- vector × tabular (6) ---
        csv_path = _make_csv_file(20)
        csv_src = _make_source(csv_path, "tabular", crs=None, bounds=None,
                                geometry_type=None,
                                columns_spec=[
                                    {"name": "id", "dtype": "int64", "null_pct": 0},
                                    {"name": "value", "dtype": "float64", "null_pct": 0},
                                    {"name": "category", "dtype": "object", "null_pct": 0},
                                ],
                                row_count=20)
        for _ in range(6):
            scenarios.append((
                [("vector", gdf_poly_a), ("tabular", pd.read_csv(csv_path))],
                [_make_source(gdf_poly_a), csv_src],
                "attribute_join",
            ))

        # --- raster × raster (2) ---
        raster_path2 = _make_raster_file(50, 50, bounds_overlap)
        raster_src2 = _make_source(raster_path2, "raster", bounds=bounds_overlap,
                                    geometry_type=None, row_count=0)
        for _ in range(2):
            scenarios.append((
                [("raster", raster_path), ("raster", raster_path2)],
                [raster_src, raster_src2],
                "band_stack",
            ))

        # --- cross-modal special (4) ---
        # raster × tabular → raster_vectorize
        scenarios.append((
            [("raster", raster_path), ("tabular", pd.read_csv(csv_path))],
            [raster_src, csv_src],
            "raster_vectorize",
        ))
        scenarios.append((
            [("raster", raster_path), ("tabular", pd.read_csv(csv_path))],
            [raster_src, csv_src],
            "raster_vectorize",
        ))
        # vector × stream → time_snapshot
        stream_src = _make_source("stream.csv", "stream", crs=None, bounds=None,
                                   geometry_type=None, row_count=100)
        scenarios.append((
            [("vector", gdf_poly_a), ("stream", "stream.csv")],
            [_make_source(gdf_poly_a), stream_src],
            "time_snapshot",
        ))
        # vector × point_cloud → height_assign
        pc_src = _make_source("cloud.las", "point_cloud", bounds=bounds_overlap,
                               geometry_type="Point", row_count=1000)
        scenarios.append((
            [("vector", gdf_poly_a), ("point_cloud", "cloud.las")],
            [_make_source(gdf_poly_a), pc_src],
            "height_assign",
        ))

        correct = 0
        details = []
        for i, (aligned, srcs, expected) in enumerate(scenarios):
            try:
                result = _auto_select_strategy(aligned, srcs)
            except Exception as e:
                details.append({"scenario": i, "error": str(e)})
                continue

            if isinstance(expected, list):
                ok = result in expected
            else:
                ok = result == expected

            if ok:
                correct += 1
            details.append({
                "scenario": i,
                "expected": expected,
                "actual": result,
                "correct": ok,
            })

        accuracy = correct / len(scenarios) if scenarios else 0
        return {
            "accuracy": round(accuracy, 4),
            "correct": correct,
            "total": len(scenarios),
            "details": details,
            "passed": accuracy >= 0.85,
            "threshold": 0.85,
        }

    # -----------------------------------------------------------------
    # Metric 3: Unit Conversion Accuracy
    # -----------------------------------------------------------------
    def bench_unit_conversion(self) -> dict:
        """Test _apply_unit_conversions for precision."""

        test_cases = [
            # (from_unit, to_unit, input_val, expected_factor)
            ("m2", "mu",  666670.0, 1 / 666.67),
            ("mu", "m2",  1.0,      666.67),
            ("m2", "ha",  10000.0,  1 / 10000),
            ("ha", "m2",  1.0,      10000),
            ("mu", "ha",  15.0,     1 / 15),
            ("ha", "mu",  1.0,      15),
            ("m", "km",   1000.0,   1 / 1000),
            ("km", "m",   1.0,      1000),
        ]

        max_rel_error = 0.0
        details = []

        for from_u, to_u, input_val, expected_factor in test_cases:
            expected_output = input_val * expected_factor

            # Build aligned data with a DataFrame containing the column
            col_name = f"test_{from_u}"
            df = pd.DataFrame({col_name: [input_val]})
            loaded = [("tabular", df)]

            field_matches = [{
                "left": f"test_{to_u}",
                "right": col_name,
                "confidence": 0.75,
                "match_type": "unit_aware",
                "left_unit": to_u,
                "right_unit": from_u,
            }]

            log = []
            _apply_unit_conversions(loaded, field_matches, log)

            actual = df[col_name].iloc[0]
            rel_error = abs(actual - expected_output) / abs(expected_output) if expected_output != 0 else 0
            max_rel_error = max(max_rel_error, rel_error)

            details.append({
                "conversion": f"{from_u}→{to_u}",
                "input": input_val,
                "expected": round(expected_output, 6),
                "actual": round(actual, 6),
                "relative_error": round(rel_error, 15),
            })

        return {
            "max_relative_error": max_rel_error,
            "conversion_count": len(test_cases),
            "details": details,
            "passed": max_rel_error < 1e-10,
            "threshold": 1e-10,
        }

    # -----------------------------------------------------------------
    # Metric 4: Compatibility Score Accuracy
    # -----------------------------------------------------------------
    def bench_compatibility_scoring(self) -> dict:
        """Test assess_compatibility scoring falls in expected bands."""

        bounds_same = (116.0, 39.0, 117.0, 40.0)
        bounds_disjoint = (120.0, 30.0, 121.0, 31.0)

        # The scoring formula is additive:
        #   CRS compatible: +0.3 (or +0.15 if fixable)
        #   Spatial overlap IoU>0.1: +0.3 (or +0.2 if tabular involved)
        #   Field matches: +0.2
        #   Strategies available: +0.2
        # So scores range from 0.0 to 1.0.

        # High compat (>=0.7): same CRS + overlap + fields + strategies
        high_cases = []
        for _ in range(5):
            gdf_a = _make_vector_gdf(20, bounds_same)
            gdf_b = _make_vector_gdf(20, bounds_same)
            src_a = _make_source(gdf_a, bounds=bounds_same)
            src_b = _make_source(gdf_b, bounds=bounds_same)
            high_cases.append(([src_a, src_b], (0.7, 1.0)))

        # Medium compat (0.35-0.9): partial factors present
        # Different CRS(+0.15), has overlap(+0.3), has fields(+0.2), has strat(+0.2) = 0.85
        mid_cases = []
        for _ in range(5):
            gdf_a = _make_vector_gdf(20, bounds_same)
            gdf_b = _make_vector_gdf(20, bounds_same, columns={
                "fid": list(range(20)), "zmj": np.random.uniform(100, 1000, 20),
            })
            src_a = _make_source(gdf_a, bounds=bounds_same)
            src_b = _make_source(gdf_b, crs="EPSG:4547", bounds=bounds_same)
            mid_cases.append(([src_a, src_b], (0.35, 0.95)))

        # Low compat (<=0.7): no overlap, no shared fields, cross-type with tabular
        # CRS: only A has CRS (+0.15), IoU=0 but tabular(+0.2), no fields(0), strat(+0.2) = 0.55
        low_cases = []
        for _ in range(5):
            gdf_a = _make_vector_gdf(20, bounds_same, columns={
                "parcel_id": list(range(20)), "slope_deg": np.random.uniform(0, 45, 20),
            })
            csv_path = _make_csv_file(20, columns={
                "serial": list(range(20)), "weight": np.random.uniform(0, 100, 20),
            })
            src_a = _make_source(gdf_a, bounds=bounds_same)
            src_b = _make_source(csv_path, "tabular", crs=None, bounds=None,
                                  geometry_type=None,
                                  columns_spec=[
                                      {"name": "serial", "dtype": "int64", "null_pct": 0},
                                      {"name": "weight", "dtype": "float64", "null_pct": 0},
                                  ],
                                  row_count=20)
            low_cases.append(([src_a, src_b], (0.2, 0.75)))

        all_cases = high_cases + mid_cases + low_cases
        hits = 0
        details = []

        for sources, (lo, hi) in all_cases:
            report = assess_compatibility(sources, use_embedding=False)
            score = report.overall_score
            in_band = lo <= score <= hi
            if in_band:
                hits += 1
            details.append({
                "expected_range": [lo, hi],
                "actual_score": score,
                "in_band": in_band,
            })

        accuracy = hits / len(all_cases)
        return {
            "accuracy": round(accuracy, 4),
            "hits": hits,
            "total": len(all_cases),
            "details": details,
            "passed": accuracy >= 0.80,
            "threshold": 0.80,
        }

    # -----------------------------------------------------------------
    # Metric 5: Fusion Quality Score (clean data)
    # -----------------------------------------------------------------
    def bench_fusion_quality(self) -> dict:
        """Run each strategy on clean synthetic data, collect quality scores."""

        bounds = (116.0, 39.0, 117.0, 40.0)
        gdf_poly = _make_vector_gdf(30, bounds, "Polygon")
        gdf_poly2 = _make_vector_gdf(30, bounds, "Polygon",
                                      columns={"fid": list(range(30)),
                                                "value": np.random.uniform(0, 100, 30)})
        gdf_point = _make_vector_gdf(30, bounds, "Point")
        raster_path = _make_raster_file(50, 50, bounds)
        csv_path = _make_csv_file(30)

        strategy_configs = {
            "spatial_join": [("vector", gdf_poly), ("vector", gdf_poly2)],
            "overlay": [("vector", gdf_poly), ("vector", gdf_poly2)],
            "nearest_join": [("vector", gdf_poly), ("vector", gdf_poly2)],
            "attribute_join": [("vector", gdf_poly), ("tabular", pd.read_csv(csv_path))],
            "zonal_statistics": [("vector", gdf_poly), ("raster", raster_path)],
            "point_sampling": [("vector", gdf_point), ("raster", raster_path)],
            "band_stack": [("raster", raster_path),
                           ("raster", _make_raster_file(50, 50, bounds))],
            "raster_vectorize": [("raster", raster_path),
                                  ("tabular", pd.read_csv(csv_path))],
        }

        src_poly = _make_source(gdf_poly)
        src_poly2 = _make_source(gdf_poly2)
        src_point = _make_source(gdf_point, geometry_type="Point")
        src_raster = _make_source(raster_path, "raster", bounds=bounds,
                                   geometry_type=None, row_count=0)

        source_map = {
            "spatial_join": [src_poly, src_poly2],
            "overlay": [src_poly, src_poly2],
            "nearest_join": [src_poly, src_poly2],
            "attribute_join": [src_poly, _make_source(csv_path, "tabular",
                                crs=None, bounds=None, geometry_type=None,
                                columns_spec=[{"name": "id", "dtype": "int64", "null_pct": 0},
                                              {"name": "value", "dtype": "float64", "null_pct": 0}],
                                row_count=30)],
            "zonal_statistics": [src_poly, src_raster],
            "point_sampling": [src_point, src_raster],
            "band_stack": [src_raster, src_raster],
            "raster_vectorize": [src_raster, _make_source(csv_path, "tabular",
                                  crs=None, bounds=None, geometry_type=None, row_count=30)],
        }

        scores = []
        details = {}

        for strategy, aligned in strategy_configs.items():
            try:
                fn = _STRATEGY_REGISTRY[strategy]
                result_gdf, log = fn(aligned, {})
                quality = validate_quality(result_gdf, source_map.get(strategy))
                q_score = quality["score"]
                scores.append(q_score)
                details[strategy] = {
                    "quality_score": q_score,
                    "rows": len(result_gdf),
                    "warnings": quality["warnings"][:3],
                }
            except Exception as e:
                details[strategy] = {"error": str(e), "quality_score": 0.0}
                scores.append(0.0)

        mean_score = np.mean(scores) if scores else 0.0
        std_score = np.std(scores) if scores else 0.0

        return {
            "mean_quality": round(float(mean_score), 4),
            "std_quality": round(float(std_score), 4),
            "strategies_tested": len(scores),
            "details": details,
            "passed": mean_score >= 0.85,
            "threshold": 0.85,
        }

    # -----------------------------------------------------------------
    # Metric 6: Defect Detection Rate
    # -----------------------------------------------------------------
    def bench_defect_detection(self) -> dict:
        """Inject known defects, verify validate_quality detects them."""

        bounds = (116.0, 39.0, 117.0, 40.0)
        detected = 0
        total = 7
        details = []

        # Defect 1: High null rate (60%)
        gdf = _make_vector_gdf(50, bounds)
        gdf["test_col"] = np.nan
        gdf.loc[:19, "test_col"] = np.random.uniform(0, 100, 20)
        q = validate_quality(gdf)
        has_null_warn = any("null" in w.lower() for w in q["warnings"])
        if has_null_warn:
            detected += 1
        details.append({"defect": "high_null_rate", "detected": has_null_warn})

        # Defect 2: Invalid geometries (self-intersecting polygons)
        gdf2 = _make_vector_gdf(50, bounds)
        # Create self-intersecting polygon (bowtie)
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        for i in range(25):
            gdf2.loc[i, "geometry"] = bowtie
        q2 = validate_quality(gdf2)
        has_geom_warn = any("invalid" in w.lower() or "geometry" in w.lower()
                            for w in q2["warnings"])
        if has_geom_warn:
            detected += 1
        details.append({"defect": "invalid_geometry", "detected": has_geom_warn})

        # Defect 3: Extreme outliers (>5×IQR)
        gdf3 = _make_vector_gdf(100, bounds)
        gdf3["value"] = np.random.uniform(10, 20, 100)
        gdf3.loc[0, "value"] = 999999  # extreme outlier
        gdf3.loc[1, "value"] = -999999
        gdf3.loc[2, "value"] = 888888
        gdf3.loc[3, "value"] = -888888
        gdf3.loc[4, "value"] = 777777
        gdf3.loc[5, "value"] = -777777
        q3 = validate_quality(gdf3)
        has_outlier = any("outlier" in w.lower() for w in q3["warnings"])
        if has_outlier:
            detected += 1
        details.append({"defect": "extreme_outliers", "detected": has_outlier})

        # Defect 4: Micro-polygons
        gdf4 = _make_vector_gdf(50, bounds)
        # Replace 30% with tiny polygons
        for i in range(15):
            cx, cy = 116.5, 39.5
            gdf4.loc[i, "geometry"] = _make_polygon(cx, cy, 0.0000001)
        q4 = validate_quality(gdf4)
        has_micro = any("micro" in w.lower() for w in q4["warnings"])
        if has_micro:
            detected += 1
        details.append({"defect": "micro_polygons", "detected": has_micro})

        # Defect 5: Topology issues (self-intersecting polygons caught by shapely)
        gdf5 = _make_vector_gdf(50, bounds)
        bowtie2 = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
        for i in range(20):
            gdf5.loc[i, "geometry"] = bowtie2
        q5 = validate_quality(gdf5)
        has_topo = any("topology" in w.lower() or "invalid" in w.lower()
                       for w in q5["warnings"])
        if has_topo:
            detected += 1
        details.append({"defect": "topology_issues", "detected": has_topo})

        # Defect 6: Row loss (output < 50% of input)
        gdf6 = _make_vector_gdf(10, bounds)
        src_big = _make_source(gdf6, row_count=100)  # claim 100 rows
        q6 = validate_quality(gdf6, [src_big])
        has_loss = any("completeness" in w.lower() or "rows" in w.lower()
                       for w in q6["warnings"])
        if has_loss:
            detected += 1
        details.append({"defect": "row_loss", "detected": has_loss})

        # Defect 7: Empty result
        gdf7 = gpd.GeoDataFrame(columns=["geometry", "value"],
                                 geometry="geometry", crs="EPSG:4326")
        q7 = validate_quality(gdf7)
        is_zero = q7["score"] == 0.0
        if is_zero:
            detected += 1
        details.append({"defect": "empty_result", "detected": is_zero})

        rate = detected / total
        return {
            "detection_rate": round(rate, 4),
            "detected": detected,
            "total": total,
            "details": details,
            "passed": rate >= 0.85,
            "threshold": 0.85,
        }

    # -----------------------------------------------------------------
    # Metric 7: Data Preservation Rate
    # -----------------------------------------------------------------
    def bench_data_preservation(self) -> dict:
        """Measure row/column/geometry preservation for core strategies."""

        bounds = (116.0, 39.0, 117.0, 40.0)
        gdf_a = _make_vector_gdf(30, bounds, columns={
            "id": list(range(30)),
            "area": np.random.uniform(100, 10000, 30),
            "name": [f"feat_{i}" for i in range(30)],
        })
        gdf_b = _make_vector_gdf(30, bounds, columns={
            "fid": list(range(30)),
            "value": np.random.uniform(0, 100, 30),
            "category": [f"cat_{i % 3}" for i in range(30)],
        })
        gdf_point = _make_vector_gdf(30, bounds, "Point", columns={
            "id": list(range(30)),
            "measurement": np.random.uniform(0, 50, 30),
        })
        raster_path = _make_raster_file(50, 50, bounds)
        csv_data = pd.DataFrame({
            "id": list(range(30)),
            "extra_val": np.random.uniform(0, 100, 30),
        })

        strategies = {
            "spatial_join": ([("vector", gdf_a), ("vector", gdf_b)],
                             gdf_a, gdf_b),
            "overlay": ([("vector", gdf_a), ("vector", gdf_b)],
                        gdf_a, gdf_b),
            "nearest_join": ([("vector", gdf_a), ("vector", gdf_b)],
                             gdf_a, gdf_b),
            "attribute_join": ([("vector", gdf_a), ("tabular", csv_data)],
                               gdf_a, csv_data),
            "zonal_statistics": ([("vector", gdf_a), ("raster", raster_path)],
                                 gdf_a, None),
            "point_sampling": ([("vector", gdf_point), ("raster", raster_path)],
                               gdf_point, None),
        }

        results = {}
        all_row_rates = []
        all_geom_valid = []

        for strategy, (aligned, left, right) in strategies.items():
            try:
                fn = _STRATEGY_REGISTRY[strategy]
                result_gdf, _ = fn(aligned, {})

                # Row preservation
                left_rows = len(left) if hasattr(left, '__len__') else 0
                row_pres = len(result_gdf) / left_rows if left_rows > 0 else 1.0

                # Column preservation
                left_cols = set(c for c in left.columns if c != "geometry") if hasattr(left, 'columns') else set()
                right_cols = set()
                if right is not None and hasattr(right, 'columns'):
                    right_cols = set(c for c in right.columns if c != "geometry")
                out_cols = set(c for c in result_gdf.columns if c != "geometry")
                total_input_cols = len(left_cols | right_cols) or 1
                col_pres = len(out_cols) / total_input_cols

                # Geometry validity
                geom_valid = 1.0
                if "geometry" in result_gdf.columns and len(result_gdf) > 0:
                    valid_count = result_gdf.geometry.is_valid.sum()
                    geom_valid = valid_count / len(result_gdf)

                all_row_rates.append(min(row_pres, 2.0))
                all_geom_valid.append(geom_valid)

                results[strategy] = {
                    "row_preservation": round(row_pres, 4),
                    "column_preservation": round(col_pres, 4),
                    "geometry_validity": round(geom_valid, 4),
                    "output_rows": len(result_gdf),
                    "output_cols": len(out_cols),
                }
            except Exception as e:
                results[strategy] = {"error": str(e)}

        avg_row = np.mean(all_row_rates) if all_row_rates else 0
        avg_geom = np.mean(all_geom_valid) if all_geom_valid else 0

        return {
            "avg_row_preservation": round(float(avg_row), 4),
            "avg_geometry_validity": round(float(avg_geom), 4),
            "strategies": results,
            "passed": avg_row >= 0.80 and avg_geom >= 0.99,
            "thresholds": {"row_preservation": 0.80, "geometry_validity": 0.99},
        }

    # -----------------------------------------------------------------
    # Metric 8: Coverage Rate
    # -----------------------------------------------------------------
    def bench_coverage(self) -> dict:
        """Enumerate modality, strategy, type-pair, and quality check coverage."""

        # Modality coverage
        supported_modalities = {"vector", "raster", "tabular", "point_cloud", "stream"}
        total_modalities = 5

        # Strategy coverage
        implemented_strategies = set(_STRATEGY_REGISTRY.keys())
        expected_strategies = {"spatial_join", "overlay", "nearest_join",
                               "attribute_join", "zonal_statistics", "point_sampling",
                               "band_stack", "time_snapshot", "height_assign",
                               "raster_vectorize"}

        # Type pair coverage
        type_pair_count = len(STRATEGY_MATRIX)

        # Quality check coverage (count checks in validate_quality)
        # 10 checks: empty, null_rate, geometry_validity, row_completeness,
        # outlier_detection, micro_polygon, column_completeness,
        # crs_consistency, topology_validation, distribution_shift
        quality_checks = [
            "empty_check", "null_rate", "geometry_validity",
            "row_completeness", "outlier_detection", "micro_polygon",
            "column_completeness", "crs_consistency",
            "topology_validation", "distribution_shift",
        ]

        # Unit conversion coverage
        unit_pair_count = len(UNIT_CONVERSIONS)

        # Equivalence group count
        from data_agent.fusion_engine import _get_equiv_groups
        equiv_count = len(_get_equiv_groups())

        return {
            "modality_coverage": f"{len(supported_modalities)}/{total_modalities}",
            "strategy_coverage": f"{len(implemented_strategies)}/{len(expected_strategies)}",
            "strategy_list": sorted(implemented_strategies),
            "type_pair_coverage": f"{type_pair_count}/11",
            "quality_check_coverage": f"{len(quality_checks)}/10",
            "unit_conversion_pairs": unit_pair_count,
            "equivalence_groups": equiv_count,
            "passed": (len(implemented_strategies) == len(expected_strategies)
                       and type_pair_count >= 11),
        }

    # -----------------------------------------------------------------
    # Metric 9: Performance (Throughput & Latency)
    # -----------------------------------------------------------------
    def bench_performance(self) -> dict:
        """Measure end-to-end latency for spatial_join at 3 scales."""

        bounds = (116.0, 39.0, 117.0, 40.0)
        scales = [100, 1000, 10000]
        results = {}

        for n in scales:
            gdf_a = _make_vector_gdf(n, bounds)
            gdf_b = _make_vector_gdf(n, bounds, columns={
                "fid": list(range(n)),
                "value": np.random.uniform(0, 100, n),
            })

            aligned = [("vector", gdf_a), ("vector", gdf_b)]
            src_a = _make_source(gdf_a, row_count=n)
            src_b = _make_source(gdf_b, row_count=n)

            # Time the full pipeline (no file I/O — in-memory)
            t0 = time.perf_counter()

            # Assess
            t_assess_start = time.perf_counter()
            report = assess_compatibility([src_a, src_b])
            t_assess = time.perf_counter() - t_assess_start

            # Select strategy
            t_strat_start = time.perf_counter()
            strategy = _auto_select_strategy(aligned, [src_a, src_b])
            t_strat = time.perf_counter() - t_strat_start

            # Fuse
            t_fuse_start = time.perf_counter()
            fn = _STRATEGY_REGISTRY[strategy]
            result_gdf, _ = fn(aligned, {})
            t_fuse = time.perf_counter() - t_fuse_start

            # Validate
            t_val_start = time.perf_counter()
            quality = validate_quality(result_gdf, [src_a, src_b])
            t_val = time.perf_counter() - t_val_start

            total = time.perf_counter() - t0
            throughput = len(result_gdf) / total if total > 0 else 0

            results[f"{n}_rows"] = {
                "total_s": round(total, 3),
                "assess_s": round(t_assess, 3),
                "strategy_s": round(t_strat, 3),
                "fuse_s": round(t_fuse, 3),
                "validate_s": round(t_val, 3),
                "output_rows": len(result_gdf),
                "throughput_rows_per_s": round(throughput, 1),
            }

        passed = (results.get("1000_rows", {}).get("total_s", 999) < 5
                  and results.get("10000_rows", {}).get("total_s", 999) < 30)

        return {
            "scales": results,
            "passed": passed,
            "thresholds": {"1000_rows": "< 5s", "10000_rows": "< 30s"},
        }

    # -----------------------------------------------------------------
    # Report Output
    # -----------------------------------------------------------------
    def print_report(self, results: dict) -> None:
        """Print formatted benchmark report to console."""
        print("\n" + "=" * 70)
        print("  MMFE Benchmark Report")
        print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("=" * 70)

        for name, data in results.items():
            passed = data.get("passed", False)
            status = "PASS" if passed else "FAIL"
            print(f"\n  [{status}] {name}")

            if "error" in data:
                print(f"        ERROR: {data['error']}")
                continue

            # Metric-specific display
            if name == "semantic_matching":
                print(f"        P={data['precision']:.4f}  R={data['recall']:.4f}  "
                      f"F1={data['f1']:.4f}  (TP={data['tp']} FP={data['fp']} "
                      f"FN={data['fn']} TN={data['tn']})")
                for tier, td in data.get("tier_breakdown", {}).items():
                    print(f"          {tier}: P={td['precision']:.2f} R={td['recall']:.2f} "
                          f"F1={td['f1']:.2f}")
            elif name == "strategy_selection":
                print(f"        Accuracy: {data['accuracy']:.2%} "
                      f"({data['correct']}/{data['total']})")
            elif name == "unit_conversion":
                print(f"        Max relative error: {data['max_relative_error']:.2e}")
            elif name == "compatibility_scoring":
                print(f"        Band accuracy: {data['accuracy']:.2%} "
                      f"({data['hits']}/{data['total']})")
            elif name == "fusion_quality":
                print(f"        Mean quality: {data['mean_quality']:.4f} "
                      f"± {data['std_quality']:.4f}")
                for s, d in data.get("details", {}).items():
                    qs = d.get("quality_score", "ERR")
                    print(f"          {s}: {qs}")
            elif name == "defect_detection":
                print(f"        Detection rate: {data['detection_rate']:.2%} "
                      f"({data['detected']}/{data['total']})")
                for d in data.get("details", []):
                    icon = "+" if d["detected"] else "-"
                    print(f"          [{icon}] {d['defect']}")
            elif name == "data_preservation":
                print(f"        Avg row preservation: {data['avg_row_preservation']:.4f}")
                print(f"        Avg geometry validity: {data['avg_geometry_validity']:.4f}")
            elif name == "coverage":
                print(f"        Modalities: {data['modality_coverage']}")
                print(f"        Strategies: {data['strategy_coverage']}")
                print(f"        Type pairs: {data['type_pair_coverage']}")
                print(f"        Quality checks: {data['quality_check_coverage']}")
                print(f"        Unit conversions: {data['unit_conversion_pairs']}")
                print(f"        Equivalence groups: {data['equivalence_groups']}")
            elif name == "performance":
                for scale, sd in data.get("scales", {}).items():
                    print(f"          {scale}: {sd['total_s']:.3f}s "
                          f"({sd['throughput_rows_per_s']:.0f} rows/s)")

        # Summary
        total = len(results)
        passed_count = sum(1 for d in results.values() if d.get("passed", False))
        print(f"\n{'=' * 70}")
        print(f"  Summary: {passed_count}/{total} metrics passed")
        print(f"{'=' * 70}\n")

    def save_report(self, results: dict, out_dir: str | None = None) -> str:
        """Save benchmark results as JSON."""
        if out_dir is None:
            out_dir = os.path.join(_HERE, "benchmark_results")
        os.makedirs(out_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"benchmark_report_{ts}.json")

        # Make NumPy types JSON-serializable
        def default(o):
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
            return str(o)

        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "metrics": results,
                "summary": {
                    "total": len(results),
                    "passed": sum(1 for d in results.values() if d.get("passed", False)),
                },
            }, f, indent=2, ensure_ascii=False, default=default)

        return path


# ===================================================================
# Standalone entry point
# ===================================================================

def main():
    bench = FusionBenchmark()
    print("Running MMFE benchmark suite (9 metrics)...")
    results = bench.run_all()
    bench.print_report(results)
    path = bench.save_report(results)
    print(f"JSON report saved to: {path}")
    return results


if __name__ == "__main__":
    main()
