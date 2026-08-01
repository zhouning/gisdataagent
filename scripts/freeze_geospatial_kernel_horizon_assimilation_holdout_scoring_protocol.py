#!/usr/bin/env python3
"""Freeze outcome requests and scoring semantics before full-outcome access."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

if __package__:
    from scripts import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout
    from scripts import run_geospatial_kernel_horizon_assimilation_holdout_outcome_free as rollout
    from scripts import (
        verify_geospatial_kernel_horizon_assimilation_holdout_rollout as verification,
    )
else:
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout
    import run_geospatial_kernel_horizon_assimilation_holdout_outcome_free as rollout
    import verify_geospatial_kernel_horizon_assimilation_holdout_rollout as verification


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDOUT_PROTOCOL = holdout.DEFAULT_OUTPUT
DEFAULT_INPUT_PLAN = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_input_plan.json"
)
DEFAULT_ROLLOUT_REPORT = rollout.DEFAULT_REPORT
DEFAULT_ROLLOUT_VERIFICATION = verification.DEFAULT_OUTPUT
DEFAULT_PREDICTIONS = rollout.DEFAULT_OUTPUT / "predictions.csv"
DEFAULT_ACQUISITION_SCRIPT = REPO_ROOT / (
    "scripts/acquire_geospatial_kernel_horizon_assimilation_holdout_outcomes.py"
)
DEFAULT_SCORER_SCRIPT = REPO_ROOT / (
    "scripts/score_geospatial_kernel_horizon_assimilation_holdout.py"
)
DEFAULT_PARSER_HELPER = REPO_ROOT / (
    "scripts/acquire_geotransport_v2_blind_validation_outcomes.py"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_scoring_protocol.json"
)
DEFAULT_OUTCOME_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout/outcomes"
)
DEFAULT_OUTCOME_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_outcomes_report.json"
)
DEFAULT_SCORE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score.json"
)
DEFAULT_SCORED_CASES = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout/scoring/scored_cases.csv"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_scoring_protocol.v1"
INPUT_PLAN_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_input_plan.v1"
PREDICTION_SHA256 = "7cace0b963bfc2914130f3e002627f0aa48f0109abc4a82fbd09de93df53ac5a"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-protocol", type=Path, default=DEFAULT_HOLDOUT_PROTOCOL)
    parser.add_argument("--input-plan", type=Path, default=DEFAULT_INPUT_PLAN)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument(
        "--rollout-verification", type=Path, default=DEFAULT_ROLLOUT_VERIFICATION
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--acquisition-script", type=Path, default=DEFAULT_ACQUISITION_SCRIPT)
    parser.add_argument("--scorer-script", type=Path, default=DEFAULT_SCORER_SCRIPT)
    parser.add_argument("--parser-helper", type=Path, default=DEFAULT_PARSER_HELPER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_scoring_protocol(
    *,
    holdout_protocol_path: Path = DEFAULT_HOLDOUT_PROTOCOL,
    input_plan_path: Path = DEFAULT_INPUT_PLAN,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    rollout_verification_path: Path = DEFAULT_ROLLOUT_VERIFICATION,
    predictions_path: Path = DEFAULT_PREDICTIONS,
    acquisition_script_path: Path = DEFAULT_ACQUISITION_SCRIPT,
    scorer_script_path: Path = DEFAULT_SCORER_SCRIPT,
    parser_helper_path: Path = DEFAULT_PARSER_HELPER,
    frozen_at: datetime | None = None,
) -> dict[str, Any]:
    holdout_body, protocol = _load_json(holdout_protocol_path)
    plan_body, plan = _load_json(input_plan_path)
    rollout_body, rollout_report = _load_json(rollout_report_path)
    verification_body, verification_report = _load_json(rollout_verification_path)
    prediction_body = predictions_path.read_bytes()
    acquisition_body = acquisition_script_path.read_bytes()
    scorer_body = scorer_script_path.read_bytes()
    helper_body = parser_helper_path.read_bytes()
    _validate_lineage(
        protocol=protocol,
        protocol_body=holdout_body,
        plan=plan,
        plan_body=plan_body,
        rollout_report=rollout_report,
        rollout_body=rollout_body,
        verification_report=verification_report,
        verification_body=verification_body,
        prediction_body=prediction_body,
    )
    now = frozen_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_holdout_scoring_frozen_at_must_be_aware")

    requests = []
    for system_id in holdout.SYSTEM_IDS:
        outcome = protocol["systems"][system_id]["future_scoring_outcome"]
        query = urlencode(
            {
                "format": "json",
                "sites": outcome["site_id"],
                "parameterCd": outcome["parameter_code"],
                "startDT": protocol["window"]["start_inclusive_utc"],
                "endDT": protocol["window"]["end_exclusive_utc"],
                "siteStatus": "all",
            }
        )
        requests.append(
            {
                "system_id": system_id,
                "method": "GET",
                "url": f"https://waterservices.usgs.gov/nwis/iv/?{query}",
                "site_id": outcome["site_id"],
                "parameter_code": outcome["parameter_code"],
                "request_start_utc": protocol["window"]["start_inclusive_utc"],
                "request_end_utc": protocol["window"]["end_exclusive_utc"],
                "logical_request_count": 1,
                "maximum_remote_attempts": 1,
            }
        )

    frozen_artifacts = {
        "holdout_protocol": _artifact(holdout_protocol_path, holdout_body),
        "input_plan": _artifact(input_plan_path, plan_body),
        "rollout_report": _artifact(rollout_report_path, rollout_body),
        "rollout_verification": _artifact(
            rollout_verification_path, verification_body
        ),
        "predictions": _artifact(predictions_path, prediction_body),
        "outcome_acquisition_script": _artifact(
            acquisition_script_path, acquisition_body
        ),
        "scorer_script": _artifact(scorer_script_path, scorer_body),
        "native_hourly_parser_helper": _artifact(parser_helper_path, helper_body),
    }
    return {
        "schema": SCHEMA,
        "status": "frozen_before_full_outcome_access",
        "frozen_at": now.astimezone(UTC).isoformat(),
        "scientific_role": (
            "single-use scoring addendum for a frozen-after-design historical "
            "holdout; not real-time prospective evidence"
        ),
        "frozen_artifacts": frozen_artifacts,
        "outcome_request_lock": {
            "source": "USGS Water Services IV",
            "logical_request_count": len(requests),
            "maximum_total_remote_attempts": len(requests),
            "requests": requests,
            "additional_outcome_request_permitted": False,
        },
        "target_lock": {
            "predicted_quantity": "outlet_discharge_hourly_interval_mean_m3s",
            "target_quantity": "USGS_00060_complete_native_sample_hourly_mean_m3s",
            "support_interval": "(target_time_minus_1h,target_time]",
            "request_boundary_samples": (
                "timestamps_equal_to_request_start_are_excluded; timestamps "
                "equal_to_request_end_are_included"
            ),
            "unit_conversion_ft3s_to_m3s": 0.028316846592,
            "native_cadence_rule": (
                "greatest_common_divisor_of_positive_sample_time_deltas; "
                "300_to_3600_seconds_and_must_divide_3600"
            ),
            "complete_hour_rule": (
                "exactly_3600_divided_by_native_cadence_approved_samples"
            ),
            "accepted_qualifiers": ["A"],
            "missing_hour_imputation": False,
        },
        "scoring_lock": dict(protocol["scoring_lock"]),
        "scoring_interpretation": {
            "candidate": "one_prediction_marked_selected_by_policy_per_issue_horizon",
            "fixed_comparator_mode": (
                "quadratic_distance_localized_mainstem_update"
            ),
            "traditional_comparator_value": (
                "sealed_exact_issue_observed_outlet_m3s_held_constant_to_target"
            ),
            "mask": (
                "common finite complete case across target candidate fixed "
                "comparator and persistence separately per system and horizon"
            ),
            "strict_below": "candidate_rmse < each_comparator_rmse; ties_fail",
            "gate_count": len(holdout.SYSTEM_IDS)
            * len(protocol["window"]["horizons_hours"]),
            "score_execution_count": 1,
            "post_score_tuning_or_rescoring_permitted": False,
        },
        "pre_access_audit": {
            "outcome_full_series_requested": False,
            "outcome_full_series_loaded": False,
            "score_computed": False,
            "outcome_acquisition_and_scorer_hashes_frozen": True,
            "exact_outcome_urls_frozen": True,
            "rollout_verification_passed": True,
        },
        "claim_boundary": {
            "scoring_protocol_frozen": True,
            "holdout_outcomes_acquired": False,
            "holdout_scored": False,
            "candidate_support_gate_evaluated": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_lineage(
    *,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    plan: Mapping[str, Any],
    plan_body: bytes,
    rollout_report: Mapping[str, Any],
    rollout_body: bytes,
    verification_report: Mapping[str, Any],
    verification_body: bytes,
    prediction_body: bytes,
) -> None:
    del verification_body
    if (
        protocol.get("schema") != holdout.SCHEMA
        or plan.get("schema") != INPUT_PLAN_SCHEMA
        or rollout_report.get("schema") != rollout.SCHEMA
        or rollout_report.get("status")
        != "all_chronological_issue_predictions_jointly_sealed"
        or verification_report.get("schema") != verification.SCHEMA
        or verification_report.get("status")
        != "pass_chronological_outcome_free_rollout_verification"
        or verification_report.get("execution_gates", {}).get(
            "all_execution_gates_passed"
        )
        is not True
        or rollout_report.get("data_isolation", {}).get(
            "full_outcome_series_requested"
        )
        is not False
        or rollout_report.get("data_isolation", {}).get("scores_computed")
        is not False
    ):
        raise ValueError("horizon_holdout_scoring_lineage_invalid")
    descriptors = rollout_report.get("frozen_artifacts") or {}
    verified = verification_report.get("verified_artifacts") or {}
    if (
        descriptors.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or descriptors.get("input_plan", {}).get("sha256")
        != hashlib.sha256(plan_body).hexdigest()
        or verified.get("rollout_report", {}).get("sha256")
        != hashlib.sha256(rollout_body).hexdigest()
        or rollout_report.get("prediction_artifact", {}).get("sha256")
        != hashlib.sha256(prediction_body).hexdigest()
        or hashlib.sha256(prediction_body).hexdigest() != PREDICTION_SHA256
        or verified.get("prediction_artifact", {}).get("sha256")
        != PREDICTION_SHA256
    ):
        raise ValueError("horizon_holdout_scoring_artifact_lineage_invalid")


def _assert_pristine(output_path: Path) -> None:
    paths = (
        output_path,
        DEFAULT_OUTCOME_ROOT,
        DEFAULT_OUTCOME_REPORT,
        DEFAULT_SCORE_REPORT,
        DEFAULT_SCORED_CASES,
    )
    present = [value.as_posix() for value in paths if value.exists()]
    if present:
        raise ValueError(f"horizon_holdout_scoring_artifact_already_exists:{present}")


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_scoring_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_scoring_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    _assert_pristine(args.output)
    report = compile_scoring_protocol(
        holdout_protocol_path=args.holdout_protocol,
        input_plan_path=args.input_plan,
        rollout_report_path=args.rollout_report,
        rollout_verification_path=args.rollout_verification,
        predictions_path=args.predictions,
        acquisition_script_path=args.acquisition_script,
        scorer_script_path=args.scorer_script,
        parser_helper_path=args.parser_helper,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(
        "logical_outcome_request_count="
        f"{report['outcome_request_lock']['logical_request_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
