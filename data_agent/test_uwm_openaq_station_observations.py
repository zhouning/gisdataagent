import json

import pytest

from data_agent.uwm.openaq_station_observations import (
    OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA,
    build_mmfe_state_input_from_openaq_station_proxy,
    build_openaq_locations_url,
    build_openaq_sensor_measurements_url,
    build_openaq_station_observation_proxy,
    write_openaq_station_snapshot,
)
from scripts.download_uwm_openaq_station_observations import scene_measurement_datetime_bounds


def _locations_payload():
    return {
        "meta": {"name": "openaq-api", "found": 1},
        "results": [
            {
                "id": 7332,
                "name": "上清寺",
                "locality": "Chongqing",
                "country": {"code": "CN", "name": "China"},
                "coordinates": {"latitude": 29.5631, "longitude": 106.5512},
                "distance": 486.4,
                "datetimeFirst": {"utc": "2018-10-17T00:00:00Z"},
                "datetimeLast": {"utc": "2021-08-09T07:00:00Z"},
                "sensors": [
                    {
                        "id": 21178,
                        "name": "pm25 sensor",
                        "parameter": {
                            "id": 2,
                            "name": "pm25",
                            "displayName": "PM2.5",
                            "units": "µg/m³",
                        },
                    }
                ],
            }
        ],
    }


def _measurements_payload():
    return {
        "meta": {"found": 2},
        "results": [
            {
                "value": 41.2,
                "parameter": {"name": "pm25", "units": "µg/m³"},
                "datetime": {"utc": "2018-10-17T00:00:00Z"},
            },
            {
                "value": 36.8,
                "parameter": {"name": "pm25", "units": "µg/m³"},
                "datetime": {"utc": "2018-10-17T01:00:00Z"},
            },
        ],
    }


def test_build_openaq_v3_urls_never_embed_api_key_and_enforce_radius_cap():
    url = build_openaq_locations_url(latitude=29.563, longitude=106.551, radius_m=25000, limit=20)

    assert url.startswith("https://api.openaq.org/v3/locations?")
    assert "coordinates=29.563,106.551" in url
    assert "radius=25000" in url
    assert "limit=20" in url
    assert "api_key" not in url.lower()
    assert "X-API-Key" not in url

    with pytest.raises(ValueError, match="OpenAQ v3 radius"):
        build_openaq_locations_url(latitude=29.563, longitude=106.551, radius_m=25001)


def test_build_sensor_measurements_url_is_parameterized_without_secret():
    url = build_openaq_sensor_measurements_url(
        sensor_id=21178,
        date_from="2018-10-17T00:00:00Z",
        date_to="2018-10-18T00:00:00Z",
        limit=100,
    )

    assert url == (
        "https://api.openaq.org/v3/sensors/21178/measurements?"
        "limit=100&datetime_from=2018-10-17T00%3A00%3A00Z&datetime_to=2018-10-18T00%3A00%3A00Z"
    )


def test_scene_measurement_datetime_bounds_cover_inclusive_scene_dates():
    date_from, date_to = scene_measurement_datetime_bounds("2024-07-01", "2024-07-07")

    assert date_from == "2024-07-01T00:00:00Z"
    assert date_to == "2024-07-08T00:00:00Z"


