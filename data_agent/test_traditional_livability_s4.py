from __future__ import annotations

from copy import deepcopy
import json

import pytest

import data_agent.uwm.traditional_livability_s4 as s4


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
            "effective_date": "2026-01-01",
            "evidence_level": "authoritative",
        }
    return {
        "schema": "uwm.traditional_livability.s1_assessment.v1",
        "supply_metrics": [{
            "planning_area_id": area,
            "canonical_class": class_id,
            "facility_count": 1,
            "facilities_per_10000_residents": 0.1,
            "compliance_status": status,
            "gap_to_standard": gap,
            "standard": standard,
            "capacity_assessment_available": False,
        }],
        "production_blockers": ["facility_capacity_missing"],
    }


def _resources():
    return {"ready": True, "planning_areas": [{"planning_area_id": "fulu_heping"}]}


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

    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": False})

    assert len(calls) == 2
    assert all(call["request"]["input_mode"] == "planning_parcel" for call in calls)
    assert all(call["request"]["planning_parcel_id"] == "parcel-selected" for call in calls)
    assert result["use_assessments"][0]["parcel_direct_evidence"]["planning_resources"][0]["resource_id"] == "parcel-selected"
    assert result["use_assessments"][0]["neighborhood_evidence"]["planning_resources"] == []


def test_s1_not_assessed_is_background_only(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result()])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": False})
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_not_assessed"
    assert result["use_assessments"][0]["status"] == "nearby_supply_review_required"
    assert result["project_summary"]["formal_alignment_enabled"] is False


def test_only_matching_authoritative_negative_gap_supports_demand(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result()])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": True})
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_supported"
    assert result["use_assessments"][0]["demand_evidence"]["matched_metric"]["gap_to_standard"] == -0.2

    _patch_s6(monkeypatch, [_s6_result()])
    mismatch = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2, area="fulu_banzhu"), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": True})
    assert mismatch["use_assessments"][0]["demand_evidence"]["status"] == "demand_evidence_not_matched"


def test_conflicting_evidence_is_retained_without_weighted_cancellation(monkeypatch):
    _patch_s6(monkeypatch, [_s6_result(conflict=True)])
    result = s4.assess_s4_project(project=_project(), s1_snapshot=_s1(status="below_standard", gap=-0.2), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": True})
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
    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": False})
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
    result = s4.assess_s4_project(project=_project(uses=uses), s1_snapshot=_s1(), s6_resources=_resources(), facility_dictionary={"ready": True}, compatibility_matrix={"ready": False})
    assert len(result["geojson"]["current_facility_hits"]["features"]) == 1
    assert len(result["geojson"]["planning_resource_hits"]["features"]) == 1
    result["geojson"]["current_facility_hits"]["features"][0]["properties"]["mutated"] = True
    assert "mutated" not in outputs[0]["geojson"]["current_facility_hits"]["features"][0]["properties"]
    assert calls
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)
