"""Read-only Iceberg table architecture observation from a Gravitino table payload.

The Gravitino table response is treated as an external provider observation. Only
the bounded table identity, Iceberg snapshot, schema columns and location are
projected; the response body and data files are never copied to the control ledger.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    ResourceURNText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

ICEBERG_ARCHITECTURE_HARVEST_SCHEMA = "gda.iceberg_architecture_harvest.v1"
_IDENTITY_NAMESPACE = UUID("81f4bf0b-7b6a-4bf5-8e56-a1fbf990252c")
_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"

IcebergName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=_NAME),
]


class IcebergArchitectureError(RuntimeError):
    """The provider payload is unavailable or cannot be used as architecture evidence."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IcebergArchitectureTarget(_FrozenModel):
    """Stable GDA and Gravitino identity plus the expected content binding."""

    tenant_id: TenantId
    resource_urn: ResourceURNText
    resource_version_id: UUID
    metalake: IcebergName
    catalog: IcebergName
    namespace: IcebergName
    object_name: IcebergName
    snapshot_ref: ExternalReference
    content_checksum: ExternalReference
    checksum_algorithm: ShortName = "sha256"
    expected_format_version: Literal["1", "2"] = "2"

    @model_validator(mode="after")
    def _tenant_matches_urn(self) -> IcebergArchitectureTarget:
        if parse_resource_urn(self.resource_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("resource_urn tenant must match tenant_id")
        return self


class IcebergSchemaField(_FrozenModel):
    ordinal: int = Field(ge=1)
    name: IcebergName
    data_type: ExternalReference
    nullable: bool
    field_id: int | None = Field(default=None, ge=0)


def iceberg_schema_snapshot_fingerprint(
    *,
    provider_namespace: str,
    provider_object_id: str,
    format_version: str,
    schema_id: int | None,
    fields: tuple[IcebergSchemaField, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": ICEBERG_ARCHITECTURE_HARVEST_SCHEMA,
            "provider_namespace": provider_namespace,
            "provider_object_id": provider_object_id,
            "format_version": format_version,
            "schema_id": schema_id,
            "fields": [field.model_dump(mode="json") for field in fields],
        }
    )


class IcebergSchemaSnapshot(_FrozenModel):
    schema_version: Literal[ICEBERG_ARCHITECTURE_HARVEST_SCHEMA] = (
        ICEBERG_ARCHITECTURE_HARVEST_SCHEMA
    )
    provider_namespace: ExternalReference
    provider_object_id: ExternalReference
    format_version: Literal["1", "2"]
    schema_id: int | None = Field(default=None, ge=0)
    fields: tuple[IcebergSchemaField, ...]
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> IcebergSchemaSnapshot:
        ordinals = [field.ordinal for field in self.fields]
        names = [field.name for field in self.fields]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("Iceberg schema field ordinals must be ordered and unique")
        if len(names) != len(set(names)):
            raise ValueError("Iceberg schema field names must be unique")
        expected = iceberg_schema_snapshot_fingerprint(
            provider_namespace=self.provider_namespace,
            provider_object_id=self.provider_object_id,
            format_version=self.format_version,
            schema_id=self.schema_id,
            fields=self.fields,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("snapshot_sha256 does not match Iceberg schema evidence")
        return self


class IcebergSnapshotLineageEntry(_FrozenModel):
    """One bounded Iceberg snapshot edge, ordered oldest to newest."""

    snapshot_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[0-9]+$"),
    ]
    parent_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[0-9]+$"),
    ] | None = None
    operation: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]


