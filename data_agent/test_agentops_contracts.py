from __future__ import annotations

from uuid import UUID

import pytest

from data_agent.agentops_contracts import (
    AgentBudget,
    AgentDeploymentEnvironment,
    AgentDeploymentRevision,
    AgentEdgeKind,
    AgentEvaluationBinding,
    AgentNodeSpec,
    AgentOnlineVerdict,
    AgentRole,
    AgentRolloutStrategy,
    AgentRun,
    AgentRunStatus,
    AgentSideEffect,
    AgentSpecVersion,
    AgentStepStatus,
    AgentTaskStep,
    AgentToolCall,
    AgentToolCallStatus,
    AgentTopology,
    AgentTopologyEdge,
    AgentVerdict,
    agent_contract_fingerprint,
    agent_deployment_revision_fingerprint,
    agent_run_fingerprint,
    agent_spec_fingerprint,
)
from data_agent.agentops_task_graph import (
    AGENT_TASK_GRAPH_SCHEMA,
    AgentTaskGraph,
    compile_agent_task_graph,
)
from data_agent.agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA,
    TEMPORAL_INPUT_SCHEMA,
    TEMPORAL_NAMESPACE_SCHEMA,
    TEMPORAL_RETRY_SCHEMA,
    TEMPORAL_SIGNAL_SCHEMA,
    TEMPORAL_TASK_QUEUE_SCHEMA,
    TEMPORAL_WORKFLOW_SCHEMA,
    TemporalActivityEvidence,
    TemporalActivityOutcome,
    TemporalContractError,
    TemporalIntegrationHarness,
    TemporalIsolationClass,
    TemporalNamespaceIdentity,
    TemporalRetryPolicy,
    TemporalSignal,
    TemporalSignalKind,
    TemporalTaskQueueIdentity,
    TemporalWorkflowIdentity,
    TemporalWorkflowInput,
    derive_temporal_workflow_id,
    temporal_contract_fingerprint,
)
from data_agent.platform_contracts import SubjectContext, SubjectType


def _topology() -> AgentTopology:
    def node(agent_id: str, role: AgentRole, capability: str) -> AgentNodeSpec:
        return AgentNodeSpec(
            agent_id=agent_id,
            role=role,
            capability_refs=(capability,),
            model_binding_ref=f"model:{agent_id}:v1",
            policy_ref=f"policy:{agent_id}:v1",
        )

    return AgentTopology(
        coordinator_agent_id="coordinator",
        nodes=(
            node("coordinator", AgentRole.SUPERVISOR, "agent.coordinate"),
            node("planner", AgentRole.PLANNER, "data.product.plan"),
            node("data_engineer", AgentRole.DATA_ENGINEER, "data.product.execute"),
            node("fusion", AgentRole.MULTIMODAL_FUSION, "mmfe.semantic_fusion.execute"),
            node("gwm", AgentRole.GWM_SPECIALIST, "gwm.observation.project"),
            node("quality", AgentRole.QUALITY_GUARDIAN, "data.quality.evaluate"),
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
                kind=AgentEdgeKind.FEEDS,
            ),
            AgentTopologyEdge(
                from_agent_id="fusion",
                to_agent_id="quality",
                kind=AgentEdgeKind.FEEDS,
            ),
            AgentTopologyEdge(
                from_agent_id="gwm",
                to_agent_id="quality",
                kind=AgentEdgeKind.FEEDS,
            ),
        ),
    )


def _spec() -> AgentSpecVersion:
    values = {
        "tenant_id": "planning",
        "agent_urn": "gda://planning/agent/gis-platform",
        "version_key": "v1.0.0",
        "topology": _topology(),
        "prompt_refs": ("prompt:planner:v1", "prompt:supervisor:v1"),
        "tool_refs": (
            "tool:data_product:v1",
            "tool:gwm:v1",
            "tool:mmfe:v1",
        ),
        "memory_context_ref": "memory:planning:governed:v1",
        "budget": AgentBudget(
            max_steps=100,
            max_tool_calls=200,
            max_tokens=100_000,
            max_cost_usd=50,
            max_wall_seconds=1_800,
        ),
        "evaluation_set_ref": "gda://planning/evaluation_set/gis-platform-v1",
    }
    values["spec_sha256"] = agent_spec_fingerprint(values)
    return AgentSpecVersion(**values)


