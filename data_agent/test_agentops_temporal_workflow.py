from __future__ import annotations

from uuid import UUID

import pytest

from data_agent.agentops_contracts import (
    AgentRunStatus,
    AgentSideEffect,
    AgentToolCallStatus,
    agent_run_fingerprint,
)
from data_agent.agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA,
    TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
    TEMPORAL_SIGNAL_SCHEMA,
    TemporalActivityCancellationType,
    TemporalActivityEvidence,
    TemporalActivityOutcome,
    TemporalActivityRequest,
    TemporalActivitySchedulePlan,
    TemporalContractError,
    TemporalIntegrationHarness,
    TemporalSignal,
    TemporalSignalKind,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_workflow import (
    TemporalTaskGraphWorkflowCheckpoint,
    TemporalTaskGraphWorkflowHarness,
)
from data_agent.test_agentops_contracts import (
    _deployment,
    _evaluation,
    _signal,
    _spec,
    _subject,
    _temporal_input,
)

ARTIFACT_1 = UUID("00000000-0000-4000-8000-000000001101")
ARTIFACT_2 = UUID("00000000-0000-4000-8000-000000001102")
TOOL_CALL_1 = UUID("00000000-0000-4000-8000-000000001111")
TOOL_CALL_2 = UUID("00000000-0000-4000-8000-000000001112")


def _input():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    return _temporal_input(deployment)


def _evidence(
    workflow_input,
    *,
    tool_call_id: UUID,
    activity_id: UUID,
    idempotency_key: str,
    side_effect: AgentSideEffect,
    outcome: TemporalActivityOutcome,
    output_artifact_id: UUID | None = None,
    external_receipt_artifact_id: UUID | None = None,
    provider_operation_ref: str | None = None,
    failure_type: str | None = None,
) -> TemporalActivityEvidence:
    values = {
        "tenant_id": workflow_input.tenant_id,
        "workflow_id": workflow_input.identity.workflow_id,
        "run_id": workflow_input.agent_run.run_id,
        "activity_id": activity_id,
        "tool_call_id": tool_call_id,
        "idempotency_key": idempotency_key,
        "side_effect": side_effect,
        "outcome": outcome,
        "policy_decision_ref": "artifact://policy-decision-agent-run",
        "output_artifact_id": output_artifact_id,
        "external_receipt_artifact_id": external_receipt_artifact_id,
        "provider_operation_ref": provider_operation_ref,
        "failure_type": failure_type,
    }
    values["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, values, "evidence_sha256"
    )
    return TemporalActivityEvidence(**values)


def _bind_and_dispatch(harness, workflow_input, *, step_id, tool_ref, key, side_effect):
    harness.start(workflow_input)
    snapshot = harness.start_step(workflow_input.identity.workflow_id, step_id)
    snapshot = harness.bind_tool_call(
        workflow_input.identity.workflow_id,
        step_id=step_id,
        tool_ref=tool_ref,
        capability_ref="capability:data_product.execute:v1",
        subject_context=_subject(),
        side_effect=side_effect,
        policy_decision_ref="artifact://policy-decision-agent-run",
        idempotency_key=key,
    )
    call = snapshot.execution.tool_calls[-1]
    return harness.dispatch_tool_call(workflow_input.identity.workflow_id, call.tool_call_id)


def test_workflow_harness_projects_step_activity_and_idempotent_replay():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]

    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:data-product-plan:v1",
        key="tool-call:coordinator:plan",
        side_effect=AgentSideEffect.DATA_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    evidence = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=TOOL_CALL_1,
        idempotency_key="activity:coordinator:plan:1",
        side_effect=AgentSideEffect.DATA_WRITE,
        outcome=TemporalActivityOutcome.SUCCEEDED,
        output_artifact_id=ARTIFACT_1,
    )
    snapshot = harness.record_activity(workflow_id, evidence)
    snapshot = harness.complete_step(
        workflow_id,
        step_id=coordinator.step_id,
        output_artifact_ids=(ARTIFACT_1,),
    )

    assert snapshot.workflow.run.status.value == "running"
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.SUCCEEDED
    assert snapshot.execution.graph.graph_sha256 == workflow_input.task_graph.graph_sha256
    assert harness.record_activity(workflow_id, evidence) == snapshot
    assert harness.dispatch_tool_call(workflow_id, call.tool_call_id) == snapshot


