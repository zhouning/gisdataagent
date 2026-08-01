from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from scripts import (
    acquire_geotransport_stage45_component_lag_replication_targets as acquire,
)


def _source() -> dict[str, object]:
    return copy.deepcopy(acquire._load_frozen_plan()["sources"][0])


def _payload(source: dict[str, object]) -> dict[str, object]:
    begin = datetime.fromisoformat(str(source["begin_utc"]).replace("Z", "+00:00"))
    features = []
    for index in range(3):
        timestamp = begin + timedelta(minutes=30 * index)
        features.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "monitoring_location_id": source["site_id"],
                    "parameter_code": "00060",
                    "statistic_id": "00011",
                    "time": timestamp.isoformat(),
                    "value": str(100 + index),
                    "unit_of_measure": "ft^3/s",
                    "approval_status": "Approved",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "numberReturned": len(features),
        "features": features,
        "links": [{"rel": "self", "href": source["url"]}],
    }


def test_stage45_acquirer_binds_exact_frozen_plan():
    plan = acquire._load_frozen_plan()

    assert plan["frozen_protocol_artifact"]["sha256"] == (acquire.planner.FROZEN_PROTOCOL_SHA256)
    assert len(plan["sources"]) == 4


def test_stage45_acquirer_requires_explicit_execution_flag():
    with pytest.raises(ValueError, match="execution_flag_required"):
        acquire._require_execution_flag(False)
    acquire._require_execution_flag(True)


def test_stage45_valid_payload_allows_gaps_without_filling():
    source = _source()
    payload = _payload(source)
    del payload["features"][1]
    payload["numberReturned"] = 2

    acquire._validate_payload(payload, source)

    assert [value["properties"]["value"] for value in payload["features"]] == [
        "100",
        "102",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("monitoring_location_id", "USGS-00000000"),
        ("parameter_code", "00065"),
        ("statistic_id", "00003"),
        ("unit_of_measure", "m3/s"),
        ("approval_status", None),
        ("value", "not-a-number"),
    ),
)
def test_stage45_payload_identity_and_values_fail_closed(field: str, value: object):
    source = _source()
    payload = _payload(source)
    payload["features"][0]["properties"][field] = value

    with pytest.raises(ValueError, match="feature_invalid"):
        acquire._validate_payload(payload, source)


def test_stage45_payload_rejects_next_page_link():
    source = _source()
    payload = _payload(source)
    payload["links"].append({"rel": "next", "href": source["url"]})

    with pytest.raises(ValueError, match="payload_invalid"):
        acquire._validate_payload(payload, source)


def test_stage45_payload_rejects_duplicate_or_unsorted_times():
    source = _source()
    payload = _payload(source)
    payload["features"][1]["properties"]["time"] = payload["features"][0]["properties"]["time"]

    with pytest.raises(ValueError, match="time_axis_invalid"):
        acquire._validate_payload(payload, source)


def test_stage45_payload_rejects_off_grid_or_out_of_window_time():
    source = _source()
    payload = _payload(source)
    payload["features"][0]["properties"]["time"] = "2023-01-28T01:15:00Z"
    with pytest.raises(ValueError, match="feature_invalid"):
        acquire._validate_payload(payload, source)

    payload = _payload(source)
    payload["features"][0]["properties"]["time"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="feature_invalid"):
        acquire._validate_payload(payload, source)


def test_stage45_url_and_output_allowlists_fail_closed(tmp_path):
    acquire._validate_url(str(_source()["url"]))
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url("https://example.com/ogcapi/v0/collections/continuous/items")
    with pytest.raises(ValueError, match="output_must_match_frozen_root"):
        acquire._validate_output(tmp_path)


def test_stage45_new_state_has_exact_four_sources(tmp_path):
    path = tmp_path / "state.json"
    sources = acquire._load_frozen_plan()["sources"]

    state = acquire._load_state(path, sources)

    assert state["schema"] == acquire.STATE_SCHEMA
    assert state["frozen_plan_sha256"] == acquire.FROZEN_PLAN_SHA256
    assert list(state["sources"]) == [value["source_id"] for value in sources]
    assert all(
        value == {"attempt_count": 0, "failed_attempts": [], "success": False}
        for value in state["sources"].values()
    )


def test_stage45_fetch_once_enforces_size_before_return():
    class Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def geturl(self):
            return _source()["url"]

        def read(self, _):
            return b"1234"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    with pytest.raises(ValueError, match="size_limit_exceeded"):
        acquire._fetch_once(
            str(_source()["url"]),
            opener=Opener(),
            timeout_seconds=1.0,
            maximum_bytes=3,
        )


def test_stage45_manifest_bounds_attempts_bytes_and_claims(tmp_path, monkeypatch):
    plan = acquire._load_frozen_plan()
    state_path = tmp_path / "state.json"
    state = acquire._load_state(state_path, plan["sources"])
    artifacts = []
    for source in plan["sources"]:
        record = state["sources"][source["source_id"]]
        record.update({"attempt_count": 1, "success": True})
        artifacts.append({"size_bytes": 100})
    monkeypatch.setattr(
        acquire,
        "_artifact",
        lambda path: {"path": str(path), "sha256": "0" * 64, "size_bytes": 1},
    )

    manifest = acquire._compile_manifest(plan, state, artifacts, state_path)

    assert manifest["actual_request_count"] == 4
    assert manifest["actual_attempt_count"] == 4
    assert manifest["actual_download_bytes"] == 400
    assert manifest["claim_boundary"]["downstream_replication_target_values_acquired"] is True
    assert manifest["claim_boundary"]["replication_test_executed"] is False
