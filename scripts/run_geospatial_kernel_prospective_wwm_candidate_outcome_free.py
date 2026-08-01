#!/usr/bin/env python3
"""Run the integrated physical-first WWM candidate without target outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.classical_arx_baseline import (
    CLASSICAL_ARX_SCHEMA,
    ClassicalCausalARXParameters,
    classical_causal_arx_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
)
from data_agent.uwm.geospatial_kernel_v2.physical_online_residual_adaptation import (
    PhysicalOnlineResidualAdaptationConfig,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidatePrediction,
    ProspectiveWwmCandidateRunner,
    ProspectiveWwmCandidateState,
    algorithm_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = Path(__file__).resolve()
CORE_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/prospective_wwm_candidate.py"
)
ARX_CORE_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/classical_arx_baseline.py"
)
DEFAULT_ARX_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_traditional_arx_posthoc_report.json"
)
ARX_REPORT_SCHEMA = "gwm.geotransport.geospatial_kernel_traditional_arx_posthoc.v1"
ISSUE_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_issue.v3"
OUTPUT_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_predictions.v2"
REPORT_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_outcome_free_run.v3"
HORIZONS = (1, 3, 6, 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--executed-at", type=str)
    return parser.parse_args()


def compile_outcome_free_prospective_wwm_candidate(
    *,
    issue_path: Path,
    state_path: Path,
    output_path: Path,
    executed_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Generate v4 inside the runtime, then emit v5 and its comparator."""

    issue_body, issue = _load_json(issue_path)
    state_body, state_payload = _load_json(state_path)
    state = ProspectiveWwmCandidateState.from_dict(state_payload)
    if (
        state.physical_residual_state.config
        != PhysicalOnlineResidualAdaptationConfig()
        or state.expert_pair_state.config != PhysicalOnlineExpertBlendConfig()
    ):
        raise ValueError("prospective_wwm_candidate_algorithm_config_not_frozen")
    (
        issue_time,
        predictions,
        provenance,
        baselines_by_horizon,
        baseline_artifacts,
    ) = _compile_predictions(issue, state)
    output_payload = {
        "schema": OUTPUT_SCHEMA,
        "system_id": state.system_id,
        "issue_time_utc": _iso(issue_time),
        "state_as_of_utc": _iso(state.state_as_of),
        "candidate": "physical_first_online_wwm_v1",
        "predictions": [
            {
                **value.as_dict(),
                **baselines_by_horizon[
                    value.v4_step.forecast_horizon_hours
                ],
            }
            for value in predictions
        ],
        "prediction_count": len(predictions),
        "raw_observations_included": False,
        "scores_included": False,
    }
    output_body = _json_body(output_payload)
    recorded_at = executed_at if executed_at is not None else datetime.now(UTC)
    if (
        not _aware(recorded_at)
        or recorded_at < issue_time
        or recorded_at
        >= min(value.target_support_end for value in predictions)
    ):
        raise ValueError("prospective_wwm_candidate_executed_at_invalid")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "outcome_free_integrated_wwm_predictions_complete",
        "executed_at_utc": _iso(recorded_at),
        "system_id": state.system_id,
        "issue_time_utc": _iso(issue_time),
        "state_as_of_utc": _iso(state.state_as_of),
        "algorithm_lock": algorithm_contract(),
        "input_provenance": provenance,
        "input_artifacts": {
            "issue": _artifact(issue_path, issue_body),
            "matured_state": _artifact(state_path, state_body),
        },
        "implementation_artifacts": {
            "prospective_wwm_core": _artifact(CORE_PATH, CORE_PATH.read_bytes()),
            "classical_arx_core": _artifact(
                ARX_CORE_PATH,
                ARX_CORE_PATH.read_bytes(),
            ),
            "outcome_free_runner": _artifact(RUNNER_PATH, RUNNER_PATH.read_bytes()),
        },
        "traditional_baseline_artifacts": baseline_artifacts,
        "prediction_artifact": _artifact(output_path, output_body),
        "execution": {
            "forecast_horizons_hours": list(HORIZONS),
            "prediction_count": len(predictions),
            "v4_generated_from_matured_state_at_issue_time": True,
            "precomputed_v4_prediction_loaded": False,
            "persistence_generated_from_issue_time_observation": True,
            "classical_arx_generated_from_locked_parameters": True,
            "precomputed_persistence_or_arx_prediction_loaded": False,
            "issue_state_quality_status": provenance[
                "latest_observed_outlet_state"
            ]["quality_status"],
            "provisional_issue_state_used": (
                provenance["latest_observed_outlet_state"]["quality_status"]
                == "provisional"
            ),
            "v4_matured_sample_count_by_horizon": {
                str(key): value
                for key, value in (
                    state.physical_residual_state.sample_count_by_horizon().items()
                )
            },
            "v5_matured_sample_count_by_horizon": {
                str(key): value
                for key, value in state.expert_pair_state.sample_count_by_horizon().items()
            },
        },
        "data_isolation": {
            "outcome_path_accepted_by_executor": False,
            "raw_observation_field_accepted_in_issue_input": False,
            "matured_issue_state_field_accepted": True,
            "score_or_loss_field_accepted_in_issue_input": False,
            "all_input_availability_not_later_than_issue": True,
            "authoritative_unimputed_provisional_issue_state_permitted": True,
            "approved_outcome_still_required_for_scoring": True,
            "current_or_future_target_used": False,
        },
        "claim_boundary": {
            "integrated_online_candidate_software_executed": True,
            "fresh_outcome_scored": False,
            "candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return output_body, report


def _compile_predictions(
    issue: Mapping[str, object],
    state: ProspectiveWwmCandidateState,
) -> tuple[
    datetime,
    tuple[ProspectiveWwmCandidatePrediction, ...],
    dict[str, object],
    dict[int, dict[str, object]],
    dict[str, object],
]:
    expected = {
        "schema",
        "system_id",
        "issue_time_utc",
        "forecast_id_prefix",
        "physical_at_latest_observation_m3s",
        "latest_observed_outlet_state",
        "traditional_baseline_inputs",
        "input_provenance",
        "forecasts",
    }
    if set(issue) != expected or (
        issue.get("schema") != ISSUE_SCHEMA
        or issue.get("system_id") != state.system_id
        or not isinstance(issue.get("forecast_id_prefix"), str)
        or not issue["forecast_id_prefix"].strip()
        or not isinstance(issue.get("input_provenance"), Mapping)
        or not isinstance(issue.get("latest_observed_outlet_state"), Mapping)
        or not isinstance(issue.get("traditional_baseline_inputs"), Mapping)
        or not isinstance(issue.get("forecasts"), list)
    ):
        raise ValueError("prospective_wwm_candidate_issue_invalid")
    issue_time = _parse_datetime(issue["issue_time_utc"])
    if state.state_as_of > issue_time:
        raise ValueError("prospective_wwm_candidate_state_after_issue")
    provenance = _validate_provenance(issue["input_provenance"], issue_time)
    latest_observed = _validate_latest_observed_outlet_state(
        issue["latest_observed_outlet_state"],
        issue_time,
    )
    baseline_inputs = _validate_traditional_baseline_inputs(
        issue["traditional_baseline_inputs"],
        issue_time,
    )
    raw_latest = issue["physical_at_latest_observation_m3s"]
    if (
        isinstance(raw_latest, bool)
        or not isinstance(raw_latest, (int, float))
        or not math.isfinite(float(raw_latest))
        or float(raw_latest) < 0.0
    ):
        raise ValueError("prospective_wwm_candidate_issue_invalid")
    physical: dict[int, float] = {}
    action: dict[int, float] = {}
    forecast_ids: dict[int, str] = {}
    for row in issue["forecasts"]:
        if not isinstance(row, Mapping) or set(row) != {
            "forecast_id",
            "horizon_hours",
            "target_support_end_utc",
            "physical_open_loop_m3s",
            "action_innovation_wwm_m3s",
        }:
            raise ValueError("prospective_wwm_candidate_issue_forecast_invalid")
        horizon = row["horizon_hours"]
        forecast_id = row["forecast_id"]
        if (
            not isinstance(horizon, int)
            or isinstance(horizon, bool)
            or horizon not in HORIZONS
            or horizon in physical
            or not isinstance(forecast_id, str)
            or not forecast_id.strip()
            or _parse_datetime(row["target_support_end_utc"])
            != issue_time + timedelta(hours=horizon)
        ):
            raise ValueError("prospective_wwm_candidate_issue_forecast_invalid")
        try:
            physical[horizon] = float(row["physical_open_loop_m3s"])
            action[horizon] = float(row["action_innovation_wwm_m3s"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "prospective_wwm_candidate_issue_forecast_invalid"
            ) from exc
        forecast_ids[horizon] = forecast_id
    predictions = ProspectiveWwmCandidateRunner(state).predict_issue(
        issue_time=issue_time,
        physical_at_latest_observation_m3s=float(raw_latest),
        physical_predictions_by_horizon=physical,
        action_innovation_predictions_by_horizon=action,
        forecast_id_prefix=issue["forecast_id_prefix"],
    )
    if any(
        value.forecast_id != forecast_ids[value.v4_step.forecast_horizon_hours]
        for value in predictions
    ):
        raise ValueError("prospective_wwm_candidate_forecast_identity_invalid")
    arx_parameters, baseline_artifacts = _load_locked_arx_parameters()
    if arx_parameters.training_data_end >= issue_time:
        raise ValueError("prospective_wwm_candidate_arx_training_not_preissue")
    issue_index = baseline_inputs["valid_times"].index(issue_time)
    target_indices = tuple(issue_index + horizon for horizon in HORIZONS)
    arx_predictions, arx_clipped_step_count = arx_parameters.forecast(
        initial_discharge_m3s=latest_observed["discharge_m3s"],
        issue_index=issue_index,
        target_indices=target_indices,
        action_release_m3s=baseline_inputs["action_release_m3s"],
        lateral_forcing_m3s=baseline_inputs["lateral_forcing_m3s"],
    )
    baselines_by_horizon = {
        horizon: {
            "causal_persistence_m3s": latest_observed["discharge_m3s"],
            "classical_arx_m3s": arx_predictions[index],
            "classical_arx_parameter_sha256": baseline_artifacts[
                "parameters"
            ]["sha256"],
            "classical_arx_clipped_step_count_for_issue": (
                arx_clipped_step_count
            ),
            "baseline_predictions_generated_at_issue_time": True,
        }
        for index, horizon in enumerate(HORIZONS)
    }
    provenance = {
        **provenance,
        "latest_observed_outlet_state": latest_observed,
        "traditional_baseline_inputs": {
            "action_provenance_id": baseline_inputs["action_provenance_id"],
            "forcing_provenance_id": baseline_inputs["forcing_provenance_id"],
            "action_available_at_utc": _iso(
                baseline_inputs["action_available_at"]
            ),
            "forcing_available_at_utc": _iso(
                baseline_inputs["forcing_available_at"]
            ),
            "operational_vintages_verified": baseline_inputs[
                "operational_vintages_verified"
            ],
        },
    }
    return (
        issue_time,
        predictions,
        provenance,
        baselines_by_horizon,
        baseline_artifacts,
    )


def _validate_latest_observed_outlet_state(
    payload: Mapping[str, object],
    issue_time: datetime,
) -> dict[str, object]:
    expected = {
        "valid_at_utc",
        "available_at_utc",
        "discharge_m3s",
        "provenance_id",
        "evidence_level",
        "quality_status",
        "value_imputed",
    }
    if set(payload) != expected:
        raise ValueError("prospective_wwm_candidate_latest_observation_invalid")
    valid_at = _parse_datetime(payload["valid_at_utc"])
    available_at = _parse_datetime(payload["available_at_utc"])
    discharge = payload["discharge_m3s"]
    provenance_id = payload["provenance_id"]
    if (
        valid_at >= issue_time
        or available_at > issue_time
        or isinstance(discharge, bool)
        or not isinstance(discharge, (int, float))
        or not math.isfinite(float(discharge))
        or float(discharge) < 0.0
        or not isinstance(provenance_id, str)
        or not provenance_id.strip()
        or payload["evidence_level"] != "authoritative"
        or payload["quality_status"] not in {"approved", "provisional"}
        or payload["value_imputed"] is not False
    ):
        raise ValueError("prospective_wwm_candidate_latest_observation_invalid")
    return {
        "valid_at_utc": _iso(valid_at),
        "available_at_utc": _iso(available_at),
        "discharge_m3s": float(discharge),
        "provenance_id": provenance_id,
        "evidence_level": "authoritative",
        "quality_status": payload["quality_status"],
        "value_imputed": False,
    }


def _validate_traditional_baseline_inputs(
    payload: Mapping[str, object],
    issue_time: datetime,
) -> dict[str, object]:
    expected = {
        "valid_times_utc",
        "action_release_m3s",
        "lateral_forcing_m3s",
        "action_provenance_id",
        "forcing_provenance_id",
        "action_available_at_utc",
        "forcing_available_at_utc",
        "operational_vintages_verified",
    }
    if set(payload) != expected:
        raise ValueError("prospective_wwm_candidate_baseline_inputs_invalid")
    raw_times = payload["valid_times_utc"]
    raw_action = payload["action_release_m3s"]
    raw_forcing = payload["lateral_forcing_m3s"]
    if (
        not isinstance(raw_times, list)
        or not isinstance(raw_action, list)
        or not isinstance(raw_forcing, list)
        or not raw_times
        or len(raw_times) != len(raw_action)
        or len(raw_times) != len(raw_forcing)
    ):
        raise ValueError("prospective_wwm_candidate_baseline_inputs_invalid")
    valid_times = tuple(_parse_datetime(value) for value in raw_times)
    if (
        tuple(sorted(set(valid_times))) != valid_times
        or any(
            second - first != timedelta(hours=1)
            for first, second in zip(valid_times, valid_times[1:], strict=False)
        )
        or valid_times[0] > issue_time - timedelta(hours=7)
        or valid_times[-1] < issue_time + timedelta(hours=max(HORIZONS))
        or issue_time not in valid_times
    ):
        raise ValueError("prospective_wwm_candidate_baseline_time_axis_invalid")

    def finite_nonnegative(values: list[object]) -> tuple[float, ...]:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in values
        ):
            raise ValueError("prospective_wwm_candidate_baseline_inputs_invalid")
        return tuple(float(value) for value in values)

    identifiers = ("action_provenance_id", "forcing_provenance_id")
    if any(
        not isinstance(payload[key], str) or not payload[key].strip()
        for key in identifiers
    ):
        raise ValueError("prospective_wwm_candidate_baseline_inputs_invalid")
    action_available_at = _parse_datetime(payload["action_available_at_utc"])
    forcing_available_at = _parse_datetime(payload["forcing_available_at_utc"])
    if action_available_at > issue_time or forcing_available_at > issue_time:
        raise ValueError("prospective_wwm_candidate_input_not_available_at_issue")
    verified = payload["operational_vintages_verified"]
    if not isinstance(verified, bool):
        raise ValueError("prospective_wwm_candidate_baseline_inputs_invalid")
    return {
        "valid_times": valid_times,
        "action_release_m3s": finite_nonnegative(raw_action),
        "lateral_forcing_m3s": finite_nonnegative(raw_forcing),
        "action_provenance_id": payload["action_provenance_id"],
        "forcing_provenance_id": payload["forcing_provenance_id"],
        "action_available_at": action_available_at,
        "forcing_available_at": forcing_available_at,
        "operational_vintages_verified": verified,
    }


def _load_locked_arx_parameters(
    report_path: Path | None = None,
) -> tuple[ClassicalCausalARXParameters, dict[str, object]]:
    locked_report_path = DEFAULT_ARX_REPORT if report_path is None else report_path
    report_body, report = _load_json(locked_report_path)
    outputs = report.get("outputs")
    parameter_lock = report.get("parameter_lock")
    if (
        report.get("schema") != ARX_REPORT_SCHEMA
        or report.get("status")
        != "traditional_arx_zero_refit_posthoc_benchmark_complete"
        or not isinstance(outputs, Mapping)
        or not isinstance(parameter_lock, Mapping)
        or not isinstance(outputs.get("parameters"), Mapping)
        or set(parameter_lock)
        != {
            "schema",
            "parameter_sha256",
            "parameter_body_compiled_before_target_outcome_document_load",
            "all_windows_use_deserialized_parameter_artifact",
        }
        or parameter_lock.get("schema") != CLASSICAL_ARX_SCHEMA
        or parameter_lock.get(
            "parameter_body_compiled_before_target_outcome_document_load"
        )
        is not True
        or parameter_lock.get("all_windows_use_deserialized_parameter_artifact")
        is not True
    ):
        raise ValueError("prospective_wwm_candidate_arx_lock_invalid")
    descriptor = outputs["parameters"]
    if set(descriptor) != {"path", "sha256", "size_bytes"}:
        raise ValueError("prospective_wwm_candidate_arx_lock_invalid")
    raw_path = descriptor["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("prospective_wwm_candidate_arx_lock_invalid")
    parameter_path = Path(raw_path)
    if not parameter_path.is_absolute():
        parameter_path = REPO_ROOT / parameter_path
    parameter_body, parameter_payload = _load_json(parameter_path)
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()
    if (
        parameter_sha256 != descriptor.get("sha256")
        or len(parameter_body) != descriptor.get("size_bytes")
        or parameter_sha256 != parameter_lock.get("parameter_sha256")
    ):
        raise ValueError("prospective_wwm_candidate_arx_artifact_verification_failed")
    try:
        parameters = classical_causal_arx_parameters_from_dict(parameter_payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("prospective_wwm_candidate_arx_parameters_invalid") from exc
    if parameters.supported_forecast_horizons_hours != HORIZONS:
        raise ValueError("prospective_wwm_candidate_arx_parameters_invalid")
    return parameters, {
        "traditional_arx_report": _artifact(locked_report_path, report_body),
        "parameters": _artifact(parameter_path, parameter_body),
    }


def _validate_provenance(
    payload: Mapping[str, object],
    issue_time: datetime,
) -> dict[str, object]:
    expected = {
        "physical_forecast_provenance_id",
        "physical_forecast_available_at_utc",
        "latest_physical_state_provenance_id",
        "latest_physical_state_available_at_utc",
        "action_innovation_forecast_provenance_id",
        "action_innovation_forecast_available_at_utc",
        "operational_vintages_verified",
    }
    identifiers = (
        "physical_forecast_provenance_id",
        "latest_physical_state_provenance_id",
        "action_innovation_forecast_provenance_id",
    )
    availability = (
        "physical_forecast_available_at_utc",
        "latest_physical_state_available_at_utc",
        "action_innovation_forecast_available_at_utc",
    )
    if set(payload) != expected or any(
        not isinstance(payload.get(key), str) or not payload[key].strip()
        for key in identifiers
    ):
        raise ValueError("prospective_wwm_candidate_provenance_invalid")
    parsed = {key: _parse_datetime(payload[key]) for key in availability}
    if any(value > issue_time for value in parsed.values()):
        raise ValueError("prospective_wwm_candidate_input_not_available_at_issue")
    verified = payload["operational_vintages_verified"]
    if not isinstance(verified, bool):
        raise ValueError("prospective_wwm_candidate_provenance_invalid")
    return {
        **{key: payload[key] for key in identifiers},
        **{key: _iso(value) for key, value in parsed.items()},
        "operational_vintages_verified": verified,
    }


def _load_json(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body = path.read_bytes()

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("prospective_wwm_candidate_json_duplicate_key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"prospective_wwm_candidate_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("prospective_wwm_candidate_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("prospective_wwm_candidate_json_invalid")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("prospective_wwm_candidate_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("prospective_wwm_candidate_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("prospective_wwm_candidate_datetime_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> None:
    args = parse_args()
    recorded_at = (
        None if args.executed_at is None else _parse_datetime(args.executed_at)
    )
    if args.output.exists() or args.report.exists():
        raise ValueError("prospective_wwm_candidate_output_overwrite_forbidden")
    output_body, report = compile_outcome_free_prospective_wwm_candidate(
        issue_path=args.issue,
        state_path=args.state,
        output_path=args.output,
        executed_at=recorded_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"system_id={report['system_id']}")
    print(f"prediction_count={report['execution']['prediction_count']}")


if __name__ == "__main__":
    main()
