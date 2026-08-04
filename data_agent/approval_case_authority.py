"""Tenant-scoped PostgreSQL authority for generic ApprovalCase lifecycle."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseEvent,
    ApprovalCaseStatus,
    Resource,
    TenantId,
)

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
AUTHORITY_SYSTEM = "gda_control"
_TENANT_ADAPTER = TypeAdapter(TenantId)


class ApprovalCaseAuthorityError(RuntimeError):
    """Base error for ApprovalCase persistence and lifecycle operations."""

    code = "approval_case_error"


class ApprovalCaseConflictError(ApprovalCaseAuthorityError):
    """An immutable case binding or state version conflicts with stored truth."""

    code = "approval_case_conflict"


class ApprovalCaseNotFoundError(ApprovalCaseAuthorityError):
    """The requested case is absent or hidden by tenant isolation."""

    code = "approval_case_not_found"


class ApprovalCaseForbiddenError(ApprovalCaseAuthorityError):
    """Tenant context or database policy rejected the operation."""

    code = "approval_case_forbidden"


class ApprovalCaseValidationError(ApprovalCaseAuthorityError):
    """The requested ApprovalCase operation violates its contract."""

    code = "approval_case_validation_error"


class ApprovalCaseConfigurationError(ApprovalCaseAuthorityError):
    """The configured database cannot enforce the ApprovalCase contract."""

    code = "approval_case_unavailable"


@dataclass(frozen=True)
class ApprovalCaseWriteResult:
    approval_case: ApprovalCase
    created: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def approval_case_resource(case: ApprovalCase, *, owner_ref: str) -> Resource:
    """Build the canonical Resource projection owned by this authority."""

    return Resource(
        tenant_id=case.tenant_id,
        resource_urn=case.approval_case_ref,
        resource_kind="approval_case",
        authority_system=AUTHORITY_SYSTEM,
        authority_locator=case.approval_case_ref,
        owner_ref=owner_ref,
        governance_ref={
            "target_resource_urn": case.target_resource_urn,
            "target_fingerprint": case.target_fingerprint,
            "action": case.action,
        },
    )


class ApprovalCaseAuthority:
    """PostgreSQL authority using the existing platform gateway role and RLS."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ApprovalCaseConfigurationError("ApprovalCase authority requires PostgreSQL")
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
                        raise ApprovalCaseConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except ApprovalCaseAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise ApprovalCaseConflictError("ApprovalCase state conflict") from exc
            if state == "P0002":
                raise ApprovalCaseNotFoundError("ApprovalCase was not found") from exc
            if state == "42501":
                raise ApprovalCaseForbiddenError("ApprovalCase tenant access was denied") from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise ApprovalCaseValidationError("ApprovalCase contract was rejected") from exc
            raise ApprovalCaseAuthorityError("ApprovalCase database operation failed") from exc
        except SQLAlchemyError as exc:
            raise ApprovalCaseAuthorityError("ApprovalCase database operation failed") from exc

    @staticmethod
    def _from_row(row) -> ApprovalCase:
        value = dict(row)
        value["request_context"] = _json_value(value["request_context"])
        return ApprovalCase.model_validate(value)

    @staticmethod
    def _event_from_row(row) -> ApprovalCaseEvent:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return ApprovalCaseEvent.model_validate(value)

    @staticmethod
    def _request_binding(case: ApprovalCase) -> tuple[Any, ...]:
        return (
            case.tenant_id,
            case.approval_case_ref,
            case.target_resource_urn,
            case.target_fingerprint,
            case.action,
            case.requester_subject,
            case.request_reason,
            case.request_context,
            case.requested_at,
            case.expires_at,
        )

    @classmethod
    def _load(cls, connection, tenant_id: str, approval_case_ref: str) -> ApprovalCase | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, approval_case_ref, target_resource_urn,
                           target_fingerprint, action, requester_subject,
                           request_reason, request_context, status, state_version,
                           requested_at, expires_at, decided_by,
                           decision_reason, decided_at
                    FROM gda_control.approval_case
                    WHERE tenant_id = :tenant_id
                      AND approval_case_ref = :approval_case_ref
                    """
                ),
                {"tenant_id": tenant_id, "approval_case_ref": approval_case_ref},
            )
            .mappings()
            .one_or_none()
        )
        return cls._from_row(row) if row is not None else None

    @staticmethod
    def _load_resource(connection, tenant_id: str, resource_urn: str) -> Resource | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, resource_urn, resource_kind,
                           authority_system, authority_locator, owner_ref,
                           governance_ref, technical_refs
                    FROM gda_control.resource
                    WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn
                    """
                ),
                {"tenant_id": tenant_id, "resource_urn": resource_urn},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["governance_ref"] = _json_value(value["governance_ref"])
        value["technical_refs"] = _json_value(value["technical_refs"])
        return Resource.model_validate(value)

    def create(self, case: ApprovalCase, *, owner_ref: str) -> ApprovalCaseWriteResult:
        if case.status is not ApprovalCaseStatus.PENDING or case.state_version != 0:
            raise ValueError("ApprovalCase creation requires initial pending state")
        resource = approval_case_resource(case, owner_ref=owner_ref)
        with self._transaction(case.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind, authority_system,
                        authority_locator, owner_ref, governance_ref, technical_refs
                    ) VALUES (
                        :tenant_id, :resource_urn, :resource_kind, :authority_system,
                        :authority_locator, :owner_ref,
                        CAST(:governance_ref AS jsonb), CAST(:technical_refs AS jsonb)
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    **resource.model_dump(
                        mode="json",
                        exclude={"governance_ref", "technical_refs"},
                    ),
                    "governance_ref": _json(resource.governance_ref),
                    "technical_refs": _json(list(resource.technical_refs)),
                },
            )
            stored_resource = self._load_resource(
                connection,
                case.tenant_id,
                case.approval_case_ref,
            )
            if stored_resource != resource:
                raise ApprovalCaseConflictError(
                    "ApprovalCase Resource identity already has different evidence"
                )

            inserted = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.approval_case (
                        tenant_id, approval_case_ref, target_resource_urn,
                        target_fingerprint, action, requester_subject,
                        request_reason, request_context, status, state_version,
                        requested_at, expires_at, updated_at
                    ) VALUES (
                        :tenant_id, :approval_case_ref, :target_resource_urn,
                        :target_fingerprint, :action, :requester_subject,
                        :request_reason, CAST(:request_context AS jsonb),
                        :status, :state_version, :requested_at, :expires_at,
                        :requested_at
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING approval_case_ref
                    """
                ),
                {
                    **case.model_dump(mode="python", exclude={"request_context"}),
                    "request_context": _json(case.request_context),
                    "status": case.status.value,
                },
            ).first()
            stored = self._load(connection, case.tenant_id, case.approval_case_ref)
            if stored is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not visible after insert")
            if self._request_binding(stored) != self._request_binding(case):
                raise ApprovalCaseConflictError(
                    "ApprovalCase identity already has different evidence"
                )
            return ApprovalCaseWriteResult(stored, inserted is not None)

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load(connection, tenant, approval_case_ref)
            if stored is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            return stored

    def decide(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        expected_state_version: int,
        verdict: ApprovalCaseStatus,
        actor_subject: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> ApprovalCase:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if expected_state_version < 0:
            raise ValueError("expected_state_version must be non-negative")
        verdict = ApprovalCaseStatus(verdict)
        if verdict is ApprovalCaseStatus.PENDING:
            raise ValueError("ApprovalCase decision must be terminal")
        if not actor_subject.strip() or not reason.strip():
            raise ValueError("actor_subject and reason are required")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_approval_case(
                        :tenant_id, :approval_case_ref, :expected_state_version,
                        :verdict, :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "approval_case_ref": approval_case_ref,
                    "expected_state_version": expected_state_version,
                    "verdict": verdict.value,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details or {}),
                },
            ).scalar_one()
            stored = self._load(connection, tenant, approval_case_ref)
            if stored is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            return stored

    def events(self, tenant_id: str, approval_case_ref: str) -> tuple[ApprovalCaseEvent, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load(connection, tenant, approval_case_ref) is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, approval_event_id, approval_case_ref,
                               sequence_no, from_status, to_status,
                               actor_subject, reason, details, occurred_at
                        FROM gda_control.approval_case_event
                        WHERE tenant_id = :tenant_id
                          AND approval_case_ref = :approval_case_ref
                        ORDER BY sequence_no
                        """
                    ),
                    {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
                )
                .mappings()
                .all()
            )
            return tuple(self._event_from_row(row) for row in rows)
