"""Fail-closed SPR and immutable audit boundary for external operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID, uuid4

from .governed_external_access_security import (
    GOVERNED_EXTERNAL_ACCESS_PURPOSE,
    ExternalAccessMode,
    GovernedExternalAccessDecision,
    GovernedExternalAccessSecurityDeniedError,
    GovernedExternalAccessSecurityError,
    build_governed_external_access_request,
    evaluate_governed_external_access,
)
from .governed_query_security import GovernedQuerySecurityCurrentReader
from .security_event_ledger import SecurityEventLedger, SecurityEventLedgerError

ResultT = TypeVar("ResultT")


class GovernedExternalAccessError(RuntimeError):
    code = "governed_external_access_error"


class GovernedExternalAccessForbidden(GovernedExternalAccessError):
    code = "governed_external_access_forbidden"


class GovernedExternalAccessUnavailable(GovernedExternalAccessError):
    code = "governed_external_access_unavailable"


class GovernedExternalAccessService:
    """Authorize and audit one bounded external operation."""

    def __init__(
        self,
        *,
        ledger: SecurityEventLedger | None = None,
        now: Callable[[], datetime] | None = None,
        access_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.ledger = ledger or SecurityEventLedger()
        self.now = now or (lambda: datetime.now(UTC))
        self.access_id_factory = access_id_factory

    def _audit_denied(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        action: str,
        actor_subject: str,
        resource_ref: str,
        roles: tuple[str, ...],
        access_mode: ExternalAccessMode,
    ) -> None:
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="denied",
                action=action,
                outcome="denied",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="spr_policy_denied",
                details={
                    "roles": list(roles),
                    "access_mode": access_mode,
                },
            )
        except SecurityEventLedgerError:
            return

    @staticmethod
    def _decision_details(
        decision: GovernedExternalAccessDecision,
        *,
        purpose_code: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        access_mode: ExternalAccessMode,
        resource_count: int,
    ) -> dict[str, Any]:
        return {
            "purpose_code": purpose_code,
            "roles": list(roles),
            "channel": channel,
            "adapter_id": adapter_id,
            "access_mode": access_mode,
            "resource_count": resource_count,
            "request_payload_sha256": decision.request.request_payload_sha256,
            "request_sha256": decision.request.request_sha256,
            "decision_sha256": decision.decision_sha256,
            "policy_ref": decision.policy_ref,
            "policy_version": decision.policy_version,
        }

    def _admit(
        self,
        *,
        tenant_id: str,
        actor_subject: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        access_mode: ExternalAccessMode,
        resource_refs: tuple[str, ...],
        request_payload: Mapping[str, Any],
        action: str,
        purpose_code: str,
        security_reader: GovernedQuerySecurityCurrentReader,
    ) -> tuple[UUID, str, dict[str, Any]]:
        access_id = self.access_id_factory()
        evaluated_at = self.now()
        resource_ref = resource_refs[0] if resource_refs else ""
        try:
            request = build_governed_external_access_request(
                tenant_id=tenant_id,
                request_id=f"external-access:{access_id}",
                actor_subject=actor_subject,
                roles=roles,
                purpose_code=purpose_code,
                channel=channel,
                adapter_id=adapter_id,
                access_mode=access_mode,
                resource_refs=resource_refs,
                request_payload=request_payload,
                evaluated_at=evaluated_at,
            )
            decision = evaluate_governed_external_access(
                request,
                security_reader,
                evaluated_at=evaluated_at,
            )
        except GovernedExternalAccessSecurityDeniedError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                action=action,
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                roles=roles,
                access_mode=access_mode,
            )
            raise GovernedExternalAccessForbidden(
                "external access was denied by current policy"
            ) from exc
        except (GovernedExternalAccessSecurityError, ValueError, TypeError) as exc:
            raise GovernedExternalAccessUnavailable(
                "external access security is unavailable"
            ) from exc

        details = self._decision_details(
            decision,
            purpose_code=purpose_code,
            roles=roles,
            channel=channel,
            adapter_id=adapter_id,
            access_mode=access_mode,
            resource_count=len(resource_refs),
        )
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="admitted",
                action=action,
                outcome="admitted",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="exact-scope SPR allow recorded before external access",
                details={**details, "operation_invocations": 0},
            )
        except SecurityEventLedgerError as exc:
            raise GovernedExternalAccessUnavailable(
                "external access admission audit is unavailable"
            ) from exc
        return access_id, resource_ref, details

    def _record_failure(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        action: str,
        actor_subject: str,
        resource_ref: str,
        details: dict[str, Any],
        error: Exception,
    ) -> None:
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="outcome",
                action=action,
                outcome="failure",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="external_operation_failed",
                details={
                    **details,
                    "operation_invocations": 1,
                    "external_error_type": type(error).__name__,
                },
            )
        except SecurityEventLedgerError as audit_error:
            raise GovernedExternalAccessUnavailable(
                "external access failure audit is unavailable"
            ) from audit_error

    def _record_success(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        action: str,
        actor_subject: str,
        resource_ref: str,
        details: dict[str, Any],
    ) -> None:
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="outcome",
                action=action,
                outcome="success",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="external_operation_succeeded",
                details={**details, "operation_invocations": 1},
            )
        except SecurityEventLedgerError as exc:
            raise GovernedExternalAccessUnavailable(
                "external access outcome audit is unavailable"
            ) from exc

    def execute(
        self,
        *,
        tenant_id: str,
        actor_subject: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        access_mode: ExternalAccessMode,
        resource_refs: tuple[str, ...],
        request_payload: Mapping[str, Any],
        action: str,
        operation: Callable[[], ResultT],
        purpose_code: str = GOVERNED_EXTERNAL_ACCESS_PURPOSE,
        security_reader: GovernedQuerySecurityCurrentReader | None = None,
    ) -> ResultT:
        """Execute synchronously after current-policy allow and admission audit."""

        if security_reader is None:
            return operation()
        access_id, resource_ref, details = self._admit(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            roles=roles,
            channel=channel,
            adapter_id=adapter_id,
            access_mode=access_mode,
            resource_refs=resource_refs,
            request_payload=request_payload,
            action=action,
            purpose_code=purpose_code,
            security_reader=security_reader,
        )
        try:
            result = operation()
        except Exception as operation_error:
            self._record_failure(
                tenant_id=tenant_id,
                access_id=access_id,
                action=action,
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                details=details,
                error=operation_error,
            )
            raise
        self._record_success(
            tenant_id=tenant_id,
            access_id=access_id,
            action=action,
            actor_subject=actor_subject,
            resource_ref=resource_ref,
            details=details,
        )
        return result

    async def execute_async(
        self,
        *,
        tenant_id: str,
        actor_subject: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        access_mode: ExternalAccessMode,
        resource_refs: tuple[str, ...],
        request_payload: Mapping[str, Any],
        action: str,
        operation: Callable[[], Awaitable[ResultT]],
        purpose_code: str = GOVERNED_EXTERNAL_ACCESS_PURPOSE,
        security_reader: GovernedQuerySecurityCurrentReader | None = None,
    ) -> ResultT:
        """Execute asynchronously after current-policy allow and admission audit."""

        if security_reader is None:
            return await operation()
        access_id, resource_ref, details = self._admit(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            roles=roles,
            channel=channel,
            adapter_id=adapter_id,
            access_mode=access_mode,
            resource_refs=resource_refs,
            request_payload=request_payload,
            action=action,
            purpose_code=purpose_code,
            security_reader=security_reader,
        )
        try:
            result = await operation()
        except Exception as operation_error:
            self._record_failure(
                tenant_id=tenant_id,
                access_id=access_id,
                action=action,
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                details=details,
                error=operation_error,
            )
            raise
        self._record_success(
            tenant_id=tenant_id,
            access_id=access_id,
            action=action,
            actor_subject=actor_subject,
            resource_ref=resource_ref,
            details=details,
        )
        return result


__all__ = [
    "GovernedExternalAccessError",
    "GovernedExternalAccessForbidden",
    "GovernedExternalAccessService",
    "GovernedExternalAccessUnavailable",
]