def _evaluation(spec: AgentSpecVersion) -> AgentEvaluationBinding:
    values = {
        "tenant_id": "planning",
        "agent_spec_sha256": spec.spec_sha256,
        "evaluation_set_ref": "gda://planning/evaluation_set/gis-platform-v1",
        "evaluator_ref": "evaluator:agentops:quality-v1",
        "min_pass_rate": 0.9,
        "max_failure_rate": 0.1,
    }
    values["binding_sha256"] = agent_contract_fingerprint(
        "gda.agent_evaluation_binding.v1", values, "binding_sha256"
    )
    return AgentEvaluationBinding(**values)


def _deployment(
    spec: AgentSpecVersion, evaluation: AgentEvaluationBinding
) -> AgentDeploymentRevision:
    values = {
        "tenant_id": "planning",
        "deployment_urn": "gda://planning/agent_deployment/gis-platform-prod",
        "agent_spec_sha256": spec.spec_sha256,
        "environment": AgentDeploymentEnvironment.PRODUCTION,
        "rollout_strategy": AgentRolloutStrategy.CANARY,
        "traffic_percent": 10,
        "evaluation_binding_sha256": evaluation.binding_sha256,
        "policy_ref": "policy:agentops:production-v1",
        "owner_ref": "team:geo-platform",
        "rollback_pointer_sha256": "f" * 64,
    }
    values["revision_sha256"] = agent_deployment_revision_fingerprint(values)
    return AgentDeploymentRevision(**values)


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id="planning",
        subject_id="agent:gis-platform:coordinator",
        subject_type=SubjectType.AGENT,
        roles=("agent_runner",),
        purpose="governed_data_product_planning",
        trace_id="trace-agentops-1",
        delegated_by="human:planner",
    )


def _run(deployment: AgentDeploymentRevision) -> AgentRun:
    run_id = UUID("00000000-0000-4000-8000-000000000901")
    values = {
        "tenant_id": "planning",
        "run_id": run_id,
        "root_run_id": run_id,
        "parent_run_id": None,
        "deployment_revision_sha256": deployment.revision_sha256,
        "subject_context": _subject(),
        "data_product_version_refs": (
            "gda://planning/data_product/parcel-gold-v1",
        ),
        "idempotency_key": "agent-run:planning:parcel-gold:v1",
        "status": AgentRunStatus.ACCEPTED,
        "state_version": 0,
    }
    values["run_sha256"] = agent_run_fingerprint(values)
    return AgentRun(**values)


