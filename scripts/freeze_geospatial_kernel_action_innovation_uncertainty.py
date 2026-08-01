#!/usr/bin/env python3
"""Freeze the empirical uncertainty candidate before prospective evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty import (
    ACTION_INNOVATION_UNCERTAINTY_METHOD,
    horizon_residual_envelope_parameters_from_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POINT_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_freeze.json"
)
DEFAULT_UNCERTAINTY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_uncertainty_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_uncertainty_freeze.json"
)
SCHEMA = "gwm.geotransport.geospatial_kernel_action_innovation_uncertainty_freeze.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point-freeze", type=Path, default=DEFAULT_POINT_FREEZE)
    parser.add_argument("--uncertainty-report", type=Path, default=DEFAULT_UNCERTAINTY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_freeze(
    *,
    point_freeze_path: Path = DEFAULT_POINT_FREEZE,
    uncertainty_report_path: Path = DEFAULT_UNCERTAINTY_REPORT,
) -> dict[str, Any]:
    point_freeze_body, point_freeze = _load_json(point_freeze_path)
    report_body, report = _load_json(uncertainty_report_path)
    _validate_point_freeze(point_freeze)
    _validate_uncertainty_report(report)

    point_artifacts = point_freeze["candidate_artifacts"]
    for descriptor in point_artifacts.values():
        _read_verified(descriptor)
    implementation = report["implementation_artifacts"]
    outputs = report["outputs"]
    operator_body = _read_verified(implementation["uncertainty_operator"])
    evaluator_body = _read_verified(implementation["evaluator"])
    parameter_body = _read_verified(outputs["parameters"])
    interval_bodies = {
        name: _read_verified(outputs[name])
        for name in (
            "development_intervals",
            "january_temporal_holdout_intervals",
            "february_d3_intervals",
        )
    }
    parameters = horizon_residual_envelope_parameters_from_dict(json.loads(parameter_body))
    point_parameter_hash = point_artifacts["parameters"]["sha256"]
    if (
        parameters.point_parameter_artifact_sha256 != point_parameter_hash
        or report["parameter_lock"]["point_parameter_artifact_sha256"] != point_parameter_hash
        or report["parameter_lock"]["uncertainty_parameter_artifact_sha256"]
        != hashlib.sha256(parameter_body).hexdigest()
    ):
        raise ValueError("action_innovation_uncertainty_freeze_identity_mismatch")

    return {
        "schema": SCHEMA,
        "status": "frozen_uncertainty_candidate_not_admitted",
        "frozen_at": datetime.now(UTC).isoformat(),
        "scientific_role": (
            "freeze a horizon-specific empirical residual envelope before any "
            "fresh prospective or multi-system coverage evaluation"
        ),
        "candidate_artifacts": {
            "point_candidate_freeze": _artifact(point_freeze_path, point_freeze_body),
            "uncertainty_report": _artifact(uncertainty_report_path, report_body),
            "uncertainty_operator": _artifact_from_descriptor(
                implementation["uncertainty_operator"], operator_body
            ),
            "uncertainty_evaluator": _artifact_from_descriptor(
                implementation["evaluator"], evaluator_body
            ),
            "uncertainty_parameters": _artifact_from_descriptor(
                outputs["parameters"], parameter_body
            ),
            **{
                name: _artifact_from_descriptor(outputs[name], body)
                for name, body in interval_bodies.items()
            },
        },
        "uncertainty_lock": {
            "method": ACTION_INNOVATION_UNCERTAINTY_METHOD,
            "target_marginal_coverage": parameters.target_marginal_coverage,
            "horizons_hours": list(parameters.horizons_hours),
            "absolute_error_radius_m3s": list(parameters.absolute_error_radius_m3s),
            "calibration_sample_count": list(parameters.calibration_sample_count),
            "calibration_target_start": (parameters.calibration_target_start.isoformat()),
            "calibration_target_end": parameters.calibration_target_end.isoformat(),
            "point_parameter_artifact_sha256": (parameters.point_parameter_artifact_sha256),
            "per_window_recalibration_permitted": False,
            "bounds_clipped_to_physical_discharge_range": True,
        },
        "statistical_claim_boundary": {
            "calibration_outcomes_used": True,
            "time_series_exchangeability_claimed": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "january_or_d3_coverage_counts_as_validation": False,
        },
        "prospective_evaluation_contract": {
            "same_point_candidate_freeze_required": True,
            "same_uncertainty_parameters_required": True,
            "fresh_prospective_window_required": True,
            "multi_system_evaluation_required": True,
            "issue_time_action_and_nwm_vintages_required_for_operational_claim": True,
            "coverage_target_may_be_changed_after_outcome_access": False,
            "radii_may_be_changed_after_outcome_access": False,
        },
        "admission_contract": {
            "uncertainty_candidate_admitted": False,
            "operational_forecast_validated": False,
            "multi_system_uncertainty_validated": False,
            "runtime_default_enabled": False,
            "automatic_admission_from_posthoc_coverage": False,
        },
        "forbidden_after_freeze": [
            "change_target_coverage_method_horizons_or_radii",
            "recalibrate_on_a_prospective_evaluation_window",
            "change_point_candidate_identity",
            "drop_rows_based_on_interval_miss",
            "claim_IID_exchangeability_or_finite_sample_coverage_guarantee",
            "treat_January_or_D3_posthoc_coverage_as_validation",
            "enable_as_runtime_default_without_separate_admission",
        ],
    }


def _validate_point_freeze(payload: Mapping[str, Any]) -> None:
    claims = payload.get("claim_boundary") or {}
    admission = payload.get("admission_contract") or {}
    if (
        payload.get("schema")
        != "gwm.geotransport.geospatial_kernel_action_innovation_candidate_freeze.v1"
        or payload.get("status") != "frozen_bounded_candidate_not_admitted"
        or claims.get("candidate_admitted") is not False
        or admission.get("runtime_default_enabled") is not False
    ):
        raise ValueError("action_innovation_uncertainty_point_freeze_invalid")


def _validate_uncertainty_report(payload: Mapping[str, Any]) -> None:
    gate = payload.get("calibration_gate") or {}
    statistical = payload.get("statistical_claim_boundary") or {}
    operational = payload.get("operational_claim_boundary") or {}
    if (
        payload.get("schema")
        != "gwm.geotransport.geospatial_kernel_action_innovation_uncertainty_candidate.v1"
        or payload.get("status")
        != "uncertainty_candidate_calibrated_posthoc_diagnostics_complete_not_validated"
        or gate.get("calibration_complete") is not True
        or gate.get("admission_gate_passed") is not False
        or statistical.get("time_series_exchangeability_claimed") is not False
        or statistical.get("finite_sample_coverage_guarantee_claimed") is not False
        or statistical.get("conditional_coverage_guarantee_claimed") is not False
        or statistical.get("posthoc_coverage_is_validation") is not False
        or operational.get("operational_forecast_validated") is not False
        or operational.get("multi_system_uncertainty_validated") is not False
        or operational.get("uncertainty_candidate_admitted") is not False
    ):
        raise ValueError("action_innovation_uncertainty_report_not_freezable")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("action_innovation_uncertainty_artifact_outside_repository") from exc
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get(
        "size_bytes"
    ):
        raise ValueError("action_innovation_uncertainty_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("action_innovation_uncertainty_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _artifact_from_descriptor(descriptor: Mapping[str, Any], body: bytes) -> dict[str, Any]:
    return _artifact(REPO_ROOT / str(descriptor["path"]), body)


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_uncertainty_freeze_refuses_overwrite")
    payload = compile_freeze(
        point_freeze_path=args.point_freeze,
        uncertainty_report_path=args.uncertainty_report,
    )
    _write(args.output, payload)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
