from copy import deepcopy

from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)
from data_agent.uwm.traditional_livability_s1_profiles import (
    MATRIX_SCHEMA,
    PROFILE_SCHEMA,
    unavailable_s1_metric_profiles,
    validate_s1_metric_profile,
    validate_s1_synthesis_matrix,
)


def _source():
    return {
        "issuing_organisation": "LIV Authority",
        "source_reference": "LIV-STD-001",
        "effective_date": "2026-01-01",
        "version": "v1",
    }


def _profile(*, dimensions=None, matrix_id="matrix-v1", method="euclidean_service_radius"):
    payload = {
        "schema": PROFILE_SCHEMA,
        "profile_id": "market-profile-v1",
        "standard_class_id": "facility.market",
        "standard_class_label": "市场",
        "dimensions": dimensions or ["FP", "FPP"],
        "source_metadata": _source(),
        "metrics": [
            {
                "dimension": "FP",
                "metric": "demand_geometry_coverage_rate",
                "unit": "percent",
                "comparator": ">=",
                "threshold": 90.0,
                "required_source_fields": ["geometry"],
                "spatial_method": method,
                "distance_crs": "EPSG:4547",
                "service_radius_m": 800.0,
            },
            {
                "dimension": "FPP",
                "metric": "facilities_per_10000_residents",
                "unit": "facilities_per_10000_residents",
                "comparator": ">=",
                "threshold": 1.0,
                "required_source_fields": ["population"],
            },
        ],
        "aggregation_geography": "planning_area",
        "synthesis_matrix_id": matrix_id,
        "authority_level": "authoritative",
    }
    payload["content_digest"] = compute_canonical_content_digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    return payload


def _matrix():
    payload = {
        "schema": MATRIX_SCHEMA,
        "matrix_id": "matrix-v1",
        "source_metadata": _source(),
        "outcomes": [
            {"fp_status": "meets", "fpp_status": "meets", "combined_status": "meets"},
            {"fp_status": "meets", "fpp_status": "does_not_meet", "combined_status": "does_not_meet"},
            {"fp_status": "does_not_meet", "fpp_status": "meets", "combined_status": "does_not_meet"},
            {"fp_status": "does_not_meet", "fpp_status": "does_not_meet", "combined_status": "does_not_meet"},
        ],
        "authority_level": "authoritative",
    }
    payload["content_digest"] = compute_canonical_content_digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    return payload


def test_valid_dual_profile_preserves_explicit_fp_and_fpp_rules():
    source = _profile()
    before = deepcopy(source)
    result = validate_s1_metric_profile(source)
    assert result["status"] == "valid"
    assert result["dimensions"] == ["FP", "FPP"]
    assert result["metrics"][0]["service_radius_m"] == 800.0
    assert source == before


def test_dual_profile_requires_matrix_reference():
    result = validate_s1_metric_profile(_profile(matrix_id=None))
    assert result["status"] == "invalid"
    assert "synthesis_matrix_reference_required" in result["blockers"]


def test_network_profile_requires_authoritative_network_contract():
    profile = _profile(method="network_service_area")
    profile["metrics"][0].pop("service_radius_m")
    profile["content_digest"] = compute_canonical_content_digest(
        {key: value for key, value in profile.items() if key != "content_digest"}
    )
    result = validate_s1_metric_profile(profile)
    assert result["status"] == "invalid"
    assert "authoritative_network_reference_required" in result["blockers"]


def test_s6_screening_distance_is_not_a_profile_default():
    result = unavailable_s1_metric_profiles()
    assert result["status"] == "unavailable"
    assert "service_radius_m" not in result
    assert "authoritative_s1_metric_profile_missing" in result["blockers"]


def test_valid_matrix_requires_all_four_dimension_pairs():
    result = validate_s1_synthesis_matrix(_matrix())
    assert result["status"] == "valid"
    incomplete = _matrix()
    incomplete["outcomes"].pop()
    incomplete["content_digest"] = compute_canonical_content_digest(
        {key: value for key, value in incomplete.items() if key != "content_digest"}
    )
    result = validate_s1_synthesis_matrix(incomplete)
    assert result["status"] == "invalid"
    assert "synthesis_matrix_incomplete" in result["blockers"]
