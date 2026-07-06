"""Graph-MDP model-based planning scaffold for UWM.

This module is inspired by graph-based sequential planning work, but it is not
a PPO/DRL implementation. It adds the missing world-model/RL boundary: graph
state, action masks, state-action-reward-transition replay tuples, and a
model-based rollout search that can be tested against static heuristics.
"""

from __future__ import annotations

from typing import Any

from .contracts import validate_uwm_observation
from .simulator import simulate_livability_rollout


GRAPH_MDP_STATE_SCHEMA = "uwm.graph_mdp_state.v1"
GRAPH_MDP_REPLAY_DATASET_SCHEMA = "uwm.graph_mdp_replay_dataset.v1"
MODEL_BASED_GRAPH_SEARCH_REPORT_SCHEMA = "uwm.model_based_graph_search_report.v1"
DEFAULT_GRAPH_SEARCH_BACKEND = "graph_mdp_beam_search_v0"
DEFAULT_STATE_ENCODER = "graph_feature_encoder_v0"


def build_admin_livability_graph_observation(
    panel: dict[str, Any],
    *,
    observation_id: str,
    created_at: str,
    max_units: int = 10,
    admin_spatial_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map an admin livability proxy panel into a graph-MDP observation.

    When an administrative spatial graph is supplied, the resulting graph is
    the induced boundary-adjacency subgraph for selected planning units. Without
    that graph, the function preserves the older priority-similarity proxy.
    """

    rows = list(panel.get("admin_livability_target_rows") or [])
    rows.sort(key=lambda row: _float(row.get("livability_need_score")), reverse=True)
    selected_rows = [row for row in rows[:max_units] if row.get("admin_unit_id")]
    spatial_units = [_admin_spatial_unit(row) for row in selected_rows]
    if admin_spatial_graph:
        graph_edges = _spatial_edges_for_units(admin_spatial_graph, [unit["unit_id"] for unit in spatial_units])
        graph_trace = {
            "step": "derive_admin_spatial_adjacency_subgraph",
            "source_graph_id": admin_spatial_graph.get("graph_id"),
            "source_node_count": (admin_spatial_graph.get("summary") or {}).get("node_count"),
            "source_edge_count": (admin_spatial_graph.get("summary") or {}).get("edge_count"),
            "selected_unit_count": len(spatial_units),
            "selected_spatial_edge_count": len(graph_edges),
            "edge_type": "admin_boundary_adjacency",
        }
        graph_quality_flags = [
            {
                "level": "info",
                "message": "graph edges are induced from administrative boundary adjacency, not mobility flow",
            }
        ]
        if not graph_edges:
            graph_quality_flags.append(
                {
                    "level": "warning",
                    "message": "selected planning units have no direct boundary adjacency in supplied admin spatial graph",
                }
            )
    else:
        graph_edges = _proxy_priority_edges(spatial_units)
        graph_trace = {
            "step": "derive_proxy_graph_mdp_observation",
            "selected_unit_count": len(spatial_units),
            "edge_type": "proxy_priority_similarity_not_spatial_adjacency",
        }
        graph_quality_flags = [
            {
                "level": "warning",
                "message": "proxy priority graph is not true spatial adjacency; use only for bounded model-based planning tests",
            }
        ]
    limitations = [str(item) for item in panel.get("limitations") or []]
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": observation_id,
        "created_at": created_at,
        "spatial_units": spatial_units,
        "object_layers": [
            {
                "role": "admin_livability_target_proxy",
                "uwm_role": "planner_targeting",
                "source_dataset_id": "admin_livability_target_panel_2024_07",
            }
        ],
        "raster_features": [],
        "graph_edges": graph_edges,
        "temporal_index": {
            "source_created_at": panel.get("created_at"),
            "observation_created_at": created_at,
        },
        "quality_flags": [
            *graph_quality_flags,
            *[{"level": "warning", "message": limitation} for limitation in limitations],
        ],
        "synthetic_flags": [
            {
                "dataset_id": "admin_livability_target_panel_2024_07",
                "status": "public_proxy",
            }
        ],
        "provenance": {
            "source_panel_id": panel.get("panel_id"),
            "source_schema": panel.get("schema"),
            "source_admin_spatial_graph_id": (admin_spatial_graph or {}).get("graph_id"),
        },
        "claim_boundary": {
            "max_claim_level": (panel.get("claim_boundary") or {}).get("max_claim_level", "bounded_support"),
            "reason": "admin livability graph observation is derived from proxy target panel",
        },
        "renderer_trace": [
            {
                "step": "load_admin_livability_target_panel",
                "source_panel_id": panel.get("panel_id"),
                "source_row_count": len(rows),
            },
            graph_trace,
        ],
    }


def build_graph_mdp_state(
    observation: dict[str, Any],
    *,
    action_types: list[str],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a graph-MDP state and feasible action mask from an observation."""

    thresholds = thresholds or {}
    validation = validate_uwm_observation(observation)
    nodes = [_node_from_unit(unit) for unit in observation.get("spatial_units") or [] if isinstance(unit, dict)]
    edges = [_edge_from_observation(edge) for edge in observation.get("graph_edges") or [] if isinstance(edge, dict)]
    available_actions: list[dict[str, Any]] = []
    action_mask_trace: list[dict[str, Any]] = []

    for node in nodes:
        for action_type in action_types:
            allowed, reason = _action_allowed(node, action_type, thresholds)
            trace = {
                "unit_id": node["unit_id"],
                "action_type": action_type,
                "allowed": allowed,
                "reason": reason,
            }
            if allowed:
                action = {
                    "action_id": f"{action_type}-{node['unit_id']}",
                    "action_type": action_type,
                    "target_units": [node["unit_id"]],
                    "intensity": 1.0,
                    "mask_reason": reason,
                }
                available_actions.append(action)
                trace["action_id"] = action["action_id"]
            action_mask_trace.append(trace)

    return {
        "schema": GRAPH_MDP_STATE_SCHEMA,
        "state_id": str(observation.get("observation_id") or "unknown_observation"),
        "source_observation_id": observation.get("observation_id"),
        "state_encoder": DEFAULT_STATE_ENCODER,
        "observation_validation": validation,
        "nodes": nodes,
        "edges": edges,
        "graph_statistics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "available_action_count": len(available_actions),
        },
        "available_actions": available_actions,
        "action_mask_trace": action_mask_trace,
        "claim_boundary": observation.get("claim_boundary") or {"max_claim_level": "not_for_claim"},
    }


