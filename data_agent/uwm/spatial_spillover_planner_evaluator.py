"""Spatial spillover evaluator for UWM planner replay."""

from __future__ import annotations

from typing import Any


UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA = (
    "uwm.spatial_spillover_planner_evaluator.v1"
)


def build_uwm_spatial_spillover_planner_evaluator(
    *,
    evaluator_id: str,
    created_at: str,
    data_calibrated_planner_replay: dict[str, Any],
    admin_spatial_graph: dict[str, Any],
) -> dict[str, Any]:
    """Compare planner and static replay spillover over first-order neighbors."""

    adjacency = _adjacency(admin_spatial_graph)
    planner_sequence = data_calibrated_planner_replay.get("best_sequence") or {}
    static_sequence = (
        data_calibrated_planner_replay.get("static_single_step_baseline") or {}
    )
    planner = _sequence_spillover(planner_sequence, adjacency)
    static = _sequence_spillover(static_sequence, adjacency)
    count_advantage = (
        planner["neighbor_benefited_unit_count"]
        - static["neighbor_benefited_unit_count"]
    )
    planner_delta_sum = round(planner["neighbor_livability_delta_sum"], 9)
    static_delta_sum = round(static["neighbor_livability_delta_sum"], 9)
    delta_advantage = planner_delta_sum - static_delta_sum
    ready = (
        count_advantage > 0
        and delta_advantage > 0.0
        and data_calibrated_planner_replay.get("observed_policy_outcome_superiority_claim")
        is not True
    )
    supported_claim = (
        "spatial_spillover_planner_replay_advantage_over_static_heuristic"
        if ready
        else "no_spatial_spillover_planner_replay_advantage_claim_supported"
    )
    return {
        "schema": UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA,
        "evaluator_id": evaluator_id,
        "created_at": created_at,
        "evaluation_method": "first_order_admin_neighbor_spillover",
        "source_planner_schema": data_calibrated_planner_replay.get("schema"),
        "source_admin_graph_schema": admin_spatial_graph.get("schema"),
        "planner_target_unit_count": planner["target_unit_count"],
        "static_target_unit_count": static["target_unit_count"],
        "planner_neighbor_unit_count": planner["neighbor_unit_count"],
        "static_neighbor_unit_count": static["neighbor_unit_count"],
        "planner_neighbor_benefited_unit_count": planner[
            "neighbor_benefited_unit_count"
        ],
        "static_neighbor_benefited_unit_count": static[
            "neighbor_benefited_unit_count"
        ],
        "neighbor_benefited_unit_count_advantage": count_advantage,
        "planner_neighbor_livability_delta_sum": planner_delta_sum,
        "static_neighbor_livability_delta_sum": static_delta_sum,
        "neighbor_livability_delta_advantage": round(delta_advantage, 9),
        "neighbor_livability_delta_advantage_ratio": round(
            planner["neighbor_livability_delta_sum"]
            / static["neighbor_livability_delta_sum"]
            if static["neighbor_livability_delta_sum"]
            else 0.0,
            6,
        ),
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "spatial spillover is evaluated from real admin adjacency graph and "
                "offline planner rollout deltas; it is not observed policy outcome"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _sequence_spillover(
    sequence: dict[str, Any],
    adjacency: dict[str, set[str]],
) -> dict[str, Any]:
    targets = {
        unit
        for action in sequence.get("action_sequence") or []
        for unit in action.get("target_units") or []
    }
    neighbors = set()
    for target in targets:
        neighbors.update(adjacency.get(target, set()))
    neighbors.difference_update(targets)
    per_unit = (
        ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
            "per_unit"
        )
        or {}
    )
    benefited_neighbors = {
        unit
        for unit in neighbors
        if _float((per_unit.get(unit) or {}).get("livability_delta")) > 0.0
    }
    return {
        "target_unit_count": len(targets),
        "neighbor_unit_count": len(neighbors),
        "neighbor_benefited_unit_count": len(benefited_neighbors),
        "neighbor_livability_delta_sum": sum(
            _float((per_unit.get(unit) or {}).get("livability_delta"))
            for unit in benefited_neighbors
        ),
    }


def _adjacency(admin_spatial_graph: dict[str, Any]) -> dict[str, set[str]]:
    adjacency = {
        str(node.get("unit_id")): set()
        for node in admin_spatial_graph.get("nodes") or []
        if node.get("unit_id") is not None
    }
    for edge in admin_spatial_graph.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    return adjacency


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
