"""Release-bound access decision and audit boundary for governed MVT reads."""

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
    MVTServingProjectionVersion,
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

GOVERNED_MVT_ACCESS_ACTION = "mvt.read"
GOVERNED_MVT_ACCESS_PURPOSE = "gis_mvt_read"
MVT_ACCESS_EVALUATOR = "workload:platform-gateway"


class MVTAccessError(RuntimeError):
    """The MVT access boundary could not complete safely."""


class MVTAccessDeniedError(MVTAccessError):
    """The release-bound service policy does not admit the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MVTAccessUnavailableError(MVTAccessError):
    """Required MVT access audit evidence could not be written."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _fingerprint(schema: str, values: dict[str, Any], field_name: str) -> str:
    payload = dict(values)
    payload.pop(field_name, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


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


class MVTAccessRequest(_FrozenModel):
    """The complete immutable scope evaluated before one provider tile read."""

    schema_id: ClassVar[str] = "gda.gis-mvt-access-request.v2"

    tenant_id: str
    request_id: ShortName
    action: Literal["mvt.read"] = GOVERNED_MVT_ACCESS_ACTION
    subject_context: SubjectContext
    service_urn: NonEmptyText
    source_product_urn: NonEmptyText
    source_data_product_version_id: UUID
    service_release_binding_id: UUID
    service_release_sha256: Sha256
    service_policy_binding_id: UUID
    service_policy_sha256: Sha256
    mvt_serving_projection_version_id: UUID
    mvt_serving_projection_sha256: Sha256
    service_consumer_binding_id: UUID | None = None
    service_consumer_binding_sha256: Sha256 | None = None
    tile_z: int = Field(ge=0, le=30)
    tile_x: int = Field(ge=0)
    tile_y: int = Field(ge=0)
    evaluated_at: datetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> MVTAccessRequest:
        _aware(self.evaluated_at, "evaluated_at")
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("MVT access subject tenant differs")
        if self.subject_context.trace_id != self.request_id:
            raise ValueError("MVT access trace differs from request")
        if (self.service_consumer_binding_id is None) != (
            self.service_consumer_binding_sha256 is None
        ):
            raise ValueError("MVT access service binding evidence is incomplete")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("MVT access request fingerprint is invalid")
        return self


class MVTAccessDecision(_FrozenModel):
    """A signed allow decision for one concrete tile request."""

    schema_id: ClassVar[str] = "gda.gis-mvt-access-decision.v2"

    request: MVTAccessRequest
    effect: Literal["allow"] = "allow"
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    evaluator_subject: Literal["workload:platform-gateway"] = MVT_ACCESS_EVALUATOR
    obligations: tuple[
        Literal["release_bound_serving_projection", "private_cache_identity"], ...
    ] = ("private_cache_identity", "release_bound_serving_projection")
    decided_at: datetime
    expires_at: datetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> MVTAccessDecision:
        decided_at = _aware(self.decided_at, "decided_at")
        expires_at = _aware(self.expires_at, "expires_at")
        if expires_at <= decided_at:
            raise ValueError("MVT access decision window is invalid")
        if self.obligations != (
            "private_cache_identity",
            "release_bound_serving_projection",
        ):
            raise ValueError("MVT access decision obligations are incomplete")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"decision_sha256"}),
            "decision_sha256",
        )
        if self.decision_sha256 != expected:
            raise ValueError("MVT access decision fingerprint is invalid")
        return self


@dataclass(frozen=True)
class MVTAccessAdmission:
    attempt_id: UUID
    decision: MVTAccessDecision


def _typed_subject(subject: SubjectContext) -> str:
    return f"{subject.subject_type.value}:{subject.subject_id}"


