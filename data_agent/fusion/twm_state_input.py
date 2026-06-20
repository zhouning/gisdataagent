"""TWM state-input artifacts derived from MMFE semantic products.

This module does not implement a Territorial World Model. It turns an MMFE
semantic fusion product into a compact downstream contract that TWM validation
code can consume: roles, canonical field bindings, semantic relation summaries,
hard constraints, multimodal evidence hooks and optimization objective bindings.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TWM_STATE_INPUT_SCHEMA = "mmfe.twm_state_input.v1"
TWM_STATE_INPUT_VERSION = "0.1"


def build_twm_state_input_from_semantic_product(
    manifest: dict,
    semantic_relations: list[dict] | None = None,
    input_contract: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build a TWM-ready state-input artifact from an MMFE semantic product."""
    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")

    mmfe_bundle = manifest.get("mmfe_bundle") or {}
    contract = input_contract or mmfe_bundle.get("twm_consumption") or {}
    layers = list(mmfe_bundle.get("layer_summaries") or [])
    relations = [
        _normalise_relation(row)
        for row in list(semantic_relations or mmfe_bundle.get("semantic_relations") or [])
        if isinstance(row, dict)
    ]
    role_bindings = _normalise_role_bindings(contract.get("role_bindings") or [], layers)
    relation_registry = _build_relation_registry(relations)
    relation_summary = _build_relation_summary(relations, relation_registry)
    optimization = mmfe_bundle.get("optimization_summary") or {}
    alignment = mmfe_bundle.get("alignment_summary") or {}
    value_domain_audit = mmfe_bundle.get("value_domain_audit_summary") or {}
    standard_source_registry = mmfe_bundle.get("standard_source_registry") or {}
    standard_source_summary = standard_source_registry.get("summary") or {}
    quality = manifest.get("quality") or {}
    warnings = _build_state_input_warnings(
        manifest=manifest,
        role_bindings=role_bindings,
        relations=relations,
        alignment=alignment,
        quality=quality,
    )

    return {
        "schema": TWM_STATE_INPUT_SCHEMA,
        "version": TWM_STATE_INPUT_VERSION,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "source_product": {
            "product_id": manifest.get("product_id"),
            "product_type": manifest.get("product_type"),
            "product_version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "business_outputs": manifest.get("business_outputs") or {},
            "quality_score": quality.get("score"),
        },
        "state_builder_policy": contract.get(
            "state_builder_policy",
            "load_semantic_product_then_dereference_raw_sources",
        ),
        "raw_data_usage": contract.get(
            "raw_data_usage",
            "source_of_truth_geometry_and_attributes",
        ),
        "semantic_product_usage": contract.get(
            "semantic_product_usage",
            "role_binding_quality_lineage_evidence_and_ai_grounding",
        ),
        "production_policy": {
            "contains_synthetic_sources": _contains_synthetic_sources(role_bindings, relations),
            "not_for_production": _is_not_for_production(manifest, role_bindings, relations),
            "authoritative_data_required_for_production": True,
            "policy_zh": (
                "该状态输入用于验证 MMFE 到 TWM 的数据契约。几何和属性事实仍以源数据为准，"
                "语义角色、字段绑定、关系、规则、证据和优化目标以 MMFE 语义融合成果为准；"
                "进入生产时必须替换为真实权威自然资源数据。"
            ),
        },
        "object_role_registry": role_bindings,
        "canonical_object_type_registry": _build_object_type_registry(role_bindings),
        "field_binding_registry": _build_field_binding_registry(role_bindings),
        "semantic_relation_summary": relation_summary,
        "semantic_relation_registry": relation_registry,
        "state_components": {
            "project_parcel_impacts": _build_usage_component(
                relation_registry,
                {"state_builder_project_parcel_impact"},
            ),
            "hard_constraints": _build_usage_component(
                relation_registry,
                {"hard_constraint_pbf_overlap", "hard_constraint_eco_overlap"},
                hard_constraint=True,
            ),
            "planning_consistency": _build_usage_component(
                relation_registry,
                {"planning_consistency_assessment", "urban_boundary_consistency"},
            ),
            "remote_sensing_evidence": _build_usage_component(
                relation_registry,
                {"multimodal_observation_evidence"},
            ),
            "dynamic_transitions": _build_usage_component(
                relation_registry,
                {"dynamic_state_transition"},
            ),
        },
        "optimization_interface": _build_optimization_interface(optimization, relation_registry),
        "standard_readiness": {
            "field_semantic_count": (contract.get("state_builder_inputs") or {}).get(
                "field_semantic_count",
                len(mmfe_bundle.get("field_semantics") or []),
            ),
            "alignment_decisions": alignment.get("decisions", {}),
            "alignment_review_required": alignment.get("review_required", 0),
            "missing_value_domains": alignment.get("missing_value_domains", {}),
            "loaded_value_domains": alignment.get("loaded_value_domains", {}),
            "value_domain_audit": value_domain_audit,
            "standard_sources": standard_source_summary,
        },
        "ai_grounding": {
            "chunk_count": len((manifest.get("ai_metadata") or {}).get("chunks") or []),
            "embedding_ready": bool((manifest.get("ai_metadata") or {}).get("embedding_ready")),
            "recommended_vector_targets": list(
                (manifest.get("ai_metadata") or {}).get("recommended_vector_targets") or []
            ),
        },
        "warnings": warnings,
    }


