"""Fulu real-data adapter for parcel-scale S2 world-model inputs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import shape
from shapely.strtree import STRtree

from data_agent.uwm.traditional_livability_s6_fulu_adapter import (
    build_fulu_s6_resources,
)


SCHEMA = "uwm.livability_s2.fulu_inputs.v1"


def build_fulu_s2_inputs(
    *, source_root: Path, facility_product: Mapping[str, Any]
) -> dict[str, Any]:
    """Build current-parcel states and preserve the complete S6 evidence inventory."""

    s6 = build_fulu_s6_resources(
        source_root=Path(source_root), facility_product=facility_product
    )
    blockers = list((s6.get("source_manifest") or {}).get("blockers") or [])
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ready": False,
        "scope": "fulu_heping_and_banzhu_real_planning_parcels",
        "source_manifest": deepcopy(s6.get("source_manifest") or {}),
        "planning_areas": deepcopy(s6.get("planning_areas") or []),
        "planning_resources": deepcopy(s6.get("planning_resources") or []),
        "current_facilities": deepcopy(s6.get("current_facilities") or []),
        "facility_inventory": deepcopy(s6.get("facility_inventory") or {}),
        "parcels": [],
        "blockers": blockers,
        "synthetic_parcels_created": False,
    }
    if not s6.get("ready"):
        payload["content_digest"] = compute_fulu_s2_content_digest(payload)
        return payload

    resources = list(payload["planning_resources"])
    current_rows = [row for row in resources if row.get("source_layer") == "JQDLTB"]
    planned_rows = [row for row in resources if row.get("source_layer") == "TDGHDL"]
    current_geometries = _geometry_cache(current_rows)
    planned_geometries = _geometry_cache(planned_rows)
    planned_indexes = _planned_spatial_indexes(planned_rows, planned_geometries)
    for current in current_rows:
        parcel = _parcel_from_current_resource(
            current,
            current_geometry=current_geometries.get(str(current.get("resource_id"))),
            planned_index=planned_indexes.get(str(current.get("planning_area_id"))),
            planned_geometries=planned_geometries,
        )
        if parcel is not None:
            payload["parcels"].append(parcel)
    payload["parcels"].sort(key=lambda row: row["parcel_id"])
    if not payload["parcels"]:
        payload["blockers"].append("no_valid_current_parcels")
    payload["ready"] = not payload["blockers"] and bool(payload["parcels"])
    payload["content_digest"] = compute_fulu_s2_content_digest(payload)
    return payload


def _parcel_from_current_resource(
    current: Mapping[str, Any],
    *,
    current_geometry: Any,
    planned_index: tuple[STRtree, list[dict[str, Any]]] | None,
    planned_geometries: Mapping[str, Any],
) -> dict[str, Any] | None:
    if current_geometry is None:
        return None
    geometry = current_geometry
    if geometry.is_empty or not geometry.is_valid:
        return None
    overlaps: list[dict[str, Any]] = []
    for planned in _query_rows(planned_index, geometry):
        planned_geometry = planned_geometries[str(planned["resource_id"])]
        intersection = geometry.intersection(planned_geometry)
        if intersection.is_empty or intersection.area <= 0.0:
            continue
        overlaps.append(
            {
                "resource_id": planned.get("resource_id"),
                "resource_domain": planned.get("resource_domain") or "unresolved",
                "raw_land_use_code": planned.get("raw_land_use_code"),
                "raw_land_use_name": planned.get("raw_land_use_name"),
                "intersection_area_m2": round(float(intersection.area), 6),
                "current_parcel_overlap_ratio": round(
                    float(intersection.area / geometry.area), 9
                )
                if geometry.area > 0.0
                else 0.0,
                "planning_status": planned.get("planning_status"),
            }
        )
    overlaps.sort(
        key=lambda row: (-row["intersection_area_m2"], str(row["resource_id"]))
    )
    planned_class, planned_status = _planned_class(overlaps)
    current_resource_id = str(current.get("resource_id"))
    return {
        "parcel_id": _stable_id("parcel", current_resource_id),
        "planning_area_id": current.get("planning_area_id"),
        "source_layer": "JQDLTB",
        "current_resource_id": current_resource_id,
        "source_record_id": current.get("source_record_id"),
        "source_land_use_code": current.get("raw_land_use_code"),
        "source_land_use_name": current.get("raw_land_use_name"),
        "current_land_use_class": current.get("resource_domain") or "unresolved",
        "planned_land_use_class": planned_class,
        "planned_land_use_status": planned_status,
        "candidate_land_use_class": None,
        "distance_crs": current.get("distance_crs"),
        "area_m2": current.get("area_m2"),
        "metric_geometry": deepcopy(current.get("metric_geometry")),
        "display_geometry_wgs84": deepcopy(current.get("display_geometry_wgs84")),
        "planned_overlap_count": len(overlaps),
        "planned_overlap_evidence": overlaps,
        "evidence_refs": [
            f"planning_resource:{current_resource_id}",
            *[f"planning_resource:{row['resource_id']}" for row in overlaps],
        ],
        "observability": "observed",
    }


def _planned_class(overlaps: list[dict[str, Any]]) -> tuple[str, str]:
    if not overlaps:
        return "unavailable", "no_planned_overlap"
    largest = overlaps[0]["intersection_area_m2"]
    leaders = [row for row in overlaps if row["intersection_area_m2"] == largest]
    domains = {str(row.get("resource_domain") or "unresolved") for row in leaders}
    if len(domains) != 1 or "unresolved" in domains:
        return "unresolved", "largest_overlap_unresolved_or_tied"
    return next(iter(domains)), "largest_overlap_proxy"


def _geometry_cache(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(row["resource_id"]): shape(row["metric_geometry"])
        for row in rows
        if row.get("resource_id") and row.get("metric_geometry")
    }


def _planned_spatial_indexes(
    rows: list[dict[str, Any]], geometries: Mapping[str, Any]
) -> dict[str, tuple[STRtree, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        resource_id = str(row.get("resource_id") or "")
        area_id = str(row.get("planning_area_id") or "")
        if resource_id in geometries and area_id:
            grouped.setdefault(area_id, []).append(row)
    result: dict[str, tuple[STRtree, list[dict[str, Any]]]] = {}
    for area_id, area_rows in grouped.items():
        ordered = sorted(area_rows, key=lambda row: str(row["resource_id"]))
        result[area_id] = (
            STRtree([geometries[str(row["resource_id"])] for row in ordered]),
            ordered,
        )
    return result


def _query_rows(
    index: tuple[STRtree, list[dict[str, Any]]] | None, geometry: Any
) -> list[dict[str, Any]]:
    if index is None:
        return []
    tree, rows = index
    return [rows[int(position)] for position in tree.query(geometry)]


def compute_fulu_s2_content_digest(payload: Mapping[str, Any]) -> str:
    content = {
        "schema": payload.get("schema"),
        "scope": payload.get("scope"),
        "ready": payload.get("ready"),
        "parcels": payload.get("parcels") or [],
        "planning_resources": sorted(
            [_stable_digest_row(row) for row in payload.get("planning_resources") or []],
            key=lambda row: str(row.get("resource_id")),
        ),
        "current_facilities": sorted(
            deepcopy(payload.get("current_facilities") or []),
            key=lambda row: str(row.get("facility_id")),
        ),
        "facility_inventory": deepcopy(payload.get("facility_inventory") or {}),
        "blockers": sorted(str(value) for value in payload.get("blockers") or []),
        "synthetic_parcels_created": False,
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_digest_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in row.items()
        if key not in {"source_row_index", "source_row_number"}
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:20]}"