def build_mvt_access_decision(
    *,
    request_id: str,
    subject_context: SubjectContext,
    service_urn: str,
    definition: GISServiceDefinitionVersion,
    release: ServiceReleaseBinding,
    service_policy: ServicePolicyBinding,
    serving_projection: MVTServingProjectionVersion,
    service_consumer_binding: ServiceConsumerBinding | None,
    z: int,
    x: int,
    y: int,
    evaluated_at: datetime,
    expires_at: datetime,
) -> MVTAccessDecision:
    """Validate the executable policy and seal its exact request scope."""

    roles = subject_context.roles
    if len(roles) != 1:
        raise MVTAccessDeniedError(
            "mvt_role_context_invalid",
            "MVT access requires exactly one authenticated role",
        )
    role = roles[0]
    if role not in service_policy.allowed_roles:
        raise MVTAccessDeniedError(
            "service_policy_denied",
            "The active service policy does not admit this role for MVT read",
        )

    binding_required = role in service_policy.consumer_binding_required_roles
    if binding_required and service_consumer_binding is None:
        raise MVTAccessDeniedError(
            "service_consumer_binding_required",
            "An active ServiceConsumerBinding for this GIS release is required",
        )
    if service_consumer_binding is not None:
        if (
            service_consumer_binding.tenant_id != subject_context.tenant_id
            or service_consumer_binding.service_urn != service_urn
            or (
                service_consumer_binding.service_definition_version_id
                != definition.service_definition_version_id
            )
            or (
                service_consumer_binding.service_release_binding_id
                != release.service_release_binding_id
            )
            or service_consumer_binding.consumer_ref != _typed_subject(subject_context)
            or service_consumer_binding.action != GOVERNED_MVT_ACCESS_ACTION
            or service_consumer_binding.purpose != GOVERNED_MVT_ACCESS_PURPOSE
            or service_consumer_binding.expires_at <= evaluated_at
        ):
            raise MVTAccessDeniedError(
                "service_consumer_binding_denied",
                "The active ServiceConsumerBinding does not match this MVT request",
            )
        operations = service_consumer_binding.scope.get("operations")
        if (
            not isinstance(operations, list)
            or service_policy.required_consumer_operation not in operations
        ):
            raise MVTAccessDeniedError(
                "service_consumer_scope_denied",
                "The active ServiceConsumerBinding does not grant MVT read access",
            )

    values = {
        "tenant_id": subject_context.tenant_id,
        "request_id": request_id,
        "action": GOVERNED_MVT_ACCESS_ACTION,
        "subject_context": subject_context,
        "service_urn": service_urn,
        "source_product_urn": definition.source_product_urn,
        "source_data_product_version_id": definition.source_data_product_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "service_release_sha256": release.binding_sha256,
        "service_policy_binding_id": service_policy.service_policy_binding_id,
        "service_policy_sha256": service_policy.policy_sha256,
        "mvt_serving_projection_version_id": (
            serving_projection.mvt_serving_projection_version_id
        ),
        "mvt_serving_projection_sha256": serving_projection.projection_sha256,
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
        "tile_z": z,
        "tile_x": x,
        "tile_y": y,
        "evaluated_at": evaluated_at,
    }
    request = MVTAccessRequest(
        **values,
        request_sha256=_fingerprint(
            MVTAccessRequest.schema_id, values, "request_sha256"
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
        "evaluator_subject": MVT_ACCESS_EVALUATOR,
        "obligations": (
            "private_cache_identity",
            "release_bound_serving_projection",
        ),
        "decided_at": evaluated_at,
        "expires_at": expires_at,
    }
    return MVTAccessDecision(
        **decision_values,
        decision_sha256=_fingerprint(
            MVTAccessDecision.schema_id, decision_values, "decision_sha256"
        ),
    )


class MVTAccessService:
    """Seal and audit MVT admission before exposing any provider response."""

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
    def _details(decision: MVTAccessDecision) -> dict[str, Any]:
        request = decision.request
        return {
            "access_schema": MVTAccessDecision.schema_id,
            "request_sha256": request.request_sha256,
            "decision_sha256": decision.decision_sha256,
            "purpose": request.subject_context.purpose,
            "source_product_urn": request.source_product_urn,
            "source_data_product_version_id": str(
                request.source_data_product_version_id
            ),
            "service_release_binding_id": str(request.service_release_binding_id),
            "service_release_sha256": request.service_release_sha256,
            "service_policy_binding_id": str(request.service_policy_binding_id),
            "service_policy_sha256": request.service_policy_sha256,
            "mvt_serving_projection_version_id": str(
                request.mvt_serving_projection_version_id
            ),
            "mvt_serving_projection_sha256": request.mvt_serving_projection_sha256,
            "service_consumer_binding_id": (
                None
                if request.service_consumer_binding_id is None
                else str(request.service_consumer_binding_id)
            ),
            "tile": {"z": request.tile_z, "x": request.tile_x, "y": request.tile_y},
        }

    def _audit_denied(
        self,
        *,
        attempt_id: UUID,
        subject_context: SubjectContext,
        service_urn: str,
        error: MVTAccessDeniedError,
    ) -> None:
        try:
            self._ledger.append(
                tenant_id=subject_context.tenant_id,
                attempt_id=attempt_id,
                phase="denied",
                action=GOVERNED_MVT_ACCESS_ACTION,
                outcome="denied",
                actor_subject=_typed_subject(subject_context),
                resource_ref=service_urn,
                reason="release_bound_mvt_access_denied",
                details={
                    "purpose": subject_context.purpose,
                    "role": subject_context.roles[0] if subject_context.roles else None,
                    "denial_code": error.code,
                },
            )
        except SecurityEventLedgerError:
            # A denial cannot become an allow because audit storage is unavailable.
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
        serving_projection: MVTServingProjectionVersion,
        service_consumer_binding: ServiceConsumerBinding | None,
        z: int,
        x: int,
        y: int,
    ) -> MVTAccessAdmission:
        attempt_id = self._attempt_id_factory()
        evaluated_at = _aware(self._now(), "MVT access clock")
        try:
            decision = build_mvt_access_decision(
                request_id=request_id,
                subject_context=subject_context,
                service_urn=service_urn,
                definition=definition,
                release=release,
                service_policy=service_policy,
                serving_projection=serving_projection,
                service_consumer_binding=service_consumer_binding,
                z=z,
                x=x,
                y=y,
                evaluated_at=evaluated_at,
                expires_at=evaluated_at + timedelta(minutes=5),
            )
        except MVTAccessDeniedError as error:
            self._audit_denied(
                attempt_id=attempt_id,
                subject_context=subject_context,
                service_urn=service_urn,
                error=error,
            )
            raise
        except (TypeError, ValueError) as error:
            raise MVTAccessUnavailableError(
                "MVT access decision could not be constructed"
            ) from error

        try:
            self._ledger.append(
                tenant_id=subject_context.tenant_id,
                attempt_id=attempt_id,
                phase="admitted",
                action=GOVERNED_MVT_ACCESS_ACTION,
                outcome="admitted",
                actor_subject=_typed_subject(subject_context),
                resource_ref=service_urn,
                reason="release_bound_mvt_access_admitted_before_provider_read",
                details={**self._details(decision), "provider_invocations": 0},
            )
        except SecurityEventLedgerError as error:
            raise MVTAccessUnavailableError(
                "MVT access admission audit is unavailable"
            ) from error
        return MVTAccessAdmission(attempt_id=attempt_id, decision=decision)

    def record_success(
        self,
        admission: MVTAccessAdmission,
        *,
        content: bytes,
        status_code: int,
        media_type: str,
        delivery_source: Literal["provider", "redis_cache"] = "provider",
    ) -> None:
        if delivery_source not in {"provider", "redis_cache"}:
            raise ValueError("unsupported MVT delivery source")
        decision = admission.decision
        provider_invocations = 1 if delivery_source == "provider" else 0
        reason = (
            "release_bound_mvt_provider_read_succeeded"
            if delivery_source == "provider"
            else "release_bound_mvt_redis_cache_read_succeeded"
        )
        try:
            self._ledger.append(
                tenant_id=decision.request.tenant_id,
                attempt_id=admission.attempt_id,
                phase="outcome",
                action=GOVERNED_MVT_ACCESS_ACTION,
                outcome="success",
                actor_subject=_typed_subject(decision.request.subject_context),
                resource_ref=decision.request.service_urn,
                reason=reason,
                details={
                    **self._details(decision),
                    "delivery_source": delivery_source,
                    "provider_invocations": provider_invocations,
                    "response_status_code": status_code,
                    "response_media_type": media_type,
                    "tile_content_sha256": hashlib.sha256(content).hexdigest(),
                    "tile_content_bytes": len(content),
                },
            )
        except SecurityEventLedgerError as error:
            raise MVTAccessUnavailableError(
                "MVT access outcome audit is unavailable"
            ) from error

    def record_failure(
        self,
        admission: MVTAccessAdmission,
        *,
        error: Exception,
    ) -> None:
        decision = admission.decision
        try:
            self._ledger.append(
                tenant_id=decision.request.tenant_id,
                attempt_id=admission.attempt_id,
                phase="outcome",
                action=GOVERNED_MVT_ACCESS_ACTION,
                outcome="failure",
                actor_subject=_typed_subject(decision.request.subject_context),
                resource_ref=decision.request.service_urn,
                reason="release_bound_mvt_provider_read_failed",
                details={
                    **self._details(decision),
                    "provider_invocations": 1,
                    "provider_error_type": type(error).__name__,
                },
            )
        except SecurityEventLedgerError as ledger_error:
            raise MVTAccessUnavailableError(
                "MVT access outcome audit is unavailable"
            ) from ledger_error


__all__ = [
    "GOVERNED_MVT_ACCESS_ACTION",
    "GOVERNED_MVT_ACCESS_PURPOSE",
    "MVTAccessAdmission",
    "MVTAccessDecision",
    "MVTAccessDeniedError",
    "MVTAccessError",
    "MVTAccessRequest",
    "MVTAccessService",
    "MVTAccessUnavailableError",
    "build_mvt_access_decision",
]