def test_build_openaq_station_observation_proxy_marks_station_observed_but_not_scene_holdout():
    proxy = build_openaq_station_observation_proxy(
        locations_payload=_locations_payload(),
        sensor_measurement_payloads={"21178": _measurements_payload()},
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T10:30:00Z",
    )

    assert proxy["schema"] == OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA
    assert proxy["source"] == "OpenAQ v3"
    assert proxy["source_dataset_ids"] == ["openaq_air_quality_station_observation_proxy"]
    assert proxy["record_counts"] == {"locations": 1, "sensors": 1, "measurements": 2}
    assert proxy["nearest_station"]["id"] == 7332
    assert proxy["nearest_station"]["distance_m"] == 486.4
    assert proxy["observed_time_range"] == {
        "start": "2018-10-17T00:00:00Z",
        "end": "2018-10-17T01:00:00Z",
    }
    assert proxy["air_pollution_summary"]["pm25_avg_ugm3"] == 39.0
    assert proxy["scene_holdout_ready"] is False
    assert "station_observations_not_aligned_to_scene_period" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_mmfe_state_input_from_openaq_station_proxy_keeps_holdout_warning():
    proxy = build_openaq_station_observation_proxy(
        locations_payload=_locations_payload(),
        sensor_measurement_payloads={"21178": _measurements_payload()},
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T10:30:00Z",
    )

    payload = build_mmfe_state_input_from_openaq_station_proxy(
        proxy,
        timestamp="2026-07-05T10:35:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == (
        "mmfe-openaq-stations-2018-10-17T00:00:00Z-2018-10-17T01:00:00Z"
    )
    assert payload["urban_spatial_unit"]["unit_type"] == "station_air_quality_proxy"
    assert payload["state_components"]["air_pollution_exposure"]["source_dataset_ids"] == [
        "openaq_air_quality_station_observation_proxy"
    ]
    assert (
        payload["graph_summary"]["relation_type_distribution"][
            "station_has_air_quality_measurement"
        ]
        == 2
    )
    assert payload["native_geometry_contract"]["metadata_complete"] is True
    assert payload["native_geometry_contract"]["geometry_types"] == ["point"]
    assert payload["native_geometry_contract"]["observation_semantics"] == ["observed"]
    assert (
        payload["object_role_registry"][0]["spatial_support"]["support_type"] == "sensor_footprint"
    )
    assert payload["source_proxy"]["scene_holdout_ready"] is False
    assert any(
        "not aligned to the UWM scene holdout period" in warning for warning in payload["warnings"]
    )


def test_write_openaq_station_snapshot_persists_without_api_key(tmp_path):
    manifest = write_openaq_station_snapshot(
        output_dir=tmp_path,
        locations_payload=_locations_payload(),
        sensor_measurement_payloads={"21178": _measurements_payload()},
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T10:30:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "openaq_station_observation_proxy_snapshot"
    assert manifest["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert (tmp_path / "openaq_locations_raw.json").exists()
    assert (tmp_path / "openaq_sensor_measurements_raw.json").exists()
    assert (tmp_path / "openaq_station_observation_proxy.json").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.iterdir() if path.is_file()
    )
    assert "X-API-Key" not in serialized
    assert "OPENAQ_TEST_SECRET_SHOULD_NOT_APPEAR" not in serialized


def test_station_lifetime_does_not_substitute_for_missing_measurements():
    proxy = build_openaq_station_observation_proxy(
        locations_payload=_locations_payload(),
        sensor_measurement_payloads={"21178": {"results": []}},
        requested_location={
            "latitude": 29.563,
            "longitude": 106.551,
            "label": "Chongqing central",
        },
        scene_time_range={"start_date": "2020-01-01", "end_date": "2020-01-02"},
        fetched_at="2026-08-04T18:00:00Z",
    )

    assert proxy["observed_time_range"] == {"start": None, "end": None}
    assert proxy["scene_holdout_ready"] is False


def test_period_measurement_bounds_are_used_for_observed_coverage():
    measurement = _measurements_payload()["results"][0]
    measurement.pop("datetime")
    measurement["period"] = {
        "datetimeFrom": {"utc": "2018-10-17T00:00:00Z"},
        "datetimeTo": {"utc": "2018-10-17T01:00:00Z"},
    }
    proxy = build_openaq_station_observation_proxy(
        locations_payload=_locations_payload(),
        sensor_measurement_payloads={"21178": {"results": [measurement]}},
        requested_location={
            "latitude": 29.563,
            "longitude": 106.551,
            "label": "Chongqing central",
        },
        scene_time_range={"start_date": "2018-10-17", "end_date": "2018-10-17"},
        fetched_at="2026-08-04T18:00:00Z",
    )

    assert proxy["observed_time_range"] == {
        "start": "2018-10-17T00:00:00Z",
        "end": "2018-10-17T01:00:00Z",
    }
    assert proxy["scene_holdout_ready"] is True
