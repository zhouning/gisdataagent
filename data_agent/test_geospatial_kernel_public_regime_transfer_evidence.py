from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_regime_transfer_evidence as evidence,
)


def _ledger():
    return evidence.compile_public_regime_transfer_evidence()


def test_stage30_verifies_two_phase_freeze_and_nine_public_sources():
    ledger = _ledger()

    assert ledger.candidate_count == 4873
    assert len(ledger.source_artifacts) == 9
    assert all(
        len(str(value["sha256"])) == 64
        and value["hash_verified"] is True
        and value["tls_hostname_verification_retained"] is True
        for value in ledger.source_artifacts
    )
    assert ledger.selection_plan_artifact["sha256"] == (
        "dfea2f8c9abf9ba0044dd8c55027087d00e7c3221fbd9696fa44524015c38175"
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        "63ab64c6e6cbb9d4372d58e28d52d005a499b31ff6d5526a1aa9b7a7429364b6"
    )
    assert ledger.observation_plan_artifact["sha256"] == (
        "51dfcb8ae9daa797fd4fead0629bfb9651fbcb4cd3bfecfea85ce6a8e9c32a6a"
    )


def test_stage30_compiles_four_release_strata_without_outcome_selection():
    events = _ledger().events

    assert [value.selection_stratum for value in events] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]
    assert [value.event_id for value in events] == [
        "release_step_20210925T1900Z",
        "release_step_20251215T1700Z",
        "release_step_20240821T2000Z",
        "release_step_20230613T0000Z",
    ]
    assert [value.predicted_lag_hours for value in events] == [5, 5, 6, 6]
    assert [value.antecedent_flow_class for value in events] == [
        "high",
        "high",
        "low",
        "low",
    ]
    assert [value.release_direction for value in events] == [
        "increase",
        "decrease",
        "increase",
        "decrease",
    ]
    assert [value.step_magnitude_class for value in events] == [
        "large",
        "moderate",
        "large",
        "moderate",
    ]
    assert all(len(value.release_values_m3s) == 72 for value in events)
    assert all(set(value.release_quality_codes) == {0} for value in events)


def test_stage30_blind_metrics_reject_frozen_regime_rule():
    events = _ledger().events

    assert [value.best_lag_hours for value in events] == [4, 6, 6, 6]
    assert [value.rule_supported for value in events] == [
        False,
        True,
        True,
        True,
    ]
    assert events[0].predicted_lag_diagnostic.pearson_r == pytest.approx(
        0.42541305790444195
    )
    assert events[0].best_lag_diagnostic.pearson_r == pytest.approx(
        0.4813937619360038
    )
    assert events[0].rule_support_reasons == (
        "predicted_lag_pearson_below_0_8",
        "best_minus_predicted_pearson_exceeds_0_05",
    )
    assert _ledger().all_strata_support_rule is False


def test_stage30_three_strata_support_frozen_predictions():
    _, high_decrease, low_increase, low_decrease = _ledger().events

    assert high_decrease.predicted_lag_diagnostic.pearson_r == pytest.approx(
        0.9324142144179708
    )
    assert high_decrease.best_lag_hours == 6
    assert high_decrease.rule_supported is True
    assert low_increase.predicted_lag_diagnostic.pearson_r == pytest.approx(
        0.8990338841735641
    )
    assert low_increase.rule_supported is True
    assert low_decrease.predicted_lag_diagnostic.pearson_r == pytest.approx(
        0.8546508671711874
    )
    assert low_decrease.rule_supported is True


def test_stage30_graph_state_contract_preserves_support_and_gaps():
    series = [value.graph_states for value in _ledger().events]

    assert [value.raw_sample_count for value in series] == [169, 163, 166, 169]
    assert [len(value.states) for value in series] == [84, 80, 82, 84]
    assert [value.missing_hour_count for value in series] == [0, 4, 2, 0]
    assert all(
        state.site_id == "USGS-03424730"
        and state.comid == 18421273
        and state.fully_approved
        for value in series
        for state in value.states
    )
    report = series[1].as_dict()
    assert report["missing_values_filled"] is False
    assert report["tributary_mouth_flux_admitted"] is False
    assert report["total_lateral_inflow_admitted"] is False
    assert report["mass_conservation_oracle_admitted"] is False


def test_stage30_rule_and_unsupported_spatial_promotions_fail_closed():
    ledger = _ledger()
    calls = (
        (
            ledger.require_regime_conditioned_lag_rule,
            "public_regime_transfer_rule_not_supported_by_all_strata",
        ),
        (
            ledger.require_physical_travel_time,
            "public_regime_transfer_empirical_lag_is_not_physical_time",
        ),
        (
            ledger.require_tributary_mouth_flux,
            "public_regime_transfer_graph_state_is_not_mouth_flux",
        ),
        (
            ledger.require_total_lateral_inflow,
            "public_regime_transfer_graph_state_is_not_lateral_total",
        ),
        (
            ledger.require_conservation_oracle,
            "public_regime_transfer_graph_state_is_not_conservation_oracle",
        ),
        (
            ledger.promote_to_runtime_operator,
            "public_regime_transfer_runtime_operator_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()

    state = ledger.events[0].graph_states.states[0]
    with pytest.raises(ValueError, match="not_tributary_mouth_flux"):
        state.require_tributary_mouth_flux()
    with pytest.raises(ValueError, match="not_conservation_oracle"):
        state.require_conservation_oracle()


def test_stage30_decision_admits_graph_state_but_not_regime_rule():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision["blind_regime_validation_admitted"] is True
    assert decision["regime_conditioned_empirical_lag_admitted"] is False
    assert decision["observed_graph_state_contract_admitted"] is True
    assert decision["tributary_mouth_flux_admitted"] is False
    assert decision["observed_lateral_inflow_total_admitted"] is False
    assert decision["mass_conservation_oracle_admitted"] is False
    assert decision["runtime_operator_admitted"] is False


def test_compiled_stage30_report_passes_with_rule_rejection():
    from scripts import (
        compile_geotransport_stage30_regime_validation_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 27
    assert all(report["gates"].values())
    assert report["status"] == (
        "four_strata_scored_regime_rule_rejected_graph_state_admitted"
    )
    assert report["decision"][
        "regime_conditioned_empirical_lag_admitted"
    ] is False
    assert report["decision"]["observed_graph_state_contract_admitted"] is True
