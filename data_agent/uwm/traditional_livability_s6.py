from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Mapping

from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform
from shapely.prepared import prep

from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
    validate_human_confirmation,
)


SCHEMA = "uwm.traditional_livability.s6_analysis.v1"
SCREENING_DISTANCE_M = 150.0
_MAX_DISPLAY_FEATURE_COUNT = 1000

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


def _json_safe_detached(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )


def _json_audit_value(value: Any) -> Any:
    try:
        return _json_safe_detached(value)
    except (TypeError, ValueError):
        return {"invalid_json_value_type": type(value).__name__}


def _safe_geometry(value: Any):
    if not isinstance(value, Mapping):
        return None
    try:
        geometry = shape(value)
        if geometry.is_empty or not geometry.is_valid:
            return None
    except Exception:
        return None
    return geometry


def _projected_crs_uses_metres(crs: CRS) -> bool:
    horizontal_axes = list(crs.axis_info[:2])
    if len(horizontal_axes) != 2:
        return False
    return all(
        axis.unit_conversion_factor is not None
        and math.isclose(
            float(axis.unit_conversion_factor),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        for axis in horizontal_axes
    )


def _duplicate_ids(
    rows: list[Mapping[str, Any]],
    *fields: str,
) -> list[tuple[str, ...]]:
    counts: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = tuple(_text(row.get(field)) or "" for field in fields)
        if all(key):
            counts[key] = counts.get(key, 0) + 1
    return sorted(key for key, count in counts.items() if count > 1)


def _source_record_reference(row: Mapping[str, Any], index: int) -> str:
    return _text(row.get("source_record_id")) or f"row-{index}"


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

    area_rows = _rows(resource_payload, "planning_areas")
    for (duplicate_area_id,) in _duplicate_ids(area_rows, "planning_area_id"):
        blockers.append(f"duplicate_planning_area_id:{duplicate_area_id}")
    resource_rows = _rows(resource_payload, "planning_resources")

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
                parsed_crs = CRS.from_user_input(distance_crs)
                if not parsed_crs.is_projected:
                    blockers.append(
                        f"planning_area_distance_crs_not_projected:{analysis_area_id}"
                    )
                elif not _projected_crs_uses_metres(parsed_crs):
                    blockers.append(
                        f"planning_area_distance_crs_not_metre:{analysis_area_id}"
                    )
            except Exception:
                blockers.append(
                    f"planning_area_distance_crs_invalid:{analysis_area_id}"
                )
        if _safe_geometry(selected_area.get("metric_geometry")) is None:
            blockers.append(f"planning_area_geometry_missing:{analysis_area_id}")

        active_resources = [
            resource
            for resource in resource_rows
            if _text(resource.get("planning_area_id")) == analysis_area_id
        ]
        for index, resource in enumerate(active_resources):
            if _text(resource.get("resource_id")) is None:
                blockers.append(
                    "planning_resource_id_missing:"
                    f"{analysis_area_id}:"
                    f"{_source_record_reference(resource, index)}"
                )
        for duplicate_resource_area_id, duplicate_resource_id in _duplicate_ids(
            resource_rows, "planning_area_id", "resource_id"
        ):
            blockers.append(
                "duplicate_planning_resource_id:"
                f"{duplicate_resource_area_id}:{duplicate_resource_id}"
            )

        active_facilities = []
        for facility in _rows(resource_payload, "current_facilities"):
            matching_area_ids = facility.get("matching_planning_area_ids")
            belongs_to_active_area = (
                _text(facility.get("planning_area_id")) == analysis_area_id
                or (
                    isinstance(matching_area_ids, list)
                    and analysis_area_id in matching_area_ids
                )
            )
            if belongs_to_active_area:
                active_facilities.append(facility)
        for index, facility in enumerate(active_facilities):
            if _text(facility.get("facility_id")) is None:
                blockers.append(
                    "current_facility_id_missing:"
                    f"{analysis_area_id}:"
                    f"{_source_record_reference(facility, index)}"
                )
        for (duplicate_facility_id,) in _duplicate_ids(
            active_facilities, "facility_id"
        ):
            blockers.append(
                "duplicate_current_facility_id:"
                f"{analysis_area_id}:{duplicate_facility_id}"
            )
        for facility in active_facilities:
            if (
                _text(facility.get("facility_id")) is not None
                and _text(facility.get("association_status"))
                == "multi_area_overlap_unresolved"
            ):
                facility_id = _text(facility.get("facility_id")) or "unknown"
                blockers.append(
                    "current_facility_spatial_association_unresolved:"
                    f"{facility_id}"
                )

    normalized: dict[str, Any] = {
        "input_mode": input_mode,
        "analysis_area_id": analysis_area_id,
        "facility_name": _text(request.get("facility_name")),
        "raw_facility_type": _text(request.get("raw_facility_type")),
        "use_description": _text(request.get("use_description")),
        "confirmed_standard_class_id": _text(
            request.get("confirmed_standard_class_id")
        ),
        "human_confirmation": None,
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

    selected_parcel_id = normalized.get("parcel_id")
    for resource in resource_rows:
        if _text(resource.get("planning_area_id")) != analysis_area_id:
            continue
        resource_id = _text(resource.get("resource_id")) or "unknown"
        if resource_id == selected_parcel_id:
            continue
        if _safe_geometry(resource.get("metric_geometry")) is None:
            blockers.append(
                f"planning_resource_geometry_missing:{resource_id}"
            )
    for facility in _rows(resource_payload, "current_facilities"):
        if _text(facility.get("planning_area_id")) != analysis_area_id:
            continue
        if _safe_geometry(facility.get("metric_geometry")) is None:
            facility_id = _text(facility.get("facility_id")) or "unknown"
            blockers.append(f"current_facility_geometry_missing:{facility_id}")

    return _json_safe_detached({
        "valid": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "normalized_request": normalized,
        "selected_area": dict(selected_area) if selected_area is not None else None,
    })


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


def _qualified_hit_id(channel: str, raw_id: Any) -> str:
    return f"{channel}:{_text(raw_id) or 'unknown'}"


def _bbox_intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0]
        or first[0] > second[2]
        or first[3] < second[1]
        or first[1] > second[3]
    )


