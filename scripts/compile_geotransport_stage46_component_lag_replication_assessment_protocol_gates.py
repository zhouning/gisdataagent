#!/usr/bin/env python3
"""Compile Stage 46 confirmatory assessment protocol gates."""

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
from scripts import (  # noqa: E402
    acquire_geotransport_stage45_component_lag_replication_targets as acquire,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage46_component_lag_replication_assessment_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage46_component_lag_replication_assessment_protocol_gates.json"
)
SCHEMA = "gwm.geotransport.stage46_component_lag_replication_assessment_protocol_gates.v1"
STATUS = "stage46_component_lag_replication_assessment_protocol_frozen_targets_pending"
PROTOCOL_PATH = f"{freeze.STAGE46_ROOT}/protocol.json"
STAGE45_ROOT = REPO_ROOT / freeze.stage45.STAGE45_ROOT
FROZEN_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/component_lag_replication_assessment.py"
    ): "8370ad5889ec0e39aff8a13492d63fcf50709a1d89a74d18c7674bc38f4104c3",
    (
        "data_agent/test_geospatial_kernel_component_lag_replication_assessment.py"
    ): "f18aaf7693574d10c4ce083878c6a90b82f8c3cd2a8600b4a17d9bd6585819df",
    (
        "scripts/freeze_geotransport_stage46_component_lag_replication_assessment_protocol.py"
    ): "5b2b2740506e4cc92ecce46ad0c0eca6934dd8eee4de6674afa44c026a6bf8e5",
    (
        "data_agent/"
        "test_freeze_geotransport_stage46_component_lag_replication_assessment_protocol.py"
    ): "cd142c18e15161be9f8437fdc7c3ad4b7600cc44e02eb3ffa98b9325d94fb7e3",
    PROTOCOL_PATH: "a5c976927bde7084047e29f6b20ac75806ca41457562f91f2c049bdeca793803",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_report() -> dict[str, Any]:
    protocol = freeze.build_protocol()
    stored_protocol = _read_json(REPO_ROOT / PROTOCOL_PATH)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    upstream = _frozen_hash_report(freeze.FROZEN_HASHES)
    events = protocol["frozen_event_contract"]
    source = protocol["source_reconstruction_contract"]
    target = protocol["target_compilation_contract"]
    lag = protocol["per_event_lag_support_contract"]
    cohort = protocol["cohort_assessment_contract"]
    checkpoint = protocol["required_post_acquisition_checkpoint"]
    boundary = protocol["decision_boundary"]
    data = protocol["data_boundary"]
    claims = protocol["claim_boundary"]
    stage45_plan = _read_json(REPO_ROOT / freeze.STAGE45_PLAN_PATH)
    stage45_sources = stage45_plan["sources"]
    gates = {
        "all_five_stage46_operator_test_freeze_and_protocol_artifacts_match": (
            len(frozen) == 5 and all(value["matches"] for value in frozen.values())
        ),
        "all_thirteen_frozen_upstream_inputs_match": (
            len(upstream) == 13 and all(value["matches"] for value in upstream.values())
        ),
        "stage46_protocol_is_exactly_reproducible": stored_protocol == protocol,
        "assessment_protocol_was_frozen_before_target_values": (
            claims["assessment_protocol_frozen_before_target_values"] is True
        ),
        "protocol_freeze_performed_zero_network_requests": (
            data["network_code_path_present"] is False and data["network_request_count"] == 0
        ),
        "stage45_target_raw_state_and_manifest_artifacts_are_absent": (
            not (STAGE45_ROOT / "raw").exists()
            and not (STAGE45_ROOT / acquire.STATE_NAME).exists()
            and not (STAGE45_ROOT / acquire.MANIFEST_NAME).exists()
        ),
        "exact_four_frozen_event_ids_are_preserved": (
            tuple(value["event_id"] for value in events) == freeze.stage45.EXPECTED_EVENT_IDS
        ),
        "selection_ranks_are_exactly_one_through_four": (
            [value["selection_rank"] for value in events] == [1, 2, 3, 4]
        ),
        "selection_strata_are_complete_and_in_frozen_order": (
            tuple(value["selection_stratum"] for value in events) == assessment.EXPECTED_STRATA
        ),
        "required_event_lags_are_exactly_five_five_six_six": (
            [value["required_lag_hours"] for value in events] == [5, 5, 6, 6]
        ),
        "event_target_source_ids_match_the_frozen_plan": (
            [value["target_source_id"] for value in events]
            == [value["source_id"] for value in stage45_sources]
        ),
        "event_target_windows_match_the_frozen_plan": (
            [(value["target_begin_utc"], value["target_end_utc"]) for value in events]
            == [(value["begin_utc"], value["end_utc"]) for value in stage45_sources]
        ),
        "target_identity_parameter_statistic_and_unit_are_exact": (
            target["site_id"] == "USGS-03424860"
            and target["parameter_code"] == "00060"
            and target["statistic_id"] == "00011"
            and target["raw_unit"] == "ft^3/s"
            and target["compiled_unit"] == "m3/s"
        ),
        "source_components_are_exactly_the_four_frozen_outlets": (
            source["components"] == ["orifice", "sluice", "spillway", "turbine"]
        ),
        "source_total_formula_is_frozen": (
            source["formula"] == "orifice_plus_sluice_plus_spillway_plus_turbine"
        ),
        "source_component_join_is_exact_utc_hour": (source["timestamp_join"] == "exact_utc_hour"),
        "source_reconstruction_has_exactly_seventy_two_offsets": (
            source["event_source_value_count"] == 72
            and source["source_offsets_from_window_start_hours"] == list(range(1, 73))
        ),
        "missing_source_components_fail_without_filling": (
            source["missing_component_value_policy"] == "reject_without_filling"
        ),
        "negative_source_components_are_rejected": (
            source["negative_component_value_policy"] == "reject"
        ),
        "source_quality_codes_are_preserved_without_scientific_approval": (
            source["quality_codes_preserved"] is True
            and source["quality_codes_are_scientific_approval"] is False
        ),
        "target_support_is_exactly_eighty_four_hours_and_169_positions": (
            target["requested_elapsed_hours"] == 84
            and target["maximum_inclusive_half_hour_positions"] == 169
        ),
        "target_hourly_aggregation_is_frozen": (
            target["hourly_aggregation"]
            == "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
        ),
        "missing_target_samples_or_hours_are_dropped_without_filling": (
            target["missing_sample_or_hour_policy"] == "drop_without_filling"
        ),
        "duplicate_target_timestamps_are_rejected": (
            target["duplicate_timestamp_policy"] == "reject"
        ),
        "target_quality_metadata_is_preserved_without_scientific_approval": (
            target["quality_metadata_preserved"] is True
            and target["quality_metadata_is_scientific_approval"] is False
        ),
        "empirical_lag_operator_schema_is_frozen": (
            lag["operator_schema"] == empirical_lag_support.SCHEMA
        ),
        "lag_candidates_are_exactly_zero_through_twelve_hours": (
            lag["lag_candidates_hours"] == list(range(13))
        ),
        "lag_correlation_loss_and_pair_thresholds_are_frozen": (
            lag["minimum_pearson_r"] == 0.8
            and lag["maximum_best_loss_pearson_r"] == 0.02
            and lag["minimum_pair_count"] == 60
        ),
        "best_lag_must_be_interior_and_response_detectable": (
            lag["best_lag_must_be_interior"] is True and lag["response_must_be_detectable"] is True
        ),
        "supported_empirical_lag_is_not_physical_travel_time": (
            lag["supported_lag_is_physical_travel_time"] is False
        ),
        "cohort_assessment_operator_schema_is_frozen": (
            cohort["operator_schema"] == assessment.SCHEMA
        ),
        "all_four_strata_are_required_by_the_assessment": (
            cohort["required_strata"] == list(assessment.EXPECTED_STRATA)
            and cohort["all_four_frozen_strata_required"] is True
        ),
        "flow_class_lag_mapping_is_exactly_high_five_low_six": (
            cohort["required_lag_by_flow_class_hours"] == {"high": 5, "low": 6}
        ),
        "replication_uses_support_membership_not_exact_best_lag": (
            cohort["support_membership_not_exact_hour_equality"] is True
        ),
        "partial_direction_or_flow_class_replication_is_forbidden": (
            cohort["partial_direction_or_flow_class_pass_allowed"] is False
            and boundary["partial_replication_admission_allowed"] is False
        ),
        "passing_scope_is_only_center_hill_flow_class_cohort_replication": (
            cohort["admitted_scope_on_pass"]
            == "center_hill_component_total_flow_class_cohort_replication_only"
        ),
        "future_checkpoint_binds_the_exact_stage45_plan_hash": (
            checkpoint["frozen_plan_sha256"] == acquire.FROZEN_PLAN_SHA256
        ),
        "future_checkpoint_names_exact_state_and_manifest": (
            checkpoint["acquisition_state_name"] == acquire.STATE_NAME
            and checkpoint["acquisition_manifest_name"] == acquire.MANIFEST_NAME
        ),
        "future_manifest_status_is_exactly_assessment_pending": (
            checkpoint["required_manifest_status"]
            == "stage45_replication_target_values_acquired_assessment_pending"
        ),
        "future_checkpoint_requires_four_requests_and_four_artifacts": (
            checkpoint["required_logical_request_count"] == 4
            and checkpoint["required_artifact_count"] == 4
            and len(checkpoint["required_source_ids"]) == 4
            and len(checkpoint["required_output_names"]) == 4
        ),
        "future_checkpoint_requires_plan_conformance_and_raw_hashes": (
            checkpoint["all_raw_hashes_must_match_manifest"] is True
            and checkpoint["all_requests_must_stay_within_frozen_plan"] is True
        ),
        "event_reselection_and_threshold_retuning_are_forbidden": (
            boundary["event_reselection_allowed"] is False
            and boundary["source_or_target_threshold_retuning_allowed"] is False
        ),
        "stage30_falsification_and_universal_lag_boundaries_remain": (
            boundary["stage30_falsification_overturned_on_cohort_pass"] is False
            and boundary["universal_lag_admitted_on_cohort_pass"] is False
        ),
        "component_causal_physical_and_runtime_promotions_remain_rejected": (
            boundary["non_turbine_component_contrast_admitted"] is False
            and boundary["causal_or_physical_relation_admitted"] is False
            and boundary["runtime_operator_admitted"] is False
        ),
        "target_assessment_replication_and_stage43_pattern_remain_pending": (
            claims["target_values_acquired"] is False
            and claims["replication_test_executed"] is False
            and claims["cohort_replication_admitted"] is False
            and claims["stage43_pattern_replicated"] is False
        ),
        "no_workspace_private_or_network_data_path_is_admitted": (
            data["workspace_or_private_data_requested"] is False
            and data["stage45_target_values_present"] is False
            and data["assessment_executed"] is False
        ),
    }
    if len(gates) != 46:
        raise ValueError(f"stage46_gate_count_invalid:{len(gates)}")
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "frozen_artifacts": frozen,
        "upstream_frozen_artifacts": upstream,
        "protocol_artifact": _artifact(REPO_ROOT / PROTOCOL_PATH),
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": {
            "component_lag_replication_assessment_operator_frozen": True,
            "assessment_protocol_frozen_before_target_values": True,
            "planned_event_count": 4,
            "required_high_flow_lag_hours": 5,
            "required_low_flow_lag_hours": 6,
            "target_values_acquired": False,
            "replication_test_executed": False,
            "cohort_replication_admitted": False,
            "stage43_pattern_replicated": False,
            "stage30_historical_falsification_overturned": False,
            "universal_lag_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    result = {}
    for path, digest in expected.items():
        actual = _sha256(REPO_ROOT / path)
        result[path] = {
            "expected_sha256": digest,
            "actual_sha256": actual,
            "matches": actual == digest,
        }
    return result


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage46_json_object_required")
    return value


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    print("network_requests=0")
    print("target_values=0")
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
