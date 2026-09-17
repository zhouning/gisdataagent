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
import unicodedata
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import canonical_json_fingerprint
from .semantic_projection_policy import (
    ProjectionCompletenessPolicyError,
    policy_matches_question,
    question_is_entity_list,
    question_requests_explicit_attributes,
    resolve_projection_completeness_policies,
    validate_projection_completeness_policies,
)


class DerivedProjectionPolicyError(ValueError):
    """A published derived-projection policy is invalid or unsafe."""


class AggregateIdentityProjectionPolicyError(ValueError):
    """A published aggregate identity-projection policy is invalid or unsafe."""


class DetailIdentityProjectionPolicyError(ValueError):
    """A published detail identity-projection policy is invalid or unsafe."""


class TwoValueComparisonPolicyError(ValueError):
    """A published categorical two-value comparison policy is unsafe."""


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
    MEDIAN = "median"


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
        r"(?:\b(?:within(?![-‐‑–—])|inside|contained|located\s+in|in\s+the\s+boundary)\b|"
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


_EXPLICIT_NUMERIC_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_])"
)


def _normalized_numeric_literals(value: Any) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    candidates = (
        [str(value)]
        if isinstance(value, (int, float))
        else _EXPLICIT_NUMERIC_LITERAL_RE.findall(str(value))
    )
    normalized: set[str] = set()
    for candidate in candidates:
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        normalized.add(format(number, ".15g"))
    return normalized


def _validate_explicit_question_numeric_literals(
    semantic_ir: AdHocSemanticQueryIR,
    question: str | None,
    semantic_layer: Mapping[str, Any] | None = None,
) -> None:
    """Reject a typed plan that silently drops an explicit user number."""

    if not question or semantic_ir.status != "query":
        return
    requested = _normalized_numeric_literals(question)
    if not requested:
        return
    represented: set[str] = set()
    if semantic_ir.limit is not None:
        represented.update(_normalized_numeric_literals(semantic_ir.limit))
    if semantic_ir.partition_limit is not None:
        represented.update(_normalized_numeric_literals(semantic_ir.partition_limit))
    for expression in semantic_ir.result_expressions:
        represented.update(_normalized_numeric_literals(expression.scale))
    for statistic in semantic_ir.partition_statistics:
        represented.update(_normalized_numeric_literals(statistic.value_filter_value))
        if statistic.percentile is not None:
            represented.update(_normalized_numeric_literals(statistic.percentile))
            represented.update(_normalized_numeric_literals(statistic.percentile * 100))
    for expression in semantic_ir.post_statistic_expressions:
        represented.update(_normalized_numeric_literals(expression.scale))
    for result_filter in (
        *semantic_ir.result_filters,
        *semantic_ir.post_window_filters,
    ):
        for value in result_filter.values:
            represented.update(_normalized_numeric_literals(value))
    for filter_spec in (*semantic_ir.filters, *semantic_ir.having_filters):
        for value in filter_spec.values:
            represented.update(_normalized_numeric_literals(value))
    for group in semantic_ir.any_filter_groups:
        for filter_spec in group.filters:
            for value in filter_spec.values:
                represented.update(_normalized_numeric_literals(value))
    for condition in semantic_ir.universal_conditions:
        for value in condition.values:
            represented.update(_normalized_numeric_literals(value))
    for join in semantic_ir.joins:
        if join.distance_metres is not None:
            represented.update(_normalized_numeric_literals(join.distance_metres))
    if semantic_ir.band_summary is not None:
        for band in semantic_ir.band_summary.bands:
            represented.update(_normalized_numeric_literals(band.lower))
            represented.update(_normalized_numeric_literals(band.upper))
    # A business number can be represented by a reviewed categorical/value
    # alias rather than a raw numeric predicate.  For example, ``50% target``
    # is represented by the reviewed ``needed_ap50``/``target_50pct`` field or
    # an ``AP50`` stage value.  Consult only metadata attached to fields that
    # the proposed IR actually references; unrelated catalog numbers cannot
    # satisfy this check.  This keeps the guard strict for an unbound ``90%``
    # threshold while allowing source-backed semantic encodings.
    if semantic_layer:
        referenced = {
            (ref.semantic_entity, ref.semantic_field)
            for ref in (
                [item.field_ref for item in semantic_ir.projections if item.field_ref is not None]
                + [item.field_ref for item in semantic_ir.filters]
                + [item.field_ref for item in semantic_ir.having_filters]
                + [item.field_ref for group in semantic_ir.any_filter_groups for item in group.filters]
                + [field_ref for join in semantic_ir.joins for field_ref in (join.left_field_ref, join.right_field_ref)]
                + (
                    [
                        semantic_ir.band_summary.score_field_ref,
                        semantic_ir.band_summary.member_field_ref,
                        *semantic_ir.band_summary.member_disambiguation_field_refs,
                    ]
                    if semantic_ir.band_summary is not None
                    else []
                )
            )
            if ref is not None
        }
        if referenced:
            # Resolve logical field aliases before inspecting their reviewed
            # metadata.  Providers may emit a reviewed business alias (for
            # example ``target_need``) instead of the canonical field token;
            # the compiler will still perform the authoritative field
            # resolution later.  This pass only decides whether an explicit
            # question number is represented by an unambiguous, source-backed
            # field, and therefore must fail closed on ambiguous aliases.
            def alias_key(value: Any) -> str:
                return re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE).strip()

            def field_aliases(field: Mapping[str, Any]) -> set[str]:
                values = {
                    field.get("semantic_field"),
                    field.get("physical_field"),
                    *(field.get("aliases") or ()),
                    *((field.get("labels") or {}).values()),
                }
                return {key for value in values if (key := alias_key(value))}

            for binding in semantic_layer.get("table_bindings") or ():
                if not isinstance(binding, Mapping):
                    continue
                entity = str(binding.get("semantic_entity") or "")
                entity_aliases = {
                    alias_key(entity),
                    alias_key(binding.get("physical_table")),
                    alias_key(binding.get("business_asset_id")),
                    *(alias_key(value) for value in (binding.get("aliases") or ())),
                    *(
                        alias_key(value)
                        for value in (binding.get("labels") or {}).values()
                    ),
                }
                binding_fields = [
                    field
                    for field in (binding.get("fields") or ())
                    if isinstance(field, Mapping)
                ]
                reference_candidates = {
                    ref: [
                        field
                        for field in binding_fields
                        if alias_key(ref[1]) in field_aliases(field)
                    ]
                    for ref in referenced
                    if alias_key(ref[0]) in entity_aliases
                }
                for field in binding_fields:
                    if not isinstance(field, Mapping):
                        continue
                    field_name = str(field.get("semantic_field") or "")
                    matching_refs = [
                        ref
                        for ref in referenced
                        if len(reference_candidates.get(ref) or []) == 1
                        and (reference_candidates.get(ref) or [None])[0] is field
                    ]
                    if not matching_refs:
                        continue
                    metadata: list[Any] = [
                        field_name,
                        field.get("physical_field"),
                        field.get("definition"),
                        field.get("description"),
                        field.get("aliases"),
                        field.get("value_domain"),
                        field.get("value_semantics"),
                    ]
                    for item in metadata:
                        if isinstance(item, Mapping):
                            metadata.extend(item.keys())
                            metadata.extend(item.values())
                    for item in metadata:
                        for number in _normalized_numeric_literals(item):
                            if number in requested:
                                represented.add(number)
    missing = sorted(requested - represented)
    if missing:
        raise SemanticIRCompilationError(
            "semantic_ir_explicit_numeric_literal_missing:" + ",".join(missing)
        )


def _repair_reviewed_numeric_alias_field_references(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    question: str | None,
) -> AdHocSemanticQueryIR:
    """Bind a measure to an explicit reviewed numeric alias when unambiguous.

    A local model may select a sibling measure (for example a current gap)
    while the question explicitly names a reviewed target alias (for example
    ``50% target``).  The repair is metadata-driven: it requires one and only
    one measure in each referenced entity to publish that numeric alias and
    only rewrites references to sibling measure fields.  Dimensions, joins,
    values, and aggregates are never invented.  Ambiguous aliases remain
    unchanged and fail closed through the normal numeric-literal validator.
    """

    if not question or semantic_ir.status != "query":
        return semantic_ir
    requested = _normalized_numeric_literals(question)
    if not requested:
        return semantic_ir

    # Collect entities and measure references already present in the proposal.
    referenced_entities: set[str] = set()
    for projection in semantic_ir.projections:
        if projection.field_ref is not None:
            referenced_entities.add(projection.field_ref.semantic_entity)
    for item in (*semantic_ir.filters, *semantic_ir.having_filters, *semantic_ir.universal_conditions):
        referenced_entities.add(item.field_ref.semantic_entity)
    for group in semantic_ir.any_filter_groups:
        referenced_entities.update(item.field_ref.semantic_entity for item in group.filters)
    if semantic_ir.band_summary is not None:
        referenced_entities.update(
            reference.semantic_entity
            for reference in (
                semantic_ir.band_summary.score_field_ref,
                semantic_ir.band_summary.member_field_ref,
                *semantic_ir.band_summary.member_disambiguation_field_refs,
            )
        )
    if not referenced_entities:
        return semantic_ir

    def numeric_aliases(field: Mapping[str, Any]) -> set[str]:
        aliases: set[str] = set()
        semantics = field.get("value_semantics")
        if isinstance(semantics, Mapping):
            raw = semantics.get("reviewed_numeric_aliases")
            values = raw if isinstance(raw, (list, tuple, set)) else [raw]
            for value in values:
                aliases.update(_normalized_numeric_literals(value))
        # Flattened card exporters may publish the same metadata under a
        # top-level alias list.  Only numeric-bearing entries qualify.
        for value in field.get("reviewed_numeric_aliases") or ():
            aliases.update(_normalized_numeric_literals(value))
        return aliases

    alias_candidates: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for binding in semantic_layer.get("table_bindings") or ():
        if not isinstance(binding, Mapping):
            continue
        entity = str(binding.get("semantic_entity") or "")
        if entity not in referenced_entities:
            continue
        for field in binding.get("fields") or ():
            if not isinstance(field, Mapping) or str(field.get("business_role") or "").casefold() not in {"measure", "metric"}:
                continue
            field_name = str(field.get("semantic_field") or "")
            if not field_name:
                continue
            if requested.intersection(numeric_aliases(field)):
                alias_candidates.setdefault(entity, []).append((field_name, field))

    # Resolve same-entity aliases using published business wording, not a
    # table/question special case.  The field whose reviewed aliases and
    # labels best overlap the user phrase wins only when it is strictly
    # better; ties remain ambiguous and therefore fail closed.
    alias_fields: dict[str, tuple[str, Mapping[str, Any]]] = {}
    question_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", str(question).casefold())
        if len(token) > 1
    }
    for entity, candidates in alias_candidates.items():
        if len(candidates) == 1:
            alias_fields[entity] = candidates[0]
            continue
        scored: list[tuple[int, str, Mapping[str, Any]]] = []
        for field_name, field in candidates:
            text = " ".join(
                [
                    field_name,
                    *(str(value) for value in field.get("aliases") or ()),
                    *(str(value) for value in (field.get("labels") or {}).values()),
                    str(field.get("definition") or ""),
                ]
            ).casefold()
            field_tokens = set(re.findall(r"[a-z0-9]+", text))
            score = len(question_tokens.intersection(field_tokens))
            scored.append((score, field_name, field))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            alias_fields[entity] = (scored[0][1], scored[0][2])

    if not alias_fields:
        return semantic_ir

    def field_metadata(entity: str, field_name: str) -> Mapping[str, Any] | None:
        for binding in semantic_layer.get("table_bindings") or ():
            if not isinstance(binding, Mapping) or str(binding.get("semantic_entity") or "") != entity:
                continue
            for field in binding.get("fields") or ():
                if isinstance(field, Mapping) and str(field.get("semantic_field") or "") == field_name:
                    return field
        return None

    def target_for(entity: str) -> tuple[str, Mapping[str, Any]] | None:
        value = alias_fields.get(entity)
        if not value or not value[0]:
            return None
        return value

    # Preserve a sibling measure when the condition's own clause explicitly
    # names that reviewed measure (for example ``existing ... = 0``). The
    # broad numeric-alias binding below must not rewrite every predicate in a
    # compound question to one target field.
    clauses = [
        " ".join(chunk.split())
        for chunk in re.split(
            r"\b(?:but|and|or|while|whereas|then|after|before)\b|[;,.!?]|\s+—\s+|\s+-\s+",
            str(question).casefold(),
        )
        if chunk.strip()
    ]

    def lexical_tokens(field: Mapping[str, Any]) -> set[str]:
        values: list[Any] = [
            field.get("semantic_field"),
            field.get("physical_field"),
            *(field.get("aliases") or ()),
            *((field.get("labels") or {}).values()),
        ]
        return {
            token
            for value in values
            for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
            if len(token) > 1
        }

    ordered_numeric_filters = [
        item
        for item in (*semantic_ir.filters, *semantic_ir.having_filters)
        if item.values
        and isinstance(item.values[0], (int, float))
        and not isinstance(item.values[0], bool)
    ]
    protected_filter_indexes: set[int] = set()
    for index, item in enumerate(ordered_numeric_filters):
        current_metadata = field_metadata(item.field_ref.semantic_entity, item.field_ref.semantic_field)
        target = target_for(item.field_ref.semantic_entity)
        if current_metadata is None or target is None:
            continue
        clause = clauses[min(index, len(clauses) - 1)] if clauses else str(question).casefold()
        clause_tokens = {
            token for token in re.findall(r"[a-z0-9]+", clause) if len(token) > 1
        }
        current_score = len(clause_tokens.intersection(lexical_tokens(current_metadata)))
        target_score = len(clause_tokens.intersection(lexical_tokens(target[1])))
        if current_score > 0 and current_score >= target_score:
            protected_filter_indexes.add(index)

    updates: dict[str, Any] = {}
    changed = False
    projections: list[dict[str, Any]] = []
    for projection in semantic_ir.projections:
        item = projection.model_dump(mode="python")
        ref = projection.field_ref
        target = target_for(ref.semantic_entity) if ref is not None else None
        if ref is not None and target is not None:
            target_field, _metadata = target
            if (
                projection.role is ProjectionRole.METRIC
                and ref.semantic_field != target_field
            ):
                item["field_ref"] = {
                    "semantic_entity": ref.semantic_entity,
                    "semantic_field": target_field,
                }
                changed = True
        projections.append(item)

    filter_numeric_index = 0

    def replace_filter(item: SemanticFilter | SemanticHavingFilter) -> dict[str, Any]:
        nonlocal changed
        nonlocal filter_numeric_index
        value = item.model_dump(mode="python")
        target = target_for(item.field_ref.semantic_entity)
        current_metadata = field_metadata(item.field_ref.semantic_entity, item.field_ref.semantic_field)
        current_role = str((current_metadata or {}).get("business_role") or "").casefold()
        is_numeric_filter = bool(
            item.values
            and isinstance(item.values[0], (int, float))
            and not isinstance(item.values[0], bool)
        )
        current_index = filter_numeric_index
        if is_numeric_filter:
            filter_numeric_index += 1
        if (
            target is not None
            and current_role in {"measure", "metric"}
            and str(item.field_ref.semantic_field) != target[0]
            and current_index not in protected_filter_indexes
        ):
            value["field_ref"] = {
                "semantic_entity": item.field_ref.semantic_entity,
                "semantic_field": target[0],
            }
            changed = True
        return value

    updates["projections"] = projections
    updates["filters"] = [replace_filter(item) for item in semantic_ir.filters]
    updates["having_filters"] = [replace_filter(item) for item in semantic_ir.having_filters]
    updates["universal_conditions"] = [replace_filter(item) for item in semantic_ir.universal_conditions]
    updates["any_filter_groups"] = [
        {
            **group.model_dump(mode="python"),
            "filters": [replace_filter(item) for item in group.filters],
        }
        for group in semantic_ir.any_filter_groups
    ]
    if not changed:
        return semantic_ir
    return AdHocSemanticQueryIR.model_validate(
        {**semantic_ir.model_dump(mode="python"), **updates}
    )


def _repair_reviewed_measure_filters_from_question(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    question: str | None,
) -> AdHocSemanticQueryIR:
    """Align numeric filter fields to reviewed measure wording in each clause.

    Smaller local models sometimes reuse one measure for several predicates in
    a compound question (for example ``existing = 0`` and ``target need > 0``
    both become the target-gap field).  This repair only addresses that
    representation error.  It uses the reviewed field labels/aliases and the
    clause containing each condition; it never creates a field, value, join,
    aggregate, or relationship.  A replacement is accepted only when one
    reviewed sibling measure scores strictly above every other candidate.
    Ambiguous conditions are left untouched and therefore fail closed.
    """

    if not question or semantic_ir.status != "query":
        return semantic_ir

    def field_metadata(entity: str, field_name: str) -> Mapping[str, Any] | None:
        for binding in semantic_layer.get("table_bindings") or ():
            if not isinstance(binding, Mapping) or str(binding.get("semantic_entity") or "") != entity:
                continue
            for field in binding.get("fields") or ():
                if isinstance(field, Mapping) and str(field.get("semantic_field") or "") == field_name:
                    return field
        return None

    def field_tokens(field: Mapping[str, Any], *, include_definition: bool = False) -> set[str]:
        values: list[Any] = [
            field.get("semantic_field"),
            field.get("physical_field"),
            *(field.get("aliases") or ()),
            *((field.get("labels") or {}).values()),
        ]
        if include_definition:
            values.extend(
                [field.get("definition"), field.get("description"), field.get("semantic_resolution_note")]
            )
        tokens: set[str] = set()
        for value in values:
            tokens.update(
                token
                for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
                if len(token) > 1
            )
        return tokens

    def question_clauses(value: str) -> list[str]:
        # Conjunctions and punctuation are the only structure used here.  The
        # model's filter order is retained, while no benchmark-specific text
        # or expected answer is consulted.
        chunks = re.split(
            r"\b(?:but|and|or|while|whereas|then|after|before)\b|[;,.!?]|\s+—\s+|\s+-\s+",
            value.casefold(),
        )
        return [" ".join(chunk.split()) for chunk in chunks if chunk.strip()]

    normalized_question = " ".join(str(question).casefold().split())
    clauses = question_clauses(normalized_question)
    if not clauses:
        return semantic_ir

    def condition_tokens(item: SemanticFilter | SemanticHavingFilter) -> set[str]:
        tokens: set[str] = set()
        operator = str(item.operator).casefold()
        value = item.values[0] if item.values else None
        if operator in {"gt", "gte"}:
            tokens.update({"positive", "above", "over", "greater", "more", "exceed", "exceeds"})
        elif operator in {"lt", "lte"}:
            tokens.update({"below", "under", "less", "fewer", "lower"})
        elif operator == "eq":
            tokens.update({"equal", "equals", "exactly", "zero", "none", "no", "without", "absent"})
            # A zero/none predicate over a reviewed facility measure normally
            # describes an existence count ("zero X"), not a KPI score.  The
            # ``count`` token is only a lexical tie-breaker; the candidate
            # still has to be a reviewed sibling measure and strictly lead.
            if value in (0, 0.0, "0"):
                tokens.add("count")
        if value is not None:
            tokens.update(
                token
                for token in re.findall(r"[a-z0-9]+", str(value).casefold())
                if len(token) > 1
            )
        return tokens

    # Numeric predicate order is the only binding between IR conditions and
    # natural-language clauses.  This is deliberately conservative: if there
    # are fewer clauses than predicates, all predicates share the full text
    # and only a strict metadata match can still qualify.
    numeric_items: list[SemanticFilter | SemanticHavingFilter] = [
        item
        for item in (*semantic_ir.filters, *semantic_ir.having_filters)
        if item.values
        and isinstance(item.values[0], (int, float))
        and not isinstance(item.values[0], bool)
        and field_metadata(item.field_ref.semantic_entity, item.field_ref.semantic_field) is not None
    ]
    if not numeric_items:
        return semantic_ir

    replacements: dict[tuple[str, str, int], str] = {}
    for index, item in enumerate(numeric_items):
        current_name = item.field_ref.semantic_field
        current_metadata = field_metadata(item.field_ref.semantic_entity, current_name)
        if current_metadata is None or str(current_metadata.get("business_role") or "").casefold() not in {"measure", "metric"}:
            continue
        candidates: list[tuple[str, Mapping[str, Any]]] = []
        for binding in semantic_layer.get("table_bindings") or ():
            if not isinstance(binding, Mapping) or str(binding.get("semantic_entity") or "") != item.field_ref.semantic_entity:
                continue
            for field in binding.get("fields") or ():
                if not isinstance(field, Mapping):
                    continue
                if str(field.get("business_role") or "").casefold() not in {"measure", "metric"}:
                    continue
                name = str(field.get("semantic_field") or "")
                if name:
                    candidates.append((name, field))
        if len(candidates) < 2:
            continue

        # Use the corresponding clause, but include condition words so a
        # measure label such as "existing" can distinguish two zero tests.
        clause = clauses[min(index, len(clauses) - 1)]
        clause_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", clause)
            if len(token) > 1
        }
        clause_tokens.update(condition_tokens(item))
        scored: list[tuple[int, str]] = []
        for name, field in candidates:
            tokens = field_tokens(field)
            # Labels/aliases are the authoritative lexical evidence.  The
            # field identifier gets no extra weight beyond token overlap.
            score = len(clause_tokens.intersection(tokens))
            # Keep the current field on equal evidence; strict lead below is
            # required before any rewrite is accepted.
            scored.append((score, name))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        if not scored or scored[0][0] <= 0:
            continue
        if len(scored) > 1 and scored[0][0] <= scored[1][0]:
            continue
        if scored[0][1] != current_name:
            replacements[(item.field_ref.semantic_entity, current_name, index)] = scored[0][1]

    if not replacements:
        return semantic_ir

    # The numeric-item index spans WHERE filters followed by HAVING filters.
    numeric_index = 0

    def replace_item(item: SemanticFilter | SemanticHavingFilter) -> dict[str, Any]:
        nonlocal numeric_index
        value = item.model_dump(mode="python")
        if (
            item.values
            and isinstance(item.values[0], (int, float))
            and not isinstance(item.values[0], bool)
            and field_metadata(item.field_ref.semantic_entity, item.field_ref.semantic_field) is not None
        ):
            key = (item.field_ref.semantic_entity, item.field_ref.semantic_field, numeric_index)
            target = replacements.get(key)
            numeric_index += 1
            if target:
                value["field_ref"] = {
                    "semantic_entity": item.field_ref.semantic_entity,
                    "semantic_field": target,
                }
        return value

    return AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "filters": [replace_item(item) for item in semantic_ir.filters],
            "having_filters": [replace_item(item) for item in semantic_ir.having_filters],
        }
    )


def _drop_redundant_universal_having_filters(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> AdHocSemanticQueryIR:
    """Remove an aggregate predicate proven redundant by a universal policy.

    Providers sometimes emit both ``AVG(score) = 100`` in ``having_filters``
    and a reviewed universal condition ``every score >= 100``.  For a field
    whose reviewed numeric validity declares an upper bound of 100, the
    universal condition already implies the aggregate equality.  Dropping
    that duplicate avoids a compiler conflict without weakening semantics.
    All decisions come from field metadata; absent or ambiguous bounds leave
    the original predicate intact and the compiler fails closed.
    """

    if semantic_ir.status != "query" or not semantic_ir.universal_conditions or not semantic_ir.having_filters:
        return semantic_ir

    def field_metadata(entity: str, field_name: str) -> Mapping[str, Any] | None:
        for binding in semantic_layer.get("table_bindings") or ():
            if not isinstance(binding, Mapping) or str(binding.get("semantic_entity") or "") != entity:
                continue
            for field in binding.get("fields") or ():
                if isinstance(field, Mapping) and str(field.get("semantic_field") or "") == field_name:
                    return field
        return None

    def reviewed_upper_bound(field: Mapping[str, Any]) -> float | None:
        validity = field.get("numeric_validity")
        if not isinstance(validity, Mapping):
            return None
        # Prefer explicit structured metadata when available.
        for key in ("upper_bound", "maximum", "max"):
            value = validity.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        # Existing published cards may encode the interval as ``(0, 100]``.
        for value in validity.values():
            if not isinstance(value, str):
                continue
            match = re.search(r",\s*([+-]?\d+(?:\.\d+)?)\s*\]", value)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    universal = semantic_ir.universal_conditions[0]
    metadata = field_metadata(universal.field_ref.semantic_entity, universal.field_ref.semantic_field)
    upper = reviewed_upper_bound(metadata) if metadata is not None else None
    if upper is None or universal.operator not in {"gte", "eq"} or not universal.values:
        return semantic_ir
    try:
        universal_value = float(universal.values[0])
    except (TypeError, ValueError):
        return semantic_ir
    if universal_value != upper:
        return semantic_ir

    kept: list[SemanticHavingFilter] = []
    removed = False
    for having in semantic_ir.having_filters:
        if (
            having.field_ref == universal.field_ref
            and having.aggregate is SemanticAggregate.AVG
            and having.operator == "eq"
            and having.values
        ):
            try:
                if float(having.values[0]) == upper:
                    removed = True
                    continue
            except (TypeError, ValueError):
                pass
        kept.append(having)
    # The universal compiler returns one row per reviewed group and therefore
    # intentionally has no metric projection.  Local providers commonly emit
    # an ``AVG`` of the same condition field merely to display the threshold
    # they used in the universal predicate.  Once the reviewed upper bound
    # proves that predicate equivalent to the universal condition, that
    # metric is redundant and can be removed.  Restrict this repair to the
    # condition field and the same aggregate that was proven redundant above;
    # unrelated metrics are left untouched and continue to fail closed via
    # the universal projection-shape validator.
    projections: list[dict[str, Any]] = []
    metric_removed = False
    for projection in semantic_ir.projections:
        if (
            projection.role is ProjectionRole.METRIC
            and projection.aggregate is SemanticAggregate.AVG
            and projection.field_ref == universal.field_ref
        ):
            metric_removed = True
            continue
        projections.append(projection.model_dump(mode="python"))
    if not removed and not metric_removed:
        return semantic_ir
    return AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "having_filters": kept,
            "projections": projections,
        }
    )


def _repair_universal_group_projection(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> AdHocSemanticQueryIR:
    """Align a universal query's sole grouping dimension to its reviewed policy.

    The universal policy is the semantic authority for the grouped entity. If
    a provider projects exactly one dimension from that same entity but uses a
    sibling dimension, replace only the field reference with the policy's
    declared ``group_field``. Multiple dimensions or cross-entity shapes are
    left untouched and remain rejected by the compiler.
    """

    if semantic_ir.status != "query" or len(semantic_ir.universal_conditions) != 1:
        return semantic_ir
    condition = semantic_ir.universal_conditions[0]
    policies = [
        policy
        for policy in semantic_layer.get("universal_quantification_policies") or ()
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("policy_id") or "") == condition.policy_id
    ]
    if len(policies) != 1:
        return semantic_ir
    policy = policies[0]
    entity = str(policy.get("semantic_entity") or "")
    group_field = str(policy.get("group_field") or "")
    if not entity or not group_field:
        return semantic_ir
    projected_group = [
        item
        for item in semantic_ir.projections
        if item.role is ProjectionRole.DIMENSION
        and item.field_ref is not None
        and item.field_ref.semantic_entity == entity
    ]
    if len(projected_group) != 1:
        return semantic_ir
    if projected_group[0].field_ref.semantic_field == group_field:
        return semantic_ir
    projections: list[dict[str, Any]] = []
    for item in semantic_ir.projections:
        value = item.model_dump(mode="python")
        if item is projected_group[0]:
            value["field_ref"] = {
                "semantic_entity": entity,
                "semantic_field": group_field,
            }
        projections.append(value)
    return AdHocSemanticQueryIR.model_validate(
        {**semantic_ir.model_dump(mode="python"), "projections": projections}
    )


