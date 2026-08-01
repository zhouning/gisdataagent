#!/usr/bin/env python3
"""Score the sealed two-system kinematic-wave holdout exactly once."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

if __package__:
    from scripts.acquire_geotransport_kinematic_wave_holdout_v1_outcomes import (
        SCHEMA as OUTCOME_SCHEMA,
    )
    from scripts.freeze_geotransport_kinematic_wave_holdout_v1 import (
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SYSTEM_IDS,
    )
    from scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
        _seal_payload,
    )
else:
    from acquire_geotransport_kinematic_wave_holdout_v1_outcomes import (
        SCHEMA as OUTCOME_SCHEMA,
    )
    from freeze_geotransport_kinematic_wave_holdout_v1 import (
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SYSTEM_IDS,
    )
    from run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
        _seal_payload,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_rollout_report.json"
)
DEFAULT_OUTCOMES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_outcomes_report.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_score.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_holdout_score.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_score(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_path: Path = DEFAULT_ROLLOUT,
    outcomes_path: Path = DEFAULT_OUTCOMES,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(protocol_path)
    rollout_body, rollout = _load_json(rollout_path)
    outcome_body, outcomes = _load_json(outcomes_path)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_dynamic_input_and_outcome_access"
        or rollout.get("schema") != ROLLOUT_SCHEMA
        or rollout.get("status") != "joint_outcome_free_predictions_sealed"
        or outcomes.get("schema") != OUTCOME_SCHEMA
        or outcomes.get("status")
        != "two_system_outcomes_acquired_after_joint_seal"
        or outcomes.get("sealed_artifacts", {}).get("rollout_report", {}).get(
            "sha256"
        )
        != hashlib.sha256(rollout_body).hexdigest()
        or outcomes.get("sealed_artifacts", {}).get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or outcomes.get("sealed_artifacts", {}).get("joint_seal_sha256")
        != rollout.get("joint_seal", {}).get("sha256")
        or (outcomes.get("ordering_audit") or {}).get(
            "both_predictions_verified_before_first_outcome_request"
        )
        is not True
        or (outcomes.get("ordering_audit") or {}).get(
            "joint_seal_recomputed_before_first_outcome_request"
        )
        is not True
        or (outcomes.get("ordering_audit") or {}).get(
            "prediction_content_changed_during_outcome_access"
        )
        is not False
    ):
        raise ValueError("kinematic_holdout_score_lineage_invalid")
    _verify_frozen_code(protocol)
    _verify_joint_seal(protocol_body, rollout)

    system_scores: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        prediction_descriptor = rollout["systems"][system_id][
            "prediction_artifact"
        ]
        outcome_descriptor = outcomes["systems"][system_id]["outcome_values"]
        if (
            outcomes["sealed_artifacts"]["predictions"][system_id]
            != prediction_descriptor
        ):
            raise ValueError(
                f"kinematic_holdout_{system_id}_sealed_prediction_mismatch"
            )
        prediction_rows = _prediction_rows(_read_verified(prediction_descriptor))
        observations = _outcome_values(_read_verified(outcome_descriptor))
        system_scores[system_id] = _score_system(
            system_id=system_id,
            prediction_rows=prediction_rows,
            observations=observations,
            rollout_system=rollout["systems"][system_id],
            protocol=protocol,
            outcome_system=outcomes["systems"][system_id],
        )

    predictive_gate = all(
        score["gates"]["all_predictive_and_execution_gates_passed"]
        for score in system_scores.values()
    )
    protocol_conformance = all(
        outcomes["systems"][system_id]["quality"]["native_cadence_predeclared"]
        is True
        for system_id in SYSTEM_IDS
    )
    prospective_gate = predictive_gate and protocol_conformance
    return {
        "schema": SCHEMA,
        "status": "two_system_kinematic_wave_holdout_scored_once",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "sealed_rollout": _artifact(rollout_path, rollout_body),
            "outcomes": _artifact(outcomes_path, outcome_body),
            "joint_prediction_seal_sha256": rollout["joint_seal"]["sha256"],
        },
        "systems": system_scores,
        "multi_system_gates": {
            "both_systems_predictive_and_execution_gates_passed": predictive_gate,
            "strict_protocol_conformance_passed": protocol_conformance,
            "prospective_holdout_gate_passed": prospective_gate,
            "non_compensatory": True,
        },
        "protocol_conformance": {
            "window_systems_operator_topology_and_parameters_predeclared": True,
            "both_predictions_jointly_sealed_before_outcome_access": True,
            "metrics_baseline_missingness_and_gates_predeclared": True,
            "native_cadence_hourly_aggregation_fully_predeclared": True,
            "model_prediction_or_gate_changed_after_outcome_access": False,
            "strict_protocol_conformance_passed": protocol_conformance,
        },
        "independence_limits": {
            "outcome_loaded_only_after_joint_prediction_seal": True,
            "external_tributary_streamflow_boundary_used": False,
            "nwm_initial_streamflow_ground_truth": False,
            "nwm_initial_streamflow_possible_nudging": True,
            "nwm_q_lateral_ground_truth": False,
            "fully_observation_independent_inputs": False,
        },
        "operator_admission": {
            "holdout_gate_passed": prospective_gate,
            "operator_form_admitted_before_scoring": False,
            "operator_form_admitted_by_this_score": False,
            "separate_architecture_decision_required": True,
            "current_role": "diagnostic_geospatial_kernel_candidate",
        },
        "claim_boundary": {
            "two_system_prospective_score_available": True,
            "predictive_gate_passed": predictive_gate,
            "prospective_holdout_gate_passed": prospective_gate,
            "operator_form_admitted": False,
            "geospatial_kernel_validated": False,
            "no_post_score_tuning_or_prediction_revision_permitted": True,
        },
    }


def _score_system(
    *,
    system_id: str,
    prediction_rows: list[dict[str, str]],
    observations: Mapping[str, float | None],
    rollout_system: Mapping[str, Any],
    protocol: Mapping[str, Any],
    outcome_system: Mapping[str, Any],
) -> dict[str, Any]:
    observed: list[float] = []
    kinematic: list[float] = []
    persistence: list[float] = []
    branch_silent: list[float] = []
    direct_release: list[float] = []
    excluded_current_missing = 0
    excluded_previous_missing = 0
    for row in prediction_rows:
        start = _canonical_utc(row["support_start_utc"])
        end = _canonical_utc(row["support_end_utc"])
        current = observations.get(end)
        previous = observations.get(start)
        if current is None:
            excluded_current_missing += 1
            continue
        if previous is None:
            excluded_previous_missing += 1
            continue
        observed.append(float(current))
        kinematic.append(float(row["kinematic_wave_m3s"]))
        persistence.append(float(previous))
        branch_silent.append(float(row["branch_silent_negative_control_m3s"]))
        direct_release.append(float(row["action_input_m3s"]))
    values = np.asarray(observed, dtype=float)
    if not values.size:
        raise ValueError(f"kinematic_holdout_{system_id}_no_scorable_rows")
    metrics = {
        "kinematic_wave": _metrics(values, np.asarray(kinematic)),
        "observed_persistence": _metrics(values, np.asarray(persistence)),
        "branch_silent_negative_control": _metrics(
            values, np.asarray(branch_silent)
        ),
        "same_hour_boundary_release": _metrics(
            values, np.asarray(direct_release)
        ),
    }
    minimum = int(protocol["scoring_lock"]["minimum_scored_hours_per_system"])
    accuracy = (
        metrics["kinematic_wave"]["rmse_m3s"]
        < metrics["observed_persistence"]["rmse_m3s"]
    )
    invariants = rollout_system["invariants"]
    execution = invariants["all_execution_gates_passed"] is True
    enough = len(values) >= minimum
    return {
        "system_id": system_id,
        "scored_hour_count": len(values),
        "mask_audit": {
            "target_hour_count": HOUR_COUNT,
            "excluded_current_observation_missing": excluded_current_missing,
            "excluded_immediate_previous_observation_missing": (
                excluded_previous_missing
            ),
            "common_complete_case_mask": True,
            "outcomes_imputed": False,
        },
        "outcome_sampling": {
            "native_sample_cadence_seconds": outcome_system["quality"][
                "native_sample_cadence_seconds"
            ],
            "native_cadence_predeclared": outcome_system["quality"][
                "native_cadence_predeclared"
            ],
            "expected_native_samples_per_complete_hour": outcome_system["quality"][
                "expected_native_samples_per_complete_hour"
            ],
            "hourly_rule": "mean_of_all_complete_approved_native_samples_on_(t-1h,t]",
        },
        "metrics": metrics,
        "diagnostics": {
            "kinematic_rmse_minus_persistence_rmse_m3s": (
                metrics["kinematic_wave"]["rmse_m3s"]
                - metrics["observed_persistence"]["rmse_m3s"]
            ),
            "kinematic_rmse_minus_branch_silent_rmse_m3s": (
                metrics["kinematic_wave"]["rmse_m3s"]
                - metrics["branch_silent_negative_control"]["rmse_m3s"]
            ),
            "kinematic_beats_branch_silent_rmse": (
                metrics["kinematic_wave"]["rmse_m3s"]
                < metrics["branch_silent_negative_control"]["rmse_m3s"]
            ),
            "branch_silent_is_registered_gate": False,
        },
        "execution_invariants": invariants,
        "gates": {
            "minimum_scored_hours_passed": enough,
            "kinematic_beats_observed_persistence_rmse": accuracy,
            "execution_invariants_passed": execution,
            "all_predictive_and_execution_gates_passed": (
                enough and accuracy and execution
            ),
        },
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if (
        observed.shape != predicted.shape
        or not np.isfinite(observed).all()
        or not np.isfinite(predicted).all()
    ):
        raise ValueError("kinematic_holdout_metric_values_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - float(observed.mean())) ** 2))
    if denominator <= 0.0:
        raise ValueError("kinematic_holdout_nse_requires_observed_variation")
    return {
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _prediction_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_start_utc",
        "support_end_utc",
        "kinematic_wave_m3s",
        "branch_silent_negative_control_m3s",
        "action_input_m3s",
        "distributed_q_lateral_input_m3s",
        "branch_q_lateral_input_m3s",
    ]
    rows = list(reader)
    if reader.fieldnames != expected or len(rows) != HOUR_COUNT:
        raise ValueError("kinematic_holdout_prediction_axis_or_columns_invalid")
    for index, row in enumerate(rows):
        start = START + timedelta(hours=index)
        if (
            _canonical_utc(row["support_start_utc"]) != _iso(start)
            or _canonical_utc(row["support_end_utc"])
            != _iso(start + timedelta(hours=1))
        ):
            raise ValueError("kinematic_holdout_prediction_time_axis_invalid")
        for column in expected[2:]:
            if not np.isfinite(float(row[column])):
                raise ValueError("kinematic_holdout_prediction_value_nonfinite")
    return rows


def _outcome_values(body: bytes) -> dict[str, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
        "evaluation_role",
    ]
    if reader.fieldnames != expected:
        raise ValueError("kinematic_holdout_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    roles: list[str] = []
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("kinematic_holdout_outcome_role_invalid")
        key = _canonical_utc(row["support_end_utc"])
        if key in result:
            raise ValueError("kinematic_holdout_outcome_duplicate_timestamp")
        value = (
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
        )
        if value is not None and (not np.isfinite(value) or value < 0.0):
            raise ValueError("kinematic_holdout_outcome_value_invalid")
        result[key] = value
        roles.append(row["evaluation_role"])
    expected_axis = {
        _iso(START + timedelta(hours=index)) for index in range(HOUR_COUNT + 1)
    }
    if (
        set(result) != expected_axis
        or roles[0] != "persistence_prior"
        or any(value != "target" for value in roles[1:])
    ):
        raise ValueError("kinematic_holdout_outcome_axis_invalid")
    return result


def _verify_joint_seal(
    protocol_body: bytes, rollout: Mapping[str, Any]
) -> None:
    input_descriptor = rollout["input_artifacts"]["input_report"]
    _read_verified(input_descriptor)
    predictions = {
        system_id: rollout["systems"][system_id]["prediction_artifact"]
        for system_id in SYSTEM_IDS
    }
    for descriptor in predictions.values():
        _read_verified(descriptor)
    seal_payload = _seal_payload(
        protocol_sha256=hashlib.sha256(protocol_body).hexdigest(),
        input_report_sha256=str(input_descriptor["sha256"]),
        predictions=predictions,
    )
    if hashlib.sha256(seal_payload).hexdigest() != rollout["joint_seal"]["sha256"]:
        raise ValueError("kinematic_holdout_score_joint_seal_hash_mismatch")


def _verify_frozen_code(protocol: Mapping[str, Any]) -> None:
    descriptors = protocol.get("frozen_code") or {}
    if not descriptors:
        raise ValueError("kinematic_holdout_frozen_code_missing")
    for descriptor in descriptors.values():
        _read_verified(descriptor)


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("kinematic_holdout_score_timezone_required")
    return _iso(parsed)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("kinematic_holdout_score_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("kinematic_holdout_score_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("kinematic_holdout_score_already_exists")
    report = compile_score(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        outcomes_path=args.outcomes,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    for system_id in SYSTEM_IDS:
        metrics = report["systems"][system_id]["metrics"]
        print(
            f"{system_id}_kinematic_rmse_m3s="
            f"{metrics['kinematic_wave']['rmse_m3s']}"
        )
        print(
            f"{system_id}_persistence_rmse_m3s="
            f"{metrics['observed_persistence']['rmse_m3s']}"
        )
    print(
        "prospective_holdout_gate_passed="
        f"{report['multi_system_gates']['prospective_holdout_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
