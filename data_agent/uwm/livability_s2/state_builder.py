"""Build the Fulu parcel-centred cross-scale state graph."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from shapely.geometry import shape

from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph


def build_fulu_s2_state_graph(
    inputs: Mapping[str, Any], *, kernel_version: str
) -> dict[str, Any]:
    """Convert validated Fulu inputs to the generic heterogeneous graph."""

    if not inputs.get("ready"):
        return {
            "schema": "uwm.livability_s2.fulu_state_graph.v1",
            "ready": False,
            "state_graph": None,
            "blockers": list(inputs.get("blockers") or ["fulu_inputs_not_ready"]),
            "build_report": {"parcel_count": 0, "node_count": 0, "edge_count": 0},
        }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    parcels = list(inputs.get("parcels") or [])
    resources = list(inputs.get("planning_resources") or [])
    facilities = list(inputs.get("current_facilities") or [])
    areas = list(inputs.get("planning_areas") or [])
    admin_id = "admin_context_fulu"

    for parcel in parcels:
        geometry = shape(parcel["metric_geometry"])
        nodes.append(
            {
                "node_id": parcel["parcel_id"],
                "node_type": "parcel",
                "state_time": "t0_current",
                "current_land_use_class": parcel["current_land_use_class"],
                "planned_land_use_class": parcel["planned_land_use_class"],
                "candidate_land_use_class": None,
                "source_land_use_code": parcel["source_land_use_code"],
                "effective_land_use_class": parcel["current_land_use_class"],
                "planning_area_id": parcel["planning_area_id"],
                "area_m2": parcel.get("area_m2"),
                "perimeter_m": round(float(geometry.length), 6),
                "metric_geometry": parcel["metric_geometry"],
                "display_geometry_wgs84": parcel.get("display_geometry_wgs84"),
                "evidence_refs": list(parcel["evidence_refs"]),
                "observability": "observed",
            }
        )
    for resource in resources:
        nodes.append(
            {
                "node_id": resource["resource_id"],
                "node_type": "planning_resource",
                "state_time": "t0_current",
                "planning_area_id": resource.get("planning_area_id"),
                "source_layer": resource.get("source_layer"),
                "resource_domain": resource.get("resource_domain"),
                "mapping_status": "unmapped"
                if resource.get("resource_domain") == "unresolved"
                else "mapped",
                "metric_geometry": resource.get("metric_geometry"),
                "display_geometry_wgs84": resource.get("display_geometry_wgs84"),
                "evidence_refs": [f"source_manifest:{resource.get('source_manifest_ref')}"],
                "observability": "observed",
            }
        )
    for facility in facilities:
        nodes.append(
            {
                "node_id": facility["facility_id"],
                "node_type": "facility",
                "state_time": "t0_current",
                "planning_area_id": facility.get("planning_area_id"),
                "mapping_status": facility.get("mapping_status") or "unmapped",
                "metric_geometry": facility.get("metric_geometry"),
                "display_geometry_wgs84": facility.get("display_geometry_wgs84"),
                "evidence_refs": [
                    f"facility_product:{(inputs.get('facility_inventory') or {}).get('product_id')}"
                ],
                "observability": "observed",
            }
        )
    for area in areas:
        village_id = _village_id(str(area.get("planning_area_id")))
        nodes.append(
            {
                "node_id": village_id,
                "node_type": "village_context",
                "state_time": "t0_current",
                "planning_area_id": area.get("planning_area_id"),
                "metric_geometry": area.get("metric_geometry"),
                "display_geometry_wgs84": area.get("display_geometry_wgs84"),
                "evidence_refs": [f"source_manifest:{area.get('source_manifest_ref')}"],
                "observability": "derived",
            }
        )
    nodes.append(
        {
            "node_id": admin_id,
            "node_type": "admin_context",
            "state_time": "t0_current",
            "evidence_refs": ["scope:fulu_heping_and_banzhu"],
            "observability": "derived",
        }
    )

    for parcel in parcels:
        parcel_geometry = shape(parcel["metric_geometry"])
        village_id = _village_id(str(parcel["planning_area_id"]))
        edges.append(
            _edge(
                parcel["parcel_id"],
                village_id,
                "parcel_within_village",
                "geometry:planning_area_membership",
            )
        )
        for resource in resources:
            if resource.get("planning_area_id") != parcel.get("planning_area_id"):
                continue
            resource_payload = resource.get("metric_geometry")
            if not resource_payload:
                continue
            intersection = parcel_geometry.intersection(shape(resource_payload))
            if intersection.is_empty or intersection.area <= 0.0:
                continue
            edge = _edge(
                parcel["parcel_id"],
                resource["resource_id"],
                "parcel_contains_resource",
                f"geometry:intersection:{resource['resource_id']}",
            )
            edge["intersection_ratio"] = round(
                float(intersection.area / parcel_geometry.area), 9
            )
            edge["active_compatibility_status"] = "unmapped" if resource.get(
                "resource_domain"
            ) == "unresolved" else "unresolved"
            edges.append(edge)
        for facility in facilities:
            if facility.get("planning_area_id") != parcel.get("planning_area_id"):
                continue
            facility_payload = facility.get("metric_geometry")
            if not facility_payload:
                continue
            distance = float(parcel_geometry.distance(shape(facility_payload)))
            if distance > 300.0:
                continue
            edge = _edge(
                parcel["parcel_id"],
                facility["facility_id"],
                "parcel_near_facility",
                f"geometry:projected_distance:{facility['facility_id']}",
                support_level="bounded_proxy",
            )
            edge["distance_m"] = round(distance, 6)
            edge["active_compatibility_status"] = "unresolved"
            edges.append(edge)

    for index, source in enumerate(parcels):
        source_geometry = shape(source["metric_geometry"])
        for target in parcels[index + 1 :]:
            if target.get("planning_area_id") != source.get("planning_area_id"):
                continue
            target_geometry = shape(target["metric_geometry"])
            shared = source_geometry.boundary.intersection(target_geometry.boundary).length
            if shared > 0.0:
                edges.append(
                    {
                        **_edge(
                            source["parcel_id"],
                            target["parcel_id"],
                            "parcel_adjacent_parcel",
                            "geometry:shared_boundary",
                        ),
                        "shared_boundary_length_m": round(float(shared), 6),
                        "source_perimeter_m": round(float(source_geometry.length), 6),
                        "target_perimeter_m": round(float(target_geometry.length), 6),
                        "compatibility_status": "unresolved",
                    }
                )
            distance = float(source_geometry.distance(target_geometry))
            if shared <= 0.0 and distance <= 300.0:
                edges.append(
                    {
                        **_edge(
                            source["parcel_id"],
                            target["parcel_id"],
                            "parcel_near_parcel",
                            "geometry:projected_distance",
                        ),
                        "distance_m": round(distance, 6),
                    }
                )
    for area in areas:
        village_id = _village_id(str(area.get("planning_area_id")))
        edges.append(
            _edge(
                village_id,
                admin_id,
                "village_within_admin",
                "scope:fulu_admin_context",
                support_level="authoritative_rule",
            )
        )

    graph = build_state_graph(nodes=nodes, edges=edges, kernel_version=kernel_version)
    return {
        "schema": "uwm.livability_s2.fulu_state_graph.v1",
        "ready": True,
        "state_graph": graph,
        "blockers": [],
        "build_report": {
            "parcel_count": len(parcels),
            "planning_resource_count": len(resources),
            "facility_count": len(facilities),
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "distance_crs_by_area": {
                str(area.get("planning_area_id")): area.get("distance_crs") for area in areas
            },
            "synthetic_parcels_created": False,
        },
    }


def _edge(
    source_id: str,
    target_id: str,
    relation_type: str,
    evidence_ref: str,
    *,
    support_level: str = "deterministic_geometry",
) -> dict[str, Any]:
    return {
        "edge_id": _stable_id("edge", source_id, target_id, relation_type),
        "source_node_id": source_id,
        "target_node_id": target_id,
        "relation_type": relation_type,
        "evidence_refs": [evidence_ref],
        "support_level": support_level,
    }


def _village_id(area_id: str) -> str:
    return f"village_context_{area_id}"


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:20]}"
