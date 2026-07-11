from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_s6 import (
    analyze_s6_facility_proposal,
)


SCHEMA = "uwm.traditional_livability.s4_project_assessment.v1"
_MAX_DISPLAY_FEATURE_COUNT = 1000


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _rows(payload: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _json_safe_detached(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )


def _confirmed_class(use: Mapping[str, Any], s6_result: Mapping[str, Any]) -> str | None:
    normalized = s6_result.get("normalized_request")
    if isinstance(normalized, Mapping):
        selected = _text(normalized.get("confirmed_standard_class_id"))
        if selected is not None:
            return selected
    return _text(use.get("confirmed_standard_class_id"))


def _authoritative_standard(row: Mapping[str, Any]) -> bool:
    standard = row.get("standard")
    return (
        isinstance(standard, Mapping)
        and standard.get("evidence_level") == "authoritative"
        and _text(standard.get("authority")) is not None
        and _text(standard.get("effective_date")) is not None
        and _text(standard.get("metric")) is not None
    )


def _area_matches(
    row: Mapping[str, Any],
    *,
    analysis_area_id: str,
    s6_resources: Mapping[str, Any],
) -> bool:
    accepted_ids = {analysis_area_id}
    for area in _rows(s6_resources, "planning_areas"):
        if _text(area.get("planning_area_id")) != analysis_area_id:
            continue
        for field in ("admin_code", "admin_id", "analysis_area_id"):
            value = _text(area.get(field))
            if value is not None:
                accepted_ids.add(value)
    represented = {
        value
        for field in ("planning_area_id", "analysis_area_id", "admin_code", "admin_id")
        if (value := _text(row.get(field))) is not None
    }
    return bool(represented & accepted_ids)


def _demand_evidence(
    *,
    s1_snapshot: Mapping[str, Any],
    s6_resources: Mapping[str, Any],
    analysis_area_id: str,
    confirmed_class_id: str | None,
) -> dict[str, Any]:
    if confirmed_class_id is None:
        return {"status": "demand_not_assessed", "matched_metric": None, "background_metrics": []}
    class_rows = [
        row
        for row in _rows(s1_snapshot, "supply_metrics")
        if _text(row.get("canonical_class")) == confirmed_class_id
    ]
    matching = [
        row
        for row in class_rows
        if _area_matches(
            row,
            analysis_area_id=analysis_area_id,
            s6_resources=s6_resources,
        )
    ]
    for row in matching:
        gap = row.get("gap_to_standard")
        if (
            row.get("compliance_status") == "below_standard"
            and isinstance(gap, (int, float))
            and not isinstance(gap, bool)
            and math.isfinite(float(gap))
            and float(gap) < 0
            and _authoritative_standard(row)
        ):
            return {
                "status": "demand_supported",
                "matched_metric": deepcopy(row),
                "background_metrics": [],
            }
    if matching and all(row.get("compliance_status") == "not_assessed" for row in matching):
        status = "demand_not_assessed"
    else:
        status = "demand_evidence_not_matched"
    return {
        "status": status,
        "matched_metric": None,
        "background_metrics": deepcopy(matching or class_rows),
    }


def _split_spatial_evidence(
    s6_result: Mapping[str, Any], planning_parcel_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    planning = [dict(row) for row in _rows(s6_result, "planning_resource_hits")]
    facilities = [dict(row) for row in _rows(s6_result, "current_facility_hits")]
    unresolved = s6_result.get("unresolved_objects")
    unresolved = unresolved if isinstance(unresolved, Mapping) else {}
    unresolved_planning = [dict(row) for row in _rows(unresolved, "planning_resources")]
    unresolved_facilities = [dict(row) for row in _rows(unresolved, "current_facilities")]
    direct_planning = [row for row in planning if _text(row.get("resource_id")) == planning_parcel_id]
    direct_unresolved = [row for row in unresolved_planning if _text(row.get("resource_id")) == planning_parcel_id]
    neighborhood_planning = [row for row in planning if _text(row.get("resource_id")) != planning_parcel_id]
    neighborhood_unresolved = [row for row in unresolved_planning if _text(row.get("resource_id")) != planning_parcel_id]
    direct_ids = {str(row.get("evidence_id")) for row in direct_planning + direct_unresolved}
    applied_rules = [dict(row) for row in _rows(s6_result, "applied_rules")]
    direct_rules = [
        row
        for row in applied_rules
        if direct_ids & {str(value) for value in row.get("applied_hit_ids") or []}
    ]
    neighborhood_rules = [row for row in applied_rules if row not in direct_rules]
    direct_conflict = any(row.get("relationship") == "conflict" for row in direct_rules)
    return (
        {
            "planning_resources": direct_planning,
            "unresolved_planning_resources": direct_unresolved,
            "applied_rules": direct_rules,
            "authoritative_conflict": direct_conflict,
            "claim_boundary": (
                "Parcel conflict is formal only when an applicable authoritative rule is retained."
            ),
        },
        {
            "planning_resources": neighborhood_planning,
            "current_facilities": facilities,
            "unresolved_planning_resources": neighborhood_unresolved,
            "unresolved_current_facilities": unresolved_facilities,
            "association_records": deepcopy(_rows(unresolved, "association_records")),
            "applied_rules": neighborhood_rules,
            "screening": deepcopy(s6_result.get("screening")),
            "claim_boundary": "The 150 m channel is static projected screening, not a service area or statutory setback.",
        },
    )


def _nearby_same_class(
    neighborhood: Mapping[str, Any], confirmed_class_id: str | None
) -> list[dict[str, Any]]:
    if confirmed_class_id is None:
        return []
    return [
        dict(row)
        for row in _rows(neighborhood, "current_facilities")
        if _text(row.get("canonical_class")) == confirmed_class_id
    ]


def _has_authoritative_capacity_rule(
    compatibility_matrix: Mapping[str, Any], confirmed_class_id: str | None
) -> bool:
    if compatibility_matrix.get("ready") is not True or confirmed_class_id is None:
        return False
    for field in ("capacity_rules", "duplication_rules", "service_area_rules"):
        for row in _rows(compatibility_matrix, field):
            if (
                _text(row.get("subject_class_id") or row.get("canonical_class")) == confirmed_class_id
                and _text(row.get("rule_id")) is not None
                and _text(row.get("rule_version")) is not None
                and _text(row.get("source_reference")) is not None
                and row.get("evidence_level", "authoritative") == "authoritative"
            ):
                return True
    return False


def _status(
    *,
    s6_result: Mapping[str, Any],
    confirmed_class_id: str | None,
    demand_status: str,
    parcel_conflict: bool,
    neighborhood_conflict: bool,
    nearby_same_class: bool,
    unresolved_objects: bool,
) -> str:
    validation_blockers = s6_result.get("validation_blockers")
    if s6_result.get("status") == "insufficient_evidence" or (
        isinstance(validation_blockers, list) and bool(validation_blockers)
    ):
        return "insufficient_evidence"
    if confirmed_class_id is None:
        return "unresolved_review_required"
    support = demand_status == "demand_supported"
    material_risk = parcel_conflict or neighborhood_conflict
    if support and material_risk:
        return "mixed_evidence_review_required"
    if parcel_conflict:
        return "potential_encroachment_review_required"
    if neighborhood_conflict:
        return "mixed_evidence_review_required"
    if nearby_same_class or unresolved_objects:
        return "nearby_supply_review_required"
    if support:
        return "provisionally_supported"
    return "insufficient_evidence"


def _merge_geojson(results: list[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    collection_names = (
        "planning_resource_hits",
        "current_facility_hits",
        "unresolved_planning_resources",
        "unresolved_current_facilities",
    )
    merged: dict[str, Any] = {
        "proposed_geometry": None,
        "screening_buffer": None,
        **{name: {"type": "FeatureCollection", "features": []} for name in collection_names},
    }
    seen: set[str] = set()
    total_unique = 0
    returned = 0
    for result in results:
        geojson = result.get("geojson")
        if not isinstance(geojson, Mapping):
            continue
        for geometry_name in ("proposed_geometry", "screening_buffer"):
            if merged[geometry_name] is None and isinstance(geojson.get(geometry_name), Mapping):
                merged[geometry_name] = deepcopy(geojson[geometry_name])
        for name in collection_names:
            collection = geojson.get(name)
            if not isinstance(collection, Mapping):
                continue
            features = collection.get("features")
            if not isinstance(features, list):
                continue
            for feature in features:
                if not isinstance(feature, Mapping):
                    continue
                key = json.dumps(feature, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
                if key in seen:
                    continue
                seen.add(key)
                total_unique += 1
                if returned >= _MAX_DISPLAY_FEATURE_COUNT:
                    continue
                merged[name]["features"].append(deepcopy(feature))
                returned += 1
    return merged, {
        "max_display_feature_count": _MAX_DISPLAY_FEATURE_COUNT,
        "truncated": returned < total_unique,
        "total_feature_count": total_unique,
        "returned_feature_count": returned,
    }


def _gfa_summary(use_assessments: list[Mapping[str, Any]], total_gfa: float) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for assessment in use_assessments:
        status = str(assessment["status"])
        totals[status] = math.fsum((totals.get(status, 0.0), float(assessment["gfa_m2"])))
    ordered = []
    allocated = 0.0
    rows = sorted(totals.items())
    for index, (status, gfa) in enumerate(rows):
        share = 1.0 - allocated if index == len(rows) - 1 else gfa / total_gfa
        allocated += share
        ordered.append({"status": status, "gfa_m2": gfa, "gfa_share": share})
    return ordered


def assess_s4_project(
    *,
    project: Mapping[str, Any],
    s1_snapshot: Mapping[str, Any],
    s6_resources: Mapping[str, Any],
    facility_dictionary: Mapping[str, Any],
    compatibility_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the evidence-bounded S4 project assessment."""
    project_payload = project if isinstance(project, Mapping) else {}
    normalized = project_payload.get("normalized_request")
    uses = project_payload.get("uses")
    if project_payload.get("valid") is not True or not isinstance(normalized, Mapping) or not isinstance(uses, list):
        return _json_safe_detached({
            "schema": SCHEMA,
            "project_id": project_payload.get("project_id"),
            "status": "insufficient_evidence",
            "use_assessments": [],
            "project_summary": {"formal_alignment_enabled": False, "total_gfa_m2": None, "gfa_by_status": []},
            "project_blockers": ["valid_s4_project_request_required"],
            "claim_boundary": {"max_claim": "preliminary_evidence_analysis_requiring_human_review", "approval_assessed": False},
            "geojson": {"proposed_geometry": None, "screening_buffer": None},
        })

    analysis_area_id = _text(normalized.get("analysis_area_id")) or ""
    planning_parcel_id = _text(normalized.get("planning_parcel_id")) or ""
    use_assessments = []
    s6_results = []
    blockers: list[str] = []
    for use in uses:
        if not isinstance(use, Mapping):
            continue
        request = {
            "input_mode": "planning_parcel",
            "analysis_area_id": analysis_area_id,
            "planning_parcel_id": planning_parcel_id,
            "facility_name": use.get("use_name"),
            "raw_facility_type": use.get("raw_use_type"),
            "use_description": use.get("use_description"),
            "confirmed_standard_class_id": use.get("confirmed_standard_class_id"),
            "human_confirmation": deepcopy(use.get("human_confirmation")),
        }
        s6_result = analyze_s6_facility_proposal(
            request=request,
            resources=s6_resources,
            dictionary=facility_dictionary,
            compatibility=compatibility_matrix,
        )
        s6_results.append(s6_result)
        confirmed_class_id = _confirmed_class(use, s6_result)
        demand = _demand_evidence(
            s1_snapshot=s1_snapshot,
            s6_resources=s6_resources,
            analysis_area_id=analysis_area_id,
            confirmed_class_id=confirmed_class_id,
        )
        parcel_direct, neighborhood = _split_spatial_evidence(s6_result, planning_parcel_id)
        same_class = _nearby_same_class(neighborhood, confirmed_class_id)
        capacity_rule_ready = _has_authoritative_capacity_rule(compatibility_matrix, confirmed_class_id)
        duplicate_status = (
            "duplicate_supply_risk"
            if same_class and capacity_rule_ready
            else "nearby_same_class_supply_detected"
            if same_class
            else "no_nearby_same_class_supply_detected"
        )
        neighborhood_conflict = any(
            row.get("relationship") == "conflict"
            for row in _rows(neighborhood, "applied_rules")
        )
        unresolved_objects = any(
            neighborhood.get(field)
            for field in (
                "unresolved_planning_resources",
                "unresolved_current_facilities",
                "association_records",
            )
        )
        use_status = _status(
            s6_result=s6_result,
            confirmed_class_id=confirmed_class_id,
            demand_status=demand["status"],
            parcel_conflict=parcel_direct["authoritative_conflict"],
            neighborhood_conflict=neighborhood_conflict,
            nearby_same_class=bool(same_class),
            unresolved_objects=unresolved_objects,
        )
        use_blockers = list(dict.fromkeys([
            *[str(value) for value in s6_result.get("validation_blockers") or []],
            *[str(value) for value in s6_result.get("production_blockers") or []],
            *([] if demand["status"] == "demand_supported" else ["authoritative_matching_demand_gap_not_available"]),
            *([] if capacity_rule_ready or not same_class else ["authoritative_capacity_or_duplication_rule_not_available"]),
        ]))
        blockers.extend(use_blockers)
        use_assessments.append({
            "use_id": use.get("use_id"),
            "use_name": use.get("use_name"),
            "gfa_m2": use.get("gfa_m2"),
            "gfa_share": use.get("gfa_share"),
            "confirmed_standard_class_id": confirmed_class_id,
            "status": use_status,
            "semantic_evidence": deepcopy(s6_result.get("semantic_resolution")),
            "demand_evidence": demand,
            "parcel_direct_evidence": parcel_direct,
            "neighborhood_evidence": neighborhood,
            "duplicate_supply_evidence": {
                "status": duplicate_status,
                "nearby_same_class_facilities": same_class,
                "authoritative_capacity_or_duplication_rule_applied": capacity_rule_ready,
            },
            "s6_status": s6_result.get("status"),
            "blockers": use_blockers,
        })

    total_gfa = float(project_payload.get("total_gfa_m2"))
    gfa_by_status = _gfa_summary(use_assessments, total_gfa)
    merged_geojson, geometry_payload = _merge_geojson(s6_results)
    all_authority_ready = (
        facility_dictionary.get("ready") is True
        and compatibility_matrix.get("ready") is True
        and bool(use_assessments)
        and all(row["demand_evidence"]["status"] == "demand_supported" for row in use_assessments)
        and all(row["s6_status"] == "confirmed_compatible" for row in use_assessments)
        and all(not row["blockers"] for row in use_assessments)
    )
    result = {
        "schema": SCHEMA,
        "project_id": project_payload.get("project_id"),
        "actor_id": project_payload.get("actor_id"),
        "project_content_digest": project_payload.get("content_digest"),
        "status": (
            "preliminary_alignment_evidence"
            if any(row["status"] == "provisionally_supported" for row in use_assessments)
            else "human_review_required"
        ),
        "executed_geography": {
            "analysis_area_id": analysis_area_id,
            "planning_parcel_id": planning_parcel_id,
        },
        "use_assessments": use_assessments,
        "project_summary": {
            "total_use_count": len(use_assessments),
            "total_gfa_m2": total_gfa,
            "gfa_by_status": gfa_by_status,
            "formal_alignment_enabled": all_authority_ready,
        },
        "project_blockers": list(dict.fromkeys(blockers)),
        "claim_boundary": {
            "max_claim": "preliminary_evidence_analysis_requiring_human_review",
            "approval_assessed": False,
            "future_impact_assessed": False,
            "gfa_treated_as_capacity": False,
            "weighted_scoring_used": False,
            "formal_alignment_requires_all_authority_ready_and_applicable": True,
        },
        "geometry_payload": geometry_payload,
        "geojson": merged_geojson,
    }
    return _json_safe_detached(result)