def test_activity_request_is_stable_per_attempt_and_bound_to_tool_call_projection():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:data-product-plan:v1",
        key="tool-call:coordinator:request",
        side_effect=AgentSideEffect.DATA_WRITE,
    )
    call = snapshot.execution.tool_calls[0]

    first = harness.build_activity_request(workflow_id, call.tool_call_id)
    replay = harness.build_activity_request(workflow_id, call.tool_call_id)
    retry = harness.build_activity_request(workflow_id, call.tool_call_id, attempt_no=2)

    assert first == replay
    assert first.activity_id != retry.activity_id
    assert first.step_id == coordinator.step_id
    assert first.tool_ref == call.tool_ref
    assert first.capability_ref == call.capability_ref
    assert first.policy_decision_ref == call.policy_decision_ref
    assert first.subject_context == call.subject_context
    assert first.input_artifact_ids == call.input_artifact_ids

    with pytest.raises(TemporalContractError, match="max_attempts"):
        harness.build_activity_request(workflow_id, call.tool_call_id, attempt_no=4)

    changed = first.model_dump(mode="json")
    changed["activity_id"] = retry.activity_id
    with pytest.raises(ValueError, match="activity_id"):
        TemporalActivityRequest(**changed)


def test_activity_schedule_uses_one_sdk_attempt_and_platform_owned_retry_identity():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:data-product-plan:v1",
        key="tool-call:coordinator:scheduled-retry",
        side_effect=AgentSideEffect.DATA_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    )
    first = snapshot.activity_schedules[0]
    assert first.sdk_maximum_attempts == 1
    assert first.task_queue_ref == workflow_input.identity.task_queue.queue_ref
    assert first.task_queue_sha256 == (
        workflow_input.identity.task_queue.queue_sha256
    )
    assert first.request_sha256 == first.request.request_sha256
    assert harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    ) == snapshot

    failed = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=first.activity_id,
        idempotency_key="activity:scheduled-retry:attempt-1",
        side_effect=AgentSideEffect.DATA_WRITE,
        outcome=TemporalActivityOutcome.FAILED,
        failure_type="ProviderTimeout",
    )
    snapshot = harness.record_scheduled_activity(workflow_id, failed)
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.RUNNING
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        attempt_no=2,
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    )
    second = snapshot.activity_schedules[1]
    assert second.sdk_maximum_attempts == 1
    assert second.activity_id != first.activity_id
    assert second.request_sha256 != first.request_sha256

    changed = second.model_dump(mode="json")
    changed["sdk_maximum_attempts"] = 2
    changed["schedule_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA, changed, "schedule_sha256"
    )
    with pytest.raises(ValueError, match="less than or equal to 1|Input should be 1"):
        TemporalActivitySchedulePlan(**changed)


def test_activity_schedule_requires_failed_predecessor_and_reconciles_unknown_first():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:external-publish:v1",
        key="tool-call:coordinator:scheduled-unknown",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    )
    first = snapshot.activity_schedules[0]
    with pytest.raises(TemporalContractError, match="failed evidence"):
        harness.schedule_activity(
            workflow_id,
            call.tool_call_id,
            activity_type="gda.agentops.activity",
            attempt_no=2,
            schedule_to_close_timeout_seconds=600,
            start_to_close_timeout_seconds=300,
            heartbeat_timeout_seconds=30,
        )

    unknown = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=first.activity_id,
        idempotency_key="activity:scheduled-unknown:attempt-1",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.UNKNOWN,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/scheduled-unknown",
    )
    snapshot = harness.record_scheduled_activity(workflow_id, unknown)
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.RECONCILING
    with pytest.raises(TemporalContractError, match="reconciling"):
        harness.schedule_activity(
            workflow_id,
            call.tool_call_id,
            activity_type="gda.agentops.activity",
            attempt_no=2,
            schedule_to_close_timeout_seconds=600,
            start_to_close_timeout_seconds=300,
            heartbeat_timeout_seconds=30,
        )


