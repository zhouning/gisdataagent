#!/usr/bin/env python3
"""Verify the chronological holdout seal chain without loading scoring outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)

if __package__:
    from scripts import (
        acquire_geospatial_kernel_horizon_assimilation_holdout_static_inputs as static,
    )
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
    )
    from scripts import (
        plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan,
    )
    from scripts import (
        run_geospatial_kernel_horizon_assimilation_holdout_outcome_free as run,
    )
else:
    import acquire_geospatial_kernel_horizon_assimilation_holdout_static_inputs as static
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze
    import plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan
    import run_geospatial_kernel_horizon_assimilation_holdout_outcome_free as run

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = freeze.DEFAULT_OUTPUT
DEFAULT_FROZEN_PLAN = frozen_plan.DEFAULT_OUTPUT
DEFAULT_STATIC_REPORT = static.DEFAULT_REPORT
DEFAULT_ROLLOUT_REPORT = run.DEFAULT_REPORT
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_rollout_verification.json"
)
RUNNER_PATH = REPO_ROOT / (
    "scripts/run_geospatial_kernel_horizon_assimilation_holdout_outcome_free.py"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_rollout_verification.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--frozen-plan", type=Path, default=DEFAULT_FROZEN_PLAN)
    parser.add_argument("--static-report", type=Path, default=DEFAULT_STATIC_REPORT)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def verify_rollout(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frozen_plan_path: Path = DEFAULT_FROZEN_PLAN,
    static_report_path: Path = DEFAULT_STATIC_REPORT,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(protocol_path)
    plan_body, plan = _load_json(frozen_plan_path)
    static_body, static_report = _load_json(static_report_path)
    rollout_body, rollout = _load_json(rollout_report_path)
    _validate_lineage(
        protocol_body=protocol_body,
        protocol=protocol,
        plan_body=plan_body,
        plan=plan,
        static_body=static_body,
        static_report=static_report,
        rollout=rollout,
    )
    policy = HorizonAssimilationPolicy.from_dict(protocol["candidate_lock"]["policy"])
    prediction_body = _read_verified(rollout["prediction_artifact"])
    expected_rows: list[dict[str, object]] = []
    previous_seal: str | None = None
    physical_checks = 0
    physical_passes = 0
    analysis_checks = 0
    analysis_passes = 0
    conformance_checks = 0
    conformance_passes = 0
    maximum_conformance_error = 0.0
    raw_observation_checks = 0
    next_state_checks = 0
    system_observations: dict[str, Counter[str]] = {
        value: Counter() for value in freeze.SYSTEM_IDS
    }
    issue_times = protocol["window"]["issue_times_utc"]

    for ordinal, (issue_index, issue_time, descriptor) in enumerate(
        zip(
            freeze.ISSUE_INDICES,
            issue_times,
            rollout["issue_artifacts"],
            strict=True,
        )
    ):
        issue_body = _read_verified(descriptor)
        issue = json.loads(issue_body)
        if not isinstance(issue, dict):
            raise ValueError("horizon_holdout_verification_issue_document_invalid")
        seal = issue.pop("joint_issue_seal", None)
        computed_seal = hashlib.sha256(run._canonical_json(issue)).hexdigest()
        lineage = issue.get("lineage") or {}
        if (
            issue.get("schema") != run.ISSUE_SCHEMA
            or issue.get("status")
            != "joint_issue_predictions_sealed_before_next_issue_request"
            or issue.get("issue_ordinal") != ordinal
            or issue.get("issue_index") != issue_index
            or issue.get("issue_time_utc") != issue_time
            or descriptor.get("issue_index") != issue_index
            or descriptor.get("issue_time_utc") != issue_time
            or descriptor.get("joint_issue_seal_sha256") != computed_seal
            or not isinstance(seal, Mapping)
            or seal.get("sha256") != computed_seal
            or lineage.get("previous_joint_issue_seal_sha256") != previous_seal
            or lineage.get("protocol_sha256")
            != hashlib.sha256(protocol_body).hexdigest()
            or lineage.get("frozen_input_plan_sha256")
            != hashlib.sha256(plan_body).hexdigest()
            or lineage.get("static_input_report_sha256")
            != hashlib.sha256(static_body).hexdigest()
            or lineage.get("policy_sha256")
            != protocol["candidate_lock"]["policy_sha256"]
        ):
            raise ValueError("horizon_holdout_verification_issue_seal_invalid")
        previous_seal = computed_seal
        _validate_issue_boundaries(issue)

        restored_issue = {**issue, "joint_issue_seal": dict(seal)}
        expected_rows.extend(run._prediction_rows(restored_issue))
        for system_id in freeze.SYSTEM_IDS:
            system = issue["systems"][system_id]
            _read_verified(system["issue_observation_raw"])
            _read_verified(system["next_canonical_state"])
            raw_observation_checks += 1
            next_state_checks += 1
            observation = system["observation"]
            stats = system_observations[system_id]
            stats["issue_count"] += 1
            if observation.get("exact_issue_timestamp_found") is True:
                stats["exact_timestamp_count"] += 1
            if observation.get("value_m3s") is None:
                stats["fallback_count"] += 1
                stats[f"fallback:{observation.get('fallback_reason')}"] += 1
            elif float(observation["value_m3s"]) < 0.0:
                stats["negative_value_count"] += 1
            else:
                stats["nonnegative_value_count"] += 1
            rollout_result = system["rollout"]
            if rollout_result["policy"] != policy.as_dict():
                raise ValueError("horizon_holdout_verification_policy_drift")
            gates = rollout_result["execution_gates"]
            if gates != {
                "all_analysis_ledgers_passed": True,
                "all_physical_mass_balances_passed": True,
                "localized_updates_preserved_all_branch_states": True,
            }:
                raise ValueError("horizon_holdout_verification_execution_gate_failed")
            mode_rollouts = rollout_result["mode_rollouts"]
            if tuple(value["mode"] for value in mode_rollouts) != (
                HORIZON_ASSIMILATION_MODES
            ):
                raise ValueError("horizon_holdout_verification_mode_order_invalid")
            for mode in mode_rollouts:
                analysis_checks += 1
                analysis_passes += mode["analysis_ledger_passed"] is True
                physical_checks += int(mode["physical_mass_balance_check_count"])
                physical_passes += int(mode["physical_mass_balance_pass_count"])
                if mode["physical_mass_balance_check_count"] != 12:
                    raise ValueError(
                        "horizon_holdout_verification_physical_step_count_invalid"
                    )
                _validate_observation_assimilation(mode, observation)
            selected = rollout_result["selected_predictions"]
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
                if selected[str(horizon)]["mode"] != policy.mode_for_horizon(horizon):
                    raise ValueError("horizon_holdout_verification_policy_route_invalid")
            conformance = system["nominal_canonical_conformance"]
            conformance_checks += 1
            conformance_passes += conformance.get("passed") is True
            maximum_conformance_error = max(
                maximum_conformance_error,
                float(conformance.get("maximum_absolute_error_m3s", float("inf"))),
            )
            if (
                conformance.get("maximum_absolute_error_m3s", float("inf"))
                > run.NOMINAL_CONFORMANCE_ABSOLUTE_TOLERANCE_M3S
            ):
                raise ValueError("horizon_holdout_verification_conformance_failed")

    reconstructed_predictions = run._encode_rows(expected_rows)
    if reconstructed_predictions != prediction_body:
        raise ValueError("horizon_holdout_verification_prediction_reconstruction_failed")
    _validate_prediction_columns_and_count(prediction_body)
    expected_physical = (
        len(freeze.SYSTEM_IDS)
        * len(freeze.ISSUE_INDICES)
        * len(HORIZON_ASSIMILATION_MODES)
        * 12
    )
    expected_analysis = (
        len(freeze.SYSTEM_IDS)
        * len(freeze.ISSUE_INDICES)
        * len(HORIZON_ASSIMILATION_MODES)
    )
    if (
        previous_seal != rollout["joint_chain"]["final_joint_issue_seal_sha256"]
        or physical_checks != expected_physical
        or physical_passes != physical_checks
        or analysis_checks != expected_analysis
        or analysis_passes != analysis_checks
        or conformance_checks != len(freeze.SYSTEM_IDS) * len(freeze.ISSUE_INDICES)
        or conformance_passes != conformance_checks
        or raw_observation_checks != len(freeze.SYSTEM_IDS) * len(freeze.ISSUE_INDICES)
        or next_state_checks != raw_observation_checks
    ):
        raise ValueError("horizon_holdout_verification_aggregate_gate_failed")

    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_holdout_verification_generated_at_must_be_aware")
    return {
        "schema": SCHEMA,
        "status": "pass_chronological_outcome_free_rollout_verification",
        "generated_at": now.astimezone(UTC).isoformat(),
        "verified_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "input_plan": _artifact(frozen_plan_path, plan_body),
            "static_input_report": _artifact(static_report_path, static_body),
            "rollout_report": _artifact(rollout_report_path, rollout_body),
            "prediction_artifact": dict(rollout["prediction_artifact"]),
            "execution_wrapper_recorded_after_execution": _artifact(
                RUNNER_PATH,
                RUNNER_PATH.read_bytes(),
            ),
        },
        "seal_chain": {
            "joint_issue_seal_count": len(freeze.ISSUE_INDICES),
            "final_joint_issue_seal_sha256": previous_seal,
            "chronological_chain_verified": True,
            "all_issue_artifact_hashes_verified": True,
            "all_previous_seal_links_verified": True,
        },
        "execution_gates": {
            "analysis_ledger_check_count": analysis_checks,
            "analysis_ledger_pass_count": analysis_passes,
            "physical_mass_balance_check_count": physical_checks,
            "physical_mass_balance_pass_count": physical_passes,
            "nominal_conformance_check_count": conformance_checks,
            "nominal_conformance_pass_count": conformance_passes,
            "maximum_nominal_conformance_error_m3s": maximum_conformance_error,
            "raw_issue_observation_hash_check_count": raw_observation_checks,
            "next_canonical_state_hash_check_count": next_state_checks,
            "prediction_csv_reconstructed_exactly": True,
            "all_execution_gates_passed": True,
        },
        "observations": {
            system_id: dict(values)
            for system_id, values in system_observations.items()
        },
        "request_boundary": {
            "frozen_request_count_completed": 122,
            "static_request_count": 10,
            "issue_only_usgs_request_count": 112,
            "full_outcome_request_count": 0,
            "full_outcome_series_loaded": False,
        },
        "claim_boundary": {
            "outcome_free_predictions_verified": True,
            "holdout_outcomes_acquired_for_scoring": False,
            "holdout_scored": False,
            "candidate_support_gate_evaluated": False,
            "geospatial_kernel_validated": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _validate_lineage(
    *,
    protocol_body: bytes,
    protocol: Mapping[str, Any],
    plan_body: bytes,
    plan: Mapping[str, Any],
    static_body: bytes,
    static_report: Mapping[str, Any],
    rollout: Mapping[str, Any],
) -> None:
    if (
        protocol.get("schema") != freeze.SCHEMA
        or plan.get("schema") != frozen_plan.SCHEMA
        or static_report.get("schema") != static.SCHEMA
        or rollout.get("schema") != run.SCHEMA
        or rollout.get("status")
        != "all_chronological_issue_predictions_jointly_sealed"
        or rollout.get("frozen_artifacts", {}).get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or rollout.get("frozen_artifacts", {}).get("input_plan", {}).get("sha256")
        != hashlib.sha256(plan_body).hexdigest()
        or rollout.get("frozen_artifacts", {}).get("static_input_report", {}).get(
            "sha256"
        )
        != hashlib.sha256(static_body).hexdigest()
        or rollout.get("execution", {}).get("joint_issue_seal_count") != 56
        or rollout.get("execution", {}).get("usgs_issue_request_count") != 112
        or rollout.get("execution", {}).get("frozen_total_request_count_completed")
        != 122
        or rollout.get("claim_boundary", {}).get("holdout_scored") is not False
        or rollout.get("claim_boundary", {}).get("candidate_promoted") is not False
        or rollout.get("data_isolation", {}).get("scores_computed") is not False
    ):
        raise ValueError("horizon_holdout_verification_lineage_invalid")


def _validate_issue_boundaries(issue: Mapping[str, Any]) -> None:
    ordering = issue.get("ordering_audit") or {}
    isolation = issue.get("data_isolation") or {}
    claims = issue.get("claim_boundary") or {}
    if (
        ordering.get("both_system_issue_observations_loaded") is not True
        or ordering.get("all_constituent_predictions_executed") is not True
        or ordering.get("both_next_canonical_states_sealed") is not True
        or ordering.get("next_issue_request_started") is not False
        or ordering.get("bulk_prefetch_used") is not False
        or isolation.get("post_issue_observation_requested") is not False
        or isolation.get("future_target_argument_accepted") is not False
        or isolation.get("score_or_loss_argument_accepted") is not False
        or isolation.get("full_outcome_series_requested") is not False
        or claims.get("holdout_scored") is not False
        or claims.get("candidate_promoted") is not False
        or claims.get("runtime_default_enabled") is not False
    ):
        raise ValueError("horizon_holdout_verification_issue_boundary_invalid")


def _validate_observation_assimilation(
    mode: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> None:
    mode_id = mode.get("mode")
    value = observation.get("value_m3s")
    if mode_id == "nominal":
        expected_assimilated = False
        expected_fallback = None
    elif value is None:
        expected_assimilated = False
        expected_fallback = "missing_issue_observation"
    elif float(value) < 0.0:
        expected_assimilated = False
        expected_fallback = "negative_discharge_outside_forward_manning_domain"
    else:
        expected_assimilated = True
        expected_fallback = None
    if (
        mode.get("observation_assimilated") is not expected_assimilated
        or mode.get("observation_fallback_reason") != expected_fallback
    ):
        raise ValueError("horizon_holdout_verification_assimilation_boundary_invalid")


def _validate_prediction_columns_and_count(body: bytes) -> None:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "issue_index",
        "issue_time_utc",
        "system_id",
        "mode",
        "horizon_hours",
        "target_time_utc",
        "predicted_outlet_m3s",
        "selected_by_policy",
        "issue_observed_outlet_m3s",
        "observation_fallback_reason",
    ]
    if reader.fieldnames != expected or sum(1 for _ in reader) != 1792:
        raise ValueError("horizon_holdout_verification_prediction_axis_invalid")
    if set(expected).intersection({"observed_target_m3s", "score", "loss"}):
        raise ValueError("horizon_holdout_verification_target_column_forbidden")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_verification_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_verification_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_verification_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_verification_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = verify_rollout(
        protocol_path=args.protocol,
        frozen_plan_path=args.frozen_plan,
        static_report_path=args.static_report,
        rollout_report_path=args.rollout_report,
    )
    _write_json(args.output, report)
    print(args.output)
    print(
        "joint_issue_seals_verified="
        f"{report['seal_chain']['joint_issue_seal_count']} "
        "physical_mass_checks="
        f"{report['execution_gates']['physical_mass_balance_check_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
