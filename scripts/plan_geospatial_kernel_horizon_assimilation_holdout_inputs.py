#!/usr/bin/env python3
"""Compile the no-network input request plan for the frozen holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

if __package__:
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
    )
else:
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_protocol.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_input_plan.json"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_input_plan.v1"
NWM_ROOT = (
    "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
    "CONUS/zarr/chrtout.zarr"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_holdout_input_plan(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(protocol_path)
    _validate_protocol(protocol)
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("horizon_holdout_input_plan_generated_at_must_be_aware")

    issue_times = tuple(_parse_time(value) for value in protocol["window"]["issue_times_utc"])
    nwm_requests: dict[str, dict[str, Any]] = {}
    system_plans: dict[str, dict[str, Any]] = {}
    for system_id in freeze.SYSTEM_IDS:
        lock = protocol["systems"][system_id]
        for feature_chunk in lock["feature_chunk_indices"]:
            for variable in ("streamflow", "velocity"):
                key = f"{variable}/{freeze.INITIAL_TIME_CHUNK}.{feature_chunk}"
                nwm_requests[key] = _nwm_request(
                    variable,
                    f"{freeze.INITIAL_TIME_CHUNK}.{feature_chunk}",
                )
            key = f"q_lateral/{freeze.FORCING_TIME_CHUNK}.{feature_chunk}"
            nwm_requests[key] = _nwm_request(
                "q_lateral",
                f"{freeze.FORCING_TIME_CHUNK}.{feature_chunk}",
            )
        for time_chunk in (freeze.INITIAL_TIME_CHUNK, freeze.FORCING_TIME_CHUNK):
            key = f"time/{time_chunk}"
            nwm_requests[key] = _nwm_request("time", str(time_chunk))
        site_id = lock["issue_observation"]["site_id"]
        issue_requests = [
            _issue_observation_request(site_id, issue_time) for issue_time in issue_times
        ]
        system_plans[system_id] = {
            "system_id": system_id,
            "action_request": {
                "method": "GET",
                "url": lock["action"]["url"],
                "expected_support_end_count": protocol["window"]["hour_count"],
                "future_target_observation": False,
            },
            "issue_observation_requests": issue_requests,
            "issue_observation_request_count": len(issue_requests),
            "full_outcome_request_included": False,
            "topology_report": dict(lock["topology_report"]),
        }
    requests = [nwm_requests[key] for key in sorted(nwm_requests)]
    return {
        "schema": SCHEMA,
        "status": "holdout_input_requests_planned_not_executed",
        "generated_at": now.astimezone(UTC).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "window": dict(protocol["window"]),
        "systems": system_plans,
        "nwm_requests": requests,
        "request_counts": {
            "nwm_unique_object_count": len(requests),
            "cwms_action_request_count": len(freeze.SYSTEM_IDS),
            "usgs_issue_observation_request_count": (
                len(freeze.SYSTEM_IDS) * len(issue_times)
            ),
            "usgs_full_outcome_request_count": 0,
            "total_external_request_count_if_executed": (
                len(requests)
                + len(freeze.SYSTEM_IDS)
                + len(freeze.SYSTEM_IDS) * len(issue_times)
            ),
        },
        "issue_observation_request_contract": {
            "one_request_per_system_and_issue": True,
            "request_start": "issue_time_minus_5_minutes",
            "request_end": "issue_time",
            "post_issue_time_requested": False,
            "execution_order": (
                "for_each_issue_time_fetch_both_system_observations_then_seal_"
                "both_system_all_mode_predictions_before_next_issue_time"
            ),
            "bulk_prefetch_all_issue_observation_values_permitted": False,
            "next_issue_request_before_current_joint_issue_seal": False,
            "exact_issue_timestamp_required_in_response": True,
            "missing_exact_issue_timestamp_policy": "issue_falls_back_to_nominal_state",
            "actual_publication_latency_verified": False,
        },
        "decoded_input_contract": {
            "initial_modeled_state": ["streamflow", "velocity"],
            "hourly_modeled_forcing": "q_lateral",
            "hourly_boundary_action": "CWMS_release",
            "issue_state_observation": "USGS_00060_exact_issue_only",
            "target_observation_columns_permitted": False,
            "score_or_loss_columns_permitted": False,
        },
        "data_isolation": {
            "network_request_executed": False,
            "dynamic_value_loaded": False,
            "full_outcome_url_compiled": False,
            "full_outcome_value_loaded": False,
            "prediction_executed": False,
            "score_computed": False,
        },
        "next_gate": {
            "action": (
                "execute the frozen input plan, validate exact axes and hashes, then "
                "run and seal each issue with the frozen policy and rollout core"
            ),
            "requires_explicit_network_execution": True,
        },
        "claim_boundary": {
            "input_plan_complete": True,
            "inputs_acquired": False,
            "outcome_free_predictions_executed": False,
            "holdout_scored": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _issue_observation_request(site_id: str, issue_time: datetime) -> dict[str, Any]:
    start = issue_time - timedelta(minutes=5)
    query = urlencode(
        {
            "format": "json",
            "sites": site_id,
            "parameterCd": "00060",
            "startDT": _iso(start),
            "endDT": _iso(issue_time),
            "siteStatus": "all",
        }
    )
    return {
        "method": "GET",
        "site_id": site_id,
        "issue_time_utc": _iso(issue_time),
        "request_start_utc": _iso(start),
        "request_end_utc": _iso(issue_time),
        "url": f"https://waterservices.usgs.gov/nwis/iv/?{query}",
        "post_issue_value_requested": False,
    }


def _nwm_request(variable: str, chunk_key: str) -> dict[str, Any]:
    return {
        "method": "GET",
        "variable": variable,
        "chunk_key": chunk_key,
        "url": f"{NWM_ROOT}/{variable}/{chunk_key}",
    }


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    claims = protocol.get("claim_boundary") or {}
    if (
        protocol.get("schema") != freeze.SCHEMA
        or protocol.get("status") != "frozen_before_holdout_input_value_access"
        or tuple(protocol.get("systems", {})) != freeze.SYSTEM_IDS
        or claims.get("holdout_protocol_frozen") is not True
        or claims.get("holdout_inputs_acquired") is not False
        or claims.get("outcome_free_predictions_executed") is not False
        or claims.get("holdout_outcomes_acquired") is not False
        or claims.get("candidate_support_gate_evaluated") is not False
        or claims.get("candidate_promoted") is not False
        or claims.get("runtime_default_enabled") is not False
    ):
        raise ValueError("horizon_holdout_input_plan_protocol_invalid")

    candidate = protocol.get("candidate_lock")
    parent = protocol.get("parent_evidence")
    time_axis = protocol.get("time_axis_evidence")
    if not all(isinstance(value, Mapping) for value in (candidate, parent, time_axis)):
        raise ValueError("horizon_holdout_input_plan_protocol_lock_missing")

    descriptors = {
        "policy_freeze_path": candidate.get("policy_freeze"),
        "parent_protocol_path": parent.get("two_system_topology_protocol"),
        "time_zarray_path": time_axis.get("nwm_time_zarray"),
        "time_zattrs_path": time_axis.get("nwm_time_zattrs"),
    }
    if not all(isinstance(value, Mapping) for value in descriptors.values()):
        raise ValueError("horizon_holdout_input_plan_protocol_lock_missing")
    for descriptor in descriptors.values():
        _read_verified(descriptor)

    try:
        frozen_at = _parse_time(protocol.get("frozen_at"))
        expected = freeze.compile_holdout_protocol(
            **{
                name: _descriptor_path(descriptor)
                for name, descriptor in descriptors.items()
            },
            frozen_at=frozen_at,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("horizon_holdout_input_plan_protocol_invalid") from exc
    if dict(protocol) != expected:
        raise ValueError("horizon_holdout_input_plan_protocol_invalid")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = _descriptor_path(descriptor)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_input_plan_artifact_identity_mismatch")
    return body


def _descriptor_path(descriptor: Mapping[str, Any]) -> Path:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_input_plan_artifact_outside_repository") from exc
    return path


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_input_plan_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_input_plan_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("horizon_holdout_input_plan_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("horizon_holdout_input_plan_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError("horizon_holdout_input_plan_time_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    plan = compile_holdout_input_plan(protocol_path=args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(
        "planned_external_requests="
        f"{plan['request_counts']['total_external_request_count_if_executed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
