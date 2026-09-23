#!/usr/bin/env python3
"""Generate private 250 m SWMM--ANUGA physics labels for one ERA5 event.

The customer 5 m DTM is a fixed terrain source.  ANUGA solves on an explicitly
declared 250 m grid; this runner must never be used to describe the result as a
5 m two-dimensional simulation.  The public ERA5 forcing is applied to the
same current-network counterfactual used by the partitioned 1D batch.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPLEMENTATION_ROOT = REPOSITORY_ROOT
DEFAULT_GRID = Path(
    os.environ.get(
        "ABU_DHABI_TERRAIN_GRID_PATH",
        str(REPOSITORY_ROOT / "data/abu_dhabi_hydrodynamics/terrain_grid_250m.npz"),
    )
)
DEFAULT_GRID_ROOT = DEFAULT_GRID.parent
DEFAULT_BASE_SWMM_INPUT = Path(
    os.environ.get(
        "ABU_DHABI_SWMM_FULL_CITY_INPUT",
        str(REPOSITORY_ROOT / "data/abu_dhabi_hydrodynamics/abu_dhabi_city_full_topology.inp"),
    )
)
DEFAULT_SWMM_LIBRARY = Path(
    os.environ.get(
        "ABU_DHABI_SWMM_LIBRARY",
        str(REPOSITORY_ROOT / "external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib"),
    )
)
SCHEMA = "gwm.abu_dhabi_flood.five_year_2d_coupled_label.v1"
WINDOW_SCHEMA = "gwm.abu_dhabi_flood.five_year_2d_coupled_window.v1"
EXTERNAL_HOLDOUT_EVENT_ID = "noaa-isd-ae-202404151200-0327"
JUNCTION_NODE_TYPE = 0
EVENT_SPLITS = frozenset({"train", "validation", "test", "external_test_2024_april", "evaluation_only"})
SWMM_TIME_ALIGNMENT_TOLERANCE_SECONDS = 1.0e-3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(value) + b"\n")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"five_year_2d_module_unavailable:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_module_artifact(flood_package: Path, stem: str) -> tuple[Path, str]:
    """Resolve source first, then interpreter-compatible sourceless bytecode."""

    source = flood_package / f"{stem}.py"
    if source.is_file():
        return source, "source"
    bytecode = flood_package / "__pycache__" / f"{stem}.{sys.implementation.cache_tag}.pyc"
    if bytecode.is_file():
        return bytecode, "bytecode"
    raise ValueError(
        "five_year_2d_verified_coupling_implementation_missing:"
        f"{source}:{bytecode}"
    )


def _load_coupling_modules(implementation_root: Path):
    """Load only the verified coupling modules in the lightweight ANUGA env."""

    root = implementation_root.expanduser().resolve()
    flood_package = root / "data_agent/uwm/abu_dhabi_flood"
    logical_names = (
        "swmm_anuga_coupling",
        "swmm_dynamic_toolkit",
        "swmm_anuga_coupled_runner",
    )
    resolved = tuple(
        _resolve_module_artifact(flood_package, stem) for stem in logical_names
    )
    required = tuple(item[0] for item in resolved)
    if "data_agent" not in sys.modules:
        data_agent = types.ModuleType("data_agent")
        data_agent.__path__ = [str(root / "data_agent")]
        sys.modules["data_agent"] = data_agent
    uwm = types.ModuleType("data_agent.uwm")
    uwm.__path__ = [str(root / "data_agent/uwm")]
    flood = types.ModuleType("data_agent.uwm.abu_dhabi_flood")
    flood.__path__ = [str(flood_package)]
    sys.modules["data_agent.uwm"] = uwm
    sys.modules["data_agent.uwm.abu_dhabi_flood"] = flood
    coupling = _load_module(
        "data_agent.uwm.abu_dhabi_flood.swmm_anuga_coupling", required[0]
    )
    dynamic = _load_module(
        "data_agent.uwm.abu_dhabi_flood.swmm_dynamic_toolkit", required[1]
    )
    runner = _load_module(
        "data_agent.uwm.abu_dhabi_flood.swmm_anuga_coupled_runner", required[2]
    )
    module_sha256 = {
        f"{stem}.py": _sha256(path)
        for stem, path in zip(logical_names, required, strict=True)
    }
    module_artifacts = {
        f"{stem}.py": {
            "artifact_path": str(path),
            "artifact_type": artifact_type,
            "artifact_sha256": module_sha256[f"{stem}.py"],
        }
        for stem, (path, artifact_type) in zip(logical_names, resolved, strict=True)
    }
    return coupling, dynamic, runner, module_sha256, module_artifacts


def _read_forcing(path: Path) -> dict[str, Any]:
    try:
        forcing = json.loads(path.read_text(encoding="utf-8"))
        event_id = str(forcing["event_id"])
        start = datetime.fromisoformat(str(forcing["start_utc"]).replace("Z", "+00:00"))
        hourly_mm = tuple(float(value) for value in forcing["hourly_precipitation_mm"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("five_year_2d_forcing_invalid") from exc
    if start.tzinfo is None or not hourly_mm or any(
        not math.isfinite(value) or value < 0.0 for value in hourly_mm
    ):
        raise ValueError("five_year_2d_forcing_invalid")
    source_path = str(forcing.get("source_path", ""))
    source_sha256 = str(forcing.get("source_sha256", ""))
    if not source_sha256 and source_path:
        candidate = Path(source_path)
        if candidate.is_file():
            source_sha256 = _sha256(candidate)
    return {
        "event_id": event_id,
        "start_utc": start.astimezone(timezone.utc).replace(tzinfo=None),
        "hourly_precipitation_mm": hourly_mm,
        "source": str(forcing.get("source", "ECMWF ERA5 hourly event grid")),
        "source_path": source_path,
        "source_sha256": source_sha256,
        "support_point_count": forcing.get("support_point_count"),
        "aggregation": str(forcing.get("aggregation", "mean of nine spatial support points")),
    }


def _normalize_swmm_elapsed_seconds(
    raw_elapsed_seconds: float,
    *,
    expected_end_seconds: float,
    duration_seconds: float,
    tolerance_seconds: float = SWMM_TIME_ALIGNMENT_TOLERANCE_SECONDS,
) -> tuple[float, str]:
    """Resolve SWMM's terminal zero sentinel without accepting early termination."""

    raw = float(raw_elapsed_seconds)
    expected = float(expected_end_seconds)
    duration = float(duration_seconds)
    tolerance = float(tolerance_seconds)
    if not all(math.isfinite(value) for value in (raw, expected, duration, tolerance)) or tolerance < 0.0:
        raise ValueError("five_year_2d_swmm_window_alignment_inputs_invalid")
    if abs(raw - expected) <= tolerance:
        return expected, "absolute_elapsed"
    if abs(expected - duration) <= tolerance and abs(raw) <= tolerance:
        # EPA SWMM 5.2.4 returns zero when swmm_stride reaches TotalDuration.
        return expected, "terminal_zero_sentinel"
    raise RuntimeError(
        "five_year_2d_swmm_window_alignment_failed:"
        f"raw_elapsed_seconds={raw:.9f}:"
        f"expected_end_seconds={expected:.9f}:"
        f"duration_seconds={duration:.9f}:"
        f"tolerance_seconds={tolerance:.9f}"
    )


