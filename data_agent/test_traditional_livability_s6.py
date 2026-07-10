from __future__ import annotations

import json

from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape

from data_agent.uwm.traditional_livability_s6 import (
    SCREENING_DISTANCE_M,
    analyze_s6_facility_proposal,
    validate_s6_request,
)
from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
)


AREA_ID = "fulu_heping"
DISTANCE_CRS = "EPSG:4523"
ORIGIN_LON = 106.0
ORIGIN_LAT = 29.5


def _metric_point(longitude: float = ORIGIN_LON, latitude: float = ORIGIN_LAT):
    transformer = Transformer.from_crs("EPSG:4326", DISTANCE_CRS, always_xy=True)
    return Point(*transformer.transform(longitude, latitude))


def _display_geometry(metric_geometry):
    transformer = Transformer.from_crs(DISTANCE_CRS, "EPSG:4326", always_xy=True)
    from shapely.ops import transform

    return mapping(transform(transformer.transform, metric_geometry))


def resource_fixture(*, complete_inventory: bool = False) -> dict:
    origin = _metric_point()
    area_geometry = box(origin.x - 1000, origin.y - 1000, origin.x + 1000, origin.y + 1000)
    selected_parcel = box(origin.x - 20, origin.y - 20, origin.x + 20, origin.y + 20)
    planning_hit = box(origin.x + 100, origin.y - 10, origin.x + 130, origin.y + 10)
    unresolved_planning = box(origin.x - 140, origin.y - 10, origin.x - 120, origin.y + 10)
    other_area_parcel = box(origin.x + 5000, origin.y + 5000, origin.x + 5040, origin.y + 5040)
    facility_hit = Point(origin.x, origin.y + 80)
    unresolved_facility = Point(origin.x, origin.y - 90)
    return {
        "schema": "uwm.traditional_livability.s6_fulu_resources.v1",
        "ready": True,
        "scope": "fulu_heping_and_banzhu_planning_samples_only",
        "source_manifest": {"ready": True, "blockers": []},
        "planning_areas": [
            {
                "planning_area_id": AREA_ID,
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(area_geometry),
                "display_geometry_wgs84": _display_geometry(area_geometry),
            },
            {
                "planning_area_id": "fulu_banzhu",
                "distance_crs": "EPSG:32648",
                "metric_geometry": mapping(other_area_parcel.buffer(1000)),
                "display_geometry_wgs84": mapping(box(106.5, 29.5, 106.6, 29.6)),
            },
        ],
        "planning_resources": [
            {
                "resource_id": "parcel-selected",
                "source_record_id": "source-selected",
                "planning_area_id": AREA_ID,
                "source_layer": "TDGHDL",
                "raw_land_use_code": "2123",
                "raw_land_use_name": "村公共服务用地",
                "resource_domain": "village_public_service_land",
                "interpretation_rule": "planning_land_use_code.v1",
                "interpretation_evidence": {"field": "DLBM", "value": "2123"},
                "planning_status": "planned",
                "planning_status_evidence": {"field": "STATUS", "value": "planned"},
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(selected_parcel),
                "display_geometry_wgs84": _display_geometry(selected_parcel),
            },
            {
                "resource_id": "planning-hit",
                "source_record_id": "source-planning-hit",
                "planning_area_id": AREA_ID,
                "source_layer": "JQDLTB",
                "raw_land_use_code": "2123",
                "raw_land_use_name": "村公共服务用地",
                "resource_domain": "village_public_service_land",
                "interpretation_rule": "planning_land_use_code.v1",
                "interpretation_evidence": {"field": "DLBM", "value": "2123"},
                "planning_status": "current",
                "planning_status_evidence": {"field": "STATUS", "value": "current"},
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(planning_hit),
                "display_geometry_wgs84": _display_geometry(planning_hit),
            },
            {
                "resource_id": "planning-unresolved",
                "source_record_id": "source-planning-unresolved",
                "planning_area_id": AREA_ID,
                "source_layer": "JQDLTB",
                "raw_land_use_code": "9999",
                "raw_land_use_name": "未知用地",
                "resource_domain": "unresolved",
                "interpretation_rule": None,
                "interpretation_evidence": None,
                "planning_status": "status_unknown",
                "planning_status_evidence": None,
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(unresolved_planning),
                "display_geometry_wgs84": _display_geometry(unresolved_planning),
            },
            {
                "resource_id": "other-area-parcel",
                "source_record_id": "source-other-area",
                "planning_area_id": "fulu_banzhu",
                "distance_crs": "EPSG:32648",
                "metric_geometry": mapping(other_area_parcel),
                "display_geometry_wgs84": mapping(box(106.5, 29.5, 106.51, 29.51)),
            },
        ],
        "current_facilities": [
            {
                "facility_id": "facility-hit",
                "source_dataset_id": "facility-product",
                "source_record_id": "facility-source-hit",
                "name": "现状市场",
                "canonical_class": "facility.market",
                "mapping_status": "mapped_internal_taxonomy",
                "mapping_version": "traditional_livability_facility_mapping.v1",
                "geometry_type": "Point",
                "association_status": "single_area_intersection",
                "planning_area_id": AREA_ID,
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(facility_hit),
                "display_geometry_wgs84": _display_geometry(facility_hit),
            },
            {
                "facility_id": "facility-unresolved",
                "source_dataset_id": "facility-product",
                "source_record_id": "facility-source-unresolved",
                "name": "未知设施",
                "canonical_class": None,
                "mapping_status": "unmapped",
                "mapping_version": "traditional_livability_facility_mapping.v1",
                "geometry_type": "Point",
                "association_status": "single_area_intersection",
                "planning_area_id": AREA_ID,
                "distance_crs": DISTANCE_CRS,
                "metric_geometry": mapping(unresolved_facility),
                "display_geometry_wgs84": _display_geometry(unresolved_facility),
            },
            {
                "facility_id": "facility-multi-area",
                "source_record_id": "facility-source-multi-area",
                "mapping_status": "unmapped",
                "association_status": "multi_area_overlap_unresolved",
                "matching_planning_area_ids": [AREA_ID, "fulu_banzhu"],
                "planning_area_id": None,
                "distance_crs": None,
                "metric_geometry": None,
                "display_geometry_wgs84": mapping(Point(ORIGIN_LON, ORIGIN_LAT)),
            },
        ],
        "facility_inventory": {
            "complete_inventory": complete_inventory,
            "mapping_version": "traditional_livability_facility_mapping.v1",
            "source_manifest": {"complete_inventory": complete_inventory},
        },
    }


