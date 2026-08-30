"""Disposable PostgreSQL rehearsal for specialist operation receipt authority."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text

from .agentops_specialist_operation_authority import (
    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
    AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
    PostgresSpecialistOperationAuthority,
    SpecialistOperationAuthorityConflictError,
)
from .agentops_specialist_providers import (
    SpecialistOperationStatus,
)
from .cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint
from .test_agentops_specialist_operation_authority import _request

_MIGRATIONS = (
    Path(__file__).resolve().parent / "migrations" / "092_platform_control_ledger.sql",
    Path(__file__).resolve().parent / "migrations" / "094_platform_control_gateway.sql",
    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
    AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
)
_TENANT = "planning"
_OTHER_TENANT = "other-tenant"
_WORKLOAD = "workload:agentops-specialist-rehearsal"
_OPERATION = "gwm.render_canonical_observation.v1://postgres-rehearsal"
_RECEIPT = "provider://gwm/postgres-rehearsal"
_OUTPUT_ID = UUID("00000000-0000-4000-8000-000000002461")
_REPORT_SCHEMA = "gda.agentops-specialist-operation-authority-postgres-rehearsal.v1"


class AgentOpsSpecialistOperationAuthorityPostgresRehearsalReport(FrozenContract):
    schema_id: str = _REPORT_SCHEMA
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    production_readiness_claimed: bool = False
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash_matches(self) -> AgentOpsSpecialistOperationAuthorityPostgresRehearsalReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("specialist operation PostgreSQL rehearsal report hash is invalid")
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


def _insert_output_artifact(connection: Any, tenant_id: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO gda_control.artifact (
                tenant_id, artifact_id, artifact_key, artifact_role,
                storage_uri, media_type, content_sha256, size_bytes,
                run_id, resource_version_id, manifest, created_by
            ) VALUES (
                :tenant_id, :artifact_id, :artifact_key, 'output',
                :storage_uri, 'application/json', :content_sha256, 2,
                NULL, NULL, CAST(:manifest AS jsonb), :created_by
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "artifact_id": _OUTPUT_ID,
            "artifact_key": "agentops-specialist:postgres-rehearsal",
            "storage_uri": "s3://agentops-specialist-rehearsal/output.json",
            "content_sha256": "a" * 64,
            "manifest": json.dumps({"schema": "gda.test.output.v1"}),
            "created_by": _WORKLOAD,
        },
    )


def run_agentops_specialist_operation_authority_postgres_rehearsal(
    admin_url: str,
) -> AgentOpsSpecialistOperationAuthorityPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    request = _request(tenant_id=_TENANT)
    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None or sandbox.database_url is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            # Migration 246 fingerprints receipts with pgcrypto.digest.  This
            # rehearsal intentionally loads only the minimal control migrations,
            # so install the explicit extension prerequisite first.
            connection.exec_driver_sql(
                "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public"
            )
            for migration in _MIGRATIONS:
                _execute_migration(connection, migration.read_text(encoding="utf-8"))
            _insert_output_artifact(connection, _TENANT)

        authority = PostgresSpecialistOperationAuthority(
            _TENANT, sandbox.runtime_engine, recorded_by=_WORKLOAD
        )
        submitted = authority.submit(
            request,
            provider_ref="provider:gwm.local",
            operation_ref=_OPERATION,
            provider_receipt_ref=_RECEIPT,
        )
        replay = authority.submit(
            request,
            provider_ref="provider:gwm.local",
            operation_ref=_OPERATION,
            provider_receipt_ref=_RECEIPT,
        )
        check(
            "submit_replay_is_idempotent",
            submitted == replay and len(authority.history(_OPERATION)) == 1,
            "replaying a provider submission created a second receipt",
        )

        restarted = PostgresSpecialistOperationAuthority(
            _TENANT, sandbox.runtime_engine, recorded_by=_WORKLOAD
        )
        observed = restarted.observe(_OPERATION)
        check(
            "new_repository_recovers_submitted_receipt",
            observed is not None
            and observed.status is SpecialistOperationStatus.SUBMITTED
            and observed.operation_ref == _OPERATION,
            "a new authority instance could not recover the submitted receipt",
        )

        succeeded = authority.succeed(_OPERATION, _OUTPUT_ID)
        settled_replay = restarted.succeed(_OPERATION, _OUTPUT_ID)
        check(
            "terminal_success_is_cas_idempotent",
            succeeded == settled_replay
            and succeeded.status is SpecialistOperationStatus.SUCCEEDED
            and succeeded.output_artifact_id == _OUTPUT_ID
            and len(authority.history(_OPERATION)) == 2,
            "success transition was not durable or idempotent",
        )
        try:
            authority.fail(_OPERATION, "late_worker_failure")
            stale_rejected = False
        except SpecialistOperationAuthorityConflictError:
            stale_rejected = True
        check(
            "stale_failure_cannot_overwrite_terminal_success",
            stale_rejected,
            "a stale failure transition overwrote a terminal success",
        )

        cancellation_operation = _OPERATION + ":cancel"
        cancellation_receipt = authority.submit(
            request,
            provider_ref="provider:gwm.local",
            operation_ref=cancellation_operation,
            provider_receipt_ref=_RECEIPT + ":cancel",
        )
        pending = authority.request_cancellation(
            cancellation_operation,
            uncertainty_type="FlinkCancellationPermissionDenied",
        )
        pending_observation = restarted.observe(cancellation_operation)
        check(
            "cancellation_is_unknown_without_provider_terminal_observation",
            cancellation_receipt.status is SpecialistOperationStatus.SUBMITTED
            and pending.status is SpecialistOperationStatus.UNKNOWN
            and pending.cancellation_requested
            and pending.uncertainty_type == "FlinkCancellationPermissionDenied"
            and pending_observation is not None
            and pending_observation.status is SpecialistOperationStatus.UNKNOWN,
            "cancellation was incorrectly treated as a definitive provider failure",
        )
        reasoned_observation = restarted.observe(cancellation_operation)
        check(
            "cancellation_uncertainty_reason_is_durable",
            reasoned_observation is not None
            and reasoned_observation.uncertainty_type == "FlinkCancellationPermissionDenied",
            "cancellation uncertainty reason was not persisted or observed",
        )

        other = PostgresSpecialistOperationAuthority(
            _OTHER_TENANT, sandbox.runtime_engine, recorded_by=_WORKLOAD
        )
        check(
            "cross_tenant_receipt_is_not_visible",
            other.observe(_OPERATION) is None,
            "a receipt leaked across tenant RLS boundaries",
        )

    values: dict[str, Any] = {
        "checked_at": datetime.now(UTC),
        "migration_ids": tuple(path.name.split("_", 1)[0] for path in _MIGRATIONS),
        "checks": checks,
        "passed": not failures,
        "failure_reasons": tuple(failures),
    }
    values["report_sha256"] = _report_hash(
        {
            "schema_id": _REPORT_SCHEMA,
            "database_scope": "temporary_database_only",
            "production_readiness_claimed": False,
            **values,
        }
    )
    return AgentOpsSpecialistOperationAuthorityPostgresRehearsalReport(
        schema_id=_REPORT_SCHEMA,
        database_scope="temporary_database_only",
        production_readiness_claimed=False,
        **values,
    )


def write_agentops_specialist_operation_authority_postgres_rehearsal_report(
    report: AgentOpsSpecialistOperationAuthorityPostgresRehearsalReport,
    target: str | Path,
) -> Path:
    path = Path(target).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--report",
        default=str(
            Path(__file__).resolve().parents[1]
            / "docs"
            / "reports"
            / "agentops_specialist_operation_authority_postgres_2026-08-28.json"
        ),
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_agentops_specialist_operation_authority_postgres_rehearsal(
        args.database_url
    )
    target = write_agentops_specialist_operation_authority_postgres_rehearsal_report(
        report, args.report
    )
    print(json.dumps({"report": str(target), "passed": report.passed}, ensure_ascii=False))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
