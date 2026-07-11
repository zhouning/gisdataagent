from __future__ import annotations

from copy import deepcopy
import json
import time

import pytest
from shapely.geometry import Point, box, mapping, shape

import data_agent.uwm.traditional_livability_s4 as s4
from data_agent.test_traditional_livability_s6 import resource_fixture
from data_agent.test_traditional_livability_s6_semantics import (
    authoritative_dictionary_fixture,
)
from data_agent.uwm.traditional_livability_facility_dictionary import (
    COMPATIBILITY_SCHEMA,
    compute_canonical_content_digest,
    validate_compatibility_matrix,
)


def _project(*, uses=None):
    uses = uses or [
        {
            "use_id": "use-market",
            "use_name": "农贸市场",
            "raw_use_type": "室内市场",
            "use_description": "固定室内市场",
            "gfa_m2": 1000.0,
            "gfa_share": 1.0,
            "confirmed_standard_class_id": "facility.market",
            "human_confirmation": None,
        }
    ]
    return {
        "schema": "uwm.traditional_livability.s4_project_request.v1",
        "valid": True,
        "project_id": "project-1",
        "actor_id": "planner-1",
        "normalized_request": {
            "analysis_area_id": "fulu_heping",
            "planning_parcel_id": "parcel-selected",
            "project_name": "和平村项目",
            "project_description": "测试",
            "uses": [{key: value for key, value in row.items() if key != "gfa_share"} for row in uses],
        },
        "uses": uses,
        "total_gfa_m2": sum(row["gfa_m2"] for row in uses),
        "content_digest": "sha256:" + "a" * 64,
    }


def _s1(*, status="not_assessed", gap=None, class_id="facility.market", area="fulu_heping"):
    standard = None
    if status != "not_assessed":
        standard = {
            "canonical_class": class_id,
            "metric": "facilities_per_10000_residents",
            "threshold": 0.3,
            "unit": "facilities_per_10000_residents",
            "authority": "Customer LIV Standard",
            "standard_id": "standard-market-1",
            "standard_version": "v1",
            "source_reference": "fixture://standard-market-1",
            "effective_date": "2026-01-01",
            "evidence_level": "authoritative",
            "admin_code": area,
        }
    payload = {
        "schema": "uwm.traditional_livability.s1_assessment.v1",
        "supply_metrics": [{
            "planning_area_id": area,
            "canonical_class": class_id,
            "metric": "facilities_per_10000_residents",
            "facility_count": 1,
            "facilities_per_10000_residents": 0.1,
            "compliance_status": status,
            "gap_to_standard": gap,
            "standard": standard,
            "capacity_assessment_available": False,
        }],
        "production_blockers": ["facility_capacity_missing"],
    }
    if status != "not_assessed":
        payload["content_digest"] = compute_canonical_content_digest(payload)
    return payload


def _resources():
    payload = json.loads(json.dumps(resource_fixture()))
    payload["content_digest"] = compute_canonical_content_digest(payload)
    return payload


def _redigest_resources(payload):
    detached = json.loads(json.dumps(payload))
    detached["content_digest"] = compute_canonical_content_digest(detached)
    return detached


def _dictionary():
    return authoritative_dictionary_fixture()


def _compatibility(*rules):
    if not rules:
        rules = ({
            "rule_id": "RULE-UNRELATED",
            "rule_version": "rule-v1",
            "subject_class_id": "facility.unrelated",
            "object_class_id": "facility.unrelated",
            "relationship": "compatible",
            "evidence_level": "authoritative",
            "applicability_conditions": {},
            "source_reference": "fixture://RULE-UNRELATED",
        },)
    payload = {
        "schema": COMPATIBILITY_SCHEMA,
        "matrix_version": "matrix-v1",
        "issuing_organization": "Fixture standards authority",
        "source_reference": "fixture://compatibility",
        "effective_date": "2026-07-10",
        "version_date": "2026-07-10",
        "imported_at": "2026-07-10T00:00:00Z",
        "rules": list(rules),
    }
    payload["content_digest"] = compute_canonical_content_digest(payload)
    result = validate_compatibility_matrix(payload)
    assert result["ready"] is True
    return result


