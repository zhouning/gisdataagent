from __future__ import annotations

import hashlib

from scripts import (
    freeze_geotransport_stage47_component_lag_replication_execution_protocol as freeze,
)


def test_stage47_protocol_binds_executor_tests_and_all_upstream_checkpoints():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert len(inputs) == 20
    assert all(len(value["sha256"]) == 64 for value in inputs.values())
    assert (
        inputs[freeze.EVIDENCE_OPERATOR_PATH]["sha256"]
        == (freeze.FROZEN_HASHES[freeze.EVIDENCE_OPERATOR_PATH])
    )


def test_stage47_protocol_requires_exact_fixed_input_and_output_roots():
    contract = freeze.build_protocol()["execution_contract"]

    assert contract["source_root"] == freeze.evidence.STAGE45_ROOT
    assert contract["output_root"] == freeze.evidence.STAGE47_ROOT
    assert contract["explicit_execution_flag"] == "--execute-frozen-assessment"
    assert contract["source_root_override_allowed"] is False
    assert contract["output_root_override_allowed"] is False


def test_stage47_protocol_freezes_four_artifact_manifest_checkpoint():
    checkpoint = freeze.build_protocol()["post_acquisition_checkpoint_contract"]

    assert checkpoint["logical_request_count"] == 4
    assert checkpoint["artifact_count"] == 4
    assert checkpoint["minimum_attempt_count"] == 4
    assert checkpoint["maximum_attempt_count"] == 12
    assert checkpoint["maximum_download_bytes"] == 8_000_000
    assert checkpoint["missing_or_drifted_artifact_policy"] == "reject"


def test_stage47_protocol_freezes_source_and_target_time_alignment():
    protocol = freeze.build_protocol()
    source = protocol["source_compilation_contract"]
    target = protocol["target_compilation_contract"]

    assert source["event_value_count"] == 72
    assert source["source_offsets_from_window_start_hours"] == list(range(1, 73))
    assert target["requested_elapsed_hours"] == 84
    assert target["hourly_sample_offsets_minutes"] == [-30, 0]
    assert "without_shifting_time_axis" in target["missing_hour_lag_behavior"]


def test_stage47_protocol_freezes_lag_pairing_and_all_four_decision():
    protocol = freeze.build_protocol()
    lag = protocol["lag_compilation_contract"]
    cohort = protocol["cohort_decision_contract"]

    assert lag["lag_candidates_hours"] == list(range(13))
    assert lag["minimum_pair_count"] == 60
    assert cohort["required_lag_by_flow_class_hours"] == {"high": 5, "low": 6}
    assert cohort["support_membership_not_exact_best_lag_equality"] is True
    assert cohort["partial_direction_or_flow_class_pass_allowed"] is False


def test_stage47_protocol_has_no_assessment_network_capability():
    protocol = freeze.build_protocol()
    execution = protocol["execution_contract"]
    data = protocol["data_boundary"]

    assert execution["network_request_capability_in_assessment_runner"] is False
    assert execution["stage45_acquirer_imported_for_payload_validation_only"] is True
    assert execution["stage45_acquisition_function_called"] is False
    assert data["protocol_freeze_network_request_count"] == 0
    assert data["stage47_assessment_executed"] is False


def test_stage47_protocol_is_pending_and_exactly_reproducible():
    protocol = freeze.build_protocol()
    claims = protocol["claim_boundary"]
    body = freeze.DEFAULT_OUTPUT.read_bytes()

    assert claims["execution_protocol_frozen_before_target_values"] is True
    assert claims["target_values_acquired"] is False
    assert claims["replication_test_executed"] is False
    assert claims["cohort_replication_admitted"] is False
    assert body == freeze.json_bytes(protocol)
    assert len(hashlib.sha256(body).hexdigest()) == 64
