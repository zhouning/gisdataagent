#!/usr/bin/env python3
"""Freeze the no-network Stage 47 replication execution protocol."""

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
from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    empirical_lag_support,
)
from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    public_component_lag_replication_evidence as evidence,
)
from scripts import (  # noqa: E402
    assess_geotransport_stage47_component_lag_replication as runner,
)

STAGE47_ROOT = evidence.STAGE47_ROOT
DEFAULT_OUTPUT = REPO_ROOT / STAGE47_ROOT / "execution_protocol.json"
SCHEMA = "gwm.geotransport.stage47_component_lag_replication_execution_protocol.v1"
EVIDENCE_OPERATOR_PATH = (
    "data_agent/uwm/geospatial_kernel_v2/public_component_lag_replication_evidence.py"
)
EVIDENCE_OPERATOR_TEST_PATH = (
    "data_agent/test_geospatial_kernel_public_component_lag_replication_evidence.py"
)
ASSESSMENT_RUNNER_PATH = "scripts/assess_geotransport_stage47_component_lag_replication.py"
FROZEN_HASHES = {
    **evidence.EXPECTED_CHECKPOINT_SHA256,
    EVIDENCE_OPERATOR_PATH: ("63ca89193e5159827ddf2e7be9774ed31f683ead4c98236ebc44938a964b57c9"),
    EVIDENCE_OPERATOR_TEST_PATH: (
        "effb302d1284c15ff74c44f0828526bbaffb6a917110d91e00fd0e38f76fb83c"
    ),
    ASSESSMENT_RUNNER_PATH: ("86ddff4b08c51a0ae020e936dd4899c4f093be7973c34b2c15a1f615b5ebb099"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_protocol() -> dict[str, Any]:
    stage46_protocol = _read_json(REPO_ROOT / evidence.STAGE46_PROTOCOL_PATH)
    stage46_gates = _read_json(REPO_ROOT / evidence.STAGE46_GATES_PATH)
    stage45_root = REPO_ROOT / evidence.STAGE45_ROOT
    if (
        stage46_protocol != evidence.stage46.build_protocol()
        or stage46_gates.get("all_gates_passed") is not True
        or len(stage46_gates.get("gates", {})) != 46
        or (stage45_root / evidence.acquire.STATE_NAME).exists()
        or (stage45_root / evidence.acquire.MANIFEST_NAME).exists()
        or (stage45_root / "raw").exists()
    ):
        raise ValueError("stage47_pre_target_freeze_checkpoint_invalid")
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-lag-replication-execution-v1",
        "frozen_inputs": {path: artifact_record(path) for path in FROZEN_HASHES},
        "execution_contract": {
            "source_root": evidence.STAGE45_ROOT,
            "required_source_files": [
                "protocol.json",
                "target_acquisition_plan.json",
                evidence.acquire.STATE_NAME,
                evidence.acquire.MANIFEST_NAME,
            ],
            "required_raw_output_names": [
                value["output_name"] for value in evidence.planner.compile_plan()["sources"]
            ],
            "output_root": STAGE47_ROOT,
            "output_name": runner.LEDGER_NAME,
            "explicit_execution_flag": "--execute-frozen-assessment",
            "execution_flag_required": True,
            "source_root_override_allowed": False,
            "output_root_override_allowed": False,
            "network_request_capability_in_assessment_runner": False,
            "stage45_acquirer_imported_for_payload_validation_only": True,
            "stage45_acquisition_function_called": False,
        },
        "post_acquisition_checkpoint_contract": {
            "manifest_schema": evidence.acquire.SCHEMA,
            "manifest_status": ("stage45_replication_target_values_acquired_assessment_pending"),
            "state_schema": evidence.acquire.STATE_SCHEMA,
            "frozen_plan_sha256": evidence.acquire.FROZEN_PLAN_SHA256,
            "logical_request_count": 4,
            "artifact_count": 4,
            "minimum_attempt_count": 4,
            "maximum_attempt_count": 12,
            "maximum_download_bytes": 8_000_000,
            "manifest_source_order_must_match_plan": True,
            "state_source_order_must_match_plan": True,
            "raw_path_hash_size_and_request_metadata_must_match": True,
            "tls_hostname_verification_must_be_retained": True,
            "payload_must_pass_stage45_frozen_validation": True,
            "missing_or_drifted_artifact_policy": "reject",
        },
        "source_compilation_contract": {
            "components": ["orifice", "sluice", "spillway", "turbine"],
            "timestamp_join": "exact_utc_hour",
            "event_value_count": 72,
            "source_offsets_from_window_start_hours": list(range(1, 73)),
            "formula": "orifice_plus_sluice_plus_spillway_plus_turbine",
            "missing_null_nonfinite_or_negative_component_policy": "reject",
            "quality_codes_preserved_per_component_hour": True,
            "quality_codes_are_scientific_approval": False,
        },
        "target_compilation_contract": {
            "site_id": "USGS-03424860",
            "parameter_code": "00060",
            "statistic_id": "00011",
            "raw_unit": "ft^3/s",
            "compiled_unit": "m3/s",
            "requested_elapsed_hours": 84,
            "hourly_support": "open_closed",
            "hourly_sample_offsets_minutes": [-30, 0],
            "hourly_aggregation": "mean_then_convert_cfs_to_m3s",
            "missing_sample_or_hour_policy": "drop_without_filling",
            "missing_hour_lag_behavior": (
                "remove_only_exact_timestamp_pair_without_shifting_time_axis"
            ),
            "quality_metadata_preserved": True,
            "quality_metadata_is_scientific_approval": False,
        },
        "lag_compilation_contract": {
            "operator_schema": empirical_lag_support.SCHEMA,
            "lag_candidates_hours": list(empirical_lag_support.LAG_CANDIDATES_HOURS),
            "pairing": "source_hour_end_plus_lag_equals_target_hour_end",
            "minimum_pearson_r": empirical_lag_support.MINIMUM_PEARSON_R,
            "maximum_best_loss_pearson_r": (empirical_lag_support.MAXIMUM_BEST_LOSS_PEARSON_R),
            "minimum_pair_count": empirical_lag_support.MINIMUM_PAIR_COUNT,
            "best_lag_must_be_interior": True,
        },
        "cohort_decision_contract": {
            "operator_schema": assessment.SCHEMA,
            "event_ids": list(evidence.stage45.EXPECTED_EVENT_IDS),
            "required_strata": list(assessment.EXPECTED_STRATA),
            "required_lag_by_flow_class_hours": (assessment.REQUIRED_LAG_BY_FLOW_CLASS),
            "support_membership_not_exact_best_lag_equality": True,
            "detectable_response_required_for_every_event": True,
            "partial_direction_or_flow_class_pass_allowed": False,
            "all_four_events_required": True,
            "admitted_scope_on_pass": (
                "center_hill_component_total_flow_class_cohort_replication_only"
            ),
        },
        "data_boundary": {
            "protocol_freeze_network_request_count": 0,
            "stage45_target_state_present": False,
            "stage45_target_manifest_present": False,
            "stage45_raw_target_directory_present": False,
            "stage47_assessment_executed": False,
            "stage47_evidence_ledger_present": False,
        },
        "claim_boundary": {
            "execution_protocol_frozen_before_target_values": True,
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
        raise ValueError(f"stage47_frozen_artifact_drift:{relative_path}")
    return {"path": relative_path, "sha256": sha256, "size_bytes": len(body)}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage47_json_object_required")
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
    print("assessment_executed=false")
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
