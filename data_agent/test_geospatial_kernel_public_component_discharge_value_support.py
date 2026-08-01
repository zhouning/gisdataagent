from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_component_discharge_value_support as evidence,
)


def _ledger():
    return evidence.compile_public_component_discharge_value_support()


def test_stage40_binds_protocol_plan_state_and_manifest():
    ledger = _ledger()

    assert ledger.protocol_artifact["sha256"] == evidence.EXPECTED_PROTOCOL_SHA256
    assert ledger.plan_artifact["sha256"] == evidence.EXPECTED_PLAN_SHA256
    assert ledger.acquisition_state_artifact["sha256"] == evidence.EXPECTED_STATE_SHA256
    assert ledger.acquisition_manifest_artifact["sha256"] == (evidence.EXPECTED_MANIFEST_SHA256)


def test_stage40_binds_all_twenty_raw_artifacts():
    artifacts = _ledger().source_artifacts

    assert len(artifacts) == 20
    assert len({value["source_id"] for value in artifacts}) == 20
    assert all(len(str(value["sha256"])) == 64 for value in artifacts)


def test_stage40_decision_admits_only_value_support():
    decision = _ledger().as_dict()["decision"]

    assert decision["component_value_artifacts_acquired"] is True
    assert decision["logical_request_count"] == 20
    assert decision["actual_attempt_count"] == 20
    assert decision["actual_download_bytes"] == 4_225_697
    assert decision["per_component_complete_hourly_coverage_admitted"] is True
    assert decision["synchronized_four_component_value_support_admitted"] is True
    assert decision["quality_code_approval_semantics_admitted"] is False
    assert decision["synchronized_total_discharge_values_compiled"] is False


def test_stage40_preserves_event_outcome_causal_and_runtime_rejections():
    decision = _ledger().as_dict()["decision"]

    assert decision["component_discharge_event_admitted"] is False
    assert decision["downstream_outcome_values_acquired"] is False
    assert decision["gate_commands_admitted"] is False
    assert decision["human_actions_admitted"] is False
    assert decision["causal_interventions_admitted"] is False
    assert decision["physical_response_time_admitted"] is False
    assert decision["runtime_operators_admitted"] is False
    assert decision["separate_event_selection_protocol_required"] is True


def test_stage40_public_refusals_fail_closed():
    ledger = _ledger()
    calls = (
        (ledger.require_quality_approval_semantics, "approval_semantics"),
        (ledger.require_total_discharge_values, "total_values_not_compiled"),
        (ledger.require_event_selection, "event_selection"),
        (ledger.require_gate_command, "gate_command"),
        (ledger.require_human_action, "human_action"),
        (ledger.require_causal_intervention, "causal_intervention"),
        (ledger.require_physical_response_time, "physical_response_time"),
        (ledger.promote_to_runtime_operator, "runtime_operator"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage40_provenance_is_content_addressed():
    provenance = _ledger().provenance_id

    assert provenance.startswith("center-hill-component-discharge-value-support:")
    assert len(provenance.rsplit(":", 1)[1]) == 64


def test_compiled_stage40_report_admits_support_not_events_or_runtime():
    from scripts import (
        compile_geotransport_stage40_component_discharge_value_support_gates as gates,
    )

    report = gates.compile_report(ledger=_ledger())

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 38
    assert sum(report["gates"].values()) == 38
    assert report["all_gates_passed"] is True
    assert report["decision"]["synchronized_four_component_value_support_admitted"] is True
    assert report["decision"]["component_discharge_event_admitted"] is False
    assert report["decision"]["runtime_operators_admitted"] is False
