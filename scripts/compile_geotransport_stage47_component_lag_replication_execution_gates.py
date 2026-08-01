#!/usr/bin/env python3
"""Compile Stage 47 component-lag replication execution gates."""

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
from scripts import (  # noqa: E402
    freeze_geotransport_stage47_component_lag_replication_execution_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage47_component_lag_replication_execution_gates.json"
)
SCHEMA = "gwm.geotransport.stage47_component_lag_replication_execution_gates.v1"
STATUS = "stage47_component_lag_replication_executor_frozen_targets_pending"
PROTOCOL_PATH = f"{freeze.STAGE47_ROOT}/execution_protocol.json"
LOCAL_FROZEN_HASHES = {
    freeze.EVIDENCE_OPERATOR_PATH: freeze.FROZEN_HASHES[freeze.EVIDENCE_OPERATOR_PATH],
    freeze.EVIDENCE_OPERATOR_TEST_PATH: freeze.FROZEN_HASHES[freeze.EVIDENCE_OPERATOR_TEST_PATH],
    freeze.ASSESSMENT_RUNNER_PATH: freeze.FROZEN_HASHES[freeze.ASSESSMENT_RUNNER_PATH],
    (
        "scripts/freeze_geotransport_stage47_component_lag_replication_execution_protocol.py"
    ): "9bbdba9269d8023cabed58b67e0d9d7fe6b478889e958b5fdcbd4d34bdc0adcc",
    (
        "data_agent/"
        "test_freeze_geotransport_stage47_component_lag_replication_execution_protocol.py"
    ): "4890d9911b7e60c7b423ad9f54fb50b1fc8b5a0db377fe42aa4ce9dccf09ff37",
    PROTOCOL_PATH: ("8c0bc867315b43a6439ea616914bcde768d5134355f69853979aa1fdd0d61a9f"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_report() -> dict[str, Any]:
    protocol = freeze.build_protocol()
    stored_protocol = _read_json(REPO_ROOT / PROTOCOL_PATH)
    frozen = _frozen_hash_report(LOCAL_FROZEN_HASHES)
    upstream = _frozen_hash_report(evidence.EXPECTED_CHECKPOINT_SHA256)
    execution = protocol["execution_contract"]
    checkpoint = protocol["post_acquisition_checkpoint_contract"]
    source = protocol["source_compilation_contract"]
    target = protocol["target_compilation_contract"]
    lag = protocol["lag_compilation_contract"]
    cohort = protocol["cohort_decision_contract"]
    data = protocol["data_boundary"]
    claims = protocol["claim_boundary"]
    stage45_root = REPO_ROOT / evidence.STAGE45_ROOT
    stage47_root = REPO_ROOT / evidence.STAGE47_ROOT
    gates = {
        "all_six_stage47_executor_test_freeze_and_protocol_artifacts_match": (
            len(frozen) == 6 and all(value["matches"] for value in frozen.values())
        ),
        "all_seventeen_upstream_checkpoint_artifacts_match": (
            len(upstream) == 17 and all(value["matches"] for value in upstream.values())
        ),
        "stage47_execution_protocol_is_exactly_reproducible": (stored_protocol == protocol),
        "stored_protocol_hash_matches_the_frozen_digest": (
            frozen[PROTOCOL_PATH]["actual_sha256"] == LOCAL_FROZEN_HASHES[PROTOCOL_PATH]
        ),
        "execution_protocol_was_frozen_before_target_values": (
            claims["execution_protocol_frozen_before_target_values"] is True
        ),
        "stage45_state_manifest_and_raw_directory_are_absent": (
            not (stage45_root / evidence.acquire.STATE_NAME).exists()
            and not (stage45_root / evidence.acquire.MANIFEST_NAME).exists()
            and not (stage45_root / "raw").exists()
        ),
        "stage47_real_evidence_ledger_is_absent": (
            not (stage47_root / runner.LEDGER_NAME).exists()
            and data["stage47_evidence_ledger_present"] is False
        ),
        "assessment_source_root_is_exactly_stage45": (
            execution["source_root"] == evidence.STAGE45_ROOT
        ),
        "assessment_output_root_and_name_are_exact": (
            execution["output_root"] == evidence.STAGE47_ROOT
            and execution["output_name"] == runner.LEDGER_NAME
        ),
        "assessment_runner_requires_the_explicit_frozen_flag": (
            execution["execution_flag_required"] is True and _execution_flag_is_required()
        ),
        "source_and_output_root_overrides_are_forbidden": (
            execution["source_root_override_allowed"] is False
            and execution["output_root_override_allowed"] is False
        ),
        "assessment_runner_has_no_network_request_capability": (
            execution["network_request_capability_in_assessment_runner"] is False
        ),
        "stage45_acquirer_is_used_only_for_validation": (
            execution["stage45_acquirer_imported_for_payload_validation_only"] is True
            and execution["stage45_acquisition_function_called"] is False
        ),
        "required_checkpoint_files_are_exactly_named": (
            execution["required_source_files"]
            == [
                "protocol.json",
                "target_acquisition_plan.json",
                evidence.acquire.STATE_NAME,
                evidence.acquire.MANIFEST_NAME,
            ]
        ),
        "required_raw_outputs_are_the_exact_four_plan_outputs": (
            execution["required_raw_output_names"]
            == [value["output_name"] for value in evidence.planner.compile_plan()["sources"]]
        ),
        "future_manifest_schema_and_status_are_exact": (
            checkpoint["manifest_schema"] == evidence.acquire.SCHEMA
            and checkpoint["manifest_status"]
            == "stage45_replication_target_values_acquired_assessment_pending"
        ),
        "future_state_schema_and_plan_hash_are_exact": (
            checkpoint["state_schema"] == evidence.acquire.STATE_SCHEMA
            and checkpoint["frozen_plan_sha256"] == evidence.acquire.FROZEN_PLAN_SHA256
        ),
        "future_checkpoint_requires_four_requests_and_artifacts": (
            checkpoint["logical_request_count"] == 4 and checkpoint["artifact_count"] == 4
        ),
        "future_attempt_count_is_bounded_from_four_through_twelve": (
            checkpoint["minimum_attempt_count"] == 4 and checkpoint["maximum_attempt_count"] == 12
        ),
        "future_download_bytes_are_bounded_to_eight_megabytes": (
            checkpoint["maximum_download_bytes"] == 8_000_000
        ),
        "future_manifest_and_state_source_order_must_match_plan": (
            checkpoint["manifest_source_order_must_match_plan"] is True
            and checkpoint["state_source_order_must_match_plan"] is True
        ),
        "future_raw_path_hash_size_and_request_metadata_must_match": (
            checkpoint["raw_path_hash_size_and_request_metadata_must_match"] is True
        ),
        "future_tls_and_payload_validation_are_required": (
            checkpoint["tls_hostname_verification_must_be_retained"] is True
            and checkpoint["payload_must_pass_stage45_frozen_validation"] is True
        ),
        "missing_or_drifted_future_artifacts_are_rejected": (
            checkpoint["missing_or_drifted_artifact_policy"] == "reject"
        ),
        "source_components_are_exactly_the_four_frozen_outlets": (
            source["components"] == ["orifice", "sluice", "spillway", "turbine"]
        ),
        "source_join_and_total_formula_are_exact": (
            source["timestamp_join"] == "exact_utc_hour"
            and source["formula"] == "orifice_plus_sluice_plus_spillway_plus_turbine"
        ),
        "source_has_exactly_seventy_two_end_labeled_offsets": (
            source["event_value_count"] == 72
            and source["source_offsets_from_window_start_hours"] == list(range(1, 73))
        ),
        "invalid_source_component_values_are_rejected": (
            source["missing_null_nonfinite_or_negative_component_policy"] == "reject"
        ),
        "source_quality_codes_are_preserved_without_scientific_approval": (
            source["quality_codes_preserved_per_component_hour"] is True
            and source["quality_codes_are_scientific_approval"] is False
        ),
        "target_identity_parameter_statistic_and_units_are_exact": (
            target["site_id"] == "USGS-03424860"
            and target["parameter_code"] == "00060"
            and target["statistic_id"] == "00011"
            and target["raw_unit"] == "ft^3/s"
            and target["compiled_unit"] == "m3/s"
        ),
        "target_has_eighty_four_hours_and_exact_half_hour_offsets": (
            target["requested_elapsed_hours"] == 84
            and target["hourly_support"] == "open_closed"
            and target["hourly_sample_offsets_minutes"] == [-30, 0]
        ),
        "target_hourly_aggregation_is_mean_then_unit_conversion": (
            target["hourly_aggregation"] == "mean_then_convert_cfs_to_m3s"
        ),
        "missing_target_samples_or_hours_are_dropped_without_filling": (
            target["missing_sample_or_hour_policy"] == "drop_without_filling"
        ),
        "missing_target_hours_remove_only_exact_pairs_without_time_shift": (
            target["missing_hour_lag_behavior"]
            == "remove_only_exact_timestamp_pair_without_shifting_time_axis"
        ),
        "target_quality_metadata_is_preserved_without_scientific_approval": (
            target["quality_metadata_preserved"] is True
            and target["quality_metadata_is_scientific_approval"] is False
        ),
        "empirical_lag_schema_and_candidates_are_exact": (
            lag["operator_schema"] == empirical_lag_support.SCHEMA
            and lag["lag_candidates_hours"] == list(range(13))
        ),
        "lag_pairing_uses_exact_source_end_plus_lag_target_end": (
            lag["pairing"] == "source_hour_end_plus_lag_equals_target_hour_end"
        ),
        "lag_correlation_loss_and_pair_thresholds_are_exact": (
            lag["minimum_pearson_r"] == 0.8
            and lag["maximum_best_loss_pearson_r"] == 0.02
            and lag["minimum_pair_count"] == 60
        ),
        "best_lag_must_remain_interior": (lag["best_lag_must_be_interior"] is True),
        "cohort_event_ids_and_strata_are_exact": (
            tuple(cohort["event_ids"]) == evidence.stage45.EXPECTED_EVENT_IDS
            and tuple(cohort["required_strata"]) == assessment.EXPECTED_STRATA
        ),
        "flow_class_lag_mapping_is_exactly_high_five_low_six": (
            cohort["required_lag_by_flow_class_hours"] == {"high": 5, "low": 6}
        ),
        "cohort_uses_support_membership_not_exact_best_lag": (
            cohort["support_membership_not_exact_best_lag_equality"] is True
        ),
        "every_response_and_all_four_events_are_required_without_partial_pass": (
            cohort["detectable_response_required_for_every_event"] is True
            and cohort["partial_direction_or_flow_class_pass_allowed"] is False
            and cohort["all_four_events_required"] is True
        ),
        "passing_scope_is_only_center_hill_flow_class_cohort_replication": (
            cohort["admitted_scope_on_pass"]
            == "center_hill_component_total_flow_class_cohort_replication_only"
        ),
        "target_assessment_and_cohort_decisions_remain_pending": (
            claims["target_values_acquired"] is False
            and claims["replication_test_executed"] is False
            and claims["cohort_replication_admitted"] is False
            and data["stage47_assessment_executed"] is False
        ),
        "stage30_falsification_and_universal_lag_boundaries_remain": (
            claims["stage30_historical_falsification_overturned"] is False
            and claims["universal_lag_admitted"] is False
        ),
        "component_causal_physical_and_runtime_promotions_remain_rejected": (
            claims["non_turbine_component_contrast_admitted"] is False
            and claims["causal_or_physical_relation_admitted"] is False
            and claims["runtime_operator_admitted"] is False
        ),
    }
    if len(gates) != 47:
        raise ValueError(f"stage47_gate_count_invalid:{len(gates)}")
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "frozen_artifacts": frozen,
        "upstream_frozen_artifacts": upstream,
        "protocol_artifact": _artifact(REPO_ROOT / PROTOCOL_PATH),
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": {
            "component_lag_replication_evidence_compiler_frozen": True,
            "offline_assessment_runner_frozen": True,
            "execution_protocol_frozen_before_target_values": True,
            "planned_event_count": 4,
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


def _execution_flag_is_required() -> bool:
    try:
        runner._require_execution_flag(False)
    except ValueError as exc:
        return str(exc) == "stage47_explicit_frozen_assessment_flag_required"
    return False


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
        raise ValueError("stage47_json_object_required")
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
    print("assessment_executed=false")
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