def point_request(**overrides) -> dict:
    request = {
        "input_mode": "point",
        "analysis_area_id": AREA_ID,
        "longitude": ORIGIN_LON,
        "latitude": ORIGIN_LAT,
        "facility_name": "流动餐饮点",
        "raw_facility_type": "食品车",
        "use_description": "提供餐饮服务",
    }
    request.update(overrides)
    return request


def parcel_request(**overrides) -> dict:
    request = point_request(input_mode="planning_parcel", parcel_id="parcel-selected")
    request.pop("longitude")
    request.pop("latitude")
    request.update(overrides)
    return request


def unavailable_dictionary() -> dict:
    return {"ready": False, "status": "dictionary_unavailable", "classes": []}


def authoritative_dictionary(*class_ids: str, aliases: list[dict] | None = None) -> dict:
    return {
        "ready": True,
        "status": "ready",
        "classes": [{"class_id": class_id, "label": class_id} for class_id in class_ids],
        "aliases": aliases or [],
        "keywords": [],
        "source_metadata": {"dictionary_version": "dict-v1"},
        "content_digest": "sha256:fixture",
    }


def unavailable_compatibility() -> dict:
    return {"ready": False, "status": "compatibility_matrix_unavailable", "rules": []}


def compatibility(*rules: dict) -> dict:
    normalized_rules = list(rules)
    return {
        "schema": "uwm.traditional_livability.facility_compatibility.v1",
        "ready": True,
        "status": "ready",
        "rules": normalized_rules,
        "rule_index": {
            row["rule_id"]: row for row in normalized_rules if row["rule_id"]
        },
        "source_metadata": {
            "matrix_version": "matrix-v1",
            "issuing_organization": "Fixture standards authority",
            "source_reference": "fixture://compatibility",
            "effective_date": "2026-07-10",
            "version_date": "2026-07-10",
            "imported_at": "2026-07-10T00:00:00Z",
        },
        "content_digest": "sha256:fixture-matrix",
        "validation_errors": [],
        "production_blockers": [],
    }


