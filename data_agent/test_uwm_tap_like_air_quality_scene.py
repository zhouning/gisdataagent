from data_agent.uwm.tap_like_air_quality_scene import (
    TAP_LIKE_PM25_SCENE_SCHEMA,
    build_tap_like_pm25_scene_v2,
)


def test_tap_like_pm25_scene_v2_is_chap_anchored_and_explicitly_semi_synthetic():
    scene = build_tap_like_pm25_scene_v2(
        chap_proxy=_chap_proxy(),
        openmeteo_raw=_openmeteo_raw(),
        openaq_raw=_openaq_raw(),
        noaa_weather_proxy=_noaa_weather_proxy(),
        gee_zonal_proxy=_gee_zonal_proxy(),
        scene_id="fixture-tap-like-scene",
        created_at="2026-07-05T20:30:00Z",
    )

    assert scene["schema"] == TAP_LIKE_PM25_SCENE_SCHEMA
    assert scene["synthetic_status"] == "semi_synthetic"
    assert scene["quality_status"] == "tap_like_pm25_scene_not_observed_holdout"
    assert scene["empirical_superiority_claim"] is False
    assert scene["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert scene["record_counts"] == {
        "admin_units": 2,
        "hours": 3,
        "records": 6,
        "openaq_pm25_pattern_points": 3,
        "noaa_weather_pattern_points": 3,
    }
    assert scene["calibration_summary"]["max_abs_chap_anchor_error_ugm3"] <= 0.001
    assert scene["calibration_summary"]["mean_abs_chap_anchor_error_ugm3"] <= 0.001
    assert scene["limitations"] == [
        "not_tap_data",
        "not_observed_air_quality_holdout",
        "not_policy_intervention_outcome",
        "semi_synthetic_for_pipeline_development_only",
    ]

    records = scene["records"]
    first = records[0]
    assert first["admin_unit_id"] == "A"
    assert first["timestamp"] == "2024-07-01T00:00:00Z"
    assert first["source_components"]["chap_monthly_anchor_pm25_ugm3"] == 20.0
    assert first["source_components"]["openmeteo_hourly_pm25_ugm3"] == 18.0
    assert "openaq_historical_pm25_anomaly_ugm3" in first["source_components"]
    assert "noaa_weather_adjustment_ugm3" in first["source_components"]
    assert "gee_cams_zonal_pm25_ugm3" in first["source_components"]
    assert first["uncertainty_interval_ugm3"]["low"] < first["pm25_ugm3"]
    assert first["uncertainty_interval_ugm3"]["high"] > first["pm25_ugm3"]
    assert "CHAP_monthly_anchor" in first["source_trace"]
    assert "OpenAQ_historical_temporal_noise" in first["source_trace"]

    means = {}
    for record in records:
        means.setdefault(record["admin_unit_id"], []).append(record["pm25_ugm3"])
    assert round(sum(means["A"]) / len(means["A"]), 3) == 20.0
    assert round(sum(means["B"]) / len(means["B"]), 3) == 30.0


def _chap_proxy():
    return {
        "schema": "uwm.chap_pm25_admin_proxy.v1",
        "admin_pm25_rows": [
            {"admin_unit_id": "A", "county": "alpha", "township": "one", "pm25_ugm3": 20.0},
            {"admin_unit_id": "B", "county": "beta", "township": "two", "pm25_ugm3": 30.0},
        ],
    }


def _openmeteo_raw():
    return {
        "A": {
            "hourly": {
                "time": ["2024-07-01T00:00", "2024-07-01T01:00", "2024-07-01T02:00"],
                "pm2_5": [18.0, 20.0, 22.0],
                "pm10": [30.0, 32.0, 34.0],
            }
        },
        "B": {
            "hourly": {
                "time": ["2024-07-01T00:00", "2024-07-01T01:00", "2024-07-01T02:00"],
                "pm2_5": [27.0, 30.0, 33.0],
                "pm10": [40.0, 42.0, 44.0],
            }
        },
    }


def _openaq_raw():
    return {
        "sensor": {
            "results": [
                {"value": 10.0, "parameter": {"name": "pm25"}},
                {"value": 20.0, "parameter": {"name": "pm25"}},
                {"value": 30.0, "parameter": {"name": "pm25"}},
            ]
        }
    }


def _noaa_weather_proxy():
    return {
        "schema": "uwm.noaa_isd_weather_proxy.v1",
        "weather_observation_rows": [
            {"timestamp_utc": "2024-07-01T00:00:00Z", "wind_speed_ms": 1.0, "air_temperature_c": 28.0},
            {"timestamp_utc": "2024-07-01T01:00:00Z", "wind_speed_ms": 2.0, "air_temperature_c": 29.0},
            {"timestamp_utc": "2024-07-01T02:00:00Z", "wind_speed_ms": 3.0, "air_temperature_c": 30.0},
        ],
    }


def _gee_zonal_proxy():
    return {
        "schema": "uwm.gee_livability_admin_zonal_environment_proxy.v1",
        "admin_environment_rows": [
            {"admin_unit_id": "A", "cams_pm25_ugm3": 21.0, "cams_aod550": 0.4},
            {"admin_unit_id": "B", "cams_pm25_ugm3": 28.0, "cams_aod550": 0.5},
        ],
    }
