"""Typed plans for governed semantic queries.

This module contains two deliberately separate paths.  The baseline SQL route
can derive observational ``ShadowSemanticPlanEvidence`` from SQL that already
passed the governed validator; that evidence never authorizes execution.  The
``semantic_ir_experimental`` route accepts a restricted ``AdHocSemanticQueryIR``
without physical identifiers and uses the validated Postgres/PostGIS compiler
to produce the executable statement.  Both paths share the same semantic
bindings, source admission and safety contracts.  The executable path remains
a canary because it does not yet cover every free-form capability.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import canonical_json_fingerprint


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticQueryRoute(StrEnum):
    REVIEWED_METRIC_CONTRACT = "reviewed_metric_contract"
    GOVERNED_SQL_AST = "governed_sql_ast"


class SemanticOperation(StrEnum):
    DETAIL = "detail"
    AGGREGATE = "aggregate"


class ProjectionRole(StrEnum):
    ATTRIBUTE = "attribute"
    DIMENSION = "dimension"
    METRIC = "metric"


class SemanticAggregate(StrEnum):
    """Aggregations supported by the first executable SemanticQueryIR slice."""

    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class SemanticDerivedMeasure(StrEnum):
    """Safe, compiler-owned geospatial measures for the initial IR slice."""

    AREA_SQUARE_METRES = "area_square_metres"
    AREA_SQUARE_KILOMETRES = "area_square_kilometres"


class PredicateKind(StrEnum):
    COMPARISON = "comparison"
    MEMBERSHIP = "membership"
    RANGE = "range"
    NULL_TEST = "null_test"
    BOOLEAN_TEST = "boolean_test"
    PATTERN = "pattern"
    COMPOSITE = "composite"


class JoinKind(StrEnum):
    EQUALITY = "equality"
    SPATIAL = "spatial"


class SpatialIntent(StrEnum):
    """User-facing spatial relationship intent carried by the model plan."""

    NONE = "none"
    CONTAINS = "contains"
    WITHIN = "within"
    INTERSECTS = "intersects"
    DISTANCE = "distance"


def infer_spatial_intent(question: str) -> SpatialIntent:
    """Infer only explicit spatial wording; ordinary relational wording stays none."""

    value = str(question or "").casefold()
    if re.search(
        r"(?:\b(?:near|nearest|within\s+\d+(?:\.\d+)?\s*(?:m|meter|meters|metre|metres|km|kilometer|kilometers|kilometre|kilometres))\b|"
        r"距离|附近|邻近|\b(?:بالقرب|مسافة|ضمن\s+مسافة)\b)",
        value,
    ):
        return SpatialIntent.DISTANCE
    if re.search(
        r"(?:\b(?:within|inside|contained|located\s+in|in\s+the\s+boundary)\b|"
        r"范围内|区域内|边界内|位于|包含于|在[^。！？,，]{0,12}(?:范围|区域|边界)内|"
        r"(?:داخل|ضمن|في\s+حدود|يقع\s+داخل))",
        value,
    ):
        return SpatialIntent.WITHIN
    if re.search(
        r"(?:\b(?:contains|covers|encloses)\b|包含|覆盖|包围|"
        r"(?:يحتوي|يغطي|يحيط))",
        value,
    ):
        return SpatialIntent.CONTAINS
    if re.search(
        r"(?:\b(?:intersect(?:s|ion)?|overlap(?:s|ping)?)\b|相交|重叠|交叠|"
        r"(?:يتقاطع|تداخل))",
        value,
    ):
        return SpatialIntent.INTERSECTS
    if re.search(r"(?:\bspatial\b|空间|空间范围|مكانية)", value):
        return SpatialIntent.INTERSECTS
    return SpatialIntent.NONE


class FederatedMergeStrategy(StrEnum):
    INDEPENDENT_SECTIONS = "independent_sections"


class SemanticTaskFrame(_FrozenModel):
    schema_id: Literal["gda.semantic_task_frame.v1"] = "gda.semantic_task_frame.v1"
    question_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Literal["zh", "en", "ar"]
    operation: SemanticOperation
    source_ids: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_sources(self) -> SemanticTaskFrame:
        if tuple(sorted(set(self.source_ids))) != self.source_ids:
            raise ValueError("task-frame source ids must be sorted and unique")
        return self


class SemanticSourceRef(_FrozenModel):
    source_id: int = Field(gt=0)
    source_name: str = Field(min_length=1, max_length=256)
    database_name: str = Field(min_length=1, max_length=256)
    authorized_schemas: tuple[str, ...] = Field(min_length=1)
    discovery_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    tables: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_scope(self) -> SemanticSourceRef:
        if tuple(sorted(set(self.authorized_schemas))) != self.authorized_schemas:
            raise ValueError("authorized schemas must be sorted and unique")
        if tuple(sorted(set(self.tables))) != self.tables:
            raise ValueError("source tables must be sorted and unique")
        return self


class SemanticFieldRef(_FrozenModel):
    table: str = Field(min_length=3, max_length=512)
    field: str = Field(min_length=1, max_length=256)


class SemanticModelFieldRef(_FrozenModel):
    """A logical field reference that a model may propose.

    The model only sees ``semantic_entity`` and ``semantic_field``.  The
    compiler resolves those stable semantic references to a reviewed physical
    binding after validation; physical table and column identifiers are not
    part of the model-facing contract.
    """

    semantic_entity: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    semantic_field: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )


class SemanticIRProjection(_FrozenModel):
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    role: ProjectionRole
    field_ref: SemanticModelFieldRef | None = None
    aggregate: SemanticAggregate | None = None
    derived_measure: SemanticDerivedMeasure | None = None

    @model_validator(mode="after")
    def _coherent_projection(self) -> SemanticIRProjection:
        if self.role is ProjectionRole.METRIC:
            if self.aggregate is None:
                raise ValueError("metric projection requires an aggregate")
            if self.aggregate is not SemanticAggregate.COUNT and self.field_ref is None:
                raise ValueError("non-count metric requires a semantic field")
            if self.derived_measure is not None:
                if self.field_ref is None:
                    raise ValueError("derived metric requires a semantic field")
                if self.aggregate in {
                    SemanticAggregate.COUNT,
                    SemanticAggregate.COUNT_DISTINCT,
                }:
                    raise ValueError(
                        "derived metric requires a numeric aggregate"
                    )
            return self
        if self.field_ref is None:
            raise ValueError("non-metric projection requires a semantic field")
        if self.aggregate is not None:
            raise ValueError("non-metric projection cannot define an aggregate")
        if self.derived_measure is not None:
            raise ValueError("non-metric projection cannot define a derived measure")
        return self


class SemanticFilter(_FrozenModel):
    field_ref: SemanticModelFieldRef
    operator: Literal[
        "eq",
        "neq",
        "in",
        "not_in",
        "gt",
        "gte",
        "lt",
        "lte",
        "contains",
        "prefix",
        "is_null",
        "not_null",
    ]
    values: tuple[str | int | float | bool, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def _coherent_values(self) -> SemanticFilter:
        null_tests = {"is_null", "not_null"}
        membership = {"in", "not_in"}
        if self.operator in null_tests and self.values:
            raise ValueError("null-test filter cannot carry values")
        if self.operator in membership and not self.values:
            raise ValueError("membership filter requires values")
        if self.operator not in null_tests | membership and len(self.values) != 1:
            raise ValueError("scalar filter requires exactly one value")
        return self


class SemanticAnyFilterGroup(_FrozenModel):
    """An OR group combined with ordinary filters and other groups by AND."""

    filters: tuple[SemanticFilter, ...] = Field(min_length=2, max_length=12)


class SemanticIROrder(_FrozenModel):
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    direction: Literal["asc", "desc"]


class SemanticIRJoin(_FrozenModel):
    """A model-authored logical relation that must match reviewed metadata."""

    left_field_ref: SemanticModelFieldRef
    right_field_ref: SemanticModelFieldRef
    kind: JoinKind
    operator: Literal[
        "eq",
        "st_covers",
        "st_contains",
        "st_dwithin",
        "st_within",
        "st_intersects",
    ]
    distance_metres: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _coherent_join(self) -> SemanticIRJoin:
        if self.left_field_ref.semantic_entity == self.right_field_ref.semantic_entity:
            raise ValueError("semantic IR join must connect two entities")
        if self.kind is JoinKind.EQUALITY and self.operator != "eq":
            raise ValueError("equality semantic IR join requires eq operator")
        if self.kind is JoinKind.SPATIAL and self.operator == "eq":
            raise ValueError("spatial semantic IR join requires spatial operator")
        if self.operator == "st_dwithin":
            if self.distance_metres is None or not math.isfinite(self.distance_metres):
                raise ValueError("st_dwithin join requires a finite distance_metres")
        elif self.distance_metres is not None:
            raise ValueError("distance_metres is supported only by st_dwithin")
        return self


class AdHocSemanticQueryIR(_FrozenModel):
    """Constrained, model-facing semantic query contract for the canary path.

    V1 begins with a small relational and PostGIS capability set. The model
    names only reviewed logical entities, fields, and relations; the compiler
    remains the sole authority for physical bindings and SQL construction.
    """

    schema_id: Literal["gda.ad_hoc_semantic_query_ir.v1"] = (
        "gda.ad_hoc_semantic_query_ir.v1"
    )
    language: Literal["zh", "en", "ar"]
    status: Literal["query", "unsupported"]
    semantic_entity: str | None = Field(
        default=None,
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    spatial_intent: SpatialIntent = SpatialIntent.NONE
    projections: tuple[SemanticIRProjection, ...] = Field(default=(), max_length=32)
    filters: tuple[SemanticFilter, ...] = Field(default=(), max_length=24)
    any_filter_groups: tuple[SemanticAnyFilterGroup, ...] = Field(default=(), max_length=8)
    joins: tuple[SemanticIRJoin, ...] = Field(default=(), max_length=4)
    order_by: tuple[SemanticIROrder, ...] = Field(default=(), max_length=8)
    distinct_rows: bool = False
    limit: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _coherent_query(self) -> AdHocSemanticQueryIR:
        if self.status == "unsupported":
            if any(
                (
                    self.semantic_entity,
                    self.spatial_intent is not SpatialIntent.NONE,
                    self.projections,
                    self.filters,
                    self.any_filter_groups,
                    self.joins,
                    self.order_by,
                    self.distinct_rows,
                    self.limit,
                )
            ):
                raise ValueError("unsupported semantic query must not contain a plan")
            if not self.reason:
                raise ValueError("unsupported semantic query requires a reason")
            return self
        if not self.semantic_entity or not self.projections:
            raise ValueError("query semantic IR requires an entity and projections")
        spatial_joins = [join for join in self.joins if join.kind is JoinKind.SPATIAL]
        if self.spatial_intent is not SpatialIntent.NONE and not spatial_joins:
            raise ValueError("spatial intent requires a spatial reviewed join")
        if self.spatial_intent is SpatialIntent.CONTAINS and not any(
            join.operator in {"st_covers", "st_contains"} for join in spatial_joins
        ):
            raise ValueError("contains spatial intent requires covers or contains")
        if self.spatial_intent is SpatialIntent.WITHIN and not any(
            join.operator in {"st_within", "st_covers", "st_contains", "st_intersects"}
            for join in spatial_joins
        ):
            raise ValueError(
                "within spatial intent requires a containment or reviewed contains-intersects operator"
            )
        if self.spatial_intent is SpatialIntent.INTERSECTS and not any(
            join.operator == "st_intersects" for join in spatial_joins
        ):
            raise ValueError("intersects spatial intent requires st_intersects")
        if self.spatial_intent is SpatialIntent.DISTANCE and not any(
            join.operator == "st_dwithin" for join in spatial_joins
        ):
            raise ValueError("distance spatial intent requires st_dwithin")
        output_names = [item.output_name.casefold() for item in self.projections]
        if len(output_names) != len(set(output_names)):
            raise ValueError("semantic IR projection aliases must be unique")
        field_refs = [
            item.field_ref
            for item in self.projections
            if item.field_ref is not None
        ] + [item.field_ref for item in self.filters] + [
            item.field_ref
            for group in self.any_filter_groups
            for item in group.filters
        ] + [
            field_ref
            for join in self.joins
            for field_ref in (join.left_field_ref, join.right_field_ref)
        ]
        entities = {item.semantic_entity for item in field_refs}
        # COUNT(*) intentionally has no field reference: the primary entity
        # itself is the semantic anchor.  Treating this projection as having
        # no referenced entity made valid single-table row-count questions fail
        # validation before the compiler could emit COUNT(*).
        if any(
            item.role is ProjectionRole.METRIC
            and item.aggregate is SemanticAggregate.COUNT
            and item.field_ref is None
            for item in self.projections
        ):
            entities.add(self.semantic_entity)
        if self.semantic_entity not in entities:
            raise ValueError("semantic IR primary entity must be referenced")
        if len(entities) > 1 and not self.joins:
            raise ValueError("semantic IR multiple entities require reviewed joins")
        joined_entities = {
            field_ref.semantic_entity
            for join in self.joins
            for field_ref in (join.left_field_ref, join.right_field_ref)
        }
        if any(entity != self.semantic_entity and entity not in joined_entities for entity in entities):
            raise ValueError("semantic IR entity is not connected by a reviewed join")
        connected = {self.semantic_entity}
        pending = list(self.joins)
        while pending:
            remaining: list[SemanticIRJoin] = []
            advanced = False
            for join in pending:
                left = join.left_field_ref.semantic_entity
                right = join.right_field_ref.semantic_entity
                if left in connected or right in connected:
                    connected.update((left, right))
                    advanced = True
                else:
                    remaining.append(join)
            if not advanced:
                raise ValueError("semantic IR join graph is disconnected")
            pending = remaining
        if not entities <= connected:
            raise ValueError("semantic IR entity is not connected by a reviewed join")
        projected_names = set(output_names)
        if any(item.output_name.casefold() not in projected_names for item in self.order_by):
            raise ValueError("semantic IR order must reference a projection alias")
        has_metric = any(item.role is ProjectionRole.METRIC for item in self.projections)
        if has_metric and any(item.role is ProjectionRole.ATTRIBUTE for item in self.projections):
            raise ValueError("aggregate semantic IR requires dimensions, not attributes")
        return self


class SemanticProjection(_FrozenModel):
    output_name: str = Field(min_length=1, max_length=256)
    role: ProjectionRole
    expression_kind: Literal["field", "aggregate", "derived", "literal"]
    aggregate: str | None = Field(default=None, max_length=64)
    source_fields: tuple[SemanticFieldRef, ...] = ()
    expression_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticPredicate(_FrozenModel):
    kind: PredicateKind
    operator: str = Field(min_length=1, max_length=64)
    source_fields: tuple[SemanticFieldRef, ...] = ()
    literal_count: int = Field(default=0, ge=0, le=1000)
    expression_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticJoin(_FrozenModel):
    kind: JoinKind
    operator: str = Field(min_length=1, max_length=64)
    source_fields: tuple[SemanticFieldRef, ...] = Field(min_length=2)
    expression_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticOrder(_FrozenModel):
    output_name: str | None = Field(default=None, max_length=256)
    direction: Literal["asc", "desc"]
    expression_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticQueryIR(_FrozenModel):
    schema_id: Literal["gda.semantic_query_ir.v1"] = "gda.semantic_query_ir.v1"
    route: SemanticQueryRoute
    semantic_version: str = Field(min_length=1, max_length=256)
    metric_contract_version: str | None = Field(default=None, max_length=256)
    metric_contract_id: str | None = Field(default=None, max_length=256)
    task_frame: SemanticTaskFrame
    sources: tuple[SemanticSourceRef, ...] = Field(min_length=1)
    operation: SemanticOperation
    projections: tuple[SemanticProjection, ...] = Field(min_length=1)
    predicates: tuple[SemanticPredicate, ...] = ()
    joins: tuple[SemanticJoin, ...] = ()
    group_expression_sha256s: tuple[str, ...] = ()
    order_by: tuple[SemanticOrder, ...] = ()
    result_limit: int = Field(ge=1, le=1_000_000)
    limit_enforcement: Literal["sql", "source_executor"]

    @model_validator(mode="after")
    def _consistent_contract_route(self) -> SemanticQueryIR:
        if (
            self.route is SemanticQueryRoute.REVIEWED_METRIC_CONTRACT
            and not self.metric_contract_id
        ):
            raise ValueError("reviewed metric route requires a contract id")
        if self.task_frame.operation is not self.operation:
            raise ValueError("task-frame and IR operations differ")
        if tuple(item.source_id for item in self.sources) != self.task_frame.source_ids:
            raise ValueError("task-frame and IR source scopes differ")
        output_names = [item.output_name.casefold() for item in self.projections]
        if len(output_names) != len(set(output_names)):
            raise ValueError("semantic projection aliases must be unique")
        return self


class ValidationCheck(_FrozenModel):
    check_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    passed: bool
    detail: str | None = Field(default=None, max_length=256)


class SemanticIRValidationReport(_FrozenModel):
    schema_id: Literal["gda.semantic_ir_validation.v1"] = "gda.semantic_ir_validation.v1"
    valid: bool
    ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[ValidationCheck, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()


class LogicalPlanNode(_FrozenModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    operator: Literal["scan", "join", "filter", "aggregate", "project", "sort", "limit"]
    input_node_ids: tuple[str, ...] = ()
    attributes: dict[str, Any] = Field(default_factory=dict)


class SemanticLogicalPlan(_FrozenModel):
    schema_id: Literal["gda.semantic_logical_plan.v1"] = "gda.semantic_logical_plan.v1"
    ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_node_id: str = Field(min_length=2, max_length=64)
    nodes: tuple[LogicalPlanNode, ...] = Field(min_length=1)


class SemanticPhysicalPlan(_FrozenModel):
    schema_id: Literal["gda.semantic_physical_plan.v1"] = "gda.semantic_physical_plan.v1"
    engine: Literal["postgresql_postgis"] = "postgresql_postgis"
    dialect: Literal["postgres"] = "postgres"
    compilation_mode: Literal[
        "reviewed_contract_shadow",
        "reviewed_contract_compiler",
        "validated_sql_ast_shadow",
        "compiled_semantic_ir_experimental",
    ]
    logical_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    statement_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ids: tuple[int, ...] = Field(min_length=1)
    tables: tuple[str, ...] = Field(min_length=1)
    columns: tuple[str, ...]
    spatial_operators: tuple[str, ...] = ()
    read_only: Literal[True] = True


class ShadowSemanticPlanEvidence(_FrozenModel):
    schema_id: Literal["gda.shadow_semantic_plan_evidence.v1"] = (
        "gda.shadow_semantic_plan_evidence.v1"
    )
    status: Literal["planned", "legacy_fallback"]
    execution_authority: Literal[False] = False
    semantic_ir: SemanticQueryIR | None = None
    validation: SemanticIRValidationReport | None = None
    logical_plan: SemanticLogicalPlan | None = None
    physical_plan: SemanticPhysicalPlan | None = None
    fingerprints: dict[str, str] = Field(default_factory=dict)
    fallback_reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _consistent_status(self) -> ShadowSemanticPlanEvidence:
        artifacts = (
            self.semantic_ir,
            self.validation,
            self.logical_plan,
            self.physical_plan,
        )
        if self.status == "planned" and any(item is None for item in artifacts):
            raise ValueError("planned shadow evidence requires every plan artifact")
        if self.status == "legacy_fallback" and not self.fallback_reason:
            raise ValueError("legacy fallback requires a reason")
        return self


class CertifiedMetricContractPlanEvidence(_FrozenModel):
    """Authoritative plan for a reviewed, server-side metric template.

    ``compiled_statement`` is intentionally produced only from the immutable
    reviewed contract.  Free-form model SQL must continue through the separate
    non-authoritative shadow evidence route until a semantic compiler can
    express and compile it end to end.
    """

    schema_id: Literal["gda.certified_metric_contract_plan.v1"] = (
        "gda.certified_metric_contract_plan.v1"
    )
    status: Literal["planned"] = "planned"
    execution_authority: Literal[True] = True
    authority: Literal["reviewed_metric_contract_template_compiler"] = (
        "reviewed_metric_contract_template_compiler"
    )
    semantic_ir: SemanticQueryIR
    validation: SemanticIRValidationReport
    logical_plan: SemanticLogicalPlan
    physical_plan: SemanticPhysicalPlan
    compiled_statement: str = Field(min_length=1)
    fingerprints: dict[str, str] = Field(default_factory=dict)


class CompiledAdHocSemanticPlanEvidence(_FrozenModel):
    """Executable evidence for the isolated SemanticQueryIR canary.

    ``semantic_ir`` contains no physical identifiers and is the only model
    authored input.  ``compiled_statement`` and its exact source binding are
    emitted after the semantic validator accepts the IR.
    """

    schema_id: Literal["gda.compiled_ad_hoc_semantic_plan.v1"] = (
        "gda.compiled_ad_hoc_semantic_plan.v1"
    )
    status: Literal["planned"] = "planned"
    execution_authority: Literal[True] = True
    authority: Literal["validated_semantic_ir_postgis_compiler_experimental"] = (
        "validated_semantic_ir_postgis_compiler_experimental"
    )
    semantic_ir: AdHocSemanticQueryIR
    validation: SemanticIRValidationReport
    logical_plan: SemanticLogicalPlan
    physical_plan: SemanticPhysicalPlan
    compiled_statement: str = Field(min_length=1)
    parameter_bindings: dict[str, str | int | float | bool] = Field(default_factory=dict)
    compiler_default_ordering: bool = False
    fingerprints: dict[str, str] = Field(default_factory=dict)


class FederatedMetricSubplanRef(_FrozenModel):
    source: str = Field(min_length=1, max_length=128)
    source_id: int = Field(gt=0)
    database_name: str = Field(min_length=1, max_length=256)
    semantic_version: str = Field(min_length=1, max_length=256)
    metric_contract_version: str = Field(min_length=1, max_length=256)
    metric_contract_id: str = Field(min_length=1, max_length=256)
    semantic_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_plan_status: Literal["planned"] = "planned"


class FederatedSemanticQueryIR(_FrozenModel):
    schema_id: Literal["gda.federated_semantic_query_ir.v1"] = (
        "gda.federated_semantic_query_ir.v1"
    )
    semantic_version: str = Field(min_length=1, max_length=256)
    federated_contract_id: str = Field(min_length=1, max_length=256)
    task_frame: SemanticTaskFrame
    subplans: tuple[FederatedMetricSubplanRef, ...] = Field(
        min_length=2,
        max_length=2,
    )
    merge_strategy: FederatedMergeStrategy = FederatedMergeStrategy.INDEPENDENT_SECTIONS
    cross_database_sql: Literal[False] = False
    cross_source_join: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_federated_scope(self) -> FederatedSemanticQueryIR:
        source_ids = tuple(item.source_id for item in self.subplans)
        if source_ids != self.task_frame.source_ids:
            raise ValueError("federated task-frame and subplan scopes differ")
        if len(set(item.source for item in self.subplans)) != len(self.subplans):
            raise ValueError("federated source aliases must be unique")
        if len(set(source_ids)) != len(self.subplans):
            raise ValueError("federated source ids must be unique")
        if self.task_frame.operation is not SemanticOperation.AGGREGATE:
            raise ValueError("independent-section federation requires aggregate subplans")
        return self


class FederatedIRValidationReport(_FrozenModel):
    schema_id: Literal["gda.federated_ir_validation.v1"] = (
        "gda.federated_ir_validation.v1"
    )
    valid: bool
    ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[ValidationCheck, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()


class FederatedLogicalPlanNode(_FrozenModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    operator: Literal["metric_contract_subplan", "independent_sections_merge"]
    input_node_ids: tuple[str, ...] = ()
    attributes: dict[str, Any] = Field(default_factory=dict)


class FederatedSemanticLogicalPlan(_FrozenModel):
    schema_id: Literal["gda.federated_semantic_logical_plan.v1"] = (
        "gda.federated_semantic_logical_plan.v1"
    )
    ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_node_id: str = Field(min_length=2, max_length=64)
    nodes: tuple[FederatedLogicalPlanNode, ...] = Field(min_length=3, max_length=3)


class FederatedApplicationPhysicalPlan(_FrozenModel):
    schema_id: Literal["gda.federated_application_physical_plan.v1"] = (
        "gda.federated_application_physical_plan.v1"
    )
    engine: Literal["gda_application_federation"] = "gda_application_federation"
    compilation_mode: Literal["reviewed_contract_application_merge"] = (
        "reviewed_contract_application_merge"
    )
    logical_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ids: tuple[int, ...] = Field(min_length=2, max_length=2)
    source_plan_sha256s: tuple[str, ...] = Field(min_length=2, max_length=2)
    merge_strategy: FederatedMergeStrategy
    cross_database_sql: Literal[False] = False
    cross_source_join: Literal[False] = False
    read_only: Literal[True] = True


class FederatedSemanticPlanEvidence(_FrozenModel):
    schema_id: Literal["gda.federated_semantic_plan_evidence.v1"] = (
        "gda.federated_semantic_plan_evidence.v1"
    )
    status: Literal["planned", "legacy_fallback"]
    execution_authority: Literal[False] = False
    semantic_ir: FederatedSemanticQueryIR | None = None
    validation: FederatedIRValidationReport | None = None
    logical_plan: FederatedSemanticLogicalPlan | None = None
    physical_plan: FederatedApplicationPhysicalPlan | None = None
    fingerprints: dict[str, str] = Field(default_factory=dict)
    fallback_reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _consistent_federated_status(self) -> FederatedSemanticPlanEvidence:
        artifacts = (
            self.semantic_ir,
            self.validation,
            self.logical_plan,
            self.physical_plan,
        )
        if self.status == "planned" and any(item is None for item in artifacts):
            raise ValueError("planned federated evidence requires every plan artifact")
        if self.status == "legacy_fallback" and not self.fallback_reason:
            raise ValueError("federated fallback requires a reason")
        return self


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expression_sha(expression: Any) -> str:
    return _sha256(expression.sql(dialect="postgres", pretty=False))


def _function_name(function: Any) -> str:
    from sqlglot import exp

    if isinstance(function, exp.Anonymous):
        return str(function.this or "").casefold()
    return str(function.key or "").casefold()


def _field_catalog(columns: tuple[str, ...]) -> tuple[dict[str, set[str]], dict[str, str]]:
    by_field: dict[str, set[str]] = {}
    canonical_tables: dict[str, str] = {}
    for value in columns:
        table, separator, field = value.rpartition(".")
        if not separator or not table or not field:
            continue
        canonical_tables[table.casefold()] = table
        by_field.setdefault(field.casefold(), set()).add(table)
    return by_field, canonical_tables


def _column_resolver(expression: Any, columns: tuple[str, ...]):
    from sqlglot import exp

    by_field, canonical_tables = _field_catalog(columns)
    aliases: dict[str, str] = {}
    for table in expression.find_all(exp.Table):
        if not table.db:
            continue
        full_name = f"{table.db}.{table.name}"
        canonical = canonical_tables.get(full_name.casefold(), full_name)
        aliases[str(table.alias_or_name).casefold()] = canonical
        aliases[str(table.name).casefold()] = canonical
        aliases[full_name.casefold()] = canonical

    def resolve_physical(
        column: Any,
        *,
        local_tables: set[str] | None = None,
    ) -> SemanticFieldRef | None:
        field = str(column.name or "")
        if not field or field == "*":
            return None
        qualifier = str(column.table or "").casefold()
        if qualifier:
            table = aliases.get(qualifier)
            if table and f"{table}.{field}" in columns:
                return SemanticFieldRef(table=table, field=field)
            return None
        candidates = sorted(by_field.get(field.casefold(), ()))
        if local_tables:
            candidates = [table for table in candidates if table in local_tables]
        if len(candidates) == 1:
            return SemanticFieldRef(table=candidates[0], field=field)
        return None

    # Preserve simple column lineage through CTE and derived-relation output
    # aliases. Multi-column derived expressions are intentionally not reduced
    # to one field; their component fields are recovered when the expression
    # itself is inspected.
    relation_lineage: dict[str, dict[str, SemanticFieldRef]] = {}
    for cte in expression.find_all(exp.CTE):
        relation_name = str(cte.alias_or_name or "").casefold()
        query = cte.this
        if not relation_name or query is None:
            continue
        local_tables = {
            canonical_tables.get(f"{table.db}.{table.name}".casefold(), "")
            for table in query.find_all(exp.Table)
            if table.db
        }
        local_tables.discard("")
        outputs: dict[str, SemanticFieldRef] = {}
        for projection in getattr(query, "expressions", ()) or ():
            output_name = str(projection.alias_or_name or "").casefold()
            body = projection.this if isinstance(projection, exp.Alias) else projection
            resolved = {
                (item.table, item.field): item
                for column in body.find_all(exp.Column)
                if (
                    item := resolve_physical(column, local_tables=local_tables)
                ) is not None
            }
            if isinstance(body, exp.Column):
                item = resolve_physical(body, local_tables=local_tables)
                if item is not None:
                    resolved[(item.table, item.field)] = item
            if output_name and len(resolved) == 1:
                outputs[output_name] = next(iter(resolved.values()))
        relation_lineage[relation_name] = outputs

    qualified_lineage: dict[str, dict[str, SemanticFieldRef]] = dict(relation_lineage)
    for table in expression.find_all(exp.Table):
        if table.db:
            continue
        relation_name = str(table.name or "").casefold()
        if relation_name in relation_lineage:
            qualified_lineage[str(table.alias_or_name or relation_name).casefold()] = (
                relation_lineage[relation_name]
            )

    def resolve(column: Any) -> SemanticFieldRef | None:
        field = str(column.name or "")
        qualifier = str(column.table or "").casefold()
        if qualifier in qualified_lineage:
            return qualified_lineage[qualifier].get(field.casefold())
        resolved = resolve_physical(column)
        if resolved is not None or qualifier:
            return resolved
        derived_candidates = {
            (item.table, item.field): item
            for lineage in qualified_lineage.values()
            if (item := lineage.get(field.casefold())) is not None
        }
        if len(derived_candidates) == 1:
            return next(iter(derived_candidates.values()))
        return None

    return resolve


def _source_fields(node: Any, resolve: Any) -> tuple[SemanticFieldRef, ...]:
    from sqlglot import exp

    values = {
        (resolved.table, resolved.field): resolved
        for column in node.find_all(exp.Column)
        if (resolved := resolve(column)) is not None
    }
    if isinstance(node, exp.Column):
        resolved = resolve(node)
        if resolved is not None:
            values[(resolved.table, resolved.field)] = resolved
    return tuple(values[key] for key in sorted(values))


def _predicate_kind(node: Any) -> tuple[PredicateKind, str]:
    from sqlglot import exp

    if isinstance(node, exp.In):
        return PredicateKind.MEMBERSHIP, "in"
    if isinstance(node, exp.Between):
        return PredicateKind.RANGE, "between"
    if isinstance(node, exp.Is):
        return PredicateKind.BOOLEAN_TEST, "is"
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return PredicateKind.NULL_TEST, "is_not"
    if isinstance(node, (exp.Like, exp.ILike)):
        return PredicateKind.PATTERN, node.key.casefold()
    comparisons = {
        exp.EQ: "eq",
        exp.NEQ: "neq",
        exp.GT: "gt",
        exp.GTE: "gte",
        exp.LT: "lt",
        exp.LTE: "lte",
    }
    for expression_type, operator in comparisons.items():
        if isinstance(node, expression_type):
            return PredicateKind.COMPARISON, operator
    return PredicateKind.COMPOSITE, node.key.casefold()


def _split_and(node: Any) -> list[Any]:
    from sqlglot import exp

    if isinstance(node, exp.And):
        return [*_split_and(node.left), *_split_and(node.right)]
    return [node]


def _build_ir(
    *,
    question: str,
    language: str,
    sql: str,
    source: Mapping[str, Any],
    semantic_version: str,
    metric_contract_version: str | None,
    semantic_evidence: Mapping[str, Any],
    metric_contract_evidence: Mapping[str, Any] | None,
    max_rows: int,
) -> SemanticQueryIR:
    from sqlglot import exp, parse_one

    expression = parse_one(sql, read="postgres")
    select = expression if isinstance(expression, exp.Select) else expression.find(exp.Select)
    if select is None:
        raise ValueError("shadow_ir_select_missing")

    tables = tuple(sorted(str(value) for value in semantic_evidence.get("tables") or []))
    columns = tuple(sorted(str(value) for value in semantic_evidence.get("columns") or []))
    resolve = _column_resolver(expression, columns)
    group = select.args.get("group")
    group_hashes = tuple(
        _expression_sha(item) for item in (group.expressions if group is not None else ())
    )
    group_sql = {
        item.sql(dialect="postgres", pretty=False).casefold()
        for item in (group.expressions if group is not None else ())
    }

    projections: list[SemanticProjection] = []
    has_aggregate = False
    for index, projection in enumerate(select.expressions, start=1):
        body = projection.this if isinstance(projection, exp.Alias) else projection
        aggregate_node = next(iter(body.find_all(exp.AggFunc)), None)
        if isinstance(body, exp.AggFunc):
            aggregate_node = body
        aggregate = aggregate_node.key.casefold() if aggregate_node is not None else None
        has_aggregate = has_aggregate or aggregate is not None
        functions = {_function_name(node) for node in body.walk() if isinstance(node, exp.Func)}
        spatial_derived = any(name.startswith("st_") for name in functions)
        body_sql = body.sql(dialect="postgres", pretty=False).casefold()
        if aggregate is not None:
            role = ProjectionRole.METRIC
            expression_kind = "aggregate"
        elif body_sql in group_sql:
            role = ProjectionRole.DIMENSION
            expression_kind = "field" if isinstance(body, exp.Column) else "derived"
        elif isinstance(body, exp.Column):
            role = ProjectionRole.ATTRIBUTE
            expression_kind = "field"
        elif isinstance(body, exp.Literal):
            role = ProjectionRole.ATTRIBUTE
            expression_kind = "literal"
        else:
            role = ProjectionRole.METRIC if spatial_derived else ProjectionRole.ATTRIBUTE
            expression_kind = "derived"
        output_name = str(projection.alias_or_name or f"column_{index}")
        projections.append(
            SemanticProjection(
                output_name=output_name,
                role=role,
                expression_kind=expression_kind,
                aggregate=aggregate,
                source_fields=_source_fields(body, resolve),
                expression_sha256=_expression_sha(body),
            )
        )

    predicates: list[SemanticPredicate] = []
    for where in expression.find_all(exp.Where):
        for predicate in _split_and(where.this):
            kind, operator = _predicate_kind(predicate)
            literal_count = sum(1 for _item in predicate.find_all(exp.Literal))
            predicates.append(
                SemanticPredicate(
                    kind=kind,
                    operator=operator,
                    source_fields=_source_fields(predicate, resolve),
                    literal_count=literal_count,
                    expression_sha256=_expression_sha(predicate),
                )
            )

    joins: list[SemanticJoin] = []
    for join in expression.find_all(exp.Join):
        on_expression = join.args.get("on")
        if on_expression is None:
            raise ValueError("shadow_ir_join_predicate_missing")
        join_kind = JoinKind.EQUALITY
        operator = "eq"
        for function in on_expression.find_all(exp.Func):
            name = _function_name(function)
            if name.startswith("st_"):
                join_kind = JoinKind.SPATIAL
                operator = name
                break
        fields = _source_fields(on_expression, resolve)
        if len(fields) < 2:
            raise ValueError("shadow_ir_join_fields_unresolved")
        joins.append(
            SemanticJoin(
                kind=join_kind,
                operator=operator,
                source_fields=fields,
                expression_sha256=_expression_sha(on_expression),
            )
        )

    order_by: list[SemanticOrder] = []
    order = select.args.get("order")
    for item in order.expressions if order is not None else ():
        body = item.this if isinstance(item, exp.Ordered) else item
        order_by.append(
            SemanticOrder(
                output_name=(str(body.name) if isinstance(body, exp.Column) else None),
                direction="desc" if bool(item.args.get("desc")) else "asc",
                expression_sha256=_expression_sha(body),
            )
        )

    sql_limit = select.args.get("limit")
    result_limit = max_rows
    limit_enforcement: Literal["sql", "source_executor"] = "source_executor"
    if sql_limit is not None and isinstance(sql_limit.expression, exp.Literal):
        result_limit = min(max_rows, max(1, int(sql_limit.expression.this)))
        limit_enforcement = "sql"

    operation = (
        SemanticOperation.AGGREGATE if has_aggregate or group_hashes else SemanticOperation.DETAIL
    )
    source_id = int(source.get("source_id") or 0)
    source_ref = SemanticSourceRef(
        source_id=source_id,
        source_name=str(source.get("source_name") or f"source-{source_id}"),
        database_name=str(source.get("database_name") or ""),
        authorized_schemas=tuple(
            sorted(set(str(value) for value in source.get("authorized_schemas") or []))
        ),
        discovery_fingerprint=str(source.get("discovery_fingerprint") or ""),
        tables=tables,
    )
    contract_id = (
        str(metric_contract_evidence.get("contract_id") or "")
        if metric_contract_evidence
        else None
    )
    return SemanticQueryIR(
        route=(
            SemanticQueryRoute.REVIEWED_METRIC_CONTRACT
            if contract_id
            else SemanticQueryRoute.GOVERNED_SQL_AST
        ),
        semantic_version=semantic_version,
        metric_contract_version=metric_contract_version,
        metric_contract_id=contract_id,
        task_frame=SemanticTaskFrame(
            question_sha256=_sha256(question),
            language=language,
            operation=operation,
            source_ids=(source_id,),
        ),
        sources=(source_ref,),
        operation=operation,
        projections=tuple(projections),
        predicates=tuple(predicates),
        joins=tuple(joins),
        group_expression_sha256s=group_hashes,
        order_by=tuple(order_by),
        result_limit=result_limit,
        limit_enforcement=limit_enforcement,
    )


def validate_semantic_query_ir(
    ir: SemanticQueryIR,
    *,
    governed_tables: tuple[str, ...],
    governed_columns: tuple[str, ...],
    max_rows: int,
) -> SemanticIRValidationReport:
    """Validate shadow IR independently of the SQL validator that produced it."""

    ir_payload = ir.model_dump(mode="json")
    ir_sha = canonical_json_fingerprint(ir_payload)
    referenced_tables = {
        field.table
        for projection in ir.projections
        for field in projection.source_fields
    } | {
        field.table
        for predicate in ir.predicates
        for field in predicate.source_fields
    } | {
        field.table for join in ir.joins for field in join.source_fields
    }
    referenced_columns = {
        f"{field.table}.{field.field}"
        for projection in ir.projections
        for field in projection.source_fields
    } | {
        f"{field.table}.{field.field}"
        for predicate in ir.predicates
        for field in predicate.source_fields
    } | {
        f"{field.table}.{field.field}" for join in ir.joins for field in join.source_fields
    }
    table_scope = set(governed_tables)
    column_scope = set(governed_columns)
    allowed_join_operators = {
        "eq",
        "st_contains",
        "st_covers",
        "st_dwithin",
        "st_intersects",
    }
    checks = (
        ValidationCheck(
            check_id="source_scope_bound",
            passed=bool(ir.sources) and all(source.source_id > 0 for source in ir.sources),
        ),
        ValidationCheck(
            check_id="table_scope_exact",
            passed=set(ir.sources[0].tables) == table_scope,
        ),
        ValidationCheck(
            check_id="referenced_tables_governed",
            passed=referenced_tables <= table_scope,
        ),
        ValidationCheck(
            check_id="referenced_columns_governed",
            passed=referenced_columns <= column_scope,
        ),
        ValidationCheck(
            check_id="join_operators_governed",
            passed=all(join.operator in allowed_join_operators for join in ir.joins),
        ),
        ValidationCheck(
            check_id="result_limit_bounded",
            passed=1 <= ir.result_limit <= max_rows,
        ),
        ValidationCheck(
            check_id="projection_contract_present",
            passed=bool(ir.projections),
        ),
    )
    reason_codes = tuple(check.check_id for check in checks if not check.passed)
    return SemanticIRValidationReport(
        valid=not reason_codes,
        ir_sha256=ir_sha,
        checks=checks,
        reason_codes=reason_codes,
    )


def build_semantic_logical_plan(
    ir: SemanticQueryIR,
    validation: SemanticIRValidationReport,
) -> SemanticLogicalPlan:
    if not validation.valid:
        raise ValueError("shadow_ir_validation_failed")
    nodes: list[LogicalPlanNode] = []
    roots: list[str] = []
    for index, table in enumerate(ir.sources[0].tables, start=1):
        node_id = f"scan_{index:03d}"
        nodes.append(
            LogicalPlanNode(
                node_id=node_id,
                operator="scan",
                attributes={"source_id": ir.sources[0].source_id, "table": table},
            )
        )
        roots.append(node_id)
    current = roots[0]
    for index, join in enumerate(ir.joins, start=1):
        node_id = f"join_{index:03d}"
        right = roots[index] if index < len(roots) else roots[-1]
        nodes.append(
            LogicalPlanNode(
                node_id=node_id,
                operator="join",
                input_node_ids=(current, right),
                attributes={"kind": join.kind.value, "operator": join.operator},
            )
        )
        current = node_id
    if ir.predicates:
        nodes.append(
            LogicalPlanNode(
                node_id="filter_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={
                    "predicate_count": len(ir.predicates),
                    "operators": sorted({item.operator for item in ir.predicates}),
                },
            )
        )
        current = "filter_001"
    if ir.operation is SemanticOperation.AGGREGATE:
        nodes.append(
            LogicalPlanNode(
                node_id="aggregate_001",
                operator="aggregate",
                input_node_ids=(current,),
                attributes={
                    "group_count": len(ir.group_expression_sha256s),
                    "metric_count": sum(
                        item.role is ProjectionRole.METRIC for item in ir.projections
                    ),
                },
            )
        )
        current = "aggregate_001"
    nodes.append(
        LogicalPlanNode(
            node_id="project_001",
            operator="project",
            input_node_ids=(current,),
            attributes={"outputs": [item.output_name for item in ir.projections]},
        )
    )
    current = "project_001"
    if ir.order_by:
        nodes.append(
            LogicalPlanNode(
                node_id="sort_001",
                operator="sort",
                input_node_ids=(current,),
                attributes={"order_count": len(ir.order_by)},
            )
        )
        current = "sort_001"
    nodes.append(
        LogicalPlanNode(
            node_id="limit_001",
            operator="limit",
            input_node_ids=(current,),
            attributes={
                "row_limit": ir.result_limit,
                "enforcement": ir.limit_enforcement,
            },
        )
    )
    return SemanticLogicalPlan(
        ir_sha256=validation.ir_sha256,
        root_node_id="limit_001",
        nodes=tuple(nodes),
    )


def build_shadow_semantic_plan_evidence(
    *,
    question: str,
    language: str,
    sql: str,
    source: Mapping[str, Any],
    semantic_version: str,
    metric_contract_version: str | None,
    semantic_evidence: Mapping[str, Any],
    metric_contract_evidence: Mapping[str, Any] | None,
    max_rows: int,
) -> ShadowSemanticPlanEvidence:
    """Build non-authoritative IR and plan evidence for one admitted query."""

    try:
        ir = _build_ir(
            question=question,
            language=language,
            sql=sql,
            source=source,
            semantic_version=semantic_version,
            metric_contract_version=metric_contract_version,
            semantic_evidence=semantic_evidence,
            metric_contract_evidence=metric_contract_evidence,
            max_rows=max_rows,
        )
        governed_tables = tuple(
            sorted(str(value) for value in semantic_evidence.get("tables") or [])
        )
        governed_columns = tuple(
            sorted(str(value) for value in semantic_evidence.get("columns") or [])
        )
        validation = validate_semantic_query_ir(
            ir,
            governed_tables=governed_tables,
            governed_columns=governed_columns,
            max_rows=max_rows,
        )
        if not validation.valid:
            return ShadowSemanticPlanEvidence(
                status="legacy_fallback",
                fallback_reason="semantic_ir_validation_failed:"
                + ",".join(validation.reason_codes),
            )
        logical_plan = build_semantic_logical_plan(ir, validation)
        logical_sha = canonical_json_fingerprint(logical_plan.model_dump(mode="json"))
        spatial_operators = tuple(
            sorted({join.operator for join in ir.joins if join.kind is JoinKind.SPATIAL})
        )
        physical_plan = SemanticPhysicalPlan(
            compilation_mode=(
                "reviewed_contract_shadow"
                if ir.route is SemanticQueryRoute.REVIEWED_METRIC_CONTRACT
                else "validated_sql_ast_shadow"
            ),
            logical_plan_sha256=logical_sha,
            statement_sha256=_sha256(sql),
            source_ids=ir.task_frame.source_ids,
            tables=governed_tables,
            columns=governed_columns,
            spatial_operators=spatial_operators,
        )
        physical_sha = canonical_json_fingerprint(physical_plan.model_dump(mode="json"))
        return ShadowSemanticPlanEvidence(
            status="planned",
            semantic_ir=ir,
            validation=validation,
            logical_plan=logical_plan,
            physical_plan=physical_plan,
            fingerprints={
                "semantic_ir_sha256": validation.ir_sha256,
                "logical_plan_sha256": logical_sha,
                "physical_plan_sha256": physical_sha,
            },
        )
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        return ShadowSemanticPlanEvidence(
            status="legacy_fallback",
            fallback_reason=f"shadow_plan_unavailable:{reason}"[:256],
        )


def build_certified_metric_contract_plan(
    *,
    question: str,
    language: str,
    canonical_sql: str,
    source: Mapping[str, Any],
    semantic_version: str,
    metric_contract_version: str | None,
    semantic_evidence: Mapping[str, Any],
    metric_contract_evidence: Mapping[str, Any],
    max_rows: int,
) -> CertifiedMetricContractPlanEvidence:
    """Plan and compile one reviewed metric contract before execution.

    This is intentionally limited to an immutable server-side SQL template.
    The compiler therefore has no model-authored SQL input and its statement
    fingerprint must exactly match the reviewed template selected by the
    metric resolver.  Any planning failure blocks execution rather than
    silently falling back to a different statement.
    """

    normalized_sql = canonical_sql.strip().rstrip(";")
    if not normalized_sql:
        raise ValueError("certified_metric_contract_sql_missing")
    if not str(metric_contract_evidence.get("contract_id") or "").strip():
        raise ValueError("certified_metric_contract_id_missing")

    ir = _build_ir(
        question=question,
        language=language,
        sql=normalized_sql,
        source=source,
        semantic_version=semantic_version,
        metric_contract_version=metric_contract_version,
        semantic_evidence=semantic_evidence,
        metric_contract_evidence=metric_contract_evidence,
        max_rows=max_rows,
    )
    if ir.route is not SemanticQueryRoute.REVIEWED_METRIC_CONTRACT:
        raise ValueError("certified_metric_contract_route_missing")
    governed_tables = tuple(
        sorted(str(value) for value in semantic_evidence.get("tables") or [])
    )
    governed_columns = tuple(
        sorted(str(value) for value in semantic_evidence.get("columns") or [])
    )
    validation = validate_semantic_query_ir(
        ir,
        governed_tables=governed_tables,
        governed_columns=governed_columns,
        max_rows=max_rows,
    )
    if not validation.valid:
        raise ValueError(
            "certified_metric_contract_validation_failed:"
            + ",".join(validation.reason_codes)
        )
    logical_plan = build_semantic_logical_plan(ir, validation)
    logical_sha = canonical_json_fingerprint(logical_plan.model_dump(mode="json"))
    spatial_operators = tuple(
        sorted({join.operator for join in ir.joins if join.kind is JoinKind.SPATIAL})
    )
    physical_plan = SemanticPhysicalPlan(
        compilation_mode="reviewed_contract_compiler",
        logical_plan_sha256=logical_sha,
        statement_sha256=_sha256(normalized_sql),
        source_ids=ir.task_frame.source_ids,
        tables=governed_tables,
        columns=governed_columns,
        spatial_operators=spatial_operators,
    )
    physical_sha = canonical_json_fingerprint(physical_plan.model_dump(mode="json"))
    return CertifiedMetricContractPlanEvidence(
        semantic_ir=ir,
        validation=validation,
        logical_plan=logical_plan,
        physical_plan=physical_plan,
        compiled_statement=normalized_sql,
        fingerprints={
            "semantic_ir_sha256": validation.ir_sha256,
            "logical_plan_sha256": logical_sha,
            "physical_plan_sha256": physical_sha,
            "compiled_statement_sha256": _sha256(normalized_sql),
        },
    )


class SemanticIRCompilationError(ValueError):
    """A constrained semantic IR cannot be compiled to an admitted plan."""


_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    if not _SQL_IDENTIFIER_RE.fullmatch(value):
        raise SemanticIRCompilationError("semantic_identifier_invalid")
    return f'"{value}"'


def _quote_table_identifier(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 2:
        raise SemanticIRCompilationError("semantic_table_identifier_invalid")
    return ".".join(_quote_identifier(item) for item in parts)


def _semantic_alias_key(value: Any) -> str:
    """Normalize a reviewed logical alias without changing its meaning."""

    return re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE).strip()


def _binding_is_execution_active(binding: Mapping[str, Any]) -> bool:
    """Return whether a binding is allowed to enter the executable compiler.

    v4 layers publish an explicit ``execution_eligible`` flag.  Older reviewed
    layers predate that field, so a reviewed status is accepted only when the
    flag is absent.  An explicit ``False`` is always authoritative and keeps
    technical-catalog bindings out of the IR compiler.
    """

    if binding.get("execution_eligible") is False:
        return False
    if binding.get("execution_eligible") is True:
        return True
    return str(binding.get("review_status") or "").casefold().startswith("reviewed")


def _binding_aliases(
    semantic_layer: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> set[str]:
    values: set[str] = {
        str(binding.get("semantic_entity") or ""),
        str(binding.get("business_asset_id") or ""),
    }
    table = str(binding.get("physical_table") or "")
    assets = [
        asset
        for asset in semantic_layer.get("semantic_assets") or []
        if isinstance(asset, Mapping)
        and table
        and table in {str(value) for value in asset.get("physical_tables") or []}
    ]
    for asset in assets:
        values.update(
            str(value)
            for value in (
                asset.get("asset_id"),
                asset.get("business_asset_id"),
                *(asset.get("aliases") or []),
                *((asset.get("labels") or {}).values()),
            )
            if str(value or "").strip()
        )
    values.update(
        str(value)
        for value in (
            *(binding.get("aliases") or []),
            *((binding.get("labels") or {}).values()),
        )
        if str(value or "").strip()
    )
    return {
        key
        for value in values
        if (key := _semantic_alias_key(value))
    }


def _semantic_entity_binding(
    semantic_layer: Mapping[str, Any],
    semantic_entity: str,
) -> Mapping[str, Any]:
    active_bindings = [
        item
        for item in semantic_layer.get("table_bindings") or []
        if isinstance(item, Mapping)
        and _binding_is_execution_active(item)
    ]
    bindings = [
        item
        for item in active_bindings
        if str(item.get("semantic_entity") or "") == semantic_entity
    ]
    if len(bindings) == 1:
        return bindings[0]
    if len(bindings) > 1:
        raise SemanticIRCompilationError("semantic_entity_not_active_or_ambiguous")
    query_key = _semantic_alias_key(semantic_entity)
    if not query_key:
        raise SemanticIRCompilationError("semantic_entity_not_active_or_ambiguous")
    candidates = [
        item
        for item in active_bindings
        if query_key in _binding_aliases(semantic_layer, item)
    ]
    if len(candidates) != 1:
        raise SemanticIRCompilationError("semantic_entity_not_active_or_ambiguous")
    return candidates[0]
    physical_table = str(bindings[0].get("physical_table") or "")
    _quote_table_identifier(physical_table)
    return bindings[0]


def _semantic_field_binding(
    binding: Mapping[str, Any],
    field_ref: SemanticModelFieldRef,
    *,
    semantic_layer: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    if str(binding.get("semantic_entity") or "") != field_ref.semantic_entity:
        # The model may use a reviewed asset id or multilingual business label
        # as the entity alias.  Entity binding is still checked by the caller;
        # this branch only avoids rejecting the corresponding field lookup.
        if semantic_layer is None or _semantic_alias_key(
            field_ref.semantic_entity
        ) not in _binding_aliases(semantic_layer, binding):
            raise SemanticIRCompilationError("semantic_field_entity_mismatch")
    fields = [
        item
        for item in binding.get("fields") or []
        if isinstance(item, Mapping)
        and str(item.get("semantic_field") or "") == field_ref.semantic_field
    ]
    if len(fields) == 1:
        _quote_identifier(str(fields[0].get("physical_field") or ""))
        return fields[0]
    if len(fields) > 1:
        raise SemanticIRCompilationError("semantic_field_not_active_or_ambiguous")
    query_key = _semantic_alias_key(field_ref.semantic_field)
    if not query_key:
        raise SemanticIRCompilationError("semantic_field_not_active_or_ambiguous")
    candidates = []
    for field in binding.get("fields") or []:
        if not isinstance(field, Mapping):
            continue
        labels = (field.get("labels") or {}).values()
        aliases = field.get("aliases") or []
        keys = {
            _semantic_alias_key(value)
            for value in (
                *labels,
                *aliases,
            )
            if _semantic_alias_key(value)
        }
        if query_key in keys:
            candidates.append(field)
    if len(candidates) != 1:
        raise SemanticIRCompilationError("semantic_field_not_active_or_ambiguous")
    _quote_identifier(str(candidates[0].get("physical_field") or ""))
    return candidates[0]


def _field_sql(field: Mapping[str, Any], *, alias: str = "gda_source") -> str:
    return alias + "." + _quote_identifier(str(field.get("physical_field") or ""))


def _normalized_relation_operator(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized == "=":
        return "eq"
    return normalized


def _reviewed_relation_for_join(
    join: SemanticIRJoin,
    *,
    resolve_field: Any,
    semantic_layer: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Resolve a logical join only when it exactly matches reviewed metadata."""

    left = resolve_field(join.left_field_ref)
    right = resolve_field(join.right_field_ref)
    left_endpoint = (
        f"{left.get('physical_table')}.{left.get('physical_field')}".casefold()
    )
    right_endpoint = (
        f"{right.get('physical_table')}.{right.get('physical_field')}".casefold()
    )
    requested_endpoints = frozenset((left_endpoint, right_endpoint))
    requested_kind = join.kind.value
    requested_operator = join.operator
    matches = [
        relation
        for relation in semantic_layer.get("relationships") or []
        if isinstance(relation, Mapping)
        and str(relation.get("review_status") or "").casefold().startswith(
            "reviewed"
        )
        and str(relation.get("kind") or "").casefold() == requested_kind
        and _normalized_relation_operator(relation.get("operator")) == requested_operator
        and frozenset(
            (
                str(relation.get("left") or "").casefold(),
                str(relation.get("right") or "").casefold(),
            )
        )
        == requested_endpoints
    ]
    if join.kind is JoinKind.SPATIAL:
        # ST_Intersects is symmetric.  A model may put the primary entity on
        # either side of the join, while the reviewed relation keeps a
        # canonical direction for its cardinality (for example,
        # district contains building).  Containment and distance operators
        # remain direction-sensitive because their CRS/geometry policies can
        # differ by endpoint.
        if join.operator != "st_intersects":
            matches = [
                relation
                for relation in matches
                if (
                    str(relation.get("left") or "").casefold(),
                    str(relation.get("right") or "").casefold(),
                )
                == (left_endpoint, right_endpoint)
            ]
    if len(matches) != 1:
        raise SemanticIRCompilationError("semantic_ir_join_not_reviewed")
    if join.operator == "st_dwithin":
        maximum = matches[0].get("max_distance_metres")
        metric_srid = matches[0].get("metric_srid")
        if maximum is None or metric_srid is None:
            raise SemanticIRCompilationError(
                "semantic_ir_spatial_distance_policy_missing"
            )
        distance = float(join.distance_metres or 0)
        if not math.isfinite(distance) or distance < 0 or distance > float(maximum):
            raise SemanticIRCompilationError(
                "semantic_ir_spatial_distance_exceeds_reviewed_maximum"
            )
    return matches[0]


