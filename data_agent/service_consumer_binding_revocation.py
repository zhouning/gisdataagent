"""Approval-bound, append-only revocation for one GIS service consumer binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .platform_contracts import (
    ApprovalCase,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .service_consumer_binding import ServiceConsumerBinding

if TYPE_CHECKING:
    from .platform_gateway import GatewayWriteResult, PlatformGateway

SERVICE_CONSUMER_BINDING_REVOKE_SCHEMA = (
    "gda.gis_service_consumer_binding_revocation.v1"
)
SERVICE_CONSUMER_BINDING_REVOKE_ACTION = "gis_service_consumer_binding.revoke"


def service_consumer_binding_revoke_plan_fingerprint(
    *,
    tenant_id: str,
    service_urn: str,
    service_consumer_binding_id: UUID,
    binding_sha256: str,
    service_release_binding_id: UUID,
    consumer_ref: str,
    service_consumer_binding_revocation_id: UUID,
    reason: str,
    context: dict[str, Any],
) -> str:
    """Fingerprint the complete proposed revoke operation."""

    return canonical_json_fingerprint(
        {
            "schema": SERVICE_CONSUMER_BINDING_REVOKE_SCHEMA,
            "tenant_id": tenant_id,
            "service_urn": service_urn,
            "service_consumer_binding_id": str(service_consumer_binding_id),
            "binding_sha256": binding_sha256,
            "service_release_binding_id": str(service_release_binding_id),
            "consumer_ref": consumer_ref,
            "service_consumer_binding_revocation_id": str(
                service_consumer_binding_revocation_id
            ),
            "reason": reason,
            "context": context,
        }
    )


class ServiceConsumerBindingRevokePlan(BaseModel):
    """Immutable payload independently approved before a binding is revoked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    target_resource_urn: ResourceURNText
    service_urn: ResourceURNText
    service_consumer_binding_id: UUID
    binding_sha256: Sha256
    service_release_binding_id: UUID
    consumer_ref: str = Field(
        pattern=r"^(human|workload|agent|service):[^\s]{1,511}$"
    )
    service_consumer_binding_revocation_id: UUID
    reason: str = Field(min_length=1, max_length=2048)
    context: dict[str, Any] = Field(default_factory=dict)
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> ServiceConsumerBindingRevokePlan:
        target = parse_resource_urn(self.target_resource_urn)
        service = parse_resource_urn(self.service_urn)
        if target["tenant_id"] != self.tenant_id or target["resource_kind"] != (
            "service_consumer_binding"
        ):
            raise ValueError("revoke target must identify the tenant service binding")
        if target["resource_id"] != self.service_consumer_binding_id.hex:
            raise ValueError("revoke target must identify the exact binding")
        if service["tenant_id"] != self.tenant_id or service["resource_kind"] != (
            "gis_service"
        ):
            raise ValueError("revoke service must identify a tenant GIS service")
        if not self.reason.strip():
            raise ValueError("revoke reason is required")
        expected = service_consumer_binding_revoke_plan_fingerprint(
            tenant_id=self.tenant_id,
            service_urn=self.service_urn,
            service_consumer_binding_id=self.service_consumer_binding_id,
            binding_sha256=self.binding_sha256,
            service_release_binding_id=self.service_release_binding_id,
            consumer_ref=self.consumer_ref,
            service_consumer_binding_revocation_id=(
                self.service_consumer_binding_revocation_id
            ),
            reason=self.reason,
            context=self.context,
        )
        if self.plan_sha256 != expected:
            raise ValueError("plan_sha256 does not match service consumer binding revoke")
        return self

    def approval_case_ref(self) -> str:
        return build_resource_urn(
            self.tenant_id,
            "approval_case",
            "gis-service-consumer-binding-revoke-"
            f"{self.service_consumer_binding_id.hex}",
        )

    def approval_context(self) -> dict[str, Any]:
        return {
            "schema": SERVICE_CONSUMER_BINDING_REVOKE_SCHEMA,
            "revoke_plan_sha256": self.plan_sha256,
            "service_consumer_binding_id": str(self.service_consumer_binding_id),
            "binding_sha256": self.binding_sha256,
            "service_urn": self.service_urn,
            "service_release_binding_id": str(self.service_release_binding_id),
            "consumer_ref": self.consumer_ref,
            "service_consumer_binding_revocation_id": str(
                self.service_consumer_binding_revocation_id
            ),
            "reason": self.reason,
            "context": self.context,
        }


