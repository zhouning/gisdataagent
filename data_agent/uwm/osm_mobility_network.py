"""OSM highway network public proxy for UWM mobility state."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


OSM_MOBILITY_NETWORK_PROXY_SCHEMA = "uwm.osm_mobility_network_proxy.v1"
OSM_MOBILITY_NETWORK_DATASET_ID = "osm_mobility_network_bbox_public_proxy"


def build_osm_mobility_network_proxy(
    *,
    raw_payload: dict[str, Any],
    requested_bbox: list[float],
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize Overpass highway elements into a bounded mobility graph proxy."""

    elements = raw_payload.get("elements") or []
    nodes = _coordinate_nodes(elements)
    highway_ways = [
        element
        for element in elements
        if element.get("type") == "way" and (element.get("tags") or {}).get("highway")
    ]
    edges, usable_way_ids = _build_edges(highway_ways, nodes)
    highway_distribution = Counter(str((way.get("tags") or {}).get("highway") or "unknown") for way in highway_ways)
    graph_summary = _graph_summary(nodes, edges)
    return {
        "schema": OSM_MOBILITY_NETWORK_PROXY_SCHEMA,
        "source": "OpenStreetMap Overpass API",
        "source_dataset_ids": [OSM_MOBILITY_NETWORK_DATASET_ID],
        "osm_base_timestamp": (raw_payload.get("osm3s") or {}).get("timestamp_osm_base"),
        "fetched_at": fetched_at,
        "requested_bbox": requested_bbox,
        "record_counts": {
            "elements": len(elements),
            "coordinate_nodes": len(nodes),
            "highway_ways": len(highway_ways),
            "usable_highway_ways": len(usable_way_ids),
            "graph_edges": len(edges),
        },
        "highway_distribution": dict(sorted(highway_distribution.items())),
        "graph_summary": graph_summary,
        "sample_edges": edges[:50],
        "mmfe_target_roles": ["mobility_graph", "mobility_activity", "simulator_context", "baseline_context"],
        "synthetic_flags": [{"dataset_id": OSM_MOBILITY_NETWORK_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "OSM bbox highway topology supports bounded mobility context only.",
        },
        "limitations": [
            "overpass_bbox_extract_not_full_municipality",
            "osm_road_tag_completeness_varies_spatially",
            "not_a_travel_time_or_od_network",
            "no_speed_calibration_or_congestion_observations",
            "odbl_attribution_required",
        ],
        "empirical_superiority_claim": False,
    }


def write_osm_mobility_network_snapshot(
    *,
    output_dir: str | Path,
    raw_payload: dict[str, Any],
    requested_bbox: list[float],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw OSM highway payload, normalized proxy and manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "osm_mobility_network_overpass_raw.json", raw_payload)
    proxy = build_osm_mobility_network_proxy(
        raw_payload=raw_payload,
        requested_bbox=requested_bbox,
        fetched_at=fetched_at,
    )
    _write_json(output_path / "osm_mobility_network_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "osm_mobility_network_bbox_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "fetched_at": fetched_at,
        "requested_bbox": requested_bbox,
        "files": {
            "raw": "osm_mobility_network_overpass_raw.json",
            "normalized_proxy": "osm_mobility_network_proxy.json",
        },
        "record_counts": proxy["record_counts"],
        "graph_summary": proxy["graph_summary"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_osm_mobility_network_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert OSM mobility graph proxy into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != OSM_MOBILITY_NETWORK_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {OSM_MOBILITY_NETWORK_PROXY_SCHEMA}")
    osm_time = str(proxy.get("osm_base_timestamp") or "unknown_osm_time")
    graph_summary = proxy.get("graph_summary") or {}
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-osm-mobility-network-{osm_time}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.55},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "osm_way_connects_coordinate_nodes",
                "uwm_usage": "mobility_graph",
                "relation_count": int(graph_summary.get("edge_count") or 0),
            },
            {
                "semantic_relation_type": "osm_highway_way_available",
                "uwm_usage": "mobility_activity",
                "relation_count": (proxy.get("record_counts") or {}).get("highway_ways", 0),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "osm_bbox_highway_network_extract",
                "crs": "EPSG:4326",
                "spatial_extent": proxy.get("requested_bbox"),
                "temporal_extent": osm_time,
            },
            "role_bindings": [
                {
                    "role": "osm_highway_bbox_topology",
                    "uwm_role": "mobility_activity",
                    "object_type": "graph",
                    "source_dataset_id": OSM_MOBILITY_NETWORK_DATASET_ID,
                    "synthetic_status": "public_proxy",
                }
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "osm_base_timestamp": proxy.get("osm_base_timestamp"),
        "record_counts": proxy.get("record_counts"),
        "graph_summary": proxy.get("graph_summary"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "OSM highway bbox topology is not a calibrated travel-time, OD, congestion, or policy-outcome dataset"
    )
    return payload


def _coordinate_nodes(elements: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    nodes: dict[int, dict[str, float]] = {}
    for element in elements:
        if element.get("type") != "node":
            continue
        node_id = _int(element.get("id"))
        lat = _float(element.get("lat"))
        lon = _float(element.get("lon"))
        if node_id is None or lat is None or lon is None:
            continue
        nodes[node_id] = {"latitude": lat, "longitude": lon}
    return nodes


def _build_edges(
    highway_ways: list[dict[str, Any]],
    nodes: dict[int, dict[str, float]],
) -> tuple[list[dict[str, Any]], set[int]]:
    edges: list[dict[str, Any]] = []
    usable_way_ids: set[int] = set()
    seen: set[tuple[int, int, int]] = set()
    for way in highway_ways:
        way_id = _int(way.get("id"))
        if way_id is None:
            continue
        refs = [_int(ref) for ref in way.get("nodes") or []]
        refs = [ref for ref in refs if ref is not None]
        tags = way.get("tags") or {}
        for source, target in zip(refs, refs[1:]):
            if source not in nodes or target not in nodes:
                continue
            key = (way_id, min(source, target), max(source, target))
            if key in seen:
                continue
            seen.add(key)
            usable_way_ids.add(way_id)
            edges.append(
                {
                    "way_id": way_id,
                    "source_osm_node": source,
                    "target_osm_node": target,
                    "highway": str(tags.get("highway") or "unknown"),
                    "name": str(tags.get("name") or ""),
                    "length_degrees_proxy": round(_edge_length_degrees(nodes[source], nodes[target]), 9),
                }
            )
    return edges, usable_way_ids


def _graph_summary(nodes: dict[int, dict[str, float]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    active_nodes = sorted(
        {
            int(edge["source_osm_node"])
            for edge in edges
        }
        | {
            int(edge["target_osm_node"])
            for edge in edges
        }
    )
    component_count = _connected_component_count(active_nodes, edges)
    edge_count = len(edges)
    node_count = len(active_nodes)
    return {
        "node_count": node_count,
        "coordinate_node_count": len(nodes),
        "edge_count": edge_count,
        "connected_component_count": component_count,
        "average_degree_proxy": round((2 * edge_count / node_count), 6) if node_count else 0.0,
    }


def _connected_component_count(active_nodes: list[int], edges: list[dict[str, Any]]) -> int:
    if not active_nodes:
        return 0
    parent = {node: node for node in active_nodes}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for edge in edges:
        union(int(edge["source_osm_node"]), int(edge["target_osm_node"]))
    return len({find(node) for node in active_nodes})


def _edge_length_degrees(source: dict[str, float], target: dict[str, float]) -> float:
    return (
        (source["latitude"] - target["latitude"]) ** 2
        + (source["longitude"] - target["longitude"]) ** 2
    ) ** 0.5


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
