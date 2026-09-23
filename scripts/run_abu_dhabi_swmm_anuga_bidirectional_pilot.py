#!/usr/bin/env python3
"""Run a short customer-data SWMM--ANUGA bidirectional pilot.

The command is intended to be executed with the repository's ANUGA Python
environment.  It reads a runtime NPZ grid prepared by
``prepare_abu_dhabi_bidirectional_pilot_grid.py`` and never modifies the
customer SWMM input or DTM.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FLOOD_PACKAGE = ROOT / "data_agent/uwm/abu_dhabi_flood"


def ensure_runtime_directories() -> None:
    for variable, fallback in (
        ("HOME", "/tmp/hydro-home"),
        ("MPLCONFIGDIR", "/tmp/matplotlib"),
        ("XDG_CACHE_HOME", "/tmp/cache"),
    ):
        Path(os.environ.get(variable, fallback)).mkdir(parents=True, exist_ok=True)


def _load_flood_modules():
    # Loading data_agent.uwm normally imports unrelated livability modules that
    # are not installed in the small ANUGA runtime.  Register a narrow package
    # shim and load only the coupling modules needed by this pilot.
    if "data_agent" not in sys.modules:
        data_agent = types.ModuleType("data_agent")
        data_agent.__path__ = [str(ROOT / "data_agent")]
        sys.modules["data_agent"] = data_agent
    uwm = types.ModuleType("data_agent.uwm")
    uwm.__path__ = [str(ROOT / "data_agent/uwm")]
    flood = types.ModuleType("data_agent.uwm.abu_dhabi_flood")
    flood.__path__ = [str(FLOOD_PACKAGE)]
    sys.modules["data_agent.uwm"] = uwm
    sys.modules["data_agent.uwm.abu_dhabi_flood"] = flood

    def load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"pilot_module_unavailable:{name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    coupling = load(
        "data_agent.uwm.abu_dhabi_flood.swmm_anuga_coupling",
        FLOOD_PACKAGE / "swmm_anuga_coupling.py",
    )
    dynamic = load(
        "data_agent.uwm.abu_dhabi_flood.swmm_dynamic_toolkit",
        FLOOD_PACKAGE / "swmm_dynamic_toolkit.py",
    )
    runner = load(
        "data_agent.uwm.abu_dhabi_flood.swmm_anuga_coupled_runner",
        FLOOD_PACKAGE / "swmm_anuga_coupled_runner.py",
    )
    return coupling, dynamic, runner


def parse_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    section = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.upper()
            continue
        if section != "[COORDINATES]" or not line or line.startswith(";"):
            continue
        values = line.split()
        if len(values) >= 3:
            try:
                result[values[0]] = (float(values[1]), float(values[2]))
            except ValueError:
                pass
    return result


class RecordingSurfaceAdapter:
    """Record compact cell states while delegating to the real ANUGA adapter."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.cell_count = adapter.cell_count
        self.states = []

    def snapshot(self):
        return self.adapter.snapshot()

    def advance(self, window_seconds, source_rate_by_cell_m3s):
        state = self.adapter.advance(window_seconds, source_rate_by_cell_m3s)
        self.states.append(state)
        return state


