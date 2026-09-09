#!/usr/bin/env python3
"""Run a citywide Abu Dhabi 2D surface model with a supplied DEM/DTM.

The computational grid, rainfall forcing, land/water mask, solver and output
contract stay fixed so a customer DTM can replace the public DEM without
changing downstream consumers. Outputs are written outside the repository.
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
ANUGA_PYTHON = Path(os.environ.get(
    "ABU_DHABI_ANUGA_PYTHON",
    next(
        (
            candidate
            for candidate in (
                REPOSITORY_ROOT / "external_models/anuga-venv/bin/python",
                Path("/Users/zhouning/gisdataagent/external_models/anuga-venv/bin/python"),
            )
            if candidate.is_file()
        ),
        REPOSITORY_ROOT / "external_models/anuga-venv/bin/python",
    ),
))
# Bounds are snapped to the 250 m model grid. They remain inside the existing
# public Copernicus crop while avoiding a partial cell at either edge.
CITY_BOUNDS = (225750.0, 2687250.0, 273250.0, 2723250.0)
# Fast citywide default. The runner also accepts finer grids (100 m is the
# recommended full-city demonstration profile; 50 m is a priority-area profile).
CELL_SIZE_M = 250.0
ACTIVE_CELL_SIZE_M = CELL_SIZE_M
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


def _parse_swmm_coordinates(inp_path: Path) -> dict[str, tuple[float, float]]:
    coordinates: dict[str, tuple[float, float]] = {}
    section = ""
    with inp_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line.upper()
                continue
            if section != "[COORDINATES]":
                continue
            values = line.split()
            if len(values) < 3:
                continue
            try:
                coordinates[values[0]] = (float(values[1]), float(values[2]))
            except ValueError:
                continue
    if not coordinates:
        raise ValueError("swmm_inp_coordinates_missing")
    return coordinates


def _parse_swmm_subcatchment_areas(inp_path: Path) -> list[tuple[str, float]]:
    """Return outlet node identifiers and areas in square metres."""

    subcatchments: list[tuple[str, float]] = []
    section = ""
    with inp_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line.upper()
                continue
            if section != "[SUBCATCHMENTS]":
                continue
            values = line.split()
            if len(values) < 4:
                continue
            try:
                area_m2 = max(0.0, float(values[3]) * 10_000.0)
            except ValueError:
                continue
            if area_m2 > 0.0:
                subcatchments.append((values[2], area_m2))
    return subcatchments


def _load_swmm_out_parser():
    parser_path = REPOSITORY_ROOT / "data_agent/uwm/abu_dhabi_flood/swmm_out_parser.py"
    spec = importlib.util.spec_from_file_location("abu_dhabi_swmm_out_parser", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("swmm_out_parser_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_swmm_exchange(
    swmm_out_path: Path,
    swmm_inp_path: Path,
    terrain_grid_path: Path,
    work: Path,
    bounds: tuple[float, float, float, float],
) -> dict[str, object]:
    """Map native SWMM node flooding rates to ANUGA surface cells.

    This is deliberately an explicit one-way adapter.  A native SWMM ``.out``
    file is a completed run, so it can provide a time-varying surface source,
    but it cannot accept ANUGA feedback after the fact.  Keeping that boundary
    explicit prevents a prescribed lateral-inflow series from being mistaken
    for a true ANUGA -> SWMM hydraulic feedback.
    """

    parser = _load_swmm_out_parser()
    header = parser.read_swmm_out_header(swmm_out_path)
    coordinates = _parse_swmm_coordinates(swmm_inp_path)
    subcatchments = _parse_swmm_subcatchment_areas(swmm_inp_path)
    nx = int(round((bounds[2] - bounds[0]) / ACTIVE_CELL_SIZE_M))
    ny = int(round((bounds[3] - bounds[1]) / ACTIVE_CELL_SIZE_M))
    with np.load(terrain_grid_path) as grid:
        land_mask = np.asarray(grid["land_mask"], dtype=bool)
    if land_mask.shape != (ny, nx):
        raise ValueError("swmm_exchange_land_mask_shape_invalid")

    node_names = list(header["node_names"])
    node_cells = np.full(len(node_names), -1, dtype=np.int64)
    matched = 0
    in_domain = 0
    remapped_to_land = 0
    from scipy.ndimage import distance_transform_edt

    _, nearest_land = distance_transform_edt(~land_mask, return_indices=True)
    for index, node_name in enumerate(node_names):
        position = coordinates.get(node_name)
        if position is None:
            continue
        matched += 1
        x, y = position
        if not (bounds[0] <= x < bounds[2] and bounds[1] < y <= bounds[3]):
            continue
        col = min(nx - 1, max(0, int((x - bounds[0]) // ACTIVE_CELL_SIZE_M)))
        row = min(ny - 1, max(0, int((bounds[3] - y) // ACTIVE_CELL_SIZE_M)))
        in_domain += 1
        if not land_mask[row, col]:
            row = int(nearest_land[0, row, col])
            col = int(nearest_land[1, row, col])
            remapped_to_land += 1
        node_cells[index] = row * nx + col

    valid_node_indices = np.flatnonzero(node_cells >= 0)
    if valid_node_indices.size == 0:
        raise ValueError("swmm_exchange_has_no_nodes_in_2d_domain")
    period_count = int(header["period_count"])
    report_step_seconds = float(header["report_step_seconds"])
    swmm_to_anuga_cell_rates_mps = np.zeros((period_count, nx * ny), dtype=np.float32)
    swmm_modeled_area_by_cell_m2 = np.zeros(nx * ny, dtype=np.float64)
    mapped_subcatchment_count = 0
    mapped_subcatchment_area_m2 = 0.0
    for outlet_node_id, area_m2 in subcatchments:
        position = coordinates.get(outlet_node_id)
        if position is None:
            continue
        x, y = position
        if not (bounds[0] <= x < bounds[2] and bounds[1] < y <= bounds[3]):
            continue
        col = min(nx - 1, max(0, int((x - bounds[0]) // ACTIVE_CELL_SIZE_M)))
        row = min(ny - 1, max(0, int((bounds[3] - y) // ACTIVE_CELL_SIZE_M)))
        if not land_mask[row, col]:
            row = int(nearest_land[0, row, col])
            col = int(nearest_land[1, row, col])
        swmm_modeled_area_by_cell_m2[row * nx + col] += area_m2
        mapped_subcatchment_count += 1
        mapped_subcatchment_area_m2 += area_m2
    cell_area_m2 = ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M
    swmm_modeled_fraction_by_cell = np.clip(
        swmm_modeled_area_by_cell_m2 / cell_area_m2, 0.0, 1.0
    ).astype(np.float32)
    surface_rainfall_fraction_by_cell = np.where(
        land_mask.reshape(-1), 1.0 - swmm_modeled_fraction_by_cell, 0.0
    ).astype(np.float32)
    times_seconds = np.asarray(
        [report_step_seconds * (index + 1) for index in range(period_count)],
        dtype=np.float64,
    )
    positive_node_periods = 0
    maximum_total_rate_m3s = 0.0
    transferred_volume_m3 = 0.0
    for period_index in range(period_count):
        period = parser.read_node_period(swmm_out_path, header, period_index)
        flooding = np.fromiter(
            (max(0.0, float(values[5])) for values in period["nodes"]),
            dtype=np.float64,
            count=len(node_names),
        )
        selected = flooding[valid_node_indices]
        positive_node_periods += int(np.count_nonzero(selected > 0.0))
        total_rate = float(selected.sum())
        maximum_total_rate_m3s = max(maximum_total_rate_m3s, total_rate)
        transferred_volume_m3 += total_rate * report_step_seconds
        overflow_by_cell_m3s = np.zeros(nx * ny, dtype=np.float64)
        np.add.at(overflow_by_cell_m3s, node_cells[valid_node_indices], selected)
        swmm_to_anuga_cell_rates_mps[period_index] = (
            overflow_by_cell_m3s / (ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M)
        ).astype(np.float32)

    exchange_path = work / "swmm_exchange.npz"
    np.savez_compressed(
        exchange_path,
        swmm_to_anuga_cell_rates_mps=swmm_to_anuga_cell_rates_mps,
        surface_rainfall_fraction_by_cell=surface_rainfall_fraction_by_cell,
        times_seconds=times_seconds,
        report_step_seconds=np.asarray(report_step_seconds, dtype=np.float64),
        cell_size_m=np.asarray(ACTIVE_CELL_SIZE_M, dtype=np.float64),
    )
    return {
        "mode": "one_way_swmm_to_anuga",
        "source_out": str(swmm_out_path),
        "source_inp": str(swmm_inp_path),
        "swmm_node_count": len(node_names),
        "coordinate_match_count": matched,
        "nodes_in_2d_domain": in_domain,
        "nodes_remapped_from_masked_water_to_nearest_land_cell": remapped_to_land,
        "mapped_node_count": int(valid_node_indices.size),
        "swmm_subcatchment_count": len(subcatchments),
        "mapped_swmm_subcatchment_count": mapped_subcatchment_count,
        "mapped_swmm_subcatchment_area_m2": mapped_subcatchment_area_m2,
        "effective_swmm_subcatchment_area_m2_after_cell_cap": float(
            swmm_modeled_fraction_by_cell.sum() * cell_area_m2
        ),
        "swmm_period_count": period_count,
        "swmm_report_step_seconds": report_step_seconds,
        "swmm_exchange_time_origin": "first_native_report_period_at_report_step_not_t0",
        "positive_node_period_count": positive_node_periods,
        "maximum_aggregate_exchange_rate_m3s": maximum_total_rate_m3s,
        "prescribed_swmm_to_anuga_volume_m3": transferred_volume_m3,
        "exchange_quantity": {
            "swmm_to_anuga": "node overflow_or_flooding_m3s",
        },
        "exchange_application": "piecewise_constant_source_over_mapped_2d_cell",
        "rainfall_partition": (
            "direct_2d_rainfall_is_reduced_by_mapped_swmm_subcatchment_fraction_"
            "to_avoid_double_counting"
        ),
        "dynamic_head_feedback_in_this_run": False,
        "bidirectional_solver_loop": "not_available_for_completed_native_swmm_out",
        "next_bidirectional_step": "synchronous_swmm_step_anuga_step_with_head_difference_exchange",
    }

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
            raise ValueError("citywide_surface_must_be_single_band_epsg32640")
        nx = int(round((bounds[2] - bounds[0]) / ACTIVE_CELL_SIZE_M))
        ny = int(round((bounds[3] - bounds[1]) / ACTIVE_CELL_SIZE_M))
        window = from_bounds(*bounds, transform=source.transform).round_offsets().round_lengths()
        arr = source.read(1, window=window, out_shape=(ny + 1, nx + 1), resampling=Resampling.bilinear, masked=True)
        if np.ma.getmaskarray(arr).any():
            raise ValueError("citywide_surface_contains_nodata")
        values = np.asarray(arr, dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError("citywide_surface_contains_nonfinite")
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
            dst_transform=from_origin(bounds[0], bounds[3], ACTIVE_CELL_SIZE_M, ACTIVE_CELL_SIZE_M),
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
            dst_transform=from_origin(bounds[0], bounds[3], ACTIVE_CELL_SIZE_M, ACTIVE_CELL_SIZE_M),
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
        "grid_shape": list(values.shape), "cell_size_m": ACTIVE_CELL_SIZE_M,
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
            "active_land_area_m2": float(land_mask.sum() * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M),
            "excluded_permanent_water_area_m2": float((~land_mask).sum() * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M),
            "claim_boundary": "public land-cover proxy; replace with customer authoritative shoreline and permanent-water polygons",
        },
    }

def _write_model_script(
    path: Path,
    terrain: dict[str, object],
    rainfall: list[float],
    bounds: tuple[float, float, float, float],
    exchange_enabled: bool = False,
) -> None:
    nx = int(round((bounds[2] - bounds[0]) / ACTIVE_CELL_SIZE_M))
    ny = int(round((bounds[3] - bounds[1]) / ACTIVE_CELL_SIZE_M))
    final_time = (RAIN_DURATION_MINUTES + TAIL_MINUTES) * 60.0
    exchange_block = """
