from __future__ import annotations

import copy
from datetime import datetime

import pytest

from scripts import acquire_geotransport_stage39_component_discharge_values as acquire


def _source() -> dict[str, object]:
    return copy.deepcopy(acquire._load_frozen_plan()["sources"][0])


def _payload(source: dict[str, object]) -> dict[str, object]:
    begin = datetime.fromisoformat(str(source["begin_utc"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(source["end_utc"]).replace("Z", "+00:00"))
    return {
        "name": source["series_id"],
        "office-id": "LRN",
        "units": "cms",
        "interval": "PT1H",
        "interval-offset": 0,
        "page-size": 20_000,
        "total": 3,
        "begin": source["begin_utc"],
        "end": source["end_utc"],
        "values": [
            [int(begin.timestamp() * 1000), 1.0, 0],
            [int((begin.timestamp() + 3600) * 1000), None, 1],
            [int(end.timestamp() * 1000), 3.0, 0],
        ],
    }


def test_stage39_acquirer_binds_exact_frozen_plan():
    plan = acquire._load_frozen_plan()

    assert plan["frozen_protocol_artifact"]["sha256"] == (acquire.planner.FROZEN_PROTOCOL_SHA256)
    assert len(plan["sources"]) == 20


def test_stage39_valid_payload_preserves_nulls_quality_and_gaps():
    source = _source()
    payload = _payload(source)

    acquire._validate_payload(payload, source)

    assert payload["values"][1] == [1609462800000, None, 1]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("name", "wrong", "payload_invalid"),
        ("office-id", "SPN", "payload_invalid"),
        ("units", "cfs", "payload_invalid"),
        ("interval", "PT30M", "payload_invalid"),
        ("next-page", "token", "payload_invalid"),
    ),
)
def test_stage39_payload_identity_and_pagination_fail_closed(
    field: str, value: object, message: str
):
    source = _source()
    payload = _payload(source)
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        acquire._validate_payload(payload, source)


def test_stage39_payload_rejects_duplicate_or_unsorted_times():
    source = _source()
    payload = _payload(source)
    payload["values"][1][0] = payload["values"][0][0]

    with pytest.raises(ValueError, match="time_axis_invalid"):
        acquire._validate_payload(payload, source)


def test_stage39_payload_rejects_subhourly_time_axis():
    source = _source()
    payload = _payload(source)
    payload["values"][1][0] = payload["values"][0][0] + 30 * 60 * 1000

    with pytest.raises(ValueError, match="time_axis_invalid"):
        acquire._validate_payload(payload, source)


def test_stage39_payload_rejects_nonfinite_values_and_boolean_quality():
    source = _source()
    payload = _payload(source)
    payload["values"][0][1] = float("nan")
    with pytest.raises(ValueError, match="row_invalid"):
        acquire._validate_payload(payload, source)

    payload = _payload(source)
    payload["values"][0][2] = True
    with pytest.raises(ValueError, match="row_invalid"):
        acquire._validate_payload(payload, source)


def test_stage39_url_and_output_allowlists_fail_closed(tmp_path):
    acquire._validate_url(str(_source()["url"]))
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url("https://example.com/cwms-data/timeseries")
    with pytest.raises(ValueError, match="output_must_match_frozen_root"):
        acquire._validate_output(tmp_path)


def test_stage39_new_state_has_exact_twenty_sources(tmp_path):
    path = tmp_path / "state.json"
    sources = acquire._load_frozen_plan()["sources"]

    state = acquire._load_state(path, sources)

    assert state["schema"] == acquire.STATE_SCHEMA
    assert list(state["sources"]) == [value["source_id"] for value in sources]
    assert all(
        value == {"attempt_count": 0, "failed_attempts": [], "success": False}
        for value in state["sources"].values()
    )


def test_stage39_fetch_once_enforces_size_before_return():
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
