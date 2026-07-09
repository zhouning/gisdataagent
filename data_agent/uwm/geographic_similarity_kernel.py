"""Geographic-configuration similarity kernel for UWM livability graphs."""

from __future__ import annotations

import math
from typing import Any


UWM_GEOGRAPHIC_SIMILARITY_KERNEL_SCHEMA = "uwm.geographic_similarity_kernel.v1"


FEATURE_NAMES = [
    "exposure_priority_score",
    "livability_need_score",
    "score_components.exposure_norm",
    "score_components.service_gap_norm",
    "score_components.essential_gap_norm",
    "service_accessibility_score",
    "service_gap_score",
    "log_service_point_count",
    "log_essential_service_count",
    "log_service_capacity_proxy",
    "log_nearest_essential_service_distance_m",
    "estimated_nearest_essential_travel_time_min",
    "log_road_segment_count",
    "log_road_length_km",
    "mean_road_speed_kmh",
    "log_healthcare_count",
    "log_education_count",
    "log_food_retail_count",
    "log_finance_count",
    "log_mobility_transport_count",
    "log_civic_public_count",
    "log_recreation_count",
    "log_lodging_count",
    "log_other_service_count",
]


def build_uwm_geographic_similarity_kernel(
    *,
    admin_livability_panel: dict[str, Any],
    admin_spatial_graph: dict[str, Any],
    kernel_id: str,
    created_at: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Build a kNN kernel over full-admin geographic configuration features."""

    rows = [
        row
        for row in admin_livability_panel.get("admin_livability_target_rows") or []
        if isinstance(row, dict) and row.get("admin_unit_id") is not None
    ]
    nodes = {
        str(node.get("unit_id")): node
        for node in admin_spatial_graph.get("nodes") or []
        if isinstance(node, dict) and node.get("unit_id") is not None
    }
    adjacency_pairs = _adjacency_pairs(admin_spatial_graph)
    vectors = [_raw_vector(row) for row in rows]
    standardized = _standardize(vectors)
    unit_ids = [str(row.get("admin_unit_id")) for row in rows]
    row_by_unit = {str(row.get("admin_unit_id")): row for row in rows}
    top_k = max(1, int(top_k))
    neighbors: dict[str, list[dict[str, Any]]] = {}
    similarity_edges: list[dict[str, Any]] = []

    for source_index, source_unit_id in enumerate(unit_ids):
        candidates = []
        source_vector = standardized[source_index]
        for target_index, target_unit_id in enumerate(unit_ids):
            if source_index == target_index:
                continue
            distance = _standardized_distance(source_vector, standardized[target_index])
            similarity = _similarity_from_distance(distance)
            candidates.append((similarity, distance, target_unit_id, target_index))
        candidates.sort(key=lambda item: (-item[0], item[2]))
        for rank, (similarity, distance, target_unit_id, _target_index) in enumerate(
            candidates[:top_k],
            start=1,
        ):
            edge = _similarity_edge(
                source_unit_id=source_unit_id,
                target_unit_id=target_unit_id,
                source_row=row_by_unit[source_unit_id],
                target_row=row_by_unit[target_unit_id],
                source_node=nodes.get(source_unit_id) or {},
                target_node=nodes.get(target_unit_id) or {},
                rank=rank,
                similarity=similarity,
                distance=distance,
                boundary_adjacent=_pair_key(source_unit_id, target_unit_id)
                in adjacency_pairs,
            )
            neighbors.setdefault(source_unit_id, []).append(edge)
            similarity_edges.append(edge)

    negative_controls = _negative_controls(
        unit_ids=unit_ids,
        standardized_vectors=standardized,
        neighbors=neighbors,
    )
    similarities = [_float(edge.get("configuration_similarity")) for edge in similarity_edges]
    non_adjacent_count = sum(
        1 for edge in similarity_edges if edge.get("boundary_adjacent") is False
    )
    adjacent_count = len(similarity_edges) - non_adjacent_count
    ready = (
        admin_livability_panel.get("schema") == "uwm.admin_livability_target_panel.v1"
        and admin_spatial_graph.get("schema") == "uwm.admin_spatial_adjacency_graph.v1"
        and len(unit_ids) > 1
        and len(similarity_edges) > 0
        and negative_controls["rotated_target_similarity_control_passed"] is True
    )
    supported_claim = (
        "geographic_similarity_configuration_kernel_ready"
        if ready
        else "no_geographic_similarity_configuration_kernel_claim_supported"
    )
    return {
        "schema": UWM_GEOGRAPHIC_SIMILARITY_KERNEL_SCHEMA,
        "version": "0.1",
        "kernel_id": kernel_id,
        "created_at": created_at,
        "source_schemas": {
            "admin_livability_panel": admin_livability_panel.get("schema"),
            "admin_spatial_graph": admin_spatial_graph.get("schema"),
        },
        "source_dataset_ids": [
            *[str(item) for item in admin_livability_panel.get("source_dataset_ids") or []],
            str(admin_spatial_graph.get("source_dataset_id") or "admin_spatial_graph_2026_07_05"),
        ],
        "configuration_features": {
            "feature_names": FEATURE_NAMES,
            "feature_count": len(FEATURE_NAMES),
            "standardization": "z_score_over_admin_units",
            "similarity_metric": "1 / (1 + root_mean_square_standardized_feature_distance)",
            "top_k": top_k,
            "uses_full_admin_livability_panel": len(unit_ids) >= 1000,
            "uses_service_road_exposure_need_features": True,
            "uses_coordinates_as_similarity_features": False,
            "uses_admin_boundary_adjacency_as_similarity_feature": False,
            "boundary_adjacency_used_for_diagnostics": True,
        },
        "neighbors": neighbors,
        "similarity_edges": similarity_edges,
        "summary": {
            "panel_unit_count": len(unit_ids),
            "graph_node_count": _int((admin_spatial_graph.get("summary") or {}).get("node_count")),
            "graph_edge_count": _int((admin_spatial_graph.get("summary") or {}).get("edge_count")),
            "kernel_source_unit_count": len(neighbors),
            "top_k": top_k,
            "similarity_edge_count": len(similarity_edges),
            "adjacent_similarity_edge_count": adjacent_count,
            "non_adjacent_similarity_edge_count": non_adjacent_count,
            "non_adjacent_similarity_edge_share": _ratio(
                non_adjacent_count,
                len(similarity_edges),
            ),
            "min_configuration_similarity": round(min(similarities) if similarities else 0.0, 9),
            "max_configuration_similarity": round(max(similarities) if similarities else 0.0, 9),
            "mean_configuration_similarity": round(
                sum(similarities) / len(similarities) if similarities else 0.0,
                9,
            ),
        },
        "negative_controls": negative_controls,
        "geographic_similarity_kernel_ready": ready,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "configuration-similarity edges are derived from the full-admin "
                "livability panel using service, road, exposure and need features; "
                "they support graph message passing and planning priors but are not "
                "observed intervention effects"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "configuration_similarity_is_feature_kernel_not_causal_effect",
            "not_observed_policy_outcome",
            "does_not_use_coordinates_as_similarity_features",
            "negative_control_is_diagnostic_not_policy_validation",
        ],
    }


def validate_uwm_geographic_similarity_kernel(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate schema and claim boundaries for a geographic similarity kernel."""

    errors: list[str] = []
    if payload.get("schema") != UWM_GEOGRAPHIC_SIMILARITY_KERNEL_SCHEMA:
        errors.append("schema_must_be_uwm_geographic_similarity_kernel_v1")
    summary = payload.get("summary") or {}
    features = payload.get("configuration_features") or {}
    negative_controls = payload.get("negative_controls") or {}
    if _int(summary.get("panel_unit_count")) <= 1:
        errors.append("panel_unit_count_must_be_greater_than_one")
    if _int(summary.get("similarity_edge_count")) <= 0:
        errors.append("similarity_edge_count_must_be_positive")
    if _int(features.get("feature_count")) <= 0:
        errors.append("feature_count_must_be_positive")
    if features.get("uses_coordinates_as_similarity_features") is not False:
        errors.append("coordinates_must_not_drive_configuration_similarity")
    if (
        negative_controls.get("rotated_target_similarity_control_passed") is not True
        and payload.get("geographic_similarity_kernel_ready") is True
    ):
        errors.append("ready_kernel_must_pass_rotated_target_similarity_control")
    if payload.get("observed_policy_outcome_superiority_claim") is True:
        errors.append("kernel_must_not_claim_observed_policy_outcome_superiority")
    if payload.get("empirical_superiority_claim") is True:
        errors.append("kernel_must_not_claim_empirical_superiority")
    return {"valid": not errors, "errors": errors}


def _similarity_edge(
    *,
    source_unit_id: str,
    target_unit_id: str,
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    rank: int,
    similarity: float,
    distance: float,
    boundary_adjacent: bool,
) -> dict[str, Any]:
    return {
        "edge_type": "geographic_configuration_similarity",
        "source_unit_id": source_unit_id,
        "target_unit_id": target_unit_id,
        "source": source_unit_id,
        "target": target_unit_id,
        "rank": rank,
        "weight": round(similarity, 9),
        "configuration_similarity": round(similarity, 9),
        "standardized_feature_distance": round(distance, 9),
        "boundary_adjacent": bool(boundary_adjacent),
        "same_county": str(source_row.get("county") or "") == str(target_row.get("county") or ""),
        "source_county": source_row.get("county"),
        "target_county": target_row.get("county"),
        "source_livability_need_score": round(_float(source_row.get("livability_need_score")), 9),
        "target_livability_need_score": round(_float(target_row.get("livability_need_score")), 9),
        "source_exposure_priority_score": round(_float(source_row.get("exposure_priority_score")), 9),
        "target_exposure_priority_score": round(_float(target_row.get("exposure_priority_score")), 9),
        "source_service_accessibility_score": round(
            _service_accessibility(source_row),
            9,
        ),
        "target_service_accessibility_score": round(
            _service_accessibility(target_row),
            9,
        ),
        "source_degree": _int(source_node.get("degree")),
        "target_degree": _int(target_node.get("degree")),
    }


def _raw_vector(row: dict[str, Any]) -> list[float]:
    return [_feature_value(row, feature) for feature in FEATURE_NAMES]


def _feature_value(row: dict[str, Any], feature: str) -> float:
    score_components = row.get("score_components") or {}
    if feature == "score_components.exposure_norm":
        return _float(score_components.get("exposure_norm"))
    if feature == "score_components.service_gap_norm":
        return _float(score_components.get("service_gap_norm"))
    if feature == "score_components.essential_gap_norm":
        return _float(score_components.get("essential_gap_norm"))
    if feature == "service_accessibility_score":
        return _service_accessibility(row)
    if feature == "service_gap_score":
        return _service_gap(row)
    if feature.startswith("log_"):
        return math.log1p(max(0.0, _float(row.get(feature.removeprefix("log_")))))
    return _float(row.get(feature))


def _service_accessibility(row: dict[str, Any]) -> float:
    if row.get("service_accessibility_score") is not None:
        return _float(row.get("service_accessibility_score"))
    return max(0.0, 1.0 - _service_gap(row))


def _service_gap(row: dict[str, Any]) -> float:
    if row.get("service_gap_score") is not None:
        return _float(row.get("service_gap_score"))
    if row.get("service_accessibility_score") is not None:
        return max(0.0, 1.0 - _float(row.get("service_accessibility_score")))
    return _float((row.get("score_components") or {}).get("service_gap_norm"))


def _standardize(vectors: list[list[float]]) -> list[list[float]]:
    if not vectors:
        return []
    feature_count = len(vectors[0])
    means = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(feature_count)
    ]
    stds = []
    for index, mean in enumerate(means):
        variance = sum((vector[index] - mean) ** 2 for vector in vectors) / len(vectors)
        std = math.sqrt(variance)
        stds.append(std if std > 1e-12 else 1.0)
    return [
        [
            (value - means[index]) / stds[index]
            for index, value in enumerate(vector)
        ]
        for vector in vectors
    ]


