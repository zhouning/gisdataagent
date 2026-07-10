from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyogrio
from shapely.geometry import Point


SCHEMA = "uwm.traditional_livability.s7_fulu_planning_inputs.v1"

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

_DEMAND_NAMES = {
    "fulu_heping": "宅基地（村居住用地）",
    "fulu_banzhu": "村居住用地",
}
_CANDIDATE_SUITABILITY = {"2123": 3, "2124": 2, "214": 1}
_CANDIDATE_POLICY = "planned_public_service_or_mixed_or_independent_construction"


def inspect_fulu_s7_planning_sources(source_root: Path) -> dict[str, Any]:
    root = Path(source_root)
    blockers: list[str] = []
    sources: list[dict[str, Any]] = []
    for spec in ASSET_SPECS:
        path = root / spec["relative_path"]
        source = {
            "planning_area_id": spec["area_id"],
            "layer": spec["layer"],
            "relative_path": str(Path(spec["relative_path"])),
            "available": path.exists(),
        }
        if not path.exists():
            if spec.get("required"):
                blockers.append(f"missing_required_source:{spec['area_id']}:{spec['layer']}")
        else:
            info = pyogrio.read_info(path, force_feature_count=True)
            source.update(
                sha256=_sha256_path(path),
                feature_count=int(info.get("features") or 0),
                crs=str(info.get("crs") or ""),
                geometry_type=str(info.get("geometry_type") or ""),
                fields=_list_values(info.get("fields")),
            )
        sources.append(source)
    return {"schema": SCHEMA, "ready": not blockers, "sources": sources, "blockers": blockers}


def load_fulu_s7_planning_inputs(source_root: Path) -> dict[str, Any]:
    root = Path(source_root)
    manifest = inspect_fulu_s7_planning_sources(root)
    empty = _payload(manifest, planning_areas=[], demand_parcels=[], candidate_parcels=[], excluded_parcels=[])
    if not manifest["ready"]:
        return empty

    specs = {(spec["area_id"], spec["layer"]): spec for spec in ASSET_SPECS}
    planning_areas: list[dict[str, Any]] = []
    demand_parcels: list[dict[str, Any]] = []
    candidate_parcels: list[dict[str, Any]] = []
    excluded_parcels: list[dict[str, Any]] = []
    for area_id in ("fulu_heping", "fulu_banzhu"):
        boundary = _read_vector(root, specs[(area_id, "GHFW")])
        demands = _read_vector(root, specs[(area_id, "JQDLTB")])
        plans = _read_vector(root, specs[(area_id, "TDGHDL")])
        planning_areas.extend(_planning_area_rows(area_id, boundary))
        demand_parcels.extend(_demand_rows(area_id, demands))
        candidates, excluded = _candidate_rows(area_id, plans)
        candidate_parcels.extend(candidates)
        excluded_parcels.extend(excluded)
    return _payload(
        manifest,
        planning_areas=planning_areas,
        demand_parcels=demand_parcels,
        candidate_parcels=candidate_parcels,
        excluded_parcels=excluded_parcels,
    )


def _payload(manifest: dict[str, Any], **items: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "ready": bool(manifest["ready"]), "manifest": manifest, **items}


def _read_vector(root: Path, spec: dict[str, Any]) -> gpd.GeoDataFrame:
    return pyogrio.read_dataframe(root / spec["relative_path"])


