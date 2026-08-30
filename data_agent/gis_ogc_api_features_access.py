"""Release-bound access decision and audit boundary for OGC API Features reads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gis_service_control_plane import (
    GISServiceDefinitionVersion,
    GISServiceType,
    ServicePolicyBinding,
    ServiceReleaseBinding,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    SubjectContext,
    canonical_json_fingerprint,
)
from .security_event_ledger import SecurityEventLedger, SecurityEventLedgerError
from .service_consumer_binding import ServiceConsumerBinding

GOVERNED_OGC_FEATURES_ACCESS_ACTION = "ogc_features.read"
GOVERNED_OGC_FEATURES_ACCESS_PURPOSE = "ogc_features_read"
OGC_FEATURES_ACCESS_EVALUATOR = "workload:platform-gateway"


class OGCFeaturesAccessError(RuntimeError):
    """The OGC API Features access boundary could not complete safely."""


class OGCFeaturesAccessDeniedError(OGCFeaturesAccessError):
    """The active release policy does not admit this request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OGCFeaturesAccessUnavailableError(OGCFeaturesAccessError):
    """Required OGC API Features audit evidence could not be written."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _aware(value, "fingerprint time").isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], field_name: str) -> str:
    payload = dict(values)
    payload.pop(field_name, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class OGCFeaturesAccessRequest(_FrozenModel):
    """The exact release, collection, identity and query admitted to a read."""

    schema_id: ClassVar[str] = "gda.ogc-api-features-access-request.v1"

    tenant_id: str
    request_id: ShortName
    action: Literal["ogc_features.read"] = GOVERNED_OGC_FEATURES_ACCESS_ACTION
    subject_context: SubjectContext
    service_urn: NonEmptyText
    source_product_urn: NonEmptyText
    source_data_product_version_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    service_release_sha256: Sha256
    service_policy_binding_id: UUID
    service_policy_sha256: Sha256
    service_consumer_binding_id: UUID | None = None
    service_consumer_binding_sha256: Sha256 | None = None
    collection_id: ShortName
    limit: int = Field(ge=1, le=1000)
    bbox: tuple[float, float, float, float] | None = None
    evaluated_at: datetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> OGCFeaturesAccessRequest:
        _aware(self.evaluated_at, "evaluated_at")
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("OGC API Features access subject tenant differs")
        if self.subject_context.trace_id != self.request_id:
            raise ValueError("OGC API Features access trace differs from request")
        if self.subject_context.purpose != GOVERNED_OGC_FEATURES_ACCESS_PURPOSE:
            raise ValueError("OGC API Features access purpose is invalid")
        if (self.service_consumer_binding_id is None) != (
            self.service_consumer_binding_sha256 is None
        ):
            raise ValueError("OGC API Features service binding evidence is incomplete")
        if self.bbox is not None and (
            len(self.bbox) != 4
            or any(value != value or value in (float("inf"), float("-inf")) for value in self.bbox)
            or self.bbox[0] > self.bbox[2]
            or self.bbox[1] > self.bbox[3]
        ):
            raise ValueError("OGC API Features bbox is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("OGC API Features access request fingerprint is invalid")
        return self


class OGCFeaturesAccessDecision(_FrozenModel):
    """A short-lived allow decision for one concrete collection read."""

    schema_id: ClassVar[str] = "gda.ogc-api-features-access-decision.v1"

    request: OGCFeaturesAccessRequest
    effect: Literal["allow"] = "allow"
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    evaluator_subject: Literal["workload:platform-gateway"] = OGC_FEATURES_ACCESS_EVALUATOR
    obligations: tuple[Literal["release_bound_collection"], ...] = (
        "release_bound_collection",
    )
    decided_at: datetime
    expires_at: datetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> OGCFeaturesAccessDecision:
        decided_at = _aware(self.decided_at, "decided_at")
        expires_at = _aware(self.expires_at, "expires_at")
        if expires_at <= decided_at:
            raise ValueError("OGC API Features access decision window is invalid")
        if self.obligations != ("release_bound_collection",):
            raise ValueError("OGC API Features access decision obligations are incomplete")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"decision_sha256"}),
            "decision_sha256",
        )
        if self.decision_sha256 != expected:
            raise ValueError("OGC API Features access decision fingerprint is invalid")
        return self


@dataclass(frozen=True)
class OGCFeaturesAccessAdmission:
    attempt_id: UUID
    decision: OGCFeaturesAccessDecision


def _typed_subject(subject: SubjectContext) -> str:
    return f"{subject.subject_type.value}:{subject.subject_id}"


def build_ogc_features_access_decision(
    *,
    request_id: str,
    subject_context: SubjectContext,
    service_urn: str,
    definition: GISServiceDefinitionVersion,
    release: ServiceReleaseBinding,
    service_policy: ServicePolicyBinding,
    service_consumer_binding: ServiceConsumerBinding | None,
    collection_id: str,
    limit: int,
    bbox: tuple[float, float, float, float] | None,
    evaluated_at: datetime,
    expires_at: datetime,
) -> OGCFeaturesAccessDecision:
    """Validate the executable Features policy and seal its exact request scope."""

    roles = subject_context.roles
    if len(roles) != 1:
        raise OGCFeaturesAccessDeniedError(
            "ogc_features_role_ambiguous",
            "Exactly one role is required for OGC API Features read",
        )
    if subject_context.purpose != GOVERNED_OGC_FEATURES_ACCESS_PURPOSE:
        raise OGCFeaturesAccessDeniedError(
            "ogc_features_purpose_denied",
            "The request purpose is not admitted for OGC API Features read",
        )
    if definition.service_type != GISServiceType.FEATURE:
        raise OGCFeaturesAccessDeniedError(
            "service_type_mismatch",
            "The active service is not a feature service",
        )
    if service_policy.action != GOVERNED_OGC_FEATURES_ACCESS_ACTION:
        raise OGCFeaturesAccessDeniedError(
            "service_policy_action_mismatch",
            "The active service policy is not an OGC API Features read policy",
        )
    role = roles[0]
    if role not in service_policy.allowed_roles:
        raise OGCFeaturesAccessDeniedError(
            "service_policy_denied",
            "The active service policy does not admit this role for OGC API Features read",
        )
    binding_required = role in service_policy.consumer_binding_required_roles
    if binding_required and service_consumer_binding is None:
        raise OGCFeaturesAccessDeniedError(
            "service_consumer_binding_required",
            "An active ServiceConsumerBinding for this GIS release is required",
        )
    if service_consumer_binding is not None:
        if (
            service_consumer_binding.tenant_id != subject_context.tenant_id
            or service_consumer_binding.service_urn != service_urn
            or service_consumer_binding.service_definition_version_id
            != definition.service_definition_version_id
            or service_consumer_binding.service_release_binding_id
            != release.service_release_binding_id
            or service_consumer_binding.consumer_ref != _typed_subject(subject_context)
            or service_consumer_binding.action != GOVERNED_OGC_FEATURES_ACCESS_ACTION
            or service_consumer_binding.purpose != GOVERNED_OGC_FEATURES_ACCESS_PURPOSE
            or service_consumer_binding.expires_at <= evaluated_at
        ):
            raise OGCFeaturesAccessDeniedError(
                "service_consumer_binding_denied",
                "The active ServiceConsumerBinding does not match this OGC API Features request",
            )
        operations = service_consumer_binding.scope.get("operations")
        if (
            not isinstance(operations, list)
            or service_policy.required_consumer_operation not in operations
        ):
            raise OGCFeaturesAccessDeniedError(
                "service_consumer_scope_denied",
                "The active ServiceConsumerBinding does not grant OGC API Features read",
            )

    values = {
        "tenant_id": subject_context.tenant_id,
        "request_id": request_id,
        "action": GOVERNED_OGC_FEATURES_ACCESS_ACTION,
        "subject_context": subject_context,
        "service_urn": service_urn,
        "source_product_urn": definition.source_product_urn,
        "source_data_product_version_id": definition.source_data_product_version_id,
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "service_release_sha256": release.binding_sha256,
        "service_policy_binding_id": service_policy.service_policy_binding_id,
        "service_policy_sha256": service_policy.policy_sha256,
        "service_consumer_binding_id": (
            None
            if service_consumer_binding is None
            else service_consumer_binding.service_consumer_binding_id
        ),
        "service_consumer_binding_sha256": (
            None
            if service_consumer_binding is None
            else service_consumer_binding.binding_sha256
        ),
        "collection_id": collection_id,
        "limit": limit,
        "bbox": bbox,
        "evaluated_at": evaluated_at,
    }
    request = OGCFeaturesAccessRequest(
        **values,
        request_sha256=_fingerprint(
            OGCFeaturesAccessRequest.schema_id, values, "request_sha256"
        ),
    )
    decision_values = {
        "request": request,
        "effect": "allow",
        "policy_ref": (
            f"gda://{subject_context.tenant_id}/service_policy/"
            f"{service_policy.service_policy_binding_id}"
        ),
        "policy_version": service_policy.version_key,
        "evaluator_subject": OGC_FEATURES_ACCESS_EVALUATOR,
        "obligations": ("release_bound_collection",),
        "decided_at": evaluated_at,
        "expires_at": expires_at,
    }
    return OGCFeaturesAccessDecision(
        **decision_values,
        decision_sha256=_fingerprint(
            OGCFeaturesAccessDecision.schema_id, decision_values, "decision_sha256"
        ),
    )


class OGCFeaturesAccessService:
    """Seal and audit Features admission before exposing any provider response."""

    def __init__(
        self,
        *,
        ledger: SecurityEventLedger | None = None,
        now: Callable[[], datetime] | None = None,
        attempt_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._ledger = ledger or SecurityEventLedger()
        self._now = now or (lambda: datetime.now(UTC))
        self._attempt_id_factory = attempt_id_factory

    @staticmethod
    def _details(decision: OGCFeaturesAccessDecision) -> dict[str, Any]:
        request = decision.request
        return {
            "access_schema": OGCFeaturesAccessDecision.schema_id,
            "request_sha256": request.request_sha256,
            "decision_sha256": decision.decision_sha256,
            "purpose": request.subject_context.purpose,
            "source_product_urn": request.source_product_urn,
            "source_data_product_version_id": str(request.source_data_product_version_id),
            "service_definition_version_id": str(request.service_definition_version_id),
            "service_release_binding_id": str(request.service_release_binding_id),
            "service_release_sha256": request.service_release_sha256,
            "service_policy_binding_id": str(request.service_policy_binding_id),
            "service_policy_sha256": request.service_policy_sha256,
            "service_consumer_binding_id": (
                None
                if request.service_consumer_binding_id is None
                else str(request.service_consumer_binding_id)
            ),
            "collection_id": request.collection_id,
            "limit": request.limit,
            "bbox": request.bbox,
        }

    def _audit_denied(
        self,
        *,
        attempt_id: UUID,
        subject_context: SubjectContext,
        service_urn: str,
        error: OGCFeaturesAccessDeniedError,
    ) -> None:
        try:
            self._ledger.append(
                tenant_id=subject_context.tenant_id,
                attempt_id=attempt_id,
                phase="denied",
                action=GOVERNED_OGC_FEATURES_ACCESS_ACTION,
                outcome="denied",
                actor_subject=_typed_subject(subject_context),
                resource_ref=service_urn,
                reason="release_bound_ogc_features_access_denied",
                details={
                    "purpose": subject_context.purpose,
                    "role": subject_context.roles[0] if subject_context.roles else None,
                    "denial_code": error.code,
                },
            )
        except SecurityEventLedgerError:
            return

    def admit(
        self,
        *,
        request_id: str,
        subject_context: SubjectContext,
        service_urn: str,
        definition: GISServiceDefinitionVersion,
        release: ServiceReleaseBinding,
        service_policy: ServicePolicyBinding,
        service_consumer_binding: ServiceConsumerBinding | None,
        collection_id: str,
        limit: int,
        bbox: tuple[float, float, float, float] | None,
    ) -> OGCFeaturesAccessAdmission:
        attempt_id = self._attempt_id_factory()
        evaluated_at = _aware(self._now(), "OGC API Features access clock")
        try:
            decision = build_ogc_features_access_decision(
                request_id=request_id,
                subject_context=subject_context,
                service_urn=service_urn,
                definition=definition,
                release=release,
                service_policy=service_policy,
                service_consumer_binding=service_consumer_binding,
                collection_id=collection_id,
                limit=limit,
                bbox=bbox,
                evaluated_at=evaluated_at,
                expires_at=evaluated_at + timedelta(minutes=5),
            )
        except OGCFeaturesAccessDeniedError as error:
            self._audit_denied(
                attempt_id=attempt_id,
                subject_context=subject_context,
                service_urn=service_urn,
                error=error,
            )
            raise
        except (TypeError, ValueError) as error:
            raise OGCFeaturesAccessUnavailableError(
                "OGC API Features access decision could not be constructed"
            ) from error

        try:
            self._ledger.append(
                tenant_id=subject_context.tenant_id,
                attempt_id=attempt_id,
                phase="admitted",
                action=GOVERNED_OGC_FEATURES_ACCESS_ACTION,
                outcome="admitted",
                actor_subject=_typed_subject(subject_context),
                resource_ref=service_urn,
                reason="release_bound_ogc_features_access_admitted_before_provider_read",
                details={**self._details(decision), "provider_invocations": 0},
            )
        except SecurityEventLedgerError as error:
            raise OGCFeaturesAccessUnavailableError(
                "OGC API Features access admission audit is unavailable"
            ) from error
        return OGCFeaturesAccessAdmission(attempt_id=attempt_id, decision=decision)

    def record_success(
        self,
        admission: OGCFeaturesAccessAdmission,
        *,
        content: bytes,
        status_code: int,
        media_type: str,
        feature_count: int,
    ) -> None:
        decision = admission.decision
        try:
            self._ledger.append(
                tenant_id=decision.request.tenant_id,
                attempt_id=admission.attempt_id,
                phase="outcome",
                action=GOVERNED_OGC_FEATURES_ACCESS_ACTION,
                outcome="success",
                actor_subject=_typed_subject(decision.request.subject_context),
                resource_ref=decision.request.service_urn,
                reason="release_bound_ogc_features_provider_read_succeeded",
                details={
                    **self._details(decision),
                    "provider_invocations": 1,
                    "response_status_code": status_code,
                    "response_media_type": media_type,
                    "feature_count": feature_count,
                    "response_content_sha256": hashlib.sha256(content).hexdigest(),
                    "response_content_bytes": len(content),
                },
            )
        except SecurityEventLedgerError as error:
            raise OGCFeaturesAccessUnavailableError(
                "OGC API Features access outcome audit is unavailable"
            ) from error

    def record_failure(
        self,
        admission: OGCFeaturesAccessAdmission,
        *,
        error: Exception,
    ) -> None:
        decision = admission.decision
        try:
            self._ledger.append(
                tenant_id=decision.request.tenant_id,
                attempt_id=admission.attempt_id,
                phase="outcome",
                action=GOVERNED_OGC_FEATURES_ACCESS_ACTION,
                outcome="failure",
                actor_subject=_typed_subject(decision.request.subject_context),
                resource_ref=decision.request.service_urn,
                reason="release_bound_ogc_features_provider_read_failed",
                details={
                    **self._details(decision),
                    "provider_invocations": 1,
                    "provider_error_type": type(error).__name__,
                },
            )
        except SecurityEventLedgerError as ledger_error:
            raise OGCFeaturesAccessUnavailableError(
                "OGC API Features access outcome audit is unavailable"
            ) from ledger_error


__all__ = [
    "GOVERNED_OGC_FEATURES_ACCESS_ACTION",
    "GOVERNED_OGC_FEATURES_ACCESS_PURPOSE",
    "OGCFeaturesAccessAdmission",
    "OGCFeaturesAccessDecision",
    "OGCFeaturesAccessDeniedError",
    "OGCFeaturesAccessError",
    "OGCFeaturesAccessRequest",
    "OGCFeaturesAccessService",
    "OGCFeaturesAccessUnavailableError",
    "build_ogc_features_access_decision",
]
