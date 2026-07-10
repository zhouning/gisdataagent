"""Full-admin mobility graph artifacts for UWM livability modeling."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .full_admin_service_accessibility_surface import (
    validate_full_admin_service_accessibility_surface,
)
from .geographic_similarity_kernel import validate_uwm_geographic_similarity_kernel


UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA = "uwm.full_admin_mobility_graph.v1"
MOBILITY_SIMILARITY_EDGE_TYPE = "mobility_accessibility_similarity"
_SUPPORTED_CLAIM = "full_admin_mobility_graph_travel_time_similarity_projection_ready"


def build_full_admin_mobility_graph(
    *,
    graph_id: str,
    created_at: str,
    full_admin_service_accessibility_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    unicom_latent_mobility_graph: dict[str, Any] | None = None,
    osm_mobility_network: dict[str, Any] | None = None,
    osm_admin_mobility_crosswalk: dict[str, Any] | None = None,
    experiment_scope: str = "full_admin_graph",
) -> dict[str, Any]:
    """Project the full-admin service surface into a mobility-oriented graph.

    The graph is intentionally explicit about its limits: it uses full-admin
    road/service travel-time proxies and similarity edges, not observed OD
    geometry or policy outcomes.
    """

    surface_validation = validate_full_admin_service_accessibility_surface(
        full_admin_service_accessibility_surface
    )
    kernel_validation = validate_uwm_geographic_similarity_kernel(
        geographic_similarity_kernel
    )
    rows = list(full_admin_service_accessibility_surface.get("admin_service_rows") or [])
    nodes = [_mobility_node_from_row(row) for row in rows if row.get("admin_unit_id")]
    nodes_by_id = {node["unit_id"]: node for node in nodes}

    mobility_edges = _project_similarity_edges(
        geographic_similarity_kernel,
        node_ids=set(nodes_by_id),
        nodes_by_id=nodes_by_id,
    )
    mobility_context = {
        "service_surface": _service_surface_context(
            full_admin_service_accessibility_surface
        ),
        "geographic_similarity_kernel": _kernel_context(geographic_similarity_kernel),
        "unicom_latent_mobility_graph": _unicom_context(
            unicom_latent_mobility_graph or {}
        ),
        "osm_mobility_network": _osm_mobility_network_context(
            osm_mobility_network or {}
        ),
        "osm_admin_mobility_crosswalk": _osm_admin_mobility_crosswalk_context(
            osm_admin_mobility_crosswalk or {}
        ),
    }
    summary = _summary(nodes, mobility_edges, mobility_context)
    negative_controls = _negative_controls(geographic_similarity_kernel)
    ready = (
        surface_validation.get("valid") is True
        and kernel_validation.get("valid") is True
        and _int(summary.get("node_count")) == _int(
            (full_admin_service_accessibility_surface.get("admin_unit_count"))
        )
        and _int(summary.get("edge_count")) == _int(
            (geographic_similarity_kernel.get("summary") or {}).get(
                "similarity_edge_count"
            )
        )
        and _int(summary.get("edge_count")) > 0
        and negative_controls["rotated_target_similarity_control_passed"] is True
        and (full_admin_service_accessibility_surface.get("claim_boundary") or {}).get(
            "max_claim_level"
        )
        in {"bounded_support", "core_support"}
    )
    supported_claim = (
        _SUPPORTED_CLAIM
        if ready
        else "no_full_admin_mobility_graph_claim_supported"
    )
    return {
        "schema": UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA,
        "graph_id": graph_id,
        "created_at": created_at,
        "experiment_scope": experiment_scope,
        "source_schemas": {
            "full_admin_service_accessibility_surface": (
                full_admin_service_accessibility_surface.get("schema")
            ),
            "geographic_similarity_kernel": geographic_similarity_kernel.get("schema"),
            "unicom_latent_mobility_graph": unicom_latent_mobility_graph.get("schema")
            if isinstance(unicom_latent_mobility_graph, dict)
            else None,
            "osm_mobility_network": osm_mobility_network.get("schema")
            if isinstance(osm_mobility_network, dict)
            else None,
            "osm_admin_mobility_crosswalk": osm_admin_mobility_crosswalk.get("schema")
            if isinstance(osm_admin_mobility_crosswalk, dict)
            else None,
        },
        "source_dataset_ids": [
            *[
                str(dataset_id)
                for dataset_id in (
                    full_admin_service_accessibility_surface.get("source_dataset_ids")
                    or []
                )
            ],
            *[
                str(dataset_id)
                for dataset_id in (geographic_similarity_kernel.get("source_dataset_ids") or [])
            ],
            *(
                [str(unicom_latent_mobility_graph.get("dataset_id"))]
                if isinstance(unicom_latent_mobility_graph, dict)
                and unicom_latent_mobility_graph.get("dataset_id")
                else []
            ),
            *(
                [str(osm_mobility_network.get("source_dataset_ids")[0])]
                if isinstance(osm_mobility_network, dict)
                and (osm_mobility_network.get("source_dataset_ids") or [])
                else []
            ),
        ],
        "source_feature_counts": dict(
            full_admin_service_accessibility_surface.get("source_feature_counts") or {}
        ),
        "node_count": len(nodes),
        "edge_count": len(mobility_edges),
        "mobility_nodes": nodes,
        "mobility_edges": mobility_edges,
        "mobility_context": mobility_context,
        "summary": summary,
        "negative_controls": negative_controls,
        "full_admin_mobility_graph_ready": ready,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "The mobility graph projects full-admin service and road travel-time proxies "
                "into a mobility-context graph with similarity edges, not observed OD flow or policy outcomes."
            ),
        },
        "limitations": [
            "mobility_graph_uses_travel_time_and_road_context_proxies_not_observed_trip_times",
            "mobility_graph_is_similarity_projection_not_true_od_geometry",
            "unicom_grid_geometry_dictionary_missing",
            "osm_mobility_network_is_bbox_proxy_not_citywide_observed_mobility_flow",
            "not_observed_policy_outcome",
        ],
        "mmfe_target_roles": [
            "mobility_graph",
            "mobility_activity",
            "simulator_context",
            "planner_targeting",
            "mmfe_alignment",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_full_admin_mobility_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the full-admin mobility graph contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA:
        errors.append(f"schema must be {UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA}")
    for key in [
        "graph_id",
        "created_at",
        "experiment_scope",
        "node_count",
        "edge_count",
        "mobility_nodes",
        "mobility_edges",
        "mobility_context",
        "summary",
        "negative_controls",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    nodes = payload.get("mobility_nodes") or []
    edges = payload.get("mobility_edges") or []
    if _int(payload.get("node_count")) != len(nodes):
        errors.append("node_count must equal mobility_nodes length")
    if _int(payload.get("edge_count")) != len(edges):
        errors.append("edge_count must equal mobility_edges length")
    if _int((payload.get("summary") or {}).get("node_count")) != len(nodes):
        errors.append("summary.node_count must equal mobility_nodes length")
    if _int((payload.get("summary") or {}).get("edge_count")) != len(edges):
        errors.append("summary.edge_count must equal mobility_edges length")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    if payload.get("full_admin_mobility_graph_ready") is True:
        if (payload.get("claim_boundary") or {}).get("max_claim_level") != "bounded_support":
            errors.append("ready graph requires bounded_support claim level")
        controls = payload.get("negative_controls") or {}
        if controls.get("rotated_target_similarity_control_passed") is not True:
            errors.append("ready graph must pass rotated target similarity control")
    return {"valid": not errors, "errors": errors}


def write_full_admin_mobility_graph_snapshot(
    *,
    output_dir: str | Path,
    graph_id: str,
    created_at: str,
    full_admin_service_accessibility_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    unicom_latent_mobility_graph: dict[str, Any] | None = None,
    osm_mobility_network: dict[str, Any] | None = None,
    osm_admin_mobility_crosswalk: dict[str, Any] | None = None,
    experiment_scope: str = "full_admin_graph",
) -> dict[str, Any]:
    """Persist the mobility graph artifact and a compact snapshot manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    graph = build_full_admin_mobility_graph(
        graph_id=graph_id,
        created_at=created_at,
        full_admin_service_accessibility_surface=full_admin_service_accessibility_surface,
        geographic_similarity_kernel=geographic_similarity_kernel,
        unicom_latent_mobility_graph=unicom_latent_mobility_graph,
        osm_mobility_network=osm_mobility_network,
        osm_admin_mobility_crosswalk=osm_admin_mobility_crosswalk,
        experiment_scope=experiment_scope,
    )
    _write_json(output_path / "full_admin_mobility_graph.json", graph)
    _write_rows_csv(output_path / "full_admin_mobility_graph_nodes.csv", graph["mobility_nodes"])
    _write_rows_csv(output_path / "full_admin_mobility_graph_edges.csv", graph["mobility_edges"])
    manifest = {
        "schema": "uwm.full_admin_mobility_graph_snapshot_manifest.v1",
        "dataset_id": graph_id,
        "created_at": created_at,
        "experiment_scope": experiment_scope,
        "files": {
            "graph": "full_admin_mobility_graph.json",
            "nodes": "full_admin_mobility_graph_nodes.csv",
            "edges": "full_admin_mobility_graph_edges.csv",
        },
        "record_counts": {
            "node_count": graph["node_count"],
            "edge_count": graph["edge_count"],
        },
        "summary": graph["summary"],
        "claim_boundary": graph["claim_boundary"],
        "limitations": graph["limitations"],
        "supported_claim": graph["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def _mobility_node_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": str(row.get("admin_unit_id") or ""),
        "county": str(row.get("county") or ""),
        "township": str(row.get("township") or ""),
        "service_point_count": _float(row.get("service_point_count")),
        "essential_service_count": _float(row.get("essential_service_count")),
        "service_accessibility_score": _float(row.get("service_accessibility_score")),
        "service_gap_score": _float(row.get("service_gap_score")),
        "nearest_essential_service_distance_m": _float(
            row.get("nearest_essential_service_distance_m")
        ),
        "estimated_nearest_essential_travel_time_min": _float(
            row.get("estimated_nearest_essential_travel_time_min")
        ),
        "road_segment_count": _float(row.get("road_segment_count")),
        "road_length_km": _float(row.get("road_length_km")),
        "mean_road_speed_kmh": _float(row.get("mean_road_speed_kmh")),
        "capacity_norm": _float(row.get("capacity_norm")),
        "essential_norm": _float(row.get("essential_norm")),
        "travel_time_inverse_norm": _float(row.get("travel_time_inverse_norm")),
    }


def _project_similarity_edges(
    geographic_similarity_kernel: dict[str, Any],
    *,
    node_ids: set[str],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for edge in geographic_similarity_kernel.get("similarity_edges") or []:
        source = str(edge.get("source") or edge.get("source_unit_id") or "")
        target = str(edge.get("target") or edge.get("target_unit_id") or "")
        if source not in node_ids or target not in node_ids:
            continue
        source_node = nodes_by_id.get(source) or {}
        target_node = nodes_by_id.get(target) or {}
        edges.append(
            {
                "edge_type": MOBILITY_SIMILARITY_EDGE_TYPE,
                "source": source,
                "target": target,
                "source_unit_id": source,
                "target_unit_id": target,
                "rank": _int(edge.get("rank")),
                "weight": _float(edge.get("weight")),
                "configuration_similarity": _float(
                    edge.get("configuration_similarity")
                ),
                "standardized_feature_distance": _float(
                    edge.get("standardized_feature_distance")
                ),
                "boundary_adjacent": bool(edge.get("boundary_adjacent")),
                "same_county": bool(edge.get("same_county")),
                "travel_time_difference_min": round(
                    abs(
                        _float(
                            source_node.get("estimated_nearest_essential_travel_time_min")
                        )
                        - _float(
                            target_node.get("estimated_nearest_essential_travel_time_min")
                        )
                    ),
                    6,
                ),
                "road_segment_difference": abs(
                    _int(source_node.get("road_segment_count"))
                    - _int(target_node.get("road_segment_count"))
                ),
                "road_length_difference_km": round(
                    abs(_float(source_node.get("road_length_km")) - _float(target_node.get("road_length_km"))),
                    6,
                ),
                "road_speed_difference_kmh": round(
                    abs(
                        _float(source_node.get("mean_road_speed_kmh"))
                        - _float(target_node.get("mean_road_speed_kmh"))
                    ),
                    6,
                ),
            }
        )
    return edges


def _summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    mobility_context: dict[str, Any],
) -> dict[str, Any]:
    travel_times = [
        _float(node.get("estimated_nearest_essential_travel_time_min"))
        for node in nodes
    ]
    road_segments = [_float(node.get("road_segment_count")) for node in nodes]
    road_lengths = [_float(node.get("road_length_km")) for node in nodes]
    speeds = [_float(node.get("mean_road_speed_kmh")) for node in nodes]
    service_accessibility = [
        _float(node.get("service_accessibility_score")) for node in nodes
    ]
    edge_similarities = [_float(edge.get("configuration_similarity")) for edge in edges]
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "mobility_similarity_edge_count": len(edges),
        "travel_time_min_mean": round(mean(travel_times), 6) if travel_times else 0.0,
        "travel_time_min_min": round(min(travel_times), 6) if travel_times else 0.0,
        "travel_time_min_max": round(max(travel_times), 6) if travel_times else 0.0,
        "road_segment_count_sum": _int(sum(road_segments)),
        "road_length_km_sum": round(sum(road_lengths), 6),
        "mean_road_speed_kmh_mean": round(mean(speeds), 6) if speeds else 0.0,
        "service_accessibility_score_mean": (
            round(mean(service_accessibility), 6) if service_accessibility else 0.0
        ),
        "mean_configuration_similarity": (
            round(mean(edge_similarities), 9) if edge_similarities else 0.0
        ),
        "mobility_activity_context": {
            "unicom_directed_edge_count": _int(
                ((mobility_context.get("unicom_latent_mobility_graph") or {}).get("directed_edge_count"))
            ),
            "unicom_total_expanded_population": _float(
                ((mobility_context.get("unicom_latent_mobility_graph") or {}).get("total_expanded_population"))
            ),
            "osm_highway_edge_count": _int(
                ((mobility_context.get("osm_mobility_network") or {}).get("edge_count"))
            ),
            "osm_crosswalk_assigned_road_segment_count": _int(
                ((mobility_context.get("osm_admin_mobility_crosswalk") or {}).get("assigned_road_segment_count"))
            ),
        },
    }


