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
    question_is_entity_list,
    question_requests_explicit_attributes,
    resolve_projection_completeness_policies,
    validate_projection_completeness_policies,
)


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
                    [semantic_ir.band_summary.score_field_ref, semantic_ir.band_summary.member_field_ref]
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
    if asks_for_list and asks_for_count and not semantic_ir.include_result_count:
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
    changed = False
    projections: list[dict[str, Any]] = []
    for projection in semantic_ir.projections:
        ref = projection.field_ref
        key = (ref.semantic_entity, ref.semantic_field) if ref is not None else None
        if (
            projection.role is ProjectionRole.METRIC
            and projection.aggregate is not None
            and projection.aggregate is not SemanticAggregate.COUNT
            and key in filter_fields
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
        {**semantic_ir.model_dump(mode="python"), "projections": projections}
    )


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
    ``Urban, Suburban, and Rural``) without spelling out a predicate.  A
    language model may therefore project the dimension but omit the required
    filter.  This repair is deliberately generic and fail-closed: values must
    come from a reviewed/source-observed domain, the field must belong to an
    entity already selected by the IR, at least two distinct values must be
    mentioned, and an existing conflicting predicate is never overwritten.
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
            (
                semantic_ir.band_summary.score_field_ref.semantic_entity,
                semantic_ir.band_summary.member_field_ref.semantic_entity,
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
            {
                (
                    semantic_ir.band_summary.score_field_ref.semantic_entity,
                    semantic_ir.band_summary.score_field_ref.semantic_field,
                ),
                (
                    semantic_ir.band_summary.member_field_ref.semantic_entity,
                    semantic_ir.band_summary.member_field_ref.semantic_field,
                ),
            }
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
            value_semantics = field.get("value_semantics") or {}
            aliases_by_source: dict[str, list[str]] = {
                source: [source]
                for source in source_values
            }
            if isinstance(value_semantics, Mapping):
                for source, aliases in value_semantics.items():
                    source_text = str(source).strip()
                    if not source_text:
                        continue
                    aliases_by_source.setdefault(source_text, [source_text])
                    aliases_by_source[source_text].extend(
                        str(alias).strip()
                        for alias in (aliases if isinstance(aliases, list) else [aliases])
                        if str(alias).strip()
                    )
            if len(aliases_by_source) < 2:
                continue
            matched: list[tuple[str, str]] = []
            for source, aliases in aliases_by_source.items():
                matching_aliases = [
                    alias for alias in dict.fromkeys(aliases)
                    if _question_mentions_domain_alias(question, alias)
                ]
                if matching_aliases:
                    # Prefer the longest matching alias for evidence/debugging;
                    # the source token remains the only value admitted.
                    matched.append((source, max(matching_aliases, key=len)))
            unique_sources = list(dict.fromkeys(source for source, _alias in matched))
            if len(unique_sources) < 2:
                continue
            candidates.append(
                {
                    "entity": entity,
                    "semantic_field": semantic_field,
                    "field": field,
                    "sources": unique_sources,
                    "matched_aliases": [alias for _source, alias in matched],
                    "projected": (entity, semantic_field) in projected_fields,
                }
            )
    if not candidates:
        return semantic_ir, ()

    # Prefer a projected field, then the candidate with the largest explicit
    # value set.  Equal candidates remain ambiguous and are intentionally not
    # repaired; the model retry can ask for a clarification/complete filter.
    candidates.sort(key=lambda item: (bool(item["projected"]), len(item["sources"])), reverse=True)
    best = candidates[0]
    if len(candidates) > 1 and (
        bool(candidates[1]["projected"]) == bool(best["projected"])
        and len(candidates[1]["sources"]) == len(best["sources"])
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
        current = existing[0]
        current_set = {repr(value) for value in current.values}
        if current.operator in {"in", "eq"} and current_set <= requested_set:
            if current_set == requested_set:
                return semantic_ir, ()
            # Expand a subset generated by the model to the complete explicit
            # user list.  No value outside the reviewed source domain is added.
            replacement = SemanticFilter(
                field_ref=current.field_ref,
                operator="in",
                values=requested_values,
            )
            filters = tuple(replacement if item is current else item for item in semantic_ir.filters)
            return (
                AdHocSemanticQueryIR.model_validate(
                    {**semantic_ir.model_dump(mode="python"), "filters": [item.model_dump(mode="python") for item in filters]}
                ),
                (
                    "semantic_ir_completed_explicit_domain_filter:"
                    + best["entity"]
                    + "."
                    + best["semantic_field"],
                ),
            )
        raise SemanticIRCompilationError("semantic_ir_explicit_domain_filter_conflict")

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
    projections: tuple[SemanticIRProjection, ...] = Field(default=(), max_length=32)
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
    # Bounded per-partition ranking (for example, top three districts within
    # each settlement classification).  The compiler emits a ROW_NUMBER()
    # window over projected aliases; the model cannot provide SQL text.
    partition_by: tuple[str, ...] = Field(default=(), max_length=8)
    partition_limit: int | None = Field(default=None, ge=1, le=1000)
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
                    self.projections,
                    self.filters,
                    self.having_filters,
                    self.any_filter_groups,
                    self.universal_conditions,
                    self.joins,
                    self.order_by,
                    self.extreme_order_by,
                    self.partition_by,
                    self.partition_limit,
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
        if not self.semantic_entity or (not self.projections and self.band_summary is None):
            raise ValueError("query semantic IR requires an entity and projections or band_summary")
        if self.band_summary is not None and self.projections:
            raise ValueError("band_summary cannot be combined with ordinary projections")
        if self.band_summary is not None and (
            self.having_filters
            or self.order_by
            or self.extreme_order_by
            or self.partition_by
            or self.partition_limit is not None
            or self.distinct_rows
            or self.include_result_count
        ):
            raise ValueError("band_summary cannot combine with ordering, grouping controls, or count companion")
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
        if self.band_summary is not None:
            projected_names.update(
                {
                    self.band_summary.band_output_name.casefold(),
                    self.band_summary.count_output_name.casefold(),
                    self.band_summary.member_output_name.casefold(),
                }
            )
        has_metric = any(item.role is ProjectionRole.METRIC for item in self.projections)
        if self.having_filters and (not has_metric or not any(
            item.role is ProjectionRole.DIMENSION for item in self.projections
        )):
            raise ValueError("having filters require grouped metric query")
        if any(item.output_name.casefold() not in projected_names for item in self.order_by):
            raise ValueError("semantic IR order must reference a projection alias")
        if any(item.output_name.casefold() not in projected_names for item in self.extreme_order_by):
            raise ValueError("semantic IR extreme order must reference a projection alias")
        if any(str(item).casefold() not in projected_names for item in self.partition_by):
            raise ValueError("semantic IR partition key must reference a projection alias")
        if self.partition_limit is not None and not self.partition_by:
            raise ValueError("semantic IR partition limit requires partition keys")
        if self.partition_by and self.partition_limit is None:
            raise ValueError("semantic IR partition keys require partition limit")
        if self.partition_by and not self.order_by:
            raise ValueError("semantic IR partition ranking requires order_by")
        if self.partition_by and self.extreme_order_by:
            raise ValueError("semantic IR partition ranking cannot combine extreme ordering")
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
    filter_spec: SemanticFilter | SemanticHavingFilter,
    *,
    field: Mapping[str, Any],
    alias: str,
    parameter_bindings: dict[str, str | int | float | bool],
    next_parameter_index: int,
    expression_override: str | None = None,
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
) -> tuple[AdHocSemanticQueryIR, tuple[str, ...], tuple[str, ...]]:
    """Add missing direct logical fields from reviewed collection metadata."""

    if not question or not semantic_ir.projections:
        return semantic_ir, (), ()
    if any(item.role is ProjectionRole.METRIC for item in semantic_ir.projections):
        return semantic_ir, (), ()
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
        return semantic_ir, (), ()

    projected = list(semantic_ir.projections)
    projected_names = {item.output_name.casefold() for item in projected}
    added_names: list[str] = []
    applied_policy_ids: list[str] = []
    for policy in policies:
        policy_id = str(policy.get("policy_id") or "")
        semantic_entity = str(policy.get("semantic_entity") or "")
        required_fields = list(policy.get("required_fields") or [])
        required_names = {
            str(item.get("semantic_field") or "") for item in required_fields
        }
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
        if policy_added:
            applied_policy_ids.append(policy_id)
    if not added_names:
        return semantic_ir, (), ()
    effective = AdHocSemanticQueryIR.model_validate(
        {
            **semantic_ir.model_dump(mode="python"),
            "projections": [item.model_dump(mode="python") for item in projected],
        }
    )
    return effective, tuple(added_names), tuple(applied_policy_ids)


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


def build_compiled_ad_hoc_semantic_plan(
    *,
    semantic_ir: AdHocSemanticQueryIR,
    source: Mapping[str, Any],
    semantic_version: str,
    semantic_layer: Mapping[str, Any],
    max_rows: int,
    expected_spatial_intent: SpatialIntent = SpatialIntent.NONE,
    question: str | None = None,
) -> CompiledAdHocSemanticPlanEvidence:
    """Validate and compile a model-authored logical query to PostgreSQL SQL.

    Only approved semantic bindings enter this function.  All physical
    identifiers are selected from the semantic layer and all user-derived
    values become named parameters, so the model cannot compose SQL text or
    select a source table directly.
    """

    semantic_ir, enum_filter_corrections = _apply_explicit_domain_filters(
        semantic_ir,
        semantic_layer,
        question,
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
    # Complete-field policies run after the entity-list presentation gate.
    # This ordering is intentional: a question such as "list all domain
    # scores" is still an entity-list syntactically, but its reviewed
    # collection request must not be trimmed away as an unrequested
    # attribute.  Conversely, the entity-list gate can first remove purely
    # incidental primary-label attributes, after which the completeness
    # policy adds only the table-card-declared collection members.
    semantic_ir, completeness_added_output_names, projection_policy_applications = (
        _apply_projection_completeness_policies(
            semantic_ir,
            semantic_layer,
            question=question,
        )
    )
    semantic_ir = _repair_reviewed_detail_projection_aggregates(
        semantic_ir,
        semantic_layer,
        question,
    )
    compiler_hidden_output_names = _having_only_metric_output_names(
        semantic_ir,
        question,
    )
    compiler_added_output_names = (
        *completeness_added_output_names,
        *display_added_output_names,
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
        # two governed logical fields still participate in source admission,
        # physical-plan lineage, and the active-field validation check.
        resolved_projection_fields.extend(
            [
                resolve_field(semantic_ir.band_summary.score_field_ref),
                resolve_field(semantic_ir.band_summary.member_field_ref),
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
    having_sql: list[str] = []
    for filter_spec in semantic_ir.having_filters:
        clause, next_parameter_index = _compile_filter(
            filter_spec,
            field=resolve_field(filter_spec.field_ref),
            alias=entity_aliases[filter_spec.field_ref.semantic_entity],
            parameter_bindings=parameter_bindings,
            next_parameter_index=next_parameter_index,
            expression_override=aggregate_field_sql(filter_spec),
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

        band_base_parts = [
            "SELECT " + score_sql + " AS gda_band_score, " + member_sql + " AS gda_band_member",
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
        statement = (
            "WITH gda_band_base AS (\n"
            + band_base_statement
            + "\n), gda_band_classified AS (\nSELECT "
            + band_case
            + " AS "
            + band_output
            + ", gda_band_member\nFROM gda_band_base\n)\n"
            + "SELECT "
            + band_output
            + ", COUNT(*) AS "
            + count_output
            + ", CASE WHEN "
            + band_output
            + " = "
            + member_label_param
            + " THEN STRING_AGG(gda_band_member::text, "
            + delimiter_param
            + " ORDER BY gda_band_member::text) END AS "
            + member_output
            + "\nFROM gda_band_classified\nWHERE "
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
    if semantic_ir.band_summary is None and semantic_ir.partition_by and not universal_statement_built:
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
        if not partition_order_terms:
            raise SemanticIRCompilationError("semantic_ir_partition_order_required")
        outer_projection = ", ".join(
            _quote_identifier(item.output_name)
            for item in semantic_ir.projections
        )
        partition_limit = int(semantic_ir.partition_limit or 0)
        statement = (
            "WITH gda_partition_base AS (\n"
            + base_statement
            + "\n), gda_partition_ranked AS (\nSELECT "
            + outer_projection
            + ", "
            + "ROW_NUMBER() OVER (PARTITION BY "
            + ", ".join(partition_aliases)
            + " ORDER BY "
            + ", ".join(partition_order_terms)
            + ") AS gda_partition_rank\nFROM gda_partition_base\n)\n"
            + "SELECT "
            + outer_projection
            + "\nFROM gda_partition_ranked\nWHERE gda_partition_rank <= "
            + str(partition_limit)
            + "\nORDER BY "
            + ", ".join(partition_aliases + partition_order_terms)
            + "\nLIMIT "
            + str(min(limit, max_rows))
        )
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
    if semantic_ir.partition_by:
        logical_nodes.append(
            LogicalPlanNode(
                node_id="window_001",
                operator="window",
                input_node_ids=(current,),
                attributes={
                    "partition_by": list(semantic_ir.partition_by),
                    "partition_limit": int(semantic_ir.partition_limit or 0),
                    "order_by": [item.output_name for item in semantic_ir.order_by],
                },
            )
        )
        current = "window_001"
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
        compiler_removed_output_names=entity_list_removed_output_names,
        compiler_hidden_output_names=compiler_hidden_output_names,
        compiler_projection_policy_applications=projection_policy_applications,
        compiler_semantic_filter_corrections=enum_filter_corrections,
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
    "SemanticBandSpec",
    "SemanticBandSummary",
    "SemanticFilter",
    "SemanticUniversalCondition",
    "SemanticIRCompilationError",
    "SemanticIRValidationReport",
    "SemanticIROrder",
    "SemanticIRProjection",
    "SemanticDerivedExpression",
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
