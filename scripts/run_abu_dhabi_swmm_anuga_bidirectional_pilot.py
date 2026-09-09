#!/usr/bin/env python3
"""Run a short customer-data SWMM--ANUGA bidirectional pilot.

The command is intended to be executed with the repository's ANUGA Python
environment.  It reads a runtime NPZ grid prepared by
``prepare_abu_dhabi_bidirectional_pilot_grid.py`` and never modifies the
customer SWMM input or DTM.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FLOOD_PACKAGE = ROOT / "data_agent/uwm/abu_dhabi_flood"


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


def build_surface(grid_path: Path, runner, output_dir: Path):
    import anuga

    grid = np.load(grid_path)
    values = np.asarray(grid["values"], dtype=float)
    x = np.asarray(grid["x"], dtype=float)
    y = np.asarray(grid["y"], dtype=float)
    ny, nx = values.shape[0] - 1, values.shape[1] - 1
    dx = float((x[-1] - x[0]) / nx)

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
    domain.set_quantity("friction", 0.035)
    domain.set_quantity("stage", topography)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary({"left": boundary, "right": boundary, "top": boundary, "bottom": boundary})
    source_operator = anuga.Rate_operator(domain, rate=0.0, label="swmm_bidirectional_exchange")
    centroids = np.asarray(domain.centroid_coordinates, dtype=float)
    columns = np.clip(np.floor((centroids[:, 0] - x[0]) / dx).astype(int), 0, nx - 1)
    rows = np.clip(np.floor((y[0] - centroids[:, 1]) / dx).astype(int), 0, ny - 1)
    triangle_to_cell = rows * nx + columns
    cell_areas = np.full(nx * ny, dx * dx, dtype=float)
    return domain, source_operator, triangle_to_cell, cell_areas, runner.AnugaSurfaceAdapter(
        domain,
        source_operator,
        triangle_to_cell,
        cell_areas,
        yieldstep_seconds=300,
        finaltime_seconds=3600,
    ), (x, y, dx)


def run(args: argparse.Namespace) -> dict[str, object]:
    _, dynamic, runner = _load_flood_modules()
    grid = np.load(args.grid)
    metadata = json.loads((args.grid.parent / "grid_metadata.json").read_text(encoding="utf-8"))
    coordinates = parse_coordinates(args.swmm_inp)
    domain, source_operator, triangle_to_cell, cell_areas, surface, geometry = build_surface(args.grid, runner, args.output)
    x, y, dx = geometry
    selected = [node_id for node_id in metadata["selected_node_ids"] if node_id in coordinates]
    if args.binding_limit is not None:
        selected = selected[: args.binding_limit]
    bindings = []
    for node_id in selected:
        px, py = coordinates[node_id]
        col = int(np.clip(np.floor((px - x[0]) / dx), 0, len(x) - 2))
        row = int(np.clip(np.floor((y[0] - py) / dx), 0, len(y) - 2))
        cell_index = row * (len(x) - 1) + col
        bindings.append(
            runner.CouplingInterfaceBinding(
                interface_id=f"{node_id}-surface",
                swmm_node_id=node_id,
                anuga_cell_index=cell_index,
                inlet_elevation_m=0.0,
                head_exchange_parameters=runner.HeadExchangeParameters(
                    opening_area_m2=args.opening_area_m2,
                    discharge_coefficient=args.discharge_coefficient,
                    maximum_exchange_rate_m3s=args.maximum_exchange_rate_m3s,
                ),
                provenance="customer_swmm_node_and_customer_dtm_pilot_mapping",
            )
        )
    if not bindings:
        raise RuntimeError("pilot_no_nodes_inside_grid")
    session = dynamic.SwmmDynamicSession(
        args.swmm_library,
        args.swmm_inp,
        args.output / "swmm_dynamic.rpt",
        args.output / "swmm_dynamic.out",
        save_results=False,
    )
    args.output.mkdir(parents=True, exist_ok=True)
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
    return result.as_dict()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swmm-inp", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--swmm-library", type=Path, default=Path("/Users/zhouning/gisdataagent/external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib"))
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument("--opening-area-m2", type=float, default=0.5)
    parser.add_argument("--discharge-coefficient", type=float, default=0.61)
    parser.add_argument("--maximum-exchange-rate-m3s", type=float, default=5.0)
    parser.add_argument("--interface-detail-limit", type=int, default=None)
    parser.add_argument("--binding-limit", type=int, default=None)
    parser.add_argument("--run-id", default="abu-dhabi-customer-dtm-swmm-anuga-bidirectional-pilot-20260909")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
