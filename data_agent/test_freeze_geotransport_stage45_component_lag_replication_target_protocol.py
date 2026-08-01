from __future__ import annotations

import hashlib

from scripts import (
    freeze_geotransport_stage45_component_lag_replication_target_protocol as freeze,
)


def test_stage45_protocol_binds_complete_stage44_checkpoint_and_target_operator():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert len(inputs) == 6
    assert all(len(value["sha256"]) == 64 for value in inputs.values())
    assert (
        inputs["stage44_replication_gates"]["sha256"]
        == (freeze.FROZEN_HASHES[freeze.STAGE44_GATES_PATH])
    )


def test_stage45_protocol_derives_four_exact_84_hour_target_windows():
    events = freeze.build_protocol()["frozen_events"]

    assert tuple(value["event_id"] for value in events) == freeze.EXPECTED_EVENT_IDS
    assert (
        tuple((value["target_begin_utc"], value["target_end_utc"]) for value in events)
        == freeze.EXPECTED_TARGET_WINDOWS_UTC
    )
    assert all(value["selected_without_target_values"] is True for value in events)


def test_stage45_protocol_requests_only_replication_outcome_site():
    protocol = freeze.build_protocol()
    target = protocol["target_source"]

    assert target == {
        "site_id": "USGS-03424860",
        "site_role": "downstream_replication_outcome",
        "parameter_code": "00060",
        "quantity": "continuous_discharge",
    }
    assert (
        protocol["target_observation_contract"]["expected_ideal_inclusive_half_hour_positions"]
        == 169
    )


def test_stage45_protocol_preserves_strict_replication_hypothesis():
    hypothesis = freeze.build_protocol()["strict_replication_hypothesis"]

    assert hypothesis["high_flow_required_supported_lag_hours"] == 5
    assert hypothesis["low_flow_required_supported_lag_hours"] == 6
    assert hypothesis["directions_required_within_each_flow_class"] == [
        "increase",
        "decrease",
    ]
    assert hypothesis["event_reselection_after_values_allowed"] is False


def test_stage45_protocol_freeze_has_no_network_authority_or_values():
    protocol = freeze.build_protocol()
    boundary = protocol["data_boundary"]
    claims = protocol["claim_boundary"]

    assert boundary["network_requests_allowed_during_protocol_freeze"] is False
    assert boundary["network_request_count"] == 0
    assert boundary["target_request_plan_frozen"] is False
    assert claims["target_values_acquired"] is False
    assert claims["stage43_pattern_replicated"] is False
    assert claims["runtime_operator_admitted"] is False


def test_stage45_frozen_protocol_artifact_is_reproducible():
    body = freeze.DEFAULT_OUTPUT.read_bytes()

    assert body == freeze.json_bytes(freeze.build_protocol())
    assert len(hashlib.sha256(body).hexdigest()) == 64
