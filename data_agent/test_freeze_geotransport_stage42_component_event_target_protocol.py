from __future__ import annotations

import hashlib

from scripts import (
    freeze_geotransport_stage42_component_event_target_protocol as freeze,
)


def test_stage42_protocol_binds_stage41_events_ledger_gates_and_target_operator():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert set(inputs) == {
        "stage41_event_manifest",
        "stage41_public_ledger",
        "stage41_gates",
        "target_operator",
    }
    assert all(len(value["sha256"]) == 64 for value in inputs.values())


def test_stage42_protocol_preserves_exact_four_event_order():
    events = freeze.build_protocol()["frozen_events"]

    assert tuple(value["event_id"] for value in events) == freeze.EXPECTED_EVENT_IDS
    assert [value["selection_rank"] for value in events] == [1, 2, 3, 4]
    assert [value["selection_stratum"] for value in events] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]
    assert all(value["dominant_step_component"] == "turbine" for value in events)


def test_stage42_protocol_extends_each_source_window_by_twelve_hours():
    events = freeze.build_protocol()["frozen_events"]

    assert [value["target_begin_utc"] for value in events] == [
        "2025-04-14T16:00:00Z",
        "2023-03-10T20:00:00Z",
        "2021-01-11T16:00:00Z",
        "2021-07-26T03:00:00Z",
    ]
    assert [value["target_end_utc"] for value in events] == [
        "2025-04-18T04:00:00Z",
        "2023-03-14T08:00:00Z",
        "2021-01-15T04:00:00Z",
        "2021-07-29T15:00:00Z",
    ]


def test_stage42_protocol_freezes_two_exact_public_target_sites():
    targets = freeze.build_protocol()["target_sources"]

    assert [(value["site_id"], value["site_role"]) for value in targets] == [
        ("USGS-03424860", "downstream_outcome"),
        ("USGS-03424730", "observed_graph_state"),
    ]
    assert {value["parameter_code"] for value in targets} == {"00060"}


def test_stage42_protocol_preserves_target_functional_and_claim_limits():
    protocol = freeze.build_protocol()
    target = protocol["frozen_target_functional"]
    claims = protocol["claim_boundary"]

    assert target["lag_candidates_hours"] == list(range(13))
    assert target["minimum_pearson_r"] == 0.8
    assert target["supported_lag_is_physical_travel_time"] is False
    assert claims["target_values_acquired"] is False
    assert claims["non_turbine_component_contrast_admitted"] is False
    assert claims["physical_response_time_admitted"] is False


def test_stage42_protocol_freeze_has_no_network_authority():
    boundary = freeze.build_protocol()["data_boundary"]

    assert boundary["network_requests_allowed_during_protocol_freeze"] is False
    assert boundary["new_target_values_acquired"] is False
    assert boundary["workspace_or_private_data_requested"] is False
    assert boundary["fresh_user_approval_required_for_target_requests"] is True


def test_stage42_frozen_protocol_artifact_is_reproducible():
    body = freeze.DEFAULT_OUTPUT.read_bytes()

    assert body == freeze.json_bytes(freeze.build_protocol())
    assert hashlib.sha256(body).hexdigest() == (
        "f5de9f9fb7b3f33964f2dd72490291362b5c20e9670fd65b539a36039de32fc1"
    )
