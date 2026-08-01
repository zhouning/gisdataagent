from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import (
    acquire_geotransport_stage36_hydraulic_boundary_events as acquire,
)


def test_stage36_selection_plan_is_source_only_and_bounded():
    plan = acquire.compile_selection_plan()

    assert plan["schema"] == acquire.SCHEMA
    assert plan["mode"] == "selection_plan"
    assert len(plan["sources"]) == 5
    assert plan["request_boundary"] == {
        "allowed_hosts": ["cwms-data.usace.army.mil"],
        "maximum_request_count": 5,
        "maximum_attempts_per_request": 3,
        "maximum_bytes_per_request": 1_000_000,
        "maximum_total_download_bytes": 5_000_000,
        "planned_maximum_bytes": 5_000_000,
        "workspace_or_private_data_sent": False,
        "release_values_requested": False,
        "downstream_or_tributary_observation_values_requested": False,
        "server_returned_pagination_followed": False,
    }
    assert all(
        value["source"] == "usace_cwms"
        and "Elev-Tail.Inst.30Minutes" in value["url"]
        and "api.waterdata.usgs.gov" not in value["url"]
        for value in plan["sources"]
    )


def test_stage36_plan_hash_binds_protocol_and_operator():
    plan = acquire.compile_selection_plan()

    assert plan["frozen_protocol_artifact"]["sha256"] == (
        acquire.FROZEN_PROTOCOL_SHA256
    )
    assert plan["frozen_operator_artifact"]["sha256"] == (
        "ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f"
    )
    assert plan["blinding_protocol"][
        "events_selected_from_tailwater_elevation_only"
    ] is True
    assert plan["predeclared_target_functional"][
        "statistical_departure_is_physical_first_arrival"
    ] is False


def test_stage36_annual_sources_cover_exact_five_year_pool():
    sources = acquire._selection_sources()

    assert [(value["begin_utc"], value["end_utc"]) for value in sources] == list(
        acquire.YEAR_WINDOWS
    )
    assert all("page-size=20000" in value["url"] for value in sources)
    assert sources[0]["begin_utc"] == acquire.CWMS_BEGIN
    assert sources[-1]["end_utc"] == acquire.CWMS_END


def test_stage36_event_selection_is_deterministic_and_source_only():
    series = _synthetic_event_series()

    candidates, selected = acquire._select_events(series)

    assert len(candidates) == 4
    assert len(selected) == 4
    assert [
        value["source_only_perturbation"]["absolute_primary_change_m"]
        for value in selected
    ] == [4.0, 3.0, 2.0, 1.0]
    assert [value["selection_rank"] for value in selected] == [1, 2, 3, 4]
    assert all(
        value["selected_without_release_or_downstream_values"] is True
        and value["role"] == "blind_hydraulic_boundary_event"
        for value in selected
    )


def test_stage36_real_source_artifacts_reproduce_frozen_four_events():
    payloads = []
    for source in acquire._selection_sources():
        path = acquire.DEFAULT_OUTPUT / str(source["output_name"])
        payload = json.loads(path.read_bytes())
        acquire._validate_tailwater_payload(payload, source)
        payloads.append(payload)
    candidates, selected = acquire._select_events(
        acquire._combine_tailwater_payloads(payloads)
    )
    manifest = json.loads(
        (acquire.DEFAULT_OUTPUT / "event_selection_manifest.json").read_bytes()
    )

    assert len(candidates) == 7_370
    assert selected == manifest["selected_events"]
    assert [value["event_id"] for value in selected] == [
        "tailwater_stage_change_20231004T1730Z",
        "tailwater_stage_change_20210901T1530Z",
        "tailwater_stage_change_20210303T2330Z",
        "tailwater_stage_change_20220903T1630Z",
    ]


def test_stage36_incomplete_or_nonzero_quality_window_is_not_a_candidate():
    series = list(_synthetic_event_series())
    first_event_index = 48
    series[first_event_index] = (
        series[first_event_index][0],
        series[first_event_index][1],
        1,
    )

    candidates = acquire._compile_candidates(tuple(series))

    assert len(candidates) == 3
    assert all(value["quality_codes"] == [0] for value in candidates)


def test_stage36_null_value_is_preserved_but_candidate_window_is_rejected():
    series = list(_synthetic_event_series())
    first_event_index = 48
    timestamp, _, quality = series[first_event_index]
    series[first_event_index] = (timestamp, None, quality)

    candidates = acquire._compile_candidates(tuple(series))

    assert len(candidates) == 3