def _rule(*, purpose=None, evidence_level="authoritative"):
    return {
        "rule_id": "RULE-DUPLICATE",
        "rule_version": "rule-v1",
        "subject_class_id": "facility.market",
        "object_class_id": "facility.market",
        "relationship": "conflict",
        "rule_purpose": purpose,
        "evidence_level": evidence_level,
        "applicability_conditions": {"input_modes": ["planning_parcel"]},
        "source_reference": "fixture://RULE-DUPLICATE",
    }


def _s6_result(*, confirmed_class="facility.market", conflict=False, same_class=True, unresolved=False):
    parcel_hit = {
        "channel": "planning",
        "evidence_id": "planning:parcel-selected",
        "resource_id": "parcel-selected",
        "resource_domain": "village_public_service_land",
        "compatibility_object_class_id": "village_public_service_land",
        "nearest_distance_m": 0.0,
        "geometry_ref": "geojson:planning:parcel-selected",
    }
    facility_hit = {
        "channel": "facility",
        "evidence_id": "facility:market-1",
        "facility_id": "market-1",
        "canonical_class": confirmed_class if same_class else "facility.other",
        "compatibility_object_class_id": confirmed_class if same_class else "facility.other",
        "nearest_distance_m": 80.0,
        "geometry_ref": "geojson:facility:market-1",
    }
    rules = []
    if conflict:
        rules = [{
            "rule_id": "rule-conflict",
            "relationship": "conflict",
            "applied_hit_ids": ["planning:parcel-selected"],
        }]
    unresolved_rows = [
        {"evidence_id": "facility:unknown", "facility_id": "unknown", "geometry_ref": "geojson:facility:unknown"}
    ] if unresolved else []
    return {
        "schema": "uwm.traditional_livability.s6_analysis.v1",
        "status": "confirmed_conflict" if conflict else "potential_conflict_review_required",
        "semantic_resolution": {
            "status": "resolved_authoritative_exact" if confirmed_class else "unresolved",
            "confirmed_standard_class_id": confirmed_class,
        },
        "normalized_request": {"confirmed_standard_class_id": confirmed_class},
        "planning_resource_hits": [parcel_hit],
        "current_facility_hits": [facility_hit] if same_class else [],
        "unresolved_objects": {
            "planning_resources": [],
            "current_facilities": unresolved_rows,
            "association_records": [],
        },
        "compatibility_rules_evaluated": rules,
        "applied_rule_ids": [row["rule_id"] for row in rules],
        "applied_rules": rules,
        "unruled_hit_ids": [] if conflict else [parcel_hit["evidence_id"], facility_hit["evidence_id"]],
        "validation_blockers": [],
        "production_blockers": ["facility_inventory_sampled_or_incomplete"],
        "completeness_warnings": [],
        "claim_boundary": "Spatial proximity alone is not a conflict.",
        "geometry_payload": {"max_display_feature_count": 1000, "truncated": False},
        "geojson": {
            "proposed_geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "screening_buffer": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
            "planning_resource_hits": {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "planning:parcel-selected", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]},
            "current_facility_hits": {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "facility:market-1", "properties": {}, "geometry": {"type": "Point", "coordinates": [1, 1]}}]},
            "unresolved_planning_resources": {"type": "FeatureCollection", "features": []},
            "unresolved_current_facilities": {"type": "FeatureCollection", "features": []},
        },
    }


def _patch_s6(monkeypatch, outputs):
    calls = []

    def fake_analyze(**kwargs):
        calls.append(deepcopy(kwargs))
        return deepcopy(outputs[len(calls) - 1])

    monkeypatch.setattr(s4, "analyze_s6_facility_proposal", fake_analyze)
    return calls


def test_calls_s6_once_per_use_with_selected_planning_parcel(monkeypatch):
    uses = [
        {**_project()["uses"][0], "use_id": "u1", "gfa_m2": 1000.0, "gfa_share": 0.25},
        {**_project()["uses"][0], "use_id": "u2", "gfa_m2": 3000.0, "gfa_share": 0.75},
    ]
    calls = _patch_s6(monkeypatch, [_s6_result(), _s6_result()])

    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())

    assert len(calls) == 2
    assert all(call["request"]["input_mode"] == "planning_parcel" for call in calls)
    assert all(call["request"]["parcel_id"] == "parcel-selected" for call in calls)
    assert all("planning_parcel_id" not in call["request"] for call in calls)
    assert result["use_assessments"][0]["parcel_direct_evidence"]["planning_resources"][0]["resource_id"] == "parcel-selected"
    assert result["use_assessments"][0]["neighborhood_evidence"]["planning_resources"] == []


