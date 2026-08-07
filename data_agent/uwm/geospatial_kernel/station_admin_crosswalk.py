"""Fail-closed station-to-administrative-unit spatial crosswalks."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import unary_union

STATION_ADMIN_CROSSWALK_SCHEMA = "uwm.geospatial_kernel.station_admin_crosswalk.v1"
STATION_ADMIN_CROSSWALK_GATES = (
    "locations_payload_parseable",
    "admin_feature_collection_parseable",
    "coordinate_crs_is_wgs84",
    "station_ids_unique_and_complete",
    "station_coordinates_complete",
    "admin_identifiers_complete",
    "admin_geometries_valid",
    "all_stations_matched_exactly_once",
)

_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "station_admin_spatial_assignment_audit_only",
    "official_admin_identifier_claim": False,
    "historical_boundary_alignment_claim": False,
    "scientific_result_claim": False,
}


def build_station_admin_crosswalk(
    *,
    crosswalk_id: str,
    created_at: str,
    locations_payload: Mapping[str, Any],
    admin_feature_collection: Mapping[str, Any],
    source_refs: Sequence[str],
) -> dict[str, Any]:
    """Assign station points to local admin polygons with explicit ambiguity audit."""

    if not _nonempty_string(crosswalk_id):
        raise ValueError("station_admin_crosswalk_id_required")
    _require_aware_timestamp(created_at)
    locations = copy.deepcopy(dict(locations_payload))
    admin_source = copy.deepcopy(dict(admin_feature_collection))
    refs = _unique_nonempty_strings(source_refs)

    location_rows = locations.get("results")
    locations_parseable = isinstance(location_rows, list) and all(
        isinstance(row, Mapping) for row in location_rows
    )
    stations = _station_rows(location_rows if isinstance(location_rows, list) else [])
    station_ids = [row["station_id"] for row in stations if row["station_id"]]

    features = admin_source.get("features")
    admin_parseable = (
        admin_source.get("type") == "FeatureCollection"
        and isinstance(features, list)
        and all(isinstance(feature, Mapping) for feature in features)
    )
    crs_wgs84 = _is_wgs84(admin_source)
    admin_units, admin_audit = _admin_units(features if isinstance(features, list) else [])

    assignments = []
    for station in sorted(stations, key=lambda row: row["station_id"]):
        longitude = station["longitude"]
        latitude = station["latitude"]
        candidates = []
        if longitude is not None and latitude is not None:
            point = Point(longitude, latitude)
            candidates = [unit for unit in admin_units if unit["geometry"].covers(point)]
        status = (
            "invalid_coordinates"
            if longitude is None or latitude is None
            else "unmatched"
            if not candidates
            else "matched"
            if len(candidates) == 1
            else "ambiguous"
        )
        candidate_rows = [
            {
                "admin_id": candidate["admin_id"],
                "province": candidate["province"],
                "city": candidate["city"],
                "county": candidate["county"],
                "township": candidate["township"],
            }
            for candidate in sorted(candidates, key=lambda row: row["admin_id"])
        ]
        assignments.append(
            {
                "station_id": station["station_id"],
                "station_name": station["station_name"],
                "longitude": longitude,
                "latitude": latitude,
                "status": status,
                "candidate_count": len(candidate_rows),
                "assignment": candidate_rows[0] if status == "matched" else None,
                "candidates": candidate_rows,
            }
        )

    status_counts = {
        status: sum(row["status"] == status for row in assignments)
        for status in ("matched", "unmatched", "ambiguous", "invalid_coordinates")
    }
    gates = {
        "locations_payload_parseable": locations_parseable,
        "admin_feature_collection_parseable": admin_parseable,
        "coordinate_crs_is_wgs84": crs_wgs84,
        "station_ids_unique_and_complete": bool(stations)
        and len(station_ids) == len(stations)
        and len(set(station_ids)) == len(stations),
        "station_coordinates_complete": bool(stations)
        and all(row["longitude"] is not None and row["latitude"] is not None for row in stations),
        "admin_identifiers_complete": bool(admin_units)
        and admin_audit["missing_identifier_feature_count"] == 0,
        "admin_geometries_valid": bool(admin_units)
        and admin_audit["invalid_geometry_feature_count"] == 0,
        "all_stations_matched_exactly_once": bool(assignments)
        and status_counts["matched"] == len(assignments),
    }
    complete = all(gates.values())
    artifact = {
        "schema": STATION_ADMIN_CROSSWALK_SCHEMA,
        "version": "0.1",
        "crosswalk_id": str(crosswalk_id),
        "created_at": str(created_at),
        "spatial_relation": "station_point_covered_by_admin_polygon",
        "coordinate_crs": "EPSG:4326",
        "admin_identifier_semantics": "local_province_county_township_name_composite",
        "input_artifact_sha256": {
            "locations_payload_sha256": _canonical_sha256(locations),
            "admin_feature_collection_sha256": _canonical_sha256(admin_source),
        },
        "source_refs": refs,
        "assignments": assignments,
        "audit": {
            "location_row_count": len(location_rows) if isinstance(location_rows, list) else 0,
            "station_count": len(stations),
            "admin_feature_count": len(features) if isinstance(features, list) else 0,
            "admin_unit_count": len(admin_units),
            **admin_audit,
            "assignment_status_counts": status_counts,
            "unmatched_station_ids": [
                row["station_id"] for row in assignments if row["status"] == "unmatched"
            ],
            "ambiguous_station_ids": [
                row["station_id"] for row in assignments if row["status"] == "ambiguous"
            ],
            "invalid_coordinate_station_ids": [
                row["station_id"] for row in assignments if row["status"] == "invalid_coordinates"
            ],
        },
        "gate_results": gates,
        "remaining_gates": [gate for gate in STATION_ADMIN_CROSSWALK_GATES if not gates[gate]],
        "crosswalk_complete": complete,
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
    }
    artifact["crosswalk_sha256"] = compute_station_admin_crosswalk_sha256(artifact)
    validation = validate_station_admin_crosswalk(artifact)
    if not validation["valid"]:
        raise ValueError("invalid_station_admin_crosswalk:" + ";".join(validation["errors"]))
    return artifact


def validate_station_admin_crosswalk(payload: Any) -> dict[str, Any]:
    """Validate structural and fail-closed consistency of a crosswalk artifact."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["station_admin_crosswalk_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "crosswalk_id",
        "created_at",
        "spatial_relation",
        "coordinate_crs",
        "admin_identifier_semantics",
        "input_artifact_sha256",
        "source_refs",
        "assignments",
        "audit",
        "gate_results",
        "remaining_gates",
        "crosswalk_complete",
        "claim_boundary",
        "crosswalk_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("station_admin_crosswalk_field_set_mismatch")
    if payload.get("schema") != STATION_ADMIN_CROSSWALK_SCHEMA:
        errors.append("station_admin_crosswalk_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("station_admin_crosswalk_version_mismatch")
    if not _nonempty_string(payload.get("crosswalk_id")):
        errors.append("station_admin_crosswalk_id_required")
    if _parse_aware_timestamp(payload.get("created_at")) is None:
        errors.append("station_admin_crosswalk_created_at_invalid")
    if payload.get("spatial_relation") != "station_point_covered_by_admin_polygon":
        errors.append("station_admin_crosswalk_spatial_relation_invalid")
    if payload.get("coordinate_crs") != "EPSG:4326":
        errors.append("station_admin_crosswalk_crs_invalid")
    if payload.get("admin_identifier_semantics") != (
        "local_province_county_township_name_composite"
    ):
        errors.append("station_admin_crosswalk_identifier_semantics_invalid")

    hashes = payload.get("input_artifact_sha256")
    if (
        not isinstance(hashes, dict)
        or set(hashes)
        != {
            "locations_payload_sha256",
            "admin_feature_collection_sha256",
        }
        or any(not _valid_sha256(value) for value in hashes.values())
    ):
        errors.append("station_admin_crosswalk_input_hashes_invalid")
    refs = payload.get("source_refs")
    if not isinstance(refs, list) or not refs or refs != _unique_nonempty_strings(refs):
        errors.append("station_admin_crosswalk_source_refs_invalid")

    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or not all(_valid_assignment(row) for row in assignments):
        errors.append("station_admin_crosswalk_assignments_invalid")
        assignment_rows: list[dict[str, Any]] = []
        expected_assignment_gates: dict[str, bool] = {}
        expected_status_counts: dict[str, int] = {}
    elif assignments != sorted(assignments, key=lambda row: row["station_id"]):
        errors.append("station_admin_crosswalk_assignments_not_sorted")
        assignment_rows = assignments
        expected_assignment_gates, expected_status_counts = _assignment_gate_audit(assignments)
    else:
        assignment_rows = assignments
        expected_assignment_gates, expected_status_counts = _assignment_gate_audit(assignments)

    audit = payload.get("audit")
    expected_audit_fields = {
        "location_row_count",
        "station_count",
        "admin_feature_count",
        "admin_unit_count",
        "missing_identifier_feature_count",
        "invalid_geometry_feature_count",
        "assignment_status_counts",
        "unmatched_station_ids",
        "ambiguous_station_ids",
        "invalid_coordinate_station_ids",
    }
    count_fields = (
        "location_row_count",
        "station_count",
        "admin_feature_count",
        "admin_unit_count",
        "missing_identifier_feature_count",
        "invalid_geometry_feature_count",
    )
    if not isinstance(audit, dict) or set(audit) != expected_audit_fields:
        errors.append("station_admin_crosswalk_audit_invalid")
        expected_audit_gates: dict[str, bool] = {}
    elif any(
        not isinstance(audit.get(field), int)
        or isinstance(audit.get(field), bool)
        or audit[field] < 0
        for field in count_fields
    ):
        errors.append("station_admin_crosswalk_audit_counts_invalid")
        expected_audit_gates = {}
    else:
        expected_audit_gates = {
            "admin_identifiers_complete": audit["admin_unit_count"] > 0
            and audit["missing_identifier_feature_count"] == 0,
            "admin_geometries_valid": audit["admin_unit_count"] > 0
            and audit["invalid_geometry_feature_count"] == 0,
        }
        expected_lists = {
            "unmatched_station_ids": [
                row["station_id"] for row in assignment_rows if row["status"] == "unmatched"
            ],
            "ambiguous_station_ids": [
                row["station_id"] for row in assignment_rows if row["status"] == "ambiguous"
            ],
            "invalid_coordinate_station_ids": [
                row["station_id"]
                for row in assignment_rows
                if row["status"] == "invalid_coordinates"
            ],
        }
        if audit["station_count"] != len(assignment_rows):
            errors.append("station_admin_crosswalk_audit_station_count_mismatch")
        if audit.get("assignment_status_counts") != expected_status_counts:
            errors.append("station_admin_crosswalk_audit_status_counts_mismatch")
        if any(audit.get(field) != values for field, values in expected_lists.items()):
            errors.append("station_admin_crosswalk_audit_station_lists_mismatch")

    gates = payload.get("gate_results")
    if (
        not isinstance(gates, dict)
        or tuple(gates) != STATION_ADMIN_CROSSWALK_GATES
        or any(not isinstance(value, bool) for value in gates.values())
    ):
        errors.append("station_admin_crosswalk_gates_invalid")
        all_pass = False
        expected_remaining: list[str] = []
    else:
        all_pass = all(gates.values())
        expected_remaining = [gate for gate in STATION_ADMIN_CROSSWALK_GATES if not gates[gate]]
        expected_gates = {**expected_assignment_gates, **expected_audit_gates}
        if expected_gates and any(
            gates.get(gate) is not value for gate, value in expected_gates.items()
        ):
            errors.append("station_admin_crosswalk_gate_assignment_audit_mismatch")
    if payload.get("remaining_gates") != expected_remaining:
        errors.append("station_admin_crosswalk_remaining_gates_mismatch")
    if payload.get("crosswalk_complete") is not all_pass:
        errors.append("station_admin_crosswalk_complete_mismatch")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("station_admin_crosswalk_claim_boundary_invalid")
    digest = payload.get("crosswalk_sha256")
    if not _valid_sha256(digest):
        errors.append("station_admin_crosswalk_sha256_invalid")
    elif digest != compute_station_admin_crosswalk_sha256(payload):
        errors.append("station_admin_crosswalk_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def station_admin_assignment_map(
    payload: Mapping[str, Any], *, require_complete: bool = True
) -> dict[str, str]:
    """Extract matched station/admin IDs only from a valid crosswalk artifact."""

    validation = validate_station_admin_crosswalk(payload)
    if not validation["valid"]:
        raise ValueError("invalid_station_admin_crosswalk:" + ";".join(validation["errors"]))
    if require_complete and payload.get("crosswalk_complete") is not True:
        raise ValueError("station_admin_crosswalk_incomplete")
    return {
        str(row["station_id"]): str(row["assignment"]["admin_id"])
        for row in payload["assignments"]
        if row["status"] == "matched"
    }


def compute_station_admin_crosswalk_sha256(payload: Mapping[str, Any]) -> str:
    values = copy.deepcopy(dict(payload))
    values.pop("crosswalk_sha256", None)
    return _canonical_sha256(values)


def _station_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    stations = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        coordinates = row.get("coordinates")
        if not isinstance(coordinates, Mapping):
            coordinates = {}
        stations.append(
            {
                "station_id": str(row.get("id") or "").strip(),
                "station_name": str(row.get("name") or "").strip() or None,
                "longitude": _coordinate(coordinates.get("longitude"), minimum=-180, maximum=180),
                "latitude": _coordinate(coordinates.get("latitude"), minimum=-90, maximum=90),
            }
        )
    return stations


def _admin_units(features: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    properties_by_id: dict[str, dict[str, str]] = {}
    missing_identifier_count = 0
    invalid_geometry_count = 0
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        fields = {
            field: str(properties.get(field) or "").strip()
            for field in ("province", "city", "county", "township")
        }
        if not fields["province"] or not fields["county"] or not fields["township"]:
            missing_identifier_count += 1
            continue
        admin_id = "|".join((fields["province"], fields["county"], fields["township"]))
        try:
            geometry = shape(feature.get("geometry"))
        except (AttributeError, TypeError, ValueError):
            invalid_geometry_count += 1
            continue
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            invalid_geometry_count += 1
            continue
        if not geometry.is_valid:
            invalid_geometry_count += 1
            continue
        grouped[admin_id].append(geometry)
        properties_by_id[admin_id] = fields
    units = []
    for admin_id, geometries in grouped.items():
        fields = properties_by_id[admin_id]
        units.append({"admin_id": admin_id, **fields, "geometry": unary_union(geometries)})
    return sorted(units, key=lambda row: row["admin_id"]), {
        "missing_identifier_feature_count": missing_identifier_count,
        "invalid_geometry_feature_count": invalid_geometry_count,
    }


def _is_wgs84(payload: Mapping[str, Any]) -> bool:
    crs = payload.get("crs")
    if crs is None:
        return True
    if not isinstance(crs, Mapping):
        return False
    properties = crs.get("properties")
    if not isinstance(properties, Mapping):
        return False
    name = str(properties.get("name") or "").lower()
    return "4326" in name or "crs84" in name


def _valid_assignment(row: Any) -> bool:
    if not isinstance(row, dict) or set(row) != {
        "station_id",
        "station_name",
        "longitude",
        "latitude",
        "status",
        "candidate_count",
        "assignment",
        "candidates",
    }:
        return False
    status = row.get("status")
    candidates = row.get("candidates")
    if (
        not _nonempty_string(row.get("station_id"))
        or status
        not in {
            "matched",
            "unmatched",
            "ambiguous",
            "invalid_coordinates",
        }
        or not isinstance(candidates, list)
    ):
        return False
    if row.get("candidate_count") != len(candidates) or not all(
        _valid_admin_candidate(candidate) for candidate in candidates
    ):
        return False
    longitude = _coordinate(row.get("longitude"), minimum=-180, maximum=180)
    latitude = _coordinate(row.get("latitude"), minimum=-90, maximum=90)
    if status == "invalid_coordinates":
        if longitude is not None and latitude is not None:
            return False
    elif longitude is None or latitude is None:
        return False
    if candidates != sorted(candidates, key=lambda candidate: candidate["admin_id"]):
        return False
    if status == "matched":
        return len(candidates) == 1 and row.get("assignment") == candidates[0]
    return row.get("assignment") is None and (
        len(candidates) > 1 if status == "ambiguous" else len(candidates) == 0
    )


def _assignment_gate_audit(
    assignments: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, bool], dict[str, int]]:
    station_ids = [str(row["station_id"]) for row in assignments]
    status_counts = {
        status: sum(row["status"] == status for row in assignments)
        for status in ("matched", "unmatched", "ambiguous", "invalid_coordinates")
    }
    return {
        "station_ids_unique_and_complete": bool(station_ids)
        and len(set(station_ids)) == len(station_ids),
        "station_coordinates_complete": bool(assignments)
        and status_counts["invalid_coordinates"] == 0,
        "all_stations_matched_exactly_once": bool(assignments)
        and status_counts["matched"] == len(assignments),
    }, status_counts


def _valid_admin_candidate(candidate: Any) -> bool:
    if (
        not isinstance(candidate, dict)
        or set(candidate)
        != {
            "admin_id",
            "province",
            "city",
            "county",
            "township",
        }
        or not all(_nonempty_string(value) for value in candidate.values())
    ):
        return False
    return candidate["admin_id"] == "|".join(
        (candidate["province"], candidate["county"], candidate["township"])
    )


def _coordinate(value: Any, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_nonempty_strings(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _require_aware_timestamp(value: Any) -> None:
    if _parse_aware_timestamp(value) is None:
        raise ValueError("station_admin_crosswalk_created_at_invalid")
