"""Deterministic governed metric query planning without LLM-authored SQL."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .metric_authority import (
    DimensionName,
    MetricAggregationKind,
    MetricDefinitionAuthority,
    MetricDefinitionVersion,
    MetricTimeGrain,
    require_active_metric,
)
from .metric_projection_authority import (
    ActiveMetricProjection,
    MetricProjectionAuthority,
    MetricProjectionEngine,
    MetricProjectionTier,
)
from .platform_contracts import Sha256, TenantId, canonical_json_fingerprint

QueryScalar = str | int | float | bool
PurposeText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$",
    ),
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricFilterOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    BETWEEN = "between"


class MetricDimensionFilter(_FrozenContract):
    dimension: DimensionName
    operator: MetricFilterOperator
    values: tuple[QueryScalar, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _consistent_arity(self) -> MetricDimensionFilter:
        expected = {
            MetricFilterOperator.EQ: 1,
            MetricFilterOperator.BETWEEN: 2,
        }.get(self.operator)
        if expected is not None and len(self.values) != expected:
            raise ValueError(f"{self.operator} filter requires {expected} value(s)")
        canonical = sorted(
            self.values,
            key=lambda value: (type(value).__name__, repr(value)),
        )
        if self.operator is MetricFilterOperator.IN and list(self.values) != canonical:
            raise ValueError("in-filter values must be sorted")
        return self


class MetricTimeRange(_FrozenContract):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query time range must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _ordered(self) -> MetricTimeRange:
        if self.end <= self.start:
            raise ValueError("metric query time range end must be after start")
        return self


class MetricSpatialFilter(_FrozenContract):
    bbox: tuple[float, float, float, float]
    crs: str = Field(pattern=r"^(EPSG|OGC):[A-Za-z0-9._-]{1,64}$")

    @model_validator(mode="after")
    def _ordered(self) -> MetricSpatialFilter:
        min_x, min_y, max_x, max_y = self.bbox
        if min_x >= max_x or min_y >= max_y:
            raise ValueError("metric spatial bbox must have increasing bounds")
        return self


class MetricQueryRequest(_FrozenContract):
    metric_name: str = Field(min_length=1, max_length=256)
    domain: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$"
    )
    group_by_dimensions: tuple[DimensionName, ...] = ()
    filters: tuple[MetricDimensionFilter, ...] = ()
    time_range: MetricTimeRange | None = None
    time_grain: MetricTimeGrain | None = None
    spatial_filter: MetricSpatialFilter | None = None
    maximum_staleness_seconds: int | None = Field(
        default=None, ge=0, le=366 * 24 * 60 * 60
    )
    maximum_latency_ms: int = Field(default=2_000, ge=1, le=86_400_000)
    allow_async: bool = True

    @field_validator("group_by_dimensions")
    @classmethod
    def _sorted_unique_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("query grouping dimensions must be unique and sorted")
        return values

    @field_validator("filters")
    @classmethod
    def _sorted_unique_filters(
        cls, values: tuple[MetricDimensionFilter, ...]
    ) -> tuple[MetricDimensionFilter, ...]:
        dimensions = tuple(item.dimension for item in values)
        if tuple(sorted(set(dimensions))) != dimensions:
            raise ValueError("query filters must have unique sorted dimensions")
        return values

    @model_validator(mode="after")
    def _time_grain_requires_grouping(self) -> MetricQueryRequest:
        if self.time_grain is not None and not self.group_by_dimensions:
            raise ValueError("query time grain requires a grouped time dimension")
        return self


class MetricQuerySecurityContext(_FrozenContract):
    tenant_id: TenantId
    subject_ref: str = Field(
        pattern=r"^(human|workload|agent):[^\s]{1,128}$"
    )
    roles: tuple[str, ...] = ()
    purpose: PurposeText = "metric_query"

    @field_validator("roles")
    @classmethod
    def _sorted_unique_roles(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value or len(value) > 128 for value in normalized):
            raise ValueError("query security roles must be non-empty and bounded")
        if tuple(sorted(set(normalized))) != normalized:
            raise ValueError("query security roles must be unique and sorted")
        return normalized


class MetricPhysicalFilter(_FrozenContract):
    dimension: DimensionName
    column: str
    operator: MetricFilterOperator
    values: tuple[QueryScalar, ...]


class MetricPhysicalTimeRange(_FrozenContract):
    column: str
    start: datetime
    end: datetime
    grain: MetricTimeGrain


class MetricPhysicalSpatialFilter(_FrozenContract):
    geometry_column: str
    geometry_srid: int
    bbox: tuple[float, float, float, float]
    crs: str
    relationship: str


class MetricPhysicalIntent(_FrozenContract):
    relation_ref: str
    value_column: str
    group_by_columns: tuple[str, ...]
    filters: tuple[MetricPhysicalFilter, ...]
    time_range: MetricPhysicalTimeRange | None = None
    spatial_filter: MetricPhysicalSpatialFilter | None = None
    rollup_operator: Literal["none", "sum"]


class MetricQueryPlan(_FrozenContract):
    schema_id: Literal["gda.metric_query_plan.v1"] = "gda.metric_query_plan.v1"
    tenant_id: TenantId
    metric_ref: str
    metric_version_ref: str
    metric_fingerprint: Sha256
    projection_ref: str
    projection_version_ref: str
    projection_fingerprint: Sha256
    data_product_version_id: str
    output_resource_version_id: str
    source_manifest_sha256: Sha256
    source_snapshot_ref: str
    engine: MetricProjectionEngine
    serving_tier: MetricProjectionTier
    execution_mode: Literal["synchronous", "asynchronous"]
    physical_intent: MetricPhysicalIntent
    estimated_rows: int
    projection_age_seconds: int
    security_context_fingerprint: Sha256
    cache_key: Sha256
    cache_ttl_seconds: int
    reasons: tuple[str, ...]
    planned_at: datetime


class MetricQueryPlanningError(RuntimeError):
    code = "metric_query_unplannable"

    def __init__(self, message: str, *, rejections: tuple[str, ...] = ()):
        super().__init__(message)
        self.rejections = rejections


_TIME_GRAIN_RANK = {
    MetricTimeGrain.MINUTE: 0,
    MetricTimeGrain.HOUR: 1,
    MetricTimeGrain.DAY: 2,
    MetricTimeGrain.WEEK: 3,
    MetricTimeGrain.MONTH: 4,
    MetricTimeGrain.QUARTER: 5,
    MetricTimeGrain.YEAR: 6,
}
_TIER_RANK = {
    MetricProjectionTier.SERVING: 0,
    MetricProjectionTier.INTERACTIVE: 1,
    MetricProjectionTier.GOLD: 2,
    MetricProjectionTier.BATCH: 3,
}


class MetricQueryPlanner:
    """Select one exact projection and return a replayable physical intent."""

    def __init__(
        self,
        metric_authority: MetricDefinitionAuthority | None = None,
        projection_authority: MetricProjectionAuthority | None = None,
        *,
        synchronous_row_limit: int = 1_000_000,
    ):
        if synchronous_row_limit < 1:
            raise ValueError("synchronous row limit must be positive")
        self._metrics = metric_authority or MetricDefinitionAuthority()
        self._projections = projection_authority or MetricProjectionAuthority()
        self._synchronous_row_limit = synchronous_row_limit

    def plan(
        self,
        request: MetricQueryRequest,
        security: MetricQuerySecurityContext,
        *,
        now: datetime | None = None,
    ) -> MetricQueryPlan:
        resolution = self._metrics.resolve_active(
            security.tenant_id, request.metric_name, domain=request.domain
        )
        require_active_metric(resolution.definition, resolution.activation)
        projections = self._projections.active_for_metric(
            security.tenant_id,
            resolution.definition.metric_version_ref,
            resolution.definition.definition_fingerprint,
        )
        return self.plan_from(
            request,
            security,
            resolution.definition,
            projections,
            now=now,
        )

    def plan_from(
        self,
        request: MetricQueryRequest,
        security: MetricQuerySecurityContext,
        metric: MetricDefinitionVersion,
        projections: tuple[ActiveMetricProjection, ...],
        *,
        now: datetime | None = None,
    ) -> MetricQueryPlan:
        planned_at = (now or datetime.now(UTC)).astimezone(UTC)
        if metric.tenant_id != security.tenant_id:
            raise MetricQueryPlanningError("metric query tenant does not match definition")
        definition = metric.definition
        declared_dimensions = set(definition.dimensions)
        requested_dimensions = set(request.group_by_dimensions)
        requested_dimensions.update(item.dimension for item in request.filters)
        if request.time_range is not None:
            if definition.time_semantics is None:
                raise MetricQueryPlanningError("metric has no governed time semantics")
            requested_dimensions.add(definition.time_semantics.dimension)
        if request.spatial_filter is not None:
            if definition.spatial_semantics is None:
                raise MetricQueryPlanningError("metric has no governed spatial semantics")
            requested_dimensions.add(definition.spatial_semantics.dimension)
        unknown = sorted(requested_dimensions - declared_dimensions)
        if unknown:
            raise MetricQueryPlanningError(
                "query references dimensions outside the active metric",
                rejections=tuple(f"unknown_dimension:{item}" for item in unknown),
            )
        if request.time_grain is not None:
            time_dimension = (
                definition.time_semantics.dimension
                if definition.time_semantics is not None
                else None
            )
            if time_dimension not in request.group_by_dimensions:
                raise MetricQueryPlanningError(
                    "query time grain requires the governed time dimension in group_by"
                )

        eligible: list[tuple[tuple[Any, ...], ActiveMetricProjection, int, str]] = []
        rejections: list[str] = []
        for active in projections:
            reason = self._incompatibility_reason(
                request, metric, active, planned_at, requested_dimensions
            )
            if reason is not None:
                rejections.append(f"{active.version.projection_ref}:{reason}")
                continue
            projection = active.version.projection
            is_async = projection.engine is MetricProjectionEngine.ICEBERG_SPARK
            if is_async and not request.allow_async:
                rejections.append(
                    f"{active.version.projection_ref}:asynchronous_execution_disabled"
                )
                continue
            if not is_async and projection.estimated_rows > self._synchronous_row_limit:
                rejections.append(
                    f"{active.version.projection_ref}:synchronous_scan_limit_exceeded"
                )
                continue
            age = max(0, int((planned_at - projection.refreshed_at).total_seconds()))
            score = (
                1 if is_async else 0,
                _TIER_RANK[projection.serving_tier],
                projection.p95_latency_ms,
                projection.estimated_rows,
                active.version.projection_ref,
            )
            eligible.append((score, active, age, "asynchronous" if is_async else "synchronous"))

        if not eligible:
            raise MetricQueryPlanningError(
                "no active metric projection satisfies query semantics and SLO",
                rejections=tuple(sorted(rejections)),
            )
        _, selected, age_seconds, execution_mode = min(eligible, key=lambda item: item[0])
        return self._build_plan(
            request,
            security,
            metric,
            selected,
            age_seconds,
            execution_mode,
            planned_at,
        )

    def _incompatibility_reason(
        self,
        request: MetricQueryRequest,
        metric: MetricDefinitionVersion,
        active: ActiveMetricProjection,
        now: datetime,
        requested_dimensions: set[str],
    ) -> str | None:
        projection = active.version.projection
        if (
            projection.metric_version_ref != metric.metric_version_ref
            or projection.metric_fingerprint != metric.definition_fingerprint
        ):
            return "metric_version_mismatch"
        projection_dimensions = set(projection.projection_dimensions)
        if not requested_dimensions <= projection_dimensions:
            return "projection_grain_missing_dimension"

        equality_dimensions = {
            item.dimension
            for item in request.filters
            if item.operator is MetricFilterOperator.EQ
        }
        preserved_dimensions = set(request.group_by_dimensions) | equality_dimensions
        rolled_up_dimensions = projection_dimensions - preserved_dimensions
        aggregation = metric.definition.aggregation
        if aggregation.kind is MetricAggregationKind.NON_ADDITIVE and rolled_up_dimensions:
            return "non_additive_rollup_forbidden"
        if aggregation.kind is MetricAggregationKind.SEMI_ADDITIVE and (
            rolled_up_dimensions & set(aggregation.non_additive_dimensions)
        ):
            return "semi_additive_rollup_crosses_non_additive_dimension"

        time_semantics = metric.definition.time_semantics
        if time_semantics is not None and time_semantics.dimension in projection_dimensions:
            if projection.time_column is None or projection.time_grain is None:
                return "projection_time_binding_missing"
            requested_grain = request.time_grain or time_semantics.grain
            projected_grain = MetricTimeGrain(projection.time_grain)
            if _TIME_GRAIN_RANK[projected_grain] > _TIME_GRAIN_RANK[requested_grain]:
                return "projection_time_grain_is_too_coarse"
            if (
                projected_grain != requested_grain
                and aggregation.kind is not MetricAggregationKind.ADDITIVE
            ):
                return "non_additive_time_rollup_forbidden"

        if request.spatial_filter is not None:
            spatial = metric.definition.spatial_semantics
            if spatial is None:
                return "metric_spatial_semantics_missing"
            if (
                projection.geometry_column is None
                or projection.geometry_srid is None
                or projection.geometry_crs is None
            ):
                return "projection_geometry_binding_missing"
            if (
                request.spatial_filter.crs != spatial.crs
                or projection.geometry_crs != spatial.crs
            ):
                return "spatial_crs_mismatch"

        policy_staleness = metric.definition.materialization_policy.maximum_staleness_seconds
        allowed_staleness = policy_staleness
        if request.maximum_staleness_seconds is not None:
            allowed_staleness = min(
                allowed_staleness, request.maximum_staleness_seconds
            )
        age_seconds = max(0, int((now - projection.refreshed_at).total_seconds()))
        if age_seconds > allowed_staleness:
            return "projection_stale"
        if (
            projection.engine is not MetricProjectionEngine.ICEBERG_SPARK
            and projection.p95_latency_ms > request.maximum_latency_ms
        ):
            return "interactive_latency_slo_exceeded"
        return None

    @staticmethod
    def _build_plan(
        request: MetricQueryRequest,
        security: MetricQuerySecurityContext,
        metric: MetricDefinitionVersion,
        selected: ActiveMetricProjection,
        age_seconds: int,
        execution_mode: str,
        planned_at: datetime,
    ) -> MetricQueryPlan:
        projection = selected.version.projection
        definition = metric.definition
        filters = tuple(
            MetricPhysicalFilter(
                dimension=item.dimension,
                column=projection.dimension_columns[item.dimension],
                operator=item.operator,
                values=item.values,
            )
            for item in request.filters
        )
        time_range = None
        if request.time_range is not None:
            assert definition.time_semantics is not None
            assert projection.time_column is not None
            time_range = MetricPhysicalTimeRange(
                column=projection.time_column,
                start=request.time_range.start,
                end=request.time_range.end,
                grain=request.time_grain or definition.time_semantics.grain,
            )
        spatial_filter = None
        if request.spatial_filter is not None:
            assert definition.spatial_semantics is not None
            assert projection.geometry_column is not None
            assert projection.geometry_srid is not None
            spatial_filter = MetricPhysicalSpatialFilter(
                geometry_column=projection.geometry_column,
                geometry_srid=projection.geometry_srid,
                bbox=request.spatial_filter.bbox,
                crs=request.spatial_filter.crs,
                relationship=definition.spatial_semantics.relationship,
            )
        preserved = set(request.group_by_dimensions) | {
            item.dimension
            for item in request.filters
            if item.operator is MetricFilterOperator.EQ
        }
        rollup = "sum" if set(projection.projection_dimensions) - preserved else "none"
        physical_intent = MetricPhysicalIntent(
            relation_ref=projection.relation_ref,
            value_column=projection.value_column,
            group_by_columns=tuple(
                projection.dimension_columns[item]
                for item in request.group_by_dimensions
            ),
            filters=filters,
            time_range=time_range,
            spatial_filter=spatial_filter,
            rollup_operator=rollup,
        )
        security_context_fingerprint = canonical_json_fingerprint(
            security.model_dump(mode="json")
        )
        cache_evidence = {
            "schema": "gda.metric_query_cache_key.v1",
            "metric_version_ref": metric.metric_version_ref,
            "metric_fingerprint": metric.definition_fingerprint,
            "projection_version_ref": selected.version.projection_version_ref,
            "projection_fingerprint": selected.version.projection_fingerprint,
            "data_product_version_id": str(projection.data_product_version_id),
            "output_resource_version_id": str(projection.output_resource_version_id),
            "source_manifest_sha256": projection.source_manifest_sha256,
            "source_snapshot_ref": projection.source_snapshot_ref,
            "request": request.model_dump(mode="json"),
            "security_context_fingerprint": security_context_fingerprint,
        }
        cache_key = canonical_json_fingerprint(cache_evidence)
        return MetricQueryPlan(
            tenant_id=security.tenant_id,
            metric_ref=metric.metric_ref,
            metric_version_ref=metric.metric_version_ref,
            metric_fingerprint=metric.definition_fingerprint,
            projection_ref=selected.version.projection_ref,
            projection_version_ref=selected.version.projection_version_ref,
            projection_fingerprint=selected.version.projection_fingerprint,
            data_product_version_id=str(projection.data_product_version_id),
            output_resource_version_id=str(projection.output_resource_version_id),
            source_manifest_sha256=projection.source_manifest_sha256,
            source_snapshot_ref=projection.source_snapshot_ref,
            engine=projection.engine,
            serving_tier=projection.serving_tier,
            execution_mode=execution_mode,
            physical_intent=physical_intent,
            estimated_rows=projection.estimated_rows,
            projection_age_seconds=age_seconds,
            security_context_fingerprint=security_context_fingerprint,
            cache_key=cache_key,
            cache_ttl_seconds=definition.materialization_policy.cache_ttl_seconds,
            reasons=(
                "exact_active_metric_version",
                "exact_active_projection_version",
                "source_snapshot_bound",
                f"selected_{projection.serving_tier.value}_{execution_mode}",
            ),
            planned_at=planned_at,
        )
