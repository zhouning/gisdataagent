#!/usr/bin/env python3
"""Freeze the no-network Stage 46 replication assessment protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    component_lag_replication_assessment as assessment,
)
from scripts import (  # noqa: E402
    acquire_geotransport_stage45_component_lag_replication_targets as acquire,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage45_component_lag_replication_target_protocol as stage45,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage45_component_lag_replication_targets as planner,
)

STAGE46_ROOT = "data/geotransport_v0_1/stage46_center_hill_component_lag_replication_assessment"
DEFAULT_OUTPUT = REPO_ROOT / STAGE46_ROOT / "protocol.json"
SCHEMA = "gwm.geotransport.stage46_component_lag_replication_assessment_protocol.v1"
ASSESSMENT_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/component_lag_replication_assessment.py"
)
ASSESSMENT_OPERATOR_TEST_PATH = (
    "data_agent/test_geospatial_kernel_component_lag_replication_assessment.py"
)
EMPIRICAL_LAG_OPERATOR_PATH = "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
STAGE40_LEDGER_PATH = (
    "data/geotransport_v0_1/stage40_center_hill_component_discharge_value_support/"
    "component_discharge_value_support_ledger.json"
)
STAGE40_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage40_component_discharge_value_support_gates.json"
)
STAGE44_PROTOCOL_PATH = (
    "data/geotransport_v0_1/stage44_center_hill_component_lag_replication/replication_protocol.json"
)
STAGE44_CANDIDATE_PATH = (
    "data/geotransport_v0_1/stage44_center_hill_component_lag_replication/"
    "replication_candidate_ledger.json"
)
STAGE44_MANIFEST_PATH = stage45.STAGE44_MANIFEST_PATH
STAGE44_GATES_PATH = stage45.STAGE44_GATES_PATH
STAGE45_PROTOCOL_PATH = f"{stage45.STAGE45_ROOT}/protocol.json"
STAGE45_PLAN_PATH = f"{stage45.STAGE45_ROOT}/target_acquisition_plan.json"
STAGE45_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage45_component_lag_replication_target_plan_gates.json"
)
STAGE45_ACQUIRER_PATH = "scripts/acquire_geotransport_stage45_component_lag_replication_targets.py"
FROZEN_HASHES = {
    ASSESSMENT_OPERATOR_PATH: ("8370ad5889ec0e39aff8a13492d63fcf50709a1d89a74d18c7674bc38f4104c3"),
    ASSESSMENT_OPERATOR_TEST_PATH: (
        "f18aaf7693574d10c4ce083878c6a90b82f8c3cd2a8600b4a17d9bd6585819df"
    ),
    EMPIRICAL_LAG_OPERATOR_PATH: (
        "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"
    ),
    STAGE40_LEDGER_PATH: ("d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1"),
    STAGE40_GATES_PATH: ("6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec"),
    STAGE44_PROTOCOL_PATH: ("ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d"),
    STAGE44_CANDIDATE_PATH: ("8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b"),
    STAGE44_MANIFEST_PATH: ("b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f"),
    STAGE44_GATES_PATH: ("1481f7426bd0102a2f1661a6de9c903c99d20ef1607d122989ec2f76f7107a49"),
    STAGE45_PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    STAGE45_PLAN_PATH: acquire.FROZEN_PLAN_SHA256,
    STAGE45_GATES_PATH: ("6324d80b982f7364f98af972ac451418fb66ec3a82ac2de5a89e9990735ae4a3"),
    STAGE45_ACQUIRER_PATH: ("1bab223eb4e85cd12e47ae6d57ecddde28979341721a71c5bf9002d95c75b348"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_protocol() -> dict[str, Any]:
    stage44_manifest = _read_json(REPO_ROOT / STAGE44_MANIFEST_PATH)
    stage45_protocol = _read_json(REPO_ROOT / STAGE45_PROTOCOL_PATH)
    stage45_plan = _read_json(REPO_ROOT / STAGE45_PLAN_PATH)
    stage45_gates = _read_json(REPO_ROOT / STAGE45_GATES_PATH)
    if (
        stage45_protocol != stage45.build_protocol()
        or stage45_plan != planner.compile_plan()
        or stage45_gates.get("all_gates_passed") is not True
        or len(stage45_gates.get("gates", {})) != 45
        or stage45_gates.get("decision", {}).get("target_values_acquired") is not False
    ):
        raise ValueError("stage46_stage45_pending_checkpoint_invalid")
    events = tuple(stage44_manifest["selected_events"])
    sources = tuple(stage45_plan["sources"])
    if (
        tuple(value["event_id"] for value in events) != stage45.EXPECTED_EVENT_IDS
        or tuple(value["event_id"] for value in sources) != stage45.EXPECTED_EVENT_IDS
    ):
        raise ValueError("stage46_frozen_event_identity_drift")
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-lag-confirmatory-assessment-v1",
        "frozen_inputs": {path: artifact_record(path) for path in FROZEN_HASHES},
        "frozen_event_contract": [
            {
                "event_id": event["event_id"],
                "selection_rank": event["selection_rank"],
                "selection_stratum": event["selection_stratum"],
                "source_start_utc": event["start_utc"],
                "source_end_utc": event["end_utc"],
                "target_begin_utc": source["begin_utc"],
                "target_end_utc": source["end_utc"],
                "target_source_id": source["source_id"],
                "target_output_name": source["output_name"],
                "required_lag_hours": (
                    assessment.REQUIRED_LAG_BY_FLOW_CLASS[str(event["antecedent_flow_class"])]
                ),
            }
            for event, source in zip(events, sources, strict=True)
        ],
        "source_reconstruction_contract": {
            "components": ["orifice", "sluice", "spillway", "turbine"],
            "formula": "orifice_plus_sluice_plus_spillway_plus_turbine",
            "timestamp_join": "exact_utc_hour",
            "event_source_value_count": 72,
            "source_offsets_from_window_start_hours": list(range(1, 73)),
            "missing_component_value_policy": "reject_without_filling",
            "negative_component_value_policy": "reject",
            "quality_codes_preserved": True,
            "quality_codes_are_scientific_approval": False,
        },
        "target_compilation_contract": {
            "site_id": "USGS-03424860",
            "parameter_code": "00060",
            "statistic_id": "00011",
            "raw_unit": "ft^3/s",
            "compiled_unit": "m3/s",
            "requested_elapsed_hours": 84,
            "maximum_inclusive_half_hour_positions": 169,
            "hourly_aggregation": ("mean_of_two_observed_half_hour_samples_in_open_closed_hour"),
            "missing_sample_or_hour_policy": "drop_without_filling",
            "duplicate_timestamp_policy": "reject",
            "quality_metadata_preserved": True,
            "quality_metadata_is_scientific_approval": False,
        },
        "per_event_lag_support_contract": {
            "operator_schema": "gwm.geospatial.empirical_lag_support.v1",
            "lag_candidates_hours": list(range(13)),
            "minimum_pearson_r": 0.8,
            "maximum_best_loss_pearson_r": 0.02,
            "minimum_pair_count": 60,
            "best_lag_must_be_interior": True,
            "response_must_be_detectable": True,
            "supported_lag_is_physical_travel_time": False,
        },
        "cohort_assessment_contract": {
            "operator_schema": assessment.SCHEMA,
            "required_strata": list(assessment.EXPECTED_STRATA),
            "required_lag_by_flow_class_hours": (assessment.REQUIRED_LAG_BY_FLOW_CLASS),
            "support_membership_not_exact_hour_equality": True,
            "partial_direction_or_flow_class_pass_allowed": False,
            "all_four_frozen_strata_required": True,
            "admitted_scope_on_pass": (
                "center_hill_component_total_flow_class_cohort_replication_only"
            ),
        },
        "required_post_acquisition_checkpoint": {
            "frozen_plan_sha256": acquire.FROZEN_PLAN_SHA256,
            "acquisition_state_name": acquire.STATE_NAME,
            "acquisition_manifest_name": acquire.MANIFEST_NAME,
            "required_manifest_status": (
                "stage45_replication_target_values_acquired_assessment_pending"
            ),
            "required_logical_request_count": 4,
            "required_artifact_count": 4,
            "required_source_ids": [value["source_id"] for value in sources],
            "required_output_names": [value["output_name"] for value in sources],
            "all_raw_hashes_must_match_manifest": True,
            "all_requests_must_stay_within_frozen_plan": True,
        },
        "decision_boundary": {
            "event_reselection_allowed": False,
            "source_or_target_threshold_retuning_allowed": False,
            "partial_replication_admission_allowed": False,
            "universal_lag_admitted_on_cohort_pass": False,
            "stage30_falsification_overturned_on_cohort_pass": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
        "data_boundary": {
            "network_code_path_present": False,
            "network_request_count": 0,
            "stage45_target_values_present": False,
            "assessment_executed": False,
            "workspace_or_private_data_requested": False,
        },
        "claim_boundary": {
            "assessment_protocol_frozen_before_target_values": True,
            "target_values_acquired": False,
            "replication_test_executed": False,
            "cohort_replication_admitted": False,
            "stage43_pattern_replicated": False,
            "universal_lag_admitted": False,
            "stage30_historical_falsification_overturned": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def artifact_record(relative_path: str) -> dict[str, object]:
    body = (REPO_ROOT / relative_path).read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage46_frozen_artifact_drift:{relative_path}")
    return {"path": relative_path, "sha256": sha256, "size_bytes": len(body)}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage46_json_object_required")
    return value


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    body = json_bytes(build_protocol())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    print(args.output)
    print("network_requests=0")
    print("target_values=0")
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