def _repair_partitioned_ranking_from_question(
    semantic_ir: AdHocSemanticQueryIR,
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Turn an unambiguous per-group Top-N proposal into partitioned ranking.

    Instruction-tuned models sometimes preserve the requested dimension,
    ranking direction and N but attach N as a global limit.  The repair is
    deliberately narrow: the question must explicitly say each/every, the IR
    must already contain one multi-value dimension filter, an ordered metric,
    and a global limit, and no partition/extreme operation may be present.
    No field, value, ordering, or numeric literal is invented here.
    """

    if (
        not question
        or semantic_ir.status != "query"
        or semantic_ir.limit is None
        or semantic_ir.partition_by
        or semantic_ir.partition_limit is not None
        or semantic_ir.extreme_order_by
        or not semantic_ir.order_by
    ):
        return semantic_ir, ()
    per_group_patterns = {
        "en": r"\b(?:for|within|in)\s+(?:each|every)\b|\bper\s+(?:each|every)\b",
        "zh": r"(?:每个|每一|各个|各自|分别)",
        "ar": r"(?:لكل|في\s+كل|ضمن\s+كل)",
    }
    ranking_patterns = {
        "en": r"\b(?:top|highest|lowest|largest|smallest|most|least)\b",
        "zh": r"(?:前\s*\d*|最高|最低|最大|最小|最多|最少)",
        "ar": r"(?:الأعلى|الأدنى|الأكثر|الأقل|أكبر|أصغر)",
    }
    language = semantic_ir.language
    if not re.search(per_group_patterns.get(language, r"$^"), question, re.IGNORECASE):
        return semantic_ir, ()
    if not re.search(ranking_patterns.get(language, r"$^"), question, re.IGNORECASE):
        return semantic_ir, ()

    multi_value_filter_refs = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in semantic_ir.filters
        if item.operator == "in" and len(item.values) >= 2
    }
    partition_candidates = [
        projection.output_name
        for projection in semantic_ir.projections
        if projection.role is ProjectionRole.DIMENSION
        and projection.field_ref is not None
        and (
            projection.field_ref.semantic_entity,
            projection.field_ref.semantic_field,
        )
        in multi_value_filter_refs
    ]
    if len(partition_candidates) != 1:
        return semantic_ir, ()

    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "partition_by": partition_candidates,
            "partition_limit": semantic_ir.limit,
            "limit": None,
        }
    )
    return effective, ("semantic_ir_promoted_unambiguous_partitioned_ranking",)


def _explicit_numeric_band_specs(
    question: str,
    language: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse a complete, explicitly worded numeric-band partition.

    The first repair slice supports the common English forms ``high above
    75``, ``medium from 50 to 75``, and ``low below 50``. Every label and
    bound comes from the question; incomplete or overlapping shapes are left
    to the normal retry path.
    """

    if language != "en" or not re.search(r"\bbands?\b", question, re.IGNORECASE):
        return [], None
    number = r"-?\d+(?:\.\d+)?"
    patterns = (
        (
            re.compile(
                rf"\b(?P<label>[A-Za-z][A-Za-z0-9_-]{{0,31}})\s+"
                rf"(?:scores?\s+)?(?:above|over|greater\s+than)\s+"
                rf"(?P<lower>{number})\s*%?",
                re.IGNORECASE,
            ),
            "lower",
        ),
        (
            re.compile(
                rf"\b(?P<label>[A-Za-z][A-Za-z0-9_-]{{0,31}})\s+"
                rf"(?:scores?\s+)?(?:from|between)\s+(?P<lower>{number})\s*%?"
                rf"\s+(?:to|and)\s+(?P<upper>{number})\s*%?",
                re.IGNORECASE,
            ),
            "range",
        ),
        (
            re.compile(
                rf"\b(?P<label>[A-Za-z][A-Za-z0-9_-]{{0,31}})\s+"
                rf"(?:scores?\s+)?(?:below|under|less\s+than)\s+"
                rf"(?P<upper>{number})\s*%?",
                re.IGNORECASE,
            ),
            "upper",
        ),
    )
    parsed: list[tuple[int, dict[str, Any]]] = []
    seen_labels: set[str] = set()
    for pattern, shape in patterns:
        for match in pattern.finditer(question):
            label = match.group("label")
            key = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_-").casefold()
            if not key or key in seen_labels:
                return [], None
            item: dict[str, Any] = {"key": key, "label": label}
            if shape in {"lower", "range"}:
                item["lower"] = float(match.group("lower"))
                item["lower_inclusive"] = shape == "range"
            if shape in {"upper", "range"}:
                item["upper"] = float(match.group("upper"))
                item["upper_inclusive"] = shape == "range"
            parsed.append((match.start(), item))
            seen_labels.add(key)
    parsed.sort(key=lambda value: value[0])
    bands = [item for _position, item in parsed]
    if not 2 <= len(bands) <= 8:
        return [], None
    if sum("lower" not in item for item in bands) != 1:
        return [], None
    if sum("upper" not in item for item in bands) != 1:
        return [], None

    member_match = re.search(
        r"\bwhich\b[^.?!]{0,100}?\b(?:in|within)\s+(?:the\s+)?"
        r"(?P<label>[A-Za-z][A-Za-z0-9_-]{0,31})\s+band\b",
        question,
        re.IGNORECASE,
    )
    member_band = member_match.group("label").casefold() if member_match else None
    if member_band not in {item["key"] for item in bands}:
        return [], None
    return bands, member_band


def _repair_numeric_band_summary_from_question(
    semantic_ir: AdHocSemanticQueryIR,
    question: str | None,
    semantic_layer: Mapping[str, Any],
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Promote a lossless ordinary projection spelling to ``band_summary``."""

    if (
        not question
        or semantic_ir.status != "query"
        or semantic_ir.band_summary is not None
        or not 3 <= len(semantic_ir.projections) <= 8
        or semantic_ir.having_filters
        or semantic_ir.universal_conditions
        or semantic_ir.order_by
        or semantic_ir.extreme_order_by
        or semantic_ir.partition_by
        or semantic_ir.partition_limit is not None
        or semantic_ir.distinct_rows
    ):
        return semantic_ir, ()
    normalized_question = " ".join(question.casefold().split())
    if not (
        re.search(r"\b(?:how many|count|number of)\b", normalized_question)
        and re.search(r"\b(?:which|list|identify|show)\b", normalized_question)
    ):
        return semantic_ir, ()
    bands, member_band = _explicit_numeric_band_specs(question, semantic_ir.language)
    if not bands or member_band is None:
        return semantic_ir, ()

    count_projections = [
        item
        for item in semantic_ir.projections
        if item.role is ProjectionRole.METRIC
        and item.aggregate in {SemanticAggregate.COUNT, SemanticAggregate.COUNT_DISTINCT}
    ]
    band_projections = [
        item
        for item in semantic_ir.projections
        if item.role is not ProjectionRole.METRIC
        and item.field_ref is not None
        and re.search(r"(?:^|_)band$", item.output_name, re.IGNORECASE)
    ]
    if len(count_projections) != 1 or len(band_projections) != 1:
        return semantic_ir, ()
    member_projections = [
        item
        for item in semantic_ir.projections
        if item not in {*count_projections, *band_projections}
        and item.role is not ProjectionRole.METRIC
        and item.field_ref is not None
        and re.search(
            rf"(?:^|_){re.escape(member_band)}(?:_|$)",
            item.output_name,
            re.IGNORECASE,
        )
    ]
    band_projection = band_projections[0]
    count_projection = count_projections[0]
    if not member_projections:
        member_projections = [
            item
            for item in semantic_ir.projections
            if item not in {*count_projections, *band_projections}
            and item.role is not ProjectionRole.METRIC
            and item.field_ref is not None
            and (
                str(
                    (
                        _reviewed_field_metadata(semantic_layer, item.field_ref)
                        or {}
                    ).get("display_role")
                    or ""
                ).casefold()
                == "primary_label"
                or str(
                    (
                        _reviewed_field_metadata(semantic_layer, item.field_ref)
                        or {}
                    ).get("business_role")
                    or ""
                ).casefold()
                == "label"
            )
        ]
    if len(member_projections) != 1:
        return semantic_ir, ()
    member_projection = member_projections[0]
    if band_projection.field_ref == member_projection.field_ref:
        return semantic_ir, ()

    allowed_projections = {count_projection, band_projection, member_projection}
    member_disambiguation_field_refs: list[SemanticModelFieldRef] = []
    for item in semantic_ir.projections:
        if item in allowed_projections:
            continue
        if item.role is ProjectionRole.METRIC or item.field_ref is None:
            return semantic_ir, ()
        field = _reviewed_field_metadata(semantic_layer, item.field_ref) or {}
        is_score_repeat = item.field_ref == band_projection.field_ref
        is_member_companion = (
            item.field_ref.semantic_entity == member_projection.field_ref.semantic_entity
            and str(field.get("display_role") or "").casefold()
            == "disambiguation_label"
        )
        if not (is_score_repeat or is_member_companion):
            return semantic_ir, ()
        if is_member_companion and item.field_ref != member_projection.field_ref:
            if item.field_ref in member_disambiguation_field_refs:
                return semantic_ir, ()
            member_disambiguation_field_refs.append(item.field_ref)
    if len(member_disambiguation_field_refs) > 3:
        return semantic_ir, ()

    band_bounds = {
        float(value)
        for band in bands
        for value in (band.get("lower"), band.get("upper"))
        if value is not None
    }
    for group in semantic_ir.any_filter_groups:
        if not group.filters:
            return semantic_ir, ()
        for filter_spec in group.filters:
            if (
                filter_spec.field_ref != band_projection.field_ref
                or filter_spec.operator not in {"gt", "gte", "lt", "lte"}
                or len(filter_spec.values) != 1
                or isinstance(filter_spec.values[0], bool)
                or not isinstance(filter_spec.values[0], (int, float))
                or float(filter_spec.values[0]) not in band_bounds
            ):
                return semantic_ir, ()

    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "band_summary": {
                "score_field_ref": band_projection.field_ref.model_dump(mode="python"),
                "member_field_ref": member_projection.field_ref.model_dump(mode="python"),
                "member_disambiguation_field_refs": [
                    field_ref.model_dump(mode="python")
                    for field_ref in member_disambiguation_field_refs
                ],
                "bands": bands,
                "member_band": member_band,
                "band_output_name": band_projection.output_name,
                "count_output_name": count_projection.output_name,
                "member_output_name": member_projection.output_name,
            },
            "projections": [],
            "any_filter_groups": [],
            "include_result_count": False,
            "result_count_alias": "result_count",
        }
    )
    return effective, ("semantic_ir_promoted_explicit_numeric_band_summary",)


def _reviewed_field_metadata(
    semantic_layer: Mapping[str, Any],
    field_ref: SemanticModelFieldRef,
) -> Mapping[str, Any] | None:
    """Resolve one logical field's reviewed metadata without physical inference."""

    for binding in semantic_layer.get("table_bindings") or ():
        if (
            not isinstance(binding, Mapping)
            or str(binding.get("semantic_entity") or "")
            != field_ref.semantic_entity
        ):
            continue
        for field in binding.get("fields") or ():
            if (
                isinstance(field, Mapping)
                and str(field.get("semantic_field") or "")
                == field_ref.semantic_field
            ):
                return field
    return None


def _repair_redundant_measure_dimension_with_filtered_label(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> tuple[
    AdHocSemanticQueryIR,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Remove a duplicated measure dimension and retain filtered identity.

    The repair requires a reviewed numeric field to be present both as a
    dimension and as an aggregate metric. If the proposal already filters one
    reviewed primary label, that existing identity becomes a display
    dimension. No field, filter, or value is inferred.
    """

    if semantic_ir.status != "query" or semantic_ir.band_summary is not None:
        return semantic_ir, (), (), ()
    metric_field_refs = {
        projection.field_ref
        for projection in semantic_ir.projections
        if projection.role is ProjectionRole.METRIC
        and projection.aggregate is not None
        and projection.field_ref is not None
    }
    if not metric_field_refs:
        return semantic_ir, (), (), ()

    removed: list[str] = []
    kept: list[SemanticIRProjection] = []
    for projection in semantic_ir.projections:
        field = (
            _reviewed_field_metadata(semantic_layer, projection.field_ref)
            if projection.field_ref is not None
            else None
        ) or {}
        if (
            projection.role is ProjectionRole.DIMENSION
            and projection.field_ref in metric_field_refs
            and str(field.get("business_role") or "").casefold()
            in {"measure", "metric"}
        ):
            removed.append(projection.output_name)
            continue
        kept.append(projection)
    if not removed:
        return semantic_ir, (), (), ()

    projected_refs = {
        projection.field_ref
        for projection in kept
        if projection.field_ref is not None
    }
    filtered_primary_labels: list[tuple[SemanticFilter, Mapping[str, Any]]] = []
    for filter_spec in semantic_ir.filters:
        field = _reviewed_field_metadata(semantic_layer, filter_spec.field_ref) or {}
        if (
            filter_spec.operator in {"eq", "in"}
            and len(filter_spec.values) == 1
            and str(field.get("display_role") or "").casefold() == "primary_label"
            and filter_spec.field_ref not in projected_refs
        ):
            filtered_primary_labels.append((filter_spec, field))

    added: list[str] = []
    if len(filtered_primary_labels) == 1:
        filter_spec, field = filtered_primary_labels[0]
        output_name = str(
            field.get("display_output_name")
            or field.get("semantic_field")
            or filter_spec.field_ref.semantic_field
        ).strip()
        if output_name and output_name.casefold() not in {
            projection.output_name.casefold() for projection in kept
        }:
            kept.insert(
                0,
                SemanticIRProjection(
                    output_name=output_name,
                    role=ProjectionRole.DIMENSION,
                    field_ref=filter_spec.field_ref,
                ),
            )
            added.append(output_name)

    effective = semantic_ir.model_copy(update={"projections": tuple(kept)})
    corrections = tuple(
        [
            f"semantic_ir_removed_redundant_measure_dimension:{name}"
            for name in removed
        ]
        + [
            f"semantic_ir_added_filtered_primary_label:{name}"
            for name in added
        ]
    )
    return effective, tuple(added), tuple(removed), corrections


def _validate_question_answer_shape(
    semantic_ir: AdHocSemanticQueryIR,
    question: str | None,
) -> None:
    """Keep list-plus-count requests as detail rows with a count companion."""

    if not question or semantic_ir.status != "query":
        return
    if semantic_ir.band_summary is not None:
        # The dedicated capability already carries both requested counts and
        # the requested member list; ordinary list/count shape repairs must
        # not reinterpret it as a detail projection.
        return
    normalized = " ".join(str(question).casefold().split())
    asks_for_list = bool(
        re.search(
            r"(?:\bwhich\b|\blist\b|\bshow\b|\bidentify\b|\bwhat\b|"
            r"哪些|列出|显示|哪些|ما هي|اذكر)",
            normalized,
        )
    )
    # A bare ``count`` often names the requested metric (for example
    # "highest citywide count"), rather than asking for a second total of the
    # listed entities. Only explicit total/count-of wording requires the
    # detail-plus-count companion column; this keeps metric questions at their
    # requested grain while preserving the guard for "which ... and how many"
    # requests.
    asks_for_count = bool(
        re.search(
            r"(?:\bhow many\b|\bnumber of\b|\btotal(?: number)?\b|"
            r"\bcount\s+(?:of|are|is|there)\b|多少|数量|计数|总数|كم عدد|عدد)",
            normalized,
        )
    )
    has_explicit_total_metric = any(
        item.aggregate == "sum" for item in semantic_ir.partition_statistics
    )
    if (
        asks_for_list
        and asks_for_count
        and not semantic_ir.include_result_count
        and not has_explicit_total_metric
    ):
        has_count_metric = any(
            item.role is ProjectionRole.METRIC
            and item.aggregate is SemanticAggregate.COUNT
            for item in semantic_ir.projections
        )
        if not has_count_metric:
            raise SemanticIRCompilationError("semantic_ir_result_count_required")

    # A detail-list question with a scalar threshold should expose the
    # matching field as an attribute.  Averaging that same field turns each
    # entity into a grouped aggregate and silently changes the requested grain.
    explicit_aggregate_word = bool(
        re.search(
            r"(?:\baverage\b|\bavg\b|\bmean\b|\bmedian\b|\bsum\b|\btotal\b|"
            r"平均|均值|中位数|合计|总和|متوسط|وسيط|مجموع)",
            normalized,
        )
    )
    if asks_for_list and not explicit_aggregate_word:
        filter_fields = {
            (item.field_ref.semantic_entity, item.field_ref.semantic_field)
            for item in semantic_ir.filters
        }
        for projection in semantic_ir.projections:
            if (
                projection.role is ProjectionRole.METRIC
                and projection.aggregate is not SemanticAggregate.COUNT
                and projection.field_ref is not None
                and (
                    projection.field_ref.semantic_entity,
                    projection.field_ref.semantic_field,
                )
                in filter_fields
            ):
                raise SemanticIRCompilationError(
                    "semantic_ir_unrequested_aggregation_on_detail_field"
                )


def _having_only_metric_output_names(
    semantic_ir: AdHocSemanticQueryIR,
    question: str | None,
) -> tuple[str, ...]:
    """Identify condition-only aggregate outputs that should stay hidden.

    A grouped question such as "which facility types have an FPP score of
    100%" needs the aggregate in ``HAVING`` but does not ask to display that
    aggregate. Providers often project it anyway. Hiding only the exact
    aggregate/field already used by a reviewed ``having_filter`` preserves the
    condition and grouped grain without adding an unrequested result column.
    """

    if not question or not semantic_ir.having_filters:
        return ()
    normalized = " ".join(str(question).casefold().split())
    asks_to_display_metric = bool(
        re.search(
            r"(?:\b(?:show|display|return|include)\b[^.]{0,100}\b(?:score|count|value|percentage|metric)\b|"
            r"\b(?:their|each)\b[^.]{0,60}\b(?:score|count|value|percentage|metric)\b)",
            normalized,
        )
    )
    if asks_to_display_metric:
        return ()
    having_signatures = {
        (
            item.field_ref.semantic_entity,
            item.field_ref.semantic_field,
            item.aggregate,
        )
        for item in semantic_ir.having_filters
    }
    ordered_names = {
        item.output_name.casefold()
        for item in (*semantic_ir.order_by, *semantic_ir.extreme_order_by)
    }
    hidden: list[str] = []
    for projection in semantic_ir.projections:
        if (
            projection.role is ProjectionRole.METRIC
            and projection.field_ref is not None
            and projection.aggregate is not None
            and (
                projection.field_ref.semantic_entity,
                projection.field_ref.semantic_field,
                projection.aggregate,
            )
            in having_signatures
            and projection.output_name.casefold() not in ordered_names
        ):
            hidden.append(projection.output_name)
    return tuple(hidden)


def _repair_reviewed_detail_projection_aggregates(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    question: str | None,
) -> AdHocSemanticQueryIR:
    """Repair a provider's metric/attribute role confusion for detail rows.

    Some providers emit ``SUM(needed_ap50)`` while the question asks for the
    district rows satisfying ``needed_ap50 > 0``.  The repair is allowed only
    when the reviewed semantic field explicitly publishes
    ``detail_projection_safe``; generic fixtures and unreviewed fields still
    fail closed through ``_validate_question_answer_shape``.  No value,
    entity, filter, or relationship is invented.
    """

    if not question or semantic_ir.status != "query":
        return semantic_ir
    normalized = " ".join(str(question).casefold().split())
    asks_for_list = bool(
        re.search(r"(?:\bwhich\b|\blist\b|\bshow\b|\bidentify\b|\bwhat\b|哪些|列出|显示|ما هي|اذكر)", normalized)
    )
    explicit_aggregate_word = bool(
        re.search(
            r"(?:\baverage\b|\bavg\b|\bmean\b|\bmedian\b|\bsum\b|\btotal\b|平均|均值|中位数|合计|总和|متوسط|وسيط|مجموع)",
            normalized,
        )
    )
    if not asks_for_list or explicit_aggregate_word:
        return semantic_ir
    filter_fields = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in semantic_ir.filters
    }
    safe_fields: set[tuple[str, str]] = set()
    for binding in semantic_layer.get("table_bindings") or ():
        if not isinstance(binding, Mapping):
            continue
        entity = str(binding.get("semantic_entity") or "")
        for field in binding.get("fields") or ():
            if isinstance(field, Mapping) and field.get("detail_projection_safe") is True:
                safe_fields.add((entity, str(field.get("semantic_field") or "")))
    referenced_entities = {
        semantic_ir.semantic_entity or "",
        *(
            projection.field_ref.semantic_entity
            for projection in semantic_ir.projections
            if projection.field_ref is not None
        ),
        *(item.field_ref.semantic_entity for item in semantic_ir.filters),
        *(item.field_ref.semantic_entity for item in semantic_ir.having_filters),
    }
    collection_member_fields = {
        (
            str(policy.get("semantic_entity") or ""),
            str(field.get("semantic_field") or ""),
        )
        for policy in resolve_projection_completeness_policies(
            question=question,
            language=semantic_ir.language,
            semantic_layer=semantic_layer,
            semantic_entities=referenced_entities,
        )
        for field in policy.get("required_fields") or ()
        if isinstance(field, Mapping)
    }
    # A HAVING predicate is valid for an aggregate entity-group result, but a
    # provider sometimes uses it for a district detail list. Only a reviewed
    # primary-label projection establishes that this is a detail result; this
    # deliberately excludes requests such as facility-type rollups.
    primary_label_fields = {
        (
            str(policy.get("semantic_entity") or ""),
            str(policy.get("primary_label_field") or ""),
        )
        for policy in semantic_layer.get("display_projection_policies") or ()
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("semantic_entity") or "")
        and str(policy.get("primary_label_field") or "")
    }
    has_reviewed_primary_label = any(
        projection.field_ref is not None
        and projection.role in {ProjectionRole.ATTRIBUTE, ProjectionRole.DIMENSION}
        and (
            projection.field_ref.semantic_entity,
            projection.field_ref.semantic_field,
        )
        in primary_label_fields
        for projection in semantic_ir.projections
    )
    regular_filters = list(semantic_ir.filters)
    remaining_having_filters: list[SemanticHavingFilter] = []
    demoted_having_fields: set[tuple[str, str]] = set()
    for having_filter in semantic_ir.having_filters:
        key = (
            having_filter.field_ref.semantic_entity,
            having_filter.field_ref.semantic_field,
        )
        if not has_reviewed_primary_label or key not in safe_fields:
            remaining_having_filters.append(having_filter)
            continue
        matching_filters = [
            item
            for item in regular_filters
            if (item.field_ref.semantic_entity, item.field_ref.semantic_field) == key
        ]
        replacement = SemanticFilter(
            field_ref=having_filter.field_ref,
            operator=having_filter.operator,
            values=having_filter.values,
        )
        if matching_filters and replacement not in matching_filters:
            # A conflicting row predicate is semantically meaningful. Leave
            # the aggregate form intact so normal compiler validation fails
            # closed rather than guessing which condition the user intended.
            remaining_having_filters.append(having_filter)
            continue
        if not matching_filters:
            regular_filters.append(replacement)
        demoted_having_fields.add(key)

    detail_filter_fields = filter_fields | demoted_having_fields
    changed = bool(demoted_having_fields)
    projections: list[dict[str, Any]] = []
    for projection in semantic_ir.projections:
        ref = projection.field_ref
        key = (ref.semantic_entity, ref.semantic_field) if ref is not None else None
        if (
            projection.role is ProjectionRole.METRIC
            and projection.aggregate is not None
            and projection.aggregate is not SemanticAggregate.COUNT
            and (
                key in detail_filter_fields
                or (has_reviewed_primary_label and key in collection_member_fields)
            )
            and key in safe_fields
        ):
            item = projection.model_dump(mode="python")
            item["role"] = ProjectionRole.ATTRIBUTE.value
            item["aggregate"] = None
            changed = True
            projections.append(item)
        else:
            projections.append(projection.model_dump(mode="python"))
    if not changed:
        return semantic_ir
    return AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "projections": projections,
            "filters": [item.model_dump(mode="python") for item in regular_filters],
            "having_filters": [
                item.model_dump(mode="python") for item in remaining_having_filters
            ],
        }
    )


def _add_reviewed_detail_filter_explanation_projections(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    *,
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Expose reviewed numeric threshold fields for an entity detail list.

    A question such as "which districts have a score above 90" asks for a
    qualifying entity list, not just the identity of those entities.  When a
    reviewed measure explicitly permits direct detail projection, returning
    the threshold measure makes each qualifying row explainable.  This is
    restricted to direct row filters and reviewed primary-label results; it
    never changes an aggregate, HAVING, grouped, or count-only query.
    """

    if (
        not question
        or semantic_ir.status != "query"
        or semantic_ir.band_summary is not None
        or semantic_ir.having_filters
        or semantic_ir.partition_by
        or semantic_ir.extreme_order_by
        or not question_is_entity_list(question, semantic_ir.language)
    ):
        return semantic_ir, ()
    if any(
        projection.role is ProjectionRole.METRIC
        or projection.derived_measure is not None
        or projection.derived_expression is not None
        or projection.json_array is not None
        or projection.field_ref is None
        for projection in semantic_ir.projections
    ):
        return semantic_ir, ()

    fields = {
        (
            str(binding.get("semantic_entity") or ""),
            str(field.get("semantic_field") or ""),
        ): field
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping)
        for field in binding.get("fields") or ()
        if isinstance(field, Mapping)
    }
    primary_label_fields = {
        (
            str(policy.get("semantic_entity") or ""),
            str(policy.get("primary_label_field") or ""),
        )
        for policy in semantic_layer.get("display_projection_policies") or ()
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("semantic_entity") or "")
        and str(policy.get("primary_label_field") or "")
    }
    if not any(
        projection.field_ref is not None
        and projection.role in {ProjectionRole.ATTRIBUTE, ProjectionRole.DIMENSION}
        and (
            projection.field_ref.semantic_entity,
            projection.field_ref.semantic_field,
        )
        in primary_label_fields
        for projection in semantic_ir.projections
    ):
        return semantic_ir, ()

    projected_refs = {
        projection.field_ref
        for projection in semantic_ir.projections
        if projection.field_ref is not None
    }
    projected_names = {
        projection.output_name.casefold() for projection in semantic_ir.projections
    }
    additions: list[SemanticIRProjection] = []
    for filter_spec in semantic_ir.filters:
        if filter_spec.operator not in {"gt", "gte", "lt", "lte"}:
            continue
        if not filter_spec.values or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in filter_spec.values
        ):
            continue
        field_ref = filter_spec.field_ref
        if field_ref in projected_refs:
            continue
        field = fields.get((field_ref.semantic_entity, field_ref.semantic_field)) or {}
        explanation_policy = field.get("detail_filter_explanation_policy") or {}
        if (
            field.get("detail_projection_safe") is not True
            or str(field.get("business_role") or "").casefold()
            not in {"measure", "metric"}
            or not isinstance(explanation_policy, Mapping)
            or explanation_policy.get("review_status") != "reviewed"
            or "entity_list_direct_numeric_filter"
            not in {
                str(value).strip()
                for value in explanation_policy.get("application") or ()
                if str(value).strip()
            }
        ):
            continue
        output_name = str(
            field.get("filter_explanation_output_name")
            or field.get("display_output_name")
            or field_ref.semantic_field
        ).strip()
        if (
            not output_name
            or output_name.casefold() in projected_names
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", output_name)
        ):
            continue
        additions.append(
            SemanticIRProjection(
                output_name=output_name,
                role=ProjectionRole.ATTRIBUTE,
                field_ref=field_ref,
            )
        )
        projected_refs.add(field_ref)
        projected_names.add(output_name.casefold())
    if not additions:
        return semantic_ir, ()
    effective = semantic_ir.model_copy(
        update={"projections": (*semantic_ir.projections, *additions)}
    )
    return effective, tuple(item.output_name for item in additions)


def _apply_reviewed_context_dimension_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    *,
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Remove a reviewed parent context dimension when its child is requested.

    A published field policy, rather than a question-specific branch, defines
    the parent/child relationship and the words that explicitly retain the
    parent. This prevents a broad category from changing the grouping grain
    when a model already selected the more specific business dimension.
    """

    if not question or semantic_ir.status != "query" or not semantic_ir.projections:
        return semantic_ir, ()
    fields = {
        (
            str(binding.get("semantic_entity") or ""),
            str(field.get("semantic_field") or ""),
        ): field
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping)
        for field in binding.get("fields") or ()
        if isinstance(field, Mapping)
    }
    projected = list(semantic_ir.projections)
    projected_keys = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in projected
        if item.field_ref is not None
    }
    protected_names = {
        *(
            item.output_name.casefold()
            for item in (*semantic_ir.order_by, *semantic_ir.extreme_order_by)
        ),
        *(item.casefold() for item in semantic_ir.partition_by),
        *(
            item.casefold()
            for item in (
                semantic_ir.group_average_filter.partition_by
                if semantic_ir.group_average_filter is not None
                else ()
            )
        ),
        *(
            item.casefold()
            for group_average in semantic_ir.group_average_filters
            for item in group_average.partition_by
        ),
    }
    removed: list[str] = []
    kept: list[SemanticIRProjection] = []
    for projection in projected:
        ref = projection.field_ref
        field = (
            fields.get((ref.semantic_entity, ref.semantic_field))
            if ref is not None
            else None
        )
        policy = field.get("dimension_context_policy") if isinstance(field, Mapping) else None
        if (
            ref is None
            or projection.role not in {ProjectionRole.ATTRIBUTE, ProjectionRole.DIMENSION}
            or projection.output_name.casefold() in protected_names
            or not isinstance(policy, Mapping)
            or policy.get("review_status") != "reviewed"
        ):
            kept.append(projection)
            continue
        child_field = str(policy.get("omit_when_child_projected") or "").strip()
        terms_by_language = policy.get("retain_when_question_mentions")
        terms = (
            terms_by_language.get(semantic_ir.language)
            if isinstance(terms_by_language, Mapping)
            else None
        )
        if (
            not child_field
            or not isinstance(terms, (list, tuple))
            or not terms
            or (ref.semantic_entity, child_field) not in projected_keys
            or any(
                _question_mentions_domain_alias(str(question), str(term))
                for term in terms
                if str(term).strip()
            )
        ):
            kept.append(projection)
            continue
        removed.append(projection.output_name)
    if not removed:
        return semantic_ir, ()
    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "projections": [item.model_dump(mode="python") for item in kept],
        }
    )
    return effective, tuple(removed)


def _domain_text(value: Any) -> str:
    """Normalize a business value for lossless enum matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _question_mentions_domain_alias(question: str, alias: str) -> bool:
    """Match a domain alias as a token/phrase, not as a substring."""

    normalized_question = _domain_text(question)
    normalized_alias = _domain_text(alias)
    if not normalized_alias or len(normalized_alias) < 2:
        return False
    if all(ord(char) < 128 for char in normalized_alias):
        return bool(
            re.search(
                r"(?<![a-z0-9])" + re.escape(normalized_alias) + r"(?![a-z0-9])",
                normalized_question,
            )
        )
    return normalized_alias in normalized_question


def _reviewed_domain_alias_variants(source: str) -> tuple[str, ...]:
    """Derive conservative English singular/plural aliases for one source value.

    The source value remains authoritative; these variants are only lexical
    evidence used to bind an explicitly named value.  Derivation is limited
    to ASCII alphabetic final tokens and is later subject to the same
    cross-value collision check as reviewed aliases.  Consequently a shared
    form (for example ``classes``/``class``) remains ambiguous and cannot
    create a filter.
    """

    normalized = _domain_text(source)
    if not normalized or not all(ord(char) < 128 for char in normalized):
        return ()
    tokens = normalized.split()
    if not tokens or not re.fullmatch(r"[a-z]+", tokens[-1]):
        return ()
    final = tokens[-1]
    singular: str | None = None
    if final.endswith("ies") and len(final) > 3:
        singular = final[:-3] + "y"
    elif final.endswith(("ches", "shes", "xes", "zes", "ses")) and len(final) > 3:
        singular = final[:-2]
    elif final.endswith("s") and not final.endswith("ss") and len(final) > 2:
        singular = final[:-1]
    plural: str
    if final.endswith("y") and len(final) > 1 and final[-2] not in "aeiou":
        plural = final[:-1] + "ies"
    elif final.endswith(("s", "x", "z", "ch", "sh")):
        plural = final + "es"
    else:
        plural = final + "s"
    variants: list[str] = []
    if singular and singular != final:
        variants.append(" ".join([*tokens[:-1], singular]))
    if plural != final:
        variants.append(" ".join([*tokens[:-1], plural]))
    return tuple(dict.fromkeys(variants))


def _coerce_domain_source_value(value: str, field: Mapping[str, Any]) -> str | int | float | bool:
    """Convert an observed source token to the field's reviewed scalar type."""

    data_type = str(
        (field.get("technical_metadata") or {}).get("data_type")
        or field.get("data_type")
        or ""
    ).casefold()
    if "bool" in data_type:
        if value.casefold() == "true":
            return True
        if value.casefold() == "false":
            return False
    if any(token in data_type for token in ("int", "numeric", "decimal", "double", "real", "float")):
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            pass
    return value


def _apply_explicit_domain_filters(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Bind explicitly enumerated business values to reviewed enum fields.

    Users often name a finite set of categories in prose (for example
    ``Urban, Suburban, and Rural``) or a single lifecycle category (for
    example ``existing``) without spelling out a predicate.  A language model
    may therefore project the dimension, or select its entity, but omit the
    required filter.  This repair is deliberately generic and fail-closed:
    values must come from a reviewed/source-observed domain, the field must
    belong to an entity already selected by the IR, exactly one candidate
    field must match, and an existing conflicting predicate is never
    overwritten.
    """

    if not question or semantic_ir.status != "query":
        return semantic_ir, ()
    referenced_entities = {semantic_ir.semantic_entity} if semantic_ir.semantic_entity else set()
    for projection in semantic_ir.projections:
        if projection.field_ref is not None:
            referenced_entities.add(projection.field_ref.semantic_entity)
        if projection.derived_expression is not None:
            referenced_entities.update(
                operand.semantic_entity for operand in projection.derived_expression.operands
            )
        if projection.json_array is not None:
            referenced_entities.add(projection.json_array.field_ref.semantic_entity)
    if semantic_ir.band_summary is not None:
        referenced_entities.update(
            reference.semantic_entity
            for reference in (
                semantic_ir.band_summary.score_field_ref,
                semantic_ir.band_summary.member_field_ref,
                *semantic_ir.band_summary.member_disambiguation_field_refs,
            )
        )
    for filter_spec in (*semantic_ir.filters, *semantic_ir.having_filters):
        referenced_entities.add(filter_spec.field_ref.semantic_entity)
    for group in semantic_ir.any_filter_groups:
        referenced_entities.update(item.field_ref.semantic_entity for item in group.filters)
    for join in semantic_ir.joins:
        referenced_entities.update(
            (join.left_field_ref.semantic_entity, join.right_field_ref.semantic_entity)
        )

    projected_fields = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in semantic_ir.projections
        if item.field_ref is not None
    }
    if semantic_ir.band_summary is not None:
        projected_fields.update(
            (reference.semantic_entity, reference.semantic_field)
            for reference in (
                semantic_ir.band_summary.score_field_ref,
                semantic_ir.band_summary.member_field_ref,
                *semantic_ir.band_summary.member_disambiguation_field_refs,
            )
        )
    candidates: list[dict[str, Any]] = []
    for binding in semantic_layer.get("table_bindings") or ():
        if not isinstance(binding, Mapping):
            continue
        entity = str(binding.get("semantic_entity") or "")
        if not entity or entity not in referenced_entities:
            continue
        for field in binding.get("fields") or ():
            if not isinstance(field, Mapping):
                continue
            semantic_field = str(field.get("semantic_field") or "")
            source_values = [
                str(value).strip()
                for value in (
                    field.get("source_value_domain_observed")
                    or field.get("value_domain")
                    or []
                )
                if str(value).strip()
            ]
            source_values = list(dict.fromkeys(source_values))
            if not source_values:
                continue
            source_by_domain_text: dict[str, str | None] = {}
            for source in source_values:
                normalized_source = _domain_text(source)
                if not normalized_source:
                    continue
                if normalized_source in source_by_domain_text:
                    # A normalized alias cannot safely select one of two
                    # distinct physical source values.
                    source_by_domain_text[normalized_source] = None
                else:
                    source_by_domain_text[normalized_source] = source
            value_semantics = field.get("value_semantics") or {}
            aliases_by_source: dict[str, list[str]] = {
                source: [source]
                for source in source_values
                if source_by_domain_text.get(_domain_text(source)) == source
            }
            if isinstance(value_semantics, Mapping):
                for source, aliases in value_semantics.items():
                    source_text = str(source).strip()
                    canonical_source = source_by_domain_text.get(_domain_text(source_text))
                    if not source_text or canonical_source is None:
                        continue
                    aliases_by_source[canonical_source].extend(
                        str(alias).strip()
                        for alias in (aliases if isinstance(aliases, list) else [aliases])
                        if str(alias).strip()
                    )
            # Reviewed aliases are the primary contract.  Add only the
            # conservative lexical singular/plural forms of each canonical
            # source value; collisions are rejected below, so this cannot
            # silently choose between two physical values.
            for source, aliases in list(aliases_by_source.items()):
                aliases.extend(_reviewed_domain_alias_variants(source))
            alias_sources: dict[str, str | None] = {}
            for source, aliases in aliases_by_source.items():
                for alias in aliases:
                    alias_key = _domain_text(alias)
                    if not alias_key:
                        continue
                    if alias_key in alias_sources and alias_sources[alias_key] != source:
                        alias_sources[alias_key] = None
                    else:
                        alias_sources.setdefault(alias_key, source)
            matched: list[tuple[str, str]] = []
            for source, aliases in aliases_by_source.items():
                matching_aliases = [
                    alias for alias in dict.fromkeys(aliases)
                    if alias_sources.get(_domain_text(alias)) == source
                    and _question_mentions_domain_alias(question, alias)
                ]
                if matching_aliases:
                    # Prefer the longest matching alias for evidence/debugging;
                    # the source token remains the only value admitted.
                    matched.append((source, max(matching_aliases, key=len)))
            unique_sources = list(dict.fromkeys(source for source, _alias in matched))
            if not unique_sources:
                continue
            projected = (entity, semantic_field) in projected_fields
            field_identity_terms = [
                semantic_field,
                str(field.get("physical_field") or ""),
                *(str(value) for value in (field.get("labels") or {}).values()),
                *(str(value) for value in field.get("aliases") or ()),
            ]
            field_identity_matched = any(
                term.strip() and _question_mentions_domain_alias(question, term)
                for term in field_identity_terms
            )
            # A bare value such as ``current`` may be a business modifier for
            # a projected measure rather than a predicate on an unrelated
            # joined dimension. For one unprojected enum value, require the
            # question to name that field as well (for example "Existing
            # lifecycle stage"). Multi-value enumerations and projected
            # dimensions remain strong enough evidence on their own.
            candidates.append(
                {
                    "entity": entity,
                    "semantic_field": semantic_field,
                    "field": field,
                    "sources": unique_sources,
                    "matched_aliases": [alias for _source, alias in matched],
                    "alias_sources": alias_sources,
                    "projected": projected,
                    "field_identity_matched": field_identity_matched,
                }
            )
    if not candidates:
        return semantic_ir, ()

    # A question can contain a word that is a valid reviewed value for more
    # than one field.  Projection is useful context for a model, but is not
    # sufficient authority for the compiler to choose one of those fields.
    # Do not infer a predicate in that case; the retry/clarification path can
    # resolve it without silently narrowing the source result.
    if len(candidates) != 1:
        return semantic_ir, ()
    best = candidates[0]
    if (
        len(best["sources"]) == 1
        and not best["projected"]
        and not best["field_identity_matched"]
    ):
        return semantic_ir, ()

    key = (best["entity"], best["semantic_field"])
    existing = [
        item for item in semantic_ir.filters
        if (item.field_ref.semantic_entity, item.field_ref.semantic_field) == key
    ]
    requested_values = tuple(
        _coerce_domain_source_value(value, best["field"])
        for value in best["sources"]
    )
    requested_set = {repr(value) for value in requested_values}
    if existing:
        def canonical_existing_value(value: str | int | float | bool) -> str | int | float | bool:
            if not isinstance(value, str):
                return value
            source_value = best["alias_sources"].get(_domain_text(value))
            return (
                _coerce_domain_source_value(source_value, best["field"])
                if source_value is not None
                else value
            )

        canonical_current_values = [
            tuple(canonical_existing_value(value) for value in item.values)
            for item in existing
        ]
        current_sets = [
            {repr(value) for value in values}
            for values in canonical_current_values
        ]
        if not all(
            item.operator in {"in", "eq"} and current_set <= requested_set
            for item, current_set in zip(existing, current_sets, strict=True)
        ):
            raise SemanticIRCompilationError("semantic_ir_explicit_domain_filter_conflict")
        model_values_are_canonical = all(
            tuple(item.values) == values
            for item, values in zip(existing, canonical_current_values, strict=True)
        )
        if all(current_set == requested_set for current_set in current_sets) and model_values_are_canonical:
            return semantic_ir, ()
        # Expand a subset generated by the model to the complete explicit user
        # list.  Replace every same-field subset: retaining a second model
        # predicate would incorrectly intersect the user's requested values.
        replacement = SemanticFilter(
            field_ref=existing[0].field_ref,
            operator="in",
            values=requested_values,
        )
        filters = tuple(
            item
            for item in semantic_ir.filters
            if (item.field_ref.semantic_entity, item.field_ref.semantic_field) != key
        ) + (replacement,)
        correction_kind = (
            "semantic_ir_normalized_explicit_domain_filter"
            if all(current_set == requested_set for current_set in current_sets)
            else "semantic_ir_completed_explicit_domain_filter"
        )
        return (
            AdHocSemanticQueryIR.model_validate(
                {**semantic_ir.model_dump(mode="python"), "filters": [item.model_dump(mode="python") for item in filters]}
            ),
            (
                correction_kind
                + ":"
                + best["entity"]
                + "."
                + best["semantic_field"],
            ),
        )

    filter_spec = SemanticFilter(
        field_ref=SemanticModelFieldRef(
            semantic_entity=best["entity"],
            semantic_field=best["semantic_field"],
        ),
        operator="in",
        values=requested_values,
    )
    filters = (*semantic_ir.filters, filter_spec)
    return (
        AdHocSemanticQueryIR.model_validate(
            {**semantic_ir.model_dump(mode="python"), "filters": [item.model_dump(mode="python") for item in filters]}
        ),
        (
            "semantic_ir_added_explicit_domain_filter:"
            + best["entity"]
            + "."
            + best["semantic_field"],
        ),
    )


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


class SemanticDerivedExpression(_FrozenModel):
    """A small compiler-owned arithmetic expression over reviewed measures.

    The model supplies only the operation and logical field references.  The
    compiler resolves physical bindings, rejects non-numeric fields, and
    emits the expression with bound identifiers.  Constants and arbitrary SQL
    text are intentionally outside this capability.
    """

    operator: Literal["add", "subtract", "multiply", "divide"]
    operands: tuple[SemanticModelFieldRef, ...] = Field(min_length=2, max_length=4)


class SemanticResultExpression(_FrozenModel):
    """A bounded arithmetic expression over validated numeric result aliases."""

    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    operator: Literal["add", "subtract", "multiply", "divide"]
    operands: tuple[str, ...] = Field(min_length=2, max_length=4)
    scale: float = 1.0

    @model_validator(mode="after")
    def _coherent_expression(self) -> SemanticResultExpression:
        if self.operator in {"subtract", "divide"} and len(self.operands) != 2:
            raise ValueError("subtract and divide result expressions require two operands")
        if any(
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", operand) is None
            for operand in self.operands
        ):
            raise ValueError("result expression operands must be output aliases")
        if not math.isfinite(self.scale) or self.scale == 0 or abs(self.scale) > 1_000_000:
            raise ValueError("result expression scale must be finite, non-zero, and bounded")
        return self


class SemanticTwoValueComparison(_FrozenModel):
    """A reviewed same-entity comparison across two categorical values.

    The model names only logical fields, two values explicitly requested by
    the user, and presentation aliases. A published policy supplies the
    pairing grain and permits the compiler-owned conditional aggregates.
    This avoids an unsafe, model-authored self-join.
    """

    policy_id: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    scope_field_ref: SemanticModelFieldRef
    measure_field_ref: SemanticModelFieldRef
    baseline_value: str = Field(min_length=1, max_length=128)
    comparison_value: str = Field(min_length=1, max_length=128)
    baseline_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    comparison_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    difference_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )

    @model_validator(mode="after")
    def _coherent_comparison(self) -> SemanticTwoValueComparison:
        if self.scope_field_ref.semantic_entity != self.measure_field_ref.semantic_entity:
            raise ValueError("two-value comparison fields must share an entity")
        if self.baseline_value.casefold() == self.comparison_value.casefold():
            raise ValueError("two-value comparison values must differ")
        aliases = [
            self.baseline_output_name.casefold(),
            self.comparison_output_name.casefold(),
            self.difference_output_name.casefold(),
        ]
        if len(aliases) != len(set(aliases)):
            raise ValueError("two-value comparison output aliases must be unique")
        return self


class SemanticCategoricalPivotValue(_FrozenModel):
    """One audited categorical value projected as a numeric result alias."""

    value: str = Field(min_length=1, max_length=128)
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )


class SemanticCategoricalPivot(_FrozenModel):
    """A reviewed same-entity pivot over multiple categorical values.

    A comparison policy supplies the allowed vocabulary, pairing grain, and
    aggregate.  The model can select audited values and output aliases, but it
    cannot author conditional aggregation or a self-join.
    """

    policy_id: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    scope_field_ref: SemanticModelFieldRef
    measure_field_ref: SemanticModelFieldRef
    values: tuple[SemanticCategoricalPivotValue, ...] = Field(
        min_length=2, max_length=8
    )

    @model_validator(mode="after")
    def _coherent_pivot(self) -> SemanticCategoricalPivot:
        if self.scope_field_ref.semantic_entity != self.measure_field_ref.semantic_entity:
            raise ValueError("categorical pivot fields must share an entity")
        value_names = [item.value.casefold() for item in self.values]
        output_names = [item.output_name.casefold() for item in self.values]
        if len(value_names) != len(set(value_names)):
            raise ValueError("categorical pivot values must be unique")
        if len(output_names) != len(set(output_names)):
            raise ValueError("categorical pivot output aliases must be unique")
        return self


class SemanticJSONArraySpec(_FrozenModel):
    """A governed aggregation over records stored in a JSONB array.

    JSONB access is deliberately represented as a small semantic capability,
    rather than allowing the model to author JSON operators or SQL functions.
    The compiler resolves the JSON column and checks the published access
    contract (shape, keys, and required scope filter) before emitting SQL.
    """

    field_ref: SemanticModelFieldRef
    value_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )


class SemanticBandSpec(_FrozenModel):
    """One compiler-owned numeric band for a governed band summary.

    Bounds are values supplied by the model from the user's wording, but are
    emitted as parameters by the compiler.  The model cannot provide CASE
    text or arbitrary expressions.
    """

    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    label: str | None = Field(default=None, min_length=1, max_length=128)
    lower: float | None = None
    lower_inclusive: bool = True
    upper: float | None = None
    upper_inclusive: bool = False

    @model_validator(mode="after")
    def _coherent_bounds(self) -> SemanticBandSpec:
        if self.lower is None and self.upper is None:
            raise ValueError("band requires a lower or upper bound")
        if self.lower is not None and not math.isfinite(self.lower):
            raise ValueError("band lower bound must be finite")
        if self.upper is not None and not math.isfinite(self.upper):
            raise ValueError("band upper bound must be finite")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise ValueError("band lower bound exceeds upper bound")
            if self.lower == self.upper and not (
                self.lower_inclusive and self.upper_inclusive
            ):
                raise ValueError("zero-width band must include both endpoints")
        return self


class SemanticBandSummary(_FrozenModel):
    """Restricted grouped numeric-band summary capability.

    This represents the common business request "count entities in each
    score band and list members of one band" without allowing a model to
    author CASE, STRING_AGG, or any other SQL text.
    """

    score_field_ref: SemanticModelFieldRef
    member_field_ref: SemanticModelFieldRef
    # The member field is the requested display label.  The optional context
    # fields preserve that label for ordinary rows and are added only when the
    # same label occurs more than once in a returned band (for example,
    # ``District A (Municipality B)``).  This lets a model request an
    # unambiguous list without authoring display SQL or silently dropping it.
    member_disambiguation_field_refs: tuple[SemanticModelFieldRef, ...] = Field(
        default=(), max_length=3
    )
    bands: tuple[SemanticBandSpec, ...] = Field(min_length=2, max_length=8)
    member_band: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    band_output_name: str = Field(
        default="score_band",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    count_output_name: str = Field(
        default="band_count",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    member_output_name: str = Field(
        default="band_members",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    delimiter: str = Field(default=", ", min_length=1, max_length=16)

    @model_validator(mode="after")
    def _coherent_summary(self) -> SemanticBandSummary:
        member_fields = (
            self.member_field_ref,
            *self.member_disambiguation_field_refs,
        )
        member_field_keys = [
            (item.semantic_entity, item.semantic_field) for item in member_fields
        ]
        if len(member_field_keys) != len(set(member_field_keys)):
            raise ValueError(
                "band summary member display and disambiguation fields must be unique"
            )
        keys = [item.key.casefold() for item in self.bands]
        if len(keys) != len(set(keys)):
            raise ValueError("band keys must be unique")
        if self.member_band.casefold() not in set(keys):
            raise ValueError("member_band must reference one declared band")
        output_names = [
            self.band_output_name.casefold(),
            self.count_output_name.casefold(),
            self.member_output_name.casefold(),
        ]
        if len(output_names) != len(set(output_names)):
            raise ValueError("band summary output aliases must be unique")
        if "\x00" in self.delimiter:
            raise ValueError("band summary delimiter must not contain NUL")
        return self


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
    derived_expression: SemanticDerivedExpression | None = None
    json_array: SemanticJSONArraySpec | None = None

    @model_validator(mode="after")
    def _coherent_projection(self) -> SemanticIRProjection:
        if self.role is ProjectionRole.METRIC:
            if self.aggregate is None:
                raise ValueError("metric projection requires an aggregate")
            if self.json_array is not None:
                if self.field_ref is not None:
                    raise ValueError("json_array metric must not also define field_ref")
                if self.aggregate not in {
                    SemanticAggregate.SUM,
                    SemanticAggregate.AVG,
                    SemanticAggregate.MIN,
                    SemanticAggregate.MAX,
                    SemanticAggregate.MEDIAN,
                }:
                    raise ValueError(
                        "json_array metric supports sum, avg, min, or max"
                    )
                if self.derived_measure is not None:
                    raise ValueError("json_array metric cannot define a derived measure")
                return self
            if self.derived_expression is not None and self.field_ref is not None:
                raise ValueError("derived expression metric must not also define field_ref")
            if self.aggregate is not SemanticAggregate.COUNT and self.field_ref is None:
                if self.derived_expression is None:
                    raise ValueError("non-count metric requires a semantic field or derived expression")
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
        if self.field_ref is None and self.derived_expression is None:
            raise ValueError("non-metric projection requires a semantic field or derived expression")
        if self.field_ref is not None and self.derived_expression is not None:
            raise ValueError("derived expression projection must not also define field_ref")
        if self.aggregate is not None:
            raise ValueError("non-metric projection cannot define an aggregate")
        if self.derived_measure is not None:
            raise ValueError("non-metric projection cannot define a derived measure")
        if self.json_array is not None:
            raise ValueError("json_array is supported only by metric projections")
        if self.derived_expression is not None and self.role is ProjectionRole.DIMENSION:
            raise ValueError("derived expression dimensions are not supported")
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


class SemanticHavingFilter(_FrozenModel):
    """A post-aggregation predicate over a governed metric expression.

    ``filters`` are row predicates and compile to ``WHERE``.  Questions such
    as "facility types with non-zero demand" require the condition to be
    evaluated after grouping (``HAVING SUM(demand_current) > 0``).  Keeping
    this as a separate typed capability avoids silently changing a row
    predicate into an aggregate predicate while allowing the same bounded
    operator/value vocabulary.
    """

    field_ref: SemanticModelFieldRef
    aggregate: SemanticAggregate
    operator: Literal[
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
    ]
    values: tuple[str | int | float | bool, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def _coherent_values(self) -> SemanticHavingFilter:
        if len(self.values) != 1:
            raise ValueError("having filter requires exactly one value")
        return self


class SemanticAnyFilterGroup(_FrozenModel):
    """An OR group combined with ordinary filters and other groups by AND."""

    filters: tuple[SemanticFilter, ...] = Field(min_length=2, max_length=12)


class SemanticUniversalCondition(_FrozenModel):
    """A governed ``every/all`` condition over a grouped result.

    The condition itself carries only logical identifiers and the explicit
    user threshold.  A reviewed semantic-layer policy supplies the assessed
    row scope, grouping key, validity/sentinel rule, and physical bindings.
    This keeps universal quantification expressive without allowing the model
    to invent SQL, sentinel values, or a population denominator.
    """

    policy_id: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    field_ref: SemanticModelFieldRef
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte"]
    values: tuple[str | int | float | bool, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def _coherent_values(self) -> SemanticUniversalCondition:
        if len(self.values) != 1:
            raise ValueError("universal condition requires exactly one value")
        return self


class SemanticIROrder(_FrozenModel):
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    direction: Literal["asc", "desc"]


class SemanticGroupAverageFilter(_FrozenModel):
    """Compare a projected numeric value with its partition average.

    Every member is a governed output alias.  The compiler owns the AVG
    window and comparison SQL, so the model cannot inject an expression or
    change the grouping grain after the base semantic query is validated.
    """

    value_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    partition_by: tuple[str, ...] = Field(min_length=1, max_length=8)
    operator: Literal["gt", "gte", "lt", "lte"]
    average_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )


class SemanticPartitionStatistic(_FrozenModel):
    """A compiler-owned statistic over validated result aliases."""

    value_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    partition_by: tuple[str, ...] = Field(min_length=1, max_length=8)
    aggregate: Literal["sum", "average", "percentile"]
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    value_filter_operator: Literal["gt", "gte", "lt", "lte"] | None = None
    value_filter_value: float | None = None
    percentile: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def _coherent_value_filter(self) -> SemanticPartitionStatistic:
        if (self.value_filter_operator is None) != (self.value_filter_value is None):
            raise ValueError("partition statistic value filter requires operator and value")
        if self.value_filter_value is not None and not math.isfinite(
            self.value_filter_value
        ):
            raise ValueError("partition statistic value filter must be finite")
        if self.aggregate == "percentile":
            if self.percentile is None:
                raise ValueError("percentile partition statistic requires percentile")
            if self.value_filter_operator is not None:
                raise ValueError("percentile partition statistic cannot use value filter")
        elif self.percentile is not None:
            raise ValueError("partition statistic percentile requires percentile aggregate")
        return self


class SemanticResultFilter(_FrozenModel):
    """Compare validated result aliases or one bounded numeric literal."""

    left_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte"]
    right_output_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    values: tuple[float, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def _coherent_comparison(self) -> SemanticResultFilter:
        if (self.right_output_name is None) == (len(self.values) == 0):
            raise ValueError("result filter requires exactly one alias or numeric value")
        if self.values and not math.isfinite(self.values[0]):
            raise ValueError("result filter value must be finite")
        return self


class SemanticCumulativeWindow(_FrozenModel):
    """A deterministic partitioned cumulative sum over a numeric result alias."""

    value_output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    partition_by: tuple[str, ...] = Field(min_length=1, max_length=8)
    order_by: tuple[SemanticIROrder, ...] = Field(min_length=1, max_length=8)
    output_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )


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
    band_summary: SemanticBandSummary | None = None
    two_value_comparison: SemanticTwoValueComparison | None = None
    categorical_pivot: SemanticCategoricalPivot | None = None
    projections: tuple[SemanticIRProjection, ...] = Field(default=(), max_length=32)
    result_expressions: tuple[SemanticResultExpression, ...] = Field(
        default=(), max_length=8
    )
    filters: tuple[SemanticFilter, ...] = Field(default=(), max_length=24)
    having_filters: tuple[SemanticHavingFilter, ...] = Field(default=(), max_length=24)
    any_filter_groups: tuple[SemanticAnyFilterGroup, ...] = Field(default=(), max_length=8)
    universal_conditions: tuple[SemanticUniversalCondition, ...] = Field(
        default=(), max_length=4
    )
    joins: tuple[SemanticIRJoin, ...] = Field(default=(), max_length=4)
    order_by: tuple[SemanticIROrder, ...] = Field(default=(), max_length=8)
    # Independent extrema over a grouped result (for example, the highest
    # and lowest facility type). Each entry reuses the governed projection
    # alias and returns the tied extreme rows deterministically; this is intentionally
    # separate from global top-N ordering.
    extreme_order_by: tuple[SemanticIROrder, ...] = Field(default=(), max_length=2)
    group_average_filter: SemanticGroupAverageFilter | None = None
    group_average_filters: tuple[SemanticGroupAverageFilter, ...] = Field(
        default=(), max_length=8
    )
    partition_statistics: tuple[SemanticPartitionStatistic, ...] = Field(
        default=(), max_length=8
    )
    post_statistic_expressions: tuple[SemanticResultExpression, ...] = Field(
        default=(), max_length=8
    )
    result_filters: tuple[SemanticResultFilter, ...] = Field(default=(), max_length=16)
    cumulative_windows: tuple[SemanticCumulativeWindow, ...] = Field(
        default=(), max_length=4
    )
    post_window_filters: tuple[SemanticResultFilter, ...] = Field(
        default=(), max_length=8
    )
    # Bounded per-partition ranking (for example, top three districts within
    # each settlement classification).  The compiler emits a ROW_NUMBER()
    # window over projected aliases; the model cannot provide SQL text.
    partition_by: tuple[str, ...] = Field(default=(), max_length=8)
    partition_limit: int | None = Field(default=None, ge=1, le=1000)
    partition_rank_output_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    map_value_output_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    distinct_rows: bool = False
    include_result_count: bool = False
    result_count_alias: str = Field(
        default="result_count",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    limit: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _coherent_query(self) -> AdHocSemanticQueryIR:
        if self.status == "unsupported":
            if any(
                (
                    self.semantic_entity,
                    self.spatial_intent is not SpatialIntent.NONE,
                    self.band_summary,
                    self.two_value_comparison,
                    self.categorical_pivot,
                    self.projections,
                    self.result_expressions,
                    self.filters,
                    self.having_filters,
                    self.any_filter_groups,
                    self.universal_conditions,
                    self.joins,
                    self.order_by,
                    self.extreme_order_by,
                    self.group_average_filter,
                    self.group_average_filters,
                    self.partition_statistics,
                    self.post_statistic_expressions,
                    self.result_filters,
                    self.cumulative_windows,
                    self.post_window_filters,
                    self.partition_by,
                    self.partition_limit,
                    self.partition_rank_output_name,
                    self.map_value_output_name,
                    self.distinct_rows,
                    self.include_result_count,
                    self.result_count_alias != "result_count",
                    self.limit,
                )
            ):
                raise ValueError("unsupported semantic query must not contain a plan")
            if not self.reason:
                raise ValueError("unsupported semantic query requires a reason")
            return self
        if not self.semantic_entity or (
            not self.projections
            and self.band_summary is None
            and self.two_value_comparison is None
            and self.categorical_pivot is None
        ):
            raise ValueError("query semantic IR requires an entity and projections or a governed summary")
        if self.band_summary is not None and (
            self.projections
            or self.two_value_comparison is not None
            or self.categorical_pivot is not None
        ):
            raise ValueError("band_summary cannot be combined with ordinary projections")
        if self.two_value_comparison is not None and self.categorical_pivot is not None:
            raise ValueError("use either two-value comparison or categorical pivot")
        if self.group_average_filter is not None and self.group_average_filters:
            raise ValueError("use either group_average_filter or group_average_filters")
        if self.two_value_comparison is not None:
            if self.band_summary is not None or not self.projections:
                raise ValueError("two-value comparison requires ordinary dimensions")
            if any(item.role is ProjectionRole.METRIC for item in self.projections):
                raise ValueError("two-value comparison owns its metric projections")
            if (
                self.having_filters
                or self.universal_conditions
                or self.extreme_order_by
            ):
                raise ValueError(
                    "two-value comparison cannot combine having, universal, or extreme controls"
                )
        if self.categorical_pivot is not None:
            if self.band_summary is not None or not self.projections:
                raise ValueError("categorical pivot requires ordinary dimensions")
            if any(item.role is ProjectionRole.METRIC for item in self.projections):
                raise ValueError("categorical pivot owns its metric projections")
            if self.having_filters or self.universal_conditions or self.extreme_order_by:
                raise ValueError(
                    "categorical pivot cannot combine having, universal, or extreme controls"
                )
        if self.band_summary is not None and (
            self.having_filters
            or self.order_by
            or self.extreme_order_by
            or self.group_average_filter is not None
            or self.group_average_filters
            or self.partition_statistics
            or self.post_statistic_expressions
            or self.result_filters
            or self.cumulative_windows
            or self.post_window_filters
            or self.partition_by
            or self.partition_limit is not None
            or self.partition_rank_output_name is not None
            or self.map_value_output_name is not None
            or self.distinct_rows
            or self.include_result_count
        ):
            raise ValueError("band_summary cannot combine with ordering, grouping controls, or count companion")
        spatial_joins = [join for join in self.joins if join.kind is JoinKind.SPATIAL]
        # A single-entity query can represent a reviewed *source-recorded*
        # spatial scope with a categorical field (for example a planning
        # precinct). Whether that is admissible depends on the published
        # semantic layer and is checked by the compiler, where the field,
        # intent, scope wording, and filter operator can all be verified.
        # Accepting a no-join representation here never grants execution
        # authority.
        if spatial_joins and self.spatial_intent is SpatialIntent.CONTAINS and not any(
            join.operator in {"st_covers", "st_contains"} for join in spatial_joins
        ):
            raise ValueError("contains spatial intent requires covers or contains")
        if spatial_joins and self.spatial_intent is SpatialIntent.WITHIN and not any(
            join.operator in {"st_within", "st_covers", "st_contains", "st_intersects"}
            for join in spatial_joins
        ):
            raise ValueError(
                "within spatial intent requires a containment or reviewed contains-intersects operator"
            )
        if spatial_joins and self.spatial_intent is SpatialIntent.INTERSECTS and not any(
            join.operator == "st_intersects" for join in spatial_joins
        ):
            raise ValueError("intersects spatial intent requires st_intersects")
        if spatial_joins and self.spatial_intent is SpatialIntent.DISTANCE and not any(
            join.operator == "st_dwithin" for join in spatial_joins
        ):
            raise ValueError("distance spatial intent requires st_dwithin")
        output_names = [item.output_name.casefold() for item in self.projections]
        if len(output_names) != len(set(output_names)):
            raise ValueError("semantic IR projection aliases must be unique")
        if self.include_result_count and self.result_count_alias.casefold() in output_names:
            raise ValueError("semantic IR result count alias conflicts with projection")
        field_refs = [
            item.field_ref
            for item in self.projections
            if item.field_ref is not None
        ] + [
            operand
            for item in self.projections
            if item.derived_expression is not None
            for operand in item.derived_expression.operands
        ] + [item.field_ref for item in self.filters] + [
            item.field_ref
            for group in self.any_filter_groups
            for item in group.filters
        ] + [item.field_ref for item in self.having_filters] + [
            item.field_ref for item in self.universal_conditions
        ] + [
            field_ref
            for join in self.joins
            for field_ref in (join.left_field_ref, join.right_field_ref)
        ] + [
            projection.json_array.field_ref
            for projection in self.projections
            if projection.json_array is not None
        ]
        if self.band_summary is not None:
            field_refs.extend(
                [
                    self.band_summary.score_field_ref,
                    self.band_summary.member_field_ref,
                    *self.band_summary.member_disambiguation_field_refs,
                ]
            )
        if self.two_value_comparison is not None:
            field_refs.extend(
                [
                    self.two_value_comparison.scope_field_ref,
                    self.two_value_comparison.measure_field_ref,
                ]
            )
        if self.categorical_pivot is not None:
            field_refs.extend(
                [
                    self.categorical_pivot.scope_field_ref,
                    self.categorical_pivot.measure_field_ref,
                ]
            )
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
        dimension_names = {
            item.output_name.casefold()
            for item in self.projections
            if item.role is ProjectionRole.DIMENSION
        }
        metric_names = {
            item.output_name.casefold()
            for item in self.projections
            if item.role is ProjectionRole.METRIC
        }
        if self.band_summary is not None:
            projected_names.update(
                {
                    self.band_summary.band_output_name.casefold(),
                    self.band_summary.count_output_name.casefold(),
                    self.band_summary.member_output_name.casefold(),
                }
            )
        if self.two_value_comparison is not None:
            projected_names.update(
                {
                    self.two_value_comparison.baseline_output_name.casefold(),
                    self.two_value_comparison.comparison_output_name.casefold(),
                    self.two_value_comparison.difference_output_name.casefold(),
                }
            )
            comparison_names = {
                self.two_value_comparison.baseline_output_name.casefold(),
                self.two_value_comparison.comparison_output_name.casefold(),
                self.two_value_comparison.difference_output_name.casefold(),
            }
            metric_names.update(comparison_names)
            if comparison_names & set(output_names):
                raise ValueError("two-value comparison output aliases conflict with projections")
            if (
                self.include_result_count
                and self.result_count_alias.casefold() in comparison_names
            ):
                raise ValueError("two-value comparison output aliases conflict with result count")
        if self.categorical_pivot is not None:
            pivot_names = {
                item.output_name.casefold()
                for item in self.categorical_pivot.values
            }
            projected_names.update(pivot_names)
            metric_names.update(pivot_names)
            if pivot_names & set(output_names):
                raise ValueError("categorical pivot output aliases conflict with projections")
            if (
                self.include_result_count
                and self.result_count_alias.casefold() in pivot_names
            ):
                raise ValueError("categorical pivot output aliases conflict with result count")
        for result_expression in self.result_expressions:
            output_name = result_expression.output_name.casefold()
            operand_names = {item.casefold() for item in result_expression.operands}
            if output_name in projected_names or output_name in metric_names:
                raise ValueError("result expression output alias conflicts with projections")
            if not operand_names <= metric_names:
                raise ValueError("result expression operands must reference numeric metric outputs")
            if self.include_result_count and output_name == self.result_count_alias.casefold():
                raise ValueError("result expression output alias conflicts with result count")
            projected_names.add(output_name)
            metric_names.add(output_name)
        effective_group_average_filters = (
            (self.group_average_filter,)
            if self.group_average_filter is not None
            else self.group_average_filters
        )
        group_average_input_names = set(metric_names)
        for group_average in effective_group_average_filters:
            value_name = group_average.value_output_name.casefold()
            average_name = group_average.average_output_name.casefold()
            partition_names = {
                str(item).casefold() for item in group_average.partition_by
            }
            if value_name not in group_average_input_names:
                raise ValueError("group average filter requires a projected metric output")
            if not partition_names <= dimension_names:
                raise ValueError("group average filter requires projected dimension partitions")
            if average_name in projected_names or average_name in metric_names:
                raise ValueError("group average output alias conflicts with projections")
            if self.include_result_count and average_name == self.result_count_alias.casefold():
                raise ValueError("group average output alias conflicts with result count")
            projected_names.add(average_name)
            metric_names.add(average_name)
        for statistic in self.partition_statistics:
            value_name = statistic.value_output_name.casefold()
            output_name = statistic.output_name.casefold()
            partition_names = {
                str(item).casefold() for item in statistic.partition_by
            }
            if value_name not in metric_names:
                raise ValueError("partition statistic requires a projected metric output")
            if not partition_names <= dimension_names:
                raise ValueError("partition statistic requires projected dimension partitions")
            if output_name in projected_names or output_name in metric_names:
                raise ValueError("partition statistic output alias conflicts with projections")
            projected_names.add(output_name)
            metric_names.add(output_name)
        for result_expression in self.post_statistic_expressions:
            output_name = result_expression.output_name.casefold()
            operand_names = {item.casefold() for item in result_expression.operands}
            if output_name in projected_names or output_name in metric_names:
                raise ValueError("post-statistic expression output alias conflicts with projections")
            if not operand_names <= metric_names:
                raise ValueError("post-statistic expression operands must reference numeric outputs")
            projected_names.add(output_name)
            metric_names.add(output_name)
        for result_filter in self.result_filters:
            if result_filter.left_output_name.casefold() not in metric_names:
                raise ValueError("result filter left alias must reference a numeric output")
            if (
                result_filter.right_output_name is not None
                and result_filter.right_output_name.casefold() not in metric_names
            ):
                raise ValueError("result filter right alias must reference a numeric output")
        for cumulative in self.cumulative_windows:
            value_name = cumulative.value_output_name.casefold()
            output_name = cumulative.output_name.casefold()
            partition_names = {
                str(item).casefold() for item in cumulative.partition_by
            }
            order_names = {
                item.output_name.casefold() for item in cumulative.order_by
            }
            if value_name not in metric_names or not order_names <= projected_names:
                raise ValueError("cumulative window requires projected numeric and order outputs")
            if not partition_names <= dimension_names:
                raise ValueError("cumulative window requires projected dimension partitions")
            if output_name in projected_names or output_name in metric_names:
                raise ValueError("cumulative window output alias conflicts with projections")
            projected_names.add(output_name)
            metric_names.add(output_name)
        for result_filter in self.post_window_filters:
            if result_filter.left_output_name.casefold() not in metric_names:
                raise ValueError("post-window filter left alias must reference a numeric output")
            if (
                result_filter.right_output_name is not None
                and result_filter.right_output_name.casefold() not in metric_names
            ):
                raise ValueError("post-window filter right alias must reference a numeric output")
        has_metric = any(item.role is ProjectionRole.METRIC for item in self.projections) or (
            self.two_value_comparison is not None or self.categorical_pivot is not None
        )
        if self.having_filters and (not has_metric or not any(
            item.role is ProjectionRole.DIMENSION for item in self.projections
        )):
            raise ValueError("having filters require grouped metric query")
        if any(item.output_name.casefold() not in projected_names for item in self.order_by):
            raise ValueError("semantic IR order must reference a projection alias")
        if any(item.output_name.casefold() not in projected_names for item in self.extreme_order_by):
            raise ValueError("semantic IR extreme order must reference a projection alias")
        if any(str(item).casefold() not in dimension_names for item in self.partition_by):
            raise ValueError("semantic IR partition key must reference a projection alias")
        if self.partition_limit is not None and not self.partition_by:
            raise ValueError("semantic IR partition limit requires partition keys")
        if (
            self.partition_by
            and self.partition_limit is None
            and self.partition_rank_output_name is None
        ):
            raise ValueError("semantic IR partition keys require a limit or rank output")
        if self.partition_by and not self.order_by:
            raise ValueError("semantic IR partition ranking requires order_by")
        if self.partition_by and self.extreme_order_by:
            raise ValueError("semantic IR partition ranking cannot combine extreme ordering")
        if effective_group_average_filters and self.extreme_order_by:
            raise ValueError("group average filter cannot combine extreme ordering")
        if self.result_expressions and self.extreme_order_by:
            raise ValueError("result expressions cannot combine extreme ordering")
        if (
            self.partition_statistics
            or self.post_statistic_expressions
            or self.result_filters
            or self.cumulative_windows
            or self.post_window_filters
        ) and self.extreme_order_by:
            raise ValueError("partition result controls cannot combine extreme ordering")
        if effective_group_average_filters and self.universal_conditions:
            raise ValueError("group average filter cannot combine universal conditions")
        if self.partition_rank_output_name is not None and not self.partition_by:
            raise ValueError("semantic IR partition rank output requires partition ranking")
        if self.partition_rank_output_name is not None:
            rank_name = self.partition_rank_output_name.casefold()
            if rank_name in projected_names or (
                self.include_result_count
                and rank_name == self.result_count_alias.casefold()
            ):
                raise ValueError("partition rank output alias conflicts with projections")
            projected_names.add(rank_name)
        if self.map_value_output_name is not None:
            if self.map_value_output_name.casefold() not in metric_names:
                raise ValueError("map value output must reference a numeric output")
        if self.order_by and self.extreme_order_by:
            raise ValueError("semantic IR cannot combine global and extreme ordering")
        if self.extreme_order_by and not has_metric:
            raise ValueError("semantic IR extrema require an aggregate metric")
        if self.extreme_order_by and not any(
            item.role is ProjectionRole.DIMENSION for item in self.projections
        ):
            raise ValueError("semantic IR extrema require a grouped dimension")
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
    operator: Literal[
        "scan",
        "join",
        "filter",
        "aggregate",
        "window",
        "project",
        "sort",
        "limit",
        "set_operation",
    ]
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


class CategoricalScopeValueResolutionEvidence(_FrozenModel):
    """Row-free evidence for a reviewed, source-bound categorical lookup.

    The lookup runs only at request time for an explicitly reviewed scope. It
    records hashes rather than either the model literal or the source value,
    so a compiled plan remains auditable without turning discovered values
    into semantic-layer metadata.
    """

    scope_id: str = Field(min_length=3, max_length=256)
    semantic_entity: str = Field(min_length=3, max_length=256)
    semantic_field: str = Field(min_length=1, max_length=256)
    strategy: Literal["unique_suffix_source_value"]
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_candidate_count: int = Field(ge=1, le=2)
    source_rows_persisted: Literal[False] = False


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
    # Names appended by the compiler as deterministic tie-breakers after an
    # explicit ordering.  These are presentation metadata only: the model
    # still controls the requested primary ordering, while the compiler
    # prevents LIMIT from selecting an unstable subset when grouped metrics or
    # detail rows are tied.
    compiler_added_ordering_tiebreakers: tuple[str, ...] = ()
    compiler_added_output_names: tuple[str, ...] = ()
    compiler_removed_output_names: tuple[str, ...] = ()
    compiler_hidden_output_names: tuple[str, ...] = ()
    compiler_projection_policy_applications: tuple[str, ...] = ()
    compiler_semantic_filter_corrections: tuple[str, ...] = ()
    # Explicit field-level text comparison policies are governed metadata. The
    # compiler records their IDs so a case-insensitive label match is never a
    # hidden runtime rewrite.
    compiler_text_comparison_policy_ids: tuple[str, ...] = ()
    # A source-recorded categorical scope is distinct from a PostGIS
    # predicate. It is emitted only when a reviewed scope contract admits it.
    compiler_categorical_spatial_scope_ids: tuple[str, ...] = ()
    compiler_categorical_scope_value_resolutions: tuple[
        CategoricalScopeValueResolutionEvidence, ...
    ] = ()
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
            using_columns = join.args.get("using") or []
            select_scope = join
            while getattr(select_scope, "parent", None) is not None and not isinstance(
                select_scope, exp.Select
            ):
                select_scope = select_scope.parent
            right_source = join.this if isinstance(join.this, exp.Table) else None
            right_table = (
                f"{right_source.db}.{right_source.name}"
                if right_source is not None and right_source.db
                else ""
            ).casefold()
            left_sources: list[Any] = []
            if isinstance(select_scope, exp.Select):
                from_clause = select_scope.args.get("from_")
                if from_clause is not None and from_clause.this is not None:
                    left_sources.append(from_clause.this)
                for sibling_join in select_scope.args.get("joins") or []:
                    if sibling_join is join:
                        break
                    left_sources.append(sibling_join.this)
            left_tables = [
                (
                    f"{source.db}.{source.name}".casefold()
                    if isinstance(source, exp.Table) and source.db
                    else ""
                )
                for source in left_sources
            ]
            left_tables = [value for value in left_tables if value]
            using_fields: list[SemanticFieldRef] = []
            for identifier in using_columns:
                field_name = str(getattr(identifier, "name", "") or identifier or "")
                if not field_name or not right_table:
                    continue
                right_ref = f"{right_table}.{field_name}"
                known_columns = {item.casefold() for item in columns}
                if right_ref not in known_columns:
                    continue
                for left_table in left_tables:
                    left_ref = f"{left_table}.{field_name}"
                    if left_ref not in known_columns:
                        continue
                    using_fields.extend(
                        [
                            SemanticFieldRef(table=left_table, field=field_name),
                            SemanticFieldRef(table=right_table, field=field_name),
                        ]
                    )
                    break
            if len(using_fields) < 2:
                raise ValueError("shadow_ir_join_predicate_missing")
            joins.append(
                SemanticJoin(
                    kind=JoinKind.EQUALITY,
                    operator="eq",
                    source_fields=tuple(
                        sorted({(item.table, item.field): item for item in using_fields}.values(), key=lambda item: (item.table, item.field))
                    ),
                    expression_sha256=hashlib.sha256(
                        ("USING(" + ",".join(str(getattr(item, "name", item)) for item in using_columns) + ")").encode("utf-8")
                    ).hexdigest(),
                )
            )
            continue
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


def _json_access_contracts(semantic_layer: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return structurally valid published JSON array contracts."""

    return tuple(
        item
        for item in semantic_layer.get("json_access_contracts") or []
        if isinstance(item, Mapping)
        and str(item.get("table") or "").count(".") == 1
        and str(item.get("json_field") or "")
        and str(item.get("shape") or "").casefold() == "array"
    )


def _json_contract_value_matches(
    value: str | int | float | bool,
    field: Mapping[str, Any],
) -> str:
    """Resolve a model categorical value to the stored source value."""

    if not isinstance(value, str):
        return str(value)
    value_key = re.sub(r"\s+", " ", value.strip()).casefold()
    semantics = field.get("value_semantics") or {}
    for source_value, aliases in semantics.items():
        if value_key == re.sub(r"\s+", " ", str(source_value).strip()).casefold():
            return str(source_value)
        if any(
            value_key == re.sub(r"\s+", " ", str(alias).strip()).casefold()
            for alias in aliases or []
        ):
            return str(source_value)
    return value.strip()


def _json_contract_aliases(contract: Mapping[str, Any], value: str) -> str:
    key = re.sub(r"\s+", " ", value.strip()).casefold()
    for source_value, aliases in (contract.get("indicator_type_value_aliases") or {}).items():
        if key == re.sub(r"\s+", " ", str(source_value).strip()).casefold():
            return str(source_value)
        if any(key == re.sub(r"\s+", " ", str(alias).strip()).casefold() for alias in aliases or []):
            return str(source_value)
    return value.strip()


def _resolve_json_array_contract(
    *,
    semantic_layer: Mapping[str, Any],
    field: Mapping[str, Any],
    value_key: str,
    aggregate: SemanticAggregate,
    semantic_ir: AdHocSemanticQueryIR,
    resolve_field: Any,
) -> Mapping[str, Any]:
    """Resolve a governed JSONB array capability and required type filter."""

    physical_table = str(field.get("physical_table") or "")
    physical_field = str(field.get("physical_field") or "")
    contracts = [
        contract
        for contract in _json_access_contracts(semantic_layer)
        if str(contract.get("table") or "").casefold() == physical_table.casefold()
        and str(contract.get("json_field") or "").casefold() == physical_field.casefold()
        and value_key in {str(item) for item in contract.get("allowed_value_keys") or []}
        and aggregate.value in {
            str(item).casefold() for item in contract.get("allowed_aggregates") or []
        }
    ]
    if len(contracts) != 1:
        raise SemanticIRCompilationError("semantic_json_array_contract_not_found_or_ambiguous")
    contract = contracts[0]
    indicator_field_ref = SemanticModelFieldRef.model_validate(
        contract.get("indicator_type_field")
        or {
            "semantic_entity": str(semantic_ir.semantic_entity),
            "semantic_field": "indicator_type",
        }
    )
    try:
        indicator_field = resolve_field(indicator_field_ref)
    except Exception as exc:
        raise SemanticIRCompilationError("semantic_json_indicator_type_field_missing") from exc
    required_physical = str(
        contract.get("indicator_type_physical_field") or "indicator_type"
    ).casefold()
    if str(indicator_field.get("physical_field") or "").casefold() != required_physical:
        raise SemanticIRCompilationError("semantic_json_indicator_type_field_mismatch")
    allowed_types = {
        str(item).casefold() for item in contract.get("allowed_indicator_types") or []
    }
    if not allowed_types:
        raise SemanticIRCompilationError("semantic_json_indicator_types_missing")

    matched_values: list[str] = []
    for filter_spec in semantic_ir.filters:
        try:
            filter_field = resolve_field(filter_spec.field_ref)
        except Exception:
            continue
        if str(filter_field.get("physical_field") or "").casefold() != required_physical:
            continue
        if filter_spec.operator not in {"eq", "in"}:
            continue
        matched_values.extend(
            _json_contract_aliases(contract, _json_contract_value_matches(value, indicator_field))
            for value in filter_spec.values
        )
    if not matched_values:
        raise SemanticIRCompilationError("semantic_json_array_indicator_filter_required")
    if not set(value.casefold() for value in matched_values) <= allowed_types:
        raise SemanticIRCompilationError("semantic_json_indicator_type_not_allowed")
    return contract


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


def _semantic_entity_reference_keys(semantic_ir: AdHocSemanticQueryIR) -> set[str]:
    """Collect model-authored entity identities before compiler repair.

    Compiler-only governance source representations are intentionally absent
    from the public ontology surface.  Capturing the original references lets
    the compiler admit an entity that it injects for a mandatory row scope
    while still rejecting the same entity when it came from model output.
    """

    keys: set[str] = set()
    pending: list[Any] = [semantic_ir.model_dump(mode="python")]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            entity = value.get("semantic_entity")
            if isinstance(entity, str) and (key := _semantic_alias_key(entity)):
                keys.add(key)
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    return keys


def _semantic_field_reference_keys(
    semantic_ir: AdHocSemanticQueryIR,
) -> set[tuple[str, str]]:
    """Collect the model-authored logical field references in an IR."""

    keys: set[tuple[str, str]] = set()
    pending: list[Any] = [semantic_ir.model_dump(mode="python")]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            entity = value.get("semantic_entity")
            field = value.get("semantic_field")
            if isinstance(entity, str) and isinstance(field, str):
                entity_key = _semantic_alias_key(entity)
                field_key = _semantic_alias_key(field)
                if entity_key and field_key:
                    keys.add((entity_key, field_key))
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    return keys


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
    *,
    allow_compiler_governance_support: bool = False,
) -> Mapping[str, Any]:
    active_bindings = [
        item
        for item in semantic_layer.get("table_bindings") or []
        if isinstance(item, Mapping)
        and (
            _binding_is_execution_active(item)
            or (
                allow_compiler_governance_support
                and item.get("compiler_governance_support") is True
            )
        )
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
    query_identifier_key = re.sub(
        r"[_\W]+",
        "",
        str(field_ref.semantic_field or "").casefold(),
        flags=re.UNICODE,
    )
    candidates = []
    for field in binding.get("fields") or []:
        if not isinstance(field, Mapping):
            continue
        labels = (field.get("labels") or {}).values()
        aliases = field.get("aliases") or []
        keys = {
            _semantic_alias_key(value)
            for value in (
                field.get("semantic_field"),
                field.get("physical_field"),
                *labels,
                *aliases,
            )
            if _semantic_alias_key(value)
        }
        identifier_keys = {
            re.sub(r"[_\W]+", "", str(value or "").casefold(), flags=re.UNICODE)
            for value in (
                field.get("semantic_field"),
                field.get("physical_field"),
            )
            if str(value or "").strip()
        }
        if query_key in keys or (
            query_identifier_key and query_identifier_key in identifier_keys
        ):
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


def _scope_wording_matches(
    question: str | None,
    language: str,
    scope: Mapping[str, Any],
) -> bool:
    """Require published scope wording before allowing a categorical scope."""

    if not question:
        return False
    groups_by_language = scope.get("required_scope_term_groups") or {}
    groups = groups_by_language.get(language) or []
    if not isinstance(groups, list) or not groups:
        return False
    normalized_question = re.sub(r"\s+", " ", str(question).casefold())
    for group in groups:
        if not isinstance(group, list) or not group:
            return False
        if not any(
            str(term).strip()
            and re.sub(r"\s+", " ", str(term).casefold().strip())
            in normalized_question
            for term in group
        ):
            return False
    return True


def _reviewed_categorical_spatial_scope_ids(
    *,
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    expected_spatial_intent: SpatialIntent,
    question: str | None,
    resolve_field: Any,
) -> tuple[str, ...]:
    """Resolve only explicitly reviewed source-recorded categorical scopes.

    A categorical scope describes a source classification, not a geometric
    predicate. A spatial join remains mandatory unless this function matches
    the exact logical field, published wording, allowed intent, and filter
    operator from semantic metadata.
    """

    if (
        expected_spatial_intent is SpatialIntent.NONE
        or semantic_ir.spatial_intent is not expected_spatial_intent
        or any(join.kind is JoinKind.SPATIAL for join in semantic_ir.joins)
    ):
        return ()
    matches: list[str] = []
    for scope in semantic_layer.get("categorical_spatial_scopes") or []:
        if not isinstance(scope, Mapping):
            continue
        if str(scope.get("review_status") or "").casefold() != "reviewed":
            continue
        if str(scope.get("scope_kind") or "") != "source_recorded_categorical_scope":
            continue
        scope_id = str(scope.get("scope_id") or "").strip()
        entity = str(scope.get("semantic_entity") or "").strip()
        field_name = str(scope.get("semantic_field") or "").strip()
        supported_intents = {
            str(value).casefold()
            for value in scope.get("supported_spatial_intents") or []
        }
        allowed_operators = {
            str(value).casefold()
            for value in scope.get("allowed_filter_operators") or []
        }
        if (
            not scope_id
            or not entity
            or not field_name
            or expected_spatial_intent.value not in supported_intents
            or not _scope_wording_matches(question, semantic_ir.language, scope)
        ):
            continue
        for filter_spec in semantic_ir.filters:
            if (
                filter_spec.field_ref.semantic_entity != entity
                or filter_spec.field_ref.semantic_field != field_name
                or filter_spec.operator not in allowed_operators
                or not filter_spec.values
            ):
                continue
            # Resolve before admission so only active governed fields are used;
            # normal compiler parameterization still applies to values.
            resolve_field(filter_spec.field_ref)
            matches.append(scope_id)
            break
    return tuple(sorted(set(matches)))


def _apply_reviewed_row_scope_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    question: str | None,
) -> tuple[
    AdHocSemanticQueryIR,
    tuple[str, ...],
    tuple[SemanticFilter, ...],
]:
    """Inject mandatory reviewed row scopes into an otherwise valid IR.

    Row scopes are governance configuration, not model-selected business
    filters. A policy is applied only when its reviewed equality join is
    unique, its boolean predicate maps to a reviewed semantic field, and the
    question has not explicitly asked to bypass the default scope. Model
    predicates on a compiler-owned row-scope field are removed before the
    reviewed predicate is injected, so an untrusted proposal cannot weaken or
    accidentally empty the governed scope. Ambiguous and unsupported policies
    remain fail-closed at compilation.
    """

    policies = semantic_layer.get("row_scope_policies") or []
    if not policies or semantic_ir.status != "query":
        return semantic_ir, (), ()

    bindings_by_entity: dict[str, Mapping[str, Any]] = {}
    bindings_by_table: dict[str, Mapping[str, Any]] = {}
    entities_by_table: dict[str, str] = {}
    for binding in semantic_layer.get("table_bindings") or []:
        if not isinstance(binding, Mapping):
            continue
        entity = str(binding.get("semantic_entity") or "").strip()
        table = str(binding.get("physical_table") or "").strip()
        if not entity or not table:
            continue
        bindings_by_entity[entity] = binding
        bindings_by_table[table.casefold()] = binding
        entities_by_table[table.casefold()] = entity

    def endpoint(value: Any) -> tuple[str, str] | None:
        table, separator, field = str(value or "").rpartition(".")
        if not separator or not table or not field:
            return None
        return table.casefold(), field.casefold()

    def logical_ref(table_key: str, field_key: str) -> SemanticModelFieldRef | None:
        binding = bindings_by_table.get(table_key)
        entity = entities_by_table.get(table_key)
        if not isinstance(binding, Mapping) or not entity:
            return None
        matches = [
            str(field.get("semantic_field") or "")
            for field in binding.get("fields") or []
            if isinstance(field, Mapping)
            and str(field.get("physical_field") or "").casefold() == field_key
            and str(field.get("semantic_field") or "").strip()
        ]
        if len(matches) != 1:
            return None
        return SemanticModelFieldRef(
            semantic_entity=entity,
            semantic_field=matches[0],
        )

    selected_entities: set[str] = {
        value
        for value in [semantic_ir.semantic_entity]
        if isinstance(value, str) and value
    }
    for projection in semantic_ir.projections:
        if projection.field_ref is not None:
            selected_entities.add(projection.field_ref.semantic_entity)
        if projection.derived_expression is not None:
            selected_entities.update(
                operand.semantic_entity for operand in projection.derived_expression.operands
            )
        if projection.json_array is not None:
            selected_entities.add(projection.json_array.field_ref.semantic_entity)
    for filter_spec in semantic_ir.filters:
        selected_entities.add(filter_spec.field_ref.semantic_entity)
    for join in semantic_ir.joins:
        selected_entities.update(
            (join.left_field_ref.semantic_entity, join.right_field_ref.semantic_entity)
        )
    selected_tables = {
        str(bindings_by_entity[entity].get("physical_table") or "").casefold()
        for entity in selected_entities
        if entity in bindings_by_entity
        and str(bindings_by_entity[entity].get("physical_table") or "")
    }
    if not selected_tables:
        return semantic_ir, (), ()

    normalized_question = " ".join(str(question or "").casefold().split())
    filters = list(semantic_ir.filters)
    joins = list(semantic_ir.joins)
    corrections: list[str] = []
    compiler_added_filters: list[SemanticFilter] = []

    def joins_match(
        left: SemanticModelFieldRef,
        right: SemanticModelFieldRef,
    ) -> bool:
        requested = frozenset(
            (
                (left.semantic_entity, left.semantic_field),
                (right.semantic_entity, right.semantic_field),
            )
        )
        return any(
            join.kind is JoinKind.EQUALITY
            and join.operator == "eq"
            and frozenset(
                (
                    (join.left_field_ref.semantic_entity, join.left_field_ref.semantic_field),
                    (join.right_field_ref.semantic_entity, join.right_field_ref.semantic_field),
                )
            )
            == requested
            for join in joins
        )

    for policy in policies:
        if not isinstance(policy, Mapping) or not str(
            policy.get("review_status") or ""
        ).casefold().startswith("reviewed"):
            continue
        policy_id = str(policy.get("policy_id") or "unknown")
        applies_to = {
            str(table).casefold()
            for table in policy.get("applies_to_tables") or []
            if str(table).strip()
        }
        if not applies_to or not (selected_tables & applies_to):
            continue
        override_terms = (
            policy.get("explicit_override_terms") or {}
        ).get(semantic_ir.language) or []
        if any(
            str(term).strip() and " ".join(str(term).casefold().split()) in normalized_question
            for term in override_terms
        ):
            continue
        predicate = policy.get("required_predicate") or {}
        predicate_table = str(predicate.get("table") or "").casefold()
        predicate_field = str(predicate.get("field") or "").casefold()
        if (
            not predicate_table
            or not predicate_field
            or str(predicate.get("operator") or "").casefold() != "is_true"
        ):
            raise SemanticIRCompilationError("semantic_ir_row_scope_policy_invalid")
        predicate_ref = logical_ref(predicate_table, predicate_field)
        if predicate_ref is None:
            raise SemanticIRCompilationError("semantic_ir_row_scope_predicate_unbound")

        if predicate_table not in selected_tables:
            relation_candidates: list[tuple[SemanticModelFieldRef, SemanticModelFieldRef]] = []
            for relation in semantic_layer.get("relationships") or []:
                if not isinstance(relation, Mapping) or not str(
                    relation.get("review_status") or ""
                ).casefold().startswith("reviewed"):
                    continue
                if str(relation.get("kind") or "").casefold() != "equality" or str(
                    relation.get("operator") or ""
                ).casefold() not in {"=", "eq"}:
                    continue
                left = endpoint(relation.get("left"))
                right = endpoint(relation.get("right"))
                if left is None or right is None:
                    continue
                if left[0] == predicate_table and right[0] in selected_tables:
                    source_endpoint, predicate_endpoint = right, left
                elif right[0] == predicate_table and left[0] in selected_tables:
                    source_endpoint, predicate_endpoint = left, right
                else:
                    continue
                source_ref = logical_ref(*source_endpoint)
                relation_predicate_ref = logical_ref(*predicate_endpoint)
                if (
                    source_ref is not None
                    and relation_predicate_ref is not None
                    and relation_predicate_ref.semantic_entity == predicate_ref.semantic_entity
                ):
                    relation_candidates.append((source_ref, relation_predicate_ref))
            unique_candidates = list(
                dict.fromkeys(
                    (left.model_dump_json(), right.model_dump_json())
                    for left, right in relation_candidates
                )
            )
            if len(unique_candidates) != 1:
                raise SemanticIRCompilationError("semantic_ir_row_scope_join_unavailable")
            source_ref = SemanticModelFieldRef.model_validate_json(unique_candidates[0][0])
            relation_predicate_ref = SemanticModelFieldRef.model_validate_json(
                unique_candidates[0][1]
            )
            if not joins_match(source_ref, relation_predicate_ref):
                joins.append(
                    SemanticIRJoin(
                        left_field_ref=source_ref,
                        right_field_ref=relation_predicate_ref,
                        kind=JoinKind.EQUALITY,
                        operator="eq",
                    )
                )
            selected_tables.add(predicate_table)
            selected_entities.add(predicate_ref.semantic_entity)

        matching_filters = [
            filter_spec
            for filter_spec in filters
            if filter_spec.field_ref == predicate_ref
        ]
        if matching_filters:
            if all(
                filter_spec.operator in {"eq", "in"}
                and set(filter_spec.values) == {True}
                for filter_spec in matching_filters
            ):
                correction = "semantic_ir_normalized_row_scope_filter:"
            else:
                correction = "semantic_ir_removed_conflicting_row_scope_filter:"
            # The reviewed scope is always injected below.  A model can restate
            # it, or emit a contradictory predicate, but neither is allowed to
            # affect a compiler-owned governance scope.
            filters = [
                filter_spec
                for filter_spec in filters
                if filter_spec not in matching_filters
            ]
            corrections.append(correction + policy_id)
        compiler_filter = SemanticFilter(
            field_ref=predicate_ref,
            operator="eq",
            values=(True,),
        )
        filters.append(compiler_filter)
        compiler_added_filters.append(compiler_filter)
        corrections.append("semantic_ir_applied_row_scope:" + policy_id)

    if not corrections:
        return semantic_ir, (), ()
    return (
        AdHocSemanticQueryIR.model_validate(
            {
                **semantic_ir.model_dump(mode="python"),
                "filters": [item.model_dump(mode="python") for item in filters],
                "joins": [item.model_dump(mode="python") for item in joins],
            }
        ),
        tuple(dict.fromkeys(corrections)),
        tuple(compiler_added_filters),
    )


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
    filter_spec: SemanticFilter | SemanticHavingFilter,
    *,
    field: Mapping[str, Any],
    alias: str,
    parameter_bindings: dict[str, str | int | float | bool],
    next_parameter_index: int,
    parameter_name_prefix: str = "gda_p",
    expression_override: str | None = None,
    text_comparison_policy_ids: list[str] | None = None,
) -> tuple[str, int]:
    field_sql = expression_override or _field_sql(field, alias=alias)
    operator = filter_spec.operator
    if operator == "is_null":
        return f"{field_sql} IS NULL", next_parameter_index
    if operator == "not_null":
        return f"{field_sql} IS NOT NULL", next_parameter_index

    values = [_validate_scalar_parameter(value) for value in filter_spec.values]
    if filter_spec.operator in {"eq", "neq", "in", "not_in", "contains", "prefix"}:
        def value_key(value: Any) -> str:
            # Source-bound values commonly use underscores while users type
            # spaces or hyphens.  This is a representation normalization only;
            # the resulting value must still resolve to an explicit source
            # value published in the semantic contract.
            return re.sub(r"\s+", " ", str(value).replace("_", " ").replace("-", " ").strip()).casefold()

        value_semantics = field.get("value_semantics") or {}
        # Build this map with first-wins semantics.  Semantic catalogs may
        # contain duplicate source keys that differ only by case (for
        # example ``AP50`` and ``ap50``); a dict comprehension lets the last
        # duplicate silently replace the canonical source token and can make
        # a valid PostgreSQL filter return zero rows.  First-wins preserves
        # the catalog's declared order, while the observed source domain
        # below provides the final canonical spelling when available.
        alias_to_source: dict[str, str] = {}
        for source_value, aliases in value_semantics.items():
            source_text = str(source_value).strip()
            if not source_text:
                continue
            alias_values = (source_text, *(aliases if isinstance(aliases, list) else [aliases]))
            for alias in alias_values:
                if str(alias).strip():
                    alias_to_source.setdefault(value_key(alias), source_text)
        # An observed source domain is sufficient to support safe separator/
        # case variants even when the customer glossary has no bespoke alias.
        # It never invents a new value; it only canonicalizes to the observed
        # source token.
        observed_source_values = (
            field.get("source_value_domain_observed")
            or field.get("value_domain")
            or []
        )
        for source_value in observed_source_values:
            if str(source_value).strip():
                # Observed values are the source-of-truth representation for
                # execution.  They override case/separator-colliding glossary
                # entries but never invent a value outside the reviewed
                # domain.
                alias_to_source[value_key(source_value)] = str(source_value).strip()

        value_set_aliases: dict[str, list[str]] = {}
        for item in field.get("value_set_semantics") or []:
            if not isinstance(item, Mapping):
                continue
            source_values = [
                str(source_value).strip()
                for source_value in item.get("source_values") or item.get("values") or []
                if str(source_value).strip()
            ]
            if not source_values:
                continue
            for alias in item.get("aliases") or []:
                if str(alias).strip():
                    value_set_aliases[value_key(alias)] = source_values

        expanded_values: list[Any] = []
        used_value_set = False
        for value in values:
            if isinstance(value, str):
                normalized = value_key(value)
                group_values = value_set_aliases.get(normalized)
                if group_values and filter_spec.operator in {"eq", "neq", "in", "not_in"}:
                    expanded_values.extend(group_values)
                    used_value_set = True
                    continue
                expanded_values.append(alias_to_source.get(normalized, value))
            else:
                expanded_values.append(value)
        values = expanded_values
        if used_value_set and filter_spec.operator == "eq":
            operator = "in"
        elif used_value_set and filter_spec.operator == "neq":
            operator = "not_in"
        # Avoid duplicate placeholders when a group alias and an explicit
        # member name are both supplied in an IN predicate.
        if operator in {"in", "not_in"}:
            deduped: list[Any] = []
            seen: set[str] = set()
            for value in values:
                key = repr(value)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(value)
            values = deduped

    text_policy = field.get("text_comparison_policy")
    if text_policy is not None and operator in {"eq", "neq", "in", "not_in"}:
        if not isinstance(text_policy, Mapping):
            raise SemanticIRCompilationError("semantic_text_comparison_policy_invalid")
        policy_id = str(text_policy.get("policy_id") or "").strip()
        review_status = str(text_policy.get("review_status") or "").casefold()
        execution_authorized = text_policy.get("execution_authorized") is True
        allowed_operators = {
            str(value).casefold()
            for value in text_policy.get("allowed_operators") or []
            if str(value).strip()
        }
        normalization = str(text_policy.get("normalization") or "").casefold()
        if not policy_id or not review_status.startswith("reviewed") or not execution_authorized:
            raise SemanticIRCompilationError("semantic_text_comparison_policy_not_reviewed")
        if operator in allowed_operators:
            if normalization != "trim_uppercase_v1":
                raise SemanticIRCompilationError(
                    "semantic_text_comparison_normalization_unsupported"
                )
            if not all(isinstance(value, str) for value in values):
                raise SemanticIRCompilationError(
                    "semantic_text_comparison_requires_text_values"
                )
            field_sql = f"UPPER(BTRIM({field_sql}))"
            values = [value.strip().upper() for value in values]
            if text_comparison_policy_ids is not None:
                text_comparison_policy_ids.append(policy_id)
    placeholders: list[str] = []
    for value in values:
        name = f"{parameter_name_prefix}_{next_parameter_index:03d}"
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


