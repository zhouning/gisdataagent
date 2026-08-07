"""Build UWM state-input artifacts from MMFE semantic products."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    build_native_geometry_contract,
    validate_native_geometry_metadata,
)


MMFE_UWM_STATE_INPUT_SCHEMA = "mmfe.uwm_state_input.v1"
MMFE_UWM_STATE_INPUT_VERSION = "0.1"

UWM_COMPONENTS = [
    "urban_form",
    "heat_exposure",
    "air_pollution_exposure",
    "service_accessibility",
    "mobility_activity",
    "population_vulnerability",
    "planning_constraints",
    "remote_sensing_state",
]


def build_uwm_state_input_from_semantic_product(
    manifest: dict[str, Any],
    semantic_relations: list[dict[str, Any]] | None = None,
    input_contract: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build the first UWM-ready contract from an MMFE semantic product."""

    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")
    contract = input_contract or {}
    relations = [_normalise_relation(row) for row in semantic_relations or [] if isinstance(row, dict)]
    role_bindings = _normalise_role_bindings(contract.get("role_bindings") or [])
    component_roles = _build_component_roles(role_bindings)

    return {
        "schema": MMFE_UWM_STATE_INPUT_SCHEMA,
        "version": MMFE_UWM_STATE_INPUT_VERSION,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "source_product": {
            "product_id": manifest.get("product_id"),
            "product_type": manifest.get("product_type"),
            "product_version": manifest.get("version"),
            "quality_score": (manifest.get("quality") or {}).get("score"),
        },
        "urban_spatial_unit": dict(contract.get("spatial_unit") or {}),
        "object_role_registry": role_bindings,
        "native_geometry_contract": build_native_geometry_contract(role_bindings),
        "state_components": _build_state_components(component_roles),
        "graph_summary": _build_graph_summary(relations),
        "semantic_relation_registry": relations,
        "production_policy": {
            "contains_synthetic_sources": _contains_synthetic_sources(role_bindings),
            "authoritative_data_required_for_production": True,
            "policy": (
                "UWM state input may use public proxies and synthetic placeholders for research "
                "progress, but production claims require authoritative urban data and evidence gates."
            ),
        },
        "warnings": _build_warnings(role_bindings, contract),
    }


def validate_uwm_state_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the MMFE-to-UWM state-input contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != MMFE_UWM_STATE_INPUT_SCHEMA:
        errors.append(f"schema must be {MMFE_UWM_STATE_INPUT_SCHEMA}")
    if not (payload.get("source_product") or {}).get("product_id"):
        errors.append("source_product.product_id is required")
    spatial_unit = payload.get("urban_spatial_unit") or {}
    if not isinstance(spatial_unit, dict):
        errors.append("urban_spatial_unit must be an object")
        spatial_unit = {}
    if not spatial_unit.get("unit_type"):
        errors.append("urban_spatial_unit.unit_type is required")
    role_bindings = payload.get("object_role_registry")
    if not isinstance(role_bindings, list):
        errors.append("object_role_registry must be a list")
    else:
        for index, row in enumerate(role_bindings):
            errors.extend(
                validate_native_geometry_metadata(
                    row,
                    prefix=f"object_role_registry[{index}]",
                )
            )
    if not isinstance(payload.get("state_components"), dict):
        errors.append("state_components must be an object")
    if not isinstance(payload.get("graph_summary"), dict):
        errors.append("graph_summary must be an object")
    production_policy = payload.get("production_policy") or {}
    if not isinstance(production_policy, dict):
        errors.append("production_policy must be an object")
    elif production_policy.get("authoritative_data_required_for_production") is not True:
        errors.append("production_policy.authoritative_data_required_for_production must be true")
    return {"valid": not errors, "errors": errors}


def _normalise_role_bindings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bindings = []
    for row in rows:
        role = str(row.get("role") or "").strip()
        if not role:
            continue
        binding = {
            "role": role,
            "uwm_role": str(row.get("uwm_role") or "unassigned").strip(),
            "object_type": str(row.get("object_type") or "unknown").strip(),
            "source_dataset_id": str(row.get("source_dataset_id") or "").strip(),
            "synthetic_status": str(row.get("synthetic_status") or "unknown").strip(),
        }
        binding.update(_normalise_native_geometry_metadata(row))
        bindings.append(binding)
    return bindings


def _normalise_native_geometry_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "aggregation_semantics",
        "geometry_type",
        "observation_semantics",
    ):
        if key in row:
            value = row.get(key)
            metadata[key] = str(value).strip() if value is not None else None
    for key in (
        "calibration",
        "spatial_support",
        "temporal_support",
        "uncertainty",
    ):
        if key in row:
            metadata[key] = deepcopy(row.get(key))
    return metadata


def _build_component_roles(role_bindings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in role_bindings:
        grouped[str(binding.get("uwm_role") or "unassigned")].append(binding)
    return grouped


def _build_state_components(component_roles: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for component in UWM_COMPONENTS:
        roles = component_roles.get(component, [])
        components[component] = {
            "role_count": len(roles),
            "roles": [role["role"] for role in roles],
            "source_dataset_ids": sorted(
                {role["source_dataset_id"] for role in roles if role.get("source_dataset_id")}
            ),
        }
    for component, roles in component_roles.items():
        if component in components:
            continue
        components[component] = {
            "role_count": len(roles),
            "roles": [role["role"] for role in roles],
            "source_dataset_ids": sorted(
                {role["source_dataset_id"] for role in roles if role.get("source_dataset_id")}
            ),
        }
    return components


def _normalise_relation(row: dict[str, Any]) -> dict[str, Any]:
    relation_type = str(row.get("semantic_relation_type") or row.get("relation_type") or "unknown").strip()
    relation_count = _safe_int(row.get("relation_count"), default=1)
    return {
        "semantic_relation_type": relation_type,
        "uwm_usage": str(row.get("uwm_usage") or "unassigned").strip(),
        "relation_count": relation_count,
    }


def _build_graph_summary(relations: list[dict[str, Any]]) -> dict[str, Any]:
    relation_type_counts = Counter()
    usage_counts = Counter()
    total = 0
    for row in relations:
        count = _safe_int(row.get("relation_count"), default=1)
        relation_type_counts[str(row.get("semantic_relation_type") or "unknown")] += count
        usage_counts[str(row.get("uwm_usage") or "unassigned")] += count
        total += count
    return {
        "total_relation_count": total,
        "relation_type_count": len(relation_type_counts),
        "relation_type_distribution": dict(relation_type_counts),
        "usage_distribution": dict(usage_counts),
    }


def _contains_synthetic_sources(role_bindings: list[dict[str, Any]]) -> bool:
    synthetic_markers = {"fitted_proxy", "synthetic", "semi_synthetic", "smoke_only"}
    return any(str(row.get("synthetic_status")) in synthetic_markers for row in role_bindings)


def _build_warnings(role_bindings: list[dict[str, Any]], contract: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not role_bindings:
        warnings.append("no role bindings were provided")
    if not (contract.get("spatial_unit") or {}).get("unit_type"):
        warnings.append("urban spatial unit is missing")
    return warnings


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
