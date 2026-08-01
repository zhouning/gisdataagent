from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_event_lag_support_evidence as evidence,
)


@pytest.fixture(scope="module")
def ledger():
    return evidence.compile_public_component_event_lag_support_evidence()


def test_stage43_binds_stage41_stage42_and_eight_raw_artifacts(ledger):
    assert {
        path: value["sha256"]
        for path, value in ledger.checkpoint_artifacts.items()
    } == evidence.EXPECTED_CHECKPOINT_SHA256
    assert len(ledger.source_artifacts) == 8
    assert {
        value["source_id"]: value["sha256"]
        for value in ledger.source_artifacts
    } == evidence.EXPECTED_RAW_SHA256
    assert ledger.actual_request_count == 8
    assert ledger.actual_attempt_count == 8
    assert ledger.actual_download_bytes == 1_112_317


def test_stage43_preserves_four_turbine_only_component_total_events(ledger):
    assert [value.event_id for value in ledger.events] == list(
        evidence.stage41.EXPECTED_EVENT_IDS
    )
    assert [value.selection_stratum for value in ledger.events] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]
    assert all(
        value.active_step_components == ("turbine",)
        and value.dominant_step_component == "turbine"
        and len(value.source_total_values_m3s) == 72
        for value in ledger.events
    )


def test_stage43_compiles_exact_event_local_lag_support(ledger):
    assert [value.lag_support.best_lag_hours for value in ledger.events] == [
        5,
        5,
        6,
        6,
    ]
    assert [value.lag_support.best_pearson_r for value in ledger.events] == (
        pytest.approx(
            [
                0.8217600767931865,
                0.8790617592474798,
                0.9244168189654225,
                0.919474372916006,
            ]
        )
    )
    assert [
        value.lag_support.supported_lags_hours for value in ledger.events
    ] == [(5,), (5,), (6, 7), (6,)]
    assert all(
        value.lag_support.response_detectable
        and tuple(item.pair_count for item in value.lag_diagnostics)
        == (72,) * 13
        for value in ledger.events
    )


def test_stage43_preserves_downstream_coverage_and_metadata(ledger):
    assert [
        value.downstream_metadata.raw_sample_count for value in ledger.events
    ] == [169, 169, 169, 169]
    assert [len(value.downstream_hourly) for value in ledger.events] == [
        84,
        84,
        84,
        84,
    ]
    assert all(
        value.downstream_metadata.all_samples_report_approved
        and value.downstream_metadata.all_qualifiers_are_none
        and value.downstream_metadata.as_dict()[
            "quality_metadata_interpreted_as_scientific_approval"
        ]
        is False
        for value in ledger.events
    )


def test_stage43_preserves_smith_fork_gaps_without_filling(ledger):
    assert [
        value.graph_state_metadata.raw_sample_count for value in ledger.events
    ] == [148, 165, 161, 169]
    assert [len(value.graph_states.states) for value in ledger.events] == [
        68,
        80,
        78,
        84,
    ]
    assert [value.graph_states.missing_hour_count for value in ledger.events] == [
        16,
        4,
        6,
        0,
    ]
    assert all(
        value.graph_states.as_dict()["missing_values_filled"] is False
        and value.graph_state_metadata.all_samples_report_approved
        and value.graph_state_metadata.all_qualifiers_are_none
        for value in ledger.events
    )


def test_stage43_binds_all_detectable_event_relations_to_outlet(ledger):
    assert ledger.all_events_have_detectable_response is True
    for value in ledger.events:
        assert value.graph_relation.source_boundary_id == "CETT1-CENTER_HILL"
        assert value.graph_relation.target_site_id == "USGS-03424860"
        assert value.graph_relation.target_comid == 18421703
        assert value.graph_relation.evidence_event_id == value.event_id
        assert value.graph_relation.lag_support == value.lag_support


def test_stage43_rejects_empty_cross_event_common_support(ledger):
    assert ledger.common_supported_lags_hours == ()
    assert ledger.common_empirical_support_admitted is False
    with pytest.raises(
        ValueError,
        match="common_empirical_support_unadmitted",
    ):
        ledger.require_common_empirical_support()


def test_stage43_refuses_component_causal_physical_flux_and_runtime_promotions(
    ledger,
):
    calls = (
        (ledger.require_quality_approval_semantics, "quality_approval"),
        (ledger.require_non_turbine_component_contrast, "non_turbine"),
        (ledger.require_causal_response, "causal_response"),
        (ledger.require_physical_travel_time, "not_physical_time"),
        (ledger.require_hydraulic_edge_travel_time, "not_hydraulic_edge_time"),
        (ledger.require_tributary_mouth_flux, "not_mouth_flux"),
        (ledger.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage43_decision_admits_local_evidence_only(ledger):
    decision = ledger.as_dict()["decision"]

    assert decision["observed_downstream_response_evidence_admitted"] is True
    assert decision["event_local_empirical_lag_support_admitted"] is True
    assert decision["event_local_empirical_lag_support_count"] == 4
    assert decision["common_empirical_support_admitted"] is False
    assert decision["non_turbine_component_contrast_admitted"] is False
    assert decision["causal_response_admitted"] is False
    assert decision["physical_travel_time_admitted"] is False
    assert decision["runtime_operator_admitted"] is False
