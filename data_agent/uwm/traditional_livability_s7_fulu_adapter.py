from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyogrio


SCHEMA = "uwm.traditional_livability.s7_fulu_planning_inputs.v1"

_HEPING_ROOT = (
    "07规划编制相关数据/村规划/璧山区福禄镇和平村规划成果/"
    "00璧山区福禄镇和平村规划最终成果0831/3规划数据库/3规划数据库"
)
_BANZHU_ROOT = "07规划编制相关数据/村规划/璧山区福禄镇斑竹村土地利用规划成果汇交/3规划数据库"

ASSET_SPECS = (
    {"area_id": "fulu_heping", "layer": "boundary", "relative_path": f"{_HEPING_ROOT}/310基础要素/GHFW.shp", "required": True},
    {"area_id": "fulu_heping", "layer": "demand", "relative_path": f"{_HEPING_ROOT}/310基础要素/JQDLTB.shp", "required": True},
    {"area_id": "fulu_heping", "layer": "candidate", "relative_path": f"{_HEPING_ROOT}/320规划要素/TDGHDL.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "boundary", "relative_path": f"{_BANZHU_ROOT}/310基础要素/GHFW.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "demand", "relative_path": f"{_BANZHU_ROOT}/310基础要素/JQDLTB.shp", "required": True},
    {"area_id": "fulu_banzhu", "layer": "candidate", "relative_path": f"{_BANZHU_ROOT}/320规划要素/TDGHDL.shp", "required": True},
)

_DEMAND_NAMES = {
    "fulu_heping": "宅基地（村居住用地）",
    "fulu_banzhu": "村居住用地",
}
_CANDIDATE_WEIGHTS = {"2123": 3, "2124": 2, "214": 1}
_EXCLUSION_REASONS = (
    ("cultivated_land", ("011",), ("耕地",)),
    ("garden_land", ("012",), ("园地",)),
    ("forest_land", ("013",), ("林地",)),
    ("water_land", ("14",), ("水域",)),
    ("road_land", ("12",), ("道路",)),
    ("mining_land", ("10",), ("采矿",)),
    ("facilities_agriculture_land", ("0601",), ("设施农业",)),
    ("natural_reservation_land", ("17",), ("自然保留",)),
)


def inspect_fulu_s7_planning_sources(source_root: Path) -> dict[str, Any]:
    root = Path(source_root)
    blockers: list[str] = []
    sources: list[dict[str, Any]] = []
    for spec in ASSET_SPECS:
        path = root / spec["relative_path"]
        source = {
            "area_id": spec["area_id"],
            "layer": spec["layer"],
            "relative_path": str(Path(spec["relative_path"])),
            "available": path.exists(),
        }
        if not path.exists():
            if spec.get("required"):
                blockers.append(
                    f"missing_required_source:{spec['area_id']}:{Path(spec['relative_path']).stem}"
                )
        else:
            info = pyogrio.read_info(path, layer=spec.get("source_layer"), force_feature_count=True)
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
    empty = {"schema": SCHEMA, "manifest": manifest, "demands": [], "candidates": [], "excluded_candidates": []}
    if not manifest["ready"]:
        return empty

    specs = {(spec["area_id"], spec["layer"]): spec for spec in ASSET_SPECS}
    demands: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for area_id in ("fulu_heping", "fulu_banzhu"):
        demand_frame = _read_vector(root, specs[(area_id, "demand")])
        candidate_frame = _read_vector(root, specs[(area_id, "candidate")])
        demands.extend(_demand_rows(area_id, demand_frame))
        included, rejected = _candidate_rows(area_id, candidate_frame)
        candidates.extend(included)
        excluded.extend(rejected)
    return {"schema": SCHEMA, "manifest": manifest, "demands": demands, "candidates": candidates, "excluded_candidates": excluded}


def _read_vector(root: Path, spec: dict[str, Any]) -> gpd.GeoDataFrame:
    return pyogrio.read_dataframe(root / spec["relative_path"], layer=spec.get("source_layer"))


def _demand_rows(area_id: str, frame: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        code = _text(row.get("JQDLDM"))
        name = _text(row.get("JQDLM"))
        if code == "2121" or name == _DEMAND_NAMES[area_id]:
            metric = _metric_row(area_id, index, row.geometry, frame.crs)
            if metric is not None:
                rows.append({"demand_proxy": "residential_land_area_m2", "weight_m2": metric.pop("area_m2"), **metric})
    return rows


def _candidate_rows(area_id: str, frame: gpd.GeoDataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        code = _text(row.get("CGHDLDM")) or _text(row.get("GHDLDM"))
        name = _text(row.get("CGHDLMC")) or _text(row.get("GHDLMC"))
        metric = _metric_row(area_id, index, row.geometry, frame.crs)
        if metric is None:
            excluded.append(_excluded_row(area_id, index, code, name, "invalid_area"))
        elif code in _CANDIDATE_WEIGHTS:
            included.append({"land_use_code": code, "land_use_name": name or None, "weight": _CANDIDATE_WEIGHTS[code], **metric})
        else:
            excluded.append(_excluded_row(area_id, index, code, name, _exclusion_reason(code, name)))
    return included, excluded


def _metric_row(area_id: str, index: Any, geometry: Any, crs: Any) -> dict[str, Any] | None:
    if geometry is None or geometry.is_empty or not geometry.is_valid:
        return None
    area_m2 = float(geometry.area)
    if area_m2 <= 0:
        return None
    centroid = geometry.centroid
    display = gpd.GeoSeries([centroid], crs=crs).to_crs("EPSG:4326").iloc[0]
    return {
        "area_id": area_id,
        "source_record_id": str(index),
        "area_m2": area_m2,
        "projected_crs": str(crs),
        "projected_centroid": {"x": float(centroid.x), "y": float(centroid.y)},
        "display_centroid": {"longitude": float(display.x), "latitude": float(display.y)},
    }


def _excluded_row(area_id: str, index: Any, code: str, name: str, reason: str) -> dict[str, Any]:
    return {"area_id": area_id, "source_record_id": str(index), "land_use_code": code or None, "land_use_name": name or None, "reason": reason}


def _exclusion_reason(code: str, name: str) -> str:
    for reason, prefixes, name_terms in _EXCLUSION_REASONS:
        if code.startswith(prefixes) or any(term in name for term in name_terms):
            return reason
    return "other_land_use"


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
