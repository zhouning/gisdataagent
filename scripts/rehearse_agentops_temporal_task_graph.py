#!/usr/bin/env python3
"""Run and replay a real six-specialist AgentTaskGraph on Temporal."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from data_agent.agentops_contracts import AgentStepStatus, AgentToolCallStatus
from data_agent.agentops_temporal_contracts import (
    TemporalActivityOutcome,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_task_graph_execution import (
    TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
)
from data_agent.agentops_temporal_task_graph_rehearsal import (
    REHEARSAL_GWM_TOOL_REF,
    REHEARSAL_WORKER_IDENTITY,
    build_rehearsal_execution_input,
    rehearsal_specialist_activity,
)
from data_agent.agentops_temporal_task_graph_runtime import (
    TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
    TASK_GRAPH_WORKFLOW_TYPE,
    TemporalTaskGraphWorkflow,
)
from data_agent.agentops_temporal_worker import (
    TemporalioWorkerFactory,
    TemporalWorkerDefinition,
    TemporalWorkerRuntimeConfig,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from data_agent.platform_contracts import canonical_json_fingerprint

REPORT_SCHEMA = "gda.agentops_temporal_task_graph_rehearsal_report.v1"
EXPECTED_WAVES = (
    ("coordinator",),
    ("planner",),
    ("data_engineer", "fusion", "gwm"),
    ("quality",),
)


async def run_rehearsal(
    *,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
) -> tuple[dict[str, Any], str]:
    run_key = str(uuid4())
    execution_input = build_rehearsal_execution_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        run_key=run_key,
    )
    workflow_input = execution_input.workflow_input
    workflow_id = workflow_input.identity.workflow_id
    config = TemporalWorkerRuntimeConfig(
        tenant_id=workflow_input.tenant_id,
        namespace_ref=namespace_ref,
        frontend_target=frontend_target,
        task_queue_ref=task_queue_ref,
        worker_identity_ref=REHEARSAL_WORKER_IDENTITY,
        workflow_type=TASK_GRAPH_WORKFLOW_TYPE,
        activity_types=(TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,),
        agent_spec_sha256=workflow_input.agent_spec_sha256,
        deployment_revision_sha256=(
            workflow_input.deployment_revision.revision_sha256
        ),
        max_concurrent_activities=6,
        max_concurrent_workflow_tasks=2,
    )
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=REHEARSAL_WORKER_IDENTITY,
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    registration = config.registration()
    worker = TemporalioWorkerFactory(
        client,
        registration,
        workflows=(
            TemporalWorkerDefinition(
                TASK_GRAPH_WORKFLOW_TYPE,
                TemporalTaskGraphWorkflow,
            ),
        ),
        activities=(
            TemporalWorkerDefinition(
                TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
                rehearsal_specialist_activity,
            ),
        ),
    ).build()

    started_at = datetime.now(UTC)
    async with worker:
        handle = await client.start_workflow(
            TASK_GRAPH_WORKFLOW_TYPE,
            execution_input.model_dump(mode="json"),
            id=workflow_id,
            task_queue=task_queue_ref,
        )
        result = await handle.result()
        completed_at = datetime.now(UTC)
    worker_stopped_at = datetime.now(UTC)

    if result.get("schema") != TASK_GRAPH_WORKFLOW_RESULT_SCHEMA:
        raise RuntimeError("task graph workflow returned an unknown result schema")
    if result.get("status") != "succeeded":
        raise RuntimeError(f"task graph workflow did not succeed: {result.get('status')}")
    expected_result_sha256 = temporal_contract_fingerprint(
        TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
        result,
        "workflow_result_sha256",
    )
    if result.get("workflow_result_sha256") != expected_result_sha256:
        raise RuntimeError("task graph workflow result fingerprint differs")
    if tuple(tuple(wave) for wave in result.get("execution_waves", ())) != EXPECTED_WAVES:
        raise RuntimeError("task graph workflow did not preserve expected fan-out/fan-in waves")

    checkpoint = TemporalTaskGraphWorkflowCheckpoint.model_validate(result["checkpoint"])
    if checkpoint.execution.graph != workflow_input.task_graph:
        raise RuntimeError("checkpoint graph differs from immutable workflow input")
    if any(
        step.status is not AgentStepStatus.SUCCEEDED
        for step in checkpoint.execution.step_states
    ):
        raise RuntimeError("checkpoint contains a non-succeeded task graph step")
    if any(
        call.status is not AgentToolCallStatus.SUCCEEDED
        for call in checkpoint.execution.tool_calls
    ):
        raise RuntimeError("checkpoint contains a non-succeeded ToolCall")
    outcomes = tuple(item.outcome for item in checkpoint.activity_evidence)
    if outcomes.count(TemporalActivityOutcome.FAILED) != 1:
        raise RuntimeError("rehearsal expected one explicit transient activity failure")
    if outcomes.count(TemporalActivityOutcome.SUCCEEDED) != 6:
        raise RuntimeError("rehearsal expected six successful specialist activities")
    gwm_plan = next(
        plan
        for plan in execution_input.execution_manifest.plans
        if plan.tool_ref == REHEARSAL_GWM_TOOL_REF
    )
    gwm_call = next(
        call
        for call in checkpoint.execution.tool_calls
        if call.step_id == gwm_plan.step_id
    )
    gwm_attempts = tuple(
        schedule.attempt_no
        for schedule in checkpoint.activity_schedules
        if schedule.tool_call_id == gwm_call.tool_call_id
    )
    if gwm_attempts != (1, 2):
        raise RuntimeError("GWM retry was not represented as explicit platform attempts 1 and 2")
    if any(schedule.sdk_maximum_attempts != 1 for schedule in checkpoint.activity_schedules):
        raise RuntimeError("task graph schedule contains hidden SDK retries")

    history = await handle.fetch_history()
    history_json = history.to_json()
    replay = await Replayer(workflows=[TemporalTaskGraphWorkflow]).replay_workflow(
        WorkflowHistory.from_json(workflow_id, history_json)
    )
    if replay.replay_failure is not None:
        raise replay.replay_failure
    event_types = tuple(EventType.Name(event.event_type) for event in history.events)
    scheduled_count = event_types.count("EVENT_TYPE_ACTIVITY_TASK_SCHEDULED")
    completed_count = event_types.count("EVENT_TYPE_ACTIVITY_TASK_COMPLETED")
    if scheduled_count != 7 or completed_count != 7:
        raise RuntimeError(
            "Temporal history must contain seven explicit schedules and completions"
        )

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": worker_stopped_at.isoformat(),
        "status": "passed",
        "scope": "docker_desktop_temporal_sandbox",
        "production_readiness_claimed": False,
        "frontend_target": frontend_target,
        "namespace_ref": namespace_ref,
        "task_queue_ref": task_queue_ref,
        "worker_identity_ref": REHEARSAL_WORKER_IDENTITY,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "workflow_type": TASK_GRAPH_WORKFLOW_TYPE,
        "workflow_id": workflow_id,
        "provider_run_id": handle.first_execution_run_id,
        "agent_spec_sha256": workflow_input.agent_spec_sha256,
        "deployment_revision_sha256": (
            workflow_input.deployment_revision.revision_sha256
        ),
        "graph_sha256": workflow_input.task_graph.graph_sha256,
        "manifest_sha256": execution_input.execution_manifest.manifest_sha256,
        "execution_input_sha256": execution_input.execution_input_sha256,
        "worker_registration_sha256": registration.registration_sha256,
        "workflow_result_sha256": result["workflow_result_sha256"],
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "execution_state_sha256": checkpoint.execution.state_sha256,
        "specialist_agents": tuple(
            plan.agent_id for plan in execution_input.execution_manifest.plans
        ),
        "execution_waves": EXPECTED_WAVES,
        "tool_call_count": len(checkpoint.execution.tool_calls),
        "activity_schedule_count": len(checkpoint.activity_schedules),
        "activity_evidence_count": len(checkpoint.activity_evidence),
        "explicit_gwm_attempts": gwm_attempts,
        "sdk_maximum_attempts": 1,
        "history_event_count": len(history.events),
        "history_activity_scheduled_count": scheduled_count,
        "history_activity_completed_count": completed_count,
        "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
        "history_replay_status": "passed",
        "started_at": started_at.isoformat(),
        "workflow_completed_at": completed_at.isoformat(),
        "worker_stopped_at": worker_stopped_at.isoformat(),
        "workflow_duration_seconds": (completed_at - started_at).total_seconds(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report, history_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument(
        "--task-queue",
        default="agentops-gis-task-graph-rehearsal",
    )
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
