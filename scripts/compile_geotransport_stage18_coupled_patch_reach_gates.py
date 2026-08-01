#!/usr/bin/env python3
"""Compile Stage 18 synchronous multi-cell patch/1D-reach gates."""

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
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_patch_reach import (
    advance_coupled_junction_patch_reaches,
    maximum_coupled_junction_patch_reach_timestep_seconds,
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
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_patch import (
    JunctionPatchCellState,
    ShallowWaterJunctionPatchState,
)
try:
    from scripts.compile_geotransport_stage17_junction_patch_gates import (
        _geometry,
        _rotate_vector,
    )
except ModuleNotFoundError:
    from compile_geotransport_stage17_junction_patch_gates import (
        _geometry,
        _rotate_vector,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage18_coupled_junction_patch_reach_gates.json"
)
SCHEMA = "gwm.geotransport.stage18_coupled_junction_patch_reach_gates.v1"
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 25
MASS_TOLERANCE_M3 = 1e-8
MOMENTUM_TOLERANCE_M4S = 1e-9
ROTATION_TOLERANCE = 1e-11

FROZEN_STAGE17_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/shallow_water_junction_patch.py": (
        "55c4ae72ed54e851f7ddac98007d886dbfb25c27ec2143aaf3ad65963261f467"
    ),
    "data_agent/test_geospatial_kernel_shallow_water_junction_patch.py": (
        "47e554eb596587550ad041826ae9d9e6a8416295d2e4d82114e2533bf877c80d"
    ),
    "scripts/compile_geotransport_stage17_junction_patch_gates.py": (
        "b211f20133e20ae91409becc319137c9713a0724c6be4087f4c8df1d4f009ea0"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage17_shallow_water_junction_patch_gates.json"
    ): (
        "41a5fa947bcd1cbef458640fe4503a5c6292777f9102e069a4ecd7847c3e3536"
    ),
    (
        "docs/architecture-decisions/"
        "adr-058-conforming-multi-cell-junction-patch.md"
    ): (
        "a665339766412cac750e1a0c473d92d4ce7e60128d8fb9804d950ba333685e60"
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
    state = _state()
    baseline = _step(state, geometry, contract, network)
    lake = _lake_control()
    rotation = _rotation_control()
    multistep = _multistep_control()
    refusals = _refusal_control()
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE17_HASHES.items()
    }
    stage17_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    exchanges = baseline.opening_exchanges
    gates = {
        "stage17_artifacts_hash_frozen": stage17_frozen,
        "common_patch_reach_cfl_timestep_is_positive": (
            baseline.maximum_stable_timestep_seconds > 0.0
        ),
        "whole_system_mass_ledger_closes": (
            abs(baseline.total_volume_ledger_error_m3) <= MASS_TOLERANCE_M3
        ),
        "east_geographic_momentum_ledger_closes": (
            abs(baseline.geographic_momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "north_geographic_momentum_ledger_closes": (
            abs(baseline.geographic_momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "internal_patch_exchange_remains_conservative": (
            baseline.junction_patch_step.maximum_internal_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
            and baseline.junction_patch_step
            .maximum_internal_momentum_cancellation_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "opening_mass_impulses_cancel": (
            baseline.maximum_opening_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
        ),
        "opening_vector_impulses_close_with_transition_reaction": (
            baseline.maximum_opening_momentum_closure_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "nonzero_transverse_opening_flux_is_exercised": any(
            value.transverse_momentum_flux_magnitude_m4s2 > 1e-6
            for value in exchanges
        ),
        "fluid_and_structure_transition_impulses_are_opposite": all(
            abs(
                value.transition_wall_fluid_impulse_east_m4s
                + value.transition_wall_structure_reaction_east_m4s
            ) <= MOMENTUM_TOLERANCE_M4S
            and abs(
                value.transition_wall_fluid_impulse_north_m4s
                + value.transition_wall_structure_reaction_north_m4s
            ) <= MOMENTUM_TOLERANCE_M4S
            for value in exchanges
        ),
        "patch_and_reach_states_update_synchronously": (
            baseline.junction_patch_step.state_after != state
            and baseline.upstream_states
            != tuple(value.state for value in network[0])
            and baseline.downstream_state != network[1].state
        ),
        "lake_at_rest_preserves_patch_and_reaches": (
            lake["maximum_patch_state_error"] <= 1e-12
            and lake["maximum_reach_state_error"] <= 1e-12
            and lake["maximum_transverse_flux_m4s2"] <= 1e-12
        ),
        "lake_at_rest_global_ledgers_close": (
            lake["mass_ledger_error_m3"] <= MASS_TOLERANCE_M3
            and lake["momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_scalar_reach_states": (
            rotation["maximum_scalar_reach_error"] <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_every_patch_cell_momentum": (
            rotation["maximum_patch_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_transition_wall_impulses": (
            rotation["maximum_transition_impulse_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "multistep_primary_states_remain_positive": (
            multistep["minimum_reach_area_m2"] > 0.0
            and multistep["minimum_patch_cell_volume_m3"] > 0.0
        ),
        "multistep_global_ledgers_close": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "multistep_has_no_persistent_transverse_reservoir": (
            multistep["persistent_transverse_state_observed"] is False
            and multistep["maximum_transverse_flux_m4s2"] > 1e-6
        ),
        "unsupported_contracts_fail_closed": all(refusals.values()),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "synchronous_multi_cell_patch_reach_invariants_pass_"
            "source_splitting_and_public_validation_pending"
        ),
        "law": {
            "patch_state": [
                "per_cell_water_volume_m3",
                "per_cell_east_momentum_m4s",
                "per_cell_north_momentum_m4s",
            ],
            "reach_state": [
                "cross_section_area_m2",
                "longitudinal_discharge_m3s",
            ],
            "opening_exchange": "one_shared_2d_HLL_flux_per_opening",
            "one_dimensional_projection": "dot(vector_momentum_flux,tangent)",
            "transverse_closure": "instantaneous_transition_wall_reaction",
            "persistent_transverse_storage": False,
            "external_forces": [
                "patch_solid_wall_hydrostatic_pressure",
                "2d_to_1d_transition_wall_reaction",
            ],
            "fitted_parameters": [],
        },
        "baseline_step": baseline.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage17_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "synchronous_multi_cell_patch_reach_coupling_implemented": True,
            "whole_system_mass_ledger_implemented": True,
            "whole_system_two_component_momentum_ledger_implemented": True,
            "complete_opening_vector_flux_audited": True,
            "instantaneous_transition_wall_reaction_implemented": True,
            "persistent_transverse_momentum_reservoir": False,
            "transition_reaction_feedback_to_flux": False,
            "source_split_reach_coupling_integrated": False,
            "uniform_flat_rectangular_reaches_only": True,
            "variable_bed_or_dry_fronts_supported": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _step(state, geometry, contract, network, *, fraction=0.5):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    return advance_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    state = _state(lake=True)
    network = _network(discharges=(0.0, 0.0, 0.0))
    result = _step(state, geometry, contract, network, fraction=1.0)
    patch_errors = []
    for before, after in zip(
        state.cells, result.junction_patch_step.state_after.cells, strict=True
    ):
        patch_errors.extend(
            (
                abs(after.volume_m3 - before.volume_m3),
                abs(after.momentum_east_m4s - before.momentum_east_m4s),
                abs(after.momentum_north_m4s - before.momentum_north_m4s),
            )
        )
    reach_errors = []
    for before, after in zip(
        (*(value.state for value in network[0]), network[1].state),
        (*result.upstream_states, result.downstream_state),
        strict=True,
    ):
        reach_errors.extend(
            abs(actual - expected)
            for actual, expected in zip(
                (*after.area_m2, *after.discharge_m3s),
                (*before.area_m2, *before.discharge_m3s),
                strict=True,
            )
        )
    return {
        "timestep_seconds": result.timestep_seconds,
        "maximum_patch_state_error": max(patch_errors),
        "maximum_reach_state_error": max(reach_errors),
        "maximum_transverse_flux_m4s2": max(
            value.transverse_momentum_flux_magnitude_m4s2
            for value in result.opening_exchanges
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
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    network = _network()
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    rotated_stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        rotated_state, rotated_geometry, rotated_contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(stable, rotated_stable)
    baseline = advance_coupled_junction_patch_reaches(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_coupled_junction_patch_reaches(
        rotated_state, rotated_geometry, rotated_contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    scalar_errors = []
    for before, after in zip(
        (*baseline.upstream_states, baseline.downstream_state),
        (*rotated.upstream_states, rotated.downstream_state),
        strict=True,
    ):
        scalar_errors.extend(
            abs(actual - expected)
            for actual, expected in zip(
                (*after.area_m2, *after.discharge_m3s),
                (*before.area_m2, *before.discharge_m3s),
                strict=True,
            )
        )
    patch_errors = []
    for before, after in zip(
        baseline.junction_patch_step.state_after.cells,
        rotated.junction_patch_step.state_after.cells,
        strict=True,
    ):
        expected = _rotate_vector(
            before.momentum_east_m4s,
            before.momentum_north_m4s,
            rotation,
        )
        patch_errors.append(
            math.hypot(
                after.momentum_east_m4s - expected[0],
                after.momentum_north_m4s - expected[1],
            )
        )
    transition_errors = []
    for before, after in zip(
        baseline.opening_exchanges, rotated.opening_exchanges, strict=True
    ):
        expected = _rotate_vector(
            before.transition_wall_fluid_impulse_east_m4s,
            before.transition_wall_fluid_impulse_north_m4s,
            rotation,
        )
        transition_errors.append(
            math.hypot(
                after.transition_wall_fluid_impulse_east_m4s - expected[0],
                after.transition_wall_fluid_impulse_north_m4s - expected[1],
            )
        )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(stable - rotated_stable),
        "maximum_scalar_reach_error": max(scalar_errors),
        "maximum_patch_momentum_rotation_error_m4s": max(patch_errors),
        "maximum_transition_impulse_rotation_error_m4s": max(transition_errors),
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    maximum_transverse = 0.0
    minimum_area = min(
        min(value.state.area_m2) for value in (*upstream, downstream)
    )
    minimum_volume = min(value.volume_m3 for value in state.cells)
    persistent_state = False
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        result = _step(
            state,
            geometry,
            contract,
            (upstream, downstream, upstream_external, downstream_external),
        )
        upstream = tuple(
            replace(reach, state=next_state)
            for reach, next_state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        state = result.junction_patch_step.state_after
        elapsed += result.timestep_seconds
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        maximum_transverse = max(
            maximum_transverse,
            max(
                value.transverse_momentum_flux_magnitude_m4s2
                for value in result.opening_exchanges
            ),
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(
            minimum_volume, result.junction_patch_step.minimum_cell_volume_m3
        )
        persistent_state = persistent_state or (
            "transverse_momentum_after" in result.as_dict()
        )
    return {
        "step_count": MULTISTEP_COUNT,
        "elapsed_seconds": elapsed,
        "minimum_reach_area_m2": minimum_area,
        "minimum_patch_cell_volume_m3": minimum_volume,
        "maximum_mass_ledger_error_m3": maximum_mass_error,
        "maximum_momentum_ledger_error_m4s": maximum_momentum_error,
        "maximum_transverse_flux_m4s2": maximum_transverse,
        "persistent_transverse_state_observed": persistent_state,
        "final_patch_state": state.as_dict(geometry),
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    results = {}
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    try:
        advance_coupled_junction_patch_reaches(
            state, geometry, contract, upstream, downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "coupled_junction_patch_reach_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False
    try:
        maximum_coupled_junction_patch_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], reach_id="wrong"), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["branch_binding"] = str(exc) == (
            "coupled_junction_patch_reach_branch_binding_mismatch"
        )
    else:
        results["branch_binding"] = False
    invalid_section = TrapezoidalChannelSection(9.0, 0.0)
    try:
        maximum_coupled_junction_patch_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], sections=(invalid_section,) * 4), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["reach_geometry"] = str(exc) == (
            "coupled_junction_patch_reach_uniform_rectangular_flat_contract_required"
        )
    else:
        results["reach_geometry"] = False
    invalid_external = replace(
        downstream_external,
        bed_elevation_m=1.0,
    )
    try:
        maximum_coupled_junction_patch_reach_timestep_seconds(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=invalid_external,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["external_boundary"] = str(exc) == (
            "coupled_junction_patch_reach_external_boundary_not_supported"
        )
    else:
        results["external_boundary"] = False
    return results


def _state(*, lake=False, rotation_degrees=0.0):
    values = (
        ("sw", 200.0, 7.0, 3.0),
        ("se", 200.0, 5.0, -4.0),
        ("nw", 190.0, 6.0, 8.0),
        ("ne", 210.0, -2.0, -3.0),
    )
    if lake:
        values = tuple((cell_id, 200.0, 0.0, 0.0) for cell_id, *_ in values)
    return ShallowWaterJunctionPatchState(
        tuple(
            JunctionPatchCellState(
                cell_id,
                volume,
                *_rotate_vector(east, north, rotation_degrees),
            )
            for cell_id, volume, east, north in values
        )
    )


def _contract(*, rotation_degrees=0.0):
    return ConservativeVectorJunctionContract(
        "junction-grid",
        ("up-a", "up-b"),
        "down",
        (
            (90.0 + rotation_degrees) % 360.0,
            rotation_degrees % 360.0,
        ),
        (90.0 + rotation_degrees) % 360.0,
        "manufactured:stage18",
    )


def _reach(branch_id, discharge):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState((20.0,) * 4, (discharge,) * 4),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (0.0,) * 4,
    )


def _network(*, discharges=(5.0, 7.0, 12.0)):
    upstream = (
        _reach("up-a", discharges[0]),
        _reach("up-b", discharges[1]),
    )
    downstream = _reach("down", discharges[2])
    upstream_external = tuple(
        FixedDynamicWaveBoundary(DynamicWaveCellState(20.0, value), 0.0)
        for value in discharges[:2]
    )
    downstream_external = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, discharges[2]), 0.0
    )
    return upstream, downstream, upstream_external, downstream_external


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
