"""Evaluation gates for comparing UWM with traditional livability methods."""

from __future__ import annotations

from typing import Any

from .baseline import compute_traditional_livability_baseline
from .planner import build_evidence_gated_plan
from .simulator import simulate_livability_rollout


UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA = "uwm.dynamic_advantage_evaluation.v1"
UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA = "uwm.planner_advantage_evaluation.v1"


def evaluate_dynamic_advantage_over_static_baseline(
    *,
    observation: dict[str, Any],
    baseline_records: list[dict[str, Any]],
    indicators: dict[str, dict[str, Any]],
    action_sequence: list[dict[str, Any]],
    scenario: dict[str, Any],
    negative_control_tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Evaluate whether UWM beats a static indicator baseline on dynamic tasks.

    The supported claim is intentionally narrow: a successful report proves
    action-conditioned dynamic advantage on a known-effect benchmark, not
    empirical predictive superiority on observed holdout outcomes.
    """

    baseline = compute_traditional_livability_baseline(baseline_records, indicators)
    rollout = simulate_livability_rollout(observation, action_sequence, scenario=scenario)
    negative_control = simulate_livability_rollout(
        observation,
        [_negative_control_action(action_sequence)],
        scenario={**scenario, "negative_control": True},
    )

    baseline_action_response = 0.0
    world_model_action_response = float(rollout["livability_delta"])
    dynamic_action_response_passed = (
        world_model_action_response > baseline_action_response
        and rollout.get("evidence_grade") != "not_for_claim"
    )
    negative_control_passed = abs(float(negative_control["livability_delta"])) <= negative_control_tolerance
    trace_passed = _trace_complete(rollout)
    architectural_superiority = dynamic_action_response_passed and negative_control_passed and trace_passed
    evidence_grade = str(rollout.get("evidence_grade") or "not_for_claim")

    return {
        "schema": UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA,
        "traditional_baseline": {
            "method": baseline["method"],
            "action_conditioned": baseline["action_conditioned"],
            "dynamic_rollout": baseline["dynamic_rollout"],
            "score_count": len(baseline["scores"]),
            "action_response_delta": baseline_action_response,
            "limitations": baseline["limitations"],
        },
        "world_model": {
            "backend": rollout["backend"],
            "action_response_delta": world_model_action_response,
            "evidence_grade": evidence_grade,
            "rollout_trace": rollout,
            "negative_control_livability_delta": negative_control["livability_delta"],
        },
        "checks": {
            "dynamic_action_response": {
                "passed": dynamic_action_response_passed,
                "baseline_delta": baseline_action_response,
                "uwm_delta": world_model_action_response,
            },
            "negative_control_stability": {
                "passed": negative_control_passed,
                "tolerance": negative_control_tolerance,
                "negative_control_delta": negative_control["livability_delta"],
            },
            "trace_completeness": {
                "passed": trace_passed,
                "required_steps": [
                    "validate_observation_contract",
                    "apply_action_effects",
                    "aggregate_rollout_delta",
                ],
                "observed_steps": [step.get("step") for step in rollout.get("simulator_trace") or []],
            },
        },
        "architectural_superiority_over_static_baseline": architectural_superiority,
        "empirical_superiority_claim": False,
        "supported_claim": _supported_claim(architectural_superiority, evidence_grade),
        "claim_boundary": {
            "max_claim_level": evidence_grade if architectural_superiority else "not_for_claim",
            "reason": _claim_reason(architectural_superiority, evidence_grade),
        },
        "remaining_gates": [
            "holdout_observed_outcomes_required",
            "external_city_validation_required",
            "causal_identification_or_counterfactual_validation_required",
            "planner_regret_test_required",
        ],
    }


def evaluate_planner_advantage_over_static_heuristic(
    *,
    rollout_traces: list[dict[str, Any]],
    static_heuristic_action_id: str,
    planning_goal: str,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare UWM planner choice with a traditional static heuristic action.

    The comparison uses known-effect rollout traces. It measures decision
    regret reduction under the simulator, not observed policy outcome superiority.
    """

    static_rollout = _find_rollout_by_action_id(rollout_traces, static_heuristic_action_id)
    if static_rollout is None:
        raise ValueError("static heuristic action must have a rollout trace")

    plan = build_evidence_gated_plan(
        rollout_traces,
        planning_goal=planning_goal,
        constraints=constraints,
        max_recommendations=1,
    )
    planner_action = plan["recommended_actions"][0]
    static_livability_delta = _safe_float(static_rollout.get("livability_delta"))
    planner_livability_delta = _safe_float(planner_action.get("livability_delta"))
    known_effect_regret_reduction = planner_livability_delta - static_livability_delta
    planner_advantage = known_effect_regret_reduction > 0
    evidence_grade = str(plan.get("evidence_grade") or "not_for_claim")
    return {
        "schema": UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA,
        "planning_goal": planning_goal,
        "static_heuristic": {
            "action_id": static_heuristic_action_id,
            "decision_basis": "static_indicator_priority",
            "livability_delta": static_livability_delta,
            "equity_delta": _safe_float(static_rollout.get("equity_delta")),
        },
        "world_model_planner": {
            "action_id": planner_action["action_id"],
            "decision_basis": planner_action["decision_basis"],
            "livability_delta": planner_livability_delta,
            "equity_delta": _safe_float(planner_action.get("equity_delta")),
            "score": _safe_float(planner_action.get("score")),
            "plan_package": plan,
        },
        "known_effect_regret_reduction": known_effect_regret_reduction,
        "planner_advantage_over_static_heuristic": planner_advantage,
        "empirical_superiority_claim": False,
        "supported_claim": _planner_supported_claim(planner_advantage, evidence_grade),
        "claim_boundary": {
            "max_claim_level": evidence_grade if planner_advantage else "not_for_claim",
            "reason": _planner_claim_reason(planner_advantage, evidence_grade),
        },
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "planner_regret_external_city_validation_required",
            "causal_policy_effect_validation_required",
        ],
    }


