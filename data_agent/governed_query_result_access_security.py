"""Live SPR contract for governed query-result consumption."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .governed_query_security import (
    GovernedQuerySecurityCurrentReader,
    build_query_security_request,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    SubjectContext,
    SubjectType,
    TenantId,
    canonical_json_fingerprint,
)

GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE = "query_result_access"
GOVERNED_QUERY_RESULT_ACCESS_OPERATION = "governed.query.result.access"


class GovernedQueryResultAccessSecurityError(RuntimeError):
    """The result-consumption security boundary failed closed."""


class GovernedQueryResultAccessSecurityDeniedError(
    GovernedQueryResultAccessSecurityError
):
    """The current policy does not admit the requested result consumption."""


class GovernedQueryResultAccessSecurityUnavailableError(
    GovernedQueryResultAccessSecurityError
):
    """The live policy reader could not produce a trustworthy decision."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _aware(value, "fingerprint time").isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint(
        {"schema": schema, "data": _json_ready(payload)}
    )


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


class GovernedQueryResultAccessSecurityResource(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-result-access-resource.v1"
    position: int = Field(ge=0, le=19)
    resource_ref: NonEmptyText
    consumption_mode: Literal["read", "download", "cache", "map", "report"]
    resource_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryResultAccessSecurityResource:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"resource_sha256"}),
            "resource_sha256",
        )
        if self.resource_sha256 != expected:
            raise ValueError("query result security resource fingerprint is invalid")
        return self


class GovernedQueryResultAccessSecurityRequest(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-result-access-request.v1"
    tenant_id: TenantId
    request_id: ShortName
    operation: Literal["governed.query.result.access"] = (
        GOVERNED_QUERY_RESULT_ACCESS_OPERATION
    )
    purpose_code: ShortName
    subject_context: SubjectContext
    channel: ShortName
    adapter_id: ShortName
    consumption_mode: Literal["read", "download", "cache", "map", "report"]
    request_payload_sha256: Sha256
    resources: tuple[GovernedQueryResultAccessSecurityResource, ...] = Field(
        min_length=1, max_length=20
    )
    evaluated_at: datetime
    external_access_performed: Literal[False] = False
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryResultAccessSecurityRequest:
        _aware(self.evaluated_at, "evaluated_at")
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("query result security subject tenant differs")
        if self.subject_context.purpose != self.purpose_code:
            raise ValueError("query result security subject purpose differs")
        if self.subject_context.trace_id != self.request_id:
            raise ValueError("query result security trace differs from request")
        if tuple(item.position for item in self.resources) != tuple(
            range(len(self.resources))
        ):
            raise ValueError("query result security resources must be ordered")
        if any(
            item.consumption_mode != self.consumption_mode for item in self.resources
        ):
            raise ValueError("query result security resource mode differs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("query result security request fingerprint is invalid")
        return self


class GovernedQueryResultAccessSecurityDecision(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-result-access-decision.v1"
    request: GovernedQueryResultAccessSecurityRequest
    effect: Literal["allow"] = "allow"
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    evaluator_subject: NonEmptyText
    obligations: tuple[NonEmptyText, ...] = ()
    decided_at: datetime
    expires_at: datetime
    authority_live_read_performed: Literal[True] = True
    external_access_performed: Literal[False] = False
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryResultAccessSecurityDecision:
        decided_at = _aware(self.decided_at, "decided_at")
        expires_at = _aware(self.expires_at, "expires_at")
        if expires_at <= decided_at:
            raise ValueError("query result security decision window is invalid")
        if self.obligations:
            raise ValueError("query result security obligations are not implemented")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"decision_sha256"}),
            "decision_sha256",
        )
        if self.decision_sha256 != expected:
            raise ValueError("query result security decision fingerprint is invalid")
        return self


