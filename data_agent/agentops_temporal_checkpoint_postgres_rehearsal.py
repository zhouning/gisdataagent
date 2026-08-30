"""Disposable PostgreSQL rehearsal for the AgentOps Temporal checkpoint authority."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from .agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityConflictError,
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
_RECORDED_BY = "workload:agentops-checkpoint-authority-rehearsal"
_OTHER_TENANT = "agentops-other"


class AgentOpsTemporalCheckpointPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.agentops-temporal-checkpoint-postgres-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    source_evidence_prefix: str
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
    ) -> AgentOpsTemporalCheckpointPostgresRehearsalReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("AgentOps checkpoint rehearsal report hash is invalid")
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


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


_CHECKPOINT_SQL = text(
    """
    SELECT checkpoint_document, checkpoint_sequence, created
    FROM gda_control.record_agentops_temporal_checkpoint(
        :tenant_id, :workflow_id, :previous_checkpoint_sha256,
        CAST(:checkpoint_document AS jsonb), :fingerprint_payload, :recorded_by
    )
    """
)


def run_agentops_temporal_checkpoint_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsTemporalCheckpointPostgresRehearsalReport:
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
    reconciliation = TemporalCheckpointReconciliation.model_validate(_load("matched"))
    checkpoint_behind = TemporalCheckpointReconciliation.model_validate(
        _load("checkpoint_behind")
    )
    tenant = before.workflow_input.tenant_id
    workflow_id = before.workflow_input.identity.workflow_id
    checkpoint_count = 0
    reconciliation_count = 0

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

        authority = PostgresAgentOpsTemporalCheckpointAuthority(sandbox.runtime_engine)
        first = authority.record_checkpoint(before, recorded_by=_RECORDED_BY)
        replay = authority.record_checkpoint(before, recorded_by=_RECORDED_BY)
        check(
            "checkpoint_replay_is_idempotent",
            first.created
            and first.checkpoint_sequence == 1
            and not replay.created
            and replay.checkpoint == before,
            "same checkpoint did not replay idempotently",
        )
        try:
            authority.record_checkpoint(
                before,
                recorded_by="workload:different-checkpoint-writer",
            )
            checkpoint_actor_drift_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            checkpoint_actor_drift_rejected = True
        check(
            "checkpoint_same_id_actor_drift_is_rejected",
            checkpoint_actor_drift_rejected,
            "same checkpoint identity accepted a different audit actor",
        )

        try:
            authority.record_checkpoint(
                after,
                previous_checkpoint_sha256="9" * 64,
                recorded_by=_RECORDED_BY,
            )
            stale_predecessor_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            stale_predecessor_rejected = True
        check(
            "stale_predecessor_is_rejected",
            stale_predecessor_rejected,
            "stale checkpoint predecessor was accepted",
        )

        second = authority.record_checkpoint(
            after,
            previous_checkpoint_sha256=before.checkpoint_sha256,
            recorded_by=_RECORDED_BY,
        )
        history = authority.checkpoint_history(
            tenant_id=tenant,
            workflow_id=workflow_id,
        )
        check(
            "checkpoint_chain_is_append_only_and_current_is_exact",
            second.created
            and second.checkpoint_sequence == 2
            and history == (before, after)
            and authority.current_checkpoint(
                tenant_id=tenant, workflow_id=workflow_id
            )
            == after,
            "checkpoint history or current projection differs",
        )

        lag_evidence = authority.record_reconciliation(
            observation,
            checkpoint_behind,
            recorded_by=_RECORDED_BY,
        )
        check(
            "checkpoint_behind_evidence_is_persisted",
            lag_evidence.created
            and lag_evidence.evidence.reconciliation.verdict.value
            == "checkpoint_behind",
            "checkpoint-behind evidence was not persisted",
        )

        evidence = authority.record_reconciliation(
            observation,
            reconciliation,
            recorded_by=_RECORDED_BY,
        )
        evidence_replay = authority.record_reconciliation(
            observation,
            reconciliation,
            recorded_by=_RECORDED_BY,
        )
        check(
            "reconciliation_replay_is_idempotent",
            evidence.created
            and not evidence_replay.created
            and evidence.evidence.observation == observation
            and evidence.evidence.reconciliation == reconciliation,
            "same reconciliation evidence did not replay idempotently",
        )
        try:
            authority.record_reconciliation(
                observation,
                reconciliation,
                recorded_by="workload:different-reconciler",
            )
            reconciliation_actor_drift_rejected = False
        except AgentOpsTemporalCheckpointAuthorityConflictError:
            reconciliation_actor_drift_rejected = True
        check(
            "reconciliation_same_id_actor_drift_is_rejected",
            reconciliation_actor_drift_rejected,
            "same reconciliation identity accepted a different audit actor",
        )

        runtime_url = sandbox.database_url.set(
            username=sandbox.role,
            password=sandbox.password,
        )
        restarted_engine = create_engine(runtime_url)
        try:
            restarted = PostgresAgentOpsTemporalCheckpointAuthority(restarted_engine)
            recovered_checkpoint = restarted.current_checkpoint(
                tenant_id=tenant, workflow_id=workflow_id
            )
            recovered_evidence = restarted.reconciliation_history(
                tenant_id=tenant, workflow_id=workflow_id
            )
        finally:
            restarted_engine.dispose()
        checkpoint_count = len(history)
        reconciliation_count = len(recovered_evidence)
        check(
            "new_repository_instance_recovers_typed_state",
            recovered_checkpoint == after
            and len(recovered_evidence) == 2
            and tuple(
                item.reconciliation.verdict.value for item in recovered_evidence
            )
            == ("checkpoint_behind", "matched")
            and all(item.observation == observation for item in recovered_evidence),
            "new repository instance could not recover typed authority state",
        )

        child_environment = os.environ.copy()
        child_environment["DATABASE_URL"] = runtime_url.render_as_string(
            hide_password=False
        )
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "data_agent.agentops_temporal_checkpoint_postgres_rehearsal",
                "--readback-tenant",
                tenant,
                "--readback-workflow",
                workflow_id,
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            child_readback = json.loads(child.stdout)
        except json.JSONDecodeError:
            child_readback = {}
        check(
            "fresh_process_recovers_checkpoint_and_reconciliation_history",
            child.returncode == 0
            and child_readback
            == {
                "checkpoint_sha256": after.checkpoint_sha256,
                "checkpoint_count": 2,
                "reconciliation_sha256s": [
                    checkpoint_behind.reconciliation_sha256,
                    reconciliation.reconciliation_sha256,
                ],
            },
            "fresh Python process could not recover the exact typed authority state",
        )

        check(
            "cross_tenant_reads_are_hidden",
            authority.current_checkpoint(
                tenant_id=_OTHER_TENANT,
                workflow_id=workflow_id,
            )
            is None
            and authority.reconciliation_history(
                tenant_id=_OTHER_TENANT,
                workflow_id=workflow_id,
            )
            == (),
            "RLS exposed AgentOps authority state across tenants",
        )

        tampered = before.model_dump(mode="json")
        tampered["run"]["status"] = "failed"
        try:
            with sandbox.runtime_engine.begin() as connection:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant},
                )
                connection.execute(
                    _CHECKPOINT_SQL,
                    {
                        "tenant_id": tenant,
                        "workflow_id": workflow_id,
                        "previous_checkpoint_sha256": None,
                        "checkpoint_document": _json(tampered),
                        "fingerprint_payload": _fingerprint_payload(
                            before.schema_id,
                            before.model_dump(mode="json"),
                            "checkpoint_sha256",
                        ),
                        "recorded_by": _RECORDED_BY,
                    },
                ).one()
            tampered_hash_rejected = False
        except DBAPIError as exc:
            tampered_hash_rejected = _sqlstate(exc) == "22023"
        check(
            "tampered_document_with_old_hash_is_rejected_in_database",
            tampered_hash_rejected,
            "database accepted a tampered checkpoint with its old hash",
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
                        INSERT INTO gda_control.agentops_temporal_checkpoint_history
                        SELECT * FROM gda_control.agentops_temporal_checkpoint_history
                        WHERE FALSE
                        """
                    )
                )
            direct_insert_rejected = False
        except DBAPIError as exc:
            direct_insert_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_direct_insert_is_denied",
            direct_insert_rejected,
            "gateway retained direct INSERT permission",
        )

        mutation_checks: list[bool] = []
        for statement in (
            """
            UPDATE gda_control.agentops_temporal_checkpoint_history
            SET recorded_by = recorded_by WHERE tenant_id = :tenant_id
            """,
            """
            DELETE FROM gda_control.agentops_temporal_reconciliation_evidence
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
            "checkpoint_and_reconciliation_are_immutable",
            all(mutation_checks),
            "authority history accepted UPDATE or DELETE",
        )

    payload = {
        "schema_id": "gda.agentops-temporal-checkpoint-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "migration_ids": ("092", "094", "169", "240"),
        "source_evidence_prefix": _PREFIX,
        "checkpoint_count": checkpoint_count,
        "reconciliation_count": reconciliation_count,
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return AgentOpsTemporalCheckpointPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_agentops_temporal_checkpoint_postgres_rehearsal_report(
    report: AgentOpsTemporalCheckpointPostgresRehearsalReport,
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
        description="Rehearse AgentOps checkpoint persistence in temporary PostgreSQL"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL administrator URL used only to create a temporary database",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--readback-tenant")
    parser.add_argument("--readback-workflow")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.readback_tenant or args.readback_workflow:
        if not args.readback_tenant or not args.readback_workflow:
            parser.error("readback requires both tenant and workflow")
        engine = create_engine(args.database_url)
        try:
            authority = PostgresAgentOpsTemporalCheckpointAuthority(engine)
            current = authority.current_checkpoint(
                tenant_id=args.readback_tenant,
                workflow_id=args.readback_workflow,
            )
            checkpoints = authority.checkpoint_history(
                tenant_id=args.readback_tenant,
                workflow_id=args.readback_workflow,
            )
            reconciliations = authority.reconciliation_history(
                tenant_id=args.readback_tenant,
                workflow_id=args.readback_workflow,
            )
        finally:
            engine.dispose()
        if current is None:
            return 2
        print(
            json.dumps(
                {
                    "checkpoint_sha256": current.checkpoint_sha256,
                    "checkpoint_count": len(checkpoints),
                    "reconciliation_sha256s": [
                        item.reconciliation.reconciliation_sha256
                        for item in reconciliations
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    report = run_agentops_temporal_checkpoint_postgres_rehearsal(args.database_url)
    if args.output:
        write_agentops_temporal_checkpoint_postgres_rehearsal_report(
            report, args.output
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AgentOpsTemporalCheckpointPostgresRehearsalReport",
    "run_agentops_temporal_checkpoint_postgres_rehearsal",
    "write_agentops_temporal_checkpoint_postgres_rehearsal_report",
]