class IcebergArchitectureHarvest(_FrozenModel):
    observation: ArchitectureProviderObservation
    schema_snapshot: IcebergSchemaSnapshot | None = None
    schema_candidate: SchemaVersion | None = None
    physical_location_candidate: PhysicalLocation | None = None
    snapshot_lineage: tuple[IcebergSnapshotLineageEntry, ...] | None = None

    @model_validator(mode="after")
    def _consistent_harvest(self) -> IcebergArchitectureHarvest:
        candidates = (
            self.schema_snapshot,
            self.schema_candidate,
            self.physical_location_candidate,
        )
        if self.observation.object_state == ProviderObjectState.PRESENT:
            if any(value is None for value in candidates):
                raise ValueError("present Iceberg harvest requires architecture candidates")
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
            if self.snapshot_lineage is not None:
                if not self.snapshot_lineage:
                    raise ValueError("Iceberg snapshot lineage cannot be empty")
                seen: set[str] = set()
                for index, entry in enumerate(self.snapshot_lineage):
                    if entry.snapshot_id in seen:
                        raise ValueError("Iceberg snapshot lineage contains duplicate snapshot")
                    if index == 0 and entry.parent_id is not None:
                        raise ValueError("Iceberg snapshot lineage root cannot have a parent")
                    if index > 0 and entry.parent_id not in seen:
                        raise ValueError(
                            "Iceberg snapshot lineage parent must precede child"
                        )
                    seen.add(entry.snapshot_id)
                current_snapshot = self.observation.source_revision.removeprefix(
                    "iceberg-snapshot:"
                )
                if self.snapshot_lineage[-1].snapshot_id != current_snapshot:
                    raise ValueError("Iceberg snapshot lineage must end at current snapshot")
        elif any(value is not None for value in candidates):
            raise ValueError("tombstone Iceberg harvest cannot create candidates")
        elif self.snapshot_lineage is not None:
            raise ValueError("tombstone Iceberg harvest cannot create snapshot lineage")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("harvest timestamp must include a timezone")
    return value.astimezone(UTC)


def _identity(target: IcebergArchitectureTarget) -> tuple[str, str, str]:
    namespace = f"{target.metalake}/{target.catalog}/{target.namespace}"
    object_id = target.object_name
    locator = f"gravitino://{target.metalake}/{target.catalog}/{target.namespace}/{target.object_name}"
    return namespace, object_id, locator