def _spatial_intent_matches_reviewed_relation(
    *,
    intent: SpatialIntent,
    join: SemanticIRJoin,
    relation: Mapping[str, Any],
    primary_table: str,
) -> bool:
    """Apply the reviewed relationship's direction to user spatial wording.

    ``ST_Intersects`` itself is symmetric, but a reviewed relationship may
    publish a directional cardinality such as ``contains``.  That metadata is
    the only authority that lets the free-form route interpret phrases such
    as "inside a district" without turning every intersection into a
    containment query.
    """

    if intent is SpatialIntent.NONE:
        return True
    operator = _normalized_relation_operator(relation.get("operator"))
    if intent is SpatialIntent.INTERSECTS:
        return operator == "st_intersects"
    if intent is SpatialIntent.DISTANCE:
        return operator == "st_dwithin"
    if intent not in {SpatialIntent.WITHIN, SpatialIntent.CONTAINS}:
        return False

    left_endpoint = str(relation.get("left") or "").casefold()
    right_endpoint = str(relation.get("right") or "").casefold()
    primary_table = str(primary_table or "").casefold()
    left_table = left_endpoint.rsplit(".", 1)[0] if "." in left_endpoint else ""
    right_table = right_endpoint.rsplit(".", 1)[0] if "." in right_endpoint else ""

    # Direct containment operators define the relation direction themselves.
    # ST_Intersects needs an explicit reviewed ``contains`` cardinality to
    # acquire containment semantics; generic many-to-many intersections do
    # not qualify.
    if operator == "st_within":
        expected_table = left_table if intent is SpatialIntent.WITHIN else right_table
    elif operator in {"st_covers", "st_contains"}:
        expected_table = right_table if intent is SpatialIntent.WITHIN else left_table
    elif operator == "st_intersects":
        if str(relation.get("cardinality") or "").casefold() != "contains":
            return False
        expected_table = right_table if intent is SpatialIntent.WITHIN else left_table
    else:
        return False
    return bool(expected_table) and primary_table == expected_table


