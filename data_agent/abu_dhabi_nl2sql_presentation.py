"""Structured, semantic-layer-driven presentation for Abu Dhabi NL2SQL answers."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_AGGREGATE_PREFIXES = {
    "avg": "avg",
    "average": "avg",
    "mean": "avg",
    "sum": "sum",
    "total": "sum",
    "min": "min",
    "minimum": "min",
    "max": "max",
    "maximum": "max",
    "count": "count",
    "number": "count",
}
_TEMPORAL_TERMS = (
    "date",
    "time",
    "year",
    "month",
    "quarter",
    "week",
    "day",
    "日期",
    "时间",
    "年份",
    "年度",
    "月份",
    "季度",
    "تاريخ",
    "وقت",
    "سنة",
    "شهر",
)


def _safe_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _column_candidates(name: str) -> list[tuple[str, str | None]]:
    normalized = str(name or "").strip().casefold()
    candidates: list[tuple[str, str | None]] = [(normalized, None)]
    remainder = normalized
    inferred_aggregate: str | None = None
    for _ in range(3):
        match = next(
            (
                (prefix, aggregate)
                for prefix, aggregate in _AGGREGATE_PREFIXES.items()
                if remainder.startswith(prefix + "_") and len(remainder) > len(prefix) + 1
            ),
            None,
        )
        if match is None:
            break
        prefix, aggregate = match
        inferred_aggregate = inferred_aggregate or aggregate
        remainder = remainder[len(prefix) + 1 :]
        candidate = (remainder, inferred_aggregate)
        if candidate not in candidates:
            candidates.append(candidate)
    if remainder.endswith("_count") and len(remainder) > len("_count"):
        candidate = (remainder[: -len("_count")], inferred_aggregate or "count")
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


@lru_cache(maxsize=16)
def _semantic_catalog(path_text: str) -> dict[str, Any]:
    payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    fields_by_table: dict[str, dict[str, dict[str, Any]]] = {}
    table_labels: dict[str, dict[str, str]] = {}
    for binding in payload.get("table_bindings") or []:
        table = str(binding.get("physical_table") or "").casefold()
        if not table:
            continue
        table_labels[table] = dict(binding.get("labels") or {})
        fields_by_table[table] = {
            str(field.get("physical_field") or field.get("semantic_field") or "").casefold(): field
            for field in binding.get("fields") or []
            if field.get("physical_field") or field.get("semantic_field")
        }
    contracts = {
        str(contract.get("contract_id") or ""): contract
        for contract in payload.get("metric_contracts") or []
        if contract.get("contract_id")
    }
    return {
        "fields_by_table": fields_by_table,
        "table_labels": table_labels,
        "contracts": contracts,
    }


def _selected_tables(report: dict[str, Any]) -> list[str]:
    query = report.get("query") or {}
    tables = [str(value).casefold() for value in query.get("tables") or []]
    if tables:
        return tables
    metric_contract = query.get("semantic_metric_contract") or {}
    return [str(value).casefold() for value in metric_contract.get("tables") or []]


def _contract_column_metadata(
    report: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, tuple[str, str | None]]:
    planner = report.get("planner") or {}
    evidence = (report.get("query") or {}).get("semantic_metric_contract") or {}
    contract_id = str(evidence.get("contract_id") or planner.get("contract_id") or "")
    contract = catalog["contracts"].get(contract_id) or {}
    metadata: dict[str, tuple[str, str | None]] = {}
    for dimension in contract.get("dimensions") or []:
        alias = str(dimension.get("alias") or dimension.get("field") or "").casefold()
        field = str(dimension.get("field") or "").casefold()
        if alias and field:
            metadata[alias] = (field, None)
    for metric in contract.get("metrics") or []:
        alias = str(metric.get("alias") or metric.get("field") or "").casefold()
        field = str(metric.get("field") or "").casefold()
        aggregate = str(metric.get("aggregate") or "").casefold() or None
        if alias and field and field != "*":
            metadata[alias] = (field, aggregate)
    return metadata


def _resolve_semantic_field(
    column: str,
    *,
    selected_tables: list[str],
    catalog: dict[str, Any],
    contract_columns: dict[str, tuple[str, str | None]],
) -> tuple[dict[str, Any] | None, str | None]:
    normalized = column.casefold()
    override = contract_columns.get(normalized)
    candidates = [override] if override else []
    candidates.extend(_column_candidates(normalized))
    table_order = selected_tables or list(catalog["fields_by_table"])
    for field_name, aggregate in candidates:
        for table in table_order:
            field = (catalog["fields_by_table"].get(table) or {}).get(field_name)
            if field:
                return field, aggregate
    return None, next((aggregate for _, aggregate in candidates if aggregate), None)


def _humanize_identifier(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ")).strip()


def _aggregate_label(label: str, aggregate: str | None, language: str) -> str:
    if not aggregate:
        return label
    if language == "zh":
        prefixes = {"avg": "平均", "sum": "总", "count": "数量", "min": "最低", "max": "最高"}
        if aggregate == "count":
            return f"{label}数量" if not label.endswith("数量") else label
        return prefixes.get(aggregate, "") + label
    if language == "ar":
        prefixes = {
            "avg": "متوسط",
            "sum": "إجمالي",
            "count": "عدد",
            "min": "أدنى",
            "max": "أعلى",
        }
        return f"{prefixes.get(aggregate, '')} {label}".strip()
    prefixes = {
        "avg": "Average",
        "sum": "Total",
        "count": "Number of",
        "min": "Minimum",
        "max": "Maximum",
    }
    return f"{prefixes.get(aggregate, '')} {label}".strip()


def _is_numeric_column(key: str, rows: list[dict[str, Any]]) -> bool:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return bool(values) and all(_safe_number(value) is not None for value in values)


def _decimals_for(column: str, aggregate: str | None, rows: list[dict[str, Any]]) -> int:
    if aggregate == "count" or column.casefold().endswith("_count"):
        return 0
    values = [row.get(column) for row in rows]
    if values and all(
        value is None or (isinstance(value, int) and not isinstance(value, bool))
        for value in values
    ):
        return 0
    return 2


def _format_number(value: float | int, decimals: int, language: str) -> str:
    if decimals == 0:
        return f"{int(round(value)):,}"
    return f"{float(value):,.{decimals}f}"


def _localized_title(
    dimensions: list[dict[str, Any]],
    measures: list[dict[str, Any]],
    language: str,
) -> str:
    if len(dimensions) == 1 and len(measures) == 1:
        dimension = dimensions[0]["label"]
        measure = measures[0]["label"]
        if language == "zh":
            return f"按{dimension}统计的{measure}"
        if language == "ar":
            return f"{measure} حسب {dimension}"
        return f"{measure} by {dimension}"
    return {"zh": "查询结果", "en": "Query result", "ar": "نتيجة الاستعلام"}[language]


def _localized_summary(
    rows: list[dict[str, Any]],
    dimension: dict[str, Any] | None,
    measure: dict[str, Any] | None,
    language: str,
) -> str:
    if not dimension or not measure or len(rows) < 2:
        return ""
    usable = [row for row in rows if _safe_number(row.get(measure["key"])) is not None]
    if len(usable) < 2:
        return ""
    highest = max(usable, key=lambda row: float(row[measure["key"]]))
    lowest = min(usable, key=lambda row: float(row[measure["key"]]))
    high_value = float(highest[measure["key"]])
    low_value = float(lowest[measure["key"]])
    decimals = int(measure["format"]["decimals"])
    high_text = _format_number(high_value, decimals, language)
    low_text = _format_number(low_value, decimals, language)
    difference = _format_number(high_value - low_value, decimals, language)
    high_name = str(highest.get(dimension["key"]) or "-")
    low_name = str(lowest.get(dimension["key"]) or "-")
    metric = str(measure["label"])
    if language == "zh":
        return (
            f"{high_name} 的{metric}最高，为 {high_text}；"
            f"{low_name} 最低，为 {low_text}，相差 {difference}。"
        )
    if language == "ar":
        return (
            f"سجل {high_name} أعلى {metric} بقيمة {high_text}، بينما سجل "
            f"{low_name} أدنى قيمة عند {low_text}؛ والفارق {difference}."
        )
    metric_sentence = metric[:1].lower() + metric[1:]
    return (
        f"{high_name} has the highest {metric_sentence} at {high_text}. "
        f"{low_name} is lowest at {low_text}; the difference is {difference}."
    )


def _is_temporal(column: dict[str, Any]) -> bool:
    text = f"{column['key']} {column['label']}".casefold()
    return any(term in text for term in _TEMPORAL_TERMS)


def _visualization_spec(
    rows: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
    measures: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(rows) == 1 and measures:
        return {"kind": "kpi", "measure_keys": [item["key"] for item in measures[:4]]}
    if len(dimensions) == 1 and 1 <= len(measures) <= 3 and 2 <= len(rows) <= 30:
        temporal = _is_temporal(dimensions[0])
        return {
            "kind": "line" if temporal else "bar",
            "orientation": "vertical" if temporal or len(rows) > 12 else "horizontal",
            "category_key": dimensions[0]["key"],
            "measure_keys": [item["key"] for item in measures],
            "sort": "source" if temporal else "measure_desc",
        }
    return {"kind": "table"}


def _model_evidence(report: dict[str, Any]) -> dict[str, Any]:
    planner = report.get("planner") or {}
    invoked = planner.get("llm_invoked") is True
    generation = report.get("generation") or {}
    usage = generation.get("usage") or {}
    versions = [str(value) for value in generation.get("observed_model_versions") or []]
    configured_model = report.get("model") or {}
    return {
        "invoked": invoked,
        "route": planner.get("route"),
        "contract_id": planner.get("contract_id"),
        "model": (
            versions[0]
            if invoked and versions
            else configured_model.get("adk_route") or configured_model.get("requested")
            if invoked
            else None
        ),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
        "generation_ms": generation.get("latency_ms") if invoked else None,
    }


def build_nl2sql_answer_presentation(
    report: dict[str, Any],
    *,
    semantic_layer_path: Path,
    language: str,
    total_ms: float | None = None,
) -> dict[str, Any] | None:
    """Build a safe structured answer without embedding benchmark-specific logic."""

    if report.get("status") != "ok":
        return None
    result = report.get("result") or {}
    raw_columns = [str(value) for value in result.get("columns") or []]
    rows = [dict(row) for row in result.get("data") or [] if isinstance(row, dict)]
    if not raw_columns:
        return None

    catalog = _semantic_catalog(str(semantic_layer_path.resolve()))
    selected_tables = _selected_tables(report)
    contract_columns = _contract_column_metadata(report, catalog)
    columns: list[dict[str, Any]] = []
    for key in raw_columns:
        field, aggregate = _resolve_semantic_field(
            key,
            selected_tables=selected_tables,
            catalog=catalog,
            contract_columns=contract_columns,
        )
        label = str((field or {}).get("labels", {}).get(language) or _humanize_identifier(key))
        label = _aggregate_label(label, aggregate, language)
        numeric = _is_numeric_column(key, rows)
        role = str((field or {}).get("business_role") or "")
        if numeric and role not in {"identifier", "district_key", "dimension"}:
            role = "measure"
        elif not role:
            role = "measure" if numeric else "dimension"
        columns.append(
            {
                "key": key,
                "label": label,
                "role": role,
                "numeric": numeric,
                "aggregate": aggregate,
                "format": {"decimals": _decimals_for(key, aggregate, rows)},
            }
        )

    dimensions = [
        item for item in columns if item["role"] in {"dimension", "category", "temporal_dimension"}
    ]
    dimensions.extend(
        item
        for item in columns
        if not item["numeric"]
        and item["role"] not in {"measure", "identifier", "district_key"}
        and item not in dimensions
    )
    measures = [item for item in columns if item["role"] == "measure" and item["numeric"]]
    if not dimensions:
        dimensions = [item for item in columns if not item["numeric"]]
    if not measures:
        measures = [
            item
            for item in columns
            if item["numeric"]
            and item["role"] not in {"identifier", "district_key", "dimension"}
            and item not in dimensions
        ]
    visualization = _visualization_spec(rows, dimensions, measures)
    source = report.get("source") or {}
    query = report.get("query") or {}
    fingerprints = result.get("equivalence_fingerprints") or {}
    timing = report.get("timing") or {}
    resolved_total_ms = total_ms if total_ms is not None else timing.get("total_ms")

    return {
        "schema": "gda.nl2sql-answer-presentation.v1",
        "language": language,
        "title": _localized_title(dimensions, measures, language),
        "summary": _localized_summary(
            rows,
            dimensions[0] if len(dimensions) == 1 else None,
            measures[0] if len(measures) == 1 else None,
            language,
        ),
        "row_count": int(result.get("row_count") or len(rows)),
        "displayed_row_count": int(result.get("displayed_row_count") or len(rows)),
        "truncated": bool(result.get("truncated_for_display")),
        "columns": columns,
        "rows": rows,
        "visualization": visualization,
        "timing": {
            "total_ms": (
                round(float(resolved_total_ms), 3) if resolved_total_ms is not None else None
            ),
            "database_ms": timing.get("database_ms"),
        },
        "model": _model_evidence(report),
        "evidence": {
            "database_name": source.get("database_name"),
            "schemas": list(source.get("authorized_schemas") or []),
            "read_only": source.get("execution_mode") == "registered_governed_virtual_read_only",
            "semantic_version": report.get("semantic_version"),
            "sql": query.get("sql"),
            "fingerprint": fingerprints.get("unordered_position_numeric6_fingerprint"),
            "execution_attempt_count": query.get("execution_attempt_count"),
        },
    }


__all__ = ["build_nl2sql_answer_presentation"]