def _apply_display_projection_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Add reviewed display companions to a logical result when required.

    A display policy is semantic metadata, not a question or answer lookup.
    It may declare that a primary label has one or more companion dimensions
    needed to disambiguate entities in grouped, ranked, or list results.  The
    compiler applies only policies whose entity/field bindings are active and
    whose companion fields are present in the same governed entity.
    """

    if not semantic_ir.projections:
        return semantic_ir, ()
    bindings = {
        str(item.get("semantic_entity") or ""): item
        for item in semantic_layer.get("table_bindings") or []
        if isinstance(item, dict) and str(item.get("semantic_entity") or "")
    }
    policies = {
        str(item.get("policy_id") or ""): item
        for item in semantic_layer.get("display_projection_policies") or []
        if isinstance(item, dict)
        and item.get("review_status") == "reviewed"
        and str(item.get("policy_id") or "")
    }
    if not policies:
        return semantic_ir, ()
    projected = list(semantic_ir.projections)
    projected_keys = {
        (
            item.field_ref.semantic_entity,
            item.field_ref.semantic_field,
        )
        for item in projected
        if item.field_ref is not None
    }
    projected_names = {item.output_name.casefold() for item in projected}
    added_names: list[str] = []
    for item in tuple(projected):
        if item.field_ref is None or item.role not in {
            ProjectionRole.ATTRIBUTE,
            ProjectionRole.DIMENSION,
        }:
            continue
        binding = bindings.get(item.field_ref.semantic_entity)
        if not binding or binding.get("execution_eligible") is not True:
            continue
        field = next(
            (
                field
                for field in binding.get("fields") or []
                if isinstance(field, dict)
                and str(field.get("semantic_field") or "")
                == item.field_ref.semantic_field
            ),
            None,
        )
        if not field:
            continue
        policy_id = str(field.get("display_companion_policy_id") or "")
        policy = policies.get(policy_id)
        if not policy or str(policy.get("semantic_entity") or "") != item.field_ref.semantic_entity:
            continue
        if str(policy.get("primary_label_field") or "") != item.field_ref.semantic_field:
            continue
        companions = policy.get("companion_fields") or field.get("display_companion_fields") or []
        if not isinstance(companions, list):
            continue
        companion_insert_at = projected.index(item) + 1
        for companion_name in companions:
            companion_name = str(companion_name or "").strip()
            if not companion_name:
                continue
            key = (item.field_ref.semantic_entity, companion_name)
            if key in projected_keys:
                continue
            companion = next(
                (
                    candidate
                    for candidate in binding.get("fields") or []
                    if isinstance(candidate, dict)
                    and str(candidate.get("semantic_field") or "") == companion_name
                ),
                None,
            )
            if not companion:
                continue
            output_name = str(
                companion.get("display_output_name")
                or companion.get("semantic_field")
                or companion_name
            ).strip()
            if not output_name or output_name.casefold() in projected_names:
                continue
            role = (
                ProjectionRole.DIMENSION
                if item.role is ProjectionRole.DIMENSION
                else ProjectionRole.ATTRIBUTE
            )
            projected.insert(
                companion_insert_at,
                SemanticIRProjection(
                    output_name=output_name,
                    role=role,
                    field_ref=SemanticModelFieldRef(
                        semantic_entity=item.field_ref.semantic_entity,
                        semantic_field=companion_name,
                    ),
                ),
            )
            companion_insert_at += 1
            projected_keys.add(key)
            projected_names.add(output_name.casefold())
            added_names.append(output_name)
    if not added_names:
        return semantic_ir, ()
    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "projections": [item.model_dump(mode="python") for item in projected],
        }
    )
    return effective, tuple(added_names)


def _apply_reviewed_entity_list_projection_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    *,
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Trim unrequested direct attributes from a simple entity-list IR.

    This is the typed-IR counterpart of the baseline SQL projection gate.
    The policy is configuration-driven and only keeps the reviewed primary
    label plus declared disambiguating companions when the user asks which
    entities qualify without requesting attributes. Aggregates, grouping,
    derived expressions, and explicit attribute wording fail open.
    """

    if (
        not question
        or semantic_ir.status != "query"
        or not question_is_entity_list(question, semantic_ir.language)
        or question_requests_explicit_attributes(question, semantic_ir.language)
        or semantic_ir.having_filters
        or semantic_ir.band_summary is not None
        or semantic_ir.partition_by
        or semantic_ir.extreme_order_by
        or semantic_ir.include_result_count
    ):
        return semantic_ir, ()
    if any(
        projection.role is ProjectionRole.METRIC
        or projection.derived_measure is not None
        or projection.derived_expression is not None
        or projection.json_array is not None
        or projection.field_ref is None
        for projection in semantic_ir.projections
    ):
        return semantic_ir, ()

    policies = [
        item
        for item in semantic_layer.get("display_projection_policies") or []
        if isinstance(item, Mapping)
        and item.get("review_status") == "reviewed"
        and item.get("trim_unrequested_attributes") is True
        and str(item.get("primary_label_field") or "").strip()
        and "entity_list"
        in {str(value) for value in item.get("application") or []}
    ]
    for policy in policies:
        physical_table = str(policy.get("physical_table") or "").strip().casefold()
        primary_label = str(policy.get("primary_label_field") or "").strip()
        candidates: list[tuple[str, str]] = []
        for binding in semantic_layer.get("table_bindings") or ():
            if not isinstance(binding, Mapping):
                continue
            if str(binding.get("physical_table") or "").strip().casefold() != physical_table:
                continue
            entity = str(binding.get("semantic_entity") or "").strip()
            if not entity:
                continue
            candidates.append((entity, primary_label))
        if len(candidates) != 1:
            continue
        entity, _label = candidates[0]
        allowed = {primary_label.casefold()}
        allowed.update(
            str(value).strip().casefold()
            for value in policy.get("companion_fields") or []
            if str(value).strip()
        )
        label_projection = next(
            (
                projection
                for projection in semantic_ir.projections
                if projection.field_ref is not None
                and projection.field_ref.semantic_entity == entity
                and projection.field_ref.semantic_field.casefold() == primary_label.casefold()
            ),
            None,
        )
        if label_projection is None:
            continue
        kept = [
            projection
            for projection in semantic_ir.projections
            if projection.field_ref is not None
            and (
                # Keep explicitly projected fields from joined entities. A
                # simple entity-list query may still request one measure from
                # a fact table (for example ``district_name`` plus
                # ``needed_ap50``). The presentation gate trims incidental
                # attributes belonging to the primary label entity, but it
                # must not erase a governed field the model selected from a
                # related entity.
                projection.field_ref.semantic_entity != entity
                or projection.field_ref.semantic_field.casefold() in allowed
            )
        ]
        if not kept or len(kept) == len(semantic_ir.projections):
            continue
        removed = tuple(
            projection.output_name
            for projection in semantic_ir.projections
            if projection not in kept
        )
        effective = AdHocSemanticQueryIR.model_validate(
            {
                **semantic_ir.model_dump(mode="python"),
                "projections": [item.model_dump(mode="python") for item in kept],
            }
        )
        return effective, removed
    return semantic_ir, ()


