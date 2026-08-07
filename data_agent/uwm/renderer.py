"""UWM renderer: MMFE state input to canonical urban observation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    UWM_OBSERVATION_SCHEMA,
    build_native_geometry_contract,
)
from .mmfe_state_input import validate_uwm_state_input


def build_canonical_observation_from_state_input(
    state_input: dict[str, Any],
    *,
    manifest_audit: dict[str, Any] | None = None,
    observation_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build `UwmCanonicalObservation.v1` from `mmfe.uwm_state_input.v1`.

    This is an observation function, not a simulator. It preserves source roles,
    graph summaries, synthetic/public-proxy flags and claim boundaries so later
    simulator/planner stages cannot silently upgrade weak evidence.
    """

    created_at = timestamp or datetime.now(timezone.utc).isoformat()
    validation = validate_uwm_state_input(state_input)
    if not validation["valid"]:
        return _invalid_observation(validation["errors"], observation_id, created_at, manifest_audit)

    role_bindings = [row for row in state_input.get("object_role_registry", []) if isinstance(row, dict)]
    manifest_audit = manifest_audit or {}
    object_layers = [_role_to_layer(row) for row in role_bindings if _is_object_layer(row)]
    raster_features = [_role_to_feature(row) for row in role_bindings if not _is_object_layer(row)]
    native_geometry_contract = build_native_geometry_contract(
        [*object_layers, *raster_features]
    )
    claim_level = _derive_claim_boundary(
        role_bindings,
        manifest_audit,
        native_geometry_contract,
    )
    observation = {
        "schema": UWM_OBSERVATION_SCHEMA,
        "observation_id": observation_id or f"uwm-observation-{created_at}",
        "created_at": created_at,
        "spatial_units": [_build_spatial_unit(state_input.get("urban_spatial_unit") or {})],
        "object_layers": object_layers,
        "raster_features": raster_features,
        "graph_edges": _build_graph_edges(state_input.get("semantic_relation_registry") or []),
        "native_geometry_contract": native_geometry_contract,
        "temporal_index": {
            "source_created_at": state_input.get("created_at"),
            "observation_created_at": created_at,
        },
        "quality_flags": _build_quality_flags(state_input, manifest_audit),
        "synthetic_flags": _build_synthetic_flags(role_bindings),
        "provenance": {
            "state_input_schema": state_input.get("schema"),
            "state_input_version": state_input.get("version"),
            "source_product_id": (state_input.get("source_product") or {}).get("product_id"),
            "manifest_path": manifest_audit.get("path"),
            "manifest_valid": manifest_audit.get("valid"),
        },
        "claim_boundary": {
            "max_claim_level": claim_level,
            "reason": _claim_reason(
                claim_level,
                role_bindings,
                manifest_audit,
                native_geometry_contract,
            ),
        },
        "renderer_trace": [
            {
                "step": "load_mmfe_uwm_state_input",
                "source_product_id": (state_input.get("source_product") or {}).get("product_id"),
            },
            {
                "step": "derive_canonical_observation",
                "object_layer_count": len(object_layers),
                "raster_feature_count": len(raster_features),
                "native_geometry_complete_role_count": native_geometry_contract[
                    "complete_role_count"
                ],
            },
        ],
    }
    return observation


def _invalid_observation(
    errors: list[str],
    observation_id: str | None,
    created_at: str,
    manifest_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": UWM_OBSERVATION_SCHEMA,
        "observation_id": observation_id or f"uwm-invalid-observation-{created_at}",
        "created_at": created_at,
        "spatial_units": [],
        "object_layers": [],
        "raster_features": [],
        "graph_edges": [],
        "native_geometry_contract": build_native_geometry_contract([]),
        "temporal_index": {"observation_created_at": created_at},
        "quality_flags": [{"level": "error", "message": error} for error in errors],
        "synthetic_flags": [],
        "provenance": {
            "manifest_path": (manifest_audit or {}).get("path"),
            "manifest_valid": (manifest_audit or {}).get("valid"),
        },
        "claim_boundary": {
            "max_claim_level": "not_for_claim",
            "reason": "invalid mmfe.uwm_state_input.v1 payload",
        },
        "renderer_trace": [{"step": "validate_mmfe_uwm_state_input", "valid": False}],
    }


