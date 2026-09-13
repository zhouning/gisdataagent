#!/usr/bin/env python3
"""Adjudicate PIN parcels and facility context for unresolved Chicago permits."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from shapely import STRtree
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_gwm_chicago_permit_tract_month_panel import (  # noqa: E402
    DEFAULT_MISSING_COORDINATE_SUPPLEMENT,
    DEFAULT_SPATIAL_MISSINGNESS_DIAGNOSTIC,
    DEFAULT_TRACT_SHAPEFILE,
    DEFAULT_UNRESOLVED_GEOCODER_RESPONSE,
    _canonical_digest,
    _load_illinois_tracts,
    _unique_point_geoid,
)


EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_PARCEL_RESPONSE = (
    EVIDENCE_DIR / "chicago_building_permits_unresolved_pin_parcel_response.json"
)
DEFAULT_PARCEL_HEADERS = (
    EVIDENCE_DIR / "chicago_building_permits_unresolved_pin_parcel_response.headers"
)
DEFAULT_AIRPORT_METADATA = EVIDENCE_DIR / "chicago_official_airports_layer31_metadata.json"
DEFAULT_AIRPORT_FEATURES = (
    EVIDENCE_DIR / "chicago_official_airports_layer31_all_features.json"
)
DEFAULT_OUTPUT = (
    EVIDENCE_DIR / "chicago_building_permits_remaining_spatial_adjudication.json"
)


def adjudicate_remaining_permit_spatial_evidence() -> dict[str, Any]:
    """Return fail-closed PIN and facility-level spatial adjudication."""

    diagnostic = _read_json(DEFAULT_SPATIAL_MISSINGNESS_DIAGNOSTIC)
    diagnostic_without_digest = dict(diagnostic)
    diagnostic_digest = diagnostic_without_digest.pop("diagnostic_digest", None)
    if diagnostic_digest != _canonical_digest(diagnostic_without_digest):
        raise ValueError("spatial_missingness_diagnostic_digest_mismatch")
    geocoder = _read_json(DEFAULT_UNRESOLVED_GEOCODER_RESPONSE)
    supplement_rows = _read_json_list(DEFAULT_MISSING_COORDINATE_SUPPLEMENT)
    supplement = {str(row["id"]): row for row in supplement_rows}

    exact_object_ids = {
        int(location.get("attributes", {}).get("ResultID") or 0)
        for location in geocoder.get("locations", [])
        if isinstance(location, Mapping)
        and location.get("score") == 100
        and location.get("attributes", {}).get("Addr_type") == "PointAddress"
    }
    all_manifest_ids = {
        str(row_id)
        for item in diagnostic.get("address_manifest", [])
        if isinstance(item, Mapping)
        for row_id in item.get("permit_ids", [])
    }
    exact_row_ids = {
        str(row_id)
        for item in diagnostic.get("address_manifest", [])
        if isinstance(item, Mapping)
        and int(item.get("object_id") or 0) in exact_object_ids
        for row_id in item.get("permit_ids", [])
    }
    remaining_ids = all_manifest_ids - exact_row_ids
    if len(remaining_ids) != 72:
        raise ValueError(f"remaining_row_count_mismatch:{len(remaining_ids)}")

    pin_rows = []
    requested_pins: set[str] = set()
    for row_id in sorted(remaining_ids):
        row = supplement[row_id]
        pins = [
            value.strip()
            for value in str(row.get("pin_list") or "").split("|")
            if value.strip()
        ]
        if not pins:
            continue
        requested_pins.update(pins)
        pin_rows.append(
            {
                "id": row_id,
                "permit_": str(row["permit_"]),
                "address": _permit_address(row),
                "street_number": int(float(row["street_number"])),
                "street_direction": str(row.get("street_direction") or "").strip(),
                "street_name": str(row.get("street_name") or "").strip(),
                "pins": pins,
            }
        )
    if len(pin_rows) != 14 or len(requested_pins) != 14:
        raise ValueError("remaining_pin_request_scope_mismatch")

    headers = DEFAULT_PARCEL_HEADERS.read_text(encoding="utf-8")
    if not any(line.startswith("HTTP/") and " 200" in line for line in headers.splitlines()):
        raise ValueError("parcel_response_http_status_not_200")
    parcel_response = _read_json(DEFAULT_PARCEL_RESPONSE)
    if (
        parcel_response.get("geometryType") != "esriGeometryPolygon"
        or parcel_response.get("spatialReference", {}).get("wkid") != 4326
    ):
        raise ValueError("parcel_response_spatial_contract_mismatch")
    parcel_features = parcel_response.get("features")
    parcel_features = parcel_features if isinstance(parcel_features, list) else []
    parcel_by_pin: dict[str, Mapping[str, Any]] = {}
    for feature in parcel_features:
        if not isinstance(feature, Mapping):
            raise ValueError("parcel_feature_invalid")
        attributes = feature.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        pin = str(attributes.get("PIN10") or "")
        if not pin or pin in parcel_by_pin or pin not in requested_pins:
            raise ValueError(f"parcel_pin_invalid_or_duplicate:{pin}")
        geometry = _arcgis_polygon(feature.get("geometry"))
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"parcel_geometry_invalid:{pin}")
        parcel_by_pin[pin] = feature
    if len(parcel_by_pin) != 11:
        raise ValueError(f"parcel_feature_count_mismatch:{len(parcel_by_pin)}")

    tract_geoids, tract_geometries, _ = _load_illinois_tracts(
        DEFAULT_TRACT_SHAPEFILE
    )
    tract_tree = STRtree(tract_geometries)
    parcel_tracts = {}
    for pin, feature in parcel_by_pin.items():
        parcel = _arcgis_polygon(feature["geometry"])
        geoid = _unique_point_geoid(
            point=parcel.representative_point(),
            tree=tract_tree,
            tract_geoids=tract_geoids,
        )
        if geoid is None:
            raise ValueError(f"parcel_representative_point_not_unique_tract:{pin}")
        parcel_tracts[pin] = geoid

    row_adjudications = []
    address_consistent_count = 0
    for row in pin_rows:
        candidates = []
        for pin in row["pins"]:
            feature = parcel_by_pin.get(pin)
            attributes = feature.get("attributes", {}) if feature else {}
            address_consistent = bool(
                feature
                and int(attributes.get("L_ADDR"))
                <= row["street_number"]
                <= int(attributes.get("H_ADDR"))
                and row["street_direction"]
                == str(attributes.get("PRE_DIR") or "").strip()
                and row["street_name"].upper()
                == _parcel_street(attributes).upper()
            )
            address_consistent_count += int(address_consistent)
            candidates.append(
                {
                    "pin10": pin,
                    "parcel_returned": feature is not None,
                    "parcel_address": _parcel_address(attributes) if feature else None,
                    "address_consistent": address_consistent,
                    "tract_geoid": parcel_tracts.get(pin),
                }
            )
        row_adjudications.append(
            {
                "id": row["id"],
                "permit_": row["permit_"],
                "permit_address": row["address"],
                "pin_candidate_count": len(row["pins"]),
                "candidates": candidates,
                "pin_spatial_assignment_admitted": False,
                "reason": (
                    "multiple_pin_candidates"
                    if len(row["pins"]) != 1
                    else "parcel_not_returned"
                    if not candidates[0]["parcel_returned"]
                    else "permit_address_not_consistent_with_current_parcel_address"
                ),
            }
        )
    if address_consistent_count != 0:
        raise ValueError("unexpected_address_consistent_pin_candidate")

    airport_metadata = _read_json(DEFAULT_AIRPORT_METADATA)
    airport_response = _read_json(DEFAULT_AIRPORT_FEATURES)
    airport_features = airport_response.get("features")
    airport_features = airport_features if isinstance(airport_features, list) else []
    if (
        airport_metadata.get("name") != "Airports"
        or airport_metadata.get("geometryType") != "esriGeometryPoint"
        or airport_response.get("spatialReference", {}).get("wkid") != 4326
        or len(airport_features) != 2
    ):
        raise ValueError("official_airport_layer_contract_mismatch")
    ohare_matches = [
        feature
        for feature in airport_features
        if feature.get("attributes", {}).get("RENDERNAME") == "O'Hare Airport"
    ]
    if len(ohare_matches) != 1:
        raise ValueError("official_ohare_point_match_count_mismatch")
    ohare = ohare_matches[0]
    ohare_geoid = _unique_point_geoid(
        point=Point(ohare["geometry"]["x"], ohare["geometry"]["y"]),
        tree=tract_tree,
        tract_geoids=tract_geoids,
    )
    if ohare_geoid is None:
        raise ValueError("official_ohare_point_not_unique_tract")
    ohare_rows = [
        row_id
        for row_id in remaining_ids
        if _permit_address(supplement[row_id]) == "10000 N BESSIE COLEMAN DR"
    ]
    if len(ohare_rows) != 26:
        raise ValueError(f"ohare_facility_row_count_mismatch:{len(ohare_rows)}")

    result = {
        "schema": "gwm.chicago_remaining_permit_spatial_adjudication.v1",
        "observed_on": "2026-07-24",
        "remaining_unresolved_row_count": len(remaining_ids),
        "pin_parcel_adjudication": {
            "endpoint": (
                "https://gisapps.chicago.gov/arcgis/rest/services/ExternalApps/"
                "operational/MapServer/1/query"
            ),
            "layer_name": "Parcel Addresses",
            "requested_unique_pin_count": len(requested_pins),
            "pin_bearing_row_count": len(pin_rows),
            "returned_unique_pin_polygon_count": len(parcel_by_pin),
            "missing_pin_count": len(requested_pins - set(parcel_by_pin)),
            "multi_pin_row_count": sum(len(row["pins"]) != 1 for row in pin_rows),
            "unique_parcel_to_tract_count": len(parcel_tracts),
            "address_consistent_row_count": address_consistent_count,
            "admitted_row_count": 0,
            "rows": row_adjudications,
        },
        "facility_context": {
            "facility_id": "chicago_ohare_airport",
            "official_name": "O'Hare Airport",
            "source_geometry_type": "point",
            "official_point_wgs84": [
                ohare["geometry"]["x"],
                ohare["geometry"]["y"],
            ],
            "official_point_tract_geoid": ohare_geoid,
            "shared_permit_address": "10000 N BESSIE COLEMAN DR",
            "context_row_count": len(ohare_rows),
            "context_permit_ids": sorted(ohare_rows),
            "facility_context_ready": True,
            "permit_tract_assignment_admitted": False,
            "reason": (
                "official_airport_layer_is_a_facility_point_not_a_project_or_"
                "facility_polygon_and_cannot_locate_each_permit_within_ohare"
            ),
        },
        "remaining_missingness": {
            "permit_type_counts": dict(
                sorted(
                    Counter(
                        str(supplement[row_id].get("permit_type"))
                        for row_id in remaining_ids
                    ).items()
                )
            ),
            "express_program_row_count": sum(
                "EXPRESS PERMIT PROGRAM"
                in str(supplement[row_id].get("permit_type"))
                for row_id in remaining_ids
            ),
            "missingness_assumed_random": False,
        },
        "artifacts": {
            "parcel_response": _artifact(DEFAULT_PARCEL_RESPONSE),
            "parcel_response_headers": _artifact(DEFAULT_PARCEL_HEADERS),
            "airport_layer_metadata": _artifact(DEFAULT_AIRPORT_METADATA),
            "airport_features": _artifact(DEFAULT_AIRPORT_FEATURES),
        },
        "readiness": {
            "pin_parcel_response_ready": True,
            "pin_spatial_recovery_ready": False,
            "facility_context_ready": True,
            "facility_level_permit_tract_assignment_ready": False,
            "complete_spatial_assignment_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "pin_not_project_location_without_address_consistency": True,
            "current_parcel_not_historical_vintage": True,
            "facility_point_not_facility_polygon": True,
            "facility_point_not_permit_location": True,
            "facility_context_not_tract_assignment": True,
            "negative_recovery_result_preserved": True,
            "gwm_k0_validated": False,
        },
    }
    result["adjudication_digest"] = _canonical_digest(result)
    return result


def _permit_address(row: Mapping[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for value in (
            row.get("street_number"),
            row.get("street_direction"),
            row.get("street_name"),
        )
        if value not in (None, "")
    )


def _arcgis_polygon(value: Any) -> Any:
    geometry = value if isinstance(value, Mapping) else {}
    rings = geometry.get("rings")
    rings = rings if isinstance(rings, list) else []
    polygons = [
        Polygon(ring)
        for ring in rings
        if isinstance(ring, list) and len(ring) >= 4
    ]
    if not polygons:
        raise ValueError("arcgis_polygon_rings_missing")
    return unary_union(polygons)


def _parcel_street(attributes: Mapping[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for value in (attributes.get("ST_NAME"), attributes.get("ST_TYPE"))
        if value not in (None, "")
    )


def _parcel_address(attributes: Mapping[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for value in (
            (
                f"{attributes.get('L_ADDR')}-{attributes.get('H_ADDR')}"
                if attributes.get("L_ADDR") is not None
                else None
            ),
            attributes.get("PRE_DIR"),
            attributes.get("ST_NAME"),
            attributes.get("ST_TYPE"),
            attributes.get("SUF_DIR"),
        )
        if value not in (None, "") and str(value).strip()
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"json_list_required:{path}")
    return payload


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = adjudicate_remaining_permit_spatial_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(result["adjudication_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
