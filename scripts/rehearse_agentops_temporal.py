#!/usr/bin/env python3
"""Run a real AgentOps Temporal activity and replay its exported history."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from data_agent.agentops_contracts import AgentSideEffect
from data_agent.agentops_temporal_adapter import (
    TemporalActivityAdapter,
    TemporalProviderActivityResult,
)
from data_agent.agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_REQUEST_SCHEMA,
    TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
    TEMPORAL_TASK_QUEUE_SCHEMA,
    TemporalActivityCancellationType,
    TemporalActivityRequest,
    TemporalActivitySchedulePlan,
    TemporalTaskQueueIdentity,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_rehearsal import (
    REHEARSAL_ACTIVITY_TYPE,
    REHEARSAL_WORKFLOW_TYPE,
    RehearsalWorkflow,
    rehearsal_activity,
)
from data_agent.agentops_temporal_worker import (
    TemporalioWorkerFactory,
    TemporalWorkerDefinition,
    TemporalWorkerRuntimeConfig,
)
from data_agent.platform_contracts import (
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
)

REPORT_SCHEMA = "gda.agentops_temporal_rehearsal_report.v1"
TENANT_ID = "planning"
WORKER_IDENTITY = "workload:gda-agentops-rehearsal-v1"


def build_schedule_plan(
    *, workflow_id: str, namespace_ref: str, task_queue_ref: str
) -> TemporalActivitySchedulePlan:
    """Build one read-only attempt with deterministic AgentOps correlation."""

    run_id = uuid5(NAMESPACE_URL, f"gda-temporal-rehearsal-run:{workflow_id}")
    step_id = uuid5(NAMESPACE_URL, f"gda-temporal-rehearsal-step:{workflow_id}")
    tool_call_id = uuid5(
        NAMESPACE_URL, f"gda-temporal-rehearsal-tool-call:{workflow_id}"
    )
    activity_id = derive_temporal_activity_id(
        run_id=run_id,
        tool_call_id=tool_call_id,
        attempt_no=1,
    )
    subject = SubjectContext(
        tenant_id=TENANT_ID,
        subject_id=WORKER_IDENTITY,
        subject_type=SubjectType.WORKLOAD,
        roles=("agentops_rehearsal",),
        purpose="Temporal AgentOps provider rehearsal",
        trace_id=f"rehearsal-{str(run_id)[:8]}",
    )
    request_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "step_id": step_id,
        "tool_call_id": tool_call_id,
        "activity_id": activity_id,
        "attempt_no": 1,
        "tool_ref": "tool:agentops-temporal-rehearsal:v1",
        "capability_ref": "capability:agentops.temporal.rehearse:v1",
        "policy_decision_ref": "artifact://agentops-temporal-rehearsal-policy",
        "subject_context": subject,
        "side_effect": AgentSideEffect.NONE,
        "idempotency_key": f"agentops-temporal-rehearsal:{workflow_id}:attempt:1",
        "input_artifact_ids": (),
    }
    request_values["request_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_REQUEST_SCHEMA,
        request_values,
        "request_sha256",
    )
    request = TemporalActivityRequest(**request_values)

    queue_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "namespace_ref": namespace_ref,
        "queue_ref": task_queue_ref,
        "worker_identity_ref": WORKER_IDENTITY,
    }
    queue_values["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA,
        queue_values,
        "queue_sha256",
    )
    queue = TemporalTaskQueueIdentity(**queue_values)
    schedule_values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "step_id": step_id,
        "tool_call_id": tool_call_id,
        "activity_id": activity_id,
        "attempt_no": 1,
        "activity_type": REHEARSAL_ACTIVITY_TYPE,
        "task_queue_ref": queue.queue_ref,
        "task_queue_sha256": queue.queue_sha256,
        "request": request,
        "request_sha256": request.request_sha256,
        "schedule_to_close_timeout_seconds": 60.0,
        "start_to_close_timeout_seconds": 30.0,
        "heartbeat_timeout_seconds": 10.0,
        "cancellation_type": (
            TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
        ),
        "sdk_maximum_attempts": 1,
    }
    schedule_values["schedule_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
        schedule_values,
        "schedule_sha256",
    )
    return TemporalActivitySchedulePlan(**schedule_values)


def _worker_config(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> TemporalWorkerRuntimeConfig:
    agent_spec_sha256 = canonical_json_fingerprint(
        {"schema": "gda.agentops_rehearsal_spec.v1", "workflow": REHEARSAL_WORKFLOW_TYPE}
    )
    deployment_sha256 = canonical_json_fingerprint(
        {
            "schema": "gda.agentops_rehearsal_deployment.v1",
            "agent_spec_sha256": agent_spec_sha256,
            "sdk": "temporalio==1.32.0",
        }
    )
    return TemporalWorkerRuntimeConfig(
        tenant_id=TENANT_ID,
        namespace_ref=namespace_ref,
        frontend_target=frontend_target,
        task_queue_ref=task_queue_ref,
        worker_identity_ref=WORKER_IDENTITY,
        workflow_type=REHEARSAL_WORKFLOW_TYPE,
        activity_types=(REHEARSAL_ACTIVITY_TYPE,),
        agent_spec_sha256=agent_spec_sha256,
        deployment_revision_sha256=deployment_sha256,
        max_concurrent_activities=1,
        max_concurrent_workflow_tasks=1,
    )


async def run_rehearsal(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> tuple[dict[str, Any], str]:
    workflow_id = f"gda-agentops-rehearsal-{uuid4()}"
    schedule = build_schedule_plan(
        workflow_id=workflow_id,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    config = _worker_config(
        frontend_target=frontend_target,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=WORKER_IDENTITY,
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    registration = config.registration()
    worker = TemporalioWorkerFactory(
        client,
        registration,
        workflows=(
            TemporalWorkerDefinition(REHEARSAL_WORKFLOW_TYPE, RehearsalWorkflow),
        ),
        activities=(
            TemporalWorkerDefinition(REHEARSAL_ACTIVITY_TYPE, rehearsal_activity),
        ),
    ).build()
    started_at = datetime.now(UTC)
    async with worker:
        handle = await client.start_workflow(
            REHEARSAL_WORKFLOW_TYPE,
            {
                "schedule": schedule.model_dump(mode="json"),
                "request": schedule.request.model_dump(mode="json"),
            },
            id=workflow_id,
            task_queue=task_queue_ref,
        )
        result_payload = await handle.result()
        workflow_completed_at = datetime.now(UTC)
    worker_stopped_at = datetime.now(UTC)

    provider_result = TemporalProviderActivityResult.model_validate(result_payload)
    evidence = TemporalActivityAdapter.evidence_from_result(
        schedule.request,
        provider_result,
    )
    history = await handle.fetch_history()
    history_json = history.to_json()
    exported_history = WorkflowHistory.from_json(workflow_id, history_json)
    replay = await Replayer(workflows=[RehearsalWorkflow]).replay_workflow(
        exported_history
    )
    if replay.replay_failure is not None:
        raise replay.replay_failure
    event_types = tuple(EventType.Name(event.event_type) for event in history.events)
    if event_types.count("EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") != 1:
        raise RuntimeError("rehearsal history does not contain exactly one activity schedule")
    if event_types.count("EVENT_TYPE_ACTIVITY_TASK_COMPLETED") != 1:
        raise RuntimeError("rehearsal history does not contain exactly one activity completion")

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": worker_stopped_at.isoformat(),
        "status": "passed",
        "frontend_target": frontend_target,
        "namespace_ref": namespace_ref,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "workflow_type": REHEARSAL_WORKFLOW_TYPE,
        "workflow_id": workflow_id,
        "provider_run_id": handle.first_execution_run_id,
        "task_queue_ref": task_queue_ref,
        "worker_identity_ref": WORKER_IDENTITY,
        "worker_registration_sha256": registration.registration_sha256,
        "activity_type": REHEARSAL_ACTIVITY_TYPE,
        "activity_id": str(schedule.activity_id),
        "request_sha256": schedule.request_sha256,
        "schedule_sha256": schedule.schedule_sha256,
        "sdk_maximum_attempts": schedule.sdk_maximum_attempts,
        "provider_result_sha256": provider_result.result_sha256,
        "activity_evidence_sha256": evidence.evidence_sha256,
        "output_artifact_id": str(evidence.output_artifact_id),
        "history_event_count": len(history.events),
        "history_event_types": event_types,
        "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
        "history_replay_status": "passed",
        "started_at": started_at.isoformat(),
        "workflow_completed_at": workflow_completed_at.isoformat(),
        "worker_stopped_at": worker_stopped_at.isoformat(),
        "workflow_duration_seconds": (
            workflow_completed_at - started_at
        ).total_seconds(),
        "worker_shutdown_seconds": (
            worker_stopped_at - workflow_completed_at
        ).total_seconds(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report, history_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-gis-rehearsal")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, history_json = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.history.write_text(history_json + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
