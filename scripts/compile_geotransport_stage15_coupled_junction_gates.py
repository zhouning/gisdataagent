#!/usr/bin/env python3
"""Compile Stage 15 synchronous 2D-junction/1D-reach coupling gates."""

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
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_reach import (
    ReachTerminalTransverseMomentum,
    advance_coupled_junction_reaches,
    maximum_coupled_junction_reach_timestep_seconds,
    zero_terminal_transverse_momentum,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveNetworkReach,
)
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_cell import (
    JunctionCellBoundaryFace,
    ShallowWaterJunctionCellGeometry,
    ShallowWaterJunctionCellState,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage15_coupled_junction_reach_gates.json"
)
SCHEMA = "gwm.geotransport.stage15_coupled_junction_reach_gates.v1"
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 25
MASS_TOLERANCE_M3 = 1e-8
MOMENTUM_TOLERANCE_M4S = 1e-9
ROTATION_TOLERANCE = 1e-11

FROZEN_STAGE14_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/shallow_water_junction_cell.py": (
        "697f8d16556d29cc427cc68531e13406007f3d0cb06bf2b645bd2c856b837c9d"
    ),
    "data_agent/test_geospatial_kernel_shallow_water_junction_cell.py": (
        "c305983306b61d90b27e1ee1c6bdd7f2e3b59c40e2e5fe62c8b67b2f601c5385"
    ),
    "scripts/compile_geotransport_stage14_junction_cell_gates.py": (
        "6e29d284ff5b516f39827ae136e68f50820a7d409294830be11a730b983664aa"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage14_shallow_water_junction_cell_gates.json"
    ): (
        "dab5fa6697895860028de9aef23e8e7229a34bbf0af24004daaadae9704384f0"
    ),
    (
        "docs/architecture-decisions/"
        "adr-055-finite-area-shallow-water-junction-cell.md"
    ): (
        "9245f00671ea0de976c3086137faeed9aeeaeb2a05e48440eb94543b105701be"
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
    contract = _contract()
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    baseline = _step(cell, geometry, contract, network, reservoirs)
    lake = _lake_control()
    rotation = _rotation_control()
    multistep = _multistep_control()
    refusals = _refusal_control()
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE14_HASHES.items()
    }
    stage14_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    lake_reach_error = max(
        lake["maximum_reach_area_error_m2"],
        lake["maximum_reach_discharge_error_m3s"],
    )
    gates = {
        "stage14_artifacts_hash_frozen": stage14_frozen,
        "common_cfl_timestep_is_positive": (
            baseline.maximum_stable_timestep_seconds > 0.0
        ),
        "whole_system_mass_ledger_closed": (
            abs(baseline.total_volume_ledger_error_m3)
            <= MASS_TOLERANCE_M3
        ),
        "east_geographic_momentum_ledger_closed": (
            abs(baseline.geographic_momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "north_geographic_momentum_ledger_closed": (
            abs(baseline.geographic_momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "junction_wall_pressure_in_global_ledger": (
            math.isfinite(
                baseline.junction_wall_pressure_impulse_east_m4s
            )
            and math.isfinite(
                baseline.junction_wall_pressure_impulse_north_m4s
            )
        ),
        "opening_mass_exchange_cancels": (
            baseline.maximum_opening_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
        ),
        "complete_opening_vector_impulse_cancels": (
            baseline.maximum_opening_momentum_cancellation_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "reach_and_junction_states_update_synchronously": (
            baseline.junction_cell_step.state_after
            != baseline.junction_cell_step.state_before
            and baseline.upstream_states
            != tuple(value.state for value in network[0])
            and baseline.downstream_state != network[1].state
        ),
        "lake_at_rest_preserves_all_primary_states": (
            lake_reach_error <= 1e-12
            and lake["junction_state_error_magnitude"] <= 1e-12
            and lake["maximum_reservoir_magnitude_m4s"] <= 1e-12
        ),
        "lake_at_rest_global_ledgers_close": (
            lake["mass_ledger_error_m3"] <= MASS_TOLERANCE_M3
            and lake["momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_scalar_reach_states": (
            rotation["maximum_scalar_reach_error"]
            <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_junction_and_reservoir_momentum": (
            rotation["junction_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
            and rotation["maximum_reservoir_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "multistep_primary_states_remain_positive": (
            multistep["minimum_reach_area_m2"] > 0.0
            and multistep["minimum_junction_volume_m3"] > 0.0
        ),
        "multistep_global_ledgers_close": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "asymmetric_evolution_populates_transverse_reservoir": (
            multistep["maximum_terminal_transverse_momentum_m4s"] > 1e-6
        ),
        "unsupported_contracts_fail_closed": all(refusals.values()),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "synchronous_junction_reach_manufactured_invariants_pass_"
            "source_splitting_and_public_validation_pending"
        ),
        "law": {
            "junction_state": [
                "water_volume_m3",
                "east_momentum_m4s",
                "north_momentum_m4s",
            ],
            "reach_state": [
                "cross_section_area_m2",
                "longitudinal_discharge_m3s",
            ],
            "opening_exchange": (
                "same_2d_HLL_flux_with_equal_and_opposite_impulses"
            ),
            "one_dimensional_projection": "dot(opening_momentum, tangent)",
            "discarded_transverse_component": False,
            "transverse_component_storage": (
                "explicit_branch_terminal_momentum_reservoir"
            ),
            "external_force": "junction_solid_wall_hydrostatic_pressure",
            "fitted_parameters": [],
        },
        "baseline_step": baseline.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage14_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "synchronous_junction_reach_coupling_implemented": True,
            "whole_system_mass_ledger_implemented": True,
            "whole_system_two_component_momentum_ledger_implemented": True,
            "complete_opening_vector_flux_retained": True,
            "terminal_transverse_momentum_reservoir_implemented": True,
            "transverse_reservoir_feedback_implemented": False,
            "friction_and_lateral_source_splitting_implemented": False,
            "uniform_flat_rectangular_reaches_only": True,
            "polygon_vertex_topology_verified": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _step(cell, geometry, contract, network, reservoirs):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_coupled_junction_reach_timestep_seconds(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    return advance_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=COURANT_NUMBER,
    )


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    network = _network(discharges=(0.0, 0.0, 0.0))
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_coupled_junction_reach_timestep_seconds(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    result = advance_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        timestep_seconds=stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    before_states = (*tuple(value.state for value in upstream), downstream.state)
    after_states = (*result.upstream_states, result.downstream_state)
    return {
        "timestep_seconds": stable,
        "maximum_reach_area_error_m2": max(
            abs(actual - expected)
            for before, after in zip(
                before_states, after_states, strict=True
            )
            for actual, expected in zip(
                after.area_m2, before.area_m2, strict=True
            )
        ),
        "maximum_reach_discharge_error_m3s": max(
            abs(actual - expected)
            for before, after in zip(
                before_states, after_states, strict=True
            )
            for actual, expected in zip(
                after.discharge_m3s, before.discharge_m3s, strict=True
            )
        ),
        "junction_state_error_magnitude": math.sqrt(
            (result.junction_cell_step.state_after.volume_m3 - cell.volume_m3)
            ** 2
            + result.junction_cell_step.state_after.momentum_east_m4s**2
            + result.junction_cell_step.state_after.momentum_north_m4s**2
        ),
        "maximum_reservoir_magnitude_m4s": max(
            value.magnitude_m4s
            for value in result.transverse_momentum_after
        ),
        "mass_ledger_error_m3": abs(result.total_volume_ledger_error_m3),
        "momentum_ledger_error_m4s": (
            result.geographic_momentum_ledger_error_magnitude_m4s
        ),
    }


def _rotation_control() -> dict[str, Any]:
    rotation = ROTATION_DEGREES
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    rotated_initial = _rotate_vector(12.0, -4.0, rotation)
    rotated_cell = ShallowWaterJunctionCellState(200.0, *rotated_initial)
    reservoirs = zero_terminal_transverse_momentum(contract)
    rotated_reservoirs = zero_terminal_transverse_momentum(rotated_contract)
    upstream, downstream, upstream_external, downstream_external = network
    baseline_stable = maximum_coupled_junction_reach_timestep_seconds(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    rotated_stable = maximum_coupled_junction_reach_timestep_seconds(
        rotated_cell,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=rotated_reservoirs,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(baseline_stable, rotated_stable)
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "timestep_seconds": timestep,
        "maximum_courant_number": COURANT_NUMBER,
    }
    baseline = advance_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        transverse_momentum=reservoirs,
        **common,
    )
    rotated = advance_coupled_junction_reaches(
        rotated_cell,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        transverse_momentum=rotated_reservoirs,
        **common,
    )
    scalar_errors = []
    for baseline_state, rotated_state in zip(
        (*baseline.upstream_states, baseline.downstream_state),
        (*rotated.upstream_states, rotated.downstream_state),
        strict=True,
    ):
        scalar_errors.extend(
            abs(left - right)
            for left, right in zip(
                baseline_state.area_m2, rotated_state.area_m2, strict=True
            )
        )
        scalar_errors.extend(
            abs(left - right)
            for left, right in zip(
                baseline_state.discharge_m3s,
                rotated_state.discharge_m3s,
                strict=True,
            )
        )
    expected_cell = _rotate_vector(
        baseline.junction_cell_step.state_after.momentum_east_m4s,
        baseline.junction_cell_step.state_after.momentum_north_m4s,
        rotation,
    )
    cell_error = math.hypot(
        rotated.junction_cell_step.state_after.momentum_east_m4s
        - expected_cell[0],
        rotated.junction_cell_step.state_after.momentum_north_m4s
        - expected_cell[1],
    )
    reservoir_errors = []
    for baseline_value, rotated_value in zip(
        baseline.transverse_momentum_after,
        rotated.transverse_momentum_after,
        strict=True,
    ):
        expected = _rotate_vector(
            baseline_value.momentum_east_m4s,
            baseline_value.momentum_north_m4s,
            rotation,
        )
        reservoir_errors.append(
            math.hypot(
                rotated_value.momentum_east_m4s - expected[0],
                rotated_value.momentum_north_m4s - expected[1],
            )
        )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(
            rotated_stable - baseline_stable
        ),
        "maximum_scalar_reach_error": max(scalar_errors),
        "junction_momentum_rotation_error_m4s": cell_error,
        "maximum_reservoir_rotation_error_m4s": max(reservoir_errors),
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    cell = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    minimum_area = min(
        min(value.state.area_m2) for value in (*upstream, downstream)
    )
    minimum_volume = cell.volume_m3
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        network = (
            upstream,
            downstream,
            upstream_external,
            downstream_external,
        )
        result = _step(cell, geometry, contract, network, reservoirs)
        upstream = tuple(
            replace(reach, state=state)
            for reach, state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        cell = result.junction_cell_step.state_after
        reservoirs = result.transverse_momentum_after
        elapsed += result.timestep_seconds
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(minimum_volume, cell.volume_m3)
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
    return {
        "step_count": MULTISTEP_COUNT,
        "elapsed_seconds": elapsed,
        "minimum_reach_area_m2": minimum_area,
        "minimum_junction_volume_m3": minimum_volume,
        "maximum_mass_ledger_error_m3": maximum_mass_error,
        "maximum_momentum_ledger_error_m4s": maximum_momentum_error,
        "maximum_terminal_transverse_momentum_m4s": max(
            value.magnitude_m4s for value in reservoirs
        ),
        "final_junction_state": cell.as_dict(geometry),
        "final_transverse_momentum": [
            value.as_dict() for value in reservoirs
        ],
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    contract = _contract()
    network = _network()
    upstream, downstream, upstream_external, downstream_external = network
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "transverse_momentum": reservoirs,
        "courant_number": COURANT_NUMBER,
    }
    results = {}
    stable = maximum_coupled_junction_reach_timestep_seconds(
        cell, geometry, contract, upstream, downstream, **common
    )
    try:
        advance_coupled_junction_reaches(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "coupled_junction_reach_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False
    try:
        maximum_coupled_junction_reach_timestep_seconds(
            cell,
            geometry,
            contract,
            (replace(upstream[0], reach_id="wrong"), upstream[1]),
            downstream,
            **common,
        )
    except ValueError as exc:
        results["branch_mismatch"] = str(exc) == (
            "coupled_junction_reach_branch_binding_mismatch"
        )
    else:
        results["branch_mismatch"] = False
    invalid_section = TrapezoidalChannelSection(9.0, 0.0)
    try:
        maximum_coupled_junction_reach_timestep_seconds(
            cell,
            geometry,
            contract,
            (replace(upstream[0], sections=(invalid_section,) * 4), upstream[1]),
            downstream,
            **common,
        )
    except ValueError as exc:
        results["geometry_mismatch"] = str(exc) == (
            "coupled_junction_reach_uniform_rectangular_flat_contract_required"
        )
    else:
        results["geometry_mismatch"] = False
    invalid_reservoirs = (
        ReachTerminalTransverseMomentum("up-a", 1.0, 1.0),
        *reservoirs[1:],
    )
    try:
        maximum_coupled_junction_reach_timestep_seconds(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=invalid_reservoirs,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["nontransverse_reservoir"] = str(exc) == (
            "coupled_junction_reach_transverse_reservoir_not_perpendicular"
        )
    else:
        results["nontransverse_reservoir"] = False
    lateral_reach = replace(
        upstream[0], lateral_inflow_m2s=(0.01,) * 4
    )
    try:
        maximum_coupled_junction_reach_timestep_seconds(
            cell,
            geometry,
            contract,
            (lateral_reach, upstream[1]),
            downstream,
            **common,
        )
    except ValueError as exc:
        results["lateral_source_pending"] = str(exc) == (
            "coupled_junction_reach_uniform_rectangular_flat_contract_required"
        )
    else:
        results["lateral_source_pending"] = False
    return results


def _network(*, discharges=(5.0, 7.0, 12.0)):
    upstream = (
        _reach("up-a", discharges[0]),
        _reach("up-b", discharges[1]),
    )
    downstream = _reach("down", discharges[2])
    upstream_external = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(20.0, discharge), 0.0
        )
        for discharge in discharges[:2]
    )
    downstream_external = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, discharges[2]), 0.0
    )
    return upstream, downstream, upstream_external, downstream_external


def _reach(branch_id: str, discharge_m3s: float):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState(
            (section.area_m2(2.0),) * 4, (discharge_m3s,) * 4
        ),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (0.0,) * 4,
    )


def _geometry(*, rotation_degrees: float = 0.0):
    width = 10.0

    def azimuth(value: float) -> float:
        return (value + rotation_degrees) % 360.0

    return ShallowWaterJunctionCellGeometry(
        "junction-y",
        100.0,
        0.0,
        (
            JunctionCellBoundaryFace(
                "opening-a", "branch_opening", width, azimuth(225.0),
                "up-a", "upstream"
            ),
            JunctionCellBoundaryFace(
                "opening-b", "branch_opening", width, azimuth(135.0),
                "up-b", "upstream"
            ),
            JunctionCellBoundaryFace(
                "opening-down", "branch_opening", width, azimuth(0.0),
                "down", "downstream"
            ),
            JunctionCellBoundaryFace(
                "wall-north", "solid_wall",
                width * (math.sqrt(2.0) - 1.0), azimuth(0.0)
            ),
            JunctionCellBoundaryFace(
                "wall-east", "solid_wall", 15.0, azimuth(90.0)
            ),
            JunctionCellBoundaryFace(
                "wall-west", "solid_wall", 15.0, azimuth(270.0)
            ),
        ),
        "manufactured:stage15-closed-y-cell",
    )


def _contract(*, rotation_degrees: float = 0.0):
    return ConservativeVectorJunctionContract(
        "junction-y",
        ("up-a", "up-b"),
        "down",
        tuple(
            (value + rotation_degrees) % 360.0
            for value in (45.0, 315.0)
        ),
        rotation_degrees % 360.0,
        "manufactured:stage15",
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
