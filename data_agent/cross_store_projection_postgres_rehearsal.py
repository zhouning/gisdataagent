"""Isolated PostgreSQL rehearsal for the projection checkpoint authority."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import DBAPIError

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionEngine,
    projection_checkpoint_fingerprint,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "169_cross_store_projection_checkpoint_authority.sql",
)
_TENANT = "cq-projection-rehearsal"
_OTHER_TENANT = "cq-projection-other"
_PROJECTION = "cq.land_parcel"
_TARGET = "postgis://cq-db/public.land_parcel_current"
_NOW = datetime(2026, 8, 15, 0, 30, tzinfo=UTC)


class CrossStoreProjectionPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.cross-store-projection-postgres-rehearsal.v1"
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
    def _fingerprint_matches(self) -> CrossStoreProjectionPostgresRehearsalReport:
        expected = _report_hash(self.model_dump(mode="json"))
        if self.report_sha256 != expected:
            raise ValueError("projection PostgreSQL rehearsal report fingerprint is invalid")
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


def _identifier(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if not value or any(char not in allowed for char in value):
        raise ValueError("unsafe SQL identifier")
    return '"' + value.replace('"', '""') + '"'


def _execute_migration(connection: Any, migration_sql: str) -> None:
    connection.exec_driver_sql(migration_sql.replace("%", "%%"))


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class _TemporaryPostgres:
    def __init__(self, admin_url: str):
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_projection_rehearsal_{uuid4().hex[:12]}"
        self.role = f"gda_projection_rehearsal_{uuid4().hex[:12]}"
        self.password = uuid4().hex
        self.admin_engine: Engine | None = None
        self.runtime_engine: Engine | None = None
        self.database_url: URL | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {_identifier(self.database)}")
        self.database_url = self.maintenance_url.set(database=self.database)
        database_engine = create_engine(self.database_url)
        try:
            for filename in _MIGRATIONS:
                migration = Path(__file__).resolve().parent / "migrations" / filename
                with database_engine.begin() as connection:
                    _execute_migration(connection, migration.read_text(encoding="utf-8"))
        finally:
            database_engine.dispose()
        with self.admin_engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE ROLE {_identifier(self.role)} LOGIN PASSWORD '{self.password}' "
                "NOINHERIT NOSUPERUSER NOBYPASSRLS"
            )
            connection.exec_driver_sql(
                f"GRANT gda_control_gateway TO {_identifier(self.role)}"
            )
        self.runtime_engine = create_engine(
            self.database_url.set(username=self.role, password=self.password)
        )

    @contextmanager
    def admin_connection(self):
        if self.database_url is None:
            raise RuntimeError("temporary PostgreSQL is not initialized")
        engine = create_engine(self.database_url)
        try:
            with engine.connect() as connection:
                with connection.begin():
                    yield connection
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


def _checkpoint(
    *,
    version: int,
    source_sha256: str,
    plan_sha256: str,
    plan_idempotency_key: str,
    updated_at: datetime,
) -> ProjectionCheckpoint:
    values = {
        "tenant_id": _TENANT,
        "projection_id": _PROJECTION,
        "source_resource_version_ref": (
            f"gda://{_TENANT}/data_product/cq-land-v{version}"
        ),
        "source_content_sha256": source_sha256,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": _TARGET,
        "target_exists": True,
        "target_content_sha256": "b" * 64,
        "target_row_count": 455,
        "checkpoint_version": version,
        "target_commit_ref": {
            "provider": "postgis",
            "commit": f"cq-land-v{version}",
            "plan_sha256": plan_sha256,
            "idempotency_key": plan_idempotency_key,
        },
        "updated_by": "workload:projection-publisher",
        "updated_at": updated_at,
    }
    return ProjectionCheckpoint(
        **values,
        checkpoint_sha256=projection_checkpoint_fingerprint(**values),
    )


def _function_parameters(checkpoint: ProjectionCheckpoint) -> dict[str, Any]:
    return {
        "tenant_id": _OTHER_TENANT,
        "projection_id": checkpoint.projection_id,
        "target_engine": checkpoint.target_engine.value,
        "target_ref": checkpoint.target_ref,
        "checkpoint_version": checkpoint.checkpoint_version,
        "source_resource_version_ref": checkpoint.source_resource_version_ref,
        "source_content_sha256": checkpoint.source_content_sha256,
        "target_exists": checkpoint.target_exists,
        "target_content_sha256": checkpoint.target_content_sha256,
        "target_row_count": checkpoint.target_row_count,
        "target_commit_ref": json.dumps(checkpoint.target_commit_ref),
        "repair_plan_sha256": checkpoint.target_commit_ref["plan_sha256"],
        "plan_idempotency_key": checkpoint.target_commit_ref["idempotency_key"],
        "previous_checkpoint_sha256": None,
        "updated_by": checkpoint.updated_by,
        "updated_at": checkpoint.updated_at,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
    }


_RECORD_SQL = text(
    """
    SELECT checkpoint_document, created
    FROM gda_control.record_cross_store_projection_checkpoint(
        :tenant_id, :projection_id, :target_engine, :target_ref,
        :checkpoint_version, :source_resource_version_ref,
        :source_content_sha256, :target_exists, :target_content_sha256,
        :target_row_count, CAST(:target_commit_ref AS jsonb),
        :repair_plan_sha256, :plan_idempotency_key,
        :previous_checkpoint_sha256, :updated_by, :updated_at,
        :checkpoint_sha256
    )
    """
)


def run_cross_store_projection_postgres_rehearsal(
    admin_url: str,
) -> CrossStoreProjectionPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, failure: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(failure)

    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None:
            raise RuntimeError("temporary runtime engine was not created")
        authority = PostgresProjectionCheckpointAuthority(sandbox.runtime_engine)
        first = _checkpoint(
            version=1,
            source_sha256="a" * 64,
            plan_sha256="c" * 64,
            plan_idempotency_key="d" * 64,
            updated_at=_NOW,
        )

        first_write = authority.record(first)
        check(
            "initial_version_one_write",
            first_write.created and first_write.checkpoint == first,
            "initial checkpoint was not recorded at version 1",
        )
        replay = authority.record(first)
        check(
            "idempotent_replay",
            not replay.created and replay.checkpoint == first,
            "same checkpoint did not replay idempotently",
        )

        changed_evidence = _checkpoint(
            version=1,
            source_sha256="e" * 64,
            plan_sha256="c" * 64,
            plan_idempotency_key="d" * 64,
            updated_at=_NOW,
        )
        try:
            authority.record(changed_evidence)
            evidence_conflict = False
        except ProjectionCheckpointConflictError:
            evidence_conflict = True
        check(
            "idempotency_evidence_conflict_rejected",
            evidence_conflict,
            "same plan idempotency key accepted different checkpoint evidence",
        )

        second = _checkpoint(
            version=2,
            source_sha256="e" * 64,
            plan_sha256="f" * 64,
            plan_idempotency_key="1" * 64,
            updated_at=_NOW + timedelta(minutes=1),
        )
        try:
            authority.record(second, previous_checkpoint_sha256="9" * 64)
            predecessor_conflict = False
        except ProjectionCheckpointConflictError:
            predecessor_conflict = True
        check(
            "stale_predecessor_rejected",
            predecessor_conflict,
            "stale predecessor fingerprint was accepted",
        )

        third = _checkpoint(
            version=3,
            source_sha256="2" * 64,
            plan_sha256="3" * 64,
            plan_idempotency_key="4" * 64,
            updated_at=_NOW + timedelta(minutes=2),
        )
        try:
            authority.record(third, previous_checkpoint_sha256=first.checkpoint_sha256)
            skipped_version = False
        except ProjectionCheckpointConflictError:
            skipped_version = True
        check(
            "version_skip_rejected",
            skipped_version,
            "checkpoint version advanced by more than one",
        )

        second_write = authority.record(
            second,
            previous_checkpoint_sha256=first.checkpoint_sha256,
        )
        history = authority.history(
            tenant_id=_TENANT,
            projection_id=_PROJECTION,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=_TARGET,
        )
        current = authority.current(
            tenant_id=_TENANT,
            projection_id=_PROJECTION,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=_TARGET,
        )
        check(
            "append_only_history_and_current_projection",
            second_write.created
            and tuple(item.checkpoint_version for item in history) == (1, 2)
            and current == second,
            "append-only history or current checkpoint projection is incorrect",
        )

        other_tenant_current = authority.current(
            tenant_id=_OTHER_TENANT,
            projection_id=_PROJECTION,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=_TARGET,
        )
        check(
            "cross_tenant_read_hidden",
            other_tenant_current is None,
            "tenant RLS exposed another tenant's current checkpoint",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text(
                            "SELECT set_config('app.current_tenant', :tenant, true)"
                        ),
                        {"tenant": _TENANT},
                    )
                    connection.execute(_RECORD_SQL, _function_parameters(first)).one()
            cross_tenant_rejected = False
        except DBAPIError as exc:
            cross_tenant_rejected = _sqlstate(exc) == "42501"
        check(
            "cross_tenant_write_rejected",
            cross_tenant_rejected,
            "cross-tenant function write was not denied",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text(
                            "SELECT set_config('app.current_tenant', :tenant, true)"
                        ),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO
                                gda_control.cross_store_projection_checkpoint_history
                            SELECT * FROM
                                gda_control.cross_store_projection_checkpoint_history
                            WHERE FALSE
                            """
                        )
                    )
            direct_write_rejected = False
        except DBAPIError as exc:
            direct_write_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_direct_table_write_rejected",
            direct_write_rejected,
            "gateway role retained direct table write permission",
        )

        try:
            with sandbox.admin_connection() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.cross_store_projection_checkpoint_history
                        SET updated_by = updated_by
                        WHERE tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": _TENANT},
                )
            immutable_update_rejected = False
        except DBAPIError as exc:
            immutable_update_rejected = _sqlstate(exc) == "55000"
        check(
            "history_mutation_rejected",
            immutable_update_rejected,
            "checkpoint history accepted an UPDATE",
        )

    payload = {
        "schema_id": "gda.cross-store-projection-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "migration_ids": tuple(item.split("_", 1)[0] for item in _MIGRATIONS),
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return CrossStoreProjectionPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_cross_store_projection_postgres_rehearsal_report(
    report: CrossStoreProjectionPostgresRehearsalReport,
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
        description="Rehearse the cross-store checkpoint authority in a temporary database"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL administrator URL used only to create a temporary database",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_cross_store_projection_postgres_rehearsal(args.database_url)
    if args.output:
        write_cross_store_projection_postgres_rehearsal_report(report, args.output)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CrossStoreProjectionPostgresRehearsalReport",
    "run_cross_store_projection_postgres_rehearsal",
    "write_cross_store_projection_postgres_rehearsal_report",
]
