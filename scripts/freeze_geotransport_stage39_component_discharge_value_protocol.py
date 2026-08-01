#!/usr/bin/env python3
"""Freeze the no-network Stage 39 component-discharge value protocol."""

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

STAGE39_ROOT = "data/geotransport_v0_1/stage39_center_hill_component_discharge_value_protocol"
DEFAULT_OUTPUT = REPO_ROOT / STAGE39_ROOT / "protocol.json"
SCHEMA = "gwm.geotransport.stage39_component_discharge_value_protocol.v1"
STAGE34_LEDGER_PATH = (
    "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
    "temporal_response_semantics_ledger.json"
)
STAGE34_GATES_PATH = "benchmarks/geotransport_v0_1/stage34_temporal_semantics_gates.json"
STAGE38_LEDGER_PATH = (
    "data/geotransport_v0_1/"
    "stage38_center_hill_cwms_component_discharge_catalog/"
    "cwms_component_discharge_catalog_ledger.json"
)
STAGE38_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage38_cwms_component_discharge_catalog_gates.json"
)
FROZEN_HASHES = {
    STAGE34_LEDGER_PATH: ("45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c"),
    STAGE34_GATES_PATH: ("482024d6517f1da7a4f5cd4ee793515e97d7eb39269db03a343f90c3c273fba7"),
    STAGE38_LEDGER_PATH: ("1cbd80d6ffde6c142dbf2f364475c6b94713b93d8f6de348d8bfecb40e4af7b4"),
    STAGE38_GATES_PATH: ("0eeab2e425200a0698041acdb64ae91bc4233c6c657b55817fc7b303862ea021"),
}
COMPONENT_ORDER = ("orifice", "sluice", "spillway", "turbine")
BEGIN_UTC = "2021-01-01T00:00:00Z"
END_UTC = "2026-01-01T00:00:00Z"
YEAR_WINDOWS = tuple(
    (
        f"{year}-01-01T00:00:00Z",
        f"{year + 1}-01-01T00:00:00Z",
    )
    for year in range(2021, 2026)
)
EXPECTED_UNIQUE_HOURLY_POSITIONS_PER_COMPONENT = 43_825
EXPECTED_COMBINED_COMPONENT_POSITIONS = 175_300


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
        raise ValueError(f"stage39_frozen_artifact_drift:{relative_path}")
    return {
        "path": relative_path,
        "sha256": actual,
        "size_bytes": len(body),
    }


