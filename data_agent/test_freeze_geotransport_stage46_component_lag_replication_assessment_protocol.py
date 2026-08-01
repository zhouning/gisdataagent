from __future__ import annotations

import hashlib

from scripts import (
    freeze_geotransport_stage46_component_lag_replication_assessment_protocol as freeze,
)


def test_stage46_protocol_binds_source_cohort_target_plan_and_both_operators():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert len(inputs) == 13
    assert all(len(value["sha256"]) == 64 for value in inputs.values())
    assert (
        inputs[freeze.ASSESSMENT_OPERATOR_PATH]["sha256"]
        == (freeze.FROZEN_HASHES[freeze.ASSESSMENT_OPERATOR_PATH])
    )


def test_stage46_protocol_freezes_exact_four_event_assessment_contracts():
    events = freeze.build_protocol()["frozen_event_contract"]

    assert tuple(value["event_id"] for value in events) == (freeze.stage45.EXPECTED_EVENT_IDS)
    assert [value["required_lag_hours"] for value in events] == [5, 5, 6, 6]
    assert [value["selection_stratum"] for value in events] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]


def test_stage46_protocol_freezes_source_and_target_compilation_without_fill():
    protocol = freeze.build_protocol()
    source = protocol["source_reconstruction_contract"]
    target = protocol["target_compilation_contract"]

    assert source["event_source_value_count"] == 72
    assert source["source_offsets_from_window_start_hours"] == list(range(1, 73))
    assert source["missing_component_value_policy"] == "reject_without_filling"
    assert target["requested_elapsed_hours"] == 84
    assert target["missing_sample_or_hour_policy"] == "drop_without_filling"


def test_stage46_protocol_freezes_support_membership_and_all_four_rule():
    contract = freeze.build_protocol()["cohort_assessment_contract"]

    assert contract["required_lag_by_flow_class_hours"] == {"high": 5, "low": 6}
    assert contract["support_membership_not_exact_hour_equality"] is True
    assert contract["partial_direction_or_flow_class_pass_allowed"] is False
    assert contract["all_four_frozen_strata_required"] is True


def test_stage46_protocol_requires_exact_future_acquisition_checkpoint():
    checkpoint = freeze.build_protocol()["required_post_acquisition_checkpoint"]

    assert checkpoint["frozen_plan_sha256"] == freeze.acquire.FROZEN_PLAN_SHA256
    assert checkpoint["required_logical_request_count"] == 4
    assert checkpoint["required_artifact_count"] == 4
    assert len(checkpoint["required_source_ids"]) == 4
    assert checkpoint["all_raw_hashes_must_match_manifest"] is True


def test_stage46_protocol_is_pending_and_has_no_network_or_target_values():
    protocol = freeze.build_protocol()
    boundary = protocol["data_boundary"]
    claims = protocol["claim_boundary"]

    assert boundary["network_code_path_present"] is False
    assert boundary["network_request_count"] == 0
    assert boundary["stage45_target_values_present"] is False
    assert claims["assessment_protocol_frozen_before_target_values"] is True
    assert claims["cohort_replication_admitted"] is False
    assert claims["stage43_pattern_replicated"] is False


def test_stage46_frozen_protocol_artifact_is_reproducible():
    body = freeze.DEFAULT_OUTPUT.read_bytes()

    assert body == freeze.json_bytes(freeze.build_protocol())
    assert len(hashlib.sha256(body).hexdigest()) == 64