def _section_replace(text: str, replacements: dict[str, list[str]]) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    seen: set[str] = set()
    while index < len(lines):
        line = lines[index]
        if not (line.startswith("[") and line.endswith("]")):
            output.append(line)
            index += 1
            continue
        name = line[1:-1].upper()
        if name not in replacements:
            output.append(line)
            index += 1
            continue
        seen.add(name)
        output.append(line)
        output.extend(replacements[name])
        index += 1
        while index < len(lines) and not (
            lines[index].startswith("[") and lines[index].endswith("]")
        ):
            index += 1
    if seen != set(replacements):
        missing = ",".join(sorted(set(replacements) - seen))
        raise ValueError(f"five_year_2d_base_input_sections_missing:{missing}")
    return "\n".join(output).rstrip() + "\n"


def _render_event_input(base_input: Path, forcing: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    start = forcing["start_utc"]
    hourly_mm = forcing["hourly_precipitation_mm"]
    end = start + timedelta(hours=len(hourly_mm))
    options = [
        "FLOW_UNITS  CMS",
        "INFILTRATION  HORTON",
        "FLOW_ROUTING  DYNWAVE",
        "LINK_OFFSETS  DEPTH",
        "MIN_SLOPE  0",
        "ALLOW_PONDING  NO",
        "SKIP_STEADY_STATE  NO",
        f"START_DATE  {start.strftime('%m/%d/%Y')}",
        f"START_TIME  {start.strftime('%H:%M:%S')}",
        f"REPORT_START_DATE  {start.strftime('%m/%d/%Y')}",
        f"REPORT_START_TIME  {start.strftime('%H:%M:%S')}",
        f"END_DATE  {end.strftime('%m/%d/%Y')}",
        f"END_TIME  {end.strftime('%H:%M:%S')}",
        "SWEEP_START  01/01",
        "SWEEP_END  12/31",
        "DRY_DAYS  0",
        "REPORT_STEP  01:00:00",
        "WET_STEP  00:05:00",
        "DRY_STEP  01:00:00",
        "ROUTING_STEP  00:05:00",
    ]
    rows = []
    for index, depth_mm in enumerate(hourly_mm):
        timestamp = start + timedelta(hours=index)
        rows.append(
            "TS_ERA5  "
            f"{timestamp.strftime('%m/%d/%Y')}  {timestamp.strftime('%H:%M')}  {depth_mm:.8f}"
        )
    rows.append(
        "TS_ERA5  "
        f"{end.strftime('%m/%d/%Y')}  {end.strftime('%H:%M')}  0.00000000"
    )
    try:
        base = base_input.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("five_year_2d_base_swmm_input_invalid") from exc
    rendered = _section_replace(
        base,
        {
            "OPTIONS": options,
            "RAINGAGES": ["RG_INTERACTIVE  INTENSITY  01:00  1.0  TIMESERIES  TS_ERA5"],
            "TIMESERIES": rows,
            "REPORT": [
                "INPUT  NO",
                "CONTROLS  NO",
                "SUBCATCHMENTS  NONE",
                "NODES  NONE",
                "LINKS  NONE",
            ],
        },
    )
    return rendered, {
        "base_input_path": str(base_input),
        "base_input_sha256": _sha256(base_input),
        "event_input_sha256": hashlib.sha256(rendered.encode("ascii")).hexdigest(),
        "rainfall_series_id": "TS_ERA5",
        "routing_method": "DYNWAVE",
        "routing_step_seconds": 300,
        "report_output_policy": "native_report_and_binary_output_discarded_after_success",
    }


def _parse_subcatchment_area_by_node(base_input: Path) -> dict[str, float]:
    section = ""
    result: dict[str, float] = {}
    for raw in base_input.read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].upper()
            continue
        if section != "SUBCATCHMENTS" or not line or line.startswith(";"):
            continue
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("five_year_2d_subcatchment_record_invalid")
        try:
            area_m2 = float(fields[3]) * 10_000.0
        except ValueError as exc:
            raise ValueError("five_year_2d_subcatchment_area_invalid") from exc
        if not math.isfinite(area_m2) or area_m2 <= 0.0:
            raise ValueError("five_year_2d_subcatchment_area_invalid")
        result[fields[2]] = result.get(fields[2], 0.0) + area_m2
    if not result:
        raise ValueError("five_year_2d_subcatchments_missing")
    return result


