#!/usr/bin/env python3
"""Run a customer-DTM, SWMM-coupled ANUGA model for Al Bateen.

This runner is intentionally independent from the 250 m citywide GWM.  It
uses the customer 5 m DTM as the terrain source, builds a local 10/20 m ANUGA
grid, and optionally injects node flooding from the matching native SWMM run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import binary_propagation
from shapely.geometry import shape


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = (
    REPOSITORY_ROOT
    / "data_agent/assets/abu_dhabi/al_bateen_boundary_utm40.json"
)
DEFAULT_DTM = Path.home() / "Downloads/阿布扎比/DTM_z40_customer/AUH_DTM_5m_Z40.TIF"
DEFAULT_LAND_COVER = (
    Path.home()
    / "gisdataagent/benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"
)
DEFAULT_OUTPUT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/al_bateen_high_resolution_runs/manual"
)
ANUGA_PYTHON = Path(
    os.environ.get(
        "ABU_DHABI_ANUGA_PYTHON",
        str(Path.home() / "gisdataagent/external_models/anuga-venv/bin/python"),
    )
)
PERMANENT_WATER_CLASS = 80
MODEL_BUFFER_M = 500.0
MINIMUM_MAPPED_DEPTH_M = 0.01
RAINFALL_DURATION_MINUTES = 180
DEFAULT_DRAINAGE_TIMESCALE_MINUTES = 120.0
DEFAULT_MINIMUM_DRAINAGE_MM_PER_HOUR = 2.0
DEFAULT_DRY_MEAN_DEPTH_THRESHOLD_M = 0.001
DEFAULT_DRY_CONSECUTIVE_FRAMES = 3
DEFAULT_TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M = 0.15


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_citywide_helpers():
    path = REPOSITORY_ROOT / "scripts/run_abu_dhabi_public_citywide_2d.py"
    spec = importlib.util.spec_from_file_location("abu_dhabi_citywide_2d_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("citywide_2d_helpers_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_boundary(path: Path) -> tuple[dict[str, Any], tuple[float, float, float, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or len(features) != 1:
        raise ValueError("al_bateen_boundary_feature_required")
    feature = features[0]
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("al_bateen_boundary_geometry_invalid")

    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, list):
            for child in value:
                visit(child)

    visit(coordinates)
    if not points:
        raise ValueError("al_bateen_boundary_coordinates_missing")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return feature, (min(xs), min(ys), max(xs), max(ys))


def _snap_bounds(
    bounds: tuple[float, float, float, float], cell_size_m: float
) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = bounds
    return (
        math.floor((xmin - MODEL_BUFFER_M) / cell_size_m) * cell_size_m,
        math.floor((ymin - MODEL_BUFFER_M) / cell_size_m) * cell_size_m,
        math.ceil((xmax + MODEL_BUFFER_M) / cell_size_m) * cell_size_m,
        math.ceil((ymax + MODEL_BUFFER_M) / cell_size_m) * cell_size_m,
    )


def _prepare_terrain(
    dtm_path: Path,
    land_cover_path: Path,
    boundary_feature: dict[str, Any],
    bounds: tuple[float, float, float, float],
    cell_size_m: float,
    tide_level_m: float,
    tidal_connectivity_vertical_tolerance_m: float,
    work: Path,
) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = bounds
    width = int(round((xmax - xmin) / cell_size_m))
    height = int(round((ymax - ymin) / cell_size_m))
    if width <= 0 or height <= 0:
        raise ValueError("al_bateen_grid_extent_invalid")
    transform = from_origin(xmin, ymax, cell_size_m, cell_size_m)

    elevation = np.full((height, width), np.nan, dtype=np.float32)
    with rasterio.open(dtm_path) as source:
        source_crs = source.crs or "EPSG:32640"
        reproject(
            source=rasterio.band(source, 1),
            destination=elevation,
            src_transform=source.transform,
            src_crs=source_crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs="EPSG:32640",
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )
    finite = np.isfinite(elevation)
    if not finite.any():
        raise ValueError("al_bateen_dtm_crop_empty")
    fill_value = float(np.nanmedian(elevation[finite]))
    elevation[~finite] = fill_value

    land_cover = np.zeros((height, width), dtype=np.uint8)
    with rasterio.open(land_cover_path) as source:
        reproject(
            source=rasterio.band(source, 1),
            destination=land_cover,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs="EPSG:32640",
            dst_nodata=0,
            resampling=Resampling.nearest,
        )

    district_mask = rasterize(
        [(boundary_feature["geometry"], 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    mapped_permanent_water = land_cover == PERMANENT_WATER_CLASS
    # The customer DTM contains a small number of strongly negative shoreline
    # cells that are connected to mapped water but classified as land by the
    # coarser land-cover raster.  At an open tidal boundary these cells can
    # never become dry, regardless of post-storm drainage.  Reclassify only
    # cells that are both within a small vertical-datum tolerance of the
    # scenario tide level and 8-neighbour connected to mapped permanent water.
    # This preserves isolated inland depressions as land while making the
    # dry-state gate relative to the physically meaningful dry-weather tidal
    # baseline.  The tolerance is explicit metadata, not a DTM modification.
    tidal_connectivity_threshold_m = (
        float(tide_level_m) + float(tidal_connectivity_vertical_tolerance_m)
    )
    tidal_connectivity_mask = mapped_permanent_water | (
        finite & (elevation <= tidal_connectivity_threshold_m)
    )
    tidal_baseline_water = np.asarray(
        binary_propagation(
            mapped_permanent_water,
            structure=np.ones((3, 3), dtype=bool),
            mask=tidal_connectivity_mask,
        ),
        dtype=bool,
    )
    tidal_reclassified_water = tidal_baseline_water & ~mapped_permanent_water
    # Keep the original mapped-water mask for the hydrodynamic domain.  Turning
    # the negative shoreline cells into several metres of dynamic water makes
    # the CFL timestep unnecessarily small.  The separate event-land mask is
    # used for rainfall, delivery products and the complete-dewatering gate.
    domain_land = finite & ~mapped_permanent_water
    district_raw_land = district_mask & domain_land
    district_land = district_raw_land & ~tidal_reclassified_water
    if not district_land.any():
        raise ValueError("al_bateen_land_mask_empty")

    district_geometry = shape(boundary_feature["geometry"])
    domain_geometry = district_geometry.buffer(MODEL_BUFFER_M, join_style="mitre")
    if domain_geometry.geom_type == "MultiPolygon":
        domain_geometry = max(domain_geometry.geoms, key=lambda geometry: geometry.area)
    domain_polygon = np.asarray(domain_geometry.exterior.coords[:-1], dtype=np.float64)
    if len(domain_polygon) < 3:
        raise ValueError("al_bateen_domain_polygon_invalid")

    x = xmin + (np.arange(width, dtype=np.float64) + 0.5) * cell_size_m
    y = ymax - (np.arange(height, dtype=np.float64) + 0.5) * cell_size_m
    np.savez_compressed(
        work / "terrain_grid.npz",
        values=elevation,
        x=x,
        y=y,
        land_mask=domain_land,
        district_mask=district_mask,
        district_raw_land_mask=district_raw_land,
        district_land_mask=district_land,
        permanent_water_mask=mapped_permanent_water,
        mapped_permanent_water_mask=mapped_permanent_water,
        tidal_baseline_water_mask=tidal_baseline_water,
        tidal_reclassified_water_mask=tidal_reclassified_water,
        water_fraction=mapped_permanent_water.astype(np.float32),
        transform=np.asarray(transform, dtype=np.float64),
        bounds=np.asarray(bounds, dtype=np.float64),
        cell_size_m=np.asarray(cell_size_m, dtype=np.float64),
        domain_polygon=domain_polygon,
    )
    return {
        "source_product": "customer AUH_DTM_5m_Z40.TIF",
        "source_resolution_m": 5.0,
        "computation_cell_size_m": cell_size_m,
        "grid_width": width,
        "grid_height": height,
        "rectangular_cells": width * height,
        "district_cells": int(district_mask.sum()),
        "district_land_cells": int(district_land.sum()),
        "district_land_area_m2": float(district_land.sum() * cell_size_m * cell_size_m),
        "district_raw_land_cells": int(district_raw_land.sum()),
        "mapped_permanent_water_cells": int(mapped_permanent_water.sum()),
        "tidal_reclassified_water_cells": int(tidal_reclassified_water.sum()),
        "tidal_reclassified_district_cells": int(
            (tidal_reclassified_water & district_mask).sum()
        ),
        "tidal_connectivity_vertical_tolerance_m": float(
            tidal_connectivity_vertical_tolerance_m
        ),
        "tidal_water_connectivity_threshold_m": tidal_connectivity_threshold_m,
        "tidal_water_classification": (
            "mapped permanent water plus cells at or below tide plus the "
            "declared vertical-datum tolerance that are 8-neighbour connected "
            "to mapped permanent water"
        ),
        "elevation_min_m": float(elevation[district_mask].min()),
        "elevation_max_m": float(elevation[district_mask].max()),
        "elevation_mean_m": float(elevation[district_mask].mean()),
        "bounds_epsg32640": list(bounds),
    }


def _rainfall(return_period_years: int, tail_minutes: int) -> tuple[list[float], dict[str, Any]]:
    from data_agent.abu_dhabi_zone_b_design_storm import zone_b_180_minute_hyetograph

    series, metadata = zone_b_180_minute_hyetograph(
        return_period_years,
        start=datetime(2022, 1, 1),
        peak_position_percent=40.0,
        tail_minutes=tail_minutes,
    )
    values = [float(intensity) for _, intensity in series[:36]]
    return values, metadata


def _write_model_script(
    path: Path,
    *,
    bounds: tuple[float, float, float, float],
    cell_size_m: float,
    rainfall_mm_per_h: list[float],
    tail_minutes: int,
    output_step_minutes: int,
    tide_level_m: float,
    manning_n: float,
    exchange_enabled: bool,
    dewater_until_dry: bool,
    drainage_timescale_minutes: float,
    minimum_drainage_mm_per_hour: float,
    dry_mean_depth_threshold_m: float,
    dry_consecutive_frames: int,
) -> None:
    nx = int(round((bounds[2] - bounds[0]) / cell_size_m))
    ny = int(round((bounds[3] - bounds[1]) / cell_size_m))
    final_time = float((RAINFALL_DURATION_MINUTES + tail_minutes) * 60)
    exchange_load = """
