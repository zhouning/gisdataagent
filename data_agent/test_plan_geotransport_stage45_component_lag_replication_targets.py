from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse

from scripts import plan_geotransport_stage45_component_lag_replication_targets as planner


def test_stage45_plan_binds_exact_frozen_protocol():
    plan = planner.compile_plan()

    assert plan["frozen_protocol_artifact"]["sha256"] == (planner.FROZEN_PROTOCOL_SHA256)
    assert planner.DEFAULT_OUTPUT.read_bytes() == planner.json_bytes(plan)
    assert len(hashlib.sha256(planner.DEFAULT_OUTPUT.read_bytes()).hexdigest()) == 64


def test_stage45_plan_has_four_downstream_only_requests_in_event_order():
    sources = planner.compile_plan()["sources"]

    assert len(sources) == 4
    assert tuple(value["event_id"] for value in sources) == (planner.freeze.EXPECTED_EVENT_IDS)
    assert {value["site_id"] for value in sources} == {"USGS-03424860"}
    assert {value["site_role"] for value in sources} == {"downstream_replication_outcome"}


def test_stage45_plan_preserves_exact_target_windows():
    sources = planner.compile_plan()["sources"]

    assert (
        tuple((value["begin_utc"], value["end_utc"]) for value in sources)
        == planner.freeze.EXPECTED_TARGET_WINDOWS_UTC
    )
    assert all(value["expected_maximum_inclusive_grid_positions"] == 169 for value in sources)


def test_stage45_plan_urls_are_exact_https_usgs_queries():
    sources = planner.compile_plan()["sources"]

    for source in sources:
        parsed = urlparse(source["url"])
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https"
        assert parsed.hostname == planner.USGS_HOST
        assert parsed.path == "/ogcapi/v0/collections/continuous/items"
        assert query == {
            "f": ["json"],
            "limit": ["10000"],
            "monitoring_location_id": ["USGS-03424860"],
            "parameter_code": ["00060"],
            "datetime": [f"{source['begin_utc']}/{source['end_utc']}"],
        }


def test_stage45_plan_bounds_attempts_and_download_bytes():
    boundary = planner.compile_plan()["request_boundary"]

    assert boundary["maximum_logical_request_count"] == 4
    assert boundary["maximum_attempts_per_request"] == 3
    assert boundary["maximum_total_attempt_count"] == 12
    assert boundary["maximum_response_bytes_per_attempt"] == 2_000_000
    assert boundary["maximum_persisted_download_bytes"] == 8_000_000
    assert boundary["maximum_total_response_bytes_across_attempts"] == 24_000_000


def test_stage45_plan_fails_closed_on_pagination_and_excludes_other_values():
    boundary = planner.compile_plan()["request_boundary"]

    assert boundary["unexpected_pagination_policy"] == "fail_closed"
    assert boundary["server_returned_pagination_followed"] is False
    assert boundary["smith_fork_graph_state_values_requested"] is False
    assert boundary["new_cwms_source_values_requested"] is False
    assert boundary["tailwater_elevation_values_requested"] is False


def test_stage45_planner_has_no_network_authority():
    plan = planner.compile_plan()
    execution = plan["request_execution"]

    assert execution["network_code_path_present_in_this_planner"] is False
    assert execution["request_execution_authorized"] is False
    assert execution["fresh_user_approval_required"] is True
    assert execution["approval_scope"] == "exact_four_stage45_logical_requests_only"


def test_stage45_plan_preserves_pending_claim_boundary():
    claims = planner.compile_plan()["claim_boundary"]

    assert claims["exact_request_plan_frozen"] is True
    assert claims["target_values_acquired"] is False
    assert claims["replication_test_executed"] is False
    assert claims["stage43_pattern_replicated"] is False
    assert claims["stage30_historical_falsification_overturned"] is False
    assert claims["causal_or_physical_relation_admitted"] is False
    assert claims["runtime_operator_admitted"] is False
