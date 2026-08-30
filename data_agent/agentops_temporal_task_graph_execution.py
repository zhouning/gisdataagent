"""Provider-neutral execution input for the real Temporal multi-agent workflow.

The task graph owns dependency ordering. AgentSpec owns capability/tool authorization. The
execution manifest binds both to exact Temporal activity options without making Temporal a
data catalog, policy authority, or DataOps scheduler.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import model_validator

from .agentops_contracts import AgentRole, AgentSideEffect, AgentSpecVersion
from .agentops_task_execution import derive_agent_tool_call_id
from .agentops_task_graph import compile_agent_task_graph
from .agentops_temporal_approval import (
    TemporalStepApprovalBinding,
    compile_temporal_step_approval_binding,
)
from .agentops_temporal_contracts import (
    TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA,
    TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA,
    TemporalActivityCancellationType,
    TemporalProviderExecutionSpec,
    TemporalSpecialistActivityPlan,
    TemporalTaskGraphExecutionManifest,
    TemporalWorkflowInput,
    temporal_contract_fingerprint,
)
from .platform_contracts import FrozenContract, Sha256

TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA = "gda.temporal_task_graph_execution_input.v1"
TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE = "gda.agentops.specialist.activity"


class TemporalTaskGraphExecutionInput(FrozenContract):
    """Immutable input accepted by the SDK-backed task-graph workflow."""

    schema_id: ClassVar[str] = TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA
    workflow_input: TemporalWorkflowInput
    agent_spec: AgentSpecVersion
    execution_manifest: TemporalTaskGraphExecutionManifest
    execution_input_sha256: Sha256
    approval_bindings: tuple[TemporalStepApprovalBinding, ...] = ()

    @model_validator(mode="after")
    def _consistent_input(self) -> TemporalTaskGraphExecutionInput:
        workflow_input = self.workflow_input
        graph = workflow_input.task_graph
        manifest = self.execution_manifest
        if self.agent_spec.tenant_id != workflow_input.tenant_id:
            raise ValueError("AgentSpec tenant differs from Temporal workflow input")
        if self.agent_spec.spec_sha256 != workflow_input.agent_spec_sha256:
            raise ValueError("AgentSpec hash differs from Temporal workflow input")
        expected_graph = compile_agent_task_graph(
            self.agent_spec,
            workflow_input.deployment_revision,
            workflow_input.agent_run,
        )
        if expected_graph != graph:
            raise ValueError("Temporal task graph differs from the supplied AgentSpec topology")
        if (
            manifest.tenant_id != workflow_input.tenant_id
            or manifest.workflow_id != workflow_input.identity.workflow_id
            or manifest.run_id != workflow_input.agent_run.run_id
            or manifest.graph_sha256 != graph.graph_sha256
        ):
            raise ValueError("execution manifest correlation differs from workflow task graph")
        if len(manifest.plans) != len(graph.steps):
            raise ValueError("execution manifest must bind every task graph step exactly once")

        bindings_by_step = {binding.step_id: binding for binding in self.approval_bindings}
        if len(bindings_by_step) != len(self.approval_bindings):
            raise ValueError("approval bindings must identify each step at most once")

        node_by_id = {node.agent_id: node for node in self.agent_spec.topology.nodes}
        for step, plan in zip(graph.steps, manifest.plans, strict=True):
            if (
                plan.step_id != step.step_id
                or plan.agent_id != step.agent_id
                or plan.role is not step.role
                or plan.sequence_no != step.sequence_no
            ):
                raise ValueError("specialist activity plan differs from task graph step")
            node = node_by_id[step.agent_id]
            if plan.capability_ref not in node.capability_refs:
                raise ValueError("specialist activity capability is not authorized by AgentSpec")
            if plan.tool_ref not in self.agent_spec.tool_refs:
                raise ValueError("specialist activity tool is not authorized by AgentSpec")
            if plan.policy_decision_ref != workflow_input.policy_decision_ref:
                raise ValueError("specialist activity policy decision differs from workflow")
            if plan.subject_context != workflow_input.subject_context:
                raise ValueError("specialist activity subject differs from workflow authority")
            if (
                plan.task_queue_ref != workflow_input.identity.task_queue.queue_ref
                or plan.task_queue_sha256 != workflow_input.identity.task_queue.queue_sha256
            ):
                raise ValueError("specialist activity task queue differs from workflow identity")
            if (
                step.role in {AgentRole.MULTIMODAL_FUSION, AgentRole.GWM_SPECIALIST}
                and plan.side_effect is AgentSideEffect.CONTROL_WRITE
            ):
                raise ValueError("MMFE and GWM specialists cannot own control-plane writes")
            binding = bindings_by_step.get(step.step_id)
            if plan.side_effect in {
                AgentSideEffect.CONTROL_WRITE,
                AgentSideEffect.EXTERNAL_WRITE,
            }:
                if binding is None:
                    raise ValueError("high-risk task graph step requires an approval binding")
                expected_tool_call_id = derive_agent_tool_call_id(
                    run_id=workflow_input.agent_run.run_id,
                    step_id=step.step_id,
                    idempotency_key=plan.idempotency_key,
                )
                if (
                    binding.tenant_id != workflow_input.tenant_id
                    or binding.workflow_id != workflow_input.identity.workflow_id
                    or binding.run_id != workflow_input.agent_run.run_id
                    or binding.graph_sha256 != graph.graph_sha256
                    or binding.step_id != step.step_id
                    or binding.agent_id != step.agent_id
                    or binding.role is not step.role
                    or binding.tool_call_id != expected_tool_call_id
                    or binding.tool_ref != plan.tool_ref
                    or binding.capability_ref != plan.capability_ref
                    or binding.policy_decision_ref != plan.policy_decision_ref
                    or binding.subject_context != plan.subject_context
                    or binding.side_effect is not plan.side_effect
                    or binding.idempotency_key != plan.idempotency_key
                ):
                    raise ValueError("approval binding differs from high-risk task step")
            elif binding is not None:
                raise ValueError("read-only task step cannot carry an approval binding")

        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "execution_input_sha256",
        )
        if self.execution_input_sha256 != expected:
            raise ValueError("execution_input_sha256 does not match task graph execution input")
        return self


def compile_temporal_task_graph_execution_input(
    workflow_input: TemporalWorkflowInput,
    agent_spec: AgentSpecVersion,
    *,
    tool_ref_by_agent: Mapping[str, str],
    capability_ref_by_agent: Mapping[str, str] | None = None,
    side_effect_by_agent: Mapping[str, AgentSideEffect] | None = None,
    approval_owner_ref_by_agent: Mapping[str, str] | None = None,
    approver_scope_by_agent: Mapping[str, str] | None = None,
    activity_type: str = TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
    provider_spec_by_agent: Mapping[str, TemporalProviderExecutionSpec] | None = None,
    schedule_to_close_timeout_seconds: float = 600.0,
    start_to_close_timeout_seconds: float = 300.0,
    heartbeat_timeout_seconds: float = 30.0,
    cancellation_type: TemporalActivityCancellationType = (
        TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
    ),
) -> TemporalTaskGraphExecutionInput:
    """Compile exact specialist bindings after checking AgentSpec authorization."""

    graph = workflow_input.task_graph
    expected_agent_ids = {step.agent_id for step in graph.steps}
    if set(tool_ref_by_agent) != expected_agent_ids:
        raise ValueError("tool_ref_by_agent must bind every task graph agent exactly once")
    if capability_ref_by_agent is not None and set(capability_ref_by_agent) != expected_agent_ids:
        raise ValueError("capability_ref_by_agent must bind every task graph agent exactly once")
    unknown_provider_spec_agents = set(provider_spec_by_agent or ()) - expected_agent_ids
    if unknown_provider_spec_agents:
        raise ValueError("provider_spec_by_agent references an unknown task graph agent")
    unknown_side_effect_agents = set(side_effect_by_agent or ()) - expected_agent_ids
    if unknown_side_effect_agents:
        raise ValueError("side_effect_by_agent references an unknown task graph agent")

    node_by_id = {node.agent_id: node for node in agent_spec.topology.nodes}
    plan_values: list[dict[str, Any]] = []
    for step in graph.steps:
        node = node_by_id.get(step.agent_id)
        if node is None:
            raise ValueError("task graph agent is missing from AgentSpec")
        if capability_ref_by_agent is None:
            if len(node.capability_refs) != 1:
                raise ValueError(
                    "agents with multiple capabilities require an explicit capability binding"
                )
            capability_ref = node.capability_refs[0]
        else:
            capability_ref = capability_ref_by_agent[step.agent_id]
        values: dict[str, Any] = {
            "tenant_id": workflow_input.tenant_id,
            "workflow_id": workflow_input.identity.workflow_id,
            "run_id": workflow_input.agent_run.run_id,
            "step_id": step.step_id,
            "agent_id": step.agent_id,
            "role": step.role,
            "sequence_no": step.sequence_no,
            "activity_type": activity_type,
            "task_queue_ref": workflow_input.identity.task_queue.queue_ref,
            "task_queue_sha256": workflow_input.identity.task_queue.queue_sha256,
            "tool_ref": tool_ref_by_agent[step.agent_id],
            "capability_ref": capability_ref,
            "policy_decision_ref": workflow_input.policy_decision_ref,
            "subject_context": workflow_input.subject_context,
            "side_effect": (side_effect_by_agent or {}).get(step.agent_id, AgentSideEffect.NONE),
            "idempotency_key": (
                f"agentops:{workflow_input.agent_run.run_id}:{step.step_id}:{step.agent_id}"
            ),
            "schedule_to_close_timeout_seconds": float(schedule_to_close_timeout_seconds),
            "start_to_close_timeout_seconds": float(start_to_close_timeout_seconds),
            "heartbeat_timeout_seconds": float(heartbeat_timeout_seconds),
            "cancellation_type": cancellation_type,
            "sdk_maximum_attempts": 1,
        }
        provider_spec = (provider_spec_by_agent or {}).get(step.agent_id)
        if provider_spec is not None:
            values["provider_spec"] = provider_spec
        values["plan_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA,
            values,
            "plan_sha256",
        )
        plan_values.append(values)

    plans = tuple(TemporalSpecialistActivityPlan(**values) for values in plan_values)
    approval_bindings: list[TemporalStepApprovalBinding] = []
    for step, plan in zip(graph.steps, plans, strict=True):
        if plan.side_effect not in {
            AgentSideEffect.CONTROL_WRITE,
            AgentSideEffect.EXTERNAL_WRITE,
        }:
            continue
        owner_ref = (approval_owner_ref_by_agent or {}).get(step.agent_id, "team:geo-platform")
        scope_ref = (approver_scope_by_agent or {}).get(
            step.agent_id, "team:geo-platform-approvers"
        )
        approval_bindings.append(
            compile_temporal_step_approval_binding(
                tenant_id=workflow_input.tenant_id,
                workflow_id=workflow_input.identity.workflow_id,
                run_id=workflow_input.agent_run.run_id,
                graph_sha256=graph.graph_sha256,
                step_id=step.step_id,
                agent_id=step.agent_id,
                role=step.role,
                tool_ref=plan.tool_ref,
                capability_ref=plan.capability_ref,
                policy_decision_ref=plan.policy_decision_ref,
                subject_context=plan.subject_context,
                side_effect=plan.side_effect,
                idempotency_key=plan.idempotency_key,
                approval_owner_ref=owner_ref,
                approver_scope_ref=scope_ref,
            )
        )
    manifest_values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "workflow_id": workflow_input.identity.workflow_id,
        "run_id": workflow_input.agent_run.run_id,
        "graph_sha256": graph.graph_sha256,
        "plans": plans,
    }
    manifest_values["manifest_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA,
        manifest_values,
        "manifest_sha256",
    )
    manifest = TemporalTaskGraphExecutionManifest(**manifest_values)
    input_values: dict[str, Any] = {
        "workflow_input": workflow_input,
        "agent_spec": agent_spec,
        "execution_manifest": manifest,
        "approval_bindings": tuple(approval_bindings),
    }
    input_values["execution_input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA,
        input_values,
        "execution_input_sha256",
    )
    return TemporalTaskGraphExecutionInput(**input_values)


__all__ = [
    "TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE",
    "TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA",
    "TemporalTaskGraphExecutionInput",
    "compile_temporal_task_graph_execution_input",
]