def _hit_display_geometry(
    row: Mapping[str, Any], metric_geometry, distance_crs: str
) -> dict[str, Any]:
    display_geometry = _safe_geometry(row.get("display_geometry_wgs84"))
    if display_geometry is not None:
        return mapping(display_geometry)
    return _display_geometry(metric_geometry, distance_crs)


def _planning_hit(
    row: Mapping[str, Any], geometry, input_geometry, screening_geometry
) -> dict[str, Any]:
    intersection = geometry.intersection(screening_geometry)
    intersection_area = None
    if not intersection.is_empty and intersection.area > 0:
        intersection_area = _rounded(intersection.area)
    return {
        "channel": "planning",
        "evidence_id": _qualified_hit_id("planning", row.get("resource_id")),
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
        "geometry_ref": (
            "geojson:"
            f"{_qualified_hit_id('planning', row.get('resource_id'))}"
        ),
    }


def _facility_hit(
    row: Mapping[str, Any], geometry, input_geometry
) -> dict[str, Any]:
    return {
        "channel": "facility",
        "evidence_id": _qualified_hit_id("facility", row.get("facility_id")),
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
        "geometry_ref": (
            "geojson:"
            f"{_qualified_hit_id('facility', row.get('facility_id'))}"
        ),
    }


def _screen_resources(
    *,
    resources: Mapping[str, Any],
    area_id: str,
    distance_crs: str,
    input_geometry,
    screening_geometry,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    planning_hits = []
    unresolved_planning = []
    display_geometries: dict[str, dict[str, Any]] = {}
    screening_bounds = screening_geometry.bounds
    prepared_screening = prep(screening_geometry)
    for row in _rows(resources, "planning_resources"):
        if _text(row.get("planning_area_id")) != area_id:
            continue
        if _text(row.get("distance_crs")) != distance_crs:
            continue
        geometry = _safe_geometry(row.get("metric_geometry"))
        if (
            geometry is None
            or not _bbox_intersects(geometry.bounds, screening_bounds)
            or not prepared_screening.intersects(geometry)
        ):
            continue
        hit = _planning_hit(row, geometry, input_geometry, screening_geometry)
        display_geometries[hit["evidence_id"]] = _hit_display_geometry(
            row, geometry, distance_crs
        )
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
        if (
            geometry is None
            or not _bbox_intersects(geometry.bounds, screening_bounds)
            or not prepared_screening.intersects(geometry)
        ):
            continue
        hit = _facility_hit(row, geometry, input_geometry)
        display_geometries[hit["evidence_id"]] = _hit_display_geometry(
            row, geometry, distance_crs
        )
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
    return (
        planning_hits,
        facility_hits,
        {
            "planning_resources": unresolved_planning,
            "current_facilities": unresolved_facilities,
            "association_records": unresolved_associations,
        },
        display_geometries,
    )


def _validate_request_confirmation(
    request: Mapping[str, Any],
    dictionary: Mapping[str, Any],
) -> dict[str, Any] | None:
    confirmation = request.get("human_confirmation")
    if not isinstance(confirmation, Mapping):
        return None
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


def _select_confirmed_class(
    *,
    requested_class_id: str | None,
    semantic_resolution: Mapping[str, Any],
    confirmation_validation: Mapping[str, Any] | None,
) -> tuple[str | None, list[str]]:
    authoritative_class_id = None
    if semantic_resolution.get("resolution_status") == "authoritative_confirmed":
        authoritative_class_id = _text(
            semantic_resolution.get("confirmed_standard_class_id")
        )
    confirmation_class_id = None
    if (
        confirmation_validation is not None
        and confirmation_validation.get("valid") is True
    ):
        confirmation_class_id = _text(
            confirmation_validation.get("selected_standard_class_id")
        )

    if (
        requested_class_id is not None
        and confirmation_class_id is not None
        and requested_class_id != confirmation_class_id
    ):
        return None, ["confirmed_class_confirmation_mismatch"]
    if requested_class_id is not None and authoritative_class_id is not None:
        if requested_class_id != authoritative_class_id:
            return None, ["confirmed_class_authoritative_mismatch"]
        return authoritative_class_id, []
    if requested_class_id is not None and confirmation_class_id is not None:
        return confirmation_class_id, []
    if requested_class_id is not None:
        return None, ["confirmed_class_requires_valid_human_confirmation"]
    if confirmation_class_id is not None:
        return confirmation_class_id, []
    if authoritative_class_id is not None:
        return authoritative_class_id, []
    return None, []


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
        return [], [], [str(hit["evidence_id"]) for hit in hits]
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
            hit_id = str(hit["evidence_id"])
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
                "applicability_conditions": _json_audit_value(
                    row.get("applicability_conditions")
                ),
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
                    "applicability_conditions": _json_audit_value(
                        row.get("applicability_conditions")
                    ),
                    "applied_hit_ids": [],
                },
            )["applied_hit_ids"].append(hit_id)
    evaluated.sort(key=lambda row: (row["rule_id"], row["evaluated_hit_id"]))
    applicable = sorted(applicable_by_rule_id.values(), key=lambda row: row["rule_id"])
    unruled_hit_ids = sorted(
        str(hit["evidence_id"])
        for hit in hits
        if str(hit["evidence_id"]) not in decisive_hit_ids
    )
    return evaluated, applicable, unruled_hit_ids