def _observation(
    *,
    target: IcebergArchitectureTarget,
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
        provider_system="gravitino",
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
        provider_system="gravitino",
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


def _required_properties(table: Mapping[str, Any]) -> tuple[str, str, str, int | None]:
    properties = table.get("properties")
    if not isinstance(properties, Mapping):
        raise IcebergArchitectureError("Gravitino table properties are not an object")
    provider = str(properties.get("provider") or "").strip().lower()
    if provider != "iceberg":
        raise IcebergArchitectureError("Gravitino table is not backed by Iceberg")
    format_version = str(properties.get("format-version") or "").strip()
    if format_version not in {"1", "2"}:
        raise IcebergArchitectureError("Iceberg table format-version is missing or invalid")
    snapshot_value = properties.get("current-snapshot-id")
    if snapshot_value is None or str(snapshot_value).strip() == "":
        raise IcebergArchitectureError("Iceberg table has no current snapshot")
    snapshot_id = str(snapshot_value).strip()
    if not snapshot_id.isdigit():
        raise IcebergArchitectureError("Iceberg current-snapshot-id is not numeric")
    location = str(properties.get("location") or "").strip()
    parsed = urlsplit(location)
    if not parsed.scheme or parsed.username or parsed.password:
        raise IcebergArchitectureError("Iceberg location must be an absolute credential-free URI")
    schema_id_value = properties.get("current-schema-id")
    schema_id = int(schema_id_value) if schema_id_value is not None else None
    if schema_id is not None and schema_id < 0:
        raise IcebergArchitectureError("Iceberg current-schema-id must be non-negative")
    return format_version, snapshot_id, location, schema_id


def project_iceberg_rest_table_response(
    response: Mapping[str, Any], *, object_name: str
) -> dict[str, Any]:
    """Project an Iceberg REST ``GET table`` response into the harvester shape.

    The REST response may contain a complete metadata document. Only the current
    schema fields, table location, format/snapshot properties and a bounded
    snapshot chain are retained; metadata JSON, manifests and data-file entries
    are deliberately discarded.
    """

    if not isinstance(response, Mapping):
        raise IcebergArchitectureError("Iceberg REST table response is not an object")
    if not object_name or len(object_name) > 128:
        raise IcebergArchitectureError("Iceberg REST table name is invalid")
    metadata = response.get("metadata")
    if not isinstance(metadata, Mapping):
        raise IcebergArchitectureError("Iceberg REST table metadata is not an object")
    format_value = metadata.get("format-version")
    if format_value not in {1, 2, "1", "2"}:
        raise IcebergArchitectureError("Iceberg REST format-version is missing or invalid")
    snapshot_value = metadata.get("current-snapshot-id")
    snapshot_id = str(snapshot_value).strip() if snapshot_value is not None else ""
    if not snapshot_id.isdigit():
        raise IcebergArchitectureError("Iceberg REST current snapshot is missing or invalid")
    location = metadata.get("location")
    if not isinstance(location, str) or not location.strip():
        raise IcebergArchitectureError("Iceberg REST table location is missing")
    schema_id_value = metadata.get("current-schema-id")
    try:
        schema_id = int(schema_id_value) if schema_id_value is not None else None
    except (TypeError, ValueError) as exc:
        raise IcebergArchitectureError("Iceberg REST current schema ID is invalid") from exc
    schemas = metadata.get("schemas")
    if not isinstance(schemas, list) or not schemas:
        raise IcebergArchitectureError("Iceberg REST schemas are missing")
    current_schema = next(
        (
            schema
            for schema in schemas
            if isinstance(schema, Mapping)
            and (schema_id is None or schema.get("schema-id") == schema_id)
        ),
        None,
    )
    if not isinstance(current_schema, Mapping):
        raise IcebergArchitectureError("Iceberg REST current schema is missing")
    raw_fields = current_schema.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields or len(raw_fields) > 512:
        raise IcebergArchitectureError("Iceberg REST schema fields are missing or too large")
    columns: list[dict[str, Any]] = []
    for field in raw_fields:
        if not isinstance(field, Mapping):
            raise IcebergArchitectureError("Iceberg REST schema field is not an object")
        name = str(field.get("name") or "").strip()
        if not name or len(name) > 128:
            raise IcebergArchitectureError("Iceberg REST schema field name is invalid")
        field_id = field.get("id")
        try:
            parsed_field_id = int(field_id) if field_id is not None else None
        except (TypeError, ValueError) as exc:
            raise IcebergArchitectureError("Iceberg REST schema field ID is invalid") from exc
        if parsed_field_id is not None and parsed_field_id < 0:
            raise IcebergArchitectureError("Iceberg REST schema field ID is invalid")
        field_type = field.get("type")
        if field_type is None:
            raise IcebergArchitectureError("Iceberg REST schema field type is missing")
        if isinstance(field_type, str):
            type_text = field_type
        else:
            try:
                type_text = json.dumps(
                    field_type, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                )
            except (TypeError, ValueError) as exc:
                raise IcebergArchitectureError("Iceberg REST schema field type is invalid") from exc
        columns.append(
            {
                "name": name,
                "type": type_text,
                "nullable": not bool(field.get("required", False)),
                "field-id": parsed_field_id,
            }
        )
    raw_snapshots = metadata.get("snapshots")
    if not isinstance(raw_snapshots, list) or not raw_snapshots or len(raw_snapshots) > 256:
        raise IcebergArchitectureError("Iceberg REST snapshots are missing or too large")
    snapshots: list[dict[str, Any]] = []
    for snapshot in raw_snapshots:
        if not isinstance(snapshot, Mapping):
            raise IcebergArchitectureError("Iceberg REST snapshot is not an object")
        current = str(snapshot.get("snapshot-id") or "").strip()
        parent_value = snapshot.get("parent-snapshot-id")
        parent = str(parent_value).strip() if parent_value is not None else None
        if not current.isdigit() or (parent is not None and not parent.isdigit()):
            raise IcebergArchitectureError("Iceberg REST snapshot ID is invalid")
        summary = snapshot.get("summary")
        operation = summary.get("operation") if isinstance(summary, Mapping) else None
        if operation is None:
            operation = snapshot.get("operation")
        operation_text = str(operation or "").strip()
        if not operation_text:
            raise IcebergArchitectureError("Iceberg REST snapshot operation is missing")
        snapshots.append(
            {"snapshot_id": current, "parent_id": parent, "operation": operation_text}
        )
    return {
        "name": object_name,
        "columns": columns,
        "properties": {
            "provider": "iceberg",
            "format-version": str(format_value),
            "current-snapshot-id": snapshot_id,
            "current-schema-id": str(schema_id) if schema_id is not None else None,
            "location": location.strip(),
        },
        "snapshots": snapshots,
    }


def harvest_gravitino_iceberg_table(
    table: Mapping[str, Any] | None,
    target: IcebergArchitectureTarget,
    *,
    observed_by: NonEmptyText,
    observed_at: datetime | None = None,
    freshness_seconds: int = 300,
) -> IcebergArchitectureHarvest:
    """Project one confirmed Gravitino Iceberg table response into architecture facts.

    ``table is None`` is reserved for a provider-confirmed not-found response. Transport,
    authorization and malformed responses must be raised by the caller rather than mapped
    to a tombstone.
    """

    if freshness_seconds < 5 or freshness_seconds > 86400:
        raise ValueError("freshness_seconds must be between 5 and 86400")
    observed = _utc(observed_at or datetime.now(UTC))
    fresh_until = observed + timedelta(seconds=freshness_seconds)
    provider_namespace, provider_object_id, locator = _identity(target)
    if table is None:
        return IcebergArchitectureHarvest(
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
    if not isinstance(table, Mapping):
        raise IcebergArchitectureError("Gravitino table response is not an object")
    if table.get("name") != target.object_name:
        raise IcebergArchitectureError("Gravitino table identity does not match target")
    format_version, snapshot_id, location, schema_id = _required_properties(table)
    if format_version != target.expected_format_version:
        raise IcebergArchitectureError("Iceberg format-version does not match target contract")
    columns = table.get("columns")
    if not isinstance(columns, list) or not columns:
        raise IcebergArchitectureError("Gravitino Iceberg table must expose non-empty columns")
    fields: list[IcebergSchemaField] = []
    for ordinal, column in enumerate(columns, start=1):
        if not isinstance(column, Mapping):
            raise IcebergArchitectureError("Iceberg table column is not an object")
        field_id_value = column.get("field-id")
        field_id = int(field_id_value) if field_id_value is not None else None
        fields.append(
            IcebergSchemaField(
                ordinal=ordinal,
                name=str(column.get("name") or ""),
                data_type=str(column.get("type") or ""),
                nullable=bool(column.get("nullable", True)),
                field_id=field_id,
            )
        )
    schema_fields = tuple(fields)
    schema_content_sha256 = iceberg_schema_snapshot_fingerprint(
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        format_version=format_version,
        schema_id=schema_id,
        fields=schema_fields,
    )
    snapshot = IcebergSchemaSnapshot(
        provider_namespace=provider_namespace,
        provider_object_id=provider_object_id,
        format_version=format_version,
        schema_id=schema_id,
        fields=schema_fields,
        snapshot_sha256=schema_content_sha256,
    )
    source_revision = f"iceberg-snapshot:{snapshot_id}"
    snapshot_lineage = _snapshot_lineage(table, current_snapshot_id=snapshot_id)
    schema_values = {
        "tenant_id": target.tenant_id,
        "resource_version_id": target.resource_version_id,
        "schema_format": "iceberg",
        "authority_system": "gravitino",
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
        "location_kind": "iceberg_table",
        "provider_system": "iceberg",
        "provider_namespace": provider_namespace,
        "provider_locator": location,
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
    return IcebergArchitectureHarvest(
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
        schema_snapshot=snapshot,
        schema_candidate=schema_candidate,
        physical_location_candidate=location_candidate,
        snapshot_lineage=snapshot_lineage,
    )


def _snapshot_lineage(
    table: Mapping[str, Any], *, current_snapshot_id: str
) -> tuple[IcebergSnapshotLineageEntry, ...] | None:
    """Validate an optional bounded provider snapshot chain without reading data files."""

    raw_snapshots = table.get("snapshots")
    if raw_snapshots is None:
        return None
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        raise IcebergArchitectureError("Iceberg snapshots must be a non-empty list")
    if len(raw_snapshots) > 256:
        raise IcebergArchitectureError("Iceberg snapshot lineage exceeds the bounded limit")
    try:
        lineage = tuple(
            IcebergSnapshotLineageEntry(
                snapshot_id=str(item.get("snapshot_id") or ""),
                parent_id=(
                    str(item["parent_id"])
                    if item.get("parent_id") is not None
                    else None
                ),
                operation=str(item.get("operation") or ""),
            )
            for item in raw_snapshots
            if isinstance(item, Mapping)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise IcebergArchitectureError("Iceberg snapshot lineage is malformed") from exc
    if len(lineage) != len(raw_snapshots):
        raise IcebergArchitectureError("Iceberg snapshot lineage entries must be objects")
    seen: set[str] = set()
    for index, entry in enumerate(lineage):
        if entry.snapshot_id in seen:
            raise IcebergArchitectureError("Iceberg snapshot lineage contains duplicate snapshot")
        if index == 0 and entry.parent_id is not None:
            raise IcebergArchitectureError("Iceberg snapshot lineage root cannot have a parent")
        if index > 0 and entry.parent_id not in seen:
            raise IcebergArchitectureError("Iceberg snapshot lineage parent must precede child")
        seen.add(entry.snapshot_id)
    if lineage[-1].snapshot_id != current_snapshot_id:
        raise IcebergArchitectureError("Iceberg snapshot lineage must end at current snapshot")
    return lineage
