from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse

from scripts import plan_geotransport_stage39_component_discharge_values as plan


def test_stage39_plan_binds_the_frozen_protocol_exactly():
    value = plan.compile_plan()

    assert value["frozen_protocol_artifact"]["sha256"] == (plan.FROZEN_PROTOCOL_SHA256)
    assert value["frozen_protocol_artifact"]["path"].endswith(
        "stage39_center_hill_component_discharge_value_protocol/protocol.json"
    )


def test_stage39_plan_has_twenty_exact_component_year_requests():
    sources = plan.compile_plan()["sources"]

    assert len(sources) == 20
    assert [value["component"] for value in sources] == (
        ["orifice"] * 5 + ["sluice"] * 5 + ["spillway"] * 5 + ["turbine"] * 5
    )
    assert [value["source_id"] for value in sources[:5]] == [
        f"cwms_center_hill_orifice_{year}" for year in range(2021, 2026)
    ]


def test_stage39_each_component_covers_exact_five_annual_windows():
    sources = plan.compile_plan()["sources"]

    for component in ("orifice", "sluice", "spillway", "turbine"):
        component_sources = [value for value in sources if value["component"] == component]
        assert [(value["begin_utc"], value["end_utc"]) for value in component_sources] == list(
            plan.freeze.YEAR_WINDOWS
        )
        assert component_sources[0]["begin_utc"] == plan.freeze.BEGIN_UTC
        assert component_sources[-1]["end_utc"] == plan.freeze.END_UTC


def test_stage39_request_urls_preserve_identity_office_unit_and_page_size():
    for source in plan.compile_plan()["sources"]:
        parsed = urlparse(source["url"])
        query = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.hostname == plan.CWMS_HOST
        assert parsed.path == "/cwms-data/timeseries"
        assert query["name"] == [source["series_id"]]
        assert query["office"] == ["LRN"]
        assert query["unit"] == ["cms"]
        assert query["begin"] == [source["begin_utc"]]
        assert query["end"] == [source["end_utc"]]
        assert query["page-size"] == ["20000"]


def test_stage39_request_limits_include_retry_worst_case():
    boundary = plan.compile_plan()["request_boundary"]

    assert boundary["maximum_logical_request_count"] == 20
    assert boundary["maximum_attempts_per_request"] == 3
    assert boundary["maximum_total_attempt_count"] == 60
    assert boundary["maximum_response_bytes_per_attempt"] == 1_000_000
    assert boundary["maximum_persisted_download_bytes"] == 20_000_000
    assert boundary["maximum_total_response_bytes_across_attempts"] == 60_000_000
    assert boundary["unexpected_pagination_policy"] == "fail_closed"


def test_stage39_plan_requests_no_private_or_downstream_data():
    boundary = plan.compile_plan()["request_boundary"]

    assert boundary["workspace_or_private_data_sent"] is False
    assert boundary["downstream_or_tributary_outcome_values_requested"] is False
    assert boundary["tailwater_elevation_values_requested"] is False
    assert boundary["server_returned_pagination_followed"] is False


def test_stage39_plan_preserves_hourly_grid_and_duplicate_policy():
    support = plan.compile_plan()["source_support"]
    sources = plan.compile_plan()["sources"]

    assert support["expected_unique_inclusive_positions_per_component"] == 43_825
    assert support["expected_combined_component_positions"] == 175_300
    assert support["duplicate_boundary_policy"] == "require_identical_then_keep_one"
    assert support["missing_values_filled"] is False
    assert [value["expected_maximum_inclusive_grid_positions"] for value in sources[:5]] == [
        8_761,
        8_761,
        8_761,
        8_785,
        8_761,
    ]


def test_stage39_planner_has_no_network_execution_path_or_authority():
    value = plan.compile_plan()
    execution = value["request_execution"]
    claims = value["claim_boundary"]

    assert execution["network_code_path_present_in_this_planner"] is False
    assert execution["request_execution_authorized"] is False
    assert execution["fresh_user_approval_required"] is True
    assert claims["request_plan_frozen"] is True
    assert claims["component_values_acquired"] is False
    assert claims["synchronized_total_discharge_admitted"] is False
    assert claims["gate_command_admitted"] is False
    assert claims["runtime_operator_admitted"] is False


def test_stage39_plan_serialization_is_deterministic():
    first = plan.json_bytes(plan.compile_plan())
    second = plan.json_bytes(plan.compile_plan())

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"generated_at" not in first


def test_compiled_stage39_report_freezes_plan_with_values_pending_approval():
    from scripts import (
        compile_geotransport_stage39_component_discharge_value_plan_gates as gates,
    )

    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 34
    assert sum(report["gates"].values()) == 34
    assert report["all_gates_passed"] is True
    assert report["decision"]["component_discharge_value_request_plan_frozen"]
    assert report["decision"]["component_values_acquired"] is False
    assert report["decision"]["fresh_user_approval_required_before_value_requests"] is True
