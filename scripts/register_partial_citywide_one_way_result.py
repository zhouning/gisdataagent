#!/usr/bin/env python3
"""Publish an existing partial ANUGA SWW as GIS Data Agent assets.

This utility does not run a hydraulic model.  It aggregates the triangle
values in an existing ANUGA ``.sww`` onto the 250 m delivery cells and writes
the maximum-depth layer, maximum-inundation extent layer and lazy-playback
GeoJSON frames expected by the public-citywide-2d API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.io import netcdf_file


OUTPUT_DEPTH_THRESHOLD_M = 0.01
CELL_SIZE_M = 250.0


def dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sww", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-window-count", type=int, default=312)
    parser.add_argument("--target-end-time-seconds", type=float, default=93600.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    rainfall = scenario.get("rainfall_profile") or {}
    rainfall_total = float(rainfall.get("total_depth_mm", 61.0))
    rainfall_duration_minutes = int(rainfall.get("duration_minutes", 120))
    duration_hours = rainfall_duration_minutes / 60.0
    label = f"{rainfall_total:g} mm / {duration_hours:g} h"
    with netcdf_file(args.sww, "r", mmap=False) as dataset:
        x = np.asarray(dataset.variables["x"].data, dtype=np.float64).copy()
        y = np.asarray(dataset.variables["y"].data, dtype=np.float64).copy()
        volumes = np.asarray(dataset.variables["volumes"].data, dtype=np.int64).copy()
        elevation = np.asarray(dataset.variables["elevation_c"].data, dtype=np.float64).copy()
        stage = np.asarray(dataset.variables["stage_c"].data, dtype=np.float64).copy()
        times = np.asarray(dataset.variables["time"].data, dtype=np.float64).copy()

    if stage.ndim != 2 or stage.shape[0] != times.size:
        raise ValueError("sww_stage_time_shape_invalid")
    if stage.shape[1] != volumes.shape[0] or elevation.size != volumes.shape[0]:
        raise ValueError("sww_triangle_shape_invalid")
    if times.size == 0:
        raise ValueError("sww_has_no_time_frames")

    # The failed run contains 125 m ANUGA vertices and two triangles per
    # 250 m delivery cell.  Aggregate by triangle centroid so the published
    # map has the same 250 m contract as the requested citywide result.
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())
    nx = int(round((xmax - xmin) / CELL_SIZE_M))
    ny = int(round((ymax - ymin) / CELL_SIZE_M))
    if nx <= 0 or ny <= 0:
        raise ValueError("sww_domain_bounds_invalid")

    centroids = np.column_stack((x[volumes].mean(axis=1), y[volumes].mean(axis=1)))
    columns = np.clip(np.floor((centroids[:, 0] - xmin) / CELL_SIZE_M).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((ymax - centroids[:, 1]) / CELL_SIZE_M).astype(int), 0, ny - 1)
    cell_ids = rows * nx + columns
    unique_cells = np.unique(cell_ids)
    depths = np.maximum(stage - elevation[None, :], 0.0)

    maximum = np.zeros(nx * ny, dtype=np.float32)
    final = np.zeros(nx * ny, dtype=np.float32)
    peak_time = np.zeros(nx * ny, dtype=np.float64)
    frame_values: list[np.ndarray] = []
    for time_index in range(times.size):
        values = np.zeros(nx * ny, dtype=np.float32)
        frame = depths[time_index]
        for cell_id in unique_cells:
            members = np.flatnonzero(cell_ids == cell_id)
            values[cell_id] = np.float32(frame[members].max())
        frame_values.append(values)
        maximum = np.maximum(maximum, values)
        if time_index == times.size - 1:
            final = values.copy()
    for cell_id in unique_cells:
        members = np.flatnonzero(cell_ids == cell_id)
        local = depths[:, members].max(axis=1)
        peak_time[cell_id] = float(times[int(np.argmax(local))])

    transformer = Transformer.from_crs(32640, 4326, always_xy=True)

    def polygon_for_cell(cell_id: int) -> list[list[float]]:
        row, col = divmod(int(cell_id), nx)
        corners = [
            (xmin + col * CELL_SIZE_M, ymax - row * CELL_SIZE_M),
            (xmin + (col + 1) * CELL_SIZE_M, ymax - row * CELL_SIZE_M),
            (xmin + (col + 1) * CELL_SIZE_M, ymax - (row + 1) * CELL_SIZE_M),
            (xmin + col * CELL_SIZE_M, ymax - (row + 1) * CELL_SIZE_M),
        ]
        return [
            [float(lon), float(lat)]
            for lon, lat in (transformer.transform(px, py) for px, py in (*corners, corners[0]))
        ]

    def features_for(
        values: np.ndarray,
        *,
        maximum_values: bool,
        time_minutes: float | None = None,
    ) -> list[dict[str, object]]:
        features: list[dict[str, object]] = []
        for cell_id in np.flatnonzero(values >= OUTPUT_DEPTH_THRESHOLD_M):
            value = float(values[cell_id])
            properties: dict[str, object] = {
                "cell_id": int(cell_id),
                "depth_m": value,
                "model_cell_size_m": CELL_SIZE_M,
                "inundation_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
            }
            if maximum_values:
                properties.update(
                    {
                        "maximum_depth_m": value,
                        "maximum_depth_time_seconds": float(peak_time[cell_id]),
                        "maximum_depth_time_minutes": float(peak_time[cell_id] / 60.0),
                        "final_depth_m": float(final[cell_id]),
                    }
                )
            else:
                properties["time_minutes"] = float(time_minutes or 0.0)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [polygon_for_cell(int(cell_id))]},
                    "properties": properties,
                }
            )
        return features

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    maximum_features = features_for(maximum, maximum_values=True)
    maximum_payload = {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_citywide_{rainfall_total:g}mm_{duration_hours:g}h_partial_one_way_maximum_depth",
        "features": maximum_features,
        "metadata": {
            "inundation_extent_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
            "completed_window_count": int(times.size),
            "complete_recession_verified": False,
        },
    }
    dump_json(output / "maximum_depth_wgs84.geojson", maximum_payload)
    extent_payload = {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_citywide_{rainfall_total:g}mm_{duration_hours:g}h_partial_one_way_maximum_inundation_extent",
        "features": [
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "cell_id": feature["properties"]["cell_id"],
                    "maximum_depth_m": feature["properties"]["maximum_depth_m"],
                    "maximum_depth_time_minutes": feature["properties"]["maximum_depth_time_minutes"],
                    "inundation_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
                },
            }
            for feature in maximum_features
        ],
        "metadata": {
            "inundation_extent_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
            "definition": f"cells reaching at least {OUTPUT_DEPTH_THRESHOLD_M:g} m in the {times.size} completed windows",
            "complete_recession_verified": False,
        },
    }
    dump_json(output / "maximum_inundation_extent_wgs84.geojson", extent_payload)

    snapshot_dir = output / "temporal_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots: list[dict[str, object]] = []
    for time_index, timestamp in enumerate(times):
        filename = f"surface_depth_t{time_index:03d}.geojson"
        dump_json(
            snapshot_dir / filename,
            {
                "type": "FeatureCollection",
                "name": f"abu_dhabi_citywide_{rainfall_total:g}mm_{duration_hours:g}h_partial_one_way_time_{time_index:03d}",
                "features": features_for(
                    frame_values[time_index],
                    maximum_values=False,
                    time_minutes=float(timestamp / 60.0),
                ),
                "metadata": {
                    "time_index": int(time_index),
                    "time_seconds": float(timestamp),
                    "time_minutes": float(timestamp / 60.0),
                    "inundation_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
                },
            },
        )
        snapshots.append(
            {
                "index": int(time_index),
                "time_seconds": float(timestamp),
                "time_minutes": float(timestamp / 60.0),
                "path": f"temporal_snapshots/{filename}",
            }
        )
    dump_json(
        snapshot_dir / "manifest.json",
        {
            "schema": "gwm.abu_dhabi_flood.public_citywide_2d_timeseries.v1",
            "snapshots": snapshots,
            "completed_window_count": int(times.size),
            "expected_window_count": int(args.expected_window_count),
            "last_completed_time_seconds": float(times[-1]),
            "target_end_time_seconds": float(args.target_end_time_seconds),
            "missing_tail_seconds": max(float(args.target_end_time_seconds) - float(times[-1]), 0.0),
            "complete_recession_verified": False,
        },
    )

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    coupling = {
        "mode": "one_way_swmm_to_anuga",
        "quality_passed": False,
        "quality_scope": f"{times.size} completed windows only; final {max(float(args.target_end_time_seconds) - float(times[-1]), 0.0):g}-second tail missing",
        "window_count": int(times.size),
        "expected_window_count": int(args.expected_window_count),
        "exchange_window_seconds": 300,
        "dynamic_head_feedback_in_this_run": False,
        "failure": receipt.get("failure"),
        "exchange_quantity": {"swmm_to_anuga": "recorded one-way source term"},
    }
    summary = {
        "schema": "gwm.abu_dhabi_flood.public_citywide_2d_delivery.v2",
        "run_id": receipt.get("run_id") or f"abu-dhabi-citywide-{rainfall_total:g}mm-{duration_hours:g}h-partial-one-way-swmm-to-anuga",
        "scenario_label": label,
        "status": "partial_completed_last_window_missing",
        "solver": "ANUGA 2D",
        "claim_boundary": f"Partial one-way SWMM→ANUGA result: {times.size} of {int(args.expected_window_count)} five-minute windows are available; the final {max(float(args.target_end_time_seconds) - float(times[-1]), 0.0):g}-second tail is missing, so complete recession is not verified.",
        "surface": {
            "product": "customer 5 m DTM input, 250 m ANUGA delivery grid",
            "evidence_class": "customer_dtm_partial_coupled_result",
            "source_resolution_m": [5.0, 5.0],
            "claim_boundary": "partial result only; not calibrated or engineering-admitted",
        },
        "domain": {
            "bounds_epsg32640": [xmin, ymin, xmax, ymax],
            "area_m2": float((xmax - xmin) * (ymax - ymin)),
            "cell_size_m": CELL_SIZE_M,
            "rectangular_cells": int(nx * ny),
            "active_land_cells": int(unique_cells.size),
            "triangle_count": int(volumes.shape[0]),
            "simulation_duration_minutes": float(times[-1] / 60.0),
            "target_simulation_duration_minutes": float(args.target_end_time_seconds / 60.0),
            "output_step_minutes": 5.0,
        },
        "forcing": {
            "source": rainfall.get("source", "customer_requested_parameter_matrix"),
            "total_depth_mm": rainfall_total,
            "duration_minutes": rainfall.get("duration_minutes", 120),
            "temporal_pattern": rainfall.get("temporal_pattern", "uniform"),
            "spatial_mode": rainfall.get("spatial_mode", "uniform"),
        },
        "coupling": coupling,
        "land_water_treatment": {
            "applied": True,
            "application_stage": "before_anuga_domain_construction",
            "active_land_cells": int(unique_cells.size),
            "excluded_permanent_water_cells": int(nx * ny - unique_cells.size),
            "rainfall_applied_to": "active_land_mesh_only",
            "permanent_water_output_policy": "excluded_from_flood_layers",
            "mesh_policy": "land_mask_applied_before_anuga_domain_construction",
            "permanent_water_feature_count": 0,
        },
        "results": {
            "maximum_depth_m": float(maximum.max()),
            "inundated_cells_ge_0_01m": int(np.sum(maximum >= OUTPUT_DEPTH_THRESHOLD_M)),
            "inundated_area_ge_0_01m2": float(np.sum(maximum >= OUTPUT_DEPTH_THRESHOLD_M) * CELL_SIZE_M * CELL_SIZE_M),
            "minimum_published_depth_m": OUTPUT_DEPTH_THRESHOLD_M,
            "maximum_inundation_extent_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
            "final_surface_volume_m3": float(final.sum() * CELL_SIZE_M * CELL_SIZE_M),
        },
        "outputs": {
            "maximum_depth": "maximum_depth_wgs84.geojson",
            "maximum_inundation_extent": "maximum_inundation_extent_wgs84.geojson",
            "timeline_manifest": "temporal_snapshots/manifest.json",
            "native_sww": str(args.sww),
        },
        "delivery": {
            "completed_window_count": int(times.size),
            "expected_window_count": int(args.expected_window_count),
            "last_completed_time_seconds": float(times[-1]),
            "target_end_time_seconds": float(args.target_end_time_seconds),
            "missing_tail_seconds": max(float(args.target_end_time_seconds) - float(times[-1]), 0.0),
            "complete_recession_verified": False,
            "inundation_extent_threshold_m": OUTPUT_DEPTH_THRESHOLD_M,
        },
        "admission": {
            "partial_result_view_allowed": True,
            "complete_recession_verified": False,
            "engineering_prediction_claim_allowed": False,
        },
    }
    dump_json(output / "delivery_summary.json", summary)
    print(json.dumps({"output": str(output), "frames": int(times.size), "maximum_features": len(maximum_features), "maximum_depth_m": float(maximum.max())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
