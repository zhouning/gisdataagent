"""Content-bound impact facts for GIS service consumer migrations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import TenantId, canonical_json_fingerprint

_ACTOR_REF_RE = re.compile(r"^(human|workload|agent|service):[^\s]{1,511}$")
_SERVICE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$"
)

GIS_SERVICE_CONSUMER_BINDING_MIGRATION_IMPACT_SCHEMA = (
    "gda.gis_service_consumer_binding_migration_impact.v1"
)


class GISServiceConsumerBindingMigrationImpact(BaseModel):
    """One exact GIS service release impact of a product migration notice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    impact_id: UUID
    source_service_consumer_binding_id: UUID
    source_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_urn: str
    consumer_ref: str = Field(min_length=1, max_length=512)
    source_service_definition_version_id: UUID
    source_service_release_binding_id: UUID
    target_service_definition_version_id: UUID
    target_service_release_binding_id: UUID
    source_product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    migration_state_id: UUID
    notification_id: UUID
    recorded_by: str = Field(min_length=1, max_length=512)
    recorded_at: datetime
    impact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("service_urn")
    @classmethod
    def _valid_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("service_urn must identify a GIS service")
        return value

    @field_validator("consumer_ref")
    @classmethod
    def _valid_consumer_ref(cls, value: str) -> str:
        value = value.strip()
        if _ACTOR_REF_RE.fullmatch(value) is None:
            raise ValueError("consumer_ref must use a typed subject reference")
        return value

    @field_validator("source_product_urn")
    @classmethod
    def _valid_source_product_urn(cls, value: str) -> str:
        if not value.startswith("gda://") or "/data_product/" not in value:
            raise ValueError("source_product_urn must identify a DataProduct")
        return value

    @field_validator("recorded_by")
    @classmethod
    def _valid_recorded_by(cls, value: str) -> str:
        value = value.strip()
        if _ACTOR_REF_RE.fullmatch(value) is None:
            raise ValueError("recorded_by must use a typed platform subject")
        return value

    @field_validator("recorded_at")
    @classmethod
    def _aware_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_impact(self) -> GISServiceConsumerBindingMigrationImpact:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if self.source_product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("source_product_urn tenant must match tenant_id")
        if self.from_product_version_id == self.to_product_version_id:
            raise ValueError("migration impact must bind different product versions")
        if self.source_service_definition_version_id == self.target_service_definition_version_id:
            raise ValueError("migration impact source and target definitions must differ")
        if self.source_service_release_binding_id == self.target_service_release_binding_id:
            raise ValueError("migration impact source and target releases must differ")
        if self.impact_sha256 != gis_service_consumer_binding_migration_impact_fingerprint(self):
            raise ValueError("impact_sha256 does not match the migration impact")
        return self


def gis_service_consumer_binding_migration_impact_fingerprint(
    value: GISServiceConsumerBindingMigrationImpact | dict[str, Any],
) -> str:
    """Fingerprint all immutable impact identity fields except its fingerprint."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="python", exclude={"impact_sha256"})
        payload = _canonical(payload)
    else:
        payload = {
            key: item
            for key, item in value.items()
            if key != "impact_sha256"
        }
        payload = _canonical(payload)
    payload.pop("recorded_by", None)
    payload.pop("recorded_at", None)
    payload["schema"] = GIS_SERVICE_CONSUMER_BINDING_MIGRATION_IMPACT_SCHEMA
    return canonical_json_fingerprint(payload)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


__all__ = [
    "GIS_SERVICE_CONSUMER_BINDING_MIGRATION_IMPACT_SCHEMA",
    "GISServiceConsumerBindingMigrationImpact",
    "gis_service_consumer_binding_migration_impact_fingerprint",
]
