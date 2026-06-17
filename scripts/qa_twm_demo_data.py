#!/usr/bin/env python3
"""Quality gate for the Territorial World Model demo dataset."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

try:
    import rasterio
except ImportError:  # pragma: no cover - handled as a QA blocker at runtime.
    rasterio = None


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_PROJECT_CRS = "EPSG:32648"


LAYER_FILES = {
    "parcel_current": "parcel_current.geojson",
    "synthetic_pbf": "synthetic_pbf.geojson",
    "synthetic_eco_redline": "synthetic_eco_redline.geojson",
    "admin_units": "admin_units.geojson",
    "synthetic_annual_change": "synthetic_annual_change.geojson",
    "synthetic_projects": "synthetic_projects.geojson",
    "synthetic_planning_zones": "synthetic_planning_zones.geojson",
    "synthetic_urban_boundary": "synthetic_urban_boundary.geojson",
    "synthetic_remote_sensing_tiles": "synthetic_remote_sensing_tiles.geojson",
}

ROLE_CONTRACT_TARGETS = {
    "parcel_current": ("layer", "parcel_current"),
    "pbf": ("layer", "synthetic_pbf"),
    "eco_redline": ("layer", "synthetic_eco_redline"),
    "urban_boundary": ("layer", "synthetic_urban_boundary"),
    "planning_zone": ("layer", "synthetic_planning_zones"),
    "project": ("layer", "synthetic_projects"),
    "approval": ("table", "approval_records"),
    "enforcement": ("table", "enforcement_events"),
    "metadata_vector": ("table", "metadata_vector"),
}


def _load_layers(data_dir: Path) -> dict[str, gpd.GeoDataFrame]:
    layers = {}
    for role, filename in LAYER_FILES.items():
        path = data_dir / filename
        if path.exists():
            gdf = gpd.read_file(path)
            if gdf.crs is None:
                raise ValueError(f"{path} has no CRS")
            layers[role] = gdf
    return layers


def _connected_components(gdf: gpd.GeoDataFrame, project_crs: str) -> dict[str, Any]:
    projected = gdf.to_crs(project_crs).reset_index(drop=True)
    if projected.empty:
        return {"connected_components": 0, "largest_component_features": 0, "largest_component_ratio": 0.0}
    parents = list(range(len(projected)))

    def find(x: int) -> int:
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[rb] = ra

    sidx = projected.sindex
    for i, geom in enumerate(projected.geometry):
        for j in sidx.query(geom, predicate="intersects"):
            j = int(j)
            if j > i:
                union(i, j)

    counts: dict[int, int] = {}
    for i in range(len(projected)):
        root = find(i)
        counts[root] = counts.get(root, 0) + 1
    largest = max(counts.values()) if counts else 0
    return {
        "connected_components": len(counts),
        "largest_component_features": int(largest),
        "largest_component_ratio": round(largest / len(projected), 4) if len(projected) else 0.0,
    }


def _layer_summary(role: str, gdf: gpd.GeoDataFrame, project_crs: str) -> dict[str, Any]:
    projected = gdf.to_crs(project_crs)
    areas = projected.geometry.area
    bbox_area = 0.0
    if len(projected):
        minx, miny, maxx, maxy = projected.total_bounds
        bbox_area = float((maxx - minx) * (maxy - miny))
    id_columns = [
        c
        for c in [
            "bsm_norm",
            "BSM",
            "control_id",
            "redline_id",
            "admin_code",
            "change_id",
            "project_id",
            "plan_zone_id",
            "boundary_id",
            "tile_id",
        ]
        if c in gdf.columns
    ]
    null_counts = {
        c: int(gdf[c].isna().sum())
        for c in gdf.columns
        if c != "geometry" and int(gdf[c].isna().sum()) > 0
    }
    summary = {
        "rows": int(len(gdf)),
        "crs": str(gdf.crs),
        "geometry_types": sorted(map(str, gdf.geom_type.dropna().unique().tolist())),
        "invalid_geometries": int((~gdf.geometry.is_valid).sum()),
        "empty_geometries": int(gdf.geometry.is_empty.sum()),
        "area_m2_sum": round(float(areas.sum()), 3) if len(areas) else 0.0,
        "area_m2_min": round(float(areas.min()), 3) if len(areas) else 0.0,
        "area_m2_p50": round(float(areas.quantile(0.5)), 3) if len(areas) else 0.0,
        "area_m2_p95": round(float(areas.quantile(0.95)), 3) if len(areas) else 0.0,
        "area_m2_max": round(float(areas.max()), 3) if len(areas) else 0.0,
        "bbox_coverage_ratio": round(float(areas.sum()) / bbox_area, 4) if bbox_area else 0.0,
        "null_counts": null_counts,
        "duplicate_counts": {c: int(gdf[c].astype(str).duplicated().sum()) for c in id_columns},
    }
    for col in ["synthetic", "not_for_production", "qa_use_for_rules", "qa_area_warning"]:
        if col in gdf.columns:
            summary[col] = gdf[col].astype(str).value_counts().to_dict()
    if role == "parcel_current":
        summary["connectedness"] = _connected_components(gdf, project_crs)
    return summary


def _internal_overlap(gdf: gpd.GeoDataFrame, project_crs: str, min_area_m2: float = 1.0) -> dict[str, Any]:
    projected = gdf.to_crs(project_crs).reset_index(drop=True)
    if projected.empty:
        return {"pairs_gt_threshold": 0, "total_overlap_area_m2": 0.0, "examples": []}
    sidx = projected.sindex
    pairs = 0
    total_area = 0.0
    examples = []
    for i, geom in enumerate(projected.geometry):
        for j in sidx.query(geom, predicate="intersects"):
            j = int(j)
            if j <= i:
                continue
            inter = geom.intersection(projected.geometry.iloc[j])
            area = float(inter.area) if not inter.is_empty else 0.0
            if area > min_area_m2:
                pairs += 1
                total_area += area
                if len(examples) < 8:
                    examples.append({"left_index": i, "right_index": j, "overlap_area_m2": round(area, 3)})
    return {
        "pairs_gt_threshold": pairs,
        "total_overlap_area_m2": round(total_area, 3),
        "examples": examples,
    }


def _area_consistency(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    if "tbmj_area_rel_error" not in gdf.columns:
        return {}
    ratio = pd.to_numeric(gdf["tbmj_area_rel_error"], errors="coerce").dropna()
    if ratio.empty:
        return {}
    return {
        "compared": int(len(ratio)),
        "median_abs_rel_error": round(float(ratio.median()), 6),
        "p95_abs_rel_error": round(float(ratio.quantile(0.95)), 6),
        "max_abs_rel_error": round(float(ratio.max()), 6),
        "count_gt_5pct": int((ratio > 0.05).sum()),
        "count_gt_10pct": int((ratio > 0.10).sum()),
    }


def _positive_overlay(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    *,
    left_id: str,
    right_id: str,
    project_crs: str,
    min_area_m2: float = 1.0,
) -> dict[str, Any]:
    if left.empty or right.empty:
        return {"positive_intersections": 0, "unique_left": 0, "unique_right": 0}
    lproj = left.to_crs(project_crs).reset_index(drop=True)
    rproj = right.to_crs(project_crs).reset_index(drop=True)
    joined = gpd.sjoin(
        lproj[[left_id, "geometry"]],
        rproj[[right_id, "geometry"]],
        predicate="intersects",
        how="inner",
    )
    ratios = []
    left_hits: set[str] = set()
    right_hits: set[str] = set()
    exact = 0
    partial = 0
    touches = 0
    for idx, row in joined.iterrows():
        ridx = int(row["index_right"])
        geom_left = lproj.geometry.iloc[int(idx)]
        geom_right = rproj.geometry.iloc[ridx]
        inter = geom_left.intersection(geom_right)
        area = float(inter.area) if not inter.is_empty else 0.0
        if area <= min_area_m2:
            touches += 1
            continue
        ratio = area / float(geom_left.area) if geom_left.area else 0.0
        ratios.append(ratio)
        left_hits.add(str(row[left_id]))
        right_hits.add(str(row[right_id]))
        if ratio > 0.99:
            exact += 1
        elif ratio > 0.01:
            partial += 1
    series = pd.Series(ratios, dtype="float64")
    return {
        "raw_intersections": int(len(joined)),
        "touch_or_lt_threshold": int(touches),
        "positive_intersections": int(len(ratios)),
        "unique_left": int(len(left_hits)),
        "unique_right": int(len(right_hits)),
        "mean_overlap_ratio_left": round(float(series.mean()), 6) if len(series) else 0.0,
        "p50_overlap_ratio_left": round(float(series.quantile(0.5)), 6) if len(series) else 0.0,
        "gt_99pct_left": exact,
        "partial_gt_1pct_left": partial,
    }


def _relation_summary(data_dir: Path) -> dict[str, Any]:
    relation_dir = data_dir / "relations"
    out = {}
    if not relation_dir.exists():
        return out
    for path in sorted(relation_dir.glob("*.csv")):
        df = pd.read_csv(path)
        out[path.stem] = {
            "rows": int(len(df)),
            "columns": list(df.columns),
            "unique_projects": int(df["project_id"].nunique()) if "project_id" in df.columns and len(df) else 0,
        }
    return out


def _table_summary(data_dir: Path) -> dict[str, Any]:
    tables_dir = data_dir / "tables"
    out = {}
    if not tables_dir.exists():
        return out
    for path in sorted(tables_dir.glob("*.csv")):
        df = pd.read_csv(path)
        summary = {
            "rows": int(len(df)),
            "columns": list(df.columns),
            "unique_projects": int(df["project_id"].nunique()) if "project_id" in df.columns and len(df) else 0,
        }
        if "rule_id" in df.columns and len(df):
            summary["unique_rules"] = int(df["rule_id"].nunique())
        if "snapshot_year" in df.columns and len(df):
            summary["snapshot_years"] = sorted(map(int, pd.to_numeric(df["snapshot_year"], errors="coerce").dropna().unique().tolist()))
        if "evidence_type" in df.columns and len(df):
            summary["evidence_types"] = df["evidence_type"].astype(str).value_counts().to_dict()
        out[path.stem] = summary
    return out


def _load_table(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / "tables" / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _series_non_empty(series: pd.Series) -> pd.Series:
    return series.notna() & (series.astype(str).str.strip() != "") & (series.astype(str).str.lower() != "nan")


def _load_standard_contract(data_dir: Path) -> dict[str, Any]:
    candidates = [
        data_dir / "standards" / "one_map_role_contracts.zh.json",
        Path("data_agent/test_data/twm_standards/one_map_role_contracts.zh.json"),
    ]
    for path in candidates:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["_path"] = str(path)
            return payload
    return {}


def _validate_field_rules(df: pd.DataFrame, rules: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"checks": {}, "warnings": [], "blockers": []}
    for field, rule in rules.items():
        if field not in df.columns:
            continue
        non_empty = df.loc[_series_non_empty(df[field]), field]
        field_check: dict[str, Any] = {"checked_rows": int(len(non_empty))}
        if not len(non_empty):
            result["checks"][field] = field_check
            continue
        if rule.get("type") == "number":
            values = pd.to_numeric(non_empty, errors="coerce")
            invalid = int(values.isna().sum())
            field_check["non_numeric"] = invalid
            if invalid:
                result["blockers"].append(f"{field}: {invalid} non-numeric values")
            if "min_exclusive" in rule:
                threshold = float(rule["min_exclusive"])
                bad = int((values <= threshold).sum())
                field_check["lte_min_exclusive"] = bad
                if bad:
                    result["blockers"].append(f"{field}: {bad} values <= {threshold}")
            if "min" in rule:
                threshold = float(rule["min"])
                bad = int((values < threshold).sum())
                field_check["lt_min"] = bad
                if bad:
                    result["blockers"].append(f"{field}: {bad} values < {threshold}")
            if "max" in rule:
                threshold = float(rule["max"])
                bad = int((values > threshold).sum())
                field_check["gt_max"] = bad
                if bad:
                    result["blockers"].append(f"{field}: {bad} values > {threshold}")
        if "pattern" in rule:
            pattern = re.compile(str(rule["pattern"]))
            bad = int((~non_empty.astype(str).map(lambda value: bool(pattern.match(value)))).sum())
            field_check["pattern_mismatch"] = bad
            if bad:
                result["blockers"].append(f"{field}: {bad} values do not match {rule['pattern']}")
        result["checks"][field] = field_check
    return result


def _standard_contract_summary(data_dir: Path, layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    contract = _load_standard_contract(data_dir)
    result: dict[str, Any] = {
        "contract_path": contract.get("_path", ""),
        "standard_id": contract.get("standard_id", ""),
        "version": contract.get("version", ""),
        "roles": {},
        "warnings": [],
        "blockers": [],
    }
    if not contract:
        result["warnings"].append("missing one_map_role_contracts.zh.json; standard contract QA skipped")
        return result

    for role, (kind, target_name) in ROLE_CONTRACT_TARGETS.items():
        role_contract = contract.get("roles", {}).get(role)
        if not role_contract:
            result["warnings"].append(f"{role}: missing role contract")
            continue
        if kind == "layer":
            df = layers.get(target_name, gpd.GeoDataFrame())
        else:
            df = _load_table(data_dir, target_name)
        required = list(role_contract.get("required_fields", []))
        if df.empty:
            role_result = {
                "target": target_name,
                "kind": kind,
                "rows": 0,
                "required_count": len(required),
                "present_required_count": 0,
                "missing_required_fields": required,
                "null_required_counts": {},
                "field_rule_checks": {},
            }
            result["roles"][role] = role_result
            result["blockers"].append(f"{role}: target {target_name} is empty or missing")
            continue
        missing = [field for field in required if field not in df.columns]
        null_counts = {
            field: int((~_series_non_empty(df[field])).sum())
            for field in required
            if field in df.columns and int((~_series_non_empty(df[field])).sum()) > 0
        }
        rule_result = _validate_field_rules(df, role_contract.get("field_rules", {}))
        role_result = {
            "target": target_name,
            "kind": kind,
            "rows": int(len(df)),
            "required_count": len(required),
            "present_required_count": len(required) - len(missing),
            "missing_required_fields": missing,
            "null_required_counts": null_counts,
            "field_rule_checks": rule_result.get("checks", {}),
        }
        result["roles"][role] = role_result
        if missing:
            result["blockers"].append(f"{role}: missing required fields {missing}")
        for field, count in null_counts.items():
            result["blockers"].append(f"{role}.{field}: {count} empty required values")
        result["blockers"].extend([f"{role}.{msg}" for msg in rule_result.get("blockers", [])])
        result["warnings"].extend([f"{role}.{msg}" for msg in rule_result.get("warnings", [])])
    return result


def _admin_coverage(layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    parcels = layers.get("parcel_current", gpd.GeoDataFrame())
    if parcels.empty or "admin9" not in parcels.columns:
        return {"has_admin9": False, "unique_admin9": 0, "admin9_counts": {}}
    counts = parcels["admin9"].astype(str).value_counts().sort_index().to_dict()
    return {
        "has_admin9": True,
        "unique_admin9": int(len(counts)),
        "admin9_counts": {k: int(v) for k, v in counts.items()},
    }


def _raster_manifest_summary(data_dir: Path, project_crs: str) -> dict[str, Any]:
    path = data_dir / "raster_manifest.json"
    result: dict[str, Any] = {"missing_raster_manifest": not path.exists(), "products": {}, "warnings": [], "blockers": []}
    if not path.exists():
        return result
    if rasterio is None:
        result["blockers"].append("rasterio is not available for raster QA")
        return result
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = payload.get("products", {})
    if not products:
        result["warnings"].append("raster_manifest.json has no products")
    for name, product in products.items():
        raster_path = data_dir / product.get("relative_path", product.get("path", ""))
        if not raster_path.exists() and product.get("path"):
            raster_path = Path(product["path"])
        if not raster_path.exists():
            result["blockers"].append(f"{name}: raster file missing")
            result["products"][name] = {"exists": False, "path": str(raster_path)}
            continue
        with rasterio.open(raster_path) as src:
            array = src.read(1, masked=True)
            valid = np.asarray(array.compressed(), dtype="float64")
            stats = {
                "valid_pixels": int(valid.size),
                "min": round(float(valid.min()), 6) if valid.size else None,
                "mean": round(float(valid.mean()), 6) if valid.size else None,
                "max": round(float(valid.max()), 6) if valid.size else None,
            }
            summary = {
                "exists": True,
                "path": str(raster_path),
                "crs": str(src.crs),
                "width": int(src.width),
                "height": int(src.height),
                "count": int(src.count),
                "dtype": src.dtypes[0] if src.dtypes else "",
                "nodata": src.nodata,
                "bounds": [round(float(v), 3) for v in src.bounds],
                "band_description": src.descriptions[0] if src.descriptions else "",
                "stats": stats,
                "tags": src.tags(),
            }
            result["products"][name] = summary
            if src.crs is None:
                result["blockers"].append(f"{name}: missing CRS")
            elif str(src.crs) != project_crs:
                result["warnings"].append(f"{name}: CRS {src.crs} differs from project_crs {project_crs}")
            if src.width <= 0 or src.height <= 0 or src.count < 1:
                result["blockers"].append(f"{name}: invalid raster dimensions")
            if valid.size == 0:
                result["blockers"].append(f"{name}: no valid pixels")
            elif not np.isfinite(valid).all():
                result["blockers"].append(f"{name}: non-finite valid pixels")
    return result


def _real_imagery_summary(data_dir: Path, project_crs: str) -> dict[str, Any]:
    path = data_dir / "real_imagery_manifest.json"
    result: dict[str, Any] = {"missing_real_imagery_manifest": not path.exists(), "products": {}, "warnings": [], "blockers": []}
    if not path.exists():
        return result
    if rasterio is None:
        result["blockers"].append("rasterio is not available for real imagery QA")
        return result
    payload = json.loads(path.read_text(encoding="utf-8"))
    local_imagery_files = sorted((data_dir / "real_imagery").glob("*.tif"))
    if payload.get("synthetic") is not False:
        result["warnings"].append("real imagery manifest is not explicitly marked synthetic=false")
    if payload.get("not_for_production") is not False:
        result["warnings"].append("real imagery manifest is not explicitly marked not_for_production=false")
    result["stac"] = payload.get("stac", {})
    result["target_grid"] = payload.get("target_grid", {})
    result["source_errors"] = []
    if local_imagery_files and not payload.get("products"):
        result["blockers"].append(
            "real_imagery_manifest.json has no products while local real_imagery/*.tif files exist"
        )
    if payload.get("products") and not payload.get("sources"):
        result["warnings"].append("real imagery manifest has products but no source records")

    stac = result["stac"]
    if stac.get("coverage_ratio_estimate", 1.0) < 0.95:
        result["warnings"].append(
            f"real imagery coverage estimate below 95%: {stac.get('coverage_ratio_estimate')}"
        )
    if not stac.get("selected_items"):
        result["blockers"].append("real imagery manifest has no selected STAC items")

    for asset_name, records in payload.get("sources", {}).items():
        for record in records:
            if record.get("error"):
                result["source_errors"].append(
                    {
                        "asset": asset_name,
                        "item_id": record.get("item_id"),
                        "error": record.get("error"),
                    }
                )
    if result["source_errors"]:
        result["warnings"].append(f"real imagery source read errors: {len(result['source_errors'])}")

    product_set = str(result["target_grid"].get("product_set", ""))
    for name, product in payload.get("products", {}).items():
        raster_path = data_dir / product.get("relative_path", product.get("path", ""))
        if not raster_path.exists() and product.get("path"):
            raster_path = Path(product["path"])
        if not raster_path.exists():
            result["blockers"].append(f"{name}: real imagery file missing")
            result["products"][name] = {"exists": False, "path": str(raster_path)}
            continue
        with rasterio.open(raster_path) as src:
            valid_pixels = 0
            band_stats = []
            for band in range(1, src.count + 1):
                arr = src.read(band, masked=True)
                valid = np.asarray(arr.compressed(), dtype="float64")
                valid_pixels = max(valid_pixels, int(valid.size))
                band_stats.append(
                    {
                        "band": band,
                        "valid_pixels": int(valid.size),
                        "min": round(float(valid.min()), 6) if valid.size else None,
                        "mean": round(float(valid.mean()), 6) if valid.size else None,
                        "max": round(float(valid.max()), 6) if valid.size else None,
                    }
                )
            result["products"][name] = {
                "exists": True,
                "path": str(raster_path),
                "crs": str(src.crs),
                "width": int(src.width),
                "height": int(src.height),
                "count": int(src.count),
                "dtype": src.dtypes[0] if src.dtypes else "",
                "bounds": [round(float(v), 3) for v in src.bounds],
                "band_stats": band_stats,
                "manifest_type": product.get("type", ""),
                "manifest_band_order": product.get("band_order", []),
            }
            if src.crs is None:
                result["blockers"].append(f"{name}: missing CRS")
            elif str(src.crs) != project_crs:
                result["warnings"].append(f"{name}: CRS {src.crs} differs from project_crs {project_crs}")
            if valid_pixels == 0:
                result["blockers"].append(f"{name}: no valid pixels")
            if src.width <= 0 or src.height <= 0 or src.count < 1:
                result["blockers"].append(f"{name}: invalid raster dimensions")
            if product.get("type") == "visual_rgb" and src.count != 3:
                result["blockers"].append(f"{name}: RGB product should have exactly 3 bands")
            if product.get("type") == "scene_classification" and src.count != 1:
                result["blockers"].append(f"{name}: SCL product should have exactly 1 band")
            if product.get("type") == "spectral_index":
                for band in band_stats:
                    min_value = band.get("min")
                    max_value = band.get("max")
                    if min_value is not None and min_value < -1.0001:
                        result["blockers"].append(f"{name}: spectral index minimum below -1")
                    if max_value is not None and max_value > 1.0001:
                        result["blockers"].append(f"{name}: spectral index maximum above 1")
            if product.get("type") == "reflectance_stack":
                band_order = product.get("band_order", [])
                expected_count = len(band_order)
                if expected_count and src.count != expected_count:
                    result["blockers"].append(
                        f"{name}: band count {src.count} differs from manifest band_order {expected_count}"
                    )
                if product_set == "core" and src.count != 4:
                    result["warnings"].append(f"{name}: core product_set normally expects 4 reflectance bands")
                if product_set == "full" and src.count != 6:
                    result["warnings"].append(f"{name}: full product_set normally expects 6 reflectance bands")
    return result


def _optimization_summary(data_dir: Path) -> dict[str, Any]:
    optimization_dir = data_dir / "optimization"
    result: dict[str, Any] = {
        "exists": optimization_dir.exists(),
        "files": {},
        "warnings": [],
        "blockers": [],
    }
    if not optimization_dir.exists():
        result["warnings"].append("optimization directory missing")
        return result

    required_files = [
        "objective_catalog.csv",
        "action_space.geojson",
        "constraint_masks.geojson",
        "scenario_candidates.csv",
        "scenario_feasibility.csv",
        "scenario_project_membership.csv",
        "scenario_metrics.csv",
        "scenario_constraint_violations.csv",
        "pareto_summary.json",
    ]
    for filename in required_files:
        path = optimization_dir / filename
        result["files"][filename] = {"exists": path.exists()}
        if not path.exists():
            result["blockers"].append(f"optimization/{filename}: missing")

    def read_csv(filename: str) -> pd.DataFrame:
        path = optimization_dir / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    objectives = read_csv("objective_catalog.csv")
    scenarios = read_csv("scenario_candidates.csv")
    feasibility = read_csv("scenario_feasibility.csv")
    memberships = read_csv("scenario_project_membership.csv")
    metrics = read_csv("scenario_metrics.csv")
    violations = read_csv("scenario_constraint_violations.csv")

    result["counts"] = {
        "objectives": int(len(objectives)),
        "scenarios": int(len(scenarios)),
        "feasibility_rows": int(len(feasibility)),
        "memberships": int(len(memberships)),
        "metrics": int(len(metrics)),
        "violations": int(len(violations)),
    }
    if not objectives.empty and len(objectives) < 8:
        result["warnings"].append("optimization/objective_catalog.csv has fewer than 8 objectives")
    if not objectives.empty:
        hard = set(objectives.loc[objectives.get("hard_constraint", False).astype(bool), "objective_id"].astype(str))
        missing_hard = sorted({"pbf_overlap_m2", "eco_overlap_m2"} - hard)
        if missing_hard:
            result["blockers"].append(f"optimization objectives missing hard constraints {missing_hard}")
    if not scenarios.empty and not feasibility.empty:
        missing_feasibility = sorted(set(scenarios["scenario_id"].astype(str)) - set(feasibility["scenario_id"].astype(str)))
        result["checks"] = {
            "missing_scenario_feasibility": missing_feasibility[:20],
            "legal_feasible_scenarios": int((feasibility["optimization_scope"].astype(str) == "legal_feasible_space").sum())
            if "optimization_scope" in feasibility.columns
            else 0,
            "blocked_scenarios": int((feasibility["optimization_scope"].astype(str) == "stress_test_only").sum())
            if "optimization_scope" in feasibility.columns
            else 0,
        }
        if missing_feasibility:
            result["blockers"].append(f"scenario_feasibility missing {len(missing_feasibility)} scenarios")
        if result["checks"]["legal_feasible_scenarios"] == 0:
            result["warnings"].append("optimization has no legal feasible scenario")
    if not metrics.empty and not objectives.empty and not scenarios.empty:
        expected = len(objectives) * len(scenarios)
        result.setdefault("checks", {})["expected_metric_rows"] = int(expected)
        if len(metrics) != expected:
            result["blockers"].append(f"scenario_metrics rows {len(metrics)} != objective_count * scenario_count {expected}")

    pareto_path = optimization_dir / "pareto_summary.json"
    if pareto_path.exists():
        pareto = json.loads(pareto_path.read_text(encoding="utf-8"))
        result["pareto"] = {
            "method": pareto.get("method"),
            "comparison_scope": pareto.get("comparison_scope"),
            "objective_count": pareto.get("objective_count"),
            "scenario_count": pareto.get("scenario_count"),
            "legal_feasible_scenario_count": pareto.get("legal_feasible_scenario_count"),
            "blocked_scenario_count": pareto.get("blocked_scenario_count"),
            "ranked_count": len(pareto.get("ranked_scenarios", [])),
            "blocked_count": len(pareto.get("blocked_scenarios", [])),
        }
        ranked = pareto.get("ranked_scenarios", [])
        illegal_ranked = [
            row.get("scenario_id")
            for row in ranked
            if row.get("optimization_scope") != "legal_feasible_space"
        ]
        if illegal_ranked:
            result["blockers"].append(f"pareto_summary ranked scenarios outside legal feasible space: {illegal_ranked}")
        if pareto.get("comparison_scope") != "legal_feasible_space":
            result["warnings"].append("pareto_summary comparison_scope is not legal_feasible_space")

    evidence_path = data_dir / "tables" / "multimodal_evidence_index.csv"
    if evidence_path.exists():
        evidence = pd.read_csv(evidence_path)
        evidence_types = set(evidence.get("evidence_type", pd.Series(dtype=str)).astype(str))
        missing = sorted({"optimization_scenario_set", "optimization_pareto_summary"} - evidence_types)
        result["evidence"] = {"missing_evidence_types": missing}
        if missing:
            result["warnings"].append(f"optimization evidence types missing {missing}")
    return result


def _domain_integrity(data_dir: Path, layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    tables_dir = data_dir / "tables"
    result: dict[str, Any] = {"checks": {}, "warnings": [], "blockers": []}
    projects = layers.get("synthetic_projects", gpd.GeoDataFrame())
    project_ids = set(projects["project_id"].astype(str)) if "project_id" in projects.columns else set()

    def read_table(name: str) -> pd.DataFrame:
        path = tables_dir / f"{name}.csv"
        if not path.exists():
            result["blockers"].append(f"missing table {name}")
            return pd.DataFrame()
        return pd.read_csv(path)

    rule_eval = read_table("rule_evaluation")
    approval = read_table("approval_records")
    enforcement = read_table("enforcement_events")
    review = read_table("review_tasks")
    state = read_table("state_snapshots")
    field_catalog = read_table("standard_field_catalog")
    evidence = read_table("multimodal_evidence_index")

    if project_ids:
        for name, df in [("rule_evaluation", rule_eval), ("approval_records", approval)]:
            ids = set(df["project_id"].astype(str)) if "project_id" in df.columns else set()
            missing = sorted(project_ids - ids)
            result["checks"][f"{name}_project_coverage"] = {
                "expected_projects": len(project_ids),
                "covered_projects": len(project_ids - set(missing)),
                "missing_projects": missing[:20],
            }
            if missing:
                result["blockers"].append(f"{name}: missing {len(missing)} projects")
    if not rule_eval.empty:
        hit_count = int((rule_eval["finding_status"].astype(str) == "hit_requires_review").sum())
        result["checks"]["rule_hits"] = {"hit_requires_review": hit_count, "rows": len(rule_eval)}
        if hit_count == 0:
            result["warnings"].append("rule_evaluation: no rule hits")
    if not enforcement.empty and not review.empty:
        enforcement_ids = set(enforcement["enforcement_id"].astype(str))
        review_enforcement_ids = set(review["enforcement_id"].astype(str))
        missing_review = sorted(enforcement_ids - review_enforcement_ids)
        result["checks"]["enforcement_review_chain"] = {
            "enforcement_events": len(enforcement_ids),
            "reviewed_events": len(enforcement_ids - set(missing_review)),
            "missing_review": missing_review[:20],
        }
        if missing_review:
            result["warnings"].append(f"review_tasks: missing {len(missing_review)} enforcement events")
    if not state.empty:
        years = sorted(map(int, pd.to_numeric(state["snapshot_year"], errors="coerce").dropna().unique().tolist()))
        result["checks"]["state_snapshot_years"] = years
        if len(years) < 2:
            result["warnings"].append("state_snapshots: fewer than two years")
    if not field_catalog.empty:
        deprecated = int((field_catalog["lifecycle_status"].astype(str) == "deprecated").sum()) if "lifecycle_status" in field_catalog else 0
        result["checks"]["standard_field_catalog"] = {"rows": len(field_catalog), "deprecated_fields": deprecated}
        if deprecated == 0:
            result["warnings"].append("standard_field_catalog: no deprecated field sample")
    if project_ids and not evidence.empty:
        text_evidence = evidence[evidence["evidence_type"].astype(str) == "text_project_document"]
        evidence_projects = set(text_evidence["linked_object_id"].astype(str)) if not text_evidence.empty else set()
        missing = sorted(project_ids - evidence_projects)
        result["checks"]["project_text_evidence_coverage"] = {
            "expected_projects": len(project_ids),
            "covered_projects": len(project_ids - set(missing)),
            "missing_projects": missing[:20],
        }
        if missing:
            result["warnings"].append(f"multimodal_evidence_index: missing text evidence for {len(missing)} projects")
        raster_evidence = evidence[evidence["evidence_type"].astype(str) == "raster_observation"]
        result["checks"]["raster_observation_evidence"] = {
            "rows": int(len(raster_evidence)),
            "linked_products": sorted(raster_evidence["linked_object_id"].astype(str).unique().tolist()) if len(raster_evidence) else [],
        }
        if raster_evidence.empty:
            result["warnings"].append("multimodal_evidence_index: missing raster_observation evidence")
    real_manifest_path = data_dir / "real_imagery_manifest.json"
    if real_manifest_path.exists() and not evidence.empty:
        real_manifest = json.loads(real_manifest_path.read_text(encoding="utf-8"))
        real_products = real_manifest.get("products", {})
        real_evidence = evidence[evidence["evidence_type"].astype(str) == "observed_remote_sensing"]
        linked_real_products = (
            sorted(real_evidence["linked_object_id"].astype(str).unique().tolist())
            if len(real_evidence)
            else []
        )
        result["checks"]["observed_remote_sensing_evidence"] = {
            "expected_products": int(len(real_products)),
            "rows": int(len(real_evidence)),
            "linked_products": linked_real_products,
        }
        if real_products and real_evidence.empty:
            result["blockers"].append(
                "multimodal_evidence_index: missing observed_remote_sensing evidence for real imagery products"
            )
    return result


def _dictionary_coverage(data_dir: Path, layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    path = data_dir / "data_dictionary.zh.json"
    if not path.exists():
        return {"missing_dictionary": True}
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = payload.get("fields", {})
    layers_meta = payload.get("layers", {})
    unknown_fields = {}
    missing_layers = []
    for role, gdf in layers.items():
        if role not in layers_meta:
            missing_layers.append(role)
        missing = [c for c in gdf.columns if c != "geometry" and c not in fields]
        if missing:
            unknown_fields[role] = missing
    return {
        "missing_dictionary": False,
        "missing_layer_aliases": missing_layers,
        "unknown_fields": unknown_fields,
    }


def _manifest_summary(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "dataset_manifest.json"
    if not path.exists():
        return {"missing_manifest": True}
    payload = json.loads(path.read_text(encoding="utf-8"))
    abs_inputs = {
        k: v
        for k, v in payload.get("inputs", {}).items()
        if isinstance(v, str) and v.startswith("/")
    }
    return {
        "missing_manifest": False,
        "dataset_id": payload.get("dataset_id"),
        "not_for_production": payload.get("not_for_production"),
        "absolute_input_paths": abs_inputs,
        "layer_count": len(payload.get("layers", {})),
        "relation_count": len(payload.get("relations", {})),
        "table_count": len(payload.get("tables", {})),
        "has_standard_rules": bool(payload.get("standard_rules", {}).get("path")),
        "has_project_documents": bool(payload.get("documents", {}).get("project_documents_zh", {}).get("path")),
        "quality_gate": payload.get("generation", {}).get("quality_gate", {}),
    }


def _scenario_distributions(layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    out = {}
    for role, gdf in layers.items():
        role_out = {}
        for col in [
            "DLBM",
            "DLMC",
            "from_dlbm",
            "to_dlbm",
            "change_type",
            "project_type",
            "approval_status",
            "risk_scenario",
            "review_priority",
            "plan_zone_type",
            "sensor",
        ]:
            if col in gdf.columns:
                role_out[col] = gdf[col].astype(str).value_counts().head(30).to_dict()
        if role_out:
            out[role] = role_out
    return out


def _quality_status(report: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    warnings = []
    layers = report.get("layers", {})
    for role, summary in layers.items():
        if summary.get("invalid_geometries", 0) > 0:
            blockers.append(f"{role}: invalid geometries {summary['invalid_geometries']}")
        if summary.get("empty_geometries", 0) > 0:
            blockers.append(f"{role}: empty geometries {summary['empty_geometries']}")
        duplicates = summary.get("duplicate_counts", {})
        for col, count in duplicates.items():
            if count:
                blockers.append(f"{role}: duplicate {col} {count}")
    area = report.get("parcel_area_consistency", {})
    if area.get("count_gt_10pct", 0) > 0:
        warnings.append(f"parcel_current: {area['count_gt_10pct']} features exceed 10% area mismatch")
    continuity = layers.get("parcel_current", {}).get("connectedness", {})
    if continuity.get("largest_component_ratio", 0.0) < 0.95:
        warnings.append("parcel_current: largest connected component below 95%")
    relation_summary = report.get("relations", {})
    for required in ["project_parcel_rel", "project_pbf_rel", "project_eco_rel", "project_planning_rel", "project_rs_tile_rel"]:
        if relation_summary.get(required, {}).get("rows", 0) == 0:
            warnings.append(f"{required}: no rows")
    table_summary = report.get("tables", {})
    for required in [
        "rule_evaluation",
        "approval_records",
        "enforcement_events",
        "review_tasks",
        "state_snapshots",
        "standard_field_catalog",
        "multimodal_evidence_index",
    ]:
        if table_summary.get(required, {}).get("rows", 0) == 0:
            warnings.append(f"{required}: no rows")
    domain = report.get("domain_integrity", {})
    blockers.extend(domain.get("blockers", []))
    warnings.extend(domain.get("warnings", []))
    rasters = report.get("rasters", {})
    blockers.extend(rasters.get("blockers", []))
    warnings.extend(rasters.get("warnings", []))
    if rasters.get("missing_raster_manifest"):
        warnings.append("raster_manifest.json missing")
    elif len(rasters.get("products", {})) == 0:
        warnings.append("raster_manifest.json has no raster products")
    real = report.get("real_imagery", {})
    blockers.extend(real.get("blockers", []))
    warnings.extend(real.get("warnings", []))
    if real.get("missing_real_imagery_manifest"):
        warnings.append("real_imagery_manifest.json missing; using synthetic raster fixture fallback")
    optimization = report.get("optimization", {})
    blockers.extend(optimization.get("blockers", []))
    warnings.extend(optimization.get("warnings", []))
    dictionary = report.get("dictionary_coverage", {})
    if dictionary.get("unknown_fields"):
        warnings.append("data_dictionary.zh.json has unknown field gaps")
    standard_contracts = report.get("standard_contracts", {})
    blockers.extend(standard_contracts.get("blockers", []))
    warnings.extend(standard_contracts.get("warnings", []))
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "warnings": warnings,
    }


def build_report(data_dir: Path, project_crs: str) -> dict[str, Any]:
    layers = _load_layers(data_dir)
    report: dict[str, Any] = {
        "data_dir": str(data_dir),
        "project_crs": project_crs,
        "layers": {role: _layer_summary(role, gdf, project_crs) for role, gdf in layers.items()},
        "relations": _relation_summary(data_dir),
        "tables": _table_summary(data_dir),
        "admin_coverage": {},
        "rasters": _raster_manifest_summary(data_dir, project_crs),
        "real_imagery": _real_imagery_summary(data_dir, project_crs),
        "optimization": _optimization_summary(data_dir),
        "dictionary_coverage": _dictionary_coverage(data_dir, layers),
        "manifest": _manifest_summary(data_dir),
        "distributions": _scenario_distributions(layers),
    }
    report["admin_coverage"] = _admin_coverage(layers)
    report["domain_integrity"] = _domain_integrity(data_dir, layers)
    report["standard_contracts"] = _standard_contract_summary(data_dir, layers)
    if "parcel_current" in layers:
        report["parcel_area_consistency"] = _area_consistency(layers["parcel_current"])
        report["parcel_internal_overlaps"] = _internal_overlap(layers["parcel_current"], project_crs)
        projected = layers["parcel_current"].to_crs(project_crs)
        union_geom = unary_union(list(projected.geometry)) if len(projected) else None
        parts = list(union_geom.geoms) if union_geom is not None and hasattr(union_geom, "geoms") else ([union_geom] if union_geom is not None else [])
        report["parcel_union"] = {
            "union_type": union_geom.geom_type if union_geom is not None else "",
            "union_parts": len(parts),
            "interior_ring_count": int(
                sum(len(part.interiors) for part in parts if hasattr(part, "interiors"))
            ),
            "union_area_m2": round(float(union_geom.area), 3) if union_geom is not None else 0.0,
        }
    if {"synthetic_projects", "synthetic_pbf"}.issubset(layers):
        report.setdefault("overlays", {})["project_pbf"] = _positive_overlay(
            layers["synthetic_projects"],
            layers["synthetic_pbf"],
            left_id="project_id",
            right_id="control_id",
            project_crs=project_crs,
        )
    if {"synthetic_projects", "synthetic_eco_redline"}.issubset(layers):
        report.setdefault("overlays", {})["project_eco"] = _positive_overlay(
            layers["synthetic_projects"],
            layers["synthetic_eco_redline"],
            left_id="project_id",
            right_id="redline_id",
            project_crs=project_crs,
        )
    if {"synthetic_projects", "synthetic_planning_zones"}.issubset(layers):
        report.setdefault("overlays", {})["project_planning"] = _positive_overlay(
            layers["synthetic_projects"],
            layers["synthetic_planning_zones"],
            left_id="project_id",
            right_id="plan_zone_id",
            project_crs=project_crs,
        )
    if {"synthetic_pbf", "synthetic_eco_redline"}.issubset(layers):
        report.setdefault("overlays", {})["pbf_eco"] = _positive_overlay(
            layers["synthetic_pbf"],
            layers["synthetic_eco_redline"],
            left_id="control_id",
            right_id="redline_id",
            project_crs=project_crs,
        )
    report["quality_gate"] = _quality_status(report)
    return report


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    rows = []
    for role, summary in report.get("layers", {}).items():
        rows.append(
            "| {role} | {rows} | {geom} | {invalid} | {empty} | {area} |".format(
                role=role,
                rows=summary.get("rows", 0),
                geom=", ".join(summary.get("geometry_types", [])),
                invalid=summary.get("invalid_geometries", 0),
                empty=summary.get("empty_geometries", 0),
                area=summary.get("area_m2_sum", 0),
            )
        )
    rel_rows = []
    for name, summary in report.get("relations", {}).items():
        rel_rows.append(f"| {name} | {summary.get('rows', 0)} | {summary.get('unique_projects', 0)} |")
    table_rows = []
    for name, summary in report.get("tables", {}).items():
        table_rows.append(
            f"| {name} | {summary.get('rows', 0)} | {summary.get('unique_projects', 0)} |"
        )
    standard_rows = []
    for role, summary in report.get("standard_contracts", {}).get("roles", {}).items():
        standard_rows.append(
            "| {role} | {target} | {rows} | {present}/{required} | {missing} | {nulls} |".format(
                role=role,
                target=summary.get("target", ""),
                rows=summary.get("rows", 0),
                present=summary.get("present_required_count", 0),
                required=summary.get("required_count", 0),
                missing=", ".join(summary.get("missing_required_fields", [])),
                nulls=json.dumps(summary.get("null_required_counts", {}), ensure_ascii=False),
            )
        )
    raster_rows = []
    for name, summary in report.get("rasters", {}).get("products", {}).items():
        stats = summary.get("stats", {})
        raster_rows.append(
            "| {name} | {width}x{height} | {crs} | {valid} | {mean} |".format(
                name=name,
                width=summary.get("width", 0),
                height=summary.get("height", 0),
                crs=summary.get("crs", ""),
                valid=stats.get("valid_pixels", 0),
                mean=stats.get("mean", ""),
            )
        )
    real_rows = []
    for name, summary in report.get("real_imagery", {}).get("products", {}).items():
        stats = summary.get("band_stats", [{}])
        first = stats[0] if stats else {}
        real_rows.append(
            "| {name} | {width}x{height} | {count} | {crs} | {valid} | {mean} |".format(
                name=name,
                width=summary.get("width", 0),
                height=summary.get("height", 0),
                count=summary.get("count", 0),
                crs=summary.get("crs", ""),
                valid=first.get("valid_pixels", 0),
                mean=first.get("mean", ""),
            )
        )
    optimization = report.get("optimization", {})
    optimization_counts = optimization.get("counts", {})
    optimization_pareto = optimization.get("pareto", {})
    overlay_rows = []
    for name, summary in report.get("overlays", {}).items():
        overlay_rows.append(
            "| {name} | {pos} | {ul} | {ur} | {mean} | {exact} |".format(
                name=name,
                pos=summary.get("positive_intersections", 0),
                ul=summary.get("unique_left", 0),
                ur=summary.get("unique_right", 0),
                mean=summary.get("mean_overlap_ratio_left", 0),
                exact=summary.get("gt_99pct_left", 0),
            )
        )
    status = report.get("quality_gate", {})
    md = f"""# TWM Demo Data Quality Report

