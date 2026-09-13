"""Deterministic heterogeneous state-graph construction."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .contracts import NODE_TYPES, PARCEL_LAND_USE_FIELDS, RELATION_TYPES, STATE_TIMES, SUPPORT_LEVELS


GEOSPATIAL_STATE_GRAPH_SCHEMA = "uwm.geospatial_kernel.state_graph.v1"


def build_state_graph(
    *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], kernel_version: str
) -> dict[str, Any]:
    """Build a canonical graph without mutating caller-owned records."""

    canonical_nodes = sorted(deepcopy(nodes), key=lambda row: str(row.get("node_id", "")))
    canonical_edges = sorted(deepcopy(edges), key=lambda row: str(row.get("edge_id", "")))
    errors = _structure_errors(canonical_nodes, canonical_edges)
    if errors:
        raise ValueError(errors[0])
    graph = {
        "schema": GEOSPATIAL_STATE_GRAPH_SCHEMA,
        "kernel_version": str(kernel_version),
        "nodes": canonical_nodes,
        "edges": canonical_edges,
    }
    graph["snapshot_digest"] = _snapshot_digest(graph)
    return graph


def validate_state_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate graph structure and its canonical snapshot digest."""

    errors: list[str] = []
    if payload.get("schema") != GEOSPATIAL_STATE_GRAPH_SCHEMA:
        errors.append("schema_mismatch")
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list):
        errors.append("nodes_missing")
        nodes = []
    if not isinstance(edges, list):
        errors.append("edges_missing")
        edges = []
    errors.extend(_structure_errors(nodes, edges))
    if payload.get("snapshot_digest") != _snapshot_digest(payload):
        errors.append("snapshot_digest_mismatch")
    return {"valid": not errors, "errors": errors}


def _structure_errors(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    node_ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if not node_id:
            errors.append("node_id_missing")
            continue
        if node_id in node_ids:
            errors.append(f"duplicate_node_id:{node_id}")
        node_ids.add(node_id)
        if node.get("node_type") not in NODE_TYPES:
            errors.append(f"invalid_node_type:{node_id}")
        if node.get("state_time") not in STATE_TIMES:
            errors.append(f"invalid_state_time:{node_id}")
        if not _evidence_refs(node):
            errors.append(f"node_evidence_refs_missing:{node_id}")
        if node.get("node_type") == "parcel" and any(
            field not in node for field in PARCEL_LAND_USE_FIELDS
        ):
            errors.append(f"parcel_land_use_fields_missing:{node_id}")

    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            errors.append("edge_id_missing")
            continue
        if edge_id in edge_ids:
            errors.append(f"duplicate_edge_id:{edge_id}")
        edge_ids.add(edge_id)
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source not in node_ids:
            errors.append(f"dangling_edge_source:{edge_id}:{source}")
        if target not in node_ids:
            errors.append(f"dangling_edge_target:{edge_id}:{target}")
        if edge.get("relation_type") not in RELATION_TYPES:
            errors.append(f"invalid_relation_type:{edge_id}")
        if edge.get("support_level") not in SUPPORT_LEVELS:
            errors.append(f"invalid_support_level:{edge_id}")
        if not _evidence_refs(edge):
            errors.append(f"edge_evidence_refs_missing:{edge_id}")
    return errors


def _snapshot_digest(payload: dict[str, Any]) -> str:
    content = {
        "schema": payload.get("schema"),
        "kernel_version": payload.get("kernel_version"),
        "nodes": payload.get("nodes") or [],
        "edges": payload.get("edges") or [],
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_refs(row: dict[str, Any]) -> bool:
    values = row.get("evidence_refs")
    return isinstance(values, list) and bool(values) and all(
        isinstance(value, str) and bool(value.strip()) for value in values
    )
