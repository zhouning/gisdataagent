#!/usr/bin/env python3
"""Freeze the bounded action-innovation candidate without admitting it."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_FORMULA,
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
    action_innovation_transition_parameters_from_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_freeze.json"
)
SCHEMA = "gwm.geotransport.geospatial_kernel_action_innovation_candidate_freeze.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_freeze(*, candidate_report_path: Path = DEFAULT_CANDIDATE_REPORT) -> dict[str, Any]:
    report_body, report = _load_json(candidate_report_path)
    _validate_candidate_report(report)

    implementation = report["implementation_artifacts"]
    outputs = report["outputs"]
    core_body = _read_verified(implementation["core_operator"])
    evaluator_body = _read_verified(implementation["evaluator"])
    parameter_body = _read_verified(outputs["parameters"])
    parameters = action_innovation_transition_parameters_from_dict(json.loads(parameter_body))

    if (
        parameters.supported_forecast_horizons_hours != ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
        or parameters.admitted
        or parameters.support.admitted
    ):
        raise ValueError("action_innovation_freeze_parameter_contract_invalid")

    return {
        "schema": SCHEMA,
        "status": "frozen_bounded_candidate_not_admitted",
        "frozen_at": datetime.now(UTC).isoformat(),
        "scientific_role": (
            "posthoc candidate identity and runtime-boundary freeze; not prospective "
            "validation and not an admission decision"
        ),
        "candidate_artifacts": {
            "candidate_report": _artifact(candidate_report_path, report_body),
            "core_operator": _artifact_from_descriptor(implementation["core_operator"], core_body),
            "evaluator": _artifact_from_descriptor(implementation["evaluator"], evaluator_body),
            "parameters": _artifact_from_descriptor(outputs["parameters"], parameter_body),
        },
        "operator_lock": {
            "parameter_schema": parameters.as_dict()["schema"],
            "formula": ACTION_INNOVATION_FORMULA,
            "state_persistence_coefficient_fixed": 1.0,
            "free_parameter_count": 3,
            "supported_forecast_horizons_hours": list(ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS),
            "timestep_seconds": parameters.timestep_seconds,
            "training_data_start": parameters.training_data_start.isoformat(),
            "training_data_end": parameters.training_data_end.isoformat(),
            "training_sample_count": parameters.training_sample_count,
            "per_window_refit_permitted": False,
            "arbitrary_long_rollout_supported": False,
            "asymptotic_stability_claimed": False,
            "mass_conserving_network_routing_replacement": False,
        },
        "causal_runtime_contract": {
            "initial_state": "latest outlet state available at issue time",
            "future_outlet_observations_permitted": False,
            "forecast_state_writeback_required": True,
            "targets_must_be_hour_aligned": True,
            "unregistered_horizon_policy": "reject",
            "missing_action_or_forcing_policy": "reject",
            "parameter_deserialization_required": True,
            "parameter_or_support_refit_at_runtime": False,
        },
        "issue_time_input_contract": {
            "action": "release plan vintage available at issue time",
            "nwm_lateral_forcing": "NWM forecast vintage available at issue time",
            "outlet_state": "observation vintage available at issue time",
            "all_vintages_must_be_verified_for_operational_use": True,
            "realized_future_action_archive_is_operational_input": False,
            "retrospective_nwm_forcing_is_operational_input": False,
            "current_diagnostics_use_verified_operational_vintages": False,
            "operational_forecast_claim_permitted": False,
        },
        "diagnostic_gate_lock": {
            "horizons_hours": list(ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS),
            "action_effect_required_horizons_hours": [6, 12],
            "primary_metric": "rmse_m3s",
            "complete_case_policy": "common mask per horizon and window",
            "development_gate": (
                "at every horizon candidate RMSE is below causal persistence, "
                "no-future-forcing, graph Manning, and local Manning; at 6h and 12h "
                "candidate RMSE is also below no-future-action; no future outlet "
                "outcomes are model inputs; every target is written back as state"
            ),
            "posthoc_window_gate": (
                "at every horizon candidate RMSE is below causal persistence and "
                "no-future-forcing; at 6h and 12h candidate RMSE is also below "
                "no-future-action; no future outlet outcomes are model inputs; every "
                "target is written back as state"
            ),
            "cross_window_compensation_permitted": False,
            "observed_result_snapshot": {
                "development_gate_passed": True,
                "both_posthoc_temporal_window_gates_passed": True,
                "candidate_diagnostic_gate_passed": True,
                "admission_gate_passed": False,
            },
            "posthoc_windows_count_as_fresh_validation": False,
        },
        "admission_contract": {
            "runtime_default_enabled": False,
            "admission_gate_passed": False,
            "fresh_prospective_evidence_required": True,
            "multi_system_evidence_required": True,
            "operational_issue_time_vintage_evidence_required": True,
            "same_frozen_artifacts_required_for_future_evaluation": True,
            "automatic_admission_from_posthoc_gate_results": False,
        },
        "forbidden_after_freeze": [
            "change_core_operator_without_creating_a_new_candidate_identity",
            "change_parameters_support_lags_or_horizons",
            "refit_parameters_per_evaluation_window_or_system",
            "use_future_outlet_observations inside a rollout",
            "label_realized_action_or_retrospective_forcing_as_issue_time_forecasts",
            "enable_as_runtime_default_without_a_separate_admission_decision",
            "claim_validation_from_the_already_exposed_January_or_D3_windows",
        ],
        "claim_boundary": {
            "candidate_identity_frozen": True,
            "bounded_runtime_contract_implemented": True,
            "candidate_diagnostics_passed": True,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "multi_system_generalization_validated": False,
            "runtime_default_enabled": False,
            "candidate_admitted": False,
        },
    }


def _validate_candidate_report(report: Mapping[str, Any]) -> None:
    aggregate = report.get("aggregate_gate") or {}
    selection = report.get("selection_boundary") or {}
    information = report.get("information_boundary") or {}
    claims = report.get("claim_boundary") or {}
    parameter_lock = report.get("parameter_lock") or {}
    kernel = report.get("kernel") or {}
    outputs = report.get("outputs") or {}
    if (
        report.get("schema") != "gwm.geotransport.geospatial_kernel_action_innovation_candidate.v1"
        or report.get("status") != "action_innovation_candidate_posthoc_gates_passed_not_validated"
        or aggregate
        != {
            "development_gate_passed": True,
            "both_posthoc_temporal_window_gates_passed": True,
            "candidate_diagnostic_gate_passed": True,
            "admission_gate_passed": False,
        }
        or selection.get("architecture_revised_after_prior_mvp_transfer_outcomes_were_seen")
        is not True
        or selection.get("fresh_blind_window_consumed") is not False
        or selection.get("public_transfer_windows_can_validate_revised_architecture") is not False
        or information.get("future_outlet_observations_used_by_kernel") is not False
        or information.get("future_realized_action_archive_used") is not True
        or information.get("future_retrospective_nwm_forcing_used") is not True
        or information.get("operational_forecast_claim_permitted") is not False
        or claims.get("geospatial_kernel_validated") is not False
        or claims.get("operational_forecast_validated") is not False
        or claims.get("multi_system_generalization_validated") is not False
        or claims.get("action_innovation_closure_admitted_as_default") is not False
        or parameter_lock.get("all_evaluations_use_deserialized_parameter_artifact") is not True
        or parameter_lock.get("per_window_refit_performed") is not False
        or kernel.get("free_parameter_count") != 3
        or kernel.get("state_persistence_coefficient_fixed") != 1.0
        or kernel.get("asymptotic_stability_claimed") is not False
        or kernel.get("mass_conserving_network_routing_replacement") is not False
        or (outputs.get("parameters") or {}).get("sha256")
        != parameter_lock.get("serialized_parameter_sha256")
    ):
        raise ValueError("action_innovation_candidate_report_not_freezable")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("action_innovation_freeze_artifact_outside_repository") from exc
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get(
        "size_bytes"
    ):
        raise ValueError("action_innovation_freeze_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("action_innovation_freeze_json_document_required")
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
        raise ValueError("action_innovation_candidate_freeze_refuses_overwrite")
    payload = compile_freeze(candidate_report_path=args.candidate_report)
    _write(args.output, payload)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
