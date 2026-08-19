"""Isolated PostgreSQL rehearsal for Chongqing reconciliation jobs."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url

from .chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJobCancelRequest,
    ChongqingDataPackageReconciliationJobRepository,
)
from .chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
)
from .chongqing_entity_link_baseline import build_chongqing_entity_link_baseline
from .platform_contracts import FrozenContract, canonical_json_fingerprint

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "160_bitemporal_entity_authority.sql",
    "161_entity_link_authority.sql",
    "162_entity_authority_batch_ingest.sql",
    "166_chongqing_data_package_reconciliation.sql",
    "167_chongqing_data_package_reconciliation_job.sql",
    "168_chongqing_data_package_reconciliation_cancel_race.sql",
)
_TENANT = "cq-postgres-rehearsal"
_ACTOR = "agent:postgres-rehearsal"


class ChongqingReconciliationPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.chongqing-reconciliation-postgres-rehearsal.v1"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprint_matches(self) -> ChongqingReconciliationPostgresRehearsalReport:
        expected = _report_hash(self.model_dump(mode="json"))
        if self.report_sha256 != expected:
            raise ValueError("PostgreSQL rehearsal report fingerprint is invalid")
        return self


def _report_hash(payload: dict[str, Any]) -> str:
    return canonical_json_fingerprint(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )


def _identifier(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if not value or any(char not in allowed for char in value):
        raise ValueError("unsafe SQL identifier")
    return '"' + value.replace('"', '""') + '"'


def _execute_migration(connection: Any, migration_sql: str) -> None:
    """Execute a complete migration through the PostgreSQL DB-API driver.

    ``exec_driver_sql`` treats percent signs as DB-API parameter markers for
    psycopg2. Several PostgreSQL migrations contain modulo operators and
    format strings, so escape percent signs before sending the complete
    multi-statement migration to the driver. The existing certification
    scripts use the same convention; unlike ``text()`` it preserves the
    migration's multi-statement execution semantics.
    """

    connection.exec_driver_sql(migration_sql.replace("%", "%%"))


class _TemporaryPostgres:
    def __init__(self, admin_url: str):
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_cq_rehearsal_{uuid4().hex[:12]}"
        self.role = f"gda_cq_rehearsal_{uuid4().hex[:12]}"
        self.password = uuid4().hex
        self.admin_engine: Engine | None = None
        self.runtime_engine: Engine | None = None
        self.runtime_url: URL | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {_identifier(self.database)}")
        database_url = self.maintenance_url.set(database=self.database)
        database_engine = create_engine(database_url)
        for filename in _MIGRATIONS:
            migration = Path(__file__).resolve().parent / "migrations" / filename
            with database_engine.begin() as connection:
                _execute_migration(connection, migration.read_text(encoding="utf-8"))
        database_engine.dispose()
        with self.admin_engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE ROLE {_identifier(self.role)} LOGIN PASSWORD '{self.password}' "
                "NOINHERIT NOSUPERUSER NOBYPASSRLS"
            )
            connection.exec_driver_sql(
                f"GRANT gda_control_gateway TO {_identifier(self.role)}"
            )
        self.runtime_url = database_url.set(
            username=self.role,
            password=self.password,
        )
        self.runtime_engine = create_engine(self.runtime_url)

    def expire(self, tenant_id: str, job_id: Any) -> None:
        if self.admin_engine is None:
            raise RuntimeError("temporary PostgreSQL is not initialized")
        database_url = self.maintenance_url.set(database=self.database)
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE gda_control.chongqing_data_package_reconciliation_job
                       SET lease_expires_at = clock_timestamp() - interval '1 second'
                     WHERE tenant_id = :tenant_id AND job_id = :job_id
                    """
                ),
                {"tenant_id": tenant_id, "job_id": job_id},
            )
        engine.dispose()

    def set_max_attempts(self, tenant_id: str, job_id: Any, max_attempts: int) -> None:
        """Adjust one rehearsal job through the temporary database admin connection."""

        if self.admin_engine is None:
            raise RuntimeError("temporary PostgreSQL is not initialized")
        database_url = self.maintenance_url.set(database=self.database)
        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.chongqing_data_package_reconciliation_job
                           SET max_attempts = :max_attempts
                         WHERE tenant_id = :tenant_id AND job_id = :job_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "job_id": job_id,
                        "max_attempts": max_attempts,
                    },
                )
        finally:
            engine.dispose()

    def close(self) -> None:
        if self.runtime_engine is not None:
            self.runtime_engine.dispose()
            self.runtime_engine = None
        if self.admin_engine is None:
            return
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS {_identifier(self.database)} WITH (FORCE)"
            )
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {_identifier(self.role)}")
        self.admin_engine.dispose()
        self.admin_engine = None


@contextmanager
def _temporary_postgres(admin_url: str):
    sandbox = _TemporaryPostgres(admin_url)
    try:
        sandbox.create()
        yield sandbox
    finally:
        sandbox.close()


def _request(suffix: str) -> ChongqingDataPackageReconciliationRequest:
    baseline = build_chongqing_entity_link_baseline(tenant_id=_TENANT)
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    return ChongqingDataPackageReconciliationRequest(
        tenant_id=_TENANT,
        previous_baseline=baseline,
        desired_baseline=baseline,
        effective_at=effective_at,
        evaluated_at=effective_at + timedelta(hours=1),
        idempotency_key=f"cq.pg.rehearsal.{suffix}",
        recorded_by=_ACTOR,
    )


