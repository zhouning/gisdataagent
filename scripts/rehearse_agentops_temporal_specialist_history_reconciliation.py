#!/usr/bin/env python3
"""Rehearse real Temporal timeout history against a PostgreSQL specialist receipt.

This is a bounded integration rehearsal.  A provider-bound activity records a
``submitted`` receipt and then hangs until Temporal observes a timeout.  The history
observer and specialist reconciler must keep the result ``unknown_pending`` until a
separate provider terminal cancellation is recorded.  No production readiness claim is
made by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from temporalio import workflow
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.worker import Replayer

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_specialist_operation_authority import (
        AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
        PostgresSpecialistOperationAuthority,
    )
    from data_agent.agentops_specialist_providers import (
        FilesystemSpecialistArtifactStore,
        SpecialistOperationAuthority,
        build_mmfe_provider_spec,
    )
    from data_agent.agentops_temporal_reconciliation import (
        TemporalProviderActivityHistoryStatus,
        reconcile_specialist_activity_history,
    )
    from data_agent.agentops_temporal_task_graph_execution import (
        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
    )
    from data_agent.agentops_temporal_task_graph_rehearsal import (
        REHEARSAL_WORKER_IDENTITY,
        build_rehearsal_execution_input,
    )
    from data_agent.agentops_temporal_task_graph_runtime import (
        build_specialist_activity_definition,
    )
    from data_agent.agentops_temporal_worker import (
        TemporalioWorkerFactory,
        TemporalWorkerDefinition,
        TemporalWorkerRuntimeConfig,
    )
    from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
    from data_agent.agentops_temporalio_provider import TemporalioProviderClient
    from data_agent.cross_store_projection_postgres_rehearsal import (
        _execute_migration,
        _temporary_postgres,
    )
    from data_agent.platform_contracts import canonical_json_fingerprint


WORKFLOW_TYPE = "gda.agentops.specialist-history-reconciliation.v1"
ENVELOPE_SCHEMA = "gda.temporal_checkpoint_reconciliation_rehearsal.v1"
REPORT_SCHEMA = "gda.agentops_temporal_specialist_history_reconciliation_report.v1"
TENANT_ID = "planning"
TASK_QUEUE = "agentops-specialist-history-reconciliation"
ACTIVITY_TIMEOUT_SECONDS = 2
ACTIVITY_BLOCK_SECONDS = 8


def _write_geojson(path: Path, offset: float) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": 1},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [offset, 0],
                                    [offset + 1, 0],
                                    [offset + 1, 1],
                                    [offset, 1],
                                    [offset, 0],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _provider_schedule(root: Path, *, namespace_ref: str, task_queue_ref: str):
    first, second = root / "first.geojson", root / "second.geojson"
    _write_geojson(first, 0)
    _write_geojson(second, 0.25)
    first_id = UUID("00000000-0000-4000-8000-000000007811")
    second_id = UUID("00000000-0000-4000-8000-000000007812")
    store = FilesystemSpecialistArtifactStore(root / "artifacts")
    store.register_input(
        tenant_id=TENANT_ID,
        artifact_id=first_id,
        source_path=first,
        media_type="application/geo+json",
    )
    store.register_input(
        tenant_id=TENANT_ID,
        artifact_id=second_id,
        source_path=second,
        media_type="application/geo+json",
    )
    execution_input = build_rehearsal_execution_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        run_key=f"specialist-history-reconciliation:{uuid4().hex}",
        input_artifact_ids=(first_id, second_id),
        provider_spec_by_agent={
            "fusion": build_mmfe_provider_spec(
                input_artifact_ids=(first_id, second_id), strategy="spatial_join"
            )
        },
    )
    workflow_input = execution_input.workflow_input
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    plans = {plan.agent_id: plan for plan in execution_input.execution_manifest.plans}
    for agent_id in ("coordinator", "planner"):
        step = next(item for item in workflow_input.task_graph.steps if item.agent_id == agent_id)
        harness.start_step(workflow_id, step.step_id)
        harness.complete_step(workflow_id, step_id=step.step_id)
    step = next(item for item in workflow_input.task_graph.steps if item.agent_id == "fusion")
    harness.start_step(workflow_id, step.step_id)
    plan = plans["fusion"]
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref=plan.tool_ref,
        capability_ref=plan.capability_ref,
        subject_context=plan.subject_context,
        side_effect=plan.side_effect,
        policy_decision_ref=plan.policy_decision_ref,
        idempotency_key=plan.idempotency_key,
        input_artifact_ids=(first_id, second_id),
    )
    call = next(item for item in snapshot.execution.tool_calls if item.step_id == step.step_id)
    harness.dispatch_tool_call(workflow_id, call.tool_call_id)
    schedule = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type=TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
        schedule_to_close_timeout_seconds=10,
        start_to_close_timeout_seconds=ACTIVITY_TIMEOUT_SECONDS,
        heartbeat_timeout_seconds=1,
        cancellation_type=plan.cancellation_type,
        provider_spec=plan.provider_spec,
    ).activity_schedules[-1]
    return workflow_input, schedule, store


class _SubmitThenHangExecutor:
    def __init__(self, authority: SpecialistOperationAuthority, block_seconds: float) -> None:
        self._authority = authority
        self._block_seconds = block_seconds

    async def __call__(self, request: Any) -> Any:
        spec = request.provider_spec
        if spec is None:
            raise RuntimeError("provider binding is required")
        operation_ref = f"{spec.operation_ref}://{request.activity_id}"
        receipt_ref = f"provider://specialist/{request.activity_id}/{request.attempt_no}"
        self._authority.submit(
            request,
            provider_ref=spec.provider_ref,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
        )
        deadline = asyncio.get_running_loop().time() + self._block_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Keep the provider operation unresolved until the bounded hang ends;
                # Temporal's timeout remains the authoritative history observation.
                continue
        raise RuntimeError("bounded provider response hang ended")


@workflow.defn(name=WORKFLOW_TYPE)
class SpecialistHistoryReconciliationWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("schema") != ENVELOPE_SCHEMA:
            raise ValueError("specialist history envelope schema mismatch")
        schedule = payload["schedule"]
        try:
            return await workflow.execute_activity(
                schedule["activity_type"],
                schedule["request"],
                task_queue=schedule["task_queue_ref"],
                activity_id=schedule["activity_id"],
                schedule_to_close_timeout=timedelta(
                    seconds=schedule["schedule_to_close_timeout_seconds"]
                ),
                start_to_close_timeout=timedelta(
                    seconds=schedule["start_to_close_timeout_seconds"]
                ),
                heartbeat_timeout=timedelta(seconds=schedule["heartbeat_timeout_seconds"]),
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=getattr(
                    workflow.ActivityCancellationType,
                    str(schedule["cancellation_type"]).upper(),
                ),
            )
        except Exception as exc:
            return {"status": "activity_terminal_observed", "error_type": type(exc).__name__}


async def run_rehearsal(
    admin_url: str,
    *,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryDirectory(prefix="gda-specialist-history-") as temp_dir:
        root = Path(temp_dir)
        workflow_input, schedule, store = _provider_schedule(
            root, namespace_ref=namespace_ref, task_queue_ref=task_queue_ref
        )
        with _temporary_postgres(admin_url) as sandbox:
            if sandbox.runtime_engine is None or sandbox.database_url is None:
                raise RuntimeError("temporary PostgreSQL runtime was not initialized")
            with sandbox.admin_connection() as connection:
                connection.exec_driver_sql(
                    "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public"
                )
                _execute_migration(
                    connection,
                    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION.read_text(
                        encoding="utf-8"
                    ),
                )
            authority = PostgresSpecialistOperationAuthority(
                TENANT_ID,
                sandbox.runtime_engine,
                recorded_by="workload:agentops-specialist-history",
            )
            executor = _SubmitThenHangExecutor(authority, ACTIVITY_BLOCK_SECONDS)
            activity_definition = build_specialist_activity_definition(executor)
            config = TemporalWorkerRuntimeConfig(
                tenant_id=TENANT_ID,
                namespace_ref=workflow_input.identity.namespace.namespace_ref,
                frontend_target=frontend_target,
                task_queue_ref=task_queue_ref,
                worker_identity_ref=REHEARSAL_WORKER_IDENTITY,
                workflow_type=WORKFLOW_TYPE,
                activity_types=(TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,),
                agent_spec_sha256=workflow_input.agent_spec_sha256,
                deployment_revision_sha256=workflow_input.deployment_revision.revision_sha256,
                max_concurrent_activities=1,
                max_concurrent_workflow_tasks=1,
            )
            client = await Client.connect(
                frontend_target,
                namespace=workflow_input.identity.namespace.namespace_ref,
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
                        WORKFLOW_TYPE, SpecialistHistoryReconciliationWorkflow
                    ),
                ),
                activities=(
                    TemporalWorkerDefinition(
                        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE, activity_definition
                    ),
                ),
            ).build()
            envelope = {
                "schema": ENVELOPE_SCHEMA,
                "workflow_input": workflow_input.model_dump(mode="json"),
                "workflow_input_sha256": workflow_input.input_sha256,
                "schedule": schedule.model_dump(mode="json"),
            }
            async with worker:
                handle = await client.start_workflow(
                    WORKFLOW_TYPE,
                    envelope,
                    id=workflow_input.identity.workflow_id,
                    task_queue=task_queue_ref,
                )
                operation_ref = (
                    f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
                    if schedule.request.provider_spec is not None
                    else ""
                )
                for _ in range(100):
                    if authority.observe(operation_ref) is not None:
                        break
                    await asyncio.sleep(0.1)
                submitted = authority.observe(operation_ref)
                if submitted is None:
                    raise RuntimeError("Temporal activity did not submit provider receipt")
                workflow_result = await handle.result()
            provider = TemporalioProviderClient(
                client,
                namespace_ref=workflow_input.identity.namespace.namespace_ref,
            )
            observed = await provider.observe_workflow_history(
                tenant_id=TENANT_ID,
                namespace_ref=workflow_input.identity.namespace.namespace_ref,
                workflow_id=workflow_input.identity.workflow_id,
                provider_run_id=handle.first_execution_run_id,
            )
            activity_observation = next(
                item for item in observed.activities if item.activity_id == schedule.activity_id
            )
            pending_join, pending_specialist, pending_settled = (
                reconcile_specialist_activity_history(
                    activity_observation,
                    artifact_store=store,
                    operation_authority=authority,
                )
            )
            cancellation_requested = authority.request_cancellation(operation_ref)
            requested_join, requested_specialist, requested_settled = (
                reconcile_specialist_activity_history(
                    activity_observation,
                    artifact_store=store,
                    operation_authority=authority,
                )
            )
            cancelled = authority.cancel(operation_ref, "ProviderCancellationConfirmed")
            cancelled_join, cancelled_specialist, cancelled_settled = (
                reconcile_specialist_activity_history(
                    activity_observation,
                    artifact_store=store,
                    operation_authority=authority,
                )
            )
            history = await handle.fetch_history()
            history_json = history.to_json()
            replay = await Replayer(
                workflows=[SpecialistHistoryReconciliationWorkflow]
            ).replay_workflow(WorkflowHistory.from_json(handle.id, history_json))
            if replay.replay_failure is not None:
                raise replay.replay_failure
            if activity_observation.status not in {
                TemporalProviderActivityHistoryStatus.TIMED_OUT,
                TemporalProviderActivityHistoryStatus.CANCELLED,
                TemporalProviderActivityHistoryStatus.FAILED,
            }:
                raise RuntimeError(
                    "Temporal activity did not reach a terminal failure history: "
                    f"{activity_observation.status}"
                )
            if pending_specialist.verdict.value != "unknown_pending":
                raise RuntimeError("submitted receipt was incorrectly treated as terminal")
            if requested_specialist.verdict.value != "unknown_pending":
                raise RuntimeError("cancellation request was incorrectly treated as terminal")
            if cancelled_specialist.verdict.value != "definitive_failed":
                raise RuntimeError("provider terminal cancellation did not settle failure")
            report: dict[str, Any] = {
                "schema": REPORT_SCHEMA,
                "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "status": "passed",
                "scope": "docker_desktop_temporal_postgres_specialist_history_bounded",
                "production_readiness_claimed": False,
                "temporal_server_version": cluster.server_version,
                "temporal_sdk_version": version("temporalio"),
                "workflow_id": handle.id,
                "provider_run_id": handle.first_execution_run_id,
                "activity_id": str(schedule.activity_id),
                "operation_ref": operation_ref,
                "temporal_activity_status": activity_observation.status.value,
                "temporal_history_event_count": observed.history_event_count,
                "temporal_history_sha256": observed.history_sha256,
                "temporal_observation_sha256": observed.observation_sha256,
                "workflow_result": workflow_result,
                "submitted_receipt_status": submitted.status.value,
                "cancellation_requested_receipt_status": cancellation_requested.status.value,
                "cancellation_requested": cancellation_requested.cancellation_requested,
                "requested_reconciliation": {
                    "verdict": requested_join.specialist_verdict.value,
                    "outcome": requested_join.resulting_outcome.value,
                },
                "pending_reconciliation": {
                    "verdict": pending_join.specialist_verdict.value,
                    "outcome": pending_join.resulting_outcome.value,
                    "settled_outcome": pending_settled.outcome.value,
                },
                "provider_terminal_cancellation": {
                    "receipt_status": cancelled.status.value,
                    "verdict": cancelled_join.specialist_verdict.value,
                    "outcome": cancelled_join.resulting_outcome.value,
                    "failure_type": cancelled_join.failure_type,
                    "settled_outcome": cancelled_settled.outcome.value,
                },
                "history_replay_status": "passed",
                "history_replay_event_count": len(history.events),
            }
            report["report_sha256"] = canonical_json_fingerprint(report)
            return report, history_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--frontend", default="gis-agent-temporal-frontend:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default=TASK_QUEUE)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    report, history_json = asyncio.run(
        run_rehearsal(
            args.database_url,
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.history.write_text(
        history_json + ("" if history_json.endswith("\n") else "\n"),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