def _temporal_input(
    deployment: AgentDeploymentRevision,
    *,
    idempotency_key: str = "agent-run:planning:parcel-gold:v1",
    run: AgentRun | None = None,
    tenant_id: str = "planning",
) -> TemporalWorkflowInput:
    current_run = run or _run(deployment)
    task_graph = compile_agent_task_graph(_spec(), deployment, current_run)
    namespace_values = {
        "tenant_id": tenant_id,
        "isolation_class": TemporalIsolationClass.TENANT,
        "namespace_ref": "gda-planning",
    }
    namespace_values["namespace_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_NAMESPACE_SCHEMA, namespace_values, "namespace_sha256"
    )
    namespace = TemporalNamespaceIdentity(**namespace_values)
    queue_values = {
        "tenant_id": tenant_id,
        "namespace_ref": namespace.namespace_ref,
        "queue_ref": "agentops-gis",
        "worker_identity_ref": "workload:agentops-worker",
    }
    queue_values["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA, queue_values, "queue_sha256"
    )
    queue = TemporalTaskQueueIdentity(**queue_values)
    workflow_values = {
        "tenant_id": tenant_id,
        "namespace": namespace,
        "task_queue": queue,
        "workflow_type": "gda.agentops.gis_product",
            "agent_spec_sha256": deployment.agent_spec_sha256,
        "deployment_revision_sha256": deployment.revision_sha256,
        "idempotency_key": idempotency_key,
    }
    workflow_values["workflow_id"] = derive_temporal_workflow_id(
        tenant_id=tenant_id,
        isolation_class=namespace.isolation_class,
        namespace_ref=namespace.namespace_ref,
        workflow_type=workflow_values["workflow_type"],
        agent_spec_sha256=workflow_values["agent_spec_sha256"],
        deployment_revision_sha256=workflow_values["deployment_revision_sha256"],
        idempotency_key=idempotency_key,
    )
    workflow_values["identity_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_SCHEMA, workflow_values, "identity_sha256"
    )
    identity = TemporalWorkflowIdentity(**workflow_values)
    retry_values = {
        "initial_interval_seconds": 2.0,
        "backoff_coefficient": 2.0,
        "max_interval_seconds": 60.0,
        "max_attempts": 3,
        "non_retryable_error_types": ("PolicyDenied", "ValidationError"),
    }
    retry_values["policy_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_RETRY_SCHEMA, retry_values, "policy_sha256"
    )
    retry = TemporalRetryPolicy(**retry_values)
    input_values = {
        "tenant_id": tenant_id,
        "identity": identity,
        "agent_run": current_run,
        "deployment_revision": deployment,
        "task_graph": task_graph,
        "agent_spec_sha256": identity.agent_spec_sha256,
        "policy_decision_ref": "artifact://policy-decision-agent-run",
        "retry_policy": retry,
        "subject_context": current_run.subject_context,
        "input_artifact_ids": (),
    }
    input_values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, input_values, "input_sha256"
    )
    return TemporalWorkflowInput(**input_values)


def _rehashed_graph(
    graph: AgentTaskGraph,
    *,
    tenant_id: str | None = None,
    run_id: UUID | None = None,
    agent_spec_sha256: str | None = None,
    deployment_revision_sha256: str | None = None,
    step_updates: dict[str, dict[str, object]] | None = None,
) -> AgentTaskGraph:
    """Build a valid graph variant for boundary-tampering tests."""

    values = graph.model_dump(mode="json")
    values["tenant_id"] = tenant_id or values["tenant_id"]
    values["run_id"] = str(run_id or graph.run_id)
    values["agent_spec_sha256"] = agent_spec_sha256 or values["agent_spec_sha256"]
    values["deployment_revision_sha256"] = (
        deployment_revision_sha256 or values["deployment_revision_sha256"]
    )
    updates = step_updates or {}
    steps = []
    for step in values["steps"]:
        updated = dict(step)
        updated["tenant_id"] = values["tenant_id"]
        updated["run_id"] = values["run_id"]
        updated.update(updates.get(updated["agent_id"], {}))
        updated["step_sha256"] = agent_contract_fingerprint(
            "gda.agent_task_step.v1", updated, "step_sha256"
        )
        steps.append(updated)
    values["steps"] = steps
    values["graph_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_GRAPH_SCHEMA, values, "graph_sha256"
    )
    return AgentTaskGraph(**values)


def test_multi_agent_spec_explicitly_models_mmfe_and_gwm_specialists():
    spec = _spec()
    roles = {node.role for node in spec.topology.nodes}
    assert AgentRole.SUPERVISOR in roles
    assert AgentRole.MULTIMODAL_FUSION in roles
    assert AgentRole.GWM_SPECIALIST in roles
    assert spec.topology.coordinator_agent_id == "coordinator"
    assert spec.spec_sha256 == agent_spec_fingerprint(spec)


