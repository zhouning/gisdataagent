from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Mapping

from shapely.geometry import shape

from data_agent.uwm.traditional_livability_s6 import (
    analyze_s6_facility_proposal,
)
from data_agent.uwm.traditional_livability_facility_dictionary import (
    COMPATIBILITY_SCHEMA,
    DICTIONARY_SCHEMA,
    compute_canonical_content_digest,
    validate_compatibility_matrix,
    validate_facility_dictionary,
)


SCHEMA = "uwm.traditional_livability.s4_project_assessment.v1"
_MAX_DISPLAY_FEATURE_COUNT = 1000
_S1_SCHEMA = "uwm.traditional_livability.s1_assessment.v1"
_S6_RESOURCE_SCHEMA = "uwm.traditional_livability.s6_fulu_resources.v1"
_S4_PROJECT_SCHEMA = "uwm.traditional_livability.s4_project_request.v1"
_DUPLICATION_RULE_PURPOSES = {"duplicate_supply", "capacity"}


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
    return None


def _validated_authority_payload(
    payload: Mapping[str, Any], *, kind: str
) -> tuple[dict[str, Any], list[str]]:
    expected_schema = DICTIONARY_SCHEMA if kind == "dictionary" else COMPATIBILITY_SCHEMA
    validator = validate_facility_dictionary if kind == "dictionary" else validate_compatibility_matrix
    blocker = (
        "facility_dictionary_contract_invalid"
        if kind == "dictionary"
        else "compatibility_matrix_contract_invalid"
    )
    if not isinstance(payload, Mapping) or payload.get("schema") != expected_schema:
        return {}, [blocker]
    source_payloads = [deepcopy(dict(payload))]
    if "provided_content_digest" in payload:
        metadata = payload.get("source_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if kind == "dictionary":
            source_payload = {
                "schema": payload.get("schema"),
                "dictionary_version": metadata.get("dictionary_version"),
                "issuing_organization": metadata.get("issuing_organization"),
                "source_reference": metadata.get("source_reference"),
                "effective_date": metadata.get("effective_date"),
                "version_date": metadata.get("version_date"),
                "imported_at": metadata.get("imported_at"),
                "authoritative_complete_43_class_dictionary": payload.get(
                    "authoritative_complete_43_class_dictionary"
                ),
                "classes": deepcopy(payload.get("classes")),
                "aliases": deepcopy(payload.get("aliases")),
                "keywords": deepcopy(payload.get("keywords")),
                "content_digest": payload.get("provided_content_digest"),
            }
            source_without_effective_date = deepcopy(source_payload)
            source_without_effective_date.pop("effective_date")
            source_payloads = [source_payload, source_without_effective_date]
        else:
            source_payloads = [{
                "schema": payload.get("schema"),
                "matrix_version": metadata.get("matrix_version"),
                "issuing_organization": metadata.get("issuing_organization"),
                "source_reference": metadata.get("source_reference"),
                "effective_date": metadata.get("effective_date"),
                "version_date": metadata.get("version_date"),
                "imported_at": metadata.get("imported_at"),
                "rules": deepcopy(payload.get("rules")),
                "content_digest": payload.get("provided_content_digest"),
            }]
    for source_payload in source_payloads:
        validated = validator(source_payload)
        if not validated.get("validation_errors"):
            return validated, []
    return {}, [blocker]


def _validate_resources(payload: Mapping[str, Any]) -> list[str]:
    if not isinstance(payload, Mapping) or payload.get("schema") != _S6_RESOURCE_SCHEMA:
        return ["s6_resources_snapshot_schema_invalid"]
    blockers = []
    if payload.get("ready") is not True or any(
        not isinstance(payload.get(field), list)
        for field in ("planning_areas", "planning_resources", "current_facilities")
    ):
        blockers.append("s6_resources_snapshot_contract_invalid")
    provided = payload.get("content_digest")
    if not isinstance(provided, str) or not provided:
        blockers.append("s6_resources_snapshot_digest_missing")
    else:
        try:
            if compute_canonical_content_digest(payload) != provided:
                blockers.append("s6_resources_snapshot_digest_mismatch")
        except Exception:
            blockers.append("s6_resources_snapshot_digest_mismatch")
    return blockers


def _validate_s1(payload: Mapping[str, Any]) -> list[str]:
    if not isinstance(payload, Mapping) or payload.get("schema") != _S1_SCHEMA:
        return ["s1_snapshot_schema_invalid"]
    metrics = payload.get("supply_metrics")
    if not isinstance(metrics, list) or any(not isinstance(row, Mapping) for row in metrics):
        return ["s1_supply_metrics_malformed"]
    allowed_statuses = {"not_assessed", "below_standard", "meets_standard"}
    if any(
        _text(row.get("canonical_class")) is None
        or row.get("compliance_status") not in allowed_statuses
        or (
            row.get("gap_to_standard") is not None
            and (
                isinstance(row.get("gap_to_standard"), bool)
                or not isinstance(row.get("gap_to_standard"), (int, float))
                or not math.isfinite(float(row["gap_to_standard"]))
            )
        )
        or not isinstance(row.get("standard"), (Mapping, type(None)))
        for row in metrics
    ):
        return ["s1_supply_metric_row_malformed"]
    return []


def _s1_digest_valid(payload: Mapping[str, Any]) -> bool:
    provided = payload.get("content_digest")
    if not isinstance(provided, str) or not provided:
        return False
    try:
        return compute_canonical_content_digest(payload) == provided
    except Exception:
        return False


def _authoritative_standard(row: Mapping[str, Any], *, s1_digest_valid: bool) -> bool:
    standard = row.get("standard")
    required_standard_fields = (
        "standard_id",
        "standard_version",
        "source_reference",
        "effective_date",
        "canonical_class",
        "admin_code",
        "metric",
        "threshold",
        "unit",
        "evidence_level",
    )
    return (
        s1_digest_valid
        and
        isinstance(standard, Mapping)
        and all(standard.get(field) not in (None, "") for field in required_standard_fields)
        and standard.get("evidence_level") == "authoritative"
        and _text(row.get("canonical_class")) == _text(standard.get("canonical_class"))
        and _text(row.get("metric")) == _text(standard.get("metric"))
        and _text(row.get("admin_code") or row.get("planning_area_id"))
        == _text(standard.get("admin_code"))
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
            and _authoritative_standard(
                row, s1_digest_valid=_s1_digest_valid(s1_snapshot)
            )
        ):
            return {
                "status": "demand_supported",
                "matched_metric": deepcopy(row),
                "background_metrics": [],
            }
    if matching and (
        all(row.get("compliance_status") == "not_assessed" for row in matching)
        or not _s1_digest_valid(s1_snapshot)
    ):
        status = "demand_not_assessed"
    else:
        status = "demand_evidence_not_matched"
    return {
        "status": status,
        "matched_metric": None,
        "background_metrics": deepcopy(matching or class_rows),
    }


def _split_spatial_evidence(
    s6_result: Mapping[str, Any],
    planning_parcel_id: str,
    s6_resources: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    planning = [dict(row) for row in _rows(s6_result, "planning_resource_hits")]
    facilities = [dict(row) for row in _rows(s6_result, "current_facility_hits")]
    unresolved = s6_result.get("unresolved_objects")
    unresolved = unresolved if isinstance(unresolved, Mapping) else {}
    unresolved_planning = [dict(row) for row in _rows(unresolved, "planning_resources")]
    unresolved_facilities = [dict(row) for row in _rows(unresolved, "current_facilities")]
    planning_sources = {
        _text(row.get("resource_id")): row
        for row in _rows(s6_resources, "planning_resources")
        if _text(row.get("resource_id")) is not None
    }
    facility_sources = {
        _text(row.get("facility_id")): row
        for row in _rows(s6_resources, "current_facilities")
        if _text(row.get("facility_id")) is not None
    }

    def safe_geometry(source: Any):
        if not isinstance(source, Mapping):
            return None
        value = source.get("metric_geometry") or source.get("display_geometry_wgs84")
        if not isinstance(value, Mapping):
            return None
        try:
            geometry = shape(value)
        except Exception:
            return None
        if geometry.is_empty or not geometry.is_valid:
            return None
        return geometry

    selected_geometry = safe_geometry(planning_sources.get(planning_parcel_id))

    def authoritative_relationship(row: Mapping[str, Any]) -> bool:
        relationship = _text(row.get("spatial_relationship"))
        evidence = row.get("relationship_evidence")
        return (
            relationship in {"contained", "contains", "intersects", "overlaps"}
            and isinstance(evidence, Mapping)
            and evidence.get("evidence_level") == "authoritative"
            and _text(evidence.get("source_reference")) is not None
            and _text(evidence.get("rule_version")) is not None
        )

    def geometry_is_direct(row: Mapping[str, Any]) -> bool:
        if selected_geometry is None:
            return False
        channel = _text(row.get("channel"))
        source = (
            planning_sources.get(_text(row.get("resource_id")))
            if channel == "planning"
            else facility_sources.get(_text(row.get("facility_id")))
            if channel == "facility"
            else None
        )
        geometry = safe_geometry(source)
        if geometry is None:
            return False
        if geometry.geom_type in {"Point", "MultiPoint"}:
            return selected_geometry.covers(geometry) and not selected_geometry.touches(geometry)
        try:
            intersection = selected_geometry.intersection(geometry)
        except Exception:
            return False
        return not intersection.is_empty and intersection.area > 0

    def is_direct(row: Mapping[str, Any]) -> bool:
        return (
            _text(row.get("resource_id")) == planning_parcel_id
            or authoritative_relationship(row)
            or geometry_is_direct(row)
        )

    direct_planning = [row for row in planning if is_direct(row)]
    direct_facilities = [row for row in facilities if is_direct(row)]
    direct_unresolved = [row for row in unresolved_planning if is_direct(row)]
    direct_unresolved_facilities = [row for row in unresolved_facilities if is_direct(row)]
    neighborhood_planning = [row for row in planning if not is_direct(row)]
    neighborhood_facilities = [row for row in facilities if not is_direct(row)]
    neighborhood_unresolved = [row for row in unresolved_planning if not is_direct(row)]
    neighborhood_unresolved_facilities = [row for row in unresolved_facilities if not is_direct(row)]
    direct_ids = {
        str(row.get("evidence_id"))
        for row in direct_planning + direct_facilities + direct_unresolved + direct_unresolved_facilities
    }
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
            "current_facilities": direct_facilities,
            "unresolved_planning_resources": direct_unresolved,
            "unresolved_current_facilities": direct_unresolved_facilities,
            "applied_rules": direct_rules,
            "authoritative_conflict": direct_conflict,
            "claim_boundary": (
                "Parcel conflict is formal only when an applicable authoritative rule is retained."
            ),
        },
        {
            "planning_resources": neighborhood_planning,
            "current_facilities": neighborhood_facilities,
            "unresolved_planning_resources": neighborhood_unresolved,
            "unresolved_current_facilities": neighborhood_unresolved_facilities,
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


def _applied_duplicate_rules(
    *,
    s6_result: Mapping[str, Any],
    compatibility_matrix: Mapping[str, Any],
    nearby_same_class: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    nearby_ids = {str(row.get("evidence_id")) for row in nearby_same_class}
    matrix_rules = {
        _text(row.get("rule_id")): row
        for row in _rows(compatibility_matrix, "rules")
        if _text(row.get("rule_id")) is not None
    }
    applied = []
    for applied_rule in _rows(s6_result, "applied_rules"):
        applied_ids = {str(value) for value in applied_rule.get("applied_hit_ids") or []}
        if not (nearby_ids & applied_ids):
            continue
        source_rule = matrix_rules.get(_text(applied_rule.get("rule_id")))
        if not isinstance(source_rule, Mapping):
            continue
        if (
            source_rule.get("evidence_level") == "authoritative"
            and _text(source_rule.get("rule_purpose")) in _DUPLICATION_RULE_PURPOSES
        ):
            applied.append(deepcopy(dict(source_rule)))
    return applied


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
    if (
        project_payload.get("schema") != _S4_PROJECT_SCHEMA
        or project_payload.get("valid") is not True
        or not isinstance(normalized, Mapping)
        or not isinstance(uses, list)
    ):
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

    input_blockers = [
        *_validate_resources(s6_resources),
        *_validate_s1(s1_snapshot),
    ]
    validated_dictionary, dictionary_blockers = _validated_authority_payload(
        facility_dictionary, kind="dictionary"
    )
    validated_compatibility, compatibility_blockers = _validated_authority_payload(
        compatibility_matrix, kind="compatibility"
    )
    input_blockers.extend(dictionary_blockers)
    input_blockers.extend(compatibility_blockers)
    normalized_uses = [row for row in uses if isinstance(row, Mapping)]
    try:
        use_gfas = [float(row.get("gfa_m2")) for row in normalized_uses]
        recomputed_total_gfa = math.fsum(use_gfas)
        declared_total_gfa = float(project_payload.get("total_gfa_m2"))
        if (
            len(normalized_uses) != len(uses)
            or any(not math.isfinite(value) or value <= 0 for value in use_gfas)
            or not math.isfinite(recomputed_total_gfa)
            or recomputed_total_gfa <= 0
        ):
            input_blockers.append("project_use_gfa_invalid")
        elif not math.isfinite(declared_total_gfa) or not math.isclose(
            declared_total_gfa, recomputed_total_gfa, rel_tol=0.0, abs_tol=1e-9
        ):
            input_blockers.append("project_total_gfa_mismatch")
    except (TypeError, ValueError, OverflowError):
        recomputed_total_gfa = 0.0
        input_blockers.append("project_use_gfa_invalid")
    if input_blockers:
        return _json_safe_detached({
            "schema": SCHEMA,
            "project_id": project_payload.get("project_id"),
            "status": "insufficient_evidence",
            "use_assessments": [],
            "project_summary": {
                "formal_alignment_enabled": False,
                "total_gfa_m2": recomputed_total_gfa if recomputed_total_gfa > 0 else None,
                "gfa_by_status": [],
            },
            "project_blockers": list(dict.fromkeys(input_blockers)),
            "claim_boundary": {
                "max_claim": "insufficient_evidence",
                "approval_assessed": False,
            },
            "geojson": {"proposed_geometry": None, "screening_buffer": None},
        })

    analysis_area_id = _text(normalized.get("analysis_area_id")) or ""
    planning_parcel_id = _text(normalized.get("planning_parcel_id")) or ""
    use_assessments = []
    s6_results = []
    blockers: list[str] = []
    allocated_share = 0.0
    for use_index, use in enumerate(normalized_uses):
        if not isinstance(use, Mapping):
            continue
        request = {
            "input_mode": "planning_parcel",
            "analysis_area_id": analysis_area_id,
            "parcel_id": planning_parcel_id,
            "facility_name": use.get("use_name"),
            "raw_facility_type": use.get("raw_use_type"),
            "use_description": use.get("use_description"),
            "confirmed_standard_class_id": use.get("confirmed_standard_class_id"),
            "human_confirmation": deepcopy(use.get("human_confirmation")),
        }
        s6_result = analyze_s6_facility_proposal(
            request=request,
            resources=s6_resources,
            dictionary=validated_dictionary,
            compatibility=validated_compatibility,
        )
        s6_results.append(s6_result)
        confirmed_class_id = _confirmed_class(use, s6_result)
        demand = _demand_evidence(
            s1_snapshot=s1_snapshot,
            s6_resources=s6_resources,
            analysis_area_id=analysis_area_id,
            confirmed_class_id=confirmed_class_id,
        )
        parcel_direct, neighborhood = _split_spatial_evidence(
            s6_result, planning_parcel_id, s6_resources
        )
        same_class = _nearby_same_class(neighborhood, confirmed_class_id)
        applied_duplicate_rules = _applied_duplicate_rules(
            s6_result=s6_result,
            compatibility_matrix=validated_compatibility,
            nearby_same_class=same_class,
        )
        duplicate_status = (
            "duplicate_supply_risk"
            if same_class and applied_duplicate_rules
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
            *([] if applied_duplicate_rules or not same_class else ["authoritative_capacity_or_duplication_rule_not_available"]),
        ]))
        blockers.extend(use_blockers)
        use_assessments.append({
            "use_id": use.get("use_id"),
            "use_name": use.get("use_name"),
            "gfa_m2": use.get("gfa_m2"),
            "gfa_share": (
                1.0 - allocated_share
                if use_index == len(normalized_uses) - 1
                else float(use.get("gfa_m2")) / recomputed_total_gfa
            ),
            "confirmed_standard_class_id": confirmed_class_id,
            "status": use_status,
            "semantic_evidence": deepcopy(s6_result.get("semantic_resolution")),
            "demand_evidence": demand,
            "parcel_direct_evidence": parcel_direct,
            "neighborhood_evidence": neighborhood,
            "duplicate_supply_evidence": {
                "status": duplicate_status,
                "nearby_same_class_facilities": same_class,
                "authoritative_capacity_or_duplication_rule_applied": bool(applied_duplicate_rules),
                "applied_rules": applied_duplicate_rules,
            },
            "s6_status": s6_result.get("status"),
            "blockers": use_blockers,
        })
        allocated_share += use_assessments[-1]["gfa_share"]

    total_gfa = recomputed_total_gfa
    gfa_by_status = _gfa_summary(use_assessments, total_gfa)
    merged_geojson, geometry_payload = _merge_geojson(s6_results)
    all_authority_ready = (
        validated_dictionary.get("ready") is True
        and validated_compatibility.get("ready") is True
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
