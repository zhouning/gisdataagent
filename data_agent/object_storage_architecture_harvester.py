"""Read-only S3-compatible object schema and revision harvester.

The harvester emits bounded architecture facts for JSON/GeoJSON objects. It
does not copy object bytes into the control ledger or turn an incomplete sample
into a schema authority.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .connectors.schema_discovery import json_document_columns
from .data_architecture_ledger import (
    ArchitectureProviderObservation,
    ExternalReference,
    PhysicalLocation,
    ProviderObjectState,
    SchemaVersion,
    architecture_provider_observation_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
)

OBJECT_STORAGE_ARCHITECTURE_HARVEST_SCHEMA = "gda.object_storage_architecture_harvest.v1"
_IDENTITY_NAMESPACE = UUID("e3f34de4-b77a-493c-9b43-8fbd5fa24772")
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchObject", "NotFound"})

ObjectName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=1024,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


class ObjectStorageArchitectureError(RuntimeError):
    """Provider access or response failed; no tombstone is inferred."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectStorageArchitectureTarget(_FrozenModel):
    """Credential-free identity and expected content binding for one object."""

    tenant_id: TenantId
    resource_version_id: UUID
    provider_ref: ShortName
    bucket: ObjectName
    key: ObjectName
    snapshot_ref: ExternalReference
    content_checksum: ExternalReference
    checksum_algorithm: ShortName = "sha256"
    schema_format: Literal["json", "geojson"] = "geojson"
    max_schema_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    max_schema_records: int = Field(default=100_000, ge=1, le=1_000_000)


class ObjectStorageSchemaField(_FrozenModel):
    name: ObjectName
    data_type: ExternalReference
    nullable: bool


def object_storage_schema_fingerprint(
    *,
    provider_namespace: str,
    provider_object_id: str,
    schema_format: str,
    fields: tuple[ObjectStorageSchemaField, ...],
) -> str:
    """Hash schema shape only; object size/count belong to provider revision."""

    return canonical_json_fingerprint(
        {
            "schema": OBJECT_STORAGE_ARCHITECTURE_HARVEST_SCHEMA,
            "provider_namespace": provider_namespace,
            "provider_object_id": provider_object_id,
            "schema_format": schema_format,
            "fields": [field.model_dump(mode="json") for field in fields],
        }
    )


