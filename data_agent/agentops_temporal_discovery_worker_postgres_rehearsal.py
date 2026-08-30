"""Disposable PostgreSQL rehearsal for discovery-worker failover and recovery.

This is an evidence-producing rehearsal, not a Kubernetes HA claim.  Two
independent Python processes share the migration-242 target authority.  The
first process is killed while observing a start input, the second process
reclaims the expired lease, exercises a simulated Temporal transport failure,
and then completes the same target after recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import create_engine

from .agentops_temporal_adapter import (
    TEMPORAL_START_RESULT_SCHEMA,
    TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
    TemporalAdapterError,
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
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from .agentops_temporal_contracts import temporal_contract_fingerprint
from .agentops_temporal_reconciler_worker import (
    AgentOpsTemporalReconcilerDiscoveryConfig,
    AgentOpsTemporalReconcilerDiscoveryStatusStore,
    AgentOpsTemporalReconcilerDiscoveryWorker,
)
from .agentops_temporal_reconciliation import (
    TemporalProviderWorkflowHistoryObservation,
)
from .agentops_temporal_start_target_authority import (
    AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
    AgentOpsTemporalStartTargetStatus,
    PostgresAgentOpsTemporalStartTargetAuthority,
    TemporalStartTarget,
)
from .cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint
from .test_agentops_temporal_checkpoint_authority import _checkpoint, _observation

_FENCED_MIGRATIONS = (
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
)
_WORKER_A = "workload:agentops-discovery-a"
_WORKER_B_FAILURE = "workload:agentops-discovery-b-failure"
_WORKER_B = "workload:agentops-discovery-b"
_WORKER_HEALTH = "workload:agentops-discovery-health"
_LEASE_SECONDS = 5
_HEARTBEAT_SECONDS = 0.4
_POLL_SECONDS = 0.2


class AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-discovery-worker-postgres-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    process_scope: str = "two_independent_discovery_worker_processes"
    migration_ids: tuple[str, ...]
    lease_seconds: int
    worker_a_pid: int
    worker_a_exit_code: int
    worker_b_failure_exit_code: int
    worker_b_recovery_exit_code: int
    heartbeat_observed_renewals: int
    final_attempt_count: int
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
    ) -> AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("discovery worker rehearsal report hash is invalid")
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


def _start_result(workflow_input: Any) -> TemporalProviderStartResult:
    values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "status": TemporalProviderStartStatus.UNKNOWN,
        "provider_run_id": None,
        "provider_receipt_ref": "temporal://gda-agentops/discovery-worker-rehearsal",
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
    )
    return TemporalProviderStartResult(**values)


def _input_observation(
    *, tenant_id: str, namespace_ref: str, workflow_id: str, request_sha256: str,
    provider_run_id: str,
) -> TemporalProviderWorkflowInputObservation:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "namespace_ref": namespace_ref,
        "workflow_id": workflow_id,
        "provider_run_id": provider_run_id,
        "provider_receipt_ref": "temporal://gda-agentops/discovery-worker-input",
        "observed_input_sha256": request_sha256,
    }
    values["observation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA, values, "observation_sha256"
    )
    return TemporalProviderWorkflowInputObservation(**values)


class _RehearsalObserver:
    """Small provider double with explicit health and transport-failure modes."""

    def __init__(
        self,
        history: TemporalProviderWorkflowHistoryObservation,
        request_sha256: str,
        *,
        mode: str = "normal",
        delay_seconds: float = 0.0,
    ) -> None:
        self.history = history
        self.request_sha256 = request_sha256
        self.mode = mode
        self.delay_seconds = delay_seconds

    async def check_health(self) -> bool:
        return self.mode != "frontend-outage"

    async def observe_workflow_input(
        self, **kwargs: Any
    ) -> TemporalProviderWorkflowInputObservation:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.mode == "network-failure":
            raise TemporalAdapterError("simulated Temporal network outage")
        return _input_observation(
            tenant_id=str(kwargs["tenant_id"]),
            namespace_ref=str(kwargs["namespace_ref"]),
            workflow_id=str(kwargs["workflow_id"]),
            request_sha256=self.request_sha256,
            provider_run_id=self.history.provider_run_id,
        )

    async def observe_workflow_history(
        self, **_kwargs: Any
    ) -> TemporalProviderWorkflowHistoryObservation:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.mode == "network-failure":
            raise TemporalAdapterError("simulated Temporal network outage")
        return self.history


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value.model_dump(mode="json"), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _spawn_child(
    database_url: str,
    *,
    worker_id: str,
    mode: str,
    delay_seconds: float,
    history_path: Path,
    request_sha256: str,
    tenant_id: str,
    namespace_ref: str,
    workflow_id: str,
    status_file: Path,
) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "data_agent.agentops_temporal_discovery_worker_postgres_rehearsal",
            "--child",
            "--database-url",
            database_url,
            "--worker-id",
            worker_id,
            "--mode",
            mode,
            "--delay-seconds",
            str(delay_seconds),
            "--history",
            str(history_path),
            "--request-sha256",
            request_sha256,
            "--tenant-id",
            tenant_id,
            "--namespace-ref",
            namespace_ref,
            "--workflow-id",
            workflow_id,
            "--status-file",
            str(status_file),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_claim(
    authority: PostgresAgentOpsTemporalStartTargetAuthority,
    *,
    tenant_id: str,
    workflow_id: str,
    worker_id: str,
    timeout_seconds: float = 15,
) -> TemporalStartTarget:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        target = authority.target_for_workflow(
            tenant_id=tenant_id, workflow_id=workflow_id
        )
        if (
            target is not None
            and target.status == AgentOpsTemporalStartTargetStatus.CLAIMED
            and target.claimed_by == worker_id
        ):
            return target
        time.sleep(0.1)
    raise RuntimeError(f"discovery worker {worker_id} did not acquire target lease")


def _wait_for_target(
    authority: PostgresAgentOpsTemporalStartTargetAuthority,
    *,
    tenant_id: str,
    workflow_id: str,
    predicate: Any,
    timeout_seconds: float = 15,
) -> TemporalStartTarget:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        target = authority.target_for_workflow(
            tenant_id=tenant_id, workflow_id=workflow_id
        )
        if target is not None and predicate(target):
            return target
        time.sleep(0.1)
    raise RuntimeError("discovery target did not reach expected state")


def _wait_process(
    process: subprocess.Popen[str], timeout_seconds: float = 20
) -> tuple[int, str, str]:
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"discovery worker process did not exit: stdout={stdout!r} stderr={stderr!r}"
        ) from exc
    return int(process.returncode), stdout, stderr


def _cycle_from_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        cycle = value.get("cycle")
        if isinstance(cycle, dict):
            return cycle
    raise RuntimeError(f"discovery worker did not emit a cycle: {stdout!r}")


def _stale_rejected(operation: Any) -> bool:
    try:
        operation()
    except AgentOpsTemporalCheckpointAuthorityConflictError:
        return True
    return False


def run_agentops_temporal_discovery_worker_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    checkpoint = _checkpoint()
    history = _observation()
    request = build_temporal_start_request(checkpoint.workflow_input)
    result = _start_result(checkpoint.workflow_input)
    pending = TemporalWorkflowAdapter(object()).reconcile_start(
        checkpoint.workflow_input, result
    )
    tenant_id = request.tenant_id
    namespace_ref = request.namespace_ref
    workflow_id = request.workflow_id
    worker_a_pid = -1
    worker_a_exit_code = -1
    worker_b_failure_exit_code = -1
    worker_b_recovery_exit_code = -1
    heartbeat_observed_renewals = 0
    final_attempt_count = 0
    reconciliation_count = 0

    with tempfile.TemporaryDirectory(prefix="gda-agentops-discovery-") as directory:
        root = Path(directory)
        history_path = root / "history.json"
        _write_json(history_path, history)
        status_a = root / "status-a.json"
        status_failure = root / "status-b-failure.json"
        status_b = root / "status-b.json"
        status_health = root / "status-health.json"

        with _temporary_postgres(admin_url) as sandbox:
            if sandbox.runtime_engine is None or sandbox.database_url is None:
                raise RuntimeError("temporary PostgreSQL runtime was not initialized")
            with sandbox.admin_connection() as connection:
                _execute_migration(
                    connection,
                    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION.read_text(
                        encoding="utf-8"
                    ),
                )
            runtime_url = sandbox.database_url.set(
                username=sandbox.role, password=sandbox.password
            ).render_as_string(hide_password=False)
            target_authority = PostgresAgentOpsTemporalStartTargetAuthority(
                sandbox.runtime_engine
            )
            checkpoint_authority = PostgresAgentOpsTemporalCheckpointAuthority(
                sandbox.runtime_engine
            )
            checkpoint_authority.record_checkpoint(
                checkpoint, recorded_by="workload:discovery-worker-bootstrap"
            )
            with sandbox.admin_connection() as connection:
                for migration in _FENCED_MIGRATIONS:
                    _execute_migration(connection, migration.read_text(encoding="utf-8"))
            target_authority.register_start_target(
                request,
                result,
                pending,
                registered_by="workload:temporal-start-gateway",
            )

            child_a = _spawn_child(
                runtime_url,
                worker_id=_WORKER_A,
                mode="normal",
                delay_seconds=60,
                history_path=history_path,
                request_sha256=request.payload_sha256,
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status_file=status_a,
            )
            worker_a_pid = child_a.pid
            claimed_a = _wait_for_claim(
                target_authority,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                worker_id=_WORKER_A,
            )
            initial_expiry = claimed_a.claimed_until
            if initial_expiry is None:
                raise RuntimeError("worker A claim has no expiry")
            renewal_deadline = time.monotonic() + _LEASE_SECONDS + 1
            renewed_a = claimed_a
            while time.monotonic() < renewal_deadline:
                current = target_authority.target_for_workflow(
                    tenant_id=tenant_id, workflow_id=workflow_id
                )
                if current is not None and current.updated_at > claimed_a.updated_at:
                    renewed_a = current
                    heartbeat_observed_renewals += 1
                    if current.claimed_until and current.claimed_until > initial_expiry:
                        break
                time.sleep(0.1)
            check(
                "worker_a_heartbeat_renews_target_claim",
                heartbeat_observed_renewals >= 1
                and renewed_a.claimed_by == _WORKER_A
                and renewed_a.claimed_until is not None
                and renewed_a.claimed_until > initial_expiry,
                "worker A did not renew its discovery target lease",
            )

            stale_snapshot = target_authority.target_for_workflow(
                tenant_id=tenant_id, workflow_id=workflow_id
            )
            if stale_snapshot is None:
                raise RuntimeError("worker A target snapshot disappeared")
            os.kill(child_a.pid, signal.SIGKILL)
            worker_a_exit_code = child_a.wait(timeout=10)
            check(
                "worker_a_sigkill_is_observed",
                worker_a_exit_code == -signal.SIGKILL,
                "worker A did not terminate via SIGKILL",
            )

            health_observer = _RehearsalObserver(
                history, request.payload_sha256, mode="frontend-outage"
            )
            health_store = AgentOpsTemporalReconcilerDiscoveryStatusStore(status_health)
            health_worker = AgentOpsTemporalReconcilerDiscoveryWorker(
                AgentOpsTemporalReconcilerDiscoveryConfig(
                    tenant_id=tenant_id,
                    namespace_ref=namespace_ref,
                    worker_id=_WORKER_HEALTH,
                    lease_seconds=_LEASE_SECONDS,
                    heartbeat_interval_seconds=_HEARTBEAT_SECONDS,
                    observation_timeout_seconds=2,
                    claim_limit=1,
                    poll_interval_seconds=_POLL_SECONDS,
                    status_file=status_health,
                ),
                provider=health_observer,
                target_authority=target_authority,
                checkpoint_authority=checkpoint_authority,
                status_store=health_store,
            )
            try:
                asyncio.run(health_worker.run_once())
            except TemporalAdapterError:
                pass
            degraded = health_store.read()
            health_target = target_authority.target_for_workflow(
                tenant_id=tenant_id, workflow_id=workflow_id
            )
            check(
                "frontend_health_failure_degrades_readiness_without_claim",
                degraded.state == "degraded"
                and degraded.frontend_reachable is False
                and degraded.last_success_at is None
                and health_target is not None
                and health_target.status == AgentOpsTemporalStartTargetStatus.CLAIMED
                and health_target.claimed_by == _WORKER_A,
                "frontend outage did not degrade readiness or avoid target claim",
            )
            health_observer.mode = "normal"
            recovered_cycle = asyncio.run(health_worker.run_once())
            healthy = health_store.read()
            check(
                "frontend_health_recovery_allows_next_cycle",
                recovered_cycle.claimed_count == 0
                and healthy.state == "ready"
                and healthy.frontend_reachable is True
                and healthy.last_success_at is not None,
                "discovery worker did not recover readiness after frontend health returned",
            )

            competing = target_authority.claim_due_targets(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                worker_id=_WORKER_B,
                lease_seconds=_LEASE_SECONDS,
            )
            check(
                "worker_b_cannot_claim_live_post_kill_lease",
                not competing,
                "worker B claimed while worker A lease was still live",
            )

            remaining = (
                (renewed_a.claimed_until - datetime.now(UTC)).total_seconds()
                if renewed_a.claimed_until
                else 0
            )
            if remaining > 0:
                time.sleep(remaining + 0.25)

            child_b_failure = _spawn_child(
                runtime_url,
                worker_id=_WORKER_B_FAILURE,
                mode="network-failure",
                delay_seconds=0.1,
                history_path=history_path,
                request_sha256=request.payload_sha256,
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status_file=status_failure,
            )
            worker_b_failure_exit_code, failure_stdout, failure_stderr = _wait_process(
                child_b_failure
            )
            failure_cycle = _cycle_from_stdout(failure_stdout)
            released = _wait_for_target(
                target_authority,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                predicate=lambda target: target.status
                == AgentOpsTemporalStartTargetStatus.PENDING_START_RECONCILIATION
                and target.claimed_by is None
                and target.provider_run_id is None,
            )
            check(
                "worker_b_network_failure_releases_target",
                worker_b_failure_exit_code == 0
                and failure_cycle.get("claimed_count") == 1
                and failure_cycle.get("pending_count") == 1
                and bool(released.last_error)
                and "simulated Temporal network outage" in str(released.last_error),
                f"network failure was not safely released: stderr={failure_stderr!r}",
            )

            child_b = _spawn_child(
                runtime_url,
                worker_id=_WORKER_B,
                mode="normal",
                delay_seconds=0.1,
                history_path=history_path,
                request_sha256=request.payload_sha256,
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status_file=status_b,
            )
            worker_b_recovery_exit_code, recovery_stdout, recovery_stderr = _wait_process(
                child_b
            )
            recovery_cycle = _cycle_from_stdout(recovery_stdout)
            completed = _wait_for_target(
                target_authority,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                predicate=lambda target: target.status
                == AgentOpsTemporalStartTargetStatus.COMPLETED,
            )
            final_attempt_count = completed.attempt_count
            reconciliation_count = len(
                checkpoint_authority.reconciliation_history(
                    tenant_id=tenant_id, workflow_id=workflow_id
                )
            )
            check(
                "worker_b_recovery_completes_once",
                worker_b_recovery_exit_code == 0
                and recovery_cycle.get("claimed_count") == 1
                and recovery_cycle.get("completed_count") == 1
                and completed.provider_run_id == history.provider_run_id
                and reconciliation_count == 1,
                f"worker B did not complete recovered target: stderr={recovery_stderr!r}",
            )
            check(
                "target_attempt_count_tracks_takeover_and_retry",
                final_attempt_count == 3,
                "expected three target attempts "
                f"(A, failed B, recovered B), got {final_attempt_count}",
            )

            input_observation = _input_observation(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                request_sha256=request.payload_sha256,
                provider_run_id=history.provider_run_id,
            )
            check(
                "stale_worker_attach_is_fenced",
                _stale_rejected(
                    lambda: target_authority.attach_provider_run(
                        stale_snapshot, input_observation, worker_id=_WORKER_A
                    )
                ),
                "stale worker attached a provider run after takeover",
            )
            check(
                "stale_worker_release_is_fenced",
                _stale_rejected(
                    lambda: target_authority.release_target_claim(
                        stale_snapshot,
                        worker_id=_WORKER_A,
                        error="stale release probe",
                    )
                ),
                "stale worker released a target after takeover",
            )
            check(
                "stale_worker_complete_is_fenced",
                _stale_rejected(
                    lambda: target_authority.complete_target(
                        stale_snapshot, worker_id=_WORKER_A
                    )
                ),
                "stale worker completed a target after takeover",
            )

    payload = {
        "schema_id": "gda.agentops-temporal-discovery-worker-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "process_scope": "two_independent_discovery_worker_processes",
        "migration_ids": ("092", "094", "240", "241", "242"),
        "lease_seconds": _LEASE_SECONDS,
        "worker_a_pid": worker_a_pid,
        "worker_a_exit_code": worker_a_exit_code,
        "worker_b_failure_exit_code": worker_b_failure_exit_code,
        "worker_b_recovery_exit_code": worker_b_recovery_exit_code,
        "heartbeat_observed_renewals": heartbeat_observed_renewals,
        "final_attempt_count": final_attempt_count,
        "reconciliation_count": reconciliation_count,
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_agentops_temporal_discovery_worker_postgres_rehearsal_report(
    report: AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport,
    output_path: str | Path,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


def _run_child(args: argparse.Namespace) -> int:
    history = TemporalProviderWorkflowHistoryObservation.model_validate(
        json.loads(Path(args.history).read_text(encoding="utf-8"))
    )
    engine = create_engine(args.database_url)
    observer = _RehearsalObserver(
        history,
        args.request_sha256,
        mode=args.mode,
        delay_seconds=args.delay_seconds,
    )
    config = AgentOpsTemporalReconcilerDiscoveryConfig(
        tenant_id=args.tenant_id,
        namespace_ref=args.namespace_ref,
        worker_id=args.worker_id,
        lease_seconds=_LEASE_SECONDS,
        heartbeat_interval_seconds=_HEARTBEAT_SECONDS,
        observation_timeout_seconds=120 if args.delay_seconds > 1 else 10,
        claim_limit=1,
        poll_interval_seconds=_POLL_SECONDS,
        status_file=Path(args.status_file),
    )
    try:
        worker = AgentOpsTemporalReconcilerDiscoveryWorker(
            config,
            provider=observer,
            target_authority=PostgresAgentOpsTemporalStartTargetAuthority(engine),
            checkpoint_authority=PostgresAgentOpsTemporalCheckpointAuthority(engine),
        )
        cycle = asyncio.run(worker.run_once())
        print(json.dumps({"cycle": cycle.__dict__}, sort_keys=True))
        return 0
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse discovery worker failover")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-id")
    parser.add_argument(
        "--mode",
        choices=("normal", "network-failure", "frontend-outage"),
        default="normal",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--request-sha256")
    parser.add_argument("--tenant-id")
    parser.add_argument("--namespace-ref")
    parser.add_argument("--workflow-id")
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()
    if args.child:
        required = (
            args.database_url,
            args.worker_id,
            args.history,
            args.request_sha256,
            args.tenant_id,
            args.namespace_ref,
            args.workflow_id,
            args.status_file,
        )
        if any(value is None for value in required):
            parser.error("child mode requires database, worker, history and target arguments")
        return _run_child(args)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_agentops_temporal_discovery_worker_postgres_rehearsal(args.database_url)
    if args.output:
        write_agentops_temporal_discovery_worker_postgres_rehearsal_report(report, args.output)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport",
    "run_agentops_temporal_discovery_worker_postgres_rehearsal",
    "write_agentops_temporal_discovery_worker_postgres_rehearsal_report",
]