EXCHANGE = np.load("swmm_exchange.npz")
SWMM_RATES = np.asarray(EXCHANGE["swmm_to_anuga_cell_rates_mps"], dtype=float)
SURFACE_RAINFALL_FRACTION = np.asarray(EXCHANGE["surface_rainfall_fraction_by_cell"], dtype=float)
EXCHANGE_TIMES = np.asarray(EXCHANGE["times_seconds"], dtype=float)
EXCHANGE_STEP_SECONDS = float(np.asarray(EXCHANGE["report_step_seconds"]).reshape(()))
""" if exchange_enabled else "SURFACE_RAINFALL_FRACTION = np.ones(LAND.size, dtype=float)\n"
    exchange_operator = """
def swmm_source_rate(x, y, t):
    active = t >= EXCHANGE_TIMES[0] and t < EXCHANGE_TIMES[-1] + EXCHANGE_STEP_SECONDS
    index = int(np.searchsorted(EXCHANGE_TIMES, t, side="right") - 1) if active else -1
    if index < 0:
        return np.zeros_like(np.asarray(x, dtype=float))
    rate = SWMM_RATES[int(np.clip(index, 0, SWMM_RATES.shape[0] - 1))][cell_ids(x, y)]
    return np.where(is_domain_land(x, y), rate, 0.0)

