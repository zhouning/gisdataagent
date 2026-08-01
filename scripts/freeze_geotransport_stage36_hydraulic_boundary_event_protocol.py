#!/usr/bin/env python3
"""Freeze the no-network Stage 36 hydraulic-boundary event protocol."""

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
    hydraulic_boundary_perturbation as perturbation,
)

STAGE36_ROOT = (
    "data/geotransport_v0_1/"
    "stage36_center_hill_hydraulic_boundary_events"
)
DEFAULT_OUTPUT = REPO_ROOT / STAGE36_ROOT / "protocol.json"
SCHEMA = (
    "gwm.geotransport.stage36_hydraulic_boundary_event_protocol.v1"
)
OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/"
    "hydraulic_boundary_perturbation.py"
)
DEVELOPMENT_PROBE_PATH = (
    f"{STAGE36_ROOT}/development/raw/"
    "cwms_tailwater_stage_20221222T1900Z_20221225T1900Z.json"
)
STAGE35_LEDGER_PATH = (
    "data/geotransport_v0_1/stage35_center_hill_event_time_uncertainty/"
    "event_time_uncertainty_ledger.json"
)
STAGE35_GATES_PATH = (
    "benchmarks/geotransport_v0_1/"
    "stage35_event_time_uncertainty_gates.json"
)
FROZEN_HASHES = {
    OPERATOR_PATH: (
        "ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f"
    ),
    DEVELOPMENT_PROBE_PATH: (
        "7d6e471371066de145e8b476c3c04c680728062251d64c7e0aabc68d86509a27"
    ),
    STAGE35_LEDGER_PATH: (
        "2d66862d4b746885d24fb8e52eff4d80c88a93cd1357e9e774077942a6daf3e2"
    ),
    STAGE35_GATES_PATH: (
        "8a20e41c14ca5015452eb3b8c83ba39c942f5c6d019ec106a8ce791b26b7e1ad"
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
PRIOR_OUTCOME_WINDOWS_UTC = (
    ("2024-05-15T00:00:00Z", "2024-05-18T00:00:00Z"),
    ("2026-02-09T00:00:00Z", "2026-02-12T00:00:00Z"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def artifact_record(relative_path: str) -> dict[str, object]:
    path = REPO_ROOT / relative_path
    body = path.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    expected = FROZEN_HASHES[relative_path]
    if actual != expected:
        raise ValueError(f"stage36_frozen_artifact_drift:{relative_path}")
    return {
        "path": relative_path,
        "sha256": actual,
        "size_bytes": len(body),
    }


def _development_report() -> dict[str, object]:
    payload = json.loads((REPO_ROOT / DEVELOPMENT_PROBE_PATH).read_bytes())
    if (
        payload.get("name")
        != "CETT1-CENTER_HILL.Elev-Tail.Inst.30Minutes.0.dcp-rev"
        or payload.get("office-id") != "LRN"
        or payload.get("units") != "m"
        or payload.get("interval") != "PT30M"
        or payload.get("begin") != "2022-12-22T19:00:00Z"
        or payload.get("end") != "2022-12-25T19:00:00Z"
        or payload.get("total") != 145
        or len(payload.get("values") or []) != 145
        or {int(row[2]) for row in payload["values"]} != {0}
    ):
        raise ValueError("stage36_development_probe_invalid")
    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        tuple(float(row[1]) for row in payload["values"])
    )
    if not report.blind_target_test_admissible:
        raise ValueError("stage36_development_probe_gate_rejected")
    return report.as_dict()


def build_protocol() -> dict[str, Any]:
    development_report = _development_report()
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-observed-hydraulic-boundary-events-v1",
        "frozen_inputs": {
            "operator": artifact_record(OPERATOR_PATH),
            "development_probe": artifact_record(DEVELOPMENT_PROBE_PATH),
            "stage35_ledger": artifact_record(STAGE35_LEDGER_PATH),
            "stage35_gates": artifact_record(STAGE35_GATES_PATH),
        },
        "approved_development_research_boundary": {
            "source": "usace_cwms_public_api",
            "series_id": (
                "CETT1-CENTER_HILL."
                "Elev-Tail.Inst.30Minutes.0.dcp-rev"
            ),
            "office": "LRN",
            "unit": "m",
            "begin_utc": "2022-12-22T19:00:00Z",
            "end_utc": "2022-12-25T19:00:00Z",
            "maximum_attempt_count": 3,
            "maximum_response_bytes_per_attempt": 250_000,
            "actual_response_bytes": 4_701,
            "downstream_outcome_requests": 0,
            "workspace_or_private_data_sent": False,
        },
        "source_observation_semantics": {
            "quantity": "tailwater_elevation",
            "evidence_role": "observed_hydraulic_boundary_state",
            "measurement_type": "instantaneous_sample",
            "sample_interval_minutes": 30,
            "source_event_marker": (
                "timestamp_of_second_sample_in_primary_elevation_change"
            ),
            "source_event_time_support_offset_minutes": [-30, 0],
            "quality_code_zero_used_as_selection_filter": True,
            "quality_code_zero_interpreted_as_approved": False,
            "release_action_semantics": False,
            "release_discharge_semantics": False,
            "backwater_or_local_hydraulic_effects_excluded": False,
        },
        "development_evidence": {
            "marker_utc": "2022-12-23T19:00:00Z",
            "prior_public_release_timing_used_to_place_probe": True,
            "release_values_used_by_source_gate": False,
            "downstream_outcome_values_used": False,
            "development_window_excluded_from_blind_selection": True,
            "observed_elevation_range_m": [145.90776, 149.019768],
            "operator_report": development_report,
        },
        "frozen_source_gate": {
            "inclusive_window_sample_count": (
                perturbation.INCLUSIVE_WINDOW_SAMPLE_COUNT
            ),
            "window_hours_before_marker": 24,
            "window_hours_after_marker": 48,
            "primary_change_support_minutes": 30,
            "minimum_absolute_primary_change_m": (
                perturbation.MINIMUM_ABSOLUTE_PRIMARY_CHANGE_M
            ),
            "excursion_change_fraction": (
                perturbation.EXCURSION_CHANGE_FRACTION
            ),
            "minimum_excursion_support_intervals": (
                perturbation.MINIMUM_EXCURSION_SUPPORT_INTERVALS
            ),
            "minimum_normalized_excursion_intervals": (
                perturbation.MINIMUM_NORMALIZED_EXCURSION_INTERVALS
            ),
            "minimum_post_event_standard_deviation_m": (
                perturbation.MINIMUM_POST_EVENT_STANDARD_DEVIATION_M
            ),
            "missing_value_policy": "reject_incomplete_candidate_window",
            "allowed_quality_codes": [0],
            "quality_filter_is_not_approval_interpretation": True,
        },
        "predeclared_event_selection": {
            "candidate_begin_utc": "2021-01-01T00:00:00Z",
            "candidate_end_utc": "2026-01-01T00:00:00Z",
            "event_count": 4,
            "minimum_event_separation_days": 180,
            "prior_outcome_exclusion_radius_days": 14,
            "development_probe_exclusion_radius_days": 90,
            "prior_outcome_event_times_utc": list(
                PRIOR_OUTCOME_EVENT_TIMES_UTC
            ),
            "prior_outcome_windows_utc": [
                list(value) for value in PRIOR_OUTCOME_WINDOWS_UTC
            ],
            "ranking": (
                "descending_absolute_primary_change_then_descending_"
                "excursion_support_then_descending_normalized_excursion_"
                "then_ascending_marker_time"
            ),
            "selection_data": "cwms_tailwater_elevation_values_only",
            "release_values_available_to_selector": False,
            "downstream_values_available_to_selector": False,
            "selected_role": "blind_hydraulic_boundary_event",
        },
        "predeclared_target_functional": {
            "operator_schema": perturbation.TARGET_FUNCTIONAL_SCHEMA,
            "target_site_id": "USGS-03424860",
            "parameter_code": "00060",
            "quantity": "continuous_discharge",
            "sample_interval_minutes": 30,
            "inclusive_window_sample_count": (
                perturbation.TARGET_INCLUSIVE_WINDOW_SAMPLE_COUNT
            ),
            "baseline_support_offsets_hours": [-24.0, -6.5],
            "minimum_baseline_sample_count": (
                perturbation.TARGET_MINIMUM_BASELINE_SAMPLE_COUNT
            ),
            "search_offsets_minutes": [30, 720],
            "threshold_formula": (
                "max(4*1.4826*MAD,0.05*abs(baseline_median),1.0_m3s)"
            ),
            "minimum_persistence_intervals": (
                perturbation.TARGET_MINIMUM_PERSISTENCE_INTERVALS
            ),
            "missing_sample_policy": "break_run_without_filling",
            "output": "first_persistent_downstream_departure_offset",
            "statistical_departure_is_physical_first_arrival": False,
            "statistical_departure_is_causal_release_response": False,
        },
        "blinding_protocol": {
            "source_operator_frozen_before_candidate_pool_values": True,
            "events_selected_from_tailwater_elevation_only": True,
            "known_outcome_events_excluded": True,
            "target_functional_frozen_before_new_downstream_values": True,
            "observation_requests_allowed_before_event_manifest_frozen": False,
            "event_selection_may_be_recomputed_from_target_values": False,
            "source_or_target_threshold_retuning_after_target_values": False,
        },
        "data_boundary": {
            "network_requests_allowed_during_protocol_freeze": False,
            "new_candidate_pool_values_acquired": False,
            "new_downstream_outcome_values_acquired": False,
            "private_or_workspace_data_requested": False,
            "fresh_approval_required_for_candidate_pool_acquisition": True,
            "fresh_approval_required_for_later_outcome_acquisition": True,
        },
        "claim_boundary": {
            "source_gate_and_target_functional_frozen": True,
            "hydraulic_boundary_events_selected": False,
            "observed_downstream_departures_compiled": False,
            "release_action_admitted": False,
            "release_discharge_admitted": False,
            "causal_response_admitted": False,
            "physical_first_arrival_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_transition_admitted": False,
        },
    }


def json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


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