def _apply_projection_completeness_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    *,
    question: str | None,
) -> tuple[
    AdHocSemanticQueryIR,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Add missing direct logical fields from reviewed collection metadata."""

    if not question or not semantic_ir.projections:
        return semantic_ir, (), (), ()
    # A provider may use the ``metric`` role for a directly stored detail
    # value. Only an actual aggregate changes the requested row grain and is
    # therefore outside a detail-projection completeness policy.
    if any(item.aggregate is not None for item in semantic_ir.projections):
        return semantic_ir, (), (), ()
    try:
        validate_projection_completeness_policies(semantic_layer)
    except ProjectionCompletenessPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc
    referenced_entities = {
        semantic_ir.semantic_entity or "",
        *(
            projection.field_ref.semantic_entity
            for projection in semantic_ir.projections
            if projection.field_ref is not None
        ),
        *(item.field_ref.semantic_entity for item in semantic_ir.filters),
        *(item.field_ref.semantic_entity for item in semantic_ir.having_filters),
        *(
            item.field_ref.semantic_entity
            for group in semantic_ir.any_filter_groups
            for item in group.filters
        ),
        *(
            field_ref.semantic_entity
            for join in semantic_ir.joins
            for field_ref in (join.left_field_ref, join.right_field_ref)
        ),
    }
    policies = resolve_projection_completeness_policies(
        question=question,
        language=semantic_ir.language,
        semantic_layer=semantic_layer,
        semantic_entities=referenced_entities,
    )
    if not policies:
        return semantic_ir, (), (), ()

    projected = list(semantic_ir.projections)
    added_names: list[str] = []
    removed_names: list[str] = []
    applied_policy_ids: list[str] = []
    for policy in policies:
        policy_id = str(policy.get("policy_id") or "")
        semantic_entity = str(policy.get("semantic_entity") or "")
        required_fields = list(policy.get("required_fields") or [])
        required_names = {
            str(item.get("semantic_field") or "") for item in required_fields
        }
        policy_removed = False
        if str(policy.get("projection_mode") or "complete").casefold() == (
            "exact_on_selected_entity"
        ):
            kept: list[SemanticIRProjection] = []
            for projection in projected:
                if (
                    projection.field_ref is not None
                    and projection.field_ref.semantic_entity == semantic_entity
                    and projection.field_ref.semantic_field not in required_names
                ):
                    removed_names.append(projection.output_name)
                    policy_removed = True
                    continue
                kept.append(projection)
            projected = kept
        projected_names = {item.output_name.casefold() for item in projected}
        existing_indexes = [
            index
            for index, projection in enumerate(projected)
            if projection.field_ref is not None
            and projection.field_ref.semantic_entity == semantic_entity
            and projection.field_ref.semantic_field in required_names
        ]
        insert_at = max(existing_indexes) + 1 if existing_indexes else len(projected)
        policy_added = False
        for field in required_fields:
            semantic_field = str(field.get("semantic_field") or "")
            if any(
                projection.field_ref is not None
                and projection.field_ref.semantic_entity == semantic_entity
                and projection.field_ref.semantic_field == semantic_field
                for projection in projected
            ):
                continue
            output_name = str(field.get("output_name") or semantic_field)
            if output_name.casefold() in projected_names:
                raise SemanticIRCompilationError(
                    f"projection_completeness_output_alias_conflict:{policy_id}:{output_name}"
                )
            projected.insert(
                insert_at,
                SemanticIRProjection(
                    output_name=output_name,
                    role=ProjectionRole(str(field.get("role") or "attribute")),
                    field_ref=SemanticModelFieldRef(
                        semantic_entity=semantic_entity,
                        semantic_field=semantic_field,
                    ),
                ),
            )
            insert_at += 1
            projected_names.add(output_name.casefold())
            added_names.append(output_name)
            policy_added = True
        if policy_added or policy_removed:
            applied_policy_ids.append(policy_id)
    if not added_names and not removed_names:
        return semantic_ir, (), (), ()
    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "projections": [item.model_dump(mode="python") for item in projected],
        }
    )
    return (
        effective,
        tuple(added_names),
        tuple(removed_names),
        tuple(applied_policy_ids),
    )


def validate_derived_projection_policies(
    semantic_layer: Mapping[str, Any],
) -> None:
    """Validate config-driven arithmetic projection replacements."""

    policies = semantic_layer.get("derived_projection_policies") or []
    if not isinstance(policies, list):
        raise DerivedProjectionPolicyError("derived_projection_policies_invalid")
    bindings = {
        str(binding.get("semantic_entity") or ""): binding
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping) and str(binding.get("semantic_entity") or "")
    }
    seen: set[str] = set()
    for policy in policies:
        if not isinstance(policy, Mapping):
            raise DerivedProjectionPolicyError("derived_projection_policy_invalid")
        policy_id = str(policy.get("policy_id") or "")
        if not policy_id or policy_id in seen:
            raise DerivedProjectionPolicyError("derived_projection_policy_id_invalid")
        seen.add(policy_id)
        if (
            policy.get("review_status") != "reviewed"
            or policy.get("operation")
            != "replace_direct_projection_with_derived_expression"
            or policy.get("operator") not in {"add", "subtract", "multiply", "divide"}
        ):
            raise DerivedProjectionPolicyError(
                f"derived_projection_policy_contract_invalid:{policy_id}"
            )
        match = policy.get("match") or {}
        groups_by_language = match.get("required_term_groups") or {}
        if not isinstance(groups_by_language, Mapping) or any(
            not isinstance(groups_by_language.get(language), list)
            or not groups_by_language.get(language)
            or any(
                not isinstance(group, list)
                or not group
                or any(not str(term).strip() for term in group)
                for group in groups_by_language.get(language) or []
            )
            for language in ("zh", "en", "ar")
        ):
            raise DerivedProjectionPolicyError(
                f"derived_projection_policy_match_invalid:{policy_id}"
            )
        target = policy.get("target_field_ref") or {}
        operands = policy.get("operand_field_refs") or []
        if not isinstance(target, Mapping) or not isinstance(operands, list) or not 2 <= len(operands) <= 4:
            raise DerivedProjectionPolicyError(
                f"derived_projection_policy_fields_invalid:{policy_id}"
            )
        references = [target, *operands]
        entities = {str(item.get("semantic_entity") or "") for item in references}
        if len(entities) != 1 or "" in entities:
            raise DerivedProjectionPolicyError(
                f"derived_projection_policy_fields_invalid:{policy_id}"
            )
        binding = bindings.get(next(iter(entities)))
        fields = {
            str(field.get("semantic_field") or ""): field
            for field in (binding or {}).get("fields") or ()
            if isinstance(field, Mapping)
        }
        names = [str(item.get("semantic_field") or "") for item in references]
        if any(name not in fields for name in names):
            raise DerivedProjectionPolicyError(
                f"derived_projection_policy_fields_invalid:{policy_id}"
            )
        for name in names[1:]:
            field = fields[name]
            data_type = str(
                (field.get("technical_metadata") or {}).get("data_type")
                or field.get("data_type")
                or ""
            ).casefold()
            if str(field.get("business_role") or "").casefold() not in {"measure", "metric"} and not any(
                token in data_type
                for token in ("int", "numeric", "decimal", "double", "real", "float")
            ):
                raise DerivedProjectionPolicyError(
                    f"derived_projection_policy_operand_not_numeric:{policy_id}:{name}"
                )


def validate_two_value_comparison_policies(
    semantic_layer: Mapping[str, Any],
) -> None:
    """Validate reviewed same-entity categorical comparison policies.

    The policy supplies the only admissible pairing grain, dimensions, and
    categorical domain.  A planner can therefore ask for a comparison, but it
    cannot turn that into an arbitrary self-join, choose a different aggregate,
    or compare unrelated records.
    """

    policies = semantic_layer.get("two_value_comparison_policies") or []
    if not isinstance(policies, list):
        raise TwoValueComparisonPolicyError("two_value_comparison_policies_invalid")
    bindings = {
        str(binding.get("semantic_entity") or ""): binding
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping) and str(binding.get("semantic_entity") or "")
    }

    def resolve_ref(
        policy_id: str,
        raw: Any,
        *,
        expected_entity: str | None = None,
    ) -> tuple[str, str, Mapping[str, Any]]:
        if not isinstance(raw, Mapping):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_field_invalid:{policy_id}"
            )
        entity = str(raw.get("semantic_entity") or "").strip()
        field_name = str(raw.get("semantic_field") or "").strip()
        if not entity or not field_name or (expected_entity and entity != expected_entity):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_field_invalid:{policy_id}"
            )
        binding = bindings.get(entity)
        if binding is None or binding.get("execution_eligible") is not True:
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_binding_invalid:{policy_id}:{entity}"
            )
        field = next(
            (
                item
                for item in binding.get("fields") or ()
                if isinstance(item, Mapping)
                and str(item.get("semantic_field") or "") == field_name
            ),
            None,
        )
        if not isinstance(field, Mapping):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_field_unbound:{policy_id}:{entity}.{field_name}"
            )
        return entity, field_name, field

    def numeric(field: Mapping[str, Any]) -> bool:
        data_type = str(
            (field.get("technical_metadata") or {}).get("data_type")
            or field.get("data_type")
            or ""
        ).casefold()
        return str(field.get("business_role") or "").casefold() in {"measure", "metric"} or any(
            token in data_type
            for token in ("int", "numeric", "decimal", "double", "real", "float")
        )

    seen: set[str] = set()
    for policy in policies:
        if not isinstance(policy, Mapping):
            raise TwoValueComparisonPolicyError("two_value_comparison_policy_invalid")
        policy_id = str(policy.get("policy_id") or "").strip()
        if not policy_id or policy_id in seen:
            raise TwoValueComparisonPolicyError("two_value_comparison_policy_id_invalid")
        seen.add(policy_id)
        if (
            policy.get("review_status") != "reviewed"
            or policy.get("operation") != "same_entity_two_value_subtract"
            or str(policy.get("aggregate") or "").casefold() != "max"
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_contract_invalid:{policy_id}"
            )
        entity = str(policy.get("semantic_entity") or "").strip()
        binding = bindings.get(entity)
        if (
            binding is None
            or binding.get("execution_eligible") is not True
            or str(binding.get("physical_table") or "")
            != str(policy.get("physical_table") or "")
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_binding_invalid:{policy_id}"
            )
        scope_entity, scope_name, scope_field = resolve_ref(
            policy_id, policy.get("scope_field_ref"), expected_entity=entity
        )
        _measure_entity, _measure_name, measure_field = resolve_ref(
            policy_id, policy.get("measure_field_ref"), expected_entity=entity
        )
        _pairing_entity, _pairing_name, pairing_field = resolve_ref(
            policy_id, policy.get("pairing_field_ref"), expected_entity=entity
        )
        if (
            str(scope_field.get("business_role") or "").casefold()
            not in {"dimension", "temporal_dimension"}
            or not numeric(measure_field)
            or str(pairing_field.get("business_role") or "").casefold()
            not in {"identifier", "join_key", "district_key"}
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_roles_invalid:{policy_id}"
            )
        allowed_values = policy.get("allowed_scope_values")
        if (
            not isinstance(allowed_values, list)
            or len(allowed_values) < 2
            or any(not isinstance(value, str) or not value.strip() for value in allowed_values)
            or len({value.casefold() for value in allowed_values}) != len(allowed_values)
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_scope_values_invalid:{policy_id}"
            )
        required_join = policy.get("required_join") or {}
        if not isinstance(required_join, Mapping):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_join_invalid:{policy_id}"
            )
        left_entity, left_name, _left_field = resolve_ref(
            policy_id, required_join.get("left_field_ref")
        )
        right_entity, right_name, _right_field = resolve_ref(
            policy_id, required_join.get("right_field_ref")
        )
        if (
            left_entity != entity
            or left_name != str(policy.get("pairing_field_ref", {}).get("semantic_field") or "")
            or right_entity == entity
            or str(required_join.get("kind") or "") != "equality"
            or str(required_join.get("operator") or "") != "eq"
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_join_invalid:{policy_id}"
            )
        dimensions = policy.get("required_dimension_field_refs")
        if not isinstance(dimensions, list) or not dimensions:
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_dimensions_invalid:{policy_id}"
            )
        dimension_keys: set[tuple[str, str]] = set()
        for value in dimensions:
            dimension_entity, dimension_name, dimension_field = resolve_ref(policy_id, value)
            key = (dimension_entity, dimension_name)
            if (
                key in dimension_keys
                or dimension_entity != right_entity
                or str(dimension_field.get("business_role") or "").casefold()
                not in {"dimension", "label", "identifier", "join_key", "district_key"}
            ):
                raise TwoValueComparisonPolicyError(
                    f"two_value_comparison_policy_dimensions_invalid:{policy_id}"
                )
            dimension_keys.add(key)
        map_binding = policy.get("map_binding")
        if map_binding is not None:
            if not isinstance(map_binding, Mapping):
                raise TwoValueComparisonPolicyError(
                    f"two_value_comparison_policy_map_invalid:{policy_id}"
                )
            map_entity = str(map_binding.get("semantic_entity") or "").strip()
            geometry_entity, _geometry_name, geometry_field = resolve_ref(
                policy_id, map_binding.get("geometry_field_ref"), expected_entity=map_entity
            )
            key_refs = map_binding.get("key_field_refs")
            if (
                map_entity != right_entity
                or geometry_entity != right_entity
                or str(geometry_field.get("business_role") or "").casefold() != "geometry"
                or not isinstance(key_refs, list)
                or {
                    (str(item.get("semantic_entity") or ""), str(item.get("semantic_field") or ""))
                    for item in key_refs
                    if isinstance(item, Mapping)
                }
                != dimension_keys
            ):
                raise TwoValueComparisonPolicyError(
                    f"two_value_comparison_policy_map_invalid:{policy_id}"
                )
        evidence = policy.get("source_evidence") or {}
        if not isinstance(evidence, Mapping) or not str(evidence.get("statement_sha256") or ""):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_evidence_invalid:{policy_id}"
            )
        if any(
            evidence.get(flag) is not False
            for flag in (
                "benchmark_questions_used",
                "gold_sql_used",
                "gold_results_used",
                "model_outputs_used",
                "source_rows_persisted",
            )
        ):
            raise TwoValueComparisonPolicyError(
                f"two_value_comparison_policy_boundary_invalid:{policy_id}"
            )


def _resolve_two_value_comparison_policy(
    *,
    comparison: SemanticTwoValueComparison,
    semantic_layer: Mapping[str, Any],
    semantic_ir: AdHocSemanticQueryIR,
) -> tuple[Mapping[str, Any], str, str]:
    """Resolve one policy and canonicalize its two audited source values."""

    try:
        validate_two_value_comparison_policies(semantic_layer)
    except TwoValueComparisonPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc
    matches = [
        policy
        for policy in semantic_layer.get("two_value_comparison_policies") or ()
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("policy_id") or "") == comparison.policy_id
    ]
    if len(matches) != 1:
        raise SemanticIRCompilationError(
            "semantic_two_value_comparison_policy_not_found_or_ambiguous"
        )
    policy = matches[0]
    if (
        str(policy.get("semantic_entity") or "") != semantic_ir.semantic_entity
        or comparison.scope_field_ref.model_dump(mode="python")
        != dict(policy.get("scope_field_ref") or {})
        or comparison.measure_field_ref.model_dump(mode="python")
        != dict(policy.get("measure_field_ref") or {})
    ):
        raise SemanticIRCompilationError("semantic_two_value_comparison_policy_field_mismatch")
    allowed_values = {
        str(value).casefold(): str(value)
        for value in policy.get("allowed_scope_values") or ()
    }
    baseline = allowed_values.get(comparison.baseline_value.casefold())
    target = allowed_values.get(comparison.comparison_value.casefold())
    if baseline is None or target is None:
        raise SemanticIRCompilationError("semantic_two_value_comparison_scope_value_unsupported")
    if baseline.casefold() == target.casefold():
        raise SemanticIRCompilationError("semantic_two_value_comparison_scope_values_equal")
    scope_filters = [
        filter_spec
        for filter_spec in (
            *semantic_ir.filters,
            *(item for group in semantic_ir.any_filter_groups for item in group.filters),
        )
        if filter_spec.field_ref == comparison.scope_field_ref
    ]
    # A compiler may narrow the source to exactly the two requested values
    # through the ordinary reviewed-domain normalizer. That is equivalent to
    # conditional aggregation over the same pair. Any partial, alternate, or
    # OR-scoped predicate could silently remove one side of the comparison and
    # is therefore rejected.
    expected_scope_values = {baseline.casefold(), target.casefold()}
    if any(
        filter_spec.operator not in {"eq", "in"}
        or {
            str(value).casefold()
            for value in filter_spec.values
            if isinstance(value, str)
        }
        != expected_scope_values
        for filter_spec in scope_filters
    ):
        raise SemanticIRCompilationError("semantic_two_value_comparison_scope_filter_conflict")
    required_join = policy.get("required_join") or {}
    left = SemanticModelFieldRef.model_validate(required_join.get("left_field_ref"))
    right = SemanticModelFieldRef.model_validate(required_join.get("right_field_ref"))
    expected_join = frozenset(
        ((left.semantic_entity, left.semantic_field), (right.semantic_entity, right.semantic_field))
    )
    if not any(
        join.kind is JoinKind.EQUALITY
        and join.operator == "eq"
        and frozenset(
            (
                (join.left_field_ref.semantic_entity, join.left_field_ref.semantic_field),
                (join.right_field_ref.semantic_entity, join.right_field_ref.semantic_field),
            )
        )
        == expected_join
        for join in semantic_ir.joins
    ):
        raise SemanticIRCompilationError("semantic_two_value_comparison_required_join_missing")
    required_dimensions = {
        (
            str(item.get("semantic_entity") or ""),
            str(item.get("semantic_field") or ""),
        )
        for item in policy.get("required_dimension_field_refs") or ()
    }
    projected_dimensions = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in semantic_ir.projections
        if item.role is ProjectionRole.DIMENSION and item.field_ref is not None
    }
    if not required_dimensions <= projected_dimensions:
        raise SemanticIRCompilationError(
            "semantic_two_value_comparison_required_dimensions_missing"
        )
    return policy, baseline, target


def _resolve_categorical_pivot_policy(
    *,
    pivot: SemanticCategoricalPivot,
    semantic_layer: Mapping[str, Any],
    semantic_ir: AdHocSemanticQueryIR,
) -> tuple[Mapping[str, Any], tuple[tuple[str, str], ...]]:
    """Resolve a reviewed comparison policy for an audited multi-value pivot."""

    try:
        validate_two_value_comparison_policies(semantic_layer)
    except TwoValueComparisonPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc
    matches = [
        policy
        for policy in semantic_layer.get("two_value_comparison_policies") or ()
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("policy_id") or "") == pivot.policy_id
    ]
    if len(matches) != 1:
        raise SemanticIRCompilationError(
            "semantic_categorical_pivot_policy_not_found_or_ambiguous"
        )
    policy = matches[0]
    if (
        str(policy.get("semantic_entity") or "") != semantic_ir.semantic_entity
        or pivot.scope_field_ref.model_dump(mode="python")
        != dict(policy.get("scope_field_ref") or {})
        or pivot.measure_field_ref.model_dump(mode="python")
        != dict(policy.get("measure_field_ref") or {})
    ):
        raise SemanticIRCompilationError("semantic_categorical_pivot_policy_field_mismatch")
    allowed_values = {
        str(value).casefold(): str(value)
        for value in policy.get("allowed_scope_values") or ()
    }
    resolved: list[tuple[str, str]] = []
    for item in pivot.values:
        canonical = allowed_values.get(item.value.casefold())
        if canonical is None:
            raise SemanticIRCompilationError(
                "semantic_categorical_pivot_scope_value_unsupported"
            )
        resolved.append((canonical, item.output_name))
    scope_filters = [
        filter_spec
        for filter_spec in (
            *semantic_ir.filters,
            *(item for group in semantic_ir.any_filter_groups for item in group.filters),
        )
        if filter_spec.field_ref == pivot.scope_field_ref
    ]
    expected_scope_values = {value.casefold() for value, _output in resolved}
    if any(
        filter_spec.operator not in {"eq", "in"}
        or {
            str(value).casefold()
            for value in filter_spec.values
            if isinstance(value, str)
        }
        != expected_scope_values
        for filter_spec in scope_filters
    ):
        raise SemanticIRCompilationError("semantic_categorical_pivot_scope_filter_conflict")
    required_join = policy.get("required_join") or {}
    left = SemanticModelFieldRef.model_validate(required_join.get("left_field_ref"))
    right = SemanticModelFieldRef.model_validate(required_join.get("right_field_ref"))
    expected_join = frozenset(
        ((left.semantic_entity, left.semantic_field), (right.semantic_entity, right.semantic_field))
    )
    if not any(
        join.kind is JoinKind.EQUALITY
        and join.operator == "eq"
        and frozenset(
            (
                (join.left_field_ref.semantic_entity, join.left_field_ref.semantic_field),
                (join.right_field_ref.semantic_entity, join.right_field_ref.semantic_field),
            )
        )
        == expected_join
        for join in semantic_ir.joins
    ):
        raise SemanticIRCompilationError("semantic_categorical_pivot_required_join_missing")
    required_dimensions = {
        (
            str(item.get("semantic_entity") or ""),
            str(item.get("semantic_field") or ""),
        )
        for item in policy.get("required_dimension_field_refs") or ()
    }
    projected_dimensions = {
        (item.field_ref.semantic_entity, item.field_ref.semantic_field)
        for item in semantic_ir.projections
        if item.role is ProjectionRole.DIMENSION and item.field_ref is not None
    }
    if not required_dimensions <= projected_dimensions:
        raise SemanticIRCompilationError(
            "semantic_categorical_pivot_required_dimensions_missing"
        )
    return policy, tuple(resolved)


def validate_aggregate_identity_projection_policies(
    semantic_layer: Mapping[str, Any],
) -> None:
    """Validate reviewed rules that preserve a fixed aggregate identity.

    A model can correctly filter a single named entity yet omit it from an
    aggregate projection.  These rules allow the compiler to preserve that
    already-filtered identity only when the semantic publisher has explicitly
    reviewed the label, its binding, and the allowed single-value predicate.
    """

    policies = semantic_layer.get("aggregate_identity_projection_policies") or []
    if not isinstance(policies, list):
        raise AggregateIdentityProjectionPolicyError(
            "aggregate_identity_projection_policies_invalid"
        )
    bindings = {
        str(binding.get("semantic_entity") or ""): binding
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping) and str(binding.get("semantic_entity") or "")
    }
    seen: set[str] = set()
    for policy in policies:
        if not isinstance(policy, Mapping):
            raise AggregateIdentityProjectionPolicyError(
                "aggregate_identity_projection_policy_invalid"
            )
        policy_id = str(policy.get("policy_id") or "").strip()
        if not policy_id or policy_id in seen:
            raise AggregateIdentityProjectionPolicyError(
                "aggregate_identity_projection_policy_id_invalid"
            )
        seen.add(policy_id)
        if (
            policy.get("review_status") != "reviewed"
            or policy.get("operation") != "project_fixed_filtered_identity"
            or policy.get("requires_aggregate_metric") is not True
        ):
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_contract_invalid:{policy_id}"
            )
        entity = str(policy.get("semantic_entity") or "").strip()
        field_name = str(policy.get("primary_label_field") or "").strip()
        binding = bindings.get(entity)
        if (
            binding is None
            or binding.get("execution_eligible") is not True
            or str(binding.get("physical_table") or "")
            != str(policy.get("physical_table") or "")
            or not field_name
        ):
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_binding_invalid:{policy_id}"
            )
        field = next(
            (
                item
                for item in binding.get("fields") or ()
                if isinstance(item, Mapping)
                and str(item.get("semantic_field") or "") == field_name
            ),
            None,
        )
        if (
            not isinstance(field, Mapping)
            or str(field.get("display_role") or "").casefold() != "primary_label"
        ):
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_label_invalid:{policy_id}"
            )
        operators = policy.get("allowed_filter_operators")
        if not isinstance(operators, list) or set(operators) != {"eq", "in"}:
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_operators_invalid:{policy_id}"
            )
        if policy.get("max_filter_values") != 1:
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_cardinality_invalid:{policy_id}"
            )
        output_name = str(policy.get("output_name") or "").strip()
        if output_name and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", output_name) is None:
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_output_invalid:{policy_id}"
            )
        evidence = policy.get("source_evidence") or {}
        if not isinstance(evidence, Mapping) or not str(
            evidence.get("statement_sha256") or ""
        ):
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_evidence_invalid:{policy_id}"
            )
        if any(
            evidence.get(flag) is not False
            for flag in (
                "benchmark_questions_used",
                "gold_sql_used",
                "gold_results_used",
                "model_outputs_used",
                "source_rows_persisted",
            )
        ):
            raise AggregateIdentityProjectionPolicyError(
                f"aggregate_identity_projection_policy_boundary_invalid:{policy_id}"
            )


def _apply_reviewed_aggregate_identity_projection_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...], tuple[str, ...]]:
    """Keep one reviewed named identity in an aggregate result.

    The policy is deliberately narrow. It fires only for an aggregate query
    with exactly one reviewed primary-label predicate holding one value, and
    never derives a filter, an entity, or a source value. If a name has more
    than one physical identity, the normal display companion and stable group
    identity rules keep those records distinct rather than silently merging
    them.
    """

    if (
        semantic_ir.status != "query"
        or semantic_ir.band_summary is not None
        or not any(item.role is ProjectionRole.METRIC for item in semantic_ir.projections)
    ):
        return semantic_ir, (), ()
    try:
        validate_aggregate_identity_projection_policies(semantic_layer)
    except AggregateIdentityProjectionPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc

    projected_refs = {
        item.field_ref
        for item in semantic_ir.projections
        if item.field_ref is not None
    }
    projected_names = {
        item.output_name.casefold() for item in semantic_ir.projections
    }
    candidates: list[tuple[Mapping[str, Any], SemanticFilter]] = []
    for policy in semantic_layer.get("aggregate_identity_projection_policies") or ():
        if not isinstance(policy, Mapping):
            continue
        label_ref = SemanticModelFieldRef(
            semantic_entity=str(policy["semantic_entity"]),
            semantic_field=str(policy["primary_label_field"]),
        )
        if label_ref in projected_refs:
            continue
        matches = [
            filter_spec
            for filter_spec in semantic_ir.filters
            if filter_spec.field_ref == label_ref
            and filter_spec.operator in set(policy["allowed_filter_operators"])
            and len(filter_spec.values) == int(policy["max_filter_values"])
        ]
        if len(matches) == 1:
            candidates.append((policy, matches[0]))
    # More than one configured identity would alter the result grain in an
    # ambiguous way. Require exactly one explicit, reviewed anchor.
    if len(candidates) != 1:
        return semantic_ir, (), ()
    policy, _filter_spec = candidates[0]
    output_name = str(
        policy.get("output_name") or policy.get("primary_label_field") or ""
    ).strip()
    if not output_name or output_name.casefold() in projected_names:
        return semantic_ir, (), ()
    projection = SemanticIRProjection(
        output_name=output_name,
        role=ProjectionRole.DIMENSION,
        field_ref=SemanticModelFieldRef(
            semantic_entity=str(policy["semantic_entity"]),
            semantic_field=str(policy["primary_label_field"]),
        ),
    )
    effective = semantic_ir.model_copy(
        update={"projections": (projection, *semantic_ir.projections)}
    )
    policy_id = str(policy["policy_id"])
    return (
        effective,
        (output_name,),
        (policy_id,),
    )


def validate_detail_identity_projection_policies(
    semantic_layer: Mapping[str, Any],
) -> None:
    """Validate reviewed identity fields retained for exact detail filters.

    The policy is intentionally independent of the question text. A publisher
    explicitly selects the reviewed presentation fields, and the compiler can
    use them only after a model has already supplied an exact single-label
    predicate for that same entity.
    """

    policies = semantic_layer.get("detail_identity_projection_policies") or []
    if not isinstance(policies, list):
        raise DetailIdentityProjectionPolicyError(
            "detail_identity_projection_policies_invalid"
        )
    bindings = {
        str(binding.get("semantic_entity") or ""): binding
        for binding in semantic_layer.get("table_bindings") or ()
        if isinstance(binding, Mapping) and str(binding.get("semantic_entity") or "")
    }
    seen: set[str] = set()
    for policy in policies:
        if not isinstance(policy, Mapping):
            raise DetailIdentityProjectionPolicyError(
                "detail_identity_projection_policy_invalid"
            )
        policy_id = str(policy.get("policy_id") or "").strip()
        if not policy_id or policy_id in seen:
            raise DetailIdentityProjectionPolicyError(
                "detail_identity_projection_policy_id_invalid"
            )
        seen.add(policy_id)
        if (
            policy.get("review_status") != "reviewed"
            or policy.get("operation")
            != "project_exact_filtered_detail_identity"
            or policy.get("requires_non_aggregate_detail") is not True
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_contract_invalid:{policy_id}"
            )
        entity = str(policy.get("semantic_entity") or "").strip()
        primary_label_field = str(policy.get("primary_label_field") or "").strip()
        binding = bindings.get(entity)
        if (
            binding is None
            or binding.get("execution_eligible") is not True
            or str(binding.get("physical_table") or "")
            != str(policy.get("physical_table") or "")
            or not primary_label_field
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_binding_invalid:{policy_id}"
            )
        fields = {
            str(item.get("semantic_field") or ""): item
            for item in binding.get("fields") or ()
            if isinstance(item, Mapping) and str(item.get("semantic_field") or "")
        }
        label = fields.get(primary_label_field)
        if (
            not isinstance(label, Mapping)
            or str(label.get("display_role") or "").casefold() != "primary_label"
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_label_invalid:{policy_id}"
            )
        operators = policy.get("allowed_filter_operators")
        if not isinstance(operators, list) or set(operators) != {"eq", "in"}:
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_operators_invalid:{policy_id}"
            )
        if policy.get("max_filter_values") != 1:
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_cardinality_invalid:{policy_id}"
            )
        if str(policy.get("projection_order") or "required_fields_first") != (
            "required_fields_first"
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_order_invalid:{policy_id}"
            )
        required_fields = policy.get("required_fields")
        if not isinstance(required_fields, list) or len(required_fields) < 2:
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_fields_invalid:{policy_id}"
            )
        seen_fields: set[str] = set()
        seen_names: set[str] = set()
        for required in required_fields:
            if not isinstance(required, Mapping):
                raise DetailIdentityProjectionPolicyError(
                    f"detail_identity_projection_policy_field_invalid:{policy_id}"
                )
            field_name = str(required.get("semantic_field") or "").strip()
            output_name = str(required.get("output_name") or "").strip()
            role = str(required.get("role") or "").casefold()
            if (
                field_name not in fields
                or not output_name
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", output_name) is None
                or role not in {ProjectionRole.ATTRIBUTE.value, ProjectionRole.DIMENSION.value}
                or field_name.casefold() in seen_fields
                or output_name.casefold() in seen_names
            ):
                raise DetailIdentityProjectionPolicyError(
                    f"detail_identity_projection_policy_field_invalid:{policy_id}:{field_name}"
                )
            seen_fields.add(field_name.casefold())
            seen_names.add(output_name.casefold())
        if primary_label_field.casefold() not in seen_fields:
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_primary_field_missing:{policy_id}"
            )
        evidence = policy.get("source_evidence") or {}
        if not isinstance(evidence, Mapping) or not str(
            evidence.get("statement_sha256") or ""
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_evidence_invalid:{policy_id}"
            )
        if any(
            evidence.get(flag) is not False
            for flag in (
                "benchmark_questions_used",
                "gold_sql_used",
                "gold_results_used",
                "model_outputs_used",
                "source_rows_persisted",
            )
        ):
            raise DetailIdentityProjectionPolicyError(
                f"detail_identity_projection_policy_boundary_invalid:{policy_id}"
            )


def _apply_reviewed_detail_identity_projection_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...], tuple[str, ...]]:
    """Retain reviewed identity fields for a detail query fixed to one entity.

    A primary-label predicate may be sufficient for SQL execution but leaves a
    result unidentifiable when the model omits its projection. This repair is
    limited to direct, non-aggregate detail results. It neither creates a
    predicate nor guesses a label value or relationship.
    """

    if (
        semantic_ir.status != "query"
        or semantic_ir.band_summary is not None
        or any(item.aggregate is not None for item in semantic_ir.projections)
    ):
        return semantic_ir, (), ()
    try:
        validate_detail_identity_projection_policies(semantic_layer)
    except DetailIdentityProjectionPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc

    projected = list(semantic_ir.projections)
    projected_refs = {
        item.field_ref for item in projected if item.field_ref is not None
    }
    projected_names = {item.output_name.casefold() for item in projected}
    additions: list[SemanticIRProjection] = []
    applied: list[str] = []
    for policy in semantic_layer.get("detail_identity_projection_policies") or ():
        if not isinstance(policy, Mapping):
            continue
        entity = str(policy.get("semantic_entity") or "")
        primary_label_field = str(policy.get("primary_label_field") or "")
        label_ref = SemanticModelFieldRef(
            semantic_entity=entity,
            semantic_field=primary_label_field,
        )
        exact_filters = [
            filter_spec
            for filter_spec in semantic_ir.filters
            if filter_spec.field_ref == label_ref
            and filter_spec.operator in set(policy.get("allowed_filter_operators") or ())
            and len(filter_spec.values) == int(policy.get("max_filter_values") or 0)
        ]
        if len(exact_filters) != 1:
            continue
        policy_additions: list[SemanticIRProjection] = []
        required_projections: list[SemanticIRProjection] = []
        identity_refs: set[SemanticModelFieldRef] = set()
        for required in policy.get("required_fields") or ():
            if not isinstance(required, Mapping):
                continue
            field_name = str(required.get("semantic_field") or "")
            field_ref = SemanticModelFieldRef(
                semantic_entity=entity,
                semantic_field=field_name,
            )
            identity_refs.add(field_ref)
            existing_projection = next(
                (
                    item
                    for item in projected
                    if item.field_ref == field_ref
                ),
                None,
            )
            if existing_projection is not None:
                required_projections.append(existing_projection)
                continue
            if field_ref in projected_refs:
                continue
            output_name = str(required.get("output_name") or field_name)
            if output_name.casefold() in projected_names:
                raise SemanticIRCompilationError(
                    "detail_identity_projection_output_alias_conflict:"
                    + str(policy.get("policy_id") or "")
                    + ":"
                    + output_name
                )
            projection = SemanticIRProjection(
                output_name=output_name,
                role=ProjectionRole(str(required.get("role") or "dimension")),
                field_ref=field_ref,
            )
            policy_additions.append(projection)
            required_projections.append(projection)
            projected_refs.add(field_ref)
            projected_names.add(output_name.casefold())
        reordered = [
            *required_projections,
            *(item for item in projected if item.field_ref not in identity_refs),
        ]
        if policy_additions or reordered != projected:
            projected = reordered
            additions.extend(policy_additions)
            applied.append(str(policy.get("policy_id") or ""))
    if not additions:
        return semantic_ir, (), ()
    return (
        semantic_ir.model_copy(update={"projections": tuple(projected)}),
        tuple(item.output_name for item in additions),
        tuple(applied),
    )


def _apply_derived_projection_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
    *,
    question: str | None,
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...], tuple[str, ...]]:
    """Apply reviewed arithmetic semantics to an already selected field."""

    if not question or not semantic_ir.projections or semantic_ir.band_summary is not None:
        return semantic_ir, (), ()
    try:
        validate_derived_projection_policies(semantic_layer)
    except DerivedProjectionPolicyError as exc:
        raise SemanticIRCompilationError(str(exc)) from exc
    matching = [
        policy
        for policy in semantic_layer.get("derived_projection_policies") or ()
        if isinstance(policy, Mapping)
        and policy_matches_question(
            policy,
            question=question,
            language=semantic_ir.language,
        )
    ]
    if not matching:
        return semantic_ir, (), ()

    projections: list[dict[str, Any]] = []
    applied: list[str] = []
    for projection in semantic_ir.projections:
        matches = [
            policy
            for policy in matching
            if projection.field_ref is not None
            and projection.field_ref.model_dump(mode="python")
            == dict(policy.get("target_field_ref") or {})
        ]
        if len(matches) > 1:
            raise SemanticIRCompilationError("derived_projection_policy_ambiguous")
        if not matches:
            projections.append(projection.model_dump(mode="python"))
            continue
        policy = matches[0]
        item = projection.model_dump(mode="python")
        item["field_ref"] = None
        item["derived_expression"] = {
            "operator": policy["operator"],
            "operands": [dict(value) for value in policy["operand_field_refs"]],
        }
        projections.append(item)
        applied.append(str(policy.get("policy_id") or ""))
    if not applied:
        return semantic_ir, (), ()
    effective = AdHocSemanticQueryIR.model_validate(
        {**semantic_ir.model_dump(mode="python"), "projections": projections}
    )
    unique = tuple(dict.fromkeys(applied))
    return (
        effective,
        unique,
        tuple(f"semantic_ir_applied_derived_projection_policy:{value}" for value in unique),
    )


def _resolve_universal_quantification_policy(
    *,
    condition: SemanticUniversalCondition,
    semantic_layer: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Resolve one reviewed, source-bound universal-quantification policy."""

    matches = [
        policy
        for policy in semantic_layer.get("universal_quantification_policies") or []
        if isinstance(policy, Mapping)
        and policy.get("review_status") == "reviewed"
        and str(policy.get("policy_id") or "") == condition.policy_id
    ]
    if len(matches) != 1:
        raise SemanticIRCompilationError(
            "semantic_universal_policy_not_found_or_ambiguous"
        )
    policy = matches[0]
    required_keys = (
        "semantic_entity",
        "physical_table",
        "group_field",
        "scope_field",
        "condition_field",
    )
    if any(not str(policy.get(key) or "").strip() for key in required_keys):
        raise SemanticIRCompilationError("semantic_universal_policy_invalid")
    if str(policy.get("semantic_entity")) != condition.field_ref.semantic_entity:
        raise SemanticIRCompilationError("semantic_universal_policy_entity_mismatch")
    if str(policy.get("condition_field")) != condition.field_ref.semantic_field:
        raise SemanticIRCompilationError("semantic_universal_policy_field_mismatch")
    validity = policy.get("validity") or []
    if not isinstance(validity, list) or not validity:
        raise SemanticIRCompilationError("semantic_universal_policy_validity_missing")
    allowed_operators = {"eq", "neq", "gt", "gte", "lt", "lte"}
    for item in validity:
        if (
            not isinstance(item, Mapping)
            or str(item.get("operator") or "") not in allowed_operators
            or "value" not in item
            or isinstance(item.get("value"), (dict, list, tuple))
        ):
            raise SemanticIRCompilationError("semantic_universal_policy_validity_invalid")
    return policy


def _apply_reviewed_grouped_measure_filter_policies(
    semantic_ir: AdHocSemanticQueryIR,
    semantic_layer: Mapping[str, Any],
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...]]:
    """Promote approved grouped-measure predicates from WHERE to HAVING.

    A model can correctly identify both a grouping dimension and its qualifying
    measure while emitting the qualifier as a row filter.  Moving such a
    predicate changes query meaning, so this is allowed only where the
    published *field-level* policy explicitly says that the measure qualifies
    a grouped result and supplies its sole approved aggregate.  No wording,
    source value, or physical identifier is inferred here.
    """

    if semantic_ir.status != "query":
        return semantic_ir, ()
    has_group_dimension = any(
        projection.role is ProjectionRole.DIMENSION
        for projection in semantic_ir.projections
    )
    has_aggregate_metric = any(
        projection.role is ProjectionRole.METRIC and projection.aggregate is not None
        for projection in semantic_ir.projections
    )
    if not has_group_dimension or not has_aggregate_metric:
        return semantic_ir, ()

    policies: dict[tuple[str, str], Mapping[str, Any]] = {}
    for binding in semantic_layer.get("table_bindings") or ():
        if not isinstance(binding, Mapping):
            continue
        entity = str(binding.get("semantic_entity") or "").strip()
        if not entity:
            continue
        for field in binding.get("fields") or ():
            if not isinstance(field, Mapping):
                continue
            policy = field.get("grouped_measure_filter_policy")
            if not isinstance(policy, Mapping):
                continue
            field_name = str(field.get("semantic_field") or "").strip()
            if field_name:
                policies[(entity, field_name)] = policy
    if not policies:
        return semantic_ir, ()

    regular_filters: list[SemanticFilter] = []
    having_filters = list(semantic_ir.having_filters)
    corrections: list[str] = []
    for filter_spec in semantic_ir.filters:
        key = (filter_spec.field_ref.semantic_entity, filter_spec.field_ref.semantic_field)
        policy = policies.get(key)
        if policy is None or filter_spec.operator not in {
            str(value).casefold() for value in policy.get("allowed_operators") or ()
        }:
            regular_filters.append(filter_spec)
            continue

        aggregate = SemanticAggregate(str(policy.get("aggregate") or ""))
        matching_having = [
            item
            for item in having_filters
            if item.field_ref == filter_spec.field_ref
        ]
        promoted = SemanticHavingFilter(
            field_ref=filter_spec.field_ref,
            aggregate=aggregate,
            operator=filter_spec.operator,
            values=filter_spec.values,
        )
        if matching_having:
            if promoted not in matching_having:
                raise SemanticIRCompilationError(
                    "semantic_ir_grouped_measure_filter_conflict"
                )
            corrections.append(
                "semantic_ir_deduplicated_grouped_measure_filter:"
                + key[0]
                + "."
                + key[1]
            )
            continue
        having_filters.append(promoted)
        corrections.append(
            "semantic_ir_promoted_grouped_measure_filter:"
            + key[0]
            + "."
            + key[1]
        )

    if not corrections:
        return semantic_ir, ()
    return (
        semantic_ir.model_copy(
            update={
                "filters": tuple(regular_filters),
                "having_filters": tuple(having_filters),
            }
        ),
        tuple(corrections),
    )


