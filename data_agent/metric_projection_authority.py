"""Immutable physical projections for active governed metric definitions."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .metric_authority import GATEWAY_DATABASE_ROLE, DimensionName
from .platform_contracts import ResourceURNText, Sha256, TenantId, parse_resource_urn

_TENANT_ADAPTER = TypeAdapter(TenantId)

ColumnName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z_][a-z0-9_]{0,62}$",
    ),
]
ProjectionLocator = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricProjectionEngine(StrEnum):
    POSTGIS = "postgis"
    DUCKDB = "duckdb"
    ICEBERG_SPARK = "iceberg_spark"


class MetricProjectionTier(StrEnum):
    SERVING = "serving"
    INTERACTIVE = "interactive"
    GOLD = "gold"
    BATCH = "batch"


class MetricProjectionDocument(_FrozenContract):
    """Version-exact physical shape; every refresh creates a new version."""

    schema_id: Literal["gda.metric_projection.v1"] = "gda.metric_projection.v1"
    metric_version_ref: ResourceURNText
    metric_fingerprint: Sha256
    product_urn: ResourceURNText
    data_product_version_id: UUID
    output_resource_version_id: UUID
    source_manifest_sha256: Sha256
    source_snapshot_ref: ProjectionLocator
    engine: MetricProjectionEngine
    serving_tier: MetricProjectionTier
    relation_ref: ProjectionLocator
    value_column: ColumnName
    dimension_columns: dict[DimensionName, ColumnName]
    projection_dimensions: tuple[DimensionName, ...] = ()
    time_column: ColumnName | None = None
    time_grain: Literal[
        "minute", "hour", "day", "week", "month", "quarter", "year"
    ] | None = None
    geometry_column: ColumnName | None = None
    geometry_srid: int | None = Field(default=None, ge=1, le=999_999)
    geometry_crs: str | None = Field(
        default=None, pattern=r"^(EPSG|OGC):[A-Za-z0-9._-]{1,64}$"
    )
    refreshed_at: datetime
    estimated_rows: int = Field(ge=0, le=10**15)
    p95_latency_ms: int = Field(ge=1, le=86_400_000)

    @field_validator("metric_version_ref")
    @classmethod
    def _metric_version_identity(cls, value: str) -> str:
        identity = parse_resource_urn(value)
        if identity["resource_kind"] != "metric_definition" or re.search(
            r"\.v[1-9][0-9]*$", value
        ) is None:
            raise ValueError("projection must bind an immutable metric version")
        return value

    @field_validator("product_urn")
    @classmethod
    def _product_identity(cls, value: str) -> str:
        if parse_resource_urn(value)["resource_kind"] != "data_product":
            raise ValueError("projection must bind a data_product")
        return value

    @field_validator("refreshed_at")
    @classmethod
    def _utc_refresh_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection refresh time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("projection_dimensions")
    @classmethod
    def _sorted_unique_dimensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("projection dimensions must be unique and sorted")
        return values

    @field_validator("dimension_columns")
    @classmethod
    def _bounded_dimension_columns(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 100:
            raise ValueError("projection dimension mapping is too large")
        if len(set(values.values())) != len(values):
            raise ValueError("projection dimension columns must be unique")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def _consistent_projection(self) -> MetricProjectionDocument:
        if tuple(self.dimension_columns) != self.projection_dimensions:
            raise ValueError("projection dimensions must exactly match dimension mapping")
        locator_patterns = {
            MetricProjectionEngine.POSTGIS: r"^postgis://[a-z0-9][a-z0-9._-]{0,127}/[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}$",
            MetricProjectionEngine.DUCKDB: r"^duckdb://[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._/-]{0,255}$",
            MetricProjectionEngine.ICEBERG_SPARK: r"^iceberg://[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$",
        }
        if re.fullmatch(locator_patterns[self.engine], self.relation_ref) is None:
            raise ValueError("projection relation does not match its engine")
        allowed_tiers = {
            MetricProjectionEngine.POSTGIS: {MetricProjectionTier.SERVING},
            MetricProjectionEngine.DUCKDB: {MetricProjectionTier.INTERACTIVE},
            MetricProjectionEngine.ICEBERG_SPARK: {
                MetricProjectionTier.GOLD,
                MetricProjectionTier.BATCH,
            },
        }
        if self.serving_tier not in allowed_tiers[self.engine]:
            raise ValueError("projection serving tier does not match its engine")
        if (self.time_column is None) != (self.time_grain is None):
            raise ValueError("projection time column and grain must be declared together")
        geometry = (
            self.geometry_column,
            self.geometry_srid,
            self.geometry_crs,
        )
        if any(value is None for value in geometry) and any(
            value is not None for value in geometry
        ):
            raise ValueError("projection geometry column, SRID and CRS are atomic")
        metric_tenant = parse_resource_urn(self.metric_version_ref)["tenant_id"]
        product_tenant = parse_resource_urn(self.product_urn)["tenant_id"]
        if metric_tenant != product_tenant:
            raise ValueError("projection metric and data product must share the tenant")
        return self


class MetricProjectionDraft(_FrozenContract):
    tenant_id: TenantId
    projection_ref: ResourceURNText
    projection_version_ref: ResourceURNText
    version: Annotated[int, Field(ge=1, le=1_000_000)]
    projection: MetricProjectionDocument
    created_by: str
    creation_reason: NonEmptyText
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection creation time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("created_by")
    @classmethod
    def _typed_creator(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("projection creator must use a typed subject")
        return value

    @model_validator(mode="after")
    def _consistent_identity(self) -> MetricProjectionDraft:
        base = parse_resource_urn(self.projection_ref)
        version = parse_resource_urn(self.projection_version_ref)
        metric = parse_resource_urn(self.projection.metric_version_ref)
        product = parse_resource_urn(self.projection.product_urn)
        if base["resource_kind"] != "metric_projection" or version[
            "resource_kind"
        ] != "metric_projection":
            raise ValueError("projection identity must use resource kind 'metric_projection'")
        if any(
            identity["tenant_id"] != self.tenant_id
            for identity in (base, version, metric, product)
        ):
            raise ValueError("projection identities must share tenant_id")
        if self.projection_version_ref != f"{self.projection_ref}.v{self.version}":
            raise ValueError("projection version reference must bind identity and version")
        if self.projection.refreshed_at > self.created_at:
            raise ValueError("projection refresh cannot occur after version registration")
        return self


class MetricProjectionVersion(MetricProjectionDraft):
    projection_fingerprint: Sha256


class MetricProjectionActivation(_FrozenContract):
    tenant_id: TenantId
    projection_ref: ResourceURNText
    active_version_ref: ResourceURNText
    active_fingerprint: Sha256
    activation_version: Annotated[int, Field(ge=1)]
    activated_by: str
    activation_reason: NonEmptyText
    activated_at: datetime

    @field_validator("activated_at")
    @classmethod
    def _utc_activated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection activation time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("activated_by")
    @classmethod
    def _typed_activator(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("projection activator must use a typed subject")
        return value

    @model_validator(mode="after")
    def _consistent_identity(self) -> MetricProjectionActivation:
        base = parse_resource_urn(self.projection_ref)
        version = parse_resource_urn(self.active_version_ref)
        if base["tenant_id"] != self.tenant_id or version[
            "tenant_id"
        ] != self.tenant_id:
            raise ValueError("projection activation identities must share tenant_id")
        if not self.active_version_ref.startswith(f"{self.projection_ref}.v"):
            raise ValueError("active projection version must belong to the projection")
        return self


class MetricProjectionEvent(_FrozenContract):
    tenant_id: TenantId
    projection_event_id: UUID
    projection_ref: ResourceURNText
    projection_version_ref: ResourceURNText
    projection_fingerprint: Sha256
    event_type: Literal["staged", "activated"]
    actor_subject: str
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection event time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("actor_subject")
    @classmethod
    def _typed_actor(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("projection event actor must use a typed subject")
        return value


class ActiveMetricProjection(_FrozenContract):
    version: MetricProjectionVersion
    activation: MetricProjectionActivation

    @model_validator(mode="after")
    def _exact_active_version(self) -> ActiveMetricProjection:
        if (
            self.activation.tenant_id != self.version.tenant_id
            or self.activation.projection_ref != self.version.projection_ref
            or self.activation.active_version_ref != self.version.projection_version_ref
            or self.activation.active_fingerprint
            != self.version.projection_fingerprint
        ):
            raise ValueError("projection activation must bind the exact version")
        return self


class MetricProjectionAuthorityError(RuntimeError):
    code = "metric_projection_authority_error"


class MetricProjectionConflictError(MetricProjectionAuthorityError):
    code = "metric_projection_conflict"


class MetricProjectionNotFoundError(MetricProjectionAuthorityError):
    code = "metric_projection_not_found"


class MetricProjectionForbiddenError(MetricProjectionAuthorityError):
    code = "metric_projection_forbidden"


class MetricProjectionValidationError(MetricProjectionAuthorityError):
    code = "metric_projection_validation_error"


class MetricProjectionConfigurationError(MetricProjectionAuthorityError):
    code = "metric_projection_authority_unavailable"


@dataclass(frozen=True)
class MetricProjectionVersionPage:
    items: tuple[MetricProjectionVersion, ...]
    offset: int
    limit: int
    has_more: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _validate_projection_ref(tenant_id: str, projection_ref: str) -> None:
    identity = parse_resource_urn(projection_ref)
    if identity["tenant_id"] != tenant_id or identity[
        "resource_kind"
    ] != "metric_projection":
        raise ValueError("metric projection identity does not match the tenant")


class MetricProjectionAuthority:
    """PostgreSQL authority for projection versions and active pointers."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise MetricProjectionConfigurationError(
                "metric projection authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise MetricProjectionConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except MetricProjectionAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise MetricProjectionConflictError(
                    "metric projection authority state conflict"
                ) from exc
            if state == "P0002":
                raise MetricProjectionNotFoundError(
                    "metric projection was not found"
                ) from exc
            if state == "42501":
                raise MetricProjectionForbiddenError(
                    "metric projection tenant access was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise MetricProjectionValidationError(
                    "metric projection contract was rejected"
                ) from exc
            raise MetricProjectionAuthorityError(
                "metric projection database operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise MetricProjectionAuthorityError(
                "metric projection database operation failed"
            ) from exc

    @staticmethod
    def _version_from_row(row: Any) -> MetricProjectionVersion:
        value = dict(row)
        value["projection"] = _json_value(value.pop("projection_document"))
        return MetricProjectionVersion.model_validate(value)

    @staticmethod
    def _activation_from_row(row: Any) -> MetricProjectionActivation:
        return MetricProjectionActivation.model_validate(dict(row))

    @staticmethod
    def _event_from_row(row: Any) -> MetricProjectionEvent:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return MetricProjectionEvent.model_validate(value)

    @classmethod
    def _load_version(
        cls, connection: Any, tenant_id: str, projection_version_ref: str
    ) -> MetricProjectionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, projection_ref, projection_version_ref,
                           projection_version AS version, projection_document,
                           projection_fingerprint, created_by,
                           creation_reason, created_at
                    FROM gda_control.metric_projection_version
                    WHERE tenant_id = :tenant_id
                      AND projection_version_ref = :projection_version_ref
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "projection_version_ref": projection_version_ref,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._version_from_row(row) if row is not None else None

    def stage(self, draft: MetricProjectionDraft) -> MetricProjectionVersion:
        with self._transaction(draft.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.stage_metric_projection_version(
                        :tenant_id, :projection_ref, :projection_version_ref,
                        :projection_version, CAST(:projection_document AS jsonb),
                        :created_by, :creation_reason, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "projection_ref": draft.projection_ref,
                    "projection_version_ref": draft.projection_version_ref,
                    "projection_version": draft.version,
                    "projection_document": _json(
                        draft.projection.model_dump(mode="json")
                    ),
                    "created_by": draft.created_by,
                    "creation_reason": draft.creation_reason,
                    "created_at": draft.created_at,
                },
            ).scalar_one()
            stored = self._load_version(
                connection, draft.tenant_id, draft.projection_version_ref
            )
            if stored is None:
                raise MetricProjectionNotFoundError(
                    "staged metric projection was not visible"
                )
            comparable = stored.model_dump(
                exclude={"projection_fingerprint", "created_at"}
            )
            if comparable != draft.model_dump(exclude={"created_at"}):
                raise MetricProjectionConflictError(
                    "projection version identity has different evidence"
                )
            return stored

    def get(
        self, tenant_id: str, projection_version_ref: str
    ) -> MetricProjectionVersion:
        _validate_projection_ref(tenant_id, projection_version_ref)
        with self._transaction(tenant_id) as connection:
            stored = self._load_version(connection, tenant_id, projection_version_ref)
            if stored is None:
                raise MetricProjectionNotFoundError("metric projection was not found")
            return stored

    def list_versions(
        self,
        tenant_id: str,
        projection_ref: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> MetricProjectionVersionPage:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        _validate_projection_ref(tenant, projection_ref)
        if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
            raise ValueError("projection version query is outside the supported range")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, projection_ref, projection_version_ref,
                               projection_version AS version, projection_document,
                               projection_fingerprint, created_by,
                               creation_reason, created_at
                        FROM gda_control.metric_projection_version
                        WHERE tenant_id = :tenant_id
                          AND projection_ref = :projection_ref
                        ORDER BY projection_version DESC, projection_version_ref DESC
                        LIMIT :row_limit OFFSET :offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "projection_ref": projection_ref,
                        "row_limit": limit + 1,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        return MetricProjectionVersionPage(
            items=tuple(self._version_from_row(row) for row in rows[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    def activate(
        self,
        *,
        tenant_id: str,
        projection_version_ref: str,
        projection_fingerprint: str,
        expected_activation_version: int,
        actor_subject: str,
        reason: str,
    ) -> MetricProjectionActivation:
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.activate_metric_projection_version(
                        :tenant_id, :projection_version_ref,
                        :projection_fingerprint, :expected_activation_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "projection_version_ref": projection_version_ref,
                    "projection_fingerprint": projection_fingerprint,
                    "expected_activation_version": expected_activation_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
            version = self._load_version(
                connection, tenant_id, projection_version_ref
            )
            if version is None:
                raise MetricProjectionNotFoundError(
                    "activated metric projection was not visible"
                )
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, projection_ref, active_version_ref,
                               active_fingerprint, activation_version,
                               activated_by, activation_reason, activated_at
                        FROM gda_control.metric_projection_activation
                        WHERE tenant_id = :tenant_id
                          AND projection_ref = :projection_ref
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "projection_ref": version.projection_ref,
                    },
                )
                .mappings()
                .one()
            )
            return self._activation_from_row(row)

    def active_for_metric(
        self,
        tenant_id: str,
        metric_version_ref: str,
        metric_fingerprint: str,
    ) -> tuple[ActiveMetricProjection, ...]:
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT v.tenant_id, v.projection_ref,
                               v.projection_version_ref,
                               v.projection_version AS version,
                               v.projection_document, v.projection_fingerprint,
                               v.created_by, v.creation_reason, v.created_at,
                               a.active_version_ref, a.active_fingerprint,
                               a.activation_version, a.activated_by,
                               a.activation_reason, a.activated_at
                        FROM gda_control.metric_projection_activation a
                        JOIN gda_control.metric_projection_version v
                          ON v.tenant_id = a.tenant_id
                         AND v.projection_version_ref = a.active_version_ref
                         AND v.projection_fingerprint = a.active_fingerprint
                        JOIN gda_control.metric_definition_activation m
                          ON m.tenant_id = v.tenant_id
                         AND m.active_version_ref = :metric_version_ref
                         AND m.active_fingerprint = :metric_fingerprint
                        WHERE v.tenant_id = :tenant_id
                          AND v.metric_version_ref = m.active_version_ref
                          AND v.metric_fingerprint = m.active_fingerprint
                        ORDER BY
                          CASE v.projection_document->>'serving_tier'
                            WHEN 'serving' THEN 0
                            WHEN 'interactive' THEN 1
                            WHEN 'gold' THEN 2
                            ELSE 3
                          END,
                          (v.projection_document->>'p95_latency_ms')::bigint,
                          v.projection_ref
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "metric_version_ref": metric_version_ref,
                        "metric_fingerprint": metric_fingerprint,
                    },
                )
                .mappings()
                .all()
            )
        active: list[ActiveMetricProjection] = []
        for source in rows:
            row = dict(source)
            activation = {
                "tenant_id": row["tenant_id"],
                "projection_ref": row["projection_ref"],
                **{
                    key: row.pop(key)
                    for key in (
                        "active_version_ref",
                        "active_fingerprint",
                        "activation_version",
                        "activated_by",
                        "activation_reason",
                        "activated_at",
                    )
                },
            }
            active.append(
                ActiveMetricProjection(
                    version=self._version_from_row(row),
                    activation=self._activation_from_row(activation),
                )
            )
        return tuple(active)

    def events(
        self, tenant_id: str, projection_ref: str
    ) -> tuple[MetricProjectionEvent, ...]:
        _validate_projection_ref(tenant_id, projection_ref)
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, projection_event_id, projection_ref,
                               projection_version_ref, projection_fingerprint,
                               event_type, actor_subject, reason, details,
                               occurred_at
                        FROM gda_control.metric_projection_event
                        WHERE tenant_id = :tenant_id
                          AND projection_ref = :projection_ref
                        ORDER BY occurred_at, projection_event_id
                        """
                    ),
                    {"tenant_id": tenant_id, "projection_ref": projection_ref},
                )
                .mappings()
                .all()
            )
        return tuple(self._event_from_row(row) for row in rows)