def build_surface(
    grid_path: Path,
    runner,
    output_dir: Path,
    *,
    window_seconds: int,
    duration_seconds: int,
    friction: float,
    initial_depth_m: float,
):
    import anuga

    with np.load(grid_path) as grid:
        values = np.asarray(grid["values"], dtype=float).copy()
        x = np.asarray(grid["x"], dtype=float).copy()
        y = np.asarray(grid["y"], dtype=float).copy()
        land_mask = (
            np.asarray(grid["land_mask"], dtype=bool).copy()
            if "land_mask" in grid.files
            else np.ones((values.shape[0] - 1, values.shape[1] - 1), dtype=bool)
        )
    ny, nx = values.shape[0] - 1, values.shape[1] - 1
    dx = float((x[-1] - x[0]) / nx)
    if values.shape != (len(y), len(x)) or land_mask.shape != (ny, nx):
        raise ValueError("pilot_grid_shape_invalid")
    if dx <= 0.0 or not np.all(np.diff(x) > 0.0) or not np.all(np.diff(y) < 0.0):
        raise ValueError("pilot_grid_coordinates_invalid")

    def topography(xp, yp):
        xp = np.asarray(xp, dtype=float)
        yp = np.asarray(yp, dtype=float)
        col = np.clip(np.floor((xp - x[0]) / dx).astype(int), 0, nx - 1)
        row = np.clip(np.floor((y[0] - yp) / dx).astype(int), 0, ny - 1)
        xw = np.clip((xp - x[col]) / dx, 0.0, 1.0)
        yw = np.clip((y[row] - yp) / dx, 0.0, 1.0)
        nw = values[row, col]
        ne = values[row, col + 1]
        sw = values[row + 1, col]
        se = values[row + 1, col + 1]
        return nw * (1.0 - xw) * (1.0 - yw) + ne * xw * (1.0 - yw) + sw * (1.0 - xw) * yw + se * xw * yw

    domain = anuga.rectangular_cross_domain(
        nx,
        ny,
        len1=float(x[-1] - x[0]),
        len2=float(y[0] - y[-1]),
        origin=(float(x[0]), float(y[-1])),
    )
    domain.set_name("abu_dhabi_swmm_anuga_bidirectional_pilot")
    domain.set_datadir(str(output_dir))
    domain.set_quantity("elevation", topography)
    domain.set_quantity("friction", friction)
    domain.set_quantity("stage", lambda xp, yp: topography(xp, yp) + initial_depth_m)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary({"left": boundary, "right": boundary, "top": boundary, "bottom": boundary})
    source_operator = anuga.Rate_operator(domain, rate=0.0, label="swmm_bidirectional_exchange")
    centroids = np.asarray(domain.centroid_coordinates, dtype=float)
    columns = np.clip(np.floor((centroids[:, 0] - x[0]) / dx).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((y[0] - centroids[:, 1]) / dx).astype(int), 0, ny - 1)
    triangle_to_cell = rows * nx + columns
    cell_areas = np.full(nx * ny, dx * dx, dtype=float)
    adapter = runner.AnugaSurfaceAdapter(
        domain,
        source_operator,
        triangle_to_cell,
        cell_areas,
        yieldstep_seconds=window_seconds,
        finaltime_seconds=duration_seconds,
    )
    return RecordingSurfaceAdapter(adapter), (x, y, dx, values, land_mask)


def _binding_records(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"pilot_binding_json_invalid_line_{line_number}") from error
            if not isinstance(record, dict):
                raise ValueError(f"pilot_binding_record_invalid_line_{line_number}")
            yield record


def _head_parameters(record: dict[str, object], runner, args: argparse.Namespace):
    source = record.get("head_exchange_parameters")
    source = source if isinstance(source, dict) else {}
    if args.coupling_mode == "one_way_swmm_to_anuga":
        opening_area = 0.0
        reverse_flow = False
    else:
        opening_area = float(source.get("opening_area_m2", args.opening_area_m2))
        reverse_flow = bool(source.get("allow_reverse_flow", True))
    return runner.HeadExchangeParameters(
        opening_area_m2=opening_area,
        discharge_coefficient=float(source.get("discharge_coefficient", args.discharge_coefficient)),
        maximum_exchange_rate_m3s=float(
            source.get("maximum_exchange_rate_m3s", args.maximum_exchange_rate_m3s)
        ),
        minimum_head_difference_m=float(source.get("minimum_head_difference_m", 1.0e-4)),
        allow_reverse_flow=reverse_flow,
    )


