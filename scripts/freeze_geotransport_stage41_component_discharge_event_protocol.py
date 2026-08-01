#!/usr/bin/env python3
"""Freeze the offline Stage 41 component-discharge event protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_event_selection as selection,
)
from data_agent.uwm.geospatial_kernel_v2 import empirical_lag_support

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE41_ROOT = (
    "data/geotransport_v0_1/"
    "stage41_center_hill_component_discharge_events"
)
DEFAULT_OUTPUT = REPO_ROOT / STAGE41_ROOT / "protocol.json"
SCHEMA = "gwm.geotransport.stage41_component_discharge_event_protocol.v1"
SELECTION_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/"
    "component_discharge_event_selection.py"
)
EXCITATION_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/"
    "release_excitation_identifiability.py"
)
TARGET_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py"
)
STAGE40_LEDGER_PATH = (
    "data/geotransport_v0_1/"
    "stage40_center_hill_component_discharge_value_support/"
    "component_discharge_value_support_ledger.json"
)
STAGE40_GATES_PATH = (
    "benchmarks/geotransport_v0_1/"
    "stage40_component_discharge_value_support_gates.json"
)
FROZEN_HASHES = {
    SELECTION_OPERATOR_PATH: (
        "f3f72959befaf70384994f9a47265ac6cd87e1fa63824fbf9879c7bf37784d04"
    ),
    EXCITATION_OPERATOR_PATH: (
        "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb"
    ),
    TARGET_OPERATOR_PATH: (
        "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"
    ),
    STAGE40_LEDGER_PATH: (
        "d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1"
    ),
    STAGE40_GATES_PATH: (
        "6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec"
    ),
}
PRIOR_OUTCOME_EVENT_TIMES_UTC = (
    "2021-03-22T12:00:00Z",
    "2021-06-25T16:00:00Z",
    "2021-09-25T19:00:00Z",
    "2022-02-02T19:00:00Z",
    "2022-06-13T13:00:00Z",
    "2022-09-19T15:00:00Z",
    "2022-12-23T19:00:00Z",
    "2023-06-13T00:00:00Z",
    "2023-09-11T15:00:00Z",
    "2024-02-03T13:00:00Z",
    "2024-08-21T20:00:00Z",
    "2025-03-03T16:00:00Z",
    "2025-06-06T16:00:00Z",
    "2025-09-10T14:00:00Z",
    "2025-12-15T17:00:00Z",
)
TARGET_EXPOSED_EVENT_TIMES_UTC = (
    "2023-10-04T17:30:00Z",
    "2021-09-01T15:30:00Z",
    "2021-03-03T23:30:00Z",
    "2022-09-03T16:30:00Z",
)
PRIOR_OUTCOME_WINDOWS_UTC = (
    ("2024-05-15T00:00:00Z", "2024-05-18T00:00:00Z"),
)
EXCLUSION_RADIUS_DAYS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def artifact_record(relative_path: str) -> dict[str, object]:
    path = REPO_ROOT / relative_path
    body = path.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    if actual != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage41_frozen_artifact_drift:{relative_path}")
    return {
        "path": relative_path,
        "sha256": actual,
        "size_bytes": len(body),
    }


def build_protocol() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-total-discharge-events-v1",
        "frozen_inputs": {
            "selection_operator": artifact_record(SELECTION_OPERATOR_PATH),
            "release_excitation_operator": artifact_record(
                EXCITATION_OPERATOR_PATH
            ),
            "target_operator": artifact_record(TARGET_OPERATOR_PATH),
            "stage40_ledger": artifact_record(STAGE40_LEDGER_PATH),
            "stage40_gates": artifact_record(STAGE40_GATES_PATH),
        },
        "source_observation_semantics": {
            "components": ["orifice", "sluice", "spillway", "turbine"],
            "quantity": "component_discharge",
            "unit": "cms",
            "measurement_statistic": "one_hour_interval_average",
            "cwms_storage_time_basis": "UTC",
            "cwms_default_timestamp_position": "end",
            "source_time_support_offsets_minutes": [-60, 0],
            "source_marker_is_release_actuation_instant": False,
            "component_value_is_gate_command": False,
            "component_value_is_human_action": False,
            "component_value_is_causal_intervention": False,
        },
        "frozen_total_derivation": {
            "formula": "orifice_plus_sluice_plus_spillway_plus_turbine",
            "timestamp_join": "exact_utc_hour",
            "expected_unique_hour_count": 43_825,
            "duplicate_annual_boundaries_removed_only_after_exact_match": True,
            "missing_value_policy": "reject_without_filling",
            "negative_value_policy": "reject",
            "quality_codes_preserved": True,
            "quality_codes_used_as_approval_filter": False,
            "persist_full_derived_total_series": False,
            "derived_total_role": "source_only_event_selector",
        },
        "source_only_development_diagnostic": {
            "stage40_source_values_available_during_protocol_design": True,
            "new_target_values_available_during_protocol_design": False,
            "excluded_target_values_used_for_threshold_tuning": False,
            "exclusion_radius_sensitivity_days": [14, 30, 90],
            "eligible_total_candidate_counts_by_radius": {
                "14": 4_041,
                "30": 2_547,
                "90": None,
            },
            "ninety_day_selection_rejection": (
                "high_increase_and_high_decrease_strata_unavailable"
            ),
            "ninety_day_strata_available": [
                "low_increase",
                "low_decrease",
            ],
            "thirty_day_all_four_strata_available": True,
            "selection_rationale": (
                "largest tested exclusion radius retaining all four frozen "
                "high_low_and_direction_strata"
            ),
            "diagnostic_does_not_admit_events": True,
        },
        "frozen_source_gate": {
            "inclusive_window_value_count": (
                selection.INCLUSIVE_WINDOW_VALUE_COUNT
            ),
            "window_hours_before_step": selection.EVENT_BEFORE_STEP_HOURS,
            "window_hours_after_step": selection.EVENT_AFTER_STEP_HOURS,
            "minimum_absolute_one_hour_step_m3s": (
                selection.MINIMUM_ABSOLUTE_STEP_M3S
            ),
            "minimum_window_range_m3s": (
                selection.MINIMUM_WINDOW_RANGE_M3S
            ),
            "reference_support_offsets_hours": [-24, -6],
            "maximum_excursion_support_hours": 12,
            "excursion_step_fraction": 0.25,
            "minimum_excursion_support_hours": 3,
            "minimum_normalized_volume_step_hours": 3.0,
            "minimum_release_standard_deviation_m3s": 30.0,
            "maximum_absolute_lag_autocorrelation": 0.97,
            "maximum_lag_design_condition_number": 50.0,
            "lag_design_candidates_hours": list(range(13)),
            "outcome_values_used": False,
            "exact_lag_identified_by_input_gate": False,
        },
        "predeclared_event_selection": {
            "candidate_begin_utc": "2021-01-01T00:00:00Z",
            "candidate_end_utc": "2026-01-01T00:00:00Z",
            "event_count": 4,
            "required_strata_in_selection_order": list(
                selection.STRATUM_ORDER
            ),
            "antecedent_flow_threshold_m3s": (
                selection.HIGH_FLOW_THRESHOLD_M3S
            ),
            "minimum_event_separation_days": (
                selection.MINIMUM_EVENT_SEPARATION_DAYS
            ),
            "prior_outcome_exclusion_radius_days": EXCLUSION_RADIUS_DAYS,
            "candidate_window_must_not_overlap_exclusion_interval": True,
            "prior_outcome_event_times_utc": list(
                PRIOR_OUTCOME_EVENT_TIMES_UTC
            ),
            "target_exposed_event_times_utc": list(
                TARGET_EXPOSED_EVENT_TIMES_UTC
            ),
            "prior_outcome_windows_utc": [
                list(value) for value in PRIOR_OUTCOME_WINDOWS_UTC
            ],
            "ranking": (
                "within_stratum_descending_excursion_support_then_"
                "descending_normalized_volume_then_ascending_lag_"
                "condition_then_descending_absolute_step_then_ascending_time"
            ),
            "selection_data": "synchronized_cwms_component_values_only",
            "downstream_values_available_to_selector": False,
            "selected_role": "blind_component_total_discharge_event",
        },
        "predeclared_target_functional": {
            "operator_schema": empirical_lag_support.SCHEMA,
            "target_site_id": "USGS-03424860",
            "observed_graph_state_site_id": "USGS-03424730",
            "parameter_code": "00060",
            "quantity": "continuous_discharge",
            "sample_interval_minutes": 30,
            "lag_candidates_hours": list(
                empirical_lag_support.LAG_CANDIDATES_HOURS
            ),
            "minimum_pearson_r": empirical_lag_support.MINIMUM_PEARSON_R,
            "maximum_best_loss_pearson_r": (
                empirical_lag_support.MAXIMUM_BEST_LOSS_PEARSON_R
            ),
            "minimum_pair_count": empirical_lag_support.MINIMUM_PAIR_COUNT,
            "best_lag_must_be_interior": True,
            "output_type": "discrete_supported_lag_set",
            "common_support_requirement": (
                "intersection_of_all_event_support_sets_is_nonempty"
            ),
            "supported_lag_is_physical_travel_time": False,
        },
        "blinding_protocol": {
            "source_values_used_for_exclusion_sensitivity_only": True,
            "selection_operator_frozen_before_final_event_manifest": True,
            "events_selected_from_source_values_only": True,
            "all_known_target_exposures_excluded": True,
            "target_functional_frozen_before_new_target_values": True,
            "event_selection_may_be_recomputed_from_target_values": False,
            "source_or_target_threshold_retuning_after_target_values": False,
        },
        "data_boundary": {
            "network_requests_allowed": False,
            "new_source_values_acquired": False,
            "new_downstream_or_tributary_values_acquired": False,
            "private_or_workspace_data_requested": False,
            "fresh_approval_required_for_later_outcome_acquisition": True,
        },
        "claim_boundary": {
            "event_protocol_frozen": True,
            "synchronized_total_discharge_derivation_admitted": False,
            "component_total_discharge_events_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "quality_code_approval_semantics_admitted": False,
            "gate_command_admitted": False,
            "human_action_admitted": False,
            "observed_downstream_response_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    body = json_bytes(build_protocol())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    print(args.output)
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
