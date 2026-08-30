from __future__ import annotations

from uuid import UUID

import pytest

from data_agent.agentops_temporal_adapter import (
    TEMPORAL_ACTIVITY_RESULT_SCHEMA,
    TemporalProviderActivityResult,
    build_temporal_start_request,
)
from data_agent.agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_REQUEST_SCHEMA,
    TemporalActivityOutcome,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_reconciliation import (
    TemporalCheckpointReconciliationVerdict,
    TemporalHistoryReconciliationError,
    TemporalProviderActivityHistoryObservation,
    TemporalProviderActivityHistoryStatus,
    TemporalProviderWorkflowHistoryObservation,
    TemporalProviderWorkflowHistoryStatus,
    activity_evidence_from_history,
    reconcile_temporal_checkpoint,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
from data_agent.test_agentops_contracts import (
    _deployment,
    _evaluation,
    _spec,
    _subject,
    _temporal_input,
)

OUTPUT_ARTIFACT = UUID("00000000-0000-4000-8000-000000009901")


def _input():
    spec = _spec()
    return _temporal_input(_deployment(spec, _evaluation(spec)))


def _history_activity(
    plan,
    *,
    status: TemporalProviderActivityHistoryStatus,
    scheduled_event_id: int,
    started_event_id: int | None,
    terminal_event_id: int | None,
    timeout_type: str | None = None,
    provider_result: TemporalProviderActivityResult | None = None,
):
    values = {
        "tenant_id": plan.tenant_id,
        "workflow_id": plan.workflow_id,
        "activity_id": plan.activity_id,
        "attempt_no": plan.attempt_no,
        "request": plan.request,
        "request_sha256": plan.request_sha256,
        "status": status,
        "scheduled_event_id": scheduled_event_id,
        "started_event_id": started_event_id,
        "terminal_event_id": terminal_event_id,
        "timeout_type": timeout_type,
        "failure_type": None,
        "provider_result": provider_result,
    }
    values["observation_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_activity_history_observation.v1",
        values,
        "observation_sha256",
    )
    return TemporalProviderActivityHistoryObservation(**values)


def _workflow_observation(
    workflow_input,
    activities,
    *,
    status: TemporalProviderWorkflowHistoryStatus = (
        TemporalProviderWorkflowHistoryStatus.RUNNING
    ),
):
    values = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "provider_run_id": "temporal-run:checkpoint-reconciliation",
        "observed_input_sha256": build_temporal_start_request(
            workflow_input
        ).payload_sha256,
        "status": status,
        "history_event_count": 19,
        "history_sha256": "a" * 64,
        "activities": tuple(activities),
    }
    values["observation_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_workflow_history_observation.v1",
        values,
        "observation_sha256",
    )
    return TemporalProviderWorkflowHistoryObservation(**values)


def _projected_state():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    step = workflow_input.task_graph.steps[0]
    harness.start_step(workflow_id, step.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref="tool:agentops-temporal-reconciliation:v1",
        capability_ref="capability:agentops.temporal.reconciliation:v1",
        subject_context=_subject(),
        side_effect="none",
        policy_decision_ref="artifact://policy-decision-agent-run",
        idempotency_key="checkpoint-reconciliation:tool-call",
    )
    call = snapshot.execution.tool_calls[0]
    harness.dispatch_tool_call(workflow_id, call.tool_call_id)
    first = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.reconciliation.activity",
        schedule_to_close_timeout_seconds=40,
        start_to_close_timeout_seconds=20,
        heartbeat_timeout_seconds=2,
    ).activity_schedules[0]
    first_observation = _history_activity(
        first,
        status=TemporalProviderActivityHistoryStatus.TIMED_OUT,
        scheduled_event_id=5,
        started_event_id=6,
        terminal_event_id=7,
        timeout_type="TIMEOUT_TYPE_START_TO_CLOSE",
    )
    harness.record_scheduled_activity(
        workflow_id, activity_evidence_from_history(first_observation)
    )
    second = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.reconciliation.activity",
        attempt_no=2,
        schedule_to_close_timeout_seconds=40,
        start_to_close_timeout_seconds=20,
        heartbeat_timeout_seconds=2,
    ).activity_schedules[1]
    result_values = {
        "tenant_id": second.tenant_id,
        "workflow_id": second.workflow_id,
        "run_id": second.run_id,
        "step_id": second.step_id,
        "tool_call_id": second.request.tool_call_id,
        "activity_id": second.activity_id,
        "attempt_no": second.attempt_no,
        "request_sha256": second.request_sha256,
        "outcome": TemporalActivityOutcome.SUCCEEDED,
        "provider_receipt_ref": "temporal://receipt/checkpoint-reconciliation",
        "provider_operation_ref": "rehearsal://operation/checkpoint-reconciliation",
        "output_artifact_id": OUTPUT_ARTIFACT,
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    result_values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_RESULT_SCHEMA, result_values, "result_sha256"
    )
    result = TemporalProviderActivityResult(**result_values)
    second_observation = _history_activity(
        second,
        status=TemporalProviderActivityHistoryStatus.SUCCEEDED,
        scheduled_event_id=11,
        started_event_id=12,
        terminal_event_id=13,
        provider_result=result,
    )
    harness.record_scheduled_activity(
        workflow_id, activity_evidence_from_history(second_observation)
    )
    harness.complete_step(
        workflow_id,
        step_id=step.step_id,
        output_artifact_ids=(OUTPUT_ARTIFACT,),
    )
    return workflow_input, harness, first, second, first_observation, second_observation


