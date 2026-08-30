from __future__ import annotations

from pathlib import Path

from .semantic_readiness import audit_source, build_readiness_bundle

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / (
    "docs/customer/abu_dhabi_liveability_site_validation"
)


def test_full_readiness_audit_keeps_technical_and_business_scopes_separate():
    report = audit_source("liveability", ARTIFACT_ROOT)

    assert report["status"] == "pass"
    assert report["semantic_coverage"]["technical_resource_count"] == 161
    assert report["semantic_coverage"]["table_tier_counts"] == {
        "excluded": 13,
        "reviewed_executable": 8,
        "technical_metadata_only": 140,
    }
    assert report["metrics"]["unreviewed_inventory_contract_count"] == 138
    assert report["benchmark"]["technical_catalog_control_case_count"] == 390
    assert report["benchmark"]["reviewed_business_case_count"] == 78
    assert report["benchmark"]["business_language_unreviewed_case_count"] == 24
    assert report["release_gate"]["status"] == "not_ready"
    assert report["release_gate"]["production_promotion_authorized"] is False
    assert "all_tables_business_reviewed" in report["release_gate"]["blocking_reasons"]


def test_makani_readiness_reports_reviewed_contract_scope_without_promoting_catalog():
    report = audit_source("makani", ARTIFACT_ROOT)

    assert report["status"] == "pass"
    assert report["semantic_coverage"]["technical_resource_count"] == 772
    assert report["semantic_coverage"]["table_tier_counts"]["reviewed_executable"] == 604
    assert report["metrics"]["reviewed_contract_count"] == 25
    assert report["metrics"]["unreviewed_inventory_contract_count"] == 764
    assert report["benchmark"]["reviewed_business_case_count"] == 33
    assert report["benchmark"]["business_language_unreviewed_case_count"] == 1812
    assert report["relationships"]["candidate_count"] == 655
    assert report["relationships"]["reviewed_relationship_count"] == 14
    assert report["release_gate"]["production_promotion_authorized"] is False


def test_readiness_bundle_has_global_non_promotion_gate():
    bundle = build_readiness_bundle(ARTIFACT_ROOT)

    assert set(bundle["sources"]) == {"liveability", "makani"}
    assert bundle["global_release_gate"] == {
        "status": "not_ready",
        "production_promotion_authorized": False,
        "reason": "arbitrary_full_database_business_semantics_not_yet_reviewed",
    }
