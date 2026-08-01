#!/usr/bin/env python3
"""Freeze the first unused historical holdout for the horizon policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_policy_freeze.json"
)
DEFAULT_PARENT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_TIME_ZARRAY = REPO_ROOT / "data/geotransport_v0_1/metadata/nwm-time-zarray.json"
DEFAULT_TIME_ZATTRS = REPO_ROOT / "data/geotransport_v0_1/metadata/nwm-time-zattrs.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_protocol.json"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_protocol.v1"
POLICY_FREEZE_SCHEMA = "gwm.geotransport.horizon_assimilation_policy_freeze.v1"
PARENT_PROTOCOL_SCHEMA = "gwm.geotransport.v2_blind_validation_protocol.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
INITIAL_STATE_AT = datetime(2022, 4, 28, 0, tzinfo=UTC)
START = datetime(2022, 4, 28, 1, tzinfo=UTC)
END = datetime(2022, 5, 26, 1, tzinfo=UTC)
HOUR_COUNT = 672
ISSUE_STRIDE_HOURS = 12
ISSUE_INDICES = tuple(range(0, HOUR_COUNT, ISSUE_STRIDE_HOURS))
INITIAL_TIME_CHUNK = 563
FORCING_TIME_CHUNK = 564
TIMESTEP_SECONDS = 3600
SUBSTEP_SECONDS = 300
NWM_ORIGIN = datetime(1979, 2, 1, 1, tzinfo=UTC)
PRISTINE_PATHS = (
    "data/geotransport_v0_1/geospatial_kernel_horizon_assimilation_holdout",
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_inputs_report.json",
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_rollout_report.json",
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-freeze", type=Path, default=DEFAULT_POLICY_FREEZE)
    parser.add_argument("--parent-protocol", type=Path, default=DEFAULT_PARENT_PROTOCOL)
    parser.add_argument("--time-zarray", type=Path, default=DEFAULT_TIME_ZARRAY)
    parser.add_argument("--time-zattrs", type=Path, default=DEFAULT_TIME_ZATTRS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_holdout_protocol(
    *,
    policy_freeze_path: Path = DEFAULT_POLICY_FREEZE,
    parent_protocol_path: Path = DEFAULT_PARENT_PROTOCOL,
    time_zarray_path: Path = DEFAULT_TIME_ZARRAY,
    time_zattrs_path: Path = DEFAULT_TIME_ZATTRS,
    frozen_at: datetime | None = None,
) -> dict[str, Any]:
    policy_body, policy_freeze = _load_json(policy_freeze_path)
    parent_body, parent = _load_json(parent_protocol_path)
    zarray_body, zarray = _load_json(time_zarray_path)
    zattrs_body, zattrs = _load_json(time_zattrs_path)
    policy = _validate_policy_freeze(policy_freeze)
    _validate_parent_protocol(parent)
    _validate_time_axis(zarray, zattrs)
    now = frozen_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("horizon_holdout_frozen_at_must_be_aware")

    systems = {
        system_id: _system_lock(system_id, parent["systems"][system_id])
        for system_id in SYSTEM_IDS
    }
    issue_times = tuple(START + timedelta(hours=value) for value in ISSUE_INDICES)
    target_times = {
        str(horizon): [
            _iso(issue_time + timedelta(hours=horizon)) for issue_time in issue_times
        ]
        for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
    }
    return {
        "schema": SCHEMA,
        "status": "frozen_before_holdout_input_value_access",
        "frozen_at": now.astimezone(UTC).isoformat(),
        "scientific_role": (
            "first repository-unconsumed historical holdout for the frozen "
            "horizon assimilation policy; not a real-time prospective campaign"
        ),
        "candidate_lock": {
            "policy_freeze": _artifact(policy_freeze_path, policy_body),
            "policy_sha256": policy_freeze["policy_sha256"],
            "policy": policy.as_dict(),
            "outcome_free_rollout_core": dict(
                policy_freeze["implementation_artifacts"][
                    "outcome_free_rollout_core"
                ]
            ),
            "policy_change_after_freeze_permitted": False,
            "runtime_default_enabled": False,
        },
        "parent_evidence": {
            "two_system_topology_protocol": _artifact(
                parent_protocol_path,
                parent_body,
            ),
            "reuse_topology_geometry_and_forcing_support_without_change": True,
            "parent_window_end_utc": parent["window"]["end_exclusive"],
            "holdout_starts_at_parent_window_end": (
                parent["window"]["end_exclusive"] == _iso(START)
            ),
        },
        "time_axis_evidence": {
            "nwm_time_zarray": _artifact(time_zarray_path, zarray_body),
            "nwm_time_zattrs": _artifact(time_zattrs_path, zattrs_body),
            "nwm_origin_utc": _iso(NWM_ORIGIN),
            "time_chunk_size_hours": 672,
            "initial_state_time_chunk_index": INITIAL_TIME_CHUNK,
            "forcing_time_chunk_index": FORCING_TIME_CHUNK,
        },
        "window": {
            "initial_state_valid_at_utc": _iso(INITIAL_STATE_AT),
            "start_inclusive_utc": _iso(START),
            "end_exclusive_utc": _iso(END),
            "hour_count": HOUR_COUNT,
            "issue_stride_hours": ISSUE_STRIDE_HOURS,
            "issue_indices": list(ISSUE_INDICES),
            "issue_times_utc": [_iso(value) for value in issue_times],
            "issue_count_per_system": len(issue_times),
            "horizons_hours": list(
                HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            ),
            "target_times_utc_by_horizon": target_times,
        },
        "systems": systems,
        "execution_lock": {
            "operator": "BranchingManningNetworkTransportOperator",
            "timestep_seconds": TIMESTEP_SECONDS,
            "integration_substep_seconds": SUBSTEP_SECONDS,
            "modeled_state_reference": (
                "NWM_v3_retrospective_streamflow_times_velocity_times_"
                "trapezoid_area_times_effective_length"
            ),
            "reference_storage_floor": (
                "one_centimeter_rectangular_channel_storage_minimum_one_m3"
            ),
            "action": "archived_CWMS_boundary_release",
            "forcing": "NWM_v3_retrospective_q_lateral",
            "issue_observation": "USGS_00060_exact_issue_support_end",
            "issue_observation_available_at": "issue_time_assumed_not_verified",
            "negative_or_missing_issue_observation_policy": "nominal_state_fallback",
            "future_target_argument_accepted": False,
            "score_or_loss_argument_accepted": False,
            "per_issue_all_constituent_predictions_sealed": True,
            "state_or_parameter_adaptation_from_matured_scores": False,
        },
        "rolling_origin_contract": {
            "later_issue_observation_may_equal_prior_12h_target": True,
            "later_issue_observation_role": "next_issue_causal_state_only",
            "later_issue_observation_may_change_policy_or_parameters": False,
            "issue_times_must_execute_in_chronological_order": True,
            "fetch_both_system_issue_observations_then_seal_joint_issue": True,
            "next_issue_observation_request_before_current_joint_issue_seal": False,
            "issue_observation_value_visible_only_to_matching_issue": True,
            "all_issue_predictions_sealed_before_full_outcome_series_request": True,
            "historical_request_order_is_not_external_prospective_proof": True,
        },
        "scoring_lock": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s"],
            "common_complete_case_mask_per_system_and_horizon": True,
            "minimum_scored_issues_per_system_and_horizon": 48,
            "fixed_single_mode_comparator": (
                "quadratic_distance_localized_mainstem_update"
            ),
            "traditional_comparator": "causal_issue_observation_persistence",
            "candidate_support_gate": (
                "policy_RMSE_strictly_below_fixed_quadratic_and_persistence_for_"
                "every_system_and_horizon_with_all_execution_gates_passed"
            ),
            "cross_system_or_cross_horizon_compensation_permitted": False,
            "score_once_after_joint_prediction_seal": True,
        },
        "freshness_boundary": {
            "window_values_accessed_by_this_compiler": False,
            "window_locally_consumed_by_prior_kernel_report": False,
            "external_prior_access_can_be_proven_absent": False,
            "historical_holdout": True,
            "real_time_prospective": False,
            "operational_action_vintage": False,
            "operational_nwm_forecast_vintage": False,
        },
        "forbidden_after_freeze": [
            "change_window_issue_schedule_systems_or_horizons",
            "change_policy_or_outcome_free_rollout_core",
            "change_topology_geometry_or_forcing_support",
            "fit_any_parameter_on_holdout_outcomes",
            "use_post_issue_observation_in_an_issue_rollout",
            "change_comparators_metrics_masks_or_gates_after_outcome_access",
            "rerun_any_sealed_issue_after_its_target_is_accessed",
        ],
        "claim_boundary": {
            "holdout_protocol_frozen": True,
            "holdout_inputs_acquired": False,
            "outcome_free_predictions_executed": False,
            "holdout_outcomes_acquired": False,
            "candidate_support_gate_evaluated": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _system_lock(system_id: str, parent: Mapping[str, Any]) -> dict[str, Any]:
    action_series = str(parent["action"]["timeseries"])
    action_query = urlencode(
        {
            "name": action_series,
            "office": parent["action"]["office"],
            "begin": _iso(START),
            "end": _iso(END),
            "unit": "cms",
            "page-size": 50000,
        }
    )
    return {
        "system_id": system_id,
        "topology_report": dict(parent["topology_report"]),
        "feature_count": int(parent["feature_count"]),
        "mainstem_feature_count": int(parent["mainstem_feature_count"]),
        "branch_feature_count": int(parent["branch_feature_count"]),
        "action_entry_feature_id": int(parent["action_entry_feature_id"]),
        "outlet_feature_id": int(parent["outlet_feature_id"]),
        "feature_chunk_indices": list(parent["feature_chunk_indices"]),
        "forcing_support": dict(parent["forcing_support"]),
        "action": {
            "source": "USACE CWMS Data API",
            "timeseries": action_series,
            "office": parent["action"]["office"],
            "unit": "cms",
            "support_kind": "interval_mean",
            "timestamp_position": "end",
            "url": f"https://cwms-data.usace.army.mil/cwms-data/timeseries?{action_query}",
        },
        "issue_observation": {
            "source": "USGS Water Services IV",
            "site_id": parent["outcome"]["site_id"],
            "parameter_code": "00060",
            "role": "causal_issue_state_only",
        },
        "future_scoring_outcome": {
            "source": "USGS Water Services IV",
            "site_id": parent["outcome"]["site_id"],
            "parameter_code": "00060",
            "access_phase": "after_all_issue_predictions_are_jointly_sealed",
        },
    }


def _validate_policy_freeze(payload: Mapping[str, Any]) -> HorizonAssimilationPolicy:
    if (
        payload.get("schema") != POLICY_FREEZE_SCHEMA
        or payload.get("status")
        != "horizon_assimilation_candidate_frozen_awaiting_unused_window"
        or payload.get("claim_boundary", {}).get("candidate_promoted") is not False
        or payload.get("claim_boundary", {}).get("runtime_default_enabled") is not False
    ):
        raise ValueError("horizon_holdout_policy_freeze_invalid")
    descriptors = payload.get("implementation_artifacts")
    if not isinstance(descriptors, Mapping) or "outcome_free_rollout_core" not in descriptors:
        raise ValueError("horizon_holdout_rollout_core_not_frozen")
    for descriptor in descriptors.values():
        _read_verified(descriptor)
    policy_payload = payload.get("policy")
    if not isinstance(policy_payload, Mapping):
        raise ValueError("horizon_holdout_policy_missing")
    canonical = json.dumps(
        policy_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != payload.get("policy_sha256"):
        raise ValueError("horizon_holdout_policy_hash_mismatch")
    return HorizonAssimilationPolicy.from_dict(policy_payload)


def _validate_parent_protocol(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema") != PARENT_PROTOCOL_SCHEMA
        or tuple(payload.get("systems", {})) != SYSTEM_IDS
        or payload.get("window", {}).get("end_exclusive") != _iso(START)
    ):
        raise ValueError("horizon_holdout_parent_protocol_invalid")
    for system_id in SYSTEM_IDS:
        system = payload["systems"][system_id]
        _read_verified(system["topology_report"])


def _validate_time_axis(zarray: Mapping[str, Any], zattrs: Mapping[str, Any]) -> None:
    chunk_size = int(zarray.get("chunks", [0])[0])
    if (
        chunk_size != HOUR_COUNT
        or zattrs.get("units") != "hours since 1979-02-01T01:00:00"
        or zattrs.get("calendar") != "proleptic_gregorian"
        or END - START != timedelta(hours=HOUR_COUNT)
        or _time_chunk(INITIAL_STATE_AT, chunk_size) != INITIAL_TIME_CHUNK
        or _time_chunk(START, chunk_size) != FORCING_TIME_CHUNK
        or _time_chunk(END - timedelta(hours=1), chunk_size)
        != FORCING_TIME_CHUNK
    ):
        raise ValueError("horizon_holdout_nwm_time_axis_invalid")


def _time_chunk(value: datetime, chunk_size: int) -> int:
    hours = int((value - NWM_ORIGIN).total_seconds() // 3600)
    return hours // chunk_size


def _assert_pristine(output_path: Path) -> None:
    present = [value for value in PRISTINE_PATHS if (REPO_ROOT / value).exists()]
    if output_path.exists():
        present.append(output_path.resolve().as_posix())
    if present:
        raise ValueError(f"horizon_holdout_artifact_already_exists:{present}")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_json_document_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_holdout_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    _assert_pristine(args.output)
    report = compile_holdout_protocol(
        policy_freeze_path=args.policy_freeze,
        parent_protocol_path=args.parent_protocol,
        time_zarray_path=args.time_zarray,
        time_zattrs_path=args.time_zattrs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"issue_count_per_system={report['window']['issue_count_per_system']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