def test_s1_not_assessed_is_background_only(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result()])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_not_assessed"
    assert result["use_assessments"][0]["status"] == "nearby_supply_review_required"
    assert result["project_summary"]["formal_alignment_enabled"] is False


def test_only_matching_authoritative_negative_gap_supports_demand(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result()])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_supported"
    assert result["use_assessments"][0]["demand_evidence"]["matched_metric"]["gap_to_standard"] == -0.2

    _patch_s6(monkeypatch, [_s6_result()])
    mismatch = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2, area="fulu_banzhu"), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assert mismatch["use_assessments"][0]["demand_evidence"]["status"] == "demand_evidence_not_matched"


def test_conflicting_evidence_is_retained_without_weighted_cancellation(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result(conflict=True)])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assessment = result["use_assessments"][0]
    assert assessment["status"] == "mixed_evidence_review_required"
    assert assessment["demand_evidence"]["status"] == "demand_supported"
    assert assessment["parcel_direct_evidence"]["authoritative_conflict"] is True
    assert "weighted_score" not in json.dumps(result, ensure_ascii=False)


def test_unresolved_semantics_and_gfa_status_totals_conserve(monkeypatch):
    uses = [
        {**_project()["uses"][0], "use_id": "u1", "gfa_m2": 1000.0, "gfa_share": 0.25},
        {**_project()["uses"][0], "use_id": "u2", "gfa_m2": 3000.0, "gfa_share": 0.75, "confirmed_standard_class_id": None},
    ]
    _patch_s6(monkeypatch, [_s6_result(), _s6_result(confirmed_class=None, same_class=False)])
    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assert result["use_assessments"][1]["status"] == "unresolved_review_required"
    totals = result["project_summary"]["gfa_by_status"]
    assert sum(row["gfa_m2"] for row in totals) == 4000.0
    assert sum(row["gfa_share"] for row in totals) == pytest.approx(1.0)
    assert {row["status"] for row in totals} == {"nearby_supply_review_required", "unresolved_review_required"}


def test_geojson_is_deduplicated_capped_detached_and_strict_json_safe(monkeypatch):
    uses = [
        {**_project()["uses"][0], "use_id": "u1", "gfa_m2": 1.0, "gfa_share": 0.5},
        {**_project()["uses"][0], "use_id": "u2", "gfa_m2": 1.0, "gfa_share": 0.5},
    ]
    outputs = [_s6_result(), _s6_result()]
    calls = _patch_s6(monkeypatch, outputs)
    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary=_dictionary(), compatibility_matrix=_compatibility())
    assert len(result["geojson"]["current_facility_hits"]["features"]) == 1
    assert len(result["geojson"]["planning_resource_hits"]["features"]) == 1
    result["geojson"]["current_facility_hits"]["features"][0]["properties"]["mutated"] = True
    assert "mutated" not in outputs[0]["geojson"]["current_facility_hits"]["features"][0]["properties"]
    assert calls
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


def test_real_s6_integration_uses_parcel_id_and_returns_hits():
    result = s4.assess_s4_project(
        project=_project(),
        s1_snapshot=_s1(),
        s6_resources=_resources(),
        facility_dictionary=_dictionary(),
        compatibility_matrix=_compatibility(),
    )

    assessment = result["use_assessments"][0]
    assert assessment["s6_status"] != "insufficient_evidence"
    assert "planning_parcel_id_missing" not in assessment["blockers"]
    assert assessment["parcel_direct_evidence"]["planning_resources"]
    assert assessment["neighborhood_evidence"]["current_facilities"]


