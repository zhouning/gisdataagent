#!/usr/bin/env python3
"""Freeze the no-network Stage 45 replication-target protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STAGE45_ROOT = "data/geotransport_v0_1/stage45_center_hill_component_lag_replication_targets"
DEFAULT_OUTPUT = REPO_ROOT / STAGE45_ROOT / "protocol.json"
SCHEMA = "gwm.geotransport.stage45_component_lag_replication_target_protocol.v1"
STAGE44_ROOT = "data/geotransport_v0_1/stage44_center_hill_component_lag_replication"
STAGE44_INVENTORY_PATH = f"{STAGE44_ROOT}/target_exposure_inventory.json"
STAGE44_PROTOCOL_PATH = f"{STAGE44_ROOT}/replication_protocol.json"
STAGE44_CANDIDATE_PATH = f"{STAGE44_ROOT}/replication_candidate_ledger.json"
STAGE44_MANIFEST_PATH = f"{STAGE44_ROOT}/replication_event_manifest.json"
STAGE44_GATES_PATH = "benchmarks/geotransport_v0_1/stage44_component_lag_replication_gates.json"
TARGET_OPERATOR_PATH = "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
FROZEN_HASHES = {
    STAGE44_INVENTORY_PATH: ("ccb102452ec522c8303d52d71fc01969504f668e5c17f17011eac3041517aa9d"),
    STAGE44_PROTOCOL_PATH: ("ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d"),
    STAGE44_CANDIDATE_PATH: ("8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b"),
    STAGE44_MANIFEST_PATH: ("b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f"),
    STAGE44_GATES_PATH: ("1481f7426bd0102a2f1661a6de9c903c99d20ef1607d122989ec2f76f7107a49"),
    TARGET_OPERATOR_PATH: ("43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"),
}
EXPECTED_EVENT_IDS = (
    "component_total_step_20230129T0100Z",
    "component_total_step_20250122T2000Z",
    "component_total_step_20210428T1700Z",
    "component_total_step_20230729T0400Z",
)
EXPECTED_TARGET_WINDOWS_UTC = (
    ("2023-01-28T01:00:00Z", "2023-01-31T13:00:00Z"),
    ("2025-01-21T20:00:00Z", "2025-01-25T08:00:00Z"),
    ("2021-04-27T17:00:00Z", "2021-05-01T05:00:00Z"),
    ("2023-07-28T04:00:00Z", "2023-07-31T16:00:00Z"),
)
OBSERVATION_EXTENSION_HOURS = 12
EXPECTED_IDEAL_HALF_HOUR_POSITIONS = 169


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_protocol() -> dict[str, Any]:
    manifest = _validated_stage44_manifest()
    hypothesis = manifest["strict_replication_hypothesis"]
    frozen_events = []
    for event, expected_id, expected_window in zip(
        manifest["selected_events"],
        EXPECTED_EVENT_IDS,
        EXPECTED_TARGET_WINDOWS_UTC,
        strict=True,
    ):
        target_window = (
            str(event["start_utc"]),
            _iso(_parse_time(str(event["end_utc"])) + timedelta(hours=OBSERVATION_EXTENSION_HOURS)),
        )
        if str(event["event_id"]) != expected_id or target_window != expected_window:
            raise ValueError("stage45_derived_target_window_drift")
        frozen_events.append(
            {
                "event_id": event["event_id"],
                "selection_rank": event["selection_rank"],
                "selection_stratum": event["selection_stratum"],
                "antecedent_flow_class": event["antecedent_flow_class"],
                "total_direction": event["total_direction"],
                "step_time_utc": event["step_time_utc"],
                "source_start_utc": event["start_utc"],
                "source_end_utc": event["end_utc"],
                "target_begin_utc": target_window[0],
                "target_end_utc": target_window[1],
                "dominant_step_component": event["dominant_step_component"],
                "selected_without_target_values": event["selected_without_downstream_values"],
            }
        )
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-lag-replication-targets-v1",
        "frozen_inputs": {
            "stage44_target_exposure_inventory": artifact_record(STAGE44_INVENTORY_PATH),
            "stage44_replication_protocol": artifact_record(STAGE44_PROTOCOL_PATH),
            "stage44_replication_candidate_ledger": artifact_record(STAGE44_CANDIDATE_PATH),
            "stage44_replication_event_manifest": artifact_record(STAGE44_MANIFEST_PATH),
            "stage44_replication_gates": artifact_record(STAGE44_GATES_PATH),
            "empirical_lag_support_operator": artifact_record(TARGET_OPERATOR_PATH),
        },
        "frozen_events": frozen_events,
        "target_source": {
            "site_id": "USGS-03424860",
            "site_role": "downstream_replication_outcome",
            "parameter_code": "00060",
            "quantity": "continuous_discharge",
        },
        "target_observation_contract": {
            "source": "usgs_water_data_ogc_continuous",
            "requested_sample_interval_minutes": 30,
            "event_source_window_hours": 72,
            "post_source_window_extension_hours": (OBSERVATION_EXTENSION_HOURS),
            "requested_elapsed_hours": 84,
            "expected_ideal_inclusive_half_hour_positions": (EXPECTED_IDEAL_HALF_HOUR_POSITIONS),
            "timestamp_grid_origin": "target_begin_utc",
            "timestamps_normalized_to_utc": True,
            "missing_samples_filled": False,
            "duplicate_timestamp_policy": "reject",
            "unexpected_parameter_site_statistic_or_unit_policy": "reject",
            "quality_metadata_preserved": True,
            "quality_metadata_is_scientific_approval": False,
            "unexpected_pagination_policy": "fail_closed",
        },
        "strict_replication_hypothesis": hypothesis,
        "post_acquisition_allowed_assessment": {
            "raw_hash_request_and_license_audit_allowed": True,
            "per_event_time_coverage_audit_allowed": True,
            "half_hour_to_hour_aggregation_allowed": (
                "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
            ),
            "missing_hour_policy": "drop_without_filling",
            "per_event_empirical_lag_support_set_allowed": True,
            "flow_class_bidirectional_replication_decision_allowed": True,
            "event_reselection_allowed": False,
            "source_or_target_threshold_retuning_allowed": False,
            "universal_lag_promotion_allowed": False,
            "stage30_falsification_override_allowed": False,
            "causal_or_physical_time_promotion_allowed": False,
        },
        "blinding_protocol": {
            "complete_known_target_exposure_inventory_applied_before_events": True,
            "events_hypothesis_and_target_operator_frozen_before_new_values": True,
            "target_values_used_during_event_selection": False,
            "target_values_may_change_event_selection": False,
            "target_values_may_change_replication_hypothesis": False,
        },
        "data_boundary": {
            "network_requests_allowed_during_protocol_freeze": False,
            "network_request_count": 0,
            "target_request_plan_frozen": False,
            "new_source_values_acquired": False,
            "new_target_values_acquired": False,
            "workspace_or_private_data_requested": False,
            "fresh_user_approval_required_after_exact_plan_freeze": True,
        },
        "claim_boundary": {
            "stage44_source_only_replication_cohort_preserved": True,
            "target_protocol_frozen": True,
            "target_request_plan_frozen": False,
            "target_values_acquired": False,
            "replication_test_executed": False,
            "stage43_pattern_replicated": False,
            "stage30_historical_falsification_overturned": False,
            "universal_lag_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _validated_stage44_manifest() -> dict[str, Any]:
    value = _read_json(REPO_ROOT / STAGE44_MANIFEST_PATH)
    gates = _read_json(REPO_ROOT / STAGE44_GATES_PATH)
    events = value.get("selected_events")
    hypothesis = value.get("strict_replication_hypothesis")
    claims = value.get("claim_boundary")
    if (
        value.get("status") != "stage44_component_lag_replication_cohort_frozen_source_only"
        or not isinstance(events, list)
        or tuple(str(event.get("event_id")) for event in events) != EXPECTED_EVENT_IDS
        or [event.get("selection_rank") for event in events] != [1, 2, 3, 4]
        or any(
            event.get("selected_without_downstream_values") is not True
            or event.get("dominant_step_component") != "turbine"
            for event in events
        )
        or not isinstance(hypothesis, dict)
        or hypothesis.get("high_flow_required_supported_lag_hours") != 5
        or hypothesis.get("low_flow_required_supported_lag_hours") != 6
        or hypothesis.get("partial_direction_or_flow_class_pass_allowed") is not False
        or not isinstance(claims, dict)
        or claims.get("source_only_replication_cohort_frozen") is not True
        or claims.get("stage43_pattern_replicated") is not False
        or gates.get("all_gates_passed") is not True
        or len(gates.get("gates", {})) != 44
    ):
        raise ValueError("stage45_stage44_checkpoint_invalid")
    return value


def artifact_record(relative_path: str) -> dict[str, object]:
    body = (REPO_ROOT / relative_path).read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage45_frozen_artifact_drift:{relative_path}")
    return {"path": relative_path, "sha256": sha256, "size_bytes": len(body)}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage45_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage45_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    body = json_bytes(build_protocol())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    print(args.output)
    print("network_requests=0")
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
