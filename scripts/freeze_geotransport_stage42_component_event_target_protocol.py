#!/usr/bin/env python3
"""Freeze the no-network Stage 42 component-event target protocol."""

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

STAGE42_ROOT = (
    "data/geotransport_v0_1/"
    "stage42_center_hill_component_event_target_protocol"
)
DEFAULT_OUTPUT = REPO_ROOT / STAGE42_ROOT / "protocol.json"
SCHEMA = "gwm.geotransport.stage42_component_event_target_protocol.v1"
STAGE41_ROOT = (
    "data/geotransport_v0_1/"
    "stage41_center_hill_component_discharge_events"
)
STAGE41_MANIFEST_PATH = f"{STAGE41_ROOT}/event_selection_manifest.json"
STAGE41_LEDGER_PATH = (
    f"{STAGE41_ROOT}/component_discharge_event_evidence_ledger.json"
)
STAGE41_GATES_PATH = (
    "benchmarks/geotransport_v0_1/"
    "stage41_component_discharge_event_gates.json"
)
TARGET_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
)
FROZEN_HASHES = {
    STAGE41_MANIFEST_PATH: (
        "3ffecd85ce74147eb11e1ccc084b4ac5b2774bae81511a416c54735b156d7e6a"
    ),
    STAGE41_LEDGER_PATH: (
        "6c859b4cc52455beea308e2418832c9ce71a679f9ca882d3bcea9facbaf7a1d3"
    ),
    STAGE41_GATES_PATH: (
        "46d92725139c4d9a93fadad708aea6ba9e4edcce93187cf2bcff945c1cbfe340"
    ),
    TARGET_OPERATOR_PATH: (
        "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"
    ),
}
EXPECTED_EVENT_IDS = (
    "component_total_step_20250415T1600Z",
    "component_total_step_20230311T2000Z",
    "component_total_step_20210112T1600Z",
    "component_total_step_20210727T0300Z",
)
OBSERVATION_EXTENSION_HOURS = 12
EXPECTED_IDEAL_HALF_HOUR_POSITIONS = 169


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def artifact_record(relative_path: str) -> dict[str, object]:
    path = REPO_ROOT / relative_path
    body = path.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    if actual != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage42_frozen_artifact_drift:{relative_path}")
    return {
        "path": relative_path,
        "sha256": actual,
        "size_bytes": len(body),
    }


