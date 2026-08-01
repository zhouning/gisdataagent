#!/usr/bin/env python3
"""Compile Stage 22 public roughness-ensemble uncertainty gates."""

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
    public_confluence_roughness_ensemble as uncertainty,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage22_center_hill_roughness_ensemble"
)
DEFAULT_ENSEMBLE_OUTPUT = DEFAULT_DATA_ROOT / "roughness_ensemble.json"
DEFAULT_PROPAGATION_OUTPUT = DEFAULT_DATA_ROOT / "friction_propagation.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage22_public_roughness_ensemble_gates.json"
)
SCHEMA = "gwm.geotransport.stage22_public_roughness_ensemble_gates.v1"
MASS_TOLERANCE_M3 = 1e-10
MOMENTUM_TOLERANCE_M4S = 1e-10
ROTATION_TOLERANCE = 1e-10
ROTATION_DEGREES = 37.0

FROZEN_STAGE21_HASHES = {
    (
        "scripts/acquire_geotransport_stage21_public_confluence_fixture.py"
    ): "e1c2ca9d78e80ac8f363b5e430f2724924318f76e5251959f62c33e63648068c",
    (
        "data_agent/uwm/geospatial_kernel_v2/public_confluence_fixture.py"
    ): "5319a34855f184c0e321e033e4d112aee60a0cd4b7b921ccd8d20de750f0bf4c",
    (
        "data_agent/test_acquire_geotransport_stage21_public_confluence_fixture.py"
    ): "d1468619f5bd5f07e96dc6a2257eb907a1691d62066dbd00352abb6885e2c77f",
    (
        "data_agent/test_geospatial_kernel_public_confluence_fixture.py"
    ): "3e766ec20d488e32fc53b39cab317603ac8388b3aa7cbc4567a4d4e27261e1ba",
    (
        "scripts/compile_geotransport_stage21_public_confluence_fixture_gates.py"
    ): "d4aa87f3b6db749ec9a447ec200eb632a226329779b7b03db124c231caa59125",
    (
        "benchmarks/geotransport_v0_1/stage21_public_confluence_fixture_gates.json"
    ): "a29cfef7af46d5bc6f518f9279cbe8cd715958dfd86f5d0ca6b404f6ef8da30b",
    (
        "docs/architecture-decisions/"
        "adr-062-bounded-public-confluence-spatial-fixture.md"
    ): "9e70672f00570155e2ff4fa2f9343ead6a75414a039c73cba09a15a9818b531e",
    (
        "data/geotransport_v0_1/stage21_center_hill_public_confluence/"
        "public_confluence_fixture.json"
    ): "80682b074867e26d6a1d84a3c1b1b5bf59c91d41efe9e49baa239b10ef146e5c",
    (
        "data/geotransport_v0_1/stage21_center_hill_public_confluence/"
        "acquisition_manifest.json"
    ): "bba4e55fd4b144b3b72a4fc7251011812d6febc1aca5b3768cce16e02bac81c7",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ensemble-output", type=Path, default=DEFAULT_ENSEMBLE_OUTPUT
    )
    parser.add_argument(
        "--propagation-output",
        type=Path,
        default=DEFAULT_PROPAGATION_OUTPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensemble = uncertainty.compile_public_confluence_roughness_ensemble()
    propagation = uncertainty.propagate_public_confluence_roughness_ensemble(
        ensemble
    )
    ensemble_artifact = _write_artifact(args.ensemble_output, ensemble.as_dict())
    propagation_artifact = _write_artifact(
        args.propagation_output, propagation.as_dict()
    )
    report = compile_report(
        ensemble=ensemble,
        propagation=propagation,
        ensemble_artifact=ensemble_artifact,
        propagation_artifact=propagation_artifact,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *,
    ensemble=None,
    propagation=None,
    ensemble_artifact: dict[str, object] | None = None,
    propagation_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ensemble is None:
        ensemble = uncertainty.compile_public_confluence_roughness_ensemble()
    if propagation is None:
        propagation = uncertainty.propagate_public_confluence_roughness_ensemble(
            ensemble
        )
    if ensemble_artifact is None:
        ensemble_artifact = _memory_artifact(
            DEFAULT_ENSEMBLE_OUTPUT, ensemble.as_dict()
        )
    if propagation_artifact is None:
        propagation_artifact = _memory_artifact(
            DEFAULT_PROPAGATION_OUTPUT, propagation.as_dict()
        )
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE21_HASHES.items()
    }
    member_by_id = {value.member_id: value.step for value in propagation.members}
    lower = member_by_id["joint_lower"]
    upper = member_by_id["joint_upper"]
    dissipation = {
        member_id: step.kinetic_energy_dissipation_m5s2
        for member_id, step in member_by_id.items()
    }
    changed_support_cells = [
        value.cell_id
        for value in ensemble.cells
        if abs(value.support_rule_center_difference) > 1e-12
    ]
    mixed_footprint_cells = [
        value.cell_id
        for value in ensemble.cells
        if len(value.footprint_class_area_fractions) > 1
    ]
    rotation = _rotation_control(ensemble)
    refusals = _refusal_control(ensemble)
    monotone_cells = all(
        lower_value.damping_factor >= upper_value.damping_factor
        and lower_value.kinetic_energy_dissipation_m5s2
        <= upper_value.kinetic_energy_dissipation_m5s2
        for lower_value, upper_value in zip(
            lower.cell_traces, upper.cell_traces, strict=True
        )
    )
    gates = {
        "stage21_artifacts_hash_frozen": all(
            value["expected_sha256"] == value["actual_sha256"]
            for value in frozen_hashes.values()
        ),
        "two_explicit_spatial_support_rules_are_compiled": (
            ensemble.as_dict()["spatial_support_rules"]
            == [
                uncertainty.SPATIAL_SUPPORT_RULE_POINT,
                uncertainty.SPATIAL_SUPPORT_RULE_FOOTPRINT,
            ]
        ),
        "pixel_footprints_cover_every_patch_cell": all(
            abs(value.footprint_coverage_fraction - 1.0) <= 1e-9
            for value in ensemble.cells
        ),
        "nearest_pixel_dependency_is_explicit": (
            sum(value.point_nearest_fallback for value in ensemble.cells) == 5
        ),
        "footprint_aggregation_exposes_mixed_class_support": (
            set(mixed_footprint_cells) == {"cell-00", "cell-04", "cell-05"}
        ),
        "support_rule_sensitivity_is_nonzero_and_localized": (
            set(changed_support_cells) == {"cell-00", "cell-04", "cell-05"}
        ),
        "joint_intervals_envelope_both_support_rules": all(
            value.joint_lower
            == min(value.point_lower, value.footprint_lower)
            and value.joint_upper
            == max(value.point_upper, value.footprint_upper)
            for value in ensemble.cells
        ),
        "eight_ordered_roughness_members_are_compiled": (
            tuple(ensemble.member_by_id) == uncertainty.ENSEMBLE_MEMBER_ORDER
        ),
        "every_member_preserves_exact_stage20_spatial_binding": all(
            member.geometry_provenance_id
            == ensemble.fixture.diagnostic_horizontal_geometry.provenance_id
            and all(
                abs(
                    value.support_area_m2
                    - ensemble.fixture.diagnostic_horizontal_geometry
                    .cell_areas_m2[value.cell_id]
                )
                <= 1e-9
                for value in member.cells
            )
            for member in ensemble.members
        ),
        "every_member_closes_mass_and_momentum_ledgers": all(
            abs(value.volume_ledger_error_m3) <= MASS_TOLERANCE_M3
            and value.momentum_ledger_error_magnitude_m4s
            <= MOMENTUM_TOLERANCE_M4S
            for value in member_by_id.values()
        ),
        "every_member_dissipates_kinetic_energy": all(
            value > 0.0 for value in dissipation.values()
        ),
        "joint_bounds_bracket_total_energy_dissipation": (
            dissipation["joint_lower"] == min(dissipation.values())
            and dissipation["joint_upper"] == max(dissipation.values())
        ),
        "joint_bounds_are_cellwise_dissipation_monotone": monotone_cells,
        "support_rule_difference_propagates_to_friction_response": (
            dissipation["point_center"]
            != dissipation["footprint_center"]
        ),
        "ensemble_propagation_is_rotation_covariant": (
            rotation["maximum_momentum_rotation_error_m4s"]
            <= ROTATION_TOLERANCE
            and rotation["maximum_energy_rotation_error_m5s2"]
            <= ROTATION_TOLERANCE
        ),
        "unsupported_class_and_state_contracts_fail_closed": all(
            refusals.values()
        ),
        "diagnostic_state_is_not_misrepresented_as_observation": (
            propagation.as_dict()["diagnostic_state_is_observed"] is False
        ),
        "runtime_hydraulic_admission_remains_closed": (
            ensemble.as_dict()["runtime_hydraulic_geometry_admitted"]
            is False
        ),
        "roughness_ensemble_remains_uncalibrated": (
            ensemble.as_dict()["roughness_calibrated"] is False
        ),
        "candidate_operator_remains_unadmitted": (
            ensemble.as_dict()["operator_admitted"] is False
            and propagation.as_dict()["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "public_roughness_support_and_parameter_uncertainty_propagated_"
            "runtime_hydraulic_admission_pending"
        ),
        "ensemble_artifact": ensemble_artifact,
        "propagation_artifact": propagation_artifact,
        "frozen_stage21_hashes": frozen_hashes,
        "spatial_support_summary": {
            "native_pixel_size_m": 30.0,
            "resampled_pixel_width_m": ensemble.land_cover_pixel_width_m,
            "resampled_pixel_height_m": ensemble.land_cover_pixel_height_m,
            "resampled_pixel_area_m2": ensemble.land_cover_pixel_area_m2,
            "patch_cell_count": len(ensemble.cells),
            "nearest_pixel_fallback_cell_count": sum(
                value.point_nearest_fallback for value in ensemble.cells
            ),
            "mixed_footprint_cells": mixed_footprint_cells,
            "support_sensitive_cells": changed_support_cells,
        },
        "roughness_summary": {
            "ensemble_member_order": list(
                uncertainty.ENSEMBLE_MEMBER_ORDER
            ),
            "cell_joint_intervals": {
                value.cell_id: [value.joint_lower, value.joint_upper]
                for value in ensemble.cells
            },
            "maximum_support_rule_center_difference": max(
                abs(value.support_rule_center_difference)
                for value in ensemble.cells
            ),
        },
        "propagation_summary": {
            "timestep_seconds": propagation.timestep_seconds,
            "diagnostic_state_is_observed": False,
            "energy_dissipation_m5s2_by_member": dissipation,
            "energy_dissipation_envelope_m5s2": [
                min(dissipation.values()),
                max(dissipation.values()),
            ],
            "maximum_mass_ledger_error_m3": max(
                abs(value.volume_ledger_error_m3)
                for value in member_by_id.values()
            ),
            "maximum_momentum_ledger_error_m4s": max(
                value.momentum_ledger_error_magnitude_m4s
                for value in member_by_id.values()
            ),
        },
        "rotation_control": rotation,
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "public_land_cover_support_uncertainty_propagated": True,
            "roughness_lookup_uncertainty_propagated": True,
            "diagnostic_state_observed": False,
            "bathymetry_uncertainty_propagated": False,
            "roughness_calibrated": False,
            "runtime_hydraulic_geometry_admitted": False,
            "public_vector_momentum_validation_completed": False,
            "operator_admitted": False,
        },
    }


def _rotation_control(ensemble) -> dict[str, float]:
    angle = math.radians(ROTATION_DEGREES)
    cosine = math.cos(angle)
    sine = math.sin(angle)

    def rotate(east: float, north: float) -> tuple[float, float]:
        return (
            east * cosine - north * sine,
            east * sine + north * cosine,
        )

    geometry = ensemble.fixture.diagnostic_horizontal_geometry
    rotated_geometry = replace(
        geometry,
        vertices=tuple(
            replace(
                value,
                east_m=rotate(value.east_m, value.north_m)[0],
                north_m=rotate(value.east_m, value.north_m)[1],
            )
            for value in geometry.vertices
        ),
        provenance_id=f"{geometry.provenance_id}:rotation-control",
    )
    rotated_fixture = replace(
        ensemble.fixture, diagnostic_horizontal_geometry=rotated_geometry
    )
    rotated_ensemble = replace(
        ensemble,
        fixture=rotated_fixture,
        members=tuple(
            replace(
                value, geometry_provenance_id=rotated_geometry.provenance_id
            )
            for value in ensemble.members
        ),
    )
    state = uncertainty.diagnostic_patch_state(ensemble)
    rotated_state = replace(
        state,
        cells=tuple(
            replace(
                value,
                momentum_east_m4s=rotate(
                    value.momentum_east_m4s, value.momentum_north_m4s
                )[0],
                momentum_north_m4s=rotate(
                    value.momentum_east_m4s, value.momentum_north_m4s
                )[1],
            )
            for value in state.cells
        ),
    )
    baseline = uncertainty.propagate_public_confluence_roughness_ensemble(
        ensemble, state=state
    )
    rotated = uncertainty.propagate_public_confluence_roughness_ensemble(
        rotated_ensemble, state=rotated_state
    )
    momentum_errors = []
    energy_errors = []
    for expected, actual in zip(
        baseline.members, rotated.members, strict=True
    ):
        energy_errors.append(
            abs(
                expected.step.kinetic_energy_dissipation_m5s2
                - actual.step.kinetic_energy_dissipation_m5s2
            )
        )
        for expected_cell, actual_cell in zip(
            expected.step.state_after.cells,
            actual.step.state_after.cells,
            strict=True,
        ):
            target = rotate(
                expected_cell.momentum_east_m4s,
                expected_cell.momentum_north_m4s,
            )
            momentum_errors.append(
                math.hypot(
                    actual_cell.momentum_east_m4s - target[0],
                    actual_cell.momentum_north_m4s - target[1],
                )
            )
    return {
        "rotation_degrees": ROTATION_DEGREES,
        "maximum_momentum_rotation_error_m4s": max(momentum_errors),
        "maximum_energy_rotation_error_m5s2": max(energy_errors),
    }


def _refusal_control(ensemble) -> dict[str, bool]:
    results = {}
    try:
        uncertainty._roughness_interval(((999, 1.0),))
    except ValueError as exc:
        results["unmapped_class"] = str(exc) == (
            "public_roughness_land_cover_class_unmapped:999"
        )
    else:
        results["unmapped_class"] = False
    state = uncertainty.diagnostic_patch_state(ensemble)
    try:
        uncertainty.propagate_public_confluence_roughness_ensemble(
            ensemble, state=replace(state, cells=tuple(reversed(state.cells)))
        )
    except ValueError as exc:
        results["state_order"] = str(exc) == (
            "public_roughness_propagation_state_mismatch"
        )
    else:
        results["state_order"] = False
    try:
        uncertainty.propagate_public_confluence_roughness_ensemble(
            ensemble, timestep_seconds=0.0
        )
    except ValueError as exc:
        results["timestep"] = str(exc) == (
            "public_roughness_propagation_timestep_invalid"
        )
    else:
        results["timestep"] = False
    return results


def _write_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _memory_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