def _feature_collection(
    rows: list[Mapping[str, Any]],
    display_geometries: Mapping[str, Mapping[str, Any]],
    limit: int,
) -> tuple[dict[str, Any], int]:
    features = []
    for row in rows[:limit]:
        evidence_id = str(row["evidence_id"])
        geometry = display_geometries.get(evidence_id)
        if not isinstance(geometry, Mapping):
            continue
        features.append(
            {
                "type": "Feature",
                "id": evidence_id,
                "geometry": dict(geometry),
                "properties": dict(row),
            }
        )
    return {"type": "FeatureCollection", "features": features}, len(features)


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
    semantic_resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = validation["normalized_request"]
    if semantic_resolution is None:
        semantic_resolution = resolve_s6_facility_semantics(
            facility_name=normalized.get("facility_name"),
            raw_facility_type=normalized.get("raw_facility_type"),
            use_description=normalized.get("use_description"),
            dictionary=dictionary,
        )
    return _json_safe_detached({
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
        "geometry_payload": {
            "max_display_feature_count": _MAX_DISPLAY_FEATURE_COUNT,
            "truncated": False,
            "total_feature_count": 0,
            "returned_feature_count": 0,
        },
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
    })


def analyze_s6_facility_proposal(
    *,
    request: Mapping[str, Any],
    resources: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the evidence-bounded S6 analysis contract."""
    validation = validate_s6_request(request, resources)
    normalized = dict(validation["normalized_request"])
    semantic_resolution = resolve_s6_facility_semantics(
        facility_name=normalized.get("facility_name"),
        raw_facility_type=normalized.get("raw_facility_type"),
        use_description=normalized.get("use_description"),
        dictionary=dictionary,
    )
    confirmation_validation = _validate_request_confirmation(request, dictionary)
    normalized["human_confirmation"] = confirmation_validation
    blockers = list(validation["blockers"])
    if (
        confirmation_validation is not None
        and confirmation_validation.get("valid") is not True
    ):
        blockers.extend(confirmation_validation.get("validation_errors") or [])
    confirmed_class_id, class_selection_blockers = _select_confirmed_class(
        requested_class_id=normalized.get("confirmed_standard_class_id"),
        semantic_resolution=semantic_resolution,
        confirmation_validation=confirmation_validation,
    )
    blockers.extend(class_selection_blockers)
    blockers = list(dict.fromkeys(blockers))
    if not blockers:
        normalized["confirmed_standard_class_id"] = confirmed_class_id
    validation = {
        **validation,
        "valid": not blockers,
        "blockers": blockers,
        "normalized_request": normalized,
    }
    if not validation["valid"]:
        return _insufficient_result(
            validation=validation,
            dictionary=dictionary,
            confirmation_validation=confirmation_validation,
            semantic_resolution=semantic_resolution,
        )

    selected_area = validation["selected_area"]
    distance_crs = selected_area["distance_crs"]
    input_geometry, proposed_display_geometry = _projected_input_geometry(
        normalized, resources, distance_crs
    )
    screening_geometry = input_geometry.buffer(SCREENING_DISTANCE_M)
    planning_hits, facility_hits, unresolved, display_geometries = _screen_resources(
        resources=resources,
        area_id=normalized["analysis_area_id"],
        distance_crs=distance_crs,
        input_geometry=input_geometry,
        screening_geometry=screening_geometry,
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
    display_channels = (
        ("planning_resource_hits", planning_hits),
        ("current_facility_hits", facility_hits),
        (
            "unresolved_planning_resources",
            unresolved["planning_resources"],
        ),
        (
            "unresolved_current_facilities",
            unresolved["current_facilities"],
        ),
    )
    remaining_display_features = _MAX_DISPLAY_FEATURE_COUNT
    returned_display_feature_count = 0
    display_feature_collections = {}
    for channel_name, channel_rows in display_channels:
        feature_collection, returned_count = _feature_collection(
            channel_rows,
            display_geometries,
            remaining_display_features,
        )
        display_feature_collections[channel_name] = feature_collection
        returned_display_feature_count += returned_count
        remaining_display_features -= returned_count
    total_display_feature_count = sum(
        len(channel_rows) for _, channel_rows in display_channels
    )
    geometry_payload_truncated = (
        returned_display_feature_count < total_display_feature_count
    )
    if geometry_payload_truncated:
        production_blockers.append("display_geometry_payload_truncated")
    s1_ready = confirmed_class_id is not None
    claim_boundary = (
        "Confirmed states require the cited authoritative rule IDs."
        if applicable_rules
        else "Spatial proximity alone is not a regulatory or business conflict."
    )
    if geometry_payload_truncated:
        claim_boundary += (
            " Hit evidence is complete; display GeoJSON is capped and truncated."
        )
    result = {
        "schema": SCHEMA,
        "analysis_id": _analysis_id(normalized),
        "analyzed_at": _text(request.get("analysis_timestamp")),
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
        "claim_boundary": claim_boundary,
        "geometry_payload": {
            "max_display_feature_count": _MAX_DISPLAY_FEATURE_COUNT,
            "truncated": geometry_payload_truncated,
            "total_feature_count": total_display_feature_count,
            "returned_feature_count": returned_display_feature_count,
        },
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
            **display_feature_collections,
        },
    }
    return _json_safe_detached(result)
