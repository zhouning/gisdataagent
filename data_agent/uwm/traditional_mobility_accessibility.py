from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping


SCHEMA = "traditional_livability.mobility_accessibility.v1"
DEMAND8_CHANNELS = {
    "service_inventory": "implemented",
    "administrative_accessibility_surface": "implemented",
    "nearest_service_distance": "implemented",
    "road_network_travel_time": "proxy_only",
    "walking_time": "proxy_only",
    "first_last_mile": "proxy_only",
    "road_connectivity": "proxy_only",
    "cycling_routes": "unavailable",
    "public_transport": "unavailable",
    "shaded_routes": "unavailable",
    "universal_accessibility": "unavailable",
    "parking_pressure": "unavailable",
    "pedestrian_crossings": "unavailable",
    "road_safety": "unavailable",
}


def build_mobility_accessibility_product(
    *,
    surface: Mapping[str, Any],
    mobility_graph: Mapping[str, Any],
    quality_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if surface.get("schema") != "uwm.full_admin_service_accessibility_surface.v1":
        raise ValueError("invalid_accessibility_surface_schema")
    if mobility_graph.get("schema") != "uwm.full_admin_mobility_graph.v1":
        raise ValueError("invalid_mobility_graph_schema")
    if quality_audit.get("schema") != "uwm.full_admin_service_surface_quality_audit.v1":
        raise ValueError("invalid_quality_audit_schema")

    rows = sorted(
        [_canonical_row(row) for row in surface.get("admin_service_rows") or []],
        key=lambda row: row["admin_unit_id"],
    )
    _apply_gap_ranking(rows)
    channel_readiness = {
        channel: _channel_readiness(channel, status)
        for channel, status in sorted(DEMAND8_CHANNELS.items())
    }
    product = {
        "schema": SCHEMA,
        "source_dataset_ids": sorted({str(value) for value in surface.get("source_dataset_ids") or []}),
        "source_schemas": {
            "surface": surface.get("schema"),
            "mobility_graph": mobility_graph.get("schema"),
            "quality_audit": quality_audit.get("schema"),
        },
        "admin_units": rows,
        "channel_readiness": channel_readiness,
        "summary": {
            "admin_unit_count": len(rows),
            "mobility_graph_node_count": (mobility_graph.get("summary") or {}).get("node_count"),
            "mobility_graph_edge_count": (mobility_graph.get("summary") or {}).get("edge_count"),
            "road_segment_count": (mobility_graph.get("summary") or {}).get("road_segment_count_sum"),
            "road_length_km_proxy": (mobility_graph.get("summary") or {}).get("road_length_km_sum"),
            "ranked_admin_unit_count": sum(row["accessibility_gap_rank"] is not None for row in rows),
            "ranking_excluded_admin_unit_count": sum(row["accessibility_gap_rank"] is None for row in rows),
        },
        "ranking_method": {
            "method": "relative_ordering_within_bound_product",
            "order": ["service_accessibility_score_ascending", "nearest_service_distance_descending", "admin_unit_id"],
            "authoritative_thresholds_used": False,
            "engineering_investment_priority": False,
        },
        "quality_evidence": {
            "supported_claim": quality_audit.get("supported_claim"),
            "claim_boundary": deepcopy(quality_audit.get("claim_boundary") or {}),
            "limitations": deepcopy(quality_audit.get("limitations") or []),
        },
        "claim_boundary": {
            "max_claim_level": "administrative_service_accessibility_and_network_proxy_gap_diagnostic",
            "network_proxy_not_observed_walk_time": True,
            "observed_trip_time": False,
            "policy_outcome_claim": False,
            "complete_demand8_fulfillment": False,
        },
        "limitations": sorted(set((surface.get("limitations") or []) + (mobility_graph.get("limitations") or []) + (quality_audit.get("limitations") or []))),
    }
    product["product_digest"] = _digest(product)
    return product


def _canonical_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "admin_unit_id": str(row.get("admin_unit_id") or ""),
        "county": row.get("county"),
        "township": row.get("township"),
        "centroid": {"longitude": row.get("longitude"), "latitude": row.get("latitude")},
        "service_point_count": row.get("service_point_count"),
        "essential_service_count": row.get("essential_service_count"),
        "nearest_essential_service_distance_m": row.get("nearest_essential_service_distance_m"),
        "nearest_essential_service_travel_time_min_proxy": row.get("nearest_essential_service_travel_time_min_proxy"),
        "road_segment_count": row.get("road_segment_count"),
        "road_length_km_proxy": row.get("road_length_km"),
        "mean_road_speed_kmh_proxy": row.get("mean_road_speed_kmh"),
        "service_accessibility_score": row.get("service_accessibility_score"),
        "network_proxy_not_observed_walk_time": True,
        "observed_trip_time": False,
        "policy_outcome_claim": False,
        "source_trace": deepcopy(row.get("source_trace") or {}),
        "limitations": ["network_proxy_not_observed_walk_time"],
        "accessibility_gap_rank": None,
        "ranking_exclusion_reason": None,
        "review_priority_reasons": [],
        "approved_connectivity_project": False,
        "expected_time_saving_min": None,
    }


