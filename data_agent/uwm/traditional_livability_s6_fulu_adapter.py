from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import unicodedata

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union


SCHEMA = "uwm.traditional_livability.s6_fulu_resources.v1"

_HEPING_ROOT = (
    "07规划编制相关数据/村规划/璧山区福禄镇和平村规划成果/"
    "00璧山区福禄镇和平村规划最终成果0831/3规划数据库/3规划数据库"
)
_BANZHU_ROOT = "07规划编制相关数据/村规划/璧山区福禄镇斑竹村土地利用规划成果汇交/3规划数据库"

ASSET_SPECS = (
    {"area_id": "fulu_heping", "layer": "GHFW", "relative_path": f"{_HEPING_ROOT}/310基础要素/GHFW.shp", "required": True},
    {"area_id": "fulu_heping", "layer": "JQDLTB", "relative_path": f"{_HEPING_ROOT}/310基础要素/JQDLTB.shp", "required": True},
    {"area_id": "fulu_heping", "layer": "TDGHDL", "relative_path": f"{_HEPING_ROOT}/320规划要素/TDGHDL.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "GHFW", "relative_path": f"{_BANZHU_ROOT}/310基础要素/GHFW.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "JQDLTB", "relative_path": f"{_BANZHU_ROOT}/310基础要素/JQDLTB.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "TDGHDL", "relative_path": f"{_BANZHU_ROOT}/320规划要素/TDGHDL.shp", "required": True},
)

_STATUS_FIELDS = ("GHZT", "规划状态", "ZT", "STATUS", "status")
_STATUS_VALUES = {
    "current": {"current", "现状", "现有", "已建", "在用"},
    "planned": {"planned", "规划", "规划中", "拟建", "新建"},
    "reserved": {"reserved", "预留", "储备"},
}
_RESOURCE_DOMAINS_BY_CODE = {
    "2121": "village_residential_land",
    "2123": "village_public_service_land",
    "2124": "village_mixed_construction_land",
    "214": "village_independent_construction_land",
}
_RESOURCE_DOMAINS_BY_NAME = {
    "宅基地（村居住用地）": "village_residential_land",
    "村居住用地": "village_residential_land",
    "村公共服务用地": "village_public_service_land",
}
_FACILITY_FIELDS = (
    "source_dataset_id",
    "source_record_id",
    "name",
    "raw_primary_class",
    "raw_secondary_class",
    "raw_tertiary_class",
    "canonical_class",
    "mapping_status",
    "admin_code",
    "geometry_type",
)


def build_fulu_s6_resources(
    *, source_root: Path, facility_product: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(source_root)
    manifest = _inspect_sources(root)
    payload = {
        "schema": SCHEMA,
        "ready": False,
        "scope": "fulu_heping_and_banzhu_planning_samples_only",
        "source_manifest": manifest,
        "planning_areas": [],
        "planning_resources": [],
    }
    if not manifest["ready"]:
        return attach_facility_resources(payload, facility_product)

    specs = {(spec["area_id"], spec["layer"]): spec for spec in ASSET_SPECS}
    for area_id in ("fulu_heping", "fulu_banzhu"):
        boundary = _read_vector(root, specs[(area_id, "GHFW")])
        current_land = _read_vector(root, specs[(area_id, "JQDLTB")])
        planned_land = _read_vector(root, specs[(area_id, "TDGHDL")])
        area = _planning_area(area_id, boundary)
        if area is None:
            payload["source_manifest"]["blockers"].append(
                f"invalid_planning_boundary:{area_id}"
            )
            continue
        payload["planning_areas"].append(area)
        payload["planning_resources"].extend(
            _planning_resource_rows(area_id, "JQDLTB", current_land)
        )
        payload["planning_resources"].extend(
            _planning_resource_rows(area_id, "TDGHDL", planned_land)
        )

    payload["ready"] = not payload["source_manifest"]["blockers"]
    payload["source_manifest"]["ready"] = payload["ready"]
    return attach_facility_resources(payload, facility_product)


def attach_facility_resources(
    planning_inputs: Mapping[str, Any], facility_product: Mapping[str, Any]
) -> dict[str, Any]:
    payload = deepcopy(dict(planning_inputs))
    areas = list(payload.get("planning_areas") or [])
    mapping_version = facility_product.get("mapping_version")
    current_facilities: list[dict[str, Any]] = []
    for facility in facility_product.get("facilities") or []:
        geometry_wgs84 = _facility_geometry_wgs84(facility)
        if geometry_wgs84 is None:
            continue
        matching_areas = [
            area
            for area in areas
            if shape(area["display_geometry_wgs84"]).intersects(geometry_wgs84)
        ]
        if not matching_areas:
            continue
        matching_area_ids = sorted(
            area["planning_area_id"] for area in matching_areas
        )
        base = {
            "facility_id": _stable_id(
                "facility",
                facility.get("source_dataset_id"),
                facility.get("source_record_id"),
            ),
            **{field: facility.get(field) for field in _FACILITY_FIELDS},
            "mapping_version": mapping_version,
            "matching_planning_area_ids": matching_area_ids,
            "display_geometry_wgs84": mapping(geometry_wgs84),
        }
        if len(matching_areas) > 1:
            current_facilities.append(
                {
                    **base,
                    "association_status": "multi_area_overlap_unresolved",
                    "planning_area_id": None,
                    "distance_crs": None,
                    "metric_geometry": None,
                }
            )
            continue
        matching_area = matching_areas[0]
        metric_geometry = gpd.GeoSeries(
            [geometry_wgs84], crs="EPSG:4326"
        ).to_crs(matching_area["distance_crs"]).iloc[0]
        current_facilities.append(
            {
                **base,
                "association_status": "single_area_intersection",
                "planning_area_id": matching_area["planning_area_id"],
                "distance_crs": matching_area["distance_crs"],
                "metric_geometry": mapping(metric_geometry),
            }
        )

    source_manifest = deepcopy(dict(facility_product.get("source_manifest") or {}))
    payload["current_facilities"] = current_facilities
    payload["facility_inventory"] = {
        "product_id": facility_product.get("product_id"),
        "mapping_version": mapping_version,
        "complete_inventory": bool(source_manifest.get("complete_inventory")),
        "source_manifest": source_manifest,
        "facility_count": len(current_facilities),
        "mapped_facility_count": sum(
            row.get("mapping_status") == "mapped_internal_taxonomy"
            for row in current_facilities
        ),
        "unmapped_facility_count": sum(
            row.get("mapping_status") == "unmapped" for row in current_facilities
        ),
    }
    return payload


def _inspect_sources(root: Path) -> dict[str, Any]:
    blockers: list[str] = []
    sources: list[dict[str, Any]] = []
    for spec in ASSET_SPECS:
        path = root / spec["relative_path"]
        source = {
            "source_id": _source_id(spec["area_id"], spec["layer"]),
            "planning_area_id": spec["area_id"],
            "layer": spec["layer"],
            "relative_path": str(Path(spec["relative_path"])),
            "available": path.exists(),
        }
        if not path.exists():
            if spec.get("required"):
                blockers.append(
                    f"missing_required_source:{spec['area_id']}:{spec['layer']}"
                )
        else:
            info = pyogrio.read_info(path, force_feature_count=True)
            sha256, components = _source_hashes(path, root)
            source.update(
                sha256=sha256,
                feature_count=int(info.get("features") or 0),
                crs=str(info.get("crs") or ""),
                geometry_type=str(info.get("geometry_type") or ""),
                fields=_list_values(info.get("fields")),
            )
            if components is not None:
                source["components"] = components
        sources.append(source)
    return {"ready": not blockers, "sources": sources, "blockers": blockers}


def _read_vector(root: Path, spec: Mapping[str, Any]) -> gpd.GeoDataFrame:
    return pyogrio.read_dataframe(root / spec["relative_path"])


def _planning_area(
    area_id: str, frame: gpd.GeoDataFrame
) -> dict[str, Any] | None:
    geometries = [
        geometry
        for geometry in frame.geometry
        if geometry is not None and not geometry.is_empty and geometry.is_valid
    ]
    if not geometries or frame.crs is None:
        return None
    metric_geometry = unary_union(geometries)
    display_geometry = gpd.GeoSeries([metric_geometry], crs=frame.crs).to_crs(
        "EPSG:4326"
    ).iloc[0]
    return {
        "planning_area_id": area_id,
        "source_manifest_ref": _source_id(area_id, "GHFW"),
        "distance_crs": str(frame.crs),
        "metric_geometry": mapping(metric_geometry),
        "display_geometry_wgs84": mapping(display_geometry),
    }


def _planning_resource_rows(
    area_id: str, source_layer: str, frame: gpd.GeoDataFrame
) -> list[dict[str, Any]]:
    if frame.crs is None:
        return []
    candidates: list[dict[str, Any]] = []
    geometry_field = frame.geometry.name
    for row_number, (index, row) in enumerate(frame.iterrows()):
        geometry = row.geometry
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            continue
        code, name = _land_use(row, source_layer)
        if not code and not name:
            continue
        raw_tbbh = _text(row.get("TBBH")) or None
        raw_bsm = _text(row.get("BSM")) or None
        identity_field, identity_value = _source_identity(row)
        identity_normalized = _normalize_identity(identity_value)
        canonical_record_content = _canonical_record_content(
            row, geometry, geometry_field
        )
        source_record_digest = hashlib.sha256(
            canonical_record_content.encode("utf-8")
        ).hexdigest()
        planning_status, evidence = _planning_status(row)
        resource_domain, interpretation_rule, interpretation_evidence = (
            _interpret_land_use(code, name)
        )
        display_geometry = gpd.GeoSeries([geometry], crs=frame.crs).to_crs(
            "EPSG:4326"
        ).iloc[0]
        candidates.append(
            {
                "planning_area_id": area_id,
                "source_layer": source_layer,
                "source_manifest_ref": _source_id(area_id, source_layer),
                "source_identity_field": identity_field,
                "source_identity_value": identity_value,
                "source_identity_normalized": identity_normalized,
                "source_record_digest": source_record_digest,
                "source_row_index": str(index),
                "source_row_number": row_number,
                "raw_tbbh": raw_tbbh,
                "raw_bsm": raw_bsm,
                "raw_land_use_code": code or None,
                "raw_land_use_name": name or None,
                "resource_domain": resource_domain,
                "interpretation_rule": interpretation_rule,
                "interpretation_evidence": interpretation_evidence,
                "planning_status": planning_status,
                "planning_status_evidence": evidence,
                "distance_crs": str(frame.crs),
                "area_m2": _polygon_area_m2(geometry),
                "metric_geometry": mapping(geometry),
                "display_geometry_wgs84": mapping(display_geometry),
                "_canonical_record_content": canonical_record_content,
            }
        )
    candidates.sort(key=_canonical_candidate_sort_key)
    collision_counts = Counter(_source_collision_key(row) for row in candidates)
    collision_ordinals: Counter[tuple[str, str, str]] = Counter()
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        collision_key = _source_collision_key(candidate)
        duplicate_ordinal = None
        if collision_counts[collision_key] > 1:
            duplicate_ordinal = collision_ordinals[collision_key]
            collision_ordinals[collision_key] += 1
        source_record_id = _stable_id(
            "planning_source_record",
            area_id,
            source_layer,
            candidate["source_identity_field"],
            candidate["source_identity_normalized"],
            candidate["source_record_digest"],
            "" if duplicate_ordinal is None else f"duplicate:{duplicate_ordinal}",
        )
        candidate.pop("_canonical_record_content")
        rows.append(
            {
                "resource_id": _stable_id("planning_resource", source_record_id),
                "source_record_id": source_record_id,
                "source_duplicate_ordinal": duplicate_ordinal,
                **candidate,
            }
        )
    return rows


def _land_use(row: Any, source_layer: str) -> tuple[str, str]:
    if source_layer == "JQDLTB":
        return (
            _first_text(row, "DLDM", "JQDLDM"),
            _first_text(row, "DLMC", "JQDLMC"),
        )
    return (
        _first_text(row, "CGHDLDM", "GHDLDM"),
        _first_text(row, "CGHDLMC", "GHDLMC"),
    )


def _planning_status(row: Any) -> tuple[str, dict[str, str] | None]:
    for field in _STATUS_FIELDS:
        value = _text(row.get(field))
        if not value:
            continue
        evidence = {"field": field, "value": value}
        normalized = value.casefold()
        for status, accepted_values in _STATUS_VALUES.items():
            if normalized in {item.casefold() for item in accepted_values}:
                return status, evidence
        return "status_unknown", evidence
    return "status_unknown", None


def _interpret_land_use(
    code: str, name: str
) -> tuple[str, str | None, dict[str, Any]]:
    if code in _RESOURCE_DOMAINS_BY_CODE:
        return (
            _RESOURCE_DOMAINS_BY_CODE[code],
            f"exact_land_use_code:{code}",
            {"field": "raw_land_use_code", "value": code},
        )
    if not code and name in _RESOURCE_DOMAINS_BY_NAME:
        return (
            _RESOURCE_DOMAINS_BY_NAME[name],
            f"exact_land_use_name:{name}",
            {"field": "raw_land_use_name", "value": name},
        )
    return (
        "unresolved",
        None,
        {
            "raw_land_use_code": code or None,
            "raw_land_use_name": name or None,
            "resolution_status": "unresolved",
        },
    )


def _polygon_area_m2(geometry: Any) -> float | None:
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    area_m2 = float(geometry.area)
    return area_m2 if area_m2 > 0 else None


def _facility_geometry_wgs84(facility: Mapping[str, Any]):
    longitude = facility.get("longitude")
    latitude = facility.get("latitude")
    if longitude is not None and latitude is not None:
        try:
            return Point(float(longitude), float(latitude))
        except (TypeError, ValueError):
            return None
    serialized = facility.get("geometry")
    geometry_crs = facility.get("geometry_crs")
    if not serialized or not geometry_crs:
        return None
    try:
        geometry = shape(serialized)
        if geometry.is_empty or not geometry.is_valid:
            return None
        return gpd.GeoSeries([geometry], crs=geometry_crs).to_crs("EPSG:4326").iloc[0]
    except (TypeError, ValueError):
        return None


def _source_identity(row: Any) -> tuple[str, str | None]:
    for field in ("BSM", "TBBH", "OBJECTID"):
        value = _text(row.get(field))
        if value:
            return field, value
    return "none", None


def _normalize_identity(value: str | None) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _canonical_record_content(
    row: Any, geometry: Any, geometry_field: str
) -> str:
    attributes = {
        str(field): _canonical_scalar(value)
        for field, value in row.items()
        if field != geometry_field
    }
    return json.dumps(
        {
            "attributes": attributes,
            "geometry_wkb_hex": geometry.wkb_hex,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_scalar(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bytes):
        return value.hex()
    return unicodedata.normalize("NFKC", str(value)).strip()


def _canonical_candidate_sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(row["source_identity_field"]),
        str(row["source_identity_normalized"]),
        str(row["source_record_digest"]),
        str(row["_canonical_record_content"]),
    )


def _source_collision_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["source_identity_field"]),
        str(row["source_identity_normalized"]),
        str(row["source_record_digest"]),
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _source_id(area_id: str, layer: str) -> str:
    return _stable_id("planning_source", area_id, layer)


def _source_hashes(
    path: Path, root: Path
) -> tuple[str, list[dict[str, str]] | None]:
    if path.suffix.casefold() != ".shp":
        return _sha256_path(path), None
    family = sorted(
        item for item in path.parent.glob(f"{path.stem}.*") if item.is_file()
    )
    components = [
        {
            "relative_path": item.relative_to(root).as_posix(),
            "sha256": _sha256_path(item),
        }
        for item in family
    ]
    aggregate = hashlib.sha256()
    for component in components:
        aggregate.update(component["relative_path"].encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(component["sha256"].encode("ascii"))
        aggregate.update(b"\0")
    return aggregate.hexdigest(), components


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(
        item for item in path.rglob("*") if item.is_file()
    )
    for item in files:
        if path.is_dir():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _list_values(value: Any) -> list[str]:
    return [
        str(item)
        for item in (value.tolist() if hasattr(value, "tolist") else value or [])
    ]


def _first_text(row: Any, *fields: str) -> str:
    for field in fields:
        value = _text(row.get(field))
        if value:
            return value
    return ""


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()