def test_temporal_history_and_gda_checkpoint_reconcile_after_worker_restart():
    workflow_input, harness, first, second, first_observation, second_observation = (
        _projected_state()
    )
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)
    observation = _workflow_observation(
        workflow_input, (first_observation, second_observation)
    )

    reconciliation = reconcile_temporal_checkpoint(checkpoint, observation)

    assert reconciliation.verdict is TemporalCheckpointReconciliationVerdict.MATCHED
    assert reconciliation.matched_activity_ids == tuple(
        sorted((first.activity_id, second.activity_id), key=str)
    )
    assert reconciliation.checkpoint_sha256 == checkpoint.checkpoint_sha256
    assert reconciliation.execution_state_sha256 == checkpoint.execution.state_sha256


def test_checkpoint_behind_reports_missing_provider_attempt_without_mutation():
    workflow_input, harness, first, second, first_observation, second_observation = (
        _projected_state()
    )
    # Rebuild a fresh projection that has only attempt one scheduled and no terminal receipt.
    fresh = TemporalTaskGraphWorkflowHarness()
    fresh.start(workflow_input)
    step = workflow_input.task_graph.steps[0]
    fresh.start_step(workflow_input.identity.workflow_id, step.step_id)
    snapshot = fresh.bind_tool_call(
        workflow_input.identity.workflow_id,
        step_id=step.step_id,
        tool_ref="tool:agentops-temporal-reconciliation:v1",
        capability_ref="capability:agentops.temporal.reconciliation:v1",
        subject_context=_subject(),
        side_effect="none",
        policy_decision_ref="artifact://policy-decision-agent-run",
        idempotency_key="checkpoint-reconciliation:tool-call",
    )
    call = snapshot.execution.tool_calls[0]
    fresh.schedule_activity(
        workflow_input.identity.workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.reconciliation.activity",
        schedule_to_close_timeout_seconds=40,
        start_to_close_timeout_seconds=20,
        heartbeat_timeout_seconds=2,
    )
    checkpoint = fresh.checkpoint(workflow_input.identity.workflow_id)
    observation = _workflow_observation(
        workflow_input, (first_observation, second_observation)
    )

    reconciliation = reconcile_temporal_checkpoint(checkpoint, observation)

    assert reconciliation.verdict is TemporalCheckpointReconciliationVerdict.CHECKPOINT_BEHIND
    assert second.activity_id in reconciliation.checkpoint_missing_activity_ids
    assert first.activity_id in reconciliation.checkpoint_missing_evidence_ids


def test_provider_behind_reports_local_schedule_not_seen_by_temporal():
    workflow_input, harness, first, _second, _first_observation, _second_observation = (
        _projected_state()
    )
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)
    empty_observation = _workflow_observation(workflow_input, ())

    reconciliation = reconcile_temporal_checkpoint(checkpoint, empty_observation)

    assert reconciliation.verdict is TemporalCheckpointReconciliationVerdict.PROVIDER_BEHIND
    assert first.activity_id in reconciliation.provider_missing_activity_ids


def test_history_request_drift_fails_closed_even_when_hash_is_recomputed():
    workflow_input, harness, _first, second, first_observation, second_observation = (
        _projected_state()
    )
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)
    request_values = second.request.model_dump(mode="json")
    request_values["tool_ref"] = "tool:drifted:v1"
    request_values["request_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_REQUEST_SCHEMA, request_values, "request_sha256"
    )
    drifted_request = second.request.__class__(**request_values)
    drifted_values = second_observation.model_dump(mode="json")
    drifted_values["request"] = drifted_request.model_dump(mode="json")
    drifted_values["request_sha256"] = drifted_request.request_sha256
    provider_result_values = second_observation.provider_result.model_dump(mode="json")
    provider_result_values["request_sha256"] = drifted_request.request_sha256
    provider_result_values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_RESULT_SCHEMA,
        provider_result_values,
        "result_sha256",
    )
    drifted_values["provider_result"] = provider_result_values
    drifted_values["observation_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_activity_history_observation.v1",
        drifted_values,
        "observation_sha256",
    )
    drifted_activity = TemporalProviderActivityHistoryObservation(**drifted_values)
    observation = _workflow_observation(workflow_input, (first_observation, drifted_activity))

    with pytest.raises(TemporalHistoryReconciliationError, match="request differs"):
        reconcile_temporal_checkpoint(checkpoint, observation)


def test_history_start_input_drift_fails_closed_even_when_observation_hash_matches():
    workflow_input, harness, _first, _second, first_observation, second_observation = (
        _projected_state()
    )
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)
    observation_values = _workflow_observation(
        workflow_input, (first_observation, second_observation)
    ).model_dump(mode="json")
    observation_values["observed_input_sha256"] = "0" * 64
    observation_values["observation_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_workflow_history_observation.v1",
        observation_values,
        "observation_sha256",
    )
    drifted_observation = TemporalProviderWorkflowHistoryObservation(**observation_values)

    with pytest.raises(TemporalHistoryReconciliationError, match="start input differs"):
        reconcile_temporal_checkpoint(checkpoint, drifted_observation)


def test_completed_provider_history_marks_nonterminal_agent_run_checkpoint_behind():
    workflow_input, harness, _first, _second, first_observation, second_observation = (
        _projected_state()
    )
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)
    observation = _workflow_observation(
        workflow_input,
        (first_observation, second_observation),
        status=TemporalProviderWorkflowHistoryStatus.COMPLETED,
    )

    reconciliation = reconcile_temporal_checkpoint(checkpoint, observation)

    assert reconciliation.verdict is TemporalCheckpointReconciliationVerdict.CHECKPOINT_BEHIND
    assert reconciliation.checkpoint_missing_run_status is True
    assert reconciliation.provider_missing_run_status is False
