"""Live SPR authorization and immutable audit contracts for governed queries.

This module is deliberately independent from the query adapters.  Deployments
may provide a durable policy reader and audit port; the query runner then
checks them immediately before adapter access and records a terminal outcome
before returning a response.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .observability import security_execution_audit_events
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)
from .security_event_ledger import SecurityEventLedger

GOVERNED_QUERY_SECURITY_PURPOSE = "semantic_query"
GOVERNED_QUERY_SECURITY_REQUIRED_ENV = "GDA_GOVERNED_QUERY_SECURITY_REQUIRED"


class GovernedQuerySecurityError(RuntimeError):
    """The query security decision or audit boundary failed closed."""


class GovernedQuerySecurityConfigurationError(GovernedQuerySecurityError):
    """A required tenant-bound security port is missing or mismatched."""


class GovernedQuerySecurityUnavailableError(GovernedQuerySecurityError):
    """A live policy or immutable audit operation was unavailable."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("query security time must be timezone-aware")
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


def _request_fingerprint(values: dict[str, Any]) -> str:
    """Fingerprint a request without making resource bindings circular."""
    payload = dict(values)
    payload.pop("request_sha256", None)
    payload["resources"] = [
        {
            key: value
            for key, value in (
                item.model_dump(mode="json")
                if isinstance(item, BaseModel)
                else item
            ).items()
            if key != "request_sha256"
        }
        for item in payload["resources"]
    ]
    return canonical_json_fingerprint(
        {
            "schema": GovernedQuerySecurityRequest.schema_id,
            "data": _json_ready(payload),
        }
    )


class GovernedQuerySecurityResource(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-security-resource.v1"
    position: int = Field(ge=0, le=19)
    channel: NonEmptyText
    adapter_id: NonEmptyText
    resource_ref: NonEmptyText
    access_mode: Literal["read"] = "read"
    request_sha256: Sha256
    resource_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQuerySecurityResource:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(
                mode="json", exclude={"resource_sha256", "request_sha256"}
            ),
            "resource_sha256",
        )
        if self.resource_sha256 != expected:
            raise ValueError("governed query security resource fingerprint is invalid")
        return self


class GovernedQuerySecurityRequest(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-security-request.v1"
    tenant_id: TenantId
    request_id: NonEmptyText
    operation: Literal["semantic.query.execute"] = "semantic.query.execute"
    purpose_code: NonEmptyText
    subject_context: SubjectContext
    channel: NonEmptyText
    adapter_id: NonEmptyText
    request_payload_sha256: Sha256
    resources: tuple[GovernedQuerySecurityResource, ...] = Field(min_length=1, max_length=20)
    evaluated_at: datetime
    provider_access_performed: Literal[False] = False
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQuerySecurityRequest:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("query security subject tenant differs")
        if self.subject_context.purpose != self.purpose_code:
            raise ValueError("query security purpose differs from subject context")
        if self.subject_context.trace_id is None:
            raise ValueError("query security subject requires a trace ID")
        if tuple(item.position for item in self.resources) != tuple(range(len(self.resources))):
            raise ValueError("query security resources must be ordered")
        expected = _request_fingerprint(self.model_dump(mode="json"))
        if self.request_sha256 != expected:
            raise ValueError("governed query security request fingerprint is invalid")
        return self


class GovernedQuerySecurityDecision(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-security-decision.v1"
    request: GovernedQuerySecurityRequest
    effect: Literal["allow", "deny"]
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    evaluator_subject: NonEmptyText
    obligations: tuple[NonEmptyText, ...] = ()
    decided_at: datetime
    expires_at: datetime
    authority_live_read_performed: Literal[True] = True
    provider_access_performed: Literal[False] = False
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQuerySecurityDecision:
        if (
            self.decided_at.tzinfo is None
            or self.decided_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.decided_at
        ):
            raise ValueError("query security decision window is invalid")
        if len(self.obligations) != len(set(self.obligations)):
            raise ValueError("query security obligations must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"decision_sha256"}),
            "decision_sha256",
        )
        if self.decision_sha256 != expected:
            raise ValueError("governed query security decision fingerprint is invalid")
        return self


class GovernedQuerySecurityAuditAdmission(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-security-audit-admission.v1"
    tenant_id: TenantId
    request_id: NonEmptyText
    subject_ref: NonEmptyText
    request_sha256: Sha256
    decision_sha256: Sha256
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    resource_scope_sha256: Sha256
    recorded_at: datetime
    admission_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQuerySecurityAuditAdmission:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("query security audit time must be timezone-aware")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"admission_sha256"}),
            "admission_sha256",
        )
        if self.admission_sha256 != expected:
            raise ValueError("governed query security admission fingerprint is invalid")
        return self