def _build_surface(
    grid_path: Path,
    runner,
    output_dir: Path,
    *,
    window_seconds: int,
    duration_seconds: int,
    shallow_water_regularization_depth_m: float,
    shallow_water_maximum_speed_mps: float,
):
    import anuga

    with np.load(grid_path) as grid:
        values = np.asarray(grid["values"], dtype=np.float64).copy()
        x = np.asarray(grid["x"], dtype=np.float64).copy()
        y = np.asarray(grid["y"], dtype=np.float64).copy()
        land_mask = np.asarray(grid["land_mask"], dtype=bool).copy()
    ny, nx = values.shape[0] - 1, values.shape[1] - 1
    if nx < 1 or ny < 1 or land_mask.shape != (ny, nx):
        raise ValueError("five_year_2d_grid_shape_invalid")
    cell_size = float((x[-1] - x[0]) / nx)
    if not math.isfinite(cell_size) or cell_size <= 0.0 or not np.allclose(np.diff(x), cell_size) or not np.allclose(np.diff(y), -cell_size):
        raise ValueError("five_year_2d_grid_spacing_invalid")

    def topography(xp, yp):
        xp = np.asarray(xp, dtype=float)
        yp = np.asarray(yp, dtype=float)
        column = np.clip(np.floor((xp - x[0]) / cell_size).astype(int), 0, nx - 1)
        row = np.clip(np.floor((y[0] - yp) / cell_size).astype(int), 0, ny - 1)
        x_weight = np.clip((xp - x[column]) / cell_size, 0.0, 1.0)
        y_weight = np.clip((y[0] - yp) / cell_size, 0.0, 1.0)
        north_west = values[row, column]
        north_east = values[row, column + 1]
        south_west = values[row + 1, column]
        south_east = values[row + 1, column + 1]
        return (
            north_west * (1.0 - x_weight) * (1.0 - y_weight)
            + north_east * x_weight * (1.0 - y_weight)
            + south_west * (1.0 - x_weight) * y_weight
            + south_east * x_weight * y_weight
        )

    domain = anuga.rectangular_cross_domain(
        nx,
        ny,
        len1=float(x[-1] - x[0]),
        len2=float(y[0] - y[-1]),
        origin=(float(x[0]), float(y[-1])),
    )
    domain.set_name("abu_dhabi_five_year_2d_coupled")
    domain.set_datadir(str(output_dir))
    domain.set_store(False)
    domain.set_minimum_allowed_height(shallow_water_regularization_depth_m)
    domain.set_maximum_allowed_speed(shallow_water_maximum_speed_mps)
    domain.set_quantity("elevation", topography)
    domain.set_quantity("friction", 0.035)
    domain.set_quantity("stage", topography)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary({"left": boundary, "right": boundary, "top": boundary, "bottom": boundary})
    source_operator = anuga.Rate_operator(domain, rate=0.0, label="era5_and_swmm_exchange")
    centroids = np.asarray(domain.centroid_coordinates, dtype=np.float64)
    columns = np.clip(np.floor((centroids[:, 0] - x[0]) / cell_size).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((y[0] - centroids[:, 1]) / cell_size).astype(int), 0, ny - 1)
    triangle_to_cell = rows * nx + columns
    cell_count = nx * ny
    triangle_elevation = np.asarray(domain.get_quantity("elevation").centroid_values, dtype=np.float64)
    elevation_by_cell = np.zeros(cell_count, dtype=np.float64)
    counts = np.zeros(cell_count, dtype=np.int64)
    np.add.at(elevation_by_cell, triangle_to_cell, triangle_elevation)
    np.add.at(counts, triangle_to_cell, 1)
    elevation_by_cell /= np.maximum(counts, 1)
    surface = runner.AnugaSurfaceAdapter(
        domain,
        source_operator,
        triangle_to_cell,
        np.full(cell_count, cell_size * cell_size, dtype=np.float64),
        yieldstep_seconds=window_seconds,
        finaltime_seconds=duration_seconds,
    )
    return surface, {
        "x": x,
        "y": y,
        "land_mask": land_mask.reshape(-1),
        "cell_size_m": cell_size,
        "cell_count": cell_count,
        "elevation_by_cell_m": elevation_by_cell,
        "active_land_cell_count": int(land_mask.sum()),
        "shallow_water_regularization_depth_m": shallow_water_regularization_depth_m,
        "shallow_water_maximum_speed_mps": shallow_water_maximum_speed_mps,
    }