def _apply_gap_ranking(rows: list[dict[str, Any]]) -> None:
    rankable = [row for row in rows if row.get("service_accessibility_score") is not None]
    rankable.sort(
        key=lambda row: (
            float(row["service_accessibility_score"]),
            -float(row.get("nearest_essential_service_distance_m") or -1.0),
            row["admin_unit_id"],
        )
    )
    scores = sorted(float(row["service_accessibility_score"]) for row in rankable)
    low_score_cut = scores[max(0, len(scores) // 3 - 1)] if scores else None
    distances = sorted(
        float(row["nearest_essential_service_distance_m"])
        for row in rankable
        if row.get("nearest_essential_service_distance_m") is not None
    )
    long_distance_cut = distances[(2 * len(distances)) // 3] if distances else None
    for rank, row in enumerate(rankable, start=1):
        row["accessibility_gap_rank"] = rank
        reasons = []
        if low_score_cut is not None and float(row["service_accessibility_score"]) <= low_score_cut:
            reasons.append("relative_low_accessibility_score")
        distance = row.get("nearest_essential_service_distance_m")
        if long_distance_cut is not None and distance is not None and float(distance) >= long_distance_cut:
            reasons.append("long_nearest_service_distance_proxy")
        if row.get("essential_service_count") == 0:
            reasons.append("zero_essential_service_count")
        if row.get("road_segment_count") == 0:
            reasons.append("limited_road_network_context")
        row["review_priority_reasons"] = reasons
    for row in rows:
        if row.get("service_accessibility_score") is None:
            row["ranking_exclusion_reason"] = "service_accessibility_score_missing"
            row["review_priority_reasons"] = ["collect_missing_accessibility_evidence"]


def _channel_readiness(channel: str, status: str) -> dict[str, Any]:
    if status == "implemented":
        return {"status": status, "value": "available_in_bound_product", "evidence": [channel], "blockers": []}
    if status == "proxy_only":
        return {"status": status, "value": "network_or_distance_proxy", "evidence": ["osm_road_and_service_proxy"], "blockers": ["observed_trip_time_missing"]}
    blockers = {
        "cycling_routes": "cycling_network_missing",
        "public_transport": "transit_routes_stops_schedules_missing",
        "shaded_routes": "shade_tree_canopy_path_data_missing",
        "universal_accessibility": "ramps_kerbs_barriers_data_missing",
        "parking_pressure": "parking_supply_occupancy_data_missing",
        "pedestrian_crossings": "crossing_inventory_missing",
        "road_safety": "crash_conflict_safety_observations_missing",
    }
    return {"status": status, "value": None, "evidence": [], "blockers": [blockers[channel]]}


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = deepcopy(dict(payload))
    canonical.pop("product_digest", None)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