def _negative_controls(geographic_similarity_kernel: dict[str, Any]) -> dict[str, Any]:
    controls = geographic_similarity_kernel.get("negative_controls") or {}
    return {
        "rotated_target_similarity_control_passed": bool(
            controls.get("rotated_target_similarity_control_passed")
        ),
        "real_minus_rotated_similarity": _float(
            controls.get("real_minus_rotated_similarity")
        ),
    }


def _service_surface_context(
    service_surface: dict[str, Any],
) -> dict[str, Any]:
    counts = service_surface.get("source_feature_counts") or {}
    coverage = service_surface.get("coverage") or {}
    return {
        "schema": service_surface.get("schema"),
        "admin_unit_count": _int(service_surface.get("admin_unit_count")),
        "poi_point_count": _int(counts.get("poi_points")),
        "road_count": _int(counts.get("roads")),
        "service_missing_admin_count": _int(
            coverage.get("service_missing_admin_count")
        ),
        "admin_units_with_road_context": _int(
            coverage.get("admin_units_with_road_context")
        ),
        "claim_level": (service_surface.get("claim_boundary") or {}).get(
            "max_claim_level"
        ),
    }


def _kernel_context(kernel: dict[str, Any]) -> dict[str, Any]:
    summary = kernel.get("summary") or {}
    features = kernel.get("configuration_features") or {}
    return {
        "schema": kernel.get("schema"),
        "kernel_id": kernel.get("kernel_id"),
        "panel_unit_count": _int(summary.get("panel_unit_count")),
        "similarity_edge_count": _int(summary.get("similarity_edge_count")),
        "non_adjacent_similarity_edge_count": _int(
            summary.get("non_adjacent_similarity_edge_count")
        ),
        "uses_coordinates_as_similarity_features": bool(
            features.get("uses_coordinates_as_similarity_features")
        ),
        "claim_level": (kernel.get("claim_boundary") or {}).get("max_claim_level"),
    }


