from __future__ import annotations

import hashlib

import pytest

from scripts import (
    freeze_geotransport_stage36_hydraulic_boundary_event_protocol as freeze,
)


def test_stage36_protocol_hash_binds_operator_probe_and_stage35():
    protocol = freeze.build_protocol()
    inputs = protocol["frozen_inputs"]

    assert protocol["schema"] == freeze.SCHEMA
    assert set(inputs) == {
        "operator",
        "development_probe",
        "stage35_ledger",
        "stage35_gates",
    }
    for key, path in (
        ("operator", freeze.OPERATOR_PATH),
        ("development_probe", freeze.DEVELOPMENT_PROBE_PATH),
        ("stage35_ledger", freeze.STAGE35_LEDGER_PATH),
        ("stage35_gates", freeze.STAGE35_GATES_PATH),
    ):
        assert inputs[key]["sha256"] == freeze.FROZEN_HASHES[path]


def test_stage36_protocol_preserves_observed_state_semantics():
    semantics = freeze.build_protocol()["source_observation_semantics"]

    assert semantics["evidence_role"] == "observed_hydraulic_boundary_state"
    assert semantics["measurement_type"] == "instantaneous_sample"
    assert semantics["source_event_time_support_offset_minutes"] == [-30, 0]
    assert semantics["quality_code_zero_interpreted_as_approved"] is False
    assert semantics["release_action_semantics"] is False
    assert semantics["release_discharge_semantics"] is False
    assert semantics["backwater_or_local_hydraulic_effects_excluded"] is False


def test_stage36_development_probe_admits_gate_without_downstream_values():
    development = freeze.build_protocol()["development_evidence"]
    report = development["operator_report"]

    assert development["marker_utc"] == "2022-12-23T19:00:00Z"
    assert development["release_values_used_by_source_gate"] is False
    assert development["downstream_outcome_values_used"] is False
    assert report["signed_primary_change_m"] == pytest.approx(0.329184)
    assert report["excursion_support_intervals"] == 24
    assert report["blind_target_test_admissible"] is True


def test_stage36_selection_excludes_all_previously_observed_events():
    selection = freeze.build_protocol()["predeclared_event_selection"]

    assert selection["event_count"] == 4
    assert selection["minimum_event_separation_days"] == 180
    assert selection["prior_outcome_exclusion_radius_days"] == 14
    assert selection["development_probe_exclusion_radius_days"] == 90
    assert selection["prior_outcome_event_times_utc"] == list(
        freeze.PRIOR_OUTCOME_EVENT_TIMES_UTC
    )
    assert len(selection["prior_outcome_event_times_utc"]) == 15
    assert selection["selection_data"] == (
        "cwms_tailwater_elevation_values_only"
    )
    assert selection["release_values_available_to_selector"] is False
    assert selection["downstream_values_available_to_selector"] is False


def test_stage36_target_functional_is_frozen_before_new_outcomes():
    protocol = freeze.build_protocol()
    target = protocol["predeclared_target_functional"]
    blinding = protocol["blinding_protocol"]

    assert target["baseline_support_offsets_hours"] == [-24.0, -6.5]
    assert target["search_offsets_minutes"] == [30, 720]
    assert target["minimum_persistence_intervals"] == 3
    assert target["missing_sample_policy"] == "break_run_without_filling"
    assert target["statistical_departure_is_physical_first_arrival"] is False
    assert blinding["target_functional_frozen_before_new_downstream_values"]
    assert blinding["event_selection_may_be_recomputed_from_target_values"] is False
    assert blinding[
        "source_or_target_threshold_retuning_after_target_values"
    ] is False


def test_stage36_protocol_freeze_is_no_network_and_claims_nothing_observed():
    protocol = freeze.build_protocol()
    boundary = protocol["data_boundary"]
    claims = protocol["claim_boundary"]

    assert boundary["network_requests_allowed_during_protocol_freeze"] is False
    assert boundary["new_candidate_pool_values_acquired"] is False
    assert boundary["new_downstream_outcome_values_acquired"] is False
    assert boundary["fresh_approval_required_for_candidate_pool_acquisition"]
    assert claims["source_gate_and_target_functional_frozen"] is True
    assert claims["hydraulic_boundary_events_selected"] is False
    assert claims["physical_travel_time_admitted"] is False
    assert claims["runtime_transition_admitted"] is False


def test_stage36_protocol_serialization_is_deterministic():
    first = freeze.json_bytes(freeze.build_protocol())
    second = freeze.json_bytes(freeze.build_protocol())

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"generated_at" not in first


def test_stage36_frozen_artifact_drift_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "operator.py"
    path.write_text("drift\n", encoding="utf-8")
    relative = "operator.py"
    monkeypatch.setattr(freeze, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(freeze, "FROZEN_HASHES", {relative: "0" * 64})

    with pytest.raises(ValueError, match="stage36_frozen_artifact_drift"):
        freeze.artifact_record(relative)
