#!/usr/bin/env python3
"""Freeze the no-network Stage 35 event-time uncertainty protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage35_center_hill_event_time_uncertainty/"
    "protocol.json"
)
SCHEMA = "gwm.geotransport.stage35_event_time_uncertainty_protocol.v1"
OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/event_time_uncertainty.py"
)
STAGE34_LEDGER_PATH = (
    "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
    "temporal_response_semantics_ledger.json"
)
STAGE34_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage34_temporal_semantics_gates.json"
)
FROZEN_HASHES = {
    OPERATOR_PATH: (
        "660d596341eea9a54c96332834e58d1418953cc4838589ac4826aba35ce4600d"
    ),
    STAGE34_LEDGER_PATH: (
        "45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c"
    ),
    STAGE34_GATES_PATH: (
        "482024d6517f1da7a4f5cd4ee793515e97d7eb39269db03a343f90c3c273fba7"
    ),
}


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
        raise ValueError(f"stage35_frozen_artifact_drift:{relative_path}")
    return {
        "path": relative_path,
        "sha256": actual,
        "size_bytes": len(body),
    }


def build_protocol() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-event-time-uncertainty-v1",
        "frozen_inputs": {
            "operator": artifact_record(OPERATOR_PATH),
            "stage34_ledger": artifact_record(STAGE34_LEDGER_PATH),
            "stage34_gates": artifact_record(STAGE34_GATES_PATH),
        },
        "observation_support_model": {
            "source_duration_hours": 1.0,
            "target_duration_hours": 1.0,
            "source_timestamp_position": "end",
            "target_timestamp_position": "end",
            "source_event_offset_hours": [-1.0, 0.0],
            "target_event_offset_hours": [-1.0, 0.0],
            "conservative_closure_used": True,
            "closure_note": (
                "open-left observation supports are closed conservatively; "
                "this may retain boundary values but cannot create a physical "
                "event-time claim"
            ),
        },
        "frozen_dilation": {
            "delay_lower_formula": (
                "max(0,label_shift-target_duration)"
            ),
            "delay_upper_formula": "label_shift+source_duration",
            "single_lag_example": {
                "label_shift_hours": 5,
                "relative_delay_interval_hours": [4.0, 6.0],
            },
            "merge_overlapping_closed_intervals": True,
            "preserve_disconnected_interval_components": True,
            "empty_support_remains_empty": True,
        },
        "frozen_empirical_support": {
            "relation_id": "center-hill-tailwater-to-stonewall",
            "path_id": "center-hill-tailwater-to-stonewall-path",
            "events": [
                {
                    "event_id": "release_step_20220202T1900Z",
                    "selection_rank": 1,
                    "label_shift_set_hours": [5, 6, 7],
                    "expected_relative_delay_envelope_hours": [[4.0, 8.0]],
                },
                {
                    "event_id": "release_step_20220919T1500Z",
                    "selection_rank": 2,
                    "label_shift_set_hours": [6, 7],
                    "expected_relative_delay_envelope_hours": [[5.0, 8.0]],
                },
                {
                    "event_id": "release_step_20230911T1500Z",
                    "selection_rank": 3,
                    "label_shift_set_hours": [7],
                    "expected_relative_delay_envelope_hours": [[6.0, 8.0]],
                },
                {
                    "event_id": "release_step_20210625T1600Z",
                    "selection_rank": 4,
                    "label_shift_set_hours": [],
                    "expected_relative_delay_envelope_hours": [],
                },
            ],
            "union_label_shift_set_hours": [5, 6, 7],
            "expected_union_delay_envelope_hours": [[4.0, 8.0]],
            "all_event_common_empirical_support_admitted": False,
        },
        "data_boundary": {
            "network_requests_allowed": False,
            "new_public_data_acquired": False,
            "private_or_workspace_data_requested": False,
            "release_or_downstream_outcome_values_requested": False,
            "post_stage34_calibration_allowed": False,
            "only_hash_bound_prior_artifacts_allowed": True,
        },
        "claim_boundary": {
            "event_time_uncertainty_propagation_may_be_admitted": True,
            "uncertainty_envelope_is_physical_delay": False,
            "numerical_overlap_overrides_process_semantics": False,
            "physical_response_time_may_be_admitted": False,
            "runtime_transition_may_be_admitted": False,
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
