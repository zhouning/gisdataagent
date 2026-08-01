from __future__ import annotations

import pytest

from scripts import (
    acquire_geotransport_stage27_public_spatial_boundary_evidence as acquire,
)


def test_stage27_plan_is_public_bounded_and_topology_first():
    plan = acquire.compile_plan()

    assert plan["mode"] == "plan"
    assert plan["target"] == {
        "root_comid": 18421703,
        "anchor_monitoring_location_id": "USGS-03424860",
    }
    boundary = plan["request_boundary"]
    assert boundary["workspace_or_private_data_sent"] is False
    assert boundary["maximum_candidate_count"] == 12
    assert boundary["maximum_request_count"] == 43
    assert boundary["maximum_match_window_count"] == 4
    assert boundary["match_window_half_width_seconds"] == 3600
    assert boundary["planned_maximum_bytes"] <= 34_000_000
    assert {
        value["navigation_code"] for value in plan["navigation_requests"]
    } == {"UT", "UM", "DM"}
    assert plan["candidate_follow_up"]["selection"] == (
        "union_of_returned_nldi_site_identifiers"
    )


def test_stage27_values_mode_keeps_spatial_claims_closed():
    plan = acquire.compile_plan(values_mode=True)

    assert plan["claim_boundary"]["source_values_acquired"] is True
    assert plan["claim_boundary"][
        "successive_anchor_records_may_replace_spatial_neighbor"
    ] is False
    assert plan["claim_boundary"]["spatial_boundary_pair_admitted"] is False
    assert plan["claim_boundary"]["operator_admitted"] is False


def test_stage27_rejects_unapproved_hosts():
    with pytest.raises(
        ValueError, match="stage27_spatial_boundary_url_outside_allowlist"
    ):
        acquire._validate_url("https://example.com/private")


def test_stage27_candidate_discovery_requires_returned_anchor():
    source_id = acquire.NAVIGATION_REQUESTS[0]["source_id"]
    bodies = {
        source_id: {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-85.9, 36.1],
                    },
                    "properties": {
                        "identifier": "USGS-03424850",
                        "name": "candidate",
                        "comid": 18421003,
                        "reachcode": "05130108000006",
                        "measure": 39.7942,
                        "mainstem": None,
                    },
                }
            ],
        }
    }

    with pytest.raises(
        ValueError, match="stage27_spatial_boundary_anchor_not_discovered"
    ):
        acquire._discover_candidates(bodies)


def test_stage27_candidate_follow_up_is_exactly_site_filtered():
    requests = acquire._candidate_requests("USGS-03424850", "03424850")

    assert len(requests) == 3
    assert requests[0]["url"].endswith(
        "/monitoring-locations/items/USGS-03424850?f=json"
    )
    assert all(
        "USGS-03424850" in value["url"] for value in requests
    )