def test_topology_rejects_cycle_and_unreachable_specialist():
    valid = _topology()
    with pytest.raises(ValueError, match="acyclic"):
        AgentTopology(
            coordinator_agent_id=valid.coordinator_agent_id,
            nodes=valid.nodes,
            edges=valid.edges
            + (
                AgentTopologyEdge(
                    from_agent_id="quality",
                    to_agent_id="planner",
                    kind=AgentEdgeKind.REVIEWS,
                ),
            ),
        )

    with pytest.raises(ValueError, match="reachable"):
        AgentTopology(
            coordinator_agent_id="coordinator",
            nodes=valid.nodes
            + (
                AgentNodeSpec(
                    agent_id="orphan",
                    role=AgentRole.REVIEWER,
                    capability_refs=("agent.review",),
                    model_binding_ref="model:orphan:v1",
                    policy_ref="policy:orphan:v1",
                ),
            ),
            edges=valid.edges,
        )


def test_deployment_revision_requires_evaluated_rollout_and_fingerprint():
    spec = _spec()
    evaluation = _evaluation(spec)
    deployment = _deployment(spec, evaluation)
    assert deployment.rollout_strategy is AgentRolloutStrategy.CANARY
    assert deployment.traffic_percent == 10
    assert deployment.revision_sha256 == agent_deployment_revision_fingerprint(deployment)

    values = deployment.model_dump(mode="json")
    values["rollout_strategy"] = AgentRolloutStrategy.ACTIVE.value
    with pytest.raises(ValueError, match="100 percent"):
        AgentDeploymentRevision(**values)


def test_agent_run_binds_subject_and_data_product_versions():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    run = _run(deployment)
    assert run.root_run_id == run.run_id
    assert run.data_product_version_refs == (
        "gda://planning/data_product/parcel-gold-v1",
    )
    assert run.run_sha256 == agent_run_fingerprint(run)

    values = run.model_dump(mode="json")
    values["root_run_id"] = str(run.run_id)
    values["parent_run_id"] = str(run.run_id)
    with pytest.raises(ValueError, match="parent itself"):
        AgentRun(**values)


def test_task_step_and_tool_call_preserve_policy_and_artifact_correlation():
    spec = _spec()
    run = _run(_deployment(spec, _evaluation(spec)))
    step_values = {
        "tenant_id": "planning",
        "run_id": run.run_id,
        "step_id": UUID("00000000-0000-4000-8000-000000000902"),
        "agent_id": "data_engineer",
        "role": AgentRole.DATA_ENGINEER,
        "sequence_no": 1,
        "depends_on_step_ids": (),
        "status": AgentStepStatus.SUCCEEDED,
        "attempt_no": 1,
        "input_artifact_ids": (),
        "output_artifact_ids": (UUID("00000000-0000-4000-8000-000000000903"),),
    }
    step_values["step_sha256"] = agent_contract_fingerprint(
        "gda.agent_task_step.v1", step_values, "step_sha256"
    )
    step = AgentTaskStep(**step_values)
    tool_values = {
        "tenant_id": "planning",
        "run_id": run.run_id,
        "step_id": step.step_id,
        "tool_call_id": UUID("00000000-0000-4000-8000-000000000904"),
        "tool_ref": "tool:data_product:v1",
        "capability_ref": "data.product.execute@1.0.0",
        "subject_context": _subject(),
        "side_effect": AgentSideEffect.DATA_WRITE,
        "policy_decision_ref": "artifact://policy-decision-904",
        "idempotency_key": "tool-call:904",
        "status": AgentToolCallStatus.SUCCEEDED,
        "input_artifact_ids": (),
        "output_artifact_id": UUID("00000000-0000-4000-8000-000000000905"),
        "external_receipt_artifact_id": None,
    }
    tool_values["tool_call_sha256"] = agent_contract_fingerprint(
        "gda.agent_tool_call.v1", tool_values, "tool_call_sha256"
    )
    tool_call = AgentToolCall(**tool_values)
    assert tool_call.step_id == step.step_id
    assert tool_call.subject_context.delegated_by == "human:planner"

    tool_values["output_artifact_id"] = None
    with pytest.raises(ValueError, match="output artifact"):
        AgentToolCall(**tool_values)


