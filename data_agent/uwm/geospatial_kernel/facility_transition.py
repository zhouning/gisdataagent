"""Direct state transitions for typed facility scenario actions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform

from .state_graph import build_state_graph


FACILITY_RELATION_DISTANCE_M = 300.0


def apply_facility_transition(
    *,
    graph: dict[str, Any],
    action: dict[str, Any],
    action_validation: dict[str, Any],
) -> dict[str, Any]:
    """Write a facility add/remove action into a new immutable graph branch."""

    if action_validation.get("valid") is not True:
        raise ValueError("validated_action_required")
    if action.get("snapshot_digest") != graph.get("snapshot_digest"):
        raise ValueError("action_snapshot_digest_mismatch")

    nodes = deepcopy(graph.get("nodes") or [])
    edges = deepcopy(graph.get("edges") or [])
    action_type = str(action.get("action_type") or "")
    facility_id = str(action.get("facility_id") or "")
    parcel_id = str(action.get("parcel_id") or "")
    planning_area_id = str(action.get("planning_area_id") or "")

    if action_type == "no_facility_change":
        return _result(
            graph=graph,
            nodes=nodes,
            edges=edges,
            action=action,
            added_node_ids=[],
            removed_node_ids=[],
            changed_edge_ids=[],
            relation_deltas=[],
        )

    changed_edge_ids: list[str] = []
    relation_deltas: list[dict[str, Any]] = []
    added_node_ids: list[str] = []
    removed_node_ids: list[str] = []
    if action_type == "add_facility":
        facility_node = {
            "node_id": facility_id,
            "node_type": "facility",
            "state_time": "t1_post_change",
            "planning_area_id": planning_area_id,
            "canonical_class": action.get("facility_class"),
            "mapping_status": "scenario_typed",
            "distance_crs": action.get("distance_crs"),
            "display_geometry_wgs84": deepcopy(
                action.get("placement_geometry_wgs84")
            ),
            "evidence_refs": list(action.get("evidence_refs") or []),
            "observability": "action_conditioned_scenario",
            "action_trace": _action_trace(action, graph),
        }
        nodes.append(facility_node)
        added_node_ids.append(facility_id)
        new_edges = _facility_edges(
            nodes=nodes,
            facility_node=facility_node,
            distance_crs=str(action.get("distance_crs") or ""),
        )
        edges.extend(new_edges)
        changed_edge_ids.extend(str(edge["edge_id"]) for edge in new_edges)
        relation_deltas.extend(
            {
                "change_type": "added",
                "edge_id": edge["edge_id"],
                "parcel_id": edge["source_node_id"],
                "facility_id": facility_id,
                "distance_m": edge["distance_m"],
            }
            for edge in new_edges
        )
    elif action_type == "remove_facility":
        removed_edges = [
            edge
            for edge in edges
            if facility_id
            in {str(edge.get("source_node_id")), str(edge.get("target_node_id"))}
        ]
        nodes = [node for node in nodes if str(node.get("node_id")) != facility_id]
        edges = [edge for edge in edges if edge not in removed_edges]
        removed_node_ids.append(facility_id)
        changed_edge_ids.extend(str(edge.get("edge_id")) for edge in removed_edges)
        relation_deltas.extend(
            {
                "change_type": "removed",
                "edge_id": edge.get("edge_id"),
                "parcel_id": edge.get("source_node_id"),
                "facility_id": facility_id,
                "distance_m": edge.get("distance_m"),
            }
            for edge in removed_edges
            if edge.get("relation_type") == "parcel_near_facility"
        )
    else:
        raise ValueError("unsupported_facility_action_type")

    return _result(
        graph=graph,
        nodes=nodes,
        edges=edges,
        action=action,
        added_node_ids=added_node_ids,
        removed_node_ids=removed_node_ids,
        changed_edge_ids=changed_edge_ids,
        relation_deltas=relation_deltas,
    )


def _result(
    *,
    graph: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    action: dict[str, Any],
    added_node_ids: list[str],
    removed_node_ids: list[str],
    changed_edge_ids: list[str],
    relation_deltas: list[dict[str, Any]],
) -> dict[str, Any]:
    next_graph = build_state_graph(
        nodes=nodes,
        edges=edges,
        kernel_version=str(graph.get("kernel_version") or ""),
    )
    changed_node_ids = sorted(added_node_ids + removed_node_ids)
    return {
        "state_time": "t1_post_change",
        "source_snapshot_digest": graph.get("snapshot_digest"),
        "state_graph": next_graph,
        "direct_state_delta": {
            "action_type": action.get("action_type"),
            "target_parcel_id": action.get("parcel_id"),
            "facility_id": action.get("facility_id"),
            "facility_class": action.get("facility_class"),
            "planning_area_id": action.get("planning_area_id"),
            "facility_changed": bool(changed_node_ids),
            "added_node_ids": sorted(added_node_ids),
            "removed_node_ids": sorted(removed_node_ids),
            "changed_node_ids": changed_node_ids,
            "changed_edge_ids": sorted(changed_edge_ids),
            "relation_deltas": sorted(
                relation_deltas,
                key=lambda row: (
                    str(row.get("change_type")),
                    str(row.get("edge_id")),
                ),
            ),
            "changed_fields": ["facility_nodes", "parcel_near_facility_relations"],
            "support_level": "bounded_proxy",
            "state_semantics": "action_conditioned_scenario_state",
            "observed_outcome": False,
            "approval_claim": False,
        },
        "unsupported_effect_fields": [
            "facility_capacity",
            "population",
            "network_accessibility",
            "approval_probability",
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_action_conditioned_spatial_scenario"
        },
        "approval_claim": False,
    }


def _facility_edges(
    *,
    nodes: list[dict[str, Any]],
    facility_node: dict[str, Any],
    distance_crs: str,
) -> list[dict[str, Any]]:
    transformer = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_user_input(distance_crs), always_xy=True
    )
    facility_geometry = transform(
        transformer.transform, shape(facility_node["display_geometry_wgs84"])
    )
    edges = []
    for parcel in nodes:
        if parcel.get("node_type") != "parcel":
            continue
        if parcel.get("planning_area_id") != facility_node.get("planning_area_id"):
            continue
        geometry = parcel.get("display_geometry_wgs84")
        if not isinstance(geometry, dict):
            continue
        parcel_geometry = transform(transformer.transform, shape(geometry))
        distance = float(parcel_geometry.distance(facility_geometry))
        if distance > FACILITY_RELATION_DISTANCE_M:
            continue
        edge_id = _stable_id(
            "edge",
            parcel.get("node_id"),
            facility_node.get("node_id"),
            "parcel_near_facility",
        )
        edges.append(
            {
                "edge_id": edge_id,
                "source_node_id": parcel.get("node_id"),
                "target_node_id": facility_node.get("node_id"),
                "relation_type": "parcel_near_facility",
                "evidence_refs": [
                    f"geometry:scenario_projected_distance:{facility_node.get('node_id')}"
                ],
                "support_level": "bounded_proxy",
                "distance_m": round(distance, 6),
                "active_compatibility_status": "unresolved",
            }
        )
    return sorted(edges, key=lambda row: str(row["edge_id"]))


def _action_trace(action: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_type": action.get("action_type"),
        "actor_id": action.get("actor_id"),
        "requested_at": action.get("requested_at"),
        "rationale": action.get("rationale"),
        "source_snapshot_digest": graph.get("snapshot_digest"),
        "permission_binding": action.get("permission_binding"),
        "approval_claim": False,
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:20]}"
