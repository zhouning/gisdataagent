from __future__ import annotations

import pytest

from scripts import acquire_geotransport_stage23_usgs_channel_measurements as acquire


def test_stage23_acquisition_plan_is_bounded_public_and_site_filtered():
    plan = acquire.compile_plan()

    assert plan["mode"] == "plan"
    assert plan["target"]["monitoring_location_id"] == "USGS-03424860"
    assert plan["target"]["nwm_feature_id"] == 18421703
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False
    assert plan["request_boundary"]["maximum_total_download_bytes"] == 1_500_000
    assert plan["request_boundary"]["limit_per_items_request"] == 10_000
    assert all(
        "monitoring_location_id=USGS-03424860" in value["url"]
        for value in plan["requests"]
        if "/items?" in value["url"]
    )


def test_stage23_acquisition_keeps_hydraulic_claims_closed():
    plan = acquire.compile_plan(values_mode=True)

    assert plan["claim_boundary"]["source_values_acquired"] is True
    assert plan["claim_boundary"]["measurement_location_is_junction_patch"] is False
    assert plan["claim_boundary"][
        "single_measurement_defines_permanent_cross_section"
    ] is False
    assert plan["claim_boundary"]["gage_height_is_bed_referenced_depth"] is False
    assert plan["claim_boundary"]["operator_admitted"] is False


def test_stage23_acquisition_rejects_unapproved_host():
    with pytest.raises(
        ValueError, match="stage23_channel_measurement_url_outside_allowlist"
    ):
        acquire._validate_url("https://example.com/measurements")