class GovernedQuerySecurityAuditOutcome(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-security-audit-outcome.v1"
    tenant_id: TenantId
    request_id: NonEmptyText
    admission_sha256: Sha256
    outcome: Literal["success", "failure", "unknown"]
    evidence_sha256: Sha256
    adapter_invocations: int = Field(ge=0, le=20)
    recorded_at: datetime
    outcome_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQuerySecurityAuditOutcome:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("query security audit time must be timezone-aware")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"outcome_sha256"}),
            "outcome_sha256",
        )
        if self.outcome_sha256 != expected:
            raise ValueError("governed query security outcome fingerprint is invalid")
        return self


class GovernedQuerySecurityCurrentReader(Protocol):
    tenant_id: str

    def governed_query_security_decision_current(
        self, request: GovernedQuerySecurityRequest
    ) -> GovernedQuerySecurityDecision: ...


class GovernedQuerySecurityAuditPort(Protocol):
    tenant_id: str

    def record_admission(
        self,
        request: GovernedQuerySecurityRequest,
        decision: GovernedQuerySecurityDecision,
    ) -> GovernedQuerySecurityAuditAdmission: ...

    def record_outcome(
        self,
        admission: GovernedQuerySecurityAuditAdmission,
        *,
        outcome: Literal["success", "failure", "unknown"],
        evidence_sha256: str,
        adapter_invocations: int,
        recorded_at: datetime,
    ) -> GovernedQuerySecurityAuditOutcome: ...


class GovernedQuerySecurityPortResolver(Protocol):
    """Resolve tenant-bound live policy and audit ports for one HTTP request."""

    def resolve(
        self, tenant_id: str
    ) -> tuple[GovernedQuerySecurityCurrentReader, GovernedQuerySecurityAuditPort]: ...


def governed_query_security_required() -> bool:
    """Return whether public query entry points must have security ports."""

    raw = os.environ.get(GOVERNED_QUERY_SECURITY_REQUIRED_ENV, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise GovernedQuerySecurityConfigurationError(
        f"{GOVERNED_QUERY_SECURITY_REQUIRED_ENV} must be a boolean"
    )


_query_security_port_resolver: GovernedQuerySecurityPortResolver | None = None


def configure_governed_query_security_port_resolver(
    resolver: GovernedQuerySecurityPortResolver | None,
) -> None:
    """Configure the deployment-owned request-time security port resolver."""

    global _query_security_port_resolver
    if resolver is not None and not callable(getattr(resolver, "resolve", None)):
        raise GovernedQuerySecurityConfigurationError(
            "governed query security resolver is invalid"
        )
    _query_security_port_resolver = resolver


def resolve_governed_query_security_ports(
    tenant_id: str,
) -> tuple[GovernedQuerySecurityCurrentReader, GovernedQuerySecurityAuditPort] | None:
    """Resolve deployment ports or fail closed when the public gate is required."""

    resolver = _query_security_port_resolver
    if resolver is None:
        if governed_query_security_required():
            raise GovernedQuerySecurityConfigurationError(
                "governed query security is required but no port resolver is configured"
            )
        return None
    try:
        ports = resolver.resolve(tenant_id)
    except GovernedQuerySecurityError:
        raise
    except Exception as exc:
        raise GovernedQuerySecurityUnavailableError(
            "governed query security port resolution failed"
        ) from exc
    if not isinstance(ports, tuple) or len(ports) != 2:
        raise GovernedQuerySecurityConfigurationError(
            "governed query security resolver returned invalid ports"
        )
    return require_query_security_ports(ports[0], ports[1], tenant_id)


def governed_query_security_resolver_configured() -> bool:
    """Return whether a deployment resolver has been installed."""

    return _query_security_port_resolver is not None


def _resource_scope_sha256(request: GovernedQuerySecurityRequest) -> str:
    return canonical_json_fingerprint(
        {"resources": [item.model_dump(mode="json") for item in request.resources]}
    )


def _audit_attempt_id(request: GovernedQuerySecurityRequest) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"gda:governed-query-security:{request.tenant_id}:{request.request_id}:"
        f"{request.request_sha256}",
    )


