from __future__ import annotations

from scripts import (
    freeze_geotransport_stage44_component_lag_replication_protocol as freeze,
)


def test_stage44_protocol_binds_inventory_source_stage30_and_stage43():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert len(inputs) == 10
    assert all(len(value["sha256"]) == 64 for value in inputs.values())
    assert (
        inputs["stage30_historical_falsification"]["sha256"]
        == (freeze.FROZEN_HASHES[freeze.STAGE30_LEDGER_PATH])
    )


def test_stage44_protocol_uses_complete_exposure_inventory_before_selection():
    boundary = freeze.build_protocol()["target_exposure_boundary"]

    assert boundary["source_artifact_count"] == 15
    assert boundary["exposure_record_count"] == 34
    assert boundary["merged_interval_count"] == 27
    assert boundary["exclusion_radius_days"] == 30
    assert boundary["candidate_window_must_not_overlap_expanded_interval"] is True


def test_stage44_protocol_freezes_strict_flow_class_replication_hypothesis():
    protocol = freeze.build_protocol()
    hypothesis = protocol["strict_replication_hypothesis"]

    assert hypothesis["high_flow_required_supported_lag_hours"] == 5
    assert hypothesis["low_flow_required_supported_lag_hours"] == 6
    assert hypothesis["directions_required_within_each_flow_class"] == [
        "increase",
        "decrease",
    ]
    assert hypothesis["partial_direction_or_flow_class_pass_allowed"] is False
    assert protocol["decision_rule"]["future_pass_does_not_overturn_stage30_falsification"] is True


def test_stage44_protocol_forbids_target_plan_and_requests():
    protocol = freeze.build_protocol()
    later = protocol["later_target_protocol_boundary"]

    assert later["target_request_plan_created_in_stage44"] is False
    assert later["target_values_acquired_in_stage44"] is False
    assert later["fresh_user_approval_required_after_plan_freeze"] is True
    assert protocol["data_boundary"]["network_request_count"] == 0
