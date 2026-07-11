import json

from data_agent.uwm.traditional_livability_s6_s1_product import (
    build_s6_s1_product_bundle,
)


def _facility_product():
    return {
        "schema": "uwm.traditional_livability.facility_product.v1",
        "product_id": "facility-v1",
        "facilities": [{"facility_id": "f1", "canonical_class": "unmapped", "admin_code": "500120"}],
        "population_units": [{"admin_code": "500120", "population": 800000}],
        "source_manifest": {"schema": "uwm.traditional_livability.source_manifest.v1", "complete_inventory": False},
        "production_blockers": ["authoritative_fp_fpp_thresholds_missing"],
    }


def _s6_resources():
    return {
        "schema": "uwm.traditional_livability.s6_fulu_resources.v1",
        "ready": True,
        "content_digest": "sha256:s6",
        "planning_areas": [{"planning_area_id": "fulu_heping"}, {"planning_area_id": "fulu_banzhu"}],
        "current_facilities": [{"facility_id": "local-1", "planning_area_id": "fulu_heping"}],
        "source_manifest": {"complete_inventory": False},
    }


def test_real_bundle_keeps_profiles_unavailable_without_authoritative_standard(tmp_path):
    result = build_s6_s1_product_bundle(
        facility_product=_facility_product(), s6_resources=_s6_resources(), output_dir=tmp_path
    )
    assert result["ready"] is True
    profiles = json.loads((tmp_path / "uwm_traditional_livability_s1_profiles.json").read_text())
    manifest = json.loads((tmp_path / "uwm_traditional_livability_s6_s1_manifest.json").read_text())
    assert profiles["status"] == "unavailable"
    assert profiles["profiles"] == []
    assert "authoritative_s1_metric_profile_missing" in profiles["blockers"]
    assert manifest["workflow_ready"] is True
    assert manifest["s1_execution_ready"] is False
    assert manifest["fabricated_values"] == []


def test_bundle_uses_one_digest_and_preserves_sampled_inventory(tmp_path):
    build_s6_s1_product_bundle(
        facility_product=_facility_product(), s6_resources=_s6_resources(), output_dir=tmp_path
    )
    facility = json.loads((tmp_path / "uwm_traditional_livability_s6_s1_facility_product.json").read_text())
    resources = json.loads((tmp_path / "uwm_traditional_livability_s6_s1_resources.json").read_text())
    assert facility["bundle_id"] == resources["bundle_id"]
    assert facility["source_manifest"]["complete_inventory"] is False
    assert resources["source_manifest"]["complete_inventory"] is False
