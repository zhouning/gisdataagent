"""Approval-bound issuance for one immutable GIS service consumer binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .platform_contracts import (
    ApprovalCase,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
)
from .service_consumer_binding import ServiceConsumerBinding

if TYPE_CHECKING:
    from .platform_gateway import GatewayWriteResult, PlatformGateway

SERVICE_CONSUMER_BINDING_GRANT_SCHEMA = "gda.gis_service_consumer_binding_grant.v1"
SERVICE_CONSUMER_BINDING_GRANT_ACTION = "gis_service_consumer_binding.grant"


def service_consumer_binding_grant_plan_fingerprint(
    binding: ServiceConsumerBinding,
) -> str:
    """Fingerprint the exact proposed binding, excluding approval outcome facts."""

    return canonical_json_fingerprint(
        {
            "schema": SERVICE_CONSUMER_BINDING_GRANT_SCHEMA,
            "service_consumer_binding": binding.model_dump(
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


class ServiceConsumerBindingGrantPlan(BaseModel):
    """Typed, immutable payload that one independent human may approve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    service_urn: ResourceURNText
    service_consumer_binding: ServiceConsumerBinding
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> ServiceConsumerBindingGrantPlan:
        binding = self.service_consumer_binding
        if self.tenant_id != binding.tenant_id or self.service_urn != binding.service_urn:
            raise ValueError("grant plan tenant and service must match its binding")
        if binding.approval_case_ref is not None or binding.grant_plan_sha256 is not None:
            raise ValueError("grant plan binding must not include an approval outcome")
        if self.plan_sha256 != service_consumer_binding_grant_plan_fingerprint(binding):
            raise ValueError("plan_sha256 does not match service consumer binding grant")
        return self

    def approval_case_ref(self) -> str:
        return build_resource_urn(
            self.tenant_id,
            "approval_case",
            "gis-service-consumer-binding-grant-"
            f"{self.service_consumer_binding.service_consumer_binding_id.hex}",
        )

    def approval_context(self) -> dict[str, Any]:
        return {
            "schema": SERVICE_CONSUMER_BINDING_GRANT_SCHEMA,
            "grant_plan_sha256": self.plan_sha256,
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


def build_service_consumer_binding_grant_plan(
    binding: ServiceConsumerBinding,
) -> ServiceConsumerBindingGrantPlan:
    """Construct the only plan representation accepted by the issuance path."""

    values = {
        "tenant_id": binding.tenant_id,
        "service_urn": binding.service_urn,
        "service_consumer_binding": binding,
    }
    return ServiceConsumerBindingGrantPlan(
        **values,
        plan_sha256=service_consumer_binding_grant_plan_fingerprint(binding),
    )


def build_service_consumer_binding_grant_approval_case(
    plan: ServiceConsumerBindingGrantPlan,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    """Create the deterministic ApprovalCase for one exact grant plan."""

    return ApprovalCase(
        tenant_id=plan.tenant_id,
        approval_case_ref=plan.approval_case_ref(),
        target_resource_urn=plan.service_urn,
        target_fingerprint=plan.plan_sha256,
        action=SERVICE_CONSUMER_BINDING_GRANT_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ServiceConsumerBindingGrantRequestResult:
    plan: ServiceConsumerBindingGrantPlan
    approval_case: ApprovalCase
    created: bool


class ServiceConsumerBindingGrantService:
    """Reuse ApprovalCase authority before persisting an MVT consumer grant."""

    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_grant(
        self,
        plan: ServiceConsumerBindingGrantPlan,
        *,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ServiceConsumerBindingGrantRequestResult:
        case = build_service_consumer_binding_grant_approval_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ServiceConsumerBindingGrantRequestResult(
            plan=plan,
            approval_case=written.approval_case,
            created=written.created,
        )

    def issue(
        self,
        plan: ServiceConsumerBindingGrantPlan,
        *,
        approval_case_ref: str,
    ) -> GatewayWriteResult:
        if approval_case_ref != plan.approval_case_ref():
            raise ValueError("grant approval case does not identify this binding plan")
        binding = plan.service_consumer_binding.model_copy(
            update={
                "approval_case_ref": approval_case_ref,
                "grant_plan_sha256": plan.plan_sha256,
            }
        )
        return self._gateway.register_service_consumer_binding(binding)