def test_rejected_s6_class_never_falls_back_to_client_class(monkeypatch):
    rejected = _s6_result(confirmed_class=None, same_class=True)
    rejected["status"] = "insufficient_evidence"
    rejected["normalized_request"]["confirmed_standard_class_id"] = None
    rejected["validation_blockers"] = ["confirmed_standard_class_id_mismatch"]
    project = _project()
    project["uses"][0]["confirmed_standard_class_id"] = "facility.market"
    _patch_s6(monkeypatch, [rejected])

    result = s4.assess_s4_project(
        project=project,
        s1_snapshot=_s1(status="below_standard", gap=-0.2),
        s6_resources=_resources(),
        facility_dictionary=_dictionary(),
        compatibility_matrix=_compatibility(_rule(purpose="duplicate_supply")),
    )

    assessment = result["use_assessments"][0]
    assert assessment["confirmed_standard_class_id"] is None
    assert assessment["demand_evidence"]["status"] == "demand_not_assessed"
    assert assessment["duplicate_supply_evidence"]["status"] == "no_nearby_same_class_supply_detected"


@pytest.mark.parametrize(
    ("purpose", "evidence_level", "expected"),
    [
        (None, "authoritative", "nearby_same_class_supply_detected"),
        ("duplicate_supply", None, "nearby_same_class_supply_detected"),
        ("duplicate_supply", "authoritative", "duplicate_supply_risk"),
        ("capacity", "authoritative", "duplicate_supply_risk"),
    ],
)
def test_duplicate_risk_requires_applied_hit_rule_with_explicit_authority(
    monkeypatch, purpose, evidence_level, expected
):
    output = _s6_result(conflict=True)
    output["applied_rules"][0]["rule_id"] = "RULE-DUPLICATE"
    output["applied_rules"][0]["applied_hit_ids"] = ["facility:market-1"]
    _patch_s6(monkeypatch, [output])
    rule = _rule(purpose=purpose, evidence_level=evidence_level)
    result = s4.assess_s4_project(
        project=_project(),
        s1_snapshot=_s1(),
        s6_resources=_resources(),
        facility_dictionary=_dictionary(),
        compatibility_matrix=_compatibility(rule),
    )
    assert result["use_assessments"][0]["duplicate_supply_evidence"]["status"] == expected


def test_zero_distance_boundary_facility_remains_neighborhood(monkeypatch):
    output = _s6_result()
    output["current_facility_hits"][0]["facility_id"] = "facility-hit"
    output["current_facility_hits"][0]["evidence_id"] = "facility:facility-hit"
    output["current_facility_hits"][0]["nearest_distance_m"] = 0.0
    resources = _resources()
    parcel_geometry = resources["planning_resources"][0]["metric_geometry"]
    parcel = box(*shape(parcel_geometry).bounds)
    resources["current_facilities"][0]["metric_geometry"] = mapping(
        Point(parcel.bounds[2], (parcel.bounds[1] + parcel.bounds[3]) / 2)
    )
    resources = _redigest_resources(resources)
    _patch_s6(monkeypatch, [output])
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=resources,
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    direct = result["use_assessments"][0]["parcel_direct_evidence"]
    neighborhood = result["use_assessments"][0]["neighborhood_evidence"]
    assert direct["current_facilities"] == []
    assert neighborhood["current_facilities"][0]["channel"] == "facility"


def test_validated_authoritative_relationship_can_mark_direct(monkeypatch):
    output = _s6_result()
    output["current_facility_hits"][0].update({
        "spatial_relationship": "contained",
        "relationship_evidence": {
            "evidence_level": "authoritative",
            "source_reference": "fixture://parcel-facility-relation",
            "rule_version": "relation-v1",
        },
    })
    _patch_s6(monkeypatch, [output])
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=_resources(),
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    assert result["use_assessments"][0]["parcel_direct_evidence"]["current_facilities"][0]["facility_id"] == "market-1"


def test_contained_point_is_parcel_direct(monkeypatch):
    output = _s6_result()
    output["current_facility_hits"][0]["facility_id"] = "facility-hit"
    output["current_facility_hits"][0]["evidence_id"] = "facility:facility-hit"
    resources = _resources()
    parcel = shape(
        resources["planning_resources"][0]["metric_geometry"]
    )
    resources["current_facilities"][0]["metric_geometry"] = mapping(
        parcel.representative_point()
    )
    resources = _redigest_resources(resources)
    _patch_s6(monkeypatch, [output])
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=resources,
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    assert result["use_assessments"][0]["parcel_direct_evidence"]["current_facilities"][0]["facility_id"] == "facility-hit"