def rule(
    *,
    rule_id: str,
    subject: str,
    object_id: str,
    relationship: str,
    applicability_conditions: dict | list | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "rule_version": "rule-v1",
        "subject_class_id": subject,
        "object_class_id": object_id,
        "relationship": relationship,
        "applicability_conditions": (
            {} if applicability_conditions is None else applicability_conditions
        ),
        "source_reference": f"fixture://{rule_id}",
    }


def confirmed_request(class_id: str) -> dict:
    request = point_request(
        facility_name="新型邻里服务点",
        raw_facility_type="未分类设施",
        use_description="现场材料由审查员核验",
        confirmed_standard_class_id=class_id,
    )
    resolution = resolve_s6_facility_semantics(
        facility_name=request["facility_name"],
        raw_facility_type=request["raw_facility_type"],
        use_description=request["use_description"],
        dictionary=authoritative_dictionary(class_id),
    )
    request["human_confirmation"] = {
            "actor_id": "planner-1",
            "confirmed_at": "2026-07-10T12:00:00Z",
            "selected_standard_class_id": class_id,
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "dict-v1",
            "selected_candidate": {
                "standard_class_id": class_id,
                "standard_class_label": class_id,
                "authority_level": "human_confirmation",
                "match_method": "human_selected",
                "confidence": "human_confirmed",
                "dictionary_version": "dict-v1",
                "rule_version": None,
                "human_confirmation_required": False,
                "human_confirmed": True,
                "evidence": [
                    {
                        "evidence_type": "reviewer_reason",
                        "reason": "Reviewer verified the proposed use against the case materials.",
                    }
                ],
            },
        }
    return request


def resources_without_unresolved_hits() -> dict:
    resources = resource_fixture(complete_inventory=True)
    resources["planning_resources"] = [
        row
        for row in resources["planning_resources"]
        if row["resource_id"] != "planning-unresolved"
    ]
    resources["current_facilities"] = [
        row
        for row in resources["current_facilities"]
        if row["facility_id"] == "facility-hit"
    ]
    return resources


def test_point_mode_returns_separate_planning_and_facility_hits():
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resource_fixture(),
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    assert result["screening"]["distance_m"] == SCREENING_DISTANCE_M
    assert result["screening"]["provider"] == "projected_planar_buffer"
    assert result["screening"]["distance_crs"] == DISTANCE_CRS
    assert {row["resource_id"] for row in result["planning_resource_hits"]} == {
        "parcel-selected",
        "planning-hit",
    }
    assert [row["facility_id"] for row in result["current_facility_hits"]] == [
        "facility-hit"
    ]
    assert result["unresolved_objects"]["planning_resources"][0]["resource_id"] == "planning-unresolved"
    assert result["unresolved_objects"]["current_facilities"][0]["facility_id"] == "facility-unresolved"
    assert result["unresolved_objects"]["association_records"][0]["facility_id"] == "facility-multi-area"


def test_point_is_projected_and_outputs_are_json_safe_geojson():
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resource_fixture(),
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    json.dumps(result, allow_nan=False)
    proposed = shape(result["geojson"]["proposed_geometry"])
    screening = shape(result["geojson"]["screening_buffer"])
    assert proposed.geom_type == "Point"
    assert abs(proposed.x - ORIGIN_LON) < 1e-8
    assert screening.geom_type == "Polygon"


