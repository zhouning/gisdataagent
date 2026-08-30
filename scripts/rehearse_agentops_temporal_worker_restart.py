#!/usr/bin/env python3
"""Rehearse Temporal worker termination and explicit AgentOps attempt recovery.

The rehearsal starts a worker in a child process, waits until an activity is actually
started, then sends SIGKILL to that worker.  The activity has no SDK retry; after the
heartbeat timeout the workflow schedules a new, explicitly identified attempt.  A second
worker completes that attempt.  This is deliberately separate from the optional Kubernetes
worker deployment, which remains disabled until a production worker image is certified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType, TimeoutType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from temporalio.exceptions import TimeoutError as TemporalTimeoutError
from temporalio.worker import Replayer

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_temporal_adapter import (
        TemporalActivityAdapter,
        TemporalProviderActivityResult,
    )
    from data_agent.agentops_temporal_contracts import (
        TEMPORAL_ACTIVITY_REQUEST_SCHEMA,
        TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
        TemporalActivityRequest,
        TemporalActivitySchedulePlan,
        derive_temporal_activity_id,
        temporal_contract_fingerprint,
    )
    from data_agent.agentops_temporal_rehearsal import _REHEARSAL_HANDLER
    from data_agent.agentops_temporal_worker import (
        TemporalioWorkerFactory,
        TemporalWorkerDefinition,
        TemporalWorkerRuntimeConfig,
    )
    from data_agent.platform_contracts import canonical_json_fingerprint
    try:  # Works both as ``scripts.<module>`` in tests and as a direct CLI script.
        from scripts.rehearse_agentops_temporal import (
            WORKER_IDENTITY,
            _worker_config,
            build_schedule_plan,
        )
    except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI entrypoint
        from rehearse_agentops_temporal import (  # type: ignore[no-redef]
            WORKER_IDENTITY,
            _worker_config,
            build_schedule_plan,
        )

REPORT_SCHEMA = "gda.agentops_temporal_worker_restart_report.v1"
RESTART_WORKFLOW_TYPE = "gda.agentops.worker-restart.v1"
RESTART_ACTIVITY_TYPE = "gda.agentops.worker-restart.activity"
WORKER_READY = "GDA_AGENTOPS_WORKER_READY"


def build_attempt_schedule(
    *, workflow_id: str, namespace_ref: str, task_queue_ref: str, attempt_no: int
) -> TemporalActivitySchedulePlan:
    """Build a deterministic schedule for an explicit platform activity attempt."""

    if attempt_no < 1:
        raise ValueError("attempt_no must be positive")
    base = build_schedule_plan(
        workflow_id=workflow_id,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    request_values = base.request.model_dump(mode="json")
    request_values["attempt_no"] = attempt_no
    request_values["activity_id"] = str(
        derive_temporal_activity_id(
            run_id=base.request.run_id,
            tool_call_id=base.request.tool_call_id,
            attempt_no=attempt_no,
        )
    )
    request_values["request_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_REQUEST_SCHEMA, request_values, "request_sha256"
    )
    request = TemporalActivityRequest(**request_values)
    schedule_values = base.model_dump(mode="json")
    schedule_values.update(
        {
            "activity_type": RESTART_ACTIVITY_TYPE,
            "attempt_no": attempt_no,
            "activity_id": str(request.activity_id),
            "request": request.model_dump(mode="json"),
            "request_sha256": request.request_sha256,
            # Keep the interruption window short enough for a local rehearsal while
            # leaving enough time for the worker process to be killed after STARTED.
            "start_to_close_timeout_seconds": 20.0,
            "schedule_to_close_timeout_seconds": 40.0,
            "heartbeat_timeout_seconds": 2.0,
        }
    )
    schedule_values["schedule_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA,
        schedule_values,
        "schedule_sha256",
    )
    return TemporalActivitySchedulePlan(**schedule_values)


def _activity_options(schedule: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": schedule["activity_id"],
        "task_queue": schedule["task_queue_ref"],
        "schedule_to_close_timeout": timedelta(
            seconds=schedule["schedule_to_close_timeout_seconds"]
        ),
        "start_to_close_timeout": timedelta(
            seconds=schedule["start_to_close_timeout_seconds"]
        ),
        "heartbeat_timeout": timedelta(seconds=schedule["heartbeat_timeout_seconds"]),
        "retry_policy": RetryPolicy(maximum_attempts=1),
        "cancellation_type": workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
    }


@activity.defn(name=RESTART_ACTIVITY_TYPE)
async def restart_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep attempt one alive until its worker is killed; complete attempt two normally."""

    request = TemporalActivityRequest.model_validate(payload)
    if request.attempt_no == 1:
        # A heartbeat proves the activity reached a worker. Killing that worker leaves
        # Temporal to record a definitive activity timeout from the pinned server.
        while True:
            activity.heartbeat({"attempt_no": request.attempt_no})
            await asyncio.sleep(0.25)
    if request.attempt_no != 2:
        raise ValueError("restart rehearsal only accepts attempts one and two")
    return await _REHEARSAL_HANDLER.handle_async(payload)


