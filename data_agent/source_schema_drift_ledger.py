"""Tenant-scoped persistence and lifecycle control for source schema drift."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .platform_contracts import TenantId
from .source_connector_governance import SchemaDriftEvent

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
_TENANT_ADAPTER = TypeAdapter(TenantId)


class SourceSchemaDriftLedgerError(RuntimeError):
    """Base error for drift persistence and lifecycle operations."""


class SourceSchemaDriftConflictError(SourceSchemaDriftLedgerError):
    """An immutable binding or state version conflicts with stored truth."""


class SourceSchemaDriftNotFoundError(SourceSchemaDriftLedgerError):
    """The requested drift event is absent or hidden by tenant isolation."""


class SourceSchemaDriftForbiddenError(SourceSchemaDriftLedgerError):
    """Tenant context or database policy rejected the operation."""


class SourceSchemaDriftValidationError(SourceSchemaDriftLedgerError):
    """The requested drift lifecycle operation violates its contract."""


class SourceSchemaDriftConfigurationError(SourceSchemaDriftLedgerError):
    """The configured database cannot enforce the drift ledger contract."""


class SchemaDriftStatus(StrEnum):
    OBSERVED = "observed"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    RECONCILED = "reconciled"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PersistedSchemaDrift(_FrozenModel):
    tenant_id: TenantId
    drift_event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    source_definition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_discovery_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_discovery_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    breaking: bool
    event_payload: SchemaDriftEvent
    detected_by: str = Field(min_length=1, max_length=512)
    status: SchemaDriftStatus
    state_version: int = Field(ge=0)
    detected_at: datetime
    updated_at: datetime

    @field_validator("detected_at", "updated_at")
    @classmethod
    def _aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("drift timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _coherent_evidence(self) -> PersistedSchemaDrift:
        event = self.event_payload
        bindings = (
            self.drift_event_id == event.event_id,
            self.source_id == event.source_id,
            self.previous_discovery_fingerprint == event.previous_discovery_fingerprint,
            self.current_discovery_fingerprint == event.current_discovery_fingerprint,
            self.breaking == event.breaking,
        )
        if not all(bindings):
            raise ValueError("persisted drift binding does not match its event payload")
        if self.updated_at < self.detected_at:
            raise ValueError("updated_at cannot precede detected_at")
        if self.state_version == 0:
            expected = (
                SchemaDriftStatus.APPROVAL_REQUIRED if self.breaking else SchemaDriftStatus.OBSERVED
            )
            if self.status is not expected:
                raise ValueError("initial drift status does not match breaking verdict")
        if not self.breaking and self.status in {
            SchemaDriftStatus.APPROVAL_REQUIRED,
            SchemaDriftStatus.APPROVED,
            SchemaDriftStatus.REJECTED,
        }:
            raise ValueError("non-breaking drift cannot enter an approval decision state")
        return self


class SchemaDriftLifecycleEntry(_FrozenModel):
    tenant_id: TenantId
    lifecycle_event_id: UUID
    drift_event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence_no: int = Field(ge=0)
    from_status: SchemaDriftStatus | None = None
    to_status: SchemaDriftStatus
    actor_subject: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2000)
    approval_case_ref: str | None = None
    details: dict[str, Any]
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lifecycle timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _coherent_decision_reference(self) -> SchemaDriftLifecycleEntry:
        decision = self.to_status in {
            SchemaDriftStatus.APPROVED,
            SchemaDriftStatus.REJECTED,
        }
        if decision != (self.approval_case_ref is not None):
            raise ValueError("approval decisions require exactly one ApprovalCase reference")
        if self.sequence_no == 0 and self.from_status is not None:
            raise ValueError("initial lifecycle entry cannot have a from_status")
        if self.sequence_no > 0 and self.from_status is None:
            raise ValueError("transition lifecycle entry requires a from_status")
        return self


@dataclass(frozen=True)
class SchemaDriftWriteResult:
    drift: PersistedSchemaDrift
    created: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class SourceSchemaDriftLedger:
    """PostgreSQL ledger using the existing platform gateway role and RLS."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise SourceSchemaDriftConfigurationError(
                "source schema drift ledger requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise SourceSchemaDriftConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except SourceSchemaDriftLedgerError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise SourceSchemaDriftConflictError("schema drift state conflict") from exc
            if state == "P0002":
                raise SourceSchemaDriftNotFoundError("schema drift event was not found") from exc
            if state == "42501":
                raise SourceSchemaDriftForbiddenError(
                    "schema drift tenant access was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise SourceSchemaDriftValidationError(
                    "schema drift contract was rejected"
                ) from exc
            raise SourceSchemaDriftLedgerError("schema drift database operation failed") from exc
        except SQLAlchemyError as exc:
            raise SourceSchemaDriftLedgerError("schema drift database operation failed") from exc

    @staticmethod
    def _from_row(row) -> PersistedSchemaDrift:
        value = dict(row)
        value["event_payload"] = _json_value(value["event_payload"])
        return PersistedSchemaDrift.model_validate(value)

    @staticmethod
    def _lifecycle_from_row(row) -> SchemaDriftLifecycleEntry:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return SchemaDriftLifecycleEntry.model_validate(value)

    @classmethod
    def _load(
        cls,
        connection,
        tenant_id: str,
        drift_event_id: str,
    ) -> PersistedSchemaDrift | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, drift_event_id, source_id,
                           source_definition_fingerprint,
                           previous_discovery_fingerprint,
                           current_discovery_fingerprint, breaking,
                           event_payload, detected_by, status, state_version,
                           detected_at, updated_at
                    FROM gda_control.source_schema_drift
                    WHERE tenant_id = :tenant_id
                      AND drift_event_id = :drift_event_id
                    """
                ),
                {"tenant_id": tenant_id, "drift_event_id": drift_event_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._from_row(row) if row is not None else None

    def record(
        self,
        *,
        tenant_id: str,
        source_definition_fingerprint: str,
        event: SchemaDriftEvent,
        detected_by: str,
        detected_at: datetime | None = None,
    ) -> SchemaDriftWriteResult:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if len(source_definition_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in source_definition_fingerprint
        ):
            raise ValueError("source_definition_fingerprint must be a SHA-256")
        if not detected_by.strip():
            raise ValueError("detected_by is required")
        if detected_at is not None and (
            detected_at.tzinfo is None or detected_at.utcoffset() is None
        ):
            raise ValueError("detected_at must include a timezone")

        payload = event.model_dump(mode="json")
        initial_status = (
            SchemaDriftStatus.APPROVAL_REQUIRED if event.breaking else SchemaDriftStatus.OBSERVED
        )
        with self._transaction(tenant) as connection:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.source_schema_drift (
                        tenant_id, drift_event_id, source_id,
                        source_definition_fingerprint,
                        previous_discovery_fingerprint,
                        current_discovery_fingerprint, breaking,
                        event_payload, detected_by, status, detected_at, updated_at
                    ) VALUES (
                        :tenant_id, :drift_event_id, :source_id,
                        :source_definition_fingerprint,
                        :previous_discovery_fingerprint,
                        :current_discovery_fingerprint, :breaking,
                        CAST(:event_payload AS jsonb), :detected_by, :status,
                        COALESCE(CAST(:detected_at AS timestamptz), clock_timestamp()),
                        COALESCE(CAST(:detected_at AS timestamptz), clock_timestamp())
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING drift_event_id
                    """
                ),
                {
                    "tenant_id": tenant,
                    "drift_event_id": event.event_id,
                    "source_id": event.source_id,
                    "source_definition_fingerprint": source_definition_fingerprint,
                    "previous_discovery_fingerprint": (event.previous_discovery_fingerprint),
                    "current_discovery_fingerprint": event.current_discovery_fingerprint,
                    "breaking": event.breaking,
                    "event_payload": _json(payload),
                    "detected_by": detected_by,
                    "status": initial_status.value,
                    "detected_at": (
                        detected_at.astimezone(UTC) if detected_at is not None else None
                    ),
                },
            ).first()
            stored = self._load(connection, tenant, event.event_id)
            if stored is None:
                raise SourceSchemaDriftNotFoundError(
                    "schema drift event was not visible after insert"
                )
            immutable_binding = (
                stored.source_id,
                stored.source_definition_fingerprint,
                stored.previous_discovery_fingerprint,
                stored.current_discovery_fingerprint,
                stored.breaking,
                stored.event_payload,
                stored.detected_by,
            )
            expected_binding = (
                event.source_id,
                source_definition_fingerprint,
                event.previous_discovery_fingerprint,
                event.current_discovery_fingerprint,
                event.breaking,
                event,
                detected_by,
            )
            if immutable_binding != expected_binding:
                raise SourceSchemaDriftConflictError(
                    "schema drift identity already has different evidence"
                )
            return SchemaDriftWriteResult(stored, inserted is not None)

    def get(self, tenant_id: str, drift_event_id: str) -> PersistedSchemaDrift:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load(connection, tenant, drift_event_id)
            if stored is None:
                raise SourceSchemaDriftNotFoundError("schema drift event was not found")
            return stored

    def transition(
        self,
        *,
        tenant_id: str,
        drift_event_id: str,
        expected_state_version: int,
        to_status: SchemaDriftStatus,
        actor_subject: str,
        reason: str,
        approval_case_ref: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> PersistedSchemaDrift:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if expected_state_version < 0:
            raise ValueError("expected_state_version must be non-negative")
        if not actor_subject.strip() or not reason.strip():
            raise ValueError("actor_subject and reason are required")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_source_schema_drift(
                        :tenant_id, :drift_event_id, :expected_state_version,
                        :to_status, :actor_subject, :reason,
                        :approval_case_ref, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "drift_event_id": drift_event_id,
                    "expected_state_version": expected_state_version,
                    "to_status": to_status.value,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "approval_case_ref": approval_case_ref,
                    "details": _json(details or {}),
                },
            ).scalar_one()
            stored = self._load(connection, tenant, drift_event_id)
            if stored is None:
                raise SourceSchemaDriftNotFoundError("schema drift event was not found")
            return stored

    def lifecycle(
        self,
        tenant_id: str,
        drift_event_id: str,
    ) -> tuple[SchemaDriftLifecycleEntry, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, lifecycle_event_id, drift_event_id,
                               sequence_no, from_status, to_status,
                               actor_subject, reason, approval_case_ref,
                               details, occurred_at
                        FROM gda_control.source_schema_drift_lifecycle_event
                        WHERE tenant_id = :tenant_id
                          AND drift_event_id = :drift_event_id
                        ORDER BY sequence_no
                        """
                    ),
                    {"tenant_id": tenant, "drift_event_id": drift_event_id},
                )
                .mappings()
                .all()
            )
            return tuple(self._lifecycle_from_row(row) for row in rows)