def _unicom_context(mobility_graph: dict[str, Any]) -> dict[str, Any]:
    summary = mobility_graph.get("summary") or {}
    records = mobility_graph.get("record_counts") or {}
    return {
        "source_artifact_exists": bool(mobility_graph),
        "schema": mobility_graph.get("schema"),
        "dataset_id": mobility_graph.get("dataset_id"),
        "raw_rows": _int(records.get("raw_rows")),
        "directed_edge_count": _int(records.get("directed_edges")),
        "node_count": _int(records.get("nodes")),
        "total_expanded_population": _float(summary.get("total_expanded_population")),
        "self_loop_expanded_population": _float(
            summary.get("self_loop_expanded_population")
        ),
        "unknown_or_external_work_grid_expanded_population": _float(
            summary.get("unknown_or_external_work_grid_expanded_population")
        ),
        "claim_level": (mobility_graph.get("claim_boundary") or {}).get(
            "max_claim_level"
        ),
        "limitations": list(mobility_graph.get("limitations") or []),
    }


def _osm_mobility_network_context(network: dict[str, Any]) -> dict[str, Any]:
    summary = network.get("graph_summary") or {}
    record_counts = network.get("record_counts") or {}
    return {
        "source_artifact_exists": bool(network),
        "schema": network.get("schema"),
        "dataset_id": (network.get("source_dataset_ids") or [None])[0],
        "node_count": _int(summary.get("node_count")),
        "edge_count": _int(summary.get("edge_count")),
        "coordinate_node_count": _int(summary.get("coordinate_node_count")),
        "usable_highway_way_count": _int(record_counts.get("usable_highway_ways")),
        "claim_level": (network.get("claim_boundary") or {}).get("max_claim_level"),
        "limitations": list(network.get("limitations") or []),
    }


def _osm_admin_mobility_crosswalk_context(crosswalk: dict[str, Any]) -> dict[str, Any]:
    evaluation = (crosswalk.get("holdout_evaluation") or {}).get(
        "service_accessibility_leave_one_admin_out"
    ) or {}
    return {
        "source_artifact_exists": bool(crosswalk),
        "schema": crosswalk.get("schema"),
        "crosswalk_id": crosswalk.get("crosswalk_id"),
        "admin_unit_count": _int(crosswalk.get("admin_unit_count")),
        "assigned_road_segment_count": _int(
            crosswalk.get("assigned_road_segment_count")
        ),
        "unassigned_road_segment_count": _int(
            crosswalk.get("unassigned_road_segment_count")
        ),
        "mobility_crosswalk_mae": _float(evaluation.get("mobility_crosswalk_mae")),
        "best_traditional_static_mae": _float(
            evaluation.get("best_traditional_static_mae")
        ),
        "claim_level": (crosswalk.get("claim_boundary") or {}).get("max_claim_level"),
        "limitations": list(crosswalk.get("limitations") or []),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return round(float(value), 9)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default
