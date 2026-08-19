"""Fail-closed immutable audit binding for the supported Chongqing paths.

The existing PostgreSQL security-event ledger is the durable implementation
boundary.  This module keeps the execution contracts independent from SQL and
allows tests and deployment adapters to provide the same two-phase contract:
record admission before any Provider access, then record the outcome before a
result is returned to an authority caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_compensation_chongqing_execution_security import (
    ChongqingFederatedCompensationExecutionSecurityDecision,
    ChongqingFederatedCompensationExecutionSecurityRequest,
    chongqing_execution_subject_ref,
)
from .observability import security_execution_audit_events
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint
from .security_event_ledger import SecurityEventLedger


class ChongqingFederatedCompensationSecurityAuditError(RuntimeError):
    """The immutable audit contract could not be recorded."""


class ChongqingFederatedCompensationSecurityAuditConfigurationError(
    ChongqingFederatedCompensationSecurityAuditError
):
    """The audit port is missing or not tenant-bound."""


class ChongqingFederatedCompensationSecurityAuditUnavailableError(
    ChongqingFederatedCompensationSecurityAuditError
):
    """The audit ledger rejected or could not persist an event."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit time must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


def audit_attempt_id(request: ChongqingFederatedCompensationExecutionSecurityRequest) -> UUID:
    """Derive a stable ledger attempt identity without accepting caller input."""

    return uuid5(
        NAMESPACE_URL,
        f"gda:chongqing-security:{request.tenant_id}:{request.run_id}:"
        f"{request.operation}:{request.request_sha256}",
    )


class ChongqingFederatedCompensationSecurityAuditAdmission(_FrozenModel):
    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-security-audit-admission.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    operation: NonEmptyText
    purpose_code: NonEmptyText
    subject_ref: NonEmptyText
    request_sha256: Sha256
    decision_sha256: Sha256
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    resource_scope_sha256: Sha256
    recorded_at: datetime
    ledger_event_sha256: Sha256
    admission_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSecurityAuditAdmission:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("audit admission time must be timezone-aware")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"admission_sha256"}),
            "admission_sha256",
        )
        if self.admission_sha256 != expected:
            raise ValueError("audit admission fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSecurityAuditOutcome(_FrozenModel):
    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-security-audit-outcome.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    operation: NonEmptyText
    admission_sha256: Sha256
    outcome: Literal["success", "failure", "unknown"]
    evidence_sha256: Sha256
    provider_invocations: int = Field(ge=0, le=5)
    recorded_at: datetime
    ledger_event_sha256: Sha256
    outcome_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSecurityAuditOutcome:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("audit outcome time must be timezone-aware")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"outcome_sha256"}),
            "outcome_sha256",
        )
        if self.outcome_sha256 != expected:
            raise ValueError("audit outcome fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSecurityAuditPort(Protocol):
    """Two-phase audit port required by the supported mutation entry points."""

    tenant_id: str

    def record_admission(
        self,
        request: ChongqingFederatedCompensationExecutionSecurityRequest,
        decision: ChongqingFederatedCompensationExecutionSecurityDecision,
    ) -> ChongqingFederatedCompensationSecurityAuditAdmission: ...

    def record_outcome(
        self,
        admission: ChongqingFederatedCompensationSecurityAuditAdmission,
        *,
        outcome: Literal["success", "failure", "unknown"],
        evidence_sha256: str,
        provider_invocations: int,
        recorded_at: datetime,
    ) -> ChongqingFederatedCompensationSecurityAuditOutcome: ...


def _resource_scope_sha256(
    request: ChongqingFederatedCompensationExecutionSecurityRequest,
) -> str:
    return canonical_json_fingerprint(
        {
            "resources": [item.model_dump(mode="json") for item in request.resources]
        }
    )


def _build_admission(
    request: ChongqingFederatedCompensationExecutionSecurityRequest,
    decision: ChongqingFederatedCompensationExecutionSecurityDecision,
    *,
    ledger_event_sha256: str,
    recorded_at: datetime,
) -> ChongqingFederatedCompensationSecurityAuditAdmission:
    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "operation": request.operation,
        "purpose_code": request.purpose_code,
        "subject_ref": chongqing_execution_subject_ref(request.subject_context),
        "request_sha256": request.request_sha256,
        "decision_sha256": decision.decision_sha256,
        "policy_ref": decision.policy_ref,
        "policy_version": decision.policy_version,
        "resource_scope_sha256": _resource_scope_sha256(request),
        "recorded_at": recorded_at,
        "ledger_event_sha256": ledger_event_sha256,
    }
    return ChongqingFederatedCompensationSecurityAuditAdmission(
        **values,
        admission_sha256=_fingerprint(
            ChongqingFederatedCompensationSecurityAuditAdmission.schema_id,
            values,
            "admission_sha256",
        ),
    )