def test_parcel_mode_buffers_actual_metric_polygon_geometry():
    resources = resource_fixture()
    result = analyze_s6_facility_proposal(
        request=parcel_request(),
        resources=resources,
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    selected = shape(resources["planning_resources"][0]["metric_geometry"])
    assert result["normalized_request"]["parcel_id"] == "parcel-selected"
    assert result["screening"]["input_geometry_type"] == "Polygon"
    assert result["screening"]["metric_buffer_area_m2"] > selected.buffer(149).area
    selected_hit = next(row for row in result["planning_resource_hits"] if row["resource_id"] == "parcel-selected")
    assert selected_hit["nearest_distance_m"] == 0.0
    assert selected_hit["intersection_area_m2"] == selected.area


def test_spatial_hits_without_rules_require_review():
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resource_fixture(),
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["max_claim_level"] == "spatial_screening_only"
    assert result["applied_rule_ids"] == []


def test_authoritative_rule_is_required_for_confirmed_conflict():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-001",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
            )
        ),
    )

    assert result["status"] == "confirmed_conflict"
    assert result["applied_rule_ids"] == ["RULE-001"]
    assert result["s1_handoff"]["ready"] is True
    assert result["s1_handoff"]["confirmed_standard_class_id"] == "facility.market"


def test_request_valid_flag_cannot_bypass_server_confirmation_validation():
    request = confirmed_request("facility.market")
    request["human_confirmation"]["valid"] = True
    request["human_confirmation"]["original_input_digest"] = "sha256:malicious"
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-001",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
            )
        ),
    )

    assert result["status"] == "insufficient_evidence"
    assert "original_input_digest_mismatch" in result["validation_blockers"]
    assert result["human_confirmation_validation"]["valid"] is False
    assert result["s1_handoff"]["ready"] is False


def test_missing_confirmation_audit_field_fails_closed_with_exact_error():
    request = confirmed_request("facility.market")
    request["human_confirmation"].pop("actor_id")
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(),
    )

    assert result["status"] == "insufficient_evidence"
    assert "actor_id_missing" in result["validation_blockers"]
    assert result["human_confirmation_validation"]["valid"] is False


def test_authoritative_alias_match_can_apply_rules_without_human_confirmation():
    result = analyze_s6_facility_proposal(
        request=point_request(facility_name="标准市场", raw_facility_type="市场"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary(
            "facility.market",
            aliases=[
                {
                    "alias": "标准市场",
                    "class_id": "facility.market",
                    "source_reference": "fixture://dictionary/market",
                }
            ],
        ),
        compatibility=compatibility(
            rule(
                rule_id="RULE-001",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
            )
        ),
    )

    assert result["semantic_resolution"]["resolution_status"] == "authoritative_confirmed"
    assert result["status"] == "confirmed_conflict"
    assert result["s1_handoff"]["ready"] is True


def test_matching_requested_class_accepts_current_authoritative_resolution():
    request = point_request(
        facility_name="标准市场",
        raw_facility_type="市场",
        confirmed_standard_class_id="facility.market",
    )
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary(
            "facility.market",
            aliases=[
                {
                    "alias": "标准市场",
                    "class_id": "facility.market",
                    "source_reference": "fixture://dictionary/market",
                }
            ],
        ),
        compatibility=compatibility(
            rule(
                rule_id="RULE-001",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
            )
        ),
    )

    assert result["status"] == "confirmed_conflict"
    assert result["normalized_request"]["confirmed_standard_class_id"] == "facility.market"
    assert result["semantic_resolution"]["resolution_status"] == "authoritative_confirmed"
    assert result["semantic_resolution"]["candidates"][0]["evidence"]
    assert result["human_confirmation_validation"] is None
    assert result["s1_handoff"]["confirmed_standard_class_id"] == "facility.market"


def test_requested_class_differing_from_authoritative_resolution_fails_closed():
    request = point_request(
        facility_name="标准市场",
        raw_facility_type="市场",
        confirmed_standard_class_id="facility.school",
    )
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary(
            "facility.market",
            "facility.school",
            aliases=[
                {
                    "alias": "标准市场",
                    "class_id": "facility.market",
                    "source_reference": "fixture://dictionary/market",
                }
            ],
        ),
        compatibility=compatibility(),
    )

    assert result["status"] == "insufficient_evidence"
    assert result["validation_blockers"] == [
        "confirmed_class_authoritative_mismatch"
    ]
    assert result["s1_handoff"]["ready"] is False


