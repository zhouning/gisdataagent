"""Semantic ontology package helpers for MMFE products.

The ontology package is a compact JSON contract derived from an MMFE semantic
product and its sidecars. It normalizes roles, object types, fields, value
domains, rules, objectives, relation types and standard sources so downstream
agents can bind to stable semantic concepts without parsing raw fixture files.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEMANTIC_ONTOLOGY_SCHEMA = "mmfe.semantic_ontology.v1"
SEMANTIC_ONTOLOGY_VERSION = "0.1"


def build_semantic_ontology_package(
    manifest: dict,
    *,
    field_semantics: list[dict] | None = None,
    value_domain_audits: list[dict] | None = None,
    standard_sources: list[dict] | None = None,
    semantic_relations: list[dict] | None = None,
    state_input: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build a JSON-only ontology package from an MMFE semantic product."""
    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")

    bundle = manifest.get("mmfe_bundle") or {}
    fields = [
        dict(row)
        for row in list(field_semantics or bundle.get("field_semantics") or [])
        if isinstance(row, dict)
    ]
    domains = [
        dict(row)
        for row in list(value_domain_audits or bundle.get("value_domain_audits") or [])
        if isinstance(row, dict)
    ]
    relations = [
        dict(row)
        for row in list(semantic_relations or bundle.get("semantic_relations") or [])
        if isinstance(row, dict)
    ]
    standard_source_rows = _resolve_standard_source_rows(bundle, standard_sources)
    state = state_input or bundle.get("twm_state_input") or {}

    role_bindings = _resolve_role_bindings(bundle, state)
    standard_roles = _build_standard_roles(role_bindings, fields)
    object_types = _build_object_types(standard_roles)
    standard_source_concepts = _build_standard_sources(standard_source_rows)
    value_domains = _build_value_domains(domains, fields, standard_source_concepts)
    semantic_keys = _build_semantic_keys(fields, role_bindings)
    field_concepts = _build_fields(fields, value_domains, standard_source_concepts)
    relation_types = _build_relation_types(relations)
    rules = _build_rules(bundle.get("rule_bindings") or [], relation_types)
    objectives = _build_objectives((bundle.get("optimization_summary") or {}).get("objectives") or [], relation_types)
    relationships = _build_relationships(
        standard_roles=standard_roles,
        object_types=object_types,
        fields=field_concepts,
        value_domains=value_domains,
        semantic_keys=semantic_keys,
        standard_sources=standard_source_concepts,
        relation_types=relation_types,
        rules=rules,
        objectives=objectives,
    )

    concepts = {
        "standard_roles": standard_roles,
        "object_types": object_types,
        "fields": field_concepts,
        "semantic_keys": semantic_keys,
        "value_domains": value_domains,
        "standard_sources": standard_source_concepts,
        "relation_types": relation_types,
        "rules": rules,
        "optimization_objectives": objectives,
    }
    return {
        "schema": SEMANTIC_ONTOLOGY_SCHEMA,
        "version": SEMANTIC_ONTOLOGY_VERSION,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "source_product": {
            "product_id": manifest.get("product_id"),
            "product_type": manifest.get("product_type"),
            "product_version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
        },
        "summary": _build_summary(concepts, relationships),
        "concepts": concepts,
        "relationships": relationships,
    }