def _build_spatial_unit(spatial_unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": spatial_unit.get("unit_id") or "uwm_spatial_unit",
        "unit_type": spatial_unit.get("unit_type"),
        "crs": spatial_unit.get("crs"),
        "spatial_extent": spatial_unit.get("spatial_extent"),
    }


def _is_object_layer(row: dict[str, Any]) -> bool:
    object_type = str(row.get("object_type") or "").lower()
    uwm_role = str(row.get("uwm_role") or "").lower()
    if object_type in {"raster", "grid", "field"}:
        return False
    if "exposure" in uwm_role or uwm_role in {"heat_exposure", "air_pollution_exposure"}:
        return False
    return True


def _role_to_layer(row: dict[str, Any]) -> dict[str, Any]:
    layer = {
        "role": row.get("role"),
        "uwm_role": row.get("uwm_role"),
        "object_type": row.get("object_type"),
        "source_dataset_id": row.get("source_dataset_id"),
    }
    layer.update(_native_geometry_metadata(row))
    return layer


def _role_to_feature(row: dict[str, Any]) -> dict[str, Any]:
    feature = {
        "feature_id": row.get("role"),
        "role": row.get("role"),
        "uwm_role": row.get("uwm_role"),
        "source_dataset_id": row.get("source_dataset_id"),
    }
    feature.update(_native_geometry_metadata(row))
    return feature


def _native_geometry_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(row[key])
        for key in (
            "aggregation_semantics",
            "calibration",
            "geometry_type",
            "observation_semantics",
            "spatial_support",
            "temporal_support",
            "uncertainty",
        )
        if key in row
    }


def _build_graph_edges(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "edge_type": row.get("semantic_relation_type"),
            "uwm_usage": row.get("uwm_usage"),
            "relation_count": row.get("relation_count", 1),
        }
        for row in relations
        if isinstance(row, dict)
    ]


def _build_quality_flags(state_input: dict[str, Any], manifest_audit: dict[str, Any]) -> list[dict[str, str]]:
    flags = [{"level": "info", "message": "canonical observation derived from MMFE UWM state input"}]
    for warning in state_input.get("warnings") or []:
        flags.append({"level": "warning", "message": str(warning)})
    if manifest_audit and manifest_audit.get("valid") is False:
        flags.append({"level": "error", "message": "data foundation manifest audit failed"})
    return flags


def _build_synthetic_flags(role_bindings: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags = []
    seen: set[tuple[str, str]] = set()
    for row in role_bindings:
        status = str(row.get("synthetic_status") or "unknown")
        if status in {"real", "unknown", ""}:
            continue
        dataset_id = str(row.get("source_dataset_id") or row.get("role"))
        key = (dataset_id, status)
        if key in seen:
            continue
        seen.add(key)
        flags.append({"dataset_id": dataset_id, "status": status})
    return flags


def _derive_claim_boundary(
    role_bindings: list[dict[str, Any]],
    manifest_audit: dict[str, Any],
    native_geometry_contract: dict[str, Any],
) -> str:
    if manifest_audit and manifest_audit.get("valid") is False:
        return "not_for_claim"
    statuses = {str(row.get("synthetic_status") or "") for row in role_bindings}
    if statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
        return "exploratory_only"
    if native_geometry_contract.get("uncalibrated_inferred_roles"):
        return "exploratory_only"
    if statuses.intersection({"public_proxy", "restricted_expected"}):
        return "bounded_support"
    return "bounded_support"


def _claim_reason(
    claim_level: str,
    role_bindings: list[dict[str, Any]],
    manifest_audit: dict[str, Any],
    native_geometry_contract: dict[str, Any],
) -> str:
    if claim_level == "not_for_claim":
        return "invalid or failed data foundation audit"
    statuses = {str(row.get("synthetic_status") or "") for row in role_bindings}
    if statuses.intersection({"synthetic", "semi_synthetic", "smoke_only"}):
        return "synthetic or semi-synthetic sources are present"
    if native_geometry_contract.get("uncalibrated_inferred_roles"):
        return "inferred spatial values are present without calibrated uncertainty"
    return "observation can support bounded UWM research claims after evidence gates"
