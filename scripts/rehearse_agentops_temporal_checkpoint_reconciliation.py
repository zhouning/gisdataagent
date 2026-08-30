#!/usr/bin/env python3
"""Rehearse Temporal history reconciliation against GDA AgentOps checkpoints."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from temporalio import activity, workflow
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.worker import Replayer

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_contracts import (
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
    from data_agent.agentops_task_graph import compile_agent_task_graph
    from data_agent.agentops_temporal_contracts import (
        TEMPORAL_INPUT_SCHEMA,
        TEMPORAL_NAMESPACE_SCHEMA,
        TEMPORAL_RETRY_SCHEMA,
        TEMPORAL_TASK_QUEUE_SCHEMA,
        TEMPORAL_WORKFLOW_SCHEMA,
        TemporalActivityCancellationType,
        TemporalIsolationClass,
        TemporalNamespaceIdentity,
        TemporalRetryPolicy,
        TemporalTaskQueueIdentity,
        TemporalWorkflowIdentity,
        TemporalWorkflowInput,
        derive_temporal_workflow_id,
        temporal_contract_fingerprint,
    )
    from data_agent.agentops_temporal_reconciliation import (
        TemporalCheckpointReconciliationVerdict,
        activity_evidence_from_history,
        reconcile_temporal_checkpoint,
    )
    from data_agent.agentops_temporal_rehearsal import _REHEARSAL_HANDLER
    from data_agent.agentops_temporal_worker import (
        TemporalioWorkerFactory,
        TemporalWorkerDefinition,
        TemporalWorkerRuntimeConfig,
    )
    from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
    from data_agent.agentops_temporalio_provider import TemporalioProviderClient
    from data_agent.platform_contracts import (
        SubjectContext,
        SubjectType,
        canonical_json_fingerprint,
    )

REPORT_SCHEMA = "gda.agentops_temporal_checkpoint_reconciliation_report.v1"
ENVELOPE_SCHEMA = "gda.temporal_checkpoint_reconciliation_rehearsal.v1"
WORKFLOW_TYPE = "gda.agentops.checkpoint-reconciliation.v1"
ACTIVITY_TYPE = "gda.agentops.checkpoint-reconciliation.activity"
RELEASE_SIGNAL = "gda_agentops_checkpoint_reconciliation_release"
TENANT_ID = "planning"
WORKER_IDENTITY = "workload:gda-agentops-checkpoint-reconciliation-v1"
TOOL_REF = "tool:agentops-temporal-reconciliation:v1"
CAPABILITY_REF = "capability:agentops.temporal.reconciliation:v1"
TOOL_IDEMPOTENCY_KEY = "agentops-temporal-checkpoint-reconciliation:tool-call"


def build_workflow_input(
    *, namespace_ref: str, task_queue_ref: str, rehearsal_id: str
) -> TemporalWorkflowInput:
    """Build a complete, immutable AgentOps start input without test fixtures."""

    topology = AgentTopology(
        coordinator_agent_id="coordinator",
        nodes=(
            AgentNodeSpec(
                agent_id="coordinator",
                role=AgentRole.SUPERVISOR,
                capability_refs=("agent.coordinate",),
                model_binding_ref="model:checkpoint-reconciliation:v1",
                policy_ref="policy:agentops-reconciliation:v1",
            ),
            AgentNodeSpec(
                agent_id="quality",
                role=AgentRole.QUALITY_GUARDIAN,
                capability_refs=("agent.evidence.verify",),
                model_binding_ref="model:checkpoint-quality:v1",
                policy_ref="policy:agentops-reconciliation:v1",
            ),
        ),
        edges=(
            AgentTopologyEdge(
                from_agent_id="coordinator",
                to_agent_id="quality",
                kind=AgentEdgeKind.FEEDS,
            ),
        ),
    )
    spec_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "agent_urn": "gda://planning/agent/checkpoint-reconciliation",
        "version_key": "v1.0.0",
        "topology": topology,
        "prompt_refs": ("prompt:checkpoint-reconciliation:v1",),
        "tool_refs": (TOOL_REF,),
        "memory_context_ref": "memory:agentops-reconciliation:v1",
        "budget": AgentBudget(
            max_steps=4,
            max_tool_calls=4,
            max_tokens=1_000,
            max_cost_usd=1,
            max_wall_seconds=300,
        ),
        "evaluation_set_ref": "gda://planning/evaluation_set/checkpoint-reconciliation-v1",
    }
    spec_values["spec_sha256"] = agent_spec_fingerprint(spec_values)
    spec = AgentSpecVersion(**spec_values)

    evaluation_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "agent_spec_sha256": spec.spec_sha256,
        "evaluation_set_ref": spec.evaluation_set_ref,
        "evaluator_ref": "evaluator:agentops-reconciliation:v1",
        "min_pass_rate": 1.0,
        "max_failure_rate": 0.0,
    }
    evaluation_values["binding_sha256"] = agent_contract_fingerprint(
        AgentEvaluationBinding.schema_id,
        evaluation_values,
        "binding_sha256",
    )
    evaluation = AgentEvaluationBinding(**evaluation_values)
    deployment_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "deployment_urn": "gda://planning/agent_deployment/checkpoint-reconciliation-sandbox",
        "agent_spec_sha256": spec.spec_sha256,
        "environment": AgentDeploymentEnvironment.TEST,
        "rollout_strategy": AgentRolloutStrategy.ACTIVE,
        "traffic_percent": 100,
        "evaluation_binding_sha256": evaluation.binding_sha256,
        "policy_ref": "policy:agentops-reconciliation:v1",
        "owner_ref": "team:geo-platform",
        "rollback_pointer_sha256": "f" * 64,
    }
    deployment_values["revision_sha256"] = agent_deployment_revision_fingerprint(
        deployment_values
    )
    deployment = AgentDeploymentRevision(**deployment_values)

    subject = SubjectContext(
        tenant_id=TENANT_ID,
        subject_id=WORKER_IDENTITY,
        subject_type=SubjectType.WORKLOAD,
        roles=("agentops_rehearsal",),
        purpose="Temporal checkpoint reconciliation rehearsal",
        trace_id=f"checkpoint-{rehearsal_id[:8]}",
    )
    run_id = uuid5(NAMESPACE_URL, f"gda-agentops-checkpoint-run:{rehearsal_id}")
    run_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "run_id": run_id,
        "root_run_id": run_id,
        "parent_run_id": None,
        "deployment_revision_sha256": deployment.revision_sha256,
        "subject_context": subject,
        "data_product_version_refs": (),
        "idempotency_key": f"agentops-checkpoint-reconciliation:{rehearsal_id}",
        "status": AgentRunStatus.ACCEPTED,
        "state_version": 0,
    }
    run_values["run_sha256"] = agent_run_fingerprint(run_values)
    agent_run = AgentRun(**run_values)
    task_graph = compile_agent_task_graph(spec, deployment, agent_run)

    namespace_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "isolation_class": TemporalIsolationClass.TENANT,
        "namespace_ref": namespace_ref,
    }
    namespace_values["namespace_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_NAMESPACE_SCHEMA, namespace_values, "namespace_sha256"
    )
    namespace = TemporalNamespaceIdentity(**namespace_values)
    queue_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "namespace_ref": namespace_ref,
        "queue_ref": task_queue_ref,
        "worker_identity_ref": WORKER_IDENTITY,
    }
    queue_values["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA, queue_values, "queue_sha256"
    )
    task_queue = TemporalTaskQueueIdentity(**queue_values)
    identity_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "namespace": namespace,
        "task_queue": task_queue,
        "workflow_type": WORKFLOW_TYPE,
        "agent_spec_sha256": spec.spec_sha256,
        "deployment_revision_sha256": deployment.revision_sha256,
        "idempotency_key": agent_run.idempotency_key,
    }
    identity_values["workflow_id"] = derive_temporal_workflow_id(
        tenant_id=TENANT_ID,
        isolation_class=namespace.isolation_class,
        namespace_ref=namespace_ref,
        workflow_type=WORKFLOW_TYPE,
        agent_spec_sha256=spec.spec_sha256,
        deployment_revision_sha256=deployment.revision_sha256,
        idempotency_key=agent_run.idempotency_key,
    )
    identity_values["identity_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_SCHEMA, identity_values, "identity_sha256"
    )
    identity = TemporalWorkflowIdentity(**identity_values)
    retry_values: dict[str, Any] = {
        "initial_interval_seconds": 1.0,
        "backoff_coefficient": 2.0,
        "max_interval_seconds": 10.0,
        "max_attempts": 1,
        "non_retryable_error_types": ("PolicyDenied", "ValidationError"),
    }
    retry_values["policy_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_RETRY_SCHEMA, retry_values, "policy_sha256"
    )
    retry_policy = TemporalRetryPolicy(**retry_values)
    input_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "identity": identity,
        "agent_run": agent_run,
        "deployment_revision": deployment,
        "task_graph": task_graph,
        "agent_spec_sha256": spec.spec_sha256,
        "policy_decision_ref": "artifact://agentops-checkpoint-reconciliation-policy",
        "retry_policy": retry_policy,
        "subject_context": subject,
        "input_artifact_ids": (),
    }
    input_values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, input_values, "input_sha256"
    )
    return TemporalWorkflowInput(**input_values)


def build_checkpoint_projection(
    workflow_input: TemporalWorkflowInput,
) -> tuple[TemporalTaskGraphWorkflowHarness, Any]:
    """Persist the GDA schedule projection before provider execution is observed."""

    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    step = workflow_input.task_graph.steps[0]
    harness.start_step(workflow_id, step.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref=TOOL_REF,
        capability_ref=CAPABILITY_REF,
        subject_context=workflow_input.subject_context,
        side_effect=AgentSideEffect.NONE,
        policy_decision_ref=workflow_input.policy_decision_ref,
        idempotency_key=TOOL_IDEMPOTENCY_KEY,
    )
    call = snapshot.execution.tool_calls[0]
    harness.dispatch_tool_call(workflow_id, call.tool_call_id)
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type=ACTIVITY_TYPE,
        schedule_to_close_timeout_seconds=60,
        start_to_close_timeout_seconds=30,
        heartbeat_timeout_seconds=10,
        cancellation_type=TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
    )
    return harness, snapshot.activity_schedules[0]


@activity.defn(name=ACTIVITY_TYPE)
async def checkpoint_reconciliation_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return await _REHEARSAL_HANDLER.handle_async(payload)


@workflow.defn(name=WORKFLOW_TYPE)
class CheckpointReconciliationWorkflow:
    def __init__(self) -> None:
        self._released = False

    @workflow.signal(name=RELEASE_SIGNAL)
    async def release(self) -> None:
        self._released = True

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("schema") != ENVELOPE_SCHEMA:
            raise ValueError("checkpoint reconciliation workflow requires rehearsal envelope")
        schedule = payload["schedule"]
        if schedule["sdk_maximum_attempts"] != 1:
            raise ValueError("checkpoint reconciliation refuses hidden activity retries")
        await workflow.wait_condition(lambda: self._released)
        return await workflow.execute_activity(
            ACTIVITY_TYPE,
            schedule["request"],
            task_queue=schedule["task_queue_ref"],
            activity_id=schedule["activity_id"],
            schedule_to_close_timeout=timedelta(
                seconds=schedule["schedule_to_close_timeout_seconds"]
            ),
            start_to_close_timeout=timedelta(
                seconds=schedule["start_to_close_timeout_seconds"]
            ),
            heartbeat_timeout=timedelta(
                seconds=schedule["heartbeat_timeout_seconds"]
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )


def _worker_config(
    workflow_input: TemporalWorkflowInput, *, frontend_target: str
) -> TemporalWorkerRuntimeConfig:
    return TemporalWorkerRuntimeConfig(
        tenant_id=workflow_input.tenant_id,
        namespace_ref=workflow_input.identity.namespace.namespace_ref,
        frontend_target=frontend_target,
        task_queue_ref=workflow_input.identity.task_queue.queue_ref,
        worker_identity_ref=WORKER_IDENTITY,
        workflow_type=WORKFLOW_TYPE,
        activity_types=(ACTIVITY_TYPE,),
        agent_spec_sha256=workflow_input.agent_spec_sha256,
        deployment_revision_sha256=(
            workflow_input.deployment_revision.revision_sha256
        ),
        max_concurrent_activities=1,
        max_concurrent_workflow_tasks=1,
    )


async def run_rehearsal(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> dict[str, Any]:
    rehearsal_id = str(uuid4())
    workflow_input = build_workflow_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        rehearsal_id=rehearsal_id,
    )
    harness, schedule = build_checkpoint_projection(workflow_input)
    workflow_id = workflow_input.identity.workflow_id
    checkpoint_before = harness.checkpoint(workflow_id)
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=WORKER_IDENTITY,
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    config = _worker_config(workflow_input, frontend_target=frontend_target)
    registration = config.registration()
    worker = TemporalioWorkerFactory(
        client,
        registration,
        workflows=(TemporalWorkerDefinition(WORKFLOW_TYPE, CheckpointReconciliationWorkflow),),
        activities=(
            TemporalWorkerDefinition(ACTIVITY_TYPE, checkpoint_reconciliation_activity),
        ),
    ).build()
    provider = TemporalioProviderClient(client, namespace_ref=namespace_ref)
    envelope = {
        "schema": ENVELOPE_SCHEMA,
        "workflow_input": workflow_input.model_dump(mode="json"),
        "workflow_input_sha256": workflow_input.input_sha256,
        "schedule": schedule.model_dump(mode="json"),
    }
    started_at = datetime.now(UTC)
    async with worker:
        handle = await client.start_workflow(
            WORKFLOW_TYPE,
            envelope,
            id=workflow_id,
            task_queue=task_queue_ref,
        )
        provider_run_id = handle.first_execution_run_id
        pre_execution_observation = await provider.observe_workflow_history(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=workflow_id,
            provider_run_id=provider_run_id,
        )
        provider_behind = reconcile_temporal_checkpoint(
            checkpoint_before, pre_execution_observation
        )
        await handle.signal(RELEASE_SIGNAL)
        await handle.result()
    completed_at = datetime.now(UTC)

    final_observation = await provider.observe_workflow_history(
        tenant_id=workflow_input.tenant_id,
        namespace_ref=namespace_ref,
        workflow_id=workflow_id,
        provider_run_id=provider_run_id,
    )
    checkpoint_behind = reconcile_temporal_checkpoint(
        checkpoint_before, final_observation
    )
    evidence = activity_evidence_from_history(final_observation.activities[0])
    harness.record_scheduled_activity(workflow_id, evidence)
    first_step = workflow_input.task_graph.steps[0]
    harness.complete_step(
        workflow_id,
        step_id=first_step.step_id,
        output_artifact_ids=(evidence.output_artifact_id,),
    )
    second_step = workflow_input.task_graph.steps[1]
    harness.start_step(workflow_id, second_step.step_id)
    harness.complete_step(workflow_id, step_id=second_step.step_id)
    checkpoint_after = harness.checkpoint(workflow_id)
    matched = reconcile_temporal_checkpoint(checkpoint_after, final_observation)

    expected_verdicts = (
        provider_behind.verdict,
        checkpoint_behind.verdict,
        matched.verdict,
    )
    if expected_verdicts != (
        TemporalCheckpointReconciliationVerdict.PROVIDER_BEHIND,
        TemporalCheckpointReconciliationVerdict.CHECKPOINT_BEHIND,
        TemporalCheckpointReconciliationVerdict.MATCHED,
    ):
        raise RuntimeError(f"unexpected reconciliation sequence: {expected_verdicts}")
    history = await handle.fetch_history()
    history_json = history.to_json()
    replay = await Replayer(
        workflows=[CheckpointReconciliationWorkflow]
    ).replay_workflow(WorkflowHistory.from_json(workflow_id, history_json))
    if replay.replay_failure is not None:
        raise replay.replay_failure

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": completed_at.isoformat(),
        "status": "passed",
        "frontend_target": frontend_target,
        "namespace_ref": namespace_ref,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "workflow_type": WORKFLOW_TYPE,
        "workflow_id": workflow_id,
        "provider_run_id": provider_run_id,
        "task_queue_ref": task_queue_ref,
        "worker_identity_ref": WORKER_IDENTITY,
        "worker_registration_sha256": registration.registration_sha256,
        "workflow_input_sha256": workflow_input.input_sha256,
        "activity_id": str(schedule.activity_id),
        "activity_request_sha256": schedule.request_sha256,
        "activity_schedule_sha256": schedule.schedule_sha256,
        "provider_history_sha256": final_observation.history_sha256,
        "provider_observation_sha256": final_observation.observation_sha256,
        "checkpoint_before_sha256": checkpoint_before.checkpoint_sha256,
        "checkpoint_after_sha256": checkpoint_after.checkpoint_sha256,
        "provider_behind_reconciliation_sha256": (
            provider_behind.reconciliation_sha256
        ),
        "checkpoint_behind_reconciliation_sha256": (
            checkpoint_behind.reconciliation_sha256
        ),
        "matched_reconciliation_sha256": matched.reconciliation_sha256,
        "verdict_sequence": [item.value for item in expected_verdicts],
        "history_event_count": final_observation.history_event_count,
        "history_replay_status": "passed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": (completed_at - started_at).total_seconds(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return {
        "report": report,
        "history_json": history_json,
        "observation": final_observation.model_dump(mode="json"),
        "checkpoint_before": checkpoint_before.model_dump(mode="json"),
        "checkpoint_after": checkpoint_after.model_dump(mode="json"),
        "provider_behind": provider_behind.model_dump(mode="json"),
        "checkpoint_behind": checkpoint_behind.model_dump(mode="json"),
        "matched": matched.model_dump(mode="json"),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument(
        "--task-queue", default="agentops-checkpoint-reconciliation"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--prefix", default="agentops_temporal_checkpoint_reconciliation_2026-08-27"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    output_dir = args.output_dir
    prefix = args.prefix
    _write_json(output_dir / f"{prefix}.json", evidence["report"])
    (output_dir / f"{prefix}_history.json").write_text(
        evidence["history_json"] + "\n"
    )
    _write_json(output_dir / f"{prefix}_observation.json", evidence["observation"])
    _write_json(
        output_dir / f"{prefix}_checkpoint_before.json",
        evidence["checkpoint_before"],
    )
    _write_json(
        output_dir / f"{prefix}_checkpoint_after.json",
        evidence["checkpoint_after"],
    )
    _write_json(
        output_dir / f"{prefix}_provider_behind.json", evidence["provider_behind"]
    )
    _write_json(
        output_dir / f"{prefix}_checkpoint_behind.json",
        evidence["checkpoint_behind"],
    )
    _write_json(output_dir / f"{prefix}_matched.json", evidence["matched"])
    print(json.dumps(evidence["report"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
