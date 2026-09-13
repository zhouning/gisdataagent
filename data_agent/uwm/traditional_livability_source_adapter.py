from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import pyogrio


SCHEMA = "uwm.traditional_livability.source_manifest.v1"

ASSET_SPECS = (
    {"asset_id": "gaode_poi", "kind": "vector", "relative_path": "09高德地图POI数据/高德地图POI数据2024年.gdb", "layer": "高德地图POI数据2024年", "required": True},
    {"asset_id": "baidu_aoi", "kind": "vector", "relative_path": "10百度地图AOI数据/百度地图AOI数据.gdb", "layer": "重庆市百度地图AOI数据_2024年", "required": True},
    {"asset_id": "admin_population_2021", "kind": "excel", "relative_path": "08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx", "required": True},
    {"asset_id": "osm_roads_2021", "kind": "vector", "relative_path": "02重庆市OSM道路数据2021年/OSM_roads.shp", "required": True},
    {"asset_id": "current_land_use", "kind": "vector", "relative_path": "07规划编制相关数据/区县/现状用地数据/GDB.gdb", "layer": "DLTB", "required": True},
)


def inspect_traditional_livability_sources(source_root: Path) -> dict[str, Any]:
    root = Path(source_root)
    sources: list[dict[str, Any]] = []
    blockers: list[str] = []
    for spec in ASSET_SPECS:
        path = root / spec["relative_path"]
        item: dict[str, Any] = {
            "asset_id": spec["asset_id"],
            "relative_path": str(Path(spec["relative_path"])),
            "kind": spec["kind"],
            "layer": spec.get("layer"),
            "available": path.exists(),
        }
        if not path.exists():
            if spec.get("required"):
                blockers.append(f"missing_required_source:{spec['asset_id']}")
            sources.append(item)
            continue
        item["sha256"] = _sha256_path(path)
        if spec["kind"] == "vector":
            info = pyogrio.read_info(path, layer=spec.get("layer"), force_feature_count=True)
            item.update(
                feature_count=int(info.get("features") or 0),
                crs=str(info.get("crs") or ""),
                geometry_type=str(info.get("geometry_type") or ""),
                fields=_list_values(info.get("fields")),
            )
        else:
            frame = pd.read_excel(path)
            item.update(row_count=len(frame), fields=[str(value) for value in frame.columns])
        sources.append(item)
    return {"schema": SCHEMA, "ready": not blockers, "sources": sources, "blockers": blockers}


def load_traditional_livability_source_rows(
    source_root: Path,
    *,
    max_poi_features: int | None = None,
    max_aoi_features: int | None = None,
) -> dict[str, Any]:
    root = Path(source_root)
    manifest = inspect_traditional_livability_sources(root)
    manifest["sampling"] = {"max_poi_features": max_poi_features, "max_aoi_features": max_aoi_features}
    manifest["complete_inventory"] = bool(manifest["ready"] and max_poi_features is None and max_aoi_features is None)
    if not manifest["ready"]:
        return {"manifest": manifest, "poi_rows": [], "aoi_rows": [], "population_rows": [], "road_rows": [], "land_parcel_rows": []}
    specs = {spec["asset_id"]: spec for spec in ASSET_SPECS}
    poi = _read_vector(root, specs["gaode_poi"], max_poi_features)
    aoi = _read_vector(root, specs["baidu_aoi"], max_aoi_features)
    roads = _read_vector(root, specs["osm_roads_2021"], None)
    land = _read_vector(root, specs["current_land_use"], None)
    population = pd.read_excel(root / specs["admin_population_2021"]["relative_path"])
    return {
        "manifest": manifest,
        "poi_rows": [_poi_row(row) for row in poi.to_dict("records")],
        "aoi_rows": [_aoi_row(row) for row in aoi.to_dict("records")],
        "population_rows": [_population_row(row) for row in population.to_dict("records")],
        "road_rows": [_road_row(row) for row in roads.to_dict("records")],
        "land_parcel_rows": [_land_row(row) for row in land.to_dict("records")],
    }


def _read_vector(root: Path, spec: dict[str, Any], limit: int | None):
    return pyogrio.read_dataframe(
        root / spec["relative_path"], layer=spec.get("layer"), max_features=limit,
    )


def _poi_row(row: dict[str, Any]) -> dict[str, Any]:
    classes = _split(row.get("类型"), ";")
    return _facility_row(row, "gaode_poi", row.get("ID"), classes, row.get("区域ID"))


def _aoi_row(row: dict[str, Any]) -> dict[str, Any]:
    classes = [row.get("第一分类"), row.get("第二分类")]
    if not any(_text(value) for value in classes):
        classes = _split(row.get("类型"), ",")
    return _facility_row(row, "baidu_aoi", row.get("uid"), classes, row.get("区县"))


def _facility_row(row, dataset_id, record_id, classes, admin_code):
    return {
        "source_record_id": _identifier(record_id), "source_dataset_id": dataset_id,
        "name": _nullable_text(row.get("名称")),
        "raw_primary_class": _at(classes, 0), "raw_secondary_class": _at(classes, 1), "raw_tertiary_class": _at(classes, 2),
        "admin_code": _identifier(admin_code), "longitude": _float(row.get("经度wgs84")), "latitude": _float(row.get("纬度wgs84")),
        "geometry_type": getattr(row.get("geometry"), "geom_type", None),
    }


def _population_row(row):
    value = _float(row.get("常住人口"))
    return {"source_record_id": _identifier(row.get("行政区划代码")), "source_dataset_id": "admin_population_2021", "admin_code": _identifier(row.get("行政区划代码")), "admin_name": _nullable_text(row.get("区划名称")), "population": int(round(value * 10000)) if value is not None else None}


def _road_row(row):
    return {"source_record_id": _identifier(row.get("osm_id")), "source_dataset_id": "osm_roads_2021", "road_class": _nullable_text(row.get("fclass")), "oneway": _nullable_text(row.get("oneway")), "maxspeed": _float(row.get("maxspeed")), "geometry_type": getattr(row.get("geometry"), "geom_type", None)}


def _land_row(row):
    return {"source_record_id": _identifier(row.get("BSM")), "source_dataset_id": "current_land_use", "land_use_code": _identifier(row.get("DLBM")), "land_use_name": _nullable_text(row.get("DLMC")), "area_m2": _float(row.get("TBMJ")), "geometry_type": getattr(row.get("geometry"), "geom_type", None)}


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        if path.is_dir():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _list_values(value):
    return [str(item) for item in (value.tolist() if hasattr(value, "tolist") else value or [])]


def _split(value, delimiter):
    return [part.strip() for part in _text(value).split(delimiter) if part.strip()]


def _at(values, index):
    return _nullable_text(values[index]) if index < len(values) else None


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _nullable_text(value):
    return _text(value) or None


def _identifier(value):
    if value is None or pd.isna(value):
        return None
    number = _float(value)
    if number is not None and number.is_integer():
        return str(int(number))
    return str(value).strip()


def _float(value):
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