def _reviewed_spatial_operand_sql(
    field_sql: str,
    relation: Mapping[str, Any],
    *,
    side: Literal["left", "right"],
) -> str:
    """Compile a spatial endpoint from reviewed CRS/geometry metadata."""

    expression = field_sql
    representative = str(relation.get(f"{side}_geometry_transform") or "").casefold()
    if representative:
        if representative != "point_on_surface":
            raise SemanticIRCompilationError(
                "semantic_ir_spatial_geometry_transform_unsupported"
            )
        expression = f"ST_PointOnSurface({expression})"
    raw_operation_srid = relation.get("operation_srid") or relation.get("metric_srid")
    if raw_operation_srid is None:
        return expression
    try:
        operation_srid = int(raw_operation_srid)
    except (TypeError, ValueError) as exc:
        raise SemanticIRCompilationError("semantic_ir_spatial_operation_srid_invalid") from exc
    raw_source_srid = relation.get(f"{side}_srid")
    if raw_source_srid is None:
        return f"ST_Transform({expression}, {operation_srid})"
    try:
        source_srid = int(raw_source_srid)
    except (TypeError, ValueError) as exc:
        raise SemanticIRCompilationError("semantic_ir_spatial_source_srid_invalid") from exc
    if source_srid != operation_srid:
        return f"ST_Transform({expression}, {operation_srid})"
    return expression


