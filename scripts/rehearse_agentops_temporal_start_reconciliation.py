#!/usr/bin/env python3
"""Rehearse real Temporal duplicate/uncertain starts and input reconciliation."""

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

from temporalio import workflow
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_temporal_adapter import (
        TemporalProviderStartStatus,
        TemporalWorkflowAdapter,
    )
    from data_agent.agentops_temporal_contracts import (
        TEMPORAL_INPUT_SCHEMA,
        TEMPORAL_NAMESPACE_SCHEMA,
        TEMPORAL_TASK_QUEUE_SCHEMA,
        TEMPORAL_WORKFLOW_SCHEMA,
        derive_temporal_workflow_id,
        temporal_contract_fingerprint,
    )
    from data_agent.agentops_temporal_rehearsal import (
        REHEARSAL_ACTIVITY_TYPE,
        rehearsal_activity,
    )
    from data_agent.agentops_temporal_worker import (
        TemporalioWorkerFactory,
        TemporalWorkerDefinition,
        TemporalWorkerRuntimeConfig,
    )
    from data_agent.agentops_temporalio_provider import TemporalioProviderClient
    from data_agent.test_agentops_temporal_adapter import _input

REPORT_SCHEMA = "gda.agentops_temporal_start_reconciliation_report.v1"
WORKFLOW_TYPE = "gda.agentops.start-reconciliation.v1"
WORKER_IDENTITY = "workload:gda-agentops-start-reconciliation-v1"


@workflow.defn(name=WORKFLOW_TYPE)
class StartReconciliationWorkflow:
    """Short-lived workflow kept running while duplicate/unknown starts are observed."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        await workflow.sleep(5)
        return {"workflow_id": payload["identity"]["workflow_id"], "status": "completed"}


class _SubmitThenRaiseClient:
    """Inject a post-submit transport error without changing Temporal server state."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.data_converter = client.data_converter

    async def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
        await self._client.start_workflow(*args, **kwargs)
        raise RuntimeError("simulated transport loss after Temporal accepted start")

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> Any:
        return self._client.get_workflow_handle(workflow_id, run_id=run_id)


def _workflow_input(namespace_ref: str) -> Any:
    """Reuse the canonical test fixture while binding it to this rehearsal workflow type."""

    original = _input()
    input_values = original.model_dump(mode="json")
    identity_values = input_values["identity"]
    identity_values["namespace"]["namespace_ref"] = namespace_ref
    identity_values["namespace"]["namespace_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_NAMESPACE_SCHEMA,
        identity_values["namespace"],
        "namespace_sha256",
    )
    identity_values["task_queue"]["namespace_ref"] = namespace_ref
    identity_values["task_queue"]["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA,
        identity_values["task_queue"],
        "queue_sha256",
    )
    identity_values["workflow_type"] = WORKFLOW_TYPE
    identity_values["idempotency_key"] = f"{identity_values['idempotency_key']}:{uuid4()}"
    identity_values["workflow_id"] = derive_temporal_workflow_id(
        tenant_id=identity_values["tenant_id"],
        isolation_class=identity_values["namespace"]["isolation_class"],
        namespace_ref=identity_values["namespace"]["namespace_ref"],
        workflow_type=WORKFLOW_TYPE,
        agent_spec_sha256=identity_values["agent_spec_sha256"],
        deployment_revision_sha256=identity_values["deployment_revision_sha256"],
        idempotency_key=identity_values["idempotency_key"],
    )
    identity_values["identity_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_SCHEMA, identity_values, "identity_sha256"
    )
    input_values["identity"] = identity_values
    input_values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, input_values, "input_sha256"
    )
    return original.__class__(**input_values)


def _worker_config(workflow_input: Any, frontend_target: str) -> TemporalWorkerRuntimeConfig:
    return TemporalWorkerRuntimeConfig(
        tenant_id=workflow_input.tenant_id,
        namespace_ref=workflow_input.identity.namespace.namespace_ref,
        frontend_target=frontend_target,
        task_queue_ref=workflow_input.identity.task_queue.queue_ref,
        worker_identity_ref=WORKER_IDENTITY,
        workflow_type=WORKFLOW_TYPE,
        activity_types=(REHEARSAL_ACTIVITY_TYPE,),
        agent_spec_sha256=workflow_input.identity.agent_spec_sha256,
        deployment_revision_sha256=workflow_input.identity.deployment_revision_sha256,
        max_concurrent_activities=1,
        max_concurrent_workflow_tasks=1,
    )


