"""Canonical, immutable metric definitions for the semantic control plane."""

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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from .platform_contracts import ResourceURNText, Sha256, TenantId, parse_resource_urn

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
METRIC_ACTIVATION_ACTION = "metric_definition.activate"
_TENANT_ADAPTER = TypeAdapter(TenantId)

MetricName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]{0,127}$",
    ),
]
DimensionName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]{0,127}$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricValueType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENTAGE = "percentage"
    DURATION = "duration"
    CURRENCY = "currency"


class MetricAggregationKind(StrEnum):
    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"


class MetricTimeKind(StrEnum):
    EVENT = "event"
    PERIODIC = "periodic"
    SNAPSHOT = "snapshot"


class MetricTimeGrain(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class MetricSpatialGrain(StrEnum):
    FEATURE = "feature"
    PARCEL = "parcel"
    GRID = "grid"
    ADMINISTRATIVE_UNIT = "administrative_unit"
    CATCHMENT = "catchment"
    CUSTOM = "custom"


class MetricSpatialRelationship(StrEnum):
    INTERSECTS = "intersects"
    WITHIN = "within"
    CONTAINS = "contains"
    CENTROID_WITHIN = "centroid_within"


class MetricMaterializationMode(StrEnum):
    ON_DEMAND = "on_demand"
    PRECOMPUTE = "precompute"
    INCREMENTAL = "incremental"


class MetricServingTier(StrEnum):
    GOLD = "gold"
    SERVING = "serving"
    INTERACTIVE = "interactive"


class MetricSecurityClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MetricNullPolicy(StrEnum):
    IGNORE = "ignore"
    ZERO = "zero"
    ERROR = "error"


class MetricDistinctPolicy(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    EXACT = "exact"
    APPROXIMATE = "approximate"


class MetricSourceBinding(_FrozenContract):
    product_urn: ResourceURNText
    data_product_version_id: UUID
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    output_resource_version_id: UUID

    @model_validator(mode="after")
    def _valid_product_identity(self) -> MetricSourceBinding:
        identity = parse_resource_urn(self.product_urn)
        if identity["resource_kind"] != "data_product":
            raise ValueError("metric source must reference a data_product")
        return self


class MetricMeasureBinding(_FrozenContract):
    binding_name: MetricName
    semantic_model_version_ref: ResourceURNText
    measure_name: MetricName

    @field_validator("semantic_model_version_ref")
    @classmethod
    def _semantic_model_ref(cls, value: str) -> str:
        identity = parse_resource_urn(value)
        if identity["resource_kind"] != "semantic_model" or not re.search(
            r"\.v[1-9][0-9]*$", value
        ):
            raise ValueError("measure must reference an immutable semantic model version")
        return value


class MetricAggregationSemantics(_FrozenContract):
    kind: MetricAggregationKind
    non_additive_dimensions: tuple[DimensionName, ...] = ()

    @field_validator("non_additive_dimensions")
    @classmethod
    def _sorted_unique_dimensions(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("non-additive dimensions must be unique and sorted")
        return values

    @model_validator(mode="after")
    def _consistent_kind(self) -> MetricAggregationSemantics:
        if self.kind is MetricAggregationKind.ADDITIVE and self.non_additive_dimensions:
            raise ValueError("additive metrics cannot declare non-additive dimensions")
        if (
            self.kind is MetricAggregationKind.SEMI_ADDITIVE
            and not self.non_additive_dimensions
        ):
            raise ValueError("semi-additive metrics require non-additive dimensions")
        return self


class MetricTimeSemantics(_FrozenContract):
    dimension: DimensionName
    kind: MetricTimeKind
    grain: MetricTimeGrain
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("metric timezone must be a known IANA timezone") from exc
        return value


class MetricSpatialSemantics(_FrozenContract):
    dimension: DimensionName
    grain: MetricSpatialGrain
    crs: str = Field(pattern=r"^(EPSG|OGC):[A-Za-z0-9._-]{1,64}$")
    relationship: MetricSpatialRelationship
    area_unit: str | None = Field(default=None, min_length=1, max_length=32)


class MetricQualityPolicy(_FrozenContract):
    minimum_completeness_basis_points: int = Field(default=10_000, ge=0, le=10_000)
    maximum_freshness_lag_seconds: int | None = Field(
        default=None, ge=0, le=366 * 24 * 60 * 60
    )
    reconciliation_tolerance_ppm: int = Field(default=0, ge=0, le=1_000_000)
    required_checks: tuple[MetricName, ...] = ()

    @field_validator("required_checks")
    @classmethod
    def _sorted_unique_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("required quality checks must be unique and sorted")
        return values


class MetricMaterializationPolicy(_FrozenContract):
    mode: MetricMaterializationMode = MetricMaterializationMode.ON_DEMAND
    preferred_tier: MetricServingTier = MetricServingTier.INTERACTIVE
    cache_ttl_seconds: int = Field(default=0, ge=0, le=7 * 24 * 60 * 60)
    maximum_staleness_seconds: int = Field(
        default=0, ge=0, le=366 * 24 * 60 * 60
    )
    group_by_dimensions: tuple[DimensionName, ...] = ()

    @field_validator("group_by_dimensions")
    @classmethod
    def _sorted_unique_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("materialization dimensions must be unique and sorted")
        return values


class MetricDefinitionDocument(_FrozenContract):
    schema_id: Literal["gda.metric_definition.v1"] = "gda.metric_definition.v1"
    canonical_name: MetricName
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    description: NonEmptyText
    aliases: tuple[str, ...] = ()
    domain: MetricName
    semantic_model_version_ref: ResourceURNText
    formula_language: Literal["semantic_expression_v1"] = "semantic_expression_v1"
    formula_expression: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
    ]
    value_type: MetricValueType
    unit: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    aggregation: MetricAggregationSemantics
    time_semantics: MetricTimeSemantics | None = None
    spatial_semantics: MetricSpatialSemantics | None = None
    dimensions: tuple[DimensionName, ...]
    measures: tuple[MetricMeasureBinding, ...]
    source_bindings: tuple[MetricSourceBinding, ...]
    dependency_version_refs: tuple[ResourceURNText, ...] = ()
    null_policy: MetricNullPolicy = MetricNullPolicy.IGNORE
    distinct_policy: MetricDistinctPolicy = MetricDistinctPolicy.NOT_APPLICABLE
    quality_policy: MetricQualityPolicy = Field(default_factory=MetricQualityPolicy)
    materialization_policy: MetricMaterializationPolicy = Field(
        default_factory=MetricMaterializationPolicy
    )
    security_classification: MetricSecurityClassification = (
        MetricSecurityClassification.INTERNAL
    )
    owner_subject: str
    steward_subject: str

    @field_validator("semantic_model_version_ref")
    @classmethod
    def _semantic_model_version(cls, value: str) -> str:
        identity = parse_resource_urn(value)
        if identity["resource_kind"] != "semantic_model" or not re.search(
            r"\.v[1-9][0-9]*$", value
        ):
            raise ValueError("metric must reference an immutable semantic model version")
        return value

    @field_validator("formula_expression")
    @classmethod
    def _semantic_expression_only(cls, value: str) -> str:
        if "\x00" in value or ";" in value:
            raise ValueError("semantic metric expressions cannot contain statements")
        return value

    @field_validator("aliases")
    @classmethod
    def _sorted_unique_aliases(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 256 for value in normalized):
            raise ValueError("metric aliases must be non-empty and bounded")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("metric aliases must be unique")
        if tuple(sorted(normalized, key=str.casefold)) != tuple(normalized):
            raise ValueError("metric aliases must be sorted")
        return tuple(normalized)

    @field_validator("dimensions")
    @classmethod
    def _sorted_unique_dimensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("metric dimensions must be unique and sorted")
        return values

    @field_validator("measures")
    @classmethod
    def _sorted_unique_measures(
        cls, values: tuple[MetricMeasureBinding, ...]
    ) -> tuple[MetricMeasureBinding, ...]:
        names = tuple(item.binding_name for item in values)
        if not values or tuple(sorted(set(names))) != names:
            raise ValueError("metric measure bindings must be non-empty, unique and sorted")
        return values

    @field_validator("source_bindings")
    @classmethod
    def _sorted_unique_sources(
        cls, values: tuple[MetricSourceBinding, ...]
    ) -> tuple[MetricSourceBinding, ...]:
        keys = tuple(
            (item.product_urn, item.version_key, str(item.data_product_version_id))
            for item in values
        )
        if not values or tuple(sorted(set(keys))) != keys:
            raise ValueError("metric source bindings must be non-empty, unique and sorted")
        return values

    @field_validator("dependency_version_refs")
    @classmethod
    def _sorted_unique_dependencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("metric dependencies must be unique and sorted")
        for value in values:
            identity = parse_resource_urn(value)
            if identity["resource_kind"] != "metric_definition" or not re.search(
                r"\.v[1-9][0-9]*$", value
            ):
                raise ValueError("metric dependencies must reference immutable versions")
        return values

    @field_validator("owner_subject", "steward_subject")
    @classmethod
    def _governance_subject(cls, value: str) -> str:
        if re.fullmatch(r"^(human|team):[^\s]{1,128}$", value) is None:
            raise ValueError("metric owner and steward must be human or team subjects")
        return value

    @model_validator(mode="after")
    def _consistent_semantics(self) -> MetricDefinitionDocument:
        dimensions = set(self.dimensions)
        if self.time_semantics and self.time_semantics.dimension not in dimensions:
            raise ValueError("metric time dimension must be declared in dimensions")
        if self.spatial_semantics and self.spatial_semantics.dimension not in dimensions:
            raise ValueError("metric spatial dimension must be declared in dimensions")
        if not set(self.aggregation.non_additive_dimensions) <= dimensions:
            raise ValueError("non-additive dimensions must be metric dimensions")
        if not set(self.materialization_policy.group_by_dimensions) <= dimensions:
            raise ValueError("materialization dimensions must be metric dimensions")
        if self.time_semantics and self.time_semantics.kind is MetricTimeKind.SNAPSHOT:
            if self.aggregation.kind is MetricAggregationKind.ADDITIVE:
                raise ValueError("snapshot metrics cannot be additive across time")
            if (
                self.aggregation.kind is MetricAggregationKind.SEMI_ADDITIVE
                and self.time_semantics.dimension
                not in self.aggregation.non_additive_dimensions
            ):
                raise ValueError("snapshot time must be a non-additive dimension")
        return self


class MetricDefinitionDraft(_FrozenContract):
    tenant_id: TenantId
    metric_ref: ResourceURNText
    metric_version_ref: ResourceURNText
    version: Annotated[int, Field(ge=1, le=1_000_000)]
    definition: MetricDefinitionDocument
    created_by: str
    creation_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
    ]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric created_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("created_by")
    @classmethod
    def _typed_creator(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("metric creator must use a typed subject")
        return value

    @model_validator(mode="after")
    def _consistent_identity(self) -> MetricDefinitionDraft:
        base = parse_resource_urn(self.metric_ref)
        version = parse_resource_urn(self.metric_version_ref)
        semantic_model = parse_resource_urn(self.definition.semantic_model_version_ref)
        if base["tenant_id"] != self.tenant_id or version["tenant_id"] != self.tenant_id:
            raise ValueError("metric identity tenant must match tenant_id")
        if base["resource_kind"] != "metric_definition" or version[
            "resource_kind"
        ] != "metric_definition":
            raise ValueError("metric identity must use resource kind 'metric_definition'")
        if self.metric_version_ref != f"{self.metric_ref}.v{self.version}":
            raise ValueError("metric version reference must bind identity and version")
        if semantic_model["tenant_id"] != self.tenant_id:
            raise ValueError("semantic model tenant must match metric tenant")
        for measure in self.definition.measures:
            identity = parse_resource_urn(measure.semantic_model_version_ref)
            if identity["tenant_id"] != self.tenant_id:
                raise ValueError("measure semantic model tenant must match metric tenant")
        for source in self.definition.source_bindings:
            identity = parse_resource_urn(source.product_urn)
            if identity["tenant_id"] != self.tenant_id:
                raise ValueError("data product tenant must match metric tenant")
        for dependency in self.definition.dependency_version_refs:
            identity = parse_resource_urn(dependency)
            if identity["tenant_id"] != self.tenant_id:
                raise ValueError("metric dependency tenant must match metric tenant")
            if dependency.startswith(f"{self.metric_ref}.v"):
                raise ValueError("metric versions cannot depend on their own metric identity")
        return self


class MetricDefinitionVersion(MetricDefinitionDraft):
    definition_fingerprint: Sha256


class MetricDefinitionActivation(_FrozenContract):
    tenant_id: TenantId
    metric_ref: ResourceURNText
    canonical_name: MetricName
    active_version_ref: ResourceURNText
    active_fingerprint: Sha256
    approval_case_ref: ResourceURNText
    activation_version: Annotated[int, Field(ge=1)]
    activated_by: str
    activation_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
    ]
    activated_at: datetime

    @field_validator("activated_at")
    @classmethod
    def _utc_activated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric activated_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("activated_by")
    @classmethod
    def _typed_activator(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("metric activator must use a typed subject")
        return value

    @model_validator(mode="after")
    def _consistent_activation_identity(self) -> MetricDefinitionActivation:
        metric = parse_resource_urn(self.metric_ref)
        version = parse_resource_urn(self.active_version_ref)
        approval = parse_resource_urn(self.approval_case_ref)
        if (
            metric["tenant_id"] != self.tenant_id
            or version["tenant_id"] != self.tenant_id
            or approval["tenant_id"] != self.tenant_id
        ):
            raise ValueError("metric activation identities must share the tenant")
        if metric["resource_kind"] != "metric_definition" or version[
            "resource_kind"
        ] != "metric_definition":
            raise ValueError("metric activation must reference metric definitions")
        if approval["resource_kind"] != "approval_case":
            raise ValueError("metric activation must reference an ApprovalCase")
        if not self.active_version_ref.startswith(f"{self.metric_ref}.v"):
            raise ValueError("metric activation version must belong to the metric")
        return self


class MetricDefinitionEvent(_FrozenContract):
    tenant_id: TenantId
    metric_event_id: UUID
    metric_ref: ResourceURNText
    metric_version_ref: ResourceURNText
    definition_fingerprint: Sha256
    event_type: Literal["staged", "activated"]
    approval_case_ref: ResourceURNText | None = None
    actor_subject: str
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
    ]
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric event time must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("actor_subject")
    @classmethod
    def _typed_actor(cls, value: str) -> str:
        if re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", value) is None:
            raise ValueError("metric event actor must use a typed subject")
        return value

    @model_validator(mode="after")
    def _approval_only_for_activation(self) -> MetricDefinitionEvent:
        if (self.event_type == "activated") != (self.approval_case_ref is not None):
            raise ValueError("only a metric activation event binds an ApprovalCase")
        metric = parse_resource_urn(self.metric_ref)
        version = parse_resource_urn(self.metric_version_ref)
        if metric["tenant_id"] != self.tenant_id or version[
            "tenant_id"
        ] != self.tenant_id:
            raise ValueError("metric event identities must share the tenant")
        if not self.metric_version_ref.startswith(f"{self.metric_ref}.v"):
            raise ValueError("metric event version must belong to the metric")
        if self.approval_case_ref is not None:
            approval = parse_resource_urn(self.approval_case_ref)
            if (
                approval["tenant_id"] != self.tenant_id
                or approval["resource_kind"] != "approval_case"
            ):
                raise ValueError("metric event ApprovalCase must share the tenant")
        return self


class MetricResolution(_FrozenContract):
    definition: MetricDefinitionVersion
    activation: MetricDefinitionActivation
    matched_by: Literal["canonical_name", "display_name", "alias"]


class MetricAuthorityError(RuntimeError):
    code = "metric_authority_error"


class MetricConflictError(MetricAuthorityError):
    code = "metric_conflict"


class MetricNotFoundError(MetricAuthorityError):
    code = "metric_not_found"


class MetricForbiddenError(MetricAuthorityError):
    code = "metric_forbidden"


class MetricValidationError(MetricAuthorityError):
    code = "metric_validation_error"


class MetricConfigurationError(MetricAuthorityError):
    code = "metric_authority_unavailable"


class MetricQueryCompilationError(ValueError):
    """A query cannot compile without an exact active metric contract."""


@dataclass(frozen=True)
class MetricDefinitionVersionPage:
    items: tuple[MetricDefinitionVersion, ...]
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


def _validate_metric_ref(tenant_id: str, metric_ref: str) -> None:
    identity = parse_resource_urn(metric_ref)
    if identity["tenant_id"] != tenant_id or identity["resource_kind"] != "metric_definition":
        raise ValueError("metric definition identity does not match the tenant")


class MetricDefinitionAuthority:
    """PostgreSQL authority for immutable metric versions and active pointers."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise MetricConfigurationError("metric authority requires PostgreSQL")
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
                        raise MetricConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except MetricAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise MetricConflictError("metric authority state conflict") from exc
            if state == "P0002":
                raise MetricNotFoundError("metric definition was not found") from exc
            if state == "42501":
                raise MetricForbiddenError("metric tenant access was denied") from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise MetricValidationError("metric authority contract was rejected") from exc
            raise MetricAuthorityError("metric database operation failed") from exc
        except SQLAlchemyError as exc:
            raise MetricAuthorityError("metric database operation failed") from exc

    @staticmethod
    def _definition_from_row(row: Any) -> MetricDefinitionVersion:
        value = dict(row)
        value["definition"] = _json_value(value.pop("definition_document"))
        return MetricDefinitionVersion.model_validate(value)

    @staticmethod
    def _activation_from_row(row: Any) -> MetricDefinitionActivation:
        return MetricDefinitionActivation.model_validate(dict(row))

    @staticmethod
    def _event_from_row(row: Any) -> MetricDefinitionEvent:
        value = dict(row)
        value["details"] = _json_value(value["details"])
        return MetricDefinitionEvent.model_validate(value)

    @classmethod
    def _load_definition(
        cls, connection: Any, tenant_id: str, metric_version_ref: str
    ) -> MetricDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, metric_ref, metric_version_ref,
                           definition_version AS version, definition_document,
                           definition_fingerprint, created_by,
                           creation_reason, created_at
                    FROM gda_control.metric_definition_version
                    WHERE tenant_id = :tenant_id
                      AND metric_version_ref = :metric_version_ref
                    """
                ),
                {"tenant_id": tenant_id, "metric_version_ref": metric_version_ref},
            )
            .mappings()
            .one_or_none()
        )
        return cls._definition_from_row(row) if row is not None else None

    def stage(self, draft: MetricDefinitionDraft) -> MetricDefinitionVersion:
        document = draft.definition.model_dump(mode="json")
        with self._transaction(draft.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.stage_metric_definition_version(
                        :tenant_id, :metric_ref, :metric_version_ref,
                        :definition_version, CAST(:definition_document AS jsonb),
                        :created_by, :creation_reason, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": draft.tenant_id,
                    "metric_ref": draft.metric_ref,
                    "metric_version_ref": draft.metric_version_ref,
                    "definition_version": draft.version,
                    "definition_document": _json(document),
                    "created_by": draft.created_by,
                    "creation_reason": draft.creation_reason,
                    "created_at": draft.created_at,
                },
            ).scalar_one()
            stored = self._load_definition(
                connection, draft.tenant_id, draft.metric_version_ref
            )
            if stored is None:
                raise MetricNotFoundError("staged metric definition was not visible")
            comparable = stored.model_dump(
                exclude={"definition_fingerprint", "created_at"}
            )
            if comparable != draft.model_dump(exclude={"created_at"}):
                raise MetricConflictError("metric version identity has different evidence")
            return stored

    def get(self, tenant_id: str, metric_version_ref: str) -> MetricDefinitionVersion:
        _validate_metric_ref(tenant_id, metric_version_ref)
        with self._transaction(tenant_id) as connection:
            stored = self._load_definition(connection, tenant_id, metric_version_ref)
            if stored is None:
                raise MetricNotFoundError("metric definition was not found")
            return stored

    def list_versions(
        self,
        tenant_id: str,
        metric_ref: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> MetricDefinitionVersionPage:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        _validate_metric_ref(tenant, metric_ref)
        if not 1 <= limit <= 100:
            raise ValueError("metric version query limit must be between 1 and 100")
        if not 0 <= offset <= 10_000:
            raise ValueError("metric version query offset must be between 0 and 10000")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, metric_ref, metric_version_ref,
                               definition_version AS version, definition_document,
                               definition_fingerprint, created_by,
                               creation_reason, created_at
                        FROM gda_control.metric_definition_version
                        WHERE tenant_id = :tenant_id AND metric_ref = :metric_ref
                        ORDER BY definition_version DESC, metric_version_ref DESC
                        LIMIT :row_limit OFFSET :offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "metric_ref": metric_ref,
                        "row_limit": limit + 1,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        return MetricDefinitionVersionPage(
            items=tuple(self._definition_from_row(row) for row in rows[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    def activate(
        self,
        *,
        tenant_id: str,
        metric_version_ref: str,
        definition_fingerprint: str,
        approval_case_ref: str,
        expected_activation_version: int,
        actor_subject: str,
        reason: str,
    ) -> MetricDefinitionActivation:
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.activate_metric_definition_version(
                        :tenant_id, :metric_version_ref, :definition_fingerprint,
                        :approval_case_ref, :expected_activation_version,
                        :actor_subject, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "metric_version_ref": metric_version_ref,
                    "definition_fingerprint": definition_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "expected_activation_version": expected_activation_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                },
            ).scalar_one()
            definition = self._load_definition(connection, tenant_id, metric_version_ref)
            if definition is None:
                raise MetricNotFoundError("activated metric definition was not visible")
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, metric_ref, canonical_name,
                               active_version_ref, active_fingerprint,
                               approval_case_ref, activation_version,
                               activated_by, activation_reason, activated_at
                        FROM gda_control.metric_definition_activation
                        WHERE tenant_id = :tenant_id AND metric_ref = :metric_ref
                        """
                    ),
                    {"tenant_id": tenant_id, "metric_ref": definition.metric_ref},
                )
                .mappings()
                .one()
            )
            return self._activation_from_row(row)

    def active(
        self, tenant_id: str, metric_ref: str
    ) -> tuple[MetricDefinitionVersion, MetricDefinitionActivation]:
        _validate_metric_ref(tenant_id, metric_ref)
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, metric_ref, canonical_name,
                               active_version_ref, active_fingerprint,
                               approval_case_ref, activation_version,
                               activated_by, activation_reason, activated_at
                        FROM gda_control.metric_definition_activation
                        WHERE tenant_id = :tenant_id AND metric_ref = :metric_ref
                        """
                    ),
                    {"tenant_id": tenant_id, "metric_ref": metric_ref},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise MetricNotFoundError("active metric definition was not found")
            activation = self._activation_from_row(row)
            definition = self._load_definition(
                connection, tenant_id, activation.active_version_ref
            )
            if definition is None:
                raise MetricNotFoundError("active metric version was not found")
            return definition, activation

    def resolve_active(
        self, tenant_id: str, name: str, *, domain: str | None = None
    ) -> MetricResolution:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        query_name = name.strip()
        if not query_name or len(query_name) > 256:
            raise ValueError("metric resolution name must be non-empty and bounded")
        if domain is not None:
            if re.fullmatch(r"^[a-z][a-z0-9_]{0,127}$", domain) is None:
                raise ValueError("metric resolution domain is invalid")
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT v.tenant_id, v.metric_ref, v.metric_version_ref,
                               v.definition_version AS version,
                               v.definition_document, v.definition_fingerprint,
                               v.created_by, v.creation_reason, v.created_at,
                               a.canonical_name, a.active_version_ref,
                               a.active_fingerprint, a.approval_case_ref,
                               a.activation_version, a.activated_by,
                               a.activation_reason, a.activated_at,
                               CASE
                                   WHEN lower(
                                       v.definition_document->>'canonical_name'
                                   ) = lower(:name)
                                       THEN 'canonical_name'
                                   WHEN lower(v.definition_document->>'display_name') = lower(:name)
                                       THEN 'display_name'
                                   ELSE 'alias'
                               END AS matched_by
                        FROM gda_control.metric_definition_activation a
                        JOIN gda_control.metric_definition_version v
                          ON v.tenant_id = a.tenant_id
                         AND v.metric_version_ref = a.active_version_ref
                         AND v.definition_fingerprint = a.active_fingerprint
                        WHERE a.tenant_id = :tenant_id
                          AND (:domain IS NULL OR v.definition_document->>'domain' = :domain)
                          AND (
                              lower(v.definition_document->>'canonical_name') = lower(:name)
                              OR lower(v.definition_document->>'display_name') = lower(:name)
                              OR EXISTS (
                                  SELECT 1
                                  FROM jsonb_array_elements_text(
                                      v.definition_document->'aliases'
                                  ) AS alias(value)
                                  WHERE lower(alias.value) = lower(:name)
                              )
                          )
                        ORDER BY CASE
                            WHEN lower(v.definition_document->>'canonical_name')
                                = lower(:name) THEN 0
                            WHEN lower(v.definition_document->>'display_name')
                                = lower(:name) THEN 1
                            ELSE 2
                        END, v.metric_ref
                        LIMIT 3
                        """
                    ),
                    {"tenant_id": tenant, "name": query_name, "domain": domain},
                )
                .mappings()
                .all()
            )
        if not rows:
            raise MetricNotFoundError("active metric could not be resolved")
        best_rank = rows[0]["matched_by"]
        best = [row for row in rows if row["matched_by"] == best_rank]
        if len(best) != 1:
            raise MetricConflictError("metric name or alias resolves ambiguously")
        row = dict(best[0])
        matched_by = row.pop("matched_by")
        activation_fields = {
            key: row.pop(key)
            for key in (
                "tenant_id",
                "metric_ref",
                "canonical_name",
                "active_version_ref",
                "active_fingerprint",
                "approval_case_ref",
                "activation_version",
                "activated_by",
                "activation_reason",
                "activated_at",
            )
        }
        definition_fields = {
            "tenant_id": activation_fields["tenant_id"],
            "metric_ref": activation_fields["metric_ref"],
            **row,
        }
        return MetricResolution(
            definition=self._definition_from_row(definition_fields),
            activation=self._activation_from_row(activation_fields),
            matched_by=matched_by,
        )

    def events(
        self, tenant_id: str, metric_ref: str
    ) -> tuple[MetricDefinitionEvent, ...]:
        _validate_metric_ref(tenant_id, metric_ref)
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, metric_event_id, metric_ref,
                               metric_version_ref, definition_fingerprint,
                               event_type, approval_case_ref, actor_subject,
                               reason, details, occurred_at
                        FROM gda_control.metric_definition_event
                        WHERE tenant_id = :tenant_id AND metric_ref = :metric_ref
                        ORDER BY occurred_at, metric_event_id
                        """
                    ),
                    {"tenant_id": tenant_id, "metric_ref": metric_ref},
                )
                .mappings()
                .all()
            )
            return tuple(self._event_from_row(row) for row in rows)


def require_active_metric(
    definition: MetricDefinitionVersion,
    activation: MetricDefinitionActivation | None,
) -> None:
    """Fail closed unless an activation binds the exact immutable definition."""

    if activation is None:
        raise MetricQueryCompilationError("metric definition is not active")
    if (
        activation.tenant_id != definition.tenant_id
        or activation.metric_ref != definition.metric_ref
        or activation.canonical_name != definition.definition.canonical_name
        or activation.active_version_ref != definition.metric_version_ref
        or activation.active_fingerprint != definition.definition_fingerprint
    ):
        raise MetricQueryCompilationError(
            "metric activation does not bind this exact definition"
        )
