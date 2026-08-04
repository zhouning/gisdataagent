"""Typed contracts for ResourceVersion data-architecture authority bindings.

The control ledger stores stable external references and canonical fingerprints,
not copies of provider schema or contract documents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
)

DATA_ARCHITECTURE_SCHEMA = "gda.data_architecture.v1"
DATA_ARCHITECTURE_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "113_data_architecture_version_authority.sql"
)
DATA_ARCHITECTURE_OBSERVATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "114_data_architecture_provider_observation.sql"
)
DATA_ARCHITECTURE_ADOPTION_LOCK_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "115_architecture_successor_adoption_lock.sql"
)

ExternalReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
ProviderLocator = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
]


class SchemaAuthoritySystem(StrEnum):
    GRAVITINO = "gravitino"
    PROVIDER = "provider"


class ContractAuthoritySystem(StrEnum):
    OPENMETADATA = "openmetadata"
    PROVIDER = "provider"


class ContractEnforcementMode(StrEnum):
    ADVISORY = "advisory"
    REQUIRED = "required"


class ProviderObjectState(StrEnum):
    PRESENT = "present"
    TOMBSTONED = "tombstoned"


class ArchitectureReconciliationStatus(StrEnum):
    UNOBSERVED = "unobserved"
    UNBOUND = "unbound"
    IN_SYNC = "in_sync"
    STALE = "stale"
    SCHEMA_DRIFT = "schema_drift"
    LOCATION_DRIFT = "location_drift"
    SCHEMA_AND_LOCATION_DRIFT = "schema_and_location_drift"
    TOMBSTONED = "tombstoned"


ArchitectureMissingComponent = Literal[
    "schema_version",
    "data_contract_version",
    "physical_location",
    "architecture_binding",
]
ArchitectureReconciliationAction = Literal[
    "harvest_provider",
    "register_architecture",
    "refresh_observation",
    "review_schema_drift",
    "review_location_drift",
    "investigate_tombstone",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("architecture ledger timestamps require a timezone")
    return value.astimezone(UTC)


def schema_version_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    schema_format: str,
    authority_system: SchemaAuthoritySystem | str,
    authority_namespace: str,
    authority_object_id: str,
    authority_version_ref: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DATA_ARCHITECTURE_SCHEMA,
            "object": "schema_version",
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "schema_format": schema_format,
            "authority_system": SchemaAuthoritySystem(authority_system).value,
            "authority_namespace": authority_namespace,
            "authority_object_id": authority_object_id,
            "authority_version_ref": authority_version_ref,
        }
    )


def data_contract_version_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    contract_kind: str,
    enforcement_mode: ContractEnforcementMode | str,
    authority_system: ContractAuthoritySystem | str,
    authority_namespace: str,
    authority_object_id: str,
    authority_version_ref: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DATA_ARCHITECTURE_SCHEMA,
            "object": "data_contract_version",
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "contract_kind": contract_kind,
            "enforcement_mode": ContractEnforcementMode(enforcement_mode).value,
            "authority_system": ContractAuthoritySystem(authority_system).value,
            "authority_namespace": authority_namespace,
            "authority_object_id": authority_object_id,
            "authority_version_ref": authority_version_ref,
        }
    )


def physical_location_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    location_kind: str,
    provider_system: str,
    provider_namespace: str,
    provider_locator: str,
    snapshot_ref: str | None,
    revision_ref: str | None,
    checksum_algorithm: str,
    content_checksum: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DATA_ARCHITECTURE_SCHEMA,
            "object": "physical_location",
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "location_kind": location_kind,
            "provider_system": provider_system,
            "provider_namespace": provider_namespace,
            "provider_locator": provider_locator,
            "snapshot_ref": snapshot_ref,
            "revision_ref": revision_ref,
            "checksum_algorithm": checksum_algorithm,
            "content_checksum": content_checksum,
        }
    )


def architecture_binding_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    schema_version_id: UUID,
    data_contract_version_id: UUID,
    physical_location_id: UUID,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DATA_ARCHITECTURE_SCHEMA,
            "object": "resource_version_architecture_binding",
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "schema_version_id": str(schema_version_id),
            "data_contract_version_id": str(data_contract_version_id),
            "physical_location_id": str(physical_location_id),
        }
    )


def architecture_provider_observation_fingerprint(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    provider_system: str,
    provider_namespace: str,
    provider_object_id: str,
    object_state: ProviderObjectState | str,
    source_revision: str | None,
    schema_content_sha256: str | None,
    schema_version_sha256: str | None,
    physical_location_sha256: str | None,
    observed_at: datetime,
    fresh_until: datetime,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DATA_ARCHITECTURE_SCHEMA,
            "object": "architecture_provider_observation",
            "tenant_id": tenant_id,
            "resource_version_id": str(resource_version_id),
            "provider_system": provider_system,
            "provider_namespace": provider_namespace,
            "provider_object_id": provider_object_id,
            "object_state": ProviderObjectState(object_state).value,
            "source_revision": source_revision,
            "schema_content_sha256": schema_content_sha256,
            "schema_version_sha256": schema_version_sha256,
            "physical_location_sha256": physical_location_sha256,
            "observed_at": _utc(observed_at).isoformat(),
            "fresh_until": _utc(fresh_until).isoformat(),
        }
    )


class SchemaVersion(_FrozenModel):
    """One immutable technical-schema reference for a ResourceVersion."""

    tenant_id: TenantId
    schema_version_id: UUID
    resource_version_id: UUID
    schema_format: ShortName
    authority_system: SchemaAuthoritySystem
    authority_namespace: ExternalReference
    authority_object_id: ExternalReference
    authority_version_ref: ExternalReference
    schema_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    _utc_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _valid_fingerprint(self) -> SchemaVersion:
        expected = schema_version_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            schema_format=self.schema_format,
            authority_system=self.authority_system,
            authority_namespace=self.authority_namespace,
            authority_object_id=self.authority_object_id,
            authority_version_ref=self.authority_version_ref,
        )
        if self.schema_sha256 != expected:
            raise ValueError("schema_sha256 does not match SchemaVersion")
        return self


class DataContractVersion(_FrozenModel):
    """One immutable governance-contract reference for a ResourceVersion."""

    tenant_id: TenantId
    data_contract_version_id: UUID
    resource_version_id: UUID
    contract_kind: ShortName
    enforcement_mode: ContractEnforcementMode
    authority_system: ContractAuthoritySystem
    authority_namespace: ExternalReference
    authority_object_id: ExternalReference
    authority_version_ref: ExternalReference
    contract_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    _utc_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _valid_fingerprint(self) -> DataContractVersion:
        expected = data_contract_version_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            contract_kind=self.contract_kind,
            enforcement_mode=self.enforcement_mode,
            authority_system=self.authority_system,
            authority_namespace=self.authority_namespace,
            authority_object_id=self.authority_object_id,
            authority_version_ref=self.authority_version_ref,
        )
        if self.contract_sha256 != expected:
            raise ValueError("contract_sha256 does not match DataContractVersion")
        return self


class PhysicalLocation(_FrozenModel):
    """One immutable provider snapshot/revision reference for a ResourceVersion."""

    tenant_id: TenantId
    physical_location_id: UUID
    resource_version_id: UUID
    location_kind: ShortName
    provider_system: ShortName
    provider_namespace: ExternalReference
    provider_locator: ProviderLocator
    snapshot_ref: ExternalReference | None = None
    revision_ref: ExternalReference | None = None
    checksum_algorithm: ShortName
    content_checksum: ExternalReference
    location_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    _utc_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _valid_location(self) -> PhysicalLocation:
        if self.snapshot_ref is None and self.revision_ref is None:
            raise ValueError("PhysicalLocation requires snapshot_ref or revision_ref")
        expected = physical_location_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            location_kind=self.location_kind,
            provider_system=self.provider_system,
            provider_namespace=self.provider_namespace,
            provider_locator=self.provider_locator,
            snapshot_ref=self.snapshot_ref,
            revision_ref=self.revision_ref,
            checksum_algorithm=self.checksum_algorithm,
            content_checksum=self.content_checksum,
        )
        if self.location_sha256 != expected:
            raise ValueError("location_sha256 does not match PhysicalLocation")
        return self


class ResourceVersionArchitectureBinding(_FrozenModel):
    """Complete, immutable architecture binding for one ResourceVersion."""

    tenant_id: TenantId
    resource_version_id: UUID
    schema_version_id: UUID
    data_contract_version_id: UUID
    physical_location_id: UUID
    binding_sha256: Sha256
    bound_by: NonEmptyText
    bound_at: datetime

    _utc_bound_at = field_validator("bound_at")(_utc)

    @model_validator(mode="after")
    def _valid_fingerprint(self) -> ResourceVersionArchitectureBinding:
        expected = architecture_binding_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            schema_version_id=self.schema_version_id,
            data_contract_version_id=self.data_contract_version_id,
            physical_location_id=self.physical_location_id,
        )
        if self.binding_sha256 != expected:
            raise ValueError("binding_sha256 does not match architecture binding")
        return self


class DataArchitectureRegistration(_FrozenModel):
    """Atomic registration of all architecture facts for one ResourceVersion."""

    schema_version: SchemaVersion
    data_contract_version: DataContractVersion
    physical_location: PhysicalLocation
    binding: ResourceVersionArchitectureBinding

    @model_validator(mode="after")
    def _consistent_registration(self) -> DataArchitectureRegistration:
        tenant_ids = {
            self.schema_version.tenant_id,
            self.data_contract_version.tenant_id,
            self.physical_location.tenant_id,
            self.binding.tenant_id,
        }
        resource_version_ids = {
            self.schema_version.resource_version_id,
            self.data_contract_version.resource_version_id,
            self.physical_location.resource_version_id,
            self.binding.resource_version_id,
        }
        if len(tenant_ids) != 1 or len(resource_version_ids) != 1:
            raise ValueError("architecture registration must bind one tenant ResourceVersion")
        if self.binding.schema_version_id != self.schema_version.schema_version_id:
            raise ValueError("architecture binding references a different SchemaVersion")
        if (
            self.binding.data_contract_version_id
            != self.data_contract_version.data_contract_version_id
        ):
            raise ValueError("architecture binding references a different DataContractVersion")
        if (
            self.binding.physical_location_id
            != self.physical_location.physical_location_id
        ):
            raise ValueError("architecture binding references a different PhysicalLocation")
        return self


class ResourceVersionArchitecture(_FrozenModel):
    """Tenant-scoped readiness projection; only a complete binding is ready."""

    schema_version: Literal[DATA_ARCHITECTURE_SCHEMA] = DATA_ARCHITECTURE_SCHEMA
    tenant_id: TenantId
    resource_version_id: UUID
    architecture_ready: bool
    missing_components: tuple[ArchitectureMissingComponent, ...]
    schema_version_record: SchemaVersion | None = None
    data_contract_version_record: DataContractVersion | None = None
    physical_location: PhysicalLocation | None = None
    binding: ResourceVersionArchitectureBinding | None = None

    @model_validator(mode="after")
    def _consistent_readiness(self) -> ResourceVersionArchitecture:
        components = (
            self.schema_version_record,
            self.data_contract_version_record,
            self.physical_location,
        )
        if self.architecture_ready:
            if self.binding is None or any(value is None for value in components):
                raise ValueError("architecture_ready requires a complete binding")
            if self.missing_components:
                raise ValueError("ready architecture cannot report missing components")
        elif not self.missing_components:
            raise ValueError("incomplete architecture must report missing components")
        if self.binding is not None:
            if any(value is None for value in components):
                raise ValueError("architecture binding cannot reference missing components")
            assert self.schema_version_record is not None
            assert self.data_contract_version_record is not None
            assert self.physical_location is not None
            if {
                self.binding.tenant_id,
                self.schema_version_record.tenant_id,
                self.data_contract_version_record.tenant_id,
                self.physical_location.tenant_id,
            } != {self.tenant_id}:
                raise ValueError("architecture records must match projection tenant")
            if {
                self.binding.resource_version_id,
                self.schema_version_record.resource_version_id,
                self.data_contract_version_record.resource_version_id,
                self.physical_location.resource_version_id,
            } != {self.resource_version_id}:
                raise ValueError("architecture records must match projection ResourceVersion")
            if (
                self.binding.schema_version_id
                != self.schema_version_record.schema_version_id
                or self.binding.data_contract_version_id
                != self.data_contract_version_record.data_contract_version_id
                or self.binding.physical_location_id
                != self.physical_location.physical_location_id
            ):
                raise ValueError("architecture binding component identities do not match")
        return self


class ArchitectureProviderObservation(_FrozenModel):
    """One successful, bounded observation of a provider object."""

    tenant_id: TenantId
    observation_id: UUID
    resource_version_id: UUID
    provider_system: ShortName
    provider_namespace: ExternalReference
    provider_object_id: ExternalReference
    object_state: ProviderObjectState
    source_revision: ExternalReference | None = None
    schema_content_sha256: Sha256 | None = None
    schema_version_sha256: Sha256 | None = None
    physical_location_sha256: Sha256 | None = None
    observed_at: datetime
    fresh_until: datetime
    observation_sha256: Sha256
    observed_by: NonEmptyText
    recorded_at: datetime

    @field_validator("observed_at", "fresh_until", "recorded_at")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_observation(self) -> ArchitectureProviderObservation:
        freshness_seconds = (self.fresh_until - self.observed_at).total_seconds()
        if freshness_seconds < 5 or freshness_seconds > 86400:
            raise ValueError("provider observation freshness must be 5..86400 seconds")
        if self.recorded_at < self.observed_at:
            raise ValueError("recorded_at cannot be earlier than observed_at")
        bounded = (
            self.source_revision,
            self.schema_content_sha256,
            self.schema_version_sha256,
            self.physical_location_sha256,
        )
        if self.object_state == ProviderObjectState.PRESENT:
            if any(value is None for value in bounded):
                raise ValueError("present observation requires revision and fingerprints")
        elif any(value is not None for value in bounded):
            raise ValueError("tombstone observation cannot carry current fingerprints")
        expected = architecture_provider_observation_fingerprint(
            tenant_id=self.tenant_id,
            resource_version_id=self.resource_version_id,
            provider_system=self.provider_system,
            provider_namespace=self.provider_namespace,
            provider_object_id=self.provider_object_id,
            object_state=self.object_state,
            source_revision=self.source_revision,
            schema_content_sha256=self.schema_content_sha256,
            schema_version_sha256=self.schema_version_sha256,
            physical_location_sha256=self.physical_location_sha256,
            observed_at=self.observed_at,
            fresh_until=self.fresh_until,
        )
        if self.observation_sha256 != expected:
            raise ValueError("observation_sha256 does not match provider observation")
        return self


class ResourceVersionArchitectureReconciliation(_FrozenModel):
    """Fail-closed comparison of one binding with its latest provider fact."""

    schema_version: Literal[DATA_ARCHITECTURE_SCHEMA] = DATA_ARCHITECTURE_SCHEMA
    tenant_id: TenantId
    resource_version_id: UUID
    status: ArchitectureReconciliationStatus
    architecture: ResourceVersionArchitecture
    latest_observation: ArchitectureProviderObservation | None = None
    schema_matches: bool | None = None
    location_matches: bool | None = None
    evaluated_at: datetime
    required_actions: tuple[ArchitectureReconciliationAction, ...]

    _utc_evaluated_at = field_validator("evaluated_at")(_utc)

    @model_validator(mode="after")
    def _consistent_reconciliation(self) -> ResourceVersionArchitectureReconciliation:
        if self.architecture.tenant_id != self.tenant_id:
            raise ValueError("architecture reconciliation tenant must match")
        if self.architecture.resource_version_id != self.resource_version_id:
            raise ValueError("architecture reconciliation ResourceVersion must match")
        if self.latest_observation is not None:
            if self.latest_observation.tenant_id != self.tenant_id:
                raise ValueError("provider observation tenant must match")
            if self.latest_observation.resource_version_id != self.resource_version_id:
                raise ValueError("provider observation ResourceVersion must match")
        if self.status == ArchitectureReconciliationStatus.IN_SYNC:
            if self.schema_matches is not True or self.location_matches is not True:
                raise ValueError("in_sync requires matching schema and location")
            if self.required_actions:
                raise ValueError("in_sync cannot require reconciliation actions")
        elif not self.required_actions:
            raise ValueError("non-synchronized architecture requires an action")
        return self