def test_overlapping_polygon_is_direct_but_adjacent_touch_is_neighborhood(monkeypatch):
    output = _s6_result()
    resources = _resources()
    selected = shape(
        resources["planning_resources"][0]["metric_geometry"]
    )
    min_x, min_y, max_x, max_y = selected.bounds
    resources["planning_resources"][1]["metric_geometry"] = mapping(
        box(max_x - 5, min_y + 5, max_x + 5, max_y - 5)
    )
    resources["planning_resources"][2]["resource_id"] = "planning-touch"
    resources["planning_resources"][2]["metric_geometry"] = mapping(
        box(max_x, min_y + 5, max_x + 10, max_y - 5)
    )
    resources = _redigest_resources(resources)
    output["planning_resource_hits"].extend([
        {**output["planning_resource_hits"][0], "evidence_id": "planning:planning-hit", "resource_id": "planning-hit"},
        {**output["planning_resource_hits"][0], "evidence_id": "planning:planning-touch", "resource_id": "planning-touch"},
    ])
    _patch_s6(monkeypatch, [output])
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=resources,
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    direct_ids = {row["resource_id"] for row in result["use_assessments"][0]["parcel_direct_evidence"]["planning_resources"]}
    neighborhood_ids = {row["resource_id"] for row in result["use_assessments"][0]["neighborhood_evidence"]["planning_resources"]}
    assert "planning-hit" in direct_ids
    assert "planning-touch" in neighborhood_ids


def test_mutated_normalized_dictionary_with_stale_digest_fails_closed():
    dictionary = _dictionary()
    dictionary["classes"][0]["class_id"] = "facility.tampered"
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=_resources(),
        facility_dictionary=dictionary, compatibility_matrix=_compatibility()
    )
    assert result["status"] == "insufficient_evidence"
    assert result["project_blockers"] == ["facility_dictionary_contract_invalid"]


def test_mutated_normalized_matrix_with_stale_digest_fails_closed():
    matrix = _compatibility(_rule(purpose="duplicate_supply"))
    matrix["rules"][0]["rule_purpose"] = "tampered"
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=_s1(), s6_resources=_resources(),
        facility_dictionary=_dictionary(), compatibility_matrix=matrix
    )
    assert result["status"] == "insufficient_evidence"
    assert result["project_blockers"] == ["compatibility_matrix_contract_invalid"]


def test_malformed_inputs_fail_closed_and_project_total_is_recomputed():
    project = _project()
    project["total_gfa_m2"] = 9999.0
    resources = _resources()
    resources["content_digest"] = "sha256:tampered"
    result = s4.assess_s4_project(
        project=project,
        s1_snapshot={"schema": "wrong", "supply_metrics": []},
        s6_resources=resources,
        facility_dictionary={"ready": True},
        compatibility_matrix={"ready": True},
    )
    assert result["status"] == "insufficient_evidence"
    assert "project_total_gfa_mismatch" in result["project_blockers"]
    assert "s6_resources_snapshot_digest_mismatch" in result["project_blockers"]
    assert "facility_dictionary_contract_invalid" in result["project_blockers"]
    assert "compatibility_matrix_contract_invalid" in result["project_blockers"]
    assert "s1_snapshot_schema_invalid" in result["project_blockers"]


def test_current_s1_without_authoritative_digest_is_background_only(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result()])
    snapshot = _s1(status="below_standard", gap=-0.2)
    snapshot["supply_metrics"][0]["standard"].pop("standard_id")
    result = s4.assess_s4_project(
        project=_project(), s1_snapshot=snapshot, s6_resources=_resources(),
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_not_assessed"


def test_multi_use_real_s6_performance_and_output_detachment():
    base = _project()["uses"][0]
    uses = [
        {**base, "use_id": f"use-{index}", "gfa_m2": 100.0, "gfa_share": 0.1}
        for index in range(10)
    ]
    resources = _resources()
    started = time.perf_counter()
    result = s4.assess_s4_project(
        project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=resources,
        facility_dictionary=_dictionary(), compatibility_matrix=_compatibility()
    )
    elapsed = time.perf_counter() - started
    assert len(result["use_assessments"]) == 10
    assert elapsed < 5.0
    result["use_assessments"][0]["parcel_direct_evidence"]["planning_resources"][0]["resource_id"] = "mutated"
    assert resources["planning_resources"][0]["resource_id"] == "parcel-selected"
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)
