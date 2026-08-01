#!/usr/bin/env python3
"""Compile Stage 16 source-split junction/reach coupling gates."""

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
    zero_terminal_transverse_momentum,
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_reach_sources import (
    advance_source_split_coupled_junction_reaches,
    maximum_source_split_coupled_junction_timestep_seconds,
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
    "stage16_source_split_junction_reach_gates.json"
)
SCHEMA = "gwm.geotransport.stage16_source_split_junction_reach_gates.v1"
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 20
MASS_TOLERANCE_M3 = 1e-8
MOMENTUM_TOLERANCE_M4S = 1e-9
ROTATION_TOLERANCE = 1e-11

FROZEN_STAGE15_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/coupled_junction_reach.py": (
        "5733e3aca007b44c228ba57f0c771ce7b70470a19104d68e799ebc2a413bfee7"
    ),
    "data_agent/test_geospatial_kernel_coupled_junction_reach.py": (
        "4798af37bfd0b055aa6beefef56676e6a7f3889a278229fa6e716460bd95aa26"
    ),
    "scripts/compile_geotransport_stage15_coupled_junction_gates.py": (
        "7f545c61bf90462779176fd5d0ab39234ba1ccf44aaf0ff7b077c280e46fc54c"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage15_coupled_junction_reach_gates.json"
    ): (
        "4e0ed21b4663f12acf63acce2b55c1f119854e1d5fcc37d8a56367ba7c4241d4"
    ),
    (
        "docs/architecture-decisions/"
        "adr-056-synchronous-junction-reach-coupling.md"
    ): (
        "3bddb851567c32dfd266223ece7e7b4f6311bdb4dc2bf829cd5d212736937ce0"
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
    zero_momentum = _step(
        cell,
        geometry,
        contract,
        network,
        reservoirs,
        "zero_longitudinal_momentum",
    )
    matched_velocity = _step(
        cell,
        geometry,
        contract,
        network,
        reservoirs,
        "matched_local_velocity",
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
        for relative, expected in FROZEN_STAGE15_HASHES.items()
    }
    stage15_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    traces = (
        *zero_momentum.upstream_source_traces,
        zero_momentum.downstream_source_trace,
    )
    gates = {
        "stage15_artifacts_hash_frozen": stage15_frozen,
        "source_adjusted_common_cfl_is_positive": (
            zero_momentum.maximum_stable_timestep_seconds > 0.0
        ),
        "strang_source_order_is_explicit": (
            zero_momentum.as_dict()["source_split_order"]
            == (
                "lateral_half,manning_friction_half,"
                "stage15_conservative_core_full,"
                "manning_friction_half,lateral_half"
            )
        ),
        "lateral_volume_is_applied_and_accounted": (
            zero_momentum.lateral_volume_change_m3 > 0.0
            and abs(zero_momentum.total_volume_ledger_error_m3)
            <= MASS_TOLERANCE_M3
        ),
        "zero_momentum_lateral_semantics_is_exact": (
            zero_momentum.lateral_momentum_change_magnitude_m4s <= 1e-12
        ),
        "matched_velocity_lateral_momentum_is_explicit": (
            matched_velocity.lateral_momentum_change_magnitude_m4s > 0.0
        ),
        "manning_friction_dissipates_each_positive_flow_reach": all(
            value.friction_longitudinal_momentum_change_m4s < 0.0
            for value in traces
        ),
        "east_source_split_momentum_ledger_closed": (
            abs(zero_momentum.geographic_momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "north_source_split_momentum_ledger_closed": (
            abs(zero_momentum.geographic_momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "matched_velocity_global_ledgers_close": (
            abs(matched_velocity.total_volume_ledger_error_m3)
            <= MASS_TOLERANCE_M3
            and matched_velocity.geographic_momentum_ledger_error_magnitude_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "stage15_opening_exchange_remains_conservative": (
            zero_momentum.conservative_core_step
            .maximum_opening_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
            and zero_momentum.conservative_core_step
            .maximum_opening_momentum_cancellation_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "lake_at_rest_preserves_primary_states": (
            lake["maximum_reach_state_error"] <= 1e-12
            and lake["junction_state_error"] <= 1e-12
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
        "rotation_covaries_source_momentum_vectors": (
            rotation["lateral_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
            and rotation["friction_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "multistep_states_remain_positive": (
            multistep["minimum_reach_area_m2"] > 0.0
            and multistep["minimum_junction_volume_m3"] > 0.0
        ),
        "multistep_source_ledgers_close": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "unsupported_contracts_fail_closed": all(refusals.values()),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "source_split_junction_reach_manufactured_invariants_pass_"
            "junction_cell_closure_and_public_validation_pending"
        ),
        "law": {
            "source_order": [
                "lateral_half",
                "manning_friction_half",
                "stage15_conservative_core_full",
                "manning_friction_half",
                "lateral_half",
            ],
            "lateral_momentum_conventions": [
                "zero_longitudinal_momentum",
                "matched_local_velocity",
            ],
            "friction_law": "implicit_flat_bed_Manning_drag_per_reach_cell",
            "opening_exchange": "unchanged_Stage15_two_dimensional_HLL",
            "fitted_parameters": [],
        },
        "zero_longitudinal_momentum_step": zero_momentum.as_dict(),
        "matched_local_velocity_step": matched_velocity.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage15_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "source_split_junction_reach_coupling_implemented": True,
            "lateral_volume_source_implemented": True,
            "explicit_lateral_momentum_semantics_implemented": True,
            "reach_manning_friction_implemented": True,
            "stage15_opening_exchange_preserved": True,
            "whole_system_source_mass_ledger_implemented": True,
            "whole_system_source_vector_momentum_ledger_implemented": True,
            "junction_cell_friction_implemented": False,
            "transverse_reservoir_feedback_implemented": False,
            "negative_lateral_flux_supported": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _step(cell, geometry, contract, network, reservoirs, convention):
    upstream, downstream, upstream_external, downstream_external = network
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "transverse_momentum": reservoirs,
        "lateral_momentum_convention": convention,
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell, geometry, contract, upstream, downstream, **common
    )
    return advance_source_split_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        lateral_momentum_convention=convention,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=COURANT_NUMBER,
    )


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    network = _network(
        discharges=(0.0, 0.0, 0.0), lateral=(0.0, 0.0, 0.0)
    )
    upstream, downstream, upstream_external, downstream_external = network
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "transverse_momentum": reservoirs,
        "lateral_momentum_convention": "zero_longitudinal_momentum",
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell, geometry, contract, upstream, downstream, **common
    )
    result = advance_source_split_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    before = (*tuple(value.state for value in upstream), downstream.state)
    after = (*result.upstream_states, result.downstream_state)
    reach_errors = [
        abs(actual - expected)
        for left, right in zip(before, after, strict=True)
        for actual, expected in (
            *zip(left.area_m2, right.area_m2, strict=True),
            *zip(left.discharge_m3s, right.discharge_m3s, strict=True),
        )
    ]
    cell_after = result.conservative_core_step.junction_cell_step.state_after
    return {
        "timestep_seconds": stable,
        "maximum_reach_state_error": max(reach_errors),
        "junction_state_error": math.sqrt(
            (cell_after.volume_m3 - cell.volume_m3) ** 2
            + cell_after.momentum_east_m4s**2
            + cell_after.momentum_north_m4s**2
        ),
        "mass_ledger_error_m3": abs(result.total_volume_ledger_error_m3),
        "momentum_ledger_error_m4s": (
            result.geographic_momentum_ledger_error_magnitude_m4s
        ),
    }


def _rotation_control() -> dict[str, Any]:
    rotation = ROTATION_DEGREES
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    network = _network()
    upstream, downstream, upstream_external, downstream_external = network
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    rotated_initial = _rotate_vector(12.0, -4.0, rotation)
    rotated_cell = ShallowWaterJunctionCellState(200.0, *rotated_initial)
    reservoirs = zero_terminal_transverse_momentum(contract)
    rotated_reservoirs = zero_terminal_transverse_momentum(rotated_contract)
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "lateral_momentum_convention": "matched_local_velocity",
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell, geometry, contract, upstream, downstream,
        transverse_momentum=reservoirs, **common
    )
    rotated_stable = maximum_source_split_coupled_junction_timestep_seconds(
        rotated_cell, rotated_geometry, rotated_contract, upstream, downstream,
        transverse_momentum=rotated_reservoirs, **common
    )
    timestep = 0.5 * min(stable, rotated_stable)
    common.pop("courant_number")
    baseline = advance_source_split_coupled_junction_reaches(
        cell, geometry, contract, upstream, downstream,
        transverse_momentum=reservoirs,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **common,
    )
    rotated = advance_source_split_coupled_junction_reaches(
        rotated_cell, rotated_geometry, rotated_contract, upstream, downstream,
        transverse_momentum=rotated_reservoirs,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **common,
    )
    scalar_errors = []
    for left, right in zip(
        (*baseline.upstream_states, baseline.downstream_state),
        (*rotated.upstream_states, rotated.downstream_state),
        strict=True,
    ):
        scalar_errors.extend(
            abs(a - b)
            for a, b in zip(left.area_m2, right.area_m2, strict=True)
        )
        scalar_errors.extend(
            abs(a - b)
            for a, b in zip(
                left.discharge_m3s, right.discharge_m3s, strict=True
            )
        )
    expected_lateral = _rotate_vector(
        baseline.lateral_momentum_change_east_m4s,
        baseline.lateral_momentum_change_north_m4s,
        rotation,
    )
    expected_friction = _rotate_vector(
        baseline.friction_momentum_change_east_m4s,
        baseline.friction_momentum_change_north_m4s,
        rotation,
    )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(stable - rotated_stable),
        "maximum_scalar_reach_error": max(scalar_errors),
        "lateral_momentum_rotation_error_m4s": math.hypot(
            rotated.lateral_momentum_change_east_m4s - expected_lateral[0],
            rotated.lateral_momentum_change_north_m4s - expected_lateral[1],
        ),
        "friction_momentum_rotation_error_m4s": math.hypot(
            rotated.friction_momentum_change_east_m4s - expected_friction[0],
            rotated.friction_momentum_change_north_m4s - expected_friction[1],
        ),
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    cell = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    minimum_area = 20.0
    minimum_volume = cell.volume_m3
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        network = upstream, downstream, upstream_external, downstream_external
        result = _step(
            cell, geometry, contract, network, reservoirs,
            "matched_local_velocity"
        )
        upstream = tuple(
            replace(reach, state=state)
            for reach, state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        cell = result.conservative_core_step.junction_cell_step.state_after
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
        "maximum_transverse_momentum_m4s": max(
            value.magnitude_m4s for value in reservoirs
        ),
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "transverse_momentum": reservoirs,
        "lateral_momentum_convention": "zero_longitudinal_momentum",
        "courant_number": COURANT_NUMBER,
    }
    results = {}
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell, geometry, contract, upstream, downstream, **common
    )
    try:
        advance_source_split_coupled_junction_reaches(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "source_split_coupled_junction_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False
    try:
        maximum_source_split_coupled_junction_timestep_seconds(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            lateral_momentum_convention="implicit",
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["implicit_lateral_momentum"] = str(exc) == (
            "source_split_coupled_junction_lateral_momentum_invalid"
        )
    else:
        results["implicit_lateral_momentum"] = False
    try:
        maximum_source_split_coupled_junction_timestep_seconds(
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
    return results


def _network(*, discharges=(5.0, 7.0, 12.0), lateral=(0.01, 0.02, 0.005)):
    upstream = (
        _reach("up-a", discharges[0], lateral[0]),
        _reach("up-b", discharges[1], lateral[1]),
    )
    downstream = _reach("down", discharges[2], lateral[2])
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


def _reach(branch_id, discharge, lateral):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState((20.0,) * 4, (discharge,) * 4),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (lateral,) * 4,
    )


def _geometry(*, rotation_degrees=0.0):
    width = 10.0

    def azimuth(value):
        return (value + rotation_degrees) % 360.0

    return ShallowWaterJunctionCellGeometry(
        "junction-y", 100.0, 0.0,
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
        "manufactured:stage16-closed-y-cell",
    )


def _contract(*, rotation_degrees=0.0):
    return ConservativeVectorJunctionContract(
        "junction-y", ("up-a", "up-b"), "down",
        tuple(
            (value + rotation_degrees) % 360.0
            for value in (45.0, 315.0)
        ),
        rotation_degrees % 360.0,
        "manufactured:stage16",
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
