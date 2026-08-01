#!/usr/bin/env python3
"""Freeze the no-network Stage 44 component-lag replication protocol."""

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

from scripts import (  # noqa: E402
    compile_geotransport_stage44_target_exposure_inventory as exposure,
)

STAGE44_ROOT = exposure.STAGE44_ROOT
DEFAULT_OUTPUT = REPO_ROOT / STAGE44_ROOT / "replication_protocol.json"
SCHEMA = "gwm.geotransport.stage44_component_lag_replication_protocol.v1"
EXCLUSION_RADIUS_DAYS = 30
EXPECTED_ELIGIBLE_CANDIDATE_COUNT = 1_343
EXPECTED_STRATUM_COUNTS = {
    "high_increase": 3,
    "high_decrease": 11,
    "low_increase": 700,
    "low_decrease": 629,
}
EXPECTED_COMPONENT_COUNTS = {
    "orifice": 0,
    "sluice": 0,
    "spillway": 0,
    "turbine": 1_337,
}
EXPECTED_EVENT_IDS = (
    "component_total_step_20230129T0100Z",
    "component_total_step_20250122T2000Z",
    "component_total_step_20210428T1700Z",
    "component_total_step_20230729T0400Z",
)
EXPECTED_EVENT_TIMES_UTC = (
    "2023-01-29T01:00:00Z",
    "2025-01-22T20:00:00Z",
    "2021-04-28T17:00:00Z",
    "2023-07-29T04:00:00Z",
)
TARGET_EXPOSURE_OPERATOR_PATH = "data_agent/uwm/geospatial_kernel_v2/target_exposure_inventory.py"
TARGET_EXPOSURE_COMPILER_PATH = "scripts/compile_geotransport_stage44_target_exposure_inventory.py"
TARGET_EXPOSURE_INVENTORY_PATH = f"{STAGE44_ROOT}/target_exposure_inventory.json"
SELECTION_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/component_discharge_event_selection.py"
)
TARGET_OPERATOR_PATH = "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
STAGE30_LEDGER_PATH = (
    "data/geotransport_v0_1/stage30_center_hill_regime_validation_events/"
    "regime_transfer_evidence_ledger.json"
)
STAGE40_LEDGER_PATH = (
    "data/geotransport_v0_1/stage40_center_hill_component_discharge_value_support/"
    "component_discharge_value_support_ledger.json"
)
STAGE40_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage40_component_discharge_value_support_gates.json"
)
STAGE43_LEDGER_PATH = (
    "data/geotransport_v0_1/stage43_center_hill_component_event_lag_support/"
    "component_event_lag_support_evidence_ledger.json"
)
STAGE43_GATES_PATH = "benchmarks/geotransport_v0_1/stage43_component_event_lag_support_gates.json"
FROZEN_HASHES = {
    TARGET_EXPOSURE_OPERATOR_PATH: (
        "983fbe82b59a3dba4fa77085c1cd65f869086b9f2f13cd73b9a02e1b99ed7794"
    ),
    TARGET_EXPOSURE_COMPILER_PATH: (
        "5f624bff41a1a10b90db463690d24d325af90e988980a2ced4c3f82427468f1f"
    ),
    TARGET_EXPOSURE_INVENTORY_PATH: (
        "ccb102452ec522c8303d52d71fc01969504f668e5c17f17011eac3041517aa9d"
    ),
    SELECTION_OPERATOR_PATH: ("f3f72959befaf70384994f9a47265ac6cd87e1fa63824fbf9879c7bf37784d04"),
    TARGET_OPERATOR_PATH: ("43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"),
    STAGE30_LEDGER_PATH: ("6153cdea6451e8ff8b2126ce5776d2f4dc33d4bc616cb8e5eb201e56cebf283c"),
    STAGE40_LEDGER_PATH: ("d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1"),
    STAGE40_GATES_PATH: ("6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec"),
    STAGE43_LEDGER_PATH: ("91c85ba78d1f4bd8e500b800b3496f395b378244549c7e0b1a68fa107e85e94a"),
    STAGE43_GATES_PATH: ("c18c11f2d637e272304b1b60a9ab39e8e135a27cc6fb4e89a86a531a4471c46c"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_protocol() -> dict[str, Any]:
    inventory = exposure.compile_inventory()
    merged = inventory.excluded_windows_utc
    compatibility_anchor = merged[0][0]
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-total-lag-replication-v1",
        "frozen_inputs": {
            key: artifact_record(path)
            for key, path in (
                ("target_exposure_operator", TARGET_EXPOSURE_OPERATOR_PATH),
                ("target_exposure_compiler", TARGET_EXPOSURE_COMPILER_PATH),
                ("target_exposure_inventory", TARGET_EXPOSURE_INVENTORY_PATH),
                ("event_selection_operator", SELECTION_OPERATOR_PATH),
                ("empirical_lag_support_operator", TARGET_OPERATOR_PATH),
                ("stage30_historical_falsification", STAGE30_LEDGER_PATH),
                ("stage40_component_source_ledger", STAGE40_LEDGER_PATH),
                ("stage40_component_source_gates", STAGE40_GATES_PATH),
                ("stage43_exploratory_evidence", STAGE43_LEDGER_PATH),
                ("stage43_exploratory_gates", STAGE43_GATES_PATH),
            )
        },
        "target_exposure_boundary": {
            "target_site_id": "USGS-03424860",
            "parameter_code": "00060",
            "source_artifact_count": len(inventory.source_artifacts),
            "exposure_record_count": len(inventory.records),
            "merged_interval_count": len(merged),
            "merged_intervals": [list(value) for value in merged],
            "exclusion_radius_days": EXCLUSION_RADIUS_DAYS,
            "candidate_window_must_not_overlap_expanded_interval": True,
            "selector_api_compatibility_anchor_utc": compatibility_anchor,
            "compatibility_anchor_is_already_contained_by_first_window": True,
        },
        "source_only_selection": {
            "candidate_begin_utc": "2021-01-01T00:00:00Z",
            "candidate_end_utc": "2026-01-01T00:00:00Z",
            "components": ["orifice", "sluice", "spillway", "turbine"],
            "total_formula": "orifice_plus_sluice_plus_spillway_plus_turbine",
            "timestamp_join": "exact_utc_hour",
            "event_window_hours_before_step": 24,
            "event_window_hours_after_step": 48,
            "minimum_absolute_one_hour_step_m3s": 50.0,
            "minimum_window_range_m3s": 100.0,
            "antecedent_flow_threshold_m3s": 200.0,
            "required_strata_in_selection_order": [
                "high_increase",
                "high_decrease",
                "low_increase",
                "low_decrease",
            ],
            "minimum_inter_event_separation_days": 180,
            "ranking": (
                "within_stratum_descending_excursion_support_then_"
                "descending_normalized_volume_then_ascending_lag_condition_"
                "then_descending_absolute_step_then_ascending_time"
            ),
            "expected_eligible_candidate_count": (EXPECTED_ELIGIBLE_CANDIDATE_COUNT),
            "expected_candidate_counts_by_stratum": EXPECTED_STRATUM_COUNTS,
            "expected_component_gate_candidate_counts": (EXPECTED_COMPONENT_COUNTS),
            "expected_event_ids": list(EXPECTED_EVENT_IDS),
            "expected_event_times_utc": list(EXPECTED_EVENT_TIMES_UTC),
            "downstream_values_available_to_selector": False,
        },
        "strict_replication_hypothesis": {
            "role": "confirmatory_test_of_stage43_exploratory_pattern",
            "event_count": 4,
            "high_flow_required_supported_lag_hours": 5,
            "low_flow_required_supported_lag_hours": 6,
            "directions_required_within_each_flow_class": [
                "increase",
                "decrease",
            ],
            "each_event_must_have_detectable_response": True,
            "required_event_local_pearson_r": 0.8,
            "maximum_supported_lag_loss_pearson_r": 0.02,
            "minimum_pair_count": 60,
            "best_lag_must_be_interior": True,
            "lag_candidates_hours": list(range(13)),
            "target_operator_retuning_after_values_allowed": False,
            "event_reselection_after_values_allowed": False,
            "partial_direction_or_flow_class_pass_allowed": False,
        },
        "later_target_protocol_boundary": {
            "target_site_id": "USGS-03424860",
            "parameter_code": "00060",
            "quantity": "continuous_discharge",
            "target_window_rule": (
                "source_event_start_through_twelve_hours_after_source_event_end"
            ),
            "target_request_plan_created_in_stage44": False,
            "target_values_acquired_in_stage44": False,
            "fresh_bounded_plan_required_before_requests": True,
            "fresh_user_approval_required_after_plan_freeze": True,
        },
        "decision_rule": {
            "future_pass_admits": (
                "center_hill_component_total_flow_class_cohort_replication_only"
            ),
            "future_pass_does_not_admit_universal_lag": True,
            "future_pass_does_not_overturn_stage30_falsification": True,
            "future_fail_retains_stage43_as_event_local_exploratory_evidence": True,
            "common_support_across_high_and_low_classes_required": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_response_admitted": False,
            "physical_travel_time_admitted": False,
            "hydraulic_edge_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
        "data_boundary": {
            "network_requests_allowed": False,
            "network_request_count": 0,
            "new_source_values_acquired": False,
            "new_target_values_acquired": False,
            "workspace_or_private_data_requested": False,
        },
    }


def artifact_record(relative_path: str) -> dict[str, object]:
    body = (REPO_ROOT / relative_path).read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage44_frozen_artifact_drift:{relative_path}")
    return {"path": relative_path, "sha256": sha256, "size_bytes": len(body)}


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
