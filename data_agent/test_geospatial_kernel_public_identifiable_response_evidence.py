from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_identifiable_response_evidence as evidence,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)


def _ledger():
    return evidence.compile_public_identifiable_response_evidence()


def test_stage31_verifies_operator_two_phase_freeze_and_public_sources():
    ledger = _ledger()

    assert ledger.candidate_count == 1812
    assert len(ledger.source_artifacts) == 9
    assert all(
        len(str(value["sha256"])) == 64
        and value["hash_verified"] is True
        and value["tls_hostname_verification_retained"] is True
        for value in ledger.source_artifacts
    )
    assert ledger.operator_artifact["sha256"] == (
        "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb"
    )
    assert ledger.selection_plan_artifact["sha256"] == (
        "0ebb39f688776b64458283d1b39ad67312381bbf9acf8bdd7f9ee864f37e53f7"
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        "d03f6a8de7511c77105ba1a051f7b57292c43c48d7081256aecdf9db13b1bf3d"
    )
    assert ledger.observation_plan_artifact["sha256"] == (
        "34169db80643a05a51c8579811c7c99320ba594734871c63cc70fc8ac8464e35"
    )


def test_stage31_compiles_four_release_supported_blind_events():
    events = _ledger().events

    assert [value.event_id for value in events] == [
        "release_step_20250606T1600Z",
        "release_step_20210322T1200Z",
        "release_step_20220613T1300Z",
        "release_step_20240203T1300Z",
    ]
    assert [value.selection_stratum for value in events] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]
    assert [
        value.release_support.excursion_support_hours for value in events
    ] == [12, 12, 12, 12]
    assert [
        value.release_support.normalized_excitation_volume_step_hours
        for value in events
    ] == pytest.approx(
        [
            23.54258207760674,
            36.51594936677283,
            26.731391584612602,
            17.423283262749198,
        ]
    )
    assert all(
        value.release_support.blind_response_test_admissible
        for value in events
    )
    assert all(len(value.release_values_m3s) == 72 for value in events)
    assert all(set(value.release_quality_codes) == {0} for value in events)


def test_stage31_all_blind_events_have_detectable_six_hour_response():
    events = _ledger().events

    assert [value.best_lag_hours for value in events] == [6, 6, 6, 6]
    assert [value.second_best_lag_hours for value in events] == [5, 5, 5, 5]
    assert [value.best_lag_diagnostic.pearson_r for value in events] == (
        pytest.approx(
            [
                0.9410482377387122,
                0.9368952303836997,
                0.9199966010515274,
                0.8310274060786108,
            ]
        )
    )
    assert [value.response_detectable for value in events] == [
        True,
        True,
        True,
        True,
    ]
    assert _ledger().all_events_have_detectable_response is True


def test_stage31_only_one_event_resolves_exact_hour():
    events = _ledger().events

    assert [value.peak_margin_pearson_r for value in events] == pytest.approx(
        [
            0.016311997488542063,
            0.01794815225576163,
            0.023221205959676694,
            0.010554875077697923,
        ]
    )
    assert [value.exact_hour_resolved for value in events] == [
        False,
        False,
        True,
        False,
    ]
    assert events[2].require_exact_hour_lag() == 6
    with pytest.raises(ValueError, match="exact_hour_not_resolved"):
        events[0].require_exact_hour_lag()
    assert _ledger().all_events_resolve_exact_hour is False


def test_stage31_graph_states_preserve_real_support_and_gaps():
    series = [value.graph_states for value in _ledger().events]

    assert [value.raw_sample_count for value in series] == [169, 166, 169, 169]
    assert [len(value.states) for value in series] == [84, 81, 84, 84]
    assert [value.missing_hour_count for value in series] == [0, 3, 0, 0]
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


def test_stage31_admits_input_gate_but_refuses_lag_overclaims():
    ledger = _ledger()

    assert ledger.require_validated_release_support_gate() == excitation.SCHEMA
    calls = (
        (
            ledger.require_universal_exact_hour_lag,
            "public_identifiable_response_exact_hour_not_universal",
        ),
        (
            ledger.require_physical_travel_time,
            "public_identifiable_response_empirical_lag_is_not_physical_time",
        ),
        (
            ledger.require_tributary_mouth_flux,
            "public_identifiable_response_graph_state_is_not_mouth_flux",
        ),
        (
            ledger.promote_to_runtime_operator,
            "public_identifiable_response_runtime_operator_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage31_decision_separates_response_support_from_exact_lag():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision["blind_identifiable_response_evidence_admitted"] is True
    assert decision["release_support_gate_validated"] is True
    assert decision["universal_exact_hour_lag_admitted"] is False
    assert decision["physical_travel_time_admitted"] is False
    assert decision["observed_graph_state_contract_admitted"] is True
    assert decision["tributary_mouth_flux_admitted"] is False
    assert decision["runtime_operator_admitted"] is False


def test_compiled_stage31_report_passes_with_exact_hour_refusal():
    from scripts import (
        compile_geotransport_stage31_identifiable_response_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 29
    assert all(report["gates"].values())
    assert report["status"] == (
        "release_support_gate_validated_exact_hour_not_universal"
    )
    assert report["decision"]["release_support_gate_validated"] is True
    assert report["decision"]["universal_exact_hour_lag_admitted"] is False
