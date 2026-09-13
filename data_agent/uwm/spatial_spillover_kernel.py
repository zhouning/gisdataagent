"""Data-calibrated spatial spillover kernel for UWM livability rollouts."""

from __future__ import annotations

import math
from typing import Any


UWM_DATA_CALIBRATED_SPATIAL_SPILLOVER_KERNEL_SCHEMA = (
    "uwm.data_calibrated_spatial_spillover_kernel.v1"
)


def build_uwm_data_calibrated_spatial_spillover_kernel(
    *,
    admin_spatial_graph: dict[str, Any],
    admin_livability_panel: dict[str, Any],
    kernel_id: str,
    created_at: str,
    base_neighbor_factor: float = 0.35,
) -> dict[str, Any]:
    """Build a directional spillover kernel from real admin graph evidence."""

    panel_rows = {
        str(row.get("admin_unit_id")): row
        for row in admin_livability_panel.get("admin_livability_target_rows") or []
        if isinstance(row, dict) and row.get("admin_unit_id") is not None
    }
    panel_unit_ids = set(panel_rows)
    nodes = {
        str(node.get("unit_id")): node
        for node in admin_spatial_graph.get("nodes") or []
        if isinstance(node, dict) and node.get("unit_id") is not None
    }
    edges = [
        edge
        for edge in admin_spatial_graph.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("source") is not None
        and edge.get("target") is not None
    ]
    boundary_totals = _boundary_totals(edges)
    neighbors: dict[str, list[dict[str, Any]]] = {}

    for edge in edges:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        for directional_source, directional_target in (
            (source, target),
            (target, source),
        ):
            if directional_source not in panel_unit_ids:
                continue
            kernel_edge = _directional_kernel_edge(
                edge=edge,
                source=directional_source,
                target=directional_target,
                source_node=nodes.get(directional_source) or {},
                source_row=panel_rows.get(directional_source) or {},
                target_row=panel_rows.get(directional_target) or {},
                source_boundary_total=boundary_totals.get(
                    directional_source,
                    0.0,
                ),
                base_neighbor_factor=base_neighbor_factor,
            )
            if kernel_edge["spillover_factor"] <= 0.0:
                continue
            neighbors.setdefault(directional_source, []).append(kernel_edge)

    for unit_neighbors in neighbors.values():
        unit_neighbors.sort(
            key=lambda row: (
                -_float(row.get("spillover_factor")),
                str(row.get("target_unit_id")),
            )
        )

    factors = [
        _float(edge.get("spillover_factor"))
        for unit_neighbors in neighbors.values()
        for edge in unit_neighbors
    ]
    ready = (
        admin_spatial_graph.get("schema") == "uwm.admin_spatial_adjacency_graph.v1"
        and admin_livability_panel.get("schema") == "uwm.admin_livability_target_panel.v1"
        and len(panel_rows) > 0
        and len(factors) > 0
    )
    return {
        "schema": UWM_DATA_CALIBRATED_SPATIAL_SPILLOVER_KERNEL_SCHEMA,
        "kernel_id": kernel_id,
        "created_at": created_at,
        "source_schemas": {
            "admin_spatial_graph": admin_spatial_graph.get("schema"),
            "admin_livability_panel": admin_livability_panel.get("schema"),
        },
        "source_dataset_ids": [
            str(admin_spatial_graph.get("source_dataset_id")),
            "admin_livability_target_panel_2024_07",
        ],
        "calibration_features": {
            "uses_shared_boundary_length": True,
            "uses_admin_livability_need": True,
            "uses_admin_exposure_priority": True,
            "uses_source_degree_attenuation": True,
            "base_neighbor_factor": round(float(base_neighbor_factor), 9),
            "formula": (
                "base_neighbor_factor * boundary_share * "
                "target_need_multiplier * exposure_alignment_multiplier / sqrt(source_degree)"
            ),
        },
        "neighbors": neighbors,
        "summary": {
            "graph_node_count": len(nodes),
            "graph_edge_count": len(edges),
            "panel_unit_count": len(panel_rows),
            "kernel_source_unit_count": len(neighbors),
            "directional_edge_count": len(factors),
            "min_spillover_factor": round(min(factors) if factors else 0.0, 9),
            "max_spillover_factor": round(max(factors) if factors else 0.0, 9),
            "mean_spillover_factor": round(
                sum(factors) / len(factors) if factors else 0.0,
                9,
            ),
        },
        "data_calibrated_spatial_spillover_kernel_ready": ready,
        "supported_claim": (
            "data_calibrated_spatial_spillover_kernel_ready"
            if ready
            else "no_data_calibrated_spatial_spillover_kernel_claim_supported"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "spatial spillover weights are derived from real admin adjacency "
                "shared-boundary geometry and the admin livability target panel; "
                "they are not observed intervention effects"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_data_calibrated_spatial_spillover_kernel(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate schema and claim boundaries for a spatial spillover kernel."""

    errors: list[str] = []
    if payload.get("schema") != UWM_DATA_CALIBRATED_SPATIAL_SPILLOVER_KERNEL_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    neighbors = payload.get("neighbors")
    if not isinstance(neighbors, dict) or not neighbors:
        errors.append("neighbors_missing")
    summary = payload.get("summary") or {}
    if _int(summary.get("directional_edge_count")) <= 0:
        errors.append("directional_edge_count_must_be_positive")
    if _float(summary.get("max_spillover_factor")) <= 0.0:
        errors.append("max_spillover_factor_must_be_positive")
    features = payload.get("calibration_features") or {}
    for key in [
        "uses_shared_boundary_length",
        "uses_admin_livability_need",
        "uses_admin_exposure_priority",
        "uses_source_degree_attenuation",
    ]:
        if features.get(key) is not True:
            errors.append(f"{key}_must_be_true")
    if payload.get("data_calibrated_spatial_spillover_kernel_ready") is True:
        if (payload.get("claim_boundary") or {}).get("max_claim_level") != "bounded_support":
            errors.append("ready_kernel_requires_bounded_support_claim_level")
    return {"valid": not errors, "errors": errors}


def _directional_kernel_edge(
    *,
    edge: dict[str, Any],
    source: str,
    target: str,
    source_node: dict[str, Any],
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    source_boundary_total: float,
    base_neighbor_factor: float,
) -> dict[str, Any]:
    shared_boundary = _edge_boundary_length(edge)
    boundary_share = (
        shared_boundary / source_boundary_total if source_boundary_total > 0.0 else 0.0
    )
    source_degree = max(1.0, _float(source_node.get("degree"), default=1.0))
    target_need = _float(target_row.get("livability_need_score"))
    source_exposure = _float(source_row.get("exposure_priority_score"))
    target_exposure = _float(target_row.get("exposure_priority_score"))
    target_need_multiplier = 1.0 + 0.50 * target_need
    exposure_alignment_multiplier = 1.0 + 0.25 * min(source_exposure, target_exposure)
    degree_attenuation = 1.0 / math.sqrt(source_degree)
    spillover_factor = (
        float(base_neighbor_factor)
        * boundary_share
        * target_need_multiplier
        * exposure_alignment_multiplier
        * degree_attenuation
    )
    return {
        "source_unit_id": source,
        "target_unit_id": target,
        "spillover_factor": round(spillover_factor, 9),
        "shared_boundary_length_degrees": round(shared_boundary, 12),
        "source_boundary_total_degrees": round(source_boundary_total, 12),
        "boundary_share": round(boundary_share, 9),
        "source_degree": round(source_degree, 9),
        "target_livability_need_score": round(target_need, 9),
        "source_exposure_priority_score": round(source_exposure, 9),
        "target_exposure_priority_score": round(target_exposure, 9),
        "target_need_multiplier": round(target_need_multiplier, 9),
        "exposure_alignment_multiplier": round(exposure_alignment_multiplier, 9),
        "degree_attenuation": round(degree_attenuation, 9),
        "adjacency_relation": edge.get("adjacency_relation"),
    }


def _boundary_totals(edges: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for edge in edges:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        length = _edge_boundary_length(edge)
        totals[source] = totals.get(source, 0.0) + length
        totals[target] = totals.get(target, 0.0) + length
    return totals


def _edge_boundary_length(edge: dict[str, Any]) -> float:
    length = _float(edge.get("shared_boundary_length_degrees"))
    if length > 0.0:
        return length
    if _float(edge.get("weight")) > 0.0:
        return 0.000001
    return 0.0


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
