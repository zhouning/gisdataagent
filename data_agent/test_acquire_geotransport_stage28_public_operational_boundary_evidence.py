from __future__ import annotations

import json

import pytest

from scripts import (
    acquire_geotransport_stage28_public_operational_boundary_evidence as acquire,
)


def test_stage28_plan_freezes_public_windows_and_lags_before_values():
    plan = acquire.compile_plan()

    assert plan["mode"] == "plan"
    assert plan["predeclared_diagnostic"] == {
        "lag_candidates_hours": list(range(13)),
        "development_event_id": "high_release_2024",
        "transfer_event_id": "low_release_2026",
        "selection_metric": "maximum_pearson_r_then_minimum_rmse",
        "cwms_support": "hour_average_timestamped_at_support_end",
        "usgs_aggregation": (
            "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
        ),
        "missing_sample_policy": "drop_hour_without_filling",
    }
    assert [(value["start"], value["end"]) for value in plan["events"]] == [
        ("2024-05-15T00:00:00Z", "2024-05-18T00:00:00Z"),
        ("2026-02-09T00:00:00Z", "2026-02-12T00:00:00Z"),
    ]
    boundary = plan["request_boundary"]
    assert boundary["workspace_or_private_data_sent"] is False
    assert boundary["maximum_request_count"] == 6
    assert boundary["planned_maximum_bytes"] <= 5_000_000
    assert boundary[
        "cwms_fixed_ip_fallback_retains_tls_hostname_verification"
    ] is True
    assert len(plan["sources"]) == 6


def test_stage28_values_mode_does_not_pre_admit_crosswalk_or_operator():
    plan = acquire.compile_plan(values_mode=True)

    assert plan["claim_boundary"]["source_values_acquired"] is True
    assert plan["claim_boundary"][
        "bounded_operational_release_windows_admitted"
    ] is False
    assert plan["claim_boundary"]["cwms_and_usgs_are_same_sensor"] is False
    assert plan["claim_boundary"]["travel_time_identified"] is False
    assert plan["claim_boundary"]["runtime_operator_admitted"] is False


def test_stage28_rejects_unapproved_hosts():
    with pytest.raises(
        ValueError, match="stage28_operational_boundary_url_outside_allowlist"
    ):
        acquire._validate_url("https://example.com/private")


def test_stage28_requires_exact_frozen_plan_before_value_access(tmp_path):
    path = tmp_path / "acquisition_plan.json"
    with pytest.raises(
        ValueError, match="stage28_acquisition_plan_must_be_frozen_before_values"
    ):
        acquire._load_frozen_plan(path)

    path.write_text(json.dumps({"schema": acquire.SCHEMA}), encoding="utf-8")
    with pytest.raises(
        ValueError, match="stage28_frozen_acquisition_plan_mismatch"
    ):
        acquire._load_frozen_plan(path)


def test_stage28_cwms_fixed_ip_fallback_preserves_tls_verification():
    source = next(
        value
        for value in acquire._compile_sources()
        if value["source_id"] == "cwms_tailwater_location"
    )
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
    assert command[-1] == source["url"]


def test_stage28_sources_are_exactly_scoped_by_event():
    sources = acquire._compile_sources()
    event_sources = [value for value in sources if value.get("event_id")]

    assert {value["event_id"] for value in event_sources} == {
        "high_release_2024",
        "low_release_2026",
    }
    assert len(event_sources) == 4
    assert all("2024-05-15" not in value["url"] for value in sources[:2])
    assert all(
        value["source"] in {"usace_cwms", "usgs_water_data"}
        for value in sources
    )
