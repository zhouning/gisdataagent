"""Deterministic task-graph workflow projection for the AgentOps Temporal boundary.

This module composes the provider-neutral Temporal harness with the immutable task graph and
execution projection. It deliberately does not schedule work, invoke a model, or call a real
Temporal SDK; a provider worker can replay the same transitions and receipts later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic import model_validator

from .agentops_contracts import (
    AgentRun,
    AgentRunStatus,
    AgentSideEffect,
    AgentToolCallStatus,
)
from .agentops_task_execution import (
    AgentTaskExecutionState,
    bind_tool_call,
    complete_step,
    deny_step_after_review,
    fail_step,
    initial_execution_state,
    resume_step_after_review,
    settle_tool_call,
    start_step,
    wait_step_for_review,
)
from .agentops_temporal_adapter import TemporalActivityAdapter
from .agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
    TemporalActivityCancellationType,
    TemporalActivityEvidence,
    TemporalActivityOutcome,
    TemporalActivityRequest,
    TemporalActivitySchedulePlan,
    TemporalContractError,
    TemporalIntegrationHarness,
    TemporalProviderExecutionSpec,
    TemporalSignal,
    TemporalStateTransition,
    TemporalWorkflowInput,
    TemporalWorkflowSnapshot,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from .platform_contracts import FrozenContract, NonEmptyText, Sha256, SubjectContext

AGENTOPS_WORKFLOW_CHECKPOINT_SCHEMA = "gda.agentops_temporal_workflow_checkpoint.v2"


@dataclass(frozen=True)
class TemporalTaskGraphWorkflowSnapshot:
    """Joint Temporal/run and task execution projection for one workflow."""

    workflow: TemporalWorkflowSnapshot
    execution: AgentTaskExecutionState
    activity_schedules: tuple[TemporalActivitySchedulePlan, ...] = ()


class TemporalTaskGraphWorkflowCheckpoint(FrozenContract):
    """Hash-bound durable checkpoint for deterministic workflow recovery."""

    schema_id: ClassVar[str] = AGENTOPS_WORKFLOW_CHECKPOINT_SCHEMA
    workflow_input: TemporalWorkflowInput
    run: AgentRun
    history: tuple[TemporalStateTransition, ...]
    activity_evidence: tuple[TemporalActivityEvidence, ...]
    signals: tuple[TemporalSignal, ...] = ()
    execution: AgentTaskExecutionState
    activity_schedules: tuple[TemporalActivitySchedulePlan, ...] = ()
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_checkpoint(self) -> TemporalTaskGraphWorkflowCheckpoint:
        workflow_id = self.workflow_input.identity.workflow_id
        if self.run.tenant_id != self.workflow_input.tenant_id:
            raise ValueError("checkpoint run tenant differs from workflow input")
        if self.run.run_id != self.workflow_input.agent_run.run_id:
            raise ValueError("checkpoint run differs from workflow input")
        if self.execution.tenant_id != self.workflow_input.tenant_id:
            raise ValueError("checkpoint execution tenant differs from workflow input")
        if self.execution.run_id != self.run.run_id:
            raise ValueError("checkpoint execution run differs from checkpoint run")
        if self.execution.graph != self.workflow_input.task_graph:
            raise ValueError("checkpoint execution graph differs from workflow input graph")
        if not self.history:
            raise ValueError("checkpoint history cannot be empty")
        for expected_sequence, event in enumerate(self.history):
            if (
                event.sequence_no != expected_sequence
                or event.tenant_id != self.workflow_input.tenant_id
                or event.workflow_id != workflow_id
                or event.run_id != self.run.run_id
            ):
                raise ValueError("checkpoint history is not contiguous or correlated")
        latest = self.history[-1]
        if latest.to_status is not self.run.status or latest.sequence_no != self.run.state_version:
            raise ValueError("checkpoint run does not match the latest transition")
        signal_ids = tuple(signal.signal_id for signal in self.signals)
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("checkpoint signal ids must be unique")
        for signal in self.signals:
            if (
                signal.tenant_id != self.workflow_input.tenant_id
                or signal.workflow_id != workflow_id
                or signal.run_id != self.run.run_id
            ):
                raise ValueError("checkpoint signal correlation differs from workflow")
        evidence_keys = tuple(evidence.idempotency_key for evidence in self.activity_evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("checkpoint activity keys must be unique")
        for evidence in self.activity_evidence:
            if (
                evidence.tenant_id != self.workflow_input.tenant_id
                or evidence.workflow_id != workflow_id
                or evidence.run_id != self.run.run_id
            ):
                raise ValueError("checkpoint activity correlation differs from workflow")
            if not any(
                call.tool_call_id == evidence.tool_call_id for call in self.execution.tool_calls
            ):
                raise ValueError("checkpoint activity evidence references an unknown tool call")
        schedule_ids = tuple(schedule.activity_id for schedule in self.activity_schedules)
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("checkpoint activity schedule ids must be unique")
        schedule_attempts = tuple(
            (schedule.tool_call_id, schedule.attempt_no) for schedule in self.activity_schedules
        )
        if len(schedule_attempts) != len(set(schedule_attempts)):
            raise ValueError("checkpoint tool-call activity attempts must be unique")
        for schedule in self.activity_schedules:
            if (
                schedule.tenant_id != self.workflow_input.tenant_id
                or schedule.workflow_id != workflow_id
                or schedule.run_id != self.run.run_id
            ):
                raise ValueError("checkpoint activity schedule correlation differs")
            if (
                schedule.task_queue_ref != self.workflow_input.identity.task_queue.queue_ref
                or schedule.task_queue_sha256
                != self.workflow_input.identity.task_queue.queue_sha256
            ):
                raise ValueError("checkpoint activity schedule task queue differs")
            if not any(
                call.tool_call_id == schedule.tool_call_id and call.step_id == schedule.step_id
                for call in self.execution.tool_calls
            ):
                raise ValueError("checkpoint activity schedule references an unknown tool call")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "checkpoint_sha256"
        )
        if self.checkpoint_sha256 != expected:
            raise ValueError("checkpoint_sha256 does not match checkpoint content")
        return self


class TemporalTaskGraphWorkflowHarness:
    """Provider-neutral workflow boundary for one immutable AgentTaskGraph."""

    def __init__(self) -> None:
        self._temporal = TemporalIntegrationHarness()
        self._snapshots: dict[str, TemporalTaskGraphWorkflowSnapshot] = {}

    def start(self, workflow_input: TemporalWorkflowInput) -> TemporalTaskGraphWorkflowSnapshot:
        workflow = self._temporal.start(workflow_input)
        existing = self._snapshots.get(workflow_input.identity.workflow_id)
        if existing is not None:
            return existing
        snapshot = TemporalTaskGraphWorkflowSnapshot(
            workflow=workflow,
            execution=initial_execution_state(workflow_input.task_graph),
        )
        self._snapshots[workflow_input.identity.workflow_id] = snapshot
        return snapshot

    def get(self, workflow_id: str) -> TemporalTaskGraphWorkflowSnapshot:
        try:
            return self._snapshots[workflow_id]
        except KeyError as exc:
            raise TemporalContractError(f"unknown task graph workflow: {workflow_id}") from exc

    def apply_signal(self, signal: TemporalSignal) -> TemporalTaskGraphWorkflowSnapshot:
        """Apply a durable signal while retaining the execution projection."""

        snapshot = self.get(signal.workflow_id)
        workflow = self._temporal.apply_signal(signal)
        return self._store(
            signal.workflow_id,
            workflow=workflow,
            execution=snapshot.execution,
        )

    def checkpoint(self, workflow_id: str) -> TemporalTaskGraphWorkflowCheckpoint:
        """Create a hash-bound checkpoint suitable for durable storage."""

        snapshot = self.get(workflow_id)
        values = {
            "workflow_input": snapshot.workflow.workflow_input,
            "run": snapshot.workflow.run,
            "history": snapshot.workflow.history,
            "activity_evidence": snapshot.workflow.activity_evidence,
            "signals": snapshot.workflow.signals,
            "execution": snapshot.execution,
            "activity_schedules": snapshot.activity_schedules,
        }
        values["checkpoint_sha256"] = temporal_contract_fingerprint(
            AGENTOPS_WORKFLOW_CHECKPOINT_SCHEMA,
            values,
            "checkpoint_sha256",
        )
        return TemporalTaskGraphWorkflowCheckpoint(**values)

    def restore_checkpoint(
        self, checkpoint: TemporalTaskGraphWorkflowCheckpoint
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Restore a validated checkpoint into this harness."""

        workflow_id = checkpoint.workflow_input.identity.workflow_id
        workflow = TemporalWorkflowSnapshot(
            workflow_input=checkpoint.workflow_input,
            run=checkpoint.run,
            history=checkpoint.history,
            activity_evidence=checkpoint.activity_evidence,
            signals=checkpoint.signals,
        )
        self._temporal.restore(workflow)
        return self._store(
            workflow_id,
            workflow=workflow,
            execution=checkpoint.execution,
            activity_schedules=checkpoint.activity_schedules,
        )

    def _store(
        self,
        workflow_id: str,
        *,
        workflow: TemporalWorkflowSnapshot,
        execution: AgentTaskExecutionState,
        activity_schedules: tuple[TemporalActivitySchedulePlan, ...] | None = None,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        existing = self._snapshots.get(workflow_id)
        snapshot = TemporalTaskGraphWorkflowSnapshot(
            workflow=workflow,
            execution=execution,
            activity_schedules=(
                activity_schedules
                if activity_schedules is not None
                else existing.activity_schedules
                if existing is not None
                else ()
            ),
        )
        self._snapshots[workflow_id] = snapshot
        return snapshot

    def start_step(self, workflow_id: str, step_id: UUID) -> TemporalTaskGraphWorkflowSnapshot:
        """Start a graph step after its dependencies have succeeded."""

        snapshot = self.get(workflow_id)
        step = next(
            (item for item in snapshot.execution.step_states if item.step_id == step_id),
            None,
        )
        if step is None:
            raise TemporalContractError(f"unknown task step: {step_id}")
        if step.status.value == "running":
            return snapshot
        if snapshot.workflow.run.status in {
            AgentRunStatus.WAITING_REVIEW,
            AgentRunStatus.PAUSED,
            AgentRunStatus.RECONCILING,
        }:
            raise TemporalContractError(
                f"cannot start a task step while run is {snapshot.workflow.run.status.value}"
            )
        execution = start_step(snapshot.execution, step_id)
        workflow = snapshot.workflow
        if workflow.run.status is AgentRunStatus.ACCEPTED:
            workflow = self._temporal.transition(
                workflow_id,
                AgentRunStatus.PLANNING,
                actor_ref="workload:agentops-workflow",
                reason="task graph step started",
            )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def bind_tool_call(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        tool_ref: NonEmptyText,
        capability_ref: NonEmptyText,
        subject_context: SubjectContext,
        side_effect: AgentSideEffect,
        policy_decision_ref: NonEmptyText,
        idempotency_key: NonEmptyText,
        input_artifact_ids: tuple[UUID, ...] = (),
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Bind an idempotent tool call and move a planning run to running."""

        snapshot = self.get(workflow_id)
        execution = bind_tool_call(
            snapshot.execution,
            step_id=step_id,
            tool_ref=tool_ref,
            capability_ref=capability_ref,
            subject_context=subject_context,
            side_effect=side_effect,
            policy_decision_ref=policy_decision_ref,
            idempotency_key=idempotency_key,
            input_artifact_ids=input_artifact_ids,
        )
        workflow = snapshot.workflow
        if workflow.run.status is AgentRunStatus.PLANNING:
            workflow = self._temporal.transition(
                workflow_id,
                AgentRunStatus.RUNNING,
                actor_ref="workload:agentops-workflow",
                reason="tool call dispatched from task graph",
            )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def wait_for_review(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        tool_call_id: UUID,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Hold one high-risk ToolCall before provider dispatch."""

        snapshot = self.get(workflow_id)
        execution = wait_step_for_review(
            snapshot.execution,
            step_id=step_id,
            tool_call_id=tool_call_id,
        )
        workflow = self._temporal.transition(
            workflow_id,
            AgentRunStatus.WAITING_REVIEW,
            actor_ref="workload:agentops-workflow",
            reason="high-risk task graph step requires authoritative ApprovalCase",
        )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def resume_after_review(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        tool_call_id: UUID,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Resume an approved ToolCall after the run signal transition."""

        snapshot = self.get(workflow_id)
        if snapshot.workflow.run.status is not AgentRunStatus.RUNNING:
            raise TemporalContractError("approval signal must resume the run first")
        execution = resume_step_after_review(
            snapshot.execution,
            step_id=step_id,
            tool_call_id=tool_call_id,
        )
        return self._store(
            workflow_id,
            workflow=snapshot.workflow,
            execution=execution,
        )

    def deny_after_review(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        tool_call_id: UUID,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Project a rejected ToolCall after the run signal cancels execution."""

        snapshot = self.get(workflow_id)
        if snapshot.workflow.run.status is not AgentRunStatus.CANCELLED:
            raise TemporalContractError("rejection signal must cancel the run first")
        execution = deny_step_after_review(
            snapshot.execution,
            step_id=step_id,
            tool_call_id=tool_call_id,
        )
        return self._store(
            workflow_id,
            workflow=snapshot.workflow,
            execution=execution,
        )

    def cancel_after_review(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        tool_call_id: UUID,
        actor_ref: str,
        reason: str,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Project an authoritative ApprovalCase expiry before provider dispatch."""

        snapshot = self.get(workflow_id)
        if snapshot.workflow.run.status is not AgentRunStatus.WAITING_REVIEW:
            raise TemporalContractError("expiry cancellation requires a waiting review")
        workflow = self._temporal.transition(
            workflow_id,
            AgentRunStatus.CANCELLED,
            actor_ref=actor_ref,
            reason=reason,
        )
        execution = deny_step_after_review(
            snapshot.execution,
            step_id=step_id,
            tool_call_id=tool_call_id,
        )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def dispatch_tool_call(
        self, workflow_id: str, tool_call_id: UUID
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Record the provider dispatch boundary without executing the provider."""

        snapshot = self.get(workflow_id)
        call = next(
            (item for item in snapshot.execution.tool_calls if item.tool_call_id == tool_call_id),
            None,
        )
        if call is None:
            raise TemporalContractError(f"unknown tool call: {tool_call_id}")
        if call.status in {
            AgentToolCallStatus.RUNNING,
            AgentToolCallStatus.RECONCILING,
            AgentToolCallStatus.SUCCEEDED,
        }:
            return snapshot
        execution = settle_tool_call(
            snapshot.execution,
            tool_call_id=tool_call_id,
            status=AgentToolCallStatus.RUNNING,
        )
        return self._store(workflow_id, workflow=snapshot.workflow, execution=execution)

    def build_activity_request(
        self,
        workflow_id: str,
        tool_call_id: UUID,
        *,
        attempt_no: int = 1,
        provider_spec: TemporalProviderExecutionSpec | None = None,
    ) -> TemporalActivityRequest:
        """Build a deterministic provider dispatch request from the current projection.

        The request is an input boundary only. It never advances ToolCall state or invokes a
        provider; the provider receipt must return through ``record_activity``.
        """

        snapshot = self.get(workflow_id)
        call = next(
            (item for item in snapshot.execution.tool_calls if item.tool_call_id == tool_call_id),
            None,
        )
        if call is None:
            raise TemporalContractError(f"unknown tool call: {tool_call_id}")
        if call.status not in {
            AgentToolCallStatus.REQUESTED,
            AgentToolCallStatus.RUNNING,
        }:
            raise TemporalContractError(f"cannot dispatch tool call from {call.status.value} state")
        if attempt_no < 1:
            raise TemporalContractError("activity attempt_no must be positive")
        max_attempts = snapshot.workflow.workflow_input.retry_policy.max_attempts
        if max_attempts and attempt_no > max_attempts:
            raise TemporalContractError(
                f"activity attempt_no {attempt_no} exceeds retry policy max_attempts {max_attempts}"
            )
        activity_id = derive_temporal_activity_id(
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            attempt_no=attempt_no,
        )
        values = {
            "tenant_id": snapshot.workflow.workflow_input.tenant_id,
            "workflow_id": workflow_id,
            "run_id": call.run_id,
            "step_id": call.step_id,
            "tool_call_id": call.tool_call_id,
            "activity_id": activity_id,
            "attempt_no": attempt_no,
            "tool_ref": call.tool_ref,
            "capability_ref": call.capability_ref,
            "policy_decision_ref": call.policy_decision_ref,
            "subject_context": call.subject_context,
            "side_effect": call.side_effect,
            "idempotency_key": call.idempotency_key,
            "input_artifact_ids": call.input_artifact_ids,
        }
        if provider_spec is not None:
            values["provider_spec"] = provider_spec
        values["request_sha256"] = temporal_contract_fingerprint(
            TemporalActivityRequest.schema_id,
            values,
            "request_sha256",
        )
        return TemporalActivityRequest(**values)

    def schedule_activity(
        self,
        workflow_id: str,
        tool_call_id: UUID,
        *,
        activity_type: str,
        attempt_no: int = 1,
        schedule_to_close_timeout_seconds: float,
        start_to_close_timeout_seconds: float,
        heartbeat_timeout_seconds: float,
        provider_spec: TemporalProviderExecutionSpec | None = None,
        cancellation_type: TemporalActivityCancellationType = (
            TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
        ),
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Persist one explicit activity attempt plan without invoking the provider."""

        snapshot = self.get(workflow_id)
        call = next(
            (item for item in snapshot.execution.tool_calls if item.tool_call_id == tool_call_id),
            None,
        )
        if call is None:
            raise TemporalContractError(f"unknown tool call: {tool_call_id}")
        request = self.build_activity_request(
            workflow_id,
            tool_call_id,
            attempt_no=attempt_no,
            provider_spec=provider_spec,
        )
        values = {
            "tenant_id": request.tenant_id,
            "workflow_id": request.workflow_id,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "tool_call_id": request.tool_call_id,
            "activity_id": request.activity_id,
            "attempt_no": request.attempt_no,
            "activity_type": activity_type,
            "task_queue_ref": snapshot.workflow.workflow_input.identity.task_queue.queue_ref,
            "task_queue_sha256": (
                snapshot.workflow.workflow_input.identity.task_queue.queue_sha256
            ),
            "request": request,
            "request_sha256": request.request_sha256,
            "schedule_to_close_timeout_seconds": float(schedule_to_close_timeout_seconds),
            "start_to_close_timeout_seconds": float(start_to_close_timeout_seconds),
            "heartbeat_timeout_seconds": float(heartbeat_timeout_seconds),
            "cancellation_type": cancellation_type,
            "sdk_maximum_attempts": 1,
        }
        values["schedule_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA, values, "schedule_sha256"
        )
        plan = TemporalActivitySchedulePlan(**values)
        existing = next(
            (item for item in snapshot.activity_schedules if item.activity_id == plan.activity_id),
            None,
        )
        if existing is not None:
            if existing != plan:
                raise TemporalContractError(
                    "activity attempt was rescheduled with different options"
                )
            return snapshot
        if attempt_no > 1:
            previous = next(
                (
                    item
                    for item in snapshot.activity_schedules
                    if item.tool_call_id == tool_call_id and item.attempt_no == attempt_no - 1
                ),
                None,
            )
            if previous is None:
                raise TemporalContractError("activity attempts must be scheduled sequentially")
            previous_evidence = next(
                (
                    item
                    for item in snapshot.workflow.activity_evidence
                    if item.activity_id == previous.activity_id
                ),
                None,
            )
            if (
                previous_evidence is None
                or previous_evidence.outcome is not TemporalActivityOutcome.FAILED
            ):
                raise TemporalContractError(
                    "next activity attempt requires definitive failed evidence"
                )
        if call.status is AgentToolCallStatus.REQUESTED:
            snapshot = self.dispatch_tool_call(workflow_id, tool_call_id)
        return self._store(
            workflow_id,
            workflow=snapshot.workflow,
            execution=snapshot.execution,
            activity_schedules=(*snapshot.activity_schedules, plan),
        )

    def record_scheduled_activity(
        self, workflow_id: str, evidence: TemporalActivityEvidence
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Apply evidence against a persisted schedule and preserve explicit retry state."""

        snapshot = self.get(workflow_id)
        plan = next(
            (
                item
                for item in snapshot.activity_schedules
                if item.activity_id == evidence.activity_id
            ),
            None,
        )
        if plan is None:
            raise TemporalContractError("activity evidence has no persisted schedule plan")
        if evidence.tool_call_id != plan.tool_call_id:
            raise TemporalContractError("activity evidence differs from schedule plan")
        request = plan.request
        if (
            evidence.tenant_id != request.tenant_id
            or evidence.workflow_id != request.workflow_id
            or evidence.run_id != request.run_id
            or evidence.policy_decision_ref != request.policy_decision_ref
            or evidence.side_effect != request.side_effect
        ):
            raise TemporalContractError("activity evidence differs from schedule request")
        if evidence.outcome is not TemporalActivityOutcome.FAILED:
            return self.record_activity(workflow_id, evidence)
        existing = next(
            (
                item
                for item in snapshot.workflow.activity_evidence
                if item.idempotency_key == evidence.idempotency_key
            ),
            None,
        )
        if existing is not None:
            if existing != evidence:
                raise TemporalContractError(
                    "activity idempotency key was reused with different evidence"
                )
            return snapshot
        max_attempts = snapshot.workflow.workflow_input.retry_policy.max_attempts
        retry_available = (
            evidence.failure_type
            not in snapshot.workflow.workflow_input.retry_policy.non_retryable_error_types
            and (max_attempts == 0 or plan.attempt_no < max_attempts)
        )
        if not retry_available:
            return self.record_activity(workflow_id, evidence)
        call = next(
            item for item in snapshot.execution.tool_calls if item.tool_call_id == plan.tool_call_id
        )
        if call.status is not AgentToolCallStatus.RUNNING:
            raise TemporalContractError("definitive retry evidence requires a running tool call")
        workflow = self._temporal.record_activity(workflow_id, evidence)
        return self._store(
            workflow_id,
            workflow=workflow,
            execution=snapshot.execution,
        )

    def dispatch_activity(
        self,
        workflow_id: str,
        tool_call_id: UUID,
        adapter: TemporalActivityAdapter,
        *,
        attempt_no: int = 1,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Dispatch one activity through the adapter and apply its typed receipt."""

        snapshot = self.get(workflow_id)
        call = next(
            (item for item in snapshot.execution.tool_calls if item.tool_call_id == tool_call_id),
            None,
        )
        if call is None:
            raise TemporalContractError(f"unknown tool call: {tool_call_id}")
        if call.status is AgentToolCallStatus.REQUESTED:
            snapshot = self.dispatch_tool_call(workflow_id, tool_call_id)
        request = self.build_activity_request(workflow_id, tool_call_id, attempt_no=attempt_no)
        evidence = adapter.dispatch(request)
        return self.record_activity(workflow_id, evidence)

    async def dispatch_activity_async(
        self,
        workflow_id: str,
        tool_call_id: UUID,
        adapter: TemporalActivityAdapter,
        *,
        attempt_no: int = 1,
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Async counterpart for an SDK-backed activity worker boundary."""

        snapshot = self.get(workflow_id)
        call = next(
            (item for item in snapshot.execution.tool_calls if item.tool_call_id == tool_call_id),
            None,
        )
        if call is None:
            raise TemporalContractError(f"unknown tool call: {tool_call_id}")
        if call.status is AgentToolCallStatus.REQUESTED:
            snapshot = self.dispatch_tool_call(workflow_id, tool_call_id)
        request = self.build_activity_request(workflow_id, tool_call_id, attempt_no=attempt_no)
        evidence = await adapter.dispatch_async(request)
        return self.record_activity(workflow_id, evidence)

    def record_activity(
        self, workflow_id: str, evidence: TemporalActivityEvidence
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Apply a typed provider receipt to the matching ToolCall and run projection."""

        snapshot = self.get(workflow_id)
        existing = next(
            (
                item
                for item in snapshot.workflow.activity_evidence
                if item.idempotency_key == evidence.idempotency_key
            ),
            None,
        )
        if existing is not None:
            if existing != evidence:
                raise TemporalContractError(
                    "activity idempotency key was reused with different evidence"
                )
            return snapshot
        call = next(
            (
                item
                for item in snapshot.execution.tool_calls
                if item.tool_call_id == evidence.tool_call_id
            ),
            None,
        )
        if call is None:
            raise TemporalContractError("activity evidence references an unknown tool call")
        if call.policy_decision_ref != evidence.policy_decision_ref:
            raise TemporalContractError("activity policy decision differs from tool call")
        if call.status not in {
            AgentToolCallStatus.RUNNING,
            AgentToolCallStatus.RECONCILING,
        }:
            raise TemporalContractError(
                "activity evidence requires a running or reconciling tool call"
            )

        if evidence.outcome is TemporalActivityOutcome.SUCCEEDED:
            execution = settle_tool_call(
                snapshot.execution,
                tool_call_id=call.tool_call_id,
                status=AgentToolCallStatus.SUCCEEDED,
                output_artifact_id=evidence.output_artifact_id,
                external_receipt_artifact_id=evidence.external_receipt_artifact_id,
            )
        elif evidence.outcome is TemporalActivityOutcome.FAILED:
            execution = settle_tool_call(
                snapshot.execution,
                tool_call_id=call.tool_call_id,
                status=AgentToolCallStatus.FAILED,
            )
        else:
            execution = settle_tool_call(
                snapshot.execution,
                tool_call_id=call.tool_call_id,
                status=AgentToolCallStatus.RECONCILING,
                external_receipt_artifact_id=evidence.external_receipt_artifact_id,
            )

        workflow = self._temporal.record_activity(workflow_id, evidence)
        if (
            evidence.outcome is TemporalActivityOutcome.SUCCEEDED
            and workflow.run.status is AgentRunStatus.RECONCILING
            and not any(
                item.status is AgentToolCallStatus.RECONCILING for item in execution.tool_calls
            )
        ):
            workflow = self._temporal.transition(
                workflow_id,
                AgentRunStatus.RUNNING,
                actor_ref="workload:agentops-workflow",
                reason="provider outcome reconciled",
            )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def complete_step(
        self,
        workflow_id: str,
        *,
        step_id: UUID,
        output_artifact_ids: tuple[UUID, ...] = (),
    ) -> TemporalTaskGraphWorkflowSnapshot:
        """Complete a step and close the run only after every graph step succeeds."""

        snapshot = self.get(workflow_id)
        execution = complete_step(
            snapshot.execution,
            step_id=step_id,
            output_artifact_ids=output_artifact_ids,
        )
        workflow = snapshot.workflow
        if workflow.run.status is AgentRunStatus.PLANNING:
            workflow = self._temporal.transition(
                workflow_id,
                AgentRunStatus.RUNNING,
                actor_ref="workload:agentops-workflow",
                reason="task graph execution active",
            )
        if all(item.status.value == "succeeded" for item in execution.step_states):
            if workflow.run.status is AgentRunStatus.RUNNING:
                workflow = self._temporal.transition(
                    workflow_id,
                    AgentRunStatus.SUCCEEDED,
                    actor_ref="workload:agentops-workflow",
                    reason="all task graph steps succeeded",
                )
        return self._store(workflow_id, workflow=workflow, execution=execution)

    def fail_step(self, workflow_id: str, step_id: UUID) -> TemporalTaskGraphWorkflowSnapshot:
        """Fail a step and close the AgentRun without retrying an unknown side effect."""

        snapshot = self.get(workflow_id)
        execution = fail_step(snapshot.execution, step_id)
        workflow = snapshot.workflow
        if workflow.run.status not in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }:
            workflow = self._temporal.transition(
                workflow_id,
                AgentRunStatus.FAILED,
                actor_ref="workload:agentops-workflow",
                reason="task graph step failed",
            )
        return self._store(workflow_id, workflow=workflow, execution=execution)


__all__ = [
    "AGENTOPS_WORKFLOW_CHECKPOINT_SCHEMA",
    "TemporalTaskGraphWorkflowCheckpoint",
    "TemporalTaskGraphWorkflowHarness",
    "TemporalTaskGraphWorkflowSnapshot",
]