def test_online_verdict_requires_finite_metrics_and_evidence():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    run = _run(deployment)
    values = {
        "tenant_id": "planning",
        "run_id": run.run_id,
        "deployment_revision_sha256": deployment.revision_sha256,
        "verdict": AgentVerdict.PASSED,
        "evaluator_ref": "evaluator:agentops:online-v1",
        "evidence_artifact_id": UUID("00000000-0000-4000-8000-000000000906"),
        "metrics": {"tool_accuracy": 0.98, "policy_violations": 0.0},
    }
    values["verdict_sha256"] = agent_contract_fingerprint(
        "gda.agent_online_verdict.v1", values, "verdict_sha256"
    )
    verdict = AgentOnlineVerdict(**values)
    assert verdict.verdict is AgentVerdict.PASSED

    values["metrics"] = {"tool_accuracy": float("nan")}
    with pytest.raises(ValueError, match="finite"):
        AgentOnlineVerdict(**values)


def test_temporal_identity_is_stable_and_retry_does_not_change_workflow_id():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    first = _temporal_input(deployment)
    second = _temporal_input(deployment)
    assert first.identity.workflow_id == second.identity.workflow_id
    assert first.agent_run.run_id == second.agent_run.run_id
    assert first.retry_policy.policy_sha256 == second.retry_policy.policy_sha256

    changed_key = _temporal_input(
        deployment, idempotency_key="agent-run:planning:parcel-gold:v2"
    )
    assert changed_key.identity.workflow_id != first.identity.workflow_id
    assert derive_temporal_workflow_id(
        tenant_id="planning",
        isolation_class=TemporalIsolationClass.TENANT,
        namespace_ref="gda-planning",
        workflow_type="gda.agentops.gis_product",
        agent_spec_sha256=first.identity.agent_spec_sha256,
        deployment_revision_sha256=first.identity.deployment_revision_sha256,
        idempotency_key=first.agent_run.idempotency_key,
    ) == first.identity.workflow_id


def test_temporal_workflow_identity_includes_tenant_and_isolation_boundary():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    identity = _temporal_input(deployment).identity
    tenant_b = derive_temporal_workflow_id(
        tenant_id="another-tenant",
        isolation_class=identity.namespace.isolation_class,
        namespace_ref=identity.namespace.namespace_ref,
        workflow_type=identity.workflow_type,
        agent_spec_sha256=identity.agent_spec_sha256,
        deployment_revision_sha256=identity.deployment_revision_sha256,
        idempotency_key=identity.idempotency_key,
    )
    isolated = derive_temporal_workflow_id(
        tenant_id=identity.tenant_id,
        isolation_class=TemporalIsolationClass.ISOLATED,
        namespace_ref=identity.namespace.namespace_ref,
        workflow_type=identity.workflow_type,
        agent_spec_sha256=identity.agent_spec_sha256,
        deployment_revision_sha256=identity.deployment_revision_sha256,
        idempotency_key=identity.idempotency_key,
    )
    assert tenant_b != identity.workflow_id
    assert isolated != identity.workflow_id


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("tenant_id", "task graph tenant"),
        ("run_id", "task graph must match AgentRun"),
        ("agent_spec_sha256", "task graph AgentSpec"),
        ("deployment_revision_sha256", "task graph deployment"),
    ),
)
def test_temporal_input_rejects_a_valid_but_mismatched_task_graph(field: str, message: str):
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    workflow_input = _temporal_input(deployment)
    updates: dict[str, object] = {}
    if field == "tenant_id":
        updates[field] = "another-tenant"
    elif field == "run_id":
        updates[field] = UUID("00000000-0000-4000-8000-000000000999")
    else:
        updates[field] = "0" * 64
    graph = _rehashed_graph(workflow_input.task_graph, **updates)
    values = workflow_input.model_dump(mode="json")
    values["task_graph"] = graph.model_dump(mode="json")
    values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, values, "input_sha256"
    )

    with pytest.raises(ValueError, match=message):
        TemporalWorkflowInput(**values)