def _validate_scalar_parameter(value: str | int | float | bool) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise SemanticIRCompilationError("semantic_filter_value_not_finite")
        return value
    if isinstance(value, str):
        if not value or len(value) > 512 or "\x00" in value:
            raise SemanticIRCompilationError("semantic_filter_value_invalid")
        return value
    raise SemanticIRCompilationError("semantic_filter_value_type_invalid")


def _compile_filter(
    filter_spec: SemanticFilter,
    *,
    field: Mapping[str, Any],
    alias: str,
    parameter_bindings: dict[str, str | int | float | bool],
    next_parameter_index: int,
) -> tuple[str, int]:
    field_sql = _field_sql(field, alias=alias)
    operator = filter_spec.operator
    if operator == "is_null":
        return f"{field_sql} IS NULL", next_parameter_index
    if operator == "not_null":
        return f"{field_sql} IS NOT NULL", next_parameter_index

    values = [_validate_scalar_parameter(value) for value in filter_spec.values]
    if filter_spec.operator in {"eq", "neq", "in", "not_in", "contains", "prefix"}:
        value_semantics = field.get("value_semantics") or {}
        alias_to_source = {
            re.sub(r"\s+", " ", str(alias).strip()).casefold(): source_value
            for source_value, aliases in value_semantics.items()
            for alias in (source_value, *aliases)
            if str(alias).strip()
        }
        values = [
            alias_to_source.get(
                re.sub(r"\s+", " ", value.strip()).casefold(),
                value,
            )
            if isinstance(value, str)
            else value
            for value in values
        ]
    placeholders: list[str] = []
    for value in values:
        name = f"gda_p_{next_parameter_index:03d}"
        next_parameter_index += 1
        if operator == "contains":
            if not isinstance(value, str):
                raise SemanticIRCompilationError("semantic_contains_requires_text")
            value = f"%{value}%"
        elif operator == "prefix":
            if not isinstance(value, str):
                raise SemanticIRCompilationError("semantic_prefix_requires_text")
            value = f"{value}%"
        parameter_bindings[name] = value
        placeholders.append(f":{name}")

    if operator == "eq":
        return f"{field_sql} = {placeholders[0]}", next_parameter_index
    if operator == "neq":
        return f"{field_sql} <> {placeholders[0]}", next_parameter_index
    if operator == "gt":
        return f"{field_sql} > {placeholders[0]}", next_parameter_index
    if operator == "gte":
        return f"{field_sql} >= {placeholders[0]}", next_parameter_index
    if operator == "lt":
        return f"{field_sql} < {placeholders[0]}", next_parameter_index
    if operator == "lte":
        return f"{field_sql} <= {placeholders[0]}", next_parameter_index
    if operator == "in":
        return f"{field_sql} IN ({', '.join(placeholders)})", next_parameter_index
    if operator == "not_in":
        return f"{field_sql} NOT IN ({', '.join(placeholders)})", next_parameter_index
    if operator == "contains":
        return f"{field_sql} ILIKE {placeholders[0]}", next_parameter_index
    if operator == "prefix":
        return f"{field_sql} ILIKE {placeholders[0]}", next_parameter_index
    raise SemanticIRCompilationError("semantic_filter_operator_unsupported")