def plan_with_model_based_graph_search(
    observation: dict[str, Any],
    *,
    action_types: list[str],
    scenario: dict[str, Any],
    horizon: int = 2,
    beam_width: int = 3,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Search over masked graph actions using simulator rollouts as the model."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if beam_width <= 0:
        raise ValueError("beam_width must be positive")

    graph_state = build_graph_mdp_state(observation, action_types=action_types, thresholds=thresholds)
    candidates = list(graph_state["available_actions"])
    if not candidates:
        raise ValueError("model-based graph search requires at least one masked candidate action")

    replay_transitions: list[dict[str, Any]] = []
    beams = [
        {
            "action_sequence": [],
            "cumulative_reward": 0.0,
            "rollout_trace": None,
            "transition_indices": [],
        }
    ]

    for step_index in range(horizon):
        expanded = []
        for beam in beams:
            used_action_ids = {action["action_id"] for action in beam["action_sequence"]}
            for action in candidates:
                if action["action_id"] in used_action_ids:
                    continue
                sequence = [*beam["action_sequence"], action]
                rollout = simulate_livability_rollout(observation, sequence, scenario=scenario)
                prefix_reward = _rollout_reward(rollout)
                transition_reward = prefix_reward - float(beam["cumulative_reward"])
                transition = _replay_transition(
                    graph_state=graph_state,
                    action=action,
                    reward=transition_reward,
                    rollout=rollout,
                    step_index=step_index,
                    cumulative_reward=prefix_reward,
                )
                replay_transitions.append(transition)
                transition_index = len(replay_transitions) - 1
                expanded.append(
                    {
                        "action_sequence": sequence,
                        "cumulative_reward": prefix_reward,
                        "rollout_trace": rollout,
                        "transition_indices": [*beam["transition_indices"], transition_index],
                    }
                )
        if not expanded:
            break
        expanded.sort(key=lambda item: item["cumulative_reward"], reverse=True)
        beams = expanded[:beam_width]

    best = beams[0]
    static_action = _static_single_step_action(graph_state)
    static_rollout = simulate_livability_rollout(observation, [static_action], scenario=scenario)
    static_reward = _rollout_reward(static_rollout)
    advantage = float(best["cumulative_reward"]) - static_reward
    evidence_grade = str((best["rollout_trace"] or {}).get("evidence_grade") or "not_for_claim")
    supported_claim = (
        "known_effect_model_based_graph_search_advantage"
        if advantage > 0 and evidence_grade != "not_for_claim"
        else "no_model_based_graph_search_advantage_claim_supported"
    )

    return {
        "schema": MODEL_BASED_GRAPH_SEARCH_REPORT_SCHEMA,
        "planner_backend": DEFAULT_GRAPH_SEARCH_BACKEND,
        "state_encoder": DEFAULT_STATE_ENCODER,
        "graph_mdp_state": graph_state,
        "search_config": {
            "horizon": horizon,
            "beam_width": beam_width,
            "candidate_action_count": len(candidates),
        },
        "best_sequence": {
            "action_count": len(best["action_sequence"]),
            "action_sequence": best["action_sequence"],
            "cumulative_reward": round(float(best["cumulative_reward"]), 9),
            "rollout_trace": best["rollout_trace"],
            "transition_indices": best["transition_indices"],
        },
        "static_single_step_baseline": {
            "method": "static_priority_single_step_heuristic",
            "decision_basis": "current_indicator_deficit_without_sequence_rollout",
            "action_sequence": [static_action],
            "cumulative_reward": round(static_reward, 9),
            "rollout_trace": static_rollout,
        },
        "trajectory_dataset": {
            "schema": GRAPH_MDP_REPLAY_DATASET_SCHEMA,
            "source_observation_id": observation.get("observation_id"),
            "transition_count": len(replay_transitions),
            "transitions": replay_transitions,
        },
        "advantage_over_static_single_step": round(advantage, 9),
        "supported_claim": supported_claim,
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": evidence_grade if advantage > 0 else "not_for_claim",
            "reason": "model-based graph search uses simulator rollouts; observed policy outcome gates remain open",
        },
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "learned_dynamics_model_required",
            "offline_policy_evaluation_required",
            "causal_policy_effect_validation_required",
        ],
    }


