"""PostgreSQL authority for AgentOps specialist provider operation receipts.

The authority owns provider-operation identity and receipt state, not Temporal
activity execution.  It is intentionally append-only: a provider submission and
each terminal transition are immutable rows.  Replaying a request returns the
existing receipt; it never creates a second provider operation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .agentops_specialist_providers import (
    SPECIALIST_OPERATION_RECEIPT_SCHEMA,
    SpecialistOperationAuthority,
    SpecialistOperationObservation,
    SpecialistOperationReceipt,
    SpecialistOperationStatus,
    SpecialistProviderError,
    SpecialistUncertaintyType,
)
from .agentops_temporal_contracts import TemporalActivityRequest, temporal_contract_fingerprint
from .db_engine import get_engine
from .platform_contracts import TenantId, canonical_json_bytes
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "246_agentops_specialist_operation_receipt_authority.sql"
)
AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "247_agentops_specialist_operation_uncertainty.sql"
)

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_OPERATION_RE = re.compile(r"^\S{1,512}$")
_TENANT_ADAPTER = TypeAdapter(TenantId)


class SpecialistOperationAuthorityError(SpecialistProviderError):
    """Base error for the durable specialist operation authority."""


class SpecialistOperationAuthorityConfigurationError(SpecialistOperationAuthorityError):
    """The database or gateway role cannot enforce the authority contract."""


class SpecialistOperationAuthorityConflictError(SpecialistOperationAuthorityError):
    """An operation identity or terminal state conflicts with existing evidence."""


class SpecialistOperationAuthorityForbiddenError(SpecialistOperationAuthorityError):
    """The database role or tenant context was denied."""


class SpecialistOperationAuthorityValidationError(SpecialistOperationAuthorityError):
    """A receipt contract or authority input is invalid."""


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("ascii")


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _tenant(value: str) -> str:
    candidate = str(value or "").strip()
    if _TENANT_RE.fullmatch(candidate) is None:
        raise SpecialistOperationAuthorityValidationError(
            "specialist operation tenant_id is invalid"
        )
    try:
        return _TENANT_ADAPTER.validate_python(candidate)
    except ValidationError as exc:
        raise SpecialistOperationAuthorityValidationError(
            "specialist operation tenant_id is invalid"
        ) from exc


def _operation_ref(value: str) -> str:
    candidate = str(value or "").strip()
    if _OPERATION_RE.fullmatch(candidate) is None:
        raise SpecialistOperationAuthorityValidationError(
            "specialist operation_ref must be a non-empty value of at most 512 bytes"
        )
    return candidate


def _actor(value: str) -> str:
    candidate = str(value or "").strip()
    if _ACTOR_RE.fullmatch(candidate) is None:
        raise SpecialistOperationAuthorityValidationError(
            "specialist operation recorded_by must be a typed subject"
        )
    return candidate


def _fingerprint_payload(schema_id: str, document: dict[str, Any], field: str) -> str:
    payload = dict(document)
    payload.pop(field, None)
    if payload.get("uncertainty_type") is None:
        payload.pop("uncertainty_type", None)
    return _json({"schema": schema_id, "data": payload})


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class PostgresSpecialistOperationAuthority(SpecialistOperationAuthority):
    """Tenant-bound append-only provider operation receipt repository."""

    def __init__(
        self,
        tenant_id: str,
        engine: Any = None,
        *,
        recorded_by: str = "workload:agentops-specialist-authority",
    ) -> None:
        self.tenant_id = _tenant(tenant_id)
        self._engine = engine
        self.recorded_by = _actor(recorded_by)

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise SpecialistOperationAuthorityConfigurationError(
                "specialist operation authority requires PostgreSQL"
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
                        raise SpecialistOperationAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except SpecialistOperationAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise SpecialistOperationAuthorityForbiddenError(
                    "specialist operation tenant or database role was denied"
                ) from exc
            if state in {"23505", "40001", "23503"}:
                raise SpecialistOperationAuthorityConflictError(
                    "specialist operation identity or terminal state conflicts"
                ) from exc
            if state in {"22023", "22P02", "23514", "23502", "55000"}:
                raise SpecialistOperationAuthorityValidationError(
                    "specialist operation receipt was rejected"
                ) from exc
            raise SpecialistOperationAuthorityConfigurationError(
                "specialist operation authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise SpecialistOperationAuthorityConfigurationError(
                "specialist operation authority operation failed"
            ) from exc

    @staticmethod
    def _receipt(document: Any) -> SpecialistOperationReceipt:
        try:
            return SpecialistOperationReceipt.model_validate(_json_value(document))
        except (TypeError, ValueError, ValidationError) as exc:
            raise SpecialistOperationAuthorityConfigurationError(
                "stored specialist operation receipt is invalid"
            ) from exc

    @staticmethod
    def _observation(receipt: SpecialistOperationReceipt) -> SpecialistOperationObservation:
        values = receipt.model_dump(mode="json")
        values["observed_at"] = datetime.now(UTC)
        fingerprint_values = dict(values)
        if fingerprint_values.get("uncertainty_type") is None:
            fingerprint_values.pop("uncertainty_type", None)
        values["observation_sha256"] = temporal_contract_fingerprint(
            SpecialistOperationObservation.schema_id,
            fingerprint_values,
            "observation_sha256",
        )
        try:
            return SpecialistOperationObservation(**values)
        except (TypeError, ValueError, ValidationError) as exc:
            raise SpecialistOperationAuthorityConfigurationError(
                "stored specialist operation observation is invalid"
            ) from exc

    def _check_tenant(self, tenant_id: str) -> None:
        if _tenant(tenant_id) != self.tenant_id:
            raise SpecialistOperationAuthorityForbiddenError(
                "specialist operation tenant differs from authority tenant"
            )

    def _record(self, receipt: SpecialistOperationReceipt) -> SpecialistOperationReceipt:
        self._check_tenant(receipt.tenant_id)
        document = receipt.model_dump(mode="json")
        if document.get("uncertainty_type") is None:
            # Migration 247 stores the optional field only when it carries a reason;
            # omitting null keeps the PostgreSQL function compatible with migration 246.
            document.pop("uncertainty_type", None)
        fingerprint_payload = _fingerprint_payload(
            SPECIALIST_OPERATION_RECEIPT_SCHEMA,
            document,
            "receipt_sha256",
        )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT receipt_document, created
                    FROM gda_control.record_agentops_specialist_operation_receipt(
                        :tenant_id, :operation_ref,
                        CAST(:receipt_document AS jsonb),
                        :fingerprint_payload, :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "operation_ref": receipt.operation_ref,
                    "receipt_document": _json(document),
                    "fingerprint_payload": fingerprint_payload,
                    "recorded_by": self.recorded_by,
                },
            ).mappings().one()
        stored = self._receipt(row["receipt_document"])
        if stored != receipt and stored.model_dump(mode="json") != document:
            raise SpecialistOperationAuthorityConfigurationError(
                "specialist operation authority returned different receipt"
            )
        return stored

    def _current(self, operation_ref: str) -> SpecialistOperationReceipt | None:
        operation = _operation_ref(operation_ref)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT receipt_document
                    FROM gda_control.agentops_specialist_operation_receipt_current
                    WHERE tenant_id = :tenant_id AND operation_ref = :operation_ref
                    """
                ),
                {"tenant_id": self.tenant_id, "operation_ref": operation},
            ).mappings().one_or_none()
        return None if row is None else self._receipt(row["receipt_document"])

    def observe(self, operation_ref: str) -> SpecialistOperationObservation | None:
        current = self._current(operation_ref)
        return None if current is None else self._observation(current)

    def submit(
        self,
        request: TemporalActivityRequest,
        *,
        provider_ref: str,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistOperationReceipt:
        self._check_tenant(request.tenant_id)
        operation = _operation_ref(operation_ref)
        if not str(provider_ref or "").strip() or not str(provider_receipt_ref or "").strip():
            raise SpecialistOperationAuthorityValidationError(
                "specialist operation provider and receipt references are required"
            )
        values: dict[str, Any] = {
            "tenant_id": request.tenant_id,
            "workflow_id": request.workflow_id,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "tool_call_id": request.tool_call_id,
            "activity_id": request.activity_id,
            "attempt_no": request.attempt_no,
            "request_sha256": request.request_sha256,
            "provider_ref": str(provider_ref).strip(),
            "operation_ref": operation,
            "provider_receipt_ref": str(provider_receipt_ref).strip(),
            "status": SpecialistOperationStatus.SUBMITTED,
            "output_artifact_id": None,
            "failure_type": None,
            "cancellation_requested": False,
        }
        values["receipt_sha256"] = SpecialistOperationReceipt.fingerprint(values)
        return self._record(SpecialistOperationReceipt(**values))

    def _transition(
        self,
        operation_ref: str,
        status: SpecialistOperationStatus,
        *,
        output_artifact_id: UUID | None = None,
        failure_type: str | None = None,
        cancellation_requested: bool | None = None,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistOperationReceipt:
        current = self._current(operation_ref)
        if current is None:
            raise SpecialistOperationAuthorityConflictError(
                "specialist provider operation receipt is not registered"
            )
        values = current.model_dump(mode="python")
        values.update(
            {
                "status": status,
                "output_artifact_id": output_artifact_id,
                "failure_type": failure_type,
                "uncertainty_type": (
                    None
                    if status
                    in {
                        SpecialistOperationStatus.SUCCEEDED,
                        SpecialistOperationStatus.FAILED,
                        SpecialistOperationStatus.CANCELLED,
                    }
                    else (
                        current.uncertainty_type
                        if uncertainty_type is None
                        else uncertainty_type
                    )
                ),
                "cancellation_requested": (
                    current.cancellation_requested
                    if cancellation_requested is None
                    else cancellation_requested
                ),
            }
        )
        values["receipt_sha256"] = SpecialistOperationReceipt.fingerprint(values)
        return self._record(SpecialistOperationReceipt(**values))

    def succeed(self, operation_ref: str, output_artifact_id: UUID) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.SUCCEEDED,
            output_artifact_id=output_artifact_id,
        )

    def fail(self, operation_ref: str, failure_type: str) -> SpecialistOperationReceipt:
        if not str(failure_type or "").strip():
            raise SpecialistOperationAuthorityValidationError("failure_type is required")
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.FAILED,
            failure_type=str(failure_type).strip(),
        )

    def cancel(
        self, operation_ref: str, failure_type: str = "ProviderCancelled"
    ) -> SpecialistOperationReceipt:
        if not str(failure_type or "").strip():
            raise SpecialistOperationAuthorityValidationError("failure_type is required")
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.CANCELLED,
            failure_type=str(failure_type).strip(),
        )

    def request_cancellation(
        self,
        operation_ref: str,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.UNKNOWN,
            cancellation_requested=True,
            uncertainty_type=uncertainty_type,
        )

    def history(
        self, operation_ref: str, *, limit: int = 100
    ) -> tuple[SpecialistOperationReceipt, ...]:
        operation = _operation_ref(operation_ref)
        if not 1 <= limit <= 10_000:
            raise SpecialistOperationAuthorityValidationError(
                "specialist operation history limit must be 1..10000"
            )
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT receipt_document
                    FROM gda_control.agentops_specialist_operation_receipt_history
                    WHERE tenant_id = :tenant_id AND operation_ref = :operation_ref
                    ORDER BY receipt_sequence
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "operation_ref": operation,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(self._receipt(row["receipt_document"]) for row in rows)


__all__ = [
    "AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION",
    "AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION",
    "PostgresSpecialistOperationAuthority",
    "SpecialistOperationAuthorityConfigurationError",
    "SpecialistOperationAuthorityConflictError",
    "SpecialistOperationAuthorityError",
    "SpecialistOperationAuthorityForbiddenError",
    "SpecialistOperationAuthorityValidationError",
]
