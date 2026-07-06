from data_agent.uwm.admin_planner_benchmark import (
    UWM_ADMIN_PLANNER_BENCHMARK_SCHEMA,
    build_admin_planner_benchmark,
    build_admin_target_observation_from_exposure_panel,
)
from data_agent.uwm.contracts import validate_uwm_observation


def _panel():
    return {
        "schema": "uwm.admin_exposure_equity_panel.v1",
        "panel_id": "panel-test",
        "target_units": [
            {
                "admin_unit_id": "A|one|0",
                "county": "A",
                "township": "one",
                "priority_score": 0.9,
                "priority_flags": ["high_pm25_proxy", "top_priority_proxy_unit"],
                "target_candidate": False,
            },
            {
                "admin_unit_id": "B|two|1",
                "county": "B",
                "township": "two",
                "priority_score": 0.8,
                "priority_flags": ["high_heat_proxy", "top_priority_proxy_unit"],
                "target_candidate": False,
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["priority_score_is_proxy_targeting_not_policy_effect"],
        "empirical_superiority_claim": False,
    }


def test_build_admin_target_observation_from_exposure_panel_is_valid_world_model_state():
    observation = build_admin_target_observation_from_exposure_panel(
        _panel(),
        observation_id="uwm-admin-target-obs-test",
        created_at="2026-07-05T13:10:00Z",
        max_units=2,
    )

    validation = validate_uwm_observation(observation)
    assert validation["valid"], validation["errors"]
    assert observation["schema"] == "uwm.canonical_observation.v1"
    assert [unit["unit_id"] for unit in observation["spatial_units"]] == ["A|one|0", "B|two|1"]
    assert observation["spatial_units"][0]["priority_score"] == 0.9
    assert observation["synthetic_flags"] == [
        {"dataset_id": "admin_exposure_equity_panel_2024_07", "status": "public_proxy"}
    ]
    assert observation["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_admin_planner_benchmark_shows_known_effect_advantage_over_static_priority_heuristic():
    benchmark = build_admin_planner_benchmark(
        exposure_equity_panel=_panel(),
        scenario={
            "scenario_id": "admin-livability-test",
            "heat_stress_multiplier": 1.1,
            "air_pollution_stress_multiplier": 1.05,
            "vulnerability_multiplier": 1.2,
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "empirical_superiority_claim": False,
        },
        benchmark_id="uwm-admin-planner-benchmark-test",
        created_at="2026-07-05T13:15:00Z",
        max_units=2,
    )

    assert benchmark["schema"] == UWM_ADMIN_PLANNER_BENCHMARK_SCHEMA
    assert benchmark["static_heuristic_action_id"] == "static-priority-traffic-control::A|one|0"
    assert benchmark["rollout_count"] == 7
    assert benchmark["planner_advantage"]["planner_advantage_over_static_heuristic"] is True
    assert benchmark["planner_advantage"]["known_effect_regret_reduction"] > 0
    assert benchmark["planner_advantage"]["empirical_superiority_claim"] is False
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"
