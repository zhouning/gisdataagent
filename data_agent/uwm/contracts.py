"""Core payload validators for Urban World Model runtime boundaries."""

from __future__ import annotations

from typing import Any


UWM_OBSERVATION_SCHEMA = "uwm.canonical_observation.v1"
UWM_ROLLOUT_TRACE_SCHEMA = "uwm.rollout_trace.v1"
UWM_PLAN_PACKAGE_SCHEMA = "uwm.plan_package.v1"
UWM_NATIVE_GEOMETRY_SCHEMA = "uwm.native_geometry_support.v1"


_GEOMETRY_TYPES = {
    "network",
    "point",
    "polygon",
    "raster",
    "volume",
}
_SPATIAL_SUPPORT_TYPES = {
    "admin_unit",
    "catchment",
    "grid_cell",
    "network_edge",
    "network_node",
    "parcel",
    "sensor_footprint",
    "spatial_object",
    "unknown",
}
_OBSERVATION_SEMANTICS = {
    "derived",
    "downscaled",
    "interpolated",
    "observed",
    "proxy",
    "simulated",
    "unknown",
}
_AGGREGATION_SEMANTICS = {
    "category",
    "count",
    "density",
    "flow",
    "mean",
    "none",
    "rate",
    "stock",
    "total",
    "unknown",
}
_INFERRED_OBSERVATION_SEMANTICS = {
    "downscaled",
    "interpolated",
    "simulated",
}
_CALIBRATION_STATUSES = {
    "calibrated",
    "failed",
    "not_applicable",
    "uncalibrated",
}
_NATIVE_GEOMETRY_KEYS = {
    "aggregation_semantics",
    "calibration",
    "geometry_type",
    "observation_semantics",
    "spatial_support",
    "temporal_support",
    "uncertainty",
}


_EVIDENCE_GRADES = {
    "core_support",
    "bounded_support",
    "fragile",
    "exploratory_only",
    "not_for_claim",
}


