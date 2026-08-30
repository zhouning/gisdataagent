#!/usr/bin/env python3
"""Rehearse the typed GDA workflow-cancel adapter against a real Temporal server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client

from data_agent.agentops_temporal_adapter import (
    TemporalProviderCancellationStatus,
    TemporalProviderStartStatus,
    TemporalWorkflowAdapter,
)
from data_agent.agentops_temporal_task_graph_rehearsal import (
    build_rehearsal_execution_input,
)
from data_agent.agentops_temporalio_provider import TemporalioProviderClient
from data_agent.platform_contracts import canonical_json_fingerprint

REPORT_SCHEMA = "gda.agentops_temporal_workflow_cancel_transport_report.v1"
TENANT_ID = "planning"


async def run_rehearsal(
    *, frontend_target: str, namespace_ref: str, task_queue_ref: str
) -> tuple[dict[str, object], str]:
    execution_input = build_rehearsal_execution_input(
        namespace_ref=namespace_ref,
        task_queue_ref=task_queue_ref,
        run_key=f"workflow-cancel-transport:{uuid4().hex}",
    )
    workflow_input = execution_input.workflow_input
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity="workload:agentops-cancel-transport-rehearsal",
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    provider = TemporalioProviderClient(client, namespace_ref=namespace_ref)
    adapter = TemporalWorkflowAdapter(provider)
    workflow_id = workflow_input.identity.workflow_id
    handle = None
    try:
        started = await adapter.start_async(workflow_input)
        handle = client.get_workflow_handle(
            workflow_id, run_id=started.provider_run_id
        )
        cancelled = await adapter.cancel_async(
            workflow_input.identity,
            reason="bounded AgentOps workflow cancellation transport rehearsal",
        )
        history = None
        event_names: list[str] = []
        for _ in range(100):
            history = await handle.fetch_history()
            event_names = [EventType.Name(event.event_type) for event in history.events]
            if "EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED" in event_names:
                break
            await asyncio.sleep(0.05)
        if history is None:
            raise RuntimeError("Temporal history was not observed")
        history_json = history.to_json()
        observed_provider_run_id = getattr(history, "run_id", None) or getattr(
            handle, "run_id", None
        )
        checks = {
            "start_observable": (
                started.status is TemporalProviderStartStatus.STARTED
                or (
                    started.status is TemporalProviderStartStatus.UNKNOWN
                    and "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED" in event_names
                )
            ),
            "cancel_transport_accepted": (
                cancelled.status is TemporalProviderCancellationStatus.ACCEPTED
            ),
            "cancel_reason_bound": cancelled.reason
            == "bounded AgentOps workflow cancellation transport rehearsal",
            "cancel_receipt_bound": cancelled.provider_receipt_ref.startswith(
                "temporal://gda-agentops/cancel/"
            ),
            "history_contains_cancel_requested": (
                "EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED" in event_names
            ),
            "workflow_identity_bound": started.workflow_id == cancelled.workflow_id == workflow_id,
        }
        payload: dict[str, object] = {
            "schema": REPORT_SCHEMA,
            "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "scope": "live_temporal_workflow_cancel_transport_bounded",
            "tenant_id": TENANT_ID,
            "namespace_ref": namespace_ref,
            "workflow_id": workflow_id,
            "provider_run_id": observed_provider_run_id,
            "start_result_provider_run_id": started.provider_run_id,
            "start_status": started.status.value,
            "cancel_status": cancelled.status.value,
            "cancel_reason": cancelled.reason,
            "cancel_provider_receipt_ref": cancelled.provider_receipt_ref,
            "temporal_server_version": getattr(cluster, "server_version", "unknown"),
            "temporal_sdk_version": version("temporalio"),
            "history_event_count": len(history.events),
            "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
            "history_event_types": event_names,
            "checks": checks,
            "passed": all(checks.values()),
            "failure_reasons": [name for name, passed in checks.items() if not passed],
            "provider_operation_cancellation_claimed": False,
            "production_readiness_claimed": False,
        }
        payload["report_sha256"] = canonical_json_fingerprint(payload)
        return payload, history_json
    finally:
        if handle is not None:
            try:
                await handle.terminate(reason="bounded cancellation transport rehearsal cleanup")
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:17233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-cancel-transport-rehearsal")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "docs/reports/agentops_temporal_workflow_cancel_transport_2026-08-29.json"
        ),
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path(
            "docs/reports/agentops_temporal_workflow_cancel_transport_history_2026-08-29.json"
        ),
    )
    args = parser.parse_args()
    report, history_json = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(history_json + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
