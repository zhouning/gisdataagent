"""Endpoint-aligned planner evaluator for UWM."""

from __future__ import annotations

from typing import Any


UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA = (
    "uwm.endpoint_aligned_planner_evaluator.v1"
)


def build_uwm_endpoint_aligned_planner_evaluator(
    *,
    evaluator_id: str,
    created_at: str,
    data_calibrated_planner_replay: dict[str, Any],
    livability_endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    """Score planner replay with validation-weighted final endpoint deltas."""

    endpoint_weights = {
        str(endpoint.get("endpoint_id")): _float(
            endpoint.get("relative_mae_reduction_vs_best_traditional")
        )
        for endpoint in livability_endpoint_suite.get("endpoint_evaluations") or []
    }
    admin_unit_count = max(1, _int(livability_endpoint_suite.get("admin_unit_count")))
    planner_sequence = data_calibrated_planner_replay.get("best_sequence") or {}
    static_sequence = (
        data_calibrated_planner_replay.get("static_single_step_baseline") or {}
    )
    planner_contributions = _endpoint_contributions(
        planner_sequence,
        endpoint_weights=endpoint_weights,
        admin_unit_count=admin_unit_count,
    )
    static_contributions = _endpoint_contributions(
        static_sequence,
        endpoint_weights=endpoint_weights,
        admin_unit_count=admin_unit_count,
    )
    planner_score = sum(planner_contributions.values())
    static_score = sum(static_contributions.values())
    advantage = planner_score - static_score
    ready = (
        livability_endpoint_suite.get("supported_claim")
        == "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
        and _int(livability_endpoint_suite.get("endpoint_count")) >= 3
        and planner_score > static_score
        and livability_endpoint_suite.get("observed_policy_outcome_superiority_claim")
        is False
    )
    supported_claim = (
        "endpoint_aligned_planner_replay_advantage_over_static_heuristic"
        if ready
        else "no_endpoint_aligned_planner_replay_advantage_claim_supported"
    )
    return {
        "schema": UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA,
        "evaluator_id": evaluator_id,
        "created_at": created_at,
        "evaluation_method": "endpoint_validation_weighted_rollout_delta",
        "source_planner_schema": data_calibrated_planner_replay.get("schema"),
        "source_endpoint_suite_schema": livability_endpoint_suite.get("schema"),
        "endpoint_count": _int(livability_endpoint_suite.get("endpoint_count")),
        "endpoint_weights": {
            key: round(value, 6) for key, value in endpoint_weights.items()
        },
        "delta_mapping": {
            "air_quality_pm25": {
                "rollout_delta": "air_pollution_exposure_delta",
                "positive_direction": "decrease",
            },
            "service_point_accessibility": {
                "rollout_delta": "service_accessibility_delta",
                "positive_direction": "increase",
            },
            "essential_service_accessibility": {
                "rollout_delta": "service_accessibility_delta",
                "positive_direction": "increase",
            },
        },
        "planner_sequence_action_count": _action_count(planner_sequence),
        "static_sequence_action_count": _action_count(static_sequence),
        "planner_endpoint_contributions": {
            key: round(value, 9) for key, value in planner_contributions.items()
        },
        "static_endpoint_contributions": {
            key: round(value, 9) for key, value in static_contributions.items()
        },
        "planner_endpoint_aligned_score": round(planner_score, 9),
        "static_endpoint_aligned_score": round(static_score, 9),
        "endpoint_aligned_advantage_over_static": round(advantage, 9),
        "endpoint_aligned_advantage_ratio": round(
            planner_score / static_score if static_score else 0.0,
            6,
        ),
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "planner replay is evaluated with validation-weighted final endpoint "
                "deltas from real prepared artifacts; this is not observed policy outcome"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _endpoint_contributions(
    sequence: dict[str, Any],
    *,
    endpoint_weights: dict[str, float],
    admin_unit_count: int,
) -> dict[str, float]:
    per_unit = (
        ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
            "per_unit"
        )
        or {}
    )
    totals = {
        "air_quality_pm25": 0.0,
        "service_point_accessibility": 0.0,
        "essential_service_accessibility": 0.0,
    }
    for delta in per_unit.values():
        air_improvement = max(0.0, -_float(delta.get("air_pollution_exposure_delta")))
        service_improvement = max(0.0, _float(delta.get("service_accessibility_delta")))
        totals["air_quality_pm25"] += air_improvement * endpoint_weights.get(
            "air_quality_pm25",
            0.0,
        )
        totals["service_point_accessibility"] += (
            service_improvement
            * endpoint_weights.get("service_point_accessibility", 0.0)
        )
        totals["essential_service_accessibility"] += (
            service_improvement
            * endpoint_weights.get("essential_service_accessibility", 0.0)
        )
    return {
        endpoint: value / admin_unit_count
        for endpoint, value in totals.items()
    }


def _action_count(sequence: dict[str, Any]) -> int:
    explicit_count = _int(sequence.get("action_count"), default=-1)
    if explicit_count >= 0:
        return explicit_count
    return len(sequence.get("action_sequence") or [])


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
