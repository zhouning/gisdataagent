"""Disposable PostgreSQL rehearsal for AgentOps reconciler fencing and crash recovery."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from .agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityConflictError,
    AgentOpsTemporalCheckpointAuthorityForbiddenError,
    PostgresAgentOpsTemporalCheckpointAuthority,
    _fingerprint_payload,
    _json,
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
_WORKER_A = "workload:agentops-reconciler-a"
_WORKER_B = "workload:agentops-reconciler-b"
_OTHER_TENANT = "agentops-fencing-other"
_CRASH_BEFORE_COMMIT = 71
_CRASH_AFTER_COMMIT = 72


class AgentOpsTemporalReconcilerFencingPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-reconciler-fencing-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    source_evidence_prefix: str
    lease_epoch_sequence: tuple[int, ...]
    checkpoint_count: int
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
    ) -> AgentOpsTemporalReconcilerFencingPostgresRehearsalReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("AgentOps fencing rehearsal report hash is invalid")
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


_FENCED_CHECKPOINT_SQL = text(
    """
    SELECT checkpoint_document, checkpoint_sequence, created
    FROM gda_control.record_agentops_temporal_checkpoint_fenced(
        :tenant_id, :workflow_id, :previous_checkpoint_sha256,
        CAST(:checkpoint_document AS jsonb), :fingerprint_payload,
        :recorded_by, :lease_owner, :lease_epoch
    )
    """
)


def _checkpoint_parameters(
    checkpoint: TemporalTaskGraphWorkflowCheckpoint,
    *,
    lease_owner: str,
    lease_epoch: int,
    previous_checkpoint_sha256: str | None,
) -> dict[str, Any]:
    document = checkpoint.model_dump(mode="json")
    return {
        "tenant_id": checkpoint.workflow_input.tenant_id,
        "workflow_id": checkpoint.workflow_input.identity.workflow_id,
        "previous_checkpoint_sha256": previous_checkpoint_sha256,
        "checkpoint_document": _json(document),
        "fingerprint_payload": _fingerprint_payload(
            checkpoint.schema_id, document, "checkpoint_sha256"
        ),
        "recorded_by": lease_owner,
        "lease_owner": lease_owner,
        "lease_epoch": lease_epoch,
    }


def _crash_child(
    *,
    database_url: str,
    checkpoint_suffix: str,
    lease_owner: str,
    lease_epoch: int,
    previous_checkpoint_sha256: str | None,
    crash_mode: str,
) -> int:
    checkpoint = TemporalTaskGraphWorkflowCheckpoint.model_validate(
        _load(checkpoint_suffix)
    )
    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
    connection.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": checkpoint.workflow_input.tenant_id},
    )
    connection.execute(
        _FENCED_CHECKPOINT_SQL,
        _checkpoint_parameters(
            checkpoint,
            lease_owner=lease_owner,
            lease_epoch=lease_epoch,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        ),
    ).one()
    if crash_mode == "before_commit":
        os._exit(_CRASH_BEFORE_COMMIT)
    transaction.commit()
    os._exit(_CRASH_AFTER_COMMIT)


def _run_crash_process(
    *,
    database_url: str,
    checkpoint_suffix: str,
    lease_owner: str,
    lease_epoch: int,
    previous_checkpoint_sha256: str | None,
    crash_mode: str,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "data_agent.agentops_temporal_reconciler_fencing_postgres_rehearsal",
        "--crash-mode",
        crash_mode,
        "--checkpoint-suffix",
        checkpoint_suffix,
        "--lease-owner",
        lease_owner,
        "--lease-epoch",
        str(lease_epoch),
    ]
    if previous_checkpoint_sha256 is not None:
        command.extend(
            ["--previous-checkpoint-sha256", previous_checkpoint_sha256]
        )
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def run_agentops_temporal_reconciler_fencing_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsTemporalReconcilerFencingPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, failure: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(failure)

    before = TemporalTaskGraphWorkflowCheckpoint.model_validate(
        _load("checkpoint_before")
    )
    after = TemporalTaskGraphWorkflowCheckpoint.model_validate(_load("checkpoint_after"))
    observation = TemporalProviderWorkflowHistoryObservation.model_validate(
        _load("observation")
    )
    checkpoint_behind = TemporalCheckpointReconciliation.model_validate(
        _load("checkpoint_behind")
    )
    matched = TemporalCheckpointReconciliation.model_validate(_load("matched"))
    tenant = before.workflow_input.tenant_id
    workflow_id = before.workflow_input.identity.workflow_id
    epochs: tuple[int, ...] = ()
    checkpoint_count = 0
    reconciliation_count = 0

    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None or sandbox.database_url is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            for migration in (
                AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
                AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
            ):
                _execute_migration(
                    connection,
                    migration.read_text(encoding="utf-8"),
                )

        authority = PostgresAgentOpsTemporalCheckpointAuthority(sandbox.runtime_engine)
        lease_a = authority.acquire_reconciler_lease(
            tenant_id=tenant,
            workflow_id=workflow_id,
            lease_owner=_WORKER_A,
            lease_seconds=3,
        )
        lease_a_replay = authority.acquire_reconciler_lease(
            tenant_id=tenant,
            workflow_id=workflow_id,
            lease_owner=_WORKER_A,
            lease_seconds=3,
        )
        check(
            "same_worker_acquire_reuses_epoch",
            lease_a.lease_epoch == 1
            and lease_a_replay.lease_epoch == lease_a.lease_epoch
            and lease_a_replay.lease_expires_at >= lease_a.lease_expires_at,
            "same worker did not recover the active lease epoch",
        )
        try:
            authority.acquire_reconciler_lease(
                tenant_id=tenant,
                workflow_id=workflow_id,
                lease_owner=_WORKER_B,
                lease_seconds=30,
            )
            competing_worker_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            competing_worker_rejected = True
        check(
            "active_lease_rejects_competing_worker",
            competing_worker_rejected,
            "a second worker acquired an active workflow lease",
        )

        runtime_url = sandbox.database_url.set(
            username=sandbox.role,
            password=sandbox.password,
        ).render_as_string(hide_password=False)
        before_commit = _run_crash_process(
            database_url=runtime_url,
            checkpoint_suffix="checkpoint_before",
            lease_owner=lease_a.lease_owner,
            lease_epoch=lease_a.lease_epoch,
            previous_checkpoint_sha256=None,
            crash_mode="before_commit",
        )
        unresolved = authority.resolve_checkpoint_write(before)
        check(
            "process_exit_before_commit_rolls_back_write_and_binding",
            before_commit.returncode == _CRASH_BEFORE_COMMIT
            and unresolved is None
            and authority.current_checkpoint(
                tenant_id=tenant, workflow_id=workflow_id
            )
            is None,
            "pre-commit process exit left a checkpoint or fencing binding",
        )

        after_commit = _run_crash_process(
            database_url=runtime_url,
            checkpoint_suffix="checkpoint_before",
            lease_owner=lease_a.lease_owner,
            lease_epoch=lease_a.lease_epoch,
            previous_checkpoint_sha256=None,
            crash_mode="after_commit",
        )
        recovered_before = authority.resolve_checkpoint_write(before)
        check(
            "process_exit_after_commit_is_resolved_without_rewrite",
            after_commit.returncode == _CRASH_AFTER_COMMIT
            and recovered_before is not None
            and recovered_before.checkpoint_sequence == 1
            and recovered_before.binding.lease_owner == _WORKER_A
            and recovered_before.binding.lease_epoch == 1,
            "post-commit process exit could not be resolved by exact fenced evidence",
        )

        remaining = (lease_a_replay.lease_expires_at - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            time.sleep(remaining + 0.1)
        lease_b = authority.acquire_reconciler_lease(
            tenant_id=tenant,
            workflow_id=workflow_id,
            lease_owner=_WORKER_B,
            lease_seconds=30,
        )
        epochs = (lease_a.lease_epoch, lease_b.lease_epoch)
        check(
            "expired_worker_takeover_increments_fencing_epoch",
            epochs == (1, 2),
            "lease takeover did not increment the fencing epoch",
        )

        try:
            authority.record_checkpoint(
                after,
                previous_checkpoint_sha256=before.checkpoint_sha256,
                recorded_by=lease_a.lease_owner,
                lease=lease_a,
            )
            stale_worker_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            stale_worker_rejected = True
        check(
            "stale_worker_is_fenced_before_checkpoint_write",
            stale_worker_rejected,
            "expired worker wrote after a new fencing epoch was issued",
        )

        second = authority.record_checkpoint(
            after,
            previous_checkpoint_sha256=before.checkpoint_sha256,
            recorded_by=lease_b.lease_owner,
            lease=lease_b,
        )
        recovered_after = authority.resolve_checkpoint_write(after)
        check(
            "takeover_worker_writes_next_checkpoint_with_new_epoch",
            second.created
            and second.checkpoint_sequence == 2
            and recovered_after is not None
            and recovered_after.binding.lease_epoch == 2
            and recovered_after.binding.lease_owner == _WORKER_B,
            "takeover worker checkpoint was not bound to epoch 2",
        )

        lag_write = authority.record_reconciliation(
            observation,
            checkpoint_behind,
            recorded_by=lease_b.lease_owner,
            lease=lease_b,
        )
        matched_write = authority.record_reconciliation(
            observation,
            matched,
            recorded_by=lease_b.lease_owner,
            lease=lease_b,
        )
        matched_replay = authority.record_reconciliation(
            observation,
            matched,
            recorded_by=lease_b.lease_owner,
            lease=lease_b,
        )
        recovered_matched = authority.resolve_reconciliation_write(
            observation, matched
        )
        check(
            "reconciliation_chain_is_fenced_and_idempotent",
            lag_write.created
            and matched_write.created
            and not matched_replay.created
            and recovered_matched is not None
            and recovered_matched.binding.lease_epoch == 2
            and recovered_matched.binding.lease_owner == _WORKER_B,
            "reconciliation evidence or fencing binding is incorrect",
        )

        try:
            authority.record_checkpoint(
                after,
                previous_checkpoint_sha256=before.checkpoint_sha256,
                recorded_by=_WORKER_B,
            )
            unfenced_gateway_write_rejected = False
        except AgentOpsTemporalCheckpointAuthorityForbiddenError:
            unfenced_gateway_write_rejected = True
        check(
            "migration_revokes_unfenced_gateway_write",
            unfenced_gateway_write_rejected,
            "gateway could still invoke the old unfenced checkpoint function",
        )

        renewed_b = authority.renew_reconciler_lease(lease_b, lease_seconds=30)
        released_b = authority.release_reconciler_lease(renewed_b)
        check(
            "lease_renew_and_release_preserve_epoch",
            renewed_b.lease_epoch == 2
            and renewed_b.lease_expires_at >= lease_b.lease_expires_at
            and released_b.lease_epoch == 2
            and released_b.lease_expires_at <= datetime.now(UTC),
            "lease renew or release changed epoch or remained active",
        )

        try:
            authority.record_reconciliation(
                observation,
                matched,
                recorded_by=released_b.lease_owner,
                lease=released_b,
            )
            released_lease_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            released_lease_rejected = True
        check(
            "released_lease_cannot_replay_write",
            released_lease_rejected,
            "released lease could still invoke a fenced write",
        )

        check(
            "cross_tenant_lease_and_recovery_are_hidden",
            authority.current_reconciler_lease(
                tenant_id=_OTHER_TENANT, workflow_id=workflow_id
            )
            is None
            and authority.current_checkpoint(
                tenant_id=_OTHER_TENANT, workflow_id=workflow_id
            )
            is None,
            "RLS exposed lease or recovery state across tenants",
        )

        try:
            with sandbox.runtime_engine.begin() as connection:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant},
                )
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.agentops_temporal_reconciler_lease
                        SET lease_epoch = lease_epoch + 1
                        WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
                        """
                    ),
                    {"tenant_id": tenant, "workflow_id": workflow_id},
                )
            direct_lease_mutation_rejected = False
        except DBAPIError as exc:
            direct_lease_mutation_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_direct_lease_mutation_is_denied",
            direct_lease_mutation_rejected,
            "gateway retained direct UPDATE on reconciler lease",
        )

        mutation_checks: list[bool] = []
        for statement in (
            """
            UPDATE gda_control.agentops_temporal_checkpoint_lease_binding
            SET lease_epoch = lease_epoch WHERE tenant_id = :tenant_id
            """,
            """
            DELETE FROM gda_control.agentops_temporal_reconciliation_lease_binding
            WHERE tenant_id = :tenant_id
            """,
        ):
            try:
                with sandbox.admin_connection() as connection:
                    connection.execute(text(statement), {"tenant_id": tenant})
                mutation_checks.append(False)
            except DBAPIError as exc:
                mutation_checks.append(_sqlstate(exc) == "55000")
        check(
            "fencing_bindings_are_immutable",
            all(mutation_checks),
            "checkpoint or reconciliation fencing binding accepted mutation",
        )

        checkpoint_count = len(
            authority.checkpoint_history(
                tenant_id=tenant, workflow_id=workflow_id
            )
        )
        reconciliation_count = len(
            authority.reconciliation_history(
                tenant_id=tenant, workflow_id=workflow_id
            )
        )

    payload = {
        "schema_id": "gda.agentops-temporal-reconciler-fencing-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "migration_ids": ("092", "094", "169", "240", "241"),
        "source_evidence_prefix": _PREFIX,
        "lease_epoch_sequence": epochs,
        "checkpoint_count": checkpoint_count,
        "reconciliation_count": reconciliation_count,
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return AgentOpsTemporalReconcilerFencingPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_agentops_temporal_reconciler_fencing_postgres_rehearsal_report(
    report: AgentOpsTemporalReconcilerFencingPostgresRehearsalReport,
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
        description="Rehearse AgentOps reconciler fencing in temporary PostgreSQL"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL URL; parent mode creates and removes a temporary database",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--crash-mode", choices=("before_commit", "after_commit")
    )
    parser.add_argument("--checkpoint-suffix")
    parser.add_argument("--lease-owner")
    parser.add_argument("--lease-epoch", type=int)
    parser.add_argument("--previous-checkpoint-sha256")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.crash_mode:
        if (
            not args.checkpoint_suffix
            or not args.lease_owner
            or args.lease_epoch is None
        ):
            parser.error("crash mode requires checkpoint, lease owner, and epoch")
        return _crash_child(
            database_url=args.database_url,
            checkpoint_suffix=args.checkpoint_suffix,
            lease_owner=args.lease_owner,
            lease_epoch=args.lease_epoch,
            previous_checkpoint_sha256=args.previous_checkpoint_sha256,
            crash_mode=args.crash_mode,
        )
    report = run_agentops_temporal_reconciler_fencing_postgres_rehearsal(
        args.database_url
    )
    if args.output:
        write_agentops_temporal_reconciler_fencing_postgres_rehearsal_report(
            report, args.output
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalReconcilerFencingPostgresRehearsalReport",
    "run_agentops_temporal_reconciler_fencing_postgres_rehearsal",
    "write_agentops_temporal_reconciler_fencing_postgres_rehearsal_report",
]
