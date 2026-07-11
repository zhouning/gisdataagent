from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .contracts import ENVIRONMENTAL_ACTION_SCHEMA, validate_environmental_action


ALLOWED_ACTION_TYPES = {
    "no_intervention",
    "increase_tree_canopy_proxy",
    "increase_green_surface_proxy",
    "convert_declared_parcel_to_green_proxy",
}


def bind_environmental_action(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    actor: str,
    s2_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action_type = str(request.get("action_type") or "")
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ValueError("unsupported_environmental_action")
    if request.get("state_snapshot_digest") != state.get("snapshot_digest"):
        raise ValueError("stale_state_snapshot")

    target_node_ids = sorted({str(value) for value in request.get("target_node_ids") or []})
    nodes = {str(row.get("node_id")): row for row in state.get("spatial_nodes") or []}
    if any(node_id not in nodes for node_id in target_node_ids):
        raise ValueError("unknown_target_node")

    if action_type == "no_intervention":
        declared_area_m2 = 0.0
        vegetation_fraction_delta = 0.0
    else:
        declared_area_m2 = _float(request.get("declared_area_m2"), "declared_area_m2_required")
        vegetation_fraction_delta = _float(
            request.get("vegetation_fraction_delta"),
            "vegetation_fraction_delta_required",
        )
        if not 0.0 <= vegetation_fraction_delta <= 1.0:
            raise ValueError("vegetation_fraction_delta_out_of_range")
        target_area = sum(float(nodes[node_id].get("geometry_area_m2") or 0.0) for node_id in target_node_ids)
        if declared_area_m2 < 0.0 or declared_area_m2 > target_area:
            raise ValueError("declared_area_exceeds_target_geometry")

    s2_digest = None
    if action_type == "convert_declared_parcel_to_green_proxy":
        if not s2_artifact:
            raise ValueError("s2_transition_artifact_required")
        if s2_artifact.get("state_snapshot_digest") != state.get("snapshot_digest"):
            raise ValueError("s2_transition_state_mismatch")
        if s2_artifact.get("transition_status") != "allowed":
            raise ValueError("s2_transition_not_allowed")
        s2_digest = s2_artifact.get("artifact_digest")
        if not s2_digest:
            raise ValueError("s2_transition_artifact_digest_required")

    action = {
        "schema": ENVIRONMENTAL_ACTION_SCHEMA,
        "action_type": action_type,
        "target_node_ids": target_node_ids,
        "declared_area_m2": declared_area_m2,
        "vegetation_fraction_delta": vegetation_fraction_delta,
        "implementation_stage": request.get("implementation_stage") or "scenario",
        "rationale": request.get("rationale") or "",
        "state_snapshot_digest": state.get("snapshot_digest"),
        "geometry_version": state.get("geography_version"),
        "evidence_bundle_id": state.get("evidence_bundle_id"),
        "actor": str(actor),
        "client_actor_accepted": False,
        "causal_effect_estimate": False,
        "s2_transition_artifact_digest": s2_digest,
    }
    validation = validate_environmental_action(action)
    if not validation["valid"]:
        raise ValueError(";".join(validation["errors"]))
    action["action_digest"] = _digest(action)
    return deepcopy(action)


def _float(value: Any, message: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(message) from None


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = deepcopy(dict(payload))
    canonical.pop("action_digest", None)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
