#!/usr/bin/env python3
"""Score the sealed two-system blind validation exactly once."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

if __package__:
    from scripts.acquire_geotransport_v2_blind_validation_outcomes import (
        SCHEMA as OUTCOME_SCHEMA,
    )
    from scripts.freeze_geotransport_v2_blind_validation_protocol import (
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
    )
    from scripts.run_geotransport_v2_blind_validation_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
    )
else:
    from acquire_geotransport_v2_blind_validation_outcomes import (
        SCHEMA as OUTCOME_SCHEMA,
    )
    from freeze_geotransport_v2_blind_validation_protocol import (
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
    )
    from run_geotransport_v2_blind_validation_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_rollout_report.json"
)
DEFAULT_OUTCOMES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_outcomes_report.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_score.json"
)
SCHEMA = "gwm.geotransport.v2_blind_validation_score.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")


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
        or (outcomes.get("ordering_audit") or {}).get(
            "both_predictions_verified_before_first_outcome_request"
        )
        is not True
    ):
        raise ValueError("blind_validation_score_lineage_invalid")

    system_scores: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        prediction_descriptor = rollout["systems"][system_id][
            "prediction_artifact"
        ]
        outcome_descriptor = outcomes["systems"][system_id]["outcome_values"]
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
    strict_protocol_conformance = False
    confirmatory_gate = predictive_gate and strict_protocol_conformance
    return {
        "schema": SCHEMA,
        "status": "two_system_blind_validation_scored_once",
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
            "strict_protocol_conformance_passed": strict_protocol_conformance,
            "confirmatory_validation_gate_passed": confirmatory_gate,
            "non_compensatory": True,
        },
        "protocol_conformance": {
            "window_systems_operator_topology_and_parameters_predeclared": True,
            "both_predictions_sealed_before_outcome_access": True,
            "metrics_baseline_missingness_and_gates_predeclared": True,
            "native_cadence_hourly_aggregation_fully_predeclared": False,
            "deviation": (
                "The protocol specified one-hour observed streamflow but did not "
                "predeclare that Center Hill has 30-minute IV samples and J. Percy "
                "Priest has 15-minute IV samples. After the joint seal, both were "
                "reduced by the same complete-native-sample interval-mean rule."
            ),
            "model_prediction_or_gate_changed_after_outcome_access": False,
            "effect_on_claim": (
                "results are a strong prospective replication but not a fully "
                "protocol-conformant confirmatory validation"
            ),
        },
        "independence_limits": {
            "outcome_loaded_only_after_joint_prediction_seal": True,
            "external_tributary_streamflow_boundary_used": False,
            "nwm_initial_streamflow_ground_truth": False,
            "nwm_initial_streamflow_possible_nudging": True,
            "nwm_q_lateral_ground_truth": False,
            "fully_observation_independent_inputs": False,
        },
        "claim_boundary": {
            "two_system_blind_score_available": True,
            "predictive_gate_passed": predictive_gate,
            "strict_confirmatory_validation_passed": confirmatory_gate,
            "geospatial_kernel_predictively_validated": confirmatory_gate,
            "no_post_score_tuning_or_revision_permitted": True,
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
    kernel: list[float] = []
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
        kernel.append(float(row["kernel_full_subnetwork_m3s"]))
        persistence.append(float(previous))
        branch_silent.append(float(row["branch_silent_negative_control_m3s"]))
        direct_release.append(float(row["action_input_m3s"]))
    values = np.asarray(observed, dtype=float)
    if not values.size:
        raise ValueError(f"blind_validation_{system_id}_no_scorable_rows")
    metrics = {
        "kernel_full_subnetwork": _metrics(values, np.asarray(kernel)),
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
        metrics["kernel_full_subnetwork"]["rmse_m3s"]
        < metrics["observed_persistence"]["rmse_m3s"]
    )
    invariants = rollout_system["invariants"]
    mass = (
        invariants["actual_conservation_passed"]
        and invariants["branch_silent_conservation_passed"]
        and invariants["zero_state_zero_input_identity_passed"]
        and invariants["modeled_tributary_boundary_never_used"]
    )
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
            "expected_native_samples_per_complete_hour": outcome_system["quality"][
                "expected_native_samples_per_complete_hour"
            ],
            "hourly_rule": "mean_of_all_complete_native_samples_on_(t-1h,t]",
        },
        "metrics": metrics,
        "diagnostics": {
            "kernel_rmse_minus_persistence_rmse_m3s": (
                metrics["kernel_full_subnetwork"]["rmse_m3s"]
                - metrics["observed_persistence"]["rmse_m3s"]
            ),
            "kernel_rmse_minus_branch_silent_rmse_m3s": (
                metrics["kernel_full_subnetwork"]["rmse_m3s"]
                - metrics["branch_silent_negative_control"]["rmse_m3s"]
            ),
            "kernel_beats_branch_silent_rmse": (
                metrics["kernel_full_subnetwork"]["rmse_m3s"]
                < metrics["branch_silent_negative_control"]["rmse_m3s"]
            ),
        },
        "gates": {
            "minimum_scored_hours_passed": enough,
            "kernel_beats_observed_persistence_rmse": accuracy,
            "execution_and_mass_invariants_passed": mass,
            "all_predictive_and_execution_gates_passed": enough and accuracy and mass,
        },
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    denominator = float(np.sum((observed - float(observed.mean())) ** 2))
    return {
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _prediction_rows(body: bytes) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    expected = [
        "support_start_utc",
        "support_end_utc",
        "kernel_full_subnetwork_m3s",
        "branch_silent_negative_control_m3s",
        "action_input_m3s",
        "distributed_q_lateral_input_m3s",
        "branch_q_lateral_input_m3s",
    ]
    if len(rows) != HOUR_COUNT or not rows or list(rows[0]) != expected:
        raise ValueError("blind_validation_prediction_axis_or_columns_invalid")
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
        raise ValueError("blind_validation_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    roles: list[str] = []
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("blind_validation_outcome_role_invalid")
        key = _canonical_utc(row["support_end_utc"])
        result[key] = (
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
        )
        roles.append(row["evaluation_role"])
    if (
        len(result) != HOUR_COUNT + 1
        or roles[0] != "persistence_prior"
        or any(value != "target" for value in roles[1:])
    ):
        raise ValueError("blind_validation_outcome_axis_invalid")
    return result


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("blind_validation_score_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("blind_validation_score_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("blind_validation_score_artifact_identity_mismatch")
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


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("blind_validation_score_already_exists")
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
            f"{system_id}_kernel_rmse_m3s="
            f"{metrics['kernel_full_subnetwork']['rmse_m3s']}"
        )
        print(
            f"{system_id}_persistence_rmse_m3s="
            f"{metrics['observed_persistence']['rmse_m3s']}"
        )
    print(
        "confirmatory_validation_gate_passed="
        f"{report['multi_system_gates']['confirmatory_validation_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
