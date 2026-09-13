import pytest

from data_agent.uwm.traditional_livability_s7 import build_s7_primary_school_siting


def _inputs(candidates=True):
    return {
        "planning_areas": [{"planning_area_id": "a", "distance_crs": "EPSG:4523"}],
        "demand_parcels": [
            {"planning_area_id": "a", "source_parcel_id": "d1", "weight_m2": 4000, "distance_crs": "EPSG:4523", "projected_centroid": {"x": 0, "y": 0}, "display_centroid": {"longitude": 106, "latitude": 29}},
            {"planning_area_id": "a", "source_parcel_id": "d2", "weight_m2": 2000, "distance_crs": "EPSG:4523", "projected_centroid": {"x": 1000, "y": 0}, "display_centroid": {"longitude": 106.01, "latitude": 29}},
        ],
        "candidate_parcels": ([
            {"planning_area_id": "a", "source_parcel_id": "candidate-best", "area_m2": 300, "suitability_score": 3, "distance_crs": "EPSG:4523", "projected_centroid": {"x": 0, "y": 0}, "display_centroid": {"longitude": 106.003, "latitude": 29}},
            {"planning_area_id": "a", "source_parcel_id": "candidate-repeat", "area_m2": 1000, "suitability_score": 2, "distance_crs": "EPSG:4523", "projected_centroid": {"x": 100, "y": 0}, "display_centroid": {"longitude": 106.005, "latitude": 29}},
            {"planning_area_id": "a", "source_parcel_id": "candidate-second", "area_m2": 100, "suitability_score": 1, "distance_crs": "EPSG:4523", "projected_centroid": {"x": 1000, "y": 0}, "display_centroid": {"longitude": 106.01, "latitude": 29}},
        ] if candidates else []),
        "excluded_parcels": [{"planning_area_id": "a", "exclusion_reason": "cultivated_land"}],
        "manifest": {"schema": "uwm.traditional_livability.s7_fulu_planning_inputs.v1", "ready": True, "sources": [{"relative_path": "fulu_heping/JQDLTB.shp"}]},
    }


def test_allocates_greedy_new_coverage_and_reports_distance_proxy():
    result = build_s7_primary_school_siting(siting_id="s7", created_at="2026-07-10T00:00:00Z", planning_inputs=_inputs(), school_supply=[], coverage_distance_m=600, max_sites=2)
    assert result["schema"] == "uwm.traditional_livability.s7_siting.v1"
    assert result["assumptions"]["distance_cost_provider"] == "projected_straight_line_distance_proxy"
    assert result["selected_sites"][0]["parcel_id"] == "candidate-best"
    assert result["selected_sites"][0]["newly_covered_proxy_area_m2"] == 4000
    assert result["demand_summary"]["unserved_proxy_area_m2"] == 0
    assert result["data_support"]["source_manifest_schema"] == "uwm.traditional_livability.s7_fulu_planning_inputs.v1"
    assert result["data_support"]["source_manifest_reference_count"] == 1
    assert "walking_minutes" not in str(result).lower()
    assert result["claim_boundary"]["walking_or_network_service_area_assessed"] is False


def test_no_candidates_returns_no_recommendation_not_fake_site():
    result = build_s7_primary_school_siting(siting_id="s7", created_at="2026-07-10T00:00:00Z", planning_inputs=_inputs(candidates=False), school_supply=[], coverage_distance_m=600, max_sites=2)
    assert result["recommendation_status"] == "no_recommendation"
    assert "candidate_policy_no_eligible_parcels" in result["production_blockers"]


def test_rejects_nonpositive_coverage_distance():
    with pytest.raises(ValueError, match="coverage_distance_m_must_be_positive"):
        build_s7_primary_school_siting(siting_id="s7", created_at="2026-07-10T00:00:00Z", planning_inputs=_inputs(), school_supply=[], coverage_distance_m=0, max_sites=1)
