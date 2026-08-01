from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import acquire_geotransport_stage29_blind_transfer_events as acquire


def test_stage29_selection_plan_is_release_only_and_predeclared():
    plan = acquire.compile_selection_plan()

    assert plan["mode"] == "selection_plan"
    assert plan["release_candidate_pool"] == {
        "series_id": (
            "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
        ),
        "office": "LRN",
        "begin": "2021-01-01T00:00:00Z",
        "end": "2026-01-01T00:00:00Z",
        "unit": "cms",
        "expected_inclusive_hour_count": 43825,
    }
    selection = plan["predeclared_event_selection"]
    assert selection["event_count"] == 3
    assert selection["minimum_absolute_one_hour_step_m3s"] == 50.0
    assert selection["minimum_window_range_m3s"] == 100.0
    assert selection["minimum_event_separation_days"] == 180
    assert selection["selected_role"] == "blind_transfer"
    diagnostic = plan["predeclared_transfer_diagnostic"]
    assert diagnostic["lag_candidates_hours"] == list(range(13))
    assert diagnostic["stage28_fixed_lag_hours"] == 6
    assert diagnostic["observation_extension_hours"] == 12
    assert diagnostic["stable_transfer_requirement"] == (
        "all_three_events_support_fixed_lag"
    )


def test_stage29_selection_phase_cannot_request_observation_values():
    plan = acquire.compile_selection_plan(values_mode=True)

    assert len(plan["sources"]) == 5
    assert plan["request_boundary"][
        "downstream_or_tributary_observation_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False
    assert all(
        "/continuous/items" not in value["url"]
        for value in plan["sources"]
    )
    assert {value["role"] for value in plan["sources"]} == {
        "release_only_event_candidate_pool",
        "observed_tributary_site_identity",
        "observed_tributary_parameter_and_time_support",
        "observed_tributary_comid_binding",
        "tributary_to_stonewall_downstream_topology_path",
    }


def test_stage29_observation_sources_are_event_frozen_and_extended():
    events = [
        {
            "event_id": f"event_{index}",
            "start_utc": f"202{index + 1}-01-01T00:00:00Z",
            "end_utc": f"202{index + 1}-01-04T00:00:00Z",
        }
        for index in range(3)
    ]
    sources = acquire._observation_sources(events)

    assert len(sources) == 6
    assert {value["site_id"] for value in sources} == {
        "USGS-03424860",
        "USGS-03424730",
    }
    assert {value["event_id"] for value in sources} == {
        "event_0",
        "event_1",
        "event_2",
    }
    assert all("T12%3A00%3A00Z" in value["url"] for value in sources)


def test_stage29_release_only_selection_is_deterministic():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    rows = []
    step_days = (50, 250, 500)
    for hour in range(700 * 24 + 1):
        value = 100.0
        for day in step_days:
            if day * 24 <= hour < day * 24 + 24:
                value = 300.0
        timestamp = int((start + timedelta(hours=hour)).timestamp() * 1000)
        rows.append([timestamp, value, 0])

    candidates, selected = acquire._select_events({"values": rows})

    assert len(candidates) == 6
    assert len(selected) == 3
    assert [value["step_time_utc"] for value in selected] == [
        "2021-02-20T00:00:00Z",
        "2021-09-08T00:00:00Z",
        "2022-05-16T00:00:00Z",
    ]
    assert all(
        value["selected_without_observation_values"] is True
        and value["role"] == "blind_transfer"
        for value in selected
    )


def test_stage29_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "selection_plan.json"
    with pytest.raises(
        ValueError, match="stage29_plan_must_be_frozen_before_values"
    ):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())

    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="stage29_frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())


def test_stage29_rejects_unapproved_hosts_and_preserves_cwms_tls():
    with pytest.raises(ValueError, match="stage29_url_outside_allowlist"):
        acquire._validate_url("https://example.com/private")

    source = acquire._selection_sources()[0]
    command = acquire._cwms_curl_command(
        source["url"],
        resolved_ip="3.30.180.152",
        timeout_seconds=90.0,
    )
    assert command[:5] == [
        "curl",
        "--noproxy",
        "*",
        "--resolve",
        "cwms-data.usace.army.mil:443:3.30.180.152",
    ]
    assert "-k" not in command
    assert "--insecure" not in command
