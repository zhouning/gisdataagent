#!/usr/bin/env python3
"""Compile Stage 24 public reach geometry-stability gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_geometry_stability as stability,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage24_center_hill_reach_geometry_stability"
)
DEFAULT_AUDIT_OUTPUT = DEFAULT_DATA_ROOT / "reach_geometry_stability_audit.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage24_public_reach_geometry_stability_gates.json"
)
SCHEMA = "gwm.geotransport.stage24_public_reach_geometry_stability_gates.v1"

FROZEN_STAGE23_HASHES = {
    (
        "scripts/acquire_geotransport_stage23_usgs_channel_measurements.py"
    ): "e77eb8b89eb42b002d201190025ce87a488c648b5e73b699c67fac66830c55e7",
    (
        "scripts/compile_geotransport_stage23_public_reach_hydraulic_gates.py"
    ): "9a046cc786ef99efe34bab4f91ac056d4a2f369699f829224309378d5331e6bb",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_reach_hydraulic_measurements.py"
    ): "45b9c440bcd690bf5a2aeea629199bb01b701cc3d51c0a8f9991e0068e7d4754",
    (
        "data_agent/test_acquire_geotransport_stage23_usgs_channel_measurements.py"
    ): "dc852b66877bc0e2bb28d161f7df15e290dfe20a1daddda94ac7b83ddd3e3949",
    (
        "data_agent/test_geospatial_kernel_public_reach_hydraulic_measurements.py"
    ): "52f0d04c3351671ec327352cf5666e625167682333fa57bf3f75d23d04f0fbb8",
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/acquisition_manifest.json"
    ): "fee1c83979c8e03fc4ae692a9fa44a3437f0c099f270d01550bb14799cbb57c8",
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/"
        "public_reach_hydraulic_measurements.json"
    ): "1aa43986eae52d49dc666b218edd14866f1ebb15d10ad1c04f72cb78f6346849",
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/README.md"
    ): "82160f31aba27414287e069b27e4b62bd53c2e31d9505b5c3247d9f1a76a641b",
    (
        "benchmarks/geotransport_v0_1/"
        "stage23_public_reach_hydraulic_gates.json"
    ): "60149e1102bd5f2843d19df58b483b11e74448c7048a455898f0d265b030ae0e",
    (
        "docs/architecture-decisions/"
        "adr-064-public-reach-observed-hydraulic-state-binding.md"
    ): "a9ba4b02c7feb98b1755f86ec2df661a5937301020bc45564ad6a9908d80df30",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = stability.compile_public_reach_geometry_stability_audit()
    audit_artifact = _write_artifact(args.audit_output, audit.as_dict())
    report = compile_report(audit=audit, audit_artifact=audit_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, audit=None, audit_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if audit is None:
        audit = stability.compile_public_reach_geometry_stability_audit()
    audit_dict = audit.as_dict()
    if audit_artifact is None:
        audit_artifact = _memory_artifact(DEFAULT_AUDIT_OUTPUT, audit_dict)
    frozen_stage23 = _frozen_hash_report(FROZEN_STAGE23_HASHES)
    cohorts = audit.cohort_measurement_ids
    all_ids = [item for values in cohorts.values() for item in values]
    candidate = audit.candidate
    development = audit.development
    temporal = audit.temporal_holdout
    method_spatial = audit.method_spatial_holdout
    refusals = _refusal_control(audit)
    stage_minimum, stage_maximum = candidate.training_stage_range_m
    structural_errors = []
    for index in range(101):
        stage = stage_minimum + (stage_maximum - stage_minimum) * index / 100
        _, width = candidate.predict(stage)
        structural_errors.append(
            abs(candidate.derivative_width_m(stage) - width)
        )
    gates = {
        "stage23_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage23.values()
        ),
        "all_110_observations_are_partitioned": (
            len(all_ids) == 110 and len(set(all_ids)) == 110
        ),
        "development_temporal_and_method_cohorts_are_disjoint": (
            set(cohorts["development"]).isdisjoint(cohorts["temporal_holdout"])
            and set(cohorts["development"]).isdisjoint(
                cohorts["method_spatial_holdout"]
            )
            and set(cohorts["temporal_holdout"]).isdisjoint(
                cohorts["method_spatial_holdout"]
            )
        ),
        "fifty_five_pre_2023_bridge_adcp_records_form_development": (
            len(cohorts["development"]) == 55
            and development.time_range[1] < stability.TEMPORAL_HOLDOUT_START
        ),
        "twenty_post_2023_bridge_adcp_records_form_temporal_holdout": (
            len(cohorts["temporal_holdout"]) == 20
            and temporal.time_range[0] >= stability.TEMPORAL_HOLDOUT_START
        ),
        "method_spatial_holdout_is_evaluated_inside_stage_support": (
            len(cohorts["method_spatial_holdout"]) == 25
            and method_spatial.measurement_count == 17
            and len(audit.method_holdout_outside_stage_support_ids) == 8
            and method_spatial.stage_range_m[0] >= stage_minimum
            and method_spatial.stage_range_m[1] <= stage_maximum
        ),
        "simultaneous_component_channels_are_excluded_from_training": (
            len(cohorts["simultaneous_component_channels"]) == 2
            and set(cohorts["simultaneous_component_channels"]).isdisjoint(
                candidate.training_measurement_ids
            )
        ),
        "provisional_stage_is_retained_but_excluded_from_training": (
            len(cohorts["provisional_primary"]) == 1
            and set(cohorts["provisional_primary"]).isdisjoint(
                candidate.training_measurement_ids
            )
        ),
        "candidate_has_positive_physical_trapezoid_parameters": (
            candidate.section.bottom_width_m > 0.0
            and candidate.section.side_slope_horizontal_per_vertical > 0.0
            and candidate.zero_area_gage_height_m < stage_minimum
            and all(
                math.isfinite(value)
                for value in (
                    candidate.section.bottom_width_m,
                    candidate.section.side_slope_horizontal_per_vertical,
                    candidate.zero_area_gage_height_m,
                )
            )
        ),
        "joint_candidate_enforces_dA_dH_equals_top_width": (
            max(structural_errors) <= 1e-12
        ),
        "area_only_derivative_audit_does_not_fit_observed_width": (
            audit_dict["independent_area_derivative_audit"][
                "observed_width_used_during_fit"
            ]
            is False
        ),
        "development_accuracy_thresholds_pass": development.accuracy_passed,
        "temporal_holdout_accuracy_thresholds_pass": temporal.accuracy_passed,
        "temporal_holdout_has_no_training_identity_leakage": (
            set(cohorts["temporal_holdout"]).isdisjoint(
                candidate.training_measurement_ids
            )
        ),
        "method_spatial_transfer_is_empirically_rejected": (
            method_spatial.accuracy_passed is False
        ),
        "method_spatial_rejection_is_material_in_area_width_and_derivative": (
            method_spatial.area_median_absolute_percentage_error > 2.0
            and method_spatial.width_median_absolute_percentage_error > 0.15
            and method_spatial.derivative_width_median_absolute_percentage_error
            > 0.20
        ),
        "gage_datum_and_inferred_zero_area_stage_are_not_bed_survey": (
            audit_dict["claim_boundary"][
                "gage_height_treated_as_bed_referenced_depth"
            ]
            is False
            and audit_dict["claim_boundary"][
                "zero_area_stage_is_surveyed_bed_elevation"
            ]
            is False
        ),
        "unsupported_geometry_claims_fail_closed": all(refusals.values()),
        "runtime_and_reach_wide_geometry_admission_remain_closed": (
            audit_dict["decision"]["reach_wide_fixed_geometry_admitted"]
            is False
            and audit_dict["decision"][
                "runtime_hydraulic_geometry_admitted"
            ]
            is False
        ),
        "candidate_operator_remains_unadmitted": (
            audit_dict["decision"]["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "bridge_location_geometry_temporally_supported_"
            "reach_wide_and_runtime_admission_rejected"
        ),
        "audit_artifact": audit_artifact,
        "frozen_stage23_hashes": frozen_stage23,
        "candidate_summary": audit_dict["candidate"],
        "evaluation_summary": audit_dict["evaluations"],
        "cohort_counts": audit_dict["cohort_counts"],
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": audit_dict["claim_boundary"],
        "decision": audit_dict["decision"],
    }


def _refusal_control(audit) -> dict[str, bool]:
    results = {}
    calls = {
        "reach_wide_fixed_geometry": (
            audit.require_reach_wide_fixed_geometry,
            "public_reach_geometry_method_spatial_holdout_failed",
        ),
        "runtime_hydraulic_geometry": (
            audit.require_runtime_hydraulic_geometry,
            "public_reach_geometry_candidate_diagnostic_only",
        ),
        "confluence_patch_bathymetry": (
            audit.require_confluence_patch_bathymetry,
            "public_reach_geometry_candidate_not_confluence_patch_bathymetry",
        ),
    }
    for name, (call, message) in calls.items():
        try:
            call()
        except ValueError as exc:
            results[name] = str(exc) == message
        else:
            results[name] = False
    return results


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    results = {}
    for relative, digest in expected.items():
        actual = _sha256(REPO_ROOT / relative)
        results[relative] = {
            "expected_sha256": digest,
            "actual_sha256": actual,
            "matches": digest == actual,
        }
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
