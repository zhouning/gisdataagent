"""Authority-bound rollback of an atomic GIS service migration cutover."""

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
_APPROVAL_CASE_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/"
    r"[a-z0-9][a-z0-9._-]{0,127}$"
)

GIS_SERVICE_MIGRATION_ROLLBACK_SCHEMA = "gda.gis_service_migration_rollback.v1"
GIS_SERVICE_MIGRATION_ROLLBACK_APPROVAL_SCHEMA = (
    "gda.gis_service_migration.rollback.v1"
)


class GISServiceMigrationRollbackRequest(BaseModel):
    """CAS request bound to one immutable migration cutover and authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    rollback_id: UUID
    cutover_id: UUID
    cutover_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_urn: str
    from_endpoint_revision_id: UUID
    to_endpoint_revision_id: UUID
    expected_state_version: int = Field(ge=0)
    authorization_kind: Literal["incident", "approval_case"]
    authorization_ref: str = Field(min_length=1, max_length=512)
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
            raise ValueError("rollback reason and idempotency key are required")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_request(self) -> GISServiceMigrationRollbackRequest:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if self.from_endpoint_revision_id == self.to_endpoint_revision_id:
            raise ValueError("rollback endpoints must differ")
        if self.authorization_kind == "incident":
            try:
                UUID(self.authorization_ref)
            except ValueError as exc:
                raise ValueError("incident authorization_ref must be a UUID") from exc
        elif (
            _APPROVAL_CASE_RE.fullmatch(self.authorization_ref) is None
            or self.authorization_ref.split("/")[2] != self.tenant_id
        ):
            raise ValueError(
                "approval_case authorization_ref must identify a tenant ApprovalCase"
            )
        return self


class GISServiceMigrationRollback(BaseModel):
    """Immutable authority, consumer-set and pointer evidence for one rollback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    rollback_id: UUID
    cutover_id: UUID
    cutover_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_urn: str
    from_endpoint_revision_id: UUID
    to_endpoint_revision_id: UUID
    from_service_definition_version_id: UUID
    from_service_release_binding_id: UUID
    to_service_definition_version_id: UUID
    to_service_release_binding_id: UUID
    source_product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    current_binding_count: int = Field(ge=0)
    current_consumer_count: int = Field(ge=0)
    rollback_binding_count: int = Field(ge=0)
    rollback_consumer_count: int = Field(ge=0)
    rollback_binding_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    from_state_version: int = Field(ge=0)
    to_state_version: int = Field(gt=0)
    activation_event_id: UUID
    cache_transition_mode: Literal["release_namespace_rollover"]
    authorization_kind: Literal["incident", "approval_case"]
    authorization_ref: str = Field(min_length=1, max_length=512)
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_status: Literal["open", "acknowledged", "approved"]
    authorization_state_version: int = Field(ge=0)
    actor_subject: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=512)
    occurred_at: datetime
    rollback_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def _aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_rollback(self) -> GISServiceMigrationRollback:
        GISServiceMigrationRollbackRequest(
            tenant_id=self.tenant_id,
            rollback_id=self.rollback_id,
            cutover_id=self.cutover_id,
            cutover_sha256=self.cutover_sha256,
            service_urn=self.service_urn,
            from_endpoint_revision_id=self.from_endpoint_revision_id,
            to_endpoint_revision_id=self.to_endpoint_revision_id,
            expected_state_version=self.from_state_version,
            authorization_kind=self.authorization_kind,
            authorization_ref=self.authorization_ref,
            actor_subject=self.actor_subject,
            reason=self.reason,
            idempotency_key=self.idempotency_key,
            occurred_at=self.occurred_at,
        )
        if self.from_product_version_id == self.to_product_version_id:
            raise ValueError("rollback product versions must differ")
        if self.current_binding_count != self.current_consumer_count:
            raise ValueError("current release consumer bindings are ambiguous")
        if self.rollback_binding_count != self.rollback_consumer_count:
            raise ValueError("rollback release consumer bindings are ambiguous")
        if self.current_consumer_count != self.rollback_consumer_count:
            raise ValueError("rollback evidence counts must describe the same set")
        if self.to_state_version != self.from_state_version + 1:
            raise ValueError("rollback state version must advance exactly once")
        if self.authorization_kind == "approval_case":
            if self.authorization_status != "approved":
                raise ValueError("ApprovalCase rollback authority must be approved")
        elif self.authorization_status not in {"open", "acknowledged"}:
            raise ValueError("Incident rollback authority must remain active")
        if self.rollback_sha256 != gis_service_migration_rollback_fingerprint(self):
            raise ValueError("rollback_sha256 does not match the rollback evidence")
        return self


def gis_service_migration_rollback_approval_context(
    value: GISServiceMigrationRollbackRequest | dict[str, Any],
) -> dict[str, Any]:
    """Build the exact ApprovalCase request context for a rollback request."""
    payload = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return _canonical(
        {
            "schema": GIS_SERVICE_MIGRATION_ROLLBACK_APPROVAL_SCHEMA,
            "tenant_id": payload["tenant_id"],
            "service_urn": payload["service_urn"],
            "cutover_id": payload["cutover_id"],
            "cutover_sha256": payload["cutover_sha256"],
            "from_endpoint_revision_id": payload["from_endpoint_revision_id"],
            "to_endpoint_revision_id": payload["to_endpoint_revision_id"],
            "from_state_version": payload.get(
                "expected_state_version", payload.get("from_state_version")
            ),
        }
    )


def gis_service_migration_rollback_operation_fingerprint(
    value: GISServiceMigrationRollbackRequest | dict[str, Any],
) -> str:
    """Fingerprint the exact operation an ApprovalCase is allowed to execute."""
    return canonical_json_fingerprint(
        gis_service_migration_rollback_approval_context(value)
    )


def gis_service_migration_rollback_fingerprint(
    value: GISServiceMigrationRollback | dict[str, Any],
) -> str:
    """Fingerprint every immutable rollback field except its own checksum."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="python", exclude={"rollback_sha256"})
    else:
        payload = {
            key: item for key, item in value.items() if key != "rollback_sha256"
        }
    payload = _canonical(payload)
    payload["schema"] = GIS_SERVICE_MIGRATION_ROLLBACK_SCHEMA
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
    "GIS_SERVICE_MIGRATION_ROLLBACK_APPROVAL_SCHEMA",
    "GIS_SERVICE_MIGRATION_ROLLBACK_SCHEMA",
    "GISServiceMigrationRollback",
    "GISServiceMigrationRollbackRequest",
    "gis_service_migration_rollback_approval_context",
    "gis_service_migration_rollback_fingerprint",
    "gis_service_migration_rollback_operation_fingerprint",
]
