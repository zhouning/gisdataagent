"""Auditable spatial-unit monitoring evaluation for planning implementation.

The module is intentionally a small deterministic model, not a chat feature or
a legal compliance engine.  It consumes governed GeoParquet/COG outputs and
produces indicators, relative diagnostics, quality evidence and lineage.  A
deployment can replace the grid with an approved administrative/planning-unit
contract later without changing the indicator contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MODEL_ID = "gda.nr.planning-monitoring.current-state"
MODEL_VERSION = "1.0.0"
CONTRACT_RESOURCE = "model_contracts/planning_monitoring_current_state.v1.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_clean(value: Any) -> Any:
    """Convert numpy values and non-finite floats before strict JSON output."""

    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_model_contract() -> dict[str, Any]:
    resource = files("data_agent").joinpath(CONTRACT_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def _contract_hash(contract: dict[str, Any]) -> str:
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonitoringConfig:
    """Runtime choices which must be recorded in the model evidence."""

    cell_size_m: int = 5000
    analysis_crs: str | None = None
    dem_resolution_m: int = 250
    sample_scope: str = "chongqing_demo"
    authority_mode: str = "rehearsal"


def discover_materialized_inputs(materialization_path: str | Path) -> dict[str, Any]:
    """Map materialization targets to model roles using conservative aliases.

    The mapping is a model input adapter, not an EA contract.  Every selected
    target keeps its original target id, source asset id and declared hash.
    """

    payload = json.loads(Path(materialization_path).read_text(encoding="utf-8"))
    targets = payload.get("outputs") or payload.get("targets") or []
    candidates: dict[str, list[dict[str, Any]]] = {
        "building": [],
        "poi": [],
        "road": [],
        "land_cover": [],
        "dem": [],
    }
    for target in targets:
        if target.get("execution_status") not in {None, "succeeded"}:
            continue
        path = str(target.get("target_path") or "")
        if not path or not Path(path).is_file():
            continue
        text = " ".join(
            str(target.get(key) or "")
            for key in ("target_name", "source_layer", "source_raw_path", "canonical_dataset")
        ).lower()
        role = None
        if path.lower().endswith((".tif", ".tiff")):
            if any(token in text for token in ("clcd", "landcover", "土地覆盖", "土地利用")):
                role = "land_cover"
            elif any(token in text for token in ("dem", "gdem", "elevation", "高程")):
                role = "dem"
        else:
            if any(token in text for token in ("建筑", "building", "zrz", "自然幢")):
                role = "building"
            elif any(token in text for token in ("poi", "兴趣点", "高德地图")):
                role = "poi"
            elif any(token in text for token in ("osm", "road", "道路", "路网")):
                role = "road"
        if role:
            candidates[role].append(target)

    # Prefer the largest/most complete target when a batch contains duplicates.
    selected: dict[str, dict[str, Any] | None] = {}
    for role, values in candidates.items():
        selected[role] = max(
            values,
            key=lambda item: int(
                (item.get("materialization_profile") or {}).get("feature_count") or 0
            )
            if not str(item.get("target_path", "")).lower().endswith((".tif", ".tiff"))
            else int(item.get("target_size") or 0),
            default=None,
        )
    return {"materialization": str(Path(materialization_path).resolve()), "roles": selected}


def _read_vector(path: Path, *, columns: list[str] | None = None):
    import geopandas as gpd

    if path.suffix.lower() == ".parquet":
        kwargs = {"columns": columns} if columns else {}
        return gpd.read_parquet(path, **kwargs)
    from .local_gis_runtime import read_vector

    return read_vector(path)


def _role_target(inputs: dict[str, Any], role: str) -> tuple[Path | None, dict[str, Any] | None]:
    target = (inputs.get("roles") or {}).get(role)
    if not target:
        return None, None
    path = Path(str(target["target_path"])).expanduser().resolve()
    return path, target


def _select_analysis_crs(buildings, configured: str | None) -> str:
    if configured:
        return configured
    estimated = buildings.estimate_utm_crs()
    if estimated is None:
        raise ValueError("building layer has no usable CRS; analysis_crs is required")
    return estimated.to_string()


def _make_grid(buildings, analysis_crs: str, cell_size: int):
    import geopandas as gpd
    from shapely.geometry import box

    projected = buildings.to_crs(analysis_crs)
    minx, miny, maxx, maxy = projected.total_bounds
    if not np.isfinite([minx, miny, maxx, maxy]).all():
        raise ValueError("building extent is empty or non-finite")
    origin_x = math.floor(minx / cell_size) * cell_size
    origin_y = math.floor(miny / cell_size) * cell_size
    ncols = max(1, math.ceil((maxx - origin_x) / cell_size))
    nrows = max(1, math.ceil((maxy - origin_y) / cell_size))
    if nrows * ncols > 10000:
        raise ValueError("building extent produces more than 10,000 monitoring units")
    rows = []
    for row in range(nrows):
        for col in range(ncols):
            rows.append(
                {
                    "unit_id": f"U{row:04d}_{col:04d}",
                    "grid_row": row,
                    "grid_col": col,
                    "geometry": box(
                        origin_x + col * cell_size,
                        origin_y + row * cell_size,
                        origin_x + (col + 1) * cell_size,
                        origin_y + (row + 1) * cell_size,
                    ),
                }
            )
    return gpd.GeoDataFrame(rows, crs=analysis_crs), projected, {
        "origin_x": origin_x,
        "origin_y": origin_y,
        "nrows": nrows,
        "ncols": ncols,
    }


def _unit_indices(
    frame, grid_meta: dict[str, Any], cell_size: int
) -> tuple[np.ndarray, np.ndarray]:
    points = frame.geometry.representative_point()
    x = points.x.to_numpy()
    y = points.y.to_numpy()
    cols = np.floor((x - grid_meta["origin_x"]) / cell_size).astype("int64")
    rows = np.floor((y - grid_meta["origin_y"]) / cell_size).astype("int64")
    return rows, cols


def _aggregate_buildings(buildings, grid, grid_meta: dict[str, Any], cell_size: int):
    projected = buildings.to_crs(grid.crs).copy()
    original_count = len(projected)
    null_count = int(projected.geometry.isna().sum())
    non_null = projected[~projected.geometry.isna()].copy()
    empty_count = int(non_null.geometry.is_empty.sum())
    invalid_count = int((~non_null.geometry.is_valid).sum())
    non_null = non_null[~non_null.geometry.is_empty].copy()
    if invalid_count:
        non_null["geometry"] = non_null.geometry.make_valid()
    non_null = non_null[non_null.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    rows, cols = _unit_indices(non_null, grid_meta, cell_size)
    in_bounds = (
        (rows >= 0)
        & (rows < grid_meta["nrows"])
        & (cols >= 0)
        & (cols < grid_meta["ncols"])
    )
    non_null = non_null.loc[in_bounds].copy()
    non_null["grid_row"] = rows[in_bounds]
    non_null["grid_col"] = cols[in_bounds]
    non_null["__area_m2"] = non_null.geometry.area
    floor_col = next(
        (name for name in ("Floor", "floor", "层数", "总层数") if name in non_null), None
    )
    if floor_col:
        floors = pd.to_numeric(non_null[floor_col], errors="coerce")
        floors = floors.where((floors > 0) & (floors <= 200))
    else:
        floors = pd.Series(np.nan, index=non_null.index)
    non_null["__floor"] = floors
    non_null["__floor_area"] = non_null["__area_m2"] * non_null["__floor"]
    grouped = non_null.groupby(["grid_row", "grid_col"], dropna=False)
    aggregates = grouped.agg(
        building_count=("__area_m2", "size"),
        building_footprint_m2=("__area_m2", "sum"),
        avg_floors=("__floor", "mean"),
        estimated_floor_area_m2=("__floor_area", "sum"),
        valid_floor_count=("__floor", "count"),
    ).reset_index()
    result = grid.merge(aggregates, on=["grid_row", "grid_col"], how="left")
    for column in ("building_count", "building_footprint_m2", "valid_floor_count"):
        result[column] = result[column].fillna(0)
    result["unit_area_m2"] = result.geometry.area
    result["building_coverage_pct"] = result["building_footprint_m2"] / result["unit_area_m2"] * 100
    result["estimated_far"] = result["estimated_floor_area_m2"] / result["unit_area_m2"]
    return result, {
        "input_feature_count": original_count,
        "null_geometry_count": null_count,
        "empty_geometry_count": empty_count,
        "invalid_geometry_count": invalid_count,
        "geometry_used_count": int(len(non_null)),
        "floor_field": floor_col,
        "missing_or_invalid_floor_count": int(len(non_null) - floors.notna().sum()),
    }


def _aggregate_points(path: Path, grid, config: MonitoringConfig, grid_meta: dict[str, Any]):
    frame = _read_vector(path, columns=["geometry"])
    if frame.crs is None:
        raise ValueError(f"point source has no CRS: {path}")
    projected = frame.to_crs(grid.crs)
    rows, cols = _unit_indices(projected, grid_meta, config.cell_size_m)
    valid = (
        (~projected.geometry.isna().to_numpy())
        & (~projected.geometry.is_empty.to_numpy())
        & (rows >= 0)
        & (rows < grid_meta["nrows"])
        & (cols >= 0)
        & (cols < grid_meta["ncols"])
    )
    counts = pd.DataFrame({"grid_row": rows[valid], "grid_col": cols[valid]}).value_counts()
    result = grid[["unit_id"]].copy()
    result["poi_count"] = [
        int(counts.get((row, col), 0))
        for row, col in grid[["grid_row", "grid_col"]].itertuples(index=False)
    ]
    return result, {
        "input_feature_count": int(len(frame)),
        "valid_geometry_count": int(valid.sum()),
        "outside_grid_count": int((~valid).sum()),
    }


def _aggregate_roads(path: Path, grid):
    import geopandas as gpd

    frame = _read_vector(path)
    if frame.crs is None:
        raise ValueError(f"road source has no CRS: {path}")
    projected = frame.to_crs(grid.crs)
    projected = projected[~projected.geometry.isna() & ~projected.geometry.is_empty].copy()
    # Spatial intersection is needed here: assigning a long road to its
    # centroid would materially undercount boundary-crossing units.
    joined = gpd.overlay(
        projected[["geometry"]],
        grid[["unit_id", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    if len(joined):
        joined["__length_km"] = joined.geometry.length / 1000
        lengths = joined.groupby("unit_id")["__length_km"].sum()
    else:
        lengths = pd.Series(dtype="float64")
    result = grid[["unit_id"]].copy()
    result["road_length_km"] = result["unit_id"].map(lengths).fillna(0.0)
    return result, {
        "input_feature_count": int(len(frame)),
        "geometry_used_count": int(len(projected)),
        "intersected_piece_count": int(len(joined)),
    }


def _raster_unit_stats(path: Path, grid, *, role: str, dem_resolution_m: int):
    import rasterio
    from pyproj import Transformer
    from rasterio.mask import geometry_mask, mask
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import mapping
    from shapely.ops import transform as shapely_transform

    stats: list[dict[str, Any]] = []
    if role == "dem":
        source = rasterio.open(path)
        transform_to_grid = Transformer.from_crs(grid.crs, source.crs, always_xy=True).transform
        try:
            with WarpedVRT(
                source,
                crs=grid.crs,
                resampling=rasterio.enums.Resampling.bilinear,
                resolution=(dem_resolution_m, dem_resolution_m),
            ) as dataset:
                for row in grid.itertuples(index=False):
                    try:
                        data, affine = mask(
                            dataset,
                            [mapping(row.geometry)],
                            crop=True,
                            filled=False,
                            indexes=1,
                        )
                    except ValueError:
                        stats.append(
                            {
                                "unit_id": row.unit_id,
                                "mean_elevation_m": np.nan,
                                "mean_slope_deg": np.nan,
                                "dem_valid_fraction": 0.0,
                            }
                        )
                        continue
                    inside = geometry_mask(
                        [mapping(row.geometry)],
                        out_shape=data.shape,
                        transform=affine,
                        invert=True,
                    )
                    values = np.asarray(data.data, dtype="float64")
                    valid = inside & ~np.ma.getmaskarray(data) & np.isfinite(values)
                    if not valid.any():
                        stats.append(
                            {
                                "unit_id": row.unit_id,
                                "mean_elevation_m": np.nan,
                                "mean_slope_deg": np.nan,
                                "dem_valid_fraction": 0.0,
                            }
                        )
                        continue
                    values[~valid] = np.nan
                    gy, gx = np.gradient(values, abs(affine.e), abs(affine.a))
                    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
                    slope_valid = valid & np.isfinite(slope)
                    stats.append(
                        {
                            "unit_id": row.unit_id,
                            "mean_elevation_m": float(np.nanmean(values[valid])),
                            "mean_slope_deg": (
                                float(np.nanmean(slope[slope_valid]))
                                if slope_valid.any()
                                else np.nan
                            ),
                            "dem_valid_fraction": float(
                                valid.sum() / max(int(inside.sum()), 1)
                            ),
                        }
                    )
        finally:
            source.close()
        return pd.DataFrame(stats), {"input_path": str(path), "role": role}

    with rasterio.open(path) as dataset:
        transform_to_grid = Transformer.from_crs(grid.crs, dataset.crs, always_xy=True).transform
        for row in grid.itertuples(index=False):
            geom = shapely_transform(transform_to_grid, row.geometry)
            try:
                data, affine = mask(
                    dataset, [mapping(geom)], crop=True, filled=False, indexes=1
                )
            except ValueError:
                stats.append(
                    {
                        "unit_id": row.unit_id,
                        "impervious_share_pct": np.nan,
                        "water_share_pct": np.nan,
                        "land_cover_valid_fraction": 0.0,
                    }
                )
                continue
            inside = geometry_mask(
                [mapping(geom)], out_shape=data.shape, transform=affine, invert=True
            )
            values = np.asarray(data.data)
            valid = inside & ~np.ma.getmaskarray(data) & np.isfinite(values)
            total = int(valid.sum())
            stats.append(
                {
                    "unit_id": row.unit_id,
                    "impervious_share_pct": (
                        float((values[valid] == 8).sum() / total * 100) if total else np.nan
                    ),
                    "water_share_pct": (
                        float((values[valid] == 5).sum() / total * 100) if total else np.nan
                    ),
                    "land_cover_valid_fraction": float(total / max(int(inside.sum()), 1)),
                }
            )
    return pd.DataFrame(stats), {"input_path": str(path), "role": role}


def _percentile(series: pd.Series, quantile: float) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(quantile)) if len(values) else None


def _relative_diagnostics(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    import pandas.api.types as ptypes

    thresholds = {
        "far_p25": _percentile(frame["estimated_far"], 0.25),
        "far_p75": _percentile(frame["estimated_far"], 0.75),
        "poi_p25": _percentile(frame["poi_density_km2"], 0.25),
        "road_p25": _percentile(frame["road_density_km_km2"], 0.25),
        "slope_p75": _percentile(frame["mean_slope_deg"], 0.75),
        "impervious_p75": _percentile(frame["impervious_share_pct"], 0.75),
    }
    diagnostics: list[list[str]] = []
    far_high = thresholds["far_p75"]
    poi_low = thresholds["poi_p25"]
    road_low = thresholds["road_p25"]
    slope_high = thresholds["slope_p75"]
    impervious_high = thresholds["impervious_p75"]
    for row in frame.itertuples(index=False):
        values: list[str] = []
        if (
            far_high is not None
            and poi_low is not None
            and pd.notna(row.estimated_far)
            and pd.notna(row.poi_density_km2)
            and row.estimated_far >= far_high
            and row.poi_density_km2 <= poi_low
        ):
            values.append("HIGH_BUILD_LOW_SERVICE")
        if (
            road_low is not None
            and pd.notna(row.road_density_km_km2)
            and row.road_density_km_km2 <= road_low
        ):
            values.append("LOW_ROAD_DENSITY")
        if (
            slope_high is not None
            and pd.notna(row.mean_slope_deg)
            and row.mean_slope_deg >= slope_high
        ):
            values.append("HIGH_TERRAIN_CONSTRAINT")
        if (
            impervious_high is not None
            and pd.notna(row.impervious_share_pct)
            and row.impervious_share_pct >= impervious_high
        ):
            values.append("HIGH_IMPERVIOUS_PRESSURE")
        diagnostics.append(values)
    frame = frame.copy()
    frame["diagnostic_codes"] = diagnostics
    frame["diagnostic_count"] = [len(item) for item in diagnostics]

    score_parts = []
    for column, weight in (
        ("estimated_far", 0.4),
        ("poi_density_km2", 0.3),
        ("road_density_km_km2", 0.3),
    ):
        if column not in frame:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if ptypes.is_numeric_dtype(values) and values.notna().sum() >= 2:
            score_parts.append(values.rank(pct=True) * weight)
    frame["current_state_intensity_score"] = sum(score_parts) * 100 if score_parts else np.nan
    frame["current_state_intensity_rank"] = (
        frame["current_state_intensity_score"]
        .rank(method="min", ascending=False)
        .where(frame["current_state_intensity_score"].notna())
    )
    return frame, thresholds


def run_monitoring_evaluation(
    materialization_path: str | Path,
    output_dir: str | Path,
    *,
    config: MonitoringConfig | None = None,
) -> dict[str, Any]:
    """Run the model and persist all evidence under ``output_dir``."""

    config = config or MonitoringConfig()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    contract = load_model_contract()
    inputs = discover_materialized_inputs(materialization_path)
    run_id = f"monitor-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    input_evidence: dict[str, Any] = {}
    for role, target in (inputs.get("roles") or {}).items():
        if not target:
            continue
        path = Path(str(target["target_path"])).resolve()
        actual_hash = _sha256(path)
        declared_hash = target.get("target_sha256")
        input_evidence[role] = {
            "role": role,
            "path": str(path),
            "target_id": target.get("target_id"),
            "source_asset_id": target.get("source_asset_id"),
            "declared_sha256": declared_hash,
            "actual_sha256": actual_hash,
            "sha256_verified": not declared_hash or declared_hash == actual_hash,
            "target_name": target.get("target_name"),
        }
    building_path, _ = _role_target(inputs, "building")
    if not building_path:
        raise ValueError("no building target found; model requires a polygon building source")

    raw_buildings = _read_vector(building_path)
    if raw_buildings.empty:
        raise ValueError("building source is empty")
    analysis_crs = _select_analysis_crs(raw_buildings, config.analysis_crs)
    grid, _, grid_meta = _make_grid(raw_buildings, analysis_crs, config.cell_size_m)
    units, building_quality = _aggregate_buildings(
        raw_buildings, grid, grid_meta, config.cell_size_m
    )
    units = units[units["building_count"] > 0].copy()
    # The grid's active cells are the observed building extent.  This avoids
    # claiming that empty cells represent planned land or administrative area.
    if units.empty:
        raise ValueError("no valid building geometry could be assigned to monitoring units")

    role_quality: dict[str, Any] = {"building": building_quality}
    for role, columns in (
        ("poi", ["poi_count"]),
        ("road", ["road_length_km"]),
        ("land_cover", ["impervious_share_pct", "water_share_pct"]),
        ("dem", ["mean_elevation_m", "mean_slope_deg"]),
    ):
        path, _ = _role_target(inputs, role)
        if not path:
            for column in columns:
                units[column] = np.nan
            continue
        if role == "poi":
            aggregate, quality = _aggregate_points(path, grid, config, grid_meta)
        elif role == "road":
            aggregate, quality = _aggregate_roads(path, grid)
        else:
            aggregate, quality = _raster_unit_stats(
                path, grid, role=role, dem_resolution_m=config.dem_resolution_m
            )
        units = units.merge(aggregate, on=["unit_id"], how="left")
        role_quality[role] = quality

    units["poi_density_km2"] = units["poi_count"] / (units["unit_area_m2"] / 1_000_000)
    units["road_density_km_km2"] = units["road_length_km"] / (units["unit_area_m2"] / 1_000_000)
    units, thresholds = _relative_diagnostics(units)
    units = units.sort_values(["current_state_intensity_rank", "unit_id"], na_position="last")

    # Keep the spatial output small enough for the offline UI while retaining
    # every computed indicator and a stable unit identifier.
    spatial_path = output / "spatial_units.parquet"
    units.to_parquet(spatial_path, index=False)
    units.to_file(output / "spatial_units.geojson", driver="GeoJSON")
    csv_path = output / "indicators.csv"
    units.drop(columns="geometry").to_csv(csv_path, index=False, encoding="utf-8-sig")

    role_status = {
        role: "available" if evidence
        else "missing"
        for role, evidence in input_evidence.items()
    }
    missing_optional = [
        role for role in ("poi", "road", "land_cover", "dem") if role not in input_evidence
    ]
    quality_status = "pass"
    if (
        missing_optional
        or building_quality["null_geometry_count"]
        or building_quality["empty_geometry_count"]
        or building_quality["invalid_geometry_count"]
        or building_quality["missing_or_invalid_floor_count"]
    ):
        quality_status = "review"
    for role in ("land_cover", "dem"):
        if role in role_quality:
            fraction_column = (
                "land_cover_valid_fraction"
                if role == "land_cover"
                else "dem_valid_fraction"
            )
            fractions = units[fraction_column]
            if fractions.notna().any() and float(fractions.median()) < 0.8:
                quality_status = "review"
    hash_verified = all(item["sha256_verified"] for item in input_evidence.values())
    if not hash_verified:
        quality_status = "blocked"

    outputs = []
    for path, kind in (
        (spatial_path, "geoparquet"),
        (output / "spatial_units.geojson", "geojson"),
        (csv_path, "csv"),
    ):
        outputs.append(
            {
                "path": str(path),
                "kind": kind,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    lineage = {
        "lineage_id": f"lineage:{run_id}",
        "run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_hash": _contract_hash(contract),
        "edges": [
            {
                "source": evidence["target_id"] or evidence["actual_sha256"],
                "source_role": role,
                "source_sha256": evidence["actual_sha256"],
                "target": f"model-run:{run_id}",
                "relation": "consumed_by_model",
            }
            for role, evidence in input_evidence.items()
        ]
        + [
            {"source": f"model-run:{run_id}", "target": item["path"], "relation": "materialized"}
            for item in outputs
        ],
    }
    _write_json(output / "lineage.json", lineage)
    quality = {
        "run_id": run_id,
        "status": quality_status,
        "checks": {
            "input_hashes": {
                role: item["sha256_verified"] for role, item in input_evidence.items()
            },
            "building": building_quality,
            "role_availability": role_status,
            "missing_optional_roles": missing_optional,
            "land_cover_median_valid_fraction": (
                float(units["land_cover_valid_fraction"].median())
                if "land_cover_valid_fraction" in units
                and units["land_cover_valid_fraction"].notna().any()
                else None
            ),
            "dem_median_valid_fraction": (
                float(units["dem_valid_fraction"].median())
                if "dem_valid_fraction" in units
                and units["dem_valid_fraction"].notna().any()
                else None
            ),
        },
        "role_quality": role_quality,
        "limitations": [
            "重庆样例不是宁夏权威数据",
            "空间单元为建筑范围规则网格，不是法定行政区或规划评估单元",
            "诊断阈值为样例内部P25/P75，不是政策阈值",
            "单期数据不能证明规划目标达成趋势或年度变化",
        ],
    }
    _write_json(output / "quality_report.json", quality)

    diagnostic_counts = (
        pd.Series([code for codes in units["diagnostic_codes"] for code in codes])
        .value_counts()
        .to_dict()
    )
    summary = {
        "run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_id": contract.get("contract_id"),
        "contract_hash": _contract_hash(contract),
        "sample_scope": config.sample_scope,
        "authority_mode": config.authority_mode,
        "production_eligible": False,
        "status": "succeeded_with_review" if quality_status == "review" else quality_status,
        "analysis_crs": analysis_crs,
        "cell_size_m": config.cell_size_m,
        "unit_count": int(len(units)),
        "input_evidence": input_evidence,
        "role_quality": role_quality,
        "relative_thresholds": thresholds,
        "diagnostic_counts": {str(key): int(value) for key, value in diagnostic_counts.items()},
        "outputs": outputs,
        "quality_report": str(output / "quality_report.json"),
        "lineage": str(output / "lineage.json"),
        "started_at": _now(),
        "limitations": quality["limitations"],
    }
    _write_json(output / "monitoring_evaluation_report.json", summary)
    _write_markdown(output / "monitoring_evaluation_report.md", summary, units)
    return summary


def _write_markdown(path: Path, summary: dict[str, Any], units) -> None:
    top = units.head(10)
    lines = [
        "# 规划实施智能监测评估模型：重庆样例现状演练",
        "",
        f"- 模型：`{summary['model_id']}@{summary['model_version']}`",
        f"- 运行：`{summary['run_id']}`；状态：`{summary['status']}`",
        f"- 样例范围：{summary['sample_scope']}；生产发布：`{summary['production_eligible']}`",
        f"- 空间单元：{summary['unit_count']} 个规则网格，边长 "
        f"{summary['cell_size_m']} m，投影 `{summary['analysis_crs']}`",
        "",
        "## 已计算指标",
        "",
        "建筑数量、建筑占地面积、建筑覆盖率、建筑平均层数、估算建筑面积、估算容积率、"
        "设施点数量与密度、道路长度与路网密度、土地覆盖不透水面/水体占比、平均海拔和平均坡度"
        "均按指标合同计算。",
        "",
        "## 相对诊断",
        "",
        "诊断只使用重庆样例内部 P25/P75 分位数，表示同一批样例单元的相对差异，"
        "不表示规划合规、审批结论或政策阈值。",
        "",
        f"诊断计数：{json.dumps(summary['diagnostic_counts'], ensure_ascii=False)}。",
        "",
        "## 最高强度单元（前10）",
        "",
        "| 单元 | 建筑数 | 估算容积率 | 设施密度(个/km2) | 路网密度(km/km2) | 诊断 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in top.itertuples(index=False):
        lines.append(
            f"| {row.unit_id} | {int(row.building_count)} | {_fmt(row.estimated_far)} | "
            f"{_fmt(row.poi_density_km2)} | {_fmt(row.road_density_km_km2)} | "
            f"{', '.join(row.diagnostic_codes) or '无'} |"
        )
    lines.extend(
        [
            "",
            "## 不能由本次演练证明的内容",
            "",
            "1. 不能证明宁夏数据的完整性、现势性或规划目标达成率。",
            "2. 不能替代永久基本农田、生态保护红线、城镇开发边界等法定约束的合规审查。",
            "3. 不能生成有法律效力的规划实施评估结论；正式运行需要年度序列、目标值、"
            "指标字典、空间矛盾规则和建议政策库。",
            "4. 原始记录仍在数据湖/治理表中，本模型只保存输入引用、指标结果和血缘，"
            "不将全部记录复制进本体库。",
            "",
            "完整机器报告位于输出目录的 `monitoring_evaluation_report.json`。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.3f}"
