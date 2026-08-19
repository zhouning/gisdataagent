"""Fail-closed SPR and audit boundary for non-run result delivery routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from .governed_query_result_access_security import (
    GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
    GovernedQueryResultAccessSecurityDecision,
    GovernedQueryResultAccessSecurityDeniedError,
    GovernedQueryResultAccessSecurityError,
    build_governed_query_result_access_security_request,
    evaluate_governed_query_result_access_security,
)
from .governed_query_security import GovernedQuerySecurityCurrentReader
from .security_event_ledger import SecurityEventLedger, SecurityEventLedgerError

ResultT = TypeVar("ResultT")
ConsumptionMode = Literal["read", "download", "cache", "map", "report"]


class GovernedQueryResultDeliveryError(RuntimeError):
    code = "governed_query_result_delivery_error"


class GovernedQueryResultDeliveryForbidden(GovernedQueryResultDeliveryError):
    code = "governed_query_result_delivery_forbidden"


class GovernedQueryResultDeliveryUnavailable(GovernedQueryResultDeliveryError):
    code = "governed_query_result_delivery_unavailable"


class GovernedQueryResultDeliveryService:
    """Authorize and audit one bounded call to a result provider."""

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
        consumption_mode: ConsumptionMode,
        reason: str,
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
                reason=reason,
                details={
                    "roles": list(roles),
                    "consumption_mode": consumption_mode,
                },
            )
        except SecurityEventLedgerError:
            # A denied request stays denied when the denial audit is unavailable.
            return

    @staticmethod
    def _decision_details(
        decision: GovernedQueryResultAccessSecurityDecision,
        *,
        purpose_code: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        consumption_mode: ConsumptionMode,
        resource_count: int,
    ) -> dict[str, Any]:
        return {
            "purpose_code": purpose_code,
            "roles": list(roles),
            "channel": channel,
            "adapter_id": adapter_id,
            "consumption_mode": consumption_mode,
            "resource_count": resource_count,
            "request_sha256": decision.request.request_sha256,
            "decision_sha256": decision.decision_sha256,
            "policy_ref": decision.policy_ref,
            "policy_version": decision.policy_version,
        }

    def execute(
        self,
        *,
        tenant_id: str,
        actor_subject: str,
        roles: tuple[str, ...],
        channel: str,
        adapter_id: str,
        consumption_mode: ConsumptionMode,
        resource_refs: tuple[str, ...],
        request_payload: Mapping[str, Any],
        action: str,
        operation: Callable[[], ResultT],
        purpose_code: str = GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
        security_reader: GovernedQuerySecurityCurrentReader | None = None,
    ) -> ResultT:
        """Execute only after current-policy allow and immutable admission audit.

        A missing reader retains the repository's optional development-mode
        behavior. Routes resolve the reader first, so required mode still fails
        closed before this method is called.
        """

        if security_reader is None:
            return operation()

        access_id = self.access_id_factory()
        evaluated_at = self.now()
        resource_ref = resource_refs[0] if resource_refs else ""
        try:
            request = build_governed_query_result_access_security_request(
                tenant_id=tenant_id,
                request_id=f"result-delivery:{access_id}",
                actor_subject=actor_subject,
                roles=roles,
                purpose_code=purpose_code,
                channel=channel,
                adapter_id=adapter_id,
                consumption_mode=consumption_mode,
                resource_refs=resource_refs,
                request_payload=request_payload,
                evaluated_at=evaluated_at,
            )
            decision = evaluate_governed_query_result_access_security(
                request,
                security_reader,
                evaluated_at=evaluated_at,
            )
        except GovernedQueryResultAccessSecurityDeniedError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                action=action,
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                roles=roles,
                consumption_mode=consumption_mode,
                reason="spr_policy_denied",
            )
            raise GovernedQueryResultDeliveryForbidden(
                "result delivery was denied by current policy"
            ) from exc
        except (GovernedQueryResultAccessSecurityError, ValueError) as exc:
            raise GovernedQueryResultDeliveryUnavailable(
                "result delivery security is unavailable"
            ) from exc

        details = self._decision_details(
            decision,
            purpose_code=purpose_code,
            roles=roles,
            channel=channel,
            adapter_id=adapter_id,
            consumption_mode=consumption_mode,
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
                reason="exact-scope SPR allow recorded before result provider access",
                details=details,
            )
        except SecurityEventLedgerError as exc:
            raise GovernedQueryResultDeliveryUnavailable(
                "result delivery security admission audit is unavailable"
            ) from exc

        try:
            result = operation()
        except Exception as operation_error:
            try:
                self.ledger.append(
                    tenant_id=tenant_id,
                    attempt_id=access_id,
                    phase="outcome",
                    action=action,
                    outcome="failure",
                    actor_subject=actor_subject,
                    resource_ref=resource_ref,
                    reason="result_provider_failed",
                    details={
                        **details,
                        "provider_error_type": type(operation_error).__name__,
                    },
                )
            except SecurityEventLedgerError as audit_error:
                raise GovernedQueryResultDeliveryUnavailable(
                    "result delivery failure audit is unavailable"
                ) from audit_error
            raise

        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="outcome",
                action=action,
                outcome="success",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="result_delivery_succeeded",
                details=details,
            )
        except SecurityEventLedgerError as exc:
            raise GovernedQueryResultDeliveryUnavailable(
                "result delivery outcome audit is unavailable"
            ) from exc
        return result


__all__ = [
    "ConsumptionMode",
    "GovernedQueryResultDeliveryError",
    "GovernedQueryResultDeliveryForbidden",
    "GovernedQueryResultDeliveryService",
    "GovernedQueryResultDeliveryUnavailable",
]