def test_non_retryable_activity_failure_settles_tool_call_without_new_attempt():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:data-product-plan:v1",
        key="tool-call:coordinator:non-retryable",
        side_effect=AgentSideEffect.NONE,
    )
    call = snapshot.execution.tool_calls[0]
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    )
    failed = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=snapshot.activity_schedules[0].activity_id,
        idempotency_key="activity:non-retryable:attempt-1",
        side_effect=AgentSideEffect.NONE,
        outcome=TemporalActivityOutcome.FAILED,
        failure_type="ValidationError",
    )

    snapshot = harness.record_scheduled_activity(workflow_id, failed)

    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.FAILED
    with pytest.raises(TemporalContractError, match="failed state"):
        harness.schedule_activity(
            workflow_id,
            call.tool_call_id,
            activity_type="gda.agentops.activity",
            attempt_no=2,
            schedule_to_close_timeout_seconds=600,
            start_to_close_timeout_seconds=300,
            heartbeat_timeout_seconds=30,
        )


def test_activity_schedule_validates_timeouts_cancellation_and_checkpoint_replay():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:data-product-plan:v1",
        key="tool-call:coordinator:schedule-checkpoint",
        side_effect=AgentSideEffect.DATA_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    with pytest.raises(ValueError, match="schedule-to-close"):
        harness.schedule_activity(
            workflow_id,
            call.tool_call_id,
            activity_type="gda.agentops.activity",
            schedule_to_close_timeout_seconds=60,
            start_to_close_timeout_seconds=120,
            heartbeat_timeout_seconds=30,
        )
    with pytest.raises(ValueError, match="wait for cancellation"):
        harness.schedule_activity(
            workflow_id,
            call.tool_call_id,
            activity_type="gda.agentops.activity",
            schedule_to_close_timeout_seconds=600,
            start_to_close_timeout_seconds=300,
            heartbeat_timeout_seconds=30,
            cancellation_type=TemporalActivityCancellationType.TRY_CANCEL,
        )
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
    )
    drifted = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=snapshot.activity_schedules[0].activity_id,
        idempotency_key="activity:schedule-checkpoint:drifted",
        side_effect=AgentSideEffect.NONE,
        outcome=TemporalActivityOutcome.FAILED,
        failure_type="ProviderTimeout",
    )
    with pytest.raises(TemporalContractError, match="schedule request"):
        harness.record_scheduled_activity(workflow_id, drifted)
    checkpoint = harness.checkpoint(workflow_id)
    restored = TemporalTaskGraphWorkflowHarness().restore_checkpoint(checkpoint)
    assert restored == snapshot
    assert restored.activity_schedules[0].schedule_sha256 == (
        snapshot.activity_schedules[0].schedule_sha256
    )


def test_activity_request_rejects_terminal_or_reconciling_tool_call():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:external-publish:v1",
        key="tool-call:coordinator:request-terminal",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    evidence = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=TOOL_CALL_2,
        idempotency_key="activity:request-terminal:unknown",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.UNKNOWN,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/request-terminal",
    )
    snapshot = harness.record_activity(workflow_id, evidence)
    with pytest.raises(TemporalContractError, match="reconciling"):
        harness.build_activity_request(workflow_id, call.tool_call_id)

    final = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=TOOL_CALL_2,
        idempotency_key="activity:request-terminal:reconciled",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.SUCCEEDED,
        output_artifact_id=ARTIFACT_1,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/request-terminal",
    )
    snapshot = harness.record_activity(workflow_id, final)
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.SUCCEEDED
    with pytest.raises(TemporalContractError, match="succeeded"):
        harness.build_activity_request(workflow_id, call.tool_call_id)


