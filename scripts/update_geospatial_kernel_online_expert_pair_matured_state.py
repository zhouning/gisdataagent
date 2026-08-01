#!/usr/bin/env python3
"""Advance the online expert pair only from matured authoritative feedback."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA,
    ProspectiveOnlineExpertMaturedFeedback,
    ProspectiveOnlineExpertPairState,
    advance_prospective_online_expert_pair_state,
)
from scripts.run_geospatial_kernel_online_expert_pair_outcome_free import (
    OUTPUT_SCHEMA,
    compile_outcome_free_online_expert_pair,
)
from scripts.run_geospatial_kernel_online_expert_pair_outcome_free import (
    REPORT_SCHEMA as PREDICTION_RUN_REPORT_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = Path(__file__).resolve()
CORE_PATH = REPO_ROOT / ("data_agent/uwm/geospatial_kernel_v2/prospective_online_expert_pair.py")
OBSERVATION_SCHEMA = "gwm.geospatial_kernel.online_expert_authoritative_observations.v1"
REPORT_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_matured_state_update.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-run-report", type=Path, required=True)
    parser.add_argument("--prior-state", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output-state", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--update-time", type=str)
    return parser.parse_args()


def compile_matured_online_expert_pair_state_update(
    *,
    prediction_run_report_path: Path,
    prior_state_path: Path,
    observations_path: Path,
    output_state_path: Path,
    update_time: datetime,
) -> tuple[bytes, dict[str, Any]]:
    """Recompute a sealed prediction run, then append only available feedback."""

    if not _aware(update_time):
        raise ValueError("online_expert_pair_state_update_time_invalid")
    prior_body, prior_payload = _load_json(prior_state_path)
    prior_state = ProspectiveOnlineExpertPairState.from_dict(prior_payload)
    if prior_state.config != PhysicalOnlineExpertBlendConfig():
        raise ValueError("online_expert_pair_state_update_config_not_frozen")
    run_report_body, run_report, prediction, prediction_state = _recompute_prediction_run(
        prediction_run_report_path
    )
    if not _state_extends(prior_state, prediction_state):
        raise ValueError("online_expert_pair_prior_state_not_prediction_state_extension")
    observation_body, observation_payload = _load_json(observations_path)
    observations, retrieved_at, source_id = _validate_observations(
        observation_payload,
        expected_system_id=prior_state.system_id,
        update_time=update_time,
    )
    prediction_executed_at = _parse_datetime(run_report["executed_at"])
    if prediction_executed_at > min(value["observation_available_at"] for value in observations):
        raise ValueError("online_expert_pair_prediction_not_sealed_before_feedback")
    feedbacks = _feedbacks_from_predictions(
        prediction,
        observations,
        expected_system_id=prior_state.system_id,
    )
    updated_state = advance_prospective_online_expert_pair_state(
        prior_state,
        feedbacks,
        update_time=update_time,
    )
    output_body = _json_body(updated_state.as_dict())
    return output_body, {
        "schema": REPORT_SCHEMA,
        "status": "matured_online_expert_pair_state_update_complete",
        "updated_at": update_time.astimezone(UTC).isoformat(),
        "system_id": prior_state.system_id,
        "observation_source_id": source_id,
        "observation_batch_retrieved_at_utc": _iso(retrieved_at),
        "input_artifacts": {
            "prior_state": _artifact(prior_state_path, prior_body),
            "sealed_prediction_run_report": _artifact(
                prediction_run_report_path,
                run_report_body,
            ),
            "sealed_predictions": dict(run_report["prediction_artifact"]),
            "authoritative_observations": _artifact(
                observations_path,
                observation_body,
            ),
        },
        "implementation_artifacts": {
            "prospective_pair_core": _artifact(CORE_PATH, CORE_PATH.read_bytes()),
            "matured_state_updater": _artifact(
                UPDATER_PATH,
                UPDATER_PATH.read_bytes(),
            ),
        },
        "output_state_artifact": _artifact(output_state_path, output_body),
        "execution": {
            "sealed_prediction_run_recomputed_exactly": True,
            "prediction_row_count": prediction["prediction_count"],
            "matured_feedback_update_count": len(feedbacks),
            "signed_negative_observation_update_count": sum(
                value["observed_discharge_m3s"] < 0.0 for value in observations
            ),
            "prior_sample_count_by_horizon": {
                str(key): value for key, value in prior_state.sample_count_by_horizon().items()
            },
            "updated_sample_count_by_horizon": {
                str(key): value for key, value in updated_state.sample_count_by_horizon().items()
            },
        },
        "causal_boundary": {
            "prediction_created_before_feedback_update": (
                prediction_executed_at
                <= min(value["observation_available_at"] for value in observations)
            ),
            "all_feedback_available_by_update_time": True,
            "prior_state_not_from_future": prior_state.state_as_of <= update_time,
            "raw_observation_retained_in_output_state": False,
            "prediction_code_or_input_refit_during_update": False,
        },
        "claim_boundary": {
            "online_state_update_software_executed": True,
            "prediction_accuracy_scored": False,
            "v5_superiority_over_traditional_selector_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _recompute_prediction_run(
    report_path: Path,
) -> tuple[
    bytes,
    Mapping[str, Any],
    Mapping[str, Any],
    ProspectiveOnlineExpertPairState,
]:
    report_body, report = _load_json(report_path)
    if (
        report.get("schema") != PREDICTION_RUN_REPORT_SCHEMA
        or report.get("status") != "outcome_free_candidate_and_baseline_predictions_complete"
        or not isinstance(report.get("input_artifacts"), Mapping)
        or not isinstance(report.get("prediction_artifact"), Mapping)
    ):
        raise ValueError("online_expert_pair_prediction_run_report_invalid")
    inputs = report["input_artifacts"]
    if set(inputs) != {"issue", "matured_state"}:
        raise ValueError("online_expert_pair_prediction_run_report_invalid")
    issue_path, _ = _read_verified_descriptor(inputs["issue"])
    state_path, state_body = _read_verified_descriptor(inputs["matured_state"])
    output_path, prediction_body = _read_verified_descriptor(report["prediction_artifact"])
    recomputed_body, recomputed_report = compile_outcome_free_online_expert_pair(
        issue_path=issue_path,
        state_path=state_path,
        output_path=output_path,
        executed_at=_parse_datetime(report["executed_at"]),
    )
    if recomputed_body != prediction_body or recomputed_report != report:
        raise ValueError("online_expert_pair_prediction_run_recomputation_failed")
    _, prediction = _load_json(output_path)
    if prediction.get("schema") != OUTPUT_SCHEMA:
        raise ValueError("online_expert_pair_prediction_output_invalid")
    prediction_state_payload = json.loads(state_body)
    if not isinstance(prediction_state_payload, Mapping):
        raise ValueError("online_expert_pair_prediction_state_invalid")
    prediction_state = ProspectiveOnlineExpertPairState.from_dict(prediction_state_payload)
    return report_body, report, prediction, prediction_state


def _state_extends(
    current: ProspectiveOnlineExpertPairState,
    prediction_state: ProspectiveOnlineExpertPairState,
) -> bool:
    if (
        current.system_id != prediction_state.system_id
        or current.config != prediction_state.config
        or current.state_as_of < prediction_state.state_as_of
    ):
        return False
    return all(
        set(prediction_samples).issubset(current.samples_by_horizon[index])
        for index, prediction_samples in enumerate(prediction_state.samples_by_horizon)
    )


def _validate_observations(
    payload: Mapping[str, object],
    *,
    expected_system_id: str,
    update_time: datetime,
) -> tuple[list[dict[str, Any]], datetime, str]:
    if set(payload) != {
        "schema",
        "system_id",
        "retrieved_at_utc",
        "source_id",
        "evidence_level",
        "values_imputed",
        "observations",
    }:
        raise ValueError("online_expert_pair_observation_batch_invalid")
    source_id = payload.get("source_id")
    if (
        payload.get("schema") != OBSERVATION_SCHEMA
        or payload.get("system_id") != expected_system_id
        or not isinstance(source_id, str)
        or not source_id.strip()
        or payload.get("evidence_level") != "authoritative"
        or payload.get("values_imputed") is not False
        or not isinstance(payload.get("observations"), list)
        or not payload["observations"]
    ):
        raise ValueError("online_expert_pair_observation_batch_invalid")
    retrieved_at = _parse_datetime(payload["retrieved_at_utc"])
    if retrieved_at > update_time:
        raise ValueError("online_expert_pair_observation_not_available")
    observations: list[dict[str, Any]] = []
    targets: set[datetime] = set()
    for value in payload["observations"]:
        if not isinstance(value, Mapping) or set(value) != {
            "target_support_end_utc",
            "observed_discharge_m3s",
            "observation_available_at_utc",
            "quality_status",
        }:
            raise ValueError("online_expert_pair_observation_invalid")
        target = _parse_datetime(value["target_support_end_utc"])
        available_at = _parse_datetime(value["observation_available_at_utc"])
        raw_observed = value["observed_discharge_m3s"]
        try:
            observed = float(raw_observed)
        except (TypeError, ValueError) as exc:
            raise ValueError("online_expert_pair_observation_invalid") from exc
        if (
            target in targets
            or isinstance(raw_observed, bool)
            or not math.isfinite(observed)
            or available_at < target
            or available_at > retrieved_at
            or available_at > update_time
            or value.get("quality_status") != "approved"
        ):
            raise ValueError("online_expert_pair_observation_invalid")
        targets.add(target)
        observations.append(
            {
                "target_support_end": target,
                "observed_discharge_m3s": observed,
                "observation_available_at": available_at,
            }
        )
    return observations, retrieved_at, source_id


def _feedbacks_from_predictions(
    prediction: Mapping[str, object],
    observations: list[dict[str, Any]],
    *,
    expected_system_id: str,
) -> tuple[ProspectiveOnlineExpertMaturedFeedback, ...]:
    if set(prediction) != {
        "schema",
        "system_id",
        "issue_time_utc",
        "state_as_of_utc",
        "primary_candidate",
        "traditional_baseline",
        "predictions",
        "prediction_count",
        "raw_observations_included",
        "scores_included",
    } or (
        prediction.get("schema") != OUTPUT_SCHEMA
        or prediction.get("system_id") != expected_system_id
        or prediction.get("raw_observations_included") is not False
        or prediction.get("scores_included") is not False
        or not isinstance(prediction.get("predictions"), list)
        or prediction.get("prediction_count") != len(prediction["predictions"])
    ):
        raise ValueError("online_expert_pair_prediction_output_invalid")
    rows_by_target: dict[datetime, Mapping[str, object]] = {}
    required = {
        "forecast_id",
        "target_support_end_utc",
        "schema",
        "system_id",
        "issue_time_utc",
        "state_as_of_utc",
        "forecast_horizon_hours",
        "physical_online_residual_adaptation_v4_m3s",
        "action_innovation_wwm_m3s",
        "physical_online_expert_blend_v5_m3s",
        "evidence_gated_follow_the_leader_m3s",
        "matured_sample_count",
        "v5_raw_weight",
        "v5_coefficient_gate_passed",
        "v5_shadow_validation_sample_count",
        "v5_shadow_performance_gate_passed",
        "v5_application_gate_passed",
        "v5_applied_weight",
        "v5_shadow_prediction_m3s",
        "traditional_baseline_wwm_selected",
        "raw_observation_used_for_prediction",
        "current_or_future_target_used_for_prediction",
    }
    for row in prediction["predictions"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != required
            or row.get("schema") != PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA
            or row.get("system_id") != expected_system_id
            or row.get("raw_observation_used_for_prediction") is not False
            or row.get("current_or_future_target_used_for_prediction") is not False
        ):
            raise ValueError("online_expert_pair_prediction_row_invalid")
        target = _parse_datetime(row["target_support_end_utc"])
        if target in rows_by_target:
            raise ValueError("online_expert_pair_prediction_target_duplicate")
        rows_by_target[target] = row
    feedbacks = []
    for observation in observations:
        target = observation["target_support_end"]
        row = rows_by_target.get(target)
        if row is None:
            raise ValueError("online_expert_pair_observation_prediction_unmatched")
        feedbacks.append(
            ProspectiveOnlineExpertMaturedFeedback(
                sample_id=row["forecast_id"],
                forecast_horizon_hours=row["forecast_horizon_hours"],
                target_support_end=target,
                observed_discharge_m3s=observation["observed_discharge_m3s"],
                observation_available_at=observation["observation_available_at"],
                baseline_prediction_m3s=row["physical_online_residual_adaptation_v4_m3s"],
                alternative_prediction_m3s=row["action_innovation_wwm_m3s"],
                coefficient_gate_shadow_prediction_m3s=row["v5_shadow_prediction_m3s"],
                coefficient_gate_passed=row["v5_coefficient_gate_passed"],
            )
        )
    return tuple(feedbacks)


def _read_verified_descriptor(
    descriptor: object,
) -> tuple[Path, bytes]:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("online_expert_pair_artifact_descriptor_invalid")
    raw_path = descriptor["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("online_expert_pair_artifact_descriptor_invalid")
    path = Path(raw_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("online_expert_pair_artifact_verification_failed")
    return path, body


def _load_json(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body = path.read_bytes()

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("online_expert_pair_state_update_json_duplicate_key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"online_expert_pair_state_update_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("online_expert_pair_state_update_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("online_expert_pair_state_update_json_invalid")
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
        raise ValueError("online_expert_pair_state_update_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("online_expert_pair_state_update_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("online_expert_pair_state_update_datetime_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    update_time = (
        datetime.now(UTC) if args.update_time is None else _parse_datetime(args.update_time)
    )
    if args.output_state.resolve() == args.prior_state.resolve():
        raise ValueError("online_expert_pair_prior_state_overwrite_forbidden")
    output_body, report = compile_matured_online_expert_pair_state_update(
        prediction_run_report_path=args.prediction_run_report,
        prior_state_path=args.prior_state,
        observations_path=args.observations,
        output_state_path=args.output_state,
        update_time=update_time,
    )
    args.output_state.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output_state.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"system_id={report['system_id']}")
    print(f"matured_feedback_update_count={report['execution']['matured_feedback_update_count']}")


if __name__ == "__main__":
    main()
