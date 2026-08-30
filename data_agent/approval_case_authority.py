"""Tenant-scoped PostgreSQL authority for generic ApprovalCase lifecycle."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .platform_contracts import (
    ApprovalAssignmentActorAccess,
    ApprovalAvailabilityStatus,
    ApprovalCase,
    ApprovalCaseAssignment,
    ApprovalCaseAssignmentEvent,
    ApprovalCaseAssignmentOperation,
    ApprovalCaseEscalation,
    ApprovalCaseEscalationPlan,
    ApprovalCaseEvent,
    ApprovalCaseNotification,
    ApprovalCaseNotificationEnvelope,
    ApprovalCaseNotificationRecoveryEvent,
    ApprovalCaseStatus,
    ApprovalPrincipal,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    ApprovalTeamMembership,
    Resource,
    ShortName,
    TenantId,
    approval_case_escalation_idempotency_key,
)

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
AUTHORITY_SYSTEM = "gda_control"
_TENANT_ADAPTER = TypeAdapter(TenantId)
_ACTION_ADAPTER = TypeAdapter(ShortName)


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


@dataclass(frozen=True)
class ApprovalCasePage:
    items: tuple[ApprovalCase, ...]
    offset: int
    limit: int
    has_more: bool


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
    def _assignment_from_row(row) -> ApprovalCaseAssignment:
        return ApprovalCaseAssignment.model_validate(dict(row))

    @staticmethod
    def _assignment_event_from_row(row) -> ApprovalCaseAssignmentEvent:
        return ApprovalCaseAssignmentEvent.model_validate(dict(row))

    @staticmethod
    def _principal_from_row(row) -> ApprovalPrincipal:
        return ApprovalPrincipal.model_validate(dict(row))

    @staticmethod
    def _membership_from_row(row) -> ApprovalTeamMembership:
        return ApprovalTeamMembership.model_validate(dict(row))

    @staticmethod
    def _notification_from_row(row) -> ApprovalCaseNotification:
        return ApprovalCaseNotification.model_validate(dict(row))

    @staticmethod
    def _notification_recovery_from_row(row) -> ApprovalCaseNotificationRecoveryEvent:
        return ApprovalCaseNotificationRecoveryEvent.model_validate(dict(row))

    @staticmethod
    def _escalation_from_row(row) -> ApprovalCaseEscalation:
        return ApprovalCaseEscalation.model_validate(dict(row))

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

    @classmethod
    def _load_event(
        cls,
        connection,
        tenant_id: str,
        approval_case_ref: str,
        sequence_no: int,
    ) -> ApprovalCaseEvent | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, approval_event_id, approval_case_ref,
                           sequence_no, from_status, to_status,
                           actor_subject, reason, details, occurred_at
                    FROM gda_control.approval_case_event
                    WHERE tenant_id = :tenant_id
                      AND approval_case_ref = :approval_case_ref
                      AND sequence_no = :sequence_no
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "approval_case_ref": approval_case_ref,
                    "sequence_no": sequence_no,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._event_from_row(row) if row is not None else None

    @classmethod
    def _notification_envelope(
        cls,
        connection,
        notification: ApprovalCaseNotification,
    ) -> ApprovalCaseNotificationEnvelope:
        approval_case = cls._load(
            connection,
            notification.tenant_id,
            notification.approval_case_ref,
        )
        if approval_case is None:
            raise ApprovalCaseNotFoundError("ApprovalCase notification binding was not found")
        event = None
        if notification.approval_event_sequence_no is not None:
            event = cls._load_event(
                connection,
                notification.tenant_id,
                notification.approval_case_ref,
                notification.approval_event_sequence_no,
            )
            if event is None:
                raise ApprovalCaseNotFoundError(
                    "ApprovalCase notification event was not found"
                )
        return ApprovalCaseNotificationEnvelope(
            notification=notification,
            approval_case=approval_case,
            event=event,
        )

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

    def list(
        self,
        tenant_id: str,
        *,
        status: ApprovalCaseStatus | None = None,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ApprovalCasePage:
        """Return one bounded tenant inbox page ordered newest first."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 100:
            raise ValueError("approval case query limit must be between 1 and 100")
        if not 0 <= offset <= 10_000:
            raise ValueError("approval case query offset must be between 0 and 10000")
        normalized_status = ApprovalCaseStatus(status).value if status is not None else None
        normalized_action = (
            _ACTION_ADAPTER.validate_python(action) if action is not None else None
        )

        with self._transaction(tenant) as connection:
            rows = (
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
                          AND status = COALESCE(CAST(:status AS text), status)
                          AND action = COALESCE(CAST(:action AS text), action)
                        ORDER BY requested_at DESC, approval_case_ref DESC
                        LIMIT :row_limit OFFSET :offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "status": normalized_status,
                        "action": normalized_action,
                        "row_limit": limit + 1,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        return ApprovalCasePage(
            items=tuple(self._from_row(row) for row in rows[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

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

    def expire(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        expected_state_version: int,
        actor_subject: str = "workload:agentops-temporal-expiry",
        reason: str = "ApprovalCase expired without an authoritative human decision",
        details: dict[str, Any] | None = None,
    ) -> ApprovalCase:
        """Atomically cancel one expired pending case in PostgreSQL.

        The database function locks the case row and evaluates expiry with its own
        clock.  This method deliberately does not perform a client-side expiry check:
        a human decision and timeout must be resolved by the same row lock.
        """

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if expected_state_version < 0:
            raise ValueError("expected_state_version must be non-negative")
        if not actor_subject.startswith(("workload:", "agent:")):
            raise ValueError("ApprovalCase expiry requires a workload or agent actor")
        if not reason.strip():
            raise ValueError("ApprovalCase expiry reason is required")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.expire_approval_case(
                        :tenant_id, :approval_case_ref, :expected_state_version,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "approval_case_ref": approval_case_ref,
                    "expected_state_version": expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details or {}),
                },
            ).scalar_one()
            stored = self._load(connection, tenant, approval_case_ref)
            if stored is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not visible after expiry")
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

    def assignment(
        self,
        tenant_id: str,
        approval_case_ref: str,
    ) -> ApprovalCaseAssignment | None:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load(connection, tenant, approval_case_ref) is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, approval_case_ref, assignment_version,
                               status, assignee_subject, last_actor_subject,
                               last_reason, delegation_depth, assigned_at,
                               updated_at, closed_at
                        FROM gda_control.approval_case_assignment
                        WHERE tenant_id = :tenant_id
                          AND approval_case_ref = :approval_case_ref
                        """
                    ),
                    {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
                )
                .mappings()
                .one_or_none()
            )
            return self._assignment_from_row(row) if row is not None else None

    def assignment_events(
        self,
        tenant_id: str,
        approval_case_ref: str,
    ) -> tuple[ApprovalCaseAssignmentEvent, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load(connection, tenant, approval_case_ref) is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, assignment_event_id,
                               approval_case_ref, assignment_version, action,
                               from_assignee_subject, to_assignee_subject,
                               actor_subject, reason, delegation_depth,
                               occurred_at
                        FROM gda_control.approval_case_assignment_event
                        WHERE tenant_id = :tenant_id
                          AND approval_case_ref = :approval_case_ref
                        ORDER BY assignment_version
                        """
                    ),
                    {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
                )
                .mappings()
                .all()
            )
            return tuple(self._assignment_event_from_row(row) for row in rows)

    def transition_assignment(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        expected_assignment_version: int,
        operation: ApprovalCaseAssignmentOperation,
        actor_subject: str,
        assignee_subject: str | None,
        reason: str,
    ) -> ApprovalCaseAssignment:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        operation = ApprovalCaseAssignmentOperation(operation)
        if expected_assignment_version < 0:
            raise ValueError("expected assignment version must be non-negative")
        if not actor_subject.startswith("human:"):
            raise ValueError("approval assignment requires a human actor")
        if not reason.strip():
            raise ValueError("approval assignment reason is required")
        if operation is ApprovalCaseAssignmentOperation.RELEASE:
            if assignee_subject is not None:
                raise ValueError("release must not include an assignee")
        elif assignee_subject is None or not assignee_subject.startswith(
            ("human:", "team:")
        ):
            raise ValueError("approval assignment requires a human or team assignee")
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.transition_approval_case_assignment(
                            :tenant_id, :approval_case_ref,
                            :expected_assignment_version, :operation,
                            :actor_subject, :assignee_subject, :reason
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "approval_case_ref": approval_case_ref,
                        "expected_assignment_version": expected_assignment_version,
                        "operation": operation.value,
                        "actor_subject": actor_subject,
                        "assignee_subject": assignee_subject,
                        "reason": reason,
                    },
                )
                .mappings()
                .one()
            )
            return self._assignment_from_row(row)

    def list_principals(
        self,
        tenant_id: str,
        *,
        eligible_only: bool = False,
    ) -> tuple[ApprovalPrincipal, ...]:
        """Return the tenant approval directory with current eligibility facts."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT principal.tenant_id, principal.principal_subject,
                               principal.principal_type, principal.display_name,
                               principal.directory_version, principal.status,
                               principal.approval_eligible,
                               principal.availability_status,
                               principal.valid_from, principal.valid_until,
                               principal.last_actor_subject, principal.last_reason,
                               principal.updated_at,
                               eligibility.reason = 'eligible' AS eligible_now,
                               eligibility.reason AS eligibility_reason
                        FROM gda_control.approval_principal AS principal
                        CROSS JOIN LATERAL (
                            SELECT gda_control.approval_principal_eligibility_reason(
                                principal.tenant_id,
                                principal.principal_subject,
                                clock_timestamp()
                            ) AS reason
                        ) AS eligibility
                        WHERE principal.tenant_id = :tenant_id
                          AND (
                              NOT :eligible_only
                              OR eligibility.reason = 'eligible'
                          )
                        ORDER BY principal.principal_type,
                                 principal.display_name,
                                 principal.principal_subject
                        """
                    ),
                    {"tenant_id": tenant, "eligible_only": eligible_only},
                )
                .mappings()
                .all()
            )
            return tuple(self._principal_from_row(row) for row in rows)

    def upsert_principal(
        self,
        *,
        tenant_id: str,
        principal_subject: str,
        expected_directory_version: int,
        principal_type: ApprovalPrincipalType,
        display_name: str,
        status: ApprovalPrincipalStatus,
        approval_eligible: bool,
        availability_status: ApprovalAvailabilityStatus,
        valid_from: datetime,
        valid_until: datetime | None,
        actor_subject: str,
        reason: str,
    ) -> ApprovalPrincipal:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        principal_type = ApprovalPrincipalType(principal_type)
        status = ApprovalPrincipalStatus(status)
        availability_status = ApprovalAvailabilityStatus(availability_status)
        if not principal_subject.startswith(f"{principal_type.value}:"):
            raise ValueError("approval principal type must match its typed subject")
        if expected_directory_version < 0:
            raise ValueError("expected directory version must be non-negative")
        if not actor_subject.startswith("human:") or not reason.strip():
            raise ValueError("approval principal update requires a human actor and reason")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.upsert_approval_principal(
                        :tenant_id, :principal_subject,
                        :expected_directory_version, :display_name, :status,
                        :approval_eligible, :availability_status,
                        :valid_from, :valid_until, :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "principal_subject": principal_subject,
                    "expected_directory_version": expected_directory_version,
                    "display_name": display_name,
                    "status": status.value,
                    "approval_eligible": approval_eligible,
                    "availability_status": availability_status.value,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).one()
            row = (
                connection.execute(
                    text(
                        """
                        SELECT principal.*,
                               eligibility.reason = 'eligible' AS eligible_now,
                               eligibility.reason AS eligibility_reason
                        FROM gda_control.approval_principal AS principal
                        CROSS JOIN LATERAL (
                            SELECT gda_control.approval_principal_eligibility_reason(
                                principal.tenant_id,
                                principal.principal_subject,
                                clock_timestamp()
                            ) AS reason
                        ) AS eligibility
                        WHERE principal.tenant_id = :tenant_id
                          AND principal.principal_subject = :principal_subject
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "principal_subject": principal_subject,
                    },
                )
                .mappings()
                .one()
            )
            return self._principal_from_row(row)

    def upsert_team_membership(
        self,
        *,
        tenant_id: str,
        team_subject: str,
        member_subject: str,
        expected_membership_version: int,
        status: ApprovalPrincipalStatus,
        can_delegate: bool,
        valid_from: datetime,
        valid_until: datetime | None,
        actor_subject: str,
        reason: str,
    ) -> ApprovalTeamMembership:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        status = ApprovalPrincipalStatus(status)
        if expected_membership_version < 0:
            raise ValueError("expected membership version must be non-negative")
        if not team_subject.startswith("team:") or not member_subject.startswith("human:"):
            raise ValueError("approval team membership requires team and human subjects")
        if not actor_subject.startswith("human:") or not reason.strip():
            raise ValueError("approval membership update requires a human actor and reason")
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.upsert_approval_team_member(
                            :tenant_id, :team_subject, :member_subject,
                            :expected_membership_version, :status,
                            :can_delegate, :valid_from, :valid_until,
                            :actor_subject, :reason
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "team_subject": team_subject,
                        "member_subject": member_subject,
                        "expected_membership_version": expected_membership_version,
                        "status": status.value,
                        "can_delegate": can_delegate,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "actor_subject": actor_subject,
                        "reason": reason,
                    },
                )
                .mappings()
                .one()
            )
            return self._membership_from_row(row)

    def list_team_memberships(
        self,
        tenant_id: str,
        team_subject: str,
    ) -> tuple[ApprovalTeamMembership, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not team_subject.startswith("team:"):
            raise ValueError("approval membership query requires a team subject")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, team_subject, member_subject,
                               membership_version, status, can_delegate,
                               valid_from, valid_until, last_actor_subject,
                               last_reason, updated_at
                        FROM gda_control.approval_team_member
                        WHERE tenant_id = :tenant_id
                          AND team_subject = :team_subject
                        ORDER BY member_subject
                        """
                    ),
                    {"tenant_id": tenant, "team_subject": team_subject},
                )
                .mappings()
                .all()
            )
            return tuple(self._membership_from_row(row) for row in rows)

    def assignment_actor_access(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        actor_subject: str,
    ) -> ApprovalAssignmentActorAccess:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not actor_subject.startswith("human:"):
            raise ValueError("approval assignment access requires a human actor")
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT :actor_subject AS actor_subject,
                               access.can_decide,
                               access.can_delegate,
                               access.access_reason
                        FROM gda_control.approval_assignment_actor_access(
                            :tenant_id, :approval_case_ref, :actor_subject,
                            clock_timestamp()
                        ) AS access
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "approval_case_ref": approval_case_ref,
                        "actor_subject": actor_subject,
                    },
                )
                .mappings()
                .one()
            )
            return ApprovalAssignmentActorAccess.model_validate(dict(row))

    def schedule_sla_escalation(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        expected_state_version: int,
        escalation_stage: int,
        due_at: datetime,
        target_team_subject: str,
        on_call_ref: str,
        actor_subject: str,
        reason: str,
    ) -> ApprovalCaseEscalation:
        """Schedule one immutable, pre-expiry escalation for a live case."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            case = self._load(connection, tenant, approval_case_ref)
            if case is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            idempotency_key = approval_case_escalation_idempotency_key(
                tenant_id=tenant,
                approval_case_ref=approval_case_ref,
                expected_state_version=expected_state_version,
                action=case.action,
                target_fingerprint=case.target_fingerprint,
                escalation_stage=escalation_stage,
                due_at=due_at,
                target_team_subject=target_team_subject,
                on_call_ref=on_call_ref,
            )
            plan = ApprovalCaseEscalationPlan(
                tenant_id=tenant,
                approval_case_ref=approval_case_ref,
                expected_state_version=expected_state_version,
                action=case.action,
                target_fingerprint=case.target_fingerprint,
                escalation_stage=escalation_stage,
                due_at=due_at,
                target_team_subject=target_team_subject,
                on_call_ref=on_call_ref,
                actor_subject=actor_subject,
                reason=reason,
                idempotency_key=idempotency_key,
            )
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.schedule_approval_case_sla_escalation(
                            :tenant_id, :approval_case_ref, :expected_state_version,
                            :escalation_stage, :due_at, :target_team_subject,
                            :on_call_ref, :actor_subject, :reason, :idempotency_key
                        )
                        """
                    ),
                    plan.model_dump(mode="python"),
                )
                .mappings()
                .one()
            )
            return self._escalation_from_row(row)

    def notifications(
        self,
        tenant_id: str,
        approval_case_ref: str,
    ) -> tuple[ApprovalCaseNotification, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load(connection, tenant, approval_case_ref) is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, notification_id, approval_case_ref,
                               approval_event_sequence_no, notification_kind,
                               channel, destination_ref, delivery_order, status,
                               attempt_count, max_attempts, available_at,
                               claimed_by, claimed_until, last_error,
                               created_at, completed_at, recovery_count,
                               last_recovered_by, last_recovery_reason,
                               last_recovered_at, escalation_stage,
                               escalation_target_subject, escalation_on_call_ref,
                               escalation_actor_subject, escalation_reason,
                               idempotency_key
                        FROM gda_control.approval_case_notification_outbox
                        WHERE tenant_id = :tenant_id
                          AND approval_case_ref = :approval_case_ref
                        ORDER BY delivery_order, created_at, notification_id
                        """
                    ),
                    {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
                )
                .mappings()
                .all()
            )
            return tuple(self._notification_from_row(row) for row in rows)

    def materialize_sla_escalations(
        self,
        tenant_id: str,
        *,
        limit: int = 20,
    ) -> tuple[ApprovalCaseNotificationEnvelope, ...]:
        """Move due scheduled escalations into the durable notification outbox."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 100:
            raise ValueError("escalation materialization limit must be between 1 and 100")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.materialize_due_approval_case_sla_escalations(
                            :tenant_id, :limit
                        )
                        """
                    ),
                    {"tenant_id": tenant, "limit": limit},
                )
                .mappings()
                .all()
            )
            return tuple(
                self._notification_envelope(
                    connection,
                    self._notification_from_row(row),
                )
                for row in rows
            )

    def notification_recoveries(
        self,
        tenant_id: str,
        approval_case_ref: str,
    ) -> tuple[ApprovalCaseNotificationRecoveryEvent, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load(connection, tenant, approval_case_ref) is None:
                raise ApprovalCaseNotFoundError("ApprovalCase was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, recovery_event_id, notification_id,
                               approval_case_ref, recovery_no, actor_subject,
                               reason, previous_attempt_count,
                               previous_last_error, occurred_at
                        FROM gda_control.approval_case_notification_recovery_event
                        WHERE tenant_id = :tenant_id
                          AND approval_case_ref = :approval_case_ref
                        ORDER BY occurred_at, recovery_event_id
                        """
                    ),
                    {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
                )
                .mappings()
                .all()
            )
            return tuple(self._notification_recovery_from_row(row) for row in rows)

    def retry_notification(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        notification_id: UUID,
        expected_attempt_count: int,
        actor_subject: str,
        reason: str,
    ) -> ApprovalCaseNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if expected_attempt_count < 1:
            raise ValueError("expected notification attempt count must be positive")
        if not actor_subject.startswith("human:"):
            raise ValueError("notification recovery requires a human identity")
        if not reason.strip():
            raise ValueError("notification recovery reason is required")
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.retry_approval_case_notification(
                            :tenant_id, :approval_case_ref, :notification_id,
                            :expected_attempt_count, :actor_subject, :reason
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "approval_case_ref": approval_case_ref,
                        "notification_id": notification_id,
                        "expected_attempt_count": expected_attempt_count,
                        "actor_subject": actor_subject,
                        "reason": reason,
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)

    def claim_notifications(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[ApprovalCaseNotificationEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 100:
            raise ValueError("notification claim limit must be between 1 and 100")
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("notification lease must be between 5 and 3600 seconds")
        if not worker_id.strip():
            raise ValueError("notification worker identity is required")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_approval_case_notifications(
                            :tenant_id, :worker_id, :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._notification_envelope(
                    connection,
                    self._notification_from_row(row),
                )
                for row in rows
            )

    def complete_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
    ) -> ApprovalCaseNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.complete_approval_case_notification(
                            :tenant_id, :notification_id, :worker_id
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)

    def fail_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> ApprovalCaseNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.fail_approval_case_notification(
                            :tenant_id, :notification_id, :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)
