#!/usr/bin/env python3
"""Run a citywide Abu Dhabi 2D prototype with public Copernicus DEM.

This runner is independent from customer DTM and customer network. It creates
a coarse, full-public-domain ANUGA surface run for customer demonstrations.
Outputs are written to a local private directory and are not model admission
evidence.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.windows import from_bounds

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEM = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif"
DEFAULT_LAND_COVER = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"
DEFAULT_OUTPUT = Path(os.environ.get(
    "ABU_DHABI_PUBLIC_CITYWIDE_2D_ROOT",
    Path.home() / "Downloads/abu_dhabi_public_citywide_2d",
))
ANUGA_PYTHON = REPOSITORY_ROOT / "external_models/anuga-venv/bin/python"
# Bounds are snapped to the 250 m model grid. They remain inside the existing
# public Copernicus crop while avoiding a partial cell at either edge.
CITY_BOUNDS = (225750.0, 2687250.0, 273250.0, 2723250.0)
CELL_SIZE_M = 250.0
RAIN_DURATION_MINUTES = 180
TAIL_MINUTES = 120
REPORT_INTERVAL_SECONDS = 1800.0
MANNING = 0.035
WATER_MANNING = 0.020
SEA_LEVEL_M = 0.0
PERMANENT_WATER_CLASS = 80
# At the 250 m public prototype resolution a shoreline often occupies one
# mixed cell.  Keep only cells with <20% permanent-water coverage so the map
# communicates inland flooding rather than coarse coastal mixing artefacts.
WATER_CELL_FRACTION_THRESHOLD = 0.20
WORLD_COVER_SOURCE_URL = "https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200"

def _json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")

def _rainfall_100y_180min() -> tuple[list[float], dict[str, object]]:
    durations = [5, 10, 15, 30, 60, 120, 180]
    depths = [26.99, 31.70, 34.64, 40.44, 47.21, 55.12, 60.33]
    cumulative = []
    for duration in range(5, 181, 5):
        if duration in durations:
            cumulative.append(depths[durations.index(duration)])
            continue
        upper = next(i for i, value in enumerate(durations) if value > duration)
        lower = upper - 1
        ratio = (math.log(duration) - math.log(durations[lower])) / (math.log(durations[upper]) - math.log(durations[lower]))
        cumulative.append(math.exp(math.log(depths[lower]) + ratio * (math.log(depths[upper]) - math.log(depths[lower]))))
    increments = [cumulative[0], *[b - a for a, b in zip(cumulative, cumulative[1:])]]
    peak_index = round(35 * 0.40)
    positions = [peak_index]
    distance = 1
    while len(positions) < len(increments):
        right, left = peak_index + distance, peak_index - distance
        if right < len(increments):
            positions.append(right)
        if left >= 0 and len(positions) < len(increments):
            positions.append(left)
        distance += 1
    ordered = [0.0] * len(increments)
    for value, position in zip(sorted(increments, reverse=True), positions, strict=True):
        ordered[position] = max(0.0, value)
    intensities = [value * 12.0 for value in ordered]
    return intensities, {
        "source": "abu_dhabi_2022_official_zone_b_ddf_table_3_6",
        "source_authority": "official_publication_user_supplied_extract",
        "return_period_years": 100,
        "duration_minutes": 180,
        "published_total_depth_mm": 60.33,
        "generated_total_depth_mm": float(sum(value / 12.0 for value in intensities)),
        "native_interval_minutes": 5,
        "peak_position_percent": 40,
        "temporal_distribution_method": "alternating_block_from_nested_ddf_increments",
        "claim_boundary": "public prototype forcing; not a customer event observation or calibrated forecast",
    }

def _prepare_terrain(
    dem_path: Path,
    land_cover_path: Path,
    work: Path,
    bounds: tuple[float, float, float, float],
) -> dict[str, object]:
    with rasterio.open(dem_path) as source:
        if source.crs is None or source.crs.to_epsg() != 32640 or source.count != 1:
            raise ValueError("public_citywide_dem_must_be_single_band_epsg32640")
        nx = int(round((bounds[2] - bounds[0]) / CELL_SIZE_M))
        ny = int(round((bounds[3] - bounds[1]) / CELL_SIZE_M))
        window = from_bounds(*bounds, transform=source.transform).round_offsets().round_lengths()
        arr = source.read(1, window=window, out_shape=(ny + 1, nx + 1), resampling=Resampling.bilinear, masked=True)
        if np.ma.getmaskarray(arr).any():
            raise ValueError("public_citywide_dem_contains_nodata")
        values = np.asarray(arr, dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError("public_citywide_dem_contains_nonfinite")
        source_resolution = [abs(float(source.transform.a)), abs(float(source.transform.e))]
    with rasterio.open(land_cover_path) as source:
        if source.crs is None or source.count != 1:
            raise ValueError("public_citywide_land_cover_must_be_single_band_with_crs")
        land_cover = source.read(1, masked=True)
        valid_source = np.asarray(~np.ma.getmaskarray(land_cover), dtype=np.float32)
        water_source = np.asarray(
            np.ma.filled(land_cover == PERMANENT_WATER_CLASS, False),
            dtype=np.float32,
        )
        water_fraction = np.zeros((ny, nx), dtype=np.float32)
        coverage_fraction = np.zeros((ny, nx), dtype=np.float32)
        reproject(
            source=water_source,
            destination=water_fraction,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=from_origin(bounds[0], bounds[3], CELL_SIZE_M, CELL_SIZE_M),
            dst_crs="EPSG:32640",
            resampling=Resampling.average,
            init_dest_nodata=False,
        )
        # WorldCover does not cover every metre of the public DEM crop.  If
        # those cells are left at the reprojector's zero default they look
        # like non-water (land) and create artificial rectangular stripes at
        # the domain edge.  Carry an explicit source-coverage raster and
        # exclude cells that are not fully covered by the land/water product.
        reproject(
            source=valid_source,
            destination=coverage_fraction,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=from_origin(bounds[0], bounds[3], CELL_SIZE_M, CELL_SIZE_M),
            dst_crs="EPSG:32640",
            resampling=Resampling.average,
            init_dest_nodata=False,
        )
        land_cover_crs = str(source.crs)
        land_cover_resolution = [abs(float(source.transform.a)), abs(float(source.transform.e))]
    water_fraction = np.clip(water_fraction, 0.0, 1.0)
    coverage_fraction = np.clip(coverage_fraction, 0.0, 1.0)
    source_coverage_threshold = 0.999
    source_covered = coverage_fraction >= source_coverage_threshold
    land_mask = (water_fraction < WATER_CELL_FRACTION_THRESHOLD) & source_covered
    if not land_mask.any() or land_mask.all():
        raise ValueError("public_citywide_land_water_mask_invalid")

    x = np.linspace(bounds[0], bounds[2], nx + 1)
    y = np.linspace(bounds[3], bounds[1], ny + 1)
    np.savez_compressed(
        work / "terrain_grid.npz",
        values=values.astype(np.float32),
        x=x,
        y=y,
        water_fraction=water_fraction,
        coverage_fraction=coverage_fraction,
        land_mask=land_mask,
    )
    return {
        "path": "terrain_grid.npz", "crs": "EPSG:32640", "bounds_epsg32640": list(bounds),
        "grid_shape": list(values.shape), "cell_size_m": CELL_SIZE_M,
        "minimum_m": float(values.min()), "maximum_m": float(values.max()), "mean_m": float(values.mean()),
        "source_resolution_m": source_resolution,
        "land_water_mask": {
            "product": "ESA WorldCover 2021 v200",
            "source_url": WORLD_COVER_SOURCE_URL,
            "source_path": str(land_cover_path),
            "source_crs": land_cover_crs,
            "source_resolution_degrees": land_cover_resolution,
            "permanent_water_class": PERMANENT_WATER_CLASS,
            "water_cell_fraction_threshold": WATER_CELL_FRACTION_THRESHOLD,
            "source_coverage_threshold": source_coverage_threshold,
            "source_covered_cells": int(source_covered.sum()),
            "source_uncovered_cells_excluded": int((~source_covered).sum()),
            "active_land_cells": int(land_mask.sum()),
            "excluded_permanent_water_cells": int((~land_mask).sum()),
            "active_land_area_m2": float(land_mask.sum() * CELL_SIZE_M * CELL_SIZE_M),
            "excluded_permanent_water_area_m2": float((~land_mask).sum() * CELL_SIZE_M * CELL_SIZE_M),
            "claim_boundary": "public land-cover proxy; replace with customer authoritative shoreline and permanent-water polygons",
        },
    }

def _write_model_script(path: Path, terrain: dict[str, object], rainfall: list[float], bounds: tuple[float, float, float, float]) -> None:
    nx = int(round((bounds[2] - bounds[0]) / CELL_SIZE_M))
    ny = int(round((bounds[3] - bounds[1]) / CELL_SIZE_M))
    final_time = (RAIN_DURATION_MINUTES + TAIL_MINUTES) * 60.0
    script = f'''"""Generated full-city Abu Dhabi public DEM ANUGA prototype."""
import numpy as np
import anuga

GRID = np.load("terrain_grid.npz")
VALUES = np.asarray(GRID["values"], dtype=float)
X = np.asarray(GRID["x"], dtype=float)
Y = np.asarray(GRID["y"], dtype=float)
LAND = np.asarray(GRID["land_mask"], dtype=bool)
RAINFALL_MM_PER_H = {tuple(float(v) for v in rainfall)!r}
DX = {CELL_SIZE_M!r}

def topography(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    col = np.clip(np.floor((x - X[0]) / DX).astype(int), 0, VALUES.shape[1] - 2)
    row = np.clip(np.floor((Y[0] - y) / DX).astype(int), 0, VALUES.shape[0] - 2)
    x_weight = np.clip((x - X[col]) / DX, 0.0, 1.0)
    y_weight = np.clip((y - Y[row + 1]) / DX, 0.0, 1.0)
    nw, ne = VALUES[row, col], VALUES[row, col + 1]
    sw, se = VALUES[row + 1, col], VALUES[row + 1, col + 1]
    return nw * (1-x_weight) * y_weight + ne * x_weight * y_weight + sw * (1-x_weight) * (1-y_weight) + se * x_weight * (1-y_weight)

def is_land(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    col = np.clip(np.floor((x - X[0]) / DX).astype(int), 0, LAND.shape[1] - 1)
    row = np.clip(np.floor((Y[0] - y) / DX).astype(int), 0, LAND.shape[0] - 1)
    return LAND[row, col]

def rainfall_rate(x, y, t):
    index = int(t // 300.0)
    intensity = RAINFALL_MM_PER_H[index] * 0.001 / 3600.0 if 0 <= index < len(RAINFALL_MM_PER_H) else 0.0
    return np.where(is_land(x, y), intensity, 0.0)

def initial_stage(x, y):
    elevation = topography(x, y)
    return np.where(is_land(x, y), elevation, np.maximum(elevation, {SEA_LEVEL_M!r}))

def surface_friction(x, y):
    return np.where(is_land(x, y), {MANNING!r}, {WATER_MANNING!r})

domain = anuga.rectangular_cross_domain({nx}, {ny}, len1={bounds[2]-bounds[0]!r}, len2={bounds[3]-bounds[1]!r}, origin=({bounds[0]!r}, {bounds[1]!r}))
domain.set_name("abu_dhabi_public_citywide_2d")
domain.set_quantity("elevation", topography)
domain.set_quantity("friction", surface_friction)
domain.set_quantity("stage", initial_stage)
boundary = anuga.Dirichlet_boundary([{SEA_LEVEL_M!r}, 0.0, 0.0])
domain.set_boundary({{"left": boundary, "right": boundary, "top": boundary, "bottom": boundary}})
rainfall_operator = anuga.Rate_operator(domain, rate=rainfall_rate, label="public_zone_b_100y_land_only_rainfall")
for _ in domain.evolve(yieldstep={REPORT_INTERVAL_SECONDS!r}, finaltime={final_time!r}):
    pass
'''
    path.write_text(script, encoding="utf-8")

def _extract_outputs(sww_path: Path, output: Path, bounds: tuple[float, float, float, float], terrain: dict[str, object], rainfall: dict[str, object], terrain_grid_path: Path) -> dict[str, object]:
    from scipy.io import netcdf_file
    with netcdf_file(sww_path, "r", mmap=False) as dataset:
        x = np.asarray(dataset.variables["x"].data, dtype=np.float64).copy()
        y = np.asarray(dataset.variables["y"].data, dtype=np.float64).copy()
        volumes = np.asarray(dataset.variables["volumes"].data, dtype=np.int64).copy()
        elevation = np.asarray(dataset.variables["elevation_c"].data, dtype=np.float64).copy()
        stage = np.asarray(dataset.variables["stage_c"].data, dtype=np.float64).copy()
        times = np.asarray(dataset.variables["time"].data, dtype=np.float64).copy()
    depths = np.maximum(stage - elevation[None, :], 0.0)
    nx = int(round((bounds[2] - bounds[0]) / CELL_SIZE_M))
    ny = int(round((bounds[3] - bounds[1]) / CELL_SIZE_M))
    with np.load(terrain_grid_path) as terrain_grid:
        land_mask = np.asarray(terrain_grid["land_mask"], dtype=bool)
        water_fraction = np.asarray(terrain_grid["water_fraction"], dtype=np.float64)
    if land_mask.shape != (ny, nx) or water_fraction.shape != (ny, nx):
        raise ValueError("public_citywide_land_water_mask_shape_invalid")
    centroids = np.column_stack((x[volumes].mean(axis=1), y[volumes].mean(axis=1)))
    columns = np.clip(np.floor((centroids[:, 0] - bounds[0]) / CELL_SIZE_M).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((bounds[3] - centroids[:, 1]) / CELL_SIZE_M).astype(int), 0, ny - 1)
    cell_ids = rows * nx + columns
    max_by_cell = np.zeros(nx * ny, dtype=np.float64)
    peak_time_by_cell = np.zeros(nx * ny, dtype=np.float64)
    final_by_cell = np.zeros(nx * ny, dtype=np.float64)
    for cell in np.unique(cell_ids):
        indices = np.where(cell_ids == cell)[0]
        local = depths[:, indices]
        max_by_cell[cell] = local.max(axis=1).max()
        peak_time_by_cell[cell] = times[int(np.argmax(local.max(axis=1)))]
        final_by_cell[cell] = local[-1].max()
    active_land_by_cell = land_mask.reshape(-1)
    water_fraction_by_cell = water_fraction.reshape(-1)
    max_by_cell[~active_land_by_cell] = 0.0
    peak_time_by_cell[~active_land_by_cell] = 0.0
    final_by_cell[~active_land_by_cell] = 0.0
    transformer = Transformer.from_crs(32640, 4326, always_xy=True)
    def polygon_for_cell(row: int, col: int) -> list[list[float]]:
        corners = [(bounds[0] + col * CELL_SIZE_M, bounds[3] - row * CELL_SIZE_M),
                   (bounds[0] + (col + 1) * CELL_SIZE_M, bounds[3] - row * CELL_SIZE_M),
                   (bounds[0] + (col + 1) * CELL_SIZE_M, bounds[3] - (row + 1) * CELL_SIZE_M),
                   (bounds[0] + col * CELL_SIZE_M, bounds[3] - (row + 1) * CELL_SIZE_M)]
        return [[float(lon), float(lat)] for lon, lat in (transformer.transform(px, py) for px, py in (*corners, corners[0]))]
    def make_features(values: np.ndarray, time_minutes: float | None = None) -> list[dict[str, object]]:
        features = []
        for cell, value in enumerate(values):
            if not active_land_by_cell[cell] or value < 0.01:
                continue
            row, col = divmod(cell, nx)
            props = {
                "cell_id": int(cell),
                "depth_m": float(value),
                "prototype_cell_size_m": CELL_SIZE_M,
                "land_fraction": float(1.0 - water_fraction_by_cell[cell]),
                "permanent_water_fraction": float(water_fraction_by_cell[cell]),
            }
            if time_minutes is None:
                props.update({"maximum_depth_m": float(value), "maximum_depth_time_minutes": float(peak_time_by_cell[cell] / 60.0), "final_depth_m": float(final_by_cell[cell])})
            else:
                props["time_minutes"] = float(time_minutes)
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [polygon_for_cell(row, col)]}, "properties": props})
        return features
    maximum = {"type": "FeatureCollection", "name": "abu_dhabi_public_copernicus_citywide_anuga_2d_maximum_depth", "features": make_features(max_by_cell)}
    _json_dump(output / "maximum_depth_wgs84.geojson", maximum)
    snapshot_dir = output / "temporal_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for time_index, timestamp in enumerate(times):
        values_by_cell = np.zeros(nx * ny, dtype=np.float64)
        for cell in np.unique(cell_ids):
            values_by_cell[cell] = depths[time_index, np.where(cell_ids == cell)[0]].max()
        name = f"surface_depth_t{time_index:03d}.geojson"
        _json_dump(snapshot_dir / name, {"type": "FeatureCollection", "name": f"abu_dhabi_public_citywide_2d_time_{time_index:03d}", "features": make_features(values_by_cell, float(timestamp / 60.0))})
        snapshots.append({"index": time_index, "time_seconds": float(timestamp), "time_minutes": float(timestamp / 60.0), "path": f"temporal_snapshots/{name}"})
    _json_dump(snapshot_dir / "manifest.json", {"schema": "gwm.abu_dhabi_flood.public_citywide_2d_timeseries.v1", "snapshots": snapshots})
    land_mask_metadata = terrain["land_water_mask"]
    active_land_count = int(active_land_by_cell.sum())
    active_land_area_m2 = float(active_land_count * CELL_SIZE_M * CELL_SIZE_M)
    maximum_depth_m = float(max_by_cell[active_land_by_cell].max())
    maximum_depth_cell = int(np.flatnonzero(active_land_by_cell)[np.argmax(max_by_cell[active_land_by_cell])])
    summary = {
        "schema": "gwm.abu_dhabi_flood.public_citywide_2d_delivery.v2",
        "status": "completed_public_copernicus_citywide_2d_prototype_not_calibrated",
        "solver": "ANUGA 2D",
        "surface": {"product": "Copernicus DEM GLO-30 public proxy", **terrain, "claim_boundary": "public proxy / prototype only"},
        "domain": {"bounds_epsg32640": list(bounds), "area_m2": float((bounds[2]-bounds[0]) * (bounds[3]-bounds[1])), "cell_size_m": CELL_SIZE_M, "rectangular_cells": nx * ny, "active_land_cells": active_land_count, "excluded_permanent_water_cells": int((~active_land_by_cell).sum()), "active_land_area_m2": active_land_area_m2, "triangle_count": int(len(volumes)), "simulation_duration_hours": float(times[-1] / 3600.0), "output_step_minutes": float(REPORT_INTERVAL_SECONDS / 60.0)},
        "forcing": rainfall,
        "land_water_treatment": {**land_mask_metadata, "rainfall_applied_to": "active_land_cells_only", "permanent_water_output_policy": "excluded_from_inland_flood_layers_and_statistics", "sea_boundary_level_m": SEA_LEVEL_M, "sea_boundary_condition": "fixed_stage_zero_momentum_at_outer_domain; connected permanent-water cells retained as drainage medium"},
        "results": {"maximum_depth_m": maximum_depth_m, "maximum_depth_time_minutes": float(peak_time_by_cell[maximum_depth_cell] / 60.0), "inundated_cells_ge_0_01m": int(np.sum((max_by_cell >= 0.01) & active_land_by_cell)), "inundated_area_ge_0_01m2": float(np.sum((max_by_cell >= 0.01) & active_land_by_cell) * CELL_SIZE_M * CELL_SIZE_M), "inundated_area_ge_0_05m2": float(np.sum((max_by_cell >= 0.05) & active_land_by_cell) * CELL_SIZE_M * CELL_SIZE_M), "final_surface_volume_m3": float(np.sum(final_by_cell[active_land_by_cell]) * CELL_SIZE_M * CELL_SIZE_M)},
        "outputs": {"maximum_depth": "maximum_depth_wgs84.geojson", "timeline_manifest": "temporal_snapshots/manifest.json", "native_sww": "abu_dhabi_public_citywide_2d.sww"},
        "admission": {"public_proxy_test_allowed": True, "customer_authoritative_engineering_prediction": False, "gwm_training_admitted": False, "citywide_prediction_claim_allowed": False},
        "replacement_contract": "Replace the DEM and public land/water proxy with customer authoritative DTM, shoreline, permanent-water polygons, vertical datum, and tide boundary; then rerun this same model/output contract.",
    }
    _json_dump(output / "delivery_summary.json", summary)
    return summary

def run(dem_path: Path, land_cover_path: Path, output: Path, *, cell_size_m: float = CELL_SIZE_M) -> dict[str, object]:
    if abs(cell_size_m - CELL_SIZE_M) > 1e-9:
        raise ValueError("this_initial_prototype_uses_fixed_250m_grid")
    if not dem_path.is_file():
        raise ValueError("public_citywide_dem_missing")
    if not land_cover_path.is_file():
        raise ValueError("public_citywide_land_cover_missing")
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abu-public-citywide-2d-"))
    try:
        terrain = _prepare_terrain(dem_path, land_cover_path, work, CITY_BOUNDS)
        rainfall, rainfall_meta = _rainfall_100y_180min()
        model_script = work / "abu_dhabi_public_citywide_2d.py"
        _write_model_script(model_script, terrain, rainfall, CITY_BOUNDS)
        process = subprocess.run([str(ANUGA_PYTHON), str(model_script)], cwd=work, capture_output=True, text=True, timeout=1800)
        (output / "anuga_stdout.log").write_text(process.stdout, encoding="utf-8")
        (output / "anuga_stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"anuga_public_citywide_failed:{process.returncode}")
        sww_candidates = sorted(work.glob("*.sww"))
        if not sww_candidates:
            raise RuntimeError("anuga_public_citywide_sww_missing")
        shutil.copy2(sww_candidates[0], output / "abu_dhabi_public_citywide_2d.sww")
        summary = _extract_outputs(output / "abu_dhabi_public_citywide_2d.sww", output, CITY_BOUNDS, terrain, rainfall_meta, work / "terrain_grid.npz")
        _json_dump(output / "run_receipt.json", {"schema": "gwm.abu_dhabi_flood.public_citywide_2d_run_receipt.v2", "status": "completed", "dem_source": str(dem_path), "dem_source_url": "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30", "land_cover_source": str(land_cover_path), "land_cover_source_url": WORLD_COVER_SOURCE_URL, "output_directory": str(output), "summary": summary, "anuga_returncode": process.returncode, "claim_boundary": "public Copernicus DEM and ESA WorldCover land/water-mask prototype only; not calibrated or engineering-admitted"})
        return summary
    finally:
        shutil.rmtree(work, ignore_errors=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    parser.add_argument("--land-cover", type=Path, default=DEFAULT_LAND_COVER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.dem.expanduser().resolve(), args.land_cover.expanduser().resolve(), args.output.expanduser().resolve())
    print(json.dumps({"output": str(args.output), "status": result["status"], "results": result["results"]}, ensure_ascii=True))

if __name__ == "__main__":
    main()