def _node_from_unit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(unit.get("unit_id")),
        "unit_id": str(unit.get("unit_id")),
        "node_type": str(unit.get("unit_type") or "spatial_unit"),
        "features": {
            "heat_risk": _float(unit.get("heat_risk")),
            "air_pollution_exposure": _float(unit.get("air_pollution_exposure")),
            "service_accessibility": _float(unit.get("service_accessibility")),
            "equity": _float(unit.get("equity")),
            "livability": _float(unit.get("livability")),
        },
    }


def _edge_from_observation(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(edge.get("source")),
        "target": str(edge.get("target")),
        "edge_type": str(edge.get("edge_type") or "spatial_adjacency"),
        "weight": _float(edge.get("weight"), default=1.0),
    }


def _admin_spatial_unit(row: dict[str, Any]) -> dict[str, Any]:
    components = row.get("score_components") or {}
    livability_need = _float(row.get("livability_need_score"))
    service_gap = _float(components.get("service_gap_norm"))
    return {
        "unit_id": str(row.get("admin_unit_id")),
        "unit_type": "admin_livability_proxy_unit",
        "county": row.get("county"),
        "township": row.get("township"),
        "heat_risk": _float(components.get("exposure_norm"), default=_float(row.get("exposure_priority_score"))),
        "air_pollution_exposure": _float(row.get("exposure_priority_score")),
        "service_accessibility": max(0.0, min(1.0, 1.0 - service_gap)),
        "equity": livability_need,
        "livability": max(0.0, min(1.0, 1.0 - livability_need)),
        "proxy_source": {
            "livability_need_score": livability_need,
            "service_point_count": _float(row.get("service_point_count")),
            "essential_service_count": _float(row.get("essential_service_count")),
        },
    }