def validate_uwm_observation(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the renderer-to-simulator observation contract."""

    errors = _base_errors(payload, UWM_OBSERVATION_SCHEMA)
    errors.extend(
        _require_keys(
            payload,
            [
                "spatial_units",
                "object_layers",
                "raster_features",
                "graph_edges",
                "temporal_index",
                "quality_flags",
                "synthetic_flags",
                "provenance",
                "claim_boundary",
                "renderer_trace",
            ],
        )
    )
    errors.extend(_require_list(payload, "spatial_units"))
    errors.extend(_require_list(payload, "object_layers"))
    errors.extend(_require_list(payload, "raster_features"))
    errors.extend(_require_list(payload, "graph_edges"))
    errors.extend(_require_list(payload, "quality_flags"))
    errors.extend(_require_list(payload, "synthetic_flags"))
    errors.extend(_require_list(payload, "renderer_trace"))
    errors.extend(_require_dict(payload, "temporal_index"))
    errors.extend(_require_dict(payload, "provenance"))
    errors.extend(_require_claim_boundary(payload))
    for collection_name in ("object_layers", "raster_features"):
        rows = payload.get(collection_name)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            errors.extend(
                validate_native_geometry_metadata(
                    row,
                    prefix=f"{collection_name}[{index}]",
                )
            )
    if "native_geometry_contract" in payload:
        errors.extend(_validate_native_geometry_contract(payload["native_geometry_contract"]))
    return _validation(errors)


def validate_native_geometry_metadata(
    payload: Any,
    *,
    prefix: str = "native_geometry",
) -> list[str]:
    """Validate optional native-geometry metadata once a producer declares it."""

    if not isinstance(payload, dict):
        return [f"{prefix} must be an object"]
    if not _NATIVE_GEOMETRY_KEYS.intersection(payload):
        return []

    errors: list[str] = []
    geometry_type = payload.get("geometry_type")
    if geometry_type not in _GEOMETRY_TYPES:
        errors.append(f"{prefix}.geometry_type must be one of {sorted(_GEOMETRY_TYPES)}")

    spatial_support = payload.get("spatial_support")
    if not isinstance(spatial_support, dict):
        errors.append(f"{prefix}.spatial_support must be an object")
    else:
        support_type = spatial_support.get("support_type")
        if support_type not in _SPATIAL_SUPPORT_TYPES:
            errors.append(
                f"{prefix}.spatial_support.support_type must be one of "
                f"{sorted(_SPATIAL_SUPPORT_TYPES)}"
            )

    observation_semantics = payload.get("observation_semantics")
    if observation_semantics not in _OBSERVATION_SEMANTICS:
        errors.append(
            f"{prefix}.observation_semantics must be one of "
            f"{sorted(_OBSERVATION_SEMANTICS)}"
        )

    aggregation_semantics = payload.get("aggregation_semantics")
    if aggregation_semantics is not None and aggregation_semantics not in _AGGREGATION_SEMANTICS:
        errors.append(
            f"{prefix}.aggregation_semantics must be one of "
            f"{sorted(_AGGREGATION_SEMANTICS)}"
        )

    temporal_support = payload.get("temporal_support")
    if temporal_support is not None and not isinstance(temporal_support, dict):
        errors.append(f"{prefix}.temporal_support must be an object")

    uncertainty = payload.get("uncertainty")
    if uncertainty is not None and not isinstance(uncertainty, dict):
        errors.append(f"{prefix}.uncertainty must be an object")

    calibration = payload.get("calibration")
    if calibration is not None and not isinstance(calibration, dict):
        errors.append(f"{prefix}.calibration must be an object")
    elif isinstance(calibration, dict):
        errors.extend(_validate_calibration(calibration, prefix=f"{prefix}.calibration"))

    if observation_semantics in _INFERRED_OBSERVATION_SEMANTICS:
        if not isinstance(uncertainty, dict) or not uncertainty:
            errors.append(
                f"{prefix}.uncertainty is required for {observation_semantics} observations"
            )
        if not isinstance(calibration, dict) or not calibration.get("status"):
            errors.append(
                f"{prefix}.calibration.status is required for "
                f"{observation_semantics} observations"
            )
    return errors


def build_native_geometry_contract(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize native-geometry completeness without invalidating legacy v1 roles."""

    declared_roles: list[str] = []
    complete_roles: list[str] = []
    incomplete_roles: list[str] = []
    inferred_roles: list[str] = []
    uncalibrated_inferred_roles: list[str] = []
    geometry_types: set[str] = set()
    observation_semantics: set[str] = set()

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or row.get("feature_id") or f"role-{index}")
        if not _NATIVE_GEOMETRY_KEYS.intersection(row):
            incomplete_roles.append(role)
            continue
        declared_roles.append(role)
        metadata_errors = validate_native_geometry_metadata(row, prefix=role)
        if metadata_errors:
            incomplete_roles.append(role)
        else:
            complete_roles.append(role)
        if row.get("geometry_type") in _GEOMETRY_TYPES:
            geometry_types.add(str(row["geometry_type"]))
        semantics = row.get("observation_semantics")
        if semantics in _OBSERVATION_SEMANTICS:
            observation_semantics.add(str(semantics))
        if semantics in _INFERRED_OBSERVATION_SEMANTICS:
            inferred_roles.append(role)
            calibration = row.get("calibration") or {}
            if calibration.get("status") != "calibrated":
                uncalibrated_inferred_roles.append(role)

    role_count = len([row for row in rows if isinstance(row, dict)])
    return {
        "schema": UWM_NATIVE_GEOMETRY_SCHEMA,
        "role_count": role_count,
        "declared_role_count": len(declared_roles),
        "complete_role_count": len(complete_roles),
        "legacy_or_incomplete_roles": incomplete_roles,
        "geometry_types": sorted(geometry_types),
        "observation_semantics": sorted(observation_semantics),
        "inferred_role_count": len(inferred_roles),
        "uncalibrated_inferred_roles": uncalibrated_inferred_roles,
        "metadata_complete": role_count == len(complete_roles),
        "claim_boundary": {
            "max_claim_level": (
                "exploratory_only" if uncalibrated_inferred_roles else "bounded_support"
            ),
            "inferred_values_are_observations": False,
        },
    }


