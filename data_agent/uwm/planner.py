"""Evidence-gated planner for Urban World Model rollouts."""

from __future__ import annotations

from typing import Any

from .contracts import UWM_PLAN_PACKAGE_SCHEMA, validate_uwm_rollout_trace


DEFAULT_PLANNER_BACKEND = "evidence_gated_rollout_planner_v0"


def build_evidence_gated_plan(
    rollout_traces: list[dict[str, Any]],
    *,
    planning_goal: str,
    constraints: dict[str, Any] | None = None,
    max_recommendations: int = 3,
) -> dict[str, Any]:
    """Build a plan package strictly from simulator rollout traces."""

    constraints = constraints or {}
    valid_candidates: list[dict[str, Any]] = []
    rejected_actions: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []

    for index, rollout in enumerate(rollout_traces):
        validation = validate_uwm_rollout_trace(rollout)
        action_id = _action_id(rollout, fallback=f"candidate-{index + 1}")
        if not validation["valid"]:
            validation_errors.append({"index": index, "action_id": action_id, "errors": validation["errors"]})
            rejected_actions.append(
                {
                    "action_id": action_id,
                    "reason": "invalid_rollout_trace",
                    "errors": validation["errors"],
                }
            )
            continue
        rejection_reason = _constraint_rejection_reason(rollout, constraints)
        if rejection_reason:
            rejected_actions.append(
                {
                    "action_id": action_id,
                    "reason": rejection_reason,
                    "evidence_grade": rollout.get("evidence_grade"),
                    "livability_delta": _float(rollout.get("livability_delta")),
                    "equity_delta": _float(rollout.get("equity_delta")),
                    "uncertainty_width": _uncertainty_width(rollout),
                }
            )
            continue
        valid_candidates.append(_candidate_from_rollout(rollout))

    if not valid_candidates:
        if validation_errors and len(validation_errors) == len(rollout_traces):
            raise ValueError("planner requires valid UwmRolloutTrace.v1 inputs")
        raise ValueError("no admissible rollout traces after evidence gates")

    valid_candidates.sort(key=lambda item: item["score"], reverse=True)
    recommended_actions = valid_candidates[:max_recommendations]
    best_action = recommended_actions[0]
    evidence_grade = _plan_evidence_grade(recommended_actions)
    data_gaps = _data_gaps(recommended_actions)
    return {
        "schema": UWM_PLAN_PACKAGE_SCHEMA,
        "planning_goal": planning_goal,
        "recommended_actions": recommended_actions,
        "rejected_actions": rejected_actions,
        "rollout_traces": [item["rollout_ref"] for item in recommended_actions],
        "expected_benefits": {
            "livability_delta": best_action["livability_delta"],
            "heat_risk_delta": best_action["heat_risk_delta"],
            "air_pollution_exposure_delta": best_action["air_pollution_exposure_delta"],
            "service_accessibility_delta": best_action["service_accessibility_delta"],
        },
        "equity_effects": {"equity_delta": best_action["equity_delta"]},
        "risk_flags": _risk_flags(recommended_actions, rejected_actions),
        "evidence_grade": evidence_grade,
        "data_gaps": data_gaps,
        "human_review_required": True,
        "claim_boundary": {
            "max_claim_level": evidence_grade,
            "reason": "planner recommendations are bounded by simulator rollout evidence and hard constraints",
        },
        "planner_trace": [
            {
                "step": "validate_rollout_traces",
                "input_count": len(rollout_traces),
                "valid_count": len(valid_candidates),
                "rejected_count": len(rejected_actions),
            },
            {
                "step": "apply_hard_constraints",
                "constraints": constraints,
            },
            {
                "step": "rank_admissible_actions",
                "backend": DEFAULT_PLANNER_BACKEND,
                "recommended_count": len(recommended_actions),
            },
        ],
    }