def _response(request: ChongqingDataPackageReconciliationRequest):
    baseline = request.previous_baseline
    return ChongqingDataPackageReconciliationResponse(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        recorded_by=request.recorded_by,
        request_sha256=request.request_sha256,
        previous_customer_bundle_version=baseline.customer_bundle_version,
        desired_customer_bundle_version=baseline.customer_bundle_version,
        effective_at=request.effective_at,
        evaluated_at=request.evaluated_at,
        plan_sha256="a" * 64,
        receipt_sha256="b" * 64,
        previous_baseline_sha256="c" * 64,
        desired_baseline_sha256="c" * 64,
        authority_state_sha256="d" * 64,
        operation_count=0,
        batch_count=0,
        unchanged_entity_count=len(baseline.temporal_entity_drafts),
        unchanged_source_count=len(baseline.source_binding_drafts),
        retained_retired_source_count=0,
        entity_correction_count=0,
        entity_addition_count=0,
        entity_activation_count=0,
        source_binding_count=0,
        entity_retirement_count=0,
        link_operation_count=0,
        link_correction_count=0,
        link_retraction_count=0,
        link_restoration_count=0,
        link_addition_count=0,
        replay_verification="passed",
        write_mode="phased_chunked_atomic_authority_batches",
        atomicity_status="atomic_per_batch_resumable_across_phases",
    )


def run_chongqing_reconciliation_postgres_rehearsal(
    admin_url: str,
) -> ChongqingReconciliationPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None:
            raise RuntimeError("temporary runtime engine was not created")
        repository = ChongqingDataPackageReconciliationJobRepository(
            sandbox.runtime_engine
        )

        request = _request("cancel-race")
        first = repository.enqueue(request)
        replay = repository.enqueue(request)
        checks["idempotent_enqueue_replay"] = first.job_id == replay.job_id
        claimed = repository.claim(
            _TENANT,
            "worker:postgres-one",
            limit=1,
            lease_seconds=30,
        )
        checks["claim_queued_job"] = len(claimed) == 1
        cancel = repository.request_cancel(
            ChongqingDataPackageReconciliationJobCancelRequest(
                job_id=first.job_id,
                requested_by="human:postgres-operator",
                reason="rehearse completion cancellation race",
            ),
            tenant_id=_TENANT,
        )
        checks["cancel_requested_state"] = cancel.status == "cancel_requested"
        completed = repository.succeed(
            claimed[0].job,
            "worker:postgres-one",
            _response(request),
        )
        checks["completion_honors_cancel"] = (
            completed.status == "cancelled"
            and completed.phase_detail == "cancelled_at_completion_boundary"
            and completed.result is None
        )

        lease_request = _request("lease-recovery")
        lease_job = repository.enqueue(lease_request)
        first_claim = repository.claim(
            _TENANT,
            "worker:postgres-expired",
            limit=1,
            lease_seconds=30,
        )
        sandbox.expire(_TENANT, lease_job.job_id)
        recovered = repository.claim(
            _TENANT,
            "worker:postgres-recovered",
            limit=1,
            lease_seconds=30,
        )
        checks["expired_lease_reclaimed"] = (
            len(first_claim) == 1
            and len(recovered) == 1
            and recovered[0].job.attempt_count == 2
            and recovered[0].job.status == "running"
        )

        duplicate_request = _request("duplicate-claim")
        repository.enqueue(duplicate_request)
        duplicate_first = repository.claim(
            _TENANT,
            "worker:duplicate-one",
            limit=1,
            lease_seconds=30,
        )
        duplicate_second = repository.claim(
            _TENANT,
            "worker:duplicate-two",
            limit=1,
            lease_seconds=30,
        )
        checks["duplicate_claim_is_excluded"] = (
            len(duplicate_first) == 1 and not duplicate_second
        )

        fail_request = _request("max-attempts")
        fail_job = repository.enqueue(fail_request)
        sandbox.set_max_attempts(_TENANT, fail_job.job_id, 1)
        fail_claim = repository.claim(
            _TENANT,
            "worker:max-attempts",
            limit=1,
            lease_seconds=30,
        )
        failed = repository.fail(
            fail_claim[0].job,
            "worker:max-attempts",
            error_code="injected_failure",
            error_message="rehearsed final failure",
        )
        checks["max_attempts_fail_closed"] = (
            len(fail_claim) == 1
            and failed.status == "failed"
            and failed.phase == "failed"
        )

        for name, passed in checks.items():
            if not passed:
                failures.append(name)

    payload: dict[str, Any] = {
        "schema_id": "gda.chongqing-reconciliation-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database_scope": "temporary_database_only",
        "migration_ids": list(_MIGRATIONS),
        "checks": checks,
        "passed": not failures,
        "failure_reasons": failures,
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    payload["report_sha256"] = _report_hash(payload)
    return ChongqingReconciliationPostgresRehearsalReport.model_validate(payload)


def write_chongqing_reconciliation_postgres_rehearsal_report(
    report: ChongqingReconciliationPostgresRehearsalReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "ChongqingReconciliationPostgresRehearsalReport",
    "run_chongqing_reconciliation_postgres_rehearsal",
    "write_chongqing_reconciliation_postgres_rehearsal_report",
]
