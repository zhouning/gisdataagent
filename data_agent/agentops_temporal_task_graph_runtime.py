"""Temporal SDK workflow for one immutable multi-agent task graph.

Importing this module requires the pinned ``agentops-temporal`` dependency. The workflow
schedules graph-ready specialists in parallel waves, records every ToolCall/activity receipt
through the provider-neutral harness, and leaves DataOps scheduling and data truth outside
Temporal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .agentops_contracts import AgentStepStatus, AgentToolCallStatus
    from .agentops_provider_identity import derive_specialist_provider_receipt_ref
    from .agentops_temporal_adapter import (
        TemporalActivityAdapter,
        TemporalProviderActivityResult,
    )
    from .agentops_temporal_approval import (
        TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
        TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
        TEMPORAL_APPROVAL_QUERY_NAME,
        TEMPORAL_APPROVAL_SIGNAL_NAME,
        TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
        TemporalApprovalAuthorityVerifier,
        TemporalApprovalCaseCreationResult,
        TemporalApprovalExpiryResult,
        TemporalApprovalVerificationResult,
        TemporalStepApprovalBinding,
        TemporalStepApprovalInbox,
        TemporalStepApprovalSignal,
        build_temporal_approval_case_creation_result,
        build_temporal_approval_expiry_result,
        build_temporal_step_approval_case,
        derive_approval_expiry_activity_id,
        derive_approval_verification_activity_id,
    )
    from .agentops_temporal_contracts import (
        TemporalActivityOutcome,
        TemporalActivitySchedulePlan,
        TemporalSignal,
        temporal_contract_fingerprint,
    )
    from .agentops_temporal_task_graph_execution import (
        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
        TemporalTaskGraphExecutionInput,
    )
    from .agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
    from .agentops_temporalio_provider import (
        TemporalActivityExecutor,
        TemporalActivityWorkerHandler,
    )

TASK_GRAPH_WORKFLOW_TYPE = "gda.agentops.task_graph.v1"
TASK_GRAPH_WORKFLOW_RESULT_SCHEMA = "gda.agentops.task_graph_workflow_result.v2"


def build_specialist_activity_definition(
    executor: TemporalActivityExecutor,
) -> Callable[[dict[str, Any]], Any]:
    """Create the single typed activity definition used by all specialist roles."""

    handler = TemporalActivityWorkerHandler(executor)

    @activity.defn(name=TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE)
    async def specialist_activity(payload: dict[str, Any]) -> dict[str, Any]:
        heartbeat_details = {
            "activity_id": payload.get("activity_id"),
            "step_id": payload.get("step_id"),
        }
        activity.heartbeat(heartbeat_details)

        async def heartbeat_loop() -> None:
            # A single admission heartbeat is not enough for long-running provider
            # calls: Temporal only delivers activity cancellation while it receives
            # heartbeats. Keep the worker-side cancellation and provider settlement
            # path live without coupling domain executors to the Temporal SDK.
            while True:
                await asyncio.sleep(1)
                activity.heartbeat(heartbeat_details)

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        try:
            return await handler.handle_async(payload)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    return specialist_activity


def build_approval_verification_activity_definition(
    authority: Any,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[dict[str, Any]], Any]:
    """Create the read-only activity that reloads the canonical ApprovalCase."""

    verifier = TemporalApprovalAuthorityVerifier(authority, clock=clock)

    @activity.defn(name=TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE)
    async def verify_approval(payload: dict[str, Any]) -> dict[str, Any]:
        binding = TemporalStepApprovalBinding.model_validate(payload["binding"])
        signal = TemporalStepApprovalSignal.model_validate(payload["signal"])
        result = await asyncio.to_thread(verifier.verify, binding, signal)
        return result.model_dump(mode="json")

    return verify_approval


def build_approval_case_creation_activity_definition(
    authority: Any,
    *,
    expiry_seconds: float = 24 * 60 * 60,
) -> Callable[[dict[str, Any]], Any]:
    """Create the idempotent activity that submits pending cases to the authority."""

    @activity.defn(name=TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE)
    async def create_approval_case(payload: dict[str, Any]) -> dict[str, Any]:
        binding = TemporalStepApprovalBinding.model_validate(payload["binding"])
        requested_at = datetime.now(UTC)
        case = build_temporal_step_approval_case(
            binding,
            requested_at=requested_at,
            expires_at=requested_at + timedelta(seconds=expiry_seconds),
            request_reason=str(
                payload.get(
                    "request_reason",
                    "high-risk Temporal task graph step requires human review",
                )
            ),
        )
        stored = await asyncio.to_thread(
            authority.create,
            case,
            owner_ref=binding.approval_owner_ref,
        )
        stored_case = getattr(stored, "approval_case", stored)
        result = build_temporal_approval_case_creation_result(
            binding,
            stored_case,
            created=bool(getattr(stored, "created", True)),
        )
        return result.model_dump(mode="json")

    return create_approval_case


def build_approval_case_expiry_activity_definition(
    authority: Any,
) -> Callable[[dict[str, Any]], Any]:
    """Create the PostgreSQL-authoritative ApprovalCase expiry activity."""

    @activity.defn(name=TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE)
    async def expire_approval_case(payload: dict[str, Any]) -> dict[str, Any]:
        binding = TemporalStepApprovalBinding.model_validate(payload["binding"])
        actor = str(payload.get("expiry_actor", "workload:agentops-temporal-expiry"))
        reason = str(
            payload.get(
                "expiry_reason",
                "ApprovalCase expired without an authoritative human decision",
            )
        )
        case = await asyncio.to_thread(
            authority.expire,
            tenant_id=binding.tenant_id,
            approval_case_ref=binding.approval_case_ref,
            expected_state_version=binding.expected_approval_state_version - 1,
            actor_subject=actor,
            reason=reason,
            details={
                "workflow_id": binding.workflow_id,
                "run_id": str(binding.run_id),
                "step_id": str(binding.step_id),
                "tool_call_id": str(binding.tool_call_id),
                "binding_sha256": binding.binding_sha256,
            },
        )
        result = build_temporal_approval_expiry_result(
            binding,
            case,
            expiry_actor=actor,
            expiry_reason=reason,
            expired_at=case.decided_at or datetime.now(UTC),
        )
        return result.model_dump(mode="json")

    return expire_approval_case


def _failed_activity_result(
    schedule: TemporalActivitySchedulePlan,
    failure_type: str,
) -> TemporalProviderActivityResult:
    """Project an SDK activity failure into the same typed receipt path."""

    request = schedule.request
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.FAILED,
        "provider_receipt_ref": (f"temporal://history/{request.workflow_id}/{request.activity_id}"),
        "provider_operation_ref": None,
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "failure_type": failure_type,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id,
        values,
        "result_sha256",
    )
    return TemporalProviderActivityResult(**values)


def _unknown_activity_result(
    schedule: TemporalActivitySchedulePlan,
) -> TemporalProviderActivityResult:
    """Project an uncertain provider-bound SDK failure into reconciliation input.

    Temporal only confirms that the activity result was not accepted.  Once a provider
    binding exists, that is not enough to claim failure: the provider may have committed
    an external operation before the worker lost the response.  Keep the operation
    identity deterministic so the receipt reconciler can inspect it without submitting
    another operation.
    """

    request = schedule.request
    spec = request.provider_spec
    if spec is None:
        raise ValueError("unknown activity result requires a provider binding")
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.UNKNOWN,
        "provider_receipt_ref": derive_specialist_provider_receipt_ref(request),
        "provider_operation_ref": f"{spec.operation_ref}://{request.activity_id}",
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id,
        values,
        "result_sha256",
    )
    return TemporalProviderActivityResult(**values)


async def _execute_schedule(
    schedule: TemporalActivitySchedulePlan,
) -> TemporalProviderActivityResult:
    try:
        payload = await workflow.execute_activity(
            schedule.activity_type,
            schedule.request.model_dump(mode="json"),
            task_queue=schedule.task_queue_ref,
            activity_id=str(schedule.activity_id),
            schedule_to_close_timeout=timedelta(seconds=schedule.schedule_to_close_timeout_seconds),
            start_to_close_timeout=timedelta(seconds=schedule.start_to_close_timeout_seconds),
            heartbeat_timeout=timedelta(seconds=schedule.heartbeat_timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=getattr(
                workflow.ActivityCancellationType,
                schedule.cancellation_type.name,
            ),
        )
        return TemporalProviderActivityResult.model_validate(payload)
    except Exception as exc:
        cause = getattr(exc, "cause", None)
        failure_type = type(cause or exc).__name__
        if schedule.request.provider_spec is not None:
            # A provider-bound activity may have committed a side effect before
            # Temporal observed timeout/cancellation/transport failure.  Leave the
            # workflow in the explicit unknown state; a receipt reconciler owns
            # terminal settlement.
            return _unknown_activity_result(schedule)
        return _failed_activity_result(schedule, failure_type)


async def _verify_approval(
    binding: TemporalStepApprovalBinding,
    signal: TemporalStepApprovalSignal,
    *,
    task_queue_ref: str,
) -> TemporalApprovalVerificationResult | None:
    try:
        payload = await workflow.execute_activity(
            TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
            {
                "binding": binding.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
            },
            task_queue=task_queue_ref,
            activity_id=str(derive_approval_verification_activity_id(binding, signal)),
            schedule_to_close_timeout=timedelta(seconds=60),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        return TemporalApprovalVerificationResult.model_validate(payload)
    except Exception:
        return None


async def _create_approval_case(
    binding: TemporalStepApprovalBinding,
    *,
    task_queue_ref: str,
) -> TemporalApprovalCaseCreationResult | None:
    try:
        payload = await workflow.execute_activity(
            TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
            {
                "binding": binding.model_dump(mode="json"),
                "request_reason": ("high-risk task graph step requires independent human review"),
            },
            task_queue=task_queue_ref,
            activity_id=f"approval-create-{binding.approval_case_ref.rsplit('/', 1)[-1]}",
            schedule_to_close_timeout=timedelta(seconds=60),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        return TemporalApprovalCaseCreationResult.model_validate(payload)
    except Exception:
        return None


async def _expire_approval_case(
    binding: TemporalStepApprovalBinding,
    *,
    task_queue_ref: str,
) -> TemporalApprovalExpiryResult | None:
    try:
        payload = await workflow.execute_activity(
            TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
            {
                "binding": binding.model_dump(mode="json"),
                "expiry_actor": "workload:agentops-temporal-expiry",
                "expiry_reason": ("ApprovalCase expired without an authoritative human decision"),
            },
            task_queue=task_queue_ref,
            activity_id=str(derive_approval_expiry_activity_id(binding)),
            schedule_to_close_timeout=timedelta(seconds=60),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        return TemporalApprovalExpiryResult.model_validate(payload)
    except Exception:
        return None


def _project_approval_signal(
    execution_input: TemporalTaskGraphExecutionInput,
    signal: TemporalStepApprovalSignal,
    *,
    expected_state_version: int,
) -> TemporalSignal:
    values: dict[str, Any] = {
        "tenant_id": execution_input.workflow_input.tenant_id,
        "workflow_id": execution_input.workflow_input.identity.workflow_id,
        "run_id": execution_input.workflow_input.agent_run.run_id,
        "signal_id": signal.signal_id,
        "kind": signal.kind,
        "expected_state_version": expected_state_version,
        "requested_by": signal.requested_by,
        "reason": signal.reason,
    }
    values["signal_sha256"] = temporal_contract_fingerprint(
        TemporalSignal.schema_id,
        values,
        "signal_sha256",
    )
    return TemporalSignal(**values)


def _workflow_result(
    harness: TemporalTaskGraphWorkflowHarness,
    execution_input: TemporalTaskGraphExecutionInput,
    *,
    activity_results: list[TemporalProviderActivityResult],
    execution_waves: list[tuple[str, ...]],
    approval_results: list[TemporalApprovalVerificationResult],
    approval_creation_results: list[TemporalApprovalCaseCreationResult],
    approval_expiry_results: list[TemporalApprovalExpiryResult],
) -> dict[str, Any]:
    workflow_id = execution_input.workflow_input.identity.workflow_id
    snapshot = harness.get(workflow_id)
    checkpoint = harness.checkpoint(workflow_id)
    values: dict[str, Any] = {
        "schema": TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
        "status": snapshot.workflow.run.status.value,
        "workflow_id": workflow_id,
        "run_id": str(snapshot.workflow.run.run_id),
        "graph_sha256": snapshot.execution.graph.graph_sha256,
        "manifest_sha256": execution_input.execution_manifest.manifest_sha256,
        "execution_input_sha256": execution_input.execution_input_sha256,
        "execution_state_sha256": snapshot.execution.state_sha256,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "activity_result_sha256s": tuple(result.result_sha256 for result in activity_results),
        "approval_binding_sha256s": tuple(
            binding.binding_sha256 for binding in execution_input.approval_bindings
        ),
        "approval_verification_result_sha256s": tuple(
            result.result_sha256 for result in approval_results
        ),
        "approval_creation_result_sha256s": tuple(
            result.result_sha256 for result in approval_creation_results
        ),
        "approval_expiry_result_sha256s": tuple(
            result.result_sha256 for result in approval_expiry_results
        ),
        "approval_case_creations": tuple(
            result.model_dump(mode="json") for result in approval_creation_results
        ),
        "approval_verifications": tuple(
            result.model_dump(mode="json") for result in approval_results
        ),
        "approval_expiries": tuple(
            result.model_dump(mode="json") for result in approval_expiry_results
        ),
        "execution_waves": tuple(execution_waves),
        "checkpoint": checkpoint.model_dump(mode="json"),
    }
    values["workflow_result_sha256"] = temporal_contract_fingerprint(
        TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
        values,
        "workflow_result_sha256",
    )
    return values


@workflow.defn(name=TASK_GRAPH_WORKFLOW_TYPE)
class TemporalTaskGraphWorkflow:
    """Execute coordinator -> planner -> specialist fan-out -> quality fan-in."""

    def __init__(self) -> None:
        self._approval_inbox = TemporalStepApprovalInbox()
        self._active_approval: dict[str, Any] | None = None

    @workflow.signal(name=TEMPORAL_APPROVAL_SIGNAL_NAME)
    def approval_signal(self, payload: dict[str, Any]) -> None:
        self._approval_inbox.submit(payload)

    @workflow.query(name=TEMPORAL_APPROVAL_QUERY_NAME)
    def pending_approval(self) -> dict[str, Any] | None:
        return self._active_approval

    async def _await_step_approval(
        self,
        harness: TemporalTaskGraphWorkflowHarness,
        execution_input: TemporalTaskGraphExecutionInput,
        binding: TemporalStepApprovalBinding,
        *,
        approval_results: list[TemporalApprovalVerificationResult],
        approval_creation_results: list[TemporalApprovalCaseCreationResult],
        approval_expiry_results: list[TemporalApprovalExpiryResult],
    ) -> bool:
        workflow_id = execution_input.workflow_input.identity.workflow_id
        creation = await _create_approval_case(
            binding,
            task_queue_ref=execution_input.workflow_input.identity.task_queue.queue_ref,
        )
        if creation is None:
            raise RuntimeError("ApprovalCase authority creation activity failed closed")
        approval_creation_results.append(creation)
        harness.wait_for_review(
            workflow_id,
            step_id=binding.step_id,
            tool_call_id=binding.tool_call_id,
        )
        self._active_approval = {
            "binding": binding.model_dump(mode="json"),
            "approval_case": creation.approval_case.model_dump(mode="json"),
            "expected_state_version": harness.get(workflow_id).workflow.run.state_version,
            "last_verification": None,
        }
        while True:
            remaining = (creation.approval_case.expires_at - workflow.now()).total_seconds()
            if remaining > 0:
                try:
                    await workflow.wait_condition(
                        lambda: self._approval_inbox.has_pending,
                        timeout=remaining,
                        timeout_summary="agentops-approval-expiry",
                    )
                except TimeoutError as exc:
                    # A signal already durably queued at the timer boundary gets
                    # first chance; PostgreSQL arbitrates the remaining race.
                    if self._approval_inbox.has_pending:
                        continue
                    expiry = await _expire_approval_case(
                        binding,
                        task_queue_ref=(
                            execution_input.workflow_input.identity.task_queue.queue_ref
                        ),
                    )
                    if expiry is None:
                        raise RuntimeError(
                            "ApprovalCase expiry authority unavailable; provider dispatch withheld"
                        ) from exc
                    approval_expiry_results.append(expiry)
                    if not expiry.expired:
                        raise RuntimeError(
                            "ApprovalCase expiry lost a terminal race; "
                            "explicit authority evidence required"
                        ) from exc
                    harness.cancel_after_review(
                        workflow_id,
                        step_id=binding.step_id,
                        tool_call_id=binding.tool_call_id,
                        actor_ref=expiry.expiry_actor,
                        reason=expiry.expiry_reason,
                    )
                    self._active_approval = None
                    return False
            elif not self._approval_inbox.has_pending:
                expiry = await _expire_approval_case(
                    binding,
                    task_queue_ref=(execution_input.workflow_input.identity.task_queue.queue_ref),
                )
                if expiry is None:
                    raise RuntimeError(
                        "ApprovalCase expiry authority unavailable; provider dispatch withheld"
                    )
                approval_expiry_results.append(expiry)
                if not expiry.expired:
                    raise RuntimeError(
                        "ApprovalCase expiry lost a terminal race; "
                        "explicit authority evidence required"
                    )
                harness.cancel_after_review(
                    workflow_id,
                    step_id=binding.step_id,
                    tool_call_id=binding.tool_call_id,
                    actor_ref=expiry.expiry_actor,
                    reason=expiry.expiry_reason,
                )
                self._active_approval = None
                return False
            signal = self._approval_inbox.pop()
            snapshot = harness.get(workflow_id)
            if signal.expected_state_version != snapshot.workflow.run.state_version:
                self._active_approval["last_verification"] = {
                    "accepted": False,
                    "reason_code": "workflow_state_version_mismatch",
                    "signal_id": str(signal.signal_id),
                }
                continue
            result = await _verify_approval(
                binding,
                signal,
                task_queue_ref=(execution_input.workflow_input.identity.task_queue.queue_ref),
            )
            if result is None:
                self._active_approval["last_verification"] = {
                    "accepted": False,
                    "reason_code": "approval_verification_activity_unavailable",
                    "signal_id": str(signal.signal_id),
                }
                continue
            approval_results.append(result)
            self._active_approval["last_verification"] = result.model_dump(mode="json")
            if not result.accepted:
                continue
            harness.apply_signal(
                _project_approval_signal(
                    execution_input,
                    signal,
                    expected_state_version=snapshot.workflow.run.state_version,
                )
            )
            self._active_approval = None
            if signal.kind.value == "approve":
                harness.resume_after_review(
                    workflow_id,
                    step_id=binding.step_id,
                    tool_call_id=binding.tool_call_id,
                )
                return True
            harness.deny_after_review(
                workflow_id,
                step_id=binding.step_id,
                tool_call_id=binding.tool_call_id,
            )
            return False

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        execution_input = TemporalTaskGraphExecutionInput.model_validate(payload)
        workflow_input = execution_input.workflow_input
        workflow_id = workflow_input.identity.workflow_id
        if workflow.info().workflow_id != workflow_id:
            raise ValueError("Temporal provider workflow id differs from execution input")

        harness = TemporalTaskGraphWorkflowHarness()
        harness.start(workflow_input)
        plan_by_step = {plan.step_id: plan for plan in execution_input.execution_manifest.plans}
        activity_results: list[TemporalProviderActivityResult] = []
        approval_results: list[TemporalApprovalVerificationResult] = []
        approval_creation_results: list[TemporalApprovalCaseCreationResult] = []
        approval_expiry_results: list[TemporalApprovalExpiryResult] = []
        execution_waves: list[tuple[str, ...]] = []
        approval_by_step = {
            binding.step_id: binding for binding in execution_input.approval_bindings
        }

        while True:
            snapshot = harness.get(workflow_id)
            if all(
                step.status is AgentStepStatus.SUCCEEDED for step in snapshot.execution.step_states
            ):
                return _workflow_result(
                    harness,
                    execution_input,
                    activity_results=activity_results,
                    execution_waves=execution_waves,
                    approval_results=approval_results,
                    approval_creation_results=approval_creation_results,
                    approval_expiry_results=approval_expiry_results,
                )
            by_id = {step.step_id: step for step in snapshot.execution.step_states}
            ready = tuple(
                step
                for step in snapshot.execution.step_states
                if step.status is AgentStepStatus.PENDING
                and all(
                    by_id[dependency].status is AgentStepStatus.SUCCEEDED
                    for dependency in step.depends_on_step_ids
                )
            )
            if not ready:
                raise ValueError("task graph execution has no ready step and is not complete")
            execution_waves.append(tuple(step.agent_id for step in ready))

            pending: list[tuple[Any, Any, int]] = []
            ordered_ready = tuple(
                sorted(
                    ready,
                    key=lambda item: (
                        item.step_id not in approval_by_step,
                        item.sequence_no,
                    ),
                )
            )
            for step in ordered_ready:
                plan = plan_by_step[step.step_id]
                harness.start_step(workflow_id, step.step_id)
                current = harness.get(workflow_id)
                input_artifact_ids = tuple(
                    sorted(
                        {
                            *workflow_input.input_artifact_ids,
                            *(
                                artifact_id
                                for dependency in step.depends_on_step_ids
                                for artifact_id in next(
                                    item
                                    for item in current.execution.step_states
                                    if item.step_id == dependency
                                ).output_artifact_ids
                            ),
                        },
                        key=str,
                    )
                )
                current = harness.bind_tool_call(
                    workflow_id,
                    step_id=step.step_id,
                    tool_ref=plan.tool_ref,
                    capability_ref=plan.capability_ref,
                    subject_context=plan.subject_context,
                    side_effect=plan.side_effect,
                    policy_decision_ref=plan.policy_decision_ref,
                    idempotency_key=plan.idempotency_key,
                    input_artifact_ids=input_artifact_ids,
                )
                call = next(
                    item for item in current.execution.tool_calls if item.step_id == step.step_id
                )
                binding = approval_by_step.get(step.step_id)
                if binding is not None:
                    approved = await self._await_step_approval(
                        harness,
                        execution_input,
                        binding,
                        approval_results=approval_results,
                        approval_creation_results=approval_creation_results,
                        approval_expiry_results=approval_expiry_results,
                    )
                    if not approved:
                        return _workflow_result(
                            harness,
                            execution_input,
                            activity_results=activity_results,
                            execution_waves=execution_waves,
                            approval_results=approval_results,
                            approval_creation_results=approval_creation_results,
                            approval_expiry_results=approval_expiry_results,
                        )
                pending.append((step, call, 1))

            while pending:
                schedules: list[TemporalActivitySchedulePlan] = []
                for step, call, attempt_no in pending:
                    plan = plan_by_step[step.step_id]
                    current = harness.schedule_activity(
                        workflow_id,
                        call.tool_call_id,
                        activity_type=plan.activity_type,
                        attempt_no=attempt_no,
                        schedule_to_close_timeout_seconds=(plan.schedule_to_close_timeout_seconds),
                        start_to_close_timeout_seconds=(plan.start_to_close_timeout_seconds),
                        heartbeat_timeout_seconds=plan.heartbeat_timeout_seconds,
                        cancellation_type=plan.cancellation_type,
                        provider_spec=plan.provider_spec,
                    )
                    schedules.append(current.activity_schedules[-1])

                results = await asyncio.gather(
                    *(_execute_schedule(schedule) for schedule in schedules)
                )
                retry_pending: list[tuple[Any, Any, int]] = []
                failed_steps: list[Any] = []
                saw_unknown = False
                for (step, call, attempt_no), schedule, result in zip(
                    pending,
                    schedules,
                    results,
                    strict=True,
                ):
                    activity_results.append(result)
                    evidence = TemporalActivityAdapter.evidence_from_result(
                        schedule.request,
                        result,
                    )
                    current = harness.record_scheduled_activity(workflow_id, evidence)
                    current_call = next(
                        item
                        for item in current.execution.tool_calls
                        if item.tool_call_id == call.tool_call_id
                    )
                    if result.outcome is TemporalActivityOutcome.SUCCEEDED:
                        harness.complete_step(
                            workflow_id,
                            step_id=step.step_id,
                            output_artifact_ids=(result.output_artifact_id,),
                        )
                    elif result.outcome is TemporalActivityOutcome.UNKNOWN:
                        saw_unknown = True
                    elif current_call.status is AgentToolCallStatus.RUNNING:
                        retry_pending.append((step, call, attempt_no + 1))
                    else:
                        failed_steps.append(step)
                if saw_unknown:
                    return _workflow_result(
                        harness,
                        execution_input,
                        activity_results=activity_results,
                        execution_waves=execution_waves,
                        approval_results=approval_results,
                        approval_creation_results=approval_creation_results,
                        approval_expiry_results=approval_expiry_results,
                    )
                if failed_steps:
                    for step in failed_steps:
                        harness.fail_step(workflow_id, step.step_id)
                    return _workflow_result(
                        harness,
                        execution_input,
                        activity_results=activity_results,
                        execution_waves=execution_waves,
                        approval_results=approval_results,
                        approval_creation_results=approval_creation_results,
                        approval_expiry_results=approval_expiry_results,
                    )
                pending = retry_pending


__all__ = [
    "TASK_GRAPH_WORKFLOW_RESULT_SCHEMA",
    "TASK_GRAPH_WORKFLOW_TYPE",
    "TemporalTaskGraphWorkflow",
    "build_approval_case_creation_activity_definition",
    "build_approval_case_expiry_activity_definition",
    "build_approval_verification_activity_definition",
    "build_specialist_activity_definition",
]
