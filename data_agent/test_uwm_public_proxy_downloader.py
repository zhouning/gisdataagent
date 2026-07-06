import json

from data_agent.uwm.public_proxy_downloader import (
    build_openmeteo_urls,
    write_openmeteo_snapshot,
)


def test_build_openmeteo_urls_uses_savemyself_fields():
    urls = build_openmeteo_urls(latitude=29.563, longitude=106.551)

    assert urls["weather"].startswith("https://api.open-meteo.com/v1/forecast?")
    assert "temperature_2m,relative_humidity_2m,precipitation,surface_pressure,wind_speed_10m" in urls["weather"]
    assert urls["air_quality"].startswith("https://air-quality-api.open-meteo.com/v1/air-quality?")
    assert "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone" in urls["air_quality"]


def test_write_openmeteo_snapshot_persists_raw_normalized_and_manifest(tmp_path):
    weather_payload = {
        "latitude": 29.56,
        "longitude": 106.56,
        "current": {"time": "2026-07-04T13:15", "temperature_2m": 27, "relative_humidity_2m": 90},
    }
    air_payload = {
        "latitude": 29.60,
        "longitude": 106.60,
        "current": {"time": "2026-07-04T13:00", "pm2_5": 62.6, "pm10": 62.9},
    }

    manifest = write_openmeteo_snapshot(
        output_dir=tmp_path,
        weather_payload=weather_payload,
        air_quality_payload=air_payload,
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        fetched_at="2026-07-04T13:30:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "openmeteo_environmental_proxy_snapshot"
    assert manifest["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert (tmp_path / "openmeteo_weather_raw.json").exists()
    assert (tmp_path / "openmeteo_air_quality_raw.json").exists()
    normalized = json.loads((tmp_path / "openmeteo_environmental_proxy.json").read_text(encoding="utf-8"))
    assert normalized["source"] == "Open-Meteo API"
    assert normalized["meteorology"]["temperature_c"] == 27.0
    assert normalized["air_pollution"]["pm25_ugm3"] == 62.6
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
