#!/usr/bin/env python3
"""Join the preregistered Chicago cohort to official spatial crosswalks."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_COHORT_INPUT = EVIDENCE_DIR / "historical_cohort_preregistration.json"
DEFAULT_ZONING_INPUT = (
    EVIDENCE_DIR / "chicago_current_zoning_2024_preregistered_cohort.json"
)
DEFAULT_GEOCODER_REQUEST_INPUT = (
    EVIDENCE_DIR / "historical_cohort_geocoder_request_v2.json"
)
DEFAULT_GEOCODER_RESPONSE_INPUT = (
    EVIDENCE_DIR / "chicago_addresspoints_2024_preregistered_cohort_v2.json"
)
DEFAULT_PARCEL_INPUT = (
    EVIDENCE_DIR / "chicago_official_parcel_addresses_19_crosswalk.json"
)
PARCEL_METADATA_INPUT = (
    EVIDENCE_DIR / "chicago_official_parcel_addresses_layer1_metadata.json"
)
DEFAULT_OUTPUT = EVIDENCE_DIR / "historical_cohort_spatial_crosswalk.json"
RETRY_FILES = {
    "O2024-0008445": "chicago_addresspoints_retry_O2024_0008445.json",
    "O2024-0008449": "chicago_addresspoints_retry_O2024_0008449.json",
    "O2024-0009011": "chicago_addresspoints_retry_O2024_0009011.json",
    "O2024-0009013": "chicago_addresspoints_retry_O2024_0009013.json",
}
POINT_CONTEXT_FILES = {
    "O2024-0012332": (
        "chicago_current_zoning_point_context_O2024_0012332.json"
    ),
}
LEGAL_LOT_AREAS = {
    "O2024-0012247": 2088.0,
    "O2024-0012532": 3885.0,
}


def build_historical_zoning_crosswalk(
    *,
    cohort_path: Path = DEFAULT_COHORT_INPUT,
    zoning_path: Path = DEFAULT_ZONING_INPUT,
    geocoder_request_path: Path = DEFAULT_GEOCODER_REQUEST_INPUT,
    geocoder_response_path: Path = DEFAULT_GEOCODER_RESPONSE_INPUT,
    parcel_path: Path = DEFAULT_PARCEL_INPUT,
) -> dict[str, Any]:
    """Return a fail-closed point, tract, and zoning-map crosswalk."""

    cohort = _read_json(cohort_path)
    zoning = _read_json(zoning_path)
    geocoder_request = _read_json(geocoder_request_path)
    geocoder_response = _read_json(geocoder_response_path)
    parcels = _read_json(parcel_path)
    cohort_events = cohort.get("events")
    cohort_events = cohort_events if isinstance(cohort_events, list) else []

    zoning_by_record: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    zoning_features = zoning.get("features")
    zoning_features = zoning_features if isinstance(zoning_features, list) else []
    for feature in zoning_features:
        if not isinstance(feature, Mapping):
            continue
        attributes = feature.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        zoning_by_record[str(attributes.get("CLERK_DOCNO") or "")].append(feature)

    request_records = geocoder_request.get("records")
    request_records = request_records if isinstance(request_records, list) else []
    result_id_to_record = {
        int(attributes["OBJECTID"]): str(attributes["record_number"])
        for request_record in request_records
        if isinstance(request_record, Mapping)
        for attributes in [request_record.get("attributes")]
        if isinstance(attributes, Mapping)
        and isinstance(attributes.get("OBJECTID"), int)
        and attributes.get("record_number")
    }
    geocoder_by_record: dict[str, Mapping[str, Any]] = {}
    locations = geocoder_response.get("locations")
    locations = locations if isinstance(locations, list) else []
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        attributes = location.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        result_id = attributes.get("ResultID")
        if isinstance(result_id, int) and result_id in result_id_to_record:
            geocoder_by_record[result_id_to_record[result_id]] = location

    parcel_by_pin: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    parcel_features = parcels.get("features")
    parcel_features = parcel_features if isinstance(parcel_features, list) else []
    for feature in parcel_features:
        if not isinstance(feature, Mapping):
            continue
        attributes = feature.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        parcel_by_pin[str(attributes.get("PIN10") or "")].append(feature)

    events = [
        _build_event_crosswalk(
            event=event,
            zoning_features=zoning_by_record.get(
                str(event.get("record_number") or ""), []
            ),
            geocoder_location=geocoder_by_record.get(
                str(event.get("record_number") or ""), {}
            ),
            parcel_by_pin=parcel_by_pin,
        )
        for event in cohort_events
        if isinstance(event, Mapping)
    ]
    zoning_ready_count = sum(event["zoning_map"]["ready"] for event in events)
    point_ready_count = sum(event["point_address"]["ready"] for event in events)
    tract_ready_count = sum(event["tract_crosswalk"]["ready"] for event in events)
    parcel_ready_count = sum(
        event["current_parcel_crosswalk"]["ready"] for event in events
    )
    parcel_augmented_ready_count = sum(
        event["spatial_consistency"]["ready"]
        and event["current_parcel_crosswalk"]["ready"]
        for event in events
    )
    joint_spatial_ready_count = sum(
        event["spatial_consistency"]["ready"] for event in events
    )
    point_polygon_mismatch_records = sorted(
        event["record_number"]
        for event in events
        if event["spatial_consistency"]["point_and_zoning_individually_ready"]
        and not event["spatial_consistency"]["point_inside_event_zoning_polygon"]
    )
    missing_zoning_records = sorted(
        event["record_number"]
        for event in events
        if not event["zoning_map"]["ready"]
    )
    unmatched_records = sorted(
        event["record_number"]
        for event in events
        if not event["point_address"]["ready"]
    )
    tract_geoids = sorted(
        {
            event["tract_crosswalk"]["tract_geoid"]
            for event in events
            if event["tract_crosswalk"]["ready"]
        }
    )
    artifact_paths = [
        cohort_path,
        zoning_path,
        geocoder_request_path,
        geocoder_response_path,
        parcel_path,
        PARCEL_METADATA_INPUT,
        *(EVIDENCE_DIR / filename for filename in RETRY_FILES.values()),
        *(EVIDENCE_DIR / filename for filename in POINT_CONTEXT_FILES.values()),
        *(
            EVIDENCE_DIR / _fcc_filename(event["record_number"])
            for event in events
            if event["tract_crosswalk"]["ready"]
        ),
    ]
    payload = {
        "schema": "gwm.chicago_historical_zoning_spatial_crosswalk.v1",
        "cohort_id": cohort.get("cohort_id"),
        "cohort_digest": cohort.get("cohort_digest"),
        "observed_on": "2026-07-24",
        "source_roles": {
            "event_metadata": "Chicago eLMS",
            "point_addresses": "City of Chicago AddressPoints GeocodeServer",
            "zoning_map": "City of Chicago Zoning FeatureServer",
            "block_to_tract": "FCC Census Block API, 2020 vintage",
        },
        "summary": {
            "cohort_event_count": len(events),
            "zoning_map_ready_count": zoning_ready_count,
            "missing_zoning_map_count": len(missing_zoning_records),
            "missing_zoning_map_records": missing_zoning_records,
            "point_address_ready_count": point_ready_count,
            "tract_crosswalk_ready_count": tract_ready_count,
            "current_parcel_crosswalk_ready_count": parcel_ready_count,
            "joint_spatial_crosswalk_ready_count": joint_spatial_ready_count,
            "parcel_augmented_spatial_crosswalk_ready_count": (
                parcel_augmented_ready_count
            ),
            "point_polygon_mismatch_count": len(point_polygon_mismatch_records),
            "point_polygon_mismatch_records": point_polygon_mismatch_records,
            "unmatched_point_address_count": len(unmatched_records),
            "unmatched_point_address_records": unmatched_records,
            "distinct_ready_tract_count": len(tract_geoids),
            "ready_tract_geoids": tract_geoids,
        },
        "events": events,
        "artifacts": {
            path.name: _artifact(path) for path in sorted(set(artifact_paths))
        },
        "readiness": {
            "metadata_cohort_preregistered": len(events) == 23,
            "zoning_map_crosswalk_complete": zoning_ready_count == len(events),
            "partial_zoning_map_crosswalk_available": zoning_ready_count > 0,
            "point_address_crosswalk_complete": point_ready_count == len(events),
            "tract_crosswalk_complete": tract_ready_count == len(events),
            "current_parcel_crosswalk_complete": (
                parcel_ready_count == len(events)
            ),
            "partial_current_parcel_crosswalk_available": (
                parcel_ready_count > 0
            ),
            "joint_spatial_crosswalk_complete": (
                joint_spatial_ready_count == len(events)
            ),
            "partial_joint_spatial_crosswalk_available": (
                joint_spatial_ready_count > 0
            ),
            "partial_point_and_tract_crosswalk_available": (
                point_ready_count == tract_ready_count and point_ready_count > 0
            ),
            "legal_treatment_geometry_ready": False,
            "effective_onset_ready": False,
            "outcome_panel_ready": False,
            "positivity_diagnostics_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "zoning_map_polygon_not_legal_parcel_polygon": True,
            "current_parcel_polygon_not_versioned_historical_geometry": True,
            "partial_crosswalk_not_complete_cohort_crosswalk": True,
            "independent_source_identity_not_spatial_coincidence": True,
            "crosswalk_not_longitudinal_outcome_panel": True,
            "cohort_size_not_positivity_evidence": True,
            "spatial_crosswalk_not_causal_identification": True,
        },
    }
    payload["crosswalk_digest"] = _canonical_digest(payload)
    return payload


def _build_event_crosswalk(
    *,
    event: Mapping[str, Any],
    zoning_features: list[Mapping[str, Any]],
    geocoder_location: Mapping[str, Any],
    parcel_by_pin: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    record_number = str(event.get("record_number") or "")
    address = str(event.get("address") or "")
    final_action = _parse_datetime(event.get("final_action_date"))
    zoning_parts = [_zoning_part(feature) for feature in zoning_features]
    zoning_parts = [part for part in zoning_parts if part is not None]
    zoning_checks = {
        "feature_present": bool(zoning_parts),
        "clerk_document_matches": bool(zoning_parts)
        and all(
            part["attributes"].get("CLERK_DOCNO") == record_number
            for part in zoning_parts
        ),
        "ordinance_date_matches_final_action": bool(zoning_parts)
        and final_action is not None
        and all(
            part["ordinance_date"] is not None
            and part["ordinance_date"].date() == final_action.date()
            for part in zoning_parts
        ),
        "polygon_present": bool(zoning_parts)
        and all(len(part["outer_ring"]) >= 4 for part in zoning_parts),
        "positive_shape_area": bool(zoning_parts)
        and all(
            float(part["attributes"].get("Shape__Area") or 0) > 0
            for part in zoning_parts
        ),
    }

    geocoder_attributes = geocoder_location.get("attributes")
    geocoder_attributes = (
        geocoder_attributes
        if isinstance(geocoder_attributes, Mapping)
        else {}
    )
    location = geocoder_location.get("location")
    location = location if isinstance(location, Mapping) else {}
    matched_address = str(geocoder_location.get("address") or "")
    point_checks = {
        "matched_status": geocoder_attributes.get("Status") == "M",
        "score_100": geocoder_location.get("score") == 100,
        "point_address_type": (
            geocoder_attributes.get("Addr_type") == "PointAddress"
        ),
        "exact_street_address": _normalized_address_prefix(matched_address)
        == address.upper(),
        "pin10_present": bool(
            re.fullmatch(r"[0-9]{10}", str(geocoder_attributes.get("PINNO") or ""))
        ),
        "wgs84_location_present": (
            isinstance(location.get("x"), (int, float))
            and isinstance(location.get("y"), (int, float))
            and -180 <= float(location["x"]) <= 180
            and -90 <= float(location["y"]) <= 90
        ),
    }
    point_ready = all(point_checks.values())
    point_epsg_3435 = (
        float(geocoder_attributes.get("X") or 0),
        float(geocoder_attributes.get("Y") or 0),
    )
    point_inside_zoning = bool(
        point_ready
        and any(
            _point_in_polygon(point_epsg_3435, part["outer_ring"])
            for part in zoning_parts
        )
    )

    fcc_path = EVIDENCE_DIR / _fcc_filename(record_number)
    fcc = _read_json(fcc_path) if point_ready and fcc_path.is_file() else {}
    block = fcc.get("Block")
    block = block if isinstance(block, Mapping) else {}
    block_fips = str(block.get("FIPS") or "")
    tract_geoid = block_fips[:11] if len(block_fips) == 15 else ""
    tract_checks = {
        "point_address_ready": point_ready,
        "fcc_status_ok": fcc.get("status") == "OK",
        "block_fips_15_digits": bool(re.fullmatch(r"[0-9]{15}", block_fips)),
        "tract_geoid_11_digits": bool(re.fullmatch(r"[0-9]{11}", tract_geoid)),
    }
    tract_ready = all(tract_checks.values())
    pin10 = str(geocoder_attributes.get("PINNO") or "") if point_ready else ""
    parcel_features = parcel_by_pin.get(pin10, [])
    parcel_parts = [_polygon_part(feature) for feature in parcel_features]
    parcel_parts = [part for part in parcel_parts if part is not None]
    parcel_point_inside = bool(
        point_ready
        and any(
            _point_in_polygon(point_epsg_3435, part["outer_ring"])
            for part in parcel_parts
        )
    )
    parcel_checks = {
        "point_address_ready": point_ready,
        "single_pin_feature": len(parcel_parts) == 1,
        "pin10_matches": bool(parcel_parts)
        and all(
            str(part["attributes"].get("PIN10") or "") == pin10
            for part in parcel_parts
        ),
        "polygon_present": bool(parcel_parts)
        and all(len(part["outer_ring"]) >= 4 for part in parcel_parts),
        "point_inside_parcel": parcel_point_inside,
    }
    parcel_ready = all(parcel_checks.values())
    parcel_area = (
        sum(
            float(part["attributes"].get("SHAPE.AREA") or 0)
            for part in parcel_parts
        )
        if parcel_parts
        else None
    )
    legal_lot_area = LEGAL_LOT_AREAS.get(record_number)
    parcel_legal_area_ratio = (
        round(parcel_area / legal_lot_area, 6)
        if parcel_area is not None and legal_lot_area is not None
        else None
    )
    point_context = _point_context_observation(record_number)
    point_and_zoning_ready = point_ready and all(zoning_checks.values())
    spatial_consistency_ready = bool(
        point_and_zoning_ready and tract_ready and point_inside_zoning
    )

    retry = _retry_observation(record_number, address)
    return {
        "record_number": record_number,
        "address": address,
        "application_number": event.get("application_number"),
        "final_action_date": event.get("final_action_date"),
        "last_publication_date": event.get("last_publication_date"),
        "zoning_map": {
            "ready": all(zoning_checks.values()),
            "checks": zoning_checks,
            "feature_count": len(zoning_parts),
            "object_ids": [
                part["attributes"].get("OBJECTID") for part in zoning_parts
            ],
            "zone_classes": sorted(
                {
                    str(part["attributes"].get("ZONE_CLASS") or "")
                    for part in zoning_parts
                }
            ),
            "ordinance_numbers": sorted(
                {
                    str(part["attributes"].get("ORDINANCE_NUM") or "")
                    for part in zoning_parts
                }
            ),
            "ordinance_date_epoch_ms": sorted(
                {
                    part["attributes"].get("ORDINANCE_DATE")
                    for part in zoning_parts
                    if part["attributes"].get("ORDINANCE_DATE") is not None
                }
            ),
            "shape_area_square_feet": sum(
                float(part["attributes"].get("Shape__Area") or 0)
                for part in zoning_parts
            ),
            "ring_count": sum(len(part["rings"]) for part in zoning_parts),
            "vertex_count": sum(
                len(part["outer_ring"]) for part in zoning_parts
            ),
            "point_address_inside_polygon": point_inside_zoning,
            "machine_legal_parcel_polygon_verified": False,
        },
        "point_address": {
            "ready": point_ready,
            "checks": point_checks,
            "matched_address": matched_address or None,
            "score": geocoder_location.get("score"),
            "pin10": (
                str(geocoder_attributes.get("PINNO")) if point_ready else None
            ),
            "ward": geocoder_attributes.get("WARD") if point_ready else None,
            "community": (
                geocoder_attributes.get("COMMUNITY") if point_ready else None
            ),
            "point_wgs84": (
                [location.get("x"), location.get("y")] if point_ready else None
            ),
            "point_epsg_3435": (
                list(point_epsg_3435) if point_ready else None
            ),
            "retry_observation": retry,
        },
        "tract_crosswalk": {
            "ready": tract_ready,
            "checks": tract_checks,
            "block_fips_2020": block_fips or None,
            "tract_geoid": tract_geoid or None,
        },
        "current_parcel_crosswalk": {
            "ready": parcel_ready,
            "checks": parcel_checks,
            "feature_count": len(parcel_parts),
            "object_ids": [
                part["attributes"].get("OBJECTID") for part in parcel_parts
            ],
            "pin14": (
                parcel_parts[0]["attributes"].get("PIN14")
                if len(parcel_parts) == 1
                else None
            ),
            "shape_area_square_feet": parcel_area,
            "legal_lot_area_square_feet": legal_lot_area,
            "area_ratio_to_legal_lot": parcel_legal_area_ratio,
            "area_within_one_percent_of_legal_lot": (
                0.99 <= parcel_legal_area_ratio <= 1.01
                if parcel_legal_area_ratio is not None
                else None
            ),
            "historical_vintage_verified": False,
            "machine_legal_treatment_polygon_verified": False,
        },
        "spatial_consistency": {
            "ready": spatial_consistency_ready,
            "point_and_zoning_individually_ready": point_and_zoning_ready,
            "point_inside_event_zoning_polygon": point_inside_zoning,
            "point_context_observation": point_context,
        },
    }


def _zoning_part(feature: Mapping[str, Any]) -> dict[str, Any] | None:
    attributes = feature.get("attributes")
    geometry = feature.get("geometry")
    if not isinstance(attributes, Mapping) or not isinstance(geometry, Mapping):
        return None
    rings = geometry.get("rings")
    rings = rings if isinstance(rings, list) else []
    outer_ring = rings[0] if rings and isinstance(rings[0], list) else []
    return {
        "attributes": attributes,
        "rings": rings,
        "outer_ring": outer_ring,
        "ordinance_date": _epoch_ms_datetime(attributes.get("ORDINANCE_DATE")),
    }


def _polygon_part(feature: Mapping[str, Any]) -> dict[str, Any] | None:
    attributes = feature.get("attributes")
    geometry = feature.get("geometry")
    if not isinstance(attributes, Mapping) or not isinstance(geometry, Mapping):
        return None
    rings = geometry.get("rings")
    rings = rings if isinstance(rings, list) else []
    return {
        "attributes": attributes,
        "rings": rings,
        "outer_ring": (
            rings[0] if rings and isinstance(rings[0], list) else []
        ),
    }


def _retry_observation(record_number: str, expected_address: str) -> dict[str, Any] | None:
    filename = RETRY_FILES.get(record_number)
    if filename is None:
        return None
    payload = _read_json(EVIDENCE_DIR / filename)
    candidates = payload.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    exact_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and _normalized_address_prefix(str(candidate.get("address") or ""))
        == expected_address.upper()
        and candidate.get("score") == 100
    ]
    return {
        "artifact": filename,
        "candidate_count": len(candidates),
        "exact_candidate_count": len(exact_candidates),
        "exact_point_address_recovered": bool(exact_candidates),
        "top_candidate_address": (
            candidates[0].get("address")
            if candidates and isinstance(candidates[0], Mapping)
            else None
        ),
        "top_candidate_score": (
            candidates[0].get("score")
            if candidates and isinstance(candidates[0], Mapping)
            else None
        ),
    }


def _point_context_observation(record_number: str) -> dict[str, Any] | None:
    filename = POINT_CONTEXT_FILES.get(record_number)
    if filename is None:
        return None
    payload = _read_json(EVIDENCE_DIR / filename)
    features = payload.get("features")
    features = features if isinstance(features, list) else []
    attributes = (
        features[0].get("attributes")
        if features and isinstance(features[0], Mapping)
        else {}
    )
    attributes = attributes if isinstance(attributes, Mapping) else {}
    return {
        "artifact": filename,
        "feature_count": len(features),
        "zone_class": attributes.get("ZONE_CLASS"),
        "clerk_document_number": attributes.get("CLERK_DOCNO"),
        "ordinance_number": attributes.get("ORDINANCE_NUM"),
    }


def _normalized_address_prefix(address: str) -> str:
    return address.split(",", 1)[0].strip().upper()


def _fcc_filename(record_number: str) -> str:
    return f"fcc_census_block_{record_number.replace('-', '_')}.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _epoch_ms_datetime(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)


def _point_in_polygon(point: tuple[float, float], ring: list[Any]) -> bool:
    if len(ring) < 4:
        return False
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        if not (
            isinstance(previous, list)
            and len(previous) >= 2
            and isinstance(current, list)
            and len(current) >= 2
        ):
            return False
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT_INPUT)
    parser.add_argument("--zoning", type=Path, default=DEFAULT_ZONING_INPUT)
    parser.add_argument(
        "--geocoder-request",
        type=Path,
        default=DEFAULT_GEOCODER_REQUEST_INPUT,
    )
    parser.add_argument(
        "--geocoder-response",
        type=Path,
        default=DEFAULT_GEOCODER_RESPONSE_INPUT,
    )
    parser.add_argument("--parcels", type=Path, default=DEFAULT_PARCEL_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    crosswalk = build_historical_zoning_crosswalk(
        cohort_path=args.cohort,
        zoning_path=args.zoning,
        geocoder_request_path=args.geocoder_request,
        geocoder_response_path=args.geocoder_response,
        parcel_path=args.parcels,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(crosswalk, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0 if crosswalk["summary"]["cohort_event_count"] == 23 else 1


if __name__ == "__main__":
    raise SystemExit(main())
