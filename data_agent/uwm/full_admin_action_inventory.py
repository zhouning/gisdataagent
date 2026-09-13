"""Full-admin feasible action inventory for UWM livability planning."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .livability_graph_mdp_env import LivabilityGraphMDPEnv
from .spatial_causal_action_binding import (
    action_with_spatial_causal_contract,
    causal_contracts_by_action_type,
    spatial_causal_action_binding_summary,
)


UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA = "uwm.full_admin_action_inventory.v1"

_SUPPORTED_CLAIM = (
    "full_admin_graph_feasible_action_inventory_enumerates_real_data_graph_mdp_actions"
)


def build_full_admin_action_inventory(
    env: LivabilityGraphMDPEnv,
    *,
    inventory_id: str,
    created_at: str,
    source_artifacts: dict[str, str] | None = None,
    spatial_causal_question_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize all feasible action candidates from the full-admin Graph-MDP."""

    nodes_by_unit = {
        str(node.get("unit_id")): node for node in env.graph_state.get("nodes") or []
    }
    thresholds = dict(env.config.thresholds)
    action_type_definitions = _action_type_definitions(thresholds)
    causal_contracts = causal_contracts_by_action_type(
        spatial_causal_question_registry or {}
    )
    actions = [
        action_with_spatial_causal_contract(
            _action_record(
                index,
                action,
                nodes_by_unit,
                action_type_definitions,
            ),
            causal_contracts,
        )
        for index, action in enumerate(env.available_actions)
    ]
    spatial_causal_binding = spatial_causal_action_binding_summary(
        spatial_causal_question_registry=spatial_causal_question_registry or {},
        actions=actions,
        total_action_count_key="feasible_action_count",
    )
    action_type_counts = dict(Counter(action["action_type"] for action in actions))
    mask_reason_counts = dict(Counter(action["mask_reason"] for action in actions))
    node_count = len(env.graph_state.get("nodes") or [])
    edge_count = len(env.graph_state.get("edges") or [])
    action_count = len(actions)
    full_data_guard = {
        "passed": (
            node_count == 1017
            and edge_count == 7932
            and action_count == 1137
            and action_type_counts
            == {
                "increase_green_infrastructure": 81,
                "traffic_emission_control": 77,
                "add_community_service": 979,
            }
        ),
        "required_scope": "full_admin_graph",
        "graph_node_count": node_count,
        "graph_edge_count": edge_count,
        "available_action_count": action_count,
    }
    return {
        "schema": UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA,
        "inventory_id": inventory_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_environment_schema": env.metadata.get("schema"),
        "source_observation_id": env.metadata.get("source_observation_id"),
        "source_artifacts": dict(source_artifacts or {}),
        "full_data_guard": full_data_guard,
        "summary": {
            "graph_node_count": node_count,
            "graph_edge_count": edge_count,
            "available_action_count": action_count,
            "candidate_action_mask_trace_count": len(
                env.graph_state.get("action_mask_trace") or []
            ),
            "action_type_counts": action_type_counts,
            "mask_reason_counts": mask_reason_counts,
            "thresholds": thresholds,
        },
        "action_type_definitions": action_type_definitions,
        "spatial_causal_contract_binding": spatial_causal_binding,
        "actions": actions,
        "supported_claim": _SUPPORTED_CLAIM
        if full_data_guard["passed"]
        else "no_full_admin_action_inventory_claim_supported",
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if full_data_guard["passed"]
            else "not_for_claim",
            "reason": (
                "The inventory enumerates feasible action candidates generated "
                "from the full-admin Graph-MDP state and threshold masks. It is "
                "not a historical intervention log and not observed policy outcome evidence."
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "feasible_action_inventory_not_historical_policy_log",
            "actions_are_single_unit_candidates_with_intensity_one",
            "threshold_mask_is_domain_rule_not_authoritative_project_feasibility_approval",
            "spatial_causal_contracts_define_do_queries_but_do_not_identify_observed_policy_effects",
        ],
    }


def _action_record(
    index: int,
    action: dict[str, Any],
    nodes_by_unit: dict[str, dict[str, Any]],
    action_type_definitions: dict[str, dict[str, str]],
) -> dict[str, Any]:
    target_unit_id = str((action.get("target_units") or [""])[0])
    node = nodes_by_unit.get(target_unit_id) or {}
    county, township, local_id = _split_admin_unit_id(target_unit_id)
    action_type = str(action.get("action_type"))
    return {
        "action_index": int(index),
        "action_id": str(action.get("action_id")),
        "action_type": action_type,
        "target_unit_id": target_unit_id,
        "target_county": county,
        "target_township": township,
        "target_local_id": local_id,
        "target_units": [target_unit_id],
        "intensity": _float(action.get("intensity"), default=1.0),
        "mask_reason": str(action.get("mask_reason")),
        "action_type_definition": dict(action_type_definitions.get(action_type) or {}),
        "target_features": _target_features(node),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _action_type_definitions(thresholds: dict[str, Any]) -> dict[str, dict[str, str]]:
    heat = _format_threshold(thresholds.get("heat_risk"), 0.7)
    air = _format_threshold(thresholds.get("air_pollution_exposure"), 0.6)
    service = _format_threshold(thresholds.get("service_accessibility"), 0.5)
    return {
        "increase_green_infrastructure": {
            "business_meaning": "increase green/cooling infrastructure for high heat-risk units",
            "state_trigger": f"heat_risk >= {heat}",
            "expected_primary_effect": "decrease heat_risk and improve livability/equity through the simulator",
        },
        "traffic_emission_control": {
            "business_meaning": "apply traffic-emission controls for high pollution-exposure units",
            "state_trigger": f"air_pollution_exposure >= {air}",
            "expected_primary_effect": "decrease air_pollution_exposure through the simulator",
        },
        "add_community_service": {
            "business_meaning": "add or improve community services for low-accessibility units",
            "state_trigger": f"service_accessibility <= {service}",
            "expected_primary_effect": "increase service_accessibility and equity through the simulator",
        },
    }


def _target_features(node: dict[str, Any]) -> dict[str, float]:
    features = node.get("features") or {}
    return {
        "heat_risk": _float(features.get("heat_risk")),
        "air_pollution_exposure": _float(features.get("air_pollution_exposure")),
        "service_accessibility": _float(features.get("service_accessibility")),
        "equity": _float(features.get("equity")),
        "livability": _float(features.get("livability")),
    }


def _split_admin_unit_id(unit_id: str) -> tuple[str, str, str]:
    parts = unit_id.split("|")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return unit_id, "", ""


def _format_threshold(value: Any, default: float) -> str:
    return f"{_float(value, default=default):g}"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return round(float(value), 9)
    except (TypeError, ValueError):
        return float(default)
