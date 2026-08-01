#!/usr/bin/env python3
"""Independently reconstruct and verify the single holdout score."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCORING_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_scoring_protocol.json"
)
DEFAULT_OUTCOMES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_outcomes_report.json"
)
DEFAULT_SCORE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score_verification.json"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_score_verification.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
MODES = (
    "nominal",
    "outlet_only_observation_update",
    "linear_distance_localized_mainstem_update",
    "quadratic_distance_localized_mainstem_update",
)
FIXED_MODE = "quadratic_distance_localized_mainstem_update"
CFS_TO_M3S = 0.028316846592


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scoring-protocol", type=Path, default=DEFAULT_SCORING_PROTOCOL
    )
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def verify_score(
    *,
    scoring_protocol_path: Path = DEFAULT_SCORING_PROTOCOL,
    outcomes_path: Path = DEFAULT_OUTCOMES,
    score_path: Path = DEFAULT_SCORE,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(scoring_protocol_path)
    outcome_body, outcome_report = _load_json(outcomes_path)
    score_body, score_report = _load_json(score_path)
    _validate_lineage(
        protocol=protocol,
        protocol_body=protocol_body,
        outcome_report=outcome_report,
        outcome_body=outcome_body,
        score_report=score_report,
    )
    frozen = protocol["frozen_artifacts"]
    holdout_protocol = json.loads(_read_verified(frozen["holdout_protocol"]))
    start = _parse_time(holdout_protocol["window"]["start_inclusive_utc"])
    end = _parse_time(holdout_protocol["window"]["end_exclusive_utc"])
    hour_count = int(holdout_protocol["window"]["hour_count"])
    support_ends = tuple(start + timedelta(hours=index + 1) for index in range(hour_count))
    if support_ends[-1] != end:
        raise ValueError("horizon_holdout_verification_window_axis_invalid")

    observations: dict[str, dict[datetime, float | None]] = {}
    outcome_checks: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        system = outcome_report["systems"][system_id]
        raw = json.loads(_read_verified(system["raw_outcome"]))
        values, cadence, counts = _parse_native_hourly(
            raw,
            site_id=str(system["site_id"]),
            support_ends=support_ends,
            request_start=start,
        )
        reconstructed = _outcome_csv(support_ends, values)
        recorded = _read_verified(system["outcome_values"])
        if reconstructed != recorded:
            raise ValueError("horizon_holdout_verification_outcome_csv_mismatch")
        observations[system_id] = values
        outcome_checks[system_id] = {
            "native_sample_cadence_seconds": cadence,
            "expected_native_samples_per_complete_hour": 3600 // cadence,
            "complete_target_hour_count": sum(
                value is not None for value in values.values()
            ),
            "missing_target_hour_count": sum(
                value is None for value in values.values()
            ),
            "sample_counts": sorted(set(counts.values())),
            "values_csv_reconstructed_exactly": True,
        }

    predictions = _prediction_rows(_read_verified(frozen["predictions"]))
    cases, groups = _reconstruct_scores(
        predictions=predictions,
        observations=observations,
        protocol=holdout_protocol,
    )
    reconstructed_cases = _cases_csv(cases)
    recorded_cases = _read_verified(score_report["scored_cases"])
    if reconstructed_cases != recorded_cases:
        raise ValueError("horizon_holdout_verification_scored_cases_mismatch")
    _validate_groups(groups, score_report)
    structural_ties = []
    for system_id in SYSTEM_IDS:
        group_id = f"{system_id}:3h"
        group = groups[group_id]
        if (
            group["metrics"]["policy"]["rmse_m3s"]
            != group["metrics"]["fixed"]["rmse_m3s"]
            or group["gates"]["policy_beats_fixed"]
        ):
            raise ValueError("horizon_holdout_verification_structural_tie_invalid")
        structural_ties.append(group_id)

    return {
        "schema": SCHEMA,
        "status": "pass_single_score_independent_reconstruction",
        "generated_at": datetime.now(UTC).isoformat(),
        "verified_artifacts": {
            "scoring_protocol": _artifact(scoring_protocol_path, protocol_body),
            "outcomes_report": _artifact(outcomes_path, outcome_body),
            "score_report": _artifact(score_path, score_body),
            "predictions": dict(frozen["predictions"]),
            "scored_cases": dict(score_report["scored_cases"]),
            "outcome_acquisition_script": dict(
                frozen["outcome_acquisition_script"]
            ),
            "scorer_script": dict(frozen["scorer_script"]),
        },
        "outcome_reconstruction": outcome_checks,
        "score_reconstruction": {
            "case_count": len(cases),
            "scored_cases_reconstructed_exactly": True,
            "system_horizon_group_count": len(groups),
            "group_metrics_and_gates_reconstructed_exactly": True,
            "minimum_sample_gate_pass_count": sum(
                value["gates"]["minimum"] for value in groups.values()
            ),
            "passed_group_count": score_report["aggregate_gate"][
                "passed_group_count"
            ],
            "failed_group_count": score_report["aggregate_gate"][
                "failed_group_count"
            ],
            "structural_tie_groups": structural_ties,
            "formal_candidate_support_gate_passed": score_report[
                "aggregate_gate"
            ]["candidate_support_gate_passed"],
        },
        "execution_audit": {
            "frozen_artifact_hashes_still_match": True,
            "logical_outcome_request_count": outcome_report["request_execution"][
                "logical_request_count"
            ],
            "remote_outcome_attempt_count": outcome_report["request_execution"][
                "remote_attempt_count"
            ],
            "formal_score_execution_count": score_report[
                "score_execution_audit"
            ]["score_execution_count"],
            "verifier_called_formal_scorer": False,
            "outcomes_imputed": False,
            "post_score_tuning_performed": False,
        },
        "claim_boundary": dict(score_report["claim_boundary"]),
    }


def _parse_native_hourly(
    payload: Mapping[str, Any],
    *,
    site_id: str,
    support_ends: tuple[datetime, ...],
    request_start: datetime,
) -> tuple[dict[datetime, float | None], int, dict[datetime, int]]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    if len(series) != 1:
        raise ValueError("horizon_holdout_verification_single_series_required")
    row = series[0]
    sites = {
        value.get("value")
        for value in (row.get("sourceInfo") or {}).get("siteCode") or []
    }
    variable = row.get("variable") or {}
    codes = {
        value.get("value") for value in variable.get("variableCode") or []
    }
    if (
        site_id not in sites
        or "00060" not in codes
        or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
    ):
        raise ValueError("horizon_holdout_verification_series_identity_invalid")
    samples = []
    seen = set()
    no_data = float(variable.get("noDataValue", -999999.0))
    for group in row.get("values") or []:
        for sample in group.get("value") or []:
            timestamp = _parse_time(str(sample["dateTime"]))
            if not request_start < timestamp <= support_ends[-1]:
                continue
            if timestamp in seen:
                raise ValueError("horizon_holdout_verification_duplicate_sample")
            seen.add(timestamp)
            value = float(sample["value"])
            if value == no_data:
                continue
            samples.append(
                (timestamp, value * CFS_TO_M3S, tuple(sample.get("qualifiers") or ()))
            )
    timestamps = [value[0] for value in samples]
    deltas = [
        int((right - left).total_seconds())
        for left, right in zip(timestamps, timestamps[1:], strict=False)
        if right > left
    ]
    if not deltas:
        raise ValueError("horizon_holdout_verification_insufficient_samples")
    cadence = math.gcd(*deltas)
    if cadence < 300 or cadence > 3600 or 3600 % cadence:
        raise ValueError("horizon_holdout_verification_cadence_invalid")
    grouped = {value: [] for value in support_ends}
    for timestamp, value, qualifiers in samples:
        seconds = timestamp.minute * 60 + timestamp.second
        if seconds % cadence or timestamp.microsecond or qualifiers != ("A",):
            raise ValueError("horizon_holdout_verification_sample_invalid")
        support_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if seconds:
            support_end += timedelta(hours=1)
        grouped[support_end].append(value)
    expected = 3600 // cadence
    if any(len(value) > expected for value in grouped.values()):
        raise ValueError("horizon_holdout_verification_excess_samples")
    values = {
        key: sum(value) / len(value) if len(value) == expected else None
        for key, value in grouped.items()
    }
    return values, cadence, {key: len(value) for key, value in grouped.items()}


def _prediction_rows(body: bytes) -> dict[tuple[str, int, int, str], dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    result = {}
    for row in reader:
        key = (
            row["system_id"],
            int(row["horizon_hours"]),
            int(row["issue_index"]),
            row["mode"],
        )
        if key in result or key[0] not in SYSTEM_IDS or key[3] not in MODES:
            raise ValueError("horizon_holdout_verification_prediction_invalid")
        result[key] = {
            "issue_time": _parse_time(row["issue_time_utc"]),
            "target_time": _parse_time(row["target_time_utc"]),
            "prediction": float(row["predicted_outlet_m3s"]),
            "selected": row["selected_by_policy"] == "True",
            "persistence": (
                None
                if row["issue_observed_outlet_m3s"] == ""
                else float(row["issue_observed_outlet_m3s"])
            ),
        }
    return result


def _reconstruct_scores(
    *,
    predictions: Mapping[tuple[str, int, int, str], Mapping[str, Any]],
    observations: Mapping[str, Mapping[datetime, float | None]],
    protocol: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    policy = protocol["candidate_lock"]["policy"][
        "selected_mode_by_horizon_hours"
    ]
    minimum = protocol["scoring_lock"][
        "minimum_scored_issues_per_system_and_horizon"
    ]
    cases = []
    groups = {}
    for system_id in SYSTEM_IDS:
        for horizon in protocol["window"]["horizons_hours"]:
            selected_mode = policy[str(horizon)]
            included = []
            exclusions = {
                "target_hour_incomplete": 0,
                "persistence_issue_observation_missing": 0,
                "nonfinite_prediction": 0,
            }
            for issue_index in protocol["window"]["issue_indices"]:
                selected = predictions[
                    (system_id, horizon, issue_index, selected_mode)
                ]
                fixed = predictions[(system_id, horizon, issue_index, FIXED_MODE)]
                if not selected["selected"]:
                    raise ValueError("horizon_holdout_verification_selection_invalid")
                observed = observations[system_id][selected["target_time"]]
                exclusion = ""
                if observed is None:
                    exclusion = "target_hour_incomplete"
                elif selected["persistence"] is None:
                    exclusion = "persistence_issue_observation_missing"
                elif not all(
                    math.isfinite(float(value))
                    for value in (
                        selected["prediction"],
                        fixed["prediction"],
                        selected["persistence"],
                    )
                ):
                    exclusion = "nonfinite_prediction"
                if exclusion:
                    exclusions[exclusion] += 1
                case = {
                    "system_id": system_id,
                    "horizon_hours": horizon,
                    "issue_index": issue_index,
                    "issue_time_utc": _iso(selected["issue_time"]),
                    "target_time_utc": _iso(selected["target_time"]),
                    "observed_target_m3s": observed,
                    "policy_mode": selected_mode,
                    "policy_prediction_m3s": selected["prediction"],
                    "fixed_quadratic_prediction_m3s": fixed["prediction"],
                    "persistence_prediction_m3s": selected["persistence"],
                    "included_common_complete_case": not exclusion,
                    "exclusion_reason": exclusion,
                }
                cases.append(case)
                if not exclusion:
                    included.append(case)
            policy_metrics = _metrics(included, "policy_prediction_m3s")
            fixed_metrics = _metrics(
                included, "fixed_quadratic_prediction_m3s"
            )
            persistence_metrics = _metrics(
                included, "persistence_prediction_m3s"
            )
            groups[f"{system_id}:{horizon}h"] = {
                "scored": len(included),
                "exclusions": exclusions,
                "metrics": {
                    "policy": policy_metrics,
                    "fixed": fixed_metrics,
                    "persistence": persistence_metrics,
                },
                "deltas": {
                    "fixed": policy_metrics["rmse_m3s"]
                    - fixed_metrics["rmse_m3s"],
                    "persistence": policy_metrics["rmse_m3s"]
                    - persistence_metrics["rmse_m3s"],
                },
                "gates": {
                    "minimum": len(included) >= minimum,
                    "policy_beats_fixed": policy_metrics["rmse_m3s"]
                    < fixed_metrics["rmse_m3s"],
                    "policy_beats_persistence": policy_metrics["rmse_m3s"]
                    < persistence_metrics["rmse_m3s"],
                },
            }
    return cases, groups


def _validate_groups(
    groups: Mapping[str, Mapping[str, Any]], score_report: Mapping[str, Any]
) -> None:
    execution = score_report["aggregate_gate"]["all_execution_gates_passed"]
    passed = 0
    for group_id, computed in groups.items():
        recorded = score_report["groups"][group_id]
        metrics = recorded["metrics"]
        if (
            computed["scored"] != recorded["scored_issue_count"]
            or computed["exclusions"] != recorded["exclusion_counts"]
            or computed["metrics"]["policy"] != metrics["frozen_horizon_policy"]
            or computed["metrics"]["fixed"]
            != metrics["fixed_quadratic_distance_localized_mainstem_update"]
            or computed["metrics"]["persistence"]
            != metrics["causal_issue_observation_persistence"]
            or computed["deltas"]["fixed"]
            != recorded["rmse_deltas_m3s"]["policy_minus_fixed_quadratic"]
            or computed["deltas"]["persistence"]
            != recorded["rmse_deltas_m3s"]["policy_minus_persistence"]
        ):
            raise ValueError("horizon_holdout_verification_group_metrics_mismatch")
        gates = recorded["gates"]
        all_group = (
            computed["gates"]["minimum"]
            and computed["gates"]["policy_beats_fixed"]
            and computed["gates"]["policy_beats_persistence"]
            and execution
        )
        if (
            computed["gates"]["minimum"]
            != gates["minimum_scored_issues_passed"]
            or computed["gates"]["policy_beats_fixed"]
            != gates["policy_strictly_beats_fixed_quadratic_rmse"]
            or computed["gates"]["policy_beats_persistence"]
            != gates["policy_strictly_beats_persistence_rmse"]
            or all_group != gates["all_group_gates_passed"]
        ):
            raise ValueError("horizon_holdout_verification_group_gate_mismatch")
        passed += int(all_group)
    aggregate = score_report["aggregate_gate"]
    if (
        passed != aggregate["passed_group_count"]
        or len(groups) - passed != aggregate["failed_group_count"]
        or aggregate["candidate_support_gate_passed"] != (passed == len(groups))
    ):
        raise ValueError("horizon_holdout_verification_aggregate_gate_mismatch")


def _metrics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    errors = [float(row[key]) - float(row["observed_target_m3s"]) for row in rows]
    return {
        "rmse_m3s": math.sqrt(math.fsum(value * value for value in errors) / len(errors)),
        "mae_m3s": math.fsum(abs(value) for value in errors) / len(errors),
        "bias_m3s": math.fsum(errors) / len(errors),
    }


def _outcome_csv(
    support_ends: Sequence[datetime], outcomes: Mapping[datetime, float | None]
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "support_end_utc",
            "observed_discharge_m3s",
            "source_role",
            "evaluation_role",
        ]
    )
    for support_end in support_ends:
        value = outcomes[support_end]
        writer.writerow(
            [
                _iso(support_end),
                "" if value is None else format(value, ".17g"),
                "independent_observation",
                "target",
            ]
        )
    return stream.getvalue().encode("utf-8")


def _cases_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    fields = [
        "system_id",
        "horizon_hours",
        "issue_index",
        "issue_time_utc",
        "target_time_utc",
        "observed_target_m3s",
        "policy_mode",
        "policy_prediction_m3s",
        "fixed_quadratic_prediction_m3s",
        "persistence_prediction_m3s",
        "included_common_complete_case",
        "exclusion_reason",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        rendered = dict(row)
        for key in (
            "observed_target_m3s",
            "policy_prediction_m3s",
            "fixed_quadratic_prediction_m3s",
            "persistence_prediction_m3s",
        ):
            rendered[key] = (
                "" if row[key] is None else format(float(row[key]), ".17g")
            )
        writer.writerow(rendered)
    return stream.getvalue().encode("utf-8")


def _validate_lineage(
    *,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    outcome_report: Mapping[str, Any],
    outcome_body: bytes,
    score_report: Mapping[str, Any],
) -> None:
    if (
        protocol.get("schema")
        != "gwm.geotransport.horizon_assimilation_holdout_scoring_protocol.v1"
        or protocol.get("status") != "frozen_before_full_outcome_access"
        or outcome_report.get("schema")
        != "gwm.geotransport.horizon_assimilation_holdout_outcomes.v1"
        or score_report.get("schema")
        != "gwm.geotransport.horizon_assimilation_holdout_score.v1"
        or outcome_report.get("scoring_protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or score_report.get("source_artifacts", {})
        .get("outcomes_report", {})
        .get("sha256")
        != hashlib.sha256(outcome_body).hexdigest()
        or score_report.get("score_execution_audit", {}).get(
            "score_execution_count"
        )
        != 1
        or score_report.get("score_execution_audit", {}).get(
            "post_score_tuning_performed"
        )
        is not False
    ):
        raise ValueError("horizon_holdout_verification_lineage_invalid")
    for descriptor in protocol["frozen_artifacts"].values():
        _read_verified(descriptor)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_verification_artifact_outside_repo") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_verification_artifact_hash_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_verification_json_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_verification_artifact_outside_repo") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("horizon_holdout_verification_time_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("horizon_holdout_score_verification_already_exists")
    report = verify_score(
        scoring_protocol_path=args.scoring_protocol,
        outcomes_path=args.outcomes,
        score_path=args.score,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(
        "formal_candidate_support_gate_passed="
        f"{report['score_reconstruction']['formal_candidate_support_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