def test_mmfe_and_gwm_activity_requests_remain_bound_to_their_graph_steps():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    coordinator, planner, data_engineer, mmfe, gwm, _quality = workflow_input.task_graph.steps
    for step in (coordinator, planner, data_engineer):
        harness.start_step(workflow_id, step.step_id)
        harness.complete_step(workflow_id, step_id=step.step_id)
    requests = []
    for step, tool_ref, key in (
        (mmfe, "tool:mmfe:semantic-fusion:v1", "tool-call:mmfe"),
        (gwm, "tool:gwm:observation:v1", "tool-call:gwm"),
    ):
        snapshot = harness.start_step(workflow_id, step.step_id)
        snapshot = harness.bind_tool_call(
            workflow_id,
            step_id=step.step_id,
            tool_ref=tool_ref,
            capability_ref="capability:data_product.execute:v1",
            subject_context=_subject(),
            side_effect=AgentSideEffect.EXTERNAL_WRITE,
            policy_decision_ref="artifact://policy-decision-agent-run",
            idempotency_key=key,
        )
        call = snapshot.execution.tool_calls[-1]
        harness.dispatch_tool_call(workflow_id, call.tool_call_id)
        requests.append(harness.build_activity_request(workflow_id, call.tool_call_id))
    assert requests[0].step_id == mmfe.step_id
    assert requests[0].tool_ref == "tool:mmfe:semantic-fusion:v1"
    assert requests[1].step_id == gwm.step_id
    assert requests[1].tool_ref == "tool:gwm:observation:v1"


def test_unknown_activity_reconciles_then_accepts_new_receipt_without_retrying():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:external-publish:v1",
        key="tool-call:coordinator:publish",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
    )
    call = snapshot.execution.tool_calls[0]
    unknown = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=TOOL_CALL_2,
        idempotency_key="activity:coordinator:publish:attempt-1",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.UNKNOWN,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/unknown-1",
    )
    snapshot = harness.record_activity(workflow_id, unknown)
    assert snapshot.workflow.run.status.value == "reconciling"
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.RECONCILING

    final = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=TOOL_CALL_2,
        idempotency_key="activity:coordinator:publish:reconcile-1",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.SUCCEEDED,
        output_artifact_id=ARTIFACT_1,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/unknown-1",
    )
    snapshot = harness.record_activity(workflow_id, final)
    assert snapshot.workflow.run.status.value == "running"
    assert snapshot.execution.tool_calls[0].status is AgentToolCallStatus.SUCCEEDED

    changed = unknown.model_dump(mode="json")
    changed["provider_operation_ref"] = "provider://operation/other"
    changed["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, changed, "evidence_sha256"
    )
    with pytest.raises(TemporalContractError, match="different evidence"):
        harness.record_activity(workflow_id, TemporalActivityEvidence(**changed))


