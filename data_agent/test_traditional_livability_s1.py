import pytest

from data_agent.uwm.traditional_livability_s1 import build_s1_facility_assessment


def _product():
    return {
        "schema": "uwm.traditional_livability.facility_product.v1",
        "product_id": "p1",
        "facilities": [
            {"source_dataset_id": "gaode_poi", "source_record_id": "1", "admin_code": "500103", "canonical_class": "education.primary_school", "mapping_status": "mapped_internal_taxonomy"},
            {"source_dataset_id": "gaode_poi", "source_record_id": "2", "admin_code": "500103", "canonical_class": "education.primary_school", "mapping_status": "mapped_internal_taxonomy"},
            {"source_dataset_id": "baidu_aoi", "source_record_id": "3", "admin_code": "渝中区", "canonical_class": "green_space.park", "mapping_status": "mapped_internal_taxonomy"},
            {"source_dataset_id": "gaode_poi", "source_record_id": "4", "admin_code": "500105", "canonical_class": "unmapped", "mapping_status": "unmapped"},
        ],
        "population_units": [
            {"admin_code": "500103", "admin_name": "渝中区", "population": 100000, "population_basis": "resident_population_2021"},
            {"admin_code": "500105", "admin_name": "江北区", "population": 200000, "population_basis": "resident_population_2021"},
        ],
        "claim_boundary": {"authoritative_fp_fpp_available": False},
        "production_blockers": ["facility_capacity_and_operating_status_missing"],
    }


def test_without_authoritative_standards_reports_inventory_not_compliance():
    result = build_s1_facility_assessment(assessment_id="s1", created_at="2026-07-10T12:00:00Z", facility_product=_product())

    assert result["schema"] == "uwm.traditional_livability.s1_assessment.v1"
    school = next(row for row in result["supply_metrics"] if row["admin_code"] == "500103" and row["canonical_class"] == "education.primary_school")
    assert school["facility_count"] == 2
    assert school["facilities_per_10000_residents"] == 0.2
    assert school["compliance_status"] == "not_assessed"
    assert school["gap_to_standard"] is None
    assert result["summary"]["unmatched_facility_count"] == 1
    assert result["summary"]["unmapped_facility_count"] == 1
    assert "authoritative_fp_fpp_thresholds_missing" in result["production_blockers"]


def test_authoritative_standard_enables_numeric_gap_with_provenance():
    standards = [{"canonical_class": "education.primary_school", "metric": "facilities_per_10000_residents", "threshold": 0.3, "unit": "facilities_per_10000_residents", "authority": "Customer LIV Standard", "effective_date": "2026-01-01", "evidence_level": "authoritative"}]

    result = build_s1_facility_assessment(assessment_id="s1", created_at="2026-07-10T12:00:00Z", facility_product=_product(), standards=standards)

    school = next(row for row in result["supply_metrics"] if row["admin_code"] == "500103" and row["canonical_class"] == "education.primary_school")
    assert school["compliance_status"] == "below_standard"
    assert school["gap_to_standard"] == -0.1
    assert school["standard"]["authority"] == "Customer LIV Standard"


def test_non_authoritative_or_incomplete_standards_are_rejected():
    result = build_s1_facility_assessment(assessment_id="s1", created_at="2026-07-10T12:00:00Z", facility_product=_product(), standards=[{"canonical_class": "education.primary_school", "metric": "facilities_per_10000_residents", "threshold": 0.3, "evidence_level": "proxy"}])

    assert len(result["rejected_standards"]) == 1
    assert all(row["compliance_status"] == "not_assessed" for row in result["supply_metrics"])


def test_rejects_invalid_population_match_data():
    product = _product()
    product["population_units"][0]["population"] = 0
    with pytest.raises(ValueError, match="population_must_be_positive"):
        build_s1_facility_assessment(assessment_id="s1", created_at="2026-07-10T12:00:00Z", facility_product=product)
