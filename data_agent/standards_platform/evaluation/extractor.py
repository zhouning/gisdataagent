"""Extract predicted derivation eval items from the live DB."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from .schema import DerivationEvalItem, DerivationEvalSet


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _source_key(row: dict) -> str:
    return f"{row['source_kind']}:{row['source_id']}"


def _value_domain_match(conn, link: dict, row: dict) -> dict[str, Any]:
    match: dict[str, Any] = {"hint_kind": row["hint_kind"]}
    domain = conn.execute(text(
        "SELECT d.kind AS domain_kind, d.code AS domain_code, "
        "       array_agg(i.value ORDER BY i.ordinal, i.value) "
        "           FILTER (WHERE i.value IS NOT NULL) AS values "
        "FROM std_data_element e "
        "LEFT JOIN std_value_domain d ON d.id = e.value_domain_id "
        "LEFT JOIN std_value_domain_item i ON i.value_domain_id = d.id "
        "WHERE e.id=:i "
        "GROUP BY d.kind, d.code"
    ), {"i": str(link["source_id"])}).mappings().first()
    if domain is None or domain["domain_kind"] is None:
        match["hint_text_zh"] = row["hint_text_zh"]
        return match

    match["domain_kind"] = domain["domain_kind"]
    if domain["domain_code"]:
        match["domain_code"] = domain["domain_code"]
    values = list(domain["values"] or [])
    if values:
        match["values"] = values
    else:
        match["hint_text_zh"] = row["hint_text_zh"]
    return match


def _semantic_hint_item(conn, link: dict) -> DerivationEvalItem | None:
    row = conn.execute(text(
        "SELECT scope_ref, hint_kind, hint_text_zh, trigger_keywords "
        "FROM agent_semantic_hints WHERE id=:i"
    ), {"i": int(link["target_id"])}).mappings().first()
    if row is None:
        return None
    return DerivationEvalItem(
        strategy=link["derivation_strategy"],
        source_key=_source_key(link),
        target_kind=link["target_kind"],
        target_key=f"{row['scope_ref']}:{row['hint_kind']}",
        match=(
            _value_domain_match(conn, link, row)
            if link["derivation_strategy"] == "to_value_semantics"
            else {"hint_kind": row["hint_kind"]}
        ),
        payload={
            "hint_text_zh": row["hint_text_zh"],
            "trigger_keywords": _json_value(row["trigger_keywords"]),
        },
    )


def _semantic_source_items(conn, link: dict) -> list[DerivationEvalItem]:
    row = conn.execute(text(
        "SELECT table_name, derived_synonyms "
        "FROM agent_semantic_sources WHERE id=:i"
    ), {"i": int(link["target_id"])}).mappings().first()
    if row is None:
        return []
    synonyms = _json_value(row["derived_synonyms"]) or []
    table_name = str(row["table_name"])
    items: list[DerivationEvalItem] = []
    for synonym in sorted({str(s) for s in synonyms if s}):
        items.append(DerivationEvalItem(
            strategy=link["derivation_strategy"],
            source_key=f"semantic_source:{table_name}",
            target_kind=link["target_kind"],
            target_key=f"{table_name}:{synonym}",
            match={"synonym": synonym},
            payload={
                "table_name": table_name,
                "derived_synonyms": synonyms,
            },
        ))
    return items


def _quality_rule_item(conn, link: dict) -> DerivationEvalItem | None:
    row = conn.execute(text(
        "SELECT rule_name, rule_type, config, severity "
        "FROM agent_quality_rules WHERE id=:i"
    ), {"i": int(link["target_id"])}).mappings().first()
    if row is None:
        return None
    config = _json_value(row["config"]) or {}
    return DerivationEvalItem(
        strategy=link["derivation_strategy"],
        source_key=_source_key(link),
        target_kind=link["target_kind"],
        target_key=f"{row['rule_name']}:{row['rule_type']}",
        match={
            "rule_type": row["rule_type"],
            "config": config,
        },
        payload={"severity": row["severity"]},
    )


def _defect_binding_item(conn, link: dict) -> DerivationEvalItem | None:
    row = conn.execute(text(
        "SELECT std_data_element_id, defect_code, severity, category, "
        "binding_kind "
        "FROM agent_defect_code_bindings WHERE id=:i"
    ), {"i": str(link["target_id"])}).mappings().first()
    if row is None:
        return None
    return DerivationEvalItem(
        strategy=link["derivation_strategy"],
        source_key=_source_key(link),
        target_kind=link["target_kind"],
        target_key=f"{row['std_data_element_id']}:{row['defect_code']}:{row['binding_kind']}",
        match={
            "defect_code": row["defect_code"],
            "binding_kind": row["binding_kind"],
        },
        payload={
            "severity": row["severity"],
            "category": row["category"],
        },
    )


def _data_model_item(conn, link: dict) -> DerivationEvalItem | None:
    row = conn.execute(text(
        "SELECT document_version_id, entity_count, attribute_count, "
        "constraint_count, ddl_postgresql "
        "FROM std_data_model_snapshot WHERE id=:i"
    ), {"i": str(link["target_id"])}).mappings().first()
    if row is None:
        return None
    ddl = row["ddl_postgresql"] or ""
    return DerivationEvalItem(
        strategy=link["derivation_strategy"],
        source_key=f"document_version:{row['document_version_id']}",
        target_kind=link["target_kind"],
        target_key=str(link["target_id"]),
        match={
            "entity_count": row["entity_count"],
            "attribute_count": row["attribute_count"],
            "constraint_count": row["constraint_count"],
        },
        payload={
            "has_ddl": bool(ddl.strip()),
            "ddl_preview": ddl[:500],
        },
    )


def _unsupported_item(link: dict) -> DerivationEvalItem:
    return DerivationEvalItem(
        strategy=link["derivation_strategy"],
        source_key=_source_key(link),
        target_kind=link["target_kind"],
        target_key=str(link["target_id"]),
        match={"unsupported_table": link["target_table"]},
        payload={"target_table": link["target_table"]},
    )


def _one(item: DerivationEvalItem | None) -> list[DerivationEvalItem]:
    return [] if item is None else [item]


def _items_for_link(conn, link: dict) -> list[DerivationEvalItem]:
    table = link["target_table"]
    if table == "agent_semantic_hints":
        return _one(_semantic_hint_item(conn, link))
    if table == "agent_semantic_sources":
        return _semantic_source_items(conn, link)
    if table == "agent_quality_rules":
        return _one(_quality_rule_item(conn, link))
    if table == "agent_defect_code_bindings":
        return _one(_defect_binding_item(conn, link))
    if table == "std_data_model_snapshot":
        return _one(_data_model_item(conn, link))
    return [_unsupported_item(link)]


def extract_prediction_set(engine, *, version_id: str) -> DerivationEvalSet:
    """Read active derivation links for a version and build prediction items."""
    with engine.connect() as conn:
        links = conn.execute(text(
            "SELECT id, source_kind, source_id, source_version_id, "
            "target_kind, target_table, target_id, derivation_strategy, status "
            "FROM std_derived_link "
            "WHERE source_version_id=:v AND status='active' "
            "ORDER BY derivation_strategy, target_table, target_id"
        ), {"v": version_id}).mappings().all()

        items: list[DerivationEvalItem] = []
        for link in links:
            items.extend(_items_for_link(conn, dict(link)))

    return DerivationEvalSet(
        dataset_id=f"predictions:{version_id}",
        metadata={"version_id": version_id},
        items=tuple(items),
    )
