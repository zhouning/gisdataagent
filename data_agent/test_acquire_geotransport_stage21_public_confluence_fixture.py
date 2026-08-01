from __future__ import annotations

import pytest

from scripts import acquire_geotransport_stage21_public_confluence_fixture as acquire


def test_stage21_acquisition_plan_is_public_bounded_and_minimal():
    plan = acquire.compile_plan()

    assert plan["mode"] == "plan"
    assert plan["target"]["site_id"] == "03424860"
    assert plan["target"]["target_feature_ids"] == [
        18421705,
        18421707,
        18421703,
    ]
    boundary = plan["request_boundary"]
    assert boundary["workspace_or_private_data_sent"] is False
    assert boundary["nldi_navigation_distance_km"] == 2.0
    assert boundary["terrain_export_shape"] == [64, 64]
    assert boundary["planned_maximum_bytes"] <= 1_000_000
    assert boundary["planned_request_count"] == 6
    assert all(
        str(value["url"]).startswith("https://")
        for value in plan["requests"]
    )


def test_stage21_acquisition_plan_preserves_claim_boundary_in_values_mode():
    plan = acquire.compile_plan(values_mode=True)

    assert plan["mode"] == "values"
    assert plan["claim_boundary"]["source_values_acquired"] is True
    assert plan["claim_boundary"]["terrain_is_channel_bathymetry"] is False
    assert plan["claim_boundary"][
        "land_cover_prior_is_calibrated_roughness"
    ] is False
    assert plan["claim_boundary"][
        "gauge_discharge_is_two_dimensional_momentum"
    ] is False
    assert plan["claim_boundary"]["operator_admitted"] is False


def test_stage21_acquisition_rejects_unapproved_host():
    with pytest.raises(
        ValueError, match="stage21_public_confluence_url_outside_allowlist"
    ):
        acquire._validate_url("https://example.com/private")


def test_stage21_cdl_response_must_return_an_allowed_https_url():
    body = (
        b'<GetCDLFileResponse><returnURL>'
        b'https://nassgeodata.gmu.edu/cache/clip.tif'
        b'</returnURL></GetCDLFileResponse>'
    )

    assert acquire._parse_cdl_return_url(body) == (
        "https://nassgeodata.gmu.edu/cache/clip.tif"
    )
    with pytest.raises(
        ValueError, match="stage21_public_confluence_url_outside_allowlist"
    ):
        acquire._parse_cdl_return_url(
            b"<x><returnURL>https://example.com/clip.tif</returnURL></x>"
        )