def _load_bindings(
    args: argparse.Namespace,
    runner,
    coordinates: dict[str, tuple[float, float]],
    geometry,
):
    x, y, dx, _, _ = geometry
    bindings = []
    if args.bindings is not None:
        if not args.bindings.is_file():
            raise FileNotFoundError(f"pilot_bindings_missing:{args.bindings}")
        for record in _binding_records(args.bindings):
            node_id = str(record.get("swmm_node_id") or "")
            if not node_id:
                raise ValueError("pilot_binding_swmm_node_id_missing")
            node_index = record.get("swmm_node_index")
            bindings.append(
                runner.CouplingInterfaceBinding(
                    interface_id=str(record.get("interface_id") or f"{node_id}-surface"),
                    swmm_node_id=node_id,
                    swmm_node_index=(int(node_index) if node_index is not None else None),
                    anuga_cell_index=int(record["anuga_cell_index"]),
                    inlet_elevation_m=float(record.get("inlet_elevation_m", 0.0)),
                    head_exchange_parameters=_head_parameters(record, runner, args),
                    provenance=str(record.get("provenance") or "mounted_customer_interface_binding"),
                )
            )
            if args.binding_limit is not None and len(bindings) >= args.binding_limit:
                break
        return bindings

    metadata_path = args.grid_metadata or (args.grid.parent / "grid_metadata.json")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"pilot_grid_metadata_missing:{metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    selected = [node_id for node_id in metadata.get("selected_node_ids", []) if node_id in coordinates]
    if args.binding_limit is not None:
        selected = selected[: args.binding_limit]
    for node_id in selected:
        px, py = coordinates[node_id]
        col = int(np.clip(np.floor((px - x[0]) / dx), 0, len(x) - 2))
        row = int(np.clip(np.floor((y[0] - py) / dx), 0, len(y) - 2))
        bindings.append(
            runner.CouplingInterfaceBinding(
                interface_id=f"{node_id}-surface",
                swmm_node_id=node_id,
                anuga_cell_index=row * (len(x) - 1) + col,
                inlet_elevation_m=0.0,
                head_exchange_parameters=_head_parameters({}, runner, args),
                provenance="swmm_coordinate_to_mounted_terrain_grid",
            )
        )
    return bindings


