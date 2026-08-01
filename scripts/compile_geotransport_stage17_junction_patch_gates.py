#!/usr/bin/env python3
"""Compile Stage 17 conforming multi-cell junction-patch gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    solve_conservative_vector_junction,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
)
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_patch import (
    JunctionPatchCellGeometry,
    JunctionPatchCellState,
    JunctionPatchFace,
    JunctionPatchVertex,
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
    advance_shallow_water_junction_patch,
    maximum_shallow_water_junction_patch_timestep_seconds,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage17_shallow_water_junction_patch_gates.json"
)
SCHEMA = "gwm.geotransport.stage17_shallow_water_junction_patch_gates.v1"
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 25
MASS_TOLERANCE_M3 = 1e-11
MOMENTUM_TOLERANCE_M4S = 1e-11
ROTATION_TOLERANCE_M4S = 1e-11

FROZEN_STAGE16_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "coupled_junction_reach_sources.py"
    ): (
        "db7a088ef666546fc6393089093dbee3bfee5c5510e0358971fe34261ef5de18"
    ),
    "data_agent/test_geospatial_kernel_coupled_junction_reach_sources.py": (
        "8d81d009632786c9512c26debdc099b0c4979ff65b5c5caf5e8b8313b3e03314"
    ),
    (
        "scripts/"
        "compile_geotransport_stage16_source_split_junction_gates.py"
    ): (
        "809dbe603bd17519476991b8f4adfc31404916d86733202916df3d341feec583"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage16_source_split_junction_reach_gates.json"
    ): (
        "874b23de5b1b59a6d23add1971e363f6ea315fb7155b3e906e757a06b1515f4a"
    ),
    (
        "docs/architecture-decisions/"
        "adr-057-source-split-junction-reach-coupling.md"
    ): (
        "de6f2548d99bed90b83b53ca24505df52ed304b32cd8fa87c831e74805147563"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report() -> dict[str, Any]:
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    baseline = advance_shallow_water_junction_patch(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    lake = _lake_control()
    rotation = _rotation_control()
    multistep = _multistep_control()
    refusals = _refusal_control()
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE16_HASHES.items()
    }
    stage16_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    geometry_report = geometry.as_dict()
    internal_fluxes = tuple(
        value
        for value in baseline.face_fluxes
        if value.boundary_type == "internal"
    )
    gates = {
        "stage16_artifacts_hash_frozen": stage16_frozen,
        "multiple_finite_area_cells_present": len(geometry.cells) >= 2,
        "counterclockwise_simple_cell_polygons_verified": (
            geometry_report["counterclockwise_cell_polygons_verified"]
            and geometry_report["simple_cell_polygons_verified"]
        ),
        "conforming_internal_face_pairs_verified": (
            geometry_report["conforming_internal_edge_pairs_verified"]
        ),
        "complete_connected_edge_topology_verified": (
            geometry_report["complete_cell_edge_coverage_verified"]
            and geometry_report["connected_cell_graph_verified"]
        ),
        "external_oriented_boundary_measure_closed": (
            math.hypot(*geometry.external_closure_east_north_m) <= 1e-12
        ),
        "common_cellwise_cfl_is_positive": stable > 0.0,
        "internal_hll_exchange_is_active": (
            len(internal_fluxes) >= 1
            and any(
                abs(value.outward_mass_flux_m3s) > 1e-6
                for value in internal_fluxes
            )
        ),
        "internal_mass_and_vector_impulses_cancel": (
            baseline.maximum_internal_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
            and baseline.maximum_internal_momentum_cancellation_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "every_cell_finite_volume_ledger_closes": (
            baseline.maximum_cell_mass_ledger_error_m3 <= MASS_TOLERANCE_M3
            and baseline.maximum_cell_momentum_ledger_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "whole_patch_mass_ledger_closes": (
            abs(baseline.mass_ledger_error_m3) <= MASS_TOLERANCE_M3
        ),
        "whole_patch_east_momentum_ledger_closes": (
            abs(baseline.momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "whole_patch_north_momentum_ledger_closes": (
            abs(baseline.momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "lake_at_rest_preserves_every_cell": (
            lake["maximum_cell_state_error"] <= MOMENTUM_TOLERANCE_M4S
        ),
        "lake_at_rest_global_ledgers_close": (
            lake["mass_ledger_error_m3"] <= MASS_TOLERANCE_M3
            and lake["momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_cell_volumes": (
            rotation["maximum_cell_volume_error_m3"]
            <= ROTATION_TOLERANCE_M4S
        ),
        "rotation_covaries_cell_momentum_vectors": (
            rotation["maximum_cell_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE_M4S
        ),
        "multistep_cell_states_remain_positive": (
            multistep["minimum_cell_volume_m3"] > 0.0
        ),
        "multistep_ledgers_close_and_internal_flux_evolves": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
            and abs(
                multistep["last_internal_mass_flux_m3s"]
                - multistep["first_internal_mass_flux_m3s"]
            )
            > 1e-8
        ),
        "unsupported_topology_and_opening_contracts_fail_closed": all(
            refusals.values()
        ),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "multi_cell_junction_patch_manufactured_invariants_pass_"
            "synchronous_reach_coupling_and_public_validation_pending"
        ),
        "law": {
            "cell_state": [
                "water_volume_m3",
                "east_momentum_m4s",
                "north_momentum_m4s",
            ],
            "internal_face_flux": "single_evaluation_rotated_2d_HLL",
            "external_opening_flux": "rotated_2d_HLL_to_stage13_boundary",
            "solid_wall_flux": "hydrostatic_reflective_slip_pressure",
            "mesh_contract": (
                "counterclockwise_simple_polygons_with_paired_internal_edges"
            ),
            "fitted_parameters": [],
        },
        "geometry": geometry_report,
        "baseline_step": baseline.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage16_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "multi_cell_finite_area_patch_implemented": True,
            "conforming_polygon_edge_topology_verified": True,
            "internal_two_dimensional_hll_exchange_implemented": True,
            "cellwise_cfl_and_drain_limits_implemented": True,
            "whole_patch_mass_and_vector_momentum_ledgers_implemented": True,
            "single_uniform_junction_cell_only": False,
            "pairwise_polygon_overlap_independently_verified": False,
            "branch_reach_states_updated_conservatively": False,
            "source_split_reach_coupling_integrated": False,
            "variable_bed_or_dry_fronts_supported": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    state = _state(lake=True)
    upstream, downstream, junction = _junction(discharges=(0.0, 0.0, 0.0))
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    result = advance_shallow_water_junction_patch(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    errors = []
    for before, after in zip(
        state.cells, result.state_after.cells, strict=True
    ):
        errors.extend(
            (
                abs(after.volume_m3 - before.volume_m3),
                abs(after.momentum_east_m4s - before.momentum_east_m4s),
                abs(after.momentum_north_m4s - before.momentum_north_m4s),
            )
        )
    return {
        "timestep_seconds": stable,
        "maximum_cell_state_error": max(errors),
        "mass_ledger_error_m3": abs(result.mass_ledger_error_m3),
        "momentum_ledger_error_m4s": (
            result.momentum_ledger_error_magnitude_m4s
        ),
    }


def _rotation_control() -> dict[str, Any]:
    rotation = ROTATION_DEGREES
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    upstream, downstream, junction = _junction()
    rotated_upstream, rotated_downstream, rotated_junction = _junction(
        rotation_degrees=rotation
    )
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state, geometry, upstream, downstream, junction,
        courant_number=COURANT_NUMBER
    )
    rotated_stable = maximum_shallow_water_junction_patch_timestep_seconds(
        rotated_state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(stable, rotated_stable)
    baseline = advance_shallow_water_junction_patch(
        state, geometry, upstream, downstream, junction,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_shallow_water_junction_patch(
        rotated_state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    volume_errors = []
    momentum_errors = []
    for before, after in zip(
        baseline.state_after.cells, rotated.state_after.cells, strict=True
    ):
        expected = _rotate_vector(
            before.momentum_east_m4s,
            before.momentum_north_m4s,
            rotation,
        )
        volume_errors.append(abs(after.volume_m3 - before.volume_m3))
        momentum_errors.append(
            math.hypot(
                after.momentum_east_m4s - expected[0],
                after.momentum_north_m4s - expected[1],
            )
        )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(stable - rotated_stable),
        "maximum_cell_volume_error_m3": max(volume_errors),
        "maximum_cell_momentum_rotation_error_m4s": max(momentum_errors),
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    minimum_volume = min(value.volume_m3 for value in state.cells)
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    first_flux = None
    last_flux = None
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        stable = maximum_shallow_water_junction_patch_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=COURANT_NUMBER,
        )
        result = advance_shallow_water_junction_patch(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=0.5 * stable,
            maximum_courant_number=COURANT_NUMBER,
        )
        flux = next(
            value.outward_mass_flux_m3s for value in result.face_fluxes
            if value.face_id == "internal-sw-nw"
        )
        if first_flux is None:
            first_flux = flux
        last_flux = flux
        state = result.state_after
        elapsed += result.timestep_seconds
        minimum_volume = min(
            minimum_volume, min(value.volume_m3 for value in state.cells)
        )
        maximum_mass_error = max(
            maximum_mass_error, abs(result.mass_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.momentum_ledger_error_magnitude_m4s,
        )
    return {
        "step_count": MULTISTEP_COUNT,
        "elapsed_seconds": elapsed,
        "minimum_cell_volume_m3": minimum_volume,
        "maximum_mass_ledger_error_m3": maximum_mass_error,
        "maximum_momentum_ledger_error_m4s": maximum_momentum_error,
        "first_internal_mass_flux_m3s": first_flux,
        "last_internal_mass_flux_m3s": last_flux,
        "final_state": state.as_dict(geometry),
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    results = {}
    internal_index = next(
        index
        for index, value in enumerate(geometry.faces)
        if value.face_id == "internal-sw-se"
    )
    invalid_faces = list(geometry.faces)
    invalid_faces[internal_index] = replace(
        invalid_faces[internal_index], right_cell_id="ne"
    )
    try:
        replace(geometry, faces=tuple(invalid_faces))
    except ValueError as exc:
        results["internal_face_pair"] = str(exc) == (
            "junction_patch_internal_face_pair_mismatch"
        )
    else:
        results["internal_face_pair"] = False
    invalid_cells = list(geometry.cells)
    invalid_cells[0] = JunctionPatchCellGeometry(
        "sw", ("v00", "v11", "v10", "v01")
    )
    try:
        replace(geometry, cells=tuple(invalid_cells))
    except ValueError as exc:
        results["invalid_cell_polygon"] = str(exc).startswith(
            "junction_patch_cell_"
        )
    else:
        results["invalid_cell_polygon"] = False
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    try:
        advance_shallow_water_junction_patch(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == "junction_patch_cfl_exceeded"
    else:
        results["cfl_exceeded"] = False
    wrong_junction = replace(
        junction,
        contract=replace(
            junction.contract, downstream_flow_azimuth_degrees=0.0
        ),
    )
    try:
        maximum_shallow_water_junction_patch_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            wrong_junction,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["opening_orientation"] = str(exc) == (
            "junction_patch_opening_contract_not_supported"
        )
    else:
        results["opening_orientation"] = False
    return results


def _geometry(*, rotation_degrees: float = 0.0):
    coordinates = {
        "v00": (0.0, 0.0), "v10": (10.0, 0.0), "v20": (20.0, 0.0),
        "v01": (0.0, 10.0), "v11": (10.0, 10.0), "v21": (20.0, 10.0),
        "v02": (0.0, 20.0), "v12": (10.0, 20.0), "v22": (20.0, 20.0),
    }
    vertices = tuple(
        JunctionPatchVertex(vertex_id, *_rotate_vector(*point, rotation_degrees))
        for vertex_id, point in coordinates.items()
    )
    return ShallowWaterJunctionPatchGeometry(
        "junction-grid", 0.0, vertices,
        (
            JunctionPatchCellGeometry("sw", ("v00", "v10", "v11", "v01")),
            JunctionPatchCellGeometry("se", ("v10", "v20", "v21", "v11")),
            JunctionPatchCellGeometry("nw", ("v01", "v11", "v12", "v02")),
            JunctionPatchCellGeometry("ne", ("v11", "v21", "v22", "v12")),
        ),
        _faces(),
        "manufactured:stage17-conforming-four-cell-grid",
    )


def _faces():
    return (
        JunctionPatchFace(
            "opening-up-a", "nw", "v02", "v01", "branch_opening",
            branch_id="up-a", branch_role="upstream"
        ),
        JunctionPatchFace(
            "opening-up-b", "sw", "v00", "v10", "branch_opening",
            branch_id="up-b", branch_role="upstream"
        ),
        JunctionPatchFace(
            "opening-down", "se", "v20", "v21", "branch_opening",
            branch_id="down", branch_role="downstream"
        ),
        JunctionPatchFace(
            "internal-sw-se", "sw", "v10", "v11", "internal",
            right_cell_id="se"
        ),
        JunctionPatchFace(
            "internal-sw-nw", "sw", "v11", "v01", "internal",
            right_cell_id="nw"
        ),
        JunctionPatchFace(
            "internal-se-ne", "se", "v21", "v11", "internal",
            right_cell_id="ne"
        ),
        JunctionPatchFace(
            "internal-nw-ne", "nw", "v11", "v12", "internal",
            right_cell_id="ne"
        ),
        JunctionPatchFace("wall-sw-west", "sw", "v01", "v00", "solid_wall"),
        JunctionPatchFace("wall-se-south", "se", "v10", "v20", "solid_wall"),
        JunctionPatchFace("wall-ne-east", "ne", "v21", "v22", "solid_wall"),
        JunctionPatchFace("wall-ne-north", "ne", "v22", "v12", "solid_wall"),
        JunctionPatchFace("wall-nw-north", "nw", "v12", "v02", "solid_wall"),
    )


def _state(*, lake=False, rotation_degrees=0.0):
    values = (
        ("sw", 200.0, 0.0, 0.0),
        ("se", 200.0, 5.0, 0.0),
        ("nw", 190.0, 0.0, 0.0),
        ("ne", 210.0, 0.0, -3.0),
    )
    if lake:
        values = tuple((cell_id, 200.0, 0.0, 0.0) for cell_id, *_ in values)
    return ShallowWaterJunctionPatchState(
        tuple(
            JunctionPatchCellState(
                cell_id, volume,
                *_rotate_vector(east, north, rotation_degrees)
            )
            for cell_id, volume, east, north in values
        )
    )


def _junction(*, discharges=(5.0, 7.0, 12.0), rotation_degrees=0.0):
    section = TrapezoidalChannelSection(10.0, 0.0)

    def terminal(branch_id, discharge):
        return DynamicWaveJunctionTerminal(
            branch_id,
            DynamicWaveCellState(section.area_m2(2.0), discharge),
            section,
            0.0,
        )

    upstream = terminal("up-a", discharges[0]), terminal("up-b", discharges[1])
    downstream = terminal("down", discharges[2])
    contract = ConservativeVectorJunctionContract(
        "junction-grid", ("up-a", "up-b"), "down",
        ((90.0 + rotation_degrees) % 360.0, rotation_degrees % 360.0),
        (90.0 + rotation_degrees) % 360.0,
        "manufactured:stage17",
    )
    return (
        upstream,
        downstream,
        solve_conservative_vector_junction(upstream, downstream, contract),
    )


def _rotate_vector(east, north, angle_degrees):
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
