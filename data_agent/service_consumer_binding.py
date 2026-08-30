"""Immutable consumer authorization for one governed GIS service release.

This narrow profile authorizes one protocol read for an exact service definition
and release. Product ConsumerBinding remains the authority for DataProduct
promotion; it is not sufficient to expose a protocol endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

_JSON_VALUE_ADAPTER = TypeAdapter(Any)


class ServiceConsumerBinding(BaseModel):
    """One immutable protocol-read grant for a specific GIS service release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    service_consumer_binding_id: UUID
    service_urn: str
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    consumer_ref: str = Field(
        pattern=r"^(human|workload|agent|service):[^\s]{1,511}$"
    )
    action: Literal["mvt.read", "ogc_features.read"] = "mvt.read"
    purpose: Literal["gis_mvt_read", "ogc_features_read"] = "gis_mvt_read"
    scope: dict[str, Any]
    credential_ref: str = Field(min_length=1, max_length=512)
    expires_at: datetime
    compatibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    compatibility_evidence: dict[str, Any]
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_case_ref: ResourceURNText | None = None
    grant_plan_sha256: Sha256 | None = None
    renewal_of_binding_id: UUID | None = None
    renewal_approval_case_ref: ResourceURNText | None = None
    renewal_plan_sha256: Sha256 | None = None

    @field_validator("created_at", "expires_at")
    @classmethod
    def _timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_binding(self) -> ServiceConsumerBinding:
        service = parse_resource_urn(self.service_urn)
        if service["tenant_id"] != self.tenant_id or service["resource_kind"] != "gis_service":
            raise ValueError("service_urn must identify a tenant GIS service Resource")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.scope != {"operations": ["read"]}:
            raise ValueError(
                "GIS service binding scope must be exactly operations=[read]"
            )
        expected_purpose = {
            "mvt.read": "gis_mvt_read",
            "ogc_features.read": "ogc_features_read",
        }[self.action]
        if self.purpose != expected_purpose:
            raise ValueError("service binding action and purpose do not match")
        if not self.compatibility_evidence:
            raise ValueError("compatibility_evidence is required")
        if (self.approval_case_ref is None) != (self.grant_plan_sha256 is None):
            raise ValueError(
                "approval_case_ref and grant_plan_sha256 must be set together"
            )
        renewal_fields = (
            self.renewal_of_binding_id,
            self.renewal_approval_case_ref,
            self.renewal_plan_sha256,
        )
        if any(value is None for value in renewal_fields) and any(
            value is not None for value in renewal_fields
        ):
            raise ValueError("renewal binding fields must be set together")
        if self.approval_case_ref is not None and any(
            value is not None for value in renewal_fields
        ):
            raise ValueError("grant and renewal approval facts are mutually exclusive")
        if self.approval_case_ref is not None:
            approval = parse_resource_urn(self.approval_case_ref)
            if (
                approval["tenant_id"] != self.tenant_id
                or approval["resource_kind"] != "approval_case"
            ):
                raise ValueError(
                    "approval_case_ref must identify a tenant ApprovalCase Resource"
                )
        if self.renewal_approval_case_ref is not None:
            renewal_approval = parse_resource_urn(self.renewal_approval_case_ref)
            if (
                renewal_approval["tenant_id"] != self.tenant_id
                or renewal_approval["resource_kind"] != "approval_case"
            ):
                raise ValueError(
                    "renewal_approval_case_ref must identify a tenant ApprovalCase Resource"
                )
        if self.binding_sha256 != service_consumer_binding_fingerprint(self):
            raise ValueError("binding_sha256 does not match the service binding")
        return self


def service_consumer_binding_fingerprint(
    value: ServiceConsumerBinding | dict[str, Any],
) -> str:
    """Fingerprint the complete immutable service-release authorization."""

    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json",
            exclude={
                "binding_sha256",
                "approval_case_ref",
                "grant_plan_sha256",
                "renewal_of_binding_id",
                "renewal_approval_case_ref",
                "renewal_plan_sha256",
            },
        )
    else:
        payload = {"action": "mvt.read", "purpose": "gis_mvt_read", **value}
        payload.pop("binding_sha256", None)
        payload.pop("approval_case_ref", None)
        payload.pop("grant_plan_sha256", None)
        payload.pop("renewal_of_binding_id", None)
        payload.pop("renewal_approval_case_ref", None)
        payload.pop("renewal_plan_sha256", None)
    return canonical_json_fingerprint(
        _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    )