def validate_twm_state_input(payload: dict) -> dict:
    """Validate the small contract surface required by downstream TWM code."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TWM_STATE_INPUT_SCHEMA:
        errors.append(f"schema must be {TWM_STATE_INPUT_SCHEMA}")
    if not (payload.get("source_product") or {}).get("product_id"):
        errors.append("source_product.product_id is required")
    if not isinstance(payload.get("object_role_registry"), list):
        errors.append("object_role_registry must be a list")
    if not isinstance(payload.get("semantic_relation_registry"), list):
        errors.append("semantic_relation_registry must be a list")
    if payload.get("canonical_object_type_registry") is not None and not isinstance(payload.get("canonical_object_type_registry"), list):
        errors.append("canonical_object_type_registry must be a list")

    relation_summary = payload.get("semantic_relation_summary") or {}
    relation_registry = payload.get("semantic_relation_registry") or []
    if isinstance(relation_registry, list):
        registry_total = sum(_safe_int(item.get("relation_count"), 0) for item in relation_registry)
        if _safe_int(relation_summary.get("total_relation_count"), registry_total) != registry_total:
            errors.append("semantic_relation_summary.total_relation_count does not match registry")

    components = payload.get("state_components") or {}
    if not isinstance(components, dict):
        errors.append("state_components must be an object")
        components = {}
    if isinstance(payload.get("object_role_registry"), list):
        errors.extend(_validate_role_type_closure(payload))
    if isinstance(relation_registry, list):
        errors.extend(_validate_component_reference_closure(payload, components, relation_registry))
    return {"valid": not errors, "errors": errors}


def _validate_role_type_closure(payload: dict) -> list[str]:
    errors: list[str] = []
    role_registry = [row for row in payload.get("object_role_registry") or [] if isinstance(row, dict)]
    canonical_registry = [row for row in payload.get("canonical_object_type_registry") or [] if isinstance(row, dict)]
    canonical_types = {str(row.get("object_type")) for row in canonical_registry if row.get("object_type")}
    seen_roles: set[str] = set()
    for idx, row in enumerate(role_registry):
        role = str(row.get("role") or "")
        standard_role = str(row.get("standard_role") or "")
        object_type = str(row.get("object_type") or "")
        if not role:
            errors.append(f"object_role_registry[{idx}].role is required")
        elif role in seen_roles:
            errors.append(f"object_role_registry role is duplicated: {role}")
        seen_roles.add(role)
        if not standard_role:
            errors.append(f"object_role_registry[{idx}].standard_role is required")
        if not object_type:
            errors.append(f"object_role_registry[{idx}].object_type is required")
        elif canonical_types and object_type not in canonical_types:
            errors.append(f"object_role_registry[{idx}].object_type is not in canonical_object_type_registry: {object_type}")
    for idx, row in enumerate(canonical_registry):
        object_type = row.get("object_type")
        if not object_type:
            errors.append(f"canonical_object_type_registry[{idx}].object_type is required")
    return errors


def _validate_component_reference_closure(payload: dict, components: dict, relation_registry: list[dict]) -> list[str]:
    errors: list[str] = []
    relation_rule_ids = {
        str(rule_id)
        for row in relation_registry
        if isinstance(row, dict)
        for rule_id in row.get("rule_ids") or []
        if rule_id
    }
    relation_objective_ids = {
        str(objective_id)
        for row in relation_registry
        if isinstance(row, dict)
        for objective_id in row.get("objective_ids") or []
        if objective_id
    }
    optimization_interface = payload.get("optimization_interface") or {}
    objective_bindings = optimization_interface.get("objective_bindings") or []
    bound_objective_ids = {
        str(row.get("objective_id"))
        for row in objective_bindings
        if isinstance(row, dict) and row.get("objective_id")
    }
    known_objective_ids = relation_objective_ids | bound_objective_ids

    for component_name, component in components.items():
        if not isinstance(component, dict):
            errors.append(f"state_components.{component_name} must be an object")
            continue
        for rule_id in component.get("rule_ids") or []:
            if rule_id and str(rule_id) not in relation_rule_ids:
                errors.append(f"state_components.{component_name}.rule_ids references unknown semantic relation rule_id: {rule_id}")
        for objective_id in component.get("objective_ids") or []:
            if objective_id and str(objective_id) not in known_objective_ids:
                errors.append(f"state_components.{component_name}.objective_ids references unknown objective_id: {objective_id}")

    hard_constraints = components.get("hard_constraints") or {}
    if isinstance(hard_constraints, dict):
        for objective_id in hard_constraints.get("objective_ids") or []:
            if objective_id and str(objective_id) not in bound_objective_ids:
                errors.append(f"state_components.hard_constraints.objective_ids is not bound in optimization_interface: {objective_id}")
    return errors


def write_twm_state_input(payload: dict, out_path: str | Path) -> str:
    """Write a TWM state-input artifact and return its path."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_twm_state_input_inputs(mmfe_dir: str | Path) -> dict:
    """Load conventional TWM MMFE product sidecars from a semantic-fusion dir."""
    root = Path(mmfe_dir)
    return {
        "manifest": _read_json(root / "twm_mmfe_semantic_product.json"),
        "semantic_relations": _read_csv(root / "twm_mmfe_semantic_relations.csv"),
        "input_contract": _read_json(root / "twm_state_input_contract.json"),
    }


