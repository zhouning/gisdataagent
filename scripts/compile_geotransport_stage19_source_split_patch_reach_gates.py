#!/usr/bin/env python3
"""Compile Stage 19 source-split multi-cell patch/reach gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.coupled_junction_patch_reach_sources import (
    advance_source_split_coupled_junction_patch_reaches,
    maximum_source_split_coupled_junction_patch_timestep_seconds,
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

try:
    from scripts.compile_geotransport_stage18_coupled_patch_reach_gates import (
        _contract,
        _geometry,
        _rotate_vector,
        _state,
    )
except ModuleNotFoundError:
    from compile_geotransport_stage18_coupled_patch_reach_gates import (
        _contract,
        _geometry,
        _rotate_vector,
        _state,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage19_source_split_coupled_junction_patch_reach_gates.json"
)
SCHEMA = (
    "gwm.geotransport.stage19_source_split_coupled_junction_patch_reach_gates.v1"
)
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 20
MASS_TOLERANCE_M3 = 1e-8
MOMENTUM_TOLERANCE_M4S = 1e-9
ROTATION_TOLERANCE = 1e-11

FROZEN_STAGE18_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "coupled_junction_patch_reach.py"
    ): (
        "da5a5452e9796464bad1f222062468bfc477f5be61a44e97b9321b3896c9ae4b"
    ),
    (
        "data_agent/"
        "test_geospatial_kernel_coupled_junction_patch_reach.py"
    ): (
        "196e3cbe3b3be35668b93c742385e697ec767b0d740344d865b51f6029e3aeb2"
    ),
    (
        "scripts/"
        "compile_geotransport_stage18_coupled_patch_reach_gates.py"
    ): (
        "8ce27f5fc8db0532501c1bcb88470c73edb285ce69a69f13ad6b99c57ce47ee0"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage18_coupled_junction_patch_reach_gates.json"
    ): (
        "8603299364ac37246ecf419b3eaec3efa3f919c2f11df84c5668a8c64eb89d27"
    ),
    (
        "docs/architecture-decisions/"
        "adr-059-synchronous-patch-reach-transition-reaction.md"
    ): (
        "94a81aed229ee7d77055ab063207148c63b4fe8e168b961f5ba5bec7d1888f5f"
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
    zero_momentum = _step(
        state,
        geometry,
        contract,
        network,
        "zero_longitudinal_momentum",
    )
    matched_velocity = _step(
        state,
        geometry,
        contract,
        network,
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
        for relative, expected in FROZEN_STAGE18_HASHES.items()
    }
    stage18_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    traces = (
        *zero_momentum.upstream_source_traces,
        zero_momentum.downstream_source_trace,
    )
    core = zero_momentum.conservative_core_step
    gates = {
        "stage18_artifacts_hash_frozen": stage18_frozen,
        "source_adjusted_patch_reach_cfl_is_positive": (
            zero_momentum.maximum_stable_timestep_seconds > 0.0
        ),
        "strang_source_order_is_explicit": (
            zero_momentum.as_dict()["source_split_order"]
            == (
                "lateral_half,manning_friction_half,"
                "stage18_patch_reach_conservative_core_full,"
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
        "east_source_split_momentum_ledger_closes": (
            abs(zero_momentum.geographic_momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "north_source_split_momentum_ledger_closes": (
            abs(zero_momentum.geographic_momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "matched_velocity_global_ledgers_close": (
            abs(matched_velocity.total_volume_ledger_error_m3)
            <= MASS_TOLERANCE_M3
            and matched_velocity.geographic_momentum_ledger_error_magnitude_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "stage18_opening_mass_exchange_remains_conservative": (
            core.maximum_opening_mass_cancellation_error_m3
            <= MASS_TOLERANCE_M3
        ),
        "stage18_opening_vector_closure_remains_conservative": (
            core.maximum_opening_momentum_closure_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "transition_reaction_remains_active": any(
            value.transverse_momentum_flux_magnitude_m4s2 > 1e-6
            for value in core.opening_exchanges
        ),
        "no_persistent_transverse_reservoir_is_reintroduced": (
            "transverse_momentum_after" not in zero_momentum.as_dict()
        ),
        "lake_at_rest_preserves_patch_and_reaches": (
            lake["maximum_reach_state_error"] <= 1e-12
            and lake["maximum_patch_state_error"] <= 1e-12
        ),
        "lake_at_rest_global_ledgers_close": (
            lake["mass_ledger_error_m3"] <= MASS_TOLERANCE_M3
            and lake["momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_scalar_reach_states": (
            rotation["maximum_scalar_reach_error"] <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_source_momentum_vectors": (
            rotation["lateral_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
            and rotation["friction_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_transition_reaction": (
            rotation["transition_impulse_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "multistep_states_remain_positive": (
            multistep["minimum_reach_area_m2"] > 0.0
            and multistep["minimum_patch_cell_volume_m3"] > 0.0
        ),
        "multistep_source_ledgers_close_without_reservoir": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
            and multistep["persistent_transverse_state_observed"] is False
        ),
        "unsupported_contracts_fail_closed": all(refusals.values()),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "source_split_multi_cell_patch_reach_invariants_pass_"
            "patch_friction_and_public_validation_pending"
        ),
        "law": {
            "source_order": [
                "lateral_half",
                "manning_friction_half",
                "stage18_patch_reach_conservative_core_full",
                "manning_friction_half",
                "lateral_half",
            ],
            "lateral_momentum_conventions": [
                "zero_longitudinal_momentum",
                "matched_local_velocity",
            ],
            "friction_law": "implicit_flat_bed_Manning_drag_per_reach_cell",
            "opening_exchange": "unchanged_Stage18_shared_2d_HLL_flux",
            "transverse_closure": "unchanged_transition_wall_reaction",
            "fitted_parameters": [],
        },
        "zero_longitudinal_momentum_step": zero_momentum.as_dict(),
        "matched_local_velocity_step": matched_velocity.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage18_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "source_split_patch_reach_coupling_implemented": True,
            "stage18_opening_exchange_preserved": True,
            "lateral_volume_source_implemented": True,
            "explicit_lateral_momentum_semantics_implemented": True,
            "reach_manning_friction_implemented": True,
            "transition_wall_reaction_preserved": True,
            "persistent_transverse_momentum_reservoir": False,
            "patch_bed_friction_implemented": False,
            "uniform_flat_rectangular_reaches_only": True,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _step(state, geometry, contract, network, convention, *, fraction=0.5):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        courant_number=COURANT_NUMBER,
    )
    return advance_source_split_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    state = _state(lake=True)
    network = _network(
        discharges=(0.0, 0.0, 0.0), lateral=(0.0, 0.0, 0.0)
    )
    result = _step(
        state,
        geometry,
        contract,
        network,
        "zero_longitudinal_momentum",
        fraction=1.0,
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
    patch_errors = []
    for before, after in zip(
        state.cells,
        result.conservative_core_step.junction_patch_step.state_after.cells,
        strict=True,
    ):
        patch_errors.extend(
            (
                abs(after.volume_m3 - before.volume_m3),
                abs(after.momentum_east_m4s - before.momentum_east_m4s),
                abs(after.momentum_north_m4s - before.momentum_north_m4s),
            )
        )
    return {
        "timestep_seconds": result.timestep_seconds,
        "maximum_reach_state_error": max(reach_errors),
        "maximum_patch_state_error": max(patch_errors),
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
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "lateral_momentum_convention": "matched_local_velocity",
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state, geometry, contract, upstream, downstream, **common
    )
    rotated_stable = (
        maximum_source_split_coupled_junction_patch_timestep_seconds(
            rotated_state,
            rotated_geometry,
            rotated_contract,
            upstream,
            downstream,
            **common,
        )
    )
    timestep = 0.5 * min(stable, rotated_stable)
    advance_common = {
        key: value for key, value in common.items() if key != "courant_number"
    }
    baseline = advance_source_split_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **advance_common,
    )
    rotated = advance_source_split_coupled_junction_patch_reaches(
        rotated_state,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **advance_common,
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
    lateral_expected = _rotate_vector(
        baseline.lateral_momentum_change_east_m4s,
        baseline.lateral_momentum_change_north_m4s,
        rotation,
    )
    friction_expected = _rotate_vector(
        baseline.friction_momentum_change_east_m4s,
        baseline.friction_momentum_change_north_m4s,
        rotation,
    )
    transition_expected = _rotate_vector(
        baseline.transition_wall_fluid_impulse_east_m4s,
        baseline.transition_wall_fluid_impulse_north_m4s,
        rotation,
    )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(stable - rotated_stable),
        "maximum_scalar_reach_error": max(scalar_errors),
        "lateral_momentum_rotation_error_m4s": math.hypot(
            rotated.lateral_momentum_change_east_m4s - lateral_expected[0],
            rotated.lateral_momentum_change_north_m4s - lateral_expected[1],
        ),
        "friction_momentum_rotation_error_m4s": math.hypot(
            rotated.friction_momentum_change_east_m4s - friction_expected[0],
            rotated.friction_momentum_change_north_m4s - friction_expected[1],
        ),
        "transition_impulse_rotation_error_m4s": math.hypot(
            rotated.transition_wall_fluid_impulse_east_m4s
            - transition_expected[0],
            rotated.transition_wall_fluid_impulse_north_m4s
            - transition_expected[1],
        ),
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    maximum_transition = 0.0
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
            "matched_local_velocity",
        )
        upstream = tuple(
            replace(reach, state=next_state)
            for reach, next_state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        state = result.conservative_core_step.junction_patch_step.state_after
        elapsed += result.timestep_seconds
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        maximum_transition = max(
            maximum_transition,
            max(
                value.transverse_momentum_flux_magnitude_m4s2
                for value in result.conservative_core_step.opening_exchanges
            ),
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(
            minimum_volume,
            result.conservative_core_step
            .junction_patch_step.minimum_cell_volume_m3,
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
        "maximum_transverse_flux_m4s2": maximum_transition,
        "persistent_transverse_state_observed": persistent_state,
        "final_patch_state": state.as_dict(geometry),
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    results = {}
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="zero_longitudinal_momentum",
        courant_number=COURANT_NUMBER,
    )
    try:
        advance_source_split_coupled_junction_patch_reaches(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "source_split_coupled_junction_patch_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False
    try:
        maximum_source_split_coupled_junction_patch_timestep_seconds(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            lateral_momentum_convention="implicit",
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["lateral_momentum_semantics"] = str(exc) == (
            "source_split_coupled_junction_patch_lateral_momentum_invalid"
        )
    else:
        results["lateral_momentum_semantics"] = False
    invalid_section = TrapezoidalChannelSection(9.0, 0.0)
    try:
        maximum_source_split_coupled_junction_patch_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], sections=(invalid_section,) * 4), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            lateral_momentum_convention="zero_longitudinal_momentum",
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["reach_geometry"] = str(exc) == (
            "coupled_junction_patch_reach_"
            "uniform_rectangular_flat_contract_required"
        )
    else:
        results["reach_geometry"] = False
    return results


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


def _network(
    *,
    discharges=(5.0, 7.0, 12.0),
    lateral=(0.01, 0.02, 0.005),
):
    upstream = (
        _reach("up-a", discharges[0], lateral[0]),
        _reach("up-b", discharges[1], lateral[1]),
    )
    downstream = _reach("down", discharges[2], lateral[2])
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
