"""Approval-bound, append-only renewal for one GIS service consumer binding."""

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

SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA = (
    "gda.gis_service_consumer_binding_renewal.v1"
)
SERVICE_CONSUMER_BINDING_RENEWAL_ACTION = "gis_service_consumer_binding.renew"


def service_consumer_binding_renewal_plan_fingerprint(
    *,
    source_binding_id: UUID,
    source_binding_sha256: str,
    target: ServiceConsumerBinding,
    renewal_id: UUID,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA,
            "source_binding_id": str(source_binding_id),
            "source_binding_sha256": source_binding_sha256,
            "renewal_id": str(renewal_id),
            "service_consumer_binding": target.model_dump(
                mode="json",
                exclude={
                    "approval_case_ref",
                    "grant_plan_sha256",
                    "renewal_of_binding_id",
                    "renewal_approval_case_ref",
                    "renewal_plan_sha256",
                },
            ),
        }
    )


class ServiceConsumerBindingRenewalPlan(BaseModel):
    """Complete target binding and source identity reviewed as one plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    target_resource_urn: ResourceURNText
    source_binding_id: UUID
    source_binding_sha256: Sha256
    service_consumer_binding_renewal_id: UUID
    service_consumer_binding: ServiceConsumerBinding
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> ServiceConsumerBindingRenewalPlan:
        target = parse_resource_urn(self.target_resource_urn)
        binding = self.service_consumer_binding
        if target["tenant_id"] != self.tenant_id or target["resource_kind"] != (
            "service_consumer_binding"
        ):
            raise ValueError("renewal target must identify the tenant service binding")
        if target["resource_id"] != binding.service_consumer_binding_id.hex:
            raise ValueError("renewal target must identify the target binding")
        if binding.tenant_id != self.tenant_id:
            raise ValueError("renewal binding tenant must match the plan")
        if (
            binding.renewal_of_binding_id is not None
            or binding.renewal_approval_case_ref is not None
        ):
            raise ValueError("renewal plan binding must not include an approval outcome")
        if binding.approval_case_ref is not None or binding.grant_plan_sha256 is not None:
            raise ValueError("renewal plan binding must not include a grant outcome")
        if binding.service_consumer_binding_id == self.source_binding_id:
            raise ValueError("renewal must create a new binding identity")
        if self.plan_sha256 != service_consumer_binding_renewal_plan_fingerprint(
            source_binding_id=self.source_binding_id,
            source_binding_sha256=self.source_binding_sha256,
            target=binding,
            renewal_id=self.service_consumer_binding_renewal_id,
        ):
            raise ValueError("plan_sha256 does not match service consumer binding renewal")
        return self

    def approval_case_ref(self) -> str:
        return build_resource_urn(
            self.tenant_id,
            "approval_case",
            "gis-service-consumer-binding-renew-"
            f"{self.service_consumer_binding.service_consumer_binding_id.hex}",
        )

    def approval_context(self) -> dict[str, Any]:
        return {
            "schema": SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA,
            "renewal_plan_sha256": self.plan_sha256,
            "source_binding_id": str(self.source_binding_id),
            "source_binding_sha256": self.source_binding_sha256,
            "service_consumer_binding_renewal_id": str(
                self.service_consumer_binding_renewal_id
            ),
            "service_consumer_binding": self.service_consumer_binding.model_dump(
                mode="json",
                exclude={
                    "approval_case_ref",
                    "grant_plan_sha256",
                    "renewal_of_binding_id",
                    "renewal_approval_case_ref",
                    "renewal_plan_sha256",
                },
            ),
        }


def build_service_consumer_binding_renewal_plan(
    source_binding: ServiceConsumerBinding,
    target_binding: ServiceConsumerBinding,
    *,
    renewal_id: UUID | None = None,
) -> ServiceConsumerBindingRenewalPlan:
    if source_binding.service_urn != target_binding.service_urn:
        raise ValueError("renewal must keep the same GIS service")
    if source_binding.service_definition_version_id != target_binding.service_definition_version_id:
        raise ValueError("renewal must keep the same service definition version")
    if source_binding.service_release_binding_id != target_binding.service_release_binding_id:
        raise ValueError("renewal must keep the same service release")
    if source_binding.consumer_ref != target_binding.consumer_ref:
        raise ValueError("renewal must keep the same consumer")
    if target_binding.expires_at <= source_binding.expires_at:
        raise ValueError("renewal expiry must extend the source binding")
    target = target_binding.model_copy(
        update={
            "approval_case_ref": None,
            "grant_plan_sha256": None,
            "renewal_of_binding_id": None,
            "renewal_approval_case_ref": None,
            "renewal_plan_sha256": None,
        }
    )
    renewal_uuid = renewal_id or uuid4()
    values = {
        "tenant_id": source_binding.tenant_id,
        "target_resource_urn": build_resource_urn(
            source_binding.tenant_id,
            "service_consumer_binding",
            target.service_consumer_binding_id.hex,
        ),
        "source_binding_id": source_binding.service_consumer_binding_id,
        "source_binding_sha256": source_binding.binding_sha256,
        "service_consumer_binding_renewal_id": renewal_uuid,
        "service_consumer_binding": target,
    }
    return ServiceConsumerBindingRenewalPlan(
        **values,
        plan_sha256=service_consumer_binding_renewal_plan_fingerprint(
            source_binding_id=values["source_binding_id"],
            source_binding_sha256=values["source_binding_sha256"],
            target=target,
            renewal_id=renewal_uuid,
        ),
    )


def build_service_consumer_binding_renewal_approval_case(
    plan: ServiceConsumerBindingRenewalPlan,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    return ApprovalCase(
        tenant_id=plan.tenant_id,
        approval_case_ref=plan.approval_case_ref(),
        target_resource_urn=plan.target_resource_urn,
        target_fingerprint=plan.plan_sha256,
        action=SERVICE_CONSUMER_BINDING_RENEWAL_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


class ServiceConsumerBindingRenewal(BaseModel):
    """Append-only fact linking a replacement binding to its source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    service_consumer_binding_renewal_id: UUID
    source_binding_id: UUID
    source_binding_sha256: Sha256
    target_binding_id: UUID
    target_binding_sha256: Sha256
    approval_case_ref: ResourceURNText
    renewal_plan_sha256: Sha256
    renewed_by: str = Field(pattern=r"^human:[^\s]{1,511}$")
    renewed_at: datetime

    @model_validator(mode="after")
    def _consistent_fact(self) -> ServiceConsumerBindingRenewal:
        case = parse_resource_urn(self.approval_case_ref)
        if case["tenant_id"] != self.tenant_id or case["resource_kind"] != "approval_case":
            raise ValueError("approval_case_ref must identify a tenant ApprovalCase")
        if self.source_binding_id == self.target_binding_id:
            raise ValueError("renewal source and target must differ")
        if self.renewed_at.tzinfo is None or self.renewed_at.utcoffset() is None:
            raise ValueError("renewed_at must include a timezone")
        return self