EXCHANGE = np.load("swmm_exchange.npz")
SWMM_TO_ANUGA_RATES = np.asarray(EXCHANGE["swmm_to_anuga_cell_rates_mps"], dtype=float)
SURFACE_RAINFALL_FRACTION = np.asarray(EXCHANGE["surface_rainfall_fraction_by_cell"], dtype=float)
EXCHANGE_TIMES = np.asarray(EXCHANGE["times_seconds"], dtype=float)
EXCHANGE_STEP_SECONDS = float(np.asarray(EXCHANGE["report_step_seconds"]).reshape(()))
if (SWMM_TO_ANUGA_RATES.ndim != 2
        or SWMM_TO_ANUGA_RATES.shape[1] != LAND.size
        or SURFACE_RAINFALL_FRACTION.size != LAND.size
        or EXCHANGE_TIMES.size != SWMM_TO_ANUGA_RATES.shape[0]):
    raise RuntimeError("swmm_exchange_grid_shape_mismatch")
""" if exchange_enabled else ""
    exchange_operators = """
def swmm_surface_source_rate(x, y, t):
    exchange_active = t >= EXCHANGE_TIMES[0] and t < EXCHANGE_TIMES[-1] + EXCHANGE_STEP_SECONDS
    exchange_index = int(np.searchsorted(EXCHANGE_TIMES, t, side=\"right\") - 1) if exchange_active else -1
    rate = SWMM_TO_ANUGA_RATES[int(np.clip(exchange_index, 0, SWMM_TO_ANUGA_RATES.shape[0] - 1))][cell_ids(x, y)] if exchange_index >= 0 else 0.0
    return np.where(is_land(x, y), rate, 0.0)

swmm_to_anuga_operator = anuga.Rate_operator(domain, rate=swmm_surface_source_rate, label=\"swmm_node_flooding_to_anuga_surface\")
""" if exchange_enabled else ""
    exchange_runtime = """
import json
with open(\"coupling_runtime.json\", \"w\", encoding=\"utf-8\") as handle:
    json.dump({
        \"actual_swmm_to_anuga_volume_m3\": float(swmm_to_anuga_operator.cumulative_influx),
    }, handle, sort_keys=True)
""" if exchange_enabled else ""
    script = f'''"""Generated full-city Abu Dhabi ANUGA model."""
import numpy as np
import anuga

GRID = np.load("terrain_grid.npz")
VALUES = np.asarray(GRID["values"], dtype=float)
X = np.asarray(GRID["x"], dtype=float)
Y = np.asarray(GRID["y"], dtype=float)
LAND = np.asarray(GRID["land_mask"], dtype=bool)
RAINFALL_MM_PER_H = {tuple(float(v) for v in rainfall)!r}
DX = {ACTIVE_CELL_SIZE_M!r}
{exchange_block}

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

def cell_ids(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    col = np.clip(np.floor((x - X[0]) / DX).astype(int), 0, LAND.shape[1] - 1)
    row = np.clip(np.floor((Y[0] - y) / DX).astype(int), 0, LAND.shape[0] - 1)
    return row * LAND.shape[1] + col

def rainfall_rate(x, y, t):
    index = int(t // 300.0)
    intensity = RAINFALL_MM_PER_H[index] * 0.001 / 3600.0 if 0 <= index < len(RAINFALL_MM_PER_H) else 0.0
    base = np.where(is_land(x, y), intensity, 0.0)
    {(
        'return base * SURFACE_RAINFALL_FRACTION[cell_ids(x, y)]'
        if exchange_enabled
        else 'return base'
    )}

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
{exchange_operators}
for _ in domain.evolve(yieldstep={REPORT_INTERVAL_SECONDS!r}, finaltime={final_time!r}):
    pass
{exchange_runtime}
'''
    path.write_text(script, encoding="utf-8")

def _extract_outputs(
    sww_path: Path,
    output: Path,
    bounds: tuple[float, float, float, float],
    terrain: dict[str, object],
    rainfall: dict[str, object],
    terrain_grid_path: Path,
    *,
    surface_product: str,
    surface_evidence_class: str,
    run_id: str,
    coupling_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    from scipy.io import netcdf_file
    with netcdf_file(sww_path, "r", mmap=False) as dataset:
        x = np.asarray(dataset.variables["x"].data, dtype=np.float64).copy()
        y = np.asarray(dataset.variables["y"].data, dtype=np.float64).copy()
        volumes = np.asarray(dataset.variables["volumes"].data, dtype=np.int64).copy()
        elevation = np.asarray(dataset.variables["elevation_c"].data, dtype=np.float64).copy()
        stage = np.asarray(dataset.variables["stage_c"].data, dtype=np.float64).copy()
        times = np.asarray(dataset.variables["time"].data, dtype=np.float64).copy()
    depths = np.maximum(stage - elevation[None, :], 0.0)
    nx = int(round((bounds[2] - bounds[0]) / ACTIVE_CELL_SIZE_M))
    ny = int(round((bounds[3] - bounds[1]) / ACTIVE_CELL_SIZE_M))
    with np.load(terrain_grid_path) as terrain_grid:
        land_mask = np.asarray(terrain_grid["land_mask"], dtype=bool)
        water_fraction = np.asarray(terrain_grid["water_fraction"], dtype=np.float64)
    if land_mask.shape != (ny, nx) or water_fraction.shape != (ny, nx):
        raise ValueError("public_citywide_land_water_mask_shape_invalid")
    centroids = np.column_stack((x[volumes].mean(axis=1), y[volumes].mean(axis=1)))
    columns = np.clip(np.floor((centroids[:, 0] - bounds[0]) / ACTIVE_CELL_SIZE_M).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((bounds[3] - centroids[:, 1]) / ACTIVE_CELL_SIZE_M).astype(int), 0, ny - 1)
    cell_ids = rows * nx + columns
    depth_by_time_cell = np.zeros((len(times), nx * ny), dtype=np.float32)
    for time_index in range(len(times)):
        np.maximum.at(depth_by_time_cell[time_index], cell_ids, depths[time_index])
    max_by_cell = np.asarray(depth_by_time_cell.max(axis=0), dtype=np.float64)
    peak_time_by_cell = times[np.argmax(depth_by_time_cell, axis=0)]
    final_by_cell = np.asarray(depth_by_time_cell[-1], dtype=np.float64)
    active_land_by_cell = land_mask.reshape(-1)
    water_fraction_by_cell = water_fraction.reshape(-1)
    max_by_cell[~active_land_by_cell] = 0.0
    peak_time_by_cell[~active_land_by_cell] = 0.0
    final_by_cell[~active_land_by_cell] = 0.0
    transformer = Transformer.from_crs(32640, 4326, always_xy=True)
    def polygon_for_cell(row: int, col: int) -> list[list[float]]:
        corners = [(bounds[0] + col * ACTIVE_CELL_SIZE_M, bounds[3] - row * ACTIVE_CELL_SIZE_M),
                   (bounds[0] + (col + 1) * ACTIVE_CELL_SIZE_M, bounds[3] - row * ACTIVE_CELL_SIZE_M),
                   (bounds[0] + (col + 1) * ACTIVE_CELL_SIZE_M, bounds[3] - (row + 1) * ACTIVE_CELL_SIZE_M),
                   (bounds[0] + col * ACTIVE_CELL_SIZE_M, bounds[3] - (row + 1) * ACTIVE_CELL_SIZE_M)]
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
                "prototype_cell_size_m": ACTIVE_CELL_SIZE_M,
                "land_fraction": float(1.0 - water_fraction_by_cell[cell]),
                "permanent_water_fraction": float(water_fraction_by_cell[cell]),
            }
            if time_minutes is None:
                props.update({"maximum_depth_m": float(value), "maximum_depth_time_minutes": float(peak_time_by_cell[cell] / 60.0), "final_depth_m": float(final_by_cell[cell])})
            else:
                props["time_minutes"] = float(time_minutes)
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [polygon_for_cell(row, col)]}, "properties": props})
        return features
    maximum = {"type": "FeatureCollection", "name": f"{run_id}_maximum_depth", "features": make_features(max_by_cell)}
    _json_dump(output / "maximum_depth_wgs84.geojson", maximum)
    snapshot_dir = output / "temporal_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for time_index, timestamp in enumerate(times):
        values_by_cell = np.asarray(depth_by_time_cell[time_index], dtype=np.float64)
        name = f"surface_depth_t{time_index:03d}.geojson"
        _json_dump(snapshot_dir / name, {"type": "FeatureCollection", "name": f"{run_id}_time_{time_index:03d}", "features": make_features(values_by_cell, float(timestamp / 60.0))})
        snapshots.append({"index": time_index, "time_seconds": float(timestamp), "time_minutes": float(timestamp / 60.0), "path": f"temporal_snapshots/{name}"})
    _json_dump(snapshot_dir / "manifest.json", {"schema": "gwm.abu_dhabi_flood.public_citywide_2d_timeseries.v1", "snapshots": snapshots})
    land_mask_metadata = terrain["land_water_mask"]
    active_land_count = int(active_land_by_cell.sum())
    active_land_area_m2 = float(active_land_count * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M)
    maximum_depth_m = float(max_by_cell[active_land_by_cell].max())
    maximum_depth_cell = int(np.flatnonzero(active_land_by_cell)[np.argmax(max_by_cell[active_land_by_cell])])
    summary = {
        "schema": "gwm.abu_dhabi_flood.public_citywide_2d_delivery.v2",
        "status": (
            "completed_customer_dtm_citywide_2d_validation"
            if surface_evidence_class.startswith("customer")
            else "completed_public_copernicus_citywide_2d_prototype_not_calibrated"
        ),
        "run_id": run_id,
        "solver": "ANUGA 2D",
        "surface": {
            "product": surface_product,
            "evidence_class": surface_evidence_class,
            **terrain,
        },
        "domain": {"bounds_epsg32640": list(bounds), "area_m2": float((bounds[2]-bounds[0]) * (bounds[3]-bounds[1])), "cell_size_m": ACTIVE_CELL_SIZE_M, "rectangular_cells": nx * ny, "active_land_cells": active_land_count, "excluded_permanent_water_cells": int((~active_land_by_cell).sum()), "active_land_area_m2": active_land_area_m2, "triangle_count": int(len(volumes)), "simulation_duration_hours": float(times[-1] / 3600.0), "output_step_minutes": float(REPORT_INTERVAL_SECONDS / 60.0)},
        "forcing": rainfall,
        "land_water_treatment": {**land_mask_metadata, "rainfall_applied_to": "active_land_cells_only", "permanent_water_output_policy": "excluded_from_inland_flood_layers_and_statistics", "sea_boundary_level_m": SEA_LEVEL_M, "sea_boundary_condition": "fixed_stage_zero_momentum_at_outer_domain; connected permanent-water cells retained as drainage medium"},
        "results": {"maximum_depth_m": maximum_depth_m, "maximum_depth_time_minutes": float(peak_time_by_cell[maximum_depth_cell] / 60.0), "inundated_cells_ge_0_01m": int(np.sum((max_by_cell >= 0.01) & active_land_by_cell)), "inundated_area_ge_0_01m2": float(np.sum((max_by_cell >= 0.01) & active_land_by_cell) * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M), "inundated_area_ge_0_05m2": float(np.sum((max_by_cell >= 0.05) & active_land_by_cell) * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M), "final_surface_volume_m3": float(np.sum(final_by_cell[active_land_by_cell]) * ACTIVE_CELL_SIZE_M * ACTIVE_CELL_SIZE_M)},
        "outputs": {"maximum_depth": "maximum_depth_wgs84.geojson", "timeline_manifest": "temporal_snapshots/manifest.json", "native_sww": "abu_dhabi_public_citywide_2d.sww"},
        "admission": {
            "numerical_validation_completed": True,
            "customer_surface_used": surface_evidence_class.startswith("customer"),
            "customer_authoritative_engineering_prediction": False,
            "gwm_training_admitted": False,
            "citywide_prediction_claim_allowed": False,
        },
        "claim_boundary": (
            "Customer 5 m DTM citywide numerical validation; vertical datum, tide boundary, "
            "urban microtopography, infiltration and observations still require calibration."
            if surface_evidence_class.startswith("customer")
            else "Public DEM citywide prototype; not calibrated or engineering-admitted."
        ),
        "replacement_contract": "The DEM/DTM is replaceable while retaining the same ANUGA and map-output contract.",
    }
    if coupling_metadata is not None:
        summary["coupling"] = coupling_metadata
    _json_dump(output / "delivery_summary.json", summary)
    return summary

def run(
    dem_path: Path,
    land_cover_path: Path,
    output: Path,
    *,
    cell_size_m: float = CELL_SIZE_M,
    surface_product: str = "Copernicus DEM GLO-30 public proxy",
    surface_evidence_class: str = "public_proxy_not_authoritative",
    dem_source_url: str | None = "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30",
    run_id: str = "abu-dhabi-public-copernicus-citywide-anuga-20260906",
    swmm_inp_path: Path | None = None,
    swmm_out_path: Path | None = None,
) -> dict[str, object]:
    if not math.isfinite(float(cell_size_m)) or cell_size_m < 25.0 or cell_size_m > 1000.0:
        raise ValueError("citywide_2d_cell_size_m_must_be_between_25_and_1000")
    if abs(round((CITY_BOUNDS[2] - CITY_BOUNDS[0]) / cell_size_m) * cell_size_m - (CITY_BOUNDS[2] - CITY_BOUNDS[0])) > 1e-6:
        raise ValueError("citywide_2d_cell_size_m_must_tile_city_bounds")
    global ACTIVE_CELL_SIZE_M
    ACTIVE_CELL_SIZE_M = float(cell_size_m)
    if not dem_path.is_file():
        raise ValueError("public_citywide_dem_missing")
    if not land_cover_path.is_file():
        raise ValueError("public_citywide_land_cover_missing")
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abu-public-citywide-2d-"))
    try:
        terrain = _prepare_terrain(dem_path, land_cover_path, work, CITY_BOUNDS)
        rainfall, rainfall_meta = _rainfall_100y_180min()
        coupling_metadata = None
        exchange_enabled = swmm_inp_path is not None or swmm_out_path is not None
        if exchange_enabled:
            if swmm_inp_path is None or swmm_out_path is None:
                raise ValueError("swmm_inp_and_out_required_for_coupled_run")
            swmm_inp_path = swmm_inp_path.expanduser().resolve()
            swmm_out_path = swmm_out_path.expanduser().resolve()
            if not swmm_inp_path.is_file() or not swmm_out_path.is_file():
                raise ValueError("swmm_coupling_input_missing")
            coupling_metadata = _prepare_swmm_exchange(
                swmm_out_path, swmm_inp_path, work / "terrain_grid.npz", work, CITY_BOUNDS
            )
        model_script = work / "abu_dhabi_public_citywide_2d.py"
        _write_model_script(model_script, terrain, rainfall, CITY_BOUNDS, exchange_enabled=exchange_enabled)
        process = subprocess.run([str(ANUGA_PYTHON), str(model_script)], cwd=work, capture_output=True, text=True, timeout=1800)
        (output / "anuga_stdout.log").write_text(process.stdout, encoding="utf-8")
        (output / "anuga_stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"anuga_public_citywide_failed:{process.returncode}")
        if exchange_enabled and coupling_metadata is not None:
            runtime_path = work / "coupling_runtime.json"
            if runtime_path.is_file():
                coupling_metadata["runtime"] = json.loads(runtime_path.read_text(encoding="utf-8"))
        sww_candidates = sorted(work.glob("*.sww"))
        if not sww_candidates:
            raise RuntimeError("anuga_public_citywide_sww_missing")
        shutil.copy2(sww_candidates[0], output / "abu_dhabi_public_citywide_2d.sww")
        summary = _extract_outputs(
            output / "abu_dhabi_public_citywide_2d.sww", output, CITY_BOUNDS,
            terrain, rainfall_meta, work / "terrain_grid.npz",
            surface_product=surface_product,
            surface_evidence_class=surface_evidence_class,
            run_id=run_id,
            coupling_metadata=coupling_metadata,
        )
        if coupling_metadata is not None:
            shutil.copy2(work / "swmm_exchange.npz", output / "swmm_exchange.npz")
            coupling_metadata["exchange_artifact"] = "swmm_exchange.npz"
            summary["coupling"] = coupling_metadata
        _json_dump(output / "run_receipt.json", {
            "schema": "gwm.abu_dhabi_flood.citywide_2d_run_receipt.v3",
            "status": "completed",
            "run_id": run_id,
            "dem_source": str(dem_path),
            "dem_source_url": dem_source_url,
            "surface_product": surface_product,
            "surface_evidence_class": surface_evidence_class,
            "land_cover_source": str(land_cover_path),
            "land_cover_source_url": WORLD_COVER_SOURCE_URL,
            "output_directory": str(output),
            "summary": summary,
            "anuga_returncode": process.returncode,
            "claim_boundary": summary["claim_boundary"],
            "coupling": coupling_metadata,
        })
        return summary
    finally:
        shutil.rmtree(work, ignore_errors=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    parser.add_argument("--land-cover", type=Path, default=DEFAULT_LAND_COVER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--surface-product", default="Copernicus DEM GLO-30 public proxy")
    parser.add_argument("--surface-evidence-class", default="public_proxy_not_authoritative")
    parser.add_argument("--dem-source-url", default="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30")
    parser.add_argument("--run-id", default="abu-dhabi-public-copernicus-citywide-anuga-20260906")
    parser.add_argument("--cell-size-m", type=float, default=CELL_SIZE_M, help="2D grid cell size in metres (100 m recommended citywide demo)")
    parser.add_argument("--swmm-inp", type=Path, default=None, help="Optional SWMM input used to map node coordinates")
    parser.add_argument("--swmm-out", type=Path, default=None, help="Optional native SWMM OUT used to inject node flooding into ANUGA")
    args = parser.parse_args()
    result = run(
        args.dem.expanduser().resolve(),
        args.land_cover.expanduser().resolve(),
        args.output.expanduser().resolve(),
        surface_product=args.surface_product,
        surface_evidence_class=args.surface_evidence_class,
        dem_source_url=args.dem_source_url or None,
        run_id=args.run_id,
        cell_size_m=args.cell_size_m,
        swmm_inp_path=args.swmm_inp,
        swmm_out_path=args.swmm_out,
    )
    print(json.dumps({"output": str(args.output), "status": result["status"], "results": result["results"]}, ensure_ascii=True))

if __name__ == "__main__":
    main()