def _build_admission(
    request: GovernedQuerySecurityRequest,
    decision: GovernedQuerySecurityDecision,
    *,
    recorded_at: datetime,
) -> GovernedQuerySecurityAuditAdmission:
    values = {
        "tenant_id": request.tenant_id,
        "request_id": request.request_id,
        "subject_ref": (
            f"{request.subject_context.subject_type.value}:"
            f"{request.subject_context.subject_id}"
        ),
        "request_sha256": request.request_sha256,
        "decision_sha256": decision.decision_sha256,
        "policy_ref": decision.policy_ref,
        "policy_version": decision.policy_version,
        "resource_scope_sha256": _resource_scope_sha256(request),
        "recorded_at": recorded_at,
    }
    return GovernedQuerySecurityAuditAdmission(
        **values,
        admission_sha256=_fingerprint(
            GovernedQuerySecurityAuditAdmission.schema_id,
            values,
            "admission_sha256",
        ),
    )


def _build_outcome(
    admission: GovernedQuerySecurityAuditAdmission,
    *,
    outcome: Literal["success", "failure", "unknown"],
    evidence_sha256: str,
    adapter_invocations: int,
    recorded_at: datetime,
) -> GovernedQuerySecurityAuditOutcome:
    values = {
        "tenant_id": admission.tenant_id,
        "request_id": admission.request_id,
        "admission_sha256": admission.admission_sha256,
        "outcome": outcome,
        "evidence_sha256": evidence_sha256,
        "adapter_invocations": adapter_invocations,
        "recorded_at": recorded_at,
    }
    return GovernedQuerySecurityAuditOutcome(
        **values,
        outcome_sha256=_fingerprint(
            GovernedQuerySecurityAuditOutcome.schema_id,
            values,
            "outcome_sha256",
        ),
    )