def test_parallel_success_does_not_clear_another_tool_calls_unknown_outcome():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    coordinator, planner, _data_engineer, fusion, gwm, _quality = (
        workflow_input.task_graph.steps
    )
    for step in (coordinator, planner):
        harness.start_step(workflow_id, step.step_id)
        harness.complete_step(workflow_id, step_id=step.step_id)

    calls = []
    for step, tool_ref in (
        (fusion, "tool:mmfe:semantic-fusion:v1"),
        (gwm, "tool:gwm:observation:v1"),
    ):
        harness.start_step(workflow_id, step.step_id)
        snapshot = harness.bind_tool_call(
            workflow_id,
            step_id=step.step_id,
            tool_ref=tool_ref,
            capability_ref="capability:data_product.execute:v1",
            subject_context=_subject(),
            side_effect=AgentSideEffect.EXTERNAL_WRITE,
            policy_decision_ref="artifact://policy-decision-agent-run",
            idempotency_key=f"tool-call:parallel:{step.agent_id}",
        )
        call = snapshot.execution.tool_calls[-1]
        harness.dispatch_tool_call(workflow_id, call.tool_call_id)
        calls.append(call)

    unknown = _evidence(
        workflow_input,
        tool_call_id=calls[0].tool_call_id,
        activity_id=TOOL_CALL_1,
        idempotency_key="activity:parallel:fusion:unknown",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.UNKNOWN,
        external_receipt_artifact_id=ARTIFACT_2,
        provider_operation_ref="provider://operation/fusion-unknown",
    )
    harness.record_activity(workflow_id, unknown)
    succeeded = _evidence(
        workflow_input,
        tool_call_id=calls[1].tool_call_id,
        activity_id=TOOL_CALL_2,
        idempotency_key="activity:parallel:gwm:succeeded",
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        outcome=TemporalActivityOutcome.SUCCEEDED,
        output_artifact_id=ARTIFACT_1,
        external_receipt_artifact_id=ARTIFACT_2,
    )

    snapshot = harness.record_activity(workflow_id, succeeded)

    assert snapshot.workflow.run.status is AgentRunStatus.RECONCILING
    assert tuple(call.status for call in snapshot.execution.tool_calls) == (
        AgentToolCallStatus.RECONCILING,
        AgentToolCallStatus.SUCCEEDED,
    )


def test_workflow_harness_closes_run_only_after_graph_fan_in():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)

    for step in workflow_input.task_graph.steps:
        snapshot = harness.start_step(workflow_id, step.step_id)
        snapshot = harness.complete_step(workflow_id, step_id=step.step_id)
        if step.agent_id != "quality":
            assert snapshot.workflow.run.status.value == "running"
    assert snapshot.workflow.run.status.value == "succeeded"
    assert all(item.status.value == "succeeded" for item in snapshot.execution.step_states)


def test_failed_activity_requires_explicit_step_failure_projection():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    snapshot = _bind_and_dispatch(
        harness,
        workflow_input,
        step_id=coordinator.step_id,
        tool_ref="tool:unstable:v1",
        key="tool-call:coordinator:unstable",
        side_effect=AgentSideEffect.NONE,
    )
    call = snapshot.execution.tool_calls[0]
    evidence = _evidence(
        workflow_input,
        tool_call_id=call.tool_call_id,
        activity_id=UUID("00000000-0000-4000-8000-000000001113"),
        idempotency_key="activity:coordinator:unstable:1",
        side_effect=AgentSideEffect.NONE,
        outcome=TemporalActivityOutcome.FAILED,
        failure_type="ProviderTimeout",
    )
    snapshot = harness.record_activity(workflow_id, evidence)
    assert snapshot.workflow.run.status.value == "running"
    snapshot = harness.fail_step(workflow_id, coordinator.step_id)
    assert snapshot.workflow.run.status.value == "failed"
    assert snapshot.execution.step_states[0].status.value == "failed"


def test_checkpoint_round_trip_restores_and_replays_task_graph_projection():
    workflow_input = _input()
    workflow_id = workflow_input.identity.workflow_id
    coordinator = workflow_input.task_graph.steps[0]
    planner = workflow_input.task_graph.steps[1]
    source = TemporalTaskGraphWorkflowHarness()
    source.start(workflow_input)
    before_checkpoint = source.start_step(workflow_id, coordinator.step_id)
    checkpoint = source.checkpoint(workflow_id)

    restored = TemporalTaskGraphWorkflowHarness()
    replayed = restored.restore_checkpoint(checkpoint)
    assert replayed == before_checkpoint
    assert replayed.execution.graph.graph_sha256 == workflow_input.task_graph.graph_sha256
    with pytest.raises(ValueError, match="dependencies"):
        restored.start_step(workflow_id, planner.step_id)

    restored.complete_step(workflow_id, step_id=coordinator.step_id)
    resumed = restored.start_step(workflow_id, planner.step_id)
    assert resumed.workflow.run.status is AgentRunStatus.RUNNING
    assert resumed.execution.step_states[1].status.value == "running"


