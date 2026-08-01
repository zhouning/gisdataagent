#!/usr/bin/env python3
"""Compile Stage 20 spatial patch-friction source-split gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    coupled_junction_patch_reach_patch_friction as patch_friction,
)

try:
    from scripts.compile_geotransport_stage19_source_split_patch_reach_gates import (
        _contract,
        _geometry,
        _network,
        _rotate_vector,
        _state,
    )
except ModuleNotFoundError:
    from compile_geotransport_stage19_source_split_patch_reach_gates import (
        _contract,
        _geometry,
        _network,
        _rotate_vector,
        _state,
    )


JunctionPatchCellManningRoughness = (
    patch_friction.JunctionPatchCellManningRoughness
)
JunctionPatchManningRoughnessField = (
    patch_friction.JunctionPatchManningRoughnessField
)
advance_patch_friction_source_split = (
    patch_friction.advance_patch_friction_source_split
)
apply_junction_patch_manning_friction = (
    patch_friction.apply_junction_patch_manning_friction
)
maximum_patch_friction_source_split_timestep_seconds = (
    patch_friction.maximum_patch_friction_source_split_timestep_seconds
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage20_patch_friction_source_split_gates.json"
)
SCHEMA = "gwm.geotransport.stage20_patch_friction_source_split_gates.v1"
COURANT_NUMBER = 0.4
ROTATION_DEGREES = 37.0
MULTISTEP_COUNT = 20
MASS_TOLERANCE_M3 = 1e-8
MOMENTUM_TOLERANCE_M4S = 1e-9
ROTATION_TOLERANCE = 1e-11

FROZEN_STAGE19_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "coupled_junction_patch_reach_sources.py"
    ): (
        "df1fb5ffde1c0d43f7bc21bfe2f59b3a3409f9fc9267f520a8e1797e679dc8f8"
    ),
    (
        "data_agent/"
        "test_geospatial_kernel_coupled_junction_patch_reach_sources.py"
    ): (
        "dda7c6931e8925fcb0beededd3254c621fceae92445b732efe6e73fc13234409"
    ),
    (
        "scripts/"
        "compile_geotransport_stage19_source_split_patch_reach_gates.py"
    ): (
        "9f295955851d877c81a542ce90eddf57bc99f9875bb19561a2689f710326807e"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage19_source_split_coupled_junction_patch_reach_gates.json"
    ): (
        "fb6ee1987bf9dc9d3b5501f699834e12e20800ffc3c4c025d0aec092706d3ce4"
    ),
    (
        "docs/architecture-decisions/"
        "adr-060-source-split-multi-cell-patch-reach-coupling.md"
    ): (
        "4f874a7a9eb936761cfd0cfd57469d7c3c635823f77eed463fb6304666eb0f6e"
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
    roughness = _roughness(geometry)
    primitive = apply_junction_patch_manning_friction(
        state, geometry, roughness, timestep_seconds=1.0
    )
    coupled = _step(state, geometry, roughness, _contract(), _network())
    lake = _lake_control()
    rotation = _rotation_control()
    multistep = _multistep_control()
    refusals = _refusal_control()
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE19_HASHES.items()
    }
    stage19_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    roughness_report = roughness.as_dict()
    reach_sources = coupled.reach_source_split_step
    core = reach_sources.conservative_core_step
    gates = {
        "stage19_artifacts_hash_frozen": stage19_frozen,
        "roughness_field_has_exact_polygon_support": (
            roughness_report["spatial_support"]
            == "exact_junction_patch_cell_polygon"
            and tuple(value["cell_id"] for value in roughness_report["cells"])
            == tuple(value.cell_id for value in geometry.cells)
        ),
        "roughness_field_has_positive_finite_values": all(
            math.isfinite(value.manning_n) and value.manning_n > 0.0
            for value in roughness.cells
        ),
        "primitive_patch_friction_preserves_volume": (
            abs(primitive.volume_ledger_error_m3) <= MASS_TOLERANCE_M3
        ),
        "primitive_patch_friction_momentum_ledger_closes": (
            primitive.momentum_ledger_error_magnitude_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "primitive_patch_friction_dissipates_kinetic_energy": (
            primitive.kinetic_energy_dissipation_m5s2 > 0.0
            and all(
                value.kinetic_energy_dissipation_m5s2 >= 0.0
                for value in primitive.cell_traces
            )
        ),
        "primitive_patch_friction_preserves_vector_direction": all(
            _direction_preserved(before, after)
            for before, after in zip(
                primitive.state_before.cells,
                primitive.state_after.cells,
                strict=True,
            )
        ),
        "primitive_patch_friction_is_rotation_covariant": (
            rotation["primitive_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
            and rotation["primitive_energy_dissipation_error_m5s2"]
            <= ROTATION_TOLERANCE
        ),
        "source_adjusted_common_cfl_is_positive": (
            coupled.maximum_stable_timestep_seconds > 0.0
        ),
        "combined_whole_system_mass_ledger_closes": (
            abs(coupled.total_volume_ledger_error_m3) <= MASS_TOLERANCE_M3
        ),
        "combined_geographic_momentum_ledger_closes": (
            coupled.geographic_momentum_ledger_error_magnitude_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "combined_patch_friction_is_active_and_dissipative": (
            coupled.patch_friction_momentum_change_magnitude_m4s > 0.0
            and coupled.patch_kinetic_energy_dissipation_m5s2 > 0.0
        ),
        "stage19_lateral_and_reach_friction_sources_are_preserved": (
            reach_sources.lateral_volume_change_m3 > 0.0
            and reach_sources.lateral_momentum_change_magnitude_m4s > 0.0
            and reach_sources.friction_momentum_change_magnitude_m4s > 0.0
        ),
        "stage18_opening_vector_closure_is_preserved": (
            core.maximum_opening_momentum_closure_error_m4s
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "stage18_transition_reaction_remains_active": any(
            value.transverse_momentum_flux_magnitude_m4s2 > 1e-6
            for value in core.opening_exchanges
        ),
        "no_persistent_transverse_reservoir_is_reintroduced": (
            "transverse_momentum_after" not in coupled.as_dict()
        ),
        "lake_at_rest_preserves_patch_and_reaches": (
            lake["maximum_patch_state_error"] <= 1e-12
            and lake["maximum_reach_state_error"] <= 1e-12
            and lake["patch_kinetic_energy_dissipation_m5s2"] == 0.0
        ),
        "lake_at_rest_global_ledgers_close": (
            lake["mass_ledger_error_m3"] <= MASS_TOLERANCE_M3
            and lake["momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_coupled_scalar_reach_states": (
            rotation["maximum_scalar_reach_error"] <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_coupled_patch_state": (
            rotation["coupled_patch_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "rotation_covaries_patch_friction_impulse": (
            rotation["patch_friction_impulse_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
        ),
        "multistep_states_remain_positive": (
            multistep["minimum_reach_area_m2"] > 0.0
            and multistep["minimum_patch_cell_volume_m3"] > 0.0
        ),
        "multistep_ledgers_close_and_patch_friction_dissipates": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
            and multistep["total_patch_kinetic_energy_dissipation_m5s2"] > 0.0
        ),
        "unsupported_spatial_and_timestep_contracts_fail_closed": all(
            refusals.values()
        ),
        "candidate_remains_unadmitted": True,
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "spatial_patch_friction_source_split_invariants_pass_"
            "roughness_calibration_and_public_validation_pending"
        ),
        "law": {
            "patch_friction": (
                "semi_implicit_vector_Manning_drag_with_local_depth_radius"
            ),
            "roughness_support": "exact_patch_cell_polygon_and_geometry_vintage",
            "source_order": [
                "patch_friction_half",
                "lateral_and_reach_friction_half",
                "stage18_patch_reach_conservative_core_full",
                "reach_friction_and_lateral_half",
                "patch_friction_half",
            ],
            "fitted_parameters": [],
        },
        "roughness_field": roughness_report,
        "primitive_patch_friction_step": primitive.as_dict(),
        "combined_source_split_step": coupled.as_dict(),
        "lake_at_rest_control": lake,
        "rotation_control": rotation,
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage19_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "spatially_supported_patch_manning_friction_implemented": True,
            "semi_implicit_rotation_invariant_vector_drag_implemented": True,
            "patch_friction_energy_dissipation_audited": True,
            "stage19_reach_source_split_preserved": True,
            "stage18_transition_wall_reaction_preserved": True,
            "persistent_transverse_momentum_reservoir": False,
            "roughness_calibrated": False,
            "roughness_uncertainty_propagated": False,
            "variable_patch_bed_or_dry_fronts_supported": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _step(state, geometry, roughness, contract, network, *, fraction=0.5):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_patch_friction_source_split_timestep_seconds(
        state,
        geometry,
        roughness,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="matched_local_velocity",
        courant_number=COURANT_NUMBER,
    )
    return advance_patch_friction_source_split(
        state,
        geometry,
        roughness,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="matched_local_velocity",
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )


def _lake_control() -> dict[str, Any]:
    geometry = _geometry()
    state = _state(lake=True)
    network = _network(
        discharges=(0.0, 0.0, 0.0), lateral=(0.0, 0.0, 0.0)
    )
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_patch_friction_source_split_timestep_seconds(
        state,
        geometry,
        _roughness(geometry),
        _contract(),
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="zero_longitudinal_momentum",
        courant_number=COURANT_NUMBER,
    )
    result = advance_patch_friction_source_split(
        state,
        geometry,
        _roughness(geometry),
        _contract(),
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    patch_errors = []
    for before, after in zip(state.cells, result.patch_state_after.cells, strict=True):
        patch_errors.extend(
            (
                abs(after.volume_m3 - before.volume_m3),
                abs(after.momentum_east_m4s - before.momentum_east_m4s),
                abs(after.momentum_north_m4s - before.momentum_north_m4s),
            )
        )
    reach_errors = []
    for before, after in zip(
        (*(value.state for value in upstream), downstream.state),
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
        "timestep_seconds": stable,
        "maximum_patch_state_error": max(patch_errors),
        "maximum_reach_state_error": max(reach_errors),
        "patch_kinetic_energy_dissipation_m5s2": (
            result.patch_kinetic_energy_dissipation_m5s2
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
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    primitive = apply_junction_patch_manning_friction(
        state, geometry, _roughness(geometry), timestep_seconds=1.0
    )
    rotated_primitive = apply_junction_patch_manning_friction(
        rotated_state,
        rotated_geometry,
        _roughness(rotated_geometry),
        timestep_seconds=1.0,
    )
    primitive_errors = _patch_rotation_errors(
        primitive.state_after, rotated_primitive.state_after, rotation
    )
    network = _network()
    stable = _maximum(
        state, geometry, _roughness(geometry), _contract(), network
    )
    rotated_stable = _maximum(
        rotated_state,
        rotated_geometry,
        _roughness(rotated_geometry),
        _contract(rotation_degrees=rotation),
        network,
    )
    timestep = 0.5 * min(stable, rotated_stable)
    baseline = _advance_exact(
        state, geometry, _roughness(geometry), _contract(), network, timestep
    )
    rotated = _advance_exact(
        rotated_state,
        rotated_geometry,
        _roughness(rotated_geometry),
        _contract(rotation_degrees=rotation),
        network,
        timestep,
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
    coupled_patch_errors = _patch_rotation_errors(
        baseline.patch_state_after, rotated.patch_state_after, rotation
    )
    expected_impulse = _rotate_vector(
        baseline.patch_friction_momentum_change_east_m4s,
        baseline.patch_friction_momentum_change_north_m4s,
        rotation,
    )
    impulse_error = math.hypot(
        rotated.patch_friction_momentum_change_east_m4s - expected_impulse[0],
        rotated.patch_friction_momentum_change_north_m4s - expected_impulse[1],
    )
    return {
        "rotation_degrees": rotation,
        "stable_timestep_error_seconds": abs(stable - rotated_stable),
        "primitive_momentum_rotation_error_m4s": max(primitive_errors),
        "primitive_energy_dissipation_error_m5s2": abs(
            primitive.kinetic_energy_dissipation_m5s2
            - rotated_primitive.kinetic_energy_dissipation_m5s2
        ),
        "maximum_scalar_reach_error": max(scalar_errors),
        "coupled_patch_momentum_rotation_error_m4s": max(
            coupled_patch_errors
        ),
        "patch_friction_impulse_rotation_error_m4s": impulse_error,
    }


def _multistep_control() -> dict[str, Any]:
    geometry = _geometry()
    roughness = _roughness(geometry)
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    minimum_area = 20.0
    minimum_volume = min(value.volume_m3 for value in state.cells)
    total_dissipation = 0.0
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        result = _step(
            state,
            geometry,
            roughness,
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
        state = result.patch_state_after
        elapsed += result.timestep_seconds
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(minimum_volume, result.minimum_patch_cell_volume_m3)
        total_dissipation += result.patch_kinetic_energy_dissipation_m5s2
    return {
        "step_count": MULTISTEP_COUNT,
        "elapsed_seconds": elapsed,
        "minimum_reach_area_m2": minimum_area,
        "minimum_patch_cell_volume_m3": minimum_volume,
        "maximum_mass_ledger_error_m3": maximum_mass_error,
        "maximum_momentum_ledger_error_m4s": maximum_momentum_error,
        "total_patch_kinetic_energy_dissipation_m5s2": total_dissipation,
        "final_patch_state": state.as_dict(geometry),
    }


def _refusal_control() -> dict[str, bool]:
    geometry = _geometry()
    state = _state()
    roughness = _roughness(geometry)
    results = {}
    invalid_area = replace(
        roughness,
        cells=(
            replace(roughness.cells[0], support_area_m2=99.0),
            *roughness.cells[1:],
        ),
    )
    try:
        apply_junction_patch_manning_friction(
            state, geometry, invalid_area, timestep_seconds=1.0
        )
    except ValueError as exc:
        results["support_area"] = str(exc) == (
            "junction_patch_manning_support_area_mismatch"
        )
    else:
        results["support_area"] = False
    try:
        apply_junction_patch_manning_friction(
            state,
            geometry,
            replace(roughness, geometry_provenance_id="wrong"),
            timestep_seconds=1.0,
        )
    except ValueError as exc:
        results["geometry_provenance"] = str(exc) == (
            "junction_patch_manning_spatial_binding_mismatch"
        )
    else:
        results["geometry_provenance"] = False
    try:
        replace(roughness.cells[0], manning_n=0.0)
    except ValueError as exc:
        results["nonpositive_roughness"] = str(exc) == (
            "junction_patch_cell_manning_roughness_invalid"
        )
    else:
        results["nonpositive_roughness"] = False
    network = _network()
    stable = _maximum(state, geometry, roughness, _contract(), network)
    try:
        _advance_exact(
            state,
            geometry,
            roughness,
            _contract(),
            network,
            stable * 1.01,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "patch_friction_source_split_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False
    return results


def _roughness(geometry):
    values = (0.030, 0.035, 0.040, 0.045)
    return JunctionPatchManningRoughnessField(
        geometry.junction_id,
        geometry.provenance_id,
        tuple(
            JunctionPatchCellManningRoughness(
                cell.cell_id,
                value,
                geometry.cell_areas_m2[cell.cell_id],
                f"manufactured:stage20:{cell.cell_id}",
            )
            for cell, value in zip(geometry.cells, values, strict=True)
        ),
        "manufactured:stage20-spatial-roughness-field",
    )


def _maximum(state, geometry, roughness, contract, network):
    return maximum_patch_friction_source_split_timestep_seconds(
        state,
        geometry,
        roughness,
        contract,
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        courant_number=COURANT_NUMBER,
    )


def _advance_exact(state, geometry, roughness, contract, network, timestep):
    return advance_patch_friction_source_split(
        state,
        geometry,
        roughness,
        contract,
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )


def _patch_rotation_errors(baseline, rotated, angle):
    return tuple(
        math.hypot(
            actual.momentum_east_m4s - expected[0],
            actual.momentum_north_m4s - expected[1],
        )
        for actual, expected in (
            (
                actual,
                _rotate_vector(
                    before.momentum_east_m4s,
                    before.momentum_north_m4s,
                    angle,
                ),
            )
            for before, actual in zip(
                baseline.cells, rotated.cells, strict=True
            )
        )
    )


def _direction_preserved(before, after):
    cross = (
        before.momentum_east_m4s * after.momentum_north_m4s
        - before.momentum_north_m4s * after.momentum_east_m4s
    )
    dot = (
        before.momentum_east_m4s * after.momentum_east_m4s
        + before.momentum_north_m4s * after.momentum_north_m4s
    )
    return abs(cross) <= 1e-14 and dot >= 0.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