def _normalise_role_bindings(bindings: list[dict], layers: list[dict]) -> list[dict]:
    if bindings:
        rows = [dict(item) for item in bindings if isinstance(item, dict)]
    else:
        rows = [
            {
                "role": layer.get("role") or layer.get("semantic_domain"),
                "standard_role": layer.get("standard_role"),
                "role_alias_zh": layer.get("standard_role_alias_zh") or layer.get("alias_zh"),
                "object_type": layer.get("object_type") or "semantic_object",
                "source_path": layer.get("path"),
                "twm_binding": layer.get("twm_binding") or {},
                "quality_score": layer.get("quality_score"),
                "semantic_readiness": "ready_for_state_builder",
                "synthetic": layer.get("synthetic"),
                "not_for_production": layer.get("not_for_production"),
            }
            for layer in layers
            if isinstance(layer, dict)
        ]

    layer_by_role = {layer.get("role"): layer for layer in layers if isinstance(layer, dict)}
    normalised = []
    for row in rows:
        role = row.get("role") or row.get("semantic_domain") or ""
        layer = layer_by_role.get(role, {})
        merged = {
            "role": role,
            "standard_role": row.get("standard_role") or layer.get("standard_role") or role,
            "role_alias_zh": row.get("role_alias_zh")
            or layer.get("standard_role_alias_zh")
            or layer.get("alias_zh")
            or role,
            "object_type": row.get("object_type") or layer.get("object_type") or "semantic_object",
            "business_role_zh": row.get("business_role_zh") or layer.get("business_role_zh") or "",
            "source_path": row.get("source_path") or layer.get("path") or "",
            "quality_score": _safe_float(row.get("quality_score", layer.get("quality_score")), None),
            "twm_binding": dict(row.get("twm_binding") or layer.get("twm_binding") or {}),
            "semantic_readiness": row.get("semantic_readiness") or "ready_for_state_builder",
            "synthetic": _to_bool(row.get("synthetic", layer.get("synthetic", False))),
            "not_for_production": _to_bool(
                row.get("not_for_production", layer.get("not_for_production", False))
            ),
        }
        normalised.append(merged)
    return normalised


def _normalise_relation(row: dict) -> dict:
    normalized = dict(row)
    normalized["metric_value"] = _safe_float(row.get("metric_value"), 0.0)
    normalized["overlap_area_m2"] = _safe_float(row.get("overlap_area_m2"), 0.0)
    normalized["overlap_ratio_left"] = _safe_float(row.get("overlap_ratio_left"), 0.0)
    normalized["overlap_ratio_right"] = _safe_float(row.get("overlap_ratio_right"), 0.0)
    normalized["confidence"] = _safe_float(row.get("confidence"), 0.0)
    normalized["requires_rule_review"] = _to_bool(row.get("requires_rule_review"))
    normalized["synthetic"] = _to_bool(row.get("synthetic"))
    normalized["not_for_production"] = _to_bool(row.get("not_for_production"))
    return normalized