def test_valid_confirmation_differing_from_requested_class_fails_exactly():
    request = confirmed_request("facility.market")
    request["confirmed_standard_class_id"] = "facility.school"
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market", "facility.school"),
        compatibility=compatibility(),
    )

    assert result["status"] == "insufficient_evidence"
    assert result["validation_blockers"] == [
        "confirmed_class_confirmation_mismatch"
    ]
    assert result["normalized_request"]["confirmed_standard_class_id"] == "facility.school"
    assert result["s1_handoff"]["confirmed_standard_class_id"] is None


def test_valid_confirmation_supplies_class_when_request_omits_it():
    request = confirmed_request("facility.market")
    request.pop("confirmed_standard_class_id")
    result = analyze_s6_facility_proposal(
        request=request,
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-001",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
            )
        ),
    )

    assert result["human_confirmation_validation"]["valid"] is True
    assert result["normalized_request"]["confirmed_standard_class_id"] == "facility.market"
    assert result["s1_handoff"]["confirmed_standard_class_id"] == "facility.market"
    assert result["status"] == "confirmed_conflict"


def test_confirmed_conflict_precedes_compatible_rules_deterministically():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="RULE-Z", subject="facility.market", object_id="facility.market", relationship="compatible"),
            rule(rule_id="RULE-A", subject="facility.market", object_id="village_public_service_land", relationship="conflict"),
        ),
    )

    assert result["status"] == "confirmed_conflict"
    assert result["applied_rule_ids"] == ["RULE-A", "RULE-Z"]


def test_nonmatching_applicability_condition_is_reported_and_not_applied():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-AREA",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
                applicability_conditions={"planning_area_ids": ["fulu_banzhu"]},
            )
        ),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["applied_rule_ids"] == []
    evaluated = result["compatibility_rules_evaluated"][0]
    assert evaluated["rule_id"] == "RULE-AREA"
    assert evaluated["applicable"] is False
    assert evaluated["non_applicable_reasons"] == [
        "condition_not_matched:planning_area_ids"
    ]


def test_supported_applicability_conditions_all_match_the_current_hit():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-PLANNING-CONDITIONS",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
                applicability_conditions={
                    "planning_area_ids": [AREA_ID],
                    "input_modes": ["point"],
                    "planning_statuses": ["current", "planned"],
                    "resource_domains": ["village_public_service_land"],
                },
            ),
            rule(
                rule_id="RULE-FACILITY-CONDITIONS",
                subject="facility.market",
                object_id="facility.market",
                relationship="compatible",
                applicability_conditions={
                    "planning_area_ids": [AREA_ID],
                    "input_modes": ["point"],
                    "facility_geometry_types": ["Point"],
                },
            ),
        ),
    )

    assert result["status"] == "confirmed_conflict"
    assert result["applied_rule_ids"] == [
        "RULE-FACILITY-CONDITIONS",
        "RULE-PLANNING-CONDITIONS",
    ]
    assert all(row["applicable"] for row in result["compatibility_rules_evaluated"])


def test_unsupported_or_malformed_applicability_is_never_applied():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(
                rule_id="RULE-UNSUPPORTED",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
                applicability_conditions={"planning_area_types": ["village"]},
            ),
            rule(
                rule_id="RULE-MALFORMED",
                subject="facility.market",
                object_id="village_public_service_land",
                relationship="conflict",
                applicability_conditions={"input_modes": "point"},
            ),
        ),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["applied_rule_ids"] == []
    reasons = {
        row["rule_id"]: row["non_applicable_reasons"]
        for row in result["compatibility_rules_evaluated"]
    }
    assert reasons == {
        "RULE-MALFORMED": ["condition_malformed:input_modes"],
        "RULE-UNSUPPORTED": ["unsupported_condition:planning_area_types"],
    }


def test_authoritative_compatible_rules_with_no_conflict_confirm_compatibility():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resources_without_unresolved_hits(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="RULE-PLANNING", subject="facility.market", object_id="village_public_service_land", relationship="compatible"),
            rule(rule_id="RULE-FACILITY", subject="facility.market", object_id="facility.market", relationship="compatible"),
        ),
    )

    assert result["status"] == "confirmed_compatible"
    assert result["applied_rule_ids"] == ["RULE-FACILITY", "RULE-PLANNING"]
    assert result["max_claim_level"] == "authoritative_rule_applied"