def _write_surface_outputs(
    args: argparse.Namespace,
    geometry,
    surface: RecordingSurfaceAdapter,
    receipt: dict[str, object],
) -> dict[str, object]:
    from pyproj import Transformer

    x, y, dx, values, land_mask = geometry
    ny, nx = land_mask.shape
    if not surface.states:
        raise RuntimeError("pilot_surface_states_missing")
    stage = np.asarray([state.stage_by_cell_m for state in surface.states], dtype=float)
    elevation = (
        values[:-1, :-1] + values[:-1, 1:] + values[1:, :-1] + values[1:, 1:]
    ) / 4.0
    depth = np.maximum(stage - elevation.reshape(1, -1), 0.0)
    depth[:, ~land_mask.reshape(-1)] = 0.0
    maximum = depth.max(axis=0)
    transformer = Transformer.from_crs(args.grid_crs, "EPSG:4326", always_xy=True)

    def ring(cell: int):
        row, column = divmod(cell, nx)
        corners = (
            (x[column], y[row]),
            (x[column + 1], y[row]),
            (x[column + 1], y[row + 1]),
            (x[column], y[row + 1]),
            (x[column], y[row]),
        )
        return [[float(lon), float(lat)] for lon, lat in (transformer.transform(*point) for point in corners)]

    def features(values_by_cell, property_name: str, time_minutes: float | None = None):
        result = []
        for cell in np.flatnonzero(
            land_mask.reshape(-1) & (values_by_cell >= args.minimum_output_depth_m)
        ):
            value = float(values_by_cell[cell])
            properties = {
                "cell_id": int(cell),
                "depth_m": value,
                property_name: value,
                "cell_size_m": dx,
            }
            if time_minutes is not None:
                properties["time_minutes"] = time_minutes
            result.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring(int(cell))]},
                    "properties": properties,
                }
            )
        return result

    maximum_payload = {
        "type": "FeatureCollection",
        "name": f"{args.run_id}_maximum_depth",
        "features": features(maximum, "maximum_depth_m"),
    }
    (args.output / "maximum_depth_wgs84.geojson").write_text(
        json.dumps(maximum_payload, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    snapshot_dir = args.output / "temporal_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for index, values_by_cell in enumerate(depth):
        elapsed_seconds = float((index + 1) * args.window_seconds)
        name = f"surface_depth_t{index:03d}.geojson"
        payload = {
            "type": "FeatureCollection",
            "name": f"{args.run_id}_time_{index:03d}",
            "features": features(values_by_cell, "depth_m", elapsed_seconds / 60.0),
        }
        (snapshot_dir / name).write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        snapshots.append(
            {
                "index": index,
                "time_seconds": elapsed_seconds,
                "time_minutes": elapsed_seconds / 60.0,
                "path": f"temporal_snapshots/{name}",
            }
        )
    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"schema": "gwm.abu_dhabi_flood.coupled_surface_timeseries.v1", "snapshots": snapshots}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    windows = receipt.get("windows") if isinstance(receipt.get("windows"), list) else []
    coupling_summary = {
        "coupling_mode": args.coupling_mode,
        "window_count": len(windows),
        "exchange_window_seconds": args.window_seconds,
        "interface_count": len(receipt.get("interface_bindings") or []),
        "total_swmm_to_anuga_m3": sum(float(item.get("total_swmm_to_anuga_m3", 0.0)) for item in windows),
        "total_anuga_to_swmm_m3": sum(float(item.get("total_anuga_to_swmm_m3", 0.0)) for item in windows),
        "quality_passed": bool(receipt.get("quality_passed")),
        "receipt": "bidirectional_coupling_receipt.json",
    }
    active = land_mask.reshape(-1)
    summary = {
        "schema": "gwm.abu_dhabi_flood.interactive_coupled_2d_delivery.v1",
        "status": "completed_interactive_coupled_surface_run_not_engineering_admitted",
        "solver": "EPA SWMM 5.2.4 + ANUGA 2D",
        "run_id": args.run_id,
        "surface": {
            "product": args.terrain_label,
            "evidence_class": "mounted_customer_runtime_artifact",
            "source_resolution_m": None,
        },
        "domain": {
            "bounds_epsg32640": [float(x[0]), float(y[-1]), float(x[-1]), float(y[0])],
            "cell_size_m": dx,
            "rectangular_cells": int(nx * ny),
            "active_land_cells": int(active.sum()),
            "excluded_permanent_water_cells": int((~active).sum()),
            "area_m2": float(active.sum() * dx * dx),
            "triangle_count": int(surface.adapter.domain.number_of_triangles),
            "simulation_duration_hours": args.duration_seconds / 3600.0,
            "output_step_minutes": args.window_seconds / 60.0,
        },
        "results": {
            "maximum_depth_m": float(maximum[active].max()) if active.any() else 0.0,
            "minimum_published_depth_m": args.minimum_output_depth_m,
            "inundated_area_ge_0_01m2": float(np.sum((maximum >= 0.01) & active) * dx * dx),
            "inundated_area_ge_0_05m2": float(np.sum((maximum >= 0.05) & active) * dx * dx),
        },
        "coupling_summary": coupling_summary,
        "outputs": {
            "maximum_depth": "maximum_depth_wgs84.geojson",
            "timeline_manifest": "temporal_snapshots/manifest.json",
            "native_sww": "abu_dhabi_swmm_anuga_bidirectional_pilot.sww",
            "coupling_receipt": "bidirectional_coupling_receipt.json",
        },
        "model_configuration": {
            "execution_mode": "interactive_swmm_anuga_coupled_run",
            "coupling_mode": args.coupling_mode,
            "return_period_years": args.return_period_years,
            "exchange_quantity": "SWMM node overflow plus signed head exchange"
            if args.coupling_mode == "two_way_swmm_anuga"
            else "SWMM node overflow only",
            "dynamic_head_feedback": args.coupling_mode == "two_way_swmm_anuga",
            "simulation_duration_minutes": args.duration_seconds / 60.0,
            "output_interval_minutes": args.window_seconds / 60.0,
            "model_cell_size_m": dx,
            "terrain_product": args.terrain_label,
        },
        "claim_boundary": "Diagnostic coupled run; not calibrated or engineering-admitted.",
    }
    (args.output / "delivery_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, object]:
    ensure_runtime_directories()
    _, dynamic, runner = _load_flood_modules()
    args.output.mkdir(parents=True, exist_ok=True)
    coordinates = parse_coordinates(args.swmm_inp)
    surface, geometry = build_surface(
        args.grid,
        runner,
        args.output,
        window_seconds=args.window_seconds,
        duration_seconds=args.duration_seconds,
        friction=args.surface_manning_n,
        initial_depth_m=args.initial_depth_m,
    )
    bindings = _load_bindings(args, runner, coordinates, geometry)
    if not bindings:
        raise RuntimeError("pilot_no_nodes_inside_grid")
    session = dynamic.SwmmDynamicSession(
        args.swmm_library,
        args.swmm_inp,
        args.output / "swmm_dynamic.rpt",
        args.output / "swmm_dynamic.out",
        save_results=False,
    )
    with session:
        result = runner.run_synchronous_coupling(
            session,
            surface,
            bindings,
            run_id=args.run_id,
            duration_seconds=args.duration_seconds,
            window_seconds=args.window_seconds,
            fail_on_mass_balance=False,
            interface_detail_limit=args.interface_detail_limit,
        )
    runner.write_coupled_run_receipt(result, args.output / "bidirectional_coupling_receipt.json")
    receipt = result.as_dict()
    if result.status != "completed":
        raise RuntimeError(f"pilot_coupled_run_failed:{result.failure}")
    summary = _write_surface_outputs(args, geometry, surface, receipt)
    return {**receipt, "delivery_summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swmm-inp", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--grid-metadata", type=Path)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--swmm-library",
        type=Path,
        default=Path(
            os.environ.get(
                "ABU_DHABI_SWMM_LIBRARY",
                str(ROOT / "external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib"),
            )
        ),
    )
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument(
        "--coupling-mode",
        choices=("one_way_swmm_to_anuga", "two_way_swmm_anuga"),
        default="two_way_swmm_anuga",
    )
    parser.add_argument("--return-period-years", type=int, default=100)
    parser.add_argument("--opening-area-m2", type=float, default=0.5)
    parser.add_argument("--discharge-coefficient", type=float, default=0.61)
    parser.add_argument("--maximum-exchange-rate-m3s", type=float, default=5.0)
    parser.add_argument("--surface-manning-n", type=float, default=0.035)
    parser.add_argument("--initial-depth-m", type=float, default=0.0)
    parser.add_argument("--minimum-output-depth-m", type=float, default=0.01)
    parser.add_argument("--grid-crs", default="EPSG:32640")
    parser.add_argument("--terrain-label", default="Mounted customer terrain grid")
    parser.add_argument("--interface-detail-limit", type=int, default=None)
    parser.add_argument("--binding-limit", type=int, default=None)
    parser.add_argument("--run-id", default="abu-dhabi-customer-dtm-swmm-anuga-bidirectional-pilot-20260909")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    payload = run(args)
    if args.quiet:
        print(
            json.dumps(
                {
                    "run_id": payload.get("run_id"),
                    "status": payload.get("status"),
                    "quality_passed": payload.get("quality_passed"),
                    "window_count": len(payload.get("windows") or []),
                },
                ensure_ascii=True,
            )
        )
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