def _build_outcome(
    admission: ChongqingFederatedCompensationSecurityAuditAdmission,
    *,
    outcome: Literal["success", "failure", "unknown"],
    evidence_sha256: str,
    provider_invocations: int,
    recorded_at: datetime,
    ledger_event_sha256: str,
) -> ChongqingFederatedCompensationSecurityAuditOutcome:
    values = {
        "tenant_id": admission.tenant_id,
        "run_id": admission.run_id,
        "operation": admission.operation,
        "admission_sha256": admission.admission_sha256,
        "outcome": outcome,
        "evidence_sha256": evidence_sha256,
        "provider_invocations": provider_invocations,
        "recorded_at": recorded_at,
        "ledger_event_sha256": ledger_event_sha256,
    }
    return ChongqingFederatedCompensationSecurityAuditOutcome(
        **values,
        outcome_sha256=_fingerprint(
            ChongqingFederatedCompensationSecurityAuditOutcome.schema_id,
            values,
            "outcome_sha256",
        ),
    )


class SecurityEventLedgerChongqingCompensationAudit:
    """Durable adapter backed by the existing immutable event ledger."""

    def __init__(self, tenant_id: str, ledger: SecurityEventLedger | None = None):
        self.tenant_id = tenant_id
        self._ledger = ledger or SecurityEventLedger()

    def record_admission(self, request, decision):
        if request.tenant_id != self.tenant_id or decision.request != request:
            raise ChongqingFederatedCompensationSecurityAuditConfigurationError(
                "audit admission tenant or decision differs from request"
            )
        if decision.effect != "allow" or decision.obligations:
            raise ChongqingFederatedCompensationSecurityAuditUnavailableError(
                "only an exact allow decision can be audited as admission"
            )
        recorded_at = decision.decided_at
        event = self._ledger.append(
            tenant_id=self.tenant_id,
            attempt_id=audit_attempt_id(request),
            phase="admitted",
            action=request.operation,
            outcome="admitted",
            actor_subject=chongqing_execution_subject_ref(request.subject_context),
            resource_ref=f"gda://chongqing/{request.run_id}/{request.operation}",
            reason="exact-scope SPR allow recorded before Provider access",
            details={
                "purpose_code": request.purpose_code,
                "purpose_version": request.purpose_version,
                "request_sha256": request.request_sha256,
                "decision_sha256": decision.decision_sha256,
                "resource_scope_sha256": _resource_scope_sha256(request),
                "policy_ref": decision.policy_ref,
                "policy_version": decision.policy_version,
            },
        )
        security_execution_audit_events.labels(
            operation=request.operation, phase="admitted", outcome="admitted"
        ).inc()
        return _build_admission(
            request,
            decision,
            ledger_event_sha256=event.event_sha256,
            recorded_at=recorded_at,
        )

    def record_outcome(
        self,
        admission,
        *,
        outcome,
        evidence_sha256,
        provider_invocations,
        recorded_at,
    ):
        if admission.tenant_id != self.tenant_id:
            raise ChongqingFederatedCompensationSecurityAuditConfigurationError(
                "audit outcome tenant differs from admission"
            )
        event = self._ledger.append(
            tenant_id=self.tenant_id,
            attempt_id=audit_attempt_id_from_admission(admission),
            phase="outcome",
            action=admission.operation,
            outcome="success" if outcome == "success" else "failure",
            actor_subject=admission.subject_ref,
            resource_ref=f"gda://chongqing/{admission.run_id}/{admission.operation}",
            reason="Provider outcome recorded after governed execution",
            details={
                "admission_sha256": admission.admission_sha256,
                "evidence_sha256": evidence_sha256,
                "provider_invocations": provider_invocations,
                "reported_outcome": outcome,
            },
        )
        security_execution_audit_events.labels(
            operation=admission.operation, phase="outcome", outcome=outcome
        ).inc()
        return _build_outcome(
            admission,
            outcome=outcome,
            evidence_sha256=evidence_sha256,
            provider_invocations=provider_invocations,
            recorded_at=recorded_at,
            ledger_event_sha256=event.event_sha256,
        )


