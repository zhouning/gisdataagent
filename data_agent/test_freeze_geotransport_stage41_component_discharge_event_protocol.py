from __future__ import annotations

import hashlib

from scripts import (
    freeze_geotransport_stage41_component_discharge_event_protocol as freeze,
)


def test_stage41_protocol_binds_stage40_and_both_frozen_operators():
    protocol = freeze.build_protocol()
    inputs = protocol["frozen_inputs"]

    assert set(inputs) == {
        "selection_operator",
        "release_excitation_operator",
        "target_operator",
        "stage40_ledger",
        "stage40_gates",
    }
    assert all(len(value["sha256"]) == 64 for value in inputs.values())


def test_stage41_protocol_freezes_exact_total_derivation():
    derivation = freeze.build_protocol()["frozen_total_derivation"]

    assert derivation["formula"] == (
        "orifice_plus_sluice_plus_spillway_plus_turbine"
    )
    assert derivation["timestamp_join"] == "exact_utc_hour"
    assert derivation["expected_unique_hour_count"] == 43_825
    assert derivation["persist_full_derived_total_series"] is False


def test_stage41_protocol_discloses_source_only_radius_sensitivity():
    diagnostic = freeze.build_protocol()["source_only_development_diagnostic"]

    assert diagnostic["stage40_source_values_available_during_protocol_design"] is True
    assert diagnostic["new_target_values_available_during_protocol_design"] is False
    assert diagnostic["eligible_total_candidate_counts_by_radius"] == {
        "14": 4_041,
        "30": 2_547,
        "90": None,
    }
    assert diagnostic["thirty_day_all_four_strata_available"] is True


def test_stage41_protocol_excludes_all_known_target_exposures():
    event_selection = freeze.build_protocol()["predeclared_event_selection"]

    assert event_selection["prior_outcome_exclusion_radius_days"] == 30
    assert event_selection["candidate_window_must_not_overlap_exclusion_interval"] is True
    assert len(event_selection["prior_outcome_event_times_utc"]) == 15
    assert len(event_selection["target_exposed_event_times_utc"]) == 4
    assert event_selection["downstream_values_available_to_selector"] is False


def test_stage41_protocol_freezes_target_before_any_new_target_request():
    protocol = freeze.build_protocol()
    target = protocol["predeclared_target_functional"]

    assert target["output_type"] == "discrete_supported_lag_set"
    assert target["minimum_pearson_r"] == 0.8
    assert target["supported_lag_is_physical_travel_time"] is False
    assert protocol["data_boundary"]["network_requests_allowed"] is False
    assert protocol["data_boundary"][
        "fresh_approval_required_for_later_outcome_acquisition"
    ] is True


def test_stage41_frozen_protocol_artifact_is_reproducible():
    body = freeze.DEFAULT_OUTPUT.read_bytes()

    assert body == freeze.json_bytes(freeze.build_protocol())
    assert hashlib.sha256(body).hexdigest() == (
        "e5da6a7c3a8b9dba355f41e92114cf3ae8bd726c2c6026fdb1d8fd4b5ed88f33"
    )
