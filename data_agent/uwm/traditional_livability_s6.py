from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Mapping

from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
    validate_human_confirmation,
)


SCHEMA = "uwm.traditional_livability.s6_analysis.v1"
SCREENING_DISTANCE_M = 150.0

_INPUT_MODES = {"point", "planning_parcel"}
_SUPPORTED_APPLICABILITY_CONDITIONS = {
    "planning_area_ids",
    "input_modes",
    "planning_statuses",
    "resource_domains",
    "facility_geometry_types",
}


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


def _safe_geometry(value: Any):
    if not isinstance(value, Mapping):
        return None
    try:
        geometry = shape(value)
    except (TypeError, ValueError):
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    return geometry


def _area_index(resources: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for row in _rows(resources, "planning_areas"):
        area_id = _text(row.get("planning_area_id"))
        if area_id is not None:
            result[area_id] = row
    return result

def _parcel_candidates(
    resources: Mapping[str, Any], parcel_id: str
) -> list[Mapping[str, Any]]:
    return [
        row
        for row in _rows(resources, "planning_resources")
        if _text(row.get("resource_id")) == parcel_id
    ]


def validate_s6_request(
    payload: Mapping[str, Any], resources: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a normalized request or exact validation blockers."""
    request = payload if isinstance(payload, Mapping) else {}
    resource_payload = resources if isinstance(resources, Mapping) else {}
    blockers: list[str] = []

    if resource_payload.get("ready") is not True:
        blockers.append("s6_resource_snapshot_not_ready")

    input_mode = _text(request.get("input_mode"))
    if input_mode not in _INPUT_MODES:
        blockers.append("unsupported_input_mode")

    analysis_area_id = _text(request.get("analysis_area_id"))
    areas = _area_index(resource_payload)
    selected_area = areas.get(analysis_area_id) if analysis_area_id else None
    if analysis_area_id is None:
        blockers.append("analysis_area_id_missing")
    elif selected_area is None:
        blockers.append(f"unknown_analysis_area:{analysis_area_id}")

    distance_crs = None
    if selected_area is not None:
        distance_crs = _text(selected_area.get("distance_crs"))
        if distance_crs is None:
            blockers.append(
                f"planning_area_distance_crs_missing:{analysis_area_id}"
            )
        else:
            try:
                if not CRS.from_user_input(distance_crs).is_projected:
                    blockers.append(
                        f"planning_area_distance_crs_not_projected:{analysis_area_id}"
                    )
            except Exception:
                blockers.append(
                    f"planning_area_distance_crs_invalid:{analysis_area_id}"
                )
        if _safe_geometry(selected_area.get("metric_geometry")) is None:
            blockers.append(f"planning_area_geometry_missing:{analysis_area_id}")

    normalized: dict[str, Any] = {
        "input_mode": input_mode,
        "analysis_area_id": analysis_area_id,
        "facility_name": _text(request.get("facility_name")),
        "raw_facility_type": _text(request.get("raw_facility_type")),
        "use_description": _text(request.get("use_description")),
        "confirmed_standard_class_id": _text(
            request.get("confirmed_standard_class_id")
        ),
        "human_confirmation": (
            dict(request["human_confirmation"])
            if isinstance(request.get("human_confirmation"), Mapping)
            else None
        ),
    }
    for field in ("facility_name", "raw_facility_type", "use_description"):
        if normalized[field] is None:
            blockers.append(f"{field}_missing")

    if input_mode == "point":
        longitude = request.get("longitude")
        latitude = request.get("latitude")
        valid_coordinates = (
            isinstance(longitude, (int, float))
            and not isinstance(longitude, bool)
            and isinstance(latitude, (int, float))
            and not isinstance(latitude, bool)
            and math.isfinite(float(longitude))
            and math.isfinite(float(latitude))
            and -180 <= float(longitude) <= 180
            and -90 <= float(latitude) <= 90
        )
        if not valid_coordinates:
            blockers.append("invalid_point_coordinates")
        else:
            normalized["longitude"] = float(longitude)
            normalized["latitude"] = float(latitude)
            if selected_area is not None:
                display_area = _safe_geometry(
                    selected_area.get("display_geometry_wgs84")
                )
                if display_area is None:
                    blockers.append(
                        f"planning_area_display_geometry_missing:{analysis_area_id}"
                    )
                else:
                    from shapely.geometry import Point

                    if not display_area.covers(
                        Point(float(longitude), float(latitude))
                    ):
                        blockers.append("point_outside_selected_area")

    if input_mode == "planning_parcel":
        parcel_id = _text(request.get("parcel_id"))
        normalized["parcel_id"] = parcel_id
        if parcel_id is None:
            blockers.append("planning_parcel_id_missing")
        else:
            candidates = _parcel_candidates(resource_payload, parcel_id)
            if not candidates:
                blockers.append(f"unknown_planning_parcel:{parcel_id}")
            else:
                same_area = [
                    row
                    for row in candidates
                    if _text(row.get("planning_area_id")) == analysis_area_id
                ]
                if not same_area:
                    blockers.append(
                        f"planning_parcel_outside_selected_area:{parcel_id}"
                    )
                else:
                    parcel = same_area[0]
                    if _safe_geometry(parcel.get("metric_geometry")) is None:
                        blockers.append(
                            f"planning_parcel_geometry_missing:{parcel_id}"
                        )
                    parcel_crs = _text(parcel.get("distance_crs"))
                    if distance_crs is not None and parcel_crs != distance_crs:
                        blockers.append(
                            f"planning_parcel_distance_crs_mismatch:{parcel_id}"
                        )

    return {
        "valid": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "normalized_request": normalized,
        "selected_area": dict(selected_area) if selected_area is not None else None,
    }


def _projected_input_geometry(
    normalized: Mapping[str, Any],
    resources: Mapping[str, Any],
    distance_crs: str,
):
    if normalized["input_mode"] == "point":
        from shapely.geometry import Point

        display_geometry = Point(
            normalized["longitude"], normalized["latitude"]
        )
        transformer = Transformer.from_crs(
            "EPSG:4326", distance_crs, always_xy=True
        )
        return transform(transformer.transform, display_geometry), display_geometry

    parcel = next(
        row
        for row in _rows(resources, "planning_resources")
        if row.get("resource_id") == normalized["parcel_id"]
        and row.get("planning_area_id") == normalized["analysis_area_id"]
    )
    metric_geometry = shape(parcel["metric_geometry"])
    display_geometry = _safe_geometry(parcel.get("display_geometry_wgs84"))
    if display_geometry is None:
        transformer = Transformer.from_crs(
            distance_crs, "EPSG:4326", always_xy=True
        )
        display_geometry = transform(transformer.transform, metric_geometry)
    return metric_geometry, display_geometry


def _display_geometry(metric_geometry, distance_crs: str) -> dict[str, Any]:
    transformer = Transformer.from_crs(
        distance_crs, "EPSG:4326", always_xy=True
    )
    return mapping(transform(transformer.transform, metric_geometry))


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _planning_hit(
    row: Mapping[str, Any], input_geometry, screening_geometry
) -> dict[str, Any]:
    geometry = shape(row["metric_geometry"])
    intersection = geometry.intersection(screening_geometry)
    intersection_area = None
    if not intersection.is_empty and intersection.area > 0:
        intersection_area = _rounded(intersection.area)
    return {
        "resource_id": row.get("resource_id"),
        "source_record_id": row.get("source_record_id"),
        "planning_area_id": row.get("planning_area_id"),
        "source_layer": row.get("source_layer"),
        "raw_land_use_code": row.get("raw_land_use_code"),
        "raw_land_use_name": row.get("raw_land_use_name"),
        "resource_domain": row.get("resource_domain"),
        "interpretation_rule": row.get("interpretation_rule"),
        "interpretation_evidence": row.get("interpretation_evidence"),
        "planning_status": row.get("planning_status"),
        "planning_status_evidence": row.get("planning_status_evidence"),
        "source_manifest_ref": row.get("source_manifest_ref"),
        "nearest_distance_m": _rounded(input_geometry.distance(geometry)),
        "intersection_area_m2": intersection_area,
        "compatibility_object_class_id": _text(row.get("resource_domain")),
        "display_geometry_wgs84": row.get("display_geometry_wgs84"),
    }


def _facility_hit(row: Mapping[str, Any], input_geometry) -> dict[str, Any]:
    geometry = shape(row["metric_geometry"])
    return {
        "facility_id": row.get("facility_id"),
        "source_dataset_id": row.get("source_dataset_id"),
        "source_record_id": row.get("source_record_id"),
        "name": row.get("name"),
        "raw_primary_class": row.get("raw_primary_class"),
        "raw_secondary_class": row.get("raw_secondary_class"),
        "raw_tertiary_class": row.get("raw_tertiary_class"),
        "canonical_class": row.get("canonical_class"),
        "mapping_status": row.get("mapping_status"),
        "mapping_version": row.get("mapping_version"),
        "geometry_type": row.get("geometry_type"),
        "nearest_distance_m": _rounded(input_geometry.distance(geometry)),
        "compatibility_object_class_id": _text(row.get("canonical_class")),
        "display_geometry_wgs84": row.get("display_geometry_wgs84"),
    }


def _screen_resources(
    *,
    resources: Mapping[str, Any],
    area_id: str,
    distance_crs: str,
    input_geometry,
    screening_geometry,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    planning_hits = []
    unresolved_planning = []
    for row in _rows(resources, "planning_resources"):
        if _text(row.get("planning_area_id")) != area_id:
            continue
        if _text(row.get("distance_crs")) != distance_crs:
            continue
        geometry = _safe_geometry(row.get("metric_geometry"))
        if geometry is None or not geometry.intersects(screening_geometry):
            continue
        hit = _planning_hit(row, input_geometry, screening_geometry)
        if hit["compatibility_object_class_id"] in (None, "unresolved"):
            unresolved_planning.append(hit)
        else:
            planning_hits.append(hit)

    facility_hits = []
    unresolved_facilities = []
    unresolved_associations = []
    for row in _rows(resources, "current_facilities"):
        association_status = _text(row.get("association_status"))
        matching_ids = row.get("matching_planning_area_ids")
        if (
            association_status == "multi_area_overlap_unresolved"
            and isinstance(matching_ids, list)
            and area_id in matching_ids
        ):
            unresolved_associations.append(
                {
                    "facility_id": row.get("facility_id"),
                    "source_record_id": row.get("source_record_id"),
                    "association_status": association_status,
                    "matching_planning_area_ids": list(matching_ids),
                    "display_geometry_wgs84": row.get(
                        "display_geometry_wgs84"
                    ),
                }
            )
            continue
        if _text(row.get("planning_area_id")) != area_id:
            continue
        if _text(row.get("distance_crs")) != distance_crs:
            continue
        geometry = _safe_geometry(row.get("metric_geometry"))
        if geometry is None or not geometry.intersects(screening_geometry):
            continue
        hit = _facility_hit(row, input_geometry)
        if row.get("mapping_status") == "unmapped" or hit[
            "compatibility_object_class_id"
        ] is None:
            unresolved_facilities.append(hit)
        else:
            facility_hits.append(hit)

    planning_hits.sort(key=lambda row: (row["nearest_distance_m"], row["resource_id"] or ""))
    facility_hits.sort(key=lambda row: (row["nearest_distance_m"], row["facility_id"] or ""))
    unresolved_planning.sort(
        key=lambda row: (row["nearest_distance_m"], row["resource_id"] or "")
    )
    unresolved_facilities.sort(
        key=lambda row: (row["nearest_distance_m"], row["facility_id"] or "")
    )
    unresolved_associations.sort(key=lambda row: row["facility_id"] or "")
    return planning_hits, facility_hits, {
        "planning_resources": unresolved_planning,
        "current_facilities": unresolved_facilities,
        "association_records": unresolved_associations,
    }


def _validate_request_confirmation(
    request: Mapping[str, Any],
    dictionary: Mapping[str, Any],
) -> dict[str, Any] | None:
    class_id = _text(request.get("confirmed_standard_class_id"))
    if class_id is None:
        return None
    confirmation = request.get("human_confirmation")
    if not isinstance(confirmation, Mapping):
        return {
            "valid": False,
            "selected_standard_class_id": class_id,
            "validation_errors": [
                "confirmed_class_requires_valid_human_confirmation"
            ],
        }
    original_input = {
        "facility_name": request.get("facility_name"),
        "raw_facility_type": request.get("raw_facility_type"),
        "use_description": request.get("use_description"),
    }
    selected_candidate = confirmation.get("selected_candidate")
    confirmation_payload = {
        key: value
        for key, value in confirmation.items()
        if key not in {"valid", "schema", "validation_errors", "selected_candidate"}
    }
    return validate_human_confirmation(
        confirmation_payload,
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=(
            selected_candidate if isinstance(selected_candidate, Mapping) else None
        ),
    )


def _confirmed_class_id(
    *,
    semantic_resolution: Mapping[str, Any],
    confirmation_validation: Mapping[str, Any] | None,
) -> str | None:
    if (
        confirmation_validation is not None
        and confirmation_validation.get("valid") is True
    ):
        return _text(confirmation_validation.get("selected_standard_class_id"))
    if semantic_resolution.get("resolution_status") == "authoritative_confirmed":
        return _text(semantic_resolution.get("confirmed_standard_class_id"))
    return None


def _condition_values(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    normalized = [_text(item) for item in value]
    if any(item is None for item in normalized):
        return None
    return [item for item in normalized if item is not None]


def _condition_context(
    normalized_request: Mapping[str, Any], hit: Mapping[str, Any]
) -> dict[str, str | None]:
    return {
        "planning_area_ids": _text(normalized_request.get("analysis_area_id")),
        "input_modes": _text(normalized_request.get("input_mode")),
        "planning_statuses": _text(hit.get("planning_status")),
        "resource_domains": _text(hit.get("resource_domain")),
        "facility_geometry_types": _text(hit.get("geometry_type")),
    }


def _evaluate_applicability_conditions(
    conditions: Any,
    *,
    normalized_request: Mapping[str, Any],
    hit: Mapping[str, Any],
) -> list[str]:
    if not isinstance(conditions, Mapping):
        return ["applicability_conditions_malformed"]
    reasons = []
    context = _condition_context(normalized_request, hit)
    condition_names = list(conditions)
    if any(not isinstance(condition_name, str) for condition_name in condition_names):
        return ["applicability_condition_key_malformed"]
    for condition_name in sorted(condition_names):
        if condition_name not in _SUPPORTED_APPLICABILITY_CONDITIONS:
            reasons.append(f"unsupported_condition:{condition_name}")
            continue
        expected_values = _condition_values(conditions[condition_name])
        if expected_values is None:
            reasons.append(f"condition_malformed:{condition_name}")
            continue
        actual_value = context[condition_name]
        if actual_value is None or actual_value not in expected_values:
            reasons.append(f"condition_not_matched:{condition_name}")
    return reasons


def _applicable_rules(
    *,
    confirmed_class_id: str | None,
    normalized_request: Mapping[str, Any],
    hits: list[Mapping[str, Any]],
    compatibility: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if confirmed_class_id is None or compatibility.get("ready") is not True:
        return [], [], [
            _text(hit.get("resource_id"))
            or _text(hit.get("facility_id"))
            or "unknown_hit"
            for hit in hits
        ]
    evaluated = []
    applicable_by_rule_id: dict[str, dict[str, Any]] = {}
    decisive_hit_ids: set[str] = set()
    for row in _rows(compatibility, "rules"):
        rule_id = _text(row.get("rule_id"))
        relationship = _text(row.get("relationship"))
        if (
            rule_id is None
            or _text(row.get("rule_version")) is None
            or _text(row.get("source_reference")) is None
            or relationship not in {"conflict", "compatible"}
            or _text(row.get("subject_class_id")) != confirmed_class_id
        ):
            continue
        object_class_id = _text(row.get("object_class_id"))
        for hit in hits:
            if _text(hit.get("compatibility_object_class_id")) != object_class_id:
                continue
            hit_id = (
                _text(hit.get("resource_id"))
                or _text(hit.get("facility_id"))
                or "unknown_hit"
            )
            reasons = _evaluate_applicability_conditions(
                row.get("applicability_conditions"),
                normalized_request=normalized_request,
                hit=hit,
            )
            evaluation = {
                "rule_id": rule_id,
                "rule_version": _text(row.get("rule_version")),
                "subject_class_id": confirmed_class_id,
                "object_class_id": object_class_id,
                "relationship": relationship,
                "source_reference": _text(row.get("source_reference")),
                "applicability_conditions": row.get("applicability_conditions"),
                "evaluated_hit_id": hit_id,
                "applicable": not reasons,
                "non_applicable_reasons": reasons,
            }
            evaluated.append(evaluation)
            if reasons:
                continue
            decisive_hit_ids.add(hit_id)
            applicable_by_rule_id.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "rule_version": evaluation["rule_version"],
                    "subject_class_id": confirmed_class_id,
                    "object_class_id": object_class_id,
                    "relationship": relationship,
                    "source_reference": evaluation["source_reference"],
                    "applicability_conditions": row.get(
                        "applicability_conditions"
                    ),
                    "applied_hit_ids": [],
                },
            )["applied_hit_ids"].append(hit_id)
    evaluated.sort(key=lambda row: (row["rule_id"], row["evaluated_hit_id"]))
    applicable = sorted(applicable_by_rule_id.values(), key=lambda row: row["rule_id"])
    unruled_hit_ids = sorted(
        (
            _text(hit.get("resource_id"))
            or _text(hit.get("facility_id"))
            or "unknown_hit"
        )
        for hit in hits
        if (
            _text(hit.get("resource_id"))
            or _text(hit.get("facility_id"))
            or "unknown_hit"
        )
        not in decisive_hit_ids
    )
    return evaluated, applicable, unruled_hit_ids


def _feature_collection(rows: list[Mapping[str, Any]], id_field: str) -> dict[str, Any]:
    features = []
    for row in rows:
        geometry = row.get("display_geometry_wgs84")
        if not isinstance(geometry, Mapping):
            continue
        features.append(
            {
                "type": "Feature",
                "id": row.get(id_field),
                "geometry": dict(geometry),
                "properties": {
                    key: value
                    for key, value in row.items()
                    if key != "display_geometry_wgs84"
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _analysis_id(normalized_request: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        normalized_request,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"s6-{sha256(serialized).hexdigest()[:16]}"


def _insufficient_result(
    *,
    validation: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    confirmation_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = validation["normalized_request"]
    semantic_resolution = resolve_s6_facility_semantics(
        facility_name=normalized.get("facility_name"),
        raw_facility_type=normalized.get("raw_facility_type"),
        use_description=normalized.get("use_description"),
        dictionary=dictionary,
    )
    return {
        "schema": SCHEMA,
        "analysis_id": _analysis_id(normalized),
        "analyzed_at": None,
        "status": "insufficient_evidence",
        "max_claim_level": "insufficient_evidence",
        "normalized_request": normalized,
        "semantic_resolution": semantic_resolution,
        "human_confirmation_validation": confirmation_validation,
        "screening": {
            "provider": "projected_planar_buffer",
            "distance_m": SCREENING_DISTANCE_M,
            "distance_crs": None,
            "input_geometry_type": None,
            "metric_buffer_area_m2": None,
        },
        "planning_resource_hits": [],
        "current_facility_hits": [],
        "unresolved_objects": {
            "planning_resources": [],
            "current_facilities": [],
            "association_records": [],
        },
        "compatibility_rules_evaluated": [],
        "applied_rule_ids": [],
        "applied_rules": [],
        "unruled_hit_ids": [],
        "validation_blockers": list(validation["blockers"]),
        "production_blockers": list(validation["blockers"]),
        "completeness_warnings": [],
        "claim_boundary": "No spatial or compatibility conclusion is supported.",
        "s1_handoff": {
            "ready": False,
            "confirmed_standard_class_id": None,
            "claim_boundary": "S1 handoff requires a confirmed standard class.",
        },
        "geojson": {
            "proposed_geometry": None,
            "screening_buffer": None,
            "planning_resource_hits": {"type": "FeatureCollection", "features": []},
            "current_facility_hits": {"type": "FeatureCollection", "features": []},
            "unresolved_planning_resources": {"type": "FeatureCollection", "features": []},
            "unresolved_current_facilities": {"type": "FeatureCollection", "features": []},
        },
    }


def analyze_s6_facility_proposal(
    *,
    request: Mapping[str, Any],
    resources: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the evidence-bounded S6 analysis contract."""
    validation = validate_s6_request(request, resources)
    normalized = validation["normalized_request"]
    confirmation_validation = _validate_request_confirmation(request, dictionary)
    if (
        confirmation_validation is not None
        and confirmation_validation.get("valid") is not True
    ):
        blockers = list(validation["blockers"])
        blockers.extend(confirmation_validation.get("validation_errors") or [])
        validation = {**validation, "valid": False, "blockers": blockers}
    if not validation["valid"]:
        return _insufficient_result(
            validation=validation,
            dictionary=dictionary,
            confirmation_validation=confirmation_validation,
        )

    selected_area = validation["selected_area"]
    distance_crs = selected_area["distance_crs"]
    input_geometry, proposed_display_geometry = _projected_input_geometry(
        normalized, resources, distance_crs
    )
    screening_geometry = input_geometry.buffer(SCREENING_DISTANCE_M)
    planning_hits, facility_hits, unresolved = _screen_resources(
        resources=resources,
        area_id=normalized["analysis_area_id"],
        distance_crs=distance_crs,
        input_geometry=input_geometry,
        screening_geometry=screening_geometry,
    )

    semantic_resolution = resolve_s6_facility_semantics(
        facility_name=normalized["facility_name"],
        raw_facility_type=normalized["raw_facility_type"],
        use_description=normalized["use_description"],
        dictionary=dictionary,
    )
    confirmed_class_id = _confirmed_class_id(
        semantic_resolution=semantic_resolution,
        confirmation_validation=confirmation_validation,
    )
    mapped_hits = planning_hits + facility_hits
    evaluated_rules, applicable_rules, unruled_hit_ids = _applicable_rules(
        confirmed_class_id=confirmed_class_id,
        normalized_request=normalized,
        hits=mapped_hits,
        compatibility=compatibility,
    )
    relationships = {row["relationship"] for row in applicable_rules}
    any_spatial_hit = bool(
        planning_hits
        or facility_hits
        or unresolved["planning_resources"]
        or unresolved["current_facilities"]
    )
    if "conflict" in relationships:
        status = "confirmed_conflict"
        max_claim_level = "authoritative_rule_applied"
    elif (
        mapped_hits
        and not unruled_hit_ids
        and "compatible" in relationships
        and not unresolved["planning_resources"]
        and not unresolved["current_facilities"]
    ):
        status = "confirmed_compatible"
        max_claim_level = "authoritative_rule_applied"
    elif any_spatial_hit:
        status = "potential_conflict_review_required"
        max_claim_level = "spatial_screening_only"
    else:
        status = "no_screening_hit"
        max_claim_level = "loaded_snapshot_no_hit_only"

    inventory = resources.get("facility_inventory")
    complete_inventory = (
        isinstance(inventory, Mapping)
        and inventory.get("complete_inventory") is True
    )
    warnings = ["local_planning_coverage_limited_to_loaded_sample_areas"]
    if not complete_inventory:
        warnings.append("facility_inventory_sampled_or_incomplete")
        if status == "no_screening_hit":
            warnings.append(
                "sampled_facility_inventory_no_hit_does_not_establish_absence"
            )
    production_blockers = []
    if dictionary.get("ready") is not True:
        production_blockers.append("authoritative_facility_dictionary_not_ready")
    if compatibility.get("ready") is not True:
        production_blockers.append(
            "authoritative_facility_compatibility_matrix_not_ready"
        )
    if not complete_inventory:
        production_blockers.append("facility_inventory_sampled_or_incomplete")

    proposed_geojson = mapping(proposed_display_geometry)
    screening_geojson = _display_geometry(screening_geometry, distance_crs)
    s1_ready = confirmed_class_id is not None
    result = {
        "schema": SCHEMA,
        "analysis_id": _analysis_id(normalized),
        "analyzed_at": request.get("analysis_timestamp"),
        "status": status,
        "max_claim_level": max_claim_level,
        "normalized_request": normalized,
        "executed_geography": {
            "planning_area_id": normalized["analysis_area_id"],
            "scope": resources.get("scope"),
        },
        "semantic_resolution": semantic_resolution,
        "human_confirmation_validation": confirmation_validation,
        "screening": {
            "provider": "projected_planar_buffer",
            "distance_m": SCREENING_DISTANCE_M,
            "distance_crs": distance_crs,
            "input_geometry_type": input_geometry.geom_type,
            "metric_buffer_area_m2": _rounded(screening_geometry.area),
            "distance_claim": "static_projected_planar_screening_threshold_only",
        },
        "planning_resource_hits": planning_hits,
        "current_facility_hits": facility_hits,
        "unresolved_objects": unresolved,
        "compatibility_rules_evaluated": evaluated_rules,
        "applied_rule_ids": [row["rule_id"] for row in applicable_rules],
        "applied_rules": applicable_rules,
        "unruled_hit_ids": unruled_hit_ids,
        "validation_blockers": [],
        "production_blockers": production_blockers,
        "completeness_warnings": warnings,
        "claim_boundary": (
            "Confirmed states require the cited authoritative rule IDs."
            if applicable_rules
            else "Spatial proximity alone is not a regulatory or business conflict."
        ),
        "s1_handoff": {
            "ready": s1_ready,
            "confirmed_standard_class_id": confirmed_class_id,
            "claim_boundary": (
                "Pass only the confirmed class; S1 retains not_assessed when FP/FPP standards are absent."
                if s1_ready
                else "S1 handoff requires a confirmed standard class."
            ),
        },
        "geojson": {
            "proposed_geometry": proposed_geojson,
            "screening_buffer": screening_geojson,
            "planning_resource_hits": _feature_collection(
                planning_hits, "resource_id"
            ),
            "current_facility_hits": _feature_collection(
                facility_hits, "facility_id"
            ),
            "unresolved_planning_resources": _feature_collection(
                unresolved["planning_resources"], "resource_id"
            ),
            "unresolved_current_facilities": _feature_collection(
                unresolved["current_facilities"], "facility_id"
            ),
        },
    }
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result