def validate_uwm_rollout_trace(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate simulator output before any planner can consume it."""

    errors = _base_errors(payload, UWM_ROLLOUT_TRACE_SCHEMA)
    errors.extend(
        _require_keys(
            payload,
            [
                "initial_state_ref",
                "action_sequence",
                "scenario",
                "backend",
                "future_state_delta",
                "heat_risk_delta",
                "air_pollution_exposure_delta",
                "service_accessibility_delta",
                "equity_delta",
                "livability_delta",
                "uncertainty_interval",
                "evidence_grade",
                "claim_boundary",
                "simulator_trace",
            ],
        )
    )
    errors.extend(_require_non_empty_list(payload, "action_sequence"))
    errors.extend(_require_non_empty_list(payload, "simulator_trace"))
    errors.extend(_require_dict(payload, "scenario"))
    errors.extend(_require_dict(payload, "future_state_delta"))
    errors.extend(_require_dict(payload, "uncertainty_interval"))
    errors.extend(_require_claim_boundary(payload))
    errors.extend(_require_evidence_grade(payload))
    return _validation(errors)


def validate_uwm_plan_package(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate planner output and enforce simulator-trace dependency."""

    errors = _base_errors(payload, UWM_PLAN_PACKAGE_SCHEMA)
    errors.extend(
        _require_keys(
            payload,
            [
                "planning_goal",
                "recommended_actions",
                "rejected_actions",
                "rollout_traces",
                "expected_benefits",
                "equity_effects",
                "risk_flags",
                "evidence_grade",
                "data_gaps",
                "human_review_required",
                "claim_boundary",
                "planner_trace",
            ],
        )
    )
    errors.extend(_require_non_empty_list(payload, "recommended_actions"))
    errors.extend(_require_list(payload, "rejected_actions"))
    errors.extend(_require_non_empty_list(payload, "rollout_traces"))
    errors.extend(_require_dict(payload, "expected_benefits"))
    errors.extend(_require_dict(payload, "equity_effects"))
    errors.extend(_require_list(payload, "risk_flags"))
    errors.extend(_require_list(payload, "data_gaps"))
    errors.extend(_require_non_empty_list(payload, "planner_trace"))
    errors.extend(_require_claim_boundary(payload))
    errors.extend(_require_evidence_grade(payload))
    if "human_review_required" in payload and not isinstance(payload["human_review_required"], bool):
        errors.append("human_review_required must be boolean")
    return _validation(errors)


def _base_errors(payload: Any, schema: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]
    if payload.get("schema") != schema:
        return [f"schema must be {schema}"]
    return []


def _validation(errors: list[str]) -> dict[str, Any]:
    return {"valid": not errors, "errors": errors}


def _validate_calibration(payload: dict[str, Any], *, prefix: str) -> list[str]:
    errors: list[str] = []
    status = payload.get("status")
    if status not in _CALIBRATION_STATUSES:
        errors.append(f"{prefix}.status must be one of {sorted(_CALIBRATION_STATUSES)}")
        return errors
    if status != "calibrated":
        return errors

    if not str(payload.get("method") or "").strip():
        errors.append(f"{prefix}.method is required when status is calibrated")
    for key in ("confidence_level", "empirical_coverage"):
        value = payload.get(key)
        if not _is_probability(value):
            errors.append(f"{prefix}.{key} must be a number between 0 and 1")
    for key in ("calibration_count", "holdout_count"):
        value = payload.get(key)
        if not _is_positive_int(value):
            errors.append(f"{prefix}.{key} must be a positive integer")
    return errors


def _validate_native_geometry_contract(payload: Any) -> list[str]:
    prefix = "native_geometry_contract"
    if not isinstance(payload, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    if payload.get("schema") != UWM_NATIVE_GEOMETRY_SCHEMA:
        errors.append(f"{prefix}.schema must be {UWM_NATIVE_GEOMETRY_SCHEMA}")
    for key in (
        "role_count",
        "declared_role_count",
        "complete_role_count",
        "inferred_role_count",
    ):
        if not _is_non_negative_int(payload.get(key)):
            errors.append(f"{prefix}.{key} must be a non-negative integer")
    for key in (
        "legacy_or_incomplete_roles",
        "geometry_types",
        "observation_semantics",
        "uncalibrated_inferred_roles",
    ):
        if not isinstance(payload.get(key), list):
            errors.append(f"{prefix}.{key} must be a list")
    if not isinstance(payload.get("metadata_complete"), bool):
        errors.append(f"{prefix}.metadata_complete must be boolean")
    claim_boundary = payload.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        errors.append(f"{prefix}.claim_boundary must be an object")
    elif claim_boundary.get("inferred_values_are_observations") is not False:
        errors.append(
            f"{prefix}.claim_boundary.inferred_values_are_observations must be false"
        )
    return errors


def _is_probability(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _require_keys(payload: dict[str, Any], keys: list[str]) -> list[str]:
    return [f"{key} is required" for key in keys if key not in payload]


def _require_list(payload: dict[str, Any], key: str) -> list[str]:
    if key not in payload:
        return []
    return [] if isinstance(payload[key], list) else [f"{key} must be a list"]


def _require_non_empty_list(payload: dict[str, Any], key: str) -> list[str]:
    if key not in payload:
        return []
    if not isinstance(payload[key], list):
        return [f"{key} must be a list"]
    if not payload[key]:
        return [f"{key} must not be empty"]
    return []


def _require_dict(payload: dict[str, Any], key: str) -> list[str]:
    if key not in payload:
        return []
    return [] if isinstance(payload[key], dict) else [f"{key} must be an object"]


def _require_claim_boundary(payload: dict[str, Any]) -> list[str]:
    if "claim_boundary" not in payload:
        return ["claim_boundary is required"]
    if not isinstance(payload["claim_boundary"], dict):
        return ["claim_boundary must be an object"]
    if not payload["claim_boundary"].get("max_claim_level"):
        return ["claim_boundary.max_claim_level is required"]
    return []


def _require_evidence_grade(payload: dict[str, Any]) -> list[str]:
    grade = payload.get("evidence_grade")
    if grade not in _EVIDENCE_GRADES:
        return [f"evidence_grade must be one of {sorted(_EVIDENCE_GRADES)}"]
    return []