swmm_operator = anuga.Rate_operator(domain, rate=swmm_source_rate, label="swmm_node_flooding")
""" if exchange_enabled else ""
    exchange_receipt = """
runtime["actual_swmm_to_surface_volume_m3"] = float(swmm_operator.cumulative_influx)
""" if exchange_enabled else "runtime[\"actual_swmm_to_surface_volume_m3\"] = 0.0\n"

    script = f'''"""Generated Al Bateen high-resolution ANUGA model."""
import json
import math
import numpy as np
import anuga
from anuga.operators.base_operator import Operator

GRID = np.load("terrain_grid.npz")
VALUES = np.asarray(GRID["values"], dtype=float)
X = np.asarray(GRID["x"], dtype=float)
Y = np.asarray(GRID["y"], dtype=float)
LAND = np.asarray(GRID["land_mask"], dtype=bool)
DISTRICT_LAND = np.asarray(GRID["district_land_mask"], dtype=bool)
DOMAIN_POLYGON = np.asarray(GRID["domain_polygon"], dtype=float)
RAINFALL_MM_PER_H = {tuple(rainfall_mm_per_h)!r}
DX = {cell_size_m!r}
ORIGIN_X = float(DOMAIN_POLYGON[:, 0].min())
ORIGIN_Y = float(DOMAIN_POLYGON[:, 1].min())
RAINFALL_END_SECONDS = {float(RAINFALL_DURATION_MINUTES * 60)!r}
DEWATER_UNTIL_DRY = {bool(dewater_until_dry)!r}
DRAINAGE_TIMESCALE_SECONDS = {float(drainage_timescale_minutes * 60)!r}
MINIMUM_DRAINAGE_RATE_MPS = {float(minimum_drainage_mm_per_hour * 0.001 / 3600.0)!r}
DRY_DEPTH_THRESHOLD_M = {float(MINIMUM_MAPPED_DEPTH_M)!r}
DRY_MEAN_DEPTH_THRESHOLD_M = {float(dry_mean_depth_threshold_m)!r}
DRY_CONSECUTIVE_FRAMES = {int(dry_consecutive_frames)!r}
{exchange_load}

def grid_indices(x, y):
    x = np.asarray(x, dtype=float) + ORIGIN_X
    y = np.asarray(y, dtype=float) + ORIGIN_Y
    col = np.clip(np.floor((x - {bounds[0]!r}) / DX).astype(int), 0, LAND.shape[1] - 1)
    row = np.clip(np.floor(({bounds[3]!r} - y) / DX).astype(int), 0, LAND.shape[0] - 1)
    return row, col

def cell_ids(x, y):
    row, col = grid_indices(x, y)
    return row * LAND.shape[1] + col

def topography(x, y):
    row, col = grid_indices(x, y)
    return VALUES[row, col]

def is_domain_land(x, y):
    row, col = grid_indices(x, y)
    return LAND[row, col]

def is_district_land(x, y):
    row, col = grid_indices(x, y)
    return DISTRICT_LAND[row, col]

def rainfall_rate(x, y, t):
    index = int(t // 300.0)
    intensity = RAINFALL_MM_PER_H[index] * 0.001 / 3600.0 if 0 <= index < len(RAINFALL_MM_PER_H) else 0.0
    fraction = SURFACE_RAINFALL_FRACTION[cell_ids(x, y)]
    return np.where(is_district_land(x, y), intensity * fraction, 0.0)

def initial_stage(x, y):
    elevation = topography(x, y)
    return np.where(is_domain_land(x, y), elevation, np.maximum(elevation, {tide_level_m!r}))

def friction(x, y):
    return np.where(is_domain_land(x, y), {manning_n!r}, 0.02)

class SurfaceDrainageOperator(Operator):
    """Auditable lumped surface-to-network/infiltration recession operator."""

    def __init__(self, domain):
        super().__init__(domain, label="post_storm_surface_drainage")
        coordinates = domain.centroid_coordinates
        # Apply the recession abstraction to all local land triangles.  The
        # domain includes a buffer around Al Bateen so that boundary inflow is
        # represented; leaving that buffer undrained lets it continuously feed
        # water back into the district and prevents a valid dry-state stop.
        self.active = np.asarray(is_domain_land(coordinates[:, 0], coordinates[:, 1]), dtype=bool)
        self.stage = domain.quantities["stage"].centroid_values
        self.elevation = domain.quantities["elevation"].centroid_values
        self.xmomentum = domain.quantities["xmomentum"].centroid_values
        self.ymomentum = domain.quantities["ymomentum"].centroid_values
        self.areas = np.asarray(domain.areas, dtype=float)
        self.cumulative_outflow_m3 = 0.0

    def __call__(self):
        if not DEWATER_UNTIL_DRY or self.domain.get_time() < RAINFALL_END_SECONDS:
            return
        timestep = float(self.domain.get_timestep())
        if timestep <= 0.0:
            return
        depth = np.maximum(self.stage - self.elevation, 0.0)
        selected = self.active & (depth > 0.0)
        if not np.any(selected):
            return
        fraction = 1.0 - math.exp(-timestep / DRAINAGE_TIMESCALE_SECONDS)
        requested = depth[selected] * fraction + MINIMUM_DRAINAGE_RATE_MPS * timestep
        removed = np.minimum(depth[selected], requested)
        remaining_fraction = np.maximum(0.0, (depth[selected] - removed) / np.maximum(depth[selected], 1.0e-10))
        self.stage[selected] -= removed
        self.xmomentum[selected] *= remaining_fraction
        self.ymomentum[selected] *= remaining_fraction
        self.cumulative_outflow_m3 += float(np.sum(removed * self.areas[selected]))

domain = anuga.create_domain_from_regions(
    DOMAIN_POLYGON.tolist(),
    {{"outer": list(range(len(DOMAIN_POLYGON)))}},
    maximum_triangle_area={float(cell_size_m * cell_size_m / 2.0)!r},
    minimum_triangle_angle=28.0,
    use_cache=False,
    verbose=False,
)
domain.set_name("al_bateen_high_resolution_2d")
domain.set_quantity("elevation", topography)
domain.set_quantity("friction", friction)
domain.set_quantity("stage", initial_stage)
boundary = anuga.Dirichlet_boundary([{tide_level_m!r}, 0.0, 0.0])
domain.set_boundary({{"outer": boundary}})
rainfall_operator = anuga.Rate_operator(domain, rate=rainfall_rate, label="zone_b_design_rainfall")
{exchange_operator}
drainage_operator = SurfaceDrainageOperator(domain)
coordinates = domain.centroid_coordinates
district_triangles = np.asarray(
    is_district_land(coordinates[:, 0], coordinates[:, 1]),
    dtype=bool,
)
district_area_m2 = float(np.sum(domain.areas[district_triangles]))
dry_frame_count = 0
stop_reason = "maximum_tail_reached"
last_wet_triangle_count = 0
last_mean_depth_m = 0.0
for _ in domain.evolve(yieldstep={float(output_step_minutes * 60)!r}, finaltime={final_time!r}):
    if domain.get_time() < RAINFALL_END_SECONDS:
        continue
    depth = np.maximum(
        domain.quantities["stage"].centroid_values - domain.quantities["elevation"].centroid_values,
        0.0,
    )
    district_depth = depth[district_triangles]
    last_wet_triangle_count = int(np.count_nonzero(district_depth >= DRY_DEPTH_THRESHOLD_M))
    last_mean_depth_m = float(
        np.sum(district_depth * domain.areas[district_triangles]) / max(district_area_m2, 1.0)
    )
    if DEWATER_UNTIL_DRY and last_wet_triangle_count == 0 and last_mean_depth_m <= DRY_MEAN_DEPTH_THRESHOLD_M:
        dry_frame_count += 1
    else:
        dry_frame_count = 0
    if DEWATER_UNTIL_DRY and dry_frame_count >= DRY_CONSECUTIVE_FRAMES:
        stop_reason = "operational_complete_dewatering_reached"
        break
runtime = {{
    "rainfall_volume_m3": float(rainfall_operator.cumulative_influx),
    "surface_drainage_outflow_m3": float(drainage_operator.cumulative_outflow_m3),
    "dewatering_enabled": bool(DEWATER_UNTIL_DRY),
    "dewatering_stop_reason": stop_reason,
    "dewatering_dry_consecutive_frames": int(dry_frame_count),
    "dewatering_final_wet_triangle_count_ge_0_01m": int(last_wet_triangle_count),
    "dewatering_final_mean_depth_m": float(last_mean_depth_m),
    "drainage_timescale_minutes": float(DRAINAGE_TIMESCALE_SECONDS / 60.0),
    "minimum_drainage_mm_per_hour": float(MINIMUM_DRAINAGE_RATE_MPS * 3600.0 * 1000.0),
    "dry_depth_threshold_m": float(DRY_DEPTH_THRESHOLD_M),
    "dry_mean_depth_threshold_m": float(DRY_MEAN_DEPTH_THRESHOLD_M),
    "dry_consecutive_frames_required": int(DRY_CONSECUTIVE_FRAMES),
    "maximum_tail_minutes": {float(tail_minutes)!r},
    "actual_simulation_end_seconds": float(domain.get_time()),
}}
{exchange_receipt}
with open("coupling_runtime.json", "w", encoding="utf-8") as handle:
    json.dump(runtime, handle, sort_keys=True)
'''
    path.write_text(script, encoding="utf-8")


def _extract_outputs(
    sww_path: Path,
    output: Path,
    terrain_grid_path: Path,
    *,
    run_id: str,
    terrain: dict[str, Any],
    forcing: dict[str, Any],
    coupling: dict[str, Any] | None,
) -> dict[str, Any]:
    from scipy.io import netcdf_file

    with np.load(terrain_grid_path) as grid:
        bounds = tuple(float(value) for value in grid["bounds"])
        cell_size_m = float(np.asarray(grid["cell_size_m"]).reshape(()))
        district_land = np.asarray(grid["district_land_mask"], dtype=bool)
    ny, nx = district_land.shape

    with netcdf_file(sww_path, "r", mmap=False) as dataset:
        x = np.asarray(dataset.variables["x"].data, dtype=np.float64).copy()
        y = np.asarray(dataset.variables["y"].data, dtype=np.float64).copy()
        volumes = np.asarray(dataset.variables["volumes"].data, dtype=np.int64).copy()
        elevation = np.asarray(dataset.variables["elevation_c"].data, dtype=np.float64).copy()
        stage = np.asarray(dataset.variables["stage_c"].data, dtype=np.float64).copy()
        times = np.asarray(dataset.variables["time"].data, dtype=np.float64).copy()
        x += float(getattr(dataset, "xllcorner", 0.0))
        y += float(getattr(dataset, "yllcorner", 0.0))
        xmomentum = (
            np.asarray(dataset.variables["xmomentum_c"].data, dtype=np.float64).copy()
            if "xmomentum_c" in dataset.variables
            else np.zeros_like(stage)
        )
        ymomentum = (
            np.asarray(dataset.variables["ymomentum_c"].data, dtype=np.float64).copy()
            if "ymomentum_c" in dataset.variables
            else np.zeros_like(stage)
        )

    depths = np.maximum(stage - elevation[None, :], 0.0)
    safe_depths = np.maximum(depths, 1e-6)
    speeds = np.sqrt(xmomentum * xmomentum + ymomentum * ymomentum) / safe_depths
    speeds[depths < 0.005] = 0.0
    centroids = np.column_stack((x[volumes].mean(axis=1), y[volumes].mean(axis=1)))
    cols = np.clip(np.floor((centroids[:, 0] - bounds[0]) / cell_size_m).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((bounds[3] - centroids[:, 1]) / cell_size_m).astype(int), 0, ny - 1)
    cell_ids = rows * nx + cols

    depth_by_time = np.zeros((len(times), nx * ny), dtype=np.float32)
    speed_by_time = np.zeros((len(times), nx * ny), dtype=np.float32)
    for time_index in range(len(times)):
        np.maximum.at(depth_by_time[time_index], cell_ids, depths[time_index])
        np.maximum.at(speed_by_time[time_index], cell_ids, speeds[time_index])

    active = district_land.reshape(-1)
    maximum_depth = depth_by_time.max(axis=0).astype(np.float64)
    maximum_speed = speed_by_time.max(axis=0).astype(np.float64)
    peak_indices = np.argmax(depth_by_time, axis=0)
    peak_time_seconds = times[peak_indices]
    final_depth = depth_by_time[-1].astype(np.float64)
    maximum_depth[~active] = 0.0
    maximum_speed[~active] = 0.0
    final_depth[~active] = 0.0
    hazard = maximum_depth * (maximum_speed + 0.5)

    transformer = Transformer.from_crs(32640, 4326, always_xy=True)

    def polygon(row: int, col: int) -> list[list[float]]:
        corners = (
            (bounds[0] + col * cell_size_m, bounds[3] - row * cell_size_m),
            (bounds[0] + (col + 1) * cell_size_m, bounds[3] - row * cell_size_m),
            (bounds[0] + (col + 1) * cell_size_m, bounds[3] - (row + 1) * cell_size_m),
            (bounds[0] + col * cell_size_m, bounds[3] - (row + 1) * cell_size_m),
        )
        transformed = [transformer.transform(px, py) for px, py in corners]
        transformed.append(transformed[0])
        return [[float(lon), float(lat)] for lon, lat in transformed]

    def features_for(values: np.ndarray, time_index: int | None = None) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        for cell in np.flatnonzero(active & (values >= MINIMUM_MAPPED_DEPTH_M)):
            row, col = divmod(int(cell), nx)
            properties: dict[str, Any] = {
                "cell_id": int(cell),
                "depth_m": float(values[cell]),
                "cell_size_m": cell_size_m,
                "source_dtm_resolution_m": 5.0,
                "model_scope": "Al Bateen ADM district 147",
            }
            if time_index is None:
                properties.update(
                    {
                        "maximum_depth_m": float(maximum_depth[cell]),
                        "maximum_speed_m_s": float(maximum_speed[cell]),
                        "hazard_index": float(hazard[cell]),
                        "peak_time_minutes": float(peak_time_seconds[cell] / 60.0),
                        "final_depth_m": float(final_depth[cell]),
                    }
                )
            else:
                properties.update(
                    {
                        "speed_m_s": float(speed_by_time[time_index, cell]),
                        "hazard_index": float(
                            values[cell] * (float(speed_by_time[time_index, cell]) + 0.5)
                        ),
                        "time_minutes": float(times[time_index] / 60.0),
                    }
                )
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [polygon(row, col)]},
                    "properties": properties,
                }
            )
        return features

    maximum_payload = {
        "type": "FeatureCollection",
        "name": f"{run_id}_maximum_depth",
        "features": features_for(maximum_depth),
    }
    _json_dump(output / "maximum_depth_wgs84.geojson", maximum_payload)

    snapshots: list[dict[str, Any]] = []
    snapshot_dir = output / "temporal_snapshots"
    for time_index, timestamp in enumerate(times):
        filename = f"surface_depth_t{time_index:03d}.geojson"
        payload = {
            "type": "FeatureCollection",
            "name": f"{run_id}_time_{time_index:03d}",
            "features": features_for(depth_by_time[time_index], time_index),
        }
        _json_dump(snapshot_dir / filename, payload)
        snapshots.append(
            {
                "index": time_index,
                "time_seconds": float(timestamp),
                "time_minutes": float(timestamp / 60.0),
                "feature_count": len(payload["features"]),
                "path": f"temporal_snapshots/{filename}",
            }
        )
    _json_dump(
        snapshot_dir / "manifest.json",
        {
            "schema": "gisdataagent.al_bateen.high_resolution_timeseries.v1",
            "snapshots": snapshots,
        },
    )

    wet_001 = active & (maximum_depth >= 0.01)
    wet_005 = active & (maximum_depth >= 0.05)
    wet_030 = active & (maximum_depth >= 0.30)
    active_depths = maximum_depth[active]
    maximum_cell = int(np.flatnonzero(active)[np.argmax(active_depths)])
    cell_area = cell_size_m * cell_size_m
    runtime = {}
    runtime_path = output / "coupling_runtime.json"
    if runtime_path.is_file():
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    summary = {
        "schema": "gisdataagent.al_bateen.high_resolution_run.v1",
        "run_id": run_id,
        "status": "completed_diagnostic_not_engineering_admitted",
        "solver": "ANUGA 2D finite-volume shallow-water solver",
        "scope": {
            "name": "AL BATEEN",
            "municipality": "ADM",
            "district_id": 147,
            "dmt_district_id": 1300,
            "area_m2": 14098960.3627955,
        },
        "terrain": terrain,
        "forcing": forcing,
        "coupling": coupling,
        "runtime_balance": runtime,
        "timeline": {
            "snapshot_count": len(snapshots),
            "output_step_minutes": float(times[1] - times[0]) / 60.0 if len(times) > 1 else 0.0,
            "simulation_duration_minutes": float(times[-1] / 60.0),
        },
        "results": {
            "maximum_depth_m": float(maximum_depth[maximum_cell]),
            "maximum_depth_time_minutes": float(peak_time_seconds[maximum_cell] / 60.0),
            "maximum_speed_m_s": float(maximum_speed[active].max()),
            "maximum_hazard_index": float(hazard[active].max()),
            "inundated_cells_ge_0_01m": int(wet_001.sum()),
            "inundated_area_ge_0_01m_m2": float(wet_001.sum() * cell_area),
            "inundated_area_ge_0_05m_m2": float(wet_005.sum() * cell_area),
            "inundated_area_ge_0_30m_m2": float(wet_030.sum() * cell_area),
            "final_surface_volume_m3": float(final_depth[active].sum() * cell_area),
            "final_wet_cells_ge_0_01m": int(np.sum(active & (final_depth >= 0.01))),
            "final_inundated_area_ge_0_01m_m2": float(
                np.sum(active & (final_depth >= 0.01)) * cell_area
            ),
            "final_mean_depth_m": float(final_depth[active].mean()),
            "mapped_maximum_feature_count": len(maximum_payload["features"]),
        },
        "outputs": {
            "maximum_depth": "maximum_depth_wgs84.geojson",
            "timeline_manifest": "temporal_snapshots/manifest.json",
            "native_sww": "al_bateen_high_resolution_2d.sww",
        },
        "claim_boundary": (
            "Local high-resolution diagnostic using customer 5 m DTM and matching SWMM node flooding. "
            "It is not derived from the 250 m GWM and is not engineering-admitted until local drainage, "
            "tide, microtopography and observed flood depths are calibrated."
        ),
    }
    dewatering_enabled = bool(runtime.get("dewatering_enabled"))
    operational_complete = bool(
        dewatering_enabled
        and runtime.get("dewatering_stop_reason") == "operational_complete_dewatering_reached"
        and summary["results"]["final_wet_cells_ge_0_01m"] == 0
        and summary["results"]["final_mean_depth_m"]
        <= float(runtime.get("dry_mean_depth_threshold_m", DEFAULT_DRY_MEAN_DEPTH_THRESHOLD_M))
    )
    summary["dewatering"] = {
        "enabled": dewatering_enabled,
        "operational_complete": operational_complete,
        "definition": (
            "three consecutive output frames with zero district cells at or above 0.01 m "
            "and district mean residual depth at or below 0.001 m"
        ),
        "rainfall_end_minutes": RAINFALL_DURATION_MINUTES,
        "actual_end_minutes": float(times[-1] / 60.0),
        "actual_tail_minutes": max(0.0, float(times[-1] / 60.0) - RAINFALL_DURATION_MINUTES),
        "maximum_tail_minutes": float(runtime.get("maximum_tail_minutes", 0.0)),
        "drainage_timescale_minutes": float(
            runtime.get("drainage_timescale_minutes", DEFAULT_DRAINAGE_TIMESCALE_MINUTES)
        ),
        "minimum_drainage_mm_per_hour": float(
            runtime.get("minimum_drainage_mm_per_hour", DEFAULT_MINIMUM_DRAINAGE_MM_PER_HOUR)
        ),
        "dry_depth_threshold_m": float(runtime.get("dry_depth_threshold_m", MINIMUM_MAPPED_DEPTH_M)),
        "dry_mean_depth_threshold_m": float(
            runtime.get("dry_mean_depth_threshold_m", DEFAULT_DRY_MEAN_DEPTH_THRESHOLD_M)
        ),
        "dry_consecutive_frames_required": int(
            runtime.get("dry_consecutive_frames_required", DEFAULT_DRY_CONSECUTIVE_FRAMES)
        ),
        "stop_reason": runtime.get("dewatering_stop_reason"),
        "surface_drainage_outflow_m3": runtime.get("surface_drainage_outflow_m3"),
        "calibration_status": "operational_assumption_pending_local_observed_recession_calibration",
    }
    if operational_complete:
        summary["status"] = "completed_operationally_dewatered_diagnostic_not_engineering_admitted"
    _json_dump(output / "delivery_summary.json", summary)
    return summary


def run(
    *,
    boundary_path: Path,
    dtm_path: Path,
    land_cover_path: Path,
    output: Path,
    run_id: str,
    return_period_years: int,
    cell_size_m: float,
    tail_minutes: int,
    output_step_minutes: int,
    tide_level_m: float,
    manning_n: float,
    swmm_inp_path: Path | None,
    swmm_out_path: Path | None,
    dewater_until_dry: bool = False,
    drainage_timescale_minutes: float = DEFAULT_DRAINAGE_TIMESCALE_MINUTES,
    minimum_drainage_mm_per_hour: float = DEFAULT_MINIMUM_DRAINAGE_MM_PER_HOUR,
    dry_mean_depth_threshold_m: float = DEFAULT_DRY_MEAN_DEPTH_THRESHOLD_M,
    dry_consecutive_frames: int = DEFAULT_DRY_CONSECUTIVE_FRAMES,
    tidal_connectivity_vertical_tolerance_m: float = (
        DEFAULT_TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M
    ),
) -> dict[str, Any]:
    if cell_size_m not in {10.0, 20.0}:
        raise ValueError("al_bateen_cell_size_m_must_be_10_or_20")
    if return_period_years not in {2, 5, 10, 25, 50, 100}:
        raise ValueError("al_bateen_return_period_not_supported")
    if tail_minutes < 0:
        raise ValueError("al_bateen_tail_minutes_invalid")
    if drainage_timescale_minutes <= 0.0:
        raise ValueError("al_bateen_drainage_timescale_invalid")
    if minimum_drainage_mm_per_hour < 0.0:
        raise ValueError("al_bateen_minimum_drainage_rate_invalid")
    if dry_mean_depth_threshold_m < 0.0:
        raise ValueError("al_bateen_dry_mean_depth_threshold_invalid")
    if dry_consecutive_frames < 1:
        raise ValueError("al_bateen_dry_consecutive_frames_invalid")
    if tidal_connectivity_vertical_tolerance_m < 0.0:
        raise ValueError("al_bateen_tidal_connectivity_tolerance_invalid")
    for required, code in (
        (boundary_path, "al_bateen_boundary_missing"),
        (dtm_path, "al_bateen_customer_dtm_missing"),
        (land_cover_path, "al_bateen_land_cover_missing"),
        (ANUGA_PYTHON, "al_bateen_anuga_runtime_missing"),
    ):
        if not required.is_file():
            raise ValueError(code)

    exchange_enabled = swmm_inp_path is not None or swmm_out_path is not None
    if exchange_enabled:
        if swmm_inp_path is None or swmm_out_path is None:
            raise ValueError("al_bateen_swmm_inp_and_out_required")
        if not swmm_inp_path.is_file() or not swmm_out_path.is_file():
            raise ValueError("al_bateen_swmm_artifact_missing")

    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="al-bateen-high-resolution-2d-"))
    try:
        boundary_feature, raw_bounds = _load_boundary(boundary_path)
        bounds = _snap_bounds(raw_bounds, cell_size_m)
        terrain = _prepare_terrain(
            dtm_path,
            land_cover_path,
            boundary_feature,
            bounds,
            cell_size_m,
            tide_level_m,
            tidal_connectivity_vertical_tolerance_m,
            work,
        )
        rainfall_values, rainfall_metadata = _rainfall(return_period_years, tail_minutes)
        coupling: dict[str, Any] | None = None
        if exchange_enabled:
            helpers = _load_citywide_helpers()
            helpers.ACTIVE_CELL_SIZE_M = cell_size_m
            coupling = helpers._prepare_swmm_exchange(
                swmm_out_path,
                swmm_inp_path,
                work / "terrain_grid.npz",
                work,
                bounds,
            )
            coupling.update(
                {
                    "source_run": swmm_inp_path.parents[1].name,
                    "source_input": swmm_inp_path.name,
                    "source_output": swmm_out_path.name,
                    "quality_boundary": "native SWMM diagnostic output; strict numerical quality warnings retained",
                }
            )

        model_script = work / "al_bateen_high_resolution_2d.py"
        _write_model_script(
            model_script,
            bounds=bounds,
            cell_size_m=cell_size_m,
            rainfall_mm_per_h=rainfall_values,
            tail_minutes=tail_minutes,
            output_step_minutes=output_step_minutes,
            tide_level_m=tide_level_m,
            manning_n=manning_n,
            exchange_enabled=exchange_enabled,
            dewater_until_dry=dewater_until_dry,
            drainage_timescale_minutes=drainage_timescale_minutes,
            minimum_drainage_mm_per_hour=minimum_drainage_mm_per_hour,
            dry_mean_depth_threshold_m=dry_mean_depth_threshold_m,
            dry_consecutive_frames=dry_consecutive_frames,
        )
        timeout_seconds = int(os.environ.get("AL_BATEEN_ANUGA_TIMEOUT_SECONDS", "7200"))
        process = subprocess.run(
            [str(ANUGA_PYTHON), str(model_script)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        (output / "anuga_stdout.log").write_text(process.stdout, encoding="utf-8")
        (output / "anuga_stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"al_bateen_anuga_failed:{process.returncode}")

        sww_candidates = sorted(work.glob("*.sww"))
        if not sww_candidates:
            raise RuntimeError("al_bateen_anuga_sww_missing")
        target_sww = output / "al_bateen_high_resolution_2d.sww"
        shutil.copy2(sww_candidates[0], target_sww)
        if (work / "coupling_runtime.json").is_file():
            shutil.copy2(work / "coupling_runtime.json", output / "coupling_runtime.json")
        if (work / "swmm_exchange.npz").is_file():
            shutil.copy2(work / "swmm_exchange.npz", output / "swmm_exchange.npz")
        shutil.copy2(work / "terrain_grid.npz", output / "terrain_grid.npz")

        summary = _extract_outputs(
            target_sww,
            output,
            output / "terrain_grid.npz",
            run_id=run_id,
            terrain=terrain,
            forcing=rainfall_metadata,
            coupling=coupling,
        )
        _json_dump(
            output / "run_receipt.json",
            {
                "schema": "gisdataagent.al_bateen.high_resolution_receipt.v1",
                "status": "completed",
                "run_id": run_id,
                "return_period_years": return_period_years,
                "cell_size_m": cell_size_m,
                "customer_dtm_used_directly": True,
                "citywide_250m_gwm_used": False,
                "operational_complete_dewatering": bool(
                    (summary.get("dewatering") or {}).get("operational_complete")
                ),
                "summary": summary,
            },
        )
        return summary
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--dtm", type=Path, default=DEFAULT_DTM)
    parser.add_argument("--land-cover", type=Path, default=DEFAULT_LAND_COVER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--return-period-years", type=int, default=10)
    parser.add_argument("--cell-size-m", type=float, default=20.0)
    parser.add_argument("--tail-minutes", type=int, default=120)
    parser.add_argument("--output-step-minutes", type=int, default=15)
    parser.add_argument("--tide-level-m", type=float, default=0.0)
    parser.add_argument("--manning-n", type=float, default=0.035)
    parser.add_argument("--dewater-until-dry", action="store_true")
    parser.add_argument(
        "--drainage-timescale-minutes",
        type=float,
        default=DEFAULT_DRAINAGE_TIMESCALE_MINUTES,
    )
    parser.add_argument(
        "--minimum-drainage-mm-per-hour",
        type=float,
        default=DEFAULT_MINIMUM_DRAINAGE_MM_PER_HOUR,
    )
    parser.add_argument(
        "--dry-mean-depth-threshold-m",
        type=float,
        default=DEFAULT_DRY_MEAN_DEPTH_THRESHOLD_M,
    )
    parser.add_argument(
        "--dry-consecutive-frames",
        type=int,
        default=DEFAULT_DRY_CONSECUTIVE_FRAMES,
    )
    parser.add_argument(
        "--tidal-connectivity-vertical-tolerance-m",
        type=float,
        default=DEFAULT_TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M,
    )
    parser.add_argument("--swmm-inp", type=Path, default=None)
    parser.add_argument("--swmm-out", type=Path, default=None)
    args = parser.parse_args()
    result = run(
        boundary_path=args.boundary.expanduser().resolve(),
        dtm_path=args.dtm.expanduser().resolve(),
        land_cover_path=args.land_cover.expanduser().resolve(),
        output=args.output.expanduser().resolve(),
        run_id=args.run_id,
        return_period_years=args.return_period_years,
        cell_size_m=args.cell_size_m,
        tail_minutes=args.tail_minutes,
        output_step_minutes=args.output_step_minutes,
        tide_level_m=args.tide_level_m,
        manning_n=args.manning_n,
        swmm_inp_path=args.swmm_inp.expanduser().resolve() if args.swmm_inp else None,
        swmm_out_path=args.swmm_out.expanduser().resolve() if args.swmm_out else None,
        dewater_until_dry=args.dewater_until_dry,
        drainage_timescale_minutes=args.drainage_timescale_minutes,
        minimum_drainage_mm_per_hour=args.minimum_drainage_mm_per_hour,
        dry_mean_depth_threshold_m=args.dry_mean_depth_threshold_m,
        dry_consecutive_frames=args.dry_consecutive_frames,
        tidal_connectivity_vertical_tolerance_m=(
            args.tidal_connectivity_vertical_tolerance_m
        ),
    )
    print(json.dumps({"status": result["status"], "run_id": result["run_id"], "results": result["results"]}))


if __name__ == "__main__":
    main()
