"""Disposable PostgreSQL rehearsal for the managed AgentOps reconciler worker."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import create_engine

from .agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityConflictError,
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from .agentops_temporal_reconciler_worker import (
    AgentOpsTemporalReconcilerCycleStatus,
    AgentOpsTemporalReconcilerWorker,
    AgentOpsTemporalReconcilerWorkerConfig,
)
from .agentops_temporal_reconciliation import (
    TemporalCheckpointReconciliation,
    TemporalProviderWorkflowHistoryObservation,
)
from .agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from .cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint

_REPORTS = Path(__file__).resolve().parents[1] / "docs" / "reports"
_PREFIX = "agentops_temporal_checkpoint_reconciliation_2026-08-27"
_WORKER_A = "workload:agentops-managed-reconciler-a"
_WORKER_B = "workload:agentops-managed-reconciler-b"
_LEASE_SECONDS = 4
_HEARTBEAT_SECONDS = 0.75


class AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-reconciler-worker-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    process_scope: str = "two_independent_worker_processes"
    migration_ids: tuple[str, ...]
    source_evidence_prefix: str
    lease_epoch_sequence: tuple[int, ...]
    child_exit_code: int
    heartbeat_observed_renewals: int
    reconciliation_count: int
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprint_matches(
        self,
    ) -> AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("AgentOps reconciler worker report hash is invalid")
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
        {
            key: value
            for key, value in normalized.items()
            if key != "report_sha256"
        }
    )


def _load(suffix: str) -> dict[str, Any]:
    return json.loads(
        (_REPORTS / f"{_PREFIX}_{suffix}.json").read_text(encoding="utf-8")
    )


class _StaticObserver:
    def __init__(self, observation: TemporalProviderWorkflowHistoryObservation, delay: float):
        self.observation = observation
        self.delay = delay

    async def observe_workflow_history(self, **_kwargs: Any):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.observation


def _config(
    checkpoint: TemporalTaskGraphWorkflowCheckpoint,
    observation: TemporalProviderWorkflowHistoryObservation,
    *,
    lease_owner: str,
) -> AgentOpsTemporalReconcilerWorkerConfig:
    return AgentOpsTemporalReconcilerWorkerConfig(
        tenant_id=checkpoint.workflow_input.tenant_id,
        namespace_ref=(
            checkpoint.workflow_input.identity.namespace.namespace_ref
        ),
        frontend_target="temporal-rehearsal.invalid:7233",
        workflow_id=checkpoint.workflow_input.identity.workflow_id,
        provider_run_id=observation.provider_run_id,
        lease_owner=lease_owner,
        lease_seconds=_LEASE_SECONDS,
        heartbeat_interval_seconds=_HEARTBEAT_SECONDS,
        observation_timeout_seconds=120,
        poll_interval_seconds=1,
    )


def _child(database_url: str, delay_seconds: float) -> int:
    checkpoint = TemporalTaskGraphWorkflowCheckpoint.model_validate(
        _load("checkpoint_after")
    )
    observation = TemporalProviderWorkflowHistoryObservation.model_validate(
        _load("observation")
    )
    engine = create_engine(database_url)
    try:
        worker = AgentOpsTemporalReconcilerWorker(
            _config(checkpoint, observation, lease_owner=_WORKER_A),
            provider=_StaticObserver(observation, delay_seconds),
            authority=PostgresAgentOpsTemporalCheckpointAuthority(engine),
        )
        asyncio.run(worker.run_once())
    finally:
        engine.dispose()
    return 0


def _spawn_child(database_url: str) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "data_agent.agentops_temporal_reconciler_worker_postgres_rehearsal",
            "--child",
            "--observation-delay-seconds",
            "60",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_lease(
    authority: PostgresAgentOpsTemporalCheckpointAuthority,
    *,
    tenant_id: str,
    workflow_id: str,
    process: subprocess.Popen[str],
    timeout_seconds: float = 15,
):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                "managed reconciler child exited before acquiring its lease: "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        lease = authority.current_reconciler_lease(
            tenant_id=tenant_id, workflow_id=workflow_id
        )
        if lease is not None and lease.lease_owner == _WORKER_A:
            return lease
        time.sleep(0.1)
    raise RuntimeError("managed reconciler child did not acquire a lease")


def _wait_until_expired(expires_at: datetime) -> None:
    remaining = (expires_at - datetime.now(UTC)).total_seconds()
    if remaining > 0:
        time.sleep(remaining + 0.2)


def _observe_heartbeat_renewals(
    authority: PostgresAgentOpsTemporalCheckpointAuthority,
    *,
    tenant_id: str,
    workflow_id: str,
    initial_updated_at: datetime,
    original_expires_at: datetime,
) -> tuple[Any, int]:
    observed_updates: set[datetime] = set()
    current = None
    deadline = original_expires_at.timestamp() + 0.3
    while time.time() < deadline:
        current = authority.current_reconciler_lease(
            tenant_id=tenant_id, workflow_id=workflow_id
        )
        if current is not None and current.lease_updated_at > initial_updated_at:
            observed_updates.add(current.lease_updated_at)
        time.sleep(0.1)
    current = authority.current_reconciler_lease(
        tenant_id=tenant_id, workflow_id=workflow_id
    )
    if current is not None and current.lease_updated_at > initial_updated_at:
        observed_updates.add(current.lease_updated_at)
    return current, len(observed_updates)


def run_agentops_temporal_reconciler_worker_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, failure: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(failure)

    checkpoint = TemporalTaskGraphWorkflowCheckpoint.model_validate(
        _load("checkpoint_after")
    )
    observation = TemporalProviderWorkflowHistoryObservation.model_validate(
        _load("observation")
    )
    reconciliation = TemporalCheckpointReconciliation.model_validate(
        _load("matched")
    )
    tenant = checkpoint.workflow_input.tenant_id
    workflow_id = checkpoint.workflow_input.identity.workflow_id
    epochs: tuple[int, ...] = ()
    child_exit_code = 0
    heartbeat_observed_renewals = 0
    reconciliation_count = 0

    with _temporary_postgres(admin_url) as sandbox:
        if (
            sandbox.runtime_engine is None
            or sandbox.database_url is None
        ):
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            _execute_migration(
                connection,
                AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION.read_text(
                    encoding="utf-8"
                ),
            )
        authority = PostgresAgentOpsTemporalCheckpointAuthority(
            sandbox.runtime_engine
        )
        authority.record_checkpoint(
            checkpoint,
            recorded_by="workload:agentops-reconciler-bootstrap",
        )
        with sandbox.admin_connection() as connection:
            _execute_migration(
                connection,
                AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION.read_text(
                    encoding="utf-8"
                ),
            )
        runtime_url = sandbox.database_url.set(
            username=sandbox.role,
            password=sandbox.password,
        ).render_as_string(hide_password=False)
        child = _spawn_child(runtime_url)
        lease_a = None
        renewed_a = None
        try:
            lease_a = _wait_for_lease(
                authority,
                tenant_id=tenant,
                workflow_id=workflow_id,
                process=child,
            )
            check(
                "first_process_acquires_epoch_one",
                lease_a.lease_epoch == 1,
                "first managed reconciler did not acquire epoch 1",
            )
            renewed_a, heartbeat_observed_renewals = (
                _observe_heartbeat_renewals(
                    authority,
                    tenant_id=tenant,
                    workflow_id=workflow_id,
                    initial_updated_at=lease_a.lease_updated_at,
                    original_expires_at=lease_a.lease_expires_at,
                )
            )
            check(
                "heartbeat_extends_lease_past_original_expiry",
                renewed_a is not None
                and renewed_a.lease_epoch == 1
                and renewed_a.lease_owner == _WORKER_A
                and renewed_a.lease_updated_at > lease_a.lease_updated_at
                and heartbeat_observed_renewals >= 1
                and renewed_a.lease_expires_at > datetime.now(UTC),
                "managed reconciler heartbeat did not extend the original lease",
            )
            try:
                authority.acquire_reconciler_lease(
                    tenant_id=tenant,
                    workflow_id=workflow_id,
                    lease_owner=_WORKER_B,
                    lease_seconds=_LEASE_SECONDS,
                )
                competitor_rejected = False
            except AgentOpsTemporalCheckpointAuthorityConflictError:
                competitor_rejected = True
            check(
                "heartbeat_blocks_competing_process_after_original_ttl",
                competitor_rejected,
                "a competing worker acquired the heartbeat-maintained lease",
            )
            child.kill()
            child_exit_code = child.wait(timeout=10)
            check(
                "lease_owner_process_is_sigkilled",
                child_exit_code == -9,
                "lease owner process was not terminated by SIGKILL",
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            child.communicate(timeout=5)
        if renewed_a is None or lease_a is None:
            raise RuntimeError("managed reconciler lease observation was incomplete")

        # No process can renew after SIGKILL. The next owner must wait for the last
        # committed expiry and receives a new fencing epoch.
        latest_a = authority.current_reconciler_lease(
            tenant_id=tenant, workflow_id=workflow_id
        )
        if latest_a is None:
            raise RuntimeError("terminated worker lease disappeared unexpectedly")
        _wait_until_expired(latest_a.lease_expires_at)
        lease_b = authority.acquire_reconciler_lease(
            tenant_id=tenant,
            workflow_id=workflow_id,
            lease_owner=_WORKER_B,
            lease_seconds=_LEASE_SECONDS,
        )
        epochs = (lease_a.lease_epoch, lease_b.lease_epoch)
        check(
            "second_process_takes_over_with_new_epoch",
            epochs == (1, 2),
            "replacement reconciler did not receive epoch 2",
        )

        cycle = asyncio.run(
            AgentOpsTemporalReconcilerWorker(
                _config(checkpoint, observation, lease_owner=_WORKER_B),
                provider=_StaticObserver(observation, 0),
                authority=authority,
            ).run_once()
        )
        recovered = authority.resolve_reconciliation_write(
            observation, reconciliation
        )
        check(
            "takeover_worker_records_fenced_reconciliation",
            cycle.status is AgentOpsTemporalReconcilerCycleStatus.RECORDED
            and cycle.created
            and cycle.lease_epoch == 2
            and recovered is not None
            and recovered.binding.lease_owner == _WORKER_B
            and recovered.binding.lease_epoch == 2,
            "replacement worker did not persist reconciliation under epoch 2",
        )
        try:
            authority.record_reconciliation(
                observation,
                reconciliation,
                recorded_by=lease_a.lease_owner,
                lease=lease_a,
            )
            stale_worker_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            stale_worker_rejected = True
        check(
            "terminated_worker_epoch_is_rejected_after_takeover",
            stale_worker_rejected,
            "terminated worker epoch could write after replacement takeover",
        )
        current = authority.current_reconciler_lease(
            tenant_id=tenant, workflow_id=workflow_id
        )
        check(
            "takeover_worker_releases_lease_after_cycle",
            current is not None
            and current.lease_epoch == 2
            and current.lease_expires_at <= datetime.now(UTC),
            "replacement worker left its workflow lease active",
        )
        reconciliation_count = len(
            authority.reconciliation_history(
                tenant_id=tenant, workflow_id=workflow_id
            )
        )
        check(
            "single_reconciliation_record_survives_failover",
            reconciliation_count == 1,
            "worker failover produced missing or duplicate reconciliation evidence",
        )

    payload = {
        "schema_id": "gda.agentops-temporal-reconciler-worker-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "process_scope": "two_independent_worker_processes",
        "migration_ids": ("092", "094", "169", "240", "241"),
        "source_evidence_prefix": _PREFIX,
        "lease_epoch_sequence": epochs,
        "child_exit_code": child_exit_code,
        "heartbeat_observed_renewals": heartbeat_observed_renewals,
        "reconciliation_count": reconciliation_count,
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_agentops_temporal_reconciler_worker_postgres_rehearsal_report(
    report: AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport,
    output_path: str | Path,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse the managed AgentOps reconciler worker"
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--observation-delay-seconds", type=float, default=60)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.child:
        return _child(args.database_url, args.observation_delay_seconds)
    report = run_agentops_temporal_reconciler_worker_postgres_rehearsal(
        args.database_url
    )
    if args.output:
        write_agentops_temporal_reconciler_worker_postgres_rehearsal_report(
            report, args.output
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalReconcilerWorkerPostgresRehearsalReport",
    "run_agentops_temporal_reconciler_worker_postgres_rehearsal",
    "write_agentops_temporal_reconciler_worker_postgres_rehearsal_report",
]
