import pytest

from data_agent.uwm.contracts import validate_uwm_plan_package
from data_agent.uwm.planner import build_evidence_gated_plan


def _rollout(action_id, *, livability, equity, uncertainty_width=0.04, evidence_grade="bounded_support"):
    uncertainty_center = livability
    return {
        "schema": "uwm.rollout_trace.v1",
        "initial_state_ref": "uwm-obs-plan-001",
        "action_sequence": [
            {
                "action_id": action_id,
                "action_type": "increase_green_infrastructure",
                "target_units": ["grid-1"],
                "intensity": 0.5,
            }
        ],
        "scenario": {"scenario_id": "heatwave_day"},
        "backend": "mechanistic_urban_livability_v0",
        "future_state_delta": {"changed_units": 2, "aggregate": {"livability_delta": livability}},
        "heat_risk_delta": -0.08,
        "air_pollution_exposure_delta": -0.02,
        "service_accessibility_delta": 0.01,
        "equity_delta": equity,
        "livability_delta": livability,
        "uncertainty_interval": {
            "low": uncertainty_center - uncertainty_width / 2,
            "high": uncertainty_center + uncertainty_width / 2,
        },
        "evidence_grade": evidence_grade,
        "claim_boundary": {"max_claim_level": evidence_grade},
        "simulator_trace": [
            {"step": "validate_observation_contract", "valid": True, "errors": []},
            {"step": "apply_action_effects", "action_id": action_id},
            {"step": "aggregate_rollout_delta", "evidence_grade": evidence_grade},
        ],
    }


def test_planner_recommends_only_admissible_rollout_traces():
    rollouts = [
        _rollout("green-grid-1", livability=0.05, equity=0.03),
        _rollout("service-grid-2", livability=0.04, equity=0.08),
        _rollout("risky-high-uncertainty", livability=0.12, equity=0.05, uncertainty_width=0.50),
        _rollout("inequitable-speedup", livability=0.07, equity=-0.04),
        _rollout("not-for-claim-action", livability=0.20, equity=0.20, evidence_grade="not_for_claim"),
    ]

    plan = build_evidence_gated_plan(
        rollouts,
        planning_goal="reduce_heat_and_improve_equity",
        constraints={
            "min_livability_delta": 0.01,
            "require_non_negative_equity": True,
            "max_uncertainty_width": 0.20,
            "allowed_evidence_grades": ["bounded_support"],
        },
    )
    validation = validate_uwm_plan_package(plan)

    assert validation["valid"], validation["errors"]
    assert plan["schema"] == "uwm.plan_package.v1"
    assert plan["recommended_actions"][0]["action_id"] == "service-grid-2"
    assert plan["recommended_actions"][0]["decision_basis"] == "simulator_rollout_trace"
    assert plan["recommended_actions"][0]["score"] > 0
    assert {item["action_id"] for item in plan["rejected_actions"]} == {
        "risky-high-uncertainty",
        "inequitable-speedup",
        "not-for-claim-action",
    }
    assert any(item["reason"] == "uncertainty_width_exceeds_constraint" for item in plan["rejected_actions"])
    assert any(item["reason"] == "negative_equity_delta" for item in plan["rejected_actions"])
    assert any(item["reason"] == "evidence_grade_not_allowed" for item in plan["rejected_actions"])
    assert plan["expected_benefits"]["livability_delta"] == plan["recommended_actions"][0]["livability_delta"]
    assert plan["equity_effects"]["equity_delta"] == plan["recommended_actions"][0]["equity_delta"]
    assert plan["human_review_required"] is True
    assert plan["planner_trace"][0]["step"] == "validate_rollout_traces"
    assert any(step["step"] == "rank_admissible_actions" for step in plan["planner_trace"])


def test_planner_refuses_raw_actions_without_rollout_trace():
    with pytest.raises(ValueError, match="planner requires valid UwmRolloutTrace.v1 inputs"):
        build_evidence_gated_plan(
            [{"action_id": "raw-green-action"}],
            planning_goal="reduce_heat_and_improve_equity",
        )
