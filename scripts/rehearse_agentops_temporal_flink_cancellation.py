#!/usr/bin/env python3
"""Rehearse a provider-native Flink cancellation from a live Temporal activity.

The Flink job is submitted outside Temporal and identified by ``--flink-job-id``.
Temporal owns the activity cancellation request, the Flink REST adapter owns the
provider observation, and PostgreSQL owns the durable operation receipt.  The script
is intentionally bounded: it does not claim a production worker rollout or create a
Flink job on behalf of the caller.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.worker import Replayer

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_contracts import AgentSideEffect
    from data_agent.agentops_flink_provider import FlinkProviderCancellationAdapter
    from data_agent.agentops_specialist_operation_authority import (
        AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
        AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
        PostgresSpecialistOperationAuthority,
    )
    from data_agent.agentops_specialist_providers import (
        FilesystemSpecialistArtifactStore,
        SpecialistOperationStatus,
        TemporalProviderCancellationProbeExecutor,
    )
    from data_agent.agentops_temporal_adapter import (
        TemporalProviderCancellationStatus,
        TemporalWorkflowAdapter,
    )
    from data_agent.agentops_temporal_contracts import (
        TemporalActivitySchedulePlan,
        TemporalProviderExecutionSpec,
        temporal_contract_fingerprint,
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


WORKFLOW_TYPE = "gda.agentops.task_graph.v1"
ENVELOPE_SCHEMA = "gda.agentops.flink_cancellation_probe.v1"
REPORT_SCHEMA = "gda.agentops.temporal_flink_cancellation_report.v1"
TENANT_ID = "planning"
DEFAULT_TASK_QUEUE = "agentops-flink-cancellation"


def _report_fingerprint(report: dict[str, Any]) -> str:
    return canonical_json_fingerprint(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )


class _FlinkCancellationPolicyProxy:
    """Local rehearsal proxy that denies only provider cancellation PATCH calls."""

    def __init__(self, upstream: str) -> None:
        parsed = urlsplit(upstream.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Flink policy proxy requires an absolute HTTP(S) upstream")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Flink policy proxy upstream cannot contain credentials/query")
        self._upstream = parsed
        self._server: Any | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Flink policy proxy is not running")
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> _FlinkCancellationPolicyProxy:
        import http.client
        from http import server as http_server

        upstream = self._upstream

        class Handler(http_server.BaseHTTPRequestHandler):
            def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler contract.
                body = b'{"error":"cancellation denied by rehearsal policy"}'
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract.
                connection_type = (
                    http.client.HTTPSConnection
                    if upstream.scheme == "https"
                    else http.client.HTTPConnection
                )
                connection = connection_type(upstream.hostname, upstream.port, timeout=15)
                target = f"{upstream.path.rstrip('/')}{self.path}"
                try:
                    connection.request("GET", target, headers={"Accept": "application/json"})
                    response = connection.getresponse()
                    body = response.read()
                    self.send_response(response.status)
                    content_type = response.getheader("Content-Type")
                    if content_type:
                        self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    connection.close()

            def log_message(self, *_args: object) -> None:
                return

        self._server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="agentops-flink-cancellation-policy-proxy",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _direct_flink_state(flink_rest: str, job_id: str) -> str:
    import httpx

    response = httpx.get(f"{flink_rest.rstrip('/')}/jobs/{job_id}", timeout=15)
    response.raise_for_status()
    payload = response.json()
    return payload.get("state", "") if isinstance(payload, dict) else ""


@workflow.defn(name=WORKFLOW_TYPE)
class FlinkCancellationProbeWorkflow:
    """One activity that remains active until the workflow is cancelled."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("schema") != ENVELOPE_SCHEMA:
            raise ValueError("Flink cancellation probe envelope schema mismatch")
        schedule = TemporalActivitySchedulePlan.model_validate(payload["schedule"])
        return await workflow.execute_activity(
            schedule.activity_type,
            schedule.request.model_dump(mode="json"),
            task_queue=schedule.task_queue_ref,
            activity_id=str(schedule.activity_id),
            schedule_to_close_timeout=timedelta(
                seconds=schedule.schedule_to_close_timeout_seconds
            ),
            start_to_close_timeout=timedelta(
                seconds=schedule.start_to_close_timeout_seconds
            ),
            heartbeat_timeout=timedelta(seconds=schedule.heartbeat_timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=getattr(
                workflow.ActivityCancellationType,
                schedule.cancellation_type.name,
            ),
        )


def _flink_spec(job_id: str) -> TemporalProviderExecutionSpec:
    values: dict[str, Any] = {
        "provider_ref": "provider:flink",
        "operation_ref": "flink.iceberg.reconciliation.v1",
        "parameters": {"job_id": job_id},
        "input_artifact_ids": (),
        "output_media_type": "application/json",
    }
    values["spec_sha256"] = temporal_contract_fingerprint(
        TemporalProviderExecutionSpec.schema_id, values, "spec_sha256"
    )
    return TemporalProviderExecutionSpec(**values)


def _build_schedule(*, namespace_ref: str, task_queue_ref: str, job_id: str):
    execution_input = build_rehearsal_execution_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        run_key=f"flink-cancellation:{job_id}:{datetime.now(UTC).timestamp()}",
        provider_spec_by_agent={"fusion": _flink_spec(job_id)},
        side_effect_by_agent={"fusion": AgentSideEffect.EXTERNAL_WRITE},
    )
    workflow_input = execution_input.workflow_input
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    plans = {plan.agent_id: plan for plan in execution_input.execution_manifest.plans}
    harness.start(workflow_input)
    for agent_id in ("coordinator", "planner"):
        step = next(item for item in workflow_input.task_graph.steps if item.agent_id == agent_id)
        harness.start_step(workflow_id, step.step_id)
        harness.complete_step(workflow_id, step_id=step.step_id)
    step = next(item for item in workflow_input.task_graph.steps if item.agent_id == "fusion")
    plan = plans["fusion"]
    harness.start_step(workflow_id, step.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref=plan.tool_ref,
        capability_ref=plan.capability_ref,
        subject_context=plan.subject_context,
        side_effect=plan.side_effect,
        policy_decision_ref=plan.policy_decision_ref,
        idempotency_key=plan.idempotency_key,
        input_artifact_ids=(),
    )
    call = next(item for item in snapshot.execution.tool_calls if item.step_id == step.step_id)
    schedule = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type=TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=10,
        cancellation_type=plan.cancellation_type,
        provider_spec=plan.provider_spec,
    ).activity_schedules[-1]
    return execution_input, schedule