def _load_bindings(grid_root: Path, runner, *, opening_area_m2: float, maximum_exchange_rate_m3s: float):
    metadata = json.loads((grid_root / "grid_metadata.json").read_text(encoding="utf-8"))
    relative = str(metadata["interface_candidates"]["relative_path"])
    bindings = []
    with gzip.open(grid_root / relative, "rt", encoding="utf-8") as handle:
        for raw in handle:
            record = json.loads(raw)
            bindings.append(
                runner.CouplingInterfaceBinding(
                    interface_id=str(record["interface_id"]),
                    swmm_node_id=str(record["swmm_node_id"]),
                    anuga_cell_index=int(record["anuga_cell_index"]),
                    inlet_elevation_m=float(record["inlet_elevation_m"]),
                    surface_elevation_m=float(record["surface_elevation_m"]),
                    swmm_rim_elevation_m=float(record["swmm_rim_elevation_m"]),
                    head_exchange_parameters=runner.HeadExchangeParameters(
                        opening_area_m2=opening_area_m2,
                        discharge_coefficient=0.61,
                        maximum_exchange_rate_m3s=maximum_exchange_rate_m3s,
                    ),
                    provenance=str(record["provenance"]),
                )
            )
    if not bindings:
        raise ValueError("five_year_2d_interface_bindings_missing")
    return tuple(bindings), metadata


def _resolve_bindings(session, bindings):
    resolved = []
    for binding in bindings:
        node_index = session.node_index(binding.swmm_node_id)
        geometry = session.node_static_geometry(node_index)
        if geometry["node_type"] != JUNCTION_NODE_TYPE:
            raise ValueError("five_year_2d_non_junction_interface")
        if binding.swmm_rim_elevation_m is None or abs(geometry["rim_elevation_m"] - binding.swmm_rim_elevation_m) > 1.0e-3:
            raise ValueError("five_year_2d_swmm_rim_mismatch")
        resolved.append(replace(binding, swmm_node_index=node_index))
    return tuple(resolved)


