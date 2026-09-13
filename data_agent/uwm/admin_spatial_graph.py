"""Administrative boundary adjacency graph utilities for UWM."""

from __future__ import annotations

from typing import Any

from shapely.geometry import shape


ADMIN_SPATIAL_ADJACENCY_GRAPH_SCHEMA = "uwm.admin_spatial_adjacency_graph.v1"
ADMIN_BOUNDARY_ADJACENCY_EDGE_TYPE = "admin_boundary_adjacency"


def build_admin_spatial_adjacency_graph(
    *,
    admin_features: list[dict[str, Any]],
    graph_id: str,
    created_at: str,
    source_dataset_id: str = "chongqing_township_admin_units_local",
    source_crs: str = "EPSG:4326",
    boundary_tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Build an auditable administrative boundary adjacency graph.

    The graph is a topology layer over township/street polygons. It is not a
    road network or mobility graph.
    """

    nodes = [
        node
        for index, feature in enumerate(admin_features)
        if (node := _node_from_feature(feature, index, source_crs=source_crs))
    ]
    edges: list[dict[str, Any]] = []
    for left_index, left in enumerate(nodes):
        for right in nodes[left_index + 1 :]:
            edge = _edge_if_adjacent(left, right, boundary_tolerance=boundary_tolerance)
            if edge:
                edges.append(edge)

    degree_by_unit = {node["unit_id"]: 0 for node in nodes}
    for edge in edges:
        degree_by_unit[edge["source"]] += 1
        degree_by_unit[edge["target"]] += 1

    public_nodes = [_public_node(node, degree_by_unit[node["unit_id"]]) for node in nodes]
    return {
        "schema": ADMIN_SPATIAL_ADJACENCY_GRAPH_SCHEMA,
        "version": "0.1",
        "graph_id": graph_id,
        "created_at": created_at,
        "source_dataset_id": source_dataset_id,
        "source_crs": source_crs,
        "nodes": public_nodes,
        "edges": edges,
        "summary": {
            "source_feature_count": len(admin_features),
            "node_count": len(public_nodes),
            "edge_count": len(edges),
            "isolated_node_count": len([unit_id for unit_id, degree in degree_by_unit.items() if degree == 0]),
            "edge_rule": "polygon_boundary_touch_or_shared_boundary_v0",
        },
        "quality_flags": [
            {
                "level": "info",
                "message": "derived from administrative polygon topology; not a transport or mobility graph",
            },
            {
                "level": "warning",
                "message": "EPSG:4326 shared-boundary lengths are angular degrees and used only as topology metadata",
            },
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "Boundary adjacency is derived from local Chongqing township/street polygons; official date and license still gate stronger claims.",
        },
    }


def _node_from_feature(feature: dict[str, Any], index: int, *, source_crs: str) -> dict[str, Any]:
    geometry = feature.get("geometry")
    if not geometry:
        return {}
    geom = shape(geometry)
    if geom.is_empty:
        return {}
    props = feature.get("properties") or {}
    unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
    centroid = geom.representative_point()
    minx, miny, maxx, maxy = geom.bounds
    return {
        "unit_id": unit_id,
        "county": str(props.get("county") or ""),
        "township": str(props.get("township") or ""),
        "geometry_type": geom.geom_type,
        "centroid": {"lon": round(float(centroid.x), 9), "lat": round(float(centroid.y), 9)},
        "bbox": [round(float(minx), 9), round(float(miny), 9), round(float(maxx), 9), round(float(maxy), 9)],
        "source_crs": source_crs,
        "_geometry": geom,
    }


def _edge_if_adjacent(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    boundary_tolerance: float,
) -> dict[str, Any]:
    if not _bbox_may_touch(left["bbox"], right["bbox"], boundary_tolerance):
        return {}
    left_geom = left["_geometry"]
    right_geom = right["_geometry"]
    boundary_intersection = left_geom.boundary.intersection(right_geom.boundary)
    shared_boundary_length = float(boundary_intersection.length)
    point_touch = not boundary_intersection.is_empty and shared_boundary_length <= boundary_tolerance
    if shared_boundary_length <= boundary_tolerance and not point_touch:
        if float(left_geom.distance(right_geom)) > boundary_tolerance:
            return {}
    relation = "shared_boundary" if shared_boundary_length > boundary_tolerance else "point_touch"
    return {
        "edge_type": ADMIN_BOUNDARY_ADJACENCY_EDGE_TYPE,
        "source": left["unit_id"],
        "target": right["unit_id"],
        "weight": 1.0 if relation == "shared_boundary" else 0.5,
        "adjacency_relation": relation,
        "shared_boundary_length_degrees": round(shared_boundary_length, 12),
    }


def _bbox_may_touch(left_bbox: list[float], right_bbox: list[float], tolerance: float) -> bool:
    left_minx, left_miny, left_maxx, left_maxy = left_bbox
    right_minx, right_miny, right_maxx, right_maxy = right_bbox
    return not (
        left_maxx < right_minx - tolerance
        or right_maxx < left_minx - tolerance
        or left_maxy < right_miny - tolerance
        or right_maxy < left_miny - tolerance
    )


def _public_node(node: dict[str, Any], degree: int) -> dict[str, Any]:
    return {
        "unit_id": node["unit_id"],
        "county": node["county"],
        "township": node["township"],
        "geometry_type": node["geometry_type"],
        "centroid": node["centroid"],
        "bbox": node["bbox"],
        "degree": degree,
    }


def _fallback_admin_unit_id(props: dict[str, Any], index: int) -> str:
    county = str(props.get("county") or "")
    township = str(props.get("township") or "")
    return f"{county}|{township}|{index}"
