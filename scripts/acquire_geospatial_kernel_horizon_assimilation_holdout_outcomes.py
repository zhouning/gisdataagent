#!/usr/bin/env python3
"""Acquire the two frozen full-window USGS outcome series exactly once."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__:
    from scripts import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_scoring_protocol as scoring_protocol,
    )
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from scripts.acquire_geotransport_v2_blind_validation_outcomes import (
        _fetch_usgs,
        _parse_usgs_native_hourly,
    )
else:
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout
    from acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from acquire_geotransport_v2_blind_validation_outcomes import (
        _fetch_usgs,
        _parse_usgs_native_hourly,
    )

    scoring_protocol = importlib.import_module(
        "freeze_geospatial_kernel_horizon_assimilation_holdout_scoring_protocol"
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCORING_PROTOCOL = scoring_protocol.DEFAULT_OUTPUT
DEFAULT_OUTPUT = scoring_protocol.DEFAULT_OUTCOME_ROOT
DEFAULT_REPORT = scoring_protocol.DEFAULT_OUTCOME_REPORT
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_outcomes.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scoring-protocol", type=Path, default=DEFAULT_SCORING_PROTOCOL
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


def acquire(
    *,
    scoring_protocol_path: Path = DEFAULT_SCORING_PROTOCOL,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    protocol_body, protocol = _load_json(scoring_protocol_path)
    holdout_body = _validate_scoring_protocol(protocol)
    holdout_protocol = json.loads(holdout_body)
    support_ends = tuple(
        holdout.START + timedelta(hours=index + 1)
        for index in range(holdout.HOUR_COUNT)
    )
    support_starts = tuple(value - timedelta(hours=1) for value in support_ends)
    opener = _opener(proxy)
    raw_bodies: dict[str, bytes] = {}
    value_bodies: dict[str, bytes] = {}
    systems: dict[str, dict[str, Any]] = {}
    requests = protocol["outcome_request_lock"]["requests"]
    for request_lock in requests:
        system_id = str(request_lock["system_id"])
        frozen_system = holdout_protocol["systems"][system_id][
            "future_scoring_outcome"
        ]
        _validate_request_lock(request_lock, frozen_system)
        body, retrieval = _fetch_usgs(
            str(request_lock["url"]),
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=1,
            maximum_bytes=5_000_000,
        )
        outcomes, qualifiers, counts, cadence = _parse_usgs_native_hourly(
            json.loads(body),
            system={
                "outcome": {
                    "site_id": request_lock["site_id"],
                    "parameter_code": request_lock["parameter_code"],
                }
            },
            support_starts=support_starts,
            support_ends=support_ends,
        )
        csv_body = _outcome_csv(support_ends, outcomes)
        raw_bodies[system_id] = body
        value_bodies[system_id] = csv_body
        complete = sum(value is not None for value in outcomes.values())
        systems[system_id] = {
            "system_id": system_id,
            "site_id": request_lock["site_id"],
            "parameter_code": request_lock["parameter_code"],
            "source": retrieval,
            "raw_outcome": _artifact(
                output_root / f"raw/{system_id}.json", body
            ),
            "outcome_values": _artifact(
                output_root / f"values/{system_id}.csv", csv_body
            ),
            "quality": {
                "target_hour_count": holdout.HOUR_COUNT,
                "complete_target_hour_count": complete,
                "missing_target_hour_count": holdout.HOUR_COUNT - complete,
                "native_sample_cadence_seconds": cadence,
                "expected_native_samples_per_complete_hour": 3600 // cadence,
                "sample_counts": sorted(set(counts.values())),
                "qualifiers": sorted(
                    {value for value in qualifiers.values() if value}
                ),
                "hourly_support": "(target_time_minus_1h,target_time]",
                "missing_values_imputed": False,
            },
        }

    if tuple(raw_bodies) != holdout.SYSTEM_IDS:
        raise ValueError("horizon_holdout_outcome_system_order_invalid")
    return raw_bodies, value_bodies, {
        "schema": SCHEMA,
        "status": "two_full_outcome_series_acquired_after_joint_prediction_seal",
        "generated_at": datetime.now(UTC).isoformat(),
        "scoring_protocol": _artifact(scoring_protocol_path, protocol_body),
        "sealed_artifacts": dict(protocol["frozen_artifacts"]),
        "request_execution": {
            "logical_request_count": len(requests),
            "remote_attempt_count": sum(
                int(value["source"]["attempt_count"]) for value in systems.values()
            ),
            "maximum_remote_attempts": protocol["outcome_request_lock"][
                "maximum_total_remote_attempts"
            ],
            "all_requests_match_frozen_urls": True,
            "additional_outcome_requests_made": False,
        },
        "systems": systems,
        "ordering_audit": {
            "joint_predictions_verified_before_first_outcome_request": True,
            "outcome_free_rollout_independently_verified_before_access": True,
            "acquisition_and_scorer_hashes_frozen_before_access": True,
            "predictions_modified_after_outcome_access": False,
        },
        "claim_boundary": {
            "holdout_outcomes_acquired": True,
            "outcomes_imputed": False,
            "holdout_scored": False,
            "candidate_support_gate_evaluated": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_scoring_protocol(protocol: Mapping[str, Any]) -> bytes:
    if (
        protocol.get("schema") != scoring_protocol.SCHEMA
        or protocol.get("status") != "frozen_before_full_outcome_access"
        or protocol.get("pre_access_audit", {}).get(
            "outcome_full_series_requested"
        )
        is not False
        or protocol.get("pre_access_audit", {}).get("score_computed") is not False
        or protocol.get("outcome_request_lock", {}).get("logical_request_count")
        != len(holdout.SYSTEM_IDS)
        or protocol.get("outcome_request_lock", {}).get(
            "maximum_total_remote_attempts"
        )
        != len(holdout.SYSTEM_IDS)
    ):
        raise ValueError("horizon_holdout_outcome_scoring_protocol_invalid")
    artifacts = protocol.get("frozen_artifacts") or {}
    expected = {
        "holdout_protocol",
        "input_plan",
        "rollout_report",
        "rollout_verification",
        "predictions",
        "outcome_acquisition_script",
        "scorer_script",
        "native_hourly_parser_helper",
    }
    if set(artifacts) != expected:
        raise ValueError("horizon_holdout_outcome_frozen_artifacts_invalid")
    bodies = {name: _read_verified(value) for name, value in artifacts.items()}
    verification = json.loads(bodies["rollout_verification"])
    rollout_report = json.loads(bodies["rollout_report"])
    if (
        verification.get("status")
        != "pass_chronological_outcome_free_rollout_verification"
        or verification.get("execution_gates", {}).get(
            "all_execution_gates_passed"
        )
        is not True
        or rollout_report.get("data_isolation", {}).get(
            "full_outcome_series_requested"
        )
        is not False
    ):
        raise ValueError("horizon_holdout_outcome_rollout_not_clean")
    return bodies["holdout_protocol"]


def _validate_request_lock(
    request_lock: Mapping[str, Any], frozen_system: Mapping[str, Any]
) -> None:
    if (
        request_lock.get("method") != "GET"
        or request_lock.get("site_id") != frozen_system.get("site_id")
        or request_lock.get("parameter_code") != frozen_system.get("parameter_code")
        or request_lock.get("request_start_utc") != _iso(holdout.START)
        or request_lock.get("request_end_utc") != _iso(holdout.END)
        or request_lock.get("logical_request_count") != 1
        or request_lock.get("maximum_remote_attempts") != 1
    ):
        raise ValueError("horizon_holdout_outcome_request_lock_invalid")


def _outcome_csv(
    support_ends: tuple[datetime, ...],
    outcomes: Mapping[datetime, float | None],
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


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_outcome_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_outcome_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_outcome_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_outcome_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.report.exists():
        raise ValueError("horizon_holdout_outcomes_already_acquired")
    if args.timeout_seconds <= 0.0:
        raise ValueError("horizon_holdout_outcome_timeout_must_be_positive")
    raw, values, report = acquire(
        scoring_protocol_path=args.scoring_protocol,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
    )
    for system_id in holdout.SYSTEM_IDS:
        raw_path = args.output / f"raw/{system_id}.json"
        value_path = args.output / f"values/{system_id}.csv"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        value_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw[system_id])
        value_path.write_bytes(values[system_id])
    _write_json(args.report, report)
    print(args.report)
    for system_id in holdout.SYSTEM_IDS:
        quality = report["systems"][system_id]["quality"]
        print(
            f"{system_id}_complete_target_hours="
            f"{quality['complete_target_hour_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
