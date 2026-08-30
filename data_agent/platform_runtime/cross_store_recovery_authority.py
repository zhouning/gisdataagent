"""PostgreSQL authority for cross-store recovery identity bindings."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from ..cross_store_projection_authority import _sqlstate
from ..db_engine import get_engine
from ..temporal_entity_authority import GATEWAY_DATABASE_ROLE
from .cross_store_recovery import (
    CrossStoreRecoveryBinding,
    CrossStoreRecoveryContractError,
)

CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "232_cross_store_recovery_binding_authority.sql"
)


class CrossStoreRecoveryAuthorityError(RuntimeError):
    """Base error for the durable cross-store recovery binding authority."""


class CrossStoreRecoveryAuthorityConfigurationError(
    CrossStoreRecoveryAuthorityError
):
    """The database or gateway role cannot enforce the authority contract."""


class CrossStoreRecoveryAuthorityForbiddenError(CrossStoreRecoveryAuthorityError):
    """The current database role or tenant context was denied."""


class CrossStoreRecoveryAuthorityValidationError(
    CrossStoreRecoveryAuthorityError,
    CrossStoreRecoveryContractError,
):
    """Binding identity or durable evidence is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _binding(document: Any) -> CrossStoreRecoveryBinding:
    payload = _json_value(document)
    if not isinstance(payload, dict):
        raise CrossStoreRecoveryAuthorityConfigurationError(
            "stored cross-store recovery binding is not an object"
        )
    try:
        payload = {**payload, "tenant_ids": tuple(payload.get("tenant_ids", ()))}
        binding = CrossStoreRecoveryBinding(
            **payload,
        )
        binding.validate()
        return binding
    except (TypeError, ValueError, CrossStoreRecoveryContractError) as exc:
        raise CrossStoreRecoveryAuthorityConfigurationError(
            "stored cross-store recovery binding is invalid"
        ) from exc


class PostgresCrossStoreRecoveryBindingAuthority:
    """Tenant-bound repository with one controlled append path.

    A multi-tenant binding is recorded once for each covered tenant.  The
    caller must use the same binding document for every authority instance;
    PostgreSQL RLS then limits each instance to its own evidence copy.
    """

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise CrossStoreRecoveryAuthorityValidationError(
                "cross-store recovery authority tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise CrossStoreRecoveryAuthorityConfigurationError(
                "cross-store recovery binding authority requires PostgreSQL"
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
                        raise CrossStoreRecoveryAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except CrossStoreRecoveryAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505", "55000"}:
                raise CrossStoreRecoveryAuthorityValidationError(
                    "cross-store recovery binding append-only or idempotency conflict"
                ) from exc
            if state == "42501":
                raise CrossStoreRecoveryAuthorityForbiddenError(
                    "cross-store recovery binding tenant or database role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise CrossStoreRecoveryAuthorityValidationError(
                    "cross-store recovery binding evidence was rejected"
                ) from exc
            raise CrossStoreRecoveryAuthorityConfigurationError(
                "cross-store recovery binding authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise CrossStoreRecoveryAuthorityConfigurationError(
                "cross-store recovery binding authority operation failed"
            ) from exc

    def _check_binding(self, binding: CrossStoreRecoveryBinding) -> None:
        try:
            binding.validate()
        except CrossStoreRecoveryContractError as exc:
            raise CrossStoreRecoveryAuthorityValidationError(str(exc)) from exc
        if self.tenant_id not in binding.tenant_ids:
            raise CrossStoreRecoveryAuthorityForbiddenError(
                "cross-store recovery binding does not cover authority tenant"
            )

    def append(self, binding: CrossStoreRecoveryBinding) -> CrossStoreRecoveryBinding:
        self._check_binding(binding)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT binding_document, created
                    FROM gda_control.record_cross_store_recovery_binding(
                        :tenant_id, :binding_sha256,
                        CAST(:binding_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "binding_sha256": binding.binding_sha256,
                    "binding_document": _json(binding.as_dict()),
                },
            ).mappings().one()
        stored = _binding(row["binding_document"])
        if stored.as_dict() != binding.as_dict():
            raise CrossStoreRecoveryAuthorityConfigurationError(
                "cross-store recovery authority returned a different binding"
            )
        return stored

    def current(self, binding_sha256: str) -> CrossStoreRecoveryBinding | None:
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT binding_document
                    FROM gda_control.cross_store_recovery_binding_current
                    WHERE tenant_id = :tenant_id AND binding_sha256 = :binding_sha256
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "binding_sha256": binding_sha256,
                },
            ).mappings().one_or_none()
        return None if row is None else _binding(row["binding_document"])

    def history(
        self, source_resource_version_ref: str | None = None
    ) -> tuple[CrossStoreRecoveryBinding, ...]:
        query = """
            SELECT binding_document
            FROM gda_control.cross_store_recovery_binding_history
            WHERE tenant_id = :tenant_id
        """
        params: dict[str, Any] = {"tenant_id": self.tenant_id}
        if source_resource_version_ref is not None:
            query += " AND source_resource_version_ref = :source_resource_version_ref"
            params["source_resource_version_ref"] = source_resource_version_ref
        query += " ORDER BY recorded_at, binding_sha256"
        with self._transaction() as connection:
            rows = connection.execute(text(query), params).mappings().all()
        return tuple(_binding(row["binding_document"]) for row in rows)


__all__ = [
    "CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION",
    "CrossStoreRecoveryAuthorityConfigurationError",
    "CrossStoreRecoveryAuthorityError",
    "CrossStoreRecoveryAuthorityForbiddenError",
    "CrossStoreRecoveryAuthorityValidationError",
    "PostgresCrossStoreRecoveryBindingAuthority",
]
