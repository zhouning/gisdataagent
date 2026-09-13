from data_agent.uwm.openmeteo_proxy import (
    OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA,
    build_openmeteo_environmental_proxy,
)


def test_openmeteo_current_payload_is_normalized_to_uwm_environmental_proxy():
    weather_payload = {
        "latitude": 29.56063,
        "longitude": 106.5625,
        "current_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "surface_pressure": "hPa",
            "wind_speed_10m": "km/h",
        },
        "current": {
            "time": "2026-07-04T13:15",
            "temperature_2m": 27.0,
            "relative_humidity_2m": 90,
            "precipitation": 0.0,
            "surface_pressure": 974.3,
            "wind_speed_10m": 2.7,
        },
    }
    air_payload = {
        "latitude": 29.599998,
        "longitude": 106.600006,
        "current_units": {
            "pm10": "μg/m³",
            "pm2_5": "μg/m³",
            "carbon_monoxide": "μg/m³",
            "nitrogen_dioxide": "μg/m³",
            "sulphur_dioxide": "μg/m³",
            "ozone": "μg/m³",
        },
        "current": {
            "time": "2026-07-04T13:00",
            "pm10": 62.9,
            "pm2_5": 62.6,
            "carbon_monoxide": 1185.0,
            "nitrogen_dioxide": 122.3,
            "sulphur_dioxide": 17.2,
            "ozone": 10.0,
        },
    }

    proxy = build_openmeteo_environmental_proxy(
        weather_payload,
        air_payload,
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
    )

    assert proxy["schema"] == OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA
    assert proxy["source"] == "Open-Meteo API"
    assert proxy["requested_location"]["label"] == "Chongqing central"
    assert proxy["meteorology"]["temperature_c"] == 27.0
    assert proxy["meteorology"]["humidity_percent"] == 90.0
    assert proxy["meteorology"]["pressure_hpa"] == 974.3
    assert proxy["air_pollution"]["pm25_ugm3"] == 62.6
    assert proxy["air_pollution"]["co_ugm3"] == 1185.0
    assert proxy["source_dataset_ids"] == [
        "openmeteo_weather_current_proxy",
        "openmeteo_air_quality_current_proxy",
    ]
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert proxy["synthetic_flags"] == [{"dataset_id": "openmeteo_environmental_proxy", "status": "public_proxy"}]
    assert "not_station_calibrated_holdout" in proxy["limitations"]