def test_partial_compatible_rule_coverage_requires_review():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resources_without_unresolved_hits(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="RULE-FACILITY", subject="facility.market", object_id="facility.market", relationship="compatible")
        ),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["applied_rule_ids"] == ["RULE-FACILITY"]
    assert result["unruled_hit_ids"] == ["parcel-selected", "planning-hit"]


def test_unresolved_hit_blocks_confirmed_compatible():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="RULE-PLANNING", subject="facility.market", object_id="village_public_service_land", relationship="compatible"),
            rule(rule_id="RULE-FACILITY", subject="facility.market", object_id="facility.market", relationship="compatible"),
        ),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["unresolved_objects"]["planning_resources"]
    assert result["unresolved_objects"]["current_facilities"]


def test_sampled_inventory_no_hit_has_explicit_warning():
    resources = resource_fixture(complete_inventory=False)
    resources["planning_resources"] = []
    resources["current_facilities"] = []
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resources,
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    assert result["status"] == "no_screening_hit"
    assert "sampled_facility_inventory_no_hit_does_not_establish_absence" in result["completeness_warnings"]
    assert result["max_claim_level"] == "loaded_snapshot_no_hit_only"


def test_unresolved_multi_area_association_alone_does_not_create_a_hit():
    resources = resource_fixture(complete_inventory=True)
    resources["planning_resources"] = []
    resources["current_facilities"] = [resources["current_facilities"][2]]
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resources,
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    assert result["status"] == "no_screening_hit"
    assert result["unresolved_objects"]["association_records"]


def test_invalid_coordinates_fail_closed_before_spatial_screening():
    result = analyze_s6_facility_proposal(
        request=point_request(longitude=181),
        resources=resource_fixture(),
        dictionary=unavailable_dictionary(),
        compatibility=unavailable_compatibility(),
    )

    assert result["status"] == "insufficient_evidence"
    assert result["validation_blockers"] == ["invalid_point_coordinates"]
    assert result["planning_resource_hits"] == []


def test_unknown_parcel_and_cross_area_parcel_are_rejected():
    resources = resource_fixture()
    unknown = validate_s6_request(parcel_request(parcel_id="missing"), resources)
    cross_area = validate_s6_request(parcel_request(parcel_id="other-area-parcel"), resources)

    assert unknown["valid"] is False
    assert unknown["blockers"] == ["unknown_planning_parcel:missing"]
    assert cross_area["valid"] is False
    assert cross_area["blockers"] == ["planning_parcel_outside_selected_area:other-area-parcel"]


def test_missing_parcel_geometry_and_crs_fail_closed():
    resources = resource_fixture()
    resources["planning_resources"][0]["metric_geometry"] = None
    missing_geometry = validate_s6_request(parcel_request(), resources)
    resources = resource_fixture()
    resources["planning_areas"][0]["distance_crs"] = None
    missing_crs = validate_s6_request(point_request(), resources)

    assert missing_geometry["blockers"] == ["planning_parcel_geometry_missing:parcel-selected"]
    assert missing_crs["blockers"] == ["planning_area_distance_crs_missing:fulu_heping"]


def test_unconfirmed_class_cannot_apply_rules_or_enable_s1_handoff():
    result = analyze_s6_facility_proposal(
        request=point_request(confirmed_standard_class_id="facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="RULE-001", subject="facility.market", object_id="village_public_service_land", relationship="conflict")
        ),
    )

    assert result["status"] == "insufficient_evidence"
    assert result["validation_blockers"] == ["confirmed_class_requires_valid_human_confirmation"]
    assert result["applied_rule_ids"] == []
    assert result["s1_handoff"]["ready"] is False


def test_invalid_authoritative_rule_id_cannot_create_confirmed_state():
    result = analyze_s6_facility_proposal(
        request=confirmed_request("facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary("facility.market"),
        compatibility=compatibility(
            rule(rule_id="", subject="facility.market", object_id="village_public_service_land", relationship="conflict")
        ),
    )

    assert result["status"] == "potential_conflict_review_required"
    assert result["applied_rule_ids"] == []
