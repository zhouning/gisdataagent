"""Generate conservative table-local inventory contracts for Abu Dhabi sources.

The source dictionaries contain enough evidence to expose a safe inventory
surface for every non-sensitive table, but not enough to invent cross-table
joins or domain-specific measures. This module deliberately emits only
COUNT(*) plus low-cardinality-looking dimensions whose names are explicit in
the runtime discovery.
"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_TERMS = {
    "zh": ["统计", "汇总"],
    "en": ["count", "summarize"],
    "ar": ["احسب", "لخص"],
}

_DIMENSION_PRIORITY = (
    "stage",
    "status",
    "statusindicator",
    "operationalstatus",
    "condition",
    "lifecyclestatus",
    "subtype",
    "subtypecd",
    "material",
    "type",
    "assetcategory",
    "category",
    "category_name",
    "ownership",
    "enabled",
    "municipality",
    "facility_category",
    "facility_type",
    "year",
    "reporting_year",
)
_EXCLUDED_FIELD_RE = re.compile(
    r"(?:^|_)(?:id|ids|fid|uid|guid|objectid|globalid|created|updated|modified|"
    r"date|time|geom|shape|xcoord|ycoord|zcoord|image|attachment|password|email|"
    r"phone|name_a|name_e)$",
    re.IGNORECASE,
)


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value)).strip("_") or "resource"


def _humanize(value: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", str(value)).strip().split()
    return " ".join(words) or str(value)


def choose_inventory_dimensions(resource: dict[str, Any], *, limit: int = 2) -> list[str]:
    """Choose only explicit, likely categorical fields; never infer values."""

    columns = [str(column.get("name") or "") for column in resource.get("columns") or []]
    available = {name.casefold(): name for name in columns if name}
    selected: list[str] = []
    for candidate in _DIMENSION_PRIORITY:
        name = available.get(candidate.casefold())
        if name and name not in selected:
            selected.append(name)
        if len(selected) >= limit:
            break
    if selected:
        return selected
    # Some utility tables expose a single categorical field with a longer name.
    for name in columns:
        lowered = name.casefold()
        if (
            name
            and not _EXCLUDED_FIELD_RE.search(lowered)
            and any(token in lowered for token in ("status", "type", "class", "category"))
        ):
            selected.append(name)
        if len(selected) >= limit:
            break
    return selected


def build_inventory_intent(
    resource: dict[str, Any],
    *,
    source_kind: str,
    mapping_row: dict[str, str] | None = None,
) -> dict[str, Any]:
    table = str(resource["name"])
    schema, _, bare = table.partition(".")
    family = str((mapping_row or {}).get("network_family_candidate") or "")
    dimensions = choose_inventory_dimensions(resource)
    safe_tail = _safe_identifier(bare).lower()
    prefix = "LIVEABILITY" if source_kind == "liveability" else "MAKANI"
    entity_prefix = "dmt_liveability" if source_kind == "liveability" else "dmt_utility"
    human = _humanize(bare)
    family_human = _humanize(family.replace("_", " ")) if family else "asset"
    asset_label = (
        f"Liveability table {human}"
        if source_kind == "liveability"
        else f"Makani {family_human} asset {human}"
    )
    contract_id = f"{prefix}_INVENTORY_{safe_tail.upper()}_V2"
    table_terms = [table, bare, human]
    questions = {
        "zh": (
            f"统计 {table} 表的记录数量"
            + (f"，按 {', '.join(dimensions)} 分组" if dimensions else "")
            + "。"
        ),
        "en": (
            f"Count records in {table}"
            + (f" grouped by {', '.join(dimensions)}" if dimensions else "")
            + "."
        ),
        "ar": (
            f"احسب سجلات الجدول {table}"
            + (f" مجمعة حسب {', '.join(dimensions)}" if dimensions else "")
            + "."
        ),
    }
    return {
        "id": f"{prefix.lower()}_inventory_{safe_tail}",
        "contract_id": contract_id,
        "table": table,
        "entity": f"{entity_prefix}.{safe_tail}",
        "labels": {
            "zh": asset_label,
            "en": asset_label,
            "ar": (
                f"جدول مكاني {human}"
                if source_kind == "makani"
                else f"جدول جودة الحياة {human}"
            ),
        },
        "aliases": [table, bare, human, asset_label],
        "dimensions": dimensions,
        "questions": questions,
        "match": {
            "required_term_groups": {
                language: [SUMMARY_TERMS[language], table_terms]
                for language in ("zh", "en", "ar")
            }
        },
        "family": family,
        "schema": schema,
    }


def metric_contract_for_inventory(intent: dict[str, Any]) -> dict[str, Any]:
    table = str(intent["table"])
    dimensions = [
        {"table": table, "field": field, "alias": field}
        for field in intent["dimensions"]
    ]
    return {
        "contract_id": intent["contract_id"],
        "operation": "grouped_summary",
        "match": intent["match"],
        "tables": [table],
        "dimensions": dimensions,
        "metrics": [{"aggregate": "count", "field": "*", "alias": "row_count"}],
        "order_by": list(intent["dimensions"]),
    }


def inventory_binding_fields(
    resource: dict[str, Any],
    intent: dict[str, Any],
) -> list[str]:
    columns = {str(column.get("name") or "") for column in resource.get("columns") or []}
    selected: list[str] = []
    primary_key = list(resource.get("primary_key") or [])
    if primary_key and str(primary_key[0]) in columns:
        selected.append(str(primary_key[0]))
    selected.extend(field for field in intent["dimensions"] if field in columns)
    if "geom" in columns:
        selected.append("geom")
    return list(dict.fromkeys(selected))
