"""Admin-unit planner benchmark built from UWM exposure-equity proxy targets."""

from __future__ import annotations

from typing import Any

from .evaluation import evaluate_planner_advantage_over_static_heuristic
from .simulator import simulate_livability_rollout


UWM_ADMIN_PLANNER_BENCHMARK_SCHEMA = "uwm.admin_planner_benchmark.v1"


def build_admin_target_observation_from_exposure_panel(
    exposure_equity_panel: dict[str, Any],
    *,
    observation_id: str,
    created_at: str,
    max_units: int = 10,
) -> dict[str, Any]:
    """Build a canonical observation over top admin proxy target units."""

    target_units = list(exposure_equity_panel.get("target_units") or [])[:max_units]
    spatial_units = [
        {
            "unit_id": str(unit.get("admin_unit_id")),
            "unit_type": "admin_exposure_equity_proxy_unit",
            "county": unit.get("county"),
            "township": unit.get("township"),
            "priority_score": _float(unit.get("priority_score")),
            "priority_flags": list(unit.get("priority_flags") or []),
            "target_candidate": bool(unit.get("target_candidate")),
        }
        for unit in target_units
        if unit.get("admin_unit_id")
    ]
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": observation_id,
        "created_at": created_at,
        "spatial_units": spatial_units,
        "object_layers": [],
        "raster_features": [
            {
                "feature_id": "admin_exposure_equity_priority",
                "role": "admin_exposure_equity_panel",
                "uwm_role": "planner_targeting",
                "source_dataset_id": "admin_exposure_equity_panel_2024_07",
            }
        ],
        "graph_edges": [],
        "temporal_index": {
            "source_created_at": exposure_equity_panel.get("created_at"),
            "observation_created_at": created_at,
        },
        "quality_flags": [
            {"level": "info", "message": "admin target observation derived from exposure-equity proxy panel"},
            *[
                {"level": "warning", "message": str(limitation)}
                for limitation in exposure_equity_panel.get("limitations") or []
            ],
        ],
        "synthetic_flags": [{"dataset_id": "admin_exposure_equity_panel_2024_07", "status": "public_proxy"}],
        "provenance": {
            "source_panel_id": exposure_equity_panel.get("panel_id"),
            "source_schema": exposure_equity_panel.get("schema"),
        },
        "claim_boundary": {
            "max_claim_level": (exposure_equity_panel.get("claim_boundary") or {}).get(
                "max_claim_level",
                "bounded_support",
            ),
            "reason": "admin target observation supports bounded simulator/planner benchmark only",
        },
        "renderer_trace": [
            {
                "step": "load_admin_exposure_equity_panel",
                "target_unit_count": len(spatial_units),
            },
            {
                "step": "derive_admin_target_observation",
                "source_panel_id": exposure_equity_panel.get("panel_id"),
            },
        ],
    }


def build_admin_planner_benchmark(
    *,
    exposure_equity_panel: dict[str, Any],
    scenario: dict[str, Any],
    benchmark_id: str,
    created_at: str,
    max_units: int = 10,
) -> dict[str, Any]:
    """Build rollout traces and planner-regret comparison for admin proxy targets."""

    observation = build_admin_target_observation_from_exposure_panel(
        exposure_equity_panel,
        observation_id=f"{benchmark_id}-observation",
        created_at=created_at,
        max_units=max_units,
    )
    target_unit_ids = [unit["unit_id"] for unit in observation["spatial_units"]]
    if not target_unit_ids:
        raise ValueError("admin planner benchmark requires at least one target unit")
    static_action = _static_heuristic_action(target_unit_ids[0])
    candidate_actions = [static_action]
    for unit_id in target_unit_ids:
        candidate_actions.extend(_uwm_candidate_actions(unit_id))
    rollout_traces = [
        simulate_livability_rollout(observation, [action], scenario=scenario)
        for action in candidate_actions
    ]
    planner_advantage = evaluate_planner_advantage_over_static_heuristic(
        rollout_traces=rollout_traces,
        static_heuristic_action_id=static_action["action_id"],
        planning_goal="admin_livability_targeting_known_effect_regret",
        constraints={
            "min_livability_delta": 0.0,
            "require_non_negative_equity": True,
            "max_uncertainty_width": 0.25,
            "allowed_evidence_grades": ["bounded_support"],
        },
    )
    return {
        "schema": UWM_ADMIN_PLANNER_BENCHMARK_SCHEMA,
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "source_panel_id": exposure_equity_panel.get("panel_id"),
        "observation": observation,
        "scenario": scenario,
        "static_heuristic_action_id": static_action["action_id"],
        "rollout_count": len(rollout_traces),
        "rollout_traces": rollout_traces,
        "planner_advantage": planner_advantage,
        "claim_boundary": {
            "max_claim_level": planner_advantage["claim_boundary"]["max_claim_level"],
            "reason": "benchmark compares UWM rollout planner with static proxy-priority heuristic on known-effect simulator traces",
        },
        "remaining_gates": planner_advantage["remaining_gates"],
        "empirical_superiority_claim": False,
    }


def _static_heuristic_action(unit_id: str) -> dict[str, Any]:
    return {
        "action_id": f"static-priority-traffic-control::{unit_id}",
        "action_type": "traffic_emission_control",
        "target_units": [unit_id],
        "intensity": 0.5,
        "decision_basis": "static_top_priority_proxy_unit",
    }


def _uwm_candidate_actions(unit_id: str) -> list[dict[str, Any]]:
    return [
        {
            "action_id": f"uwm-traffic-emission-control::{unit_id}",
            "action_type": "traffic_emission_control",
            "target_units": [unit_id],
            "intensity": 0.5,
        },
        {
            "action_id": f"uwm-urban-greening::{unit_id}",
            "action_type": "urban_greening",
            "target_units": [unit_id],
            "intensity": 0.5,
        },
        {
            "action_id": f"uwm-service-accessibility-improvement::{unit_id}",
            "action_type": "service_accessibility_improvement",
            "target_units": [unit_id],
            "intensity": 0.5,
        },
    ]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
