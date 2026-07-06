from data_agent.uwm.scene_state import (
    UWM_SCENE_STATE_SCHEMA,
    build_scene_state_from_proxy_artifacts,
    derive_simulator_scenario_from_scene_state,
    validate_scene_state,
)


def test_build_scene_state_from_proxy_artifacts_derives_traceable_stress_controls():
    observations = [
        {
            "schema": "uwm.canonical_observation.v1",
            "observation_id": "uwm-ghsl-admin-obs-2020",
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "synthetic_flags": [{"dataset_id": "ghsl_admin_zonal_proxy_alignment", "status": "public_proxy"}],
        },
        {
            "schema": "uwm.canonical_observation.v1",
            "observation_id": "uwm-openmeteo-history-obs-2024-07-01-07",
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "synthetic_flags": [
                {"dataset_id": "openmeteo_weather_historical_point_proxy", "status": "public_proxy"},
                {"dataset_id": "openmeteo_air_quality_historical_point_proxy", "status": "public_proxy"},
            ],
        },
    ]
    ghsl_alignment = {"dataset_id": "ghsl_admin_zonal_proxy_alignment", "admin_feature_count": 3}
    ghsl_rows = [
        {"population_proxy_sum": "100", "built_surface_proxy_sum": "50"},
        {"population_proxy_sum": "300", "built_surface_proxy_sum": "150"},
        {"population_proxy_sum": "0", "built_surface_proxy_sum": "0"},
    ]
    openmeteo_proxy = {
        "schema": "uwm.openmeteo_historical_environmental_proxy.v1",
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "meteorology_summary": {"temperature_2m_mean_avg_c": 30.0, "precipitation_sum_total_mm": 40.0},
        "air_pollution_summary": {"pm25_avg_ugm3": 45.0, "no2_avg_ugm3": 36.0},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["not_station_calibrated_holdout"],
        "empirical_superiority_claim": False,
    }

    scene_state = build_scene_state_from_proxy_artifacts(
        observations=observations,
        ghsl_alignment=ghsl_alignment,
        ghsl_zonal_rows=ghsl_rows,
        openmeteo_proxy=openmeteo_proxy,
        scene_id="uwm-scene-test",
        created_at="2026-07-05T02:30:00Z",
    )

    validation = validate_scene_state(scene_state)
    assert validation["valid"], validation["errors"]
    assert scene_state["schema"] == UWM_SCENE_STATE_SCHEMA
    assert scene_state["scene_id"] == "uwm-scene-test"
    assert scene_state["source_observation_ids"] == [
        "uwm-ghsl-admin-obs-2020",
        "uwm-openmeteo-history-obs-2024-07-01-07",
    ]
    assert scene_state["population_context"]["admin_unit_count"] == 3
    assert scene_state["population_context"]["nonzero_population_unit_count"] == 2
    assert scene_state["environmental_context"]["pm25_avg_ugm3"] == 45.0
    assert scene_state["scenario_controls"]["heat_stress_multiplier"] > 1.0
    assert scene_state["scenario_controls"]["air_pollution_stress_multiplier"] > 1.0
    assert scene_state["scenario_controls"]["vulnerability_multiplier"] > 1.0
    assert scene_state["empirical_superiority_claim"] is False
    assert "not_station_calibrated_holdout" in scene_state["limitations"]


def test_derive_simulator_scenario_from_scene_state_preserves_source_and_claim_boundary():
    scene_state = {
        "schema": UWM_SCENE_STATE_SCHEMA,
        "scene_id": "uwm-scene-test",
        "source_observation_ids": ["uwm-ghsl-admin-obs-2020", "uwm-openmeteo-history-obs-2024-07-01-07"],
        "population_context": {"admin_unit_count": 3},
        "environmental_context": {"time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"}},
        "scenario_controls": {
            "heat_stress_multiplier": 1.25,
            "air_pollution_stress_multiplier": 1.10,
            "vulnerability_multiplier": 1.05,
        },
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["not_station_calibrated_holdout"],
        "empirical_superiority_claim": False,
        "scene_trace": [{"step": "derive_simulator_controls"}],
    }

    scenario = derive_simulator_scenario_from_scene_state(scene_state, scenario_id="livability_heat_air_episode")

    assert scenario["scenario_id"] == "livability_heat_air_episode"
    assert scenario["source_scene_state_id"] == "uwm-scene-test"
    assert scenario["heat_stress_multiplier"] == 1.25
    assert scenario["air_pollution_stress_multiplier"] == 1.10
    assert scenario["vulnerability_multiplier"] == 1.05
    assert scenario["empirical_superiority_claim"] is False
