"""Authority-safe crosswalk and delivery contracts for the Metadata Fabric."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .data_architecture_ledger import (
    ArchitectureProviderObservation,
    ProviderObjectState,
    architecture_provider_observation_fingerprint,
)
from .master_data_authority import MasterEntityVersion
from .platform_contracts import (
    LineageEvent,
    NonEmptyText,
    ResourceURNText,
    ResourceVersion,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

METADATA_FABRIC_SCHEMA = "gda.metadata_fabric.v1"
METADATA_FABRIC_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "112_metadata_fabric_binding_outbox.sql"
)

ExternalReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]

_GRAVITINO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
GRAVITINO_REFERENCE_SCHEMA = "gda.gravitino_technical_object_reference.v1"


class MetadataFabricSystem(StrEnum):
    OPENMETADATA = "openmetadata"
    GRAVITINO = "gravitino"


class MetadataBindingKind(StrEnum):
    GOVERNANCE_ENTITY = "governance_entity"
    TECHNICAL_OBJECT = "technical_object"


class MetadataChangeType(StrEnum):
    LINEAGE_UPSERT = "lineage_upsert"


class MetadataChangeStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def metadata_fabric_binding_fingerprint(
    *,
    tenant_id: str,
    resource_urn: str,
    system: MetadataFabricSystem | str,
    binding_kind: MetadataBindingKind | str,
    external_namespace: str,
    external_object_id: str,
    external_object_type: str,
    external_version_ref: str | None,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": METADATA_FABRIC_SCHEMA,
            "tenant_id": tenant_id,
            "resource_urn": resource_urn,
            "system": MetadataFabricSystem(system).value,
            "binding_kind": MetadataBindingKind(binding_kind).value,
            "external_namespace": external_namespace,
            "external_object_id": external_object_id,
            "external_object_type": external_object_type,
            "external_version_ref": external_version_ref,
        }
    )


class MetadataFabricBinding(_FrozenModel):
    """Stable ResourceURN crosswalk; external systems retain metadata authority."""

    tenant_id: TenantId
    binding_id: UUID
    resource_urn: ResourceURNText
    system: MetadataFabricSystem
    binding_kind: MetadataBindingKind
    external_namespace: ExternalReference
    external_object_id: ExternalReference
    external_object_type: ExternalReference
    external_version_ref: ExternalReference | None = None
    binding_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_binding(self) -> MetadataFabricBinding:
        if parse_resource_urn(self.resource_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("resource_urn tenant must match tenant_id")
        expected_kind = {
            MetadataFabricSystem.OPENMETADATA: MetadataBindingKind.GOVERNANCE_ENTITY,
            MetadataFabricSystem.GRAVITINO: MetadataBindingKind.TECHNICAL_OBJECT,
        }[self.system]
        if self.binding_kind != expected_kind:
            raise ValueError("binding_kind does not match Metadata Fabric system authority")
        if self.system == MetadataFabricSystem.OPENMETADATA:
            try:
                external_object_id = UUID(self.external_object_id)
            except ValueError as exc:
                raise ValueError(
                    "OpenMetadata external_object_id must be a UUID"
                ) from exc
            if str(external_object_id) != self.external_object_id:
                raise ValueError(
                    "OpenMetadata external_object_id must use canonical UUID text"
                )
        expected_sha256 = metadata_fabric_binding_fingerprint(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            system=self.system,
            binding_kind=self.binding_kind,
            external_namespace=self.external_namespace,
            external_object_id=self.external_object_id,
            external_object_type=self.external_object_type,
            external_version_ref=self.external_version_ref,
        )
        if self.binding_sha256 != expected_sha256:
            raise ValueError("binding_sha256 does not match Metadata Fabric binding")
        return self


def gravitino_reference_fingerprint(
    *,
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    metalake: str,
    catalog: str,
    namespace: str,
    object_name: str,
    object_type: str,
    object_version_ref: str,
) -> str:
    """Fingerprint one immutable GDA-to-Gravitino technical object mapping."""
    return canonical_json_fingerprint(
        {
            "schema": GRAVITINO_REFERENCE_SCHEMA,
            "tenant_id": tenant_id,
            "resource_urn": resource_urn,
            "resource_version_id": str(resource_version_id),
            "metalake": metalake,
            "catalog": catalog,
            "namespace": namespace,
            "object_name": object_name,
            "object_type": object_type,
            "object_version_ref": object_version_ref,
        }
    )


class GravitinoTechnicalObjectReference(_FrozenModel):
    """Canonical technical-object identity used by the Gravitino bridge.

    This is deliberately a reference contract, not a second catalog. The
    technical provider remains authoritative for object state and version;
    GDA stores only this immutable crosswalk and its evidence fingerprint.
    """

    schema_version: Literal[GRAVITINO_REFERENCE_SCHEMA] = GRAVITINO_REFERENCE_SCHEMA
    tenant_id: TenantId
    resource_urn: ResourceURNText
    resource_version_id: UUID
    metalake: str = Field(min_length=1, max_length=128)
    catalog: str = Field(min_length=1, max_length=128)
    namespace: str = Field(min_length=1, max_length=128)
    object_name: str = Field(min_length=1, max_length=128)
    object_type: Literal["table", "view", "fileset", "topic"]
    object_version_ref: ExternalReference
    reference_sha256: Sha256

    @field_validator("metalake", "catalog", "namespace", "object_name")
    @classmethod
    def _safe_gravitino_name(cls, value: str) -> str:
        if _GRAVITINO_NAME.fullmatch(value) is None:
            raise ValueError("Gravitino identifiers must be canonical names")
        return value

    @model_validator(mode="after")
    def _consistent_reference(self) -> GravitinoTechnicalObjectReference:
        if parse_resource_urn(self.resource_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("resource_urn tenant must match tenant_id")
        expected = gravitino_reference_fingerprint(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            metalake=self.metalake,
            catalog=self.catalog,
            namespace=self.namespace,
            object_name=self.object_name,
            object_type=self.object_type,
            object_version_ref=self.object_version_ref,
        )
        if self.reference_sha256 != expected:
            raise ValueError("reference_sha256 does not match the technical mapping")
        return self

    @property
    def external_namespace(self) -> str:
        return f"{self.metalake}/{self.catalog}/{self.namespace}"

    @property
    def external_object_id(self) -> str:
        return self.object_name

    def to_metadata_binding(
        self,
        *,
        binding_id: UUID,
        created_by: str,
        created_at: datetime,
    ) -> MetadataFabricBinding:
        """Materialize the compatibility binding consumed by the control ledger."""
        return MetadataFabricBinding(
            tenant_id=self.tenant_id,
            binding_id=binding_id,
            resource_urn=self.resource_urn,
            system=MetadataFabricSystem.GRAVITINO,
            binding_kind=MetadataBindingKind.TECHNICAL_OBJECT,
            external_namespace=self.external_namespace,
            external_object_id=self.external_object_id,
            external_object_type=self.object_type,
            external_version_ref=self.object_version_ref,
            binding_sha256=metadata_fabric_binding_fingerprint(
                tenant_id=self.tenant_id,
                resource_urn=self.resource_urn,
                system=MetadataFabricSystem.GRAVITINO,
                binding_kind=MetadataBindingKind.TECHNICAL_OBJECT,
                external_namespace=self.external_namespace,
                external_object_id=self.external_object_id,
                external_object_type=self.object_type,
                external_version_ref=self.object_version_ref,
            ),
            created_by=created_by,
            created_at=created_at,
        )


def build_gravitino_reference(
    resource_version: ResourceVersion,
    *,
    metalake: str,
    catalog: str,
    namespace: str,
    object_name: str,
    object_type: Literal["table", "view", "fileset", "topic"],
    object_version_ref: str,
) -> GravitinoTechnicalObjectReference:
    """Build the canonical reference from an already admitted ResourceVersion."""
    fingerprint = gravitino_reference_fingerprint(
        tenant_id=resource_version.tenant_id,
        resource_urn=resource_version.resource_urn,
        resource_version_id=resource_version.resource_version_id,
        metalake=metalake,
        catalog=catalog,
        namespace=namespace,
        object_name=object_name,
        object_type=object_type,
        object_version_ref=object_version_ref,
    )
    return GravitinoTechnicalObjectReference(
        tenant_id=resource_version.tenant_id,
        resource_urn=resource_version.resource_urn,
        resource_version_id=resource_version.resource_version_id,
        metalake=metalake,
        catalog=catalog,
        namespace=namespace,
        object_name=object_name,
        object_type=object_type,
        object_version_ref=object_version_ref,
        reference_sha256=fingerprint,
    )


def gravitino_reference_from_binding(
    binding: MetadataFabricBinding,
    *,
    resource_version: ResourceVersion,
) -> GravitinoTechnicalObjectReference:
    """Reconstruct and validate the canonical reference from a compatibility binding."""
    if binding.system != MetadataFabricSystem.GRAVITINO:
        raise ValueError("Gravitino reference requires a Gravitino binding")
    if (
        binding.tenant_id != resource_version.tenant_id
        or binding.resource_urn != resource_version.resource_urn
    ):
        raise ValueError("Gravitino binding must match the ResourceVersion identity")
    parts = binding.external_namespace.split("/")
    if len(parts) != 3:
        raise ValueError("Gravitino external namespace must be metalake/catalog/namespace")
    metalake, catalog, namespace = parts
    provisional = GravitinoTechnicalObjectReference.model_construct(
        tenant_id=binding.tenant_id,
        resource_urn=binding.resource_urn,
        resource_version_id=resource_version.resource_version_id,
        metalake=metalake,
        catalog=catalog,
        namespace=namespace,
        object_name=binding.external_object_id,
        object_type=binding.external_object_type,
        object_version_ref=binding.external_version_ref,
        reference_sha256="0" * 64,
    )
    return GravitinoTechnicalObjectReference(
        **provisional.model_dump(exclude={"reference_sha256"}),
        reference_sha256=gravitino_reference_fingerprint(
            tenant_id=provisional.tenant_id,
            resource_urn=provisional.resource_urn,
            resource_version_id=provisional.resource_version_id,
            metalake=provisional.metalake,
            catalog=provisional.catalog,
            namespace=provisional.namespace,
            object_name=provisional.object_name,
            object_type=provisional.object_type,
            object_version_ref=provisional.object_version_ref,
        ),
    )


def build_gravitino_architecture_observation(
    reference: GravitinoTechnicalObjectReference,
    *,
    source_revision: str | None,
    schema_content_sha256: str | None,
    schema_version_sha256: str | None,
    physical_location_sha256: str | None,
    observed_at: datetime,
    fresh_until: datetime,
    observed_by: str,
    recorded_at: datetime,
    object_state: ProviderObjectState | str = ProviderObjectState.PRESENT,
) -> ArchitectureProviderObservation:
    """Project a Gravitino observation into the shared architecture ledger."""
    state = ProviderObjectState(object_state)
    observation_sha256 = architecture_provider_observation_fingerprint(
        tenant_id=reference.tenant_id,
        resource_version_id=reference.resource_version_id,
        provider_system=MetadataFabricSystem.GRAVITINO.value,
        provider_namespace=reference.external_namespace,
        provider_object_id=reference.external_object_id,
        object_state=state,
        source_revision=source_revision,
        schema_content_sha256=schema_content_sha256,
        schema_version_sha256=schema_version_sha256,
        physical_location_sha256=physical_location_sha256,
        observed_at=observed_at,
        fresh_until=fresh_until,
    )
    return ArchitectureProviderObservation(
        tenant_id=reference.tenant_id,
        observation_id=uuid5(reference.resource_version_id, observation_sha256),
        resource_version_id=reference.resource_version_id,
        provider_system=MetadataFabricSystem.GRAVITINO.value,
        provider_namespace=reference.external_namespace,
        provider_object_id=reference.external_object_id,
        object_state=state,
        source_revision=source_revision,
        schema_content_sha256=schema_content_sha256,
        schema_version_sha256=schema_version_sha256,
        physical_location_sha256=physical_location_sha256,
        observed_at=observed_at,
        fresh_until=fresh_until,
        observation_sha256=observation_sha256,
        observed_by=observed_by,
        recorded_at=recorded_at,
    )


class MetadataChange(_FrozenModel):
    """One leased, at-least-once Metadata Fabric projection change."""

    tenant_id: TenantId
    change_id: UUID
    change_type: Literal[MetadataChangeType.LINEAGE_UPSERT]
    aggregate_id: UUID
    destination_ref: Literal["openmetadata:default"]
    payload_sha256: Sha256
    status: MetadataChangeStatus = MetadataChangeStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=10, ge=1, le=100)
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: NonEmptyText | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Metadata Fabric delivery timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_delivery(self) -> MetadataChange:
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("change claim owner and expiry must be set together")
        if self.status == MetadataChangeStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending change cannot be claimed or completed")
        elif self.status == MetadataChangeStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight change requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("completed change must release its claim")
        return self


class MetadataLineageProjectionEnvelope(_FrozenModel):
    """A claimed lineage change plus currently resolved governance bindings."""

    schema_version: Literal[METADATA_FABRIC_SCHEMA] = METADATA_FABRIC_SCHEMA
    change: MetadataChange
    lineage_event: LineageEvent
    source_resource_version: ResourceVersion
    target_resource_version: ResourceVersion
    source_binding: MetadataFabricBinding | None = None
    target_binding: MetadataFabricBinding | None = None

    @model_validator(mode="after")
    def _consistent_projection(self) -> MetadataLineageProjectionEnvelope:
        tenant_ids = {
            self.change.tenant_id,
            self.lineage_event.tenant_id,
            self.source_resource_version.tenant_id,
            self.target_resource_version.tenant_id,
        }
        if self.source_binding is not None:
            tenant_ids.add(self.source_binding.tenant_id)
        if self.target_binding is not None:
            tenant_ids.add(self.target_binding.tenant_id)
        if len(tenant_ids) != 1:
            raise ValueError("Metadata Fabric projection tenants must match")
        if self.change.aggregate_id != self.lineage_event.lineage_event_id:
            raise ValueError("metadata change must bind the LineageEvent")
        if self.change.payload_sha256 != self.lineage_event.event_sha256:
            raise ValueError("metadata change payload hash must bind the LineageEvent")
        if (
            self.source_resource_version.resource_version_id
            != self.lineage_event.source_resource_version_id
            or self.target_resource_version.resource_version_id
            != self.lineage_event.target_resource_version_id
        ):
            raise ValueError("projection resource versions must bind the lineage edge")
        for binding, version in (
            (self.source_binding, self.source_resource_version),
            (self.target_binding, self.target_resource_version),
        ):
            if binding is None:
                continue
            if binding.system != MetadataFabricSystem.OPENMETADATA:
                raise ValueError("lineage projection requires OpenMetadata bindings")
            if binding.resource_urn != version.resource_urn:
                raise ValueError("OpenMetadata binding must match the resource URN")
        return self


class MasterMetadataProjectionChange(_FrozenModel):
    """One leased delivery of an activated master version to metadata fabric."""

    tenant_id: TenantId
    projection_change_id: UUID
    entity_ref: ResourceURNText
    activation_version: int = Field(ge=1)
    resource_version_id: UUID
    entity_fingerprint: Sha256
    destination_ref: Literal["openmetadata:default"]
    payload_sha256: Sha256
    status: MetadataChangeStatus = MetadataChangeStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=10, ge=1, le=100)
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: NonEmptyText | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("master metadata projection timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_delivery(self) -> MasterMetadataProjectionChange:
        identity = parse_resource_urn(self.entity_ref)
        if (
            identity["tenant_id"] != self.tenant_id
            or identity["resource_kind"] != "master_entity"
        ):
            raise ValueError("master metadata projection identity is invalid")
        if self.payload_sha256 != self.entity_fingerprint:
            raise ValueError("master metadata payload must bind the entity fingerprint")
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("projection claim owner and expiry must be set together")
        if self.status == MetadataChangeStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending projection cannot be claimed or completed")
        elif self.status == MetadataChangeStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight projection requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("completed projection must release its claim")
        return self


class MasterMetadataProjectionEnvelope(_FrozenModel):
    """Exact activated master version plus its optional provider crosswalk."""

    schema_version: Literal["gda.master_metadata_projection.v1"] = (
        "gda.master_metadata_projection.v1"
    )
    change: MasterMetadataProjectionChange
    master_version: MasterEntityVersion
    resource_version: ResourceVersion
    openmetadata_binding: MetadataFabricBinding | None = None

    @model_validator(mode="after")
    def _consistent_projection(self) -> MasterMetadataProjectionEnvelope:
        if len(
            {
                self.change.tenant_id,
                self.master_version.tenant_id,
                self.resource_version.tenant_id,
            }
        ) != 1:
            raise ValueError("master metadata projection tenants must match")
        if (
            self.change.entity_ref != self.master_version.entity_ref
            or self.change.entity_fingerprint
            != self.master_version.entity_fingerprint
            or self.change.resource_version_id
            != self.resource_version.resource_version_id
            or self.resource_version.resource_urn != self.change.entity_ref
            or self.resource_version.content_sha256
            != self.change.entity_fingerprint
        ):
            raise ValueError("master metadata projection must bind the exact version")
        authority = self.resource_version.authority_version_ref
        if (
            authority.get("authority_system") != "gda_control.master_data"
            or authority.get("entity_version_ref")
            != self.master_version.entity_version_ref
            or authority.get("entity_fingerprint")
            != self.master_version.entity_fingerprint
        ):
            raise ValueError("master metadata authority evidence is inconsistent")
        binding = self.openmetadata_binding
        if binding is not None and (
            binding.tenant_id != self.change.tenant_id
            or binding.resource_urn != self.change.entity_ref
            or binding.system != MetadataFabricSystem.OPENMETADATA
        ):
            raise ValueError("master metadata projection requires an OpenMetadata binding")
        return self
