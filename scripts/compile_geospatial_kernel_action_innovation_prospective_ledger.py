#!/usr/bin/env python3
"""Compile deduplicated multi-issue evidence for one frozen shadow candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
    load_frozen_action_innovation_uncertainty_shadow_runtime,
)

if __package__:
    from scripts.audit_geospatial_kernel_action_innovation_prospective_evidence import (
        load_and_recompute_prospective_evidence_audit,
    )
    from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        MAXIMUM_ISSUE_LATENCY,
        _validate_receipt_contract,
    )
else:
    from audit_geospatial_kernel_action_innovation_prospective_evidence import (
        load_and_recompute_prospective_evidence_audit,
    )
    from verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        MAXIMUM_ISSUE_LATENCY,
        _validate_receipt_contract,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "gwm.geospatial_kernel.action_innovation_prospective_evidence_ledger.v1"
VERIFICATION_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_uncertainty_prospective_verification.v1"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forecast-receipt",
        type=Path,
        action="append",
        required=True,
        help="One issued forecast receipt; repeat for the complete submitted inventory.",
    )
    parser.add_argument(
        "--evidence-audit",
        type=Path,
        action="append",
        required=True,
        help="One recomputable prospective issue audit; repeat for multiple issues.",
    )
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def compile_prospective_evidence_ledger(
    evidence_audit_paths: Sequence[Path],
    *,
    forecast_receipt_paths: Sequence[Path],
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    paths = tuple(evidence_audit_paths)
    receipt_paths = tuple(forecast_receipt_paths)
    if not paths:
        raise ValueError("action_innovation_prospective_ledger_evidence_audit_required")
    if not receipt_paths:
        raise ValueError("action_innovation_prospective_ledger_forecast_receipt_required")
    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime(
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        enabled=False,
    )
    freeze = _json_mapping(uncertainty_freeze_path.read_bytes())
    frozen_at = _time(freeze.get("frozen_at"), "uncertainty_frozen_at")
    issued_records = [
        _load_issued_forecast(path, runtime=runtime, frozen_at=frozen_at)
        for path in receipt_paths
    ]
    issued_records.sort(key=lambda value: value["issue_time"])
    records: list[dict[str, Any]] = []
    for path in paths:
        audited = load_and_recompute_prospective_evidence_audit(
            path,
            repository_root=repository_root,
        )
        body = audited["verification_body"]
        payload = audited["verification"]
        _validate_verification(payload)
        records.append(
            {
                "path": audited["verification_path"],
                "body": body,
                "payload": payload,
                "audit_path": audited["audit_path"],
                "audit_body": audited["audit_body"],
                "issue_time": _time(payload["request_identity"]["issue_time"], "issue_time"),
            }
        )
    records.sort(key=lambda value: value["issue_time"])

    identities = [record["payload"]["frozen_candidate_identity"] for record in records]
    reference_identity = identities[0]
    issued_identities = [record["candidate_identity"] for record in issued_records]
    if any(identity != reference_identity for identity in identities[1:] + issued_identities):
        raise ValueError("action_innovation_prospective_ledger_candidate_identity_mismatch")
    networks = [record["payload"]["request_identity"]["network_id"] for record in records]
    issued_networks = [record["network_id"] for record in issued_records]
    if len(set(networks + issued_networks)) != 1:
        raise ValueError("action_innovation_prospective_ledger_network_identity_mismatch")
    request_ids = [record["payload"]["request_identity"]["request_id"] for record in records]
    issue_keys = [
        (network, record["payload"]["request_identity"]["issue_time"])
        for network, record in zip(networks, records, strict=True)
    ]
    forecast_hashes = [
        record["payload"]["source_artifacts"]["forecast_receipt"]["sha256"] for record in records
    ]
    observation_hashes = [
        record["payload"]["source_artifacts"]["observation_batch"]["sha256"]
        for record in records
    ]
    if (
        len(set(request_ids)) != len(request_ids)
        or len(set(issue_keys)) != len(issue_keys)
        or len(set(forecast_hashes)) != len(forecast_hashes)
        or len(set(observation_hashes)) != len(observation_hashes)
    ):
        raise ValueError("action_innovation_prospective_ledger_duplicate_issue")
    issued_request_ids = [record["request_id"] for record in issued_records]
    issued_issue_keys = [
        (record["network_id"], record["issue_time_text"]) for record in issued_records
    ]
    issued_forecast_hashes = [record["forecast_sha256"] for record in issued_records]
    if (
        len(set(issued_request_ids)) != len(issued_request_ids)
        or len(set(issued_issue_keys)) != len(issued_issue_keys)
        or len(set(issued_forecast_hashes)) != len(issued_forecast_hashes)
    ):
        raise ValueError("action_innovation_prospective_ledger_duplicate_issued_forecast")
    issued_by_hash = {record["forecast_sha256"]: record for record in issued_records}
    for record, forecast_hash in zip(records, forecast_hashes, strict=True):
        issued = issued_by_hash.get(forecast_hash)
        request = record["payload"]["request_identity"]
        if (
            issued is None
            or issued["request_id"] != request["request_id"]
            or issued["network_id"] != request["network_id"]
            or issued["issue_time_text"] != request["issue_time"]
        ):
            raise ValueError(
                "action_innovation_prospective_ledger_audit_not_in_issuance_inventory"
            )

    rows = [
        {**row, "request_id": record["payload"]["request_identity"]["request_id"]}
        for record in records
        for row in record["payload"]["score"]["rows"]
    ]
    per_horizon = {
        str(horizon): _metrics([row for row in rows if row["horizon_hours"] == horizon])
        for horizon in ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
    }
    issue_count = len(records)
    compiled_at = _now()
    scored_hashes = set(forecast_hashes)
    issuance_inventory = []
    unscored_matured_count = 0
    pending_outcome_count = 0
    for record in issued_records:
        if record["forecast_sha256"] in scored_hashes:
            reconciliation_status = "scored_and_source_recomputed"
        elif max(record["target_valid_times"]) <= compiled_at:
            reconciliation_status = "unscored_matured"
            unscored_matured_count += 1
        else:
            reconciliation_status = "pending_outcomes"
            pending_outcome_count += 1
        issuance_inventory.append(
            {
                **_artifact(record["path"], record["body"]),
                "request_id": record["request_id"],
                "network_id": record["network_id"],
                "issue_time": record["issue_time_text"],
                "last_target_valid_time": max(record["target_valid_times"]).isoformat(),
                "reconciliation_status": reconciliation_status,
            }
        )
    return {
        "schema": SCHEMA,
        "status": "multi_issue_shadow_evidence_compiled_not_admitted",
        "generated_at": compiled_at.isoformat(),
        "frozen_candidate_identity": reference_identity,
        "network_identity": {
            "network_id": networks[0],
            "distinct_network_count": 1,
            "cross_network_records_accepted": False,
        },
        "verification_artifacts": [
            {
                **_artifact(record["path"], record["body"]),
                "request_id": record["payload"]["request_identity"]["request_id"],
                "network_id": record["payload"]["request_identity"]["network_id"],
                "issue_time": record["payload"]["request_identity"]["issue_time"],
                "evidence_audit": _artifact(
                    record["audit_path"],
                    record["audit_body"],
                ),
            }
            for record in records
        ],
        "issuance_inventory": issuance_inventory,
        "evidence_coverage": {
            "issue_count": issue_count,
            "issued_forecast_count": len(issued_records),
            "scored_issue_count": issue_count,
            "pending_outcome_count": pending_outcome_count,
            "unscored_matured_issue_count": unscored_matured_count,
            "forecast_horizon_count_per_issue": len(ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS),
            "scored_row_count": len(rows),
            "first_issue_time": records[0]["payload"]["request_identity"]["issue_time"],
            "last_issue_time": records[-1]["payload"]["request_identity"]["issue_time"],
            "first_issued_issue_time": issued_records[0]["issue_time_text"],
            "last_issued_issue_time": issued_records[-1]["issue_time_text"],
        },
        "aggregate": {
            "all_horizons": _metrics(rows),
            "by_horizon_hours": per_horizon,
        },
        "evidence_gates": {
            "all_reports_bind_exact_same_frozen_candidate": True,
            "all_reports_bind_exact_same_network": True,
            "duplicate_request_issue_forecast_or_observation_present": False,
            "all_source_observation_artifacts_verified": True,
            "all_verification_reports_recomputed_from_exact_sources": True,
            "all_audits_match_submitted_issuance_inventory": True,
            "all_matured_issued_forecasts_scored": unscored_matured_count == 0,
            "unscored_matured_issued_forecast_present": unscored_matured_count > 0,
            "all_reported_metrics_recomputed": True,
            "multi_issue_shadow_evidence_present": issue_count >= 2,
            "trusted_external_timestamp_evidence_present": False,
            "multi_system_evidence_present": False,
            "automatic_admission_gate_passed": False,
        },
        "claim_boundary": {
            "multi_issue_shadow_evidence_accumulated": issue_count >= 2,
            "submitted_issuance_inventory_reconciled": True,
            "selective_reporting_bias_excluded": False,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "coverage_or_radii_recalibrated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        },
    }


def _load_issued_forecast(
    path: Path,
    *,
    runtime: Any,
    frozen_at: datetime,
) -> dict[str, Any]:
    body = path.read_bytes()
    receipt = _json_mapping(body)
    _validate_receipt_contract(receipt)
    execution = receipt["execution_identity"]
    request = receipt["request_identity"]
    result = receipt["result"]
    point_shadow = result["point_shadow_forecast"]
    interval = result["interval_forecast"]
    point = interval["point_forecast"]
    issue_time = _time(point["issue_time"], "issued_forecast_issue")
    generated_at = _time(receipt["generated_at"], "issued_forecast_generated")
    targets = tuple(
        _time(value, "issued_forecast_target") for value in point["target_valid_times"]
    )
    expected_targets = tuple(
        issue_time + timedelta(hours=horizon)
        for horizon in ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
    )
    frozen_network_id = runtime.point_runtime.parameters.support.network_id
    if (
        execution["uncertainty_freeze_sha256"] != runtime.uncertainty_freeze_sha256
        or execution["uncertainty_parameter_sha256"]
        != runtime.uncertainty_parameter_sha256
        or execution["point_freeze_sha256"] != runtime.point_runtime.freeze_sha256
        or execution["point_parameter_sha256"]
        != runtime.point_runtime.parameter_sha256
        or execution["uncertainty_runtime_sha256"]
        != runtime.uncertainty_runtime_sha256
        or execution["point_runtime_sha256"] != runtime.point_runtime.runtime_sha256
    ):
        raise ValueError(
            "action_innovation_prospective_ledger_issued_forecast_identity_mismatch"
        )
    if (
        request["network_id"] != frozen_network_id
        or result["network_id"] != frozen_network_id
        or point_shadow["network_id"] != frozen_network_id
        or point_shadow["input_attestation"]["network_id"] != frozen_network_id
        or _time(
            point_shadow["input_attestation"]["issue_time"],
            "issued_attestation_issue",
        )
        != issue_time
        or point_shadow["forecast"] != point
        or point_shadow["freeze_sha256"] != execution["point_freeze_sha256"]
        or point_shadow["parameter_sha256"] != execution["point_parameter_sha256"]
        or point_shadow["runtime_sha256"] != execution["point_runtime_sha256"]
        or interval["parameters"] != runtime.uncertainty_parameters.as_dict()
        or point["parameters"] != runtime.point_runtime.parameters.as_dict()
    ):
        raise ValueError(
            "action_innovation_prospective_ledger_issued_forecast_runtime_mismatch"
        )
    if (
        targets != expected_targets
        or issue_time < frozen_at
        or generated_at < max(issue_time, frozen_at)
        or generated_at > issue_time + MAXIMUM_ISSUE_LATENCY
        or generated_at >= min(targets)
    ):
        raise ValueError(
            "action_innovation_prospective_ledger_issued_forecast_ordering_invalid"
        )
    return {
        "path": path,
        "body": body,
        "forecast_sha256": hashlib.sha256(body).hexdigest(),
        "request_id": request["request_id"],
        "network_id": frozen_network_id,
        "issue_time": issue_time,
        "issue_time_text": issue_time.isoformat(),
        "target_valid_times": targets,
        "candidate_identity": {
            "point_freeze_sha256": runtime.point_runtime.freeze_sha256,
            "point_parameter_sha256": runtime.point_runtime.parameter_sha256,
            "uncertainty_freeze_sha256": runtime.uncertainty_freeze_sha256,
            "uncertainty_parameter_sha256": runtime.uncertainty_parameter_sha256,
        },
    }


def _validate_verification(payload: Mapping[str, Any]) -> None:
    if set(payload) != {
        "schema",
        "status",
        "generated_at",
        "source_artifacts",
        "request_identity",
        "frozen_candidate_identity",
        "score",
        "ordering_audit",
        "claim_boundary",
    }:
        raise ValueError("action_innovation_prospective_ledger_report_fields_invalid")
    source = payload.get("source_artifacts") or {}
    request = payload.get("request_identity") or {}
    identity = payload.get("frozen_candidate_identity") or {}
    score = payload.get("score") or {}
    ordering = payload.get("ordering_audit") or {}
    claims = payload.get("claim_boundary") or {}
    if (
        payload.get("schema") != VERIFICATION_SCHEMA
        or payload.get("status") != "single_issue_shadow_outcomes_scored_not_admitted"
        or set(source)
        != {
            "forecast_receipt",
            "outcomes",
            "observation_batch",
            "uncertainty_freeze",
        }
        or not _descriptor(source["forecast_receipt"], path_required=False)
        or not _descriptor(source["outcomes"], path_required=False)
        or not _descriptor(source["observation_batch"], path_required=False)
        or not _descriptor(source["uncertainty_freeze"], path_required=True)
        or set(request)
        != {
            "request_id",
            "network_id",
            "issue_time",
            "forecast_generated_at",
            "outcomes_available_at",
            "outlet_observation_provenance_id",
            "source_observation_artifact_sha256",
            "source_observation_artifact_size_bytes",
        }
        or any(
            not isinstance(request.get(name), str) or not request[name].strip()
            for name in (
                "request_id",
                "network_id",
                "outlet_observation_provenance_id",
            )
        )
        or not _valid_sha256(request.get("source_observation_artifact_sha256"))
        or not isinstance(request.get("source_observation_artifact_size_bytes"), int)
        or isinstance(request.get("source_observation_artifact_size_bytes"), bool)
        or request["source_observation_artifact_size_bytes"] <= 0
        or source["observation_batch"]["sha256"]
        != request["source_observation_artifact_sha256"]
        or source["observation_batch"]["size_bytes"]
        != request["source_observation_artifact_size_bytes"]
        or set(identity)
        != {
            "point_freeze_sha256",
            "point_parameter_sha256",
            "uncertainty_freeze_sha256",
            "uncertainty_parameter_sha256",
        }
        or any(not _valid_sha256(value) for value in identity.values())
        or ordering
        != {
            "forecast_generated_after_uncertainty_freeze": True,
            "forecast_generated_within_issue_latency_limit": True,
            "forecast_generated_before_first_target": True,
            "all_observations_available_no_earlier_than_target": True,
            "outcome_document_bound_to_exact_forecast_receipt": True,
            "source_observation_artifact_verified": True,
            "outcome_values_match_source_observation_batch": True,
            "outcomes_declared_available_before_scoring": True,
            "trusted_external_timestamp_verified": False,
        }
        or claims
        != {
            "fresh_window_separation_verified": True,
            "single_issue_shadow_score_available": True,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "coverage_or_radii_recalibrated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        }
    ):
        raise ValueError("action_innovation_prospective_ledger_report_invalid")
    issue = _time(request["issue_time"], "issue_time")
    forecast_generated = _time(request["forecast_generated_at"], "forecast_generated_at")
    outcomes_available = _time(request["outcomes_available_at"], "outcomes_available_at")
    generated = _time(payload["generated_at"], "verification_generated_at")
    if not issue <= forecast_generated < outcomes_available <= generated:
        raise ValueError("action_innovation_prospective_ledger_report_ordering_invalid")
    _validate_score(score, issue)


def _validate_score(score: Mapping[str, Any], issue_time: datetime) -> None:
    if (
        not isinstance(score, Mapping)
        or set(score)
        != {
            "schema",
            "target_marginal_coverage",
            "rows",
            "aggregate",
            "single_issue_only",
            "finite_sample_coverage_guarantee_claimed",
            "conditional_coverage_guarantee_claimed",
            "admitted",
        }
        or score.get("schema") != ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA
        or score.get("single_issue_only") is not True
        or score.get("finite_sample_coverage_guarantee_claimed") is not False
        or score.get("conditional_coverage_guarantee_claimed") is not False
        or score.get("admitted") is not False
        or not isinstance(score.get("rows"), list)
        or len(score["rows"]) != 4
        or not isinstance(score.get("aggregate"), Mapping)
    ):
        raise ValueError("action_innovation_prospective_ledger_score_invalid")
    coverage = _number(score["target_marginal_coverage"], "target_coverage")
    if not 0.5 < coverage < 1.0:
        raise ValueError("action_innovation_prospective_ledger_score_invalid")
    rows = score["rows"]
    for row, horizon in zip(
        rows,
        ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
        strict=True,
    ):
        _validate_row(row, issue_time, horizon, coverage)
    calculated = _metrics(rows)
    _assert_metrics_equal(score["aggregate"], calculated)


def _validate_row(
    row: object,
    issue_time: datetime,
    horizon: int,
    coverage: float,
) -> None:
    if not isinstance(row, Mapping) or set(row) != {
        "horizon_hours",
        "target_valid_time",
        "point_discharge_m3s",
        "lower_discharge_m3s",
        "upper_discharge_m3s",
        "observed_discharge_m3s",
        "error_m3s",
        "absolute_error_m3s",
        "interval_contains_observation",
        "interval_width_m3s",
        "interval_score",
    }:
        raise ValueError("action_innovation_prospective_ledger_score_row_invalid")
    if row["horizon_hours"] != horizon or _time(
        row["target_valid_time"], "target_valid_time"
    ) != issue_time + timedelta(hours=horizon):
        raise ValueError("action_innovation_prospective_ledger_score_axis_invalid")
    point = _number(row["point_discharge_m3s"], "point")
    lower = _number(row["lower_discharge_m3s"], "lower")
    upper = _number(row["upper_discharge_m3s"], "upper")
    observed = _number(row["observed_discharge_m3s"], "observed")
    error = point - observed
    absolute_error = abs(error)
    contained = lower <= observed <= upper
    width = upper - lower
    alpha = 1.0 - coverage
    interval_score = width
    if observed < lower:
        interval_score += 2.0 / alpha * (lower - observed)
    elif observed > upper:
        interval_score += 2.0 / alpha * (observed - upper)
    if (
        lower < 0.0
        or not lower <= point <= upper
        or not _close(row["error_m3s"], error)
        or not _close(row["absolute_error_m3s"], absolute_error)
        or row["interval_contains_observation"] is not contained
        or not _close(row["interval_width_m3s"], width)
        or not _close(row["interval_score"], interval_score)
    ):
        raise ValueError("action_innovation_prospective_ledger_score_row_invalid")


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if not rows:
        raise ValueError("action_innovation_prospective_ledger_metric_rows_required")
    errors = [float(row["error_m3s"]) for row in rows]
    absolute = [float(row["absolute_error_m3s"]) for row in rows]
    contained = [bool(row["interval_contains_observation"]) for row in rows]
    widths = [float(row["interval_width_m3s"]) for row in rows]
    interval_scores = [float(row["interval_score"]) for row in rows]
    count = len(rows)
    return {
        "sample_count": count,
        "mae_m3s": sum(absolute) / count,
        "rmse_m3s": math.sqrt(sum(value * value for value in errors) / count),
        "bias_m3s": sum(errors) / count,
        "empirical_marginal_coverage": sum(contained) / count,
        "mean_interval_width_m3s": sum(widths) / count,
        "mean_interval_score": sum(interval_scores) / count,
    }


def _assert_metrics_equal(reported: Mapping[str, Any], calculated: Mapping[str, object]) -> None:
    if set(reported) != set(calculated):
        raise ValueError("action_innovation_prospective_ledger_aggregate_invalid")
    for name, expected in calculated.items():
        value = reported[name]
        if name == "sample_count":
            if value != expected:
                raise ValueError("action_innovation_prospective_ledger_aggregate_invalid")
        elif not _close(value, float(expected)):
            raise ValueError("action_innovation_prospective_ledger_aggregate_invalid")


def _descriptor(value: object, *, path_required: bool) -> bool:
    if not isinstance(value, Mapping):
        return False
    expected = {"sha256", "size_bytes"} | ({"path"} if path_required else set())
    return (
        set(value) == expected
        and _valid_sha256(value.get("sha256"))
        and isinstance(value.get("size_bytes"), int)
        and not isinstance(value.get("size_bytes"), bool)
        and value["size_bytes"] > 0
        and (
            not path_required
            or (isinstance(value.get("path"), str) and bool(value["path"].strip()))
        )
    )


def _artifact(path: Path, body: bytes) -> dict[str, object]:
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


def _json_mapping(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("action_innovation_prospective_ledger_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("action_innovation_prospective_ledger_json_invalid")
    return payload


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"action_innovation_prospective_ledger_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"action_innovation_prospective_ledger_{name}_time_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"action_innovation_prospective_ledger_{name}_time_invalid")
    return parsed


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"action_innovation_prospective_ledger_{name}_number_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"action_innovation_prospective_ledger_{name}_number_invalid")
    return result


def _close(value: object, expected: float) -> bool:
    try:
        actual = _number(value, "metric")
    except ValueError:
        return False
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)


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
        raise ValueError("action_innovation_prospective_ledger_refuses_overwrite")
    ledger = compile_prospective_evidence_ledger(
        args.evidence_audit,
        forecast_receipt_paths=args.forecast_receipt,
        uncertainty_freeze_path=args.uncertainty_freeze,
    )
    _write(args.output, ledger)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
