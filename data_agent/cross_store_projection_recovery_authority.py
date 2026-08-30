"""PostgreSQL-backed append-only ledger for projection recovery snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import _sqlstate
from .cross_store_projection_recovery import (
    ProjectionRecoveryError,
    ProjectionRecoverySnapshot,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

PROJECTION_RECOVERY_LEDGER_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "170_cross_store_projection_recovery_ledger.sql"
)


class ProjectionRecoveryAuthorityError(RuntimeError):
    """Base error for the durable projection recovery ledger."""


class ProjectionRecoveryAuthorityConfigurationError(ProjectionRecoveryAuthorityError):
    """The database or gateway role cannot enforce the ledger contract."""


class ProjectionRecoveryAuthorityForbiddenError(ProjectionRecoveryAuthorityError):
    """The current database role or tenant context was denied."""


class ProjectionRecoveryAuthorityValidationError(
    ProjectionRecoveryAuthorityError,
    ProjectionRecoveryError,
):
    """Recovery snapshot identity or event evidence is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgresProjectionRecoveryLedger:
    """Tenant-bound repository with one SECURITY DEFINER write path."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ProjectionRecoveryAuthorityValidationError(
                "recovery ledger tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ProjectionRecoveryAuthorityConfigurationError(
                "projection recovery ledger requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise ProjectionRecoveryAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except ProjectionRecoveryAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise ProjectionRecoveryError(
                    "projection recovery append-only or idempotency conflict"
                ) from exc
            if state == "42501":
                raise ProjectionRecoveryAuthorityForbiddenError(
                    "projection recovery tenant or database role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise ProjectionRecoveryAuthorityValidationError(
                    "projection recovery evidence was rejected"
                ) from exc
            raise ProjectionRecoveryAuthorityConfigurationError(
                "projection recovery ledger operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ProjectionRecoveryAuthorityConfigurationError(
                "projection recovery ledger operation failed"
            ) from exc

    @staticmethod
    def _snapshot(document: Any) -> ProjectionRecoverySnapshot:
        try:
            return ProjectionRecoverySnapshot.model_validate(_json_value(document))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProjectionRecoveryAuthorityConfigurationError(
                "stored projection recovery snapshot is invalid"
            ) from exc

    def append(self, snapshot: ProjectionRecoverySnapshot) -> ProjectionRecoverySnapshot:
        if snapshot.tenant_id != self.tenant_id:
            raise ProjectionRecoveryAuthorityForbiddenError(
                "recovery snapshot tenant does not match ledger tenant"
            )
        if not snapshot.events:
            raise ProjectionRecoveryAuthorityValidationError(
                "recovery snapshot must contain an event"
            )
        event = snapshot.events[-1]
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT snapshot_document, created
                    FROM gda_control.record_cross_store_projection_recovery_snapshot(
                        :tenant_id, :plan_sha256, :plan_idempotency_key,
                        :projection_id, :target_engine, :target_ref,
                        CAST(:snapshot_document AS jsonb), :snapshot_sha256,
                        CAST(:event_document AS jsonb), :event_sha256
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "plan_sha256": snapshot.plan_sha256,
                    "plan_idempotency_key": snapshot.plan_idempotency_key,
                    "projection_id": snapshot.projection_id,
                    "target_engine": snapshot.target_engine.value,
                    "target_ref": snapshot.target_ref,
                    "snapshot_document": _json(snapshot.model_dump(mode="json")),
                    "snapshot_sha256": snapshot.snapshot_sha256,
                    "event_document": _json(event.model_dump(mode="json")),
                    "event_sha256": event.event_sha256,
                },
            ).mappings().one()
        stored = self._snapshot(row["snapshot_document"])
        if stored.plan_sha256 != snapshot.plan_sha256:
            raise ProjectionRecoveryAuthorityConfigurationError(
                "recovery ledger returned a different plan"
            )
        return stored

    def current(self, plan_sha256: str) -> ProjectionRecoverySnapshot | None:
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT snapshot_document
                    FROM gda_control.cross_store_projection_recovery_snapshot_current
                    WHERE tenant_id = :tenant_id AND plan_sha256 = :plan_sha256
                    """
                ),
                {"tenant_id": self.tenant_id, "plan_sha256": plan_sha256},
            ).mappings().one_or_none()
        return None if row is None else self._snapshot(row["snapshot_document"])

    def history(self, plan_sha256: str) -> tuple[ProjectionRecoverySnapshot, ...]:
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT snapshot_document
                    FROM gda_control.cross_store_projection_recovery_snapshot_history
                    WHERE tenant_id = :tenant_id AND plan_sha256 = :plan_sha256
                    ORDER BY snapshot_version
                    """
                ),
                {"tenant_id": self.tenant_id, "plan_sha256": plan_sha256},
            ).mappings().all()
        return tuple(self._snapshot(row["snapshot_document"]) for row in rows)


__all__ = [
    "PROJECTION_RECOVERY_LEDGER_MIGRATION",
    "PostgresProjectionRecoveryLedger",
    "ProjectionRecoveryAuthorityConfigurationError",
    "ProjectionRecoveryAuthorityError",
    "ProjectionRecoveryAuthorityForbiddenError",
    "ProjectionRecoveryAuthorityValidationError",
]
