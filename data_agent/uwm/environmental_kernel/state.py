from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .contracts import ENVIRONMENTAL_STATE_SCHEMA, STATE_FIELDS, validate_environmental_state


ALLOWED_RELATIONS = {
    "grid_adjacent_grid",
    "grid_within_admin",
    "admin_adjacent_admin",
    "geographic_similarity",
}


def build_environmental_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    state = deepcopy(dict(payload))
    state["schema"] = ENVIRONMENTAL_STATE_SCHEMA
    nodes = [deepcopy(dict(row)) for row in state.get("spatial_nodes") or []]
    edges = [deepcopy(dict(row)) for row in state.get("spatial_edges") or []]

    node_ids = [str(row.get("node_id") or "") for row in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("duplicate_node_id")
    if any(not node_id for node_id in node_ids):
        raise ValueError("node_id_required")
    known_nodes = set(node_ids)

    for node in nodes:
        for fraction_field in ("vegetation_fraction", "built_fraction"):
            value = node.get(fraction_field)
            if value is not None and not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{fraction_field}_out_of_range")
        node["missing_fields"] = sorted(
            field for field in STATE_FIELDS if node.get(field) is None
        )

    edge_ids = [str(row.get("edge_id") or "") for row in edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("duplicate_edge_id")
    for edge in edges:
        if edge.get("relation_type") not in ALLOWED_RELATIONS:
            raise ValueError("unsupported_relation_type")
        if edge.get("source_node_id") not in known_nodes or edge.get("target_node_id") not in known_nodes:
            raise ValueError("dangling_edge_endpoint")
        if edge.get("relation_type") == "admin_adjacent_admin" and not edge.get("verified_crosswalk_id"):
            raise ValueError("admin_adjacency_requires_verified_crosswalk")
        if edge.get("relation_type") == "geographic_similarity":
            edge["physical_adjacency"] = False

    state["spatial_nodes"] = sorted(nodes, key=lambda row: str(row["node_id"]))
    state["spatial_edges"] = sorted(edges, key=lambda row: str(row["edge_id"]))
    state["source_dataset_ids"] = sorted({str(value) for value in state.get("source_dataset_ids") or []})
    validation = validate_environmental_state(state)
    if not validation["valid"]:
        raise ValueError(";".join(validation["errors"]))
    state["claim_boundary"] = deepcopy(
        state.get("claim_boundary")
        or {
            "max_claim_level": "observed_environmental_state",
            "causal_policy_effect": False,
        }
    )
    state["snapshot_digest"] = _digest(state)
    return state


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = deepcopy(dict(payload))
    canonical.pop("snapshot_digest", None)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