def _standardized_distance(source: list[float], target: list[float]) -> float:
    if not source:
        return 0.0
    return math.sqrt(
        sum((source[index] - target[index]) ** 2 for index in range(len(source)))
        / len(source)
    )


def _similarity_from_distance(distance: float) -> float:
    return 1.0 / (1.0 + max(0.0, distance))


def _negative_controls(
    *,
    unit_ids: list[str],
    standardized_vectors: list[list[float]],
    neighbors: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    unit_index = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    real_source_means = []
    rotated_similarities = []
    rotation = max(1, len(unit_ids) // 2)
    for source_unit_id, source_neighbors in neighbors.items():
        if not source_neighbors:
            continue
        source_index = unit_index[source_unit_id]
        neighbor_targets = {str(edge.get("target_unit_id")) for edge in source_neighbors}
        real_source_means.append(
            sum(_float(edge.get("configuration_similarity")) for edge in source_neighbors)
            / len(source_neighbors)
        )
        rotated_index = _rotated_target_index(
            source_index=source_index,
            rotation=rotation,
            unit_ids=unit_ids,
            disallowed_targets=neighbor_targets | {source_unit_id},
        )
        distance = _standardized_distance(
            standardized_vectors[source_index],
            standardized_vectors[rotated_index],
        )
        rotated_similarities.append(_similarity_from_distance(distance))
    real_mean = sum(real_source_means) / len(real_source_means) if real_source_means else 0.0
    rotated_mean = (
        sum(rotated_similarities) / len(rotated_similarities)
        if rotated_similarities
        else 0.0
    )
    advantage = real_mean - rotated_mean
    return {
        "control_type": "deterministic_rotated_target_similarity",
        "real_topk_mean_similarity": round(real_mean, 9),
        "rotated_target_mean_similarity": round(rotated_mean, 9),
        "real_minus_rotated_similarity": round(advantage, 9),
        "rotated_target_similarity_control_passed": advantage > 0.0,
    }


def _rotated_target_index(
    *,
    source_index: int,
    rotation: int,
    unit_ids: list[str],
    disallowed_targets: set[str],
) -> int:
    count = len(unit_ids)
    for offset in range(count):
        candidate_index = (source_index + rotation + offset) % count
        if unit_ids[candidate_index] not in disallowed_targets:
            return candidate_index
    return (source_index + 1) % count


def _adjacency_pairs(admin_spatial_graph: dict[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    for edge in admin_spatial_graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if source is None or target is None:
            continue
        pairs.add(_pair_key(str(source), str(target)))
    return pairs


def _pair_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 9) if denominator else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default