def _constraint_rejection_reason(rollout: dict[str, Any], constraints: dict[str, Any]) -> str | None:
    allowed = constraints.get("allowed_evidence_grades")
    if allowed is not None and rollout.get("evidence_grade") not in set(allowed):
        return "evidence_grade_not_allowed"
    if rollout.get("evidence_grade") == "not_for_claim":
        return "evidence_grade_not_allowed"
    if constraints.get("require_non_negative_equity") and _float(rollout.get("equity_delta")) < 0:
        return "negative_equity_delta"
    min_livability = constraints.get("min_livability_delta")
    if min_livability is not None and _float(rollout.get("livability_delta")) < _float(min_livability):
        return "livability_delta_below_constraint"
    max_uncertainty_width = constraints.get("max_uncertainty_width")
    if max_uncertainty_width is not None and _uncertainty_width(rollout) > _float(max_uncertainty_width):
        return "uncertainty_width_exceeds_constraint"
    return None


def _candidate_from_rollout(rollout: dict[str, Any]) -> dict[str, Any]:
    action = rollout["action_sequence"][0]
    livability_delta = _float(rollout.get("livability_delta"))
    equity_delta = _float(rollout.get("equity_delta"))
    uncertainty_width = _uncertainty_width(rollout)
    score = livability_delta + 0.50 * equity_delta - 0.10 * uncertainty_width
    return {
        "action_id": _action_id(rollout),
        "action_type": action.get("action_type"),
        "target_units": action.get("target_units", []),
        "decision_basis": "simulator_rollout_trace",
        "rollout_ref": _rollout_ref(rollout),
        "score": score,
        "livability_delta": livability_delta,
        "heat_risk_delta": _float(rollout.get("heat_risk_delta")),
        "air_pollution_exposure_delta": _float(rollout.get("air_pollution_exposure_delta")),
        "service_accessibility_delta": _float(rollout.get("service_accessibility_delta")),
        "equity_delta": equity_delta,
        "uncertainty_width": uncertainty_width,
        "evidence_grade": rollout.get("evidence_grade"),
    }


def _plan_evidence_grade(recommended_actions: list[dict[str, Any]]) -> str:
    grades = {str(action.get("evidence_grade")) for action in recommended_actions}
    for grade in ["not_for_claim", "exploratory_only", "fragile", "bounded_support", "core_support"]:
        if grade in grades:
            return grade
    return "bounded_support"


def _risk_flags(
    recommended_actions: list[dict[str, Any]],
    rejected_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if any(action.get("evidence_grade") != "core_support" for action in recommended_actions):
        flags.append({"level": "warning", "message": "recommendations require human review before policy use"})
    if rejected_actions:
        flags.append({"level": "info", "message": "some candidate actions were rejected by evidence gates"})
    return flags


def _data_gaps(recommended_actions: list[dict[str, Any]]) -> list[str]:
    gaps = []
    if any(action.get("evidence_grade") == "bounded_support" for action in recommended_actions):
        gaps.append("observed_holdout_outcomes_for_planner_regret")
    if any(action.get("evidence_grade") == "exploratory_only" for action in recommended_actions):
        gaps.append("replace_synthetic_or_exploratory_inputs")
    return gaps


def _action_id(rollout: dict[str, Any], *, fallback: str = "unknown-action") -> str:
    actions = rollout.get("action_sequence") if isinstance(rollout, dict) else None
    if isinstance(actions, list) and actions and isinstance(actions[0], dict):
        return str(actions[0].get("action_id") or fallback)
    return str(rollout.get("action_id") or fallback) if isinstance(rollout, dict) else fallback


def _rollout_ref(rollout: dict[str, Any]) -> str:
    return f"{rollout.get('initial_state_ref')}::{_action_id(rollout)}::{(rollout.get('scenario') or {}).get('scenario_id')}"


def _uncertainty_width(rollout: dict[str, Any]) -> float:
    interval = rollout.get("uncertainty_interval") or {}
    return _float(interval.get("high")) - _float(interval.get("low"))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
