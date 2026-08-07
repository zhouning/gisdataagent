from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .evidence_gate import build_environmental_evidence_gate
from .state import build_environmental_state


def assemble_chongqing_product(*, evidence: Mapping[str, Any], scene: Mapping[str, Any], graph: Mapping[str, Any], tap: Mapping[str, Any], tap_replay: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    graph_nodes = {str(row["unit_id"]): row for row in graph.get("nodes") or []}
    spatial_nodes = []
    for row in scene.get("admin_unit_states") or []:
        node_id = str(row["admin_unit_id"])
        vector = row.get("state_vector") or {}
        geometry = graph_nodes.get(node_id) or {}
        temperature = vector.get("gee_temperature_2m_mean_c")
        pm25 = vector.get("tap_scene_pm25_mean_ugm3")
        built_surface = vector.get("ghsl_built_surface_proxy_sum")
        spatial_nodes.append({
            "node_id": node_id,
            "node_type": "admin",
            "geometry_ref": {"centroid": geometry.get("centroid"), "bbox": geometry.get("bbox")},
            "geometry_area_m2": None,
            "county": row.get("county"),
            "township": row.get("township"),
            "pm25_ugm3": pm25,
            "pm25_support_level": "observed_context" if pm25 is not None else "unavailable",
            "temperature_c": temperature,
            "temperature_support_level": "observed_context" if temperature is not None else "unavailable",
            "vegetation_fraction": None,
            "vegetation_fraction_support_level": "unavailable",
            "built_fraction": None,
            "built_fraction_support_level": "unavailable",
            "built_surface_proxy_sum": built_surface,
        })
    known = {row["node_id"] for row in spatial_nodes}
    spatial_edges = [
        {
            "edge_id": f"admin-adjacent:{edge['source']}:{edge['target']}",
            "source_node_id": edge["source"],
            "target_node_id": edge["target"],
            "relation_type": "admin_adjacent_admin",
            "support_level": "observed_context",
            "verified_crosswalk_id": graph.get("graph_id"),
        }
        for edge in graph.get("edges") or []
        if edge.get("source") in known and edge.get("target") in known
    ]
    source_ids = sorted(set((evidence.get("source_dataset_ids") or []) + (tap.get("source_dataset_ids") or []) + [str(graph.get("source_dataset_id"))]))
    state = build_environmental_state({
        "scene_id": scene.get("scene_id"),
        "snapshot_time": (evidence.get("scene_time_range") or {}).get("end_date"),
        "geography_version": graph.get("graph_id"),
        "evidence_bundle_id": evidence.get("bundle_id"),
        "source_dataset_ids": source_ids,
        "external_forcing": {"forcing_id": "observed-scene-period", "scene_time_range": evidence.get("scene_time_range")},
        "spatial_nodes": spatial_nodes,
        "spatial_edges": spatial_edges,
        "kernel_versions": {"environmental_kernel": "0.1.0"},
    })
    temporal_passed = tap.get("supported_claim") == "tap_external_temporal_dynamics_advantage_without_spatial_claim"
    gate = build_environmental_evidence_gate({
        "state_observation": {"ready": bool(spatial_nodes), "support_level": "observed_context", "source_ids": source_ids},
        "temporal_channels": {"pm25": {"holdout_passed": temporal_passed, "calibration_artifact_id": "tap_pm25_external_dynamics_2026_07_06" if temporal_passed else None, "coefficient_source": "tap_external_dynamics" if temporal_passed else None}},
        "action_response_channels": {"pm25": {}, "temperature": {}, "vegetation": {}},
        "spatial_channels": {"pm25": {}, "temperature": {}, "vegetation": {}},
        "external_forcing": {"scene_aligned": True, "forcing_id": "observed-scene-period"},
    })
    bundle_id = "uwm-environmental-kernel-" + hashlib.sha256((state["snapshot_digest"] + json.dumps(gate, sort_keys=True)).encode()).hexdigest()[:20]
    scene_product = {"schema": "uwm.environmental_kernel_scene.v1", "bundle_id": bundle_id, "scene_time_range": deepcopy(evidence.get("scene_time_range")), "source_dataset_ids": source_ids, "state": state}
    gate_product = {**gate, "bundle_id": bundle_id}
    rollout = {
        "schema": "uwm.environmental_rollout.v1", "bundle_id": bundle_id,
        "baseline_trajectory": [state], "intervention_trajectory": [state],
        "mechanism_contributions": {"baseline": [], "intervention": []},
        "evidence_gate": gate, "intervention_status": "action_response_closed",
        "production_blockers": gate["production_blockers"], "not_a_causal_effect_estimate": True,
        "fabricated_value_count": 0,
    }
    map_product = {"schema": "map_update.v1", "bundle_id": bundle_id, "summary": {"title": "重庆环境动态 Kernel 观测状态"}, "layers": [{"name": "环境状态节点", "type": "geojson", "geojsonData": {"type": "FeatureCollection", "features": [_feature(row) for row in spatial_nodes if (row.get("geometry_ref") or {}).get("centroid")]}}]}
    payloads = {"scene.json": scene_product, "evidence_gate.json": gate_product, "current_rollout.json": rollout, "map.json": map_product}
    if tap_replay:
        payloads["temporal_replay.json"] = _temporal_replay_product(bundle_id, tap_replay, known)
    return payloads


def _temporal_replay_product(bundle_id: str, tap_replay: Mapping[str, Any], known_nodes: set[str]) -> dict[str, Any]:
    series_by_node: dict[str, list[dict[str, Any]]] = {}
    for record in tap_replay.get("records") or []:
        unit_id = str(record.get("admin_unit_id") or "")
        pm25 = record.get("pm25_ugm3")
        timestamp = record.get("timestamp")
        if unit_id not in known_nodes or pm25 is None or not timestamp:
            continue
        interval = record.get("uncertainty_interval_ugm3") or {}
        series_by_node.setdefault(unit_id, []).append(
            {
                "timestamp": str(timestamp),
                "pm25_ugm3": float(pm25),
                "uncertainty_low_ugm3": interval.get("low"),
                "uncertainty_high_ugm3": interval.get("high"),
            }
        )
    nodes = []
    for unit_id, values in sorted(series_by_node.items()):
        values.sort(key=lambda row: row["timestamp"])
        pm25_values = [row["pm25_ugm3"] for row in values]
        nodes.append(
            {
                "node_id": unit_id,
                "record_count": len(values),
                "start_timestamp": values[0]["timestamp"],
                "end_timestamp": values[-1]["timestamp"],
                "pm25_min_ugm3": round(min(pm25_values), 6),
                "pm25_max_ugm3": round(max(pm25_values), 6),
                "pm25_mean_ugm3": round(sum(pm25_values) / len(pm25_values), 6),
                "pm25_last_minus_first_ugm3": round(pm25_values[-1] - pm25_values[0], 6),
                "series": values,
            }
        )
    return {
        "schema": "uwm.environmental_temporal_state_replay.v1",
        "bundle_id": bundle_id,
        "replay_kind": "historical_proxy_state_replay",
        "source_dataset_ids": list(tap_replay.get("source_dataset_ids") or []),
        "source_quality": {
            "synthetic_status": "semi_synthetic",
            "quality_status": "tap_like_pm25_scene_not_observed_holdout",
            "support_level": "bounded_proxy",
            "not_calendar_forecast": True,
            "not_policy_effect": True,
        },
        "node_series": nodes,
    }


def _feature(row: Mapping[str, Any]) -> dict[str, Any]:
    centroid = row["geometry_ref"]["centroid"]
    return {"type": "Feature", "properties": {key: value for key, value in row.items() if key != "geometry_ref"}, "geometry": {"type": "Point", "coordinates": [centroid["lon"], centroid["lat"]]}}