def _build_object_type_registry(role_bindings: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for binding in role_bindings:
        grouped[binding.get("object_type") or "semantic_object"].append(binding)
    return [
        {
            "object_type": object_type,
            "roles": [item["role"] for item in rows if item.get("role")],
            "standard_roles": sorted({item.get("standard_role") for item in rows if item.get("standard_role")}),
            "source_count": len(rows),
        }
        for object_type, rows in sorted(grouped.items())
    ]


def _build_field_binding_registry(role_bindings: list[dict]) -> list[dict]:
    return [
        {
            "role": binding["role"],
            "standard_role": binding["standard_role"],
            "object_type": binding["object_type"],
            "source_path": binding["source_path"],
            "bindings": binding.get("twm_binding") or {},
            "binding_count": len(binding.get("twm_binding") or {}),
        }
        for binding in role_bindings
    ]


def _build_relation_registry(relations: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in relations:
        relation_type = row.get("semantic_relation_type") or row.get("relation_type") or "semantic_relation"
        grouped[relation_type].append(row)

    registry = []
    for relation_type, rows in sorted(grouped.items()):
        metric_sums: dict[str, float] = defaultdict(float)
        max_metric_value = 0.0
        for row in rows:
            metric_name = row.get("metric_name") or "metric_value"
            metric_value = _safe_float(row.get("metric_value"), 0.0)
            metric_sums[metric_name] += metric_value
            max_metric_value = max(max_metric_value, metric_value)
        registry.append({
            "semantic_relation_type": relation_type,
            "relation_count": len(rows),
            "twm_usages": sorted({row.get("twm_usage") for row in rows if row.get("twm_usage")}),
            "source_object_types": sorted(
                {row.get("source_object_type") for row in rows if row.get("source_object_type")}
            ),
            "target_object_types": sorted(
                {row.get("target_object_type") for row in rows if row.get("target_object_type")}
            ),
            "target_standard_roles": sorted(
                {row.get("target_standard_role") for row in rows if row.get("target_standard_role")}
            ),
            "objective_ids": sorted({row.get("objective_id") for row in rows if row.get("objective_id")}),
            "rule_ids": sorted({row.get("rule_id") for row in rows if row.get("rule_id")}),
            "evidence_types": sorted({row.get("evidence_type") for row in rows if row.get("evidence_type")}),
            "requires_rule_review_count": sum(1 for row in rows if _to_bool(row.get("requires_rule_review"))),
            "source_object_count": len({row.get("source_object_id") for row in rows if row.get("source_object_id")}),
            "target_object_count": len({row.get("target_object_id") for row in rows if row.get("target_object_id")}),
            "metric_sums_by_name": {key: round(value, 6) for key, value in sorted(metric_sums.items())},
            "max_metric_value": round(max_metric_value, 6),
            "sample_relations": [_relation_sample(row) for row in rows[:5]],
        })
    return registry


def _relation_sample(row: dict) -> dict:
    return {
        "relation_id": row.get("relation_id"),
        "source_object_id": row.get("source_object_id"),
        "target_object_id": row.get("target_object_id"),
        "predicate_zh": row.get("predicate_zh"),
        "twm_usage": row.get("twm_usage"),
        "objective_id": row.get("objective_id"),
        "rule_id": row.get("rule_id"),
        "metric_name": row.get("metric_name"),
        "metric_value": _safe_float(row.get("metric_value"), 0.0),
        "confidence": _safe_float(row.get("confidence"), 0.0),
    }


def _build_relation_summary(relations: list[dict], registry: list[dict]) -> dict:
    usage_counter = Counter(row.get("twm_usage") for row in relations if row.get("twm_usage"))
    type_counter = Counter(row.get("semantic_relation_type") for row in relations if row.get("semantic_relation_type"))
    target_role_counter = Counter(row.get("target_standard_role") for row in relations if row.get("target_standard_role"))
    return {
        "total_relation_count": len(relations),
        "relation_type_distribution": dict(type_counter),
        "twm_usage_distribution": dict(usage_counter),
        "target_role_distribution": dict(target_role_counter),
        "rule_review_relation_count": sum(1 for row in relations if _to_bool(row.get("requires_rule_review"))),
        "registered_relation_type_count": len(registry),
    }


def _build_usage_component(
    relation_registry: list[dict],
    usage_values: set[str],
    hard_constraint: bool = False,
) -> dict:
    selected = [
        item
        for item in relation_registry
        if usage_values.intersection(set(item.get("twm_usages") or []))
    ]
    metric_sums: dict[str, float] = defaultdict(float)
    for item in selected:
        for name, value in (item.get("metric_sums_by_name") or {}).items():
            metric_sums[name] += _safe_float(value, 0.0)
    return {
        "relation_count": sum(_safe_int(item.get("relation_count"), 0) for item in selected),
        "relation_types": [item["semantic_relation_type"] for item in selected],
        "twm_usages": sorted(usage_values),
        "objective_ids": sorted({obj for item in selected for obj in item.get("objective_ids") or []}),
        "rule_ids": sorted({rule for item in selected for rule in item.get("rule_ids") or []}),
        "target_standard_roles": sorted(
            {role for item in selected for role in item.get("target_standard_roles") or []}
        ),
        "requires_rule_review_count": sum(
            _safe_int(item.get("requires_rule_review_count"), 0) for item in selected
        ),
        "metric_sums_by_name": {key: round(value, 6) for key, value in sorted(metric_sums.items())},
        "hard_constraint": hard_constraint,
    }


def _build_optimization_interface(optimization: dict, relation_registry: list[dict]) -> dict:
    objectives = list(optimization.get("objectives") or [])
    hard_ids = set(optimization.get("hard_constraint_objectives") or [])
    registry_by_objective: dict[str, list[dict]] = defaultdict(list)
    for item in relation_registry:
        for objective_id in item.get("objective_ids") or []:
            registry_by_objective[objective_id].append(item)

    objective_bindings = []
    for objective in objectives:
        objective_id = objective.get("objective_id")
        related = registry_by_objective.get(objective_id, [])
        objective_bindings.append({
            "objective_id": objective_id,
            "objective_name_zh": objective.get("objective_name_zh"),
            "category": objective.get("category"),
            "direction": objective.get("direction"),
            "unit": objective.get("unit"),
            "weight": _safe_float(objective.get("weight"), 0.0),
            "hard_constraint": bool(objective.get("hard_constraint")) or objective_id in hard_ids,
            "relation_types": [item["semantic_relation_type"] for item in related],
            "relation_count": sum(_safe_int(item.get("relation_count"), 0) for item in related),
            "rule_ids": sorted({rule for item in related for rule in item.get("rule_ids") or []}),
            "twm_usages": sorted({usage for item in related for usage in item.get("twm_usages") or []}),
        })

    return {
        "method": optimization.get("method"),
        "objective_count": optimization.get("objective_count") or len(objectives),
        "scenario_count": optimization.get("scenario_count"),
        "legal_feasible_scenario_count": optimization.get("legal_feasible_scenario_count"),
        "blocked_scenario_count": optimization.get("blocked_scenario_count"),
        "comparison_scope": optimization.get("comparison_scope"),
        "hard_constraint_policy_zh": optimization.get("hard_constraint_policy_zh"),
        "hard_constraint_objectives": sorted(hard_ids),
        "objective_bindings": objective_bindings,
    }


def _build_state_input_warnings(
    *,
    manifest: dict,
    role_bindings: list[dict],
    relations: list[dict],
    alignment: dict,
    quality: dict,
) -> list[str]:
    warnings = [str(item) for item in quality.get("warnings") or [] if item]
    if _is_not_for_production(manifest, role_bindings, relations):
        warnings.append("TWM state input is a validation scaffold and is not for production decisions.")
    missing_value_domains = alignment.get("missing_value_domains") or {}
    if missing_value_domains:
        warnings.append(f"Missing value-domain items require standard-platform completion: {missing_value_domains}.")
    if not role_bindings:
        warnings.append("No role bindings were found; TWM state builder cannot bind source roles.")
    if not relations:
        warnings.append("No semantic relations were found; downstream TWM relation graph will be empty.")
    return _dedupe(warnings)


def _contains_synthetic_sources(role_bindings: list[dict], relations: list[dict]) -> bool:
    return any(_to_bool(row.get("synthetic")) for row in role_bindings + relations) or any(
        "synthetic" in str(row.get("role") or row.get("source_path") or "").lower()
        for row in role_bindings
    )


def _is_not_for_production(manifest: dict, role_bindings: list[dict], relations: list[dict]) -> bool:
    if _to_bool(manifest.get("not_for_production")):
        return True
    if any(_to_bool(row.get("not_for_production")) for row in role_bindings + relations):
        return True
    return any("not for production" in str(warning).lower() for warning in (manifest.get("quality") or {}).get("warnings") or [])


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