def _planning_area_rows(area_id: str, frame: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        metric = _metric_row(row.geometry, frame.crs)
        if metric is not None:
            rows.append(
                {
                    "planning_area_id": area_id,
                    "source_parcel_id": _record_id(row, index),
                    "distance_crs": str(frame.crs),
                    "area_m2": metric["area_m2"],
                    "display_centroid": metric["display_centroid"],
                    "boundary_geometry_wgs84": gpd.GeoSeries(
                        [row.geometry], crs=frame.crs
                    ).to_crs("EPSG:4326").iloc[0],
                }
            )
    return rows


def _demand_rows(area_id: str, frame: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        code = _text(row.get("JQDLDM"))
        name = _text(row.get("JQDLMC"))
        if code != "2121" and name != _DEMAND_NAMES[area_id]:
            continue
        metric = _metric_row(row.geometry, frame.crs)
        if metric is None:
            continue
        rows.append(
            {
                "planning_area_id": area_id,
                "source_parcel_id": _record_id(row, index),
                "land_use_code": code or None,
                "land_use_name": name or None,
                "demand_proxy": "residential_land_area_m2",
                "weight_m2": metric.pop("area_m2"),
                "distance_crs": str(frame.crs),
                **metric,
            }
        )
    return rows


def _candidate_rows(area_id: str, frame: gpd.GeoDataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        code = _text(row.get("CGHDLDM")) or _text(row.get("GHDLDM"))
        name = _text(row.get("CGHDLMC")) or _text(row.get("GHDLMC"))
        metric = _metric_row(row.geometry, frame.crs)
        base = {
            "planning_area_id": area_id,
            "source_parcel_id": _record_id(row, index),
            "land_use_code": code or None,
            "land_use_name": name or None,
            "distance_crs": str(frame.crs),
        }
        if metric is None:
            excluded.append({**base, "exclusion_reason": "invalid_area"})
        elif code in _CANDIDATE_SUITABILITY:
            candidates.append(
                {
                    **base,
                    "candidate_policy": _CANDIDATE_POLICY,
                    "suitability_score": _CANDIDATE_SUITABILITY[code],
                    **metric,
                }
            )
        else:
            excluded.append({**base, "exclusion_reason": _exclusion_reason(code, name), **metric})
    return candidates, excluded


def _metric_row(geometry: Any, crs: Any) -> dict[str, Any] | None:
    if geometry is None or geometry.is_empty or not geometry.is_valid:
        return None
    area_m2 = float(geometry.area)
    if area_m2 <= 0:
        return None
    centroid = geometry.centroid
    display = gpd.GeoSeries([centroid], crs=crs).to_crs("EPSG:4326").iloc[0]
    return {
        "area_m2": area_m2,
        "projected_centroid": {"x": float(centroid.x), "y": float(centroid.y)},
        "display_centroid": {"longitude": float(display.x), "latitude": float(display.y)},
    }


def _record_id(row: Any, index: Any) -> str:
    for field in ("TBBH", "BSM", "OBJECTID"):
        value = _text(row.get(field))
        if value:
            return value
    return str(index)


def _exclusion_reason(code: str, name: str) -> str:
    if code.startswith(("011", "111", "112", "113")) or any(term in name for term in ("耕地", "水田", "旱地")):
        return "cultivated_land"
    if code.startswith("12") or "园地" in name:
        return "garden_land"
    if code.startswith("13") or "林地" in name:
        return "forest_land"
    if code.startswith("151") or "设施农用地" in name:
        return "facilities_agriculture_land"
    if code.startswith(("14", "15", "31")) or any(term in name for term in ("水面", "水域", "水库", "河流")):
        return "water_land"
    if code.startswith("22") or "道路" in name:
        return "road_land"
    if code.startswith("213") or "采矿" in name:
        return "mining_land"
    if code.startswith("32") or "自然保留" in name:
        return "natural_reservation_land"
    return "other_land_use"


def classify_primary_school_supply(
    *, facility_product: dict[str, Any], planning_inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """Classify exact primary-school facilities by planning-boundary containment."""

    areas = list(planning_inputs.get("planning_areas") or [])
    rows: list[dict[str, Any]] = []
    for facility in facility_product.get("facilities") or []:
        if facility.get("canonical_class") != "education.primary_school":
            continue
        longitude, latitude = facility.get("longitude"), facility.get("latitude")
        if longitude is None or latitude is None:
            rows.append(
                _supply_row(facility, None, "unlocatable_reference", None, None)
            )
            continue
        try:
            point = Point(float(longitude), float(latitude))
        except (TypeError, ValueError):
            rows.append(
                _supply_row(facility, None, "unlocatable_reference", None, None)
            )
            continue
        matching = next(
            (
                area
                for area in areas
                if area.get("boundary_geometry_wgs84") is not None
                and area["boundary_geometry_wgs84"].covers(point)
            ),
            None,
        )
        if matching is None:
            rows.append(
                _supply_row(
                    facility,
                    None,
                    "outside_planning_area_reference",
                    None,
                    {"longitude": float(point.x), "latitude": float(point.y)},
                )
            )
            continue
        projected = gpd.GeoSeries([point], crs="EPSG:4326").to_crs(
            matching["distance_crs"]
        ).iloc[0]
        rows.append(
            _supply_row(
                facility,
                matching["planning_area_id"],
                "locally_verified_current_supply",
                {"x": float(projected.x), "y": float(projected.y)},
                {"longitude": float(point.x), "latitude": float(point.y)},
            )
        )
    return rows


def _supply_row(facility, planning_area_id, status, projected_centroid, display_centroid):
    return {
        "source_dataset_id": facility.get("source_dataset_id"),
        "source_record_id": facility.get("source_record_id"),
        "name": facility.get("name"),
        "planning_area_id": planning_area_id,
        "supply_verification_status": status,
        "projected_centroid": projected_centroid,
        "display_centroid": display_centroid,
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    for item in [path] if path.is_file() else sorted(child for child in path.rglob("*") if child.is_file()):
        if path.is_dir():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _list_values(value: Any) -> list[str]:
    return [str(item) for item in (value.tolist() if hasattr(value, "tolist") else value or [])]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