def build_protocol() -> dict[str, Any]:
    manifest = _validated_stage41_manifest()
    ledger = _validated_stage41_ledger()
    target = manifest["target_functional"]
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-event-target-values-v1",
        "frozen_inputs": {
            "stage41_event_manifest": artifact_record(
                STAGE41_MANIFEST_PATH
            ),
            "stage41_public_ledger": artifact_record(STAGE41_LEDGER_PATH),
            "stage41_gates": artifact_record(STAGE41_GATES_PATH),
            "target_operator": artifact_record(TARGET_OPERATOR_PATH),
        },
        "frozen_events": [
            {
                "event_id": event["event_id"],
                "selection_rank": event["selection_rank"],
                "selection_stratum": event["selection_stratum"],
                "step_time_utc": event["step_time_utc"],
                "source_start_utc": event["start_utc"],
                "source_end_utc": event["end_utc"],
                "target_begin_utc": event["start_utc"],
                "target_end_utc": _iso(
                    _parse_time(str(event["end_utc"]))
                    + timedelta(hours=OBSERVATION_EXTENSION_HOURS)
                ),
                "dominant_step_component": event[
                    "dominant_step_component"
                ],
                "selected_without_target_values": event[
                    "selected_without_downstream_values"
                ],
            }
            for event in manifest["selected_events"]
        ],
        "target_sources": [
            {
                "site_id": target["target_site_id"],
                "site_role": "downstream_outcome",
                "quantity": target["quantity"],
                "parameter_code": target["parameter_code"],
            },
            {
                "site_id": target["observed_graph_state_site_id"],
                "site_role": "observed_graph_state",
                "quantity": target["quantity"],
                "parameter_code": target["parameter_code"],
            },
        ],
        "target_observation_contract": {
            "source": "usgs_water_data_ogc_continuous",
            "quantity": "continuous_discharge",
            "parameter_code": "00060",
            "requested_sample_interval_minutes": 30,
            "event_source_window_hours": 72,
            "post_source_window_extension_hours": (
                OBSERVATION_EXTENSION_HOURS
            ),
            "requested_elapsed_hours": 84,
            "expected_ideal_inclusive_half_hour_positions": (
                EXPECTED_IDEAL_HALF_HOUR_POSITIONS
            ),
            "timestamps_normalized_to_utc": True,
            "missing_samples_filled": False,
            "duplicate_timestamp_policy": "require_identical_then_keep_one",
            "unexpected_parameter_or_site_policy": "reject",
            "quality_metadata_preserved": True,
            "quality_metadata_is_approval_semantics": False,
        },
        "frozen_target_functional": target,
        "post_acquisition_allowed_assessment": {
            "raw_hash_request_and_license_audit_allowed": True,
            "per_event_site_time_coverage_audit_allowed": True,
            "half_hour_to_hour_aggregation_allowed": (
                "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
            ),
            "missing_hour_policy": "drop_without_filling",
            "per_event_empirical_lag_support_set_allowed": True,
            "cross_event_common_support_intersection_allowed": True,
            "event_reselection_allowed": False,
            "source_or_target_threshold_retuning_allowed": False,
            "causal_or_physical_time_promotion_allowed": False,
        },
        "blinding_protocol": {
            "events_and_target_operator_hash_frozen_before_target_values": True,
            "target_values_used_during_event_selection": False,
            "event_selection_may_be_recomputed_from_target_values": False,
            "target_operator_may_be_retuned_after_target_values": False,
            "component_contrast_may_be_inferred_from_turbine_only_events": False,
        },
        "data_boundary": {
            "network_requests_allowed_during_protocol_freeze": False,
            "new_source_values_acquired": False,
            "new_target_values_acquired": False,
            "workspace_or_private_data_requested": False,
            "fresh_user_approval_required_for_target_requests": True,
        },
        "claim_boundary": {
            "stage41_source_only_events_preserved": True,
            "target_value_protocol_frozen": True,
            "target_values_acquired": False,
            "empirical_lag_support_sets_compiled": False,
            "common_empirical_lag_support_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "observed_downstream_response_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
        "stage41_decision": ledger["decision"],
    }


def _validated_stage41_manifest() -> dict[str, Any]:
    value = _read_json(REPO_ROOT / STAGE41_MANIFEST_PATH)
    events = value.get("selected_events")
    target = value.get("target_functional")
    boundary = value.get("data_boundary")
    claims = value.get("claim_boundary")
    if (
        value.get("status")
        != "stage41_component_total_discharge_events_frozen_source_only"
        or not isinstance(events, list)
        or tuple(str(event.get("event_id")) for event in events)
        != EXPECTED_EVENT_IDS
        or [event.get("selection_rank") for event in events] != [1, 2, 3, 4]
        or any(
            event.get("selected_without_downstream_values") is not True
            or event.get("dominant_step_component") != "turbine"
            for event in events
        )
        or not isinstance(target, dict)
        or target.get("operator_schema")
        != "gwm.geospatial.empirical_lag_support.v1"
        or target.get("lag_candidates_hours") != list(range(13))
        or target.get("supported_lag_is_physical_travel_time") is not False
        or not isinstance(boundary, dict)
        or boundary.get("network_request_count") != 0
        or not isinstance(claims, dict)
        or claims.get("source_only_total_discharge_events_admitted") is not True
        or claims.get("non_turbine_component_contrast_admitted") is not False
    ):
        raise ValueError("stage42_stage41_event_manifest_invalid")
    return value


def _validated_stage41_ledger() -> dict[str, Any]:
    value = _read_json(REPO_ROOT / STAGE41_LEDGER_PATH)
    gates = _read_json(REPO_ROOT / STAGE41_GATES_PATH)
    decision = value.get("decision")
    if (
        value.get("status")
        != "stage41_complete_source_only_total_discharge_events_admitted"
        or not isinstance(decision, dict)
        or decision.get("source_only_total_discharge_event_count") != 4
        or decision.get("non_turbine_component_contrast_admitted") is not False
        or decision.get("downstream_or_tributary_values_acquired") is not False
        or gates.get("all_gates_passed") is not True
        or gates.get("status")
        != "stage41_complete_source_only_total_discharge_events_admitted"
        or len(gates.get("gates", {})) != 37
    ):
        raise ValueError("stage42_stage41_public_checkpoint_invalid")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage42_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage42_timezone_required")
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
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
