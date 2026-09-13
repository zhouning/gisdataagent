from data_agent.uwm.environmental_fusion import (
    UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA,
    build_environmental_evidence_bundle,
    validate_environmental_evidence_bundle,
)
from data_agent.uwm.scene_state import build_scene_state_from_proxy_artifacts, validate_scene_state


def _openmeteo_proxy():
    return {
        "schema": "uwm.openmeteo_historical_environmental_proxy.v1",
        "source_dataset_ids": [
            "openmeteo_weather_historical_point_proxy",
            "openmeteo_air_quality_historical_point_proxy",
        ],
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "record_counts": {"weather_hourly": 168, "weather_daily": 7, "air_quality_hourly": 168},
        "meteorology_summary": {
            "temperature_2m_mean_avg_c": 30.0,
            "precipitation_sum_total_mm": 20.0,
            "surface_pressure_avg_hpa": 970.0,
        },
        "air_pollution_summary": {"pm25_avg_ugm3": 40.0, "no2_avg_ugm3": 35.0},
        "limitations": ["not_station_calibrated_holdout"],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": False,
    }


def _gee_proxy():
    return {
        "schema": "uwm.gee_era5_cams_environmental_proxy.v1",
        "source_dataset_ids": ["gee_era5_hourly_chongqing_proxy", "gee_cams_nrt_chongqing_proxy"],
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "record_counts": {"era5_hourly": 168, "cams_hourly": 574},
        "meteorology_summary": {
            "temperature_2m_mean_avg_c": 28.0,
            "precipitation_total_mm": 10.0,
            "surface_pressure_avg_hpa": 962.0,
        },
        "air_pollution_summary": {"cams_pm25_avg_ugm3": 20.0, "cams_aod550_avg": 0.3},
        "limitations": ["gee_reanalysis_or_model_proxy_not_station_holdout"],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": False,
    }


def _openaq_proxy():
    return {
        "schema": "uwm.openaq_station_observation_proxy.v1",
        "source_dataset_ids": ["openaq_air_quality_station_observation_proxy"],
        "record_counts": {"locations": 15, "sensors": 90, "measurements": 600},
        "observed_time_range": {"start": "2018-10-17T12:00:00Z", "end": "2021-08-09T11:00:00Z"},
        "air_pollution_summary": {"pm25_avg_ugm3": 38.0, "pm10_avg_ugm3": 52.0},
        "scene_holdout_ready": False,
        "limitations": ["station_observations_not_aligned_to_scene_period"],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": False,
    }


def test_environmental_evidence_bundle_fuses_scene_sources_without_observed_holdout_overclaim():
    bundle = build_environmental_evidence_bundle(
        openmeteo_proxy=_openmeteo_proxy(),
        gee_proxy=_gee_proxy(),
        openaq_proxy=_openaq_proxy(),
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        bundle_id="uwm-env-evidence-test",
        created_at="2026-07-05T11:00:00Z",
    )

    validation = validate_environmental_evidence_bundle(bundle)
    assert validation["valid"], validation["errors"]
    assert bundle["schema"] == UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA
    assert bundle["scene_aligned_sources"] == [
        "openmeteo_weather_historical_point_proxy",
        "openmeteo_air_quality_historical_point_proxy",
        "gee_era5_hourly_chongqing_proxy",
        "gee_cams_nrt_chongqing_proxy",
    ]
    assert bundle["observed_holdout_sources"] == []
    assert bundle["meteorology_fusion"]["temperature_2m_mean_c"] == 29.0
    assert bundle["meteorology_fusion"]["precipitation_total_mm"] == 15.0
    assert bundle["air_pollution_fusion"]["pm25_scene_proxy_ugm3"] == 30.0
    assert bundle["air_pollution_fusion"]["pm25_observed_reference_ugm3"] == 38.0
    assert bundle["source_disagreement"]["pm25_scene_proxy_range_ugm3"] == 20.0
    assert "high_pm25_source_disagreement" in bundle["evidence_flags"]
    assert "observed_holdout_not_ready" in bundle["evidence_flags"]
    assert bundle["observed_holdout_ready"] is False
    assert bundle["empirical_superiority_claim"] is False


def test_scene_state_can_consume_environmental_evidence_bundle_for_world_model_controls():
    bundle = build_environmental_evidence_bundle(
        openmeteo_proxy=_openmeteo_proxy(),
        gee_proxy=_gee_proxy(),
        openaq_proxy=_openaq_proxy(),
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        bundle_id="uwm-env-evidence-test",
        created_at="2026-07-05T11:00:00Z",
    )
    scene_state = build_scene_state_from_proxy_artifacts(
        observations=[
            {
                "schema": "uwm.canonical_observation.v1",
                "observation_id": "uwm-env-evidence-obs",
                "claim_boundary": {"max_claim_level": "bounded_support"},
                "synthetic_flags": [
                    {"dataset_id": "gee_cams_nrt_chongqing_proxy", "status": "public_proxy"},
                    {"dataset_id": "openaq_air_quality_station_observation_proxy", "status": "public_proxy"},
                ],
            }
        ],
        ghsl_alignment={"dataset_id": "ghsl_admin_zonal_proxy_alignment", "admin_feature_count": 2},
        ghsl_zonal_rows=[
            {"population_proxy_sum": "100", "built_surface_proxy_sum": "60"},
            {"population_proxy_sum": "400", "built_surface_proxy_sum": "180"},
        ],
        openmeteo_proxy=_openmeteo_proxy(),
        environmental_evidence_bundle=bundle,
        scene_id="uwm-scene-env-evidence-test",
        created_at="2026-07-05T11:05:00Z",
    )

    validation = validate_scene_state(scene_state)
    assert validation["valid"], validation["errors"]
    assert scene_state["environmental_context"]["source_schema"] == UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA
    assert scene_state["environmental_context"]["pm25_avg_ugm3"] == 30.0
    assert scene_state["environmental_context"]["observed_holdout_ready"] is False
    assert "high_pm25_source_disagreement" in scene_state["limitations"]
    assert scene_state["scenario_controls"]["air_pollution_stress_multiplier"] > 1.0
    assert scene_state["empirical_superiority_claim"] is False
