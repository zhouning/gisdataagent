from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse

from scripts import plan_geotransport_stage42_component_event_targets as planner


def test_stage42_plan_binds_exact_frozen_protocol():
    plan = planner.compile_plan()

    assert plan["frozen_protocol_artifact"]["sha256"] == (
        planner.FROZEN_PROTOCOL_SHA256
    )
    assert planner.DEFAULT_OUTPUT.read_bytes() == planner.json_bytes(plan)
    assert hashlib.sha256(planner.DEFAULT_OUTPUT.read_bytes()).hexdigest() == (
        "28519b1c7834527da9b9b8c2bf30e15f15b293e040b264f60cdbf8df88449ef0"
    )


def test_stage42_plan_has_eight_requests_in_event_then_site_order():
    sources = planner.compile_plan()["sources"]

    assert len(sources) == 8
    assert [value["event_id"] for value in sources] == [
        event_id
        for event_id in planner.freeze.EXPECTED_EVENT_IDS
        for _ in range(2)
    ]
    assert [value["site_id"] for value in sources] == [
        "USGS-03424860",
        "USGS-03424730",
    ] * 4


def test_stage42_plan_preserves_exact_target_windows():
    sources = planner.compile_plan()["sources"]
    windows = [
        (value["begin_utc"], value["end_utc"])
        for value in sources[::2]
    ]

    assert windows == [
        ("2025-04-14T16:00:00Z", "2025-04-18T04:00:00Z"),
        ("2023-03-10T20:00:00Z", "2023-03-14T08:00:00Z"),
        ("2021-01-11T16:00:00Z", "2021-01-15T04:00:00Z"),
        ("2021-07-26T03:00:00Z", "2021-07-29T15:00:00Z"),
    ]
    assert all(value["expected_maximum_inclusive_grid_positions"] == 169 for value in sources)


def test_stage42_plan_urls_are_exact_https_usgs_queries():
    sources = planner.compile_plan()["sources"]

    for source in sources:
        parsed = urlparse(source["url"])
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https"
        assert parsed.hostname == planner.USGS_HOST
        assert parsed.path.endswith("/collections/continuous/items")
        assert query == {
            "f": ["json"],
            "limit": ["10000"],
            "monitoring_location_id": [source["site_id"]],
            "parameter_code": ["00060"],
            "datetime": [f"{source['begin_utc']}/{source['end_utc']}"],
        }


def test_stage42_plan_bounds_attempts_and_download_bytes():
    boundary = planner.compile_plan()["request_boundary"]

    assert boundary["maximum_logical_request_count"] == 8
    assert boundary["maximum_attempts_per_request"] == 3
    assert boundary["maximum_total_attempt_count"] == 24
    assert boundary["maximum_response_bytes_per_attempt"] == 2_000_000
    assert boundary["maximum_persisted_download_bytes"] == 16_000_000
    assert boundary["maximum_total_response_bytes_across_attempts"] == 48_000_000


def test_stage42_plan_fails_closed_on_unexpected_pagination():
    boundary = planner.compile_plan()["request_boundary"]

    assert boundary["server_returned_pagination_followed"] is False
    assert boundary["unexpected_pagination_policy"] == "fail_closed"
    assert boundary["ogc_limit"] == 10_000


def test_stage42_planner_has_no_network_execution_path_or_authority():
    plan = planner.compile_plan()
    execution = plan["request_execution"]

    assert execution["network_code_path_present_in_this_planner"] is False
    assert execution["request_execution_authorized"] is False
    assert execution["fresh_user_approval_required"] is True
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage42_plan_preserves_blinding_and_rejects_promotions():
    claims = planner.compile_plan()["claim_boundary"]

    assert claims["stage41_source_only_events_preserved"] is True
    assert claims["target_values_acquired"] is False
    assert claims["empirical_lag_support_sets_compiled"] is False
    assert claims["non_turbine_component_contrast_admitted"] is False
    assert claims["causal_intervention_admitted"] is False
    assert claims["physical_response_time_admitted"] is False
    assert claims["runtime_operator_admitted"] is False
