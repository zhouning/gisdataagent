"""Read-only PostGIS technical-schema and location harvester."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    model_validator,
)
from sqlalchemy import text

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
from .postgis_schema_evidence import (
    PostgisSchemaColumn,
    PostgisSchemaConstraint,
    PostgisSchemaIndex,
    PostgisSchemaSnapshot,
    postgis_schema_snapshot_fingerprint,
)

POSTGIS_ARCHITECTURE_HARVEST_SCHEMA = "gda.postgis_architecture_harvest.v1"
_IDENTITY_NAMESPACE = UUID("99d738a5-f630-4bc8-9e7a-b66d96e216b8")

PostgresObjectName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PostgisArchitectureTarget(_FrozenModel):
    """Credential-free identity and immutable content binding for one table."""

    tenant_id: TenantId
    resource_version_id: UUID
    provider_ref: ShortName
    schema_name: PostgresObjectName
    table_name: PostgresObjectName
    snapshot_ref: ExternalReference
    content_checksum: ExternalReference
    checksum_algorithm: ShortName = "sha256"


class PostgisArchitectureHarvest(_FrozenModel):
    """One observation and present-only architecture candidates."""

    observation: ArchitectureProviderObservation
    schema_snapshot: PostgisSchemaSnapshot | None = None
    schema_candidate: SchemaVersion | None = None
    physical_location_candidate: PhysicalLocation | None = None

    @model_validator(mode="after")
    def _consistent_harvest(self) -> PostgisArchitectureHarvest:
        candidates = (
            self.schema_snapshot,
            self.schema_candidate,
            self.physical_location_candidate,
        )
        if self.observation.object_state == ProviderObjectState.PRESENT:
            if any(value is None for value in candidates):
                raise ValueError("present PostGIS harvest requires architecture candidates")
            assert self.schema_candidate is not None
            assert self.physical_location_candidate is not None
            assert self.schema_snapshot is not None
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
            raise ValueError("tombstone PostGIS harvest cannot create candidates")
        return self


_RELATION_SQL = text(
    """
    SELECT current_database() AS database_name,
           relation.oid::bigint AS relation_oid,
           pg_relation_filenode(relation.oid)::bigint AS relation_filenode,
           relation.relkind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = :schema_name
      AND relation.relname = :table_name
      AND relation.relkind IN ('r', 'p', 'm')
    """
)

_COLUMNS_SQL = text(
    """
    SELECT attribute.attnum AS ordinal,
           attribute.attname AS name,
           pg_catalog.format_type(
               attribute.atttypid, attribute.atttypmod
           ) AS data_type,
           attribute.attnotnull AS not_null,
           attribute.attidentity AS identity_kind,
           attribute.attgenerated AS generated_kind,
           pg_catalog.pg_get_expr(
               default_value.adbin, default_value.adrelid
           ) AS default_expression
    FROM pg_catalog.pg_attribute AS attribute
    LEFT JOIN pg_catalog.pg_attrdef AS default_value
      ON default_value.adrelid = attribute.attrelid
     AND default_value.adnum = attribute.attnum
    WHERE attribute.attrelid = :relation_oid
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    ORDER BY attribute.attnum
    """
)

_CONSTRAINTS_SQL = text(
    """
    SELECT constraint_row.conname AS name,
           constraint_row.contype AS constraint_type,
           pg_catalog.pg_get_constraintdef(
               constraint_row.oid, true
           ) AS definition
    FROM pg_catalog.pg_constraint AS constraint_row
    WHERE constraint_row.conrelid = :relation_oid
    ORDER BY constraint_row.contype, constraint_row.conname
    """
)

_INDEXES_SQL = text(
    """
    SELECT index_row.relname AS name,
           pg_catalog.pg_get_indexdef(index_row.oid) AS definition
    FROM pg_catalog.pg_index AS index_link
    JOIN pg_catalog.pg_class AS index_row
      ON index_row.oid = index_link.indexrelid
    WHERE index_link.indrelid = :relation_oid
      AND NOT index_link.indisprimary
    ORDER BY index_row.relname
    """
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("harvest timestamp must include a timezone")
    return value.astimezone(UTC)


def _provider_identity(
    target: PostgisArchitectureTarget,
    database_name: str,
) -> tuple[str, str, str]:
    namespace = f"{target.provider_ref}/{database_name}"
    object_id = f"{target.schema_name}.{target.table_name}"
    locator = (
        f"postgresql://{target.provider_ref}/"
        f"{quote(database_name, safe='')}/"
        f"{quote(target.schema_name, safe='')}/"
        f"{quote(target.table_name, safe='')}"
    )
    return namespace, object_id, locator


def _observation(
    *,
    target: PostgisArchitectureTarget,
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
        provider_system="postgis",
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
        provider_system="postgis",
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


def harvest_postgis_architecture(
    engine,
    target: PostgisArchitectureTarget,
    *,
    observed_by: NonEmptyText,
    observed_at: datetime | None = None,
    freshness_seconds: int = 300,
) -> PostgisArchitectureHarvest:
    """Read PostgreSQL catalogs in a read-only transaction and hash bounded facts."""
    if engine.dialect.name != "postgresql":
        raise ValueError("PostGIS architecture harvesting requires PostgreSQL")
    if freshness_seconds < 5 or freshness_seconds > 86400:
        raise ValueError("freshness_seconds must be between 5 and 86400")
    observed = _utc(observed_at or datetime.now(UTC))
    fresh_until = observed + timedelta(seconds=freshness_seconds)

    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
            relation = (
                connection.execute(
                    _RELATION_SQL,
                    {
                        "schema_name": target.schema_name,
                        "table_name": target.table_name,
                    },
                )
                .mappings()
                .one_or_none()
            )
            provider_namespace, provider_object_id, locator = _provider_identity(
                target, database_name
            )
            if relation is None:
                return PostgisArchitectureHarvest(
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
            relation_oid = int(relation["relation_oid"])
            columns = [
                dict(row)
                for row in connection.execute(
                    _COLUMNS_SQL, {"relation_oid": relation_oid}
                ).mappings()
            ]
            constraints = [
                dict(row)
                for row in connection.execute(
                    _CONSTRAINTS_SQL, {"relation_oid": relation_oid}
                ).mappings()
            ]
            indexes = [
                dict(row)
                for row in connection.execute(
                    _INDEXES_SQL, {"relation_oid": relation_oid}
                ).mappings()
            ]

    normalized_columns = tuple(
        PostgisSchemaColumn(
            ordinal=int(column["ordinal"]),
            name=column["name"],
            data_type=column["data_type"],
            not_null=bool(column["not_null"]),
            identity_kind=column["identity_kind"] or "",
            generated_kind=column["generated_kind"] or "",
            default_expression_sha256=(
                canonical_json_fingerprint({"expression": column["default_expression"]})
                if column["default_expression"] is not None
                else None
            ),
        )
        for column in columns
    )
    normalized_constraints = tuple(
        PostgisSchemaConstraint(
            name=constraint["name"],
            constraint_type=constraint["constraint_type"],
            definition_sha256=canonical_json_fingerprint({"definition": constraint["definition"]}),
        )
        for constraint in constraints
    )
    normalized_indexes = tuple(
        PostgisSchemaIndex(
            name=index["name"],
            definition_sha256=canonical_json_fingerprint({"definition": index["definition"]}),
        )
        for index in indexes
    )
    snapshot_values = {
        "provider_namespace": provider_namespace,
        "provider_object_id": provider_object_id,
        "relation_kind": relation["relkind"],
        "columns": normalized_columns,
        "constraints": normalized_constraints,
        "indexes": normalized_indexes,
    }
    schema_content_sha256: Sha256 = postgis_schema_snapshot_fingerprint(**snapshot_values)
    schema_snapshot = PostgisSchemaSnapshot(
        snapshot_sha256=schema_content_sha256,
        **snapshot_values,
    )
    source_revision = f"schema-sha256:{schema_content_sha256}"
    relation_filenode = relation["relation_filenode"]
    relation_revision = f"postgres-oid:{relation_oid}:filenode:{relation_filenode or 0}"
    schema_values = {
        "tenant_id": target.tenant_id,
        "resource_version_id": target.resource_version_id,
        "schema_format": "postgresql",
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
        "location_kind": "postgis_table",
        "provider_system": "postgis",
        "provider_namespace": provider_namespace,
        "provider_locator": locator,
        "snapshot_ref": target.snapshot_ref,
        "revision_ref": relation_revision,
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
    return PostgisArchitectureHarvest(
        observation=observation,
        schema_snapshot=schema_snapshot,
        schema_candidate=schema_candidate,
        physical_location_candidate=location_candidate,
    )
