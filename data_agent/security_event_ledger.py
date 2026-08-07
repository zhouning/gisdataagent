"""Tenant-scoped immutable security event ledger."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine

SECURITY_LEDGER_DATABASE_ROLE = "gda_control_gateway"
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,127}$")
_ACTOR_RE = re.compile(r"^(human|workload|agent):\S+$")
_PHASE_OUTCOMES = {
    "admitted": frozenset({"admitted"}),
    "outcome": frozenset({"success", "failure"}),
    "denied": frozenset({"denied"}),
}


class SecurityEventLedgerError(RuntimeError):
    code = "security_ledger_error"


class SecurityEventLedgerUnavailableError(SecurityEventLedgerError):
    code = "security_ledger_unavailable"


class SecurityEventLedgerConfigurationError(SecurityEventLedgerError):
    code = "security_ledger_configuration_error"


class SecurityEventLedgerForbiddenError(SecurityEventLedgerError):
    code = "security_ledger_forbidden"


class SecurityEventLedgerConflictError(SecurityEventLedgerError):
    code = "security_ledger_conflict"


class SecurityEventLedgerValidationError(SecurityEventLedgerError):
    code = "security_ledger_validation_error"


@dataclass(frozen=True)
class SecurityEvent:
    tenant_id: str
    event_id: UUID
    sequence_no: int
    attempt_id: UUID
    phase: str
    action: str
    outcome: str
    actor_subject: str
    resource_ref: str
    reason: str
    details: dict[str, Any]
    previous_event_sha256: str | None
    event_sha256: str
    occurred_at: datetime
    inserted: bool = True


@dataclass(frozen=True)
class SecurityOperationReceipt:
    tenant_id: str
    receipt_id: UUID
    attempt_id: UUID
    action: str
    resource_ref: str
    receipt_type: str
    receipt_sha256: str
    evidence: dict[str, Any]
    recorded_by: str
    recorded_at: datetime
    inserted: bool = True


def _event_from_row(row: Any, *, inserted: bool = False) -> SecurityEvent:
    return SecurityEvent(
        tenant_id=row["tenant_id"],
        event_id=row["event_id"],
        sequence_no=int(row["sequence_no"]),
        attempt_id=row["attempt_id"],
        phase=row["phase"],
        action=row["action"],
        outcome=row["outcome"],
        actor_subject=row["actor_subject"],
        resource_ref=row["resource_ref"],
        reason=row["reason"],
        details=row["details"],
        previous_event_sha256=row["previous_event_sha256"],
        event_sha256=row["event_sha256"],
        occurred_at=row["occurred_at"],
        inserted=inserted,
    )


def _sqlstate(error: DBAPIError) -> str | None:
    original = getattr(error, "orig", None)
    return getattr(original, "pgcode", None) or getattr(original, "sqlstate", None)


def _validate_text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SecurityEventLedgerValidationError(f"invalid {field}")
    return value.strip()


class SecurityEventLedger:
    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None:
            raise SecurityEventLedgerUnavailableError(
                "security ledger database is not configured"
            )
        if engine.dialect.name != "postgresql":
            raise SecurityEventLedgerConfigurationError(
                "security ledger requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        if not isinstance(tenant_id, str) or not _TENANT_RE.fullmatch(tenant_id):
            raise SecurityEventLedgerValidationError("invalid tenant_id")
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{SECURITY_LEDGER_DATABASE_ROLE}"'
                        )
                    except DBAPIError as error:
                        raise SecurityEventLedgerConfigurationError(
                            "database login is not a member of the security ledger role"
                        ) from error
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                        {"tenant_id": tenant_id},
                    )
                    yield connection
        except SecurityEventLedgerError:
            raise
        except DBAPIError as error:
            state = _sqlstate(error)
            if state == "42501":
                raise SecurityEventLedgerForbiddenError(
                    "security ledger tenant access was denied"
                ) from error
            if state in {"40001", "23505"}:
                raise SecurityEventLedgerConflictError(
                    "security event idempotency conflict"
                ) from error
            if state in {"22023", "22P02", "23502", "23514"}:
                raise SecurityEventLedgerValidationError(
                    "security event was rejected"
                ) from error
            raise SecurityEventLedgerUnavailableError(
                "security ledger database operation failed"
            ) from error
        except SQLAlchemyError as error:
            raise SecurityEventLedgerUnavailableError(
                "security ledger database operation failed"
            ) from error

    @staticmethod
    def _validate_event(
        *,
        attempt_id: UUID,
        phase: str,
        action: str,
        outcome: str,
        actor_subject: str,
        resource_ref: str,
        reason: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        if phase not in _PHASE_OUTCOMES or outcome not in _PHASE_OUTCOMES[phase]:
            raise SecurityEventLedgerValidationError("invalid phase/outcome")
        if not isinstance(action, str) or not _ACTION_RE.fullmatch(action):
            raise SecurityEventLedgerValidationError("invalid action")
        if not isinstance(actor_subject, str) or not _ACTOR_RE.fullmatch(actor_subject):
            raise SecurityEventLedgerValidationError("invalid actor_subject")
        resource_ref = _validate_text(resource_ref, "resource_ref", 512)
        reason = _validate_text(reason, "reason", 512)
        if not isinstance(details, dict):
            raise SecurityEventLedgerValidationError("details must be an object")
        try:
            details_json = json.dumps(
                details,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise SecurityEventLedgerValidationError(
                "details must contain JSON values"
            ) from error
        return {
            "attempt_id": attempt_id,
            "phase": phase,
            "action": action,
            "outcome": outcome,
            "actor_subject": actor_subject,
            "resource_ref": resource_ref,
            "reason": reason,
            "details": details_json,
        }

    def append(
        self,
        *,
        tenant_id: str,
        attempt_id: UUID,
        phase: str,
        action: str,
        outcome: str,
        actor_subject: str,
        resource_ref: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        event_details = {} if details is None else details
        params = self._validate_event(
            attempt_id=attempt_id,
            phase=phase,
            action=action,
            outcome=outcome,
            actor_subject=actor_subject,
            resource_ref=resource_ref,
            reason=reason,
            details=event_details,
        )
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT result_event_id, result_sequence_no,
                               result_previous_event_sha256,
                               result_event_sha256, result_occurred_at,
                               result_inserted
                        FROM gda_control.append_security_event(
                            :tenant_id,
                            :attempt_id,
                            :phase,
                            :action,
                            :outcome,
                            :actor_subject,
                            :resource_ref,
                            :reason,
                            CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {"tenant_id": tenant_id, **params},
                )
                .mappings()
                .one()
            )
            return SecurityEvent(
                tenant_id=tenant_id,
                event_id=row["result_event_id"],
                sequence_no=int(row["result_sequence_no"]),
                attempt_id=attempt_id,
                phase=phase,
                action=action,
                outcome=outcome,
                actor_subject=actor_subject,
                resource_ref=params["resource_ref"],
                reason=params["reason"],
                details=event_details,
                previous_event_sha256=row["result_previous_event_sha256"],
                event_sha256=row["result_event_sha256"],
                occurred_at=row["result_occurred_at"],
                inserted=bool(row["result_inserted"]),
            )

    def verify_chain(self, tenant_id: str) -> bool:
        with self._transaction(tenant_id) as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT gda_control.verify_security_event_chain(:tenant_id)"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

    @contextmanager
    def attempt_lock(
        self,
        tenant_id: str,
        attempt_id: UUID,
    ) -> Iterator[bool]:
        """Hold a non-blocking tenant/attempt lock for one execution boundary."""
        if not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        digest = hashlib.sha256(f"{tenant_id}:{attempt_id}".encode()).digest()
        lock_class = int.from_bytes(digest[:4], byteorder="big", signed=True)
        lock_object = int.from_bytes(digest[4:8], byteorder="big", signed=True)
        with self._transaction(tenant_id) as connection:
            acquired = bool(
                connection.execute(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        ":lock_class, :lock_object)"
                    ),
                    {"lock_class": lock_class, "lock_object": lock_object},
                ).scalar_one()
            )
            yield acquired

    def record_operation_receipt(
        self,
        *,
        tenant_id: str,
        attempt_id: UUID,
        action: str,
        resource_ref: str,
        receipt_type: str,
        evidence: dict[str, Any],
        recorded_by: str,
    ) -> SecurityOperationReceipt:
        resource_ref, evidence_json = self._validate_operation_receipt(
            attempt_id=attempt_id,
            action=action,
            resource_ref=resource_ref,
            receipt_type=receipt_type,
            evidence=evidence,
            recorded_by=recorded_by,
        )
        with self._transaction(tenant_id) as connection:
            return self._record_operation_receipt_on_connection(
                connection,
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                action=action,
                resource_ref=resource_ref,
                receipt_type=receipt_type,
                evidence=evidence,
                evidence_json=evidence_json,
                recorded_by=recorded_by,
            )

    @staticmethod
    def _validate_operation_receipt(
        *,
        attempt_id: UUID,
        action: str,
        resource_ref: str,
        receipt_type: str,
        evidence: dict[str, Any],
        recorded_by: str,
    ) -> tuple[str, str]:
        if not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        if not isinstance(action, str) or not _ACTION_RE.fullmatch(action):
            raise SecurityEventLedgerValidationError("invalid action")
        resource_ref = _validate_text(resource_ref, "resource_ref", 512)
        if not isinstance(receipt_type, str) or not _ACTION_RE.fullmatch(receipt_type):
            raise SecurityEventLedgerValidationError("invalid receipt_type")
        if not isinstance(recorded_by, str) or not _ACTOR_RE.fullmatch(recorded_by):
            raise SecurityEventLedgerValidationError("invalid recorded_by")
        if not isinstance(evidence, dict):
            raise SecurityEventLedgerValidationError("evidence must be an object")
        try:
            evidence_json = json.dumps(
                evidence,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise SecurityEventLedgerValidationError(
                "evidence must contain JSON values"
            ) from error
        return resource_ref, evidence_json

    @staticmethod
    def _record_operation_receipt_on_connection(
        connection,
        *,
        tenant_id: str,
        attempt_id: UUID,
        action: str,
        resource_ref: str,
        receipt_type: str,
        evidence: dict[str, Any],
        evidence_json: str,
        recorded_by: str,
    ) -> SecurityOperationReceipt:
        row = (
            connection.execute(
                text(
                    """
                    SELECT result_receipt_id, result_receipt_sha256,
                           result_recorded_at, result_inserted
                    FROM gda_control.record_security_operation_receipt(
                        :tenant_id,
                        :attempt_id,
                        :action,
                        :resource_ref,
                        :receipt_type,
                        CAST(:evidence AS jsonb),
                        :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "attempt_id": attempt_id,
                    "action": action,
                    "resource_ref": resource_ref,
                    "receipt_type": receipt_type,
                    "evidence": evidence_json,
                    "recorded_by": recorded_by,
                },
            )
            .mappings()
            .one()
        )
        return SecurityOperationReceipt(
            tenant_id=tenant_id,
            receipt_id=row["result_receipt_id"],
            attempt_id=attempt_id,
            action=action,
            resource_ref=resource_ref,
            receipt_type=receipt_type,
            receipt_sha256=row["result_receipt_sha256"],
            evidence=evidence,
            recorded_by=recorded_by,
            recorded_at=row["result_recorded_at"],
            inserted=bool(row["result_inserted"]),
        )

    def record_operation_receipt_in_transaction(
        self,
        connection,
        *,
        tenant_id: str,
        attempt_id: UUID,
        action: str,
        resource_ref: str,
        receipt_type: str,
        evidence: dict[str, Any],
        recorded_by: str,
    ) -> SecurityOperationReceipt:
        """Record a receipt without committing the caller-owned transaction."""
        self._get_engine()
        if not isinstance(tenant_id, str) or not _TENANT_RE.fullmatch(tenant_id):
            raise SecurityEventLedgerValidationError("invalid tenant_id")
        if connection is None or not connection.in_transaction():
            raise SecurityEventLedgerValidationError(
                "an active caller-owned transaction is required"
            )
        resource_ref, evidence_json = self._validate_operation_receipt(
            attempt_id=attempt_id,
            action=action,
            resource_ref=resource_ref,
            receipt_type=receipt_type,
            evidence=evidence,
            recorded_by=recorded_by,
        )
        try:
            try:
                connection.exec_driver_sql(
                    f'SET LOCAL ROLE "{SECURITY_LEDGER_DATABASE_ROLE}"'
                )
            except DBAPIError as error:
                raise SecurityEventLedgerConfigurationError(
                    "database login is not a member of the security ledger role"
                ) from error
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            receipt = self._record_operation_receipt_on_connection(
                connection,
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                action=action,
                resource_ref=resource_ref,
                receipt_type=receipt_type,
                evidence=evidence,
                evidence_json=evidence_json,
                recorded_by=recorded_by,
            )
            connection.exec_driver_sql("RESET ROLE")
            return receipt
        except SecurityEventLedgerError:
            raise
        except DBAPIError as error:
            state = _sqlstate(error)
            if state == "42501":
                raise SecurityEventLedgerForbiddenError(
                    "security ledger tenant access was denied"
                ) from error
            if state in {"40001", "23505"}:
                raise SecurityEventLedgerConflictError(
                    "security event idempotency conflict"
                ) from error
            if state in {"22023", "22P02", "23502", "23514"}:
                raise SecurityEventLedgerValidationError(
                    "security event was rejected"
                ) from error
            raise SecurityEventLedgerUnavailableError(
                "security ledger database operation failed"
            ) from error
        except SQLAlchemyError as error:
            raise SecurityEventLedgerUnavailableError(
                "security ledger database operation failed"
            ) from error

    def get_operation_receipt(
        self,
        tenant_id: str,
        attempt_id: UUID,
    ) -> SecurityOperationReceipt | None:
        if not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, receipt_id, attempt_id, action,
                               resource_ref, receipt_type, receipt_sha256,
                               evidence, recorded_by, recorded_at
                        FROM gda_control.security_operation_receipt
                        WHERE tenant_id = :tenant_id
                          AND attempt_id = :attempt_id
                        """
                    ),
                    {"tenant_id": tenant_id, "attempt_id": attempt_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return SecurityOperationReceipt(
            tenant_id=row["tenant_id"],
            receipt_id=row["receipt_id"],
            attempt_id=row["attempt_id"],
            action=row["action"],
            resource_ref=row["resource_ref"],
            receipt_type=row["receipt_type"],
            receipt_sha256=row["receipt_sha256"],
            evidence=row["evidence"],
            recorded_by=row["recorded_by"],
            recorded_at=row["recorded_at"],
            inserted=False,
        )

    def verify_operation_receipts(self, tenant_id: str) -> bool:
        with self._transaction(tenant_id) as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT gda_control.verify_security_operation_receipts("
                        ":tenant_id)"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

    def list_events(
        self,
        tenant_id: str,
        *,
        attempt_id: UUID | None = None,
        limit: int = 100,
    ) -> list[SecurityEvent]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise SecurityEventLedgerValidationError("limit must be between 1 and 1000")
        if attempt_id is not None and not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, event_id, sequence_no, attempt_id,
                               phase, action, outcome, actor_subject,
                               resource_ref, reason, details,
                               previous_event_sha256, event_sha256, occurred_at
                        FROM gda_control.security_event
                        WHERE tenant_id = :tenant_id
                          AND (:attempt_id IS NULL OR attempt_id = :attempt_id)
                        ORDER BY sequence_no DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "attempt_id": attempt_id,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        return [_event_from_row(row) for row in rows]

    def list_incomplete_admissions(
        self,
        tenant_id: str,
        *,
        older_than: datetime,
        attempt_id: UUID | None = None,
        limit: int = 100,
    ) -> list[SecurityEvent]:
        if not isinstance(older_than, datetime) or older_than.utcoffset() is None:
            raise SecurityEventLedgerValidationError(
                "older_than must be timezone-aware"
            )
        if attempt_id is not None and not isinstance(attempt_id, UUID):
            raise SecurityEventLedgerValidationError("invalid attempt_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise SecurityEventLedgerValidationError("limit must be between 1 and 1000")
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT admitted.tenant_id, admitted.event_id,
                               admitted.sequence_no, admitted.attempt_id,
                               admitted.phase, admitted.action, admitted.outcome,
                               admitted.actor_subject, admitted.resource_ref,
                               admitted.reason, admitted.details,
                               admitted.previous_event_sha256,
                               admitted.event_sha256, admitted.occurred_at
                        FROM gda_control.security_event AS admitted
                        WHERE admitted.tenant_id = :tenant_id
                          AND admitted.phase = 'admitted'
                          AND admitted.occurred_at <= :older_than
                          AND (
                            :attempt_id IS NULL
                            OR admitted.attempt_id = :attempt_id
                          )
                          AND NOT EXISTS (
                            SELECT 1
                            FROM gda_control.security_event AS outcome
                            WHERE outcome.tenant_id = admitted.tenant_id
                              AND outcome.attempt_id = admitted.attempt_id
                              AND outcome.phase = 'outcome'
                          )
                        ORDER BY admitted.occurred_at, admitted.sequence_no
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "older_than": older_than,
                        "attempt_id": attempt_id,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        return [_event_from_row(row) for row in rows]
