"""Constrained direct state transitions for parcel land-use actions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .state_graph import build_state_graph


UNSUPPORTED_EFFECT_FIELDS = sorted(
    [
        "population",
        "land_price",
        "facility_capacity",
        "traffic_flow",
        "construction_status",
        "livability_score",
        "approval_probability",
    ]
)


def apply_direct_transition(
    *,
    graph: dict[str, Any],
    action: dict[str, Any],
    action_validation: dict[str, Any],
) -> dict[str, Any]:
    """Advance the target parcel to t1 without inventing downstream effects."""

    if action_validation.get("valid") is not True:
        raise ValueError("validated_action_required")
    if action.get("snapshot_digest") != graph.get("snapshot_digest"):
        raise ValueError("action_snapshot_digest_mismatch")

    nodes = deepcopy(graph.get("nodes") or [])
    edges = deepcopy(graph.get("edges") or [])
    parcel_id = str(action.get("parcel_id"))
    target = next((node for node in nodes if node.get("node_id") == parcel_id), None)
    if target is None or target.get("node_type") != "parcel":
        raise ValueError("target_parcel_missing")

    previous_effective = target.get("effective_land_use_class") or target.get(
        "current_land_use_class"
    )
    next_effective = str(action.get("to_land_use_class"))
    target["candidate_land_use_class"] = next_effective
    target["effective_land_use_class"] = next_effective
    target["state_time"] = "t1_post_change"
    target["action_trace"] = {
        "action_type": action.get("action_type"),
        "actor_id": action.get("actor_id"),
        "requested_at": action.get("requested_at"),
        "rationale": action.get("rationale"),
        "source_snapshot_digest": graph.get("snapshot_digest"),
        "transition_status": (action_validation.get("transition") or {}).get("status"),
        "approval_claim": False,
    }

    changed_edge_ids: list[str] = []
    for edge in edges:
        if parcel_id not in {edge.get("source_node_id"), edge.get("target_node_id")}:
            continue
        compatibility = edge.get("compatibility_by_land_use")
        if not isinstance(compatibility, dict):
            continue
        previous_status = edge.get("active_compatibility_status")
        next_status = compatibility.get(next_effective, "unresolved")
        edge["active_compatibility_status"] = next_status
        edge["compatibility_evaluated_for_land_use"] = next_effective
        if next_status != previous_status:
            changed_edge_ids.append(str(edge.get("edge_id")))

    next_graph = build_state_graph(
        nodes=nodes,
        edges=edges,
        kernel_version=str(graph.get("kernel_version") or ""),
    )
    land_use_changed = previous_effective != next_effective
    changed_fields = ["candidate_land_use_class", "state_time"]
    if land_use_changed:
        changed_fields.append("effective_land_use_class")
    return {
        "state_time": "t1_post_change",
        "source_snapshot_digest": graph.get("snapshot_digest"),
        "state_graph": next_graph,
        "direct_state_delta": {
            "target_parcel_id": parcel_id,
            "from_land_use_class": previous_effective,
            "to_land_use_class": next_effective,
            "land_use_changed": land_use_changed,
            "changed_node_ids": [parcel_id],
            "changed_edge_ids": sorted(changed_edge_ids),
            "changed_fields": sorted(changed_fields),
            "support_level": "observed_state_change",
            "approval_claim": False,
        },
        "unsupported_effect_fields": list(UNSUPPORTED_EFFECT_FIELDS),
        "claim_boundary": {
            "max_claim_level": "bounded_action_conditioned_spatial_scenario"
        },
        "approval_claim": False,
    }