def _proxy_priority_edges(spatial_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for index in range(len(spatial_units) - 1):
        source = spatial_units[index]["unit_id"]
        target = spatial_units[index + 1]["unit_id"]
        edges.append(
            {
                "edge_type": "proxy_priority_similarity_not_spatial_adjacency",
                "source": source,
                "target": target,
                "weight": 0.1,
            }
        )
    return edges


def _spatial_edges_for_units(admin_spatial_graph: dict[str, Any], unit_ids: list[str]) -> list[dict[str, Any]]:
    selected = {str(unit_id) for unit_id in unit_ids}
    edges = []
    for edge in admin_spatial_graph.get("edges") or []:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        if source not in selected or target not in selected:
            continue
        edges.append(
            {
                "edge_type": str(edge.get("edge_type") or "admin_boundary_adjacency"),
                "source": source,
                "target": target,
                "weight": _float(edge.get("weight"), default=1.0),
                "adjacency_relation": edge.get("adjacency_relation"),
                "shared_boundary_length_degrees": _float(edge.get("shared_boundary_length_degrees")),
            }
        )
    return edges


def _action_allowed(
    node: dict[str, Any],
    action_type: str,
    thresholds: dict[str, float],
) -> tuple[bool, str]:
    features = node["features"]
    action_key = action_type.lower()
    if action_key in {"increase_green", "increase_green_infrastructure", "urban_greening"}:
        return (
            features["heat_risk"] >= _float(thresholds.get("heat_risk"), default=0.7),
            "heat_risk_above_threshold",
        )
    if action_key in {"cool_roof", "cool_roofs", "building_cooling_retrofit"}:
        return (
            features["heat_risk"] >= _float(thresholds.get("heat_risk"), default=0.7),
            "heat_risk_above_threshold",
        )
    if action_key in {"traffic_emission_control", "low_emission_zone"}:
        return (
            features["air_pollution_exposure"]
            >= _float(thresholds.get("air_pollution_exposure"), default=0.6),
            "air_pollution_exposure_above_threshold",
        )
    if action_key in {"add_community_service", "service_accessibility_improvement"}:
        return (
            features["service_accessibility"]
            <= _float(thresholds.get("service_accessibility"), default=0.5),
            "service_accessibility_below_threshold",
        )
    return True, "generic_action_allowed"


def _rollout_reward(rollout: dict[str, Any]) -> float:
    interval = rollout.get("uncertainty_interval") or {}
    uncertainty_width = _float(interval.get("high")) - _float(interval.get("low"))
    return (
        _float(rollout.get("livability_delta"))
        + 0.50 * _float(rollout.get("equity_delta"))
        - 0.10 * uncertainty_width
    )


def _replay_transition(
    *,
    graph_state: dict[str, Any],
    action: dict[str, Any],
    reward: float,
    rollout: dict[str, Any],
    step_index: int,
    cumulative_reward: float,
) -> dict[str, Any]:
    return {
        "tuple_keys": ["state", "action", "reward", "next_state_delta", "transition"],
        "state": {
            "state_id": graph_state["state_id"],
            "state_encoder": graph_state["state_encoder"],
            "node_count": graph_state["graph_statistics"]["node_count"],
            "edge_count": graph_state["graph_statistics"]["edge_count"],
        },
        "action": action,
        "reward": round(reward, 9),
        "next_state_delta": rollout.get("future_state_delta"),
        "transition": {
            "step_index": step_index,
            "cumulative_reward": round(cumulative_reward, 9),
            "evidence_grade": rollout.get("evidence_grade"),
            "claim_boundary": rollout.get("claim_boundary"),
            "simulator_trace_steps": [step.get("step") for step in rollout.get("simulator_trace") or []],
        },
    }


def _static_single_step_action(graph_state: dict[str, Any]) -> dict[str, Any]:
    candidates = list(graph_state["available_actions"])
    candidates.sort(key=_static_priority_score, reverse=True)
    action = dict(candidates[0])
    action["action_id"] = f"static-{action['action_id']}"
    return action


def _static_priority_score(action: dict[str, Any]) -> float:
    reason_weight = {
        "heat_risk_above_threshold": 3.0,
        "air_pollution_exposure_above_threshold": 2.0,
        "service_accessibility_below_threshold": 1.0,
        "generic_action_allowed": 0.0,
    }
    return reason_weight.get(str(action.get("mask_reason")), 0.0)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
