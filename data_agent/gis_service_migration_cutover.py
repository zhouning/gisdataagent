"""Atomic, evidence-bound cutover of a governed GIS service migration."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import TenantId, canonical_json_fingerprint

_ACTOR_REF_RE = re.compile(r"^(human|workload|agent|service):[^\s]{1,511}$")
_SERVICE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$"
)

GIS_SERVICE_MIGRATION_CUTOVER_SCHEMA = "gda.gis_service_migration_cutover.v1"


class GISServiceMigrationCutoverRequest(BaseModel):
    """CAS request naming both endpoint and release sides of one cutover."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    cutover_id: UUID
    service_urn: str
    source_endpoint_revision_id: UUID
    target_endpoint_revision_id: UUID
    source_service_definition_version_id: UUID
    source_service_release_binding_id: UUID
    target_service_definition_version_id: UUID
    target_service_release_binding_id: UUID
    source_product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    expected_state_version: int = Field(ge=0)
    actor_subject: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=512)
    occurred_at: datetime

    @field_validator("service_urn")
    @classmethod
    def _valid_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("service_urn must identify a GIS service")
        return value

    @field_validator("source_product_urn")
    @classmethod
    def _valid_product_urn(cls, value: str) -> str:
        if not value.startswith("gda://") or "/data_product/" not in value:
            raise ValueError("source_product_urn must identify a DataProduct")
        return value

    @field_validator("actor_subject")
    @classmethod
    def _valid_actor(cls, value: str) -> str:
        value = value.strip()
        if _ACTOR_REF_RE.fullmatch(value) is None:
            raise ValueError("actor_subject must use a typed platform subject")
        return value

    @field_validator("reason", "idempotency_key")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cutover reason and idempotency key are required")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_request(self) -> GISServiceMigrationCutoverRequest:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if self.source_product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("source_product_urn tenant must match tenant_id")
        if self.source_endpoint_revision_id == self.target_endpoint_revision_id:
            raise ValueError("cutover endpoints must differ")
        if (
            self.source_service_definition_version_id
            == self.target_service_definition_version_id
        ):
            raise ValueError("cutover definitions must differ")
        if (
            self.source_service_release_binding_id
            == self.target_service_release_binding_id
        ):
            raise ValueError("cutover releases must differ")
        if self.from_product_version_id == self.to_product_version_id:
            raise ValueError("cutover product versions must differ")
        return self


class GISServiceMigrationCutover(BaseModel):
    """Immutable result and consumer-set evidence for one endpoint cutover."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    cutover_id: UUID
    service_urn: str
    source_endpoint_revision_id: UUID
    target_endpoint_revision_id: UUID
    source_service_definition_version_id: UUID
    source_service_release_binding_id: UUID
    target_service_definition_version_id: UUID
    target_service_release_binding_id: UUID
    source_product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    source_binding_count: int = Field(gt=0)
    impact_count: int = Field(gt=0)
    acknowledged_count: int = Field(gt=0)
    target_binding_count: int = Field(gt=0)
    impact_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledgement_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_binding_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    from_state_version: int = Field(ge=0)
    to_state_version: int = Field(gt=0)
    activation_event_id: UUID
    cache_transition_mode: Literal["release_namespace_rollover"]
    actor_subject: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=512)
    occurred_at: datetime
    cutover_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def _aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_cutover(self) -> GISServiceMigrationCutover:
        GISServiceMigrationCutoverRequest(
            tenant_id=self.tenant_id,
            cutover_id=self.cutover_id,
            service_urn=self.service_urn,
            source_endpoint_revision_id=self.source_endpoint_revision_id,
            target_endpoint_revision_id=self.target_endpoint_revision_id,
            source_service_definition_version_id=(
                self.source_service_definition_version_id
            ),
            source_service_release_binding_id=self.source_service_release_binding_id,
            target_service_definition_version_id=(
                self.target_service_definition_version_id
            ),
            target_service_release_binding_id=self.target_service_release_binding_id,
            source_product_urn=self.source_product_urn,
            from_product_version_id=self.from_product_version_id,
            to_product_version_id=self.to_product_version_id,
            expected_state_version=self.from_state_version,
            actor_subject=self.actor_subject,
            reason=self.reason,
            idempotency_key=self.idempotency_key,
            occurred_at=self.occurred_at,
        )
        if len(
            {
                self.source_binding_count,
                self.impact_count,
                self.acknowledged_count,
                self.target_binding_count,
            }
        ) != 1:
            raise ValueError("cutover evidence counts must describe the same set")
        if self.to_state_version != self.from_state_version + 1:
            raise ValueError("cutover state version must advance exactly once")
        if self.cutover_sha256 != gis_service_migration_cutover_fingerprint(self):
            raise ValueError("cutover_sha256 does not match the cutover evidence")
        return self


def gis_service_migration_cutover_fingerprint(
    value: GISServiceMigrationCutover | dict[str, Any],
) -> str:
    """Fingerprint every immutable cutover field except its own checksum."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="python", exclude={"cutover_sha256"})
    else:
        payload = {
            key: item for key, item in value.items() if key != "cutover_sha256"
        }
    payload = _canonical(payload)
    payload["schema"] = GIS_SERVICE_MIGRATION_CUTOVER_SCHEMA
    return canonical_json_fingerprint(payload)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    return value


__all__ = [
    "GIS_SERVICE_MIGRATION_CUTOVER_SCHEMA",
    "GISServiceMigrationCutover",
    "GISServiceMigrationCutoverRequest",
    "gis_service_migration_cutover_fingerprint",
]