class InMemoryGovernedQuerySecurityAudit:
    """Local contract adapter; production must use a durable audit port."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.admissions: list[GovernedQuerySecurityAuditAdmission] = []
        self.outcomes: list[GovernedQuerySecurityAuditOutcome] = []

    def record_admission(self, request, decision):
        if request.tenant_id != self.tenant_id or decision.request != request:
            raise GovernedQuerySecurityConfigurationError(
                "query security audit tenant or decision differs from request"
            )
        if decision.effect != "allow" or decision.obligations:
            raise GovernedQuerySecurityUnavailableError(
                "only an exact allow decision can be audited as admission"
            )
        admission = _build_admission(
            request, decision, recorded_at=decision.decided_at
        )
        self.admissions.append(admission)
        security_execution_audit_events.labels(
            operation="semantic.query.execute", phase="admitted", outcome="admitted"
        ).inc()
        return admission

    def record_outcome(
        self,
        admission,
        *,
        outcome,
        evidence_sha256,
        adapter_invocations,
        recorded_at,
    ):
        if admission.tenant_id != self.tenant_id:
            raise GovernedQuerySecurityConfigurationError(
                "query security audit outcome tenant differs from admission"
            )
        result = _build_outcome(
            admission,
            outcome=outcome,
            evidence_sha256=evidence_sha256,
            adapter_invocations=adapter_invocations,
            recorded_at=recorded_at,
        )
        self.outcomes.append(result)
        security_execution_audit_events.labels(
            operation="semantic.query.execute", phase="outcome", outcome=outcome
        ).inc()
        return result


class SecurityEventLedgerGovernedQueryAudit:
    """Durable adapter backed by the existing tenant-scoped security ledger."""

    def __init__(self, tenant_id: str, ledger: SecurityEventLedger | None = None):
        self.tenant_id = tenant_id
        self._ledger = ledger or SecurityEventLedger()

    def record_admission(self, request, decision):
        if request.tenant_id != self.tenant_id or decision.request != request:
            raise GovernedQuerySecurityConfigurationError(
                "query security audit tenant or decision differs from request"
            )
        if decision.effect != "allow" or decision.obligations:
            raise GovernedQuerySecurityUnavailableError(
                "only an exact allow decision can be audited as admission"
            )
        event = self._ledger.append(
            tenant_id=self.tenant_id,
            attempt_id=_audit_attempt_id(request),
            phase="admitted",
            action="semantic.query.execute",
            outcome="admitted",
            actor_subject=(
                f"{request.subject_context.subject_type.value}:"
                f"{request.subject_context.subject_id}"
            ),
            resource_ref=f"gda://query/{request.tenant_id}/{request.request_id}",
            reason="exact-scope SPR allow recorded before query adapter access",
            details={
                "purpose_code": request.purpose_code,
                "request_sha256": request.request_sha256,
                "decision_sha256": decision.decision_sha256,
                "resource_scope_sha256": _resource_scope_sha256(request),
                "policy_ref": decision.policy_ref,
                "policy_version": decision.policy_version,
            },
        )
        security_execution_audit_events.labels(
            operation="semantic.query.execute", phase="admitted", outcome="admitted"
        ).inc()
        result = _build_admission(
            request, decision, recorded_at=decision.decided_at
        )
        if event.event_sha256 == "":
            raise GovernedQuerySecurityUnavailableError("query admission audit is empty")
        return result

    def record_outcome(
        self,
        admission,
        *,
        outcome,
        evidence_sha256,
        adapter_invocations,
        recorded_at,
    ):
        if admission.tenant_id != self.tenant_id:
            raise GovernedQuerySecurityConfigurationError(
                "query security audit outcome tenant differs from admission"
            )
        event = self._ledger.append(
            tenant_id=self.tenant_id,
            attempt_id=uuid5(
                NAMESPACE_URL,
                f"gda:governed-query-security:{admission.tenant_id}:"
                f"{admission.request_id}:{admission.request_sha256}",
            ),
            phase="outcome",
            action="semantic.query.execute",
            outcome="success" if outcome == "success" else "failure",
            actor_subject="workload:semantic-query-control-plane",
            resource_ref=f"gda://query/{admission.tenant_id}/{admission.request_id}",
            reason="query adapter outcome recorded after governed execution",
            details={
                "admission_sha256": admission.admission_sha256,
                "evidence_sha256": evidence_sha256,
                "adapter_invocations": adapter_invocations,
                "reported_outcome": outcome,
            },
        )
        security_execution_audit_events.labels(
            operation="semantic.query.execute", phase="outcome", outcome=outcome
        ).inc()
        result = _build_outcome(
            admission,
            outcome=outcome,
            evidence_sha256=evidence_sha256,
            adapter_invocations=adapter_invocations,
            recorded_at=recorded_at,
        )
        if event.event_sha256 == "":
            raise GovernedQuerySecurityUnavailableError("query outcome audit is empty")
        return result


def build_query_security_resource(
    *,
    position: int,
    channel: str,
    adapter_id: str,
    resource_ref: str,
    request_sha256: str,
) -> GovernedQuerySecurityResource:
    values = {
        "position": position,
        "channel": channel,
        "adapter_id": adapter_id,
        "resource_ref": resource_ref,
        "access_mode": "read",
    }
    return GovernedQuerySecurityResource(
        **values,
        request_sha256=request_sha256,
        resource_sha256=_fingerprint(
            GovernedQuerySecurityResource.schema_id, values, "resource_sha256"
        ),
    )


def build_query_security_request(
    *,
    request_payload_sha256: str,
    request_id: str,
    tenant_id: str,
    subject_context: SubjectContext,
    purpose_code: str,
    channel: str,
    adapter_id: str,
    resource_refs: tuple[str, ...],
    evaluated_at: datetime,
) -> GovernedQuerySecurityRequest:
    base = {
        "tenant_id": tenant_id,
        "request_id": request_id,
        "operation": "semantic.query.execute",
        "purpose_code": purpose_code,
        "subject_context": subject_context,
        "channel": channel,
        "adapter_id": adapter_id,
        "request_payload_sha256": request_payload_sha256,
        "evaluated_at": evaluated_at,
        "provider_access_performed": False,
    }
    provisional_resources = tuple(
        build_query_security_resource(
            position=index,
            channel=channel,
            adapter_id=adapter_id,
            resource_ref=resource_ref,
            request_sha256="0" * 64,
        )
        for index, resource_ref in enumerate(resource_refs)
    )
    provisional = {**base, "resources": provisional_resources}
    request_sha256 = _request_fingerprint(provisional)
    resources = tuple(
        item.model_copy(update={"request_sha256": request_sha256})
        for item in provisional_resources
    )
    values = {**base, "resources": resources}
    return GovernedQuerySecurityRequest(
        **values,
        request_sha256=_request_fingerprint(values),
    )


def require_query_security_ports(
    reader: GovernedQuerySecurityCurrentReader | None,
    audit_port: GovernedQuerySecurityAuditPort | None,
    tenant_id: str,
) -> tuple[GovernedQuerySecurityCurrentReader, GovernedQuerySecurityAuditPort]:
    if reader is None or audit_port is None:
        raise GovernedQuerySecurityConfigurationError(
            "governed query security requires both a live reader and audit port"
        )
    if (
        getattr(reader, "tenant_id", None) != tenant_id
        or getattr(audit_port, "tenant_id", None) != tenant_id
    ):
        raise GovernedQuerySecurityConfigurationError(
            "governed query security ports must be tenant-bound"
        )
    if not callable(getattr(reader, "governed_query_security_decision_current", None)):
        raise GovernedQuerySecurityConfigurationError("query security reader is invalid")
    if not callable(getattr(audit_port, "record_admission", None)) or not callable(
        getattr(audit_port, "record_outcome", None)
    ):
        raise GovernedQuerySecurityConfigurationError("query security audit port is invalid")
    return reader, audit_port


__all__ = [
    "GOVERNED_QUERY_SECURITY_PURPOSE",
    "GOVERNED_QUERY_SECURITY_REQUIRED_ENV",
    "GovernedQuerySecurityAuditAdmission",
    "GovernedQuerySecurityAuditOutcome",
    "GovernedQuerySecurityAuditPort",
    "GovernedQuerySecurityConfigurationError",
    "GovernedQuerySecurityCurrentReader",
    "GovernedQuerySecurityDecision",
    "GovernedQuerySecurityError",
    "GovernedQuerySecurityRequest",
    "GovernedQuerySecurityResource",
    "GovernedQuerySecurityPortResolver",
    "GovernedQuerySecurityUnavailableError",
    "InMemoryGovernedQuerySecurityAudit",
    "SecurityEventLedgerGovernedQueryAudit",
    "build_query_security_request",
    "build_query_security_resource",
    "configure_governed_query_security_port_resolver",
    "governed_query_security_required",
    "governed_query_security_resolver_configured",
    "require_query_security_ports",
    "resolve_governed_query_security_ports",
]
