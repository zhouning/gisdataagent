from copy import deepcopy

from shapely.geometry import Point, box, mapping

from data_agent.uwm.traditional_livability_s1_comparison import (
    compare_s1_baseline_and_proposal,
)


def _handoff():
    return {
        "schema": "uwm.traditional_livability.s6_s1_handoff.v1",
        "handoff_id": "handoff-1",
        "ready_for_s1": True,
        "actor_id": "alice",
        "confirmed_standard_class_id": "facility.market",
        "metric_profile_bundle_id": "profile-bundle-v1",
        "proposal": {
            "analysis_area_id": "area-1",
            "facility_name": "拟建市场",
            "metric_geometry": mapping(Point(1000, 0)),
            "metric_crs": "EPSG:3857",
            "proposed_geometry": {
                "type": "Feature",
                "geometry": mapping(Point(106.1, 29.5)),
                "properties": {},
            },
        },
        "source_resource_bundle": {"bundle_id": "facility-bundle-v1", "complete_inventory": True},
    }


def _facility_product():
    return {
        "product_id": "facilities-v1",
        "bundle_id": "facility-bundle-v1",
        "source_manifest": {"complete_inventory": True},
        "facilities": [
            {
                "facility_id": "market-1",
                "canonical_class": "facility.market",
                "admin_code": "area-1",
                "metric_geometry": mapping(Point(0, 0)),
                "metric_crs": "EPSG:3857",
            }
        ],
        "population_units": [{"admin_code": "area-1", "population": 20000}],
    }


def _demand_units():
    return [
        {
            "demand_unit_id": "near-existing",
            "admin_code": "area-1",
            "population": 100,
            "metric_geometry": mapping(box(-100, -100, 100, 100)),
            "metric_crs": "EPSG:3857",
        },
        {
            "demand_unit_id": "near-proposal",
            "admin_code": "area-1",
            "population": 100,
            "metric_geometry": mapping(box(900, -100, 1100, 100)),
            "metric_crs": "EPSG:3857",
        },
    ]


def _profile():
    return {
        "profile_id": "market-dual-v1",
        "standard_class_id": "facility.market",
        "status": "valid",
        "dimensions": ["FP", "FPP"],
        "metrics": [
            {
                "dimension": "FP",
                "metric": "population_weighted_demand_geometry_coverage_rate",
                "unit": "percent",
                "comparator": ">=",
                "threshold": 100.0,
                "spatial_method": "euclidean_service_radius",
                "distance_crs": "EPSG:3857",
                "service_radius_m": 300.0,
            },
            {
                "dimension": "FPP",
                "metric": "facility_count",
                "unit": "count",
                "comparator": ">=",
                "threshold": 2.0,
            },
        ],
        "synthesis_matrix_id": "matrix-v1",
    }


def _matrix():
    return {
        "status": "valid",
        "matrix_id": "matrix-v1",
        "content_digest": "sha256:matrix",
        "outcomes": [
            {"fp_status": "meets", "fpp_status": "meets", "combined_status": "meets"},
            {"fp_status": "meets", "fpp_status": "does_not_meet", "combined_status": "partially_meets"},
            {"fp_status": "does_not_meet", "fpp_status": "meets", "combined_status": "partially_meets"},
            {"fp_status": "does_not_meet", "fpp_status": "does_not_meet", "combined_status": "does_not_meet"},
        ],
    }


def test_comparison_is_static_and_not_a_world_model_rollout():
    result = compare_s1_baseline_and_proposal(
        handoff=_handoff(),
        facility_product=_facility_product(),
        demand_units=_demand_units(),
        profile=_profile(),
        synthesis_matrix=_matrix(),
    )
    assert result["method"] == "deterministic_static_proposal_comparison"
    assert result["claim_boundary"]["uwm_rollout"] is False
    assert result["claim_boundary"]["future_adaptation_assessed"] is False
    assert result["baseline"]["fp"]["observed_value"] == 50.0
    assert result["proposal_snapshot"]["fp"]["observed_value"] == 100.0
    assert result["baseline"]["fpp"]["observed_value"] == 1.0
    assert result["proposal_snapshot"]["fpp"]["observed_value"] == 2.0
    assert result["comparison"]["fp_delta"] == 50.0
    assert result["comparison"]["fpp_delta"] == 1.0


def test_baseline_input_is_not_mutated_by_proposal_insertion():
    product = _facility_product()
    handoff = _handoff()
    before_product = deepcopy(product)
    before_handoff = deepcopy(handoff)
    result = compare_s1_baseline_and_proposal(
        handoff=handoff,
        facility_product=product,
        demand_units=_demand_units(),
        profile=_profile(),
        synthesis_matrix=_matrix(),
    )
    result["proposal_snapshot"]["facility_ids"].append("mutated")
    assert product == before_product
    assert handoff == before_handoff


def test_bundle_or_profile_mismatch_fails_closed():
    handoff = _handoff()
    handoff["metric_profile_bundle_id"] = "other-profile-bundle"
    result = compare_s1_baseline_and_proposal(
        handoff=handoff,
        facility_product=_facility_product(),
        demand_units=_demand_units(),
        profile={**_profile(), "profile_bundle_id": "profile-bundle-v1"},
        synthesis_matrix=_matrix(),
    )
    assert result["status"] == "unresolved"
    assert "metric_profile_bundle_mismatch" in result["blockers"]


def test_missing_proposal_metric_geometry_keeps_fp_unresolved_but_count_changes():
    handoff = _handoff()
    handoff["proposal"].pop("metric_geometry")
    result = compare_s1_baseline_and_proposal(
        handoff=handoff,
        facility_product=_facility_product(),
        demand_units=_demand_units(),
        profile=_profile(),
        synthesis_matrix=_matrix(),
    )
    assert result["proposal_snapshot"]["fp"]["status"] == "unresolved"
    assert result["proposal_snapshot"]["fpp"]["observed_value"] == 2.0
    assert "proposal_metric_geometry_missing" in result["proposal_snapshot"]["fp"]["blockers"]