def build_governed_query_result_access_security_request(
    *,
    tenant_id: str,
    request_id: str,
    actor_subject: str,
    roles: tuple[str, ...],
    purpose_code: str,
    channel: str,
    adapter_id: str,
    consumption_mode: Literal["read", "download", "cache", "map", "report"],
    resource_refs: tuple[str, ...],
    request_payload: Mapping[str, Any],
    evaluated_at: datetime,
) -> GovernedQueryResultAccessSecurityRequest:
    subject_type_value, separator, subject_id = actor_subject.partition(":")
    if not separator or not subject_id:
        raise ValueError("query result security actor must be a typed subject")
    subject_context = SubjectContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        subject_type=SubjectType(subject_type_value),
        roles=roles,
        purpose=purpose_code,
        trace_id=request_id,
    )
    resources = tuple(
        _build_resource(
            position=position,
            resource_ref=resource_ref,
            consumption_mode=consumption_mode,
        )
        for position, resource_ref in enumerate(resource_refs)
    )
    values = {
        "tenant_id": tenant_id,
        "request_id": request_id,
        "operation": GOVERNED_QUERY_RESULT_ACCESS_OPERATION,
        "purpose_code": purpose_code,
        "subject_context": subject_context,
        "channel": channel,
        "adapter_id": adapter_id,
        "consumption_mode": consumption_mode,
        "request_payload_sha256": canonical_json_fingerprint(
            _json_ready(dict(request_payload))
        ),
        "resources": resources,
        "evaluated_at": evaluated_at,
        "external_access_performed": False,
    }
    return GovernedQueryResultAccessSecurityRequest(
        **values,
        request_sha256=_fingerprint(
            GovernedQueryResultAccessSecurityRequest.schema_id,
            values,
            "request_sha256",
        ),
    )


def _build_resource(
    *,
    position: int,
    resource_ref: str,
    consumption_mode: Literal["read", "download", "cache", "map", "report"],
) -> GovernedQueryResultAccessSecurityResource:
    values = {
        "position": position,
        "resource_ref": resource_ref,
        "consumption_mode": consumption_mode,
    }
    return GovernedQueryResultAccessSecurityResource(
        **values,
        resource_sha256=_fingerprint(
            GovernedQueryResultAccessSecurityResource.schema_id,
            values,
            "resource_sha256",
        ),
    )


def evaluate_governed_query_result_access_security(
    request: GovernedQueryResultAccessSecurityRequest,
    reader: GovernedQuerySecurityCurrentReader,
    *,
    evaluated_at: datetime | None = None,
) -> GovernedQueryResultAccessSecurityDecision:
    if getattr(reader, "tenant_id", None) != request.tenant_id:
        raise GovernedQueryResultAccessSecurityUnavailableError(
            "query result security reader is not tenant-bound"
        )
    translated = build_query_security_request(
        request_payload_sha256=request.request_payload_sha256,
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        subject_context=request.subject_context,
        purpose_code=request.purpose_code,
        channel=request.channel,
        adapter_id=request.adapter_id,
        resource_refs=tuple(item.resource_ref for item in request.resources),
        evaluated_at=request.evaluated_at,
    )
    try:
        source = reader.governed_query_security_decision_current(translated)
    except Exception as exc:
        raise GovernedQueryResultAccessSecurityUnavailableError(
            "live query result security reader failed"
        ) from exc
    if source.request != translated:
        raise GovernedQueryResultAccessSecurityUnavailableError(
            "query result security decision scope differs"
        )
    current_time = _aware(evaluated_at or datetime.now(UTC), "authority check time")
    if source.effect != "allow":
        raise GovernedQueryResultAccessSecurityDeniedError(
            "query result access is not admitted by current policy"
        )
    if source.obligations:
        raise GovernedQueryResultAccessSecurityDeniedError(
            "query result access policy has unsupported obligations"
        )
    if source.decided_at > current_time or source.expires_at <= current_time:
        raise GovernedQueryResultAccessSecurityDeniedError(
            "query result access policy decision is not current"
        )
    values = {
        "request": request,
        "effect": "allow",
        "policy_ref": source.policy_ref,
        "policy_version": source.policy_version,
        "evaluator_subject": source.evaluator_subject,
        "obligations": (),
        "decided_at": source.decided_at,
        "expires_at": source.expires_at,
        "authority_live_read_performed": True,
        "external_access_performed": False,
    }
    return GovernedQueryResultAccessSecurityDecision(
        **values,
        decision_sha256=_fingerprint(
            GovernedQueryResultAccessSecurityDecision.schema_id,
            values,
            "decision_sha256",
        ),
    )


__all__ = [
    "GOVERNED_QUERY_RESULT_ACCESS_OPERATION",
    "GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE",
    "GovernedQueryResultAccessSecurityDecision",
    "GovernedQueryResultAccessSecurityDeniedError",
    "GovernedQueryResultAccessSecurityError",
    "GovernedQueryResultAccessSecurityRequest",
    "GovernedQueryResultAccessSecurityResource",
    "GovernedQueryResultAccessSecurityUnavailableError",
    "build_governed_query_result_access_security_request",
    "evaluate_governed_query_result_access_security",
]