def test_checkpoint_restores_signal_idempotency_index():
    workflow_input = _input()
    workflow_id = workflow_input.identity.workflow_id
    source = TemporalTaskGraphWorkflowHarness()
    source.start(workflow_input)
    source.start_step(workflow_id, workflow_input.task_graph.steps[0].step_id)
    signal = _signal(
        workflow_input,
        kind=TemporalSignalKind.PAUSE,
        expected_state_version=1,
    )
    paused = source.apply_signal(signal)
    checkpoint = source.checkpoint(workflow_id)

    restored = TemporalTaskGraphWorkflowHarness()
    assert restored.restore_checkpoint(checkpoint) == paused
    assert restored.apply_signal(signal) == paused
    changed = signal.model_dump(mode="json")
    changed["reason"] = "different reason"
    changed["signal_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_SIGNAL_SCHEMA, changed, "signal_sha256"
    )
    with pytest.raises(TemporalContractError, match="reused"):
        restored.apply_signal(TemporalSignal(**changed))


def test_checkpoint_rejects_run_state_that_does_not_match_history():
    workflow_input = _input()
    workflow_id = workflow_input.identity.workflow_id
    harness = TemporalTaskGraphWorkflowHarness()
    harness.start(workflow_input)
    harness.start_step(workflow_id, workflow_input.task_graph.steps[0].step_id)
    checkpoint = harness.checkpoint(workflow_id)
    values = checkpoint.model_dump(mode="json")
    run_values = dict(values["run"])
    run_values["status"] = AgentRunStatus.FAILED.value
    run_values["run_sha256"] = agent_run_fingerprint(run_values)
    values["run"] = run_values
    values["checkpoint_sha256"] = temporal_contract_fingerprint(
        checkpoint.schema_id, values, "checkpoint_sha256"
    )
    with pytest.raises(ValueError, match="latest transition"):
        TemporalTaskGraphWorkflowCheckpoint(**values)


def test_checkpoint_rejects_activity_evidence_without_execution_tool_call():
    workflow_input = _input()
    workflow_id = workflow_input.identity.workflow_id
    harness = TemporalTaskGraphWorkflowHarness()
    harness.start(workflow_input)
    checkpoint = harness.checkpoint(workflow_id)
    values = checkpoint.model_dump(mode="json")
    evidence_values = _evidence(
        workflow_input,
        tool_call_id=TOOL_CALL_1,
        activity_id=TOOL_CALL_1,
        idempotency_key="activity:orphan",
        side_effect=AgentSideEffect.NONE,
        outcome=TemporalActivityOutcome.FAILED,
        failure_type="ProviderTimeout",
    ).model_dump(mode="json")
    values["activity_evidence"] = [evidence_values]
    values["checkpoint_sha256"] = temporal_contract_fingerprint(
        checkpoint.schema_id, values, "checkpoint_sha256"
    )
    with pytest.raises(ValueError, match="unknown tool call"):
        TemporalTaskGraphWorkflowCheckpoint(**values)


def test_temporal_integration_restore_rejects_inconsistent_snapshot():
    workflow_input = _input()
    workflow_id = workflow_input.identity.workflow_id
    harness = TemporalTaskGraphWorkflowHarness()
    harness.start(workflow_input)
    checkpoint = harness.checkpoint(workflow_id)
    restored_temporal = TemporalIntegrationHarness()
    invalid = checkpoint.run.model_copy(update={"state_version": 99})
    from data_agent.agentops_temporal_contracts import TemporalWorkflowSnapshot

    snapshot = TemporalWorkflowSnapshot(
        workflow_input=checkpoint.workflow_input,
        run=invalid,
        history=checkpoint.history,
        activity_evidence=checkpoint.activity_evidence,
        signals=checkpoint.signals,
    )
    with pytest.raises(TemporalContractError, match="state version"):
        restored_temporal.restore(snapshot)