@dataclass(frozen=True)
class ServiceConsumerBindingRenewalRequestResult:
    plan: ServiceConsumerBindingRenewalPlan
    approval_case: ApprovalCase
    created: bool


@dataclass(frozen=True)
class ServiceConsumerBindingRenewalResult:
    plan: ServiceConsumerBindingRenewalPlan
    approval_case: ApprovalCase
    binding: GatewayWriteResult


class ServiceConsumerBindingRenewalService:
    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_renewal(
        self,
        plan: ServiceConsumerBindingRenewalPlan,
        *,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ServiceConsumerBindingRenewalRequestResult:
        case = build_service_consumer_binding_renewal_approval_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ServiceConsumerBindingRenewalRequestResult(
            plan=plan, approval_case=written.approval_case, created=written.created
        )

    def renew(
        self,
        plan: ServiceConsumerBindingRenewalPlan,
        *,
        approval_case_ref: str,
        renewed_at: datetime | None = None,
    ) -> ServiceConsumerBindingRenewalResult:
        if approval_case_ref != plan.approval_case_ref():
            raise ValueError("renewal approval case does not identify this binding plan")
        case = self._approval_authority.get(plan.tenant_id, approval_case_ref)
        target = plan.service_consumer_binding.model_copy(
            update={
                "renewal_of_binding_id": plan.source_binding_id,
                "renewal_approval_case_ref": approval_case_ref,
                "renewal_plan_sha256": plan.plan_sha256,
            }
        )
        fact = ServiceConsumerBindingRenewal(
            tenant_id=plan.tenant_id,
            service_consumer_binding_renewal_id=(
                plan.service_consumer_binding_renewal_id
            ),
            source_binding_id=plan.source_binding_id,
            source_binding_sha256=plan.source_binding_sha256,
            target_binding_id=target.service_consumer_binding_id,
            target_binding_sha256=target.binding_sha256,
            approval_case_ref=approval_case_ref,
            renewal_plan_sha256=plan.plan_sha256,
            renewed_by=case.decided_by or "human:pending-renewal",
            renewed_at=renewed_at or case.decided_at or datetime.now(UTC),
        )
        written = self._gateway.register_service_consumer_binding_renewal(target, fact)
        return ServiceConsumerBindingRenewalResult(plan, case, written)


__all__ = [
    "SERVICE_CONSUMER_BINDING_RENEWAL_ACTION",
    "SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA",
    "ServiceConsumerBindingRenewal",
    "ServiceConsumerBindingRenewalPlan",
    "ServiceConsumerBindingRenewalRequestResult",
    "ServiceConsumerBindingRenewalResult",
    "ServiceConsumerBindingRenewalService",
    "build_service_consumer_binding_renewal_approval_case",
    "build_service_consumer_binding_renewal_plan",
    "service_consumer_binding_renewal_plan_fingerprint",
]
