import copy
import json

import pytest

from scripts.download_uwm_openaq_station_observations import (
    acquire_openaq_snapshot,
    choose_pm25_sensor_bindings,
    fetch_paginated_results,
)


def test_pm25_selector_chooses_one_sensor_per_location_and_honors_allowlists():
    locations = _locations_payload()

    bindings = choose_pm25_sensor_bindings(locations, limit=2)

    assert [(row["station_id"], row["sensor_id"]) for row in bindings] == [
        (1001, 101),
        (1002, 201),
    ]
    station_two = choose_pm25_sensor_bindings(
        locations,
        limit=1,
        station_allowlist=[1002],
        sensor_allowlist=[201],
    )
    assert [(row["station_id"], row["sensor_id"]) for row in station_two] == [(1002, 201)]
    with pytest.raises(ValueError, match="requested_pm25_sensors_missing"):
        choose_pm25_sensor_bindings(locations, limit=2, sensor_allowlist=[999])


def test_paginated_fetch_requires_found_to_equal_fetched():
    client = _SequenceClient(
        [
            _payload(found=3, page=1, results=[{"id": 1}, {"id": 2}]),
            _payload(found=3, page=2, results=[{"id": 3}]),
        ]
    )

    aggregate, audit = fetch_paginated_results(
        client=client,
        url_for_page=lambda page: f"https://example.test/data?page={page}",
        headers={"X-API-Key": "not-persisted"},
        max_pages=3,
    )

    assert [row["id"] for row in aggregate["results"]] == [1, 2, 3]
    assert aggregate["meta"]["fetched"] == 3
    assert aggregate["meta"]["acquisition_complete"] is True
    assert audit == {
        "found": 3,
        "found_relation": "exact",
        "found_lower_bound_exclusive": None,
        "fetched": 3,
        "reported_found_consistent": True,
        "pages_fetched": 2,
        "page_audit": [
            {"page": 1, "result_count": 2, "reported_found": 3},
            {"page": 2, "result_count": 1, "reported_found": 3},
        ],
        "completion_signal": "reported_found_reached",
        "complete": True,
    }


def test_paginated_fetch_supports_openaq_lower_bound_found_until_short_page():
    client = _SequenceClient(
        [
            _payload(found=">100", page=1, results=[{"id": index} for index in range(100)]),
            _payload(found=2, page=2, results=[{"id": 100}, {"id": 101}]),
        ]
    )

    aggregate, audit = fetch_paginated_results(
        client=client,
        url_for_page=lambda page: f"https://example.test/data?page={page}",
        headers={"X-API-Key": "not-persisted"},
        max_pages=3,
    )

    assert len(aggregate["results"]) == 102
    assert audit["found"] == ">100"
    assert audit["found_relation"] == "lower_bound"
    assert audit["found_lower_bound_exclusive"] == 100
    assert audit["fetched"] == 102
    assert audit["reported_found_consistent"] is False
    assert audit["completion_signal"] == "terminal_short_page"
    assert audit["complete"] is True


def test_partial_sensor_failure_does_not_replace_existing_snapshot(tmp_path):
    output = tmp_path / "snapshot"
    output.mkdir()
    (output / "sentinel.txt").write_text("original", encoding="utf-8")
    client = _RoutingClient(fail_sensor_id=201)

    with pytest.raises(RuntimeError, match="simulated request failure"):
        _acquire(client, output, replace_existing=True)

    assert (output / "sentinel.txt").read_text(encoding="utf-8") == "original"
    assert sorted(path.name for path in output.iterdir()) == ["sentinel.txt"]


def test_existing_snapshot_is_not_touched_without_explicit_replace(tmp_path):
    output = tmp_path / "snapshot"
    output.mkdir()
    (output / "sentinel.txt").write_text("original", encoding="utf-8")
    client = _RoutingClient()

    with pytest.raises(FileExistsError, match="already exists"):
        _acquire(client, output, replace_existing=False)

    assert client.urls == []
    assert (output / "sentinel.txt").read_text(encoding="utf-8") == "original"


def test_complete_acquisition_publishes_audited_snapshot_without_secret(tmp_path):
    output = tmp_path / "snapshot"

    result = _acquire(_RoutingClient(), output, replace_existing=False)

    audit = json.loads((output / "openaq_acquisition_audit.json").read_text(encoding="utf-8"))
    assert audit["all_pages_complete"] is True
    assert audit["api_key_persisted"] is False
    assert audit["selected_bindings"] == result["bindings"]
    assert result["manifest"]["record_counts"]["measurements"] == 2
    assert {row["station_id"] for row in result["bindings"]} == {1001, 1002}
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in output.iterdir() if path.is_file()
    )
    assert "OPENAQ_TEST_SECRET" not in serialized


def _acquire(client, output, *, replace_existing):
    return acquire_openaq_snapshot(
        client=client,
        headers={"X-API-Key": "OPENAQ_TEST_SECRET"},
        output_dir=output,
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "fixture"},
        radius_m=25000,
        location_page_limit=20,
        station_limit=2,
        station_allowlist=[],
        sensor_allowlist=[],
        date_from="2024-07-01T00:00:00Z",
        date_to="2024-07-02T00:00:00Z",
        measurement_page_limit=100,
        max_pages=10,
        scene_time_range={"start_date": "2024-07-01", "end_date": "2024-07-01"},
        fetched_at="2026-08-04T20:00:00Z",
        api_key="OPENAQ_TEST_SECRET",
        replace_existing=replace_existing,
    )


def _locations_payload():
    return {
        "meta": {"found": 2, "page": 1, "limit": 20},
        "results": [
            {
                "id": 1001,
                "name": "station-one",
                "distance": 10.0,
                "coordinates": {"latitude": 29.5, "longitude": 106.5},
                "sensors": [
                    {"id": 101, "parameter": {"name": "pm25"}},
                    {"id": 102, "parameter": {"name": "pm10"}},
                    {"id": 103, "parameter": {"name": "pm25"}},
                ],
            },
            {
                "id": 1002,
                "name": "station-two",
                "distance": 20.0,
                "coordinates": {"latitude": 29.6, "longitude": 106.6},
                "sensors": [{"id": 201, "parameter": {"name": "pm2.5"}}],
            },
        ],
    }


def _measurement(sensor_id):
    return {
        "value": float(sensor_id),
        "parameter": {"name": "pm25", "units": "ug/m3"},
        "datetime": {"utc": "2024-07-01T00:00:00Z"},
    }


def _payload(*, found, page, results):
    return {"meta": {"found": found, "page": page, "limit": 100}, "results": results}


class _Response:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return copy.deepcopy(self.payload)


class _SequenceClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    def get(self, url, headers):
        self.urls.append(url)
        return _Response(self.payloads.pop(0))


class _RoutingClient:
    def __init__(self, fail_sensor_id=None):
        self.fail_sensor_id = fail_sensor_id
        self.urls = []

    def get(self, url, headers):
        self.urls.append(url)
        if "/locations?" in url:
            return _Response(_locations_payload())
        for sensor_id in (101, 201):
            if f"/sensors/{sensor_id}/" in url:
                if sensor_id == self.fail_sensor_id:
                    return _Response(error=RuntimeError("simulated request failure"))
                return _Response(_payload(found=1, page=1, results=[_measurement(sensor_id)]))
        raise AssertionError(f"unexpected URL: {url}")