def build_compiled_ad_hoc_semantic_plan(
    *,
    semantic_ir: AdHocSemanticQueryIR,
    source: Mapping[str, Any],
    semantic_version: str,
    semantic_layer: Mapping[str, Any],
    max_rows: int,
    expected_spatial_intent: SpatialIntent = SpatialIntent.NONE,
) -> CompiledAdHocSemanticPlanEvidence:
    """Validate and compile a model-authored logical query to PostgreSQL SQL.

    Only approved semantic bindings enter this function.  All physical
    identifiers are selected from the semantic layer and all user-derived
    values become named parameters, so the model cannot compose SQL text or
    select a source table directly.
    """

    if semantic_ir.status != "query":
        raise SemanticIRCompilationError("semantic_ir_not_query")
    if max_rows < 1:
        raise SemanticIRCompilationError("semantic_max_rows_invalid")
    if (semantic_layer.get("activation_gate") or {}).get(
        "active_for_free_form_nl2sql"
    ) is not True:
        raise SemanticIRCompilationError("semantic_ir_not_activated")

    entity = str(semantic_ir.semantic_entity or "")
    entity_bindings: dict[str, Mapping[str, Any]] = {}
    entity_tables: dict[str, str] = {}
    field_bindings: dict[tuple[str, str], Mapping[str, Any]] = {}

    def resolve_entity_binding(semantic_entity: str) -> Mapping[str, Any]:
        if semantic_entity not in entity_bindings:
            binding = _semantic_entity_binding(semantic_layer, semantic_entity)
            physical_table = str(binding.get("physical_table") or "")
            _quote_table_identifier(physical_table)
            entity_bindings[semantic_entity] = binding
            entity_tables[semantic_entity] = physical_table
        return entity_bindings[semantic_entity]

    def resolve_field(field_ref: SemanticModelFieldRef) -> Mapping[str, Any]:
        key = (field_ref.semantic_entity, field_ref.semantic_field)
        if key not in field_bindings:
            binding = resolve_entity_binding(field_ref.semantic_entity)
            field_bindings[key] = {
                **dict(
                    _semantic_field_binding(
                        binding,
                        field_ref,
                        semantic_layer=semantic_layer,
                    )
                ),
                "physical_table": entity_tables[field_ref.semantic_entity],
            }
        return field_bindings[key]

    resolve_entity_binding(entity)
    resolved_projection_fields: list[Mapping[str, Any]] = []
    resolved_filter_fields: list[Mapping[str, Any]] = []
    resolved_join_fields: list[Mapping[str, Any]] = []
    for projection in semantic_ir.projections:
        if projection.field_ref is None:
            continue
        field = resolve_field(projection.field_ref)
        geometry_only = str(field.get("usage") or "") == (
            "predicate_or_derived_metric_only"
        )
        geometry_role = str(field.get("business_role") or "") == "geometry"
        if projection.derived_measure is not None:
            if not (geometry_only and geometry_role):
                raise SemanticIRCompilationError(
                    "semantic_derived_measure_requires_geometry"
                )
        elif geometry_only or geometry_role:
            raise SemanticIRCompilationError("semantic_geometry_projection_rejected")
        resolved_projection_fields.append(field)
    for filter_spec in semantic_ir.filters:
        resolved_filter_fields.append(resolve_field(filter_spec.field_ref))
    for group in semantic_ir.any_filter_groups:
        for filter_spec in group.filters:
            resolved_filter_fields.append(resolve_field(filter_spec.field_ref))
    reviewed_joins: list[Mapping[str, Any]] = []
    for join in semantic_ir.joins:
        resolved_join_fields.extend(
            (
                resolve_field(join.left_field_ref),
                resolve_field(join.right_field_ref),
            )
        )
        reviewed_joins.append(
            _reviewed_relation_for_join(
                join,
                resolve_field=resolve_field,
                semantic_layer=semantic_layer,
            )
        )

    spatial_joins = [join for join in semantic_ir.joins if join.kind is JoinKind.SPATIAL]
    if expected_spatial_intent is not SpatialIntent.NONE:
        if not spatial_joins:
            raise SemanticIRCompilationError("semantic_ir_spatial_intent_requires_spatial_join")
        if semantic_ir.spatial_intent is not expected_spatial_intent:
            raise SemanticIRCompilationError("semantic_ir_spatial_intent_mismatch")
    if semantic_ir.spatial_intent is not SpatialIntent.NONE:
        primary_table = entity_tables.get(entity, "")
        for join, relation in zip(semantic_ir.joins, reviewed_joins):
            if join.kind is not JoinKind.SPATIAL:
                continue
            if not _spatial_intent_matches_reviewed_relation(
                intent=semantic_ir.spatial_intent,
                join=join,
                relation=relation,
                primary_table=primary_table,
            ):
                raise SemanticIRCompilationError(
                    "semantic_ir_spatial_intent_not_supported_by_reviewed_relation"
                )

    # Each added entity receives a compiler-owned alias.  The model never
    # controls aliases, table names, columns, predicates, or SQL functions.
    entity_aliases = {entity: "gda_source"}
    pending_joins = list(enumerate(semantic_ir.joins))
    tree_joins: list[tuple[int, str]] = []
    residual_join_indexes: list[int] = []
    while pending_joins:
        next_pending: list[tuple[int, SemanticIRJoin]] = []
        advanced = False
        for join_index, join in pending_joins:
            left_entity = join.left_field_ref.semantic_entity
            right_entity = join.right_field_ref.semantic_entity
            left_present = left_entity in entity_aliases
            right_present = right_entity in entity_aliases
            if left_present and right_present:
                residual_join_indexes.append(join_index)
                advanced = True
                continue
            if left_present or right_present:
                added_entity = right_entity if left_present else left_entity
                entity_aliases[added_entity] = (
                    f"gda_join_{len(entity_aliases):03d}"
                )
                tree_joins.append((join_index, added_entity))
                advanced = True
                continue
            next_pending.append((join_index, join))
        if not advanced:
            raise SemanticIRCompilationError("semantic_ir_join_graph_disconnected")
        pending_joins = next_pending

    def field_sql(field_ref: SemanticModelFieldRef) -> str:
        return _field_sql(
            resolve_field(field_ref),
            alias=entity_aliases[field_ref.semantic_entity],
        )

    parameter_bindings: dict[str, str | int | float | bool] = {}

    def join_condition(join_index: int, join: SemanticIRJoin) -> str:
        left_sql = field_sql(join.left_field_ref)
        right_sql = field_sql(join.right_field_ref)
        if join.kind is JoinKind.EQUALITY:
            return f"{left_sql} = {right_sql}"
        relation = reviewed_joins[join_index]
        left_sql = _reviewed_spatial_operand_sql(
            left_sql,
            relation,
            side="left",
        )
        right_sql = _reviewed_spatial_operand_sql(
            right_sql,
            relation,
            side="right",
        )
        if join.operator == "st_dwithin":
            metric_srid = int(
                relation.get("operation_srid") or relation["metric_srid"]
            )
            parameter_name = f"gda_join_distance_{join_index + 1:03d}"
            parameter_bindings[parameter_name] = float(join.distance_metres or 0)
            return (
                f"ST_DWithin({left_sql}, {right_sql}, :{parameter_name})"
            )
        spatial_functions = {
            "st_covers": "ST_Covers",
            "st_contains": "ST_Contains",
            "st_within": "ST_Within",
            "st_intersects": "ST_Intersects",
        }
        return f"{spatial_functions[join.operator]}({left_sql}, {right_sql})"

    join_conditions = [
        join_condition(index, join) for index, join in enumerate(semantic_ir.joins)
    ]
    limit = min(int(semantic_ir.limit or max_rows), max_rows)
    ir_sha = canonical_json_fingerprint(semantic_ir.model_dump(mode="json"))
    checks = (
        ValidationCheck(
            check_id="source_scope_bound",
            passed=int(source.get("source_id") or 0) > 0,
        ),
        ValidationCheck(
            check_id="semantic_entity_active",
            passed=bool(entity_tables.get(entity)),
        ),
        ValidationCheck(
            check_id="semantic_fields_active",
            passed=bool(resolved_projection_fields) or any(
                item.aggregate is SemanticAggregate.COUNT
                for item in semantic_ir.projections
            ),
        ),
        ValidationCheck(
            check_id="semantic_relationships_reviewed",
            passed=len(reviewed_joins) == len(semantic_ir.joins),
        ),
        ValidationCheck(
            check_id="geometry_usage_safe",
            passed=True,
        ),
        ValidationCheck(
            check_id="result_limit_bounded",
            passed=1 <= limit <= max_rows,
        ),
    )
    reason_codes = tuple(item.check_id for item in checks if not item.passed)
    validation = SemanticIRValidationReport(
        valid=not reason_codes,
        ir_sha256=ir_sha,
        checks=checks,
        reason_codes=reason_codes,
    )
    if not validation.valid:
        raise SemanticIRCompilationError(
            "semantic_ir_validation_failed:" + ",".join(reason_codes)
        )

    projection_sql: list[str] = []
    has_metric = False
    dimension_sql: list[str] = []
    for projection in semantic_ir.projections:
        quoted_alias = _quote_identifier(projection.output_name)
        if projection.role is not ProjectionRole.METRIC:
            assert projection.field_ref is not None
            expression = field_sql(projection.field_ref)
            projection_sql.append(f"{expression} AS {quoted_alias}")
            if projection.role is ProjectionRole.DIMENSION:
                dimension_sql.append(expression)
            continue
        has_metric = True
        aggregate = projection.aggregate
        assert aggregate is not None
        if aggregate is SemanticAggregate.COUNT and projection.field_ref is None:
            expression = "COUNT(*)"
        else:
            assert projection.field_ref is not None
            field = resolve_field(projection.field_ref)
            if (
                aggregate is SemanticAggregate.COUNT
                and str(field.get("business_role") or "") == "join_key"
            ):
                raise SemanticIRCompilationError(
                    "semantic_ir_count_join_key_requires_row_count"
                )
            expression = field_sql(projection.field_ref)
            if projection.derived_measure is not None:
                if projection.derived_measure is SemanticDerivedMeasure.AREA_SQUARE_METRES:
                    # Reviewed area contracts aggregate exact numeric values
                    # rather than PostgreSQL float8 intermediates. Casting
                    # each measurement before aggregation keeps IR results
                    # equivalent to the governed canonical area semantics.
                    expression = f"ST_Area({expression}::geography)::numeric"
                else:
                    expression = (
                        f"ST_Area({expression}::geography)::numeric / 1000000.0"
                    )
                expression = f"{aggregate.value.upper()}({expression})"
            elif aggregate is SemanticAggregate.COUNT:
                expression = f"COUNT({expression})"
            elif aggregate is SemanticAggregate.COUNT_DISTINCT:
                expression = f"COUNT(DISTINCT {expression})"
            else:
                expression = f"{aggregate.value.upper()}({expression})"
        projection_sql.append(f"{expression} AS {quoted_alias}")

    # A capped grouped result without an ordering can return a different
    # subset between executions. The compiler supplies a stable presentation
    # order when the logical request leaves it unspecified; this never changes
    # an explicit user-requested ordering.
    compiler_default_ordering = bool(
        has_metric and dimension_sql and not semantic_ir.order_by
    )
    effective_order_by = (
        tuple((item.output_name, item.direction) for item in semantic_ir.order_by)
        if semantic_ir.order_by
        else tuple(
            (projection.output_name, "asc")
            for projection in semantic_ir.projections
            if projection.role is ProjectionRole.DIMENSION
        )
        if compiler_default_ordering
        else ()
    )

    filters_sql: list[str] = []
    next_parameter_index = 1
    for filter_spec in semantic_ir.filters:
        clause, next_parameter_index = _compile_filter(
            filter_spec,
            field=resolve_field(filter_spec.field_ref),
            alias=entity_aliases[filter_spec.field_ref.semantic_entity],
            parameter_bindings=parameter_bindings,
            next_parameter_index=next_parameter_index,
        )
        filters_sql.append(clause)
    any_filter_groups_sql: list[str] = []
    for group in semantic_ir.any_filter_groups:
        clauses: list[str] = []
        for filter_spec in group.filters:
            clause, next_parameter_index = _compile_filter(
                filter_spec,
                field=resolve_field(filter_spec.field_ref),
                alias=entity_aliases[filter_spec.field_ref.semantic_entity],
                parameter_bindings=parameter_bindings,
                next_parameter_index=next_parameter_index,
            )
            clauses.append(clause)
        any_filter_groups_sql.append("(" + " OR ".join(clauses) + ")")

    statement_parts = [
        "SELECT " + ("DISTINCT " if semantic_ir.distinct_rows else "") + ", ".join(projection_sql),
        # Tables are compiler-selected canonical ``schema.table`` values, which
        # lets the runtime table guard compare them to the governed allow-list.
        "FROM " + entity_tables[entity] + " AS gda_source",
    ]
    for join_index, added_entity in tree_joins:
        statement_parts.append(
            "JOIN "
            + entity_tables[added_entity]
            + " AS "
            + entity_aliases[added_entity]
            + " ON "
            + join_conditions[join_index]
        )
    where_clauses = [
        *filters_sql,
        *any_filter_groups_sql,
        *(join_conditions[index] for index in residual_join_indexes),
    ]
    if where_clauses:
        statement_parts.append("WHERE " + " AND ".join(where_clauses))
    if has_metric and dimension_sql:
        statement_parts.append("GROUP BY " + ", ".join(dimension_sql))
    if effective_order_by:
        statement_parts.append(
            "ORDER BY "
            + ", ".join(
                _quote_identifier(output_name) + " " + direction.upper()
                for output_name, direction in effective_order_by
            )
        )
    statement_parts.append(f"LIMIT {limit}")
    statement = "\n".join(statement_parts)

    logical_nodes: list[LogicalPlanNode] = [
        LogicalPlanNode(
            node_id="scan_001",
            operator="scan",
            attributes={"semantic_entity": entity},
        )
    ]
    current = "scan_001"
    for ordinal, (join_index, added_entity) in enumerate(tree_joins, start=1):
        scan_node = f"scan_{ordinal + 1:03d}"
        join_node = f"join_{ordinal:03d}"
        join = semantic_ir.joins[join_index]
        logical_nodes.append(
            LogicalPlanNode(
                node_id=scan_node,
                operator="scan",
                attributes={"semantic_entity": added_entity},
            )
        )
        logical_nodes.append(
            LogicalPlanNode(
                node_id=join_node,
                operator="join",
                input_node_ids=(current, scan_node),
                attributes={
                    "kind": join.kind.value,
                    "operator": join.operator,
                    "left_entity": join.left_field_ref.semantic_entity,
                    "right_entity": join.right_field_ref.semantic_entity,
                },
            )
        )
        current = join_node
    if filters_sql or residual_join_indexes:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="filter_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={"predicate_count": len(where_clauses)},
            )
        )
        current = "filter_001"
    if has_metric:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="aggregate_001",
                operator="aggregate",
                input_node_ids=(current,),
                attributes={"group_count": len(dimension_sql)},
            )
        )
        current = "aggregate_001"
    logical_nodes.append(
        LogicalPlanNode(
            node_id="project_001",
            operator="project",
            input_node_ids=(current,),
            attributes={"outputs": [item.output_name for item in semantic_ir.projections]},
        )
    )
    current = "project_001"
    if effective_order_by:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="sort_001",
                operator="sort",
                input_node_ids=(current,),
                attributes={
                    "order_count": len(effective_order_by),
                    "ordering_source": (
                        "compiler_default_bounded_aggregate"
                        if compiler_default_ordering
                        else "semantic_ir"
                    ),
                },
            )
        )
        current = "sort_001"
    logical_nodes.append(
        LogicalPlanNode(
            node_id="limit_001",
            operator="limit",
            input_node_ids=(current,),
            attributes={"row_limit": limit, "enforcement": "sql"},
        )
    )
    logical_plan = SemanticLogicalPlan(
        ir_sha256=ir_sha,
        root_node_id="limit_001",
        nodes=tuple(logical_nodes),
    )
    logical_sha = canonical_json_fingerprint(logical_plan.model_dump(mode="json"))
    physical_columns = tuple(
        sorted(
            {
                f"{str(field.get('physical_table') or '')}."
                f"{str(field.get('physical_field') or '')}"
                for field in [
                    *resolved_projection_fields,
                    *resolved_filter_fields,
                    *resolved_join_fields,
                ]
            }
        )
    )
    physical_plan = SemanticPhysicalPlan(
        compilation_mode="compiled_semantic_ir_experimental",
        logical_plan_sha256=logical_sha,
        statement_sha256=_sha256(statement),
        source_ids=(int(source.get("source_id") or 0),),
        tables=tuple(sorted(entity_tables[item] for item in entity_aliases)),
        columns=physical_columns,
        spatial_operators=tuple(
            sorted(
                {
                    join.operator
                    for join in semantic_ir.joins
                    if join.kind is JoinKind.SPATIAL
                }
            )
        ),
    )
    physical_sha = canonical_json_fingerprint(physical_plan.model_dump(mode="json"))
    return CompiledAdHocSemanticPlanEvidence(
        semantic_ir=semantic_ir,
        validation=validation,
        logical_plan=logical_plan,
        physical_plan=physical_plan,
        compiled_statement=statement,
        parameter_bindings=parameter_bindings,
        compiler_default_ordering=compiler_default_ordering,
        fingerprints={
            "semantic_ir_sha256": ir_sha,
            "logical_plan_sha256": logical_sha,
            "physical_plan_sha256": physical_sha,
            "compiled_statement_sha256": _sha256(statement),
        },
    )


