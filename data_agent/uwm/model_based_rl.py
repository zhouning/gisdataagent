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
from .data_calibrated_mechanism_table import validate_uwm_data_calibrated_mechanism_table
from .geographic_similarity_kernel import validate_uwm_geographic_similarity_kernel
from .spatial_spillover_kernel import (
    validate_uwm_data_calibrated_spatial_spillover_kernel,
)
from .spatial_causal_action_binding import (
    action_with_spatial_causal_contract,
    causal_contracts_by_action_type,
    spatial_causal_action_binding_summary,
)


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
    max_units: int | None = None,
    admin_spatial_graph: dict[str, Any] | None = None,
    geographic_similarity_kernel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map an admin livability proxy panel into a graph-MDP observation.

    When an administrative spatial graph is supplied, the resulting graph is
    the induced boundary-adjacency subgraph for selected planning units. Without
    that graph, the function preserves the older priority-similarity proxy.
    """

    rows = list(panel.get("admin_livability_target_rows") or [])
    rows.sort(key=lambda row: _float(row.get("livability_need_score")), reverse=True)
    selection_mode = "all_rows"
    selected_source_rows = rows
    if max_units is not None:
        selection_mode = f"top_{max_units}_rows"
        selected_source_rows = rows[:max_units]
    selected_rows = [row for row in selected_source_rows if row.get("admin_unit_id")]
    spatial_units = [_admin_spatial_unit(row) for row in selected_rows]
    if admin_spatial_graph:
        graph_edges = _spatial_edges_for_units(admin_spatial_graph, [unit["unit_id"] for unit in spatial_units])
        graph_trace = {
            "step": "derive_admin_spatial_adjacency_subgraph",
            "source_graph_id": admin_spatial_graph.get("graph_id"),
            "source_node_count": (admin_spatial_graph.get("summary") or {}).get("node_count"),
            "source_edge_count": (admin_spatial_graph.get("summary") or {}).get("edge_count"),
            "source_row_count": len(rows),
            "selected_unit_count": len(spatial_units),
            "selected_spatial_edge_count": len(graph_edges),
            "selection_mode": selection_mode,
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
            "source_row_count": len(rows),
            "selected_unit_count": len(spatial_units),
            "selection_mode": selection_mode,
            "edge_type": "proxy_priority_similarity_not_spatial_adjacency",
        }
        graph_quality_flags = [
            {
                "level": "warning",
                "message": "proxy priority graph is not true spatial adjacency; use only for bounded model-based planning tests",
            }
        ]
    renderer_trace = [
        {
            "step": "load_admin_livability_target_panel",
            "source_panel_id": panel.get("panel_id"),
            "source_row_count": len(rows),
            "selected_unit_count": len(spatial_units),
            "selection_mode": selection_mode,
        },
        graph_trace,
    ]
    similarity_edges, similarity_trace, similarity_quality_flags = (
        _geographic_similarity_edges_for_units(
            geographic_similarity_kernel,
            [unit["unit_id"] for unit in spatial_units],
        )
    )
    if similarity_trace:
        renderer_trace.append(similarity_trace)
    graph_edges = [*graph_edges, *similarity_edges]
    graph_quality_flags = [*graph_quality_flags, *similarity_quality_flags]
    limitations = [str(item) for item in panel.get("limitations") or []]
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": observation_id,
        "created_at": created_at,
        "experiment_scope": _observation_scope(panel, selection_mode),
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
            "source_geographic_similarity_kernel_id": (
                geographic_similarity_kernel or {}
            ).get("kernel_id"),
        },
        "claim_boundary": {
            "max_claim_level": (panel.get("claim_boundary") or {}).get("max_claim_level", "bounded_support"),
            "reason": "admin livability graph observation is derived from proxy target panel",
        },
        "renderer_trace": renderer_trace,
    }


def _observation_scope(panel: dict[str, Any], selection_mode: str) -> str:
    panel_scope = str(panel.get("experiment_scope") or "full_admin_graph")
    if selection_mode == "all_rows":
        return panel_scope
    return f"subset_{selection_mode}"


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
    mechanism_table: dict[str, Any] | None = None,
    air_quality_uncertainty_context: dict[str, Any] | None = None,
    spatial_spillover_kernel: dict[str, Any] | None = None,
    transition_storage: str = "full",
    spatial_causal_question_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search over masked graph actions using simulator rollouts as the model."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if beam_width <= 0:
        raise ValueError("beam_width must be positive")
    if transition_storage not in {"full", "compact"}:
        raise ValueError("transition_storage must be 'full' or 'compact'")

    graph_state = build_graph_mdp_state(
        observation,
        action_types=action_types,
        thresholds=thresholds,
    )
    causal_contracts = causal_contracts_by_action_type(
        spatial_causal_question_registry or {}
    )
    candidates = [
        action_with_spatial_causal_contract(action, causal_contracts)
        for action in graph_state["available_actions"]
    ]
    graph_state = {
        **graph_state,
        "available_actions": candidates,
    }
    spatial_causal_binding = spatial_causal_action_binding_summary(
        spatial_causal_question_registry=spatial_causal_question_registry or {},
        actions=candidates,
        total_action_count_key="feasible_action_count",
    )
    if not candidates:
        raise ValueError("model-based graph search requires at least one masked candidate action")
    mechanism_summary = _mechanism_table_summary(mechanism_table)
    active_mechanism_table = mechanism_table if mechanism_summary["valid"] else None
    air_quality_uncertainty_summary = _air_quality_uncertainty_summary(
        air_quality_uncertainty_context
    )
    spatial_spillover_kernel_summary = _spatial_spillover_kernel_summary(
        spatial_spillover_kernel
    )
    active_spatial_spillover_kernel = (
        spatial_spillover_kernel
        if spatial_spillover_kernel_summary[
            "data_calibrated_spatial_spillover_kernel_ready"
        ]
        else None
    )

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
                rollout = simulate_livability_rollout(
                    observation,
                    sequence,
                    scenario=scenario,
                    mechanism_table=active_mechanism_table,
                    spatial_spillover_kernel=active_spatial_spillover_kernel,
                )
                prefix_reward = _rollout_reward(rollout)
                transition_reward = prefix_reward - float(beam["cumulative_reward"])
                transition = _replay_transition(
                    graph_state=graph_state,
                    action=action,
                    reward=transition_reward,
                    rollout=rollout,
                    step_index=step_index,
                    cumulative_reward=prefix_reward,
                    transition_storage=transition_storage,
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
    static_rollout = simulate_livability_rollout(
        observation,
        [static_action],
        scenario=scenario,
        mechanism_table=active_mechanism_table,
        spatial_spillover_kernel=active_spatial_spillover_kernel,
    )
    static_reward = _rollout_reward(static_rollout)
    advantage = float(best["cumulative_reward"]) - static_reward
    risk_adjusted_evaluation = _risk_adjusted_planner_evaluation(
        best_rollout=best["rollout_trace"] or {},
        static_rollout=static_rollout,
        best_reward=float(best["cumulative_reward"]),
        static_reward=static_reward,
        air_quality_uncertainty_summary=air_quality_uncertainty_summary,
    )
    evidence_grade = str((best["rollout_trace"] or {}).get("evidence_grade") or "not_for_claim")
    binding_ready = spatial_causal_binding["binding_ready"] is True
    supported_claim = (
        (
            "data_calibrated_model_based_graph_search_advantage_over_static_heuristic"
            if mechanism_summary["data_calibrated_mechanism_ready"]
            else "known_effect_model_based_graph_search_advantage"
        )
        if advantage > 0 and evidence_grade != "not_for_claim" and binding_ready
        else "no_model_based_graph_search_advantage_claim_supported"
    )
    claim_level = evidence_grade if advantage > 0 and binding_ready else "not_for_claim"
    remaining_gates = [
        "observed_policy_outcome_holdout_required",
        "learned_dynamics_model_required",
        "offline_policy_evaluation_required",
        "causal_policy_effect_validation_required",
    ]
    if not binding_ready:
        remaining_gates.append("spatial_causal_question_registry_binding_required")

    return {
        "schema": MODEL_BASED_GRAPH_SEARCH_REPORT_SCHEMA,
        "planner_backend": DEFAULT_GRAPH_SEARCH_BACKEND,
        "state_encoder": DEFAULT_STATE_ENCODER,
        "mechanism_table_summary": mechanism_summary,
        "spatial_spillover_kernel_summary": spatial_spillover_kernel_summary,
        "air_quality_uncertainty_calibration_summary": air_quality_uncertainty_summary,
        "spatial_causal_contract_binding": spatial_causal_binding,
        "graph_mdp_state": graph_state,
            "search_config": {
                "horizon": horizon,
                "beam_width": beam_width,
                "candidate_action_count": len(candidates),
                "transition_storage": transition_storage,
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
        "risk_adjusted_planner_evaluation": risk_adjusted_evaluation,
        "supported_claim": supported_claim,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": claim_level,
            "reason": (
                "model-based graph search uses data-calibrated simulator rollouts; observed policy "
                "outcome gates remain open"
                if mechanism_summary["data_calibrated_mechanism_ready"] and binding_ready
                else "model-based graph search lacks required spatial causal action binding"
                if not binding_ready
                else "model-based graph search uses simulator rollouts; observed policy outcome gates remain open"
            ),
        },
        "remaining_gates": remaining_gates,
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


def _geographic_similarity_edges_for_units(
    geographic_similarity_kernel: dict[str, Any] | None,
    unit_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, str]]]:
    if geographic_similarity_kernel is None:
        return [], None, []
    validation = validate_uwm_geographic_similarity_kernel(geographic_similarity_kernel)
    if not validation.get("valid"):
        return (
            [],
            {
                "step": "reject_geographic_configuration_similarity_kernel",
                "validation_errors": validation.get("errors") or [],
            },
            [
                {
                    "level": "warning",
                    "message": "geographic similarity kernel was supplied but failed validation",
                }
            ],
        )
    selected = {str(unit_id) for unit_id in unit_ids}
    edges = []
    for edge in geographic_similarity_kernel.get("similarity_edges") or []:
        source = str(edge.get("source") or edge.get("source_unit_id") or "")
        target = str(edge.get("target") or edge.get("target_unit_id") or "")
        if source not in selected or target not in selected:
            continue
        edges.append(
            {
                "edge_type": "geographic_configuration_similarity",
                "source": source,
                "target": target,
                "weight": _float(edge.get("weight"), default=0.0),
                "rank": _int(edge.get("rank")),
                "configuration_similarity": _float(
                    edge.get("configuration_similarity"),
                    default=0.0,
                ),
                "standardized_feature_distance": _float(
                    edge.get("standardized_feature_distance"),
                    default=0.0,
                ),
                "boundary_adjacent": bool(edge.get("boundary_adjacent")),
                "same_county": bool(edge.get("same_county")),
            }
        )
    return (
        edges,
        {
            "step": "append_geographic_configuration_similarity_edges",
            "source_kernel_id": geographic_similarity_kernel.get("kernel_id"),
            "source_similarity_edge_count": (
                geographic_similarity_kernel.get("summary") or {}
            ).get("similarity_edge_count"),
            "selected_unit_count": len(selected),
            "selected_similarity_edge_count": len(edges),
            "edge_type": "geographic_configuration_similarity",
        },
        [
            {
                "level": "info",
                "message": (
                    "geographic configuration similarity edges are derived from "
                    "service, road, exposure and livability-need features, not "
                    "from coordinate proximity"
                ),
            }
        ],
    )


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
    transition_storage: str = "full",
) -> dict[str, Any]:
    transition = {
        "tuple_keys": ["state", "action", "reward", "next_state_delta", "transition"],
        "state": {
            "state_id": graph_state["state_id"],
            "state_encoder": graph_state["state_encoder"],
            "node_count": graph_state["graph_statistics"]["node_count"],
            "edge_count": graph_state["graph_statistics"]["edge_count"],
        },
        "action": action,
        "reward": round(reward, 9),
        "transition": {
            "step_index": step_index,
            "cumulative_reward": round(cumulative_reward, 9),
            "evidence_grade": rollout.get("evidence_grade"),
            "claim_boundary": rollout.get("claim_boundary"),
            "simulator_trace_steps": [step.get("step") for step in rollout.get("simulator_trace") or []],
            "simulator_mechanism_sources": sorted(
                {
                    str(step.get("mechanism_source"))
                    for step in rollout.get("simulator_trace") or []
                    if step.get("mechanism_source")
                }
            ),
        },
    }
    if transition_storage == "compact":
        transition["tuple_keys"] = [
            "state",
            "action",
            "reward",
            "next_state_delta_summary",
            "transition",
        ]
        transition["next_state_delta_summary"] = _compact_state_delta(
            rollout.get("future_state_delta") or {}
        )
    else:
        transition["next_state_delta"] = rollout.get("future_state_delta")
    return transition


def _compact_state_delta(delta: dict[str, Any]) -> dict[str, Any]:
    per_unit = delta.get("per_unit") or {}
    changed_units = [
        {"unit_id": unit_id, **unit_delta}
        for unit_id, unit_delta in per_unit.items()
        if isinstance(unit_delta, dict) and _unit_delta_changed(unit_delta)
    ]
    changed_units.sort(
        key=lambda row: abs(_float(row.get("livability_delta"))),
        reverse=True,
    )
    return {
        "changed_units": delta.get("changed_units", len(changed_units)),
        "aggregate": delta.get("aggregate") or {},
        "top_changed_units": changed_units[:10],
    }


def _unit_delta_changed(unit_delta: dict[str, Any]) -> bool:
    return any(
        abs(_float(unit_delta.get(key))) > 0.0
        for key in [
            "heat_risk_delta",
            "air_pollution_exposure_delta",
            "service_accessibility_delta",
            "equity_delta",
            "livability_delta",
        ]
    )


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


def _mechanism_table_summary(mechanism_table: dict[str, Any] | None) -> dict[str, Any]:
    if mechanism_table is None:
        return {
            "mechanism_source": "hardcoded_mechanistic_coefficients",
            "mechanism_table_id": None,
            "valid": False,
            "validation_errors": ["mechanism_table_not_supplied"],
            "data_calibrated_mechanism_ready": False,
            "hardcoded_mechanism_replacement_ready": False,
        }
    validation = validate_uwm_data_calibrated_mechanism_table(mechanism_table)
    ready = (
        validation.get("valid") is True
        and mechanism_table.get("data_calibrated_mechanism_ready") is True
        and mechanism_table.get("observed_policy_outcome_superiority_claim") is False
        and (mechanism_table.get("claim_boundary") or {}).get("max_claim_level")
        == "bounded_support"
    )
    return {
        "mechanism_source": (
            "data_calibrated_mechanism_table"
            if ready
            else "invalid_data_calibrated_mechanism_table"
        ),
        "mechanism_table_id": mechanism_table.get("table_id"),
        "valid": validation.get("valid") is True,
        "validation_errors": validation.get("errors") or [],
        "data_calibrated_mechanism_ready": ready,
        "hardcoded_mechanism_replacement_ready": bool(
            mechanism_table.get("hardcoded_mechanism_replacement_ready")
        )
        and ready,
        "claim_level": (mechanism_table.get("claim_boundary") or {}).get("max_claim_level"),
        "policy_outcome_claim": False,
    }


def _spatial_spillover_kernel_summary(
    spatial_spillover_kernel: dict[str, Any] | None,
) -> dict[str, Any]:
    if spatial_spillover_kernel is None:
        return {
            "kernel_id": None,
            "valid": False,
            "validation_errors": ["spatial_spillover_kernel_not_supplied"],
            "data_calibrated_spatial_spillover_kernel_ready": False,
            "directional_edge_count": 0,
            "kernel_source_unit_count": 0,
            "mechanism_source": "graph_edge_constant_neighbor_factor",
        }
    validation = validate_uwm_data_calibrated_spatial_spillover_kernel(
        spatial_spillover_kernel
    )
    ready = (
        validation.get("valid") is True
        and spatial_spillover_kernel.get(
            "data_calibrated_spatial_spillover_kernel_ready"
        )
        is True
        and spatial_spillover_kernel.get("observed_policy_outcome_superiority_claim")
        is False
        and (spatial_spillover_kernel.get("claim_boundary") or {}).get(
            "max_claim_level"
        )
        == "bounded_support"
    )
    summary = spatial_spillover_kernel.get("summary") or {}
    return {
        "kernel_id": spatial_spillover_kernel.get("kernel_id"),
        "valid": validation.get("valid") is True,
        "validation_errors": validation.get("errors") or [],
        "data_calibrated_spatial_spillover_kernel_ready": ready,
        "directional_edge_count": _int(summary.get("directional_edge_count")),
        "kernel_source_unit_count": _int(summary.get("kernel_source_unit_count")),
        "min_spillover_factor": _float(summary.get("min_spillover_factor")),
        "max_spillover_factor": _float(summary.get("max_spillover_factor")),
        "mean_spillover_factor": _float(summary.get("mean_spillover_factor")),
        "mechanism_source": (
            "data_calibrated_spatial_spillover_kernel"
            if ready
            else "invalid_data_calibrated_spatial_spillover_kernel"
        ),
        "policy_outcome_claim": False,
    }


def _air_quality_uncertainty_summary(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    if context is None:
        return {
            "uwm_uncertainty_calibration_ready": False,
            "source_benchmark_id": None,
            "source_schema": None,
            "method": None,
            "confidence_level": 0.0,
            "calibration_count": 0,
            "holdout_count": 0,
            "uwm_interval_score": 0.0,
            "static_interval_score": 0.0,
            "uwm_interval_score_reduction": 0.0,
            "pm25_scene_range_ugm3": 0.0,
            "scene_aligned_station_calibrated_air_quality_holdout_ready": False,
            "observed_policy_outcome_superiority_claim": False,
            "ready_reason": "air_quality_uncertainty_context_not_supplied",
        }

    calibration = context.get("uncertainty_calibration") or context
    pm25_values = _scene_pm25_values(context)
    pm25_min = min(pm25_values) if pm25_values else 0.0
    pm25_max = max(pm25_values) if pm25_values else 0.0
    pm25_range = pm25_max - pm25_min
    gridded_ready = bool(
        context.get("scene_aligned_gridded_air_quality_holdout_ready", True)
    )
    station_ready = bool(
        context.get("scene_aligned_station_calibrated_air_quality_holdout_ready")
    )
    policy_claim = bool(context.get("observed_policy_outcome_superiority_claim"))
    interval_score = _float(calibration.get("uwm_interval_score"))
    static_interval_score = _float(calibration.get("static_interval_score"))
    score_reduction = _float(calibration.get("uwm_interval_score_reduction"))
    ready = (
        gridded_ready
        and not station_ready
        and not policy_claim
        and calibration.get("uwm_uncertainty_calibration_ready") is True
        and interval_score > 0.0
        and static_interval_score > interval_score
        and pm25_range > 0.0
    )
    return {
        "uwm_uncertainty_calibration_ready": ready,
        "source_benchmark_id": context.get("benchmark_id"),
        "source_schema": context.get("schema"),
        "source_scope": "scene_aligned_gridded_air_quality_uncertainty_calibration_not_station_or_policy_outcome",
        "method": calibration.get("method"),
        "confidence_level": _float(calibration.get("confidence_level")),
        "calibration_count": int(_float(calibration.get("calibration_count"))),
        "holdout_count": int(_float(calibration.get("holdout_count"))),
        "best_uwm_method": calibration.get("best_uwm_method"),
        "static_baseline_method": calibration.get("static_baseline_method"),
        "uwm_interval_radius": _float(calibration.get("uwm_interval_radius")),
        "static_interval_radius": _float(calibration.get("static_interval_radius")),
        "uwm_interval_coverage": _float(calibration.get("uwm_interval_coverage")),
        "static_interval_coverage": _float(calibration.get("static_interval_coverage")),
        "uwm_interval_score": interval_score,
        "static_interval_score": static_interval_score,
        "uwm_interval_score_reduction": score_reduction,
        "pm25_scene_min_ugm3": round(pm25_min, 9),
        "pm25_scene_max_ugm3": round(pm25_max, 9),
        "pm25_scene_range_ugm3": round(pm25_range, 9),
        "scene_aligned_gridded_air_quality_holdout_ready": gridded_ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": station_ready,
        "observed_policy_outcome_superiority_claim": policy_claim,
        "empirical_superiority_claim": bool(context.get("empirical_superiority_claim")),
        "limitations": [
            *[str(item) for item in context.get("limitations") or []],
            *[str(item) for item in calibration.get("limitations") or []],
        ],
        "ready_reason": (
            "scene_aligned_gridded_split_conformal_pm25_uncertainty_ready"
            if ready
            else "scene_aligned_gridded_pm25_uncertainty_not_ready_for_planner_risk"
        ),
    }


def _risk_adjusted_planner_evaluation(
    *,
    best_rollout: dict[str, Any],
    static_rollout: dict[str, Any],
    best_reward: float,
    static_reward: float,
    air_quality_uncertainty_summary: dict[str, Any],
) -> dict[str, Any]:
    interval_score = _float(air_quality_uncertainty_summary.get("uwm_interval_score"))
    pm25_range = _float(air_quality_uncertainty_summary.get("pm25_scene_range_ugm3"))
    normalized_interval_score = interval_score / pm25_range if pm25_range > 0.0 else 0.0
    best_dependency = _air_quality_reward_dependency(best_rollout)
    static_dependency = _air_quality_reward_dependency(static_rollout)
    best_penalty = best_dependency * normalized_interval_score
    static_penalty = static_dependency * normalized_interval_score
    best_risk_adjusted = best_reward - best_penalty
    static_risk_adjusted = static_reward - static_penalty
    risk_adjusted_advantage = best_risk_adjusted - static_risk_adjusted
    ready = (
        air_quality_uncertainty_summary.get("uwm_uncertainty_calibration_ready") is True
        and risk_adjusted_advantage > 0.0
    )
    return {
        "method": "same_conformal_pm25_uncertainty_penalty",
        "uses_same_calibrated_uncertainty_for_planner_and_static": True,
        "air_quality_reward_weight": 0.25,
        "pm25_scene_range_ugm3": round(pm25_range, 9),
        "uwm_interval_score": round(interval_score, 9),
        "normalized_uwm_interval_score": round(normalized_interval_score, 9),
        "best_sequence_raw_reward": round(best_reward, 9),
        "static_single_step_raw_reward": round(static_reward, 9),
        "best_sequence_air_quality_dependency": round(best_dependency, 9),
        "static_single_step_air_quality_dependency": round(static_dependency, 9),
        "best_sequence_uncertainty_penalty": round(best_penalty, 9),
        "static_single_step_uncertainty_penalty": round(static_penalty, 9),
        "best_sequence_risk_adjusted_reward": round(best_risk_adjusted, 9),
        "static_single_step_risk_adjusted_reward": round(static_risk_adjusted, 9),
        "risk_adjusted_advantage_over_static_single_step": round(
            risk_adjusted_advantage,
            9,
        ),
        "risk_calibrated_planner_replay_ready": ready,
        "supported_claim": (
            "risk_calibrated_data_calibrated_planner_replay_advantage_over_static_heuristic"
            if ready
            else "no_risk_calibrated_planner_replay_claim_supported"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "risk-adjusted planner replay uses the same scene-aligned gridded "
                "split-conformal PM2.5 uncertainty penalty for model-based and static plans"
                if ready
                else "risk-adjusted planner replay is not claim-ready"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _air_quality_reward_dependency(rollout: dict[str, Any]) -> float:
    return 0.25 * abs(_float(rollout.get("air_pollution_exposure_delta")))


def _scene_pm25_values(context: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for series in context.get("series_results") or []:
        if not isinstance(series, dict):
            continue
        for record in series.get("daily_pm25") or []:
            if not isinstance(record, dict):
                continue
            values.append(_float(record.get("pm25_ugm3")))
    return values


def _float(value: Any, default: float = 0.0) -> float:
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