def build_compiled_ad_hoc_semantic_plan(
    *,
    semantic_ir: AdHocSemanticQueryIR,
    source: Mapping[str, Any],
    semantic_version: str,
    semantic_layer: Mapping[str, Any],
    max_rows: int,
    expected_spatial_intent: SpatialIntent = SpatialIntent.NONE,
    question: str | None = None,
    categorical_scope_value_resolutions: tuple[
        CategoricalScopeValueResolutionEvidence, ...
    ] = (),
) -> CompiledAdHocSemanticPlanEvidence:
    """Validate and compile a model-authored logical query to PostgreSQL SQL.

    Only approved semantic bindings enter this function.  All physical
    identifiers are selected from the semantic layer and all user-derived
    values become named parameters, so the model cannot compose SQL text or
    select a source table directly.
    """

    model_authored_entity_keys = _semantic_entity_reference_keys(semantic_ir)
    model_authored_field_keys = _semantic_field_reference_keys(semantic_ir)
    semantic_ir, enum_filter_corrections = _apply_explicit_domain_filters(
        semantic_ir,
        semantic_layer,
        question,
    )
    semantic_ir, grouped_measure_filter_corrections = (
        _apply_reviewed_grouped_measure_filter_policies(
            semantic_ir,
            semantic_layer,
        )
    )
    semantic_ir, partitioned_ranking_corrections = (
        _repair_partitioned_ranking_from_question(semantic_ir, question)
    )
    semantic_ir, numeric_band_corrections = (
        _repair_numeric_band_summary_from_question(
            semantic_ir,
            question,
            semantic_layer,
        )
    )
    (
        semantic_ir,
        derived_projection_policy_applications,
        derived_projection_corrections,
    ) = _apply_derived_projection_policies(
        semantic_ir,
        semantic_layer,
        question=question,
    )
    (
        semantic_ir,
        filtered_label_added_output_names,
        redundant_measure_removed_output_names,
        redundant_measure_corrections,
    ) = _repair_redundant_measure_dimension_with_filtered_label(
        semantic_ir,
        semantic_layer,
    )
    semantic_ir, context_dimension_removed_output_names = (
        _apply_reviewed_context_dimension_policies(
            semantic_ir,
            semantic_layer,
            question=question,
        )
    )
    (
        semantic_ir,
        aggregate_identity_added_output_names,
        aggregate_identity_policy_applications,
    ) = _apply_reviewed_aggregate_identity_projection_policies(
        semantic_ir,
        semantic_layer,
    )
    (
        semantic_ir,
        detail_identity_added_output_names,
        detail_identity_policy_applications,
    ) = _apply_reviewed_detail_identity_projection_policies(
        semantic_ir,
        semantic_layer,
    )
    # Apply only explicitly published, reviewed display-companion policies.
    # This keeps human-facing grouped/list results unambiguous (for example,
    # district name plus municipality) without teaching the model a table or
    # benchmark-specific answer.  The effective IR is revalidated below and
    # the added output names are persisted as plan evidence.
    semantic_ir, display_added_output_names = _apply_display_projection_policies(
        semantic_ir,
        semantic_layer,
    )
    semantic_ir, entity_list_removed_output_names = (
        _apply_reviewed_entity_list_projection_policies(
            semantic_ir,
            semantic_layer,
            question=question,
        )
    )
    # Normalize detail-safe aggregate/attribute role confusion before applying
    # complete-field policies. Otherwise one incidental model metric can hide
    # a reviewed exact projection contract, even though the same metric is
    # subsequently repaired back to a detail attribute.
    semantic_ir = _repair_reviewed_detail_projection_aggregates(
        semantic_ir,
        semantic_layer,
        question,
    )
    (
        semantic_ir,
        detail_filter_explanation_added_output_names,
    ) = _add_reviewed_detail_filter_explanation_projections(
        semantic_ir,
        semantic_layer,
        question=question,
    )
    # Complete-field policies run after the entity-list presentation gate.
    # This ordering is intentional: a question such as "list all domain
    # scores" is still an entity-list syntactically, but its reviewed
    # collection request must not be trimmed away as an unrequested
    # attribute.  Conversely, the entity-list gate can first remove purely
    # incidental primary-label attributes, after which the completeness
    # policy adds only the table-card-declared collection members.
    (
        semantic_ir,
        completeness_added_output_names,
        completeness_removed_output_names,
        completeness_policy_applications,
    ) = (
        _apply_projection_completeness_policies(
            semantic_ir,
            semantic_layer,
            question=question,
        )
    )
    projection_policy_applications = tuple(
        dict.fromkeys(
            (
                *derived_projection_policy_applications,
                *aggregate_identity_policy_applications,
                *detail_identity_policy_applications,
                *completeness_policy_applications,
            )
        )
    )
    # Row scopes are reviewed semantic governance, rather than a best-effort
    # instruction for the model. Apply them to the typed IR before resolving
    # fields so required joins and predicates receive the normal compiler
    # validation and parameterization.
    (
        semantic_ir,
        row_scope_filter_corrections,
        compiler_added_row_scope_filters,
    ) = _apply_reviewed_row_scope_policies(
        semantic_ir,
        semantic_layer,
        question,
    )
    semantic_ir = _repair_reviewed_measure_filters_from_question(
        semantic_ir,
        semantic_layer,
        question,
    )
    # Bind an explicit reviewed numeric alias (for example a 50% target) to
    # the sole measure that publishes that alias when a sibling measure was
    # selected by the provider.  This remains metadata-driven and is applied
    # before strict literal-preservation checks.
    semantic_ir = _repair_reviewed_numeric_alias_field_references(
        semantic_ir,
        semantic_layer,
        question,
    )
    semantic_ir = _drop_redundant_universal_having_filters(
        semantic_ir,
        semantic_layer,
    )
    semantic_ir = _repair_universal_group_projection(
        semantic_ir,
        semantic_layer,
    )
    compiler_hidden_output_names = _having_only_metric_output_names(
        semantic_ir,
        question,
    )
    compiler_added_output_names = (
        *completeness_added_output_names,
        *filtered_label_added_output_names,
        *aggregate_identity_added_output_names,
        *detail_identity_added_output_names,
        *display_added_output_names,
        *detail_filter_explanation_added_output_names,
    )
    _validate_explicit_question_numeric_literals(semantic_ir, question, semantic_layer)
    _validate_question_answer_shape(semantic_ir, question)

    if semantic_ir.status != "query":
        raise SemanticIRCompilationError("semantic_ir_not_query")
    if max_rows < 1:
        raise SemanticIRCompilationError("semantic_max_rows_invalid")
    if (semantic_layer.get("activation_gate") or {}).get(
        "active_for_free_form_nl2sql"
    ) is not True:
        raise SemanticIRCompilationError("semantic_ir_not_activated")

    entity = str(semantic_ir.semantic_entity or "")
    universal_condition = None
    universal_policy: Mapping[str, Any] | None = None
    if semantic_ir.universal_conditions:
        if len(semantic_ir.universal_conditions) != 1:
            raise SemanticIRCompilationError(
                "semantic_universal_multiple_conditions_unsupported"
            )
        universal_condition = semantic_ir.universal_conditions[0]
        universal_policy = _resolve_universal_quantification_policy(
            condition=universal_condition,
            semantic_layer=semantic_layer,
        )
        if entity != universal_condition.field_ref.semantic_entity:
            raise SemanticIRCompilationError("semantic_universal_primary_entity_mismatch")
    two_value_comparison = semantic_ir.two_value_comparison
    two_value_comparison_policy: Mapping[str, Any] | None = None
    two_value_baseline_value: str | None = None
    two_value_comparison_value: str | None = None
    if two_value_comparison is not None:
        (
            two_value_comparison_policy,
            two_value_baseline_value,
            two_value_comparison_value,
        ) = _resolve_two_value_comparison_policy(
            comparison=two_value_comparison,
            semantic_layer=semantic_layer,
            semantic_ir=semantic_ir,
        )
    categorical_pivot = semantic_ir.categorical_pivot
    categorical_pivot_policy: Mapping[str, Any] | None = None
    categorical_pivot_values: tuple[tuple[str, str], ...] = ()
    if categorical_pivot is not None:
        (
            categorical_pivot_policy,
            categorical_pivot_values,
        ) = _resolve_categorical_pivot_policy(
            pivot=categorical_pivot,
            semantic_layer=semantic_layer,
            semantic_ir=semantic_ir,
        )
    entity_bindings: dict[str, Mapping[str, Any]] = {}
    entity_tables: dict[str, str] = {}
    field_bindings: dict[tuple[str, str], Mapping[str, Any]] = {}

    def resolve_entity_binding(semantic_entity: str) -> Mapping[str, Any]:
        if semantic_entity not in entity_bindings:
            # A non-ontology source representation may enter the plan only
            # when a reviewed compiler policy injected it after model output
            # was captured.  A model-authored reference to the same identity
            # remains outside the executable business ontology and therefore
            # fails closed.
            allow_governance_support = (
                _semantic_alias_key(semantic_entity)
                not in model_authored_entity_keys
            )
            binding = _semantic_entity_binding(
                semantic_layer,
                semantic_entity,
                allow_compiler_governance_support=allow_governance_support,
            )
            physical_table = str(binding.get("physical_table") or "")
            _quote_table_identifier(physical_table)
            entity_bindings[semantic_entity] = binding
            entity_tables[semantic_entity] = physical_table
        return entity_bindings[semantic_entity]

    def resolve_field(field_ref: SemanticModelFieldRef) -> Mapping[str, Any]:
        key = (field_ref.semantic_entity, field_ref.semantic_field)
        if key not in field_bindings:
            binding = resolve_entity_binding(field_ref.semantic_entity)
            resolved_field = _semantic_field_binding(
                binding,
                field_ref,
                semantic_layer=semantic_layer,
            )
            authored_key = (
                _semantic_alias_key(field_ref.semantic_entity),
                _semantic_alias_key(field_ref.semantic_field),
            )
            if (
                resolved_field.get("compiler_governance_support") is True
                and authored_key in model_authored_field_keys
            ):
                raise SemanticIRCompilationError(
                    "semantic_field_not_active_or_ambiguous"
                )
            field_bindings[key] = {
                **dict(resolved_field),
                "physical_table": entity_tables[field_ref.semantic_entity],
            }
        return field_bindings[key]

    resolve_entity_binding(entity)
    universal_group_field: Mapping[str, Any] | None = None
    universal_scope_field: Mapping[str, Any] | None = None
    universal_condition_field: Mapping[str, Any] | None = None
    if universal_policy is not None and universal_condition is not None:
        universal_group_field = resolve_field(
            SemanticModelFieldRef(
                semantic_entity=str(universal_policy["semantic_entity"]),
                semantic_field=str(universal_policy["group_field"]),
            )
        )
        universal_scope_field = resolve_field(
            SemanticModelFieldRef(
                semantic_entity=str(universal_policy["semantic_entity"]),
                semantic_field=str(universal_policy["scope_field"]),
            )
        )
        universal_condition_field = resolve_field(universal_condition.field_ref)
        # The universal threshold is evaluated after grouping.  A regular
        # row-level predicate on the same field would change "every assessed
        # row" into "every row that already passed the threshold" and is
        # therefore ambiguous; fail closed and ask the model to regenerate.
        if any(
            item.field_ref == universal_condition.field_ref
            for item in (
                *semantic_ir.filters,
                *(item for group in semantic_ir.any_filter_groups for item in group.filters),
            )
        ):
            raise SemanticIRCompilationError(
                "semantic_universal_condition_filter_conflict"
            )
    resolved_projection_fields: list[Mapping[str, Any]] = []
    resolved_filter_fields: list[Mapping[str, Any]] = []
    resolved_having_fields: list[Mapping[str, Any]] = []
    resolved_join_fields: list[Mapping[str, Any]] = []
    if (
        universal_group_field is not None
        and universal_scope_field is not None
        and universal_condition_field is not None
    ):
        resolved_filter_fields.extend(
            [universal_group_field, universal_scope_field, universal_condition_field]
        )
    for projection in semantic_ir.projections:
        projection_field_ref = projection.field_ref
        if projection_field_ref is None and projection.json_array is not None:
            projection_field_ref = projection.json_array.field_ref
        if projection_field_ref is not None:
            field = resolve_field(projection_field_ref)
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
            elif (
                projection.role is ProjectionRole.METRIC
                and projection.json_array is None
                and projection.aggregate
                in {
                    SemanticAggregate.SUM,
                    SemanticAggregate.AVG,
                    SemanticAggregate.MIN,
                    SemanticAggregate.MAX,
                    SemanticAggregate.MEDIAN,
                }
                and str(field.get("json_access_contract_id") or "").strip()
            ):
                raise SemanticIRCompilationError(
                    "semantic_json_array_projection_required"
                )
            resolved_projection_fields.append(field)
        if projection.derived_expression is not None:
            for operand in projection.derived_expression.operands:
                field = resolve_field(operand)
                data_type = str(
                    (field.get("technical_metadata") or {}).get("data_type")
                    or field.get("data_type")
                    or ""
                ).casefold()
                business_role = str(field.get("business_role") or "").casefold()
                numeric = business_role in {"measure", "metric"} or any(
                    token in data_type
                    for token in (
                        "int", "numeric", "decimal", "double", "real", "float"
                    )
                )
                if not numeric:
                    raise SemanticIRCompilationError(
                        "semantic_derived_expression_operand_not_numeric"
                    )
                resolved_projection_fields.append(field)
    if semantic_ir.band_summary is not None:
        # The dedicated band capability has no ordinary projections, but its
        # governed score, display, and optional disambiguation fields still
        # participate in source admission, physical-plan lineage, and active
        # field validation.
        resolved_projection_fields.extend(
            [
                resolve_field(semantic_ir.band_summary.score_field_ref),
                resolve_field(semantic_ir.band_summary.member_field_ref),
                *(
                    resolve_field(reference)
                    for reference in semantic_ir.band_summary.member_disambiguation_field_refs
                ),
            ]
        )
    if two_value_comparison is not None:
        # These fields are compiler-owned conditional aggregate inputs. They
        # remain part of source admission and physical lineage even though the
        # model never represents them as ordinary metric projections.
        resolved_projection_fields.extend(
            [
                resolve_field(two_value_comparison.scope_field_ref),
                resolve_field(two_value_comparison.measure_field_ref),
            ]
        )
    if categorical_pivot is not None:
        resolved_projection_fields.extend(
            [
                resolve_field(categorical_pivot.scope_field_ref),
                resolve_field(categorical_pivot.measure_field_ref),
            ]
        )
    for filter_spec in semantic_ir.filters:
        resolved_filter_fields.append(resolve_field(filter_spec.field_ref))
    for filter_spec in semantic_ir.having_filters:
        resolved_having_fields.append(resolve_field(filter_spec.field_ref))
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
    categorical_spatial_scope_ids = _reviewed_categorical_spatial_scope_ids(
        semantic_ir=semantic_ir,
        semantic_layer=semantic_layer,
        expected_spatial_intent=expected_spatial_intent,
        question=question,
        resolve_field=resolve_field,
    )
    if expected_spatial_intent is not SpatialIntent.NONE:
        if not spatial_joins and not categorical_spatial_scope_ids:
            raise SemanticIRCompilationError(
                "semantic_ir_spatial_intent_requires_spatial_join"
            )
        if semantic_ir.spatial_intent is not expected_spatial_intent:
            raise SemanticIRCompilationError("semantic_ir_spatial_intent_mismatch")
    elif semantic_ir.spatial_intent is not SpatialIntent.NONE and not spatial_joins:
        # The public compiler can also be called outside the normal request
        # pipeline.  Do not let that bypass the question-derived intent gate
        # that normally supplies ``expected_spatial_intent``.
        raise SemanticIRCompilationError("semantic_ir_spatial_intent_requires_spatial_join")
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

    def derived_expression_sql(projection: SemanticIRProjection) -> str:
        expression = projection.derived_expression
        if expression is None:
            raise SemanticIRCompilationError("semantic_derived_expression_missing")
        operands = [field_sql(item) for item in expression.operands]
        operator = expression.operator
        if operator == "add":
            return "(" + " + ".join(operands) + ")"
        if operator == "subtract":
            return "(" + " - ".join(operands) + ")"
        if operator == "multiply":
            return "(" + " * ".join(operands) + ")"
        if operator == "divide":
            if len(operands) != 2:
                raise SemanticIRCompilationError(
                    "semantic_derived_expression_divide_requires_two_operands"
                )
            return f"({operands[0]} / NULLIF({operands[1]}, 0))"
        raise SemanticIRCompilationError("semantic_derived_expression_operator_unsupported")

    def aggregate_field_sql(filter_spec: SemanticHavingFilter) -> str:
        """Compile a governed aggregate expression for a HAVING predicate."""

        field = resolve_field(filter_spec.field_ref)
        expression = field_sql(filter_spec.field_ref)
        aggregate = filter_spec.aggregate
        if aggregate is SemanticAggregate.COUNT:
            if str(field.get("business_role") or "") == "join_key":
                raise SemanticIRCompilationError(
                    "semantic_ir_count_join_key_requires_row_count"
                )
            return f"COUNT({expression})"
        if aggregate is SemanticAggregate.COUNT_DISTINCT:
            return f"COUNT(DISTINCT {expression})"
        if aggregate is SemanticAggregate.MEDIAN:
            return "PERCENTILE_CONT(0.5) WITHIN GROUP " f"(ORDER BY {expression})"
        return f"{aggregate.value.upper()}({expression})"

    parameter_bindings: dict[str, str | int | float | bool] = {}
    json_array_contracts: dict[str, tuple[Mapping[str, Any], str]] = {}

    def relation_side(
        field_ref: SemanticModelFieldRef,
        relation: Mapping[str, Any],
    ) -> Literal["left", "right"]:
        field = resolve_field(field_ref)
        endpoint = (
            f"{field.get('physical_table')}.{field.get('physical_field')}"
        ).casefold()
        if endpoint == str(relation.get("left") or "").casefold():
            return "left"
        if endpoint == str(relation.get("right") or "").casefold():
            return "right"
        # _reviewed_relation_for_join already establishes exact endpoints.
        # Keep this compiler invariant explicit so CRS/geometry policies can
        # never be applied to an unrelated logical field.
        raise SemanticIRCompilationError("semantic_ir_relation_endpoint_unresolved")

    def join_condition(join_index: int, join: SemanticIRJoin) -> str:
        left_sql = field_sql(join.left_field_ref)
        right_sql = field_sql(join.right_field_ref)
        if join.kind is JoinKind.EQUALITY:
            return f"{left_sql} = {right_sql}"
        relation = reviewed_joins[join_index]
        left_sql = _reviewed_spatial_operand_sql(
            left_sql,
            relation,
            side=relation_side(join.left_field_ref, relation),
        )
        right_sql = _reviewed_spatial_operand_sql(
            right_sql,
            relation,
            side=relation_side(join.right_field_ref, relation),
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
        *(
            (
                ValidationCheck(
                    check_id="reviewed_two_value_comparison_policy",
                    passed=two_value_comparison_policy is not None,
                    detail=str(two_value_comparison_policy.get("policy_id") or ""),
                ),
            )
            if two_value_comparison is not None
            else ()
        ),
        *(
            (
                ValidationCheck(
                    check_id="reviewed_categorical_pivot_policy",
                    passed=categorical_pivot_policy is not None,
                    detail=str(categorical_pivot_policy.get("policy_id") or ""),
                ),
            )
            if categorical_pivot is not None
            else ()
        ),
        ValidationCheck(
            check_id="geometry_usage_safe",
            passed=True,
        ),
        *(
            (
                ValidationCheck(
                    check_id="reviewed_categorical_spatial_scope",
                    passed=True,
                    detail=",".join(categorical_spatial_scope_ids),
                ),
            )
            if categorical_spatial_scope_ids
            else ()
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
    has_metric = two_value_comparison is not None or categorical_pivot is not None
    dimension_sql: list[str] = []
    stable_group_identity_ordering: list[tuple[str, str]] = []
    # Detail Top-N queries can also contain many tied values (for example a
    # completion rate of 0 for every district).  A human-readable label is
    # not a reliable identity and PostgreSQL is free to return any tied rows
    # before LIMIT.  Keep a separate list for detail rows so grouped-query
    # ordering semantics remain unchanged below.
    stable_detail_identity_ordering: list[tuple[str, str]] = []
    detail_tiebreaker_applied = False
    for projection in semantic_ir.projections:
        quoted_alias = _quote_identifier(projection.output_name)
        if projection.role is not ProjectionRole.METRIC:
            expression = (
                derived_expression_sql(projection)
                if projection.derived_expression is not None
                else field_sql(projection.field_ref)
            )
            projection_sql.append(f"{expression} AS {quoted_alias}")
            if projection.role is ProjectionRole.DIMENSION:
                dimension_sql.append(expression)
                field = resolve_field(projection.field_ref)
                # A display label is not necessarily unique (for example two
                # districts can share the same name in different
                # municipalities).  Preserve the governed entity grain by
                # grouping on the owning binding's primary key as a hidden
                # SQL grouping expression.  Ordinary categorical dimensions
                # remain unchanged, so grouping by stage/status still merges
                # rows exactly as requested.
                if str(field.get("business_role") or "").casefold() == "label":
                    binding = resolve_entity_binding(
                        projection.field_ref.semantic_entity
                    )
                    available_fields = {
                        str(item.get("physical_field") or "")
                        for item in binding.get("fields") or []
                        if isinstance(item, Mapping)
                    }
                    projected_physical_field = str(
                        field.get("physical_field") or ""
                    )
                    for primary_key in binding.get("primary_key") or []:
                        primary_key = str(primary_key or "")
                        if (
                            not primary_key
                            or primary_key == projected_physical_field
                            or primary_key not in available_fields
                        ):
                            continue
                        identity_expression = (
                            f"{entity_aliases[projection.field_ref.semantic_entity]}."
                            f"{_quote_identifier(primary_key)}"
                        )
                        if identity_expression not in dimension_sql:
                            dimension_sql.append(identity_expression)
                        identity_name = (
                            f"{projection.field_ref.semantic_entity}.{primary_key}"
                        )
                        if (identity_name, identity_expression) not in stable_group_identity_ordering:
                            stable_group_identity_ordering.append(
                                (identity_name, identity_expression)
                            )
            elif projection.role is ProjectionRole.ATTRIBUTE and projection.field_ref is not None:
                # Detail projections do not carry a GROUP BY dimension, so
                # collect the reviewed primary key for deterministic bounded
                # ordering.  We intentionally use only keys of entities the
                # user asked to display; unrelated joined-table keys would
                # impose an arbitrary order on otherwise equivalent rows.
                binding = resolve_entity_binding(projection.field_ref.semantic_entity)
                available_fields = {
                    str(item.get("physical_field") or "")
                    for item in binding.get("fields") or []
                    if isinstance(item, Mapping)
                }
                projected_physical_field = str(
                    resolve_field(projection.field_ref).get("physical_field") or ""
                )
                for primary_key in binding.get("primary_key") or []:
                    primary_key = str(primary_key or "")
                    if (
                        not primary_key
                        or primary_key == projected_physical_field
                        or primary_key not in available_fields
                    ):
                        continue
                    identity_expression = (
                        f"{entity_aliases[projection.field_ref.semantic_entity]}."
                        f"{_quote_identifier(primary_key)}"
                    )
                    identity_name = (
                        f"{projection.field_ref.semantic_entity}.{primary_key}"
                    )
                    item = (identity_name, identity_expression)
                    if item not in stable_detail_identity_ordering:
                        stable_detail_identity_ordering.append(item)
            continue
        has_metric = True
        aggregate = projection.aggregate
        assert aggregate is not None
        if projection.output_name in compiler_hidden_output_names:
            # Keep this aggregate in the grouped query so its HAVING predicate
            # remains valid, but do not expose it as an unrequested result
            # column. The exact field/aggregate match was established above;
            # no value or physical identifier is invented here.
            continue
        if projection.json_array is not None:
            json_spec = projection.json_array
            json_field = resolve_field(json_spec.field_ref)
            contract = _resolve_json_array_contract(
                semantic_layer=semantic_layer,
                field=json_field,
                value_key=json_spec.value_key,
                aggregate=aggregate,
                semantic_ir=semantic_ir,
                resolve_field=resolve_field,
            )
            json_alias = f"gda_json_item_{len(json_array_contracts) + 1:03d}"
            json_array_contracts[projection.output_name] = (contract, json_spec.value_key)
            json_key_literal = json_spec.value_key.replace("'", "''")
            json_column_sql = field_sql(json_spec.field_ref)
            expression = (
                f"{aggregate.value.upper()}((\n"
                f"  SELECT COALESCE(SUM(({json_alias} ->> '{json_key_literal}')::double precision), 0)\n"
                f"  FROM jsonb_array_elements(\n"
                f"    CASE WHEN jsonb_typeof({json_column_sql}) = 'array'\n"
                f"         THEN {json_column_sql} ELSE '[]'::jsonb END\n"
                f"  ) AS {json_alias}\n"
                f"))"
            )
            projection_sql.append(f"{expression} AS {quoted_alias}")
            continue
        if aggregate is SemanticAggregate.COUNT and projection.field_ref is None:
            expression = "COUNT(*)"
        else:
            if projection.derived_expression is not None:
                expression = derived_expression_sql(projection)
                if aggregate is SemanticAggregate.COUNT:
                    expression = f"COUNT({expression})"
                elif aggregate is SemanticAggregate.COUNT_DISTINCT:
                    expression = f"COUNT(DISTINCT {expression})"
                elif aggregate is SemanticAggregate.MEDIAN:
                    expression = (
                        "PERCENTILE_CONT(0.5) WITHIN GROUP "
                        f"(ORDER BY {expression})"
                    )
                else:
                    expression = f"{aggregate.value.upper()}({expression})"
                projection_sql.append(f"{expression} AS {quoted_alias}")
                continue
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
            elif aggregate is SemanticAggregate.MEDIAN:
                # PostgreSQL's ordered-set aggregate is the portable,
                # deterministic median primitive.  Keep it compiler-owned so
                # the model can request only the semantic operation and never
                # inject percentile SQL or an arbitrary expression.
                expression = (
                    "PERCENTILE_CONT(0.5) WITHIN GROUP "
                    f"(ORDER BY {expression})"
                )
            else:
                expression = f"{aggregate.value.upper()}({expression})"
        projection_sql.append(f"{expression} AS {quoted_alias}")

    if two_value_comparison is not None:
        assert two_value_baseline_value is not None
        assert two_value_comparison_value is not None
        scope_sql = field_sql(two_value_comparison.scope_field_ref)
        measure_sql = field_sql(two_value_comparison.measure_field_ref)
        baseline_parameter = "gda_two_value_baseline_001"
        comparison_parameter = "gda_two_value_comparison_001"
        parameter_bindings[baseline_parameter] = two_value_baseline_value
        parameter_bindings[comparison_parameter] = two_value_comparison_value
        baseline_expression = (
            f"MAX({measure_sql}) FILTER (WHERE {scope_sql} = :{baseline_parameter})"
        )
        comparison_expression = (
            f"MAX({measure_sql}) FILTER (WHERE {scope_sql} = :{comparison_parameter})"
        )
        projection_sql.extend(
            (
                baseline_expression
                + " AS "
                + _quote_identifier(two_value_comparison.baseline_output_name),
                comparison_expression
                + " AS "
                + _quote_identifier(two_value_comparison.comparison_output_name),
                "("
                + comparison_expression
                + " - "
                + baseline_expression
                + ") AS "
                + _quote_identifier(two_value_comparison.difference_output_name),
            )
        )
    if categorical_pivot is not None:
        scope_sql = field_sql(categorical_pivot.scope_field_ref)
        measure_sql = field_sql(categorical_pivot.measure_field_ref)
        for pivot_index, (value, output_name) in enumerate(
            categorical_pivot_values,
            start=1,
        ):
            parameter_name = f"gda_categorical_pivot_{pivot_index:03d}"
            parameter_bindings[parameter_name] = value
            projection_sql.append(
                f"MAX({measure_sql}) FILTER (WHERE {scope_sql} = :{parameter_name}) "
                f"AS {_quote_identifier(output_name)}"
            )

    if semantic_ir.include_result_count:
        projection_sql.append(
            "COUNT(*) OVER () AS " + _quote_identifier(semantic_ir.result_count_alias)
        )

    # A capped grouped result without an ordering can return a different
    # subset between executions. The compiler supplies a stable presentation
    # order when the logical request leaves it unspecified; this never changes
    # an explicit user-requested ordering.
    compiler_default_ordering = bool(
        has_metric
        and dimension_sql
        and not semantic_ir.order_by
        and not semantic_ir.extreme_order_by
    )
    compiler_added_ordering_tiebreakers: tuple[str, ...] = ()
    if semantic_ir.order_by:
        explicit_order = [
            (item.output_name, item.direction, False) for item in semantic_ir.order_by
        ]
        # A grouped metric ordered only by the metric is not deterministic when
        # several groups share that value.  Append every projected dimension
        # not already present, in semantic projection order.  This is a
        # generic bounded-query rule, independent of benchmark IDs, table
        # names, or particular business metrics.
        if has_metric and dimension_sql:
            explicit_names = {
                name.casefold() for name, _direction, _is_expression in explicit_order
            }
            if stable_group_identity_ordering:
                additions = tuple(
                    name for name, _expression in stable_group_identity_ordering
                )
                explicit_order.extend(
                    (expression, "asc", True)
                    for _name, expression in stable_group_identity_ordering
                )
            else:
                additions = tuple(
                    projection.output_name
                    for projection in semantic_ir.projections
                    if projection.role is ProjectionRole.DIMENSION
                    and projection.output_name.casefold() not in explicit_names
                )
                explicit_order.extend((name, "asc", False) for name in additions)
            compiler_added_ordering_tiebreakers = additions
        elif not has_metric and stable_detail_identity_ordering:
            # For an ungrouped detail result, append the reviewed primary key
            # of projected entities.  The key is compiler-resolved from the
            # semantic binding; it is never authored as a physical identifier
            # by the model and does not change the requested primary ordering.
            explicit_names = {
                name.casefold() for name, _direction, _is_expression in explicit_order
            }
            additions = tuple(
                name
                for name, _expression in stable_detail_identity_ordering
                if name.casefold() not in explicit_names
            )
            explicit_order.extend(
                (expression, "asc", True)
                for name, expression in stable_detail_identity_ordering
                if name.casefold() not in explicit_names
            )
            compiler_added_ordering_tiebreakers = additions
            detail_tiebreaker_applied = bool(additions)
        effective_order_by = tuple(explicit_order)
    elif compiler_default_ordering:
        effective_order_by = tuple(
            (projection.output_name, "asc", False)
            for projection in semantic_ir.projections
            if projection.role is ProjectionRole.DIMENSION
        )
    else:
        effective_order_by = ()
    metric_order_output_names = {
        projection.output_name.casefold()
        for projection in semantic_ir.projections
        if projection.role is ProjectionRole.METRIC
    }
    if two_value_comparison is not None:
        metric_order_output_names.update(
            {
                two_value_comparison.baseline_output_name.casefold(),
                two_value_comparison.comparison_output_name.casefold(),
                two_value_comparison.difference_output_name.casefold(),
            }
        )
    if categorical_pivot is not None:
        metric_order_output_names.update(
            item.output_name.casefold() for item in categorical_pivot.values
        )
    metric_order_output_names.update(
        item.output_name.casefold() for item in semantic_ir.result_expressions
    )
    metric_order_output_names.update(
        item.output_name.casefold() for item in semantic_ir.partition_statistics
    )
    metric_order_output_names.update(
        item.output_name.casefold()
        for item in semantic_ir.post_statistic_expressions
    )
    metric_order_output_names.update(
        item.output_name.casefold() for item in semantic_ir.cumulative_windows
    )

    filters_sql: list[str] = []
    text_comparison_policy_ids: list[str] = []
    next_parameter_index = 1
    next_scope_parameter_index = 1
    compiler_row_scope_filter_keys = {
        (
            filter_spec.field_ref.semantic_entity,
            filter_spec.field_ref.semantic_field,
            filter_spec.operator,
            filter_spec.values,
        )
        for filter_spec in compiler_added_row_scope_filters
    }
    for filter_spec in semantic_ir.filters:
        filter_key = (
            filter_spec.field_ref.semantic_entity,
            filter_spec.field_ref.semantic_field,
            filter_spec.operator,
            filter_spec.values,
        )
        is_compiler_row_scope = filter_key in compiler_row_scope_filter_keys
        active_parameter_index = (
            next_scope_parameter_index if is_compiler_row_scope else next_parameter_index
        )
        clause, updated_parameter_index = _compile_filter(
            filter_spec,
            field=resolve_field(filter_spec.field_ref),
            alias=entity_aliases[filter_spec.field_ref.semantic_entity],
            parameter_bindings=parameter_bindings,
            next_parameter_index=active_parameter_index,
            parameter_name_prefix="gda_scope" if is_compiler_row_scope else "gda_p",
            text_comparison_policy_ids=text_comparison_policy_ids,
        )
        if is_compiler_row_scope:
            next_scope_parameter_index = updated_parameter_index
        else:
            next_parameter_index = updated_parameter_index
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
                text_comparison_policy_ids=text_comparison_policy_ids,
            )
            clauses.append(clause)
        any_filter_groups_sql.append("(" + " OR ".join(clauses) + ")")
    having_sql: list[str] = []
    for filter_spec in semantic_ir.having_filters:
        clause, next_parameter_index = _compile_filter(
            filter_spec,
            field=resolve_field(filter_spec.field_ref),
            alias=entity_aliases[filter_spec.field_ref.semantic_entity],
            parameter_bindings=parameter_bindings,
            next_parameter_index=next_parameter_index,
            expression_override=aggregate_field_sql(filter_spec),
            text_comparison_policy_ids=text_comparison_policy_ids,
        )
        having_sql.append(clause)

    where_clauses = [
        *filters_sql,
        *any_filter_groups_sql,
        *(join_conditions[index] for index in residual_join_indexes),
    ]
    universal_statement_built = False
    if semantic_ir.band_summary is not None:
        band_summary = semantic_ir.band_summary
        score_field = resolve_field(band_summary.score_field_ref)
        score_type = str(
            (score_field.get("technical_metadata") or {}).get("data_type")
            or score_field.get("data_type")
            or ""
        ).casefold()
        if not any(
            token in score_type
            for token in ("int", "numeric", "decimal", "double", "real", "float")
        ) and str(score_field.get("business_role") or "").casefold() not in {
            "measure",
            "metric",
        }:
            raise SemanticIRCompilationError("semantic_band_score_field_not_numeric")

        # Validate the partition independently of the order in which the
        # model listed the bands.  A complete, non-overlapping partition is
        # required so no score silently disappears or matches two bands.
        ordered_bands = sorted(
            enumerate(band_summary.bands),
            key=lambda item: (
                item[1].lower is not None,
                item[1].lower if item[1].lower is not None else float("-inf"),
            ),
        )
        if ordered_bands[0][1].lower is not None or ordered_bands[-1][1].upper is not None:
            raise SemanticIRCompilationError("semantic_band_partition_not_open_ended")
        for (_prev_index, previous), (_next_index, current) in zip(
            ordered_bands, ordered_bands[1:], strict=False
        ):
            if previous.upper is None or current.lower is None:
                raise SemanticIRCompilationError("semantic_band_partition_invalid")
            if previous.upper < current.lower:
                raise SemanticIRCompilationError("semantic_band_partition_gap")
            if previous.upper > current.lower:
                raise SemanticIRCompilationError("semantic_band_partition_overlap")
            if previous.upper_inclusive and current.lower_inclusive:
                raise SemanticIRCompilationError("semantic_band_partition_overlap")
            if not previous.upper_inclusive and not current.lower_inclusive:
                raise SemanticIRCompilationError("semantic_band_partition_gap")

        def add_band_parameter(value: str | int | float | bool, *, prefix: str) -> str:
            nonlocal next_parameter_index
            value = _validate_scalar_parameter(value)
            name = f"gda_band_{prefix}_{next_parameter_index:03d}"
            next_parameter_index += 1
            parameter_bindings[name] = value
            return f":{name}"

        score_sql = field_sql(band_summary.score_field_ref)
        member_sql = field_sql(band_summary.member_field_ref)
        member_disambiguation_sql = tuple(
            field_sql(reference)
            for reference in band_summary.member_disambiguation_field_refs
        )
        member_disambiguation_aliases = tuple(
            f"gda_band_member_context_{index:03d}"
            for index, _reference in enumerate(
                band_summary.member_disambiguation_field_refs,
                start=1,
            )
        )
        label_params: dict[str, str] = {}
        conditions: list[str] = []
        for index, band in enumerate(band_summary.bands, start=1):
            predicates: list[str] = []
            if band.lower is not None:
                lower_param = add_band_parameter(
                    band.lower,
                    prefix=f"lower_{index:03d}",
                )
                predicates.append(
                    f"gda_band_score {'>=' if band.lower_inclusive else '>'} {lower_param}"
                )
            if band.upper is not None:
                upper_param = add_band_parameter(
                    band.upper,
                    prefix=f"upper_{index:03d}",
                )
                predicates.append(
                    f"gda_band_score {'<=' if band.upper_inclusive else '<'} {upper_param}"
                )
            label_params[band.key.casefold()] = add_band_parameter(
                band.label or band.key,
                prefix=f"label_{index:03d}",
            )
            conditions.append(
                " WHEN " + " AND ".join(predicates) + " THEN " + label_params[band.key.casefold()]
            )
        band_case = "CASE" + "".join(conditions) + " ELSE NULL END"
        member_label_param = label_params[band_summary.member_band.casefold()]
        delimiter_param = add_band_parameter(
            band_summary.delimiter,
            prefix="delimiter",
        )
        band_base_select = [
            score_sql + " AS gda_band_score",
            member_sql + " AS gda_band_member",
            *(
                field + " AS " + alias
                for field, alias in zip(
                    member_disambiguation_sql,
                    member_disambiguation_aliases,
                    strict=True,
                )
            ),
        ]
        band_base_parts = [
            "SELECT " + ", ".join(band_base_select),
            # Tables are compiler-selected canonical ``schema.table`` values,
            # which lets the runtime table guard compare them to the governed
            # allow-list.
            "FROM " + entity_tables[entity] + " AS gda_source",
        ]
        for join_index, added_entity in tree_joins:
            band_base_parts.append(
                "JOIN "
                + entity_tables[added_entity]
                + " AS "
                + entity_aliases[added_entity]
                + " ON "
                + join_conditions[join_index]
            )
        if where_clauses:
            band_base_parts.append("WHERE " + " AND ".join(where_clauses))
        band_base_statement = "\n".join(band_base_parts)
        band_output = _quote_identifier(band_summary.band_output_name)
        count_output = _quote_identifier(band_summary.count_output_name)
        member_output = _quote_identifier(band_summary.member_output_name)
        classified_context_columns = "".join(
            ", " + alias for alias in member_disambiguation_aliases
        )
        classified_source = "gda_band_classified"
        member_aggregate_expression = "gda_band_member"
        disambiguation_cte = ""
        if member_disambiguation_aliases:
            context_delimiter_param = add_band_parameter(
                ", ",
                prefix="member_context_delimiter",
            )
            context_expression = (
                "CONCAT_WS("
                + context_delimiter_param
                + ", "
                + ", ".join(member_disambiguation_aliases)
                + ")"
            )
            disambiguation_cte = (
                ", gda_band_displayed AS (\nSELECT "
                + band_output
                + ", gda_band_member, CASE WHEN COUNT(*) OVER (PARTITION BY "
                + band_output
                + ", gda_band_member) > 1 AND NULLIF("
                + context_expression
                + ", '') IS NOT NULL THEN gda_band_member::text || ' (' || "
                + context_expression
                + " || ')' ELSE gda_band_member::text END AS gda_band_member_display\n"
                + "FROM gda_band_classified\n)\n"
            )
            classified_source = "gda_band_displayed"
            member_aggregate_expression = "gda_band_member_display"
        statement = (
            "WITH gda_band_base AS (\n"
            + band_base_statement
            + "\n), gda_band_classified AS (\nSELECT "
            + band_case
            + " AS "
            + band_output
            + ", gda_band_member"
            + classified_context_columns
            + "\nFROM gda_band_base\n)\n"
            + disambiguation_cte
            + "SELECT "
            + band_output
            + ", COUNT(*) AS "
            + count_output
            + ", CASE WHEN "
            + band_output
            + " = "
            + member_label_param
            + " THEN STRING_AGG("
            + member_aggregate_expression
            + "::text, "
            + delimiter_param
            + " ORDER BY gda_band_member::text) END AS "
            + member_output
            + "\nFROM "
            + classified_source
            + "\nWHERE "
            + band_output
            + " IS NOT NULL\nGROUP BY "
            + band_output
            + "\nORDER BY CASE "
            + " ".join(
                f"WHEN {band_output} = {label_params[band.key.casefold()]} THEN {index}"
                for index, band in enumerate(band_summary.bands, start=1)
            )
            + " ELSE 999 END\nLIMIT "
            + str(min(limit, max_rows, len(band_summary.bands)))
        )
        plan_result_limit = min(limit, max_rows, len(band_summary.bands))
        band_summary_output_names = (
            band_summary.band_output_name,
            band_summary.count_output_name,
            band_summary.member_output_name,
        )
    else:
        source_from_parts = [
            # Tables are compiler-selected canonical ``schema.table`` values,
            # which lets the runtime table guard compare them to the governed
            # allow-list.
            "FROM " + entity_tables[entity] + " AS gda_source",
        ]
        for join_index, added_entity in tree_joins:
            source_from_parts.append(
                "JOIN "
                + entity_tables[added_entity]
                + " AS "
                + entity_aliases[added_entity]
                + " ON "
                + join_conditions[join_index]
            )
        if universal_condition is not None and universal_policy is not None:
            if semantic_ir.distinct_rows or semantic_ir.having_filters:
                raise SemanticIRCompilationError(
                    "semantic_universal_query_grouping_control_conflict"
                )
            group_field_name = str(universal_policy["group_field"])
            group_projections = [
                projection
                for projection in semantic_ir.projections
                if projection.field_ref is not None
                and projection.field_ref.semantic_entity
                == str(universal_policy["semantic_entity"])
                and projection.field_ref.semantic_field == group_field_name
                and projection.role is not ProjectionRole.METRIC
            ]
            if len(group_projections) != 1:
                raise SemanticIRCompilationError(
                    "semantic_universal_group_field_not_projected_once"
                )
            if any(
                projection.role is ProjectionRole.METRIC
                or projection.derived_expression is not None
                or projection.json_array is not None
                for projection in semantic_ir.projections
            ):
                raise SemanticIRCompilationError(
                    "semantic_universal_projection_shape_unsupported"
                )

            # Validity/sentinel predicates are published by the policy and
            # therefore become compiler-owned parameters.  The model supplies
            # only the post-group threshold in ``universal_conditions``.
            universal_validity_clauses: list[str] = []
            condition_sql = field_sql(universal_condition.field_ref)
            sql_operators = {
                "eq": "=",
                "neq": "<>",
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
            }
            for index, validity in enumerate(universal_policy.get("validity") or [], start=1):
                operator = str(validity.get("operator") or "")
                value = _validate_scalar_parameter(validity.get("value"))
                parameter_name = f"gda_universal_valid_{index:03d}"
                parameter_bindings[parameter_name] = value
                universal_validity_clauses.append(
                    f"{condition_sql} {sql_operators[operator]} :{parameter_name}"
                )
            target_value = _validate_scalar_parameter(universal_condition.values[0])
            target_parameter_name = "gda_universal_target_001"
            parameter_bindings[target_parameter_name] = target_value

            group_projection = group_projections[0]
            group_sql = field_sql(group_projection.field_ref)
            scope_sql = field_sql(
                SemanticModelFieldRef(
                    semantic_entity=str(universal_policy["semantic_entity"]),
                    semantic_field=str(universal_policy["scope_field"]),
                )
            )
            base_parts = [
                "SELECT "
                + group_sql
                + " AS gda_universal_group, "
                + scope_sql
                + " AS gda_universal_scope, "
                + condition_sql
                + " AS gda_universal_value",
                *source_from_parts,
            ]
            universal_where = [*where_clauses, *universal_validity_clauses]
            if universal_where:
                base_parts.append("WHERE " + " AND ".join(universal_where))
            base_statement = "\n".join(base_parts)
            output_alias = _quote_identifier(group_projection.output_name)
            statement = (
                "WITH gda_universal_base AS (\n"
                + base_statement
                + "\n), gda_universal_grouped AS (\nSELECT "
                "gda_universal_group AS gda_universal_group, "
                "COUNT(DISTINCT gda_universal_scope) AS gda_universal_scope_count, "
                "MIN(gda_universal_value) AS gda_universal_min_value, "
                "COUNT(*) AS gda_universal_row_count\n"
                "FROM gda_universal_base\n"
                "GROUP BY gda_universal_group\n)\n"
                "SELECT gda_universal_group AS "
                + output_alias
                + "\nFROM gda_universal_grouped\n"
                "WHERE gda_universal_row_count > 0\n"
                "  AND gda_universal_scope_count > 0\n"
                "  AND gda_universal_min_value "
                + sql_operators[universal_condition.operator]
                + " :"
                + target_parameter_name
                + "\nORDER BY gda_universal_group ASC\nLIMIT "
                + str(min(limit, max_rows))
            )
            band_summary_output_names = ()
            # The universal branch is already a complete bounded statement;
            # skip the ordinary detail/partition/extreme statement builders.
            universal_statement_built = True
        else:
            statement_parts = [
                "SELECT " + ("DISTINCT " if semantic_ir.distinct_rows else "") + ", ".join(projection_sql),
                *source_from_parts,
            ]
            if where_clauses:
                statement_parts.append("WHERE " + " AND ".join(where_clauses))
            if has_metric and dimension_sql:
                statement_parts.append("GROUP BY " + ", ".join(dimension_sql))
            if having_sql:
                statement_parts.append("HAVING " + " AND ".join(having_sql))
            base_statement = "\n".join(statement_parts)
            band_summary_output_names = ()
    if (
        semantic_ir.band_summary is None
        and (
            semantic_ir.partition_by
            or semantic_ir.result_expressions
            or semantic_ir.group_average_filter is not None
            or semantic_ir.group_average_filters
            or semantic_ir.partition_statistics
            or semantic_ir.post_statistic_expressions
            or semantic_ir.result_filters
            or semantic_ir.cumulative_windows
            or semantic_ir.post_window_filters
        )
        and not universal_statement_built
    ):
        # Per-partition Top-N is compiled as a bounded window over the
        # already governed relational plan.  The model supplies only
        # projected aliases and a small integer; physical identifiers and
        # ROW_NUMBER syntax remain compiler-owned.
        partition_aliases = [
            _quote_identifier(value) for value in semantic_ir.partition_by
        ]
        partition_order_terms: list[str] = []
        for output_name, direction, is_expression in effective_order_by:
            if is_expression:
                # Hidden physical tie-breakers are not visible through the
                # CTE.  Projected ordering fields remain sufficient for the
                # bounded ranking and are already governed aliases.
                continue
            partition_order_terms.append(
                _quote_identifier(output_name)
                + " "
                + direction.upper()
                + (
                    " NULLS LAST"
                    if output_name.casefold() in metric_order_output_names
                    else ""
                )
            )
        partition_name_keys = {
            str(value).casefold() for value in semantic_ir.partition_by
        }
        ordered_name_keys = {
            output_name.casefold()
            for output_name, _direction, is_expression in effective_order_by
            if not is_expression
        }
        for projection in semantic_ir.projections:
            output_name = projection.output_name
            output_name_key = output_name.casefold()
            if (
                projection.role is not ProjectionRole.DIMENSION
                or output_name in compiler_hidden_output_names
                or output_name_key in partition_name_keys
                or output_name_key in ordered_name_keys
            ):
                continue
            partition_order_terms.append(
                _quote_identifier(output_name) + " ASC NULLS LAST"
            )
            ordered_name_keys.add(output_name_key)
        if semantic_ir.partition_by and not partition_order_terms:
            raise SemanticIRCompilationError("semantic_ir_partition_order_required")
        base_output_names = [
            item.output_name
            for item in semantic_ir.projections
            if item.output_name not in compiler_hidden_output_names
        ]
        if two_value_comparison is not None:
            base_output_names.extend(
                (
                    two_value_comparison.baseline_output_name,
                    two_value_comparison.comparison_output_name,
                    two_value_comparison.difference_output_name,
                )
            )
        if categorical_pivot is not None:
            base_output_names.extend(
                item.output_name for item in categorical_pivot.values
            )
        ctes = ["gda_partition_base AS (\n" + base_statement + "\n)"]
        ranked_source = "gda_partition_base"
        final_output_names = list(base_output_names)
        for expression_index, result_expression in enumerate(
            semantic_ir.result_expressions,
            start=1,
        ):
            operand_sql = [
                _quote_identifier(value) for value in result_expression.operands
            ]
            if result_expression.operator == "add":
                expression_sql = "(" + " + ".join(operand_sql) + ")"
            elif result_expression.operator == "subtract":
                expression_sql = f"({operand_sql[0]} - {operand_sql[1]})"
            elif result_expression.operator == "multiply":
                expression_sql = "(" + " * ".join(operand_sql) + ")"
            else:
                expression_sql = (
                    f"({operand_sql[0]}::double precision / "
                    f"NULLIF({operand_sql[1]}::double precision, 0.0))"
                )
            if result_expression.scale != 1.0:
                expression_sql = (
                    f"({expression_sql} * {format(result_expression.scale, '.15g')})"
                )
            current_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            expression_source = f"gda_result_expression_{expression_index:03d}"
            ctes.append(
                expression_source
                + " AS (\nSELECT "
                + current_projection
                + ", "
                + expression_sql
                + " AS "
                + _quote_identifier(result_expression.output_name)
                + "\nFROM "
                + ranked_source
                + "\n)"
            )
            ranked_source = expression_source
            final_output_names.append(result_expression.output_name)
        if semantic_ir.partition_statistics:
            current_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            statistic_projections: list[str] = []
            for statistic_index, statistic in enumerate(
                semantic_ir.partition_statistics,
                start=1,
            ):
                value_alias = _quote_identifier(statistic.value_output_name)
                partition_sql = ", ".join(
                    _quote_identifier(value) for value in statistic.partition_by
                )
                if statistic.aggregate == "percentile":
                    assert statistic.percentile is not None
                    percentile_parameter = (
                        f"gda_partition_percentile_{statistic_index:03d}"
                    )
                    parameter_bindings[percentile_parameter] = statistic.percentile
                    statistic_projection = (
                        "PERCENTILE_CONT(:"
                        + percentile_parameter
                        + ") WITHIN GROUP (ORDER BY gda_stat_source."
                        + value_alias
                        + ")"
                        + " FROM "
                        + ranked_source
                        + " AS gda_stat_source WHERE "
                        + " AND ".join(
                            "gda_stat_source."
                            + _quote_identifier(value)
                            + " IS NOT DISTINCT FROM gda_stat_outer."
                            + _quote_identifier(value)
                            for value in statistic.partition_by
                        )
                    )
                    statistic_projections.append(
                        "(SELECT "
                        + statistic_projection
                        + ") AS "
                        + _quote_identifier(statistic.output_name)
                    )
                    final_output_names.append(statistic.output_name)
                    continue
                aggregate_sql = (
                    "AVG(" + value_alias + ")"
                    if statistic.aggregate == "average"
                    else "SUM(" + value_alias + ")"
                )
                if statistic.value_filter_operator is not None:
                    parameter_name = f"gda_partition_stat_{statistic_index:03d}"
                    parameter_bindings[parameter_name] = statistic.value_filter_value
                    aggregate_sql += (
                        " FILTER (WHERE "
                        + value_alias
                        + " "
                        + {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[
                            statistic.value_filter_operator
                        ]
                        + " :"
                        + parameter_name
                        + ")"
                    )
                statistic_projections.append(
                    aggregate_sql
                    + " OVER (PARTITION BY "
                    + partition_sql
                    + ") AS "
                    + _quote_identifier(statistic.output_name)
                )
                final_output_names.append(statistic.output_name)
            ctes.append(
                "gda_partition_statistics AS (\nSELECT "
                + current_projection
                + ", "
                + ", ".join(statistic_projections)
                + "\nFROM "
                + ranked_source
                + " AS gda_stat_outer"
                + "\n)"
            )
            ranked_source = "gda_partition_statistics"
        for expression_index, result_expression in enumerate(
            semantic_ir.post_statistic_expressions,
            start=1,
        ):
            operand_sql = [
                _quote_identifier(value) for value in result_expression.operands
            ]
            if result_expression.operator == "add":
                expression_sql = "(" + " + ".join(operand_sql) + ")"
            elif result_expression.operator == "subtract":
                expression_sql = f"({operand_sql[0]} - {operand_sql[1]})"
            elif result_expression.operator == "multiply":
                expression_sql = "(" + " * ".join(operand_sql) + ")"
            else:
                expression_sql = (
                    f"({operand_sql[0]}::double precision / "
                    f"NULLIF({operand_sql[1]}::double precision, 0.0))"
                )
            if result_expression.scale != 1.0:
                expression_sql = (
                    f"({expression_sql} * {format(result_expression.scale, '.15g')})"
                )
            current_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            expression_source = f"gda_post_statistic_expression_{expression_index:03d}"
            ctes.append(
                expression_source
                + " AS (\nSELECT "
                + current_projection
                + ", "
                + expression_sql
                + " AS "
                + _quote_identifier(result_expression.output_name)
                + "\nFROM "
                + ranked_source
                + "\n)"
            )
            ranked_source = expression_source
            final_output_names.append(result_expression.output_name)
        effective_group_average_filters = (
            (semantic_ir.group_average_filter,)
            if semantic_ir.group_average_filter is not None
            else semantic_ir.group_average_filters
        )
        window_filter_clauses: list[str] = []
        if effective_group_average_filters:
            current_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            average_projections: list[str] = []
            for group_average in effective_group_average_filters:
                group_partition = ", ".join(
                    _quote_identifier(value) for value in group_average.partition_by
                )
                average_alias = _quote_identifier(group_average.average_output_name)
                value_alias = _quote_identifier(group_average.value_output_name)
                average_projections.append(
                    "AVG("
                    + value_alias
                    + ") OVER (PARTITION BY "
                    + group_partition
                    + ") AS "
                    + average_alias
                )
                final_output_names.append(group_average.average_output_name)
                window_filter_clauses.append(
                    value_alias
                    + " "
                    + {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[
                        group_average.operator
                    ]
                    + " "
                    + average_alias
                )
            ctes.append(
                "gda_group_average AS (\nSELECT "
                + current_projection
                + ", "
                + ", ".join(average_projections)
                + "\nFROM "
                + ranked_source
                + "\n)"
            )
            ranked_source = "gda_group_average"
        result_filter_clauses: list[str] = []
        for filter_index, result_filter in enumerate(
            semantic_ir.result_filters,
            start=1,
        ):
            right_sql: str
            if result_filter.right_output_name is not None:
                right_sql = _quote_identifier(result_filter.right_output_name)
            else:
                parameter_name = f"gda_result_filter_{filter_index:03d}"
                parameter_bindings[parameter_name] = result_filter.values[0]
                right_sql = ":" + parameter_name
            result_filter_clauses.append(
                _quote_identifier(result_filter.left_output_name)
                + " "
                + {
                    "eq": "=",
                    "neq": "<>",
                    "gt": ">",
                    "gte": ">=",
                    "lt": "<",
                    "lte": "<=",
                }[result_filter.operator]
                + " "
                + right_sql
            )
        candidate_filter_clauses = [
            *window_filter_clauses,
            *result_filter_clauses,
        ]
        if candidate_filter_clauses and (
            semantic_ir.partition_by or semantic_ir.cumulative_windows
        ):
            ctes.append(
                "gda_result_candidates AS (\nSELECT "
                + ", ".join(
                    _quote_identifier(value) for value in final_output_names
                )
                + "\nFROM "
                + ranked_source
                + "\nWHERE "
                + " AND ".join(candidate_filter_clauses)
                + "\n)"
            )
            ranked_source = "gda_result_candidates"
            candidate_filter_clauses = []
        if semantic_ir.partition_by or semantic_ir.cumulative_windows:
            current_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            window_projections: list[str] = []
            if semantic_ir.partition_by:
                window_projections.append(
                    "ROW_NUMBER() OVER (PARTITION BY "
                    + ", ".join(partition_aliases)
                    + " ORDER BY "
                    + ", ".join(partition_order_terms)
                    + ") AS gda_partition_rank"
                )
            for cumulative in semantic_ir.cumulative_windows:
                cumulative_partition = ", ".join(
                    _quote_identifier(value) for value in cumulative.partition_by
                )
                cumulative_order_terms = [
                    _quote_identifier(item.output_name)
                    + " "
                    + item.direction.upper()
                    + " NULLS LAST"
                    for item in cumulative.order_by
                ]
                cumulative_order_names = {
                    item.output_name.casefold() for item in cumulative.order_by
                }
                for projection in semantic_ir.projections:
                    if (
                        projection.role is ProjectionRole.DIMENSION
                        and projection.output_name.casefold()
                        not in cumulative_order_names
                        and projection.output_name.casefold()
                        not in {
                            str(value).casefold()
                            for value in cumulative.partition_by
                        }
                    ):
                        cumulative_order_terms.append(
                            _quote_identifier(projection.output_name)
                            + " ASC NULLS LAST"
                        )
                        cumulative_order_names.add(projection.output_name.casefold())
                window_projections.append(
                    "SUM("
                    + _quote_identifier(cumulative.value_output_name)
                    + ") OVER (PARTITION BY "
                    + cumulative_partition
                    + " ORDER BY "
                    + ", ".join(cumulative_order_terms)
                    + " ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "
                    + _quote_identifier(cumulative.output_name)
                )
                final_output_names.append(cumulative.output_name)
            ranked_statement = (
                "gda_partition_ranked AS (\nSELECT "
                + current_projection
                + ", "
                + ", ".join(window_projections)
                + "\nFROM "
                + ranked_source
            )
            if candidate_filter_clauses:
                ranked_statement += "\nWHERE " + " AND ".join(
                    candidate_filter_clauses
                )
            ranked_statement += "\n)"
            ctes.append(ranked_statement)
            ranked_source = "gda_partition_ranked"
            final_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            if semantic_ir.partition_rank_output_name is not None:
                final_projection += (
                    ", gda_partition_rank AS "
                    + _quote_identifier(semantic_ir.partition_rank_output_name)
                )
            final_filter_clauses: list[str] = []
            if semantic_ir.partition_limit is not None:
                final_filter_clauses.append(
                    "gda_partition_rank <= " + str(int(semantic_ir.partition_limit))
                )
            for filter_index, result_filter in enumerate(
                semantic_ir.post_window_filters,
                start=1,
            ):
                if result_filter.right_output_name is not None:
                    right_sql = _quote_identifier(result_filter.right_output_name)
                else:
                    parameter_name = f"gda_post_window_filter_{filter_index:03d}"
                    parameter_bindings[parameter_name] = result_filter.values[0]
                    right_sql = ":" + parameter_name
                final_filter_clauses.append(
                    _quote_identifier(result_filter.left_output_name)
                    + " "
                    + {
                        "eq": "=",
                        "neq": "<>",
                        "gt": ">",
                        "gte": ">=",
                        "lt": "<",
                        "lte": "<=",
                    }[result_filter.operator]
                    + " "
                    + right_sql
                )
            statement = (
                "WITH "
                + ",\n".join(ctes)
                + "\nSELECT "
                + final_projection
                + "\nFROM gda_partition_ranked"
            )
            if final_filter_clauses:
                statement += "\nWHERE " + " AND ".join(final_filter_clauses)
            if semantic_ir.partition_by:
                statement += "\nORDER BY " + ", ".join(
                    partition_aliases + ["gda_partition_rank ASC"]
                )
            elif effective_order_by:
                statement += "\nORDER BY " + ", ".join(
                    _quote_identifier(output_name) + " " + direction.upper()
                    for output_name, direction, is_expression in effective_order_by
                    if not is_expression
                )
            statement += "\nLIMIT " + str(min(limit, max_rows))
        else:
            ranked_projection = ", ".join(
                _quote_identifier(value) for value in final_output_names
            )
            statement = (
                "WITH "
                + ",\n".join(ctes)
                + "\nSELECT "
                + ranked_projection
                + "\nFROM "
                + ranked_source
            )
            if candidate_filter_clauses:
                statement += "\nWHERE " + " AND ".join(candidate_filter_clauses)
            if effective_order_by:
                statement += (
                    "\nORDER BY "
                    + ", ".join(
                        (output_name if is_expression else _quote_identifier(output_name))
                        + " "
                        + direction.upper()
                        for output_name, direction, is_expression in effective_order_by
                        if not is_expression
                    )
                )
            statement += "\nLIMIT " + str(min(limit, max_rows))
    elif semantic_ir.band_summary is None and semantic_ir.extreme_order_by and not universal_statement_built:
        if len(semantic_ir.extreme_order_by) > max_rows:
            raise SemanticIRCompilationError("semantic_ir_extreme_result_limit_exceeded")
        metric_aliases = {
            item.output_name.casefold()
            for item in semantic_ir.projections
            if item.role is ProjectionRole.METRIC
        }
        if any(
            item.output_name.casefold() not in metric_aliases
            for item in semantic_ir.extreme_order_by
        ):
            raise SemanticIRCompilationError("semantic_ir_extreme_order_requires_metric")
        dimension_aliases = [
            item.output_name
            for item in semantic_ir.projections
            if item.role is ProjectionRole.DIMENSION
        ]
        branches: list[str] = []
        cte_names: list[str] = []
        outer_projection = ", ".join(
            _quote_identifier(item.output_name)
            for item in semantic_ir.projections
        )
        for ordinal, item in enumerate(semantic_ir.extreme_order_by, start=1):
            order_terms = [
                f"{_quote_identifier(item.output_name)} {item.direction.upper()} NULLS LAST"
            ]
            order_terms.extend(
                f"{_quote_identifier(alias)} ASC"
                for alias in dimension_aliases
                if alias.casefold() != item.output_name.casefold()
            )
            cte_name = f"gda_extreme_{ordinal:03d}"
            cte_names.append(cte_name)
            # Keep each ordered extreme in a CTE.  Besides being valid
            # PostgreSQL syntax, this starts with ``WITH`` so the shared
            # read-only connector can apply its normal bounded-query wrapper
            # without treating the statement as an untrusted parenthesized
            # expression.
            branches.append(
                cte_name
                + " AS (\nSELECT "
                + outer_projection
                + " FROM (\n"
                + base_statement
                + f"\n) AS gda_extreme_base_{ordinal:03d}\nORDER BY "
                + ", ".join(order_terms)
                + "\nFETCH FIRST 1 ROW WITH TIES\n)"
            )
        union_branches = "\nUNION ALL\n".join(
            "SELECT " + outer_projection + " FROM " + name
            for name in cte_names
        )
        statement = "WITH " + ",\n".join(branches) + "\n" + union_branches
    elif semantic_ir.band_summary is None and not universal_statement_built:
        if effective_order_by:
            statement_parts.append(
                "ORDER BY "
                + ", ".join(
                    (output_name if is_expression else _quote_identifier(output_name))
                    + " "
                    + direction.upper()
                    + (
                        " NULLS LAST"
                        if not is_expression
                        and output_name.casefold() in metric_order_output_names
                        else ""
                    )
                    for output_name, direction, is_expression in effective_order_by
                )
            )
        statement_parts.append(f"LIMIT {limit}")
        statement = "\n".join(statement_parts)
    if semantic_ir.band_summary is None:
        plan_result_limit = (
            len(semantic_ir.extreme_order_by)
            if semantic_ir.extreme_order_by
            else limit
        )

    logical_nodes: list[LogicalPlanNode] = [
        LogicalPlanNode(
            node_id="scan_001",
            operator="scan",
            attributes={
                "semantic_entity": entity,
                "categorical_spatial_scope_ids": list(categorical_spatial_scope_ids),
            },
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
    if filters_sql or any_filter_groups_sql or residual_join_indexes:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="filter_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={"predicate_count": len(where_clauses)},
            )
        )
        current = "filter_001"
    if has_metric or universal_statement_built:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="aggregate_001",
                operator="aggregate",
                input_node_ids=(current,),
                attributes={
                    "group_count": 1
                    if semantic_ir.band_summary is not None or universal_statement_built
                    else len(dimension_sql),
                    "band_summary": (
                        {
                            "band_output_name": semantic_ir.band_summary.band_output_name,
                            "count_output_name": semantic_ir.band_summary.count_output_name,
                            "member_output_name": semantic_ir.band_summary.member_output_name,
                            "member_band": semantic_ir.band_summary.member_band,
                            "band_count": len(semantic_ir.band_summary.bands),
                        }
                        if semantic_ir.band_summary is not None
                        else None
                    ),
                    "universal_quantification": (
                        {
                            "policy_id": universal_condition.policy_id,
                            "condition_field": universal_condition.field_ref.semantic_field,
                            "operator": universal_condition.operator,
                        }
                        if universal_condition is not None
                        else None
                    ),
                    "two_value_comparison": (
                        {
                            "policy_id": str(
                                two_value_comparison_policy.get("policy_id") or ""
                            ),
                            "scope_field": two_value_comparison.scope_field_ref.semantic_field,
                            "measure_field": two_value_comparison.measure_field_ref.semantic_field,
                            "operation": "comparison_minus_baseline",
                            "aggregate": "max",
                            "output_names": [
                                two_value_comparison.baseline_output_name,
                                two_value_comparison.comparison_output_name,
                                two_value_comparison.difference_output_name,
                            ],
                        }
                        if two_value_comparison is not None
                        and two_value_comparison_policy is not None
                        else None
                    ),
                    "categorical_pivot": (
                        {
                            "policy_id": str(
                                categorical_pivot_policy.get("policy_id") or ""
                            ),
                            "scope_field": categorical_pivot.scope_field_ref.semantic_field,
                            "measure_field": categorical_pivot.measure_field_ref.semantic_field,
                            "aggregate": "max",
                            "values": [
                                {
                                    "value": value,
                                    "output_name": output_name,
                                }
                                for value, output_name in categorical_pivot_values
                            ],
                        }
                        if categorical_pivot is not None
                        and categorical_pivot_policy is not None
                        else None
                    ),
                    "json_array_metrics": [
                        {
                            "output_name": output_name,
                            "value_key": value_key,
                            "contract_id": str(contract.get("contract_id") or ""),
                        }
                        for output_name, (contract, value_key) in json_array_contracts.items()
                    ],
                },
            )
        )
        current = "aggregate_001"
    if having_sql:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="having_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={
                    "predicate_count": len(having_sql),
                    "predicate_stage": "post_aggregate",
                },
            )
        )
        current = "having_001"
    if semantic_ir.result_expressions:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="result_expression_001",
                operator="project",
                input_node_ids=(current,),
                attributes={
                    "operation": "bounded_result_arithmetic",
                    "expressions": [
                        {
                            "output_name": item.output_name,
                            "operator": item.operator,
                            "operands": list(item.operands),
                            "scale": item.scale,
                            "zero_division": "null" if item.operator == "divide" else None,
                        }
                        for item in semantic_ir.result_expressions
                    ],
                },
            )
        )
        current = "result_expression_001"
    effective_group_average_filters = (
        (semantic_ir.group_average_filter,)
        if semantic_ir.group_average_filter is not None
        else semantic_ir.group_average_filters
    )
    if effective_group_average_filters:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="window_average_001",
                operator="window",
                input_node_ids=(current,),
                attributes={
                    "operation": "partition_average_filter",
                    "filters": [
                        {
                            "value_output_name": item.value_output_name,
                            "average_output_name": item.average_output_name,
                            "partition_by": list(item.partition_by),
                            "operator": item.operator,
                        }
                        for item in effective_group_average_filters
                    ],
                },
            )
        )
        current = "window_average_001"
    if semantic_ir.partition_statistics:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="window_statistic_001",
                operator="window",
                input_node_ids=(current,),
                attributes={
                    "operation": "partition_statistics",
                    "statistics": [
                        {
                            "value_output_name": item.value_output_name,
                            "partition_by": list(item.partition_by),
                            "aggregate": item.aggregate,
                            "output_name": item.output_name,
                            "value_filter_operator": item.value_filter_operator,
                            "value_filter_value": item.value_filter_value,
                            "percentile": item.percentile,
                        }
                        for item in semantic_ir.partition_statistics
                    ],
                },
            )
        )
        current = "window_statistic_001"
    if semantic_ir.post_statistic_expressions:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="post_statistic_expression_001",
                operator="project",
                input_node_ids=(current,),
                attributes={
                    "operation": "bounded_result_arithmetic",
                    "expressions": [
                        {
                            "output_name": item.output_name,
                            "operator": item.operator,
                            "operands": list(item.operands),
                            "scale": item.scale,
                            "zero_division": "null" if item.operator == "divide" else None,
                        }
                        for item in semantic_ir.post_statistic_expressions
                    ],
                },
            )
        )
        current = "post_statistic_expression_001"
    if semantic_ir.result_filters:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="result_filter_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={
                    "operation": "validated_result_alias_filter",
                    "predicate_count": len(semantic_ir.result_filters),
                },
            )
        )
        current = "result_filter_001"
    if semantic_ir.partition_by or semantic_ir.cumulative_windows:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="window_001",
                operator="window",
                input_node_ids=(current,),
                attributes={
                    "partition_by": list(semantic_ir.partition_by),
                    "partition_limit": semantic_ir.partition_limit,
                    "order_by": [item.output_name for item in semantic_ir.order_by],
                    "rank_output_name": semantic_ir.partition_rank_output_name,
                    "cumulative_windows": [
                        {
                            "value_output_name": item.value_output_name,
                            "partition_by": list(item.partition_by),
                            "order_by": [
                                {
                                    "output_name": order.output_name,
                                    "direction": order.direction,
                                }
                                for order in item.order_by
                            ],
                            "output_name": item.output_name,
                            "frame": "rows_unbounded_preceding_to_current_row",
                        }
                        for item in semantic_ir.cumulative_windows
                    ],
                },
            )
        )
        current = "window_001"
    if semantic_ir.post_window_filters:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="post_window_filter_001",
                operator="filter",
                input_node_ids=(current,),
                attributes={
                    "operation": "validated_result_alias_filter",
                    "predicate_count": len(semantic_ir.post_window_filters),
                },
            )
        )
        current = "post_window_filter_001"
    elif semantic_ir.extreme_order_by:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="set_operation_001",
                operator="set_operation",
                input_node_ids=(current,),
                attributes={
                    "kind": "union_all_extremes",
                    "branch_count": len(semantic_ir.extreme_order_by),
                    "order_by": [
                        {
                            "output_name": item.output_name,
                            "direction": item.direction,
                        }
                        for item in semantic_ir.extreme_order_by
                    ],
                },
            )
        )
        current = "set_operation_001"
    logical_nodes.append(
        LogicalPlanNode(
            node_id="project_001",
            operator="project",
            input_node_ids=(current,),
            attributes={
                "outputs": (
                    list(band_summary_output_names)
                    if semantic_ir.band_summary is not None
                    else [
                        projection.output_name
                        for projection in semantic_ir.projections
                        if universal_statement_built
                        and universal_policy is not None
                        and projection.field_ref is not None
                        and projection.field_ref.semantic_entity
                        == str(universal_policy.get("semantic_entity") or "")
                        and projection.field_ref.semantic_field
                        == str(universal_policy.get("group_field") or "")
                    ]
                    if universal_statement_built
                    else [
                        item.output_name
                        for item in semantic_ir.projections
                        if item.output_name not in compiler_hidden_output_names
                    ]
                    + (
                        [
                            two_value_comparison.baseline_output_name,
                            two_value_comparison.comparison_output_name,
                            two_value_comparison.difference_output_name,
                        ]
                        if two_value_comparison is not None
                        else []
                    )
                    + (
                        [item.output_name for item in categorical_pivot.values]
                        if categorical_pivot is not None
                        else []
                    )
                    + (
                        [item.output_name for item in semantic_ir.result_expressions]
                    )
                    + (
                        [
                            item.average_output_name
                            for item in effective_group_average_filters
                        ]
                    )
                    + ([item.output_name for item in semantic_ir.partition_statistics])
                    + ([item.output_name for item in semantic_ir.post_statistic_expressions])
                    + ([item.output_name for item in semantic_ir.cumulative_windows])
                    + (
                        [semantic_ir.partition_rank_output_name]
                        if semantic_ir.partition_rank_output_name is not None
                        else []
                    )
                )
                + ([semantic_ir.result_count_alias] if semantic_ir.include_result_count else [])
            },
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
                        else "semantic_ir_with_dimension_tiebreakers"
                        if compiler_added_ordering_tiebreakers
                        and stable_group_identity_ordering
                        else "semantic_ir_with_detail_tiebreakers"
                        if detail_tiebreaker_applied
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
            attributes={"row_limit": plan_result_limit, "enforcement": "sql"},
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
                    *resolved_having_fields,
                    *resolved_join_fields,
                ]
            }
            | {
                f"{str(resolve_entity_binding(name.rsplit('.', 1)[0]).get('physical_table') or '')}."
                f"{str(name.rsplit('.', 1)[1])}"
                for name, _expression in (
                    *stable_group_identity_ordering,
                    *stable_detail_identity_ordering,
                )
                if "." in name
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
        compiler_added_ordering_tiebreakers=compiler_added_ordering_tiebreakers,
        compiler_added_output_names=compiler_added_output_names,
        compiler_removed_output_names=tuple(
            dict.fromkeys(
                (
                    *entity_list_removed_output_names,
                    *context_dimension_removed_output_names,
                    *completeness_removed_output_names,
                    *redundant_measure_removed_output_names,
                )
            )
        ),
        compiler_hidden_output_names=compiler_hidden_output_names,
        compiler_projection_policy_applications=projection_policy_applications,
        compiler_semantic_filter_corrections=tuple(
            dict.fromkeys(
                (
                    *enum_filter_corrections,
                    *grouped_measure_filter_corrections,
                    *partitioned_ranking_corrections,
                    *numeric_band_corrections,
                    *derived_projection_corrections,
                    *redundant_measure_corrections,
                    *row_scope_filter_corrections,
                )
            )
        ),
        compiler_text_comparison_policy_ids=tuple(
            dict.fromkeys(text_comparison_policy_ids)
        ),
        compiler_categorical_spatial_scope_ids=categorical_spatial_scope_ids,
        compiler_categorical_scope_value_resolutions=(
            categorical_scope_value_resolutions
        ),
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
    "AggregateIdentityProjectionPolicyError",
    "DetailIdentityProjectionPolicyError",
    "TwoValueComparisonPolicyError",
    "SemanticBandSpec",
    "SemanticBandSummary",
    "SemanticFilter",
    "SemanticUniversalCondition",
    "SemanticIRCompilationError",
    "SemanticIRValidationReport",
    "SemanticIROrder",
    "SemanticIRProjection",
    "SemanticDerivedExpression",
    "SemanticPartitionStatistic",
    "SemanticResultExpression",
    "SemanticResultFilter",
    "SemanticCumulativeWindow",
    "SemanticTwoValueComparison",
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
    "validate_aggregate_identity_projection_policies",
    "validate_detail_identity_projection_policies",
    "validate_two_value_comparison_policies",
]
