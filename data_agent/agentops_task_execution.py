"""Provider-neutral immutable execution state for an AgentTaskGraph.

This module advances a compiled graph through typed step and tool-call contracts. It does not
run a model, invoke a provider, or persist state; a durable runtime can persist each returned
state and use the fingerprints for idempotency/reconciliation.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from .agentops_contracts import (
    AGENT_TASK_STEP_SCHEMA,
    AGENT_TOOL_CALL_SCHEMA,
    AgentSideEffect,
    AgentStepStatus,
    AgentTaskStep,
    AgentToolCall,
    AgentToolCallStatus,
    agent_contract_fingerprint,
)
from .agentops_task_graph import AgentTaskGraph
from .platform_contracts import (
    FrozenContract,
    NonEmptyText,
    Sha256,
    SubjectContext,
    TenantId,
)

AGENT_TASK_EXECUTION_SCHEMA = "gda.agent_task_execution.v1"
_TOOL_CALL_ID_NAMESPACE = NAMESPACE_URL


def derive_agent_tool_call_id(
    *, run_id: UUID, step_id: UUID, idempotency_key: str
) -> UUID:
    """Derive the immutable ToolCall identity before execution state is mutated."""

    return uuid5(
        _TOOL_CALL_ID_NAMESPACE,
        f"gda-agent-tool-call:{run_id}:{step_id}:{idempotency_key}",
    )


class AgentTaskExecutionState(FrozenContract):
    """Immutable execution projection for one compiled graph."""

    schema_id: ClassVar[str] = AGENT_TASK_EXECUTION_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    graph: AgentTaskGraph
    step_states: tuple[AgentTaskStep, ...]
    tool_calls: tuple[AgentToolCall, ...] = ()
    state_version: int = Field(ge=0)
    state_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_state(self) -> AgentTaskExecutionState:
        if self.graph.tenant_id != self.tenant_id or self.graph.run_id != self.run_id:
            raise ValueError("execution state graph correlation differs")
        if tuple(step.step_id for step in self.step_states) != tuple(
            step.step_id for step in self.graph.steps
        ):
            raise ValueError("execution state step projection differs from graph plan")
        immutable_step_fields = (
            "tenant_id",
            "run_id",
            "step_id",
            "agent_id",
            "role",
            "sequence_no",
            "depends_on_step_ids",
        )
        for planned, projected in zip(self.graph.steps, self.step_states, strict=True):
            if any(
                getattr(projected, field) != getattr(planned, field)
                for field in immutable_step_fields
            ):
                raise ValueError("execution state changed an immutable graph step field")
        step_ids = {step.step_id for step in self.step_states}
        call_ids = tuple(call.tool_call_id for call in self.tool_calls)
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("execution state tool call ids must be unique")
        idempotency_keys = tuple(call.idempotency_key for call in self.tool_calls)
        if len(idempotency_keys) != len(set(idempotency_keys)):
            raise ValueError("execution state tool call idempotency keys must be unique")
        for call in self.tool_calls:
            if call.tenant_id != self.tenant_id or call.run_id != self.run_id:
                raise ValueError("tool call correlation differs from execution state")
            if call.step_id not in step_ids:
                raise ValueError("tool call references an unknown task step")
        expected = agent_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "state_sha256"
        )
        if self.state_sha256 != expected:
            raise ValueError("state_sha256 does not match execution state")
        return self


def initial_execution_state(graph: AgentTaskGraph) -> AgentTaskExecutionState:
    """Create the zero-version execution projection for a compiled graph."""

    values: dict[str, Any] = {
        "tenant_id": graph.tenant_id,
        "run_id": graph.run_id,
        "graph": graph,
        "step_states": graph.steps,
        "tool_calls": (),
        "state_version": 0,
    }
    values["state_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_EXECUTION_SCHEMA, values, "state_sha256"
    )
    return AgentTaskExecutionState(**values)


def _step_values(step: AgentTaskStep, **changes: Any) -> dict[str, Any]:
    values = step.model_dump(mode="json")
    values.update(changes)
    values["step_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_STEP_SCHEMA, values, "step_sha256"
    )
    return values


def _tool_call_values(call: AgentToolCall, **changes: Any) -> dict[str, Any]:
    values = call.model_dump(mode="json")
    values.update(changes)
    values["tool_call_sha256"] = agent_contract_fingerprint(
        AGENT_TOOL_CALL_SCHEMA, values, "tool_call_sha256"
    )
    return values


def _build_tool_call(values: dict[str, Any]) -> AgentToolCall:
    values = dict(values)
    values["tool_call_sha256"] = agent_contract_fingerprint(
        AGENT_TOOL_CALL_SCHEMA, values, "tool_call_sha256"
    )
    return AgentToolCall(**values)


def _advance(
    state: AgentTaskExecutionState,
    *,
    step_states: tuple[AgentTaskStep, ...] | None = None,
    tool_calls: tuple[AgentToolCall, ...] | None = None,
) -> AgentTaskExecutionState:
    values: dict[str, Any] = {
        "tenant_id": state.tenant_id,
        "run_id": state.run_id,
        "graph": state.graph,
        "step_states": state.step_states if step_states is None else step_states,
        "tool_calls": state.tool_calls if tool_calls is None else tool_calls,
        "state_version": state.state_version + 1,
    }
    values["state_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_EXECUTION_SCHEMA, values, "state_sha256"
    )
    return AgentTaskExecutionState(**values)


def _step(state: AgentTaskExecutionState, step_id: UUID) -> AgentTaskStep:
    for step in state.step_states:
        if step.step_id == step_id:
            return step
    raise ValueError(f"unknown task step: {step_id}")


def start_step(state: AgentTaskExecutionState, step_id: UUID) -> AgentTaskExecutionState:
    """Move a pending step to running only after all dependencies succeeded."""

    step = _step(state, step_id)
    if step.status is not AgentStepStatus.PENDING:
        raise ValueError("only pending task steps can start")
    by_id = {candidate.step_id: candidate for candidate in state.step_states}
    if any(
        by_id[dependency].status is not AgentStepStatus.SUCCEEDED
        for dependency in step.depends_on_step_ids
    ):
        raise ValueError("task step dependencies are not all succeeded")
    updated = _step_values(step, status=AgentStepStatus.RUNNING.value)
    steps = tuple(
        AgentTaskStep(**updated)
        if candidate.step_id == step_id
        else candidate
        for candidate in state.step_states
    )
    return _advance(state, step_states=steps)


def bind_tool_call(
    state: AgentTaskExecutionState,
    *,
    step_id: UUID,
    tool_ref: NonEmptyText,
    capability_ref: NonEmptyText,
    subject_context: SubjectContext,
    side_effect: AgentSideEffect,
    policy_decision_ref: NonEmptyText,
    idempotency_key: NonEmptyText,
    input_artifact_ids: tuple[UUID, ...] = (),
) -> AgentTaskExecutionState:
    """Bind one governed tool call to a running step, idempotently."""

    step = _step(state, step_id)
    if step.status is not AgentStepStatus.RUNNING:
        raise ValueError("tool calls require a running task step")
    tool_call_id = derive_agent_tool_call_id(
        run_id=state.run_id,
        step_id=step_id,
        idempotency_key=idempotency_key,
    )
    existing = next(
        (call for call in state.tool_calls if call.tool_call_id == tool_call_id), None
    )
    if existing is not None:
        expected = {
            "tenant_id": state.tenant_id,
            "run_id": state.run_id,
            "step_id": step_id,
            "tool_call_id": tool_call_id,
            "tool_ref": tool_ref,
            "capability_ref": capability_ref,
            "subject_context": subject_context,
            "side_effect": side_effect,
            "policy_decision_ref": policy_decision_ref,
            "idempotency_key": idempotency_key,
            "status": AgentToolCallStatus.REQUESTED,
            "input_artifact_ids": input_artifact_ids,
            "output_artifact_id": None,
            "external_receipt_artifact_id": None,
        }
        expected_call = _build_tool_call(expected)
        immutable_fields = (
            "tenant_id",
            "run_id",
            "step_id",
            "tool_call_id",
            "tool_ref",
            "capability_ref",
            "subject_context",
            "side_effect",
            "policy_decision_ref",
            "idempotency_key",
            "input_artifact_ids",
        )
        if any(
            getattr(existing, field) != getattr(expected_call, field)
            for field in immutable_fields
        ):
            raise ValueError("tool call idempotency key was reused with different content")
        return state

    values: dict[str, Any] = {
        "tenant_id": state.tenant_id,
        "run_id": state.run_id,
        "step_id": step_id,
        "tool_call_id": tool_call_id,
        "tool_ref": tool_ref,
        "capability_ref": capability_ref,
        "subject_context": subject_context,
        "side_effect": side_effect,
        "policy_decision_ref": policy_decision_ref,
        "idempotency_key": idempotency_key,
        "status": AgentToolCallStatus.REQUESTED,
        "input_artifact_ids": input_artifact_ids,
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
    }
    call = _build_tool_call(values)
    return _advance(state, tool_calls=(*state.tool_calls, call))


def settle_tool_call(
    state: AgentTaskExecutionState,
    *,
    tool_call_id: UUID,
    status: AgentToolCallStatus,
    output_artifact_id: UUID | None = None,
    external_receipt_artifact_id: UUID | None = None,
) -> AgentTaskExecutionState:
    """Settle a tool call; unknown side effects remain reconciling."""

    try:
        call = next(item for item in state.tool_calls if item.tool_call_id == tool_call_id)
    except StopIteration as exc:
        raise ValueError(f"unknown tool call: {tool_call_id}") from exc
    allowed = {
        AgentToolCallStatus.REQUESTED: {
            AgentToolCallStatus.RUNNING,
            AgentToolCallStatus.DENIED,
            AgentToolCallStatus.FAILED,
        },
        AgentToolCallStatus.RUNNING: {
            AgentToolCallStatus.SUCCEEDED,
            AgentToolCallStatus.FAILED,
            AgentToolCallStatus.RECONCILING,
        },
        AgentToolCallStatus.RECONCILING: {
            AgentToolCallStatus.SUCCEEDED,
            AgentToolCallStatus.FAILED,
        },
    }
    if status not in allowed.get(call.status, set()):
        raise ValueError(f"invalid tool call transition {call.status.value} -> {status.value}")
    if status is AgentToolCallStatus.RECONCILING:
        if call.side_effect is AgentSideEffect.NONE:
            raise ValueError("read-only tool call cannot enter reconciliation")
        if external_receipt_artifact_id is None:
            raise ValueError("reconciling side effect requires an external receipt artifact")
    if status is AgentToolCallStatus.SUCCEEDED and output_artifact_id is None:
        raise ValueError("successful tool call requires an output artifact")
    values = _tool_call_values(
        call,
        status=status.value,
        output_artifact_id=(
            str(output_artifact_id) if output_artifact_id is not None else call.output_artifact_id
        ),
        external_receipt_artifact_id=(
            str(external_receipt_artifact_id)
            if external_receipt_artifact_id is not None
            else call.external_receipt_artifact_id
        ),
    )
    updated = AgentToolCall(**values)
    calls = tuple(
        updated if item.tool_call_id == tool_call_id else item
        for item in state.tool_calls
    )
    return _advance(state, tool_calls=calls)


def wait_step_for_review(
    state: AgentTaskExecutionState,
    *,
    step_id: UUID,
    tool_call_id: UUID,
) -> AgentTaskExecutionState:
    """Hold one requested write ToolCall before any provider dispatch occurs."""

    step = _step(state, step_id)
    if step.status is not AgentStepStatus.RUNNING:
        raise ValueError("only a running task step can wait for review")
    call = next(
        (item for item in state.tool_calls if item.tool_call_id == tool_call_id), None
    )
    if call is None or call.step_id != step_id:
        raise ValueError("review gate references an unknown step ToolCall")
    if call.status is not AgentToolCallStatus.REQUESTED:
        raise ValueError("review gate must precede provider dispatch")
    updated = _step_values(step, status=AgentStepStatus.WAITING_REVIEW.value)
    steps = tuple(
        AgentTaskStep(**updated) if candidate.step_id == step_id else candidate
        for candidate in state.step_states
    )
    return _advance(state, step_states=steps)


def resume_step_after_review(
    state: AgentTaskExecutionState,
    *,
    step_id: UUID,
    tool_call_id: UUID,
) -> AgentTaskExecutionState:
    """Resume an approved write ToolCall without changing its immutable binding."""

    step = _step(state, step_id)
    if step.status is not AgentStepStatus.WAITING_REVIEW:
        raise ValueError("only a review-waiting task step can resume")
    call = next(
        (item for item in state.tool_calls if item.tool_call_id == tool_call_id), None
    )
    if call is None or call.step_id != step_id:
        raise ValueError("review approval references an unknown step ToolCall")
    if call.status is not AgentToolCallStatus.REQUESTED:
        raise ValueError("approved ToolCall must still be undispatched")
    updated = _step_values(step, status=AgentStepStatus.RUNNING.value)
    steps = tuple(
        AgentTaskStep(**updated) if candidate.step_id == step_id else candidate
        for candidate in state.step_states
    )
    return _advance(state, step_states=steps)


def deny_step_after_review(
    state: AgentTaskExecutionState,
    *,
    step_id: UUID,
    tool_call_id: UUID,
) -> AgentTaskExecutionState:
    """Close a rejected write ToolCall without dispatching its provider activity."""

    step = _step(state, step_id)
    if step.status is not AgentStepStatus.WAITING_REVIEW:
        raise ValueError("only a review-waiting task step can be denied")
    call = next(
        (item for item in state.tool_calls if item.tool_call_id == tool_call_id), None
    )
    if call is None or call.step_id != step_id:
        raise ValueError("review rejection references an unknown step ToolCall")
    if call.status is not AgentToolCallStatus.REQUESTED:
        raise ValueError("rejected ToolCall must still be undispatched")
    denied_call = AgentToolCall(
        **_tool_call_values(call, status=AgentToolCallStatus.DENIED.value)
    )
    failed_step = AgentTaskStep(
        **_step_values(step, status=AgentStepStatus.FAILED.value)
    )
    calls = tuple(
        denied_call if item.tool_call_id == tool_call_id else item
        for item in state.tool_calls
    )
    steps = tuple(
        failed_step if item.step_id == step_id else item
        for item in state.step_states
    )
    return _advance(state, step_states=steps, tool_calls=calls)


def complete_step(
    state: AgentTaskExecutionState,
    *,
    step_id: UUID,
    output_artifact_ids: tuple[UUID, ...] = (),
) -> AgentTaskExecutionState:
    """Complete a step only after all its bound tool calls succeeded."""

    step = _step(state, step_id)
    if step.status not in {AgentStepStatus.RUNNING, AgentStepStatus.WAITING_REVIEW}:
        raise ValueError("only running or review-waiting task steps can complete")
    calls = [call for call in state.tool_calls if call.step_id == step_id]
    if any(call.status is not AgentToolCallStatus.SUCCEEDED for call in calls):
        raise ValueError("all bound tool calls must succeed before step completion")
    if len(output_artifact_ids) != len(set(output_artifact_ids)):
        raise ValueError("step output artifact ids must be unique")
    updated = _step_values(
        step,
        status=AgentStepStatus.SUCCEEDED.value,
        output_artifact_ids=[str(item) for item in output_artifact_ids],
    )
    steps = tuple(
        AgentTaskStep(**updated)
        if candidate.step_id == step_id
        else candidate
        for candidate in state.step_states
    )
    return _advance(state, step_states=steps)


def fail_step(state: AgentTaskExecutionState, step_id: UUID) -> AgentTaskExecutionState:
    """Move a running or review-waiting step to failed without asserting outputs."""

    step = _step(state, step_id)
    if step.status not in {AgentStepStatus.RUNNING, AgentStepStatus.WAITING_REVIEW}:
        raise ValueError("only running or review-waiting task steps can fail")
    updated = _step_values(step, status=AgentStepStatus.FAILED.value)
    steps = tuple(
        AgentTaskStep(**updated)
        if candidate.step_id == step_id
        else candidate
        for candidate in state.step_states
    )
    return _advance(state, step_states=steps)


__all__ = [
    "AGENT_TASK_EXECUTION_SCHEMA",
    "AgentTaskExecutionState",
    "bind_tool_call",
    "complete_step",
    "deny_step_after_review",
    "derive_agent_tool_call_id",
    "fail_step",
    "initial_execution_state",
    "resume_step_after_review",
    "settle_tool_call",
    "start_step",
    "wait_step_for_review",
]