def test_task_graph_is_part_of_input_fingerprint_but_not_workflow_identity():
    deployment = _deployment(_spec(), _evaluation(_spec()))
    first = _temporal_input(deployment)
    quality = next(step for step in first.task_graph.steps if step.agent_id == "quality")
    changed_dependencies = tuple(
        dependency
        for dependency in quality.depends_on_step_ids
        if dependency != next(
            step.step_id for step in first.task_graph.steps if step.agent_id == "gwm"
        )
    )
    changed_graph = _rehashed_graph(
        first.task_graph,
        step_updates={
            "quality": {"depends_on_step_ids": changed_dependencies},
        },
    )
    values = first.model_dump(mode="json")
    values["task_graph"] = changed_graph.model_dump(mode="json")
    values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, values, "input_sha256"
    )
    changed = TemporalWorkflowInput(**values)

    assert changed.identity.workflow_id == first.identity.workflow_id
    assert changed.task_graph.graph_sha256 != first.task_graph.graph_sha256
    assert changed.input_sha256 != first.input_sha256
    harness = TemporalIntegrationHarness()
    harness.start(first)
    with pytest.raises(TemporalContractError, match="different workflow input"):
        harness.start(changed)


def _signal(
    workflow_input: TemporalWorkflowInput,
    *,
    kind: TemporalSignalKind,
    expected_state_version: int,
    reason: str = "operator decision",
) -> TemporalSignal:
    signal_suffix = {
        TemporalSignalKind.APPROVE: "920",
        TemporalSignalKind.REJECT: "925",
        TemporalSignalKind.PAUSE: "926",
        TemporalSignalKind.RESUME: "927",
        TemporalSignalKind.CANCEL: "928",
        TemporalSignalKind.RECONCILE: "929",
    }[kind]
    values = {
        "tenant_id": workflow_input.tenant_id,
        "workflow_id": workflow_input.identity.workflow_id,
        "run_id": workflow_input.agent_run.run_id,
        "signal_id": UUID(f"00000000-0000-4000-8000-000000000{signal_suffix}"),
        "kind": kind,
        "expected_state_version": expected_state_version,
        "requested_by": "human:operator",
        "reason": reason,
    }
    values["signal_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_SIGNAL_SCHEMA, values, "signal_sha256"
    )
    return TemporalSignal(**values)


def test_temporal_harness_enforces_approval_pause_resume_and_stale_signal():
    deployment = _deployment(_spec(), _evaluation(_spec()))
    workflow_input = _temporal_input(deployment)
    harness = TemporalIntegrationHarness()
    snapshot = harness.start(workflow_input)
    assert snapshot.run.status is AgentRunStatus.ACCEPTED
    assert len(snapshot.history) == 1

    snapshot = harness.transition(
        workflow_input.identity.workflow_id,
        AgentRunStatus.PLANNING,
        actor_ref="workload:temporal-adapter",
        reason="planner started",
    )
    snapshot = harness.transition(
        workflow_input.identity.workflow_id,
        AgentRunStatus.RUNNING,
        actor_ref="workload:temporal-adapter",
        reason="specialists dispatched",
    )
    snapshot = harness.transition(
        workflow_input.identity.workflow_id,
        AgentRunStatus.WAITING_REVIEW,
        actor_ref="workload:quality-guardian",
        reason="write requires approval",
    )
    snapshot = harness.apply_signal(
        _signal(
            workflow_input,
            kind=TemporalSignalKind.APPROVE,
            expected_state_version=snapshot.run.state_version,
        )
    )
    assert snapshot.run.status is AgentRunStatus.RUNNING
    approved_signal = _signal(
        workflow_input,
        kind=TemporalSignalKind.PAUSE,
        expected_state_version=snapshot.run.state_version,
    )
    snapshot = harness.apply_signal(
        approved_signal
    )
    assert snapshot.run.status is AgentRunStatus.PAUSED
    assert harness.apply_signal(approved_signal) == snapshot
    snapshot = harness.apply_signal(
        _signal(
            workflow_input,
            kind=TemporalSignalKind.RESUME,
            expected_state_version=snapshot.run.state_version,
        )
    )
    assert snapshot.run.status is AgentRunStatus.RUNNING
    with pytest.raises(TemporalContractError, match="stale"):
        harness.apply_signal(
            _signal(
                workflow_input,
                kind=TemporalSignalKind.CANCEL,
                expected_state_version=0,
            )
        )


