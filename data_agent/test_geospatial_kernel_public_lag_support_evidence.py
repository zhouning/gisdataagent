from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_lag_support_evidence as evidence,
)


def _ledger():
    return evidence.compile_public_lag_support_evidence()


def test_stage32_verifies_two_operators_two_phase_freeze_and_sources():
    ledger = _ledger()

    assert ledger.candidate_count == 401
    assert len(ledger.source_artifacts) == 9
    assert all(
        len(str(value["sha256"])) == 64
        and value["hash_verified"] is True
        and value["tls_hostname_verification_retained"] is True
        for value in ledger.source_artifacts
    )
    assert ledger.operator_artifacts["release_excitation_identifiability"][
        "sha256"
    ] == "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb"
    assert ledger.operator_artifacts["empirical_lag_support"]["sha256"] == (
        "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"
    )
    assert ledger.selection_plan_artifact["sha256"] == (
        "dc43874cb02b865cca760d21dfa7352db7e85e73329c414f65af5168bf491282"
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        "d66df4681831774b55bde7b156b52be3673e129b31b601bcff038fcb3ea6b17d"
    )
    assert ledger.observation_plan_artifact["sha256"] == (
        "f1e5f2e7d6f0183023f29b960deb8ce0a41c38542e2f9e8dbb0dd5a223026af5"
    )


def test_stage32_compiles_four_release_supported_blind_events():
    events = _ledger().events

    assert [value.event_id for value in events] == [
        "release_step_20220202T1900Z",
        "release_step_20220919T1500Z",
        "release_step_20230911T1500Z",
        "release_step_20210625T1600Z",
    ]
    assert [value.release_direction for value in events] == [
        "decrease",
        "increase",
        "increase",
        "increase",
    ]
    assert [
        value.release_support.excursion_support_hours for value in events
    ] == [12, 12, 12, 7]
    assert all(
        value.release_support.blind_response_test_admissible
        for value in events
    )
    assert all(len(value.release_values_m3s) == 72 for value in events)
    assert all(set(value.release_quality_codes) == {0} for value in events)


def test_stage32_compiles_gap_aware_discrete_lag_support_sets():
    events = _ledger().events

    assert [value.lag_support.best_lag_hours for value in events] == [
        6,
        6,
        7,
        7,
    ]
    assert [value.lag_support.best_pearson_r for value in events] == (
        pytest.approx(
            [
                0.8533970825151787,
                0.8672719516081647,
                0.8561258336937435,
                0.7476521168447066,
            ]
        )
    )
    assert [
        value.lag_support.supported_lags_hours for value in events
    ] == [(5, 6, 7), (6, 7), (7,), ()]
    assert [
        value.lag_support.response_detectable for value in events
    ] == [True, True, True, False]
    assert events[3].lag_support.response_rejection_reasons == (
        "best_lag_pearson_below_0_8",
    )


def test_stage32_preserves_downstream_gaps_and_real_pair_counts():
    events = _ledger().events

    assert [len(value.downstream_hourly) for value in events] == [
        84,
        84,
        77,
        84,
    ]
    assert [
        tuple(value.pair_count for value in event.lag_diagnostics)
        for event in events
    ] == [
        (72,) * 13,
        (72,) * 13,
        (66, 66, 66, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65),
        (72,) * 13,
    ]
    assert all(
        event.as_dict()["downstream_missing_hour_count"]
        == 84 - len(event.downstream_hourly)
        for event in events
    )


def test_stage32_binds_only_detectable_empirical_graph_relations():
    events = _ledger().events

    assert [value.graph_relation is not None for value in events] == [
        True,
        True,
        True,
        False,
    ]
    for event in events[:3]:
        relation = event.graph_relation
        assert relation is not None
        assert relation.source_boundary_id == "CETT1-CENTER_HILL"
        assert relation.source_spatial_role == "operational_tailwater_zone"
        assert relation.target_site_id == "USGS-03424860"
        assert relation.target_comid == 18421703
        assert relation.evidence_event_id == event.event_id
        with pytest.raises(ValueError, match="not_hydraulic_edge_time"):
            relation.require_hydraulic_edge_travel_time()
        with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
            relation.promote_to_runtime_transition()


def test_stage32_common_support_fails_closed_on_weak_blind_event():
    ledger = _ledger()

    assert ledger.all_events_have_detectable_response is False
    assert ledger.common_supported_lags_hours == ()
    assert ledger.common_empirical_support_admitted is False
    with pytest.raises(ValueError, match="common_empirical_support_unadmitted"):
        ledger.require_common_empirical_support()


def test_stage32_graph_states_preserve_real_support_and_gaps():
    series = [value.graph_states for value in _ledger().events]

    assert [len(value.states) for value in series] == [74, 84, 84, 81]
    assert [value.missing_hour_count for value in series] == [10, 0, 0, 3]
    assert all(
        state.site_id == "USGS-03424730"
        and state.comid == 18421273
        and state.fully_approved
        for value in series
        for state in value.states
    )
    assert all(
        value.as_dict()["missing_values_filled"] is False
        for value in series
    )


def test_stage32_refuses_physical_flux_and_runtime_promotions():
    ledger = _ledger()
    calls = (
        (
            ledger.require_physical_travel_time,
            "empirical_set_is_not_physical_time",
        ),
        (
            ledger.require_hydraulic_edge_travel_time,
            "relation_is_not_hydraulic_edge_time",
        ),
        (
            ledger.require_tributary_mouth_flux,
            "graph_state_is_not_mouth_flux",
        ),
        (
            ledger.promote_to_runtime_operator,
            "runtime_operator_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage32_decision_admits_evidence_but_not_common_lag_support():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision["blind_lag_support_evidence_admitted"] is True
    assert decision["common_empirical_support_admitted"] is False
    assert decision["common_supported_lags_hours"] == []
    assert decision["physical_travel_time_admitted"] is False
    assert decision["hydraulic_edge_travel_time_admitted"] is False
    assert decision["observed_graph_state_contract_admitted"] is True
    assert decision["tributary_mouth_flux_admitted"] is False
    assert decision["runtime_operator_admitted"] is False


def test_compiled_stage32_report_passes_with_common_support_refusal():
    from scripts import compile_geotransport_stage32_lag_support_gates as gates

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 32
    assert all(report["gates"].values())
    assert report["status"] == (
        "blind_common_empirical_lag_support_rejected"
    )
    assert report["decision"]["common_empirical_support_admitted"] is False
    assert report["decision"]["common_supported_lags_hours"] == []
