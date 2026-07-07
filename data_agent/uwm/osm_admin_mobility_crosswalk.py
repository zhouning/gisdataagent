"""OSM road-to-admin mobility crosswalk for UWM."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA = "uwm.osm_admin_mobility_crosswalk.v1"


def build_uwm_osm_admin_mobility_crosswalk(
    *,
    crosswalk_id: str,
    created_at: str,
    admin_livability_rows: list[dict[str, Any]],
    service_accessibility_rows: list[dict[str, Any]],
    ghsl_admin_rows: list[dict[str, Any]],
    admin_spatial_graph: dict[str, Any],
    osm_mobility_network: dict[str, Any],
    osm_overpass_raw: dict[str, Any],
) -> dict[str, Any]:
    """Assign OSM road segments to candidate admin-unit bboxes."""

    candidate_keys = {_county_township_key(row) for row in admin_livability_rows}
    graph_nodes = []
    for node in admin_spatial_graph.get("nodes") or []:
        key = _county_township_key(node)
        if key not in candidate_keys:
            continue
        bbox = node.get("bbox") or []
        if len(bbox) != 4:
            continue
        xmin, ymin, xmax, ymax = [_float(value) for value in bbox]
        area = max(0.0, (xmax - xmin) * (ymax - ymin))
        graph_nodes.append(
            {
                "key": key,
                "unit_id": node.get("unit_id"),
                "bbox": (xmin, ymin, xmax, ymax),
                "bbox_area_degrees2": area,
            }
        )

    stats = {
        node["key"]: {
            "road_segment_count": 0,
            "road_length_degrees_proxy": 0.0,
        }
        for node in graph_nodes
    }
    raw_elements = osm_overpass_raw.get("elements") or []
    coordinates = {
        element.get("id"): (_float(element.get("lon")), _float(element.get("lat")))
        for element in raw_elements
        if element.get("type") == "node"
        and element.get("id") is not None
        and element.get("lon") is not None
        and element.get("lat") is not None
    }
    highway_ways = [
        element
        for element in raw_elements
        if element.get("type") == "way"
        and (element.get("tags") or {}).get("highway") is not None
    ]
    parsed_segment_count = 0
    assigned_segment_count = 0
    for way in highway_ways:
        way_nodes = list(way.get("nodes") or [])
        for source_node, target_node in zip(way_nodes, way_nodes[1:]):
            if source_node not in coordinates or target_node not in coordinates:
                continue
            parsed_segment_count += 1
            lon1, lat1 = coordinates[source_node]
            lon2, lat2 = coordinates[target_node]
            midpoint = ((lon1 + lon2) / 2.0, (lat1 + lat2) / 2.0)
            match = _smallest_bbox_midpoint_match(graph_nodes, midpoint)
            if match is None:
                continue
            length = math.hypot(lon2 - lon1, lat2 - lat1)
            stats[match["key"]]["road_segment_count"] += 1
            stats[match["key"]]["road_length_degrees_proxy"] += length
            assigned_segment_count += 1

    service_by_key = _rows_by_county_township(service_accessibility_rows)
    ghsl_by_key = _rows_by_county_township(ghsl_admin_rows)
    graph_by_key = {node["key"]: node for node in graph_nodes}
    rows = []
    for row in admin_livability_rows:
        key = _county_township_key(row)
        graph_node = graph_by_key[key]
        service = service_by_key[key]
        ghsl = ghsl_by_key[key]
        road = stats[key]
        rows.append(
            {
                "admin_unit_id": row.get("admin_unit_id"),
                "county": row.get("county"),
                "township": row.get("township"),
                "assignment_rule": "segment_midpoint_inside_admin_bbox_choose_smallest_bbox_area",
                "road_segment_count": road["road_segment_count"],
                "road_length_degrees_proxy": round(
                    road["road_length_degrees_proxy"],
                    9,
                ),
                "bbox_area_degrees2": round(graph_node["bbox_area_degrees2"], 12),
                "observed_service_point_count": _float(
                    service.get("service_point_count")
                ),
                "observed_essential_service_count": _float(
                    service.get("essential_service_count")
                ),
                "ghsl_population_proxy_sum": _float(ghsl.get("population_proxy_sum")),
                "ghsl_built_surface_proxy_sum": _float(
                    ghsl.get("built_surface_proxy_sum")
                ),
            }
        )

    evaluation = _service_accessibility_leave_one_admin_out(rows)
    supported_claim = (
        "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines"
        if evaluation["beats_all_traditional_static_baselines"]
        else "no_osm_admin_mobility_crosswalk_service_accessibility_claim_supported"
    )
    return {
        "schema": UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA,
        "crosswalk_id": crosswalk_id,
        "created_at": created_at,
        "admin_unit_count": len(rows),
        "osm_raw_node_count": len(coordinates),
        "osm_highway_way_count": len(highway_ways),
        "osm_graph_edge_count": _int(
            (osm_mobility_network.get("graph_summary") or {}).get("edge_count")
        ),
        "parsed_road_segment_count": parsed_segment_count,
        "assigned_road_segment_count": assigned_segment_count,
        "unassigned_road_segment_count": max(
            0,
            parsed_segment_count - assigned_segment_count,
        ),
        "assignment_rule": "segment_midpoint_inside_admin_bbox_choose_smallest_bbox_area",
        "admin_mobility_rows": rows,
        "holdout_evaluation": {
            "service_accessibility_leave_one_admin_out": evaluation,
        },
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": (
                "bounded_support"
                if supported_claim
                == "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines"
                else "not_for_claim"
            ),
            "reason": (
                "OSM road segment bbox crosswalk predicts observed OSM service count "
                "better than static population/built/city baselines; not a policy outcome"
            ),
        },
        "limitations": [
            "bbox_midpoint_assignment_not_polygon_overlay",
            "osm_service_count_is_public_proxy_not_authoritative_service_inventory",
            "not_policy_intervention_outcome",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _service_accessibility_leave_one_admin_out(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [
        {
            "target": _float(row.get("observed_service_point_count")),
            "road_segment_count": _float(row.get("road_segment_count")),
            "ghsl_population_proxy_sum": _float(row.get("ghsl_population_proxy_sum")),
            "ghsl_built_surface_proxy_sum": _float(
                row.get("ghsl_built_surface_proxy_sum")
            ),
        }
        for row in rows
    ]
    mobility_errors = _loo_abs_errors(records, ["road_segment_count"])
    city_errors = _loo_city_mean_errors(records)
    population_errors = _loo_abs_errors(records, ["ghsl_population_proxy_sum"])
    built_errors = _loo_abs_errors(records, ["ghsl_built_surface_proxy_sum"])
    mobility_mae = _mean(mobility_errors)
    baselines = {
        "city_mean": round(_mean(city_errors), 6),
        "ghsl_population_proxy": round(_mean(population_errors), 6),
        "ghsl_built_surface_proxy": round(_mean(built_errors), 6),
    }
    best_baseline = min(baselines.values())
    built_mae = baselines["ghsl_built_surface_proxy"]
    built_errors_for_wins = built_errors
    return {
        "target": "osm_service_point_count",
        "model": "osm_road_segment_count_standardized_ridge",
        "ridge": 1.0,
        "holdout_admin_unit_count": len(records),
        "mobility_crosswalk_mae": round(mobility_mae, 6),
        "traditional_static_baselines": baselines,
        "best_traditional_static_mae": round(best_baseline, 6),
        "mae_reduction_vs_best_traditional_static": round(
            best_baseline - mobility_mae,
            6,
        ),
        "paired_win_count_vs_best_traditional": sum(
            mobility < built
            for mobility, built in zip(mobility_errors, built_errors_for_wins)
        ),
        "paired_loss_count_vs_best_traditional": sum(
            mobility > built
            for mobility, built in zip(mobility_errors, built_errors_for_wins)
        ),
        "best_traditional_static_method": (
            "ghsl_built_surface_proxy"
            if built_mae == best_baseline
            else "other_static_baseline"
        ),
        "beats_all_traditional_static_baselines": mobility_mae < best_baseline,
    }


def _loo_abs_errors(records: list[dict[str, float]], columns: list[str]) -> list[float]:
    errors = []
    for index, test in enumerate(records):
        train = [record for item, record in enumerate(records) if item != index]
        prediction = _standardized_ridge_predict(train, test, columns)
        errors.append(abs(prediction - test["target"]))
    return errors


def _loo_city_mean_errors(records: list[dict[str, float]]) -> list[float]:
    errors = []
    for index, test in enumerate(records):
        train = [record for item, record in enumerate(records) if item != index]
        prediction = _mean([record["target"] for record in train])
        errors.append(abs(prediction - test["target"]))
    return errors


def _standardized_ridge_predict(
    train: list[dict[str, float]],
    test: dict[str, float],
    columns: list[str],
    *,
    ridge: float = 1.0,
) -> float:
    x_train = np.array([[record[column] for column in columns] for record in train])
    y_train = np.array([record["target"] for record in train])
    x_test = np.array([test[column] for column in columns])
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale == 0.0] = 1.0
    design = np.column_stack([np.ones(len(train)), (x_train - mean) / scale])
    penalty = ridge * np.eye(design.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return max(0.0, float(np.r_[1.0, (x_test - mean) / scale] @ coefficients))


def _smallest_bbox_midpoint_match(
    graph_nodes: list[dict[str, Any]],
    midpoint: tuple[float, float],
) -> dict[str, Any] | None:
    lon, lat = midpoint
    matches = []
    for node in graph_nodes:
        xmin, ymin, xmax, ymax = node["bbox"]
        if xmin <= lon <= xmax and ymin <= lat <= ymax:
            matches.append((node["bbox_area_degrees2"], node))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def _rows_by_county_township(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {_county_township_key(row): row for row in rows}


def _county_township_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("county") or ""), str(row.get("township") or ""))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
