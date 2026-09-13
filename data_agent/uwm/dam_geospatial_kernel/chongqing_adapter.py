"""Adapter from existing Chongqing UWM artifacts to a multi-scale DAM-GK graph."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch

from .contracts import DAMGKBatch


CHONGQING_DAM_GK_ADAPTER_SCHEMA = "gwm.dam_gk.chongqing_multiscale_graph.v1"

RELATION_TYPES = {
    "boundary_adjacency": 0,
    "mobility_context": 1,
    "configuration_similarity": 2,
    "fine_within_county": 3,
    "county_contains_fine": 4,
}

STATE_FEATURE_NAMES = [
    "exposure_priority_score",
    "service_accessibility_score",
    "service_gap_score",
    "livability_need_score",
    "log_service_point_count",
    "log_essential_service_count",
    "log_road_segment_count",
    "log_road_length_km",
    "mean_road_speed_kmh",
    "nearest_essential_service_distance_m",
]

EDGE_FEATURE_NAMES = [
    "relation_weight",
    "distance_or_difference_norm",
    "shared_boundary_norm",
    "same_county",
    "hierarchy_edge",
    "evidence_confidence",
]


@dataclass(frozen=True)
class ChongqingDAMGKGraph:
    batch: DAMGKBatch
    node_ids: list[str]
    fine_node_count: int
    coarse_node_count: int
    fine_to_coarse: torch.Tensor
    metadata: dict[str, Any]


def build_chongqing_dam_gk_graph(
    *,
    admin_livability_panel: dict[str, Any],
    admin_spatial_graph: dict[str, Any],
    mobility_graph: dict[str, Any],
    similarity_kernel: dict[str, Any],
    action: dict[str, Any] | None = None,
) -> ChongqingDAMGKGraph:
    """Build fine administrative nodes plus explicit county-scale aggregate nodes."""

    panel_rows = {
        str(row.get("admin_unit_id") or ""): row
        for row in admin_livability_panel.get("admin_livability_target_rows") or []
        if str(row.get("admin_unit_id") or "")
    }
    spatial_nodes = {
        str(row.get("unit_id") or ""): row
        for row in admin_spatial_graph.get("nodes") or []
        if str(row.get("unit_id") or "")
    }
    mobility_nodes = {
        str(row.get("unit_id") or ""): row
        for row in mobility_graph.get("mobility_nodes") or []
        if str(row.get("unit_id") or "")
    }
    fine_ids = sorted(set(panel_rows) & set(spatial_nodes))
    if not fine_ids:
        raise ValueError("no_joined_admin_nodes")
    counties = sorted({str(panel_rows[unit_id].get("county") or "unknown") for unit_id in fine_ids})
    county_ids = [f"county::{county}" for county in counties]
    node_ids = fine_ids + county_ids
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    county_index = {county: index for index, county in enumerate(counties)}

    raw_fine_features = [
        _raw_state_features(
            panel_rows[unit_id],
            mobility_nodes.get(unit_id) or {},
        )
        for unit_id in fine_ids
    ]
    fine_features = _minmax_columns(torch.tensor(raw_fine_features, dtype=torch.float32))
    fine_to_coarse = torch.zeros((len(counties), len(fine_ids)), dtype=torch.float32)
    for fine_index, unit_id in enumerate(fine_ids):
        county = str(panel_rows[unit_id].get("county") or "unknown")
        fine_to_coarse[county_index[county], fine_index] = 1.0
    county_mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
    coarse_features = (fine_to_coarse / county_mass) @ fine_features
    node_state = torch.cat([fine_features, coarse_features], dim=0)

    node_context = torch.zeros((len(node_ids), 4), dtype=torch.float32)
    centroids = torch.tensor(
        [
            [
                float((spatial_nodes[unit_id].get("centroid") or {}).get("lon") or 0.0),
                float((spatial_nodes[unit_id].get("centroid") or {}).get("lat") or 0.0),
            ]
            for unit_id in fine_ids
        ],
        dtype=torch.float32,
    )
    normalized_centroids = _minmax_columns(centroids)
    node_context[: len(fine_ids), :2] = normalized_centroids
    node_context[: len(fine_ids), 2] = 0.0
    node_context[: len(fine_ids), 3] = torch.tensor(
        [county_index[str(panel_rows[unit_id].get("county") or "unknown")] for unit_id in fine_ids],
        dtype=torch.float32,
    ) / max(1.0, float(len(counties) - 1))
    coarse_centroids = (fine_to_coarse / county_mass) @ normalized_centroids
    node_context[len(fine_ids) :, :2] = coarse_centroids
    node_context[len(fine_ids) :, 2] = 1.0
    node_context[len(fine_ids) :, 3] = torch.arange(len(counties), dtype=torch.float32) / max(
        1.0, float(len(counties) - 1)
    )

    node_action = torch.zeros((len(node_ids), 4), dtype=torch.float32)
    if action:
        action_type = str(action.get("action_type") or "")
        action_channel = {
            "increase_green_infrastructure": 0,
            "traffic_emission_control": 1,
            "add_community_service": 2,
        }.get(action_type, 2)
        intensity = float(action.get("intensity") or 1.0)
        for target_id in action.get("target_units") or [action.get("target_unit_id")]:
            target_id = str(target_id or "")
            if target_id not in node_index:
                continue
            node_action[node_index[target_id], action_channel] = 1.0
            node_action[node_index[target_id], 3] = intensity

    edges: list[tuple[int, int]] = []
    edge_features: list[list[float]] = []
    edge_types: list[int] = []
    seen: set[tuple[int, int, int]] = set()

    boundary_lengths = [
        float(edge.get("shared_boundary_length_degrees") or 0.0)
        for edge in admin_spatial_graph.get("edges") or []
    ]
    max_boundary = max(boundary_lengths or [1.0])
    for edge in admin_spatial_graph.get("edges") or []:
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        if source_id not in node_index or target_id not in node_index:
            continue
        boundary = float(edge.get("shared_boundary_length_degrees") or 0.0) / max_boundary
        for source_id, target_id in ((source_id, target_id), (target_id, source_id)):
            _append_edge(
                edges,
                edge_features,
                edge_types,
                seen,
                source=node_index[source_id],
                target=node_index[target_id],
                relation_type=RELATION_TYPES["boundary_adjacency"],
                feature_row=[1.0, 0.0, boundary, _same_county(source_id, target_id), 0.0, 1.0],
            )

    for edge in mobility_graph.get("mobility_edges") or []:
        source_id = str(edge.get("source_unit_id") or edge.get("source") or "")
        target_id = str(edge.get("target_unit_id") or edge.get("target") or "")
        if source_id not in node_index or target_id not in node_index:
            continue
        difference = float(edge.get("travel_time_difference_min") or 0.0)
        difference_norm = difference / (difference + 10.0)
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            source=node_index[source_id],
            target=node_index[target_id],
            relation_type=RELATION_TYPES["mobility_context"],
            feature_row=[
                float(edge.get("weight") or 0.0),
                difference_norm,
                0.0,
                1.0 if edge.get("same_county") else 0.0,
                0.0,
                0.55,
            ],
        )

    for edge in similarity_kernel.get("similarity_edges") or []:
        source_id = str(edge.get("source_unit_id") or edge.get("source") or "")
        target_id = str(edge.get("target_unit_id") or edge.get("target") or "")
        if source_id not in node_index or target_id not in node_index:
            continue
        distance = float(edge.get("standardized_feature_distance") or 0.0)
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            source=node_index[source_id],
            target=node_index[target_id],
            relation_type=RELATION_TYPES["configuration_similarity"],
            feature_row=[
                float(edge.get("weight") or 0.0),
                distance / (distance + 1.0),
                0.0,
                1.0 if edge.get("same_county") else 0.0,
                0.0,
                0.65,
            ],
        )

    for fine_index, unit_id in enumerate(fine_ids):
        county = str(panel_rows[unit_id].get("county") or "unknown")
        coarse_index = len(fine_ids) + county_index[county]
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            source=fine_index,
            target=coarse_index,
            relation_type=RELATION_TYPES["fine_within_county"],
            feature_row=[1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
        )
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            source=coarse_index,
            target=fine_index,
            relation_type=RELATION_TYPES["county_contains_fine"],
            feature_row=[1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
        )

    return ChongqingDAMGKGraph(
        batch=DAMGKBatch(
            node_state=node_state,
            node_action=node_action,
            edge_index=torch.tensor(edges, dtype=torch.long).t().contiguous(),
            edge_features=torch.tensor(edge_features, dtype=torch.float32),
            edge_types=torch.tensor(edge_types, dtype=torch.long),
            node_context=node_context,
            edge_valid_mask=torch.ones(len(edges), dtype=torch.bool),
        ),
        node_ids=node_ids,
        fine_node_count=len(fine_ids),
        coarse_node_count=len(counties),
        fine_to_coarse=fine_to_coarse,
        metadata={
            "schema": CHONGQING_DAM_GK_ADAPTER_SCHEMA,
            "state_feature_names": STATE_FEATURE_NAMES,
            "edge_feature_names": EDGE_FEATURE_NAMES,
            "relation_types": RELATION_TYPES,
            "fine_node_count": len(fine_ids),
            "coarse_node_count": len(counties),
            "total_node_count": len(node_ids),
            "edge_count": len(edges),
            "claim_boundary": {
                "max_claim_level": "real_multirelational_graph_input_ready",
                "observed_policy_effect_claim": False,
            },
        },
    )


def _raw_state_features(panel: dict[str, Any], mobility: dict[str, Any]) -> list[float]:
    return [
        float(panel.get("exposure_priority_score") or 0.0),
        float(panel.get("service_accessibility_score") or 0.0),
        float(panel.get("service_gap_score") or 0.0),
        float(panel.get("livability_need_score") or 0.0),
        math.log1p(float(panel.get("service_point_count") or 0.0)),
        math.log1p(float(panel.get("essential_service_count") or 0.0)),
        math.log1p(float(mobility.get("road_segment_count") or panel.get("road_segment_count") or 0.0)),
        math.log1p(float(mobility.get("road_length_km") or panel.get("road_length_km") or 0.0)),
        float(mobility.get("mean_road_speed_kmh") or panel.get("mean_road_speed_kmh") or 0.0),
        float(panel.get("nearest_essential_service_distance_m") or 0.0),
    ]


def _minmax_columns(values: torch.Tensor) -> torch.Tensor:
    minimum = values.min(dim=0).values
    maximum = values.max(dim=0).values
    return (values - minimum) / (maximum - minimum).clamp_min(1e-8)


def _same_county(source_id: str, target_id: str) -> float:
    return 1.0 if source_id.split("|", 1)[0] == target_id.split("|", 1)[0] else 0.0


def _append_edge(
    edges: list[tuple[int, int]],
    edge_feature_rows: list[list[float]],
    types: list[int],
    seen: set[tuple[int, int, int]],
    *,
    source: int,
    target: int,
    relation_type: int,
    feature_row: list[float],
) -> None:
    key = (source, target, relation_type)
    if key in seen:
        return
    seen.add(key)
    edges.append((source, target))
    edge_feature_rows.append(feature_row)
    types.append(relation_type)