## Gate Status

- Status: `{status.get("status", "unknown")}`
- Blockers: {len(status.get("blockers", []))}
- Warnings: {len(status.get("warnings", []))}

### Blockers

{chr(10).join(f"- {item}" for item in status.get("blockers", [])) or "- None"}

### Warnings

{chr(10).join(f"- {item}" for item in status.get("warnings", [])) or "- None"}

## Layer Quality

| Layer | Rows | Geometry | Invalid | Empty | Area m2 |
|---|---:|---|---:|---:|---:|
{chr(10).join(rows)}

## Parcel Continuity

```json
{json.dumps(report.get("layers", {}).get("parcel_current", {}).get("connectedness", {}), ensure_ascii=False, indent=2)}
```

## Admin Coverage

```json
{json.dumps(report.get("admin_coverage", {}), ensure_ascii=False, indent=2)}
```

## Parcel Area Consistency

```json
{json.dumps(report.get("parcel_area_consistency", {}), ensure_ascii=False, indent=2)}
```

## Overlay Semantics

| Overlay | Positive intersections | Unique left | Unique right | Mean left ratio | Full-cover hits |
|---|---:|---:|---:|---:|---:|
{chr(10).join(overlay_rows)}

## Relation Tables

| Relation | Rows | Unique projects |
|---|---:|---:|
{chr(10).join(rel_rows)}

