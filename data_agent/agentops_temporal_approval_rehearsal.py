"""Real Temporal + PostgreSQL rehearsal for step-bound HITL approval."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from .agentops_contracts import AgentSideEffect
from .agentops_temporal_approval import (
    TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
    TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
    TEMPORAL_APPROVAL_QUERY_NAME,
    TEMPORAL_APPROVAL_SIGNAL_NAME,
    TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
    build_temporal_step_approval_signal,
)
from .agentops_temporal_contracts import TemporalSignalKind
from .agentops_temporal_task_graph_rehearsal import (
    REHEARSAL_WORKER_IDENTITY,
    build_rehearsal_execution_input,
    rehearsal_specialist_activity,
)
from .agentops_temporal_task_graph_runtime import (
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
from .approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseForbiddenError,
)
from .cross_store_projection_postgres_rehearsal import _temporary_postgres
from .platform_contracts import (
    ApprovalAvailabilityStatus,
    ApprovalCase,
    ApprovalCaseAssignmentOperation,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    canonical_json_fingerprint,
)

REPORT_SCHEMA = "gda.agentops_temporal_step_hitl_rehearsal_report.v2"


def _migrate_approval_authority(database_url: Any) -> None:
    engine = create_engine(database_url)
    try:
        for filename in (
            "102_source_schema_drift_ledger.sql",
            "103_unified_approval_case_authority.sql",
            "120_approval_case_assignment_authority.sql",
            "121_approval_principal_directory.sql",
            "243_agentops_approval_expiry_authority.sql",
        ):
            sql = (
                Path(__file__).resolve().parent / "migrations" / filename
            ).read_text(encoding="utf-8")
            with engine.begin() as connection:
                connection.exec_driver_sql(sql.replace("%", "%%"))
    finally:
        engine.dispose()


def _seed_approval_directory(authority: ApprovalCaseAuthority) -> None:
    """Register the exact team and human used by the live Temporal approval signal."""

    valid_from = datetime.now(UTC) - timedelta(minutes=1)
    authority.upsert_principal(
        tenant_id="planning",
        principal_subject="team:geo-platform-approvers",
        expected_directory_version=0,
        principal_type=ApprovalPrincipalType.TEAM,
        display_name="Geo Platform Approvers",
        status=ApprovalPrincipalStatus.ACTIVE,
        approval_eligible=True,
        availability_status=ApprovalAvailabilityStatus.AVAILABLE,
        valid_from=valid_from,
        valid_until=None,
        actor_subject="human:agentops-directory-admin",
        reason="register Temporal HITL approval team",
    )
    authority.upsert_principal(
        tenant_id="planning",
        principal_subject="human:agentops-rehearsal-approver",
        expected_directory_version=0,
        principal_type=ApprovalPrincipalType.HUMAN,
        display_name="AgentOps Rehearsal Approver",
        status=ApprovalPrincipalStatus.ACTIVE,
        approval_eligible=True,
        availability_status=ApprovalAvailabilityStatus.AVAILABLE,
        valid_from=valid_from,
        valid_until=None,
        actor_subject="human:agentops-directory-admin",
        reason="register Temporal HITL approval principal",
    )
    authority.upsert_principal(
        tenant_id="planning",
        principal_subject="human:agentops-standby-approver",
        expected_directory_version=0,
        principal_type=ApprovalPrincipalType.HUMAN,
        display_name="AgentOps Standby Approver",
        status=ApprovalPrincipalStatus.ACTIVE,
        approval_eligible=True,
        availability_status=ApprovalAvailabilityStatus.AVAILABLE,
        valid_from=valid_from,
        valid_until=None,
        actor_subject="human:agentops-directory-admin",
        reason="register standby principal for reassignment rehearsal",
    )
    authority.upsert_team_membership(
        tenant_id="planning",
        team_subject="team:geo-platform-approvers",
        member_subject="human:agentops-rehearsal-approver",
        expected_membership_version=0,
        status=ApprovalPrincipalStatus.ACTIVE,
        can_delegate=True,
        valid_from=valid_from,
        valid_until=None,
        actor_subject="human:agentops-directory-admin",
        reason="add rehearsal approver to Temporal HITL team",
    )


async def run_rehearsal(
    *,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
    admin_database_url: str,
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
                        TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE,
            "gda.agentops.specialist.activity",
            TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE,
                    }
                )
            ),
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
        def build_worker():
            return TemporalioWorkerFactory(
                client,
                registration,
                workflows=(
                    TemporalWorkerDefinition(
                        TASK_GRAPH_WORKFLOW_TYPE, TemporalTaskGraphWorkflow
                    ),
                ),
                activities=(
                    TemporalWorkerDefinition(
                        "gda.agentops.specialist.activity",
                        rehearsal_specialist_activity,
                    ),
                    TemporalWorkerDefinition(
                        TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE,
                        build_approval_case_creation_activity_definition(authority),
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
            for _ in range(600):
                pending = await handle.query(TEMPORAL_APPROVAL_QUERY_NAME)
                if pending is not None:
                    break
                await asyncio.sleep(0.05)
            if pending is None:
                raise RuntimeError("Temporal workflow did not expose pending ApprovalCase")

        async with build_worker():
            recovered_pending: dict[str, Any] | None = None
            for _ in range(600):
                recovered_pending = await handle.query(TEMPORAL_APPROVAL_QUERY_NAME)
                if recovered_pending is not None:
                    break
                await asyncio.sleep(0.05)
            if recovered_pending is None:
                raise RuntimeError("restarted worker did not recover pending ApprovalCase")
            if recovered_pending != pending:
                raise RuntimeError("pending ApprovalCase state drifted across worker restart")
            worker_restart_pending_state_preserved = True
            binding = execution_input.approval_bindings[0]
            case = ApprovalCase.model_validate(recovered_pending["approval_case"])
            initial_assignment = authority.transition_assignment(
                tenant_id=case.tenant_id,
                approval_case_ref=case.approval_case_ref,
                expected_assignment_version=0,
                operation=ApprovalCaseAssignmentOperation.ASSIGN,
                actor_subject="human:agentops-directory-admin",
                assignee_subject="human:agentops-standby-approver",
                reason="initial standby routing before on-call reassignment",
            )
            assignment = authority.transition_assignment(
                tenant_id=case.tenant_id,
                approval_case_ref=case.approval_case_ref,
                expected_assignment_version=initial_assignment.assignment_version,
                operation=ApprovalCaseAssignmentOperation.REASSIGN,
                actor_subject="human:agentops-directory-admin",
                assignee_subject=binding.approver_scope_ref,
                reason="route exact Temporal step to its declared approver scope",
            )
            if assignment.assignee_subject != binding.approver_scope_ref:
                raise RuntimeError("Temporal HITL rehearsal assignment scope drifted")
            premature_signal = build_temporal_step_approval_signal(
                binding,
                signal_id=uuid4(),
                kind=TemporalSignalKind.APPROVE,
                expected_state_version=int(recovered_pending["expected_state_version"]),
                requested_by="human:agentops-rehearsal-approver",
                reason="premature approval must remain blocked while case is pending",
            )
            await handle.signal(
                TEMPORAL_APPROVAL_SIGNAL_NAME,
                premature_signal.model_dump(mode="json"),
            )
            rejected_pending: dict[str, Any] | None = None
            for _ in range(600):
                current = await handle.query(TEMPORAL_APPROVAL_QUERY_NAME)
                last = (current or {}).get("last_verification")
                if last and last.get("signal_id") == str(premature_signal.signal_id):
                    rejected_pending = last
                    break
                await asyncio.sleep(0.05)
            if rejected_pending is None or rejected_pending.get("reason_code") != (
                "approval_state_version_mismatch"
            ):
                raise RuntimeError(
                    "pending ApprovalCase signal was not rejected by authority: "
                    f"{rejected_pending!r}"
                )
            try:
                authority.decide(
                    tenant_id=case.tenant_id,
                    approval_case_ref=case.approval_case_ref,
                    expected_state_version=case.state_version,
                    verdict="approved",
                    actor_subject="human:agentops-standby-approver",
                    reason="stale assignee must not authorize the reassigned step",
                )
            except ApprovalCaseForbiddenError:
                stale_assignee_rejected = True
            else:
                raise RuntimeError("reassigned stale approver was allowed to decide")
            decided = authority.decide(
                tenant_id=case.tenant_id,
                approval_case_ref=case.approval_case_ref,
                expected_state_version=case.state_version,
                verdict="approved",
                actor_subject="human:agentops-rehearsal-approver",
                reason="approved exact coordinator control write",
            )
            signal = build_temporal_step_approval_signal(
                binding,
                signal_id=uuid4(),
                kind=TemporalSignalKind.APPROVE,
                expected_state_version=int(recovered_pending["expected_state_version"]),
                requested_by=decided.decided_by or "human:agentops-rehearsal-approver",
                reason=decided.decision_reason or "approved exact coordinator control write",
            )
            await handle.signal(TEMPORAL_APPROVAL_SIGNAL_NAME, signal.model_dump(mode="json"))
            result = await handle.result()
            terminal_assignment = authority.assignment(
                case.tenant_id,
                case.approval_case_ref,
            )
            assignment_events = authority.assignment_events(
                case.tenant_id,
                case.approval_case_ref,
            )
        completed_at = datetime.now(UTC)
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
    if result.get("schema") != TASK_GRAPH_WORKFLOW_RESULT_SCHEMA:
        raise RuntimeError("HITL rehearsal returned an unknown workflow result schema")
    if result.get("status") != "succeeded":
        raise RuntimeError(f"HITL rehearsal did not succeed: {result.get('status')}")
    if len(result.get("approval_case_creations", ())) != 1:
        raise RuntimeError("HITL rehearsal must create exactly one ApprovalCase")
    if len(result.get("approval_verifications", ())) != 2:
        raise RuntimeError("HITL rehearsal must verify the pending and approved signals")
    if result["approval_verifications"][0]["reason_code"] != "approval_state_version_mismatch":
        raise RuntimeError("HITL rehearsal lost the pending-signal rejection evidence")
    if scheduled_count != 10 or completed_count != 10:
        raise RuntimeError("HITL rehearsal must record ten explicit activity completions")
    if terminal_assignment is None or terminal_assignment.status.value != "closed":
        raise RuntimeError("HITL rehearsal lost terminal assignment close evidence")
    if terminal_assignment.assignee_subject != binding.approver_scope_ref:
        raise RuntimeError("terminal assignment no longer matches approval binding scope")
    if terminal_assignment.last_actor_subject != decided.decided_by:
        raise RuntimeError("terminal assignment actor differs from ApprovalCase decision")
    if terminal_assignment.closed_at != decided.decided_at:
        raise RuntimeError("terminal assignment time differs from ApprovalCase decision")
    if tuple(event.action.value for event in assignment_events) != (
        "assigned",
        "reassigned",
        "closed",
    ):
        raise RuntimeError("HITL assignment event chain is incomplete")
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
        "graph_sha256": workflow_input.task_graph.graph_sha256,
        "manifest_sha256": execution_input.execution_manifest.manifest_sha256,
        "approval_binding_sha256": execution_input.approval_bindings[0].binding_sha256,
        "approval_case_ref": execution_input.approval_bindings[0].approval_case_ref,
        "approval_case_status": "approved",
        "approval_signal_kind": "approve",
        "approval_assignment_scope_ref": terminal_assignment.assignee_subject,
        "approval_assignment_version": terminal_assignment.assignment_version,
        "approval_assignment_event_count": len(assignment_events),
        "approval_assignment_event_actions": tuple(
            event.action.value for event in assignment_events
        ),
        "stale_assignee_rejected": stale_assignee_rejected,
        "worker_restart_pending_state_preserved": (
            worker_restart_pending_state_preserved
        ),
        "approval_creation_count": len(result["approval_case_creations"]),
        "approval_verification_count": len(result["approval_verifications"]),
        "pending_signal_rejected": True,
        "activity_schedule_count": scheduled_count,
        "activity_completion_count": completed_count,
        "history_event_count": len(history.events),
        "history_replay_status": "passed",
        "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report, history_json


def write_report(report: dict[str, Any], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["REPORT_SCHEMA", "run_rehearsal", "write_report"]