def _surface_rainfall_fraction(
    bindings,
    subcatchment_area_by_node: dict[str, float],
    grid: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    covered = np.zeros(grid["cell_count"], dtype=np.float64)
    bound_nodes = {binding.swmm_node_id: binding for binding in bindings}
    missing = sorted(set(subcatchment_area_by_node) - set(bound_nodes))
    for node_id, area_m2 in subcatchment_area_by_node.items():
        if node_id in missing:
            continue
        covered[bound_nodes[node_id].anuga_cell_index] += area_m2
    fraction = np.clip(1.0 - covered / (grid["cell_size_m"] ** 2), 0.0, 1.0)
    fraction[~grid["land_mask"]] = 0.0
    return fraction, {
        "method": "per_250m_cell_1_minus_SWMM_subcatchment_area_over_cell_area_clamped",
        "subcatchment_count": len(subcatchment_area_by_node),
        "modeled_subcatchment_area_m2": float(sum(subcatchment_area_by_node.values())),
        "subcatchments_without_land_surface_interface_count": len(missing),
        "subcatchment_area_without_land_surface_interface_m2": float(
            sum(subcatchment_area_by_node[node_id] for node_id in missing)
        ),
        "subcatchments_without_land_surface_interface_policy": "rainfall_remains_in_SWMM_only; no_land_2d_direct_rain_or_exchange_is_inferred_for_public_water_or_uncovered_cells",
        "cells_with_clamped_zero_direct_rain_fraction": int(np.sum((covered >= grid["cell_size_m"] ** 2) & grid["land_mask"])),
        "land_mask_policy": "ESA_WorldCover_2021_permanent_water_or_uncovered_cells_receive_no_direct_rain_and_are_excluded_from_labels",
    }


def _write_bindings(path: Path, bindings) -> dict[str, Any]:
    digest = hashlib.sha256()
    with gzip.open(path, "wb") as handle:
        for binding in bindings:
            line = _canonical_json(binding.as_dict()) + b"\n"
            digest.update(line)
            handle.write(line)
    return {
        "relative_path": path.name,
        "format": "jsonl-gzip",
        "record_count": len(bindings),
        "canonical_jsonl_sha256": digest.hexdigest(),
        "compressed_size_bytes": path.stat().st_size,
    }


def _run_coupling(
    session,
    surface,
    runner,
    bindings,
    forcing: dict[str, Any],
    grid: dict[str, Any],
    surface_fraction: np.ndarray,
    *,
    window_seconds: int,
) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    hourly = forcing["hourly_precipitation_mm"]
    duration_seconds = len(hourly) * 3600
    if duration_seconds % window_seconds:
        raise ValueError("five_year_2d_duration_window_mismatch")
    current_surface = surface.snapshot()
    initial_heads = [
        float(session.node_state(binding.swmm_node_index)["head_m"])
        for binding in bindings
    ]
    initial_stages = [
        float(current_surface.stage_by_cell_m[binding.anuga_cell_index])
        for binding in bindings
    ]
    pending_exchange = [
        -rate
        for rate in runner._aggregate_bounded_head_rates(
            bindings,
            initial_heads,
            initial_stages,
            current_surface.available_volume_by_cell_m3 or None,
            window_seconds,
        )
    ]
    depth_frames = [
        np.maximum(
            np.asarray(current_surface.stage_by_cell_m, dtype=np.float64)
            - grid["elevation_by_cell_m"],
            0.0,
        ).astype(np.float32)
    ]
    records: list[dict[str, Any]] = []
    for index in range(duration_seconds // window_seconds):
        hour_index = min(len(hourly) - 1, (index * window_seconds) // 3600)
        rainfall_m3s = (
            float(hourly[hour_index])
            * 0.001
            / 3600.0
            * (grid["cell_size_m"] ** 2)
            * surface_fraction
        )
        node_storage_start = float(session.node_storage_m3())
        network_storage_start = node_storage_start + float(session.link_storage_m3())
        for binding, rate in zip(bindings, pending_exchange, strict=True):
            session.set_node_surface_exchange_flow(binding.swmm_node_index, rate)
        raw_swmm_elapsed = float(session.stride(window_seconds))
        expected_end = float((index + 1) * window_seconds)
        effective_swmm_elapsed, swmm_elapsed_mode = _normalize_swmm_elapsed_seconds(
            raw_swmm_elapsed,
            expected_end_seconds=expected_end,
            duration_seconds=float(duration_seconds),
        )
        heads: list[float] = []
        overflow: list[float] = []
        for binding in bindings:
            state = session.node_state(binding.swmm_node_index)
            heads.append(float(state["head_m"]))
            overflow.append(max(0.0, float(state["overflow_or_flooding_m3s"])))
        source = rainfall_m3s.copy()
        overflow_volume = 0.0
        head_to_surface_volume = 0.0
        surface_to_swmm_volume = 0.0
        for binding_index, binding in enumerate(bindings):
            head_rate = -pending_exchange[binding_index]
            source[binding.anuga_cell_index] += overflow[binding_index] + head_rate
            overflow_volume += overflow[binding_index] * window_seconds
            head_to_surface_volume += max(0.0, head_rate) * window_seconds
            surface_to_swmm_volume += max(0.0, -head_rate) * window_seconds
        state = surface.advance(window_seconds, source)
        node_storage_end = float(session.node_storage_m3())
        network_storage_end = node_storage_end + float(session.link_storage_m3())
        next_stages = [float(state.stage_by_cell_m[binding.anuga_cell_index]) for binding in bindings]
        next_rates = runner._aggregate_bounded_head_rates(
            bindings,
            heads,
            next_stages,
            state.available_volume_by_cell_m3 or None,
            window_seconds,
        )
        pending_exchange = [-rate for rate in next_rates]
        rainfall_volume = float(rainfall_m3s.sum() * window_seconds)
        expected_source = rainfall_volume + overflow_volume + head_to_surface_volume - surface_to_swmm_volume
        applied_source = (
            expected_source
            if state.applied_source_volume_m3 is None
            else float(state.applied_source_volume_m3)
        )
        external_outflow = float(
            state.external_outflow_m3 + state.boundary_outflow_m3 + state.infiltration_loss_m3
        )
        residual = float(state.storage_change_m3 - applied_source + external_outflow)
        application_difference = float(applied_source - expected_source)
        scale = max(
            abs(expected_source),
            abs(applied_source),
            overflow_volume + head_to_surface_volume + surface_to_swmm_volume + rainfall_volume,
            1.0,
        )
        record = {
            "schema": WINDOW_SCHEMA,
            "window_index": index,
            "start_seconds": float(index * window_seconds),
            "end_seconds": expected_end,
            "swmm_raw_elapsed_seconds": raw_swmm_elapsed,
            "swmm_effective_elapsed_seconds": effective_swmm_elapsed,
            "swmm_elapsed_report_mode": swmm_elapsed_mode,
            "swmm_time_alignment_tolerance_seconds": SWMM_TIME_ALIGNMENT_TOLERANCE_SECONDS,
            "era5_hour_index": int(hour_index),
            "era5_hourly_precipitation_mm": float(hourly[hour_index]),
            "surface_direct_rainfall_m3": rainfall_volume,
            "swmm_overflow_to_surface_m3": overflow_volume,
            "head_exchange_swmm_to_surface_m3": head_to_surface_volume,
            "head_exchange_surface_to_swmm_m3": surface_to_swmm_volume,
            "surface_storage_start_m3": float(current_surface.storage_end_m3),
            "surface_storage_end_m3": float(state.storage_end_m3),
            "surface_external_outflow_m3": external_outflow,
            "surface_mass_balance_residual_m3": residual,
            "anuga_requested_signed_source_m3": expected_source,
            "anuga_applied_signed_source_m3": applied_source,
            "exchange_application_difference_m3": application_difference,
            "exchange_application_relative_difference": abs(application_difference) / scale,
            "swmm_node_storage_start_m3": node_storage_start,
            "swmm_node_storage_end_m3": node_storage_end,
            "swmm_node_plus_link_storage_start_m3": network_storage_start,
            "swmm_node_plus_link_storage_end_m3": network_storage_end,
            "quality_passed": abs(residual) <= 1.0e-3 and abs(application_difference) / scale <= 5.0e-3,
        }
        records.append(record)
        if not record["quality_passed"]:
            raise RuntimeError(f"five_year_2d_surface_quality_gate_failed_window_{index}")
        current_surface = state
        depth_frames.append(
            np.maximum(
                np.asarray(state.stage_by_cell_m, dtype=np.float64) - grid["elevation_by_cell_m"],
                0.0,
            ).astype(np.float32)
        )
        if (index + 1) % 12 == 0 or index + 1 == len(hourly) * 3600 // window_seconds:
            print(
                f"window {index + 1}/{len(hourly) * 3600 // window_seconds} "
                f"hour {hour_index + 1}/{len(hourly)} residual={residual:.3e}",
                flush=True,
            )
    return records, np.asarray(depth_frames, dtype=np.float32), np.arange(
        len(depth_frames), dtype=np.int64
    ) * window_seconds


def _write_label_arrays(output: Path, depths: np.ndarray, times: np.ndarray, grid: dict[str, Any], fraction: np.ndarray) -> dict[str, Any]:
    land = np.asarray(grid["land_mask"], dtype=bool)
    depths[:, ~land] = 0.0
    maximum = np.asarray(depths.max(axis=0), dtype=np.float32)
    peak_index = np.asarray(depths.argmax(axis=0), dtype=np.int32)
    np.savez_compressed(
        output / "surface_depth_labels_250m.npz",
        depth_m=depths,
        time_seconds=times,
        x=grid["x"],
        y=grid["y"],
        land_mask=land.reshape(len(grid["y"]) - 1, len(grid["x"]) - 1),
        surface_rainfall_fraction_by_cell=fraction.reshape(len(grid["y"]) - 1, len(grid["x"]) - 1),
    )
    np.savez_compressed(
        output / "maximum_depth_250m.npz",
        maximum_depth_m=maximum.reshape(len(grid["y"]) - 1, len(grid["x"]) - 1),
        peak_time_seconds=times[peak_index].reshape(len(grid["y"]) - 1, len(grid["x"]) - 1),
    )
    return {
        "depth_labels": "surface_depth_labels_250m.npz",
        "maximum_depth": "maximum_depth_250m.npz",
        "time_frame_count": int(depths.shape[0]),
        "cell_count": int(depths.shape[1]),
        "maximum_depth_m": float(maximum[land].max(initial=0.0)),
        "inundated_area_ge_0_01m2": float(np.sum((maximum >= 0.01) & land) * grid["cell_size_m"] ** 2),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    forcing = _read_forcing(args.forcing)
    event_split = args.event_split or ("train" if args.training else "evaluation_only")
    if event_split not in EVENT_SPLITS:
        raise ValueError("five_year_2d_event_split_invalid")
    if args.training != (event_split == "train"):
        raise ValueError("five_year_2d_training_flag_and_split_mismatch")
    external_holdout = forcing["event_id"] == EXTERNAL_HOLDOUT_EVENT_ID
    if args.training and external_holdout:
        raise ValueError("five_year_2d_external_holdout_cannot_generate_training_label")
    if external_holdout != (event_split == "external_test_2024_april"):
        raise ValueError("five_year_2d_external_holdout_split_mismatch")
    if args.window_seconds != 300:
        raise ValueError("five_year_2d_window_seconds_must_be_300")
    if (
        not math.isfinite(args.shallow_water_regularization_depth_m)
        or args.shallow_water_regularization_depth_m <= 0.0
        or not math.isfinite(args.shallow_water_maximum_speed_mps)
        or args.shallow_water_maximum_speed_mps <= 0.0
    ):
        raise ValueError("five_year_2d_shallow_water_regularization_invalid")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "run_receipt.json"
    runner_sha256 = _sha256(Path(__file__))
    if receipt_path.is_file():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "completed"
            and existing.get("quality_passed") is True
            and existing.get("implementation", {}).get("runner_sha256") == runner_sha256
        ):
            return existing
    (
        _,
        dynamic,
        runner,
        implementation_hashes,
        implementation_artifacts,
    ) = _load_coupling_modules(args.implementation_root)
    duration_seconds = len(forcing["hourly_precipitation_mm"]) * 3600
    surface, grid = _build_surface(
        args.grid.expanduser().resolve(), runner, output,
        window_seconds=args.window_seconds,
        duration_seconds=duration_seconds,
        shallow_water_regularization_depth_m=args.shallow_water_regularization_depth_m,
        shallow_water_maximum_speed_mps=args.shallow_water_maximum_speed_mps,
    )
    bindings, grid_metadata = _load_bindings(
        args.grid.parent, runner,
        opening_area_m2=args.opening_area_m2,
        maximum_exchange_rate_m3s=args.maximum_exchange_rate_m3s,
    )
    fraction, fraction_metadata = _surface_rainfall_fraction(
        bindings, _parse_subcatchment_area_by_node(args.base_swmm_input), grid
    )
    input_text, input_metadata = _render_event_input(args.base_swmm_input, forcing)
    binding_manifest = _write_bindings(output / "interface_bindings.jsonl.gz", bindings)
    try:
        with tempfile.TemporaryDirectory(prefix=f"abu-dhabi-2d-{forcing['event_id']}-") as temp:
            temporary = Path(temp)
            input_path = temporary / "event.inp"
            input_path.write_text(input_text, encoding="ascii")
            session = dynamic.SwmmDynamicSession(
                args.swmm_library,
                input_path,
                Path("/dev/null"),
                temporary / "event.out",
                save_results=False,
            )
            with session:
                resolved = _resolve_bindings(session, bindings)
                records, depths, times = _run_coupling(
                    session, surface, runner, resolved, forcing, grid, fraction,
                    window_seconds=args.window_seconds,
                )
        outputs = _write_label_arrays(output, depths, times, grid, fraction)
        quality_passed = all(record["quality_passed"] for record in records)
        receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "completed",
            "quality_passed": quality_passed,
            "event": {
                "event_id": forcing["event_id"],
                "split": event_split,
                "external_holdout": external_holdout,
                "start_utc": forcing["start_utc"].isoformat() + "Z",
                "duration_hours": len(forcing["hourly_precipitation_mm"]),
            },
            "forcing": {
                "source": forcing["source"],
                "source_path": forcing["source_path"],
                "source_sha256": forcing["source_sha256"],
                "support_point_count": forcing["support_point_count"],
                "aggregation": forcing["aggregation"],
                "total_precipitation_mm": float(sum(forcing["hourly_precipitation_mm"])),
                "peak_hourly_precipitation_mm": float(max(forcing["hourly_precipitation_mm"])),
            },
            "terrain": {
                "customer_dtm_path": str(args.dtm),
                "customer_dtm_sha256": _sha256(args.dtm),
                "customer_dtm_source_resolution_m": 5.0,
                "anuga_computation_cell_size_m": grid["cell_size_m"],
                "shallow_water_regularization": {
                    "minimum_allowed_height_m": grid["shallow_water_regularization_depth_m"],
                    "maximum_allowed_speed_mps_when_shallower_than_threshold": grid["shallow_water_maximum_speed_mps"],
                },
                "city_scale_5m_direct_2d_solution_claimed": False,
                "grid_metadata_sha256": _sha256(args.grid.parent / "grid_metadata.json"),
            },
            "network": {
                "base_swmm_input": input_metadata,
                "cross_partition_edges_preserved": True,
                "network_state_assumption": "current_network_held_fixed_for_five_year_rainfall_counterfactual",
            },
            "coupling": {
                "solver": "EPA SWMM 5.2.4 dynamic API + ANUGA 2D synchronous explicit exchange",
                "window_seconds": args.window_seconds,
                "interface_bindings": binding_manifest,
                "interface_count": len(resolved),
                "head_exchange": {
                    "opening_area_m2": args.opening_area_m2,
                    "maximum_exchange_rate_m3s": args.maximum_exchange_rate_m3s,
                    "scheme": "surface_stage_and_swmm_head_one_window_explicit_lag",
                },
                "surface_rainfall": fraction_metadata,
                "quality_scope": "surface_mass_balance_and_exchange_source_application_per_window; SWMM_node_plus_link_storage_recorded_but_not_complete_system_mass_balance",
                "windows": records,
            },
            "outputs": outputs,
            "runtime_storage_policy": {
                "temporary_event_swmm_input": "deleted_on_exit",
                "temporary_native_swmm_out_and_report": "deleted_on_exit",
                "retained": ["compressed_250m_depth_labels", "maximum_depth", "coupling_receipt", "interface_binding_manifest"],
                "native_anuga_sww": "not_written; every 300s water-depth frame is retained directly in compressed_labels",
            },
            "implementation": {
                "verified_implementation_root": str(args.implementation_root),
                "module_sha256": implementation_hashes,
                "module_artifacts": implementation_artifacts,
                "runner_sha256": runner_sha256,
            },
            "claim_boundary": [
                "candidate physics label generated from current customer network and public ERA5 forcing, not an observed historical inundation label",
                "customer 5m DTM is the fixed terrain source; 250m is the declared ANUGA computation grid",
                "ESA WorldCover permanent-water masking remains a public proxy limitation until customer shoreline or water polygons are supplied",
                "unverified inlet area, catchment, roughness, boundary, tide, pump, blockage and vertical-datum assumptions remain outside engineering admission",
            ],
        }
        receipt["receipt_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        _write_json(receipt_path, receipt)
        return receipt
    except Exception as exc:
        failed = {
            "schema": SCHEMA,
            "status": "failed",
            "quality_passed": False,
            "event_id": forcing["event_id"],
            "failure_type": type(exc).__name__,
            "failure_reason": str(exc),
        }
        _write_json(receipt_path, failed)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    parser.add_argument(
        "--dtm",
        type=Path,
        default=Path(
            os.environ.get(
                "ABU_DHABI_CUSTOMER_DTM_PATH",
                str(REPOSITORY_ROOT / "data/abu_dhabi_hydrodynamics/AUH_DTM_5m_Z40.TIF"),
            )
        ),
    )
    parser.add_argument("--base-swmm-input", type=Path, default=DEFAULT_BASE_SWMM_INPUT)
    parser.add_argument("--swmm-library", type=Path, default=DEFAULT_SWMM_LIBRARY)
    parser.add_argument("--implementation-root", type=Path, default=DEFAULT_IMPLEMENTATION_ROOT)
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument("--opening-area-m2", type=float, default=0.5)
    parser.add_argument("--maximum-exchange-rate-m3s", type=float, default=5.0)
    parser.add_argument("--shallow-water-regularization-depth-m", type=float, default=0.01)
    parser.add_argument("--shallow-water-maximum-speed-mps", type=float, default=10.0)
    parser.add_argument("--training", action="store_true")
    parser.add_argument("--event-split", choices=sorted(EVENT_SPLITS))
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({
        "status": result["status"],
        "event_id": result["event"]["event_id"],
        "quality_passed": result["quality_passed"],
        "maximum_depth_m": result["outputs"]["maximum_depth_m"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
