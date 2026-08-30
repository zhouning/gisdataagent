"""Disposable PostgreSQL rehearsal for Temporal start-target discovery."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .agentops_temporal_adapter import (
    TEMPORAL_START_RESULT_SCHEMA,
    TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalProviderWorkflowInputObservation,
    TemporalWorkflowAdapter,
    build_temporal_start_request,
)
from .agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityConflictError,
)
from .agentops_temporal_contracts import temporal_contract_fingerprint
from .agentops_temporal_start_target_authority import (
    AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
    PostgresAgentOpsTemporalStartTargetAuthority,
)
from .cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint
from .test_agentops_temporal_checkpoint_authority import _checkpoint

_MIGRATION_FILES = (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
)
_WORKER_A = "workload:agentops-start-discovery-a"
_WORKER_B = "workload:agentops-start-discovery-b"
_LEASE_SECONDS = 5


class AgentOpsTemporalStartTargetPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-start-target-postgres-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash_matches(self) -> AgentOpsTemporalStartTargetPostgresRehearsalReport:
        payload = self.model_dump(mode="json")
        payload.pop("report_sha256", None)
        if self.report_sha256 != _report_hash(payload):
            raise ValueError("start-target rehearsal report hash is invalid")
        return self


def _report_hash(payload: dict[str, Any]) -> str:
    normalized = json.loads(
        json.dumps(
            payload,
            ensure_ascii=True,
            default=lambda value: value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        )
    )
    return canonical_json_fingerprint(
        {key: value for key, value in normalized.items() if key != "report_sha256"}
    )


def _start_result(
    workflow_input: Any, status: TemporalProviderStartStatus
) -> TemporalProviderStartResult:
    values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "status": status,
        "provider_run_id": (
            "temporal-run:start-target"
            if status is not TemporalProviderStartStatus.UNKNOWN
            else None
        ),
        "provider_receipt_ref": "temporal://gda-agentops/start-target-receipt",
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
    )
    return TemporalProviderStartResult(**values)


def _input_observation(
    workflow_input: Any, request_sha256: str
) -> TemporalProviderWorkflowInputObservation:
    values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "provider_run_id": "temporal-run:start-target",
        "provider_receipt_ref": "temporal://gda-agentops/input-observation",
        "observed_input_sha256": request_sha256,
    }
    values["observation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA, values, "observation_sha256"
    )
    return TemporalProviderWorkflowInputObservation(**values)


def run_agentops_temporal_start_target_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsTemporalStartTargetPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    workflow_input = _checkpoint().workflow_input
    request = build_temporal_start_request(workflow_input)
    unknown_result = _start_result(workflow_input, TemporalProviderStartStatus.UNKNOWN)
    adapter = TemporalWorkflowAdapter(object())
    pending = adapter.reconcile_start(workflow_input, unknown_result)

    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None or sandbox.database_url is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            for migration in _MIGRATION_FILES:
                _execute_migration(connection, migration.read_text(encoding="utf-8"))
        runtime = PostgresAgentOpsTemporalStartTargetAuthority(sandbox.runtime_engine)
        first = runtime.register_start_target(
            request,
            unknown_result,
            pending,
            registered_by="workload:temporal-start-gateway",
        )
        replay = runtime.register_start_target(
            request,
            unknown_result,
            pending,
            registered_by="workload:temporal-start-gateway",
        )
        check(
            "start_receipt_replay_is_idempotent",
            first.target_id == replay.target_id
            and first.status == "pending_start_reconciliation",
            "replaying the same start receipt changed its target",
        )

        claimed_a = runtime.claim_due_targets(
            tenant_id=first.tenant_id,
            namespace_ref=first.namespace_ref,
            worker_id=_WORKER_A,
            lease_seconds=_LEASE_SECONDS,
        )
        check(
            "worker_a_claims_pending_target",
            len(claimed_a) == 1,
            "worker A did not claim target",
        )
        try:
            competing = runtime.claim_due_targets(
                tenant_id=first.tenant_id,
                namespace_ref=first.namespace_ref,
                worker_id=_WORKER_B,
                lease_seconds=_LEASE_SECONDS,
            )
            competitor_rejected = len(competing) == 0
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            competitor_rejected = True
        check(
            "worker_b_cannot_claim_live_target_lease",
            competitor_rejected,
            "a second worker claimed a target whose lease was still live",
        )
        time.sleep(_LEASE_SECONDS + 0.3)
        claimed_b = runtime.claim_due_targets(
            tenant_id=first.tenant_id,
            namespace_ref=first.namespace_ref,
            worker_id=_WORKER_B,
            lease_seconds=_LEASE_SECONDS,
        )
        check(
            "expired_claim_is_recoverable",
            len(claimed_b) == 1 and claimed_b[0].target_id == first.target_id,
            "expired start target was not reclaimed",
        )
        observation = _input_observation(workflow_input, request.payload_sha256)
        attached = runtime.attach_provider_run(
            claimed_b[0], observation, worker_id=_WORKER_B
        )
        completed = runtime.complete_target(attached, worker_id=_WORKER_B)
        check(
            "unknown_start_converges_after_matching_input",
            completed.status == "completed"
            and completed.provider_run_id == observation.provider_run_id
            and completed.start_reconciliation_document is not None,
            "unknown start did not converge after matching provider input",
        )
        try:
            runtime.complete_target(claimed_b[0], worker_id=_WORKER_A)
            stale_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            stale_rejected = True
        check(
            "stale_worker_cannot_settle_reclaimed_target",
            stale_rejected,
            "stale worker settled a target after lease takeover",
        )

    payload = {
        "schema_id": "gda.agentops-temporal-start-target-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "migration_ids": ("092", "094", "240", "241", "242"),
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
    }
    return AgentOpsTemporalStartTargetPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_agentops_temporal_start_target_postgres_rehearsal_report(
    report: AgentOpsTemporalStartTargetPostgresRehearsalReport, output_path: str | Path
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse Temporal start-target discovery")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_agentops_temporal_start_target_postgres_rehearsal(args.database_url)
    if args.output:
        write_agentops_temporal_start_target_postgres_rehearsal_report(report, args.output)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalStartTargetPostgresRehearsalReport",
    "run_agentops_temporal_start_target_postgres_rehearsal",
    "write_agentops_temporal_start_target_postgres_rehearsal_report",
]
