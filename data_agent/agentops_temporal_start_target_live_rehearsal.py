"""Live Temporal + PostgreSQL rehearsal for start-target discovery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from temporalio import workflow as _workflow
from temporalio.client import Client
from temporalio.worker import Worker

with _workflow.unsafe.imports_passed_through():
    from data_agent.agentops_temporal_adapter import (
        TemporalProviderStartStatus,
        TemporalWorkflowAdapter,
        build_temporal_start_request,
    )
    from data_agent.agentops_temporal_checkpoint_authority import (
        AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
        AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
        PostgresAgentOpsTemporalCheckpointAuthority,
    )
    from data_agent.agentops_temporal_reconciler_worker import (
        AgentOpsTemporalReconcilerDiscoveryConfig,
        AgentOpsTemporalReconcilerDiscoveryWorker,
    )
    from data_agent.agentops_temporal_start_target_authority import (
        AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
        PostgresAgentOpsTemporalStartTargetAuthority,
    )
    from data_agent.cross_store_projection_postgres_rehearsal import (
        _execute_migration,
        _temporary_postgres,
    )
    from data_agent.platform_contracts import FrozenContract, canonical_json_fingerprint
    from data_agent.test_agentops_temporal_adapter import _input

_WORKFLOW_TYPE = "gda.agentops.start-target-live-rehearsal.v1"
_TASK_QUEUE = "agentops-start-target-live"
_WORKER_ID = "workload:agentops-start-target-live"


@_workflow.defn(name=_WORKFLOW_TYPE)
class StartTargetLiveWorkflow:
    @_workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, str]:
        await _workflow.sleep(2)
        return {"workflow_id": payload["identity"]["workflow_id"]}


class _SubmitThenRaiseClient:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.data_converter = client.data_converter

    async def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
        await self._client.start_workflow(*args, **kwargs)
        raise RuntimeError("simulated transport loss after Temporal accepted start")

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> Any:
        return self._client.get_workflow_handle(workflow_id, run_id=run_id)


class AgentOpsTemporalStartTargetLiveRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-start-target-live-rehearsal.v1"
    checked_at: datetime
    frontend_target: str
    namespace_ref: str
    workflow_id: str
    provider_run_id: str
    temporal_sdk_version: str
    temporal_history_event_count: int
    target_status: str
    target_start_reconciliation_verdict: str
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash_matches(self) -> AgentOpsTemporalStartTargetLiveRehearsalReport:
        values = self.model_dump(mode="json")
        supplied = values.pop("report_sha256")
        if supplied != canonical_json_fingerprint(values):
            raise ValueError("live start-target report hash is invalid")
        return self


def _workflow_input(namespace_ref: str) -> Any:
    original = _input()
    values = original.model_dump(mode="json")
    identity = values["identity"]
    identity["namespace"]["namespace_ref"] = namespace_ref
    identity["task_queue"]["namespace_ref"] = namespace_ref
    identity["task_queue"]["queue_ref"] = _TASK_QUEUE
    identity["workflow_type"] = _WORKFLOW_TYPE
    from .agentops_temporal_contracts import (
        TEMPORAL_INPUT_SCHEMA,
        TEMPORAL_NAMESPACE_SCHEMA,
        TEMPORAL_TASK_QUEUE_SCHEMA,
        TEMPORAL_WORKFLOW_SCHEMA,
        derive_temporal_workflow_id,
        temporal_contract_fingerprint,
    )

    identity["namespace"]["namespace_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_NAMESPACE_SCHEMA, identity["namespace"], "namespace_sha256"
    )
    identity["task_queue"]["queue_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_QUEUE_SCHEMA, identity["task_queue"], "queue_sha256"
    )
    identity["workflow_id"] = derive_temporal_workflow_id(
        tenant_id=identity["tenant_id"],
        isolation_class=identity["namespace"]["isolation_class"],
        namespace_ref=namespace_ref,
        workflow_type=_WORKFLOW_TYPE,
        agent_spec_sha256=identity["agent_spec_sha256"],
        deployment_revision_sha256=identity["deployment_revision_sha256"],
        idempotency_key=identity["idempotency_key"] + ":live-start-target",
    )
    identity["idempotency_key"] += ":live-start-target"
    identity["identity_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_SCHEMA, identity, "identity_sha256"
    )
    values["identity"] = identity
    values["input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_INPUT_SCHEMA, values, "input_sha256"
    )
    return original.__class__(**values)


async def _run_live(
    *, frontend_target: str, namespace_ref: str, admin_url: str
) -> AgentOpsTemporalStartTargetLiveRehearsalReport:
    workflow_input = _workflow_input(namespace_ref)
    request = build_temporal_start_request(workflow_input)
    client = await Client.connect(frontend_target, namespace=namespace_ref, identity=_WORKER_ID)
    provider = None
    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            _execute_migration(
                connection,
                AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION.read_text(encoding="utf-8"),
            )
            _execute_migration(
                connection,
                AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION.read_text(encoding="utf-8"),
            )
            _execute_migration(
                connection,
                AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION.read_text(encoding="utf-8"),
            )
        target_authority = PostgresAgentOpsTemporalStartTargetAuthority(
            sandbox.runtime_engine
        )
        checkpoint_authority = PostgresAgentOpsTemporalCheckpointAuthority(
            sandbox.runtime_engine
        )
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[StartTargetLiveWorkflow],
        ):
            from .agentops_temporalio_provider import TemporalioProviderClient

            provider = TemporalioProviderClient(
                _SubmitThenRaiseClient(client), namespace_ref=namespace_ref
            )
            unknown = await provider.start_workflow(
                tenant_id=workflow_input.tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_input.identity.workflow_id,
                workflow_type=_WORKFLOW_TYPE,
                task_queue_ref=_TASK_QUEUE,
                payload=workflow_input.model_dump(mode="json"),
                retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
            )
            pending = TemporalWorkflowAdapter(provider).reconcile_start(
                workflow_input, unknown
            )
            target = target_authority.register_start_target(
                request,
                unknown,
                pending,
                registered_by=_WORKER_ID,
            )
            discovery = AgentOpsTemporalReconcilerDiscoveryWorker(
                AgentOpsTemporalReconcilerDiscoveryConfig(
                    tenant_id=target.tenant_id,
                    namespace_ref=target.namespace_ref,
                    worker_id=_WORKER_ID,
                    lease_seconds=10,
                    heartbeat_interval_seconds=1,
                    observation_timeout_seconds=20,
                    poll_interval_seconds=0.2,
                ),
                provider=TemporalioProviderClient(client, namespace_ref=namespace_ref),
                target_authority=target_authority,
                checkpoint_authority=checkpoint_authority,
            )
            cycle = await discovery.run_once()
            settled = target_authority.get_target(
                tenant_id=target.tenant_id, target_id=target.target_id
            )
            if settled is None or settled.provider_run_id is None:
                raise RuntimeError("live Temporal discovery did not attach a provider run")
            history = await client.get_workflow_handle(
                workflow_input.identity.workflow_id, run_id=settled.provider_run_id
            ).fetch_history()
            await client.get_workflow_handle(
                workflow_input.identity.workflow_id, run_id=settled.provider_run_id
            ).result()
            checks = {
                "provider_returns_unknown_after_submit": unknown.status
                is TemporalProviderStartStatus.UNKNOWN,
                "discovery_claims_one_target": cycle.claimed_count == 1,
                "real_temporal_input_observation_attaches_run": (
                    settled.provider_run_id is not None
                    and settled.start_reconciliation_document is not None
                    and settled.start_reconciliation_document.get("verdict")
                    == "already_exists_matched"
                ),
                "target_remains_ready_without_gda_checkpoint": settled.status == "ready",
                "real_temporal_history_is_observed": len(history.events) >= 2,
            }
            payload = {
                "schema_id": "gda.agentops-temporal-start-target-live-rehearsal.v1",
                "checked_at": datetime.now(UTC),
                "frontend_target": frontend_target,
                "namespace_ref": namespace_ref,
                "workflow_id": workflow_input.identity.workflow_id,
                "provider_run_id": settled.provider_run_id,
                "temporal_sdk_version": version("temporalio"),
                "temporal_history_event_count": len(history.events),
                "target_status": settled.status,
                "target_start_reconciliation_verdict": settled.start_reconciliation_document.get(
                    "verdict", ""
                ),
                "checks": checks,
                "passed": all(checks.values()),
                "failure_reasons": tuple(
                    name for name, passed in checks.items() if not passed
                ),
            }
            normalized = json.loads(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    default=lambda value: value.astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                )
            )
            return AgentOpsTemporalStartTargetLiveRehearsalReport(
                **payload,
                report_sha256=canonical_json_fingerprint(normalized),
            )


def write_report(report: AgentOpsTemporalStartTargetLiveRehearsalReport, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = asyncio.run(
        _run_live(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            admin_url=args.database_url,
        )
    )
    write_report(report, args.report)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalStartTargetLiveRehearsalReport",
    "write_report",
]
