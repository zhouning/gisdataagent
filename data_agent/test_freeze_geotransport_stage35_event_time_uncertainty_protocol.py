from __future__ import annotations

import hashlib

import pytest

from scripts import (
    freeze_geotransport_stage35_event_time_uncertainty_protocol as freeze,
)


def test_stage35_protocol_freezes_operator_and_stage34_artifacts():
    protocol = freeze.build_protocol()
    inputs = protocol["frozen_inputs"]

    assert protocol["schema"] == freeze.SCHEMA
    assert inputs["operator"]["sha256"] == freeze.FROZEN_HASHES[
        freeze.OPERATOR_PATH
    ]
    assert inputs["stage34_ledger"]["sha256"] == freeze.FROZEN_HASHES[
        freeze.STAGE34_LEDGER_PATH
    ]
    assert inputs["stage34_gates"]["sha256"] == freeze.FROZEN_HASHES[
        freeze.STAGE34_GATES_PATH
    ]


def test_stage35_protocol_freezes_exact_dilation_and_conservative_closure():
    protocol = freeze.build_protocol()
    support = protocol["observation_support_model"]
    dilation = protocol["frozen_dilation"]

    assert support["source_event_offset_hours"] == [-1.0, 0.0]
    assert support["target_event_offset_hours"] == [-1.0, 0.0]
    assert support["conservative_closure_used"] is True
    assert dilation["delay_lower_formula"] == (
        "max(0,label_shift-target_duration)"
    )
    assert dilation["delay_upper_formula"] == (
        "label_shift+source_duration"
    )
    assert dilation["preserve_disconnected_interval_components"] is True
    assert dilation["empty_support_remains_empty"] is True


def test_stage35_protocol_preserves_all_four_events_including_empty_event():
    empirical = freeze.build_protocol()["frozen_empirical_support"]
    events = empirical["events"]

    assert [value["event_id"] for value in events] == [
        "release_step_20220202T1900Z",
        "release_step_20220919T1500Z",
        "release_step_20230911T1500Z",
        "release_step_20210625T1600Z",
    ]
    assert [value["selection_rank"] for value in events] == [1, 2, 3, 4]
    assert [value["label_shift_set_hours"] for value in events] == [
        [5, 6, 7],
        [6, 7],
        [7],
        [],
    ]
    assert [
        value["expected_relative_delay_envelope_hours"] for value in events
    ] == [
        [[4.0, 8.0]],
        [[5.0, 8.0]],
        [[6.0, 8.0]],
        [],
    ]
    assert empirical["all_event_common_empirical_support_admitted"] is False


def test_stage35_protocol_forbids_new_data_and_physical_promotion():
    protocol = freeze.build_protocol()
    boundary = protocol["data_boundary"]
    claims = protocol["claim_boundary"]

    assert boundary == {
        "network_requests_allowed": False,
        "new_public_data_acquired": False,
        "private_or_workspace_data_requested": False,
        "release_or_downstream_outcome_values_requested": False,
        "post_stage34_calibration_allowed": False,
        "only_hash_bound_prior_artifacts_allowed": True,
    }
    assert claims["uncertainty_envelope_is_physical_delay"] is False
    assert claims["physical_response_time_may_be_admitted"] is False
    assert claims["runtime_transition_may_be_admitted"] is False


def test_stage35_protocol_serialization_is_deterministic(tmp_path):
    first = freeze.json_bytes(freeze.build_protocol())
    second = freeze.json_bytes(freeze.build_protocol())

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"generated_at" not in first


def test_stage35_frozen_artifact_drift_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "operator.py"
    path.write_text("drift\n", encoding="utf-8")
    relative = "operator.py"
    monkeypatch.setattr(freeze, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        freeze,
        "FROZEN_HASHES",
        {relative: "0" * 64},
    )

    with pytest.raises(ValueError, match="stage35_frozen_artifact_drift"):
        freeze.artifact_record(relative)
