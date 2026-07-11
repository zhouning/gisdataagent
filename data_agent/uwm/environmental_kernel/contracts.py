from __future__ import annotations

from typing import Any, Mapping


ENVIRONMENTAL_STATE_SCHEMA = "uwm.environmental_state.v1"
ENVIRONMENTAL_ACTION_SCHEMA = "uwm.environmental_action.v1"
ENVIRONMENTAL_EVIDENCE_GATE_SCHEMA = "uwm.environmental_evidence_gate.v1"
ENVIRONMENTAL_ROLLOUT_SCHEMA = "uwm.environmental_rollout.v1"

OBSERVED_CALIBRATED = "observed_calibrated"
OBSERVED_CONTEXT = "observed_context"
BOUNDED_PROXY = "bounded_proxy"
UNAVAILABLE = "unavailable"

SUPPORT_LEVELS = {
    OBSERVED_CALIBRATED,
    OBSERVED_CONTEXT,
    BOUNDED_PROXY,
    UNAVAILABLE,
}

STATE_FIELDS = (
    "pm25_ugm3",
    "temperature_c",
    "vegetation_fraction",
    "built_fraction",
    "population_exposure_proxy",
)


def validate_environmental_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema") != ENVIRONMENTAL_STATE_SCHEMA:
        errors.append(f"schema must be {ENVIRONMENTAL_STATE_SCHEMA}")
    if not payload.get("evidence_bundle_id"):
        errors.append("evidence_bundle_id is required")
    nodes = payload.get("spatial_nodes")
    if not isinstance(nodes, list):
        errors.append("spatial_nodes must be a list")
        nodes = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            errors.append(f"spatial_nodes[{index}] must be an object")
            continue
        if not node.get("node_id"):
            errors.append(f"spatial_nodes[{index}].node_id is required")
        for field in STATE_FIELDS:
            support_key = f"{field.removesuffix('_ugm3').removesuffix('_c')}_support_level"
            if field == "population_exposure_proxy":
                support_key = "exposure_support_level"
            if field not in node and support_key not in node:
                continue
            support = node.get(support_key)
            if support not in SUPPORT_LEVELS:
                errors.append(f"spatial_nodes[{index}].{support_key} is invalid")
            if support == UNAVAILABLE and node.get(field) is not None:
                errors.append(f"spatial_nodes[{index}].{field} must be null when unavailable")
    return {"valid": not errors, "errors": errors}


def validate_environmental_action(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema") != ENVIRONMENTAL_ACTION_SCHEMA:
        errors.append(f"schema must be {ENVIRONMENTAL_ACTION_SCHEMA}")
    for key in ("action_type", "state_snapshot_digest", "actor"):
        if not payload.get(key):
            errors.append(f"{key} is required")
    if payload.get("causal_effect_estimate") is not False:
        errors.append("causal_effect_estimate must remain false")
    return {"valid": not errors, "errors": errors}


def validate_rollout_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema") != ENVIRONMENTAL_ROLLOUT_SCHEMA:
        errors.append(f"schema must be {ENVIRONMENTAL_ROLLOUT_SCHEMA}")
    for key in (
        "baseline_trajectory",
        "intervention_trajectory",
        "mechanism_contributions",
        "evidence_gate",
    ):
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("not_a_causal_effect_estimate") is not True:
        errors.append("not_a_causal_effect_estimate must be true")
    return {"valid": not errors, "errors": errors}