async def run_rehearsal(
    *, frontend_target: str, namespace_ref: str
) -> tuple[dict[str, Any], str, str]:
    workflow_input = _workflow_input(namespace_ref)
    client = await Client.connect(
        frontend_target,
        namespace=namespace_ref,
        identity=WORKER_IDENTITY,
    )
    cluster = await client.service_client.workflow_service.get_cluster_info(
        GetClusterInfoRequest()
    )
    config = _worker_config(workflow_input, frontend_target)
    registration = config.registration()
    worker = TemporalioWorkerFactory(
        client,
        registration,
        workflows=(
            TemporalWorkerDefinition(WORKFLOW_TYPE, StartReconciliationWorkflow),
        ),
        activities=(
            TemporalWorkerDefinition(REHEARSAL_ACTIVITY_TYPE, rehearsal_activity),
        ),
    ).build()
    payload = workflow_input.model_dump(mode="json")
    task_queue = workflow_input.identity.task_queue.queue_ref

    async with worker:
        primary = await client.start_workflow(
            WORKFLOW_TYPE,
            payload,
            id=workflow_input.identity.workflow_id,
            task_queue=task_queue,
        )
        provider = TemporalioProviderClient(client, namespace_ref=namespace_ref)
        duplicate = await provider.start_workflow(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            workflow_type=WORKFLOW_TYPE,
            task_queue_ref=task_queue,
            payload=payload,
            retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
        )
        duplicate_observation = await provider.observe_workflow_input(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            provider_run_id=duplicate.provider_run_id,
        )
        duplicate_reconciliation = TemporalWorkflowAdapter(provider).reconcile_start(
            workflow_input,
            duplicate,
            observed_input_sha256=duplicate_observation.observed_input_sha256,
            observed_provider_run_id=duplicate_observation.provider_run_id,
        )
        duplicate_observation_history = await client.get_workflow_handle(
            workflow_input.identity.workflow_id,
            run_id=duplicate.provider_run_id,
        ).fetch_history()
        await primary.result()
        duplicate_history = await client.get_workflow_handle(
            workflow_input.identity.workflow_id,
            run_id=duplicate.provider_run_id,
        ).fetch_history()

        uncertain_input = _workflow_input(namespace_ref)
        uncertain_client = _SubmitThenRaiseClient(client)
        uncertain_provider = TemporalioProviderClient(
            uncertain_client, namespace_ref=namespace_ref
        )
        uncertain_payload = uncertain_input.model_dump(mode="json")
        uncertain = await uncertain_provider.start_workflow(
            tenant_id=uncertain_input.tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=uncertain_input.identity.workflow_id,
            workflow_type=WORKFLOW_TYPE,
            task_queue_ref=uncertain_input.identity.task_queue.queue_ref,
            payload=uncertain_payload,
            retry_policy=uncertain_input.retry_policy.model_dump(mode="json"),
        )
        uncertain_reconciliation = await TemporalWorkflowAdapter(
            uncertain_provider
        ).reconcile_start_async(uncertain_input, uncertain)
        uncertain_handle = uncertain_client.get_workflow_handle(
            uncertain_input.identity.workflow_id
        )
        await uncertain_handle.result()
        uncertain_history = await uncertain_handle.fetch_history()

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "frontend_target": frontend_target,
        "namespace_ref": namespace_ref,
        "temporal_server_version": cluster.server_version,
        "temporal_sdk_version": version("temporalio"),
        "workflow_type": WORKFLOW_TYPE,
        "duplicate_workflow_id": workflow_input.identity.workflow_id,
        "duplicate_provider_run_id": duplicate.provider_run_id,
        "duplicate_provider_status": duplicate.status.value,
        "duplicate_observed_input_sha256": duplicate_observation.observed_input_sha256,
        "duplicate_reconciliation_verdict": duplicate_reconciliation.verdict.value,
        "duplicate_reconciliation_sha256": duplicate_reconciliation.reconciliation_sha256,
        "duplicate_history_event_count": len(duplicate_history.events),
        "duplicate_observation_history_event_count": len(
            duplicate_observation_history.events
        ),
        "duplicate_history_sha256": hashlib.sha256(
            duplicate_history.to_json().encode("utf-8")
        ).hexdigest(),
        "uncertain_workflow_id": uncertain_input.identity.workflow_id,
        "uncertain_provider_status": uncertain.status.value,
        "uncertain_provider_receipt_ref": uncertain.provider_receipt_ref,
        "uncertain_reconciliation_verdict": uncertain_reconciliation.verdict.value,
        "uncertain_provider_run_id": uncertain_reconciliation.provider_run_id,
        "uncertain_observed_input_sha256": uncertain_reconciliation.observed_input_sha256,
        "uncertain_reconciliation_sha256": uncertain_reconciliation.reconciliation_sha256,
        "uncertain_history_event_count": len(uncertain_history.events),
        "uncertain_history_sha256": hashlib.sha256(
            uncertain_history.to_json().encode("utf-8")
        ).hexdigest(),
        "worker_registration_sha256": registration.registration_sha256,
    }
    if duplicate.status is not TemporalProviderStartStatus.ALREADY_EXISTS:
        raise RuntimeError("duplicate start did not return already_exists")
    if duplicate_reconciliation.verdict.value != "already_exists_matched":
        raise RuntimeError("duplicate start reconciliation did not match")
    if uncertain.status is not TemporalProviderStartStatus.UNKNOWN:
        raise RuntimeError("transport injection did not return unknown")
    if uncertain_reconciliation.verdict.value != "already_exists_matched":
        raise RuntimeError("unknown start reconciliation did not match observed history")
    report["report_sha256"] = temporal_contract_fingerprint(
        REPORT_SCHEMA, report, "report_sha256"
    )
    return report, duplicate_history.to_json(), uncertain_history.to_json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--duplicate-history", type=Path)
    parser.add_argument("--uncertain-history", type=Path)
    args = parser.parse_args()
    report, duplicate_history, uncertain_history = asyncio.run(
        run_rehearsal(frontend_target=args.frontend, namespace_ref=args.namespace)
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.duplicate_history:
        args.duplicate_history.parent.mkdir(parents=True, exist_ok=True)
        args.duplicate_history.write_text(duplicate_history + "\n")
    if args.uncertain_history:
        args.uncertain_history.parent.mkdir(parents=True, exist_ok=True)
        args.uncertain_history.write_text(uncertain_history + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
