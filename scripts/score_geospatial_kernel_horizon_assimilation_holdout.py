#!/usr/bin/env python3
"""Score the frozen horizon-assimilation holdout exactly once."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__:
    from scripts import acquire_geospatial_kernel_horizon_assimilation_holdout_outcomes as outcomes
    from scripts import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_scoring_protocol as scoring_protocol,
    )
else:
    import acquire_geospatial_kernel_horizon_assimilation_holdout_outcomes as outcomes
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout

    scoring_protocol = importlib.import_module(
        "freeze_geospatial_kernel_horizon_assimilation_holdout_scoring_protocol"
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCORING_PROTOCOL = scoring_protocol.DEFAULT_OUTPUT
DEFAULT_OUTCOMES = scoring_protocol.DEFAULT_OUTCOME_REPORT
DEFAULT_REPORT = scoring_protocol.DEFAULT_SCORE_REPORT
DEFAULT_CASES = scoring_protocol.DEFAULT_SCORED_CASES
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_score.v1"
MODES = (
    "nominal",
    "outlet_only_observation_update",
    "linear_distance_localized_mainstem_update",
    "quadratic_distance_localized_mainstem_update",
)
FIXED_COMPARATOR_MODE = "quadratic_distance_localized_mainstem_update"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scoring-protocol", type=Path, default=DEFAULT_SCORING_PROTOCOL
    )
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    return parser.parse_args()


def compile_score(
    *,
    scoring_protocol_path: Path = DEFAULT_SCORING_PROTOCOL,
    outcomes_path: Path = DEFAULT_OUTCOMES,
    cases_path: Path = DEFAULT_CASES,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(scoring_protocol_path)
    outcome_body, outcome_report = _load_json(outcomes_path)
    _validate_lineage(
        protocol=protocol,
        protocol_body=protocol_body,
        outcome_report=outcome_report,
    )
    frozen = protocol["frozen_artifacts"]
    holdout_protocol = json.loads(_read_verified(frozen["holdout_protocol"]))
    prediction_rows = _prediction_rows(_read_verified(frozen["predictions"]))
    observations = {
        system_id: _outcome_values(
            _read_verified(outcome_report["systems"][system_id]["outcome_values"])
        )
        for system_id in holdout.SYSTEM_IDS
    }
    cases, groups = _score_all(
        prediction_rows=prediction_rows,
        observations=observations,
        protocol=holdout_protocol,
    )
    cases_body = _cases_csv(cases)
    execution_passed = bool(
        json.loads(_read_verified(frozen["rollout_verification"]))[
            "execution_gates"
        ]["all_execution_gates_passed"]
    )
    for group in groups.values():
        group["gates"]["execution_gates_passed"] = execution_passed
        group["gates"]["all_group_gates_passed"] = (
            group["gates"]["minimum_scored_issues_passed"]
            and group["gates"]["policy_strictly_beats_fixed_quadratic_rmse"]
            and group["gates"]["policy_strictly_beats_persistence_rmse"]
            and execution_passed
        )
    support_gate = all(
        group["gates"]["all_group_gates_passed"] for group in groups.values()
    )
    passed_count = sum(
        group["gates"]["all_group_gates_passed"] for group in groups.values()
    )
    return cases_body, {
        "schema": SCHEMA,
        "status": "holdout_scored_exactly_once_no_post_score_tuning",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_artifacts": {
            "scoring_protocol": _artifact(scoring_protocol_path, protocol_body),
            "outcomes_report": _artifact(outcomes_path, outcome_body),
            "predictions": dict(frozen["predictions"]),
            "rollout_verification": dict(frozen["rollout_verification"]),
        },
        "scored_cases": _artifact(cases_path, cases_body),
        "groups": groups,
        "aggregate_gate": {
            "system_horizon_group_count": len(groups),
            "passed_group_count": passed_count,
            "failed_group_count": len(groups) - passed_count,
            "all_execution_gates_passed": execution_passed,
            "candidate_support_gate_passed": support_gate,
            "cross_system_or_cross_horizon_compensation_used": False,
            "ties_count_as_pass": False,
        },
        "score_execution_audit": {
            "score_execution_count": 1,
            "outcome_values_imputed": False,
            "common_complete_case_mask_applied_per_system_horizon": True,
            "policy_or_comparator_changed_after_outcome_access": False,
            "post_score_tuning_performed": False,
            "rescore_permitted": False,
        },
        "claim_boundary": {
            "holdout_outcomes_acquired": True,
            "holdout_scored": True,
            "candidate_support_gate_evaluated": True,
            "candidate_support_gate_passed": support_gate,
            "historical_holdout_not_real_time_prospective": True,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _score_all(
    *,
    prediction_rows: Mapping[tuple[str, int, int], Mapping[str, Mapping[str, Any]]],
    observations: Mapping[str, Mapping[datetime, float | None]],
    protocol: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    policy_modes = protocol["candidate_lock"]["policy"][
        "selected_mode_by_horizon_hours"
    ]
    minimum = int(
        protocol["scoring_lock"]["minimum_scored_issues_per_system_and_horizon"]
    )
    cases: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for system_id in holdout.SYSTEM_IDS:
        for horizon in protocol["window"]["horizons_hours"]:
            selected_mode = str(policy_modes[str(horizon)])
            included: list[dict[str, Any]] = []
            exclusion_counts = {
                "target_hour_incomplete": 0,
                "persistence_issue_observation_missing": 0,
                "nonfinite_prediction": 0,
            }
            for issue_index in protocol["window"]["issue_indices"]:
                mode_rows = prediction_rows[(system_id, int(horizon), issue_index)]
                selected_rows = [
                    row for row in mode_rows.values() if row["selected_by_policy"]
                ]
                if (
                    len(selected_rows) != 1
                    or selected_rows[0]["mode"] != selected_mode
                ):
                    raise ValueError("horizon_holdout_score_policy_selection_invalid")
                candidate = float(selected_rows[0]["predicted_outlet_m3s"])
                fixed = float(
                    mode_rows[FIXED_COMPARATOR_MODE]["predicted_outlet_m3s"]
                )
                persistence = selected_rows[0]["issue_observed_outlet_m3s"]
                target_time = selected_rows[0]["target_time"]
                observed = observations[system_id][target_time]
                exclusion = ""
                if observed is None:
                    exclusion = "target_hour_incomplete"
                elif persistence is None:
                    exclusion = "persistence_issue_observation_missing"
                elif not all(
                    math.isfinite(value)
                    for value in (candidate, fixed, float(persistence))
                ):
                    exclusion = "nonfinite_prediction"
                if exclusion:
                    exclusion_counts[exclusion] += 1
                case = {
                    "system_id": system_id,
                    "horizon_hours": int(horizon),
                    "issue_index": int(issue_index),
                    "issue_time_utc": _iso(selected_rows[0]["issue_time"]),
                    "target_time_utc": _iso(target_time),
                    "observed_target_m3s": observed,
                    "policy_mode": selected_mode,
                    "policy_prediction_m3s": candidate,
                    "fixed_quadratic_prediction_m3s": fixed,
                    "persistence_prediction_m3s": persistence,
                    "included_common_complete_case": not exclusion,
                    "exclusion_reason": exclusion,
                }
                cases.append(case)
                if not exclusion:
                    included.append(case)
            group_id = f"{system_id}:{horizon}h"
            policy_metrics = _metrics(
                [float(row["observed_target_m3s"]) for row in included],
                [float(row["policy_prediction_m3s"]) for row in included],
            )
            fixed_metrics = _metrics(
                [float(row["observed_target_m3s"]) for row in included],
                [
                    float(row["fixed_quadratic_prediction_m3s"])
                    for row in included
                ],
            )
            persistence_metrics = _metrics(
                [float(row["observed_target_m3s"]) for row in included],
                [float(row["persistence_prediction_m3s"]) for row in included],
            )
            groups[group_id] = {
                "system_id": system_id,
                "horizon_hours": int(horizon),
                "policy_mode": selected_mode,
                "issue_count": len(protocol["window"]["issue_indices"]),
                "scored_issue_count": len(included),
                "excluded_issue_count": sum(exclusion_counts.values()),
                "exclusion_counts": exclusion_counts,
                "common_complete_case_mask": True,
                "metrics": {
                    "frozen_horizon_policy": policy_metrics,
                    "fixed_quadratic_distance_localized_mainstem_update": (
                        fixed_metrics
                    ),
                    "causal_issue_observation_persistence": persistence_metrics,
                },
                "rmse_deltas_m3s": {
                    "policy_minus_fixed_quadratic": (
                        policy_metrics["rmse_m3s"] - fixed_metrics["rmse_m3s"]
                    ),
                    "policy_minus_persistence": (
                        policy_metrics["rmse_m3s"]
                        - persistence_metrics["rmse_m3s"]
                    ),
                },
                "gates": {
                    "minimum_scored_issues_passed": len(included) >= minimum,
                    "policy_strictly_beats_fixed_quadratic_rmse": (
                        policy_metrics["rmse_m3s"] < fixed_metrics["rmse_m3s"]
                    ),
                    "policy_strictly_beats_persistence_rmse": (
                        policy_metrics["rmse_m3s"]
                        < persistence_metrics["rmse_m3s"]
                    ),
                },
            }
    return cases, groups


def _metrics(observed: Sequence[float], predicted: Sequence[float]) -> dict[str, float]:
    if not observed or len(observed) != len(predicted):
        raise ValueError("horizon_holdout_score_no_complete_cases")
    errors = [
        prediction - target
        for target, prediction in zip(observed, predicted, strict=True)
    ]
    return {
        "rmse_m3s": math.sqrt(math.fsum(value * value for value in errors) / len(errors)),
        "mae_m3s": math.fsum(abs(value) for value in errors) / len(errors),
        "bias_m3s": math.fsum(errors) / len(errors),
    }


def _prediction_rows(
    body: bytes,
) -> dict[tuple[str, int, int], dict[str, dict[str, Any]]]:
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
    if reader.fieldnames != expected:
        raise ValueError("horizon_holdout_score_prediction_columns_invalid")
    result: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}
    for raw in reader:
        system_id = raw["system_id"]
        issue_index = int(raw["issue_index"])
        horizon = int(raw["horizon_hours"])
        mode = raw["mode"]
        if (
            system_id not in holdout.SYSTEM_IDS
            or issue_index not in holdout.ISSUE_INDICES
            or horizon not in (1, 3, 6, 12)
            or mode not in MODES
            or raw["selected_by_policy"] not in {"True", "False"}
        ):
            raise ValueError("horizon_holdout_score_prediction_identity_invalid")
        issue_time = _parse_time(raw["issue_time_utc"])
        target_time = _parse_time(raw["target_time_utc"])
        prediction = float(raw["predicted_outlet_m3s"])
        observation = (
            None
            if raw["issue_observed_outlet_m3s"] == ""
            else float(raw["issue_observed_outlet_m3s"])
        )
        if (
            issue_time != holdout.START + timedelta(hours=issue_index)
            or target_time != issue_time + timedelta(hours=horizon)
            or not math.isfinite(prediction)
            or (observation is not None and not math.isfinite(observation))
        ):
            raise ValueError("horizon_holdout_score_prediction_value_invalid")
        key = (system_id, horizon, issue_index)
        modes = result.setdefault(key, {})
        if mode in modes:
            raise ValueError("horizon_holdout_score_duplicate_prediction")
        modes[mode] = {
            "mode": mode,
            "issue_time": issue_time,
            "target_time": target_time,
            "predicted_outlet_m3s": prediction,
            "selected_by_policy": raw["selected_by_policy"] == "True",
            "issue_observed_outlet_m3s": observation,
            "observation_fallback_reason": raw["observation_fallback_reason"],
        }
    expected_group_count = (
        len(holdout.SYSTEM_IDS) * len((1, 3, 6, 12)) * len(holdout.ISSUE_INDICES)
    )
    if len(result) != expected_group_count or any(
        tuple(value) != MODES for value in result.values()
    ):
        raise ValueError("horizon_holdout_score_prediction_axis_invalid")
    for mode_rows in result.values():
        observations = {
            value["issue_observed_outlet_m3s"] for value in mode_rows.values()
        }
        fallback = {
            value["observation_fallback_reason"] for value in mode_rows.values()
        }
        if len(observations) != 1 or len(fallback) != 1:
            raise ValueError("horizon_holdout_score_issue_observation_mismatch")
    return result


def _outcome_values(body: bytes) -> dict[datetime, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
        "evaluation_role",
    ]
    if reader.fieldnames != expected:
        raise ValueError("horizon_holdout_score_outcome_columns_invalid")
    values: dict[datetime, float | None] = {}
    for row in reader:
        support_end = _parse_time(row["support_end_utc"])
        value = (
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
        )
        if (
            support_end in values
            or row["source_role"] != "independent_observation"
            or row["evaluation_role"] != "target"
            or (value is not None and not math.isfinite(value))
        ):
            raise ValueError("horizon_holdout_score_outcome_value_invalid")
        values[support_end] = value
    expected_axis = {
        holdout.START + timedelta(hours=index + 1)
        for index in range(holdout.HOUR_COUNT)
    }
    if set(values) != expected_axis:
        raise ValueError("horizon_holdout_score_outcome_axis_invalid")
    return values


def _cases_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    fieldnames = [
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
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
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
) -> None:
    if (
        protocol.get("schema") != scoring_protocol.SCHEMA
        or protocol.get("status") != "frozen_before_full_outcome_access"
        or outcome_report.get("schema") != outcomes.SCHEMA
        or outcome_report.get("status")
        != "two_full_outcome_series_acquired_after_joint_prediction_seal"
        or outcome_report.get("scoring_protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or outcome_report.get("request_execution", {}).get(
            "logical_request_count"
        )
        != len(holdout.SYSTEM_IDS)
        or outcome_report.get("request_execution", {}).get("remote_attempt_count")
        != len(holdout.SYSTEM_IDS)
        or outcome_report.get("claim_boundary", {}).get("holdout_scored")
        is not False
    ):
        raise ValueError("horizon_holdout_score_lineage_invalid")
    artifacts = protocol.get("frozen_artifacts") or {}
    for descriptor in artifacts.values():
        _read_verified(descriptor)
    current = Path(__file__).read_bytes()
    if artifacts.get("scorer_script", {}).get("sha256") != hashlib.sha256(
        current
    ).hexdigest():
        raise ValueError("horizon_holdout_score_scorer_hash_invalid")
    for system_id in holdout.SYSTEM_IDS:
        _read_verified(outcome_report["systems"][system_id]["raw_outcome"])
        _read_verified(outcome_report["systems"][system_id]["outcome_values"])


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_score_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_score_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_score_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_score_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("horizon_holdout_score_time_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("horizon_holdout_score_time_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.report.exists() or args.cases.exists():
        raise ValueError("horizon_holdout_score_already_exists")
    cases_body, report = compile_score(
        scoring_protocol_path=args.scoring_protocol,
        outcomes_path=args.outcomes,
        cases_path=args.cases,
    )
    args.cases.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.cases.write_bytes(cases_body)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    print(
        "candidate_support_gate_passed="
        f"{report['aggregate_gate']['candidate_support_gate_passed']}"
    )
    print(f"passed_group_count={report['aggregate_gate']['passed_group_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
