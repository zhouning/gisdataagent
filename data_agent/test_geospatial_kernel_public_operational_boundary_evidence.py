from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_operational_boundary_evidence as evidence,
)


def _ledger():
    return evidence.compile_public_operational_boundary_evidence()


def test_stage28_verifies_six_public_sources_and_frozen_lag_plan():
    ledger = _ledger()
    report = ledger.as_dict()

    assert len(ledger.source_artifacts) == 6
    assert all(len(str(value["sha256"])) == 64 for value in ledger.source_artifacts)
    assert ledger.acquisition_plan["sha256"] == (
        "335cf57dad76c469e1f8e78cf9e93ccba2a606c38258cd69b45153f5ebc4d0bb"
    )
    assert report["diagnostic_summary"]["lag_candidates_hours"] == list(
        range(13)
    )
    assert ledger.request_boundary["workspace_or_private_data_sent"] is False
    assert ledger.request_boundary[
        "cwms_fixed_ip_fallback_retains_tls_hostname_verification"
    ] is True


def test_stage28_binds_cwms_tailwater_to_stage27_upstream_site_zone_only():
    ledger = _ledger()
    binding = ledger.location_binding
    report = binding.as_dict()

    assert binding.cwms_location_id == "CETT1-CENTER_HILL"
    assert binding.cwms_public_name == "Center Hill Dam Tailwater"
    assert binding.cwms_coordinate_nad83 == (-85.8261235, 36.0975966)
    assert binding.upstream_monitoring_location_id == "USGS-03424010"
    assert binding.coordinate_distance_m == pytest.approx(100.98614590402315)
    assert binding.within_upstream_site_zone is True
    assert report["same_physical_tailwater_zone_admitted"] is True
    assert report["same_sensor_or_measurement_process_admitted"] is False


def test_stage28_preserves_exact_cwms_series_and_support_semantics():
    catalog = _ledger().series_catalog
    report = catalog.as_dict()

    assert catalog.name == (
        "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
    )
    assert catalog.office == "LRN"
    assert catalog.units == "cms"
    assert catalog.interval == "1Hour"
    assert catalog.interval_offset_minutes == 0
    assert catalog.earliest_time == "1987-05-20T05:00:00Z"
    assert catalog.latest_time == "2026-07-28T05:00:00Z"
    assert report["outflow_alias_present"] is True
    assert report["total_flow_alias_present"] is True
    assert report["support_semantics"] == (
        "one_hour_average_with_timestamp_at_support_end"
    )
    assert report["quality_code_zero_interpreted_as_approved"] is False


def test_stage28_aggregates_real_half_hour_samples_without_filling():
    ledger = _ledger()

    for event in ledger.events:
        assert event.raw_release_value_count == 73
        assert event.raw_downstream_sample_count == 145
        assert len(event.hourly_releases) == 72
        assert len(event.hourly_downstream) == 72
        assert event.dropped_downstream_hour_count == 0
        assert event.downstream_fully_approved is True
        assert all(
            len(value.sample_times_utc) == 2
            for value in event.hourly_downstream
        )
        assert [value.pair_count for value in event.lag_diagnostics] == [
            72 - lag for lag in range(13)
        ]

    first = ledger.development_event.hourly_downstream[0]
    assert first.support_start_utc == "2024-05-15T00:00:00Z"
    assert first.support_end_utc == "2024-05-15T01:00:00Z"
    assert first.sample_times_utc == (
        "2024-05-15T00:30:00Z",
        "2024-05-15T01:00:00Z",
    )
    assert first.mean_value_m3s == pytest.approx(
        ((18600.0 + 18600.0) / 2.0) * evidence.CFS_TO_M3S
    )


def test_stage28_development_event_has_six_hour_diagnostic_not_travel_time():
    event = _ledger().development_event

    assert event.role == "development"
    assert event.release_value_range_m3s == pytest.approx(157.80978606)
    assert event.selected_lag_hours == 6
    assert event.lag_selection_status == (
        "development_correlation_lag_diagnostic_only"
    )
    selected = event.lag_diagnostics[6]
    assert selected.pair_count == 66
    assert selected.pearson_r == pytest.approx(0.9537370044069898)
    assert selected.rmse_m3s == pytest.approx(21.595624358061848)
    assert selected.mean_bias_m3s == pytest.approx(-2.773334793563639)


def test_stage28_transfer_event_zero_variance_refuses_lag_selection():
    event = _ledger().transfer_event

    assert event.role == "transfer"
    assert event.release_value_range_m3s == 0.0
    assert event.selected_lag_hours is None
    assert event.lag_selection_status == (
        "release_variance_zero_lag_unidentifiable"
    )
    assert all(value.pearson_r is None for value in event.lag_diagnostics)
    assert all(
        value.release_standard_deviation_m3s == 0.0
        for value in event.lag_diagnostics
    )


def test_stage28_compares_field_measurements_without_claiming_same_sensor():
    first, second = _ledger().field_release_comparisons

    assert first.field_observation_time_utc == "2024-05-16T14:40:55+00:00"
    assert first.field_approval_status == "Provisional"
    assert first.release_support_end_utc == "2024-05-16T15:00:00Z"
    assert first.release_m3s == pytest.approx(640.75360469)
    assert first.field_minus_release_m3s == pytest.approx(2.03881294840005)
    assert first.field_to_release_ratio == pytest.approx(1.0031818985230467)
    assert second.release_support_end_utc == "2026-02-10T17:00:00Z"
    assert second.release_m3s == pytest.approx(7.07921165)
    assert second.field_minus_release_m3s == pytest.approx(0.679604316208)
    assert second.field_to_release_ratio == pytest.approx(1.0959999996903609)
    assert all(
        value.as_dict()["exact_sensor_crosswalk_claimed"] is False
        for value in (first, second)
    )


def test_stage28_refuses_crosswalk_transfer_travel_time_and_rollout():
    ledger = _ledger()

    calls = (
        (
            ledger.require_exact_sensor_crosswalk,
            "public_operational_boundary_exact_sensor_crosswalk_unproven",
        ),
        (
            ledger.require_transfer_identified_lag,
            "public_operational_boundary_transfer_release_variance_zero",
        ),
        (
            ledger.require_stable_travel_time,
            "public_operational_boundary_two_event_travel_time_unidentified",
        ),
        (
            ledger.require_boundary_conditioned_rollout,
            "public_operational_boundary_diagnostic_is_not_rollout",
        ),
        (
            ledger.promote_lag_to_runtime_operator,
            "public_operational_boundary_lag_operator_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()

    report = ledger.as_dict()
    assert report["decision"]["operational_boundary_evidence_admitted"] is True
    assert report["decision"]["development_lag_diagnostic_admitted"] is True
    assert report["decision"]["travel_time_admitted"] is False
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False


def test_compiled_stage28_report_passes_with_diagnostic_only_admission():
    from scripts import (
        compile_geotransport_stage28_public_operational_boundary_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 25
    assert all(report["gates"].values())
    assert report["decision"]["operational_boundary_evidence_admitted"] is True
    assert report["decision"]["development_lag_diagnostic_admitted"] is True
    assert report["decision"]["travel_time_admitted"] is False
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["runtime_operator_admitted"] is False
