from copy import deepcopy

import pytest

from data_agent.uwm.traditional_social_public_service import (
    DEMAND12_CHANNELS,
    DEMAND21_CHANNELS,
    build_social_public_service_product,
)


def source_fixture():
    return {
        "facilities": [
            {
                "facility_id": "gov-1",
                "name": "甲街道办事处",
                "raw_category": "街道办事处",
                "canonical_category": "government_service",
                "longitude": 106.51,
                "latitude": 29.51,
                "admin_unit_id": "A",
                "source_dataset": "facility-product",
                "source_record_id": "1",
                "classification_method": "dictionary_exact",
                "classification_confidence": 1.0,
            },
            {
                "facility_id": "school-1",
                "name": "甲学校",
                "raw_category": "学校",
                "canonical_category": "education",
                "longitude": 106.52,
                "latitude": 29.52,
                "admin_unit_id": "A",
                "source_dataset": "facility-product",
                "source_record_id": "2",
                "classification_method": "dictionary_exact",
                "classification_confidence": 1.0,
            },
            {
                "facility_id": "park-1",
                "name": "乙公园",
                "raw_category": "公园",
                "canonical_category": "park_recreation",
                "longitude": 106.62,
                "latitude": 29.62,
                "admin_unit_id": "B",
                "source_dataset": "facility-product",
                "source_record_id": "3",
                "classification_method": "dictionary_exact",
                "classification_confidence": 1.0,
            },
        ],
        "admin_units": [
            {"admin_unit_id": "C", "county": "县C", "township": "镇C", "service_accessibility_score": None},
            {"admin_unit_id": "A", "county": "县A", "township": "镇A", "service_accessibility_score": 0.8},
            {"admin_unit_id": "B", "county": "县B", "township": "镇B", "service_accessibility_score": 0.2},
        ],
        "source_artifacts": ["facility.json", "accessibility.json"],
    }


def test_channel_registries_cover_required_evidence_and_closed_channels():
    assert set(DEMAND12_CHANNELS) == {
        "facility_inventory", "semantic_classification", "administrative_distribution",
        "category_diversity", "nearest_service_accessibility", "relative_evidence_gap",
        "authoritative_capacity", "population_capacity_match", "overload_determination",
        "lifecycle_status", "active_inactive_composition", "meps_bdms_verification",
        "authoritative_service_area", "future_demand",
    }
    assert set(DEMAND21_CHANNELS) == {
        "public_service_inventory", "semantic_classification", "administrative_distribution",
        "service_type_diversity", "nearest_service_accessibility", "relative_evidence_gap",
        "observed_service_availability", "authoritative_service_area",
        "population_service_match", "authoritative_service_deficit", "policy_effect",
    }


def test_product_builds_two_views_and_canonical_order():
    product = build_social_public_service_product(**source_fixture())

    assert product["schema"] == "traditional_livability.social_public_service.v1"
    assert [row["facility_id"] for row in product["facilities"]] == ["gov-1", "park-1", "school-1"]
    assert [row["admin_unit_id"] for row in product["admin_units"]] == ["A", "B", "C"]
    assert product["views"]["social_infrastructure"]["demand_id"] == "12"
    assert product["views"]["government_public_service"]["demand_id"] == "21"


def test_facility_membership_is_requirement_specific():
    product = build_social_public_service_product(**source_fixture())
    rows = {row["facility_id"]: row for row in product["facilities"]}

    assert rows["school-1"]["view_membership"] == ["social_infrastructure"]
    assert rows["park-1"]["view_membership"] == ["social_infrastructure"]
    assert rows["gov-1"]["view_membership"] == ["government_public_service"]


def test_unsupported_fields_remain_null_and_unavailable_channels_have_no_values():
    product = build_social_public_service_product(**source_fixture())

    for row in product["facilities"]:
        assert row["capacity"] is None
        assert row["lifecycle_status"] is None
        assert row["active_status"] is None
        assert row["service_radius_m"] is None
    for view in product["channel_readiness"].values():
        for readiness in view.values():
            if readiness["status"] == "unavailable":
                assert readiness["value"] is None


def test_missing_source_trace_and_duplicate_ids_are_rejected():
    sources = source_fixture()
    sources["facilities"][0]["source_dataset"] = ""
    with pytest.raises(ValueError, match="facility_source_trace_missing"):
        build_social_public_service_product(**sources)

    sources = source_fixture()
    sources["facilities"].append(deepcopy(sources["facilities"][0]))
    with pytest.raises(ValueError, match="duplicate_facility_id"):
        build_social_public_service_product(**sources)


def test_claim_boundary_forbids_capacity_deficit_future_and_policy_claims():
    product = build_social_public_service_product(**source_fixture())
    boundary = product["claim_boundary"]

    assert boundary["max_claim_level"] == "observed_inventory_and_relative_proxy"
    assert boundary["authoritative_service_deficit_claim"] is False
    assert boundary["authoritative_capacity_claim"] is False
    assert boundary["future_demand_claim"] is False
    assert boundary["causal_policy_effect_claim"] is False
