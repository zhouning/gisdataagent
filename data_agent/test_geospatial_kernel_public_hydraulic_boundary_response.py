from __future__ import annotations

import json

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_response as evidence,
)


def _ledger():
    return evidence.compile_public_hydraulic_boundary_response()


def test_stage36_verifies_freeze_chain_and_nine_raw_sources():
    ledger = _ledger()

    assert ledger.operator_artifact["sha256"] == (
        "ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f"
    )
    assert ledger.protocol_artifact["sha256"] == (
        "b0be7dedec2b7dfd933f2c81ea16a2b6bf853a3acafa499fd9beef84f7551ff7"
    )
    assert ledger.selection_plan_artifact["sha256"] == (
        "bee38f828d4a40fb9322e3cbf9bb14181b7e976b2a6e93c31423493c1f8e66a2"
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        "532a94a860b65d46f2361703c6acd6c1dafa2a4ab5860b801aebe339960a7540"
    )
    assert ledger.observation_plan_artifact["sha256"] == (
        "6402bbe5ef8fabca8090590b97379cc422bfbc557df53829f23cbfd5869e4f6f"
    )
    assert ledger.observation_acquisition_manifest_artifact["sha256"] == (
        "88c88416741287984ab5091e3d6e4a6d95384dad14a545832e76c50bf784a269"
    )
    assert len(ledger.source_artifacts) == 9


def test_stage36_preserves_half_hour_grid_gaps_without_fill():
    events = _ledger().events

    assert [value.raw_sample_count for value in events] == [48, 97, 97, 97]
    assert [value.grid_real_sample_count for value in events] == [48, 97, 97, 97]
    assert [value.grid_missing_sample_count for value in events] == [49, 0, 0, 0]
    assert [value.baseline_real_sample_count for value in events] == [18, 36, 36, 36]
    assert all(value.approved_sample_count == value.raw_sample_count for value in events)


def test_stage36_fails_closed_when_frozen_baseline_support_is_insufficient():
    first = _ledger().events[0]

    assert first.target_functional_assessable is False
    assert first.target_report is None
    assert first.target_support_rejection_reasons == (
        evidence.BASELINE_SUPPORT_REJECTION,
    )


def test_stage36_compiles_only_assessable_statistical_departures():
    ledger = _ledger()
    events = ledger.events

    assert [value.target_functional_assessable for value in events] == [
        False,
        True,
        True,
        True,
    ]
    assert ledger.assessable_event_count == 3
    assert ledger.all_events_target_functional_assessable is False
    assert all(
        value.target_report is not None for value in events[1:]
    )
    assert [
        value.target_report.baseline_median_m3s
        for value in events[1:]
        if value.target_report is not None
    ] == pytest.approx(
        [111.56837557248001, 259.94865171456, 99.53371577088001]
    )
    assert [
        value.target_report.departure_threshold_m3s
        for value in events[1:]
        if value.target_report is not None
    ] == pytest.approx(
        [269.5280143818608, 246.8574337329194, 437.2903111840285]
    )
    assert ledger.detected_event_count == 0
    assert [value.statistical_departure_detected for value in events] == [
        False,
        False,
        False,
        False,
    ]


def test_stage36_refuses_all_event_physical_and_runtime_promotions():
    ledger = _ledger()
    calls = (
        (ledger.require_all_event_statistical_departures, "all_event_departures"),
        (ledger.require_causal_release_response, "not_causal_response"),
        (ledger.require_physical_first_arrival, "not_physical_arrival"),
        (ledger.require_physical_travel_time, "not_physical_time"),
        (ledger.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage36_observation_plan_tampering_fails_closed(tmp_path):
    source = evidence.DEFAULT_SOURCE_ROOT
    for name in (
        "protocol.json",
        "selection_plan.json",
        "event_selection_manifest.json",
        "observation_acquisition_manifest.json",
    ):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    value = json.loads((source / "observation_plan.json").read_bytes())
    value["request_boundary"]["source_or_target_threshold_retuning_allowed"] = True
    (tmp_path / "observation_plan.json").write_text(
        json.dumps(value), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="artifact_mismatch|plan_invalid"):
        evidence.compile_public_hydraulic_boundary_response(source_root=tmp_path)


def test_compiled_stage36_report_passes_with_departure_support_refusal():
    from scripts import (
        compile_geotransport_stage36_hydraulic_boundary_response_gates as gates,
    )

    report = gates.compile_report(ledger=_ledger())

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 32
    assert sum(report["gates"].values()) == 32
    assert report["all_gates_passed"] is True
    assert report["decision"]["detected_event_count"] == 0
    assert report["decision"][
        "all_event_statistical_departure_support_admitted"
    ] is False
