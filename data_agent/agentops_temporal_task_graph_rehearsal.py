"""Deterministic six-specialist input and activity for Temporal runtime acceptance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .agentops_contracts import (
    AgentBudget,
    AgentDeploymentEnvironment,
    AgentDeploymentRevision,
    AgentEdgeKind,
    AgentEvaluationBinding,
    AgentNodeSpec,
    AgentRole,
    AgentRolloutStrategy,
    AgentRun,
    AgentRunStatus,
    AgentSideEffect,
    AgentSpecVersion,
    AgentTopology,
    AgentTopologyEdge,
    agent_contract_fingerprint,
    agent_deployment_revision_fingerprint,
    agent_run_fingerprint,
    agent_spec_fingerprint,
)
from .agentops_task_graph import compile_agent_task_graph
from .agentops_temporal_adapter import TemporalProviderActivityResult
from .agentops_temporal_contracts import (
    TEMPORAL_INPUT_SCHEMA,
    TEMPORAL_NAMESPACE_SCHEMA,
    TEMPORAL_RETRY_SCHEMA,
    TEMPORAL_TASK_QUEUE_SCHEMA,
    TEMPORAL_WORKFLOW_SCHEMA,
    TemporalActivityOutcome,
    TemporalActivityRequest,
    TemporalIsolationClass,
    TemporalNamespaceIdentity,
    TemporalProviderExecutionSpec,
    TemporalRetryPolicy,
    TemporalTaskQueueIdentity,
    TemporalWorkflowIdentity,
    TemporalWorkflowInput,
    derive_temporal_workflow_id,
    temporal_contract_fingerprint,
)
from .agentops_temporal_task_graph_execution import (
    TemporalTaskGraphExecutionInput,
    compile_temporal_task_graph_execution_input,
)
from .agentops_temporal_task_graph_runtime import (
    TASK_GRAPH_WORKFLOW_TYPE,
    build_specialist_activity_definition,
)
from .platform_contracts import SubjectContext, SubjectType

REHEARSAL_TENANT_ID = "planning"
REHEARSAL_WORKER_IDENTITY = "workload:gda-agentops-task-graph-rehearsal-v1"
REHEARSAL_GWM_TOOL_REF = "tool:gwm:v1"


def _node(agent_id: str, role: AgentRole, capability: str) -> AgentNodeSpec:
    return AgentNodeSpec(
        agent_id=agent_id,
        role=role,
        capability_refs=(capability,),
        model_binding_ref=f"model:{agent_id}:rehearsal-v1",
        policy_ref=f"policy:{agent_id}:rehearsal-v1",
    )


def _agent_spec() -> AgentSpecVersion:
    topology = AgentTopology(
        coordinator_agent_id="coordinator",
        nodes=(
            _node("coordinator", AgentRole.SUPERVISOR, "agent.coordinate"),
            _node("planner", AgentRole.PLANNER, "data.product.plan"),
            _node("data_engineer", AgentRole.DATA_ENGINEER, "data.product.execute"),
            _node(
                "fusion",
                AgentRole.MULTIMODAL_FUSION,
                "mmfe.semantic_fusion.execute",
            ),
            _node("gwm", AgentRole.GWM_SPECIALIST, "gwm.observation.project"),
            _node("quality", AgentRole.QUALITY_GUARDIAN, "data.quality.evaluate"),
        ),
        edges=(
            AgentTopologyEdge(
                from_agent_id="coordinator",
                to_agent_id="planner",
                kind=AgentEdgeKind.DELEGATES,
            ),
            AgentTopologyEdge(
                from_agent_id="planner",
                to_agent_id="data_engineer",
                kind=AgentEdgeKind.DELEGATES,
            ),
            AgentTopologyEdge(
                from_agent_id="planner",
                to_agent_id="fusion",
                kind=AgentEdgeKind.DELEGATES,
            ),
            AgentTopologyEdge(
                from_agent_id="planner",
                to_agent_id="gwm",
                kind=AgentEdgeKind.DELEGATES,
            ),
            AgentTopologyEdge(
                from_agent_id="data_engineer",
                to_agent_id="quality",
                kind=AgentEdgeKind.PARALLEL_JOIN,
            ),
            AgentTopologyEdge(
                from_agent_id="fusion",
                to_agent_id="quality",
                kind=AgentEdgeKind.PARALLEL_JOIN,
            ),
            AgentTopologyEdge(
                from_agent_id="gwm",
                to_agent_id="quality",
                kind=AgentEdgeKind.PARALLEL_JOIN,
            ),
        ),
    )
    values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "agent_urn": "gda://planning/agent/temporal-task-graph-rehearsal",
        "version_key": "v1.0.0",
        "topology": topology,
        "prompt_refs": ("prompt:agentops-task-graph-rehearsal:v1",),
        "tool_refs": (
            "tool:data_product:v1",
            REHEARSAL_GWM_TOOL_REF,
            "tool:mmfe:v1",
        ),
        "memory_context_ref": None,
        "budget": AgentBudget(
            max_steps=20,
            max_tool_calls=20,
            max_tokens=20_000,
            max_cost_usd=1,
            max_wall_seconds=600,
        ),
        "evaluation_set_ref": "gda://planning/evaluation_set/temporal-rehearsal-v1",
    }
    values["spec_sha256"] = agent_spec_fingerprint(values)
    return AgentSpecVersion(**values)


def _deployment(spec: AgentSpecVersion) -> AgentDeploymentRevision:
    evaluation_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "agent_spec_sha256": spec.spec_sha256,
        "evaluation_set_ref": spec.evaluation_set_ref,
        "evaluator_ref": "evaluator:agentops-task-graph-rehearsal:v1",
        "min_pass_rate": 1.0,
        "max_failure_rate": 0.0,
    }
    evaluation_values["binding_sha256"] = agent_contract_fingerprint(
        AgentEvaluationBinding.schema_id,
        evaluation_values,
        "binding_sha256",
    )
    evaluation = AgentEvaluationBinding(**evaluation_values)
    values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "deployment_urn": ("gda://planning/agent_deployment/temporal-task-graph-rehearsal"),
        "agent_spec_sha256": spec.spec_sha256,
        "environment": AgentDeploymentEnvironment.TEST,
        "rollout_strategy": AgentRolloutStrategy.ACTIVE,
        "traffic_percent": 100,
        "evaluation_binding_sha256": evaluation.binding_sha256,
        "policy_ref": "policy:agentops-task-graph-rehearsal:v1",
        "owner_ref": "team:geo-platform",
        "rollback_pointer_sha256": None,
    }
    values["revision_sha256"] = agent_deployment_revision_fingerprint(values)
    return AgentDeploymentRevision(**values)


def build_rehearsal_execution_input(
    *,
    namespace_ref: str,
    task_queue_ref: str,
    run_key: str,
    side_effect_by_agent: Mapping[str, AgentSideEffect] | None = None,
    input_artifact_ids: tuple[UUID, ...] = (),
    provider_spec_by_agent: Mapping[str, TemporalProviderExecutionSpec] | None = None,
) -> TemporalTaskGraphExecutionInput:
    spec = _agent_spec()
    deployment = _deployment(spec)
    run_id = uuid5(NAMESPACE_URL, f"gda-agentops-task-graph-rehearsal:{run_key}")
    subject = SubjectContext(
        tenant_id=REHEARSAL_TENANT_ID,
        subject_id=REHEARSAL_WORKER_IDENTITY,
        subject_type=SubjectType.WORKLOAD,
        roles=("agentops_rehearsal",),
        purpose="Temporal multi-specialist task graph runtime acceptance",
        trace_id=f"task-graph-{str(run_id)[:12]}",
    )
    run_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "run_id": run_id,
        "root_run_id": run_id,
        "parent_run_id": None,
        "deployment_revision_sha256": deployment.revision_sha256,
        "subject_context": subject,
        "data_product_version_refs": (),
        "idempotency_key": f"agentops-task-graph-rehearsal:{run_key}",
        "status": AgentRunStatus.ACCEPTED,
        "state_version": 0,
    }
    run_values["run_sha256"] = agent_run_fingerprint(run_values)
    run = AgentRun(**run_values)
    graph = compile_agent_task_graph(spec, deployment, run)

    namespace_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "isolation_class": TemporalIsolationClass.TENANT,
        "namespace_ref": namespace_ref,
    }
    namespace_values["namespace_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_NAMESPACE_SCHEMA,
        namespace_values,
        "namespace_sha256",
    )
    namespace = TemporalNamespaceIdentity(**namespace_values)
    queue_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "namespace_ref": namespace_ref,
        "queue_ref": task_queue_ref,
        "worker_identity_ref": REHEARSAL_WORKER_IDENTITY,
    }
    queue_values["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA,
        queue_values,
        "queue_sha256",
    )
    queue = TemporalTaskQueueIdentity(**queue_values)
    idempotency_key = f"agentops-task-graph-rehearsal:{run_key}"
    workflow_id = derive_temporal_workflow_id(
        tenant_id=REHEARSAL_TENANT_ID,
        isolation_class=namespace.isolation_class,
        namespace_ref=namespace_ref,
        workflow_type=TASK_GRAPH_WORKFLOW_TYPE,
        agent_spec_sha256=spec.spec_sha256,
        deployment_revision_sha256=deployment.revision_sha256,
        idempotency_key=idempotency_key,
    )
    identity_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "namespace": namespace,
        "task_queue": queue,
        "workflow_type": TASK_GRAPH_WORKFLOW_TYPE,
        "agent_spec_sha256": spec.spec_sha256,
        "deployment_revision_sha256": deployment.revision_sha256,
        "idempotency_key": idempotency_key,
        "workflow_id": workflow_id,
    }
    identity_values["identity_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_SCHEMA,
        identity_values,
        "identity_sha256",
    )
    identity = TemporalWorkflowIdentity(**identity_values)
    retry_values: dict[str, Any] = {
        "initial_interval_seconds": 0.1,
        "backoff_coefficient": 1.0,
        "max_interval_seconds": 0.1,
        "max_attempts": 3,
        "non_retryable_error_types": ("PolicyDenied", "ValidationError"),
    }
    retry_values["policy_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_RETRY_SCHEMA,
        retry_values,
        "policy_sha256",
    )
    retry = TemporalRetryPolicy(**retry_values)
    workflow_values: dict[str, Any] = {
        "tenant_id": REHEARSAL_TENANT_ID,
        "identity": identity,
        "agent_run": run,
        "deployment_revision": deployment,
        "task_graph": graph,
        "agent_spec_sha256": spec.spec_sha256,
        "policy_decision_ref": "artifact://agentops-task-graph-rehearsal-policy",
        "retry_policy": retry,
        "subject_context": subject,
        "input_artifact_ids": input_artifact_ids,
    }
    workflow_values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA,
        workflow_values,
        "input_sha256",
    )
    workflow_input = TemporalWorkflowInput(**workflow_values)
    return compile_temporal_task_graph_execution_input(
        workflow_input,
        spec,
        tool_ref_by_agent={
            "coordinator": "tool:data_product:v1",
            "planner": "tool:data_product:v1",
            "data_engineer": "tool:data_product:v1",
            "fusion": "tool:mmfe:v1",
            "gwm": REHEARSAL_GWM_TOOL_REF,
            "quality": "tool:data_product:v1",
        },
        side_effect_by_agent=side_effect_by_agent
        or {
            "data_engineer": AgentSideEffect.DATA_WRITE,
            "fusion": AgentSideEffect.DATA_WRITE,
        },
        provider_spec_by_agent=provider_spec_by_agent,
        schedule_to_close_timeout_seconds=60,
        start_to_close_timeout_seconds=30,
        heartbeat_timeout_seconds=10,
    )


def _artifact_id(prefix: str, request: TemporalActivityRequest) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"{prefix}:{request.run_id}:{request.step_id}:{request.attempt_no}",
    )


def rehearsal_specialist_executor(
    request: TemporalActivityRequest,
) -> TemporalProviderActivityResult:
    transient_gwm_failure = request.tool_ref == REHEARSAL_GWM_TOOL_REF and request.attempt_no == 1
    outcome = (
        TemporalActivityOutcome.FAILED
        if transient_gwm_failure
        else TemporalActivityOutcome.SUCCEEDED
    )
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": outcome,
        "provider_receipt_ref": (
            f"temporal://task-graph-rehearsal/{request.workflow_id}/{request.activity_id}"
        ),
        "provider_operation_ref": None,
        "output_artifact_id": (
            None
            if transient_gwm_failure
            else _artifact_id("gda-agentops-specialist-output", request)
        ),
        "external_receipt_artifact_id": None,
        "failure_type": "SyntheticTransientFailure" if transient_gwm_failure else None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id,
        values,
        "result_sha256",
    )
    return TemporalProviderActivityResult(**values)


rehearsal_specialist_activity = build_specialist_activity_definition(rehearsal_specialist_executor)


__all__ = [
    "REHEARSAL_GWM_TOOL_REF",
    "REHEARSAL_TENANT_ID",
    "REHEARSAL_WORKER_IDENTITY",
    "build_rehearsal_execution_input",
    "rehearsal_specialist_activity",
    "rehearsal_specialist_executor",
]