def _negative_control_action(action_sequence: list[dict[str, Any]]) -> dict[str, Any]:
    first_action = action_sequence[0] if action_sequence else {}
    return {
        "action_id": "negative-control-no-intervention",
        "action_type": "observe_only_no_intervention",
        "target_units": first_action.get("target_units", []),
        "intensity": first_action.get("intensity", 1.0),
    }


def _trace_complete(rollout: dict[str, Any]) -> bool:
    steps = {step.get("step") for step in rollout.get("simulator_trace") or []}
    return {
        "validate_observation_contract",
        "apply_action_effects",
        "aggregate_rollout_delta",
    }.issubset(steps)


def _supported_claim(architectural_superiority: bool, evidence_grade: str) -> str:
    if not architectural_superiority:
        return "no_superiority_claim_supported"
    if evidence_grade == "exploratory_only":
        return "exploratory_known_effect_dynamic_advantage_only"
    return "known_effect_dynamic_advantage_over_static_baseline"


def _claim_reason(architectural_superiority: bool, evidence_grade: str) -> str:
    if not architectural_superiority:
        return "one or more dynamic evaluation gates failed"
    if evidence_grade == "exploratory_only":
        return "dynamic advantage is shown only on exploratory or synthetic-supported inputs"
    return "UWM responds to interventions and passes negative-control trace gates; empirical holdout gates remain open"


def _find_rollout_by_action_id(
    rollout_traces: list[dict[str, Any]],
    action_id: str,
) -> dict[str, Any] | None:
    for rollout in rollout_traces:
        actions = rollout.get("action_sequence") if isinstance(rollout, dict) else None
        if isinstance(actions, list) and actions and actions[0].get("action_id") == action_id:
            return rollout
    return None


def _planner_supported_claim(planner_advantage: bool, evidence_grade: str) -> str:
    if not planner_advantage:
        return "no_planner_advantage_claim_supported"
    if evidence_grade == "exploratory_only":
        return "exploratory_known_effect_planner_advantage_only"
    return "known_effect_planner_advantage_over_static_heuristic"


def _planner_claim_reason(planner_advantage: bool, evidence_grade: str) -> str:
    if not planner_advantage:
        return "UWM planner did not reduce known-effect regret versus the static heuristic"
    if evidence_grade == "exploratory_only":
        return "planner advantage depends on exploratory or synthetic-supported rollout traces"
    return "planner reduces known-effect regret under simulator traces; observed policy outcome gates remain open"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