class ObjectStorageSchemaSnapshot(_FrozenModel):
    schema_version: Literal[OBJECT_STORAGE_ARCHITECTURE_HARVEST_SCHEMA] = (
        OBJECT_STORAGE_ARCHITECTURE_HARVEST_SCHEMA
    )
    provider_namespace: ExternalReference
    provider_object_id: ExternalReference
    schema_format: Literal["json", "geojson"]
    fields: tuple[ObjectStorageSchemaField, ...]
    record_count: int = Field(ge=0)
    object_size_bytes: int = Field(ge=0)
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> ObjectStorageSchemaSnapshot:
        names = [field.name for field in self.fields]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("object schema fields must be sorted and unique")
        expected = object_storage_schema_fingerprint(
            provider_namespace=self.provider_namespace,
            provider_object_id=self.provider_object_id,
            schema_format=self.schema_format,
            fields=self.fields,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("snapshot_sha256 does not match object schema evidence")
        return self


class ObjectStorageArchitectureHarvest(_FrozenModel):
    observation: ArchitectureProviderObservation
    schema_snapshot: ObjectStorageSchemaSnapshot | None = None
    schema_candidate: SchemaVersion | None = None
    physical_location_candidate: PhysicalLocation | None = None

    @model_validator(mode="after")
    def _consistent_harvest(self) -> ObjectStorageArchitectureHarvest:
        candidates = (
            self.schema_snapshot,
            self.schema_candidate,
            self.physical_location_candidate,
        )
        if self.observation.object_state == ProviderObjectState.PRESENT:
            if any(value is None for value in candidates):
                raise ValueError("present object harvest requires architecture candidates")
            assert self.schema_snapshot is not None
            assert self.schema_candidate is not None
            assert self.physical_location_candidate is not None
            if self.schema_snapshot.snapshot_sha256 != self.observation.schema_content_sha256:
                raise ValueError("schema snapshot must match provider observation")
            if self.schema_candidate.schema_sha256 != self.observation.schema_version_sha256:
                raise ValueError("schema candidate must match provider observation")
            if (
                self.physical_location_candidate.location_sha256
                != self.observation.physical_location_sha256
            ):
                raise ValueError("location candidate must match provider observation")
        elif any(value is not None for value in candidates):
            raise ValueError("tombstone object harvest cannot create candidates")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("harvest timestamp must include a timezone")
    return value.astimezone(UTC)


def _provider_identity(target: ObjectStorageArchitectureTarget) -> tuple[str, str, str]:
    namespace = f"{target.provider_ref}/{target.bucket}"
    object_id = target.key
    locator = (
        f"s3://{quote(target.bucket, safe='')}/{quote(target.key, safe='/')}"
    )
    return namespace, object_id, locator


def _error_code(error: BaseException) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        error_data = response.get("Error")
        if isinstance(error_data, dict):
            value = error_data.get("Code")
            return str(value) if value is not None else None
    return None


def _head(client: Any, target: ObjectStorageArchitectureTarget) -> dict[str, Any] | None:
    try:
        return dict(client.head_object(Bucket=target.bucket, Key=target.key))
    except Exception as exc:
        if _error_code(exc) in _NOT_FOUND_CODES:
            return None
        raise ObjectStorageArchitectureError("object HEAD failed") from exc


def _read_object_bytes(
    client: Any,
    target: ObjectStorageArchitectureTarget,
    object_size: int,
) -> bytes:
    if object_size > target.max_schema_bytes:
        raise ObjectStorageArchitectureError(
            "object exceeds exact schema harvest byte limit; use a governed manifest"
        )
    try:
        response = client.get_object(Bucket=target.bucket, Key=target.key)
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise ObjectStorageArchitectureError("object GET response has no readable body")
        try:
            payload = body.read(target.max_schema_bytes + 1)
        finally:
            if hasattr(body, "close"):
                body.close()
    except ObjectStorageArchitectureError:
        raise
    except Exception as exc:
        raise ObjectStorageArchitectureError("object GET failed") from exc
    if len(payload) != object_size:
        raise ObjectStorageArchitectureError("object GET length does not match HEAD")
    return payload


def _source_revision(head: dict[str, Any], object_size: int) -> str:
    version_id = str(head.get("VersionId") or "").strip()
    if version_id and version_id != "null":
        return f"s3-version:{version_id}"
    etag = str(head.get("ETag") or "").strip().strip('"')
    if not etag:
        raise ObjectStorageArchitectureError(
            "object HEAD must provide VersionId or ETag for revision binding"
        )
    return f"s3-etag:{etag}:size:{object_size}"


def _observation(
    *,
    target: ObjectStorageArchitectureTarget,
    provider_namespace: str,
    provider_object_id: str,
    object_state: ProviderObjectState,
    observed_at: datetime,
    fresh_until: datetime,
    observed_by: str,
    source_revision: str | None = None,
    schema_content_sha256: str | None = None,
    schema_version_sha256: str | None = None,
    physical_location_sha256: str | None = None,
) -> ArchitectureProviderObservation:
    fingerprint = architecture_provider_observation_fingerprint(
        tenant_id=target.tenant_id,
        resource_version_id=target.resource_version_id,
        provider_system="object_storage",
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        object_state=object_state,
        source_revision=source_revision,
        schema_content_sha256=schema_content_sha256,
        schema_version_sha256=schema_version_sha256,
        physical_location_sha256=physical_location_sha256,
        observed_at=observed_at,
        fresh_until=fresh_until,
    )
    return ArchitectureProviderObservation(
        tenant_id=target.tenant_id,
        observation_id=uuid5(_IDENTITY_NAMESPACE, fingerprint),
        resource_version_id=target.resource_version_id,
        provider_system="object_storage",
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        object_state=object_state,
        source_revision=source_revision,
        schema_content_sha256=schema_content_sha256,
        schema_version_sha256=schema_version_sha256,
        physical_location_sha256=physical_location_sha256,
        observed_at=observed_at,
        fresh_until=fresh_until,
        observation_sha256=fingerprint,
        observed_by=observed_by,
        recorded_at=observed_at,
    )


def harvest_object_storage_architecture(
    client: Any,
    target: ObjectStorageArchitectureTarget,
    *,
    observed_by: NonEmptyText,
    observed_at: datetime | None = None,
    freshness_seconds: int = 300,
) -> ObjectStorageArchitectureHarvest:
    """Read one JSON/GeoJSON object via HEAD + exact bounded GET."""

    if freshness_seconds < 5 or freshness_seconds > 86400:
        raise ValueError("freshness_seconds must be between 5 and 86400")
    observed = _utc(observed_at or datetime.now(UTC))
    fresh_until = observed + timedelta(seconds=freshness_seconds)
    provider_namespace, provider_object_id, locator = _provider_identity(target)
    head = _head(client, target)
    if head is None:
        return ObjectStorageArchitectureHarvest(
            observation=_observation(
                target=target,
                provider_namespace=provider_namespace,
                provider_object_id=provider_object_id,
                object_state=ProviderObjectState.TOMBSTONED,
                observed_at=observed,
                fresh_until=fresh_until,
                observed_by=observed_by,
            )
        )

    try:
        object_size = int(head["ContentLength"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ObjectStorageArchitectureError("object HEAD has invalid ContentLength") from exc
    if object_size < 0:
        raise ObjectStorageArchitectureError("object HEAD has negative ContentLength")
    source_revision = _source_revision(head, object_size)
    payload = _read_object_bytes(client, target, object_size)
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObjectStorageArchitectureError("object is not valid UTF-8 JSON") from exc
    if target.schema_format == "geojson" and not (
        isinstance(document, dict)
        and document.get("type") == "FeatureCollection"
        and isinstance(document.get("features"), list)
    ):
        raise ObjectStorageArchitectureError("object is not a GeoJSON FeatureCollection")
    columns, record_count, schema_truncated = json_document_columns(
        document,
        record_limit=target.max_schema_records,
    )
    if schema_truncated:
        raise ObjectStorageArchitectureError(
            "object schema exceeds exact record limit; use a governed manifest"
        )
    fields = tuple(
        ObjectStorageSchemaField(
            name=column["name"],
            data_type=column["type"],
            nullable=bool(column["nullable"]),
        )
        for column in columns
    )
    schema_content_sha256 = object_storage_schema_fingerprint(
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        schema_format=target.schema_format,
        fields=fields,
    )
    schema_snapshot = ObjectStorageSchemaSnapshot(
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        schema_format=target.schema_format,
        fields=fields,
        record_count=record_count,
        object_size_bytes=object_size,
        snapshot_sha256=schema_content_sha256,
    )
    schema_values = {
        "tenant_id": target.tenant_id,
        "resource_version_id": target.resource_version_id,
        "schema_format": target.schema_format,
        "authority_system": "provider",
        "authority_namespace": provider_namespace,
        "authority_object_id": provider_object_id,
        "authority_version_ref": f"schema-sha256:{schema_content_sha256}",
    }
    schema_sha256 = schema_version_fingerprint(**schema_values)
    schema_candidate = SchemaVersion(
        schema_version_id=uuid5(
            _IDENTITY_NAMESPACE,
            f"schema-version:{target.tenant_id}:{target.resource_version_id}:{schema_sha256}",
        ),
        schema_sha256=schema_sha256,
        created_by=observed_by,
        created_at=observed,
        **schema_values,
    )
    location_values = {
        "tenant_id": target.tenant_id,
        "resource_version_id": target.resource_version_id,
        "location_kind": "object",
        "provider_system": "object_storage",
        "provider_namespace": provider_namespace,
        "provider_locator": locator,
        "snapshot_ref": target.snapshot_ref,
        "revision_ref": source_revision,
        "checksum_algorithm": target.checksum_algorithm,
        "content_checksum": target.content_checksum,
    }
    location_sha256 = physical_location_fingerprint(**location_values)
    location_candidate = PhysicalLocation(
        physical_location_id=uuid5(
            _IDENTITY_NAMESPACE,
            f"physical-location:{target.tenant_id}:{target.resource_version_id}:{location_sha256}",
        ),
        location_sha256=location_sha256,
        created_by=observed_by,
        created_at=observed,
        **location_values,
    )
    return ObjectStorageArchitectureHarvest(
        observation=_observation(
            target=target,
            provider_namespace=provider_namespace,
            provider_object_id=provider_object_id,
            object_state=ProviderObjectState.PRESENT,
            source_revision=source_revision,
            schema_content_sha256=schema_content_sha256,
            schema_version_sha256=schema_sha256,
            physical_location_sha256=location_sha256,
            observed_at=observed,
            fresh_until=fresh_until,
            observed_by=observed_by,
        ),
        schema_snapshot=schema_snapshot,
        schema_candidate=schema_candidate,
        physical_location_candidate=location_candidate,
    )