## Governance Tables

| Table | Rows | Unique projects |
|---|---:|---:|
{chr(10).join(table_rows)}

## One Map Standard Contracts

Contract: `{report.get("standard_contracts", {}).get("contract_path", "")}`

| Role | Target | Rows | Required fields | Missing | Empty required |
|---|---|---:|---:|---|---|
{chr(10).join(standard_rows)}

## Raster Fixtures

| Raster | Size | CRS | Valid pixels | Mean |
|---|---:|---|---:|---:|
{chr(10).join(raster_rows)}

## Real Imagery

```json
{json.dumps({k: report.get("real_imagery", {}).get(k) for k in ["missing_real_imagery_manifest", "stac", "target_grid"]}, ensure_ascii=False, indent=2)}
```

| Product | Size | Bands | CRS | First-band valid pixels | First-band mean |
|---|---:|---:|---|---:|---:|
{chr(10).join(real_rows)}

## Optimization Dataset

```json
{json.dumps({"exists": optimization.get("exists"), "counts": optimization_counts, "pareto": optimization_pareto}, ensure_ascii=False, indent=2)}
```

## Domain Integrity

```json
{json.dumps(report.get("domain_integrity", {}), ensure_ascii=False, indent=2)}
```

## Dictionary Coverage

```json
{json.dumps(report.get("dictionary_coverage", {}), ensure_ascii=False, indent=2)}
```
"""
    path.write_text(md, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--project-crs", default=DEFAULT_PROJECT_CRS)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--md-out", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    report = build_report(data_dir, args.project_crs)
    json_out = Path(args.json_out) if args.json_out else data_dir / "data_quality_report.json"
    md_out = Path(args.md_out) if args.md_out else data_dir / "data_quality_report.md"
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_markdown(report, md_out)
    print(
        json.dumps(
            {
                "status": report["quality_gate"]["status"],
                "json": str(json_out),
                "markdown": str(md_out),
                "blockers": report["quality_gate"]["blockers"],
                "warnings": report["quality_gate"]["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
