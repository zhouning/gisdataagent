"""Read-only DuckDB schema and location harvester for the lightweight profile.

DuckDB is an execution and storage provider, not a second metadata authority.
This module only emits bounded schema evidence and stable provider references;
the platform gateway remains responsible for recording observations and binding
them to a ResourceVersion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
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
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
)

DUCKDB_ARCHITECTURE_HARVEST_SCHEMA = "gda.duckdb_architecture_harvest.v1"
_IDENTITY_NAMESPACE = UUID("b7d4e08e-2ebd-48e3-9f4d-4b10cc86f0e9")

DuckdbObjectName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DuckdbArchitectureTarget(_FrozenModel):
    """Credential-free identity and immutable content binding for one table."""

    tenant_id: TenantId
    resource_version_id: UUID
    provider_ref: ShortName
    database_ref: ExternalReference
    schema_name: DuckdbObjectName
    table_name: DuckdbObjectName
    snapshot_ref: ExternalReference
    content_checksum: ExternalReference
    checksum_algorithm: ShortName = "sha256"


class DuckdbSchemaColumn(_FrozenModel):
    ordinal: int = Field(ge=1)
    name: DuckdbObjectName
    data_type: ExternalReference
    nullable: bool
    default_expression_sha256: Sha256 | None = None


class DuckdbSchemaConstraint(_FrozenModel):
    ordinal: int = Field(ge=0)
    name: DuckdbObjectName
    constraint_type: ShortName
    definition_sha256: Sha256


class DuckdbSchemaIndex(_FrozenModel):
    name: DuckdbObjectName
    is_unique: bool
    is_primary: bool
    definition_sha256: Sha256


def duckdb_schema_snapshot_fingerprint(
    *,
    provider_namespace: str,
    provider_object_id: str,
    table_oid: int,
    columns: tuple[DuckdbSchemaColumn, ...],
    constraints: tuple[DuckdbSchemaConstraint, ...],
    indexes: tuple[DuckdbSchemaIndex, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": DUCKDB_ARCHITECTURE_HARVEST_SCHEMA,
            "provider_namespace": provider_namespace,
            "provider_object_id": provider_object_id,
            "columns": [column.model_dump(mode="json") for column in columns],
            "constraints": [constraint.model_dump(mode="json") for constraint in constraints],
            "indexes": [index.model_dump(mode="json") for index in indexes],
        }
    )


class DuckdbSchemaSnapshot(_FrozenModel):
    schema_version: Literal[DUCKDB_ARCHITECTURE_HARVEST_SCHEMA] = (
        DUCKDB_ARCHITECTURE_HARVEST_SCHEMA
    )
    provider_namespace: ExternalReference
    provider_object_id: ExternalReference
    table_oid: int = Field(ge=0)
    columns: tuple[DuckdbSchemaColumn, ...]
    constraints: tuple[DuckdbSchemaConstraint, ...]
    indexes: tuple[DuckdbSchemaIndex, ...]
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_snapshot(self) -> DuckdbSchemaSnapshot:
        ordinals = [column.ordinal for column in self.columns]
        names = [column.name for column in self.columns]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("DuckDB schema column ordinals must be ordered and unique")
        if len(names) != len(set(names)):
            raise ValueError("DuckDB schema column names must be unique")
        constraint_ordinals = [constraint.ordinal for constraint in self.constraints]
        if constraint_ordinals != sorted(constraint_ordinals) or len(
            constraint_ordinals
        ) != len(set(constraint_ordinals)):
            raise ValueError("DuckDB schema constraints must be ordered and unique")
        index_names = [index.name for index in self.indexes]
        if index_names != sorted(index_names) or len(index_names) != len(set(index_names)):
            raise ValueError("DuckDB schema indexes must be ordered and unique")
        expected = duckdb_schema_snapshot_fingerprint(
            provider_namespace=self.provider_namespace,
            provider_object_id=self.provider_object_id,
            table_oid=self.table_oid,
            columns=self.columns,
            constraints=self.constraints,
            indexes=self.indexes,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("snapshot_sha256 does not match DuckDB schema evidence")
        return self


class DuckdbArchitectureHarvest(_FrozenModel):
    """One observation and present-only architecture candidates."""

    observation: ArchitectureProviderObservation
    schema_snapshot: DuckdbSchemaSnapshot | None = None
    schema_candidate: SchemaVersion | None = None
    physical_location_candidate: PhysicalLocation | None = None

    @model_validator(mode="after")
    def _consistent_harvest(self) -> DuckdbArchitectureHarvest:
        candidates = (
            self.schema_snapshot,
            self.schema_candidate,
            self.physical_location_candidate,
        )
        if self.observation.object_state == ProviderObjectState.PRESENT:
            if any(value is None for value in candidates):
                raise ValueError("present DuckDB harvest requires architecture candidates")
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
            raise ValueError("tombstone DuckDB harvest cannot create candidates")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("harvest timestamp must include a timezone")
    return value.astimezone(UTC)


def _provider_identity(target: DuckdbArchitectureTarget) -> tuple[str, str, str]:
    namespace = f"{target.provider_ref}/{target.database_ref}"
    object_id = f"{target.schema_name}.{target.table_name}"
    locator = (
        f"duckdb://{quote(target.provider_ref, safe='')}/"
        f"{quote(target.database_ref, safe='')}/"
        f"{quote(target.schema_name, safe='')}/"
        f"{quote(target.table_name, safe='')}"
    )
    return namespace, object_id, locator


def _rows(connection: Any, statement: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = connection.execute(statement, parameters)
    names = [description[0] for description in cursor.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _observation(
    *,
    target: DuckdbArchitectureTarget,
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
        provider_system="duckdb",
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
        provider_system="duckdb",
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


def harvest_duckdb_architecture(
    database: str | Path | Any,
    target: DuckdbArchitectureTarget,
    *,
    observed_by: NonEmptyText,
    observed_at: datetime | None = None,
    freshness_seconds: int = 300,
) -> DuckdbArchitectureHarvest:
    """Read one DuckDB table in a read-only connection and hash bounded facts.

    ``database`` may be a DuckDB path or an already-open DB-API connection.
    Callers passing a connection own its transaction; path-based harvesting
    always opens a provider-enforced read-only connection.
    """
    if freshness_seconds < 5 or freshness_seconds > 86400:
        raise ValueError("freshness_seconds must be between 5 and 86400")
    observed = _utc(observed_at or datetime.now(UTC))
    fresh_until = observed + timedelta(seconds=freshness_seconds)
    provider_namespace, provider_object_id, locator = _provider_identity(target)

    owns_connection = isinstance(database, (str, Path))
    if owns_connection:
        import duckdb

        connection = duckdb.connect(str(database), read_only=True)
    else:
        connection = database
    try:
        tables = _rows(
            connection,
            """
            SELECT table_oid
            FROM duckdb_tables()
            WHERE schema_name = ? AND table_name = ?
            """,
            (target.schema_name, target.table_name),
        )
        if not tables:
            return DuckdbArchitectureHarvest(
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
        if len(tables) != 1:
            raise ValueError("DuckDB provider returned multiple objects for one table identity")
        table_oid = int(tables[0]["table_oid"])
        columns = _rows(
            connection,
            """
            SELECT ordinal_position, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            ORDER BY ordinal_position
            """,
            (target.schema_name, target.table_name),
        )
        constraints = _rows(
            connection,
            """
            SELECT constraint_index, constraint_type, constraint_text,
                   constraint_name
            FROM duckdb_constraints()
            WHERE schema_name = ? AND table_name = ?
            ORDER BY constraint_index
            """,
            (target.schema_name, target.table_name),
        )
        indexes = _rows(
            connection,
            """
            SELECT index_name, is_unique, is_primary, sql
            FROM duckdb_indexes()
            WHERE schema_name = ? AND table_name = ?
            ORDER BY index_name
            """,
            (target.schema_name, target.table_name),
        )
    finally:
        if owns_connection:
            connection.close()

    normalized_columns = tuple(
        DuckdbSchemaColumn(
            ordinal=int(column["ordinal_position"]),
            name=column["column_name"],
            data_type=column["data_type"],
            nullable=column["is_nullable"] == "YES",
            default_expression_sha256=(
                canonical_json_fingerprint({"expression": column["column_default"]})
                if column["column_default"] is not None
                else None
            ),
        )
        for column in columns
    )
    normalized_constraints = tuple(
        DuckdbSchemaConstraint(
            ordinal=int(constraint["constraint_index"]),
            name=constraint["constraint_name"]
            or f"{constraint['constraint_type'].lower()}-{constraint['constraint_index']}",
            constraint_type=constraint["constraint_type"].lower().replace(" ", "_"),
            definition_sha256=canonical_json_fingerprint(
                {"definition": constraint["constraint_text"]}
            ),
        )
        for constraint in constraints
    )
    normalized_indexes = tuple(
        DuckdbSchemaIndex(
            name=index["index_name"],
            is_unique=bool(index["is_unique"]),
            is_primary=bool(index["is_primary"]),
            definition_sha256=canonical_json_fingerprint({"definition": index["sql"]}),
        )
        for index in indexes
    )
    snapshot_values = {
        "provider_namespace": provider_namespace,
        "provider_object_id": provider_object_id,
        "table_oid": table_oid,
        "columns": normalized_columns,
        "constraints": normalized_constraints,
        "indexes": normalized_indexes,
    }
    schema_content_sha256 = duckdb_schema_snapshot_fingerprint(**snapshot_values)
    schema_snapshot = DuckdbSchemaSnapshot(
        snapshot_sha256=schema_content_sha256,
        **snapshot_values,
    )
    source_revision = f"schema-sha256:{schema_content_sha256}:table-oid:{table_oid}"
    schema_values = {
        "tenant_id": target.tenant_id,
        "resource_version_id": target.resource_version_id,
        "schema_format": "duckdb",
        "authority_system": "provider",
        "authority_namespace": provider_namespace,
        "authority_object_id": provider_object_id,
        "authority_version_ref": source_revision,
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
        "location_kind": "duckdb_table",
        "provider_system": "duckdb",
        "provider_namespace": provider_namespace,
        "provider_locator": locator,
        "snapshot_ref": target.snapshot_ref,
        "revision_ref": f"duckdb-table-oid:{table_oid}",
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
    observation = _observation(
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
    )
    return DuckdbArchitectureHarvest(
        observation=observation,
        schema_snapshot=schema_snapshot,
        schema_candidate=schema_candidate,
        physical_location_candidate=location_candidate,
    )