def build_protocol() -> dict[str, Any]:
    stage34 = _validated_stage34_ledger()
    stage38 = _validated_stage38_ledger()
    identities = stage38["catalog_evidence"]["components"]
    return {
        "schema": SCHEMA,
        "protocol_id": "center-hill-component-discharge-values-v1",
        "frozen_inputs": {
            "stage34_temporal_semantics_ledger": artifact_record(STAGE34_LEDGER_PATH),
            "stage34_temporal_semantics_gates": artifact_record(STAGE34_GATES_PATH),
            "stage38_catalog_ledger": artifact_record(STAGE38_LEDGER_PATH),
            "stage38_catalog_gates": artifact_record(STAGE38_GATES_PATH),
        },
        "admitted_source_identities": [
            {
                "component": value["component"],
                "series_id": value["series_id"],
                "display_alias": value["display_alias"],
                "office": value["office"],
                "unit": value["units"],
                "catalog_interval": value["interval"],
                "catalog_time_zone": value["time_zone"],
                "evidence_role": "observed_component_discharge_boundary_flux",
            }
            for value in identities
        ],
        "source_observation_semantics": {
            "quantity": "component_discharge",
            "measurement_statistic": "one_hour_interval_average",
            "cwms_composite_default_timestamp_position": stage34["document_findings"][
                "composite_default_timestamp_position"
            ],
            "cwms_storage_time_basis": stage34["document_findings"]["cwms_storage_time_basis"],
            "source_time_support_offsets_minutes": [-60, 0],
            "source_marker_is_release_actuation_instant": False,
            "component_value_is_gate_command": False,
            "component_value_is_human_action": False,
            "component_value_is_causal_intervention": False,
        },
        "frozen_value_window": {
            "begin_utc": BEGIN_UTC,
            "end_utc": END_UTC,
            "annual_windows": [list(value) for value in YEAR_WINDOWS],
            "sample_interval_minutes": 60,
            "expected_unique_inclusive_positions_per_component": (
                EXPECTED_UNIQUE_HOURLY_POSITIONS_PER_COMPONENT
            ),
            "expected_combined_component_positions": (EXPECTED_COMBINED_COMPONENT_POSITIONS),
            "annual_windows_share_boundary_samples": True,
            "duplicate_boundary_policy": "require_identical_then_keep_one",
        },
        "value_shape_contract": {
            "required_payload_name_matches_requested_series": True,
            "required_office_id": "LRN",
            "required_units": "cms",
            "required_interval": "PT1H",
            "value_row_shape": ["epoch_milliseconds", "value", "quality_code"],
            "explicit_null_values_preserved": True,
            "missing_values_filled": False,
            "quality_codes_preserved_without_approval_interpretation": True,
            "timestamps_normalized_to_utc": True,
            "out_of_window_values_rejected": True,
        },
        "synchronized_total_discharge_eligibility": {
            "formula": "orifice+sluice+spillway+turbine",
            "all_four_component_values_required_at_same_hour": True,
            "partial_component_sum_allowed": False,
            "missing_component_imputation_allowed": False,
            "negative_component_value_allowed": False,
            "total_discharge_values_compiled_during_stage39": False,
        },
        "post_acquisition_assessment_boundary": {
            "raw_hash_and_request_provenance_audit_allowed": True,
            "per_component_time_coverage_audit_allowed": True,
            "duplicate_boundary_audit_allowed": True,
            "quality_code_inventory_allowed": True,
            "simultaneous_four_component_support_audit_allowed": True,
            "event_selection_allowed": False,
            "downstream_outcome_request_allowed": False,
            "source_or_target_threshold_definition_allowed": False,
            "model_fitting_or_scoring_allowed": False,
        },
        "blinding_protocol": {
            "component_values_are_source_only": True,
            "no_downstream_values_enter_stage39": True,
            "known_outcome_windows_do_not_define_value_requests": True,
            "event_selector_must_be_frozen_after_source_audit_and_before_new_outcomes": True,
            "target_functional_must_be_frozen_before_new_outcomes": True,
        },
        "data_boundary": {
            "network_requests_allowed_during_protocol_freeze": False,
            "component_values_acquired": False,
            "downstream_outcome_values_acquired": False,
            "workspace_or_private_data_requested": False,
            "fresh_approval_required_for_component_value_acquisition": True,
            "fresh_approval_required_for_later_outcome_acquisition": True,
        },
        "claim_boundary": {
            "stage38_source_identity_checkpoint_preserved": True,
            "component_value_protocol_frozen": True,
            "component_values_acquired": False,
            "coverage_or_quality_support_admitted": False,
            "synchronized_total_discharge_admitted": False,
            "component_discharge_event_admitted": False,
            "gate_command_admitted": False,
            "human_action_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _validated_stage34_ledger() -> dict[str, Any]:
    value = _read_json(REPO_ROOT / STAGE34_LEDGER_PATH)
    gates = _read_json(REPO_ROOT / STAGE34_GATES_PATH)
    findings = value.get("document_findings")
    decision = value.get("decision")
    if (
        not isinstance(findings, dict)
        or findings.get("composite_default_timestamp_position") != "end"
        or findings.get("one_hour_duration_is_composite_window_seconds") != 3600
        or findings.get("cwms_storage_time_basis") != "UTC"
        or not isinstance(decision, dict)
        or decision.get("public_temporal_semantics_evidence_admitted") is not True
        or decision.get("release_actuation_instant_admitted") is not False
        or gates.get("all_gates_passed") is not True
        or gates.get("status")
        != "interval_label_shift_admitted_physical_response_semantics_rejected"
        or len(gates.get("gates", {})) != 34
    ):
        raise ValueError("stage39_stage34_temporal_semantics_invalid")
    return value


def _validated_stage38_ledger() -> dict[str, Any]:
    value = _read_json(REPO_ROOT / STAGE38_LEDGER_PATH)
    gates = _read_json(REPO_ROOT / STAGE38_GATES_PATH)
    catalog_evidence = value.get("catalog_evidence")
    decision = value.get("decision")
    if not isinstance(catalog_evidence, dict):
        raise ValueError("stage39_stage38_catalog_evidence_invalid")
    components = catalog_evidence.get("components")
    if (
        not isinstance(components, list)
        or [item.get("component") for item in components] != list(COMPONENT_ORDER)
        or not isinstance(decision, dict)
        or decision.get("component_discharge_source_identity_count") != 4
        or decision.get("component_discharge_source_identities_admitted") is not True
        or decision.get("component_values_acquisition_admitted") is not False
        or gates.get("all_gates_passed") is not True
        or gates.get("status") != "stage38_cwms_component_discharge_catalog_checkpoint_admitted"
        or len(gates.get("gates", {})) != 34
    ):
        raise ValueError("stage39_stage38_catalog_checkpoint_invalid")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage39_json_object_required")
    return value


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
