#!/usr/bin/env python3
"""Score one sealed uncertainty-shadow forecast after its outcomes mature."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    action_innovation_authoritative_observation_batch_from_dict,
    action_innovation_prospective_outcomes_from_dict,
    score_action_innovation_prospective_forecast,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    ISSUE_TIME_INPUT_ATTESTATION_SCHEMA,
    REPO_ROOT,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_FORECAST_SCHEMA,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    ACTION_INNOVATION_UNCERTAINTY_SHADOW_FORECAST_SCHEMA,
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
    load_frozen_action_innovation_uncertainty_shadow_runtime,
)

FORECAST_RECEIPT_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_uncertainty_shadow_run_receipt.v1"
)
INTERVAL_FORECAST_SCHEMA = "gwm.geospatial_kernel.action_innovation_uncertainty_forecast.v1"
POINT_SHADOW_FORECAST_SCHEMA = "gwm.geospatial_kernel.action_innovation_shadow_forecast.v1"
REPORT_SCHEMA = "gwm.geospatial_kernel.action_innovation_uncertainty_prospective_verification.v1"
MAXIMUM_ISSUE_LATENCY = timedelta(minutes=15)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-receipt", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--observation-batch", type=Path, required=True)
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def compile_prospective_verification(
    forecast_receipt_body: bytes,
    outcome_body: bytes,
    observation_batch_body: bytes,
    *,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    receipt = _json_mapping(
        forecast_receipt_body,
        "action_innovation_prospective_forecast_receipt_json_invalid",
    )
    outcome_payload = _json_mapping(
        outcome_body,
        "action_innovation_prospective_outcome_json_invalid",
    )
    outcomes = action_innovation_prospective_outcomes_from_dict(outcome_payload)
    observation_batch_payload = _json_mapping(
        observation_batch_body,
        "action_innovation_prospective_observation_batch_json_invalid",
    )
    observation_batch = action_innovation_authoritative_observation_batch_from_dict(
        observation_batch_payload
    )
    _validate_receipt_contract(receipt)

    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime(
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        enabled=False,
    )
    execution = receipt["execution_identity"]
    if (
        execution["uncertainty_freeze_sha256"] != runtime.uncertainty_freeze_sha256
        or execution["uncertainty_parameter_sha256"] != runtime.uncertainty_parameter_sha256
        or execution["point_freeze_sha256"] != runtime.point_runtime.freeze_sha256
        or execution["point_parameter_sha256"] != runtime.point_runtime.parameter_sha256
        or execution["uncertainty_runtime_sha256"] != runtime.uncertainty_runtime_sha256
        or execution["point_runtime_sha256"] != runtime.point_runtime.runtime_sha256
    ):
        raise ValueError("action_innovation_prospective_frozen_identity_mismatch")

    receipt_hash = hashlib.sha256(forecast_receipt_body).hexdigest()
    observation_batch_hash = hashlib.sha256(observation_batch_body).hexdigest()
    request_identity = receipt["request_identity"]
    if (
        outcomes.request_id != request_identity["request_id"]
        or outcomes.forecast_receipt_sha256 != receipt_hash
    ):
        raise ValueError("action_innovation_prospective_outcome_forecast_binding_invalid")
    if (
        outcomes.source_observation_artifact_sha256 != observation_batch_hash
        or outcomes.source_observation_artifact_size_bytes
        != len(observation_batch_body)
    ):
        raise ValueError(
            "action_innovation_prospective_outcome_observation_artifact_binding_invalid"
        )

    result = receipt["result"]
    point_shadow = result["point_shadow_forecast"]
    interval = result["interval_forecast"]
    point = interval["point_forecast"]
    if point_shadow["forecast"] != point:
        raise ValueError("action_innovation_prospective_duplicate_point_forecast_mismatch")
    issue_time = _time(point["issue_time"], "forecast_issue")
    if (
        _time(
            point_shadow["input_attestation"]["issue_time"],
            "attestation_issue",
        )
        != issue_time
    ):
        raise ValueError("action_innovation_prospective_attestation_issue_mismatch")
    targets = tuple(_time(value, "forecast_target") for value in point["target_valid_times"])
    generated_at = _time(receipt["generated_at"], "forecast_generated")
    freeze_body = uncertainty_freeze_path.read_bytes()
    freeze = _json_mapping(
        freeze_body,
        "action_innovation_prospective_uncertainty_freeze_json_invalid",
    )
    frozen_at = _time(freeze["frozen_at"], "uncertainty_frozen")
    verification_time = verified_at if verified_at is not None else _now()
    if (
        not isinstance(verification_time, datetime)
        or verification_time.tzinfo is None
        or verification_time.utcoffset() is None
    ):
        raise ValueError("action_innovation_prospective_verified_time_invalid")
    if (
        issue_time < frozen_at
        or generated_at < frozen_at
        or generated_at < issue_time
        or generated_at > issue_time + MAXIMUM_ISSUE_LATENCY
        or generated_at >= min(targets)
        or outcomes.outcomes_available_at <= generated_at
        or outcomes.outcomes_available_at > verification_time
        or outcomes.outcomes_available_at < max(targets)
    ):
        raise ValueError("action_innovation_prospective_ordering_invalid")

    parameters = interval["parameters"]
    frozen_network_id = runtime.point_runtime.parameters.support.network_id
    if (
        parameters != runtime.uncertainty_parameters.as_dict()
        or point["parameters"] != runtime.point_runtime.parameters.as_dict()
        or request_identity["network_id"] != frozen_network_id
        or result["network_id"] != frozen_network_id
        or point_shadow["network_id"] != frozen_network_id
        or point_shadow["input_attestation"]["network_id"] != frozen_network_id
        or observation_batch.network_id != frozen_network_id
        or point_shadow["freeze_sha256"] != execution["point_freeze_sha256"]
        or point_shadow["parameter_sha256"] != execution["point_parameter_sha256"]
        or point_shadow["runtime_sha256"] != execution["point_runtime_sha256"]
    ):
        raise ValueError("action_innovation_prospective_embedded_parameter_mismatch")
    source_by_target = {
        value.target_valid_time: value for value in observation_batch.observations
    }
    outcome_by_target = {
        value.target_valid_time: value for value in outcomes.observations
    }
    if (
        observation_batch.retrieved_at != outcomes.outcomes_available_at
        or observation_batch.outlet_observation_provenance_id
        != outcomes.outlet_observation_provenance_id
        or observation_batch.outlet_observation_evidence_level
        != outcomes.outlet_observation_evidence_level
        or source_by_target != outcome_by_target
    ):
        raise ValueError(
            "action_innovation_prospective_outcome_observation_content_mismatch"
        )
    score = score_action_innovation_prospective_forecast(
        issue_time=issue_time,
        target_valid_times=targets,
        point_discharge_m3s=tuple(
            _number(value, "point_discharge") for value in point["target_discharge_m3s"]
        ),
        lower_discharge_m3s=tuple(
            _number(value, "lower_discharge") for value in interval["lower_discharge_m3s"]
        ),
        upper_discharge_m3s=tuple(
            _number(value, "upper_discharge") for value in interval["upper_discharge_m3s"]
        ),
        outcomes=outcomes,
        target_marginal_coverage=_number(parameters["target_marginal_coverage"], "target_coverage"),
    )
    return {
        "schema": REPORT_SCHEMA,
        "status": "single_issue_shadow_outcomes_scored_not_admitted",
        "generated_at": verification_time.isoformat(),
        "source_artifacts": {
            "forecast_receipt": _artifact_bytes(forecast_receipt_body),
            "outcomes": _artifact_bytes(outcome_body),
            "observation_batch": _artifact_bytes(observation_batch_body),
            "uncertainty_freeze": _artifact_path(uncertainty_freeze_path, freeze_body),
        },
        "request_identity": {
            "request_id": outcomes.request_id,
            "network_id": frozen_network_id,
            "issue_time": issue_time.isoformat(),
            "forecast_generated_at": generated_at.isoformat(),
            "outcomes_available_at": outcomes.outcomes_available_at.isoformat(),
            "outlet_observation_provenance_id": (outcomes.outlet_observation_provenance_id),
            "source_observation_artifact_sha256": (
                outcomes.source_observation_artifact_sha256
            ),
            "source_observation_artifact_size_bytes": (
                outcomes.source_observation_artifact_size_bytes
            ),
        },
        "frozen_candidate_identity": {
            "point_freeze_sha256": runtime.point_runtime.freeze_sha256,
            "point_parameter_sha256": runtime.point_runtime.parameter_sha256,
            "uncertainty_freeze_sha256": runtime.uncertainty_freeze_sha256,
            "uncertainty_parameter_sha256": runtime.uncertainty_parameter_sha256,
        },
        "score": score,
        "ordering_audit": {
            "forecast_generated_after_uncertainty_freeze": True,
            "forecast_generated_within_issue_latency_limit": True,
            "forecast_generated_before_first_target": True,
            "all_observations_available_no_earlier_than_target": True,
            "outcome_document_bound_to_exact_forecast_receipt": True,
            "source_observation_artifact_verified": True,
            "outcome_values_match_source_observation_batch": True,
            "outcomes_declared_available_before_scoring": True,
            "trusted_external_timestamp_verified": False,
        },
        "claim_boundary": {
            "fresh_window_separation_verified": True,
            "single_issue_shadow_score_available": True,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "coverage_or_radii_recalibrated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        },
    }


def _validate_receipt_contract(receipt: Mapping[str, object]) -> None:
    if set(receipt) != {
        "schema",
        "status",
        "generated_at",
        "request_identity",
        "execution_identity",
        "result",
        "claim_boundary",
    }:
        raise ValueError("action_innovation_prospective_forecast_receipt_fields_invalid")
    claims = receipt.get("claim_boundary") or {}
    execution = receipt.get("execution_identity") or {}
    result = receipt.get("result") or {}
    if (
        receipt.get("schema") != FORECAST_RECEIPT_SCHEMA
        or receipt.get("status") != "uncertainty_shadow_forecast_complete_not_admitted"
        or claims
        != {
            "shadow_only": True,
            "calibration_outcomes_used": True,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "production_eligible": False,
            "runtime_default_enabled": False,
            "admitted": False,
        }
        or not isinstance(execution, Mapping)
        or set(execution)
        != {
            "point_freeze_sha256",
            "point_parameter_sha256",
            "point_runtime_sha256",
            "uncertainty_freeze_sha256",
            "uncertainty_parameter_sha256",
            "uncertainty_runtime_sha256",
            "request_adapter_sha256",
            "runner_sha256",
        }
        or any(not _valid_sha256(value) for value in execution.values())
    ):
        raise ValueError("action_innovation_prospective_forecast_receipt_invalid")
    if not isinstance(result, Mapping) or set(result) != {
        "schema",
        "mode",
        "network_id",
        "uncertainty_freeze_sha256",
        "uncertainty_parameter_sha256",
        "uncertainty_runtime_sha256",
        "point_shadow_forecast",
        "interval_forecast",
        "calibration_outcomes_used",
        "time_series_exchangeability_claimed",
        "finite_sample_coverage_guarantee_claimed",
        "conditional_coverage_guarantee_claimed",
        "production_eligible",
        "runtime_default_enabled",
        "admitted",
    }:
        raise ValueError("action_innovation_prospective_forecast_result_fields_invalid")
    if (
        result["schema"] != ACTION_INNOVATION_UNCERTAINTY_SHADOW_FORECAST_SCHEMA
        or result["mode"] != "uncertainty_shadow"
        or not isinstance(result["network_id"], str)
        or not result["network_id"].strip()
        or result["calibration_outcomes_used"] is not True
        or result["time_series_exchangeability_claimed"] is not False
        or result["finite_sample_coverage_guarantee_claimed"] is not False
        or result["conditional_coverage_guarantee_claimed"] is not False
        or result["production_eligible"] is not False
        or result["runtime_default_enabled"] is not False
        or result["admitted"] is not False
        or result["uncertainty_freeze_sha256"] != execution["uncertainty_freeze_sha256"]
        or result["uncertainty_parameter_sha256"] != execution["uncertainty_parameter_sha256"]
        or result["uncertainty_runtime_sha256"] != execution["uncertainty_runtime_sha256"]
    ):
        raise ValueError("action_innovation_prospective_forecast_result_invalid")
    point_shadow = result.get("point_shadow_forecast") or {}
    interval = result.get("interval_forecast") or {}
    point = interval.get("point_forecast") if isinstance(interval, Mapping) else None
    request_identity = receipt.get("request_identity") or {}
    attestation = (
        point_shadow.get("input_attestation") if isinstance(point_shadow, Mapping) else None
    )
    if (
        not isinstance(request_identity, Mapping)
        or set(request_identity)
        != {
            "request_id",
            "network_id",
            "source_document_sha256",
            "source_document_size_bytes",
            "normalized_request_sha256",
        }
        or not isinstance(request_identity.get("request_id"), str)
        or not request_identity["request_id"].strip()
        or not isinstance(request_identity.get("network_id"), str)
        or not request_identity["network_id"].strip()
        or not _valid_sha256(request_identity.get("source_document_sha256"))
        or not _valid_sha256(request_identity.get("normalized_request_sha256"))
        or not isinstance(request_identity.get("source_document_size_bytes"), int)
        or isinstance(request_identity.get("source_document_size_bytes"), bool)
        or request_identity["source_document_size_bytes"] <= 0
        or not isinstance(point_shadow, Mapping)
        or set(point_shadow)
        != {
            "schema",
            "mode",
            "network_id",
            "freeze_sha256",
            "parameter_sha256",
            "runtime_sha256",
            "input_attestation",
            "forecast",
            "operational_vintages_verified",
            "future_outlet_observations_used",
            "production_eligible",
            "runtime_default_enabled",
            "admitted",
        }
        or point_shadow.get("schema") != POINT_SHADOW_FORECAST_SCHEMA
        or point_shadow.get("mode") != "shadow"
        or not isinstance(point_shadow.get("network_id"), str)
        or not point_shadow["network_id"].strip()
        or point_shadow.get("operational_vintages_verified") is not True
        or point_shadow.get("future_outlet_observations_used") is not False
        or point_shadow.get("production_eligible") is not False
        or point_shadow.get("runtime_default_enabled") is not False
        or point_shadow.get("admitted") is not False
        or not isinstance(interval, Mapping)
        or set(interval)
        != {
            "schema",
            "point_forecast",
            "lower_discharge_m3s",
            "upper_discharge_m3s",
            "parameters",
            "future_outlet_observations_used",
            "finite_sample_coverage_guarantee_claimed",
            "conditional_coverage_guarantee_claimed",
            "admitted",
        }
        or interval.get("schema") != INTERVAL_FORECAST_SCHEMA
        or not isinstance(interval.get("lower_discharge_m3s"), list)
        or not isinstance(interval.get("upper_discharge_m3s"), list)
        or interval.get("future_outlet_observations_used") is not False
        or interval.get("finite_sample_coverage_guarantee_claimed") is not False
        or interval.get("conditional_coverage_guarantee_claimed") is not False
        or interval.get("admitted") is not False
        or not isinstance(point, Mapping)
        or set(point)
        != {
            "schema",
            "issue_time",
            "initial_state",
            "issue_state",
            "final_state",
            "target_valid_times",
            "target_discharge_m3s",
            "steps",
            "future_observations_used",
            "operational_vintages_verified",
            "admitted",
            "parameters",
        }
        or point.get("schema") != ACTION_INNOVATION_FORECAST_SCHEMA
        or not isinstance(point.get("target_valid_times"), list)
        or len(point.get("target_valid_times")) != 4
        or not isinstance(point.get("target_discharge_m3s"), list)
        or len(point.get("target_discharge_m3s")) != 4
        or len(interval.get("lower_discharge_m3s")) != 4
        or len(interval.get("upper_discharge_m3s")) != 4
        or not isinstance(interval.get("parameters"), Mapping)
        or not isinstance(point.get("parameters"), Mapping)
        or not isinstance(point_shadow.get("forecast"), Mapping)
        or point.get("future_observations_used") is not False
        or point.get("operational_vintages_verified") is not True
        or point.get("admitted") is not False
        or not isinstance(attestation, Mapping)
        or set(attestation)
        != {
            "schema",
            "issue_time",
            "network_id",
            "action_provenance_id",
            "action_plan_available_at",
            "forcing_provenance_id",
            "forcing_forecast_available_at",
            "outlet_state_provenance_id",
            "outlet_state_available_at",
            "verification_id",
        }
        or attestation.get("schema") != ISSUE_TIME_INPUT_ATTESTATION_SCHEMA
        or not isinstance(attestation.get("network_id"), str)
        or not attestation["network_id"].strip()
    ):
        raise ValueError("action_innovation_prospective_nested_forecast_invalid")


def _json_mapping(body: bytes, error: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(error) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(error)
    return payload


def _artifact_bytes(body: bytes) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _artifact_path(path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": path.resolve().as_posix(),
        **_artifact_bytes(body),
    }


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid")
    return result


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"action_innovation_prospective_{name}_number_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"action_innovation_prospective_{name}_number_invalid")
    return result


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_prospective_verification_refuses_overwrite")
    report = compile_prospective_verification(
        args.forecast_receipt.read_bytes(),
        args.outcomes.read_bytes(),
        args.observation_batch.read_bytes(),
        uncertainty_freeze_path=args.uncertainty_freeze,
    )
    _write(args.output, report)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
