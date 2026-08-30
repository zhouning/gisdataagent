"""Real Temporal + PostgreSQL rehearsal for automatic ApprovalCase expiry."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from .agentops_contracts import AgentSideEffect
from .agentops_temporal_approval import (
    TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
    TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
    TEMPORAL_APPROVAL_QUERY_NAME,
    TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
)
from .agentops_temporal_approval_rehearsal import (
    REHEARSAL_WORKER_IDENTITY,
    _migrate_approval_authority,
    _seed_approval_directory,
    _temporary_postgres,
)
from .agentops_temporal_task_graph_rehearsal import (
    build_rehearsal_execution_input,
    rehearsal_specialist_activity,
)
from .agentops_temporal_task_graph_runtime import (
    TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
    TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
    TASK_GRAPH_WORKFLOW_TYPE,
    TemporalTaskGraphWorkflow,
    build_approval_case_creation_activity_definition,
    build_approval_case_expiry_activity_definition,
    build_approval_verification_activity_definition,
)
from .agentops_temporal_worker import (
    TemporalioWorkerFactory,
    TemporalWorkerDefinition,
    TemporalWorkerRuntimeConfig,
)
from .approval_case_authority import ApprovalCaseAuthority
from .platform_contracts import ApprovalCaseAssignmentOperation, canonical_json_fingerprint

REPORT_SCHEMA = "gda.agentops_temporal_step_hitl_expiry_rehearsal_report.v1"


async def run_rehearsal(
    *,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
    admin_database_url: str,
    expiry_seconds: float = 1.5,
) -> tuple[dict[str, Any], str]:
    run_key = str(uuid4())
    execution_input = build_rehearsal_execution_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        run_key=run_key,
        side_effect_by_agent={"coordinator": AgentSideEffect.CONTROL_WRITE},
    )
    workflow_input = execution_input.workflow_input
    workflow_id = workflow_input.identity.workflow_id
    provider_calls: list[dict[str, Any]] = []

    with _temporary_postgres(admin_database_url) as sandbox:
        if sandbox.runtime_engine is None or sandbox.database_url is None:
            raise RuntimeError("temporary ApprovalCase database was not created")
        _migrate_approval_authority(sandbox.database_url)
        authority = ApprovalCaseAuthority(sandbox.runtime_engine)
        _seed_approval_directory(authority)
        config = TemporalWorkerRuntimeConfig(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=namespace_ref,
            frontend_target=frontend_target,
            task_queue_ref=task_queue_ref,
            worker_identity_ref=REHEARSAL_WORKER_IDENTITY,
            workflow_type=TASK_GRAPH_WORKFLOW_TYPE,
            activity_types=tuple(
                sorted(
                    {
                        TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
                        TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
                        TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
                        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
                    }
                )
            ),
            agent_spec_sha256=workflow_input.agent_spec_sha256,
            deployment_revision_sha256=workflow_input.deployment_revision.revision_sha256,
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

        @activity.defn(name=TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE)
        async def tracked_specialist(payload: dict[str, Any]) -> dict[str, Any]:
            provider_calls.append(payload)
            return await rehearsal_specialist_activity(payload)

        registration = config.registration()

        def build_worker():
            return TemporalioWorkerFactory(
                client,
                registration,
                workflows=(
                    TemporalWorkerDefinition(TASK_GRAPH_WORKFLOW_TYPE, TemporalTaskGraphWorkflow),
                ),
                activities=(
                    TemporalWorkerDefinition(
                        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE, tracked_specialist
                    ),
                    TemporalWorkerDefinition(
                        TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
                        build_approval_case_creation_activity_definition(
                            authority, expiry_seconds=expiry_seconds
                        ),
                    ),
                    TemporalWorkerDefinition(
                        TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
                        build_approval_verification_activity_definition(authority),
                    ),
                    TemporalWorkerDefinition(
                        TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
                        build_approval_case_expiry_activity_definition(authority),
                    ),
                ),
            ).build()

        started_at = datetime.now(UTC)
        async with build_worker():
            handle = await client.start_workflow(
                TASK_GRAPH_WORKFLOW_TYPE,
                execution_input.model_dump(mode="json"),
                id=workflow_id,
                task_queue=task_queue_ref,
            )
            pending: dict[str, Any] | None = None
            for _ in range(300):
                pending = await handle.query(TEMPORAL_APPROVAL_QUERY_NAME)
                if pending is not None:
                    break
                await asyncio.sleep(0.01)
            if pending is None:
                raise RuntimeError("Temporal workflow did not expose pending ApprovalCase")
            case_ref = pending["approval_case"]["approval_case_ref"]
            assignment = authority.transition_assignment(
                tenant_id=workflow_input.tenant_id,
                approval_case_ref=case_ref,
                expected_assignment_version=0,
                operation=ApprovalCaseAssignmentOperation.ASSIGN,
                actor_subject="human:agentops-directory-admin",
                assignee_subject="team:geo-platform-approvers",
                reason="route timeout rehearsal to the declared approval scope",
            )
            result = await handle.result()
            terminal_assignment = authority.assignment(workflow_input.tenant_id, case_ref)
            assignment_events = authority.assignment_events(workflow_input.tenant_id, case_ref)
            case = authority.get(workflow_input.tenant_id, case_ref)

        history = await handle.fetch_history()
        history_json = history.to_json()
        replay = await Replayer(workflows=[TemporalTaskGraphWorkflow]).replay_workflow(
            WorkflowHistory.from_json(workflow_id, history_json)
        )
        if replay.replay_failure is not None:
            raise replay.replay_failure

    event_types = tuple(EventType.Name(event.event_type) for event in history.events)
    scheduled_count = event_types.count("EVENT_TYPE_ACTIVITY_TASK_SCHEDULED")
    if result.get("schema") != TASK_GRAPH_WORKFLOW_RESULT_SCHEMA:
        raise RuntimeError("expiry rehearsal returned an unknown workflow result schema")
    if result.get("status") != "cancelled":
        raise RuntimeError(f"expiry rehearsal did not cancel: {result.get('status')}")
    expiries = result.get("approval_expiries", ())
    if len(expiries) != 1 or expiries[0].get("reason_code") != "expired_cancelled":
        raise RuntimeError("expiry rehearsal lost authoritative cancellation evidence")
    if case.status.value != "cancelled" or case.decided_at is None:
        raise RuntimeError("ApprovalCase did not converge to cancelled")
    if terminal_assignment is None or terminal_assignment.status.value != "closed":
        raise RuntimeError("expiry rehearsal lost assignment close evidence")
    if terminal_assignment.assignee_subject != assignment.assignee_subject:
        raise RuntimeError("expiry rehearsal assignment scope drifted")
    if terminal_assignment.last_actor_subject != case.decided_by:
        raise RuntimeError("expiry assignment close actor differs from case expiry actor")
    if terminal_assignment.closed_at != case.decided_at:
        raise RuntimeError("expiry assignment close time differs from case decision time")
    if tuple(event.action.value for event in assignment_events) != ("assigned", "closed"):
        raise RuntimeError("expiry rehearsal assignment event chain is incomplete")
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "passed",
        "scope": "temporary_postgres_plus_docker_desktop_temporal_sandbox",
        "production_readiness_claimed": False,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "namespace_ref": namespace_ref,
        "task_queue_ref": task_queue_ref,
        "workflow_id": workflow_id,
        "approval_case_ref": case.approval_case_ref,
        "approval_case_status": case.status.value,
        "approval_case_decided_by": case.decided_by,
        "approval_case_decided_at": case.decided_at.isoformat() if case.decided_at else None,
        "approval_assignment_scope_ref": terminal_assignment.assignee_subject,
        "approval_assignment_version": terminal_assignment.assignment_version,
        "approval_assignment_event_actions": tuple(
            event.action.value for event in assignment_events
        ),
        "provider_specialist_activity_count": len(provider_calls),
        "provider_dispatch_withheld": len(provider_calls) == 0,
        "approval_expiry_count": len(expiries),
        "activity_schedule_count": scheduled_count,
        "history_event_count": len(history.events),
        "history_replay_status": "passed",
        "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report, history_json


def write_report(report: dict[str, Any], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
