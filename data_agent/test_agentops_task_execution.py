from __future__ import annotations

from uuid import UUID

import pytest

from data_agent.agentops_contracts import (
    AGENT_TASK_STEP_SCHEMA,
    AgentSideEffect,
    AgentToolCallStatus,
    agent_contract_fingerprint,
)
from data_agent.agentops_task_execution import (
    AGENT_TASK_EXECUTION_SCHEMA,
    AgentTaskExecutionState,
    bind_tool_call,
    complete_step,
    initial_execution_state,
    settle_tool_call,
    start_step,
)
from data_agent.agentops_task_graph import compile_agent_task_graph
from data_agent.test_agentops_contracts import _deployment, _evaluation, _run, _spec, _subject

ARTIFACT_1 = UUID("00000000-0000-4000-8000-000000001001")
ARTIFACT_2 = UUID("00000000-0000-4000-8000-000000001002")


def _state():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    graph = compile_agent_task_graph(spec, deployment, _run(deployment))
    return initial_execution_state(graph)


def test_execution_enforces_dag_dependencies_and_recomputes_hashes() -> None:
    state = _state()
    coordinator = state.step_states[0]
    planner = state.step_states[1]

    with pytest.raises(ValueError, match="dependencies"):
        start_step(state, planner.step_id)

    state = start_step(state, coordinator.step_id)
    state = complete_step(state, step_id=coordinator.step_id)
    state = start_step(state, planner.step_id)

    assert state.state_version == 3
    assert state.step_states[0].status.value == "succeeded"
    assert state.step_states[1].status.value == "running"
    assert all(step.status.value == "pending" for step in state.graph.steps)
    assert state.graph.graph_sha256
    assert state.state_sha256


def test_execution_rejects_projection_changes_to_immutable_graph_step_fields() -> None:
    state = _state()
    values = state.model_dump(mode="json")
    projected = dict(values["step_states"][1])
    projected["role"] = "quality_guardian"
    projected["step_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_STEP_SCHEMA, projected, "step_sha256"
    )
    values["step_states"][1] = projected
    values["state_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_EXECUTION_SCHEMA, values, "state_sha256"
    )

    with pytest.raises(ValueError, match="immutable graph step field"):
        AgentTaskExecutionState(**values)


def test_tool_call_binding_is_stable_and_success_requires_output_artifact() -> None:
    state = _state()
    coordinator = state.step_states[0]
    state = start_step(state, coordinator.step_id)
    state = bind_tool_call(
        state,
        step_id=coordinator.step_id,
        tool_ref="tool:data_product:v1",
        capability_ref="capability:data_product.plan:v1",
        subject_context=_subject(),
        side_effect=AgentSideEffect.NONE,
        policy_decision_ref="policy:agentops:read-v1",
        idempotency_key="tool-call:coordinator:plan",
    )
    call = state.tool_calls[0]
    replay = bind_tool_call(
        state,
        step_id=coordinator.step_id,
        tool_ref="tool:data_product:v1",
        capability_ref="capability:data_product.plan:v1",
        subject_context=_subject(),
        side_effect=AgentSideEffect.NONE,
        policy_decision_ref="policy:agentops:read-v1",
        idempotency_key="tool-call:coordinator:plan",
    )
    assert replay == state
    assert call.tool_call_id == replay.tool_calls[0].tool_call_id

    state = settle_tool_call(
        state,
        tool_call_id=call.tool_call_id,
        status=AgentToolCallStatus.RUNNING,
    )
    replay_running = bind_tool_call(
        state,
        step_id=coordinator.step_id,
        tool_ref="tool:data_product:v1",
        capability_ref="capability:data_product.plan:v1",
        subject_context=_subject(),
        side_effect=AgentSideEffect.NONE,
        policy_decision_ref="policy:agentops:read-v1",
        idempotency_key="tool-call:coordinator:plan",
    )
    assert replay_running == state
    with pytest.raises(ValueError, match="output artifact"):
        settle_tool_call(
            state,
            tool_call_id=call.tool_call_id,
            status=AgentToolCallStatus.SUCCEEDED,
        )
    state = settle_tool_call(
        state,
        tool_call_id=call.tool_call_id,
        status=AgentToolCallStatus.SUCCEEDED,
        output_artifact_id=ARTIFACT_1,
    )
    state = complete_step(
        state,
        step_id=coordinator.step_id,
        output_artifact_ids=(ARTIFACT_1,),
    )
    assert state.tool_calls[0].status is AgentToolCallStatus.SUCCEEDED
    assert state.step_states[0].output_artifact_ids == (ARTIFACT_1,)


def test_external_side_effect_unknown_requires_reconciliation_receipt() -> None:
    state = _state()
    coordinator = state.step_states[0]
    state = start_step(state, coordinator.step_id)
    state = bind_tool_call(
        state,
        step_id=coordinator.step_id,
        tool_ref="tool:external-publish:v1",
        capability_ref="capability:external.publish:v1",
        subject_context=_subject(),
        side_effect=AgentSideEffect.EXTERNAL_WRITE,
        policy_decision_ref="policy:agentops:write-v1",
        idempotency_key="tool-call:coordinator:publish",
    )
    call = state.tool_calls[0]
    state = settle_tool_call(
        state,
        tool_call_id=call.tool_call_id,
        status=AgentToolCallStatus.RUNNING,
    )
    with pytest.raises(ValueError, match="external receipt"):
        settle_tool_call(
            state,
            tool_call_id=call.tool_call_id,
            status=AgentToolCallStatus.RECONCILING,
        )
    state = settle_tool_call(
        state,
        tool_call_id=call.tool_call_id,
        status=AgentToolCallStatus.RECONCILING,
        external_receipt_artifact_id=ARTIFACT_2,
    )
    assert state.tool_calls[0].status is AgentToolCallStatus.RECONCILING
    with pytest.raises(ValueError, match="all bound tool calls"):
        complete_step(state, step_id=coordinator.step_id)