def validate_semantic_ontology_package(payload: dict) -> dict:
    """Validate the ontology package surface required by downstream consumers."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != SEMANTIC_ONTOLOGY_SCHEMA:
        errors.append(f"schema must be {SEMANTIC_ONTOLOGY_SCHEMA}")
    if not (payload.get("source_product") or {}).get("product_id"):
        errors.append("source_product.product_id is required")
    concepts = payload.get("concepts")
    if not isinstance(concepts, dict):
        errors.append("concepts must be a JSON object")
        concepts = {}
    for key in (
        "standard_roles",
        "object_types",
        "fields",
        "value_domains",
        "standard_sources",
        "relation_types",
        "rules",
        "optimization_objectives",
    ):
        if not isinstance(concepts.get(key), list):
            errors.append(f"concepts.{key} must be a list")
    relationships = payload.get("relationships")
    if not isinstance(relationships, list):
        errors.append("relationships must be a list")
    summary = payload.get("summary") or {}
    if not isinstance(summary.get("field_count"), int):
        errors.append("summary.field_count must be an integer")
    if not isinstance(summary.get("relationship_count"), int):
        errors.append("summary.relationship_count must be an integer")
    return {"valid": not errors, "errors": errors}


def write_semantic_ontology_package(payload: dict, out_path: str | Path) -> str:
    """Write an ontology package and return its path."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _resolve_standard_source_rows(bundle: dict, standard_sources: list[dict] | None) -> list[dict]:
    if standard_sources:
        return [dict(row) for row in standard_sources if isinstance(row, dict)]
    registry = bundle.get("standard_source_registry") or {}
    entries = registry.get("entries")
    if isinstance(entries, list) and entries:
        return [dict(row) for row in entries if isinstance(row, dict)]
    rows = bundle.get("standard_source_rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _resolve_role_bindings(bundle: dict, state_input: dict) -> list[dict]:
    state_roles = state_input.get("object_role_registry") if isinstance(state_input, dict) else None
    if isinstance(state_roles, list) and state_roles:
        return [dict(row) for row in state_roles if isinstance(row, dict)]
    contract = bundle.get("twm_consumption") or {}
    bindings = contract.get("role_bindings")
    if isinstance(bindings, list) and bindings:
        return [dict(row) for row in bindings if isinstance(row, dict)]
    layers = bundle.get("layer_summaries") or []
    rows = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        rows.append({
            "role": layer.get("role") or layer.get("semantic_domain"),
            "standard_role": layer.get("standard_role") or layer.get("role"),
            "role_alias_zh": layer.get("standard_role_alias_zh") or layer.get("alias_zh"),
            "object_type": layer.get("object_type") or "semantic_object",
            "source_path": layer.get("path"),
            "quality_score": layer.get("quality_score"),
            "business_role_zh": layer.get("business_role_zh"),
            "twm_binding": layer.get("twm_binding") or {},
            "semantic_readiness": layer.get("semantic_readiness") or "ready_for_state_builder",
        })
    return rows


def _build_standard_roles(role_bindings: list[dict], field_semantics: list[dict]) -> list[dict]:
    fields_by_role = defaultdict(list)
    for field in field_semantics:
        role = field.get("layer_role") or ""
        if role:
            fields_by_role[role].append(field)

    role_by_name: dict[str, dict] = {}
    for binding in role_bindings:
        role = str(binding.get("role") or "").strip()
        if not role:
            continue
        standard_role = str(binding.get("standard_role") or role).strip()
        object_type = str(binding.get("object_type") or "semantic_object").strip()
        row_fields = fields_by_role.get(role, [])
        role_by_name[role] = {
            "id": f"role:{standard_role}",
            "role": role,
            "standard_role": standard_role,
            "label_zh": binding.get("role_alias_zh") or binding.get("business_role_zh") or standard_role,
            "object_type": object_type,
            "business_role_zh": binding.get("business_role_zh") or "",
            "source_path": binding.get("source_path") or "",
            "quality_score": _safe_float(binding.get("quality_score"), None),
            "semantic_readiness": binding.get("semantic_readiness") or "",
            "twm_binding": dict(binding.get("twm_binding") or {}),
            "field_count": _safe_int(binding.get("field_count"), len(row_fields)),
            "accepted_field_count": sum(1 for item in row_fields if item.get("alignment_decision") == "accept"),
            "review_field_count": sum(1 for item in row_fields if _to_bool(item.get("requires_review"))),
            "not_for_production": _to_bool(binding.get("not_for_production")),
        }

    for field in field_semantics:
        role = str(field.get("layer_role") or "").strip()
        if not role or role in role_by_name:
            continue
        standard_role = str(field.get("standard_role") or role).strip()
        object_type = str(field.get("object_type") or "semantic_object").strip()
        role_fields = fields_by_role.get(role, [])
        role_by_name[role] = {
            "id": f"role:{standard_role}",
            "role": role,
            "standard_role": standard_role,
            "label_zh": standard_role,
            "object_type": object_type,
            "business_role_zh": "",
            "source_path": "",
            "quality_score": None,
            "semantic_readiness": "field_semantics_only",
            "twm_binding": {},
            "field_count": len(role_fields),
            "accepted_field_count": sum(1 for item in role_fields if item.get("alignment_decision") == "accept"),
            "review_field_count": sum(1 for item in role_fields if _to_bool(item.get("requires_review"))),
            "not_for_production": any(_to_bool(item.get("not_for_production")) for item in role_fields),
        }

    return sorted(role_by_name.values(), key=lambda item: (item["standard_role"], item["role"]))


def _build_object_types(standard_roles: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for role in standard_roles:
        grouped[role.get("object_type") or "semantic_object"].append(role)
    rows = []
    for object_type, roles in grouped.items():
        rows.append({
            "id": f"object_type:{object_type}",
            "object_type": object_type,
            "standard_roles": sorted({role.get("standard_role") for role in roles if role.get("standard_role")}),
            "layer_roles": sorted({role.get("role") for role in roles if role.get("role")}),
            "source_count": len({role.get("source_path") for role in roles if role.get("source_path")}),
            "field_count": sum(_safe_int(role.get("field_count"), 0) for role in roles),
        })
    return sorted(rows, key=lambda item: item["object_type"])


def _build_standard_sources(rows: list[dict]) -> list[dict]:
    concepts = []
    for row in rows:
        identifier = row.get("standard_identifier") or row.get("source_name") or row.get("title_zh")
        if not identifier:
            continue
        concepts.append({
            "id": f"standard_source:{_slug(identifier)}",
            "standard_identifier": identifier,
            "source_name": row.get("source_name") or row.get("title_zh") or identifier,
            "title_zh": row.get("title_zh") or row.get("source_name") or identifier,
            "title_en": row.get("title_en") or "",
            "authority": row.get("authority") or "",
            "official_platform": row.get("official_platform") or "",
            "official_url": row.get("official_url") or "",
            "retrieval_status": row.get("retrieval_status") or "",
            "access_mode": row.get("access_mode") or "",
            "used_for": list(row.get("used_for") or []),
            "can_download": _to_bool(row.get("can_download")),
            "can_online_preview": _to_bool(row.get("can_online_preview")),
            "not_for_production_gap": _to_bool(row.get("not_for_production_gap")),
        })
    return sorted(_dedupe_by_id(concepts), key=lambda item: item["id"])


def _build_value_domains(
    audits: list[dict],
    field_semantics: list[dict],
    standard_sources: list[dict],
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for audit in audits:
        domain = str(audit.get("domain") or audit.get("value_domain") or "").strip()
        if domain:
            grouped[domain].append(audit)
    for field in field_semantics:
        domain = str(field.get("value_domain") or "").strip()
        if domain and domain not in grouped:
            grouped[domain] = []

    concepts = []
    for domain, rows in grouped.items():
        coverage_values = [_safe_float(row.get("coverage"), None) for row in rows]
        coverage_values = [value for value in coverage_values if value is not None]
        status_counts = Counter(str(row.get("audit_status") or row.get("domain_status") or "unknown") for row in rows)
        field_refs = [
            _field_id(row.get("layer_role"), row.get("field_name"))
            for row in rows
            if row.get("layer_role") and row.get("field_name")
        ]
        source_ids = _infer_standard_source_ids_for_domain(domain, standard_sources)
        concepts.append({
            "id": f"value_domain:{domain}",
            "domain": domain,
            "domain_status": _first_non_empty(row.get("domain_status") for row in rows),
            "audit_status_distribution": dict(status_counts),
            "audited_field_count": len(rows),
            "field_ids": field_refs,
            "domain_item_count": max([_safe_int(row.get("domain_item_count"), 0) for row in rows] or [0]),
            "total_observation_count": sum(_safe_int(row.get("total_count"), 0) for row in rows),
            "unknown_value_count": sum(_safe_int(row.get("unknown_count"), 0) for row in rows),
            "coverage_min": min(coverage_values) if coverage_values else None,
            "coverage_mean": round(sum(coverage_values) / len(coverage_values), 6) if coverage_values else None,
            "sample_observed_values": _sample_domain_values(rows),
            "standard_source_ids": source_ids,
            "not_for_production": any(_to_bool(row.get("not_for_production")) for row in rows),
        })
    return sorted(concepts, key=lambda item: item["domain"])


def _build_semantic_keys(field_semantics: list[dict], role_bindings: list[dict]) -> list[dict]:
    refs: dict[str, set[str]] = defaultdict(set)
    for field in field_semantics:
        key = str(field.get("twm_semantic_key") or "").strip()
        if key:
            refs[key].add(_field_id(field.get("layer_role"), field.get("field_name")))
    for binding in role_bindings:
        role = binding.get("role")
        for key, field_name in (binding.get("twm_binding") or {}).items():
            if key and field_name:
                refs[str(key)].add(_field_id(role, field_name))
    return [
        {
            "id": f"semantic_key:{key}",
            "semantic_key": key,
            "field_ids": sorted(field_ids),
            "field_count": len(field_ids),
        }
        for key, field_ids in sorted(refs.items())
    ]


def _build_fields(
    rows: list[dict],
    value_domains: list[dict],
    standard_sources: list[dict],
) -> list[dict]:
    domain_by_name = {domain["domain"]: domain for domain in value_domains}
    concepts = []
    for row in rows:
        layer_role = row.get("layer_role")
        field_name = row.get("field_name")
        if not layer_role or not field_name:
            continue
        standard_ref = _json_object(row.get("standard_reference_json"))
        source_ids = _infer_standard_source_ids_for_field(standard_ref, standard_sources)
        domain = row.get("value_domain") or ""
        if domain and domain_by_name.get(domain):
            source_ids = sorted(set(source_ids) | set(domain_by_name[domain].get("standard_source_ids") or []))
        concepts.append({
            "id": _field_id(layer_role, field_name),
            "layer_role": layer_role,
            "standard_role": row.get("standard_role") or "",
            "object_type": row.get("object_type") or "",
            "field_name": field_name,
            "field_alias_zh": row.get("field_alias_zh") or "",
            "standard_field": row.get("standard_field") or "",
            "twm_semantic_key": row.get("twm_semantic_key") or "",
            "value_domain": domain,
            "alignment_decision": row.get("alignment_decision") or "",
            "alignment_match_type": row.get("alignment_match_type") or row.get("match_type") or "",
            "alignment_score": _safe_float(row.get("alignment_score"), None),
            "confidence": _safe_float(row.get("confidence"), None),
            "requires_review": _to_bool(row.get("requires_review")),
            "contract_requirement": row.get("contract_requirement") or "",
            "standard_reference": standard_ref,
            "standard_source_ids": source_ids,
            "not_for_production": _to_bool(row.get("not_for_production")),
        })
    return sorted(concepts, key=lambda item: item["id"])


def _build_relation_types(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        relation_type = str(row.get("semantic_relation_type") or row.get("relation_type") or "").strip()
        if relation_type:
            grouped[relation_type].append(row)

    concepts = []
    for relation_type, rels in grouped.items():
        concepts.append({
            "id": f"relation_type:{relation_type}",
            "relation_type": relation_type,
            "relation_count": len(rels),
            "source_object_types": sorted({row.get("source_object_type") for row in rels if row.get("source_object_type")}),
            "target_object_types": sorted({row.get("target_object_type") for row in rels if row.get("target_object_type")}),
            "target_standard_roles": sorted({row.get("target_standard_role") for row in rels if row.get("target_standard_role")}),
            "twm_usages": sorted({row.get("twm_usage") for row in rels if row.get("twm_usage")}),
            "rule_ids": sorted({row.get("rule_id") for row in rels if row.get("rule_id")}),
            "objective_ids": sorted({row.get("objective_id") for row in rels if row.get("objective_id")}),
            "evidence_types": sorted({row.get("evidence_type") for row in rels if row.get("evidence_type")}),
            "metric_names": sorted({row.get("metric_name") for row in rels if row.get("metric_name")}),
            "requires_review_count": sum(1 for row in rels if _to_bool(row.get("requires_rule_review"))),
            "semantic_strength_distribution": dict(Counter(row.get("semantic_strength") or "unknown" for row in rels)),
            "not_for_production": any(_to_bool(row.get("not_for_production")) for row in rels),
        })
    return sorted(concepts, key=lambda item: item["relation_type"])


def _build_rules(rows: list[dict], relation_types: list[dict]) -> list[dict]:
    rels_by_rule: dict[str, list[str]] = defaultdict(list)
    for rel in relation_types:
        for rule_id in rel.get("rule_ids") or []:
            rels_by_rule[rule_id].append(rel["id"])

    concepts = []
    for row in rows:
        rule_id = row.get("rule_id")
        if not rule_id:
            continue
        concepts.append({
            "id": f"rule:{rule_id}",
            "rule_id": rule_id,
            "rule_name_zh": row.get("rule_name_zh") or rule_id,
            "severity": row.get("severity") or "",
            "target_layer": row.get("target_layer") or "",
            "target_standard_role": row.get("target_standard_role") or "",
            "constraint_layer": row.get("constraint_layer") or "",
            "constraint_standard_role": row.get("constraint_standard_role") or "",
            "logic": row.get("logic") or "",
            "relation_type_ids": sorted(set(rels_by_rule.get(rule_id) or [])),
        })
    return sorted(concepts, key=lambda item: item["rule_id"])


def _build_objectives(rows: list[dict], relation_types: list[dict]) -> list[dict]:
    rels_by_objective: dict[str, list[str]] = defaultdict(list)
    for rel in relation_types:
        for objective_id in rel.get("objective_ids") or []:
            rels_by_objective[objective_id].append(rel["id"])

    concepts = []
    for row in rows:
        objective_id = row.get("objective_id")
        if not objective_id:
            continue
        concepts.append({
            "id": f"objective:{objective_id}",
            "objective_id": objective_id,
            "objective_name_zh": row.get("objective_name_zh") or objective_id,
            "category": row.get("category") or "",
            "direction": row.get("direction") or "",
            "unit": row.get("unit") or "",
            "weight": _safe_float(row.get("weight"), None),
            "hard_constraint": _to_bool(row.get("hard_constraint")),
            "description_zh": row.get("description_zh") or "",
            "relation_type_ids": sorted(set(rels_by_objective.get(objective_id) or [])),
        })
    return sorted(concepts, key=lambda item: item["objective_id"])


def _build_relationships(
    *,
    standard_roles: list[dict],
    object_types: list[dict],
    fields: list[dict],
    value_domains: list[dict],
    semantic_keys: list[dict],
    standard_sources: list[dict],
    relation_types: list[dict],
    rules: list[dict],
    objectives: list[dict],
) -> list[dict]:
    existing_object_types = {item["id"] for item in object_types}
    existing_standard_sources = {item["id"] for item in standard_sources}
    relationships = []

    for role in standard_roles:
        target = f"object_type:{role.get('object_type')}"
        if target in existing_object_types:
            relationships.append(_edge(role["id"], target, "binds_object_type"))

    for field in fields:
        if field.get("standard_role"):
            relationships.append(_edge(field["id"], f"role:{field['standard_role']}", "belongs_to_role"))
        if field.get("value_domain"):
            relationships.append(_edge(field["id"], f"value_domain:{field['value_domain']}", "uses_value_domain"))
        if field.get("twm_semantic_key"):
            relationships.append(_edge(field["id"], f"semantic_key:{field['twm_semantic_key']}", "provides_semantic_key"))
        for source_id in field.get("standard_source_ids") or []:
            if source_id in existing_standard_sources:
                relationships.append(_edge(field["id"], source_id, "grounded_by_standard_source"))

    for domain in value_domains:
        for field_id in domain.get("field_ids") or []:
            relationships.append(_edge(domain["id"], field_id, "audits_field"))
        for source_id in domain.get("standard_source_ids") or []:
            if source_id in existing_standard_sources:
                relationships.append(_edge(domain["id"], source_id, "grounded_by_standard_source"))

    for key in semantic_keys:
        for field_id in key.get("field_ids") or []:
            relationships.append(_edge(key["id"], field_id, "implemented_by_field"))

    role_ids = {role["id"] for role in standard_roles}
    object_type_ids = {item["id"] for item in object_types}
    for rel in relation_types:
        for object_type in set((rel.get("source_object_types") or []) + (rel.get("target_object_types") or [])):
            target = f"object_type:{object_type}"
            if target in object_type_ids:
                relationships.append(_edge(rel["id"], target, "connects_object_type"))
        for standard_role in rel.get("target_standard_roles") or []:
            target = f"role:{standard_role}"
            if target in role_ids:
                relationships.append(_edge(rel["id"], target, "targets_role"))

    for rule in rules:
        for relation_type_id in rule.get("relation_type_ids") or []:
            relationships.append(_edge(rule["id"], relation_type_id, "checks_relation_type"))
    for objective in objectives:
        for relation_type_id in objective.get("relation_type_ids") or []:
            relationships.append(_edge(objective["id"], relation_type_id, "uses_relation_type"))

    return _dedupe_edges(relationships)


def _build_summary(concepts: dict[str, list[dict]], relationships: list[dict]) -> dict:
    fields = concepts.get("fields") or []
    standard_sources = concepts.get("standard_sources") or []
    value_domains = concepts.get("value_domains") or []
    return {
        "standard_role_count": len(concepts.get("standard_roles") or []),
        "object_type_count": len(concepts.get("object_types") or []),
        "field_count": len(fields),
        "semantic_key_count": len(concepts.get("semantic_keys") or []),
        "value_domain_count": len(value_domains),
        "audited_value_domain_count": sum(1 for item in value_domains if _safe_int(item.get("audited_field_count"), 0) > 0),
        "standard_source_count": len(standard_sources),
        "official_standard_source_count": sum(
            1 for item in standard_sources if str(item.get("retrieval_status") or "").startswith("official_")
        ),
        "relation_type_count": len(concepts.get("relation_types") or []),
        "rule_count": len(concepts.get("rules") or []),
        "optimization_objective_count": len(concepts.get("optimization_objectives") or []),
        "relationship_count": len(relationships),
        "accepted_field_count": sum(1 for item in fields if item.get("alignment_decision") == "accept"),
        "review_field_count": sum(1 for item in fields if item.get("requires_review")),
        "production_gap_count": sum(1 for item in standard_sources if item.get("not_for_production_gap")),
        "not_for_production": any(
            item.get("not_for_production")
            for group in concepts.values()
            for item in group
            if isinstance(item, dict)
        ),
    }


def _infer_standard_source_ids_for_domain(domain: str, standard_sources: list[dict]) -> list[str]:
    tokens = {_normal_key(domain)}
    if "21010" in domain:
        tokens.add("gbt210102017")
        tokens.add("gbt21010")
    matches = []
    for source in standard_sources:
        haystack = _normal_key(
            " ".join(
                str(source.get(key) or "")
                for key in ("standard_identifier", "source_name", "title_zh")
            )
        )
        used_for = _normal_key(" ".join(str(item) for item in source.get("used_for") or []))
        if any(token and (token in haystack or token in used_for) for token in tokens):
            matches.append(source["id"])
    return sorted(set(matches))


def _infer_standard_source_ids_for_field(standard_ref: dict, standard_sources: list[dict]) -> list[str]:
    docs = standard_ref.get("source_documents") if isinstance(standard_ref, dict) else None
    standard_id = standard_ref.get("standard_id") if isinstance(standard_ref, dict) else None
    tokens = {_normal_key(item) for item in docs or [] if item}
    if standard_id:
        tokens.add(_normal_key(standard_id))
    matches = []
    for source in standard_sources:
        haystack = _normal_key(
            " ".join(
                str(source.get(key) or "")
                for key in ("standard_identifier", "source_name", "title_zh")
            )
        )
        if any(token and (token in haystack or haystack in token) for token in tokens):
            matches.append(source["id"])
    return sorted(set(matches))


def _sample_domain_values(rows: list[dict], limit: int = 8) -> list[dict]:
    values = []
    for row in rows:
        parsed = _json_list(row.get("observed_values_json"))
        for item in parsed:
            if isinstance(item, dict):
                values.append({
                    "code": item.get("code"),
                    "name_zh": item.get("name_zh"),
                    "count": item.get("count"),
                })
            if len(values) >= limit:
                return values
    return values


def _field_id(layer_role: Any, field_name: Any) -> str:
    return f"field:{layer_role}.{field_name}"


def _edge(source: str, target: str, relationship: str, properties: dict | None = None) -> dict:
    edge = {"source": source, "target": target, "relationship": relationship}
    if properties:
        edge["properties"] = properties
    return edge


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    seen = set()
    rows = []
    for edge in edges:
        key = (edge.get("source"), edge.get("target"), edge.get("relationship"))
        if not edge.get("source") or not edge.get("target") or key in seen:
            continue
        seen.add(key)
        rows.append(edge)
    return sorted(rows, key=lambda item: (item["source"], item["relationship"], item["target"]))


def _dedupe_by_id(rows: list[dict]) -> list[dict]:
    by_id = {}
    for row in rows:
        by_id[row["id"]] = row
    return list(by_id.values())


def _json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _first_non_empty(values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("/", "-")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    return text.strip("-") or "unknown"


def _normal_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())
