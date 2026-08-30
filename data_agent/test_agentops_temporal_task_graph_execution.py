from __future__ import annotations

import pytest

from data_agent.agentops_contracts import AgentSideEffect
from data_agent.agentops_temporal_contracts import (
    TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA,
    TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA,
    TemporalSpecialistActivityPlan,
    TemporalTaskGraphExecutionManifest,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_task_graph_execution import (
    TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
    TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA,
    TemporalTaskGraphExecutionInput,
    compile_temporal_task_graph_execution_input,
)
from data_agent.test_agentops_contracts import (
    _deployment,
    _evaluation,
    _spec,
    _temporal_input,
)


def _execution_input(**kwargs):
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    workflow_input = _temporal_input(deployment)
    tool_ref_by_agent = {
        "coordinator": "tool:data_product:v1",
        "planner": "tool:data_product:v1",
        "data_engineer": "tool:data_product:v1",
        "fusion": "tool:mmfe:v1",
        "gwm": "tool:gwm:v1",
        "quality": "tool:data_product:v1",
    }
    return compile_temporal_task_graph_execution_input(
        workflow_input,
        spec,
        tool_ref_by_agent=tool_ref_by_agent,
        **kwargs,
    )


def _rehash_plan(plan: TemporalSpecialistActivityPlan, **updates):
    values = plan.model_dump(mode="json")
    values.update(updates)
    values["plan_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA,
        values,
        "plan_sha256",
    )
    return TemporalSpecialistActivityPlan(**values)


def _replace_plan(execution_input, plan):
    manifest_values = execution_input.execution_manifest.model_dump(mode="json")
    plans = list(execution_input.execution_manifest.plans)
    plans[plan.sequence_no] = plan
    manifest_values["plans"] = plans
    manifest_values["manifest_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA,
        manifest_values,
        "manifest_sha256",
    )
    manifest = TemporalTaskGraphExecutionManifest(**manifest_values)
    values = execution_input.model_dump(mode="json")
    values["execution_manifest"] = manifest
    values["execution_input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA,
        values,
        "execution_input_sha256",
    )
    return values


def test_execution_manifest_binds_every_graph_step_and_specialist_authority():
    execution_input = _execution_input(
        side_effect_by_agent={
            "data_engineer": AgentSideEffect.DATA_WRITE,
            "fusion": AgentSideEffect.DATA_WRITE,
        }
    )

    graph = execution_input.workflow_input.task_graph
    manifest = execution_input.execution_manifest
    assert tuple(plan.step_id for plan in manifest.plans) == tuple(
        step.step_id for step in graph.steps
    )
    assert tuple(plan.agent_id for plan in manifest.plans) == (
        "coordinator",
        "planner",
        "data_engineer",
        "fusion",
        "gwm",
        "quality",
    )
    assert {plan.activity_type for plan in manifest.plans} == {
        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE
    }
    assert {plan.sdk_maximum_attempts for plan in manifest.plans} == {1}
    assert manifest.graph_sha256 == graph.graph_sha256


@pytest.mark.parametrize(
    ("agent_id", "updates", "message"),
    (
        (
            "fusion",
            {"capability_ref": "gwm.observation.project"},
            "capability is not authorized",
        ),
        (
            "gwm",
            {"tool_ref": "tool:unregistered:v1"},
            "tool is not authorized",
        ),
        (
            "quality",
            {"agent_id": "quality_alt"},
            "differs from task graph step",
        ),
    ),
)
def test_execution_input_rejects_graph_or_tool_authority_drift(
    agent_id, updates, message
):
    execution_input = _execution_input()
    original = next(
        plan
        for plan in execution_input.execution_manifest.plans
        if plan.agent_id == agent_id
    )
    drifted = _rehash_plan(original, **updates)

    with pytest.raises(ValueError, match=message):
        TemporalTaskGraphExecutionInput(**_replace_plan(execution_input, drifted))


@pytest.mark.parametrize("agent_id", ("fusion", "gwm"))
def test_mmfe_and_gwm_cannot_claim_control_plane_write_authority(agent_id):
    with pytest.raises(ValueError, match="control-plane writes"):
        _execution_input(
            side_effect_by_agent={agent_id: AgentSideEffect.CONTROL_WRITE}
        )


def test_manifest_compiler_requires_complete_tool_bindings():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    workflow_input = _temporal_input(deployment)

    with pytest.raises(ValueError, match="every task graph agent"):
        compile_temporal_task_graph_execution_input(
            workflow_input,
            spec,
            tool_ref_by_agent={"coordinator": "tool:data_product:v1"},
        )
