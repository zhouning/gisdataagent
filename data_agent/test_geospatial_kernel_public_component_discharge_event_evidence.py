from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_discharge_event_evidence as evidence,
)


@pytest.fixture(scope="module")
def ledger():
    return evidence.compile_public_component_discharge_event_evidence()


def test_stage41_public_evidence_binds_protocol_candidates_and_manifest(ledger):
    assert ledger.protocol_artifact["sha256"] == evidence.EXPECTED_PROTOCOL_SHA256
    assert ledger.candidate_ledger_artifact["sha256"] == (
        evidence.EXPECTED_CANDIDATE_LEDGER_SHA256
    )
    assert ledger.event_selection_manifest_artifact["sha256"] == (
        evidence.EXPECTED_MANIFEST_SHA256
    )


def test_stage41_public_evidence_preserves_twenty_stage40_sources(ledger):
    assert len(ledger.source_artifacts) == 20
    assert len({value["source_id"] for value in ledger.source_artifacts}) == 20
    assert all(len(str(value["sha256"])) == 64 for value in ledger.source_artifacts)


def test_stage41_public_evidence_admits_only_source_events(ledger):
    decision = ledger.as_dict()["decision"]

    assert decision["synchronized_total_discharge_derivation_admitted"] is True
    assert decision["full_derived_total_series_persisted"] is False
    assert decision["eligible_source_event_count"] == 2_547
    assert decision["source_only_total_discharge_event_count"] == 4
    assert decision["source_only_total_discharge_events_admitted"] is True
    assert decision["selected_dominant_components"] == ["turbine"] * 4
    assert decision["non_turbine_component_contrast_admitted"] is False


def test_stage41_public_evidence_records_zero_new_requests(ledger):
    decision = ledger.as_dict()["decision"]

    assert decision["new_network_request_count"] == 0
    assert decision["downstream_or_tributary_values_acquired"] is False
    assert decision["observed_downstream_response_admitted"] is False
    assert decision["fresh_approval_required_for_target_acquisition"] is True


def test_stage41_public_refusals_fail_closed(ledger):
    calls = (
        (ledger.require_quality_approval_semantics, "approval_semantics"),
        (ledger.require_non_turbine_component_contrast, "contrast"),
        (ledger.require_gate_command, "gate_command"),
        (ledger.require_human_action, "human_action"),
        (ledger.require_observed_downstream_response, "downstream_response"),
        (ledger.require_causal_intervention, "causal_intervention"),
        (ledger.require_physical_response_time, "physical_response_time"),
        (ledger.promote_to_runtime_operator, "runtime_operator"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage41_public_provenance_is_content_addressed(ledger):
    assert ledger.provenance_id.startswith("center-hill-component-discharge-events:")
    assert len(ledger.provenance_id.rsplit(":", 1)[1]) == 64


def test_compiled_stage41_report_admits_events_not_component_contrast(ledger):
    from scripts import (
        compile_geotransport_stage41_component_discharge_event_gates as gates,
    )

    report = gates.compile_report(ledger=ledger)

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 37
    assert sum(report["gates"].values()) == 37
    assert report["all_gates_passed"] is True
    assert report["decision"]["source_only_total_discharge_events_admitted"] is True
    assert report["decision"]["non_turbine_component_contrast_admitted"] is False
