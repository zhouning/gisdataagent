"""Governed map handoff for Abu Dhabi NL2SQL aggregate results.

The NL2SQL result contract deliberately excludes raw geometry.  This module
uses only reviewed semantic bindings to retrieve a bounded, server-side map
layer after a successful aggregate query, and passes GeoJSON directly to the
map renderer rather than to the chat answer.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .connectors.database import validate_database_read_query
from .query_result_contract import tabular_result_contract
from .virtual_sources import get_virtual_source, query_virtual_source

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAP_REQUEST_RE = re.compile(
    r"(?:\bmap\b|\bchoropleth\b|\bgraduated\b|地图|图上|图层|地图展示|分级设色|分级着色)",
    re.IGNORECASE,
)
_CHOROPLETH_RE = re.compile(
    r"(?:\bchoropleth\b|\bgraduated\b|分级设色|分级着色|按.{0,24}(?:着色|设色|颜色))",
    re.IGNORECASE,
)


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError("invalid semantic map identifier")
    return f'"{value}"'


def _quote_table(value: str) -> str:
    parts = str(value or "").split(".")
    if len(parts) != 2:
        raise ValueError("invalid semantic map table")
    return ".".join(_quote_identifier(part) for part in parts)


def _map_requested(question: str) -> bool:
    return bool(_MAP_REQUEST_RE.search(str(question or "")))


def _row_scope_predicates(
    *,
    semantic_layer: dict[str, Any],
    table: str,
    alias: str,
    question: str,
    language: str,
) -> list[str]:
    """Compile only reviewed boolean default scopes for a map binding."""

    predicates: list[str] = []
    normalized_table = str(table).casefold()
    for policy in semantic_layer.get("row_scope_policies") or []:
        if policy.get("review_status") != "reviewed":
            continue
        applies_to = {
            str(value or "").casefold()
            for value in policy.get("applies_to_tables") or []
        }
        if normalized_table not in applies_to:
            continue
        overrides = (policy.get("explicit_override_terms") or {}).get(language) or []
        lowered_question = str(question or "").casefold()
        if any(str(term or "").casefold() in lowered_question for term in overrides):
            continue
        predicate = policy.get("required_predicate") or {}
        if (
            str(predicate.get("table") or "").casefold() != normalized_table
            or str(predicate.get("operator") or "").casefold() != "is_true"
        ):
            raise ValueError("semantic_map_row_scope_requires_external_dimension")
        field = str(predicate.get("field") or "")
        predicates.append(f"{alias}.{_quote_identifier(field)} IS TRUE")
    return predicates


def _localized_label(item: dict[str, Any], language: str) -> str:
    labels = item.get("labels") or {}
    if not isinstance(labels, dict):
        return ""
    for locale in (language, "en", "zh", "ar"):
        value = str(labels.get(locale) or "").strip()
        if value:
            return value
    return ""


def _semantic_entity_label(
    semantic_layer: dict[str, Any],
    table: str,
    language: str,
) -> str:
    for asset in semantic_layer.get("semantic_assets") or []:
        if not isinstance(asset, dict):
            continue
        physical_tables = {str(value or "") for value in asset.get("physical_tables") or []}
        if table in physical_tables:
            return _localized_label(asset, language)
    return ""


def _semantic_field_label(
    semantic_layer: dict[str, Any],
    table: str,
    field: str,
    language: str,
) -> str:
    binding = next(
        (
            item
            for item in semantic_layer.get("table_bindings") or []
            if isinstance(item, dict) and str(item.get("physical_table") or "") == table
        ),
        None,
    )
    if not isinstance(binding, dict):
        return ""
    for candidate in binding.get("fields") or []:
        if not isinstance(candidate, dict):
            continue
        if field in {
            str(candidate.get("physical_field") or ""),
            str(candidate.get("semantic_field") or ""),
        }:
            return _localized_label(candidate, language)
    return ""


def _metric_table(contract: dict[str, Any], metric: dict[str, Any], dimension_table: str) -> str:
    declared = str(metric.get("table") or "").strip()
    if declared:
        return declared
    tables = [str(value or "") for value in contract.get("tables") or []]
    non_dimension_tables = [table for table in tables if table and table != dimension_table]
    return non_dimension_tables[0] if len(non_dimension_tables) == 1 else (tables[0] if tables else "")


def _aggregate_display_label(base: str, aggregate: str, language: str) -> str:
    normalized = aggregate.casefold()
    if normalized == "count":
        if language == "zh":
            return base if base.endswith("数量") else f"{base}数量"
        if language == "ar":
            return base if base.startswith("عدد ") else f"عدد {base}"
        return base if base.casefold().endswith("count") else f"{base} count"
    if normalized == "sum":
        return f"{base}合计" if language == "zh" else (f"إجمالي {base}" if language == "ar" else f"total {base}")
    if normalized in {"avg", "average"}:
        return f"{base}平均值" if language == "zh" else (f"متوسط {base}" if language == "ar" else f"average {base}")
    if normalized == "min":
        return f"{base}最小值" if language == "zh" else (f"الحد الأدنى لـ {base}" if language == "ar" else f"minimum {base}")
    if normalized == "max":
        return f"{base}最大值" if language == "zh" else (f"الحد الأقصى لـ {base}" if language == "ar" else f"maximum {base}")
    return base


def _contract_map_binding(
    report: dict[str, Any],
    semantic_layer: dict[str, Any],
    language: str,
) -> dict[str, Any] | None:
    query = report.get("query") or {}
    evidence = query.get("semantic_metric_contract") or {}
    contract_id = str(evidence.get("contract_id") or "")
    if not contract_id:
        return None
    contract = next(
        (
            item
            for item in semantic_layer.get("metric_contracts") or []
            if str(item.get("contract_id") or "") == contract_id
        ),
        None,
    )
    if not isinstance(contract, dict) or contract.get("review_status") != "reviewed_candidate":
        return None
    dimensions = list(contract.get("dimensions") or [])
    metrics = list(contract.get("metrics") or [])
    if len(dimensions) != 1 or len(metrics) != 1:
        return None

    dimension = dimensions[0]
    metric = metrics[0]
    table = str(dimension.get("table") or "")
    key_field = str(dimension.get("field") or "")
    key_alias = str(dimension.get("alias") or key_field)
    value_alias = str(metric.get("alias") or "")
    if not table or not key_field or not key_alias or not value_alias:
        return None
    binding = next(
        (
            item
            for item in semantic_layer.get("table_bindings") or []
            if str(item.get("physical_table") or "") == table
            and item.get("execution_eligible") is True
        ),
        None,
    )
    if not isinstance(binding, dict):
        return None
    geometry_fields = [
        str(field.get("physical_field") or "")
        for field in binding.get("fields") or []
        if str(field.get("business_role") or "").casefold() == "geometry"
        and str(field.get("physical_field") or "")
    ]
    if len(geometry_fields) != 1:
        return None
    # A reviewed metric contract may have a companion grouping field added by
    # the semantic projection policy (for example a municipality disambiguates
    # districts with the same display name).  Treat every result column that
    # binds to a reviewed dimension/identifier field as part of the map key.
    result_columns = {str(value) for value in (report.get("result") or {}).get("columns") or []}
    field_bindings = [item for item in binding.get("fields") or [] if isinstance(item, dict)]
    key_fields: list[dict[str, str]] = [{"physical_field": key_field, "output_alias": key_alias}]
    for output_alias in sorted(result_columns - {key_alias, value_alias}):
        match = next(
            (
                item
                for item in field_bindings
                if str(item.get("business_role") or "").casefold()
                in {"dimension", "identifier"}
                and output_alias.casefold()
                in {
                    str(item.get("semantic_field") or "").casefold(),
                    str(item.get("physical_field") or "").casefold(),
                }
            ),
            None,
        )
        if match is not None:
            key_fields.append(
                {
                    "physical_field": str(match.get("physical_field") or ""),
                    "output_alias": output_alias,
                }
            )
    if any(not item["physical_field"] or not _IDENTIFIER_RE.fullmatch(item["output_alias"]) for item in key_fields):
        return None
    dimension_label = (
        _semantic_entity_label(semantic_layer, table, language)
        or _semantic_field_label(semantic_layer, table, key_field, language)
        or key_alias.replace("_", " ")
    )
    metric_table = _metric_table(contract, metric, table)
    metric_field = str(metric.get("field") or "")
    metric_base_label = (
        _semantic_entity_label(semantic_layer, metric_table, language)
        if metric_field in {"", "*"}
        else _semantic_field_label(semantic_layer, metric_table, metric_field, language)
    )
    metric_base_label = metric_base_label or _semantic_entity_label(semantic_layer, metric_table, language)
    metric_label = _aggregate_display_label(
        metric_base_label or value_alias.replace("_", " "),
        str(metric.get("aggregate") or ""),
        language,
    )
    return {
        "contract_id": contract_id,
        "table": table,
        "key_field": key_field,
        "key_alias": key_alias,
        "value_alias": value_alias,
        "geometry_field": geometry_fields[0],
        "key_fields": key_fields,
        "dimension_label": dimension_label,
        "metric_label": metric_label,
    }


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _quantile_breaks(values: list[float | int], *, maximum_classes: int = 5) -> list[float | int]:
    ordered = sorted(values)
    if not ordered:
        return []
    class_count = min(maximum_classes, len(set(ordered)))
    breaks = []
    for index in range(1, class_count + 1):
        position = max(0, math.ceil(index * len(ordered) / class_count) - 1)
        value = ordered[position]
        if not breaks or value > breaks[-1]:
            breaks.append(value)
    if breaks[-1] != ordered[-1]:
        breaks.append(ordered[-1])
    return breaks


def _layer_title(*, language: str, metric: str, dimension: str) -> str:
    if language == "zh":
        return f"按{dimension}分级设色的{metric}"
    if language == "ar":
        return f"{metric} حسب {dimension}"
    return f"{metric} by {dimension}"


async def build_governed_nl2sql_map_update(
    *,
    report: dict[str, Any],
    question: str,
    semantic_layer_path: Path,
    source_id: int,
    owner: str,
    language: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a bounded choropleth map update from a reviewed metric result.

    The function returns a diagnostic for the audit metadata.  A missing
    governed binding is a normal non-map outcome; it never alters the NL2SQL
    tabular answer.
    """

    if not _map_requested(question):
        return None, {"status": "not_requested"}
    if report.get("status") != "ok":
        return None, {"status": "query_not_successful"}
    try:
        semantic_layer = json.loads(semantic_layer_path.read_text(encoding="utf-8"))
        binding = _contract_map_binding(report, semantic_layer, language)
        if binding is None:
            return None, {"status": "no_reviewed_polygon_metric_binding"}

        source = get_virtual_source(source_id, owner)
        if source is None:
            return None, {"status": "source_not_visible"}
        result = report.get("result") or {}
        metric_sql = str((report.get("query") or {}).get("sql") or "")
        if not metric_sql:
            return None, {"status": "metric_sql_unavailable"}
        validate_database_read_query(metric_sql, source.get("query_config") or {}, limit=1000)
        metric_frame = await query_virtual_source(
            source,
            limit=1000,
            extra_params={"sql": metric_sql, "geom_column": ""},
            register_result=False,
        )
        if isinstance(metric_frame, dict) or not hasattr(metric_frame, "columns"):
            return None, {"status": "metric_snapshot_unavailable"}
        snapshot = tabular_result_contract(metric_frame)
        if snapshot["result_fingerprint"] != result.get("result_fingerprint"):
            return None, {"status": "metric_snapshot_changed"}

        metric_columns = {str(value) for value in metric_frame.columns}
        if {binding["key_alias"], binding["value_alias"]} - metric_columns:
            return None, {"status": "metric_result_binding_mismatch"}
        def composite_key(row: dict[str, Any]) -> str:
            values = [str(row.get(item["output_alias"]) or "").strip() for item in binding["key_fields"]]
            if any(not value for value in values):
                return ""
            return json.dumps(values, ensure_ascii=False, separators=(",", ":"))

        metric_values: dict[str, tuple[dict[str, Any], float | int]] = {}
        for row in metric_frame.to_dict(orient="records"):
            key = composite_key(row)
            value = _finite_number(row.get(binding["value_alias"]))
            if not key or value is None or key in metric_values:
                return None, {"status": "metric_result_key_not_unique"}
            metric_values[key] = (row, value)

        alias = "gda_map"
        predicates = _row_scope_predicates(
            semantic_layer=semantic_layer,
            table=binding["table"],
            alias=alias,
            question=question,
            language=language,
        )
        predicates.append(f"{alias}.{_quote_identifier(binding['geometry_field'])} IS NOT NULL")
        key_select = ", ".join(
            f"{alias}.{_quote_identifier(item['physical_field'])} AS {_quote_identifier(item['output_alias'])}"
            for item in binding["key_fields"]
        )
        geometry_sql = (
            f"SELECT {key_select}, "
            f"ST_AsGeoJSON({alias}.{_quote_identifier(binding['geometry_field'])}) AS geometry_json "
            f"FROM {_quote_table(binding['table'])} AS {alias} "
            f"WHERE {' AND '.join(predicates)} "
            f"ORDER BY {alias}.{_quote_identifier(binding['key_field'])} LIMIT 1000"
        )
        validate_database_read_query(geometry_sql, source.get("query_config") or {}, limit=1000)
        geometry_frame = await query_virtual_source(
            source,
            limit=1000,
            extra_params={"sql": geometry_sql, "geom_column": ""},
            register_result=False,
        )
        if isinstance(geometry_frame, dict) or not hasattr(geometry_frame, "columns"):
            return None, {"status": "geometry_snapshot_unavailable"}

        geometries: dict[str, dict[str, Any]] = {}
        for row in geometry_frame.to_dict(orient="records"):
            key = composite_key(row)
            raw_geometry = row.get("geometry_json")
            if not key or key in geometries or not isinstance(raw_geometry, str):
                return None, {"status": "geometry_key_not_unique"}
            geometry = json.loads(raw_geometry)
            if not isinstance(geometry, dict) or not geometry.get("type"):
                return None, {"status": "geometry_payload_invalid"}
            geometries[key] = geometry

        features = [
            {
                "type": "Feature",
                "properties": {
                    **{
                        item["output_alias"]: row.get(item["output_alias"])
                        for item in binding["key_fields"]
                    },
                    binding["value_alias"]: value,
                },
                "geometry": geometries[key],
            }
            for key, (row, value) in metric_values.items()
            if key in geometries
        ]
        if not features:
            return None, {"status": "no_geometry_matches"}
        values = [feature["properties"][binding["value_alias"]] for feature in features]
        breaks = _quantile_breaks(values)
        if not breaks:
            return None, {"status": "no_numeric_metric_values"}

        title = _layer_title(
            language=language,
            metric=binding["metric_label"],
            dimension=binding["dimension_label"],
        )
        map_update = {
            "schema": "map_update.v1",
            "summary": {
                "title": title,
                "query_type": "governed_nl2sql_choropleth",
                "contract_id": binding["contract_id"],
                "feature_count": len(features),
                "result_row_count": len(metric_values),
                "metric_result_fingerprint": snapshot["result_fingerprint"],
            },
            "layers": [
                {
                    "name": title,
                    "type": "choropleth",
                    "geojsonData": {"type": "FeatureCollection", "features": features},
                    "value_column": binding["value_alias"],
                    "breaks": breaks,
                    "color_scheme": "YlGnBu",
                    "legend_title": title,
                    "style": {"color": "#475569", "weight": 1, "fillOpacity": 0.72},
                }
            ],
        }
        return map_update, {
            "status": "ready",
            "contract_id": binding["contract_id"],
            "feature_count": len(features),
            "unmapped_result_rows": len(metric_values) - len(features),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return None, {"status": "unavailable", "reason": str(exc)[:180]}


__all__ = ["build_governed_nl2sql_map_update"]
