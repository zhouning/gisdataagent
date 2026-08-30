"""PostgreSQL authority for append-only cross-store projection checkpoints."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionCheckpointWriteResult,
    ProjectionConsistencyError,
    ProjectionEngine,
)
from .db_engine import get_engine
from .platform_contracts import TenantId
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

CROSS_STORE_PROJECTION_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "169_cross_store_projection_checkpoint_authority.sql"
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_PROJECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProjectionCheckpointAuthorityError(RuntimeError):
    """Base error for the durable checkpoint authority."""


class ProjectionCheckpointAuthorityConfigurationError(
    ProjectionCheckpointAuthorityError
):
    """The database or gateway role cannot enforce the authority contract."""


class ProjectionCheckpointAuthorityForbiddenError(ProjectionCheckpointAuthorityError):
    """The current database role or tenant context was denied."""


class ProjectionCheckpointAuthorityValidationError(
    ProjectionCheckpointAuthorityError,
    ProjectionConsistencyError,
):
    """Checkpoint identity or repair evidence is invalid."""


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _projection_identity(
    *,
    tenant_id: str,
    projection_id: str,
    target_engine: ProjectionEngine | str,
    target_ref: str,
) -> tuple[str, str, ProjectionEngine, str]:
    try:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        engine = ProjectionEngine(target_engine)
    except (ValueError, ValidationError) as exc:
        raise ProjectionCheckpointAuthorityValidationError(
            "projection checkpoint identity is invalid"
        ) from exc
    projection = str(projection_id or "").strip()
    target = str(target_ref or "").strip()
    if _PROJECTION_ID_RE.fullmatch(projection) is None:
        raise ProjectionCheckpointAuthorityValidationError(
            "projection checkpoint projection_id is invalid"
        )
    if not target or len(target.encode("utf-8")) > 512:
        raise ProjectionCheckpointAuthorityValidationError(
            "projection checkpoint target_ref is invalid"
        )
    return tenant, projection, engine, target


class PostgresProjectionCheckpointAuthority:
    """Tenant-bound repository with a single database-controlled write path."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ProjectionCheckpointAuthorityConfigurationError(
                "cross-store projection checkpoint authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        try:
            tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        except ValidationError as exc:
            raise ProjectionCheckpointAuthorityValidationError(
                "projection checkpoint tenant_id is invalid"
            ) from exc
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise ProjectionCheckpointAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except (
            ProjectionCheckpointAuthorityError,
            ProjectionCheckpointConflictError,
        ):
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise ProjectionCheckpointConflictError(
                    "projection checkpoint predecessor or idempotency conflict"
                ) from exc
            if state == "42501":
                raise ProjectionCheckpointAuthorityForbiddenError(
                    "projection checkpoint tenant or database role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise ProjectionCheckpointAuthorityValidationError(
                    "projection checkpoint evidence was rejected"
                ) from exc
            raise ProjectionCheckpointAuthorityConfigurationError(
                "projection checkpoint authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ProjectionCheckpointAuthorityConfigurationError(
                "projection checkpoint authority operation failed"
            ) from exc

    @staticmethod
    def _checkpoint_from_document(document: Any) -> ProjectionCheckpoint:
        values = _json_value(document)
        if not isinstance(values, dict):
            raise ProjectionCheckpointAuthorityConfigurationError(
                "projection checkpoint authority returned an invalid document"
            )
        values = dict(values)
        for key in (
            "repair_plan_sha256",
            "plan_idempotency_key",
            "previous_checkpoint_sha256",
        ):
            values.pop(key, None)
        try:
            return ProjectionCheckpoint.model_validate(values)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProjectionCheckpointAuthorityConfigurationError(
                "stored projection checkpoint is invalid"
            ) from exc

    def record(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        previous_checkpoint_sha256: str | None = None,
    ) -> ProjectionCheckpointWriteResult:
        repair_plan_sha256 = checkpoint.target_commit_ref.get("plan_sha256")
        plan_idempotency_key = checkpoint.target_commit_ref.get("idempotency_key")
        if not isinstance(repair_plan_sha256, str) or (
            _SHA256_RE.fullmatch(repair_plan_sha256) is None
        ):
            raise ProjectionCheckpointAuthorityValidationError(
                "target commit evidence does not contain a repair plan fingerprint"
            )
        if not isinstance(plan_idempotency_key, str) or (
            _SHA256_RE.fullmatch(plan_idempotency_key) is None
        ):
            raise ProjectionCheckpointAuthorityValidationError(
                "target commit evidence does not contain a plan idempotency key"
            )
        if previous_checkpoint_sha256 is not None and (
            _SHA256_RE.fullmatch(previous_checkpoint_sha256) is None
        ):
            raise ProjectionCheckpointAuthorityValidationError(
                "previous projection checkpoint fingerprint is invalid"
            )

        with self._transaction(checkpoint.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT checkpoint_document, created
                    FROM gda_control.record_cross_store_projection_checkpoint(
                        :tenant_id, :projection_id, :target_engine, :target_ref,
                        :checkpoint_version, :source_resource_version_ref,
                        :source_content_sha256, :target_exists,
                        :target_content_sha256, :target_row_count,
                        CAST(:target_commit_ref AS jsonb), :repair_plan_sha256,
                        :plan_idempotency_key, :previous_checkpoint_sha256,
                        :updated_by, :updated_at, :checkpoint_sha256
                    )
                    """
                ),
                {
                    "tenant_id": checkpoint.tenant_id,
                    "projection_id": checkpoint.projection_id,
                    "target_engine": checkpoint.target_engine.value,
                    "target_ref": checkpoint.target_ref,
                    "checkpoint_version": checkpoint.checkpoint_version,
                    "source_resource_version_ref": (
                        checkpoint.source_resource_version_ref
                    ),
                    "source_content_sha256": checkpoint.source_content_sha256,
                    "target_exists": checkpoint.target_exists,
                    "target_content_sha256": checkpoint.target_content_sha256,
                    "target_row_count": checkpoint.target_row_count,
                    "target_commit_ref": _json(checkpoint.target_commit_ref),
                    "repair_plan_sha256": repair_plan_sha256,
                    "plan_idempotency_key": plan_idempotency_key,
                    "previous_checkpoint_sha256": previous_checkpoint_sha256,
                    "updated_by": checkpoint.updated_by,
                    "updated_at": checkpoint.updated_at,
                    "checkpoint_sha256": checkpoint.checkpoint_sha256,
                },
            ).mappings().one()
        return ProjectionCheckpointWriteResult(
            checkpoint=self._checkpoint_from_document(row["checkpoint_document"]),
            created=bool(row["created"]),
        )

    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
    ) -> ProjectionCheckpoint | None:
        tenant, projection, engine, target = _projection_identity(
            tenant_id=tenant_id,
            projection_id=projection_id,
            target_engine=target_engine,
            target_ref=target_ref,
        )
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT to_jsonb(current_checkpoint) AS checkpoint_document
                    FROM gda_control.cross_store_projection_checkpoint_current
                        AS current_checkpoint
                    WHERE tenant_id = :tenant_id
                      AND projection_id = :projection_id
                      AND target_engine = :target_engine
                      AND target_ref = :target_ref
                    """
                ),
                {
                    "tenant_id": tenant,
                    "projection_id": projection,
                    "target_engine": engine.value,
                    "target_ref": target,
                },
            ).mappings().one_or_none()
        if row is None:
            return None
        return self._checkpoint_from_document(row["checkpoint_document"])

    def history(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
        limit: int = 1_000,
    ) -> tuple[ProjectionCheckpoint, ...]:
        if limit < 1 or limit > 10_000:
            raise ProjectionCheckpointAuthorityValidationError(
                "projection checkpoint history limit must be 1..10000"
            )
        tenant, projection, engine, target = _projection_identity(
            tenant_id=tenant_id,
            projection_id=projection_id,
            target_engine=target_engine,
            target_ref=target_ref,
        )
        with self._transaction(tenant) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT to_jsonb(history) AS checkpoint_document
                    FROM gda_control.cross_store_projection_checkpoint_history
                        AS history
                    WHERE tenant_id = :tenant_id
                      AND projection_id = :projection_id
                      AND target_engine = :target_engine
                      AND target_ref = :target_ref
                    ORDER BY checkpoint_version
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant,
                    "projection_id": projection,
                    "target_engine": engine.value,
                    "target_ref": target,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(
            self._checkpoint_from_document(row["checkpoint_document"])
            for row in rows
        )


__all__ = [
    "CROSS_STORE_PROJECTION_AUTHORITY_MIGRATION",
    "PostgresProjectionCheckpointAuthority",
    "ProjectionCheckpointAuthorityConfigurationError",
    "ProjectionCheckpointAuthorityError",
    "ProjectionCheckpointAuthorityForbiddenError",
    "ProjectionCheckpointAuthorityValidationError",
]