async def run_rehearsal(
    *,
    admin_url: str,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
    flink_rest: str,
    flink_job_id: str,
    cancel_timeout_seconds: float = 90,
    submission_timeout_seconds: float = 60,
    deny_cancellation: bool = False,
) -> tuple[dict[str, Any], str]:
    if submission_timeout_seconds <= 0:
        raise ValueError("submission_timeout_seconds must be positive")
    execution_input, schedule = _build_schedule(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        job_id=flink_job_id,
    )
    workflow_input = execution_input.workflow_input
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    provider_receipt_ref = f"flink://job/{flink_job_id}"
    with tempfile.TemporaryDirectory(prefix="gda-temporal-flink-cancel-") as temp_dir:
        with _temporary_postgres(admin_url) as sandbox:
            if sandbox.runtime_engine is None:
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
                _execute_migration(
                    connection,
                    AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION.read_text(
                        encoding="utf-8"
                    ),
                )
            authority = PostgresSpecialistOperationAuthority(
                TENANT_ID,
                sandbox.runtime_engine,
                recorded_by="workload:agentops-temporal-flink-cancel",
            )
            policy_proxy = _FlinkCancellationPolicyProxy(flink_rest) if deny_cancellation else None
            if policy_proxy is not None:
                policy_proxy.__enter__()
            cancellation_adapter = FlinkProviderCancellationAdapter(
                policy_proxy.url if policy_proxy is not None else flink_rest
            )
            submitted = None
            workflow_handle = None
            workflow_cleanup_required = False
            try:
                probe = TemporalProviderCancellationProbeExecutor(
                    authority,
                    cancellation_adapter,
                    hold_seconds=300,
                )
                activity_definition = build_specialist_activity_definition(probe)
                config = TemporalWorkerRuntimeConfig(
                    tenant_id=TENANT_ID,
                    namespace_ref=namespace_ref,
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
                    namespace=namespace_ref,
                    identity="workload:agentops-temporal-flink-cancel",
                )
                cluster = await client.service_client.workflow_service.get_cluster_info(
                    GetClusterInfoRequest()
                )
                worker = TemporalioWorkerFactory(
                    client,
                    config.registration(),
                    workflows=(
                        TemporalWorkerDefinition(WORKFLOW_TYPE, FlinkCancellationProbeWorkflow),
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
                    workflow_handle = await client.start_workflow(
                        WORKFLOW_TYPE,
                        envelope,
                        id=workflow_input.identity.workflow_id,
                        task_queue=task_queue_ref,
                    )
                    workflow_cleanup_required = True
                    submission_deadline = (
                        asyncio.get_running_loop().time() + submission_timeout_seconds
                    )
                    while asyncio.get_running_loop().time() < submission_deadline:
                        submitted = authority.observe(operation_ref)
                        if submitted is not None:
                            break
                        await asyncio.sleep(0.1)
                    if submitted is None:
                        observed_event_types: tuple[str, ...] = ()
                        try:
                            pending_history = await workflow_handle.fetch_history()
                            observed_event_types = tuple(
                                EventType.Name(event.event_type)
                                for event in pending_history.events
                            )
                        except Exception as exc:
                            observed_event_types = (
                                f"history_observation_error:{type(exc).__name__}",
                            )
                        raise RuntimeError(
                            "Temporal activity did not submit provider receipt within "
                            f"{submission_timeout_seconds:g}s; workflow_id={workflow_handle.id}; "
                            f"history_events={list(observed_event_types)}"
                        )
                    adapter = TemporalWorkflowAdapter(
                        TemporalioProviderClient(client, namespace_ref=namespace_ref)
                    )
                    cancel_result = await adapter.cancel_async(
                        workflow_input.identity,
                        reason="provider-native Flink cancellation activity rehearsal",
                    )
                    deadline = asyncio.get_running_loop().time() + cancel_timeout_seconds
                    while asyncio.get_running_loop().time() < deadline:
                        current = authority.observe(operation_ref)
                        if current is not None and current.status in {
                            SpecialistOperationStatus.UNKNOWN,
                            SpecialistOperationStatus.CANCELLED,
                        }:
                            break
                        await asyncio.sleep(0.25)
                    try:
                        await workflow_handle.result()
                    except Exception:
                        pass

                history = await workflow_handle.fetch_history()
                workflow_cleanup_required = False
                history_json = history.to_json()
                event_types = tuple(EventType.Name(event.event_type) for event in history.events)
                provider = TemporalioProviderClient(client, namespace_ref=namespace_ref)
                observed = await provider.observe_workflow_history(
                    tenant_id=TENANT_ID,
                    namespace_ref=namespace_ref,
                    workflow_id=workflow_handle.id,
                    provider_run_id=workflow_handle.first_execution_run_id,
                )
                activity_observation = next(
                    item for item in observed.activities if item.activity_id == schedule.activity_id
                )
                artifact_store = FilesystemSpecialistArtifactStore(Path(temp_dir) / "artifacts")
                history_join, specialist_reconciliation, settled = (
                    reconcile_specialist_activity_history(
                        activity_observation,
                        artifact_store=artifact_store,
                        operation_authority=authority,
                    )
                )
                receipt = authority.observe(operation_ref)
                provider_state_before_cleanup = (
                    _direct_flink_state(flink_rest, flink_job_id) if deny_cancellation else None
                )
                if deny_cancellation:
                    checks = {
                        "temporal_cancel_transport_accepted": (
                            cancel_result.status is TemporalProviderCancellationStatus.ACCEPTED
                        ),
                        "temporal_activity_terminal_cancelled": activity_observation.status
                        is TemporalProviderActivityHistoryStatus.CANCELLED,
                        "temporal_history_contains_activity_cancel_request": (
                            "EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED" in event_types
                        ),
                        "provider_receipt_identity_is_job_bound": (
                            receipt is not None
                            and receipt.provider_receipt_ref == provider_receipt_ref
                        ),
                        "provider_receipt_is_unknown_permission_denied": (
                            receipt is not None
                            and receipt.status is SpecialistOperationStatus.UNKNOWN
                            and receipt.cancellation_requested
                            and getattr(receipt.uncertainty_type, "value", None)
                            == "FlinkCancellationPermissionDenied"
                        ),
                        "provider_job_remains_running_after_denial": provider_state_before_cleanup
                        in {"RUNNING", "CREATED"},
                        "specialist_reconciliation_remains_unknown_pending": (
                            specialist_reconciliation.verdict.value == "unknown_pending"
                            and settled.outcome.value == "unknown"
                        ),
                    }
                else:
                    checks = {
                    "temporal_cancel_transport_accepted": (
                        cancel_result.status is TemporalProviderCancellationStatus.ACCEPTED
                    ),
                    "temporal_activity_terminal_cancelled": activity_observation.status
                    is TemporalProviderActivityHistoryStatus.CANCELLED,
                    "temporal_history_contains_activity_cancel_request": (
                        "EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED" in event_types
                    ),
                    "provider_receipt_identity_is_job_bound": (
                        receipt is not None
                        and receipt.provider_receipt_ref == provider_receipt_ref
                    ),
                    "provider_receipt_terminal_cancelled": (
                        receipt is not None
                        and receipt.status is SpecialistOperationStatus.CANCELLED
                    ),
                    "specialist_reconciliation_is_definitive_failed": (
                        specialist_reconciliation.verdict.value == "definitive_failed"
                        and settled.failure_type is not None
                    ),
                    }
                replay = await Replayer(
                    workflows=[FlinkCancellationProbeWorkflow]
                ).replay_workflow(WorkflowHistory.from_json(workflow_handle.id, history_json))
                checks["history_replay_passed"] = replay.replay_failure is None
                report: dict[str, Any] = {
                    "schema": REPORT_SCHEMA,
                    "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "status": "passed" if all(checks.values()) else "failed",
                    "scope": "docker_desktop_live_temporal_flink_provider_cancellation",
                    "cancellation_policy": "deny_patch" if deny_cancellation else "allow",
                    "production_readiness_claimed": False,
                    "temporal_server_version": cluster.server_version,
                    "temporal_sdk_version": version("temporalio"),
                    "namespace_ref": namespace_ref,
                    "workflow_id": workflow_handle.id,
                    "provider_run_id": workflow_handle.first_execution_run_id,
                    "activity_id": str(schedule.activity_id),
                    "operation_ref": operation_ref,
                    "provider_receipt_ref": provider_receipt_ref,
                    "cancel_result": cancel_result.model_dump(mode="json"),
                    "temporal_activity_status": activity_observation.status.value,
                    "temporal_history_event_types": event_types,
                    "temporal_history_event_count": len(history.events),
                    "temporal_history_sha256": hashlib.sha256(
                        history_json.encode("utf-8")
                    ).hexdigest(),
                    "provider_receipt": (
                        receipt.model_dump(mode="json") if receipt is not None else None
                    ),
                    "specialist_reconciliation": specialist_reconciliation.model_dump(
                        mode="json"
                    ),
                    "history_reconciliation": history_join.model_dump(mode="json"),
                    "settled_result": settled.model_dump(mode="json"),
                    "provider_state_before_cleanup": provider_state_before_cleanup,
                    "checks": checks,
                    "failure_reasons": [name for name, passed in checks.items() if not passed],
                }
                report["report_sha256"] = _report_fingerprint(report)
                if deny_cancellation:
                    cleanup_adapter = FlinkProviderCancellationAdapter(flink_rest)
                    try:
                        cleanup = cleanup_adapter.request_cancellation(
                            schedule.request,
                            operation_ref=operation_ref,
                            provider_receipt_ref=provider_receipt_ref,
                        )
                        cleanup_deadline = asyncio.get_running_loop().time() + 60
                        while (
                            cleanup.status.value != "confirmed"
                            and asyncio.get_running_loop().time() < cleanup_deadline
                        ):
                            await asyncio.sleep(0.25)
                            cleanup = cleanup_adapter.observe_cancellation(
                                schedule.request,
                                operation_ref=operation_ref,
                                provider_receipt_ref=provider_receipt_ref,
                            )
                        report["cleanup_provider_cancellation"] = cleanup.model_dump(mode="json")
                        report["cleanup_provider_job_cancelled"] = (
                            cleanup.status.value == "confirmed"
                        )
                        # The next managed reconciliation cycle runs after an
                        # operator restores provider permissions. Temporal has
                        # already recorded cancellation, so only the provider's
                        # native terminal observation may settle the receipt.
                        recovery_history_join, recovery_specialist, recovery_settled = (
                            reconcile_specialist_activity_history(
                                activity_observation,
                                artifact_store=artifact_store,
                                operation_authority=authority,
                                cancellation_adapter=cleanup_adapter,
                            )
                        )
                        recovery_receipt = authority.observe(operation_ref)
                        recovery_state = _direct_flink_state(flink_rest, flink_job_id)
                        report["recovery_reconciliation"] = recovery_history_join.model_dump(
                            mode="json"
                        )
                        report["recovery_specialist_reconciliation"] = (
                            recovery_specialist.model_dump(mode="json")
                        )
                        report["recovery_settled_result"] = recovery_settled.model_dump(
                            mode="json"
                        )
                        report["recovery_provider_receipt"] = (
                            recovery_receipt.model_dump(mode="json")
                            if recovery_receipt is not None
                            else None
                        )
                        report["provider_state_after_recovery"] = recovery_state
                        report["checks"].update(
                            {
                                "managed_reconciliation_observes_provider_cancellation": (
                                    recovery_receipt is not None
                                    and recovery_receipt.status
                                    is SpecialistOperationStatus.CANCELLED
                                    and recovery_settled.outcome.value == "failed"
                                    and recovery_specialist.verdict.value == "definitive_failed"
                                ),
                                "provider_permission_recovery_converges_without_resubmit": (
                                    recovery_state == "CANCELED"
                                    and recovery_receipt is not None
                                    and recovery_receipt.provider_receipt_ref
                                    == provider_receipt_ref
                                ),
                            }
                        )
                        report["status"] = (
                            "passed" if all(report["checks"].values()) else "failed"
                        )
                        report["failure_reasons"] = [
                            name for name, passed in report["checks"].items() if not passed
                        ]
                        report["report_sha256"] = _report_fingerprint(report)
                    finally:
                        cleanup_adapter.close()
                return report, history_json
            finally:
                if workflow_cleanup_required and workflow_handle is not None:
                    try:
                        await workflow_handle.cancel(
                            reason="cleanup incomplete bounded Flink cancellation rehearsal"
                        )
                    except Exception:
                        pass
                cancellation_adapter.close()
                if policy_proxy is not None:
                    policy_proxy.__exit__(None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--flink-rest", required=True)
    parser.add_argument("--flink-job-id", required=True)
    parser.add_argument("--cancel-timeout-seconds", type=float, default=90)
    parser.add_argument("--submission-timeout-seconds", type=float, default=60)
    parser.add_argument(
        "--deny-cancellation",
        action="store_true",
        help="deny only the provider PATCH cancellation call through a local policy proxy",
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    report, history = asyncio.run(
        run_rehearsal(
            admin_url=args.database_url,
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
            flink_rest=args.flink_rest,
            flink_job_id=args.flink_job_id,
            cancel_timeout_seconds=args.cancel_timeout_seconds,
            submission_timeout_seconds=args.submission_timeout_seconds,
            deny_cancellation=args.deny_cancellation,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.history.write_text(
        history + ("" if history.endswith("\n") else "\n"), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
