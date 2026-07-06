import json

from data_agent.uwm.openmeteo_history import (
    OPENMETEO_HISTORICAL_PROXY_SCHEMA,
    build_mmfe_state_input_from_openmeteo_historical_proxy,
    build_openmeteo_historical_urls,
    write_openmeteo_historical_snapshot,
)


def test_build_openmeteo_historical_urls_uses_reproducible_date_range_and_fields():
    urls = build_openmeteo_historical_urls(
        latitude=29.563,
        longitude=106.551,
        start_date="2024-07-01",
        end_date="2024-07-07",
        timezone="Asia/Shanghai",
    )

    assert urls["weather"].startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "start_date=2024-07-01" in urls["weather"]
    assert "end_date=2024-07-07" in urls["weather"]
    assert "temperature_2m_mean,precipitation_sum,wind_speed_10m_max" in urls["weather"]
    assert "relative_humidity_2m,surface_pressure" in urls["weather"]
    assert urls["air_quality"].startswith("https://air-quality-api.open-meteo.com/v1/air-quality?")
    assert "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone" in urls["air_quality"]


def test_write_openmeteo_historical_snapshot_persists_proxy_with_non_holdout_boundary(tmp_path):
    weather_payload = {
        "latitude": 29.56063,
        "longitude": 106.5625,
        "timezone": "Asia/Shanghai",
        "hourly": {
            "time": ["2024-07-01T00:00", "2024-07-01T01:00"],
            "relative_humidity_2m": [92, 88],
            "surface_pressure": [969.7, 969.1],
        },
        "daily": {
            "time": ["2024-07-01", "2024-07-02"],
            "temperature_2m_mean": [25.7, 26.7],
            "precipitation_sum": [14.2, 0.0],
            "wind_speed_10m_max": [11.1, 13.5],
        },
    }
    air_payload = {
        "latitude": 29.599998,
        "longitude": 106.600006,
        "timezone": "Asia/Shanghai",
        "hourly": {
            "time": ["2024-07-01T00:00", "2024-07-01T01:00"],
            "pm10": [71.2, 65.2],
            "pm2_5": [47.8, 44.0],
            "carbon_monoxide": [457.0, 439.0],
            "nitrogen_dioxide": [36.0, 36.2],
            "sulphur_dioxide": [17.0, 15.7],
            "ozone": [76.0, 65.0],
        },
    }

    manifest = write_openmeteo_historical_snapshot(
        output_dir=tmp_path,
        weather_payload=weather_payload,
        air_quality_payload=air_payload,
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        start_date="2024-07-01",
        end_date="2024-07-07",
        fetched_at="2026-07-05T01:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "openmeteo_historical_environmental_proxy_snapshot"
    assert manifest["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "not_station_calibrated_holdout" in manifest["limitations"]
    assert (tmp_path / "openmeteo_historical_weather_raw.json").exists()
    assert (tmp_path / "openmeteo_historical_air_quality_raw.json").exists()

    proxy = json.loads((tmp_path / "openmeteo_historical_environmental_proxy.json").read_text(encoding="utf-8"))
    assert proxy["schema"] == OPENMETEO_HISTORICAL_PROXY_SCHEMA
    assert proxy["time_range"] == {"start_date": "2024-07-01", "end_date": "2024-07-07"}
    assert proxy["record_counts"]["weather_hourly"] == 2
    assert proxy["record_counts"]["weather_daily"] == 2
    assert proxy["record_counts"]["air_quality_hourly"] == 2
    assert proxy["non_null_counts"]["pm2_5"] == 2
    assert proxy["non_null_counts"]["temperature_2m_mean"] == 2
    assert proxy["meteorology_summary"]["temperature_2m_mean_avg_c"] == 26.2
    assert proxy["air_pollution_summary"]["pm25_avg_ugm3"] == 45.9
    assert proxy["empirical_superiority_claim"] is False
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest


def test_openmeteo_historical_proxy_marks_all_null_air_quality_as_missing_evidence(tmp_path):
    weather_payload = {
        "latitude": 29.56063,
        "longitude": 106.5625,
        "timezone": "Asia/Shanghai",
        "hourly": {
            "time": ["2018-10-17T00:00", "2018-10-17T01:00"],
            "relative_humidity_2m": [92, 88],
            "surface_pressure": [969.7, 969.1],
        },
        "daily": {
            "time": ["2018-10-17", "2018-10-18"],
            "temperature_2m_mean": [16.0, 17.0],
            "precipitation_sum": [0.0, 1.0],
            "wind_speed_10m_max": [11.1, 13.5],
        },
    }
    air_payload = {
        "latitude": 29.599998,
        "longitude": 106.600006,
        "timezone": "Asia/Shanghai",
        "hourly": {
            "time": ["2018-10-17T00:00", "2018-10-17T01:00"],
            "pm10": [None, None],
            "pm2_5": [None, None],
            "carbon_monoxide": [None, None],
            "nitrogen_dioxide": [None, None],
            "sulphur_dioxide": [None, None],
            "ozone": [None, None],
        },
    }

    write_openmeteo_historical_snapshot(
        output_dir=tmp_path,
        weather_payload=weather_payload,
        air_quality_payload=air_payload,
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        start_date="2018-10-17",
        end_date="2018-10-18",
        fetched_at="2026-07-05T04:44:42Z",
    )

    proxy = json.loads((tmp_path / "openmeteo_historical_environmental_proxy.json").read_text(encoding="utf-8"))
    assert proxy["record_counts"]["air_quality_hourly"] == 2
    assert proxy["non_null_counts"]["pm2_5"] == 0
    assert proxy["air_pollution_summary"]["pm25_avg_ugm3"] is None
    assert "air_quality_values_missing_for_requested_period" in proxy["limitations"]


def test_build_mmfe_state_input_from_openmeteo_historical_proxy_preserves_non_holdout_warning():
    proxy = {
        "schema": OPENMETEO_HISTORICAL_PROXY_SCHEMA,
        "source_dataset_ids": [
            "openmeteo_weather_historical_point_proxy",
            "openmeteo_air_quality_historical_point_proxy",
        ],
        "requested_location": {"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "record_counts": {"weather_hourly": 168, "weather_daily": 7, "air_quality_hourly": 168},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["not_station_calibrated_holdout", "point_proxy_not_citywide_grid"],
        "empirical_superiority_claim": False,
    }

    payload = build_mmfe_state_input_from_openmeteo_historical_proxy(
        proxy,
        timestamp="2026-07-05T01:30:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-openmeteo-history-2024-07-01-2024-07-07"
    assert payload["urban_spatial_unit"]["unit_type"] == "point_environmental_proxy"
    assert payload["state_components"]["meteorology"]["role_count"] == 2
    assert payload["state_components"]["air_pollution_exposure"]["role_count"] == 1
    assert payload["graph_summary"]["relation_type_distribution"]["point_has_weather_hourly_record"] == 168
    assert payload["graph_summary"]["relation_type_distribution"]["point_has_air_quality_hourly_record"] == 168
    assert payload["source_proxy"]["empirical_superiority_claim"] is False
    assert any("not station-calibrated holdout" in warning for warning in payload["warnings"])
