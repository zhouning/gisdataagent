import json

from data_agent.uwm.traditional_livability_s7_gated_product import build_gated_s7_product


def _s7():
    return {
        "schema": "uwm.traditional_livability.s7_siting.v1",
        "siting_id": "s7-real",
        "created_at": "2026-07-10T00:00:00Z",
        "planning_area_ids": ["fulu_heping", "fulu_banzhu"],
        "assumptions": {"facility_type": "education.primary_school", "coverage_distance_m": 1500.0},
        "data_support": {"planning_scope": "fulu_heping_and_banzhu_planning_samples_only"},
        "ranked_candidates": [{"parcel_id": "p1"}, {"parcel_id": "p2"}],
        "selected_sites": [{"parcel_id": "p1", "selection_round": 1}],
        "geometry_payload": {},
        "production_blockers": ["authoritative_fp_fpp_thresholds_missing"],
        "claim_boundary": {"walking_or_network_service_area_assessed": False},
    }


def _s1():
    return {
        "schema": "uwm.traditional_livability.s1_assessment.v1",
        "assessment_id": "s1-real",
        "created_at": "2026-07-10T00:00:00Z",
        "facility_product_id": "facility-real",
        "production_blockers": ["authoritative_fp_fpp_thresholds_missing", "facility_capacity_missing"],
        "accepted_standards": [],
    }


def _facility():
    return {
        "schema": "uwm.traditional_livability.facility_product.v1",
        "product_id": "facility-real",
        "facilities": [{"facility_id": "f1"}],
        "source_manifest": {"complete_inventory": False},
    }


def test_real_product_is_unresolved_and_conditional_only(tmp_path):
    result = build_gated_s7_product(
        s7_snapshot=_s7(), s1_snapshot=_s1(), facility_product=_facility(), output_dir=tmp_path
    )
    assert result["ready"] is True
    gate = json.loads((tmp_path / "uwm_traditional_livability_s7_demand_gate.json").read_text())
    siting = json.loads((tmp_path / "uwm_traditional_livability_s7_gated.json").read_text())
    manifest = json.loads((tmp_path / "uwm_traditional_livability_s7_gated_manifest.json").read_text())
    assert gate["state"] == "need_unresolved"
    assert siting["recommendation_status"] == "conditional_candidate_ranking_available"
    assert all(row["not_a_site_recommendation"] for row in siting["ranked_candidates"])
    assert all(row["not_a_site_recommendation"] for row in siting["selected_sites"])
    assert manifest["fabricated_values"] == []
    assert manifest["authoritative_recommendation_available"] is False


def test_real_product_preserves_candidate_order_and_uses_one_bundle(tmp_path):
    build_gated_s7_product(
        s7_snapshot=_s7(), s1_snapshot=_s1(), facility_product=_facility(), output_dir=tmp_path
    )
    siting = json.loads((tmp_path / "uwm_traditional_livability_s7_gated.json").read_text())
    gate = json.loads((tmp_path / "uwm_traditional_livability_s7_demand_gate.json").read_text())
    assert [row["parcel_id"] for row in siting["ranked_candidates"]] == ["p1", "p2"]
    assert siting["bundle_id"] == gate["bundle_id"]
    assert siting["assumptions"]["coverage_distance_m"] == 1500.0
