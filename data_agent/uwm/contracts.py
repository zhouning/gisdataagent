"""Core payload validators for Urban World Model runtime boundaries."""

from __future__ import annotations

from typing import Any


UWM_OBSERVATION_SCHEMA = "uwm.canonical_observation.v1"
UWM_ROLLOUT_TRACE_SCHEMA = "uwm.rollout_trace.v1"
UWM_PLAN_PACKAGE_SCHEMA = "uwm.plan_package.v1"


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
    return _validation(errors)


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