class ServiceConsumerBindingRevocation(BaseModel):
    """Immutable revocation fact recorded beside, never inside, the binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    service_consumer_binding_revocation_id: UUID
    service_consumer_binding_id: UUID
    binding_sha256: Sha256
    approval_case_ref: ResourceURNText
    revoke_plan_sha256: Sha256
    reason: str = Field(min_length=1, max_length=2048)
    context: dict[str, Any] = Field(default_factory=dict)
    revoked_by: str = Field(pattern=r"^human:[^\s]{1,511}$")
    revoked_at: datetime

    @model_validator(mode="after")
    def _consistent_fact(self) -> ServiceConsumerBindingRevocation:
        case = parse_resource_urn(self.approval_case_ref)
        if case["tenant_id"] != self.tenant_id or case["resource_kind"] != (
            "approval_case"
        ):
            raise ValueError("approval_case_ref must identify a tenant ApprovalCase")
        if self.revoked_at.tzinfo is None or self.revoked_at.utcoffset() is None:
            raise ValueError("revoked_at must include a timezone")
        return self


def build_service_consumer_binding_revoke_plan(
    binding: ServiceConsumerBinding,
    *,
    reason: str,
    context: dict[str, Any] | None = None,
    revocation_id: UUID | None = None,
) -> ServiceConsumerBindingRevokePlan:
    """Construct the only plan representation accepted by the revoke path."""

    revoke_id = revocation_id or uuid4()
    values = {
        "tenant_id": binding.tenant_id,
        "target_resource_urn": build_resource_urn(
            binding.tenant_id,
            "service_consumer_binding",
            binding.service_consumer_binding_id.hex,
        ),
        "service_urn": binding.service_urn,
        "service_consumer_binding_id": binding.service_consumer_binding_id,
        "binding_sha256": binding.binding_sha256,
        "service_release_binding_id": binding.service_release_binding_id,
        "consumer_ref": binding.consumer_ref,
        "service_consumer_binding_revocation_id": revoke_id,
        "reason": reason,
        "context": context or {},
    }
    return ServiceConsumerBindingRevokePlan(
        **values,
        plan_sha256=service_consumer_binding_revoke_plan_fingerprint(
            tenant_id=values["tenant_id"],
            service_urn=values["service_urn"],
            service_consumer_binding_id=values["service_consumer_binding_id"],
            binding_sha256=values["binding_sha256"],
            service_release_binding_id=values["service_release_binding_id"],
            consumer_ref=values["consumer_ref"],
            service_consumer_binding_revocation_id=(
                values["service_consumer_binding_revocation_id"]
            ),
            reason=values["reason"],
            context=values["context"],
        ),
    )


def build_service_consumer_binding_revoke_approval_case(
    plan: ServiceConsumerBindingRevokePlan,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    """Create the deterministic ApprovalCase for one exact revoke plan."""

    return ApprovalCase(
        tenant_id=plan.tenant_id,
        approval_case_ref=plan.approval_case_ref(),
        target_resource_urn=plan.target_resource_urn,
        target_fingerprint=plan.plan_sha256,
        action=SERVICE_CONSUMER_BINDING_REVOKE_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ServiceConsumerBindingRevokeRequestResult:
    plan: ServiceConsumerBindingRevokePlan
    approval_case: ApprovalCase
    created: bool


@dataclass(frozen=True)
class ServiceConsumerBindingRevokeResult:
    plan: ServiceConsumerBindingRevokePlan
    approval_case: ApprovalCase
    revocation: GatewayWriteResult


class ServiceConsumerBindingRevocationService:
    """Reuse ApprovalCase authority before writing an append-only revoke fact."""

    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_revoke(
        self,
        plan: ServiceConsumerBindingRevokePlan,
        *,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ServiceConsumerBindingRevokeRequestResult:
        case = build_service_consumer_binding_revoke_approval_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ServiceConsumerBindingRevokeRequestResult(
            plan=plan,
            approval_case=written.approval_case,
            created=written.created,
        )

    def revoke(
        self,
        plan: ServiceConsumerBindingRevokePlan,
        *,
        approval_case_ref: str,
        revoked_at: datetime | None = None,
    ) -> ServiceConsumerBindingRevokeResult:
        if approval_case_ref != plan.approval_case_ref():
            raise ValueError("revoke approval case does not identify this binding plan")
        case = self._approval_authority.get(plan.tenant_id, approval_case_ref)
        fact = ServiceConsumerBindingRevocation(
            tenant_id=plan.tenant_id,
            service_consumer_binding_revocation_id=(
                plan.service_consumer_binding_revocation_id
            ),
            service_consumer_binding_id=plan.service_consumer_binding_id,
            binding_sha256=plan.binding_sha256,
            approval_case_ref=approval_case_ref,
            revoke_plan_sha256=plan.plan_sha256,
            reason=plan.reason,
            context=plan.context,
            # Pending/rejected cases deliberately reach the database recorder
            # with a non-authoritative placeholder; SQL must reject them.
            revoked_by=case.decided_by or "human:pending-revoke",
            revoked_at=revoked_at or case.decided_at or datetime.now(UTC),
        )
        result = self._gateway.register_service_consumer_binding_revocation(fact)
        return ServiceConsumerBindingRevokeResult(plan, case, result)