class InMemoryChongqingCompensationSecurityAudit:
    """Deterministic adapter for isolated tests and local contract rehearsal."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.admissions: list[ChongqingFederatedCompensationSecurityAuditAdmission] = []
        self.outcomes: list[ChongqingFederatedCompensationSecurityAuditOutcome] = []

    def record_admission(self, request, decision):
        if request.tenant_id != self.tenant_id or decision.request != request:
            raise ChongqingFederatedCompensationSecurityAuditConfigurationError(
                "audit admission tenant or decision differs from request"
            )
        receipt = _build_admission(
            request,
            decision,
            ledger_event_sha256=_fingerprint(
                "gda.chongqing-federated-compensation-security-audit-event.v1",
                {
                    "phase": "admitted",
                    "request_sha256": request.request_sha256,
                    "decision_sha256": decision.decision_sha256,
                },
                "event_sha256",
            ),
            recorded_at=decision.decided_at,
        )
        self.admissions.append(receipt)
        security_execution_audit_events.labels(
            operation=request.operation, phase="admitted", outcome="admitted"
        ).inc()
        return receipt

    def record_outcome(
        self,
        admission,
        *,
        outcome,
        evidence_sha256,
        provider_invocations,
        recorded_at,
    ):
        if admission.tenant_id != self.tenant_id:
            raise ChongqingFederatedCompensationSecurityAuditConfigurationError(
                "audit outcome tenant differs from admission"
            )
        receipt = _build_outcome(
            admission,
            outcome=outcome,
            evidence_sha256=evidence_sha256,
            provider_invocations=provider_invocations,
            recorded_at=recorded_at,
            ledger_event_sha256=_fingerprint(
                "gda.chongqing-federated-compensation-security-audit-event.v1",
                {
                    "phase": "outcome",
                    "admission_sha256": admission.admission_sha256,
                    "evidence_sha256": evidence_sha256,
                    "outcome": outcome,
                },
                "event_sha256",
            ),
        )
        self.outcomes.append(receipt)
        security_execution_audit_events.labels(
            operation=admission.operation, phase="outcome", outcome=outcome
        ).inc()
        return receipt


def audit_attempt_id_from_admission(
    admission: ChongqingFederatedCompensationSecurityAuditAdmission,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"gda:chongqing-security:{admission.tenant_id}:{admission.run_id}:"
        f"{admission.operation}:{admission.request_sha256}",
    )


def require_security_audit_port(
    port: ChongqingFederatedCompensationSecurityAuditPort | None,
    tenant_id: str,
) -> ChongqingFederatedCompensationSecurityAuditPort:
    if (
        port is None
        or getattr(port, "tenant_id", None) != tenant_id
        or not callable(getattr(port, "record_admission", None))
        or not callable(getattr(port, "record_outcome", None))
    ):
        raise ChongqingFederatedCompensationSecurityAuditConfigurationError(
            "supported Chongqing execution requires a tenant-bound security audit port"
        )
    return port


__all__ = [
    "ChongqingFederatedCompensationSecurityAuditAdmission",
    "ChongqingFederatedCompensationSecurityAuditConfigurationError",
    "ChongqingFederatedCompensationSecurityAuditError",
    "ChongqingFederatedCompensationSecurityAuditOutcome",
    "ChongqingFederatedCompensationSecurityAuditPort",
    "ChongqingFederatedCompensationSecurityAuditUnavailableError",
    "SecurityEventLedgerChongqingCompensationAudit",
    "InMemoryChongqingCompensationSecurityAudit",
    "audit_attempt_id",
    "require_security_audit_port",
]
