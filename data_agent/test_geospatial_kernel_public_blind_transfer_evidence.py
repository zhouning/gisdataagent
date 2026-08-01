from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as evidence,
)


def _ledger():
    return evidence.compile_public_blind_transfer_evidence()


def test_stage29_verifies_two_phase_freeze_and_eleven_public_sources():
    ledger = _ledger()

    assert ledger.candidate_count == 7266
    assert len(ledger.source_artifacts) == 11
    assert all(
        len(str(value["sha256"])) == 64
        and value["hash_verified"] is True
        and value["tls_hostname_verification_retained"] is True
        for value in ledger.source_artifacts
    )
    assert ledger.selection_plan_artifact["sha256"] == (
        "6b1a2b776ac1cc8d91ef1722e9b82fe48046f86cc242d88b091388090408dff5"
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        "480734abcdb2a535e7a2bc794dbf2a5d7e708d3d6faac7becbdea9429d05c91b"
    )
    assert ledger.observation_plan_artifact["sha256"] == (
        "ab90b2795616242c27c80cf06b5cba3c43462c535f4da1d8424a92c4a7b53727"
    )


def test_stage29_binds_one_observed_tributary_state_to_outlet_path():
    binding = _ledger().tributary_binding
    report = binding.as_dict()

    assert binding.site_id == "USGS-03424730"
    assert binding.name == "SMITH FORK AT TEMPERANCE HALL, TN"
    assert binding.coordinate_wgs84 == (-85.9074257025393, 36.08734569587428)
    assert binding.drainage_area_square_miles == 214.0
    assert binding.comid == 18421273
    assert binding.reachcode == "05130108000024"
    assert binding.downstream_path_feature_ids[0] == 18421273
    assert 18421743 in binding.downstream_path_feature_ids
    assert 18421703 in binding.downstream_path_feature_ids
    assert binding.path_reaches_outlet is True
    assert report["admitted_role"] == "observed_tributary_state_at_gauge"
    assert report["tributary_mouth_flux_admitted"] is False
    assert report["all_lateral_inflow_admitted"] is False


def test_stage29_compiles_three_release_selected_blind_events_without_fill():
    ledger = _ledger()

    assert [value.event_id for value in ledger.events] == [
        "release_step_20221223T1900Z",
        "release_step_20250910T1400Z",
        "release_step_20250303T1600Z",
    ]
    assert [value.best_lag_hours for value in ledger.events] == [5, 6, 6]
    for event in ledger.events:
        assert len(event.release_values_m3s) == 72
        assert set(event.release_quality_codes) == {0}
        assert event.raw_downstream_sample_count == 169
        assert len(event.downstream_hourly) == 84
        assert all(value.fully_approved for value in event.downstream_hourly)
        assert [value.pair_count for value in event.lag_diagnostics] == [
            72 for _ in range(13)
        ]


def test_stage29_blind_transfer_metrics_reject_unanimous_fixed_lag():
    first, second, third = _ledger().events

    assert first.best_lag_hours == 5
    assert first.best_lag_diagnostic.pearson_r == pytest.approx(
        0.799624219109659
    )
    assert first.fixed_lag_diagnostic.pearson_r == pytest.approx(
        0.7270395584160697
    )
    assert first.fixed_lag_supported is False
    assert first.fixed_lag_support_reasons == (
        "fixed_lag_pearson_below_0_8",
        "best_minus_fixed_pearson_exceeds_0_05",
    )
    assert second.best_lag_hours == 6
    assert second.fixed_lag_diagnostic.pearson_r == pytest.approx(
        0.8310662796172466
    )
    assert second.fixed_lag_supported is True
    assert third.best_lag_hours == 6
    assert third.fixed_lag_diagnostic.pearson_r == pytest.approx(
        0.8177595568106913
    )
    assert third.fixed_lag_supported is True
    assert _ledger().all_events_support_fixed_lag is False


def test_stage29_preserves_tributary_gaps_and_approved_state():
    contexts = [value.tributary_context for value in _ledger().events]

    assert [value.raw_sample_count for value in contexts] == [141, 169, 163]
    assert [value.complete_hour_count for value in contexts] == [61, 84, 79]
    assert [value.missing_hour_count for value in contexts] == [23, 0, 5]
    assert [value.fully_approved_hour_count for value in contexts] == [61, 84, 79]
    assert [value.coverage_ratio for value in contexts] == pytest.approx(
        [61 / 84, 1.0, 79 / 84]
    )
    assert [value.mean_m3s for value in contexts] == pytest.approx(
        [1.9836183142995942, 1.2922426652790864, 3.1226312969054]
    )
    assert [value.maximum_m3s for value in contexts] == pytest.approx(
        [2.2058823495168003, 1.9170505142784002, 3.766140596736]
    )
    assert all(
        value.as_dict()["missing_values_filled"] is False
        and value.as_dict()["represents_all_lateral_inflow"] is False
        for value in contexts
    )


def test_stage29_refuses_stable_lag_physical_time_lateral_total_and_rollout():
    ledger = _ledger()

    calls = (
        (
            ledger.require_stable_empirical_release_response_lag,
            "public_blind_transfer_fixed_lag_not_supported_by_all_events",
        ),
        (
            ledger.require_physical_travel_time,
            "public_blind_transfer_empirical_lag_is_not_physical_travel_time",
        ),
        (
            ledger.require_tributary_mouth_flux,
            "public_blind_transfer_gauge_is_not_tributary_mouth_flux",
        ),
        (
            ledger.require_all_lateral_inflow,
            "public_blind_transfer_single_tributary_is_not_lateral_inflow_total",
        ),
        (
            ledger.require_boundary_conditioned_rollout,
            "public_blind_transfer_evidence_is_not_spatial_rollout",
        ),
        (
            ledger.promote_to_runtime_operator,
            "public_blind_transfer_runtime_operator_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()

    report = ledger.as_dict()
    assert report["decision"]["blind_transfer_evidence_admitted"] is True
    assert report["decision"]["stable_empirical_lag_admitted"] is False
    assert report["decision"]["physical_travel_time_admitted"] is False
    assert report["decision"]["observed_tributary_state_admitted"] is True
    assert report["decision"]["observed_lateral_inflow_total_admitted"] is False
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False


def test_compiled_stage29_report_passes_with_two_of_three_support():
    from scripts import compile_geotransport_stage29_blind_transfer_gates as gates

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 27
    assert all(report["gates"].values())
    assert report["decision"]["blind_transfer_evidence_admitted"] is True
    assert report["decision"]["stable_empirical_lag_admitted"] is False
    assert report["decision"]["observed_tributary_state_admitted"] is True
    assert report["decision"]["observed_lateral_inflow_total_admitted"] is False
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
