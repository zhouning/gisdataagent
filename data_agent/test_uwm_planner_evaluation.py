import pytest

from data_agent.uwm.evaluation import evaluate_planner_advantage_over_static_heuristic


def _rollout(action_id, *, livability, equity):
    return {
        "schema": "uwm.rollout_trace.v1",
        "initial_state_ref": "uwm-obs-planner-eval-001",
        "action_sequence": [
            {
                "action_id": action_id,
                "action_type": "service_accessibility_improvement",
                "target_units": ["grid-1"],
                "intensity": 0.5,
            }
        ],
        "scenario": {"scenario_id": "heatwave_day"},
        "backend": "mechanistic_urban_livability_v0",
        "future_state_delta": {"changed_units": 1, "aggregate": {"livability_delta": livability}},
        "heat_risk_delta": -0.02,
        "air_pollution_exposure_delta": -0.01,
        "service_accessibility_delta": 0.06,
        "equity_delta": equity,
        "livability_delta": livability,
        "uncertainty_interval": {"low": livability - 0.02, "high": livability + 0.02},
        "evidence_grade": "bounded_support",
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "simulator_trace": [
            {"step": "validate_observation_contract", "valid": True, "errors": []},
            {"step": "apply_action_effects", "action_id": action_id},
            {"step": "aggregate_rollout_delta", "evidence_grade": "bounded_support"},
        ],
    }


def test_planner_advantage_evaluation_measures_known_effect_regret_reduction():
    report = evaluate_planner_advantage_over_static_heuristic(
        rollout_traces=[
            _rollout("static-heat-hotspot-action", livability=0.03, equity=0.01),
            _rollout("uwm-equity-service-action", livability=0.04, equity=0.08),
            _rollout("low-benefit-action", livability=0.01, equity=0.02),
        ],
        static_heuristic_action_id="static-heat-hotspot-action",
        planning_goal="reduce_heat_and_improve_equity",
        constraints={
            "min_livability_delta": 0.005,
            "require_non_negative_equity": True,
            "max_uncertainty_width": 0.20,
            "allowed_evidence_grades": ["bounded_support"],
        },
    )

    assert report["schema"] == "uwm.planner_advantage_evaluation.v1"
    assert report["static_heuristic"]["action_id"] == "static-heat-hotspot-action"
    assert report["static_heuristic"]["decision_basis"] == "static_indicator_priority"
    assert report["world_model_planner"]["action_id"] == "uwm-equity-service-action"
    assert report["world_model_planner"]["decision_basis"] == "simulator_rollout_trace"
    assert report["known_effect_regret_reduction"] > 0
    assert report["planner_advantage_over_static_heuristic"] is True
    assert report["empirical_superiority_claim"] is False
    assert report["supported_claim"] == "known_effect_planner_advantage_over_static_heuristic"
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def test_planner_advantage_evaluation_requires_static_action_rollout():
    with pytest.raises(ValueError, match="static heuristic action must have a rollout trace"):
        evaluate_planner_advantage_over_static_heuristic(
            rollout_traces=[_rollout("uwm-equity-service-action", livability=0.04, equity=0.08)],
            static_heuristic_action_id="missing-static-action",
            planning_goal="reduce_heat_and_improve_equity",
        )