def test_stage36_real_2022_pool_accepts_explicit_nulls_without_filling():
    path = acquire.DEFAULT_OUTPUT / "raw/cwms_tailwater_stage_2022.json"
    payload = json.loads(path.read_bytes())

    acquire._validate_tailwater_payload(payload, acquire._selection_sources()[1])

    assert sum(row[1] is None for row in payload["values"]) == 100


def test_stage36_interrupted_attempt_audit_preserves_request_limits():
    audit = acquire._load_attempt_audit(
        acquire.DEFAULT_OUTPUT / acquire.ATTEMPT_AUDIT_NAME,
        acquire._selection_sources(),
    )

    assert [value["attempts_before_resume"] for value in audit.values()] == [
        2,
        2,
        0,
        0,
        0,
    ]
    assert all(value["attempts_before_resume"] <= 3 for value in audit.values())


def test_stage36_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "selection_plan.json"
    with pytest.raises(ValueError, match="plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())


def test_stage36_observation_plan_hash_binds_events_and_exact_target_windows():
    plan = acquire.compile_observation_plan()

    assert plan["mode"] == "observation_plan"
    assert plan["frozen_event_selection_manifest"]["sha256"] == (
        "532a94a860b65d46f2361703c6acd6c1dafa2a4ab5860b801aebe339960a7540"
    )
    assert len(plan["sources"]) == 4
    assert plan["request_boundary"]["allowed_hosts"] == [acquire.USGS_HOST]
    assert plan["request_boundary"]["maximum_total_download_bytes"] == 4_000_000
    assert plan["request_boundary"][
        "event_selection_may_be_recomputed_from_outcomes"
    ] is False
    for event, source in zip(
        plan["selected_events"], plan["sources"], strict=True
    ):
        marker = acquire.stage29._parse_time(event["marker_time_utc"])
        assert source["begin_utc"] == acquire.stage29._iso(
            marker - timedelta(hours=24)
        )
        assert source["end_utc"] == acquire.stage29._iso(
            marker + timedelta(hours=24)
        )
        query = parse_qs(urlparse(source["url"]).query)
        assert query["monitoring_location_id"] == [acquire.TARGET_SITE_ID]
        assert query["parameter_code"] == [acquire.TARGET_PARAMETER_CODE]


def test_stage36_frozen_observation_plan_matches_compiler_and_hash():
    path = acquire.DEFAULT_OUTPUT / "observation_plan.json"

    assert json.loads(path.read_bytes()) == acquire.compile_observation_plan()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "6402bbe5ef8fabca8090590b97379cc422bfbc557df53829f23cbfd5869e4f6f"
    )


def test_stage36_observation_plan_rejects_selection_manifest_tampering(tmp_path):
    source = acquire.DEFAULT_OUTPUT / "event_selection_manifest.json"
    value = json.loads(source.read_bytes())
    value["selected_events"][0][
        "selected_without_release_or_downstream_values"
    ] = False
    path = tmp_path / "event_selection_manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="event_selection_manifest_invalid"):
        acquire.compile_observation_plan(path)


def test_stage36_url_allowlist_is_phase_specific():
    acquire._validate_url(
        "https://cwms-data.usace.army.mil/cwms-data/timeseries",
        allowed_host=acquire.CWMS_HOST,
    )
    acquire._validate_url(
        "https://api.waterdata.usgs.gov/anything",
        allowed_host=acquire.USGS_HOST,
    )
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url(
            "https://api.waterdata.usgs.gov/anything",
            allowed_host=acquire.CWMS_HOST,
        )


def _synthetic_event_series() -> tuple[tuple[datetime, float, int], ...]:
    result = []
    starts = (
        datetime(2030, 1, 1, tzinfo=UTC),
        datetime(2030, 8, 1, tzinfo=UTC),
        datetime(2031, 3, 1, tzinfo=UTC),
        datetime(2031, 10, 1, tzinfo=UTC),
    )
    for start, amplitude in zip(starts, (4.0, 3.0, 2.0, 1.0), strict=True):
        for index in range(145):
            result.append(
                (
                    start + timedelta(minutes=30 * index),
                    100.0 if index < 48 else 100.0 + amplitude,
                    0,
                )
            )
    return tuple(result)