@workflow.defn(name=RESTART_WORKFLOW_TYPE)
class WorkerRestartWorkflow:
    """Workflow that converts a definitive timeout into an explicit second attempt."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedules = payload["schedules"]
        first_timed_out = False
        try:
            await workflow.execute_activity(
                RESTART_ACTIVITY_TYPE,
                schedules[0]["request"],
                **_activity_options(schedules[0]),
            )
        except ActivityError as error:
            # SDK retries are disabled.  The workflow itself owns the transition to the
            # next platform attempt, so the new activity id is visible in history.
            if not isinstance(error.cause, TemporalTimeoutError):
                raise
            first_timed_out = True
        if not first_timed_out:
            raise RuntimeError("restart rehearsal first attempt unexpectedly completed")
        second_result = await workflow.execute_activity(
            RESTART_ACTIVITY_TYPE,
            schedules[1]["request"],
            **_activity_options(schedules[1]),
        )
        return {
            "first_attempt": schedules[0]["attempt_no"],
            "first_attempt_recovered_by_workflow": first_timed_out,
            "second_attempt": schedules[1]["attempt_no"],
            "second_result": second_result,
        }


def _worker_config_for_restart(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> TemporalWorkerRuntimeConfig:
    base = _worker_config(
        frontend_target=frontend_target,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    return base.model_copy(
        update={
            "workflow_type": RESTART_WORKFLOW_TYPE,
            "activity_types": (RESTART_ACTIVITY_TYPE,),
        }
    )


async def _worker_process(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> None:
    config = _worker_config_for_restart(
        frontend_target=frontend_target,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=WORKER_IDENTITY,
    )
    worker = TemporalioWorkerFactory(
        client,
        config.registration(),
        workflows=(
            TemporalWorkerDefinition(RESTART_WORKFLOW_TYPE, WorkerRestartWorkflow),
        ),
        activities=(
            TemporalWorkerDefinition(RESTART_ACTIVITY_TYPE, restart_activity),
        ),
    ).build()
    print(WORKER_READY, flush=True)
    # Keep the worker inside the SDK async context so pollers are started before the
    # parent submits the workflow.  The parent owns process termination for this rehearsal.
    async with worker:
        await asyncio.Event().wait()


async def _spawn_worker(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--frontend",
        frontend_target,
        "--namespace",
        namespace_ref,
        "--task-queue",
        task_queue_ref,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("Temporal worker did not become ready") from exc
    if line.decode(errors="replace").strip() != WORKER_READY:
        stderr = await process.stderr.read() if process.stderr is not None else b""
        await process.wait()
        raise RuntimeError(
            "Temporal worker failed before readiness: "
            + stderr.decode(errors="replace")
        )
    return process


async def _wait_for_event_types(
    handle: Any,
    required: set[str],
    *,
    timeout_seconds: float = 30,
    worker: asyncio.subprocess.Process | None = None,
) -> tuple[Any, tuple[str, ...]]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        history = await handle.fetch_history()
        event_types = tuple(EventType.Name(event.event_type) for event in history.events)
        if required.issubset(set(event_types)):
            return history, event_types
        if asyncio.get_running_loop().time() >= deadline:
            worker_state = None if worker is None else worker.returncode
            worker_error = ""
            if worker is not None and worker.returncode is not None and worker.stderr is not None:
                worker_error = (await worker.stderr.read()).decode(errors="replace")[-4000:]
            raise TimeoutError(
                f"Temporal history for {handle.id} did not reach events "
                f"{sorted(required)}; observed={list(event_types)}; "
                f"worker_returncode={worker_state}; worker_stderr={worker_error}"
            )
        await asyncio.sleep(0.25)


async def run_rehearsal(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> tuple[dict[str, Any], str]:
    unique_suffix = uuid5(UUID(int=0), str(datetime.now(UTC).timestamp()))
    workflow_id = f"gda-agentops-worker-restart-{os.getpid()}-{unique_suffix}"
    first = build_attempt_schedule(
        workflow_id=workflow_id,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        attempt_no=1,
    )
    second = build_attempt_schedule(
        workflow_id=workflow_id,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        attempt_no=2,
    )
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=WORKER_IDENTITY,
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    worker_one = await _spawn_worker(
        frontend_target=frontend_target,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    handle = await client.start_workflow(
        RESTART_WORKFLOW_TYPE,
        {"schedules": [first.model_dump(mode="json"), second.model_dump(mode="json")]},
        id=workflow_id,
        task_queue=task_queue_ref,
    )
    try:
        _, started_events = await _wait_for_event_types(
            handle,
            {"EVENT_TYPE_ACTIVITY_TASK_STARTED"},
            timeout_seconds=20,
            worker=worker_one,
        )
    except BaseException:
        if worker_one.returncode is None:
            worker_one.kill()
            await worker_one.wait()
        raise
    kill_at = datetime.now(UTC)
    worker_one.kill()
    worker_one_exit = await worker_one.wait()
    timeout_history, timeout_events = await _wait_for_event_types(
        handle, {"EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT"}, timeout_seconds=20
    )
    worker_two = await _spawn_worker(
        frontend_target=frontend_target,
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
    )
    try:
        result_payload = await handle.result()
        completed_at = datetime.now(UTC)
    finally:
        worker_two.terminate()
        try:
            worker_two_exit = await asyncio.wait_for(worker_two.wait(), timeout=10)
        except TimeoutError:
            worker_two.kill()
            worker_two_exit = await worker_two.wait()
    history = await handle.fetch_history()
    history_json = history.to_json()
    exported_history = WorkflowHistory.from_json(workflow_id, history_json)
    replay = await Replayer(workflows=[WorkerRestartWorkflow]).replay_workflow(
        exported_history
    )
    event_types = tuple(EventType.Name(event.event_type) for event in history.events)
    provider_result = TemporalProviderActivityResult.model_validate(
        result_payload["second_result"]
    )
    second_evidence = TemporalActivityAdapter.evidence_from_result(
        second.request, provider_result
    )
    if event_types.count("EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") != 2:
        raise RuntimeError("restart history must contain exactly two activity schedules")
    if event_types.count("EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT") != 1:
        raise RuntimeError("restart history must contain exactly one timeout")
    if event_types.count("EVENT_TYPE_ACTIVITY_TASK_COMPLETED") != 1:
        raise RuntimeError("restart history must contain exactly one completion")
    if worker_one_exit == 0:
        raise RuntimeError("first worker was not terminated")
    timeout_event = next(
        event
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT
    )
    timeout_info = (
        timeout_event.activity_task_timed_out_event_attributes.failure.timeout_failure_info
    )
    timeout_type = TimeoutType.Name(timeout_info.timeout_type)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": completed_at.isoformat(),
        "status": "passed",
        "frontend_target": frontend_target,
        "namespace_ref": namespace_ref,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "workflow_type": RESTART_WORKFLOW_TYPE,
        "workflow_id": workflow_id,
        "provider_run_id": handle.first_execution_run_id,
        "task_queue_ref": task_queue_ref,
        "worker_identity_ref": WORKER_IDENTITY,
        "first_worker_exit_code": worker_one_exit,
        "second_worker_exit_code": worker_two_exit,
        "first_activity_id": str(first.activity_id),
        "second_activity_id": str(second.activity_id),
        "first_request_sha256": first.request_sha256,
        "second_request_sha256": second.request_sha256,
        "first_schedule_sha256": first.schedule_sha256,
        "second_schedule_sha256": second.schedule_sha256,
        "second_provider_result_sha256": provider_result.result_sha256,
        "second_activity_evidence_sha256": second_evidence.evidence_sha256,
        "second_output_artifact_id": str(second_evidence.output_artifact_id),
        "started_event_count_before_kill": started_events.count(
            "EVENT_TYPE_ACTIVITY_TASK_STARTED"
        ),
        "timeout_event_count_after_kill": timeout_events.count(
            "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT"
        ),
        "activity_timeout_type": timeout_type,
        "history_event_count": len(history.events),
        "history_event_types": event_types,
        "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
        "history_before_restart_sha256": hashlib.sha256(
            timeout_history.to_json().encode("utf-8")
        ).hexdigest(),
        "worker_kill_at": kill_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "recovery_duration_seconds": (completed_at - kill_at).total_seconds(),
        "explicit_sdk_maximum_attempts": 1,
        "history_replay_status": "passed" if replay.replay_failure is None else "failed",
    }
    if replay.replay_failure is not None:
        raise replay.replay_failure
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report, history_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-gis-worker-restart")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--history", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        asyncio.run(
            _worker_process(
                frontend_target=args.frontend,
                namespace_ref=args.namespace,
                task_queue_ref=args.task_queue,
            )
        )
        return
    if args.report is None or args.history is None:
        raise SystemExit("--report and --history are required for rehearsal mode")
    report, history_json = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    args.history.write_text(history_json + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