def build_federated_semantic_plan_evidence(
    *,
    question: str,
    language: str,
    semantic_version: str,
    federated_contract_id: str,
    subplans: list[Mapping[str, Any]],
) -> FederatedSemanticPlanEvidence:
    """Build typed evidence for two independently executed metric contracts."""

    try:
        refs: list[FederatedMetricSubplanRef] = []
        for item in subplans:
            report = item.get("report") or {}
            source = report.get("source") or {}
            source_plan = (report.get("query") or {}).get("semantic_plan") or {}
            source_ir = source_plan.get("semantic_ir") or {}
            fingerprints = source_plan.get("fingerprints") or {}
            contract_id = str(item.get("metric_contract_id") or "")
            if source_plan.get("status") != "planned":
                raise ValueError("federated_source_semantic_plan_not_planned")
            if source_ir.get("route") != SemanticQueryRoute.REVIEWED_METRIC_CONTRACT:
                raise ValueError("federated_source_not_reviewed_metric_contract")
            if source_ir.get("metric_contract_id") != contract_id:
                raise ValueError("federated_source_metric_contract_drift")
            refs.append(
                FederatedMetricSubplanRef(
                    source=str(item.get("source") or ""),
                    source_id=int(source.get("source_id") or 0),
                    database_name=str(source.get("database_name") or ""),
                    semantic_version=str(report.get("semantic_version") or ""),
                    metric_contract_version=str(
                        report.get("metric_contract_version") or ""
                    ),
                    metric_contract_id=contract_id,
                    semantic_plan_sha256=str(
                        fingerprints.get("semantic_ir_sha256") or ""
                    ),
                )
            )
        refs.sort(key=lambda item: item.source_id)
        source_ids = tuple(item.source_id for item in refs)
        ir = FederatedSemanticQueryIR(
            semantic_version=semantic_version,
            federated_contract_id=federated_contract_id,
            task_frame=SemanticTaskFrame(
                question_sha256=_sha256(question),
                language=language,
                operation=SemanticOperation.AGGREGATE,
                source_ids=source_ids,
            ),
            subplans=tuple(refs),
        )
        ir_sha = canonical_json_fingerprint(ir.model_dump(mode="json"))
        checks = (
            ValidationCheck(
                check_id="two_independent_sources",
                passed=len(refs) == 2 and len(set(source_ids)) == 2,
            ),
            ValidationCheck(
                check_id="reviewed_metric_contract_refs",
                passed=all(bool(item.metric_contract_id) for item in refs),
            ),
            ValidationCheck(
                check_id="source_semantic_plans_validated",
                passed=all(item.semantic_plan_status == "planned" for item in refs),
            ),
            ValidationCheck(
                check_id="independent_sections_merge",
                passed=ir.merge_strategy is FederatedMergeStrategy.INDEPENDENT_SECTIONS,
            ),
            ValidationCheck(
                check_id="cross_database_sql_disabled",
                passed=ir.cross_database_sql is False,
            ),
            ValidationCheck(
                check_id="cross_source_join_disabled",
                passed=ir.cross_source_join is False,
            ),
        )
        reason_codes = tuple(check.check_id for check in checks if not check.passed)
        validation = FederatedIRValidationReport(
            valid=not reason_codes,
            ir_sha256=ir_sha,
            checks=checks,
            reason_codes=reason_codes,
        )
        if not validation.valid:
            raise ValueError(
                "federated_ir_validation_failed:" + ",".join(reason_codes)
            )
        nodes = tuple(
            FederatedLogicalPlanNode(
                node_id=f"subplan_{index:03d}",
                operator="metric_contract_subplan",
                attributes={
                    "source": item.source,
                    "source_id": item.source_id,
                    "metric_contract_id": item.metric_contract_id,
                    "semantic_plan_sha256": item.semantic_plan_sha256,
                },
            )
            for index, item in enumerate(refs, start=1)
        )
        logical_plan = FederatedSemanticLogicalPlan(
            ir_sha256=ir_sha,
            root_node_id="merge_001",
            nodes=(
                *nodes,
                FederatedLogicalPlanNode(
                    node_id="merge_001",
                    operator="independent_sections_merge",
                    input_node_ids=tuple(item.node_id for item in nodes),
                    attributes={
                        "cross_database_sql": False,
                        "cross_source_join": False,
                    },
                ),
            ),
        )
        logical_sha = canonical_json_fingerprint(
            logical_plan.model_dump(mode="json")
        )
        physical_plan = FederatedApplicationPhysicalPlan(
            logical_plan_sha256=logical_sha,
            source_ids=source_ids,
            source_plan_sha256s=tuple(item.semantic_plan_sha256 for item in refs),
            merge_strategy=FederatedMergeStrategy.INDEPENDENT_SECTIONS,
        )
        physical_sha = canonical_json_fingerprint(
            physical_plan.model_dump(mode="json")
        )
        return FederatedSemanticPlanEvidence(
            status="planned",
            semantic_ir=ir,
            validation=validation,
            logical_plan=logical_plan,
            physical_plan=physical_plan,
            fingerprints={
                "semantic_ir_sha256": ir_sha,
                "logical_plan_sha256": logical_sha,
                "physical_plan_sha256": physical_sha,
            },
        )
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        return FederatedSemanticPlanEvidence(
            status="legacy_fallback",
            fallback_reason=f"federated_plan_unavailable:{reason}"[:256],
        )


__all__ = [
    "AdHocSemanticQueryIR",
    "CertifiedMetricContractPlanEvidence",
    "CompiledAdHocSemanticPlanEvidence",
    "FederatedApplicationPhysicalPlan",
    "FederatedIRValidationReport",
    "FederatedMergeStrategy",
    "FederatedMetricSubplanRef",
    "FederatedSemanticLogicalPlan",
    "FederatedSemanticPlanEvidence",
    "FederatedSemanticQueryIR",
    "JoinKind",
    "ProjectionRole",
    "SemanticAggregate",
    "SemanticFilter",
    "SemanticIRCompilationError",
    "SemanticIRValidationReport",
    "SemanticIROrder",
    "SemanticIRProjection",
    "SemanticLogicalPlan",
    "SemanticModelFieldRef",
    "SemanticOperation",
    "SemanticPhysicalPlan",
    "SemanticQueryIR",
    "SemanticQueryRoute",
    "ShadowSemanticPlanEvidence",
    "build_compiled_ad_hoc_semantic_plan",
    "build_semantic_logical_plan",
    "build_federated_semantic_plan_evidence",
    "build_certified_metric_contract_plan",
    "build_shadow_semantic_plan_evidence",
    "validate_semantic_query_ir",
]