def test_temporal_unknown_provider_outcome_enters_reconciliation_and_is_idempotent():
    deployment = _deployment(_spec(), _evaluation(_spec()))
    workflow_input = _temporal_input(deployment)
    harness = TemporalIntegrationHarness()
    harness.start(workflow_input)
    harness.transition(
        workflow_input.identity.workflow_id,
        AgentRunStatus.PLANNING,
        actor_ref="workload:temporal-adapter",
        reason="planner started",
    )
    activity_values = {
        "tenant_id": "planning",
        "workflow_id": workflow_input.identity.workflow_id,
        "run_id": workflow_input.agent_run.run_id,
        "activity_id": UUID("00000000-0000-4000-8000-000000000921"),
        "tool_call_id": UUID("00000000-0000-4000-8000-000000000922"),
        "idempotency_key": "tool-call:unknown-provider:1",
        "side_effect": AgentSideEffect.DATA_WRITE,
        "outcome": TemporalActivityOutcome.UNKNOWN,
        "policy_decision_ref": "artifact://policy-decision-921",
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "provider_operation_ref": "spark://operation/921",
        "failure_type": None,
    }
    activity_values["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, activity_values, "evidence_sha256"
    )
    evidence = TemporalActivityEvidence(**activity_values)
    snapshot = harness.record_activity(workflow_input.identity.workflow_id, evidence)
    assert snapshot.run.status is AgentRunStatus.RECONCILING
    assert len(snapshot.activity_evidence) == 1
    assert harness.record_activity(workflow_input.identity.workflow_id, evidence) == snapshot

    changed = dict(activity_values)
    changed["provider_operation_ref"] = "spark://operation/other"
    changed["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, changed, "evidence_sha256"
    )
    with pytest.raises(TemporalContractError, match="reused"):
        harness.record_activity(
            workflow_input.identity.workflow_id, TemporalActivityEvidence(**changed)
        )


def test_temporal_unknown_outcome_cannot_partially_write_after_terminal_run():
    deployment = _deployment(_spec(), _evaluation(_spec()))
    workflow_input = _temporal_input(deployment)
    harness = TemporalIntegrationHarness()
    harness.start(workflow_input)
    for status in (
        AgentRunStatus.PLANNING,
        AgentRunStatus.RUNNING,
        AgentRunStatus.SUCCEEDED,
    ):
        harness.transition(
            workflow_input.identity.workflow_id,
            status,
            actor_ref="workload:temporal-adapter",
            reason="progress",
        )
    values = {
        "tenant_id": "planning",
        "workflow_id": workflow_input.identity.workflow_id,
        "run_id": workflow_input.agent_run.run_id,
        "activity_id": UUID("00000000-0000-4000-8000-000000000923"),
        "tool_call_id": UUID("00000000-0000-4000-8000-000000000924"),
        "idempotency_key": "tool-call:unknown-after-terminal:1",
        "side_effect": AgentSideEffect.DATA_WRITE,
        "outcome": TemporalActivityOutcome.UNKNOWN,
        "policy_decision_ref": "artifact://policy-decision-923",
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "provider_operation_ref": "spark://operation/923",
        "failure_type": None,
    }
    values["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, values, "evidence_sha256"
    )
    with pytest.raises(TemporalContractError, match="not allowed"):
        harness.record_activity(
            workflow_input.identity.workflow_id, TemporalActivityEvidence(**values)
        )
    snapshot = harness.get(workflow_input.identity.workflow_id)
    assert snapshot.run.status is AgentRunStatus.SUCCEEDED
    assert snapshot.activity_evidence == ()
