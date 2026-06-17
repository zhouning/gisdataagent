#!/usr/bin/env python3
"""Generate a TWM package from the Natural Resources One Map village samples.

The package is a standard-structure compatibility baseline. It preserves source
sample fields from the village planning shapefiles, then adds the role fields
required by the TWM One Map contract so later TWM code can bind by role instead
of by source filename.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

try:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
except ImportError:  # pragma: no cover - runtime dependency check is enough.
    rasterio = None
    rasterize = None
    from_bounds = None


DEFAULT_SOURCE_ROOT = Path(
    ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例/07规划编制相关数据/村规划"
)
DEFAULT_OUTPUT_DIR = Path("data_agent/test_data/twm_one_map_village_standard_sample")
STANDARD_CONTRACT_DIR = Path("data_agent/test_data/twm_standards")
PROJECT_CRS = "EPSG:4523"
DATASET_ID = "twm_one_map_village_standard_sample"
DATASET_ALIAS_ZH = "自然资源一张图村规划标准结构样例包"
STANDARD_VERSION = "NR_ONE_MAP_TWM_CORE_2026@2026-06-16-draft"
GENERATED_DATE = "2026-06-16"

STANDARD_FILES = [
    "one_map_role_contracts.zh.json",
    "one_map_field_aliases.zh.json",
    "one_map_value_domains.zh.json",
]

ROLE_LAYER_FILES = {
    "parcel_current": "parcel_current.geojson",
    "synthetic_pbf": "synthetic_pbf.geojson",
    "synthetic_eco_redline": "synthetic_eco_redline.geojson",
    "admin_units": "admin_units.geojson",
    "synthetic_annual_change": "synthetic_annual_change.geojson",
    "synthetic_projects": "synthetic_projects.geojson",
    "synthetic_planning_zones": "synthetic_planning_zones.geojson",
    "synthetic_urban_boundary": "synthetic_urban_boundary.geojson",
    "synthetic_remote_sensing_tiles": "synthetic_remote_sensing_tiles.geojson",
    "sensitive_areas": "sensitive_areas.geojson",
}

LAYER_ALIASES = {
    "parcel_current": {
        "alias_zh": "村规划现状地类图斑样例",
        "business_role_zh": "状态对象底板",
        "description_zh": "来自村规划汇交样例 JQDLTB 的现状地类图斑，保留源字段并补齐 TWM 标准契约字段。",
    },
    "synthetic_pbf": {
        "alias_zh": "契约测试永久基本农田替身",
        "business_role_zh": "耕地保护硬约束",
        "description_zh": "由村规划现状耕地图斑派生的永久基本农田契约测试层，不代表真实永久基本农田。",
    },
    "synthetic_eco_redline": {
        "alias_zh": "村规划生态保护红线样例",
        "business_role_zh": "生态保护硬约束",
        "description_zh": "来自村规划汇交样例 STBHHX 的生态保护红线要素，补齐 TWM 标准契约字段。",
    },
    "admin_units": {
        "alias_zh": "村规划范围样例",
        "business_role_zh": "区域汇总与项目范围",
        "description_zh": "来自村规划汇交样例 GHFW 的村级规划范围。",
    },
    "synthetic_annual_change": {
        "alias_zh": "村规划现状-规划差异图斑",
        "business_role_zh": "状态变化与时序证据",
        "description_zh": "由 TDGHDL 中近期地类与规划地类差异派生的变化图斑，用于 TWM 时序状态测试。",
    },
    "synthetic_projects": {
        "alias_zh": "契约测试建设项目范围替身",
        "business_role_zh": "项目约束校验主体",
        "description_zh": "从村规划差异和规划地类中派生的建设项目范围契约测试层，不代表真实审批项目。",
    },
    "synthetic_planning_zones": {
        "alias_zh": "村规划土地规划地类样例",
        "business_role_zh": "规划一致性约束",
        "description_zh": "来自村规划汇交样例 TDGHDL 的规划地类，用于用途管制分区角色兼容性验证。",
    },
    "synthetic_urban_boundary": {
        "alias_zh": "村规划建设用地管制区样例",
        "business_role_zh": "城镇开发边界/建设管制约束",
        "description_zh": "来自村规划汇交样例 JSYDGZQ 的建设用地管制区，映射为 TWM 开发边界角色。",
    },
    "synthetic_remote_sensing_tiles": {
        "alias_zh": "契约测试遥感瓦片索引",
        "business_role_zh": "多模态观测证据",
        "description_zh": "覆盖村规划样例范围的合成遥感瓦片索引，用于 MMFE 证据链结构测试。",
    },
    "sensitive_areas": {
        "alias_zh": "村规划空间管制敏感要素样例",
        "business_role_zh": "辅助约束与敏感区证据",
        "description_zh": "来自 YBD、EJYSLD、LSWH、STHFQ 等空间管制要素的辅助约束样例。",
    },
}

EXTRA_FIELD_ALIASES = {
    "source_village": "来源村",
    "source_layer": "来源图层",
    "source_path": "来源文件",
    "source_BSM": "源标识码",
    "source_sample": "是否来源样例",
    "derived_from_source_sample": "是否由样例派生",
    "category": "归并地类",
    "geom_area_m2": "投影几何面积",
    "tbmj_area_rel_error": "图斑面积相对误差",
    "qa_use_for_rules": "可用于规则计算",
    "control_id": "管控区编号",
    "control_name": "管控区名称",
    "control_type": "管控区类型",
    "control_grade": "管控区等级",
    "control_area_m2": "管控区面积",
    "redline_id": "红线区编号",
    "redline_name": "红线区名称",
    "protection_level": "保护等级",
    "ecological_function": "生态功能",
    "redline_area_m2": "红线区面积",
    "plan_zone_id": "用途分区编号",
    "plan_zone_type": "用途分区类型",
    "plan_zone_name": "用途分区名称",
    "plan_rule": "用途管制规则",
    "zone_area_m2": "分区面积",
    "boundary_id": "边界编号",
    "boundary_type": "边界类型",
    "boundary_name": "边界名称",
    "boundary_area_m2": "边界面积",
    "change_id": "变化编号",
    "from_dlbm": "变化前地类编码",
    "from_dlmc": "变化前地类名称",
    "to_dlbm": "变化后地类编码",
    "to_dlmc": "变化后地类名称",
    "change_type": "变化类型",
    "change_year": "变化年份",
    "event_date": "事件日期",
    "temporal_stage": "时序阶段",
    "evidence_confidence": "证据置信度",
    "source_feature_id": "来源要素编号",
    "project_id": "项目编号",
    "project_name": "项目名称",
    "project_type": "项目类型",
    "approval_status": "审批状态",
    "risk_scenario": "风险场景",
    "review_priority": "复核优先级",
    "planned_start": "计划开始日期",
    "planned_end": "计划结束日期",
    "planned_area_m2": "项目计划面积",
    "tile_id": "影像瓦片编号",
    "modality": "模态类型",
    "sensor": "传感器",
    "acquisition_date": "采集日期",
    "band_set": "波段组合",
    "cloud_cover_pct": "云量百分比",
    "image_uri": "影像资源地址",
    "raster_product_id": "栅格产品编号",
    "raster_uri": "栅格资源地址",
    "tile_area_m2": "瓦片覆盖面积",
    "constraint_id": "约束编号",
    "constraint_type": "约束类型",
    "constraint_name": "约束名称",
    "constraint_area_m2": "约束面积",
    "synthetic": "是否合成",
    "not_for_production": "禁止生产使用",
    "synthetic_method": "合成方法",
    "source_dataset": "来源数据集",
}

PLANNING_SPACE_NAMES = {
    "01": "农业生产空间",
    "02": "生态保护空间",
    "03": "城镇建设空间",
    "04": "水域保护空间",
    "99": "其他国土空间",
}

URBAN_PARTITION_NAMES = {
    "01": "城镇集中建设区",
    "02": "城镇弹性发展区",
    "03": "特别用途区",
    "99": "其他城镇开发边界分区",
}


def _clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return default
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except Exception:
        return default


def _polygonal_geometry(geom: Any) -> Any:
    if geom is None or geom.is_empty:
        return None
    fixed = make_valid(geom)
    if fixed.is_empty:
        return None
    if isinstance(fixed, (Polygon, MultiPolygon)):
        return fixed
    if isinstance(fixed, GeometryCollection):
        polygons = [g for g in fixed.geoms if isinstance(g, Polygon)]
        multipolygons = [g for g in fixed.geoms if isinstance(g, MultiPolygon)]
        parts = polygons.copy()
        for multi in multipolygons:
            parts.extend(list(multi.geoms))
        if not parts:
            return None
        return MultiPolygon(parts) if len(parts) > 1 else parts[0]
    return None


def _normalise_gdf(gdf: gpd.GeoDataFrame, project_crs: str) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.set_crs(project_crs, allow_override=True) if gdf.crs is None else gdf.to_crs(project_crs)
    if gdf.crs is None:
        raise ValueError("source layer has no CRS")
    out = gdf.to_crs(project_crs).copy()
    out["geometry"] = out.geometry.map(_polygonal_geometry)
    out = out[out.geometry.notna() & ~out.geometry.is_empty].copy()
    out["geom_area_m2"] = out.geometry.area.round(3)
    return out


def _find_village_databases(source_root: Path) -> list[dict[str, Any]]:
    records = []
    seen: set[Path] = set()
    for parcel_path in sorted(source_root.glob("**/JQDLTB.shp")):
        db_root = parcel_path.parent.parent
        if db_root in seen:
            continue
        seen.add(db_root)
        parts = list(parcel_path.parts)
        village = "未知村"
        for part in parts:
            if "和平村" in part:
                village = "和平村"
                break
            if "斑竹村" in part:
                village = "斑竹村"
                break
        records.append(
            {
                "village": village,
                "db_root": db_root,
                "layers": {
                    "GHFW": db_root / "310基础要素" / "GHFW.shp",
                    "JQDLTB": db_root / "310基础要素" / "JQDLTB.shp",
                    "TDGHDL": db_root / "320规划要素" / "TDGHDL.shp",
                    "JSYDGZQ": db_root / "320规划要素" / "JSYDGZQ.shp",
                    "STBHHX": db_root / "330空间管制要素" / "STBHHX.shp",
                    "YBD": db_root / "330空间管制要素" / "YBD.shp",
                    "EJYSLD": db_root / "330空间管制要素" / "EJYSLD.shp",
                    "LSWH": db_root / "330空间管制要素" / "LSWH.shp",
                    "STHFQ": db_root / "330空间管制要素" / "STHFQ.shp",
                },
            }
        )
    return records


def _read_layer(record: dict[str, Any], layer_name: str, project_crs: str) -> gpd.GeoDataFrame:
    path = record["layers"].get(layer_name)
    if not path or not path.exists():
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=project_crs)
    gdf = gpd.read_file(path)
    gdf = _normalise_gdf(gdf, project_crs)
    gdf["source_village"] = record["village"]
    gdf["source_layer"] = layer_name
    gdf["source_path"] = str(path)
    if "BSM" in gdf.columns:
        gdf["source_BSM"] = gdf["BSM"].map(_clean_text)
    else:
        gdf["source_BSM"] = ""
    return gdf


def _concat_layers(records: list[dict[str, Any]], layer_name: str, project_crs: str) -> gpd.GeoDataFrame:
    frames = [_read_layer(record, layer_name, project_crs) for record in records]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=project_crs)
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=project_crs)


def _classify_land_use(code: Any, name: Any) -> str:
    text = f"{_clean_text(code)} {_clean_text(name)}"
    if any(token in text for token in ["水田", "旱地", "水浇地", "耕地"]):
        return "Farmland"
    if any(token in text for token in ["林地", "灌木", "乔木", "森林"]):
        return "Forest"
    if any(token in text for token in ["果园", "园地", "茶园"]):
        return "Orchard"
    if any(token in text for token in ["水", "坑塘", "河", "沟渠", "湖"]):
        return "Water"
    if any(token in text for token in ["城镇", "村庄", "住宅", "工矿", "建设", "道路", "公路"]):
        return "Built"
    return "Other"


def _planning_space_code(code: Any, name: Any) -> str:
    text = f"{_clean_text(code)} {_clean_text(name)}"
    if any(token in text for token in ["水田", "旱地", "水浇地", "耕地", "园地", "果园", "农业"]):
        return "01"
    if any(token in text for token in ["林地", "生态", "草地", "保护"]):
        return "02"
    if any(token in text for token in ["城镇", "村庄", "住宅", "工矿", "建设", "道路"]):
        return "03"
    if any(token in text for token in ["水", "坑塘", "河", "沟渠", "湖"]):
        return "04"
    return "99"


def _urban_partition_code(source_code: Any, name: Any) -> str:
    code = _clean_text(source_code)
    text = f"{code} {_clean_text(name)}"
    if code.startswith("010") or "集中" in text:
        return "01"
    if code.startswith("020") or "弹性" in text:
        return "02"
    if code.startswith("030") or "特别" in text:
        return "03"
    return "99"


def _assign_unique_ids(gdf: gpd.GeoDataFrame, prefix: str, column: str = "BSM") -> gpd.GeoDataFrame:
    out = gdf.copy()
    out[column] = [f"{prefix}-{i:06d}" for i in range(1, len(out) + 1)]
    return out


def _build_parcels(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    parcels = _concat_layers(records, "JQDLTB", project_crs)
    parcels = _assign_unique_ids(parcels, "VPARCEL")
    parcels["bsm_norm"] = parcels["BSM"]
    parcels["DLBM"] = parcels.apply(
        lambda row: _clean_text(row.get("XZDLDM")) or _clean_text(row.get("DLDM")) or "9999",
        axis=1,
    )
    parcels["DLMC"] = parcels.apply(
        lambda row: _clean_text(row.get("XZDLMC")) or _clean_text(row.get("DLMC")) or "未分类",
        axis=1,
    )
    parcels["TBBH"] = [
        _clean_text(value) or f"TB{i:06d}" for i, value in enumerate(parcels.get("TBBH", []), start=1)
    ]
    parcels["YSDM"] = parcels.get("YSDM", "").map(lambda value: _clean_text(value, "2003010100"))
    parcels["QSXZ"] = parcels.get("QSXZ", "").map(lambda value: _clean_text(value, "30"))
    for col in ["QSDWDM", "QSDWMC", "ZLDWDM", "ZLDWMC"]:
        if col not in parcels.columns:
            parcels[col] = ""
        parcels[col] = parcels[col].map(lambda value: _clean_text(value, "unknown"))
    parcels["TBMJ"] = parcels["TBMJ"].map(lambda value: round(max(_as_number(value), 0.001), 3))
    if "TBDLMJ" not in parcels.columns:
        parcels["TBDLMJ"] = parcels["TBMJ"]
    parcels["TBDLMJ"] = parcels["TBDLMJ"].map(lambda value: round(max(_as_number(value), 0.001), 3))
    parcels["SJNF"] = "2020"
    parcels["MSSM"] = "村规划标准结构样例现状地类图斑"
    parcels["category"] = parcels.apply(lambda row: _classify_land_use(row["DLBM"], row["DLMC"]), axis=1)
    parcels["admin9"] = parcels["QSDWDM"].map(lambda value: _clean_text(value)[:9])
    parcels["tbmj_area_rel_error"] = (
        (parcels["geom_area_m2"] - parcels["TBMJ"]).abs() / parcels["TBMJ"].replace(0, np.nan)
    ).fillna(0.0).round(6)
    parcels["source_sample"] = True
    parcels["derived_from_source_sample"] = False
    parcels["synthetic"] = False
    parcels["not_for_production"] = True
    parcels["source_dataset"] = "自然资源一张图数据库标准1128村规划样例/JQDLTB"
    parcels["qa_use_for_rules"] = parcels["geometry"].is_valid & (parcels["geom_area_m2"] > 0)
    return parcels


def _build_admin_units(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    admin = _concat_layers(records, "GHFW", project_crs)
    admin = _assign_unique_ids(admin, "VADMIN")
    admin["admin_code"] = admin.get("XZQDM", "").map(lambda value: _clean_text(value, "unknown"))
    admin["admin_name"] = admin.get("XZQMC", "").map(lambda value: _clean_text(value, "未知村"))
    admin["admin_level"] = "village"
    admin["admin_parent_code"] = admin["admin_code"].str[:9]
    admin["admin_level_rank"] = 5
    admin["admin_source_level"] = "village_planning_scope"
    admin["matched_admin9_values"] = admin["admin_parent_code"]
    admin["matched_parcel_count"] = 0
    admin["overlap_area_m2"] = admin["geom_area_m2"].round(3)
    admin["overlap_ratio_to_parcels"] = 1.0
    admin["source_sample"] = True
    admin["derived_from_source_sample"] = False
    admin["synthetic"] = False
    admin["not_for_production"] = True
    admin["qa_use_for_rules"] = admin["geometry"].is_valid & (admin["geom_area_m2"] > 0)
    return admin


def _build_pbf(parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    farmland = parcels[parcels["category"].isin(["Farmland"])].copy()
    if farmland.empty:
        farmland = parcels.sort_values("geom_area_m2", ascending=False).head(min(80, len(parcels))).copy()
    selected = []
    for _, group in farmland.groupby("source_village", dropna=False):
        ranked = group.sort_values("geom_area_m2", ascending=False)
        take = min(max(20, int(len(ranked) * 0.35)), 180)
        selected.append(ranked.head(take))
    pbf = gpd.GeoDataFrame(pd.concat(selected, ignore_index=True), geometry="geometry", crs=parcels.crs)
    pbf = _assign_unique_ids(pbf, "VPBF")
    pbf["YSDM"] = "2005010100"
    pbf["XZQDM"] = pbf["QSDWDM"].map(lambda value: _clean_text(value)[:12] or "unknown")
    pbf["XZQMC"] = pbf["QSDWMC"].map(lambda value: _clean_text(value, "未知权属单位"))
    pbf["YJJBNTTBBH"] = [f"YJJBNTTB-{i:06d}" for i in range(1, len(pbf) + 1)]
    pbf["YJJBNTTBMJ"] = pbf["geom_area_m2"].round(3)
    pbf["YJJBNTMJ"] = pbf["geom_area_m2"].round(3)
    pbf["SJNF"] = "2020"
    pbf["BHKSSJ"] = "20200101"
    pbf["BHJSSJ"] = "20351231"
    pbf["WDGD"] = "1"
    pbf["control_id"] = pbf["YJJBNTTBBH"]
    pbf["control_name"] = pbf["source_village"] + "永久基本农田契约测试图斑"
    pbf["control_type"] = "永久基本农田保护图斑"
    pbf["control_grade"] = "contract_substitute"
    pbf["control_area_m2"] = pbf["YJJBNTMJ"]
    pbf["source_sample"] = False
    pbf["derived_from_source_sample"] = True
    pbf["synthetic"] = True
    pbf["not_for_production"] = True
    pbf["synthetic_method"] = "derive_from_standard_sample_farmland_area_rank"
    pbf["source_dataset"] = "parcel_current/JQDLTB farmland subset"
    pbf["qa_use_for_rules"] = True
    return pbf


def _build_eco_redline(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    eco = _concat_layers(records, "STBHHX", project_crs)
    if eco.empty:
        return eco
    eco = _assign_unique_ids(eco, "VECO")
    eco["YSDM"] = eco.get("YSDM", "").map(lambda value: _clean_text(value, "3001080000"))
    eco["XJXZQDM"] = eco.get("XZQDM", "").map(lambda value: _clean_text(value, "unknown"))
    eco["XJXZQMC"] = eco.get("XZQMC", "").map(lambda value: _clean_text(value, "未知行政区"))
    eco["LHLX"] = "1"
    eco["MJ"] = eco["geom_area_m2"].round(3)
    eco["XJXZQHDM"] = eco["XJXZQDM"]
    eco["LXDM"] = "01"
    eco["MC"] = eco.get("GZMC", "").map(lambda value: _clean_text(value, "生态保护红线"))
    eco["QYMJ"] = (eco["geom_area_m2"] / 1_000_000.0).round(6)
    eco["SLSJ"] = "20200101"
    eco["GKCS"] = "生态保护红线严格管控"
    eco["redline_id"] = eco["BSM"]
    eco["redline_name"] = eco["MC"]
    eco["protection_level"] = "生态保护红线"
    eco["ecological_function"] = "生态功能维护"
    eco["redline_area_m2"] = eco["MJ"]
    eco["source_sample"] = True
    eco["derived_from_source_sample"] = False
    eco["synthetic"] = False
    eco["not_for_production"] = True
    eco["source_dataset"] = "自然资源一张图数据库标准1128村规划样例/STBHHX"
    eco["qa_use_for_rules"] = True
    return eco


def _build_sensitive_areas(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    frames = []
    for name in ["YBD", "EJYSLD", "LSWH", "STHFQ"]:
        frame = _concat_layers(records, name, project_crs)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=project_crs)
    sensitive = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=project_crs)
    sensitive = _assign_unique_ids(sensitive, "VSENS")
    sensitive["constraint_id"] = sensitive["BSM"]
    sensitive["constraint_type"] = sensitive["source_layer"]
    sensitive["constraint_name"] = sensitive.get("GZMC", "").map(lambda value: _clean_text(value, "空间管制敏感要素"))
    sensitive["constraint_area_m2"] = sensitive["geom_area_m2"].round(3)
    sensitive["source_sample"] = True
    sensitive["derived_from_source_sample"] = False
    sensitive["synthetic"] = False
    sensitive["not_for_production"] = True
    sensitive["qa_use_for_rules"] = True
    return sensitive


def _build_planning_zones(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    planning = _concat_layers(records, "TDGHDL", project_crs)
    planning = _assign_unique_ids(planning, "VPLAN")
    planning["YSDM"] = planning.get("YSDM", "").map(lambda value: _clean_text(value, "2003020210"))
    planning["XZQDM"] = planning.get("XZQDM", "").map(lambda value: _clean_text(value, "unknown"))
    planning["XZQMC"] = planning.get("XZQMC", "").map(lambda value: _clean_text(value, "未知行政区"))
    planning["source_GHDLDM"] = planning.get("GHDLDM", "").map(_clean_text)
    planning["source_GHDLMC"] = planning.get("GHDLMC", "").map(_clean_text)
    planning["GHFQDM"] = planning.apply(
        lambda row: _planning_space_code(row.get("GHDLDM"), row.get("GHDLMC")),
        axis=1,
    )
    planning["GHFQMC"] = planning["GHFQDM"].map(PLANNING_SPACE_NAMES)
    planning["MJ"] = planning["geom_area_m2"].round(3)
    planning["plan_zone_id"] = planning["BSM"]
    planning["plan_zone_type"] = planning["GHFQMC"]
    planning["plan_zone_name"] = planning["source_village"] + planning["GHFQMC"]
    planning["plan_rule"] = "按国土空间用途分区进行准入校验"
    planning["zone_area_m2"] = planning["MJ"]
    planning["source_sample"] = True
    planning["derived_from_source_sample"] = False
    planning["synthetic"] = False
    planning["not_for_production"] = True
    planning["source_dataset"] = "自然资源一张图数据库标准1128村规划样例/TDGHDL"
    planning["qa_use_for_rules"] = True
    return planning


def _build_urban_boundary(records: list[dict[str, Any]], project_crs: str) -> gpd.GeoDataFrame:
    urban = _concat_layers(records, "JSYDGZQ", project_crs)
    urban = _assign_unique_ids(urban, "VURBAN")
    urban["YSDM"] = urban.get("YSDM", "").map(lambda value: _clean_text(value, "2003020200"))
    urban["XZQDM"] = urban.get("XZQDM", "").map(lambda value: _clean_text(value, "unknown"))
    urban["XZQMC"] = urban.get("XZQMC", "").map(lambda value: _clean_text(value, "未知行政区"))
    urban["GHFQDM"] = urban.apply(lambda row: _urban_partition_code(row.get("GZQLXDM"), row.get("GZQLXDM")), axis=1)
    urban["GHFQMC"] = urban["GHFQDM"].map(URBAN_PARTITION_NAMES)
    urban["MJ"] = urban["geom_area_m2"].round(3)
    urban["CZMC"] = urban["XZQMC"]
    urban["XJXZQHDM"] = urban["XZQDM"]
    urban["CZKFMJ"] = urban["geom_area_m2"].round(3)
    urban["SLSJ"] = "20200101"
    urban["boundary_id"] = urban["BSM"]
    urban["boundary_type"] = urban["GHFQMC"]
    urban["boundary_name"] = urban["source_village"] + "建设用地管制区"
    urban["boundary_area_m2"] = urban["MJ"]
    urban["source_sample"] = True
    urban["derived_from_source_sample"] = False
    urban["synthetic"] = False
    urban["not_for_production"] = True
    urban["source_dataset"] = "自然资源一张图数据库标准1128村规划样例/JSYDGZQ"
    urban["qa_use_for_rules"] = True
    return urban


def _build_annual_change(planning: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if planning.empty:
        return planning
    changed = planning[
        planning.apply(
            lambda row: _clean_text(row.get("JQDLDM")) != _clean_text(row.get("GHDLDM")),
            axis=1,
        )
    ].copy()
    if changed.empty:
        changed = planning.sort_values("geom_area_m2", ascending=False).head(min(80, len(planning))).copy()
    changed = changed.sort_values("geom_area_m2", ascending=False).head(min(260, len(changed))).copy()
    changed = _assign_unique_ids(changed, "VCHANGE")
    changed["change_id"] = changed["BSM"]
    changed["from_dlbm"] = changed.get("JQDLDM", "").map(lambda value: _clean_text(value, "unknown"))
    changed["from_dlmc"] = changed.get("JQDLMC", "").map(lambda value: _clean_text(value, "未知现状地类"))
    changed["to_dlbm"] = changed.get("GHDLDM", "").map(lambda value: _clean_text(value, "unknown"))
    changed["to_dlmc"] = changed.get("GHDLMC", "").map(lambda value: _clean_text(value, "未知规划地类"))
    changed["OPT_DLBM"] = changed["to_dlbm"]
    changed["OPT_DLMC"] = changed["to_dlmc"]
    changed["ORIG_DLBM"] = changed["from_dlbm"]
    changed["CHG_FLAG"] = "planning_transition"
    changed["change_type"] = "current_to_planned_land_use"
    changed["change_year"] = 2035
    changed["event_date"] = "2035-12-31"
    changed["temporal_stage"] = "planning_target"
    changed["evidence_confidence"] = 0.86
    changed["source_feature_id"] = changed["plan_zone_id"]
    changed["source_sample"] = True
    changed["derived_from_source_sample"] = True
    changed["synthetic"] = False
    changed["not_for_production"] = True
    changed["source_dataset"] = "TDGHDL JQDLDM/GHDLDM comparison"
    changed["qa_use_for_rules"] = True
    return changed


def _build_projects(
    changes: gpd.GeoDataFrame,
    planning: gpd.GeoDataFrame,
    admin: gpd.GeoDataFrame,
    max_projects: int,
) -> gpd.GeoDataFrame:
    base = changes if not changes.empty else planning
    base = base.sort_values("geom_area_m2", ascending=False).head(max_projects * 2).copy()
    if base.empty:
        raise ValueError("cannot build project substitutes without planning or change geometries")
    rows = []
    for i, (_, row) in enumerate(base.head(max_projects).iterrows(), start=1):
        project_id = f"VPRJ-{i:04d}"
        admin_code = _clean_text(row.get("XZQDM")) or _clean_text(row.get("QSDWDM")) or "unknown"
        admin_name = _clean_text(row.get("XZQMC")) or _clean_text(row.get("QSDWMC")) or _clean_text(row.get("source_village"), "未知村")
        geom = row.geometry
        area = float(geom.area)
        rows.append(
            {
                "geometry": geom,
                "YSDM": "6002010100",
                "XMDM": project_id,
                "DZJGH": f"DZJG-{GENERATED_DATE.replace('-', '')}-{i:04d}",
                "AJBH": f"AJ-{GENERATED_DATE.replace('-', '')}-{i:04d}",
                "XMMC": f"{_clean_text(row.get('source_village'), '村规划')}空间治理契约测试项目{i:02d}",
                "SZXZQDM": admin_code,
                "SZXZQMC": admin_name,
                "YDMJ": round(area, 3),
                "SQDW": "TWM工程测试",
                "XMPZLX": "contract_test",
                "HYFLBM": "N01",
                "HYFLMC": "自然资源治理测试",
                "TDYTDM": _clean_text(row.get("to_dlbm")) or _clean_text(row.get("GHDLDM")) or "99",
                "TDYTMC": _clean_text(row.get("to_dlmc")) or _clean_text(row.get("GHDLMC")) or "规划用途",
                "ZYNYDMJ": 0.0,
                "ZYGDMJ": 0.0,
                "SJSTHXMJ": 0.0,
                "ZYJSYDMJ": round(area, 3),
                "ZYWLDMJ": 0.0,
                "SQRQ": "20260616",
                "GXRQ": "20260616",
                "project_id": project_id,
                "project_name": f"{_clean_text(row.get('source_village'), '村规划')}空间治理契约测试项目{i:02d}",
                "project_type": "村规划用途调整契约测试",
                "approval_status": "审查中" if i % 3 else "拟退回",
                "risk_scenario": "pending_overlay",
                "review_priority": "medium",
                "planned_start": "2026-07-01",
                "planned_end": "2027-12-31",
                "planned_area_m2": round(area, 3),
                "source_feature_id": _clean_text(row.get("change_id")) or _clean_text(row.get("plan_zone_id")),
                "source_village": _clean_text(row.get("source_village"), "未知村"),
                "source_layer": "derived_project",
                "source_path": "",
                "source_sample": False,
                "derived_from_source_sample": True,
                "synthetic": True,
                "not_for_production": True,
                "synthetic_method": "derive_project_footprints_from_village_planning_differences",
                "source_dataset": "TDGHDL planning differences",
                "qa_use_for_rules": True,
            }
        )
    projects = gpd.GeoDataFrame(rows, geometry="geometry", crs=base.crs)
    projects = _assign_unique_ids(projects, "VPROJ")
    if not admin.empty:
        projects["admin9"] = projects["SZXZQDM"].str[:9]
    return projects


def _build_remote_sensing_tiles(bounds: list[float], crs: str) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bounds
    cols = 4
    rows = 3
    dx = (maxx - minx) / cols
    dy = (maxy - miny) / rows
    records = []
    idx = 1
    for r in range(rows):
        for c in range(cols):
            geom = box(minx + c * dx, miny + r * dy, minx + (c + 1) * dx, miny + (r + 1) * dy)
            records.append(
                {
                    "tile_id": f"VRS-{idx:03d}",
                    "modality": "remote_sensing",
                    "sensor": "synthetic_fixture",
                    "acquisition_date": "2026-06-16",
                    "band_set": "rgb,ndvi,change_intensity",
                    "cloud_cover_pct": round(3.0 + idx * 0.7, 2),
                    "image_uri": f"synthetic://village-standard-sample/tile-{idx:03d}",
                    "raster_product_id": "RASTER-NDVI-2026|RASTER-CHANGE-2026",
                    "raster_uri": "raster_manifest.json",
                    "tile_area_m2": round(float(geom.area), 3),
                    "source_sample": False,
                    "derived_from_source_sample": True,
                    "synthetic": True,
                    "not_for_production": True,
                    "synthetic_method": "aoi_grid_fixture",
                    "source_dataset": "village_sample_aoi",
                    "qa_use_for_rules": True,
                    "geometry": geom,
                }
            )
            idx += 1
    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)


def _positive_relation(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    *,
    left_id: str,
    right_id: str,
    relation_name: str,
    right_role: str,
    min_area: float = 1.0,
) -> pd.DataFrame:
    columns = [
        "relation_id",
        "relation_type",
        left_id,
        right_id,
        "right_role",
        "overlap_area_m2",
        "overlap_ratio_left",
        "overlap_ratio_right",
        "confidence",
        "synthetic",
        "not_for_production",
    ]
    if left.empty or right.empty:
        return pd.DataFrame(columns=columns)
    ldf = left.reset_index(drop=True)
    rdf = right.reset_index(drop=True)
    joined = gpd.sjoin(ldf[[left_id, "geometry"]], rdf[[right_id, "geometry"]], how="inner", predicate="intersects")
    rows = []
    for _, row in joined.iterrows():
        li = int(row.name)
        ri = int(row["index_right"])
        geom_left = ldf.geometry.iloc[li]
        geom_right = rdf.geometry.iloc[ri]
        inter = geom_left.intersection(geom_right)
        area = float(inter.area) if not inter.is_empty else 0.0
        if area <= min_area:
            continue
        rows.append(
            {
                "relation_id": f"{relation_name.upper()}-{len(rows) + 1:06d}",
                "relation_type": relation_name,
                left_id: row[left_id],
                right_id: row[right_id],
                "right_role": right_role,
                "overlap_area_m2": round(area, 3),
                "overlap_ratio_left": round(area / float(geom_left.area), 6) if geom_left.area else 0.0,
                "overlap_ratio_right": round(area / float(geom_right.area), 6) if geom_right.area else 0.0,
                "confidence": 0.88,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _build_change_parcel_relation(changes: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame) -> pd.DataFrame:
    rel = _positive_relation(
        changes,
        parcels,
        left_id="change_id",
        right_id="bsm_norm",
        relation_name="change_intersects_parcel",
        right_role="parcel_current",
    )
    if rel.empty:
        return pd.DataFrame(
            columns=[
                "relation_id",
                "relation_type",
                "change_id",
                "bsm_norm",
                "match_type",
                "confidence",
                "synthetic",
                "not_for_production",
            ]
        )
    rel["match_type"] = "positive_area_intersection"
    return rel[
        [
            "relation_id",
            "relation_type",
            "change_id",
            "bsm_norm",
            "match_type",
            "confidence",
            "synthetic",
            "not_for_production",
        ]
    ]


def _overlay_metric(projects: gpd.GeoDataFrame, constraints: gpd.GeoDataFrame, right_id: str) -> dict[str, float]:
    rel = _positive_relation(
        projects,
        constraints,
        left_id="project_id",
        right_id=right_id,
        relation_name="metric",
        right_role=right_id,
    )
    return rel.groupby("project_id")["overlap_area_m2"].sum().to_dict() if not rel.empty else {}


def _build_governance_tables(
    projects: gpd.GeoDataFrame,
    pbf: gpd.GeoDataFrame,
    eco: gpd.GeoDataFrame,
    planning: gpd.GeoDataFrame,
) -> dict[str, pd.DataFrame]:
    pbf_area = _overlay_metric(projects, pbf, "control_id")
    eco_area = _overlay_metric(projects, eco, "redline_id")
    planning_area = _overlay_metric(projects, planning, "plan_zone_id")
    rule_rows = []
    for _, project in projects.iterrows():
        pid = project["project_id"]
        specs = [
            ("TWM-FARM-001", "永久基本农田占用检查", "major", pbf_area.get(pid, 0.0), "永久基本农田保护约束"),
            ("TWM-ECO-001", "生态保护红线占用检查", "critical", eco_area.get(pid, 0.0), "生态保护红线约束"),
            ("TWM-PLAN-001", "规划用途一致性检查", "minor", planning_area.get(pid, 0.0), "国土空间规划分区约束"),
        ]
        for rule_id, rule_name, severity, value, basis in specs:
            status = "hit_requires_review" if value > 1.0 and rule_id != "TWM-PLAN-001" else "pass"
            rule_rows.append(
                {
                    "rule_eval_id": f"RE-{len(rule_rows) + 1:06d}",
                    "project_id": pid,
                    "rule_id": rule_id,
                    "rule_name_zh": rule_name,
                    "severity": severity if status != "pass" else "info",
                    "finding_status": status,
                    "finding_basis": f"{basis}; overlap_area_m2={value:.3f}",
                    "metric_value": round(value, 3),
                    "metric_unit": "m2",
                    "standard_version": STANDARD_VERSION,
                    "legal_basis": "自然资源一张图 TWM 核心角色标准契约",
                    "event_date": "2026-06-16",
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    rule_eval = pd.DataFrame(rule_rows)

    approval_rows = []
    for i, (_, project) in enumerate(projects.iterrows(), start=1):
        approval_rows.append(
            {
                "YSDM": "6003010100",
                "DKBH": f"VDK-{i:05d}",
                "DKMC": project["project_name"],
                "DKMJ": project["planned_area_m2"],
                "DKXZQDM": project["SZXZQDM"],
                "DKXZQMC": project["SZXZQMC"],
                "DKYTDM": project["TDYTDM"],
                "DKYTMC": project["TDYTMC"],
                "DKZT": "审查中",
                "DZJGH": project["DZJGH"],
                "AJBH": project["AJBH"],
                "XZQDM": project["SZXZQDM"],
                "XZQMC": project["SZXZQMC"],
                "ZYZMJ": project["planned_area_m2"],
                "ZDZMJ": project["planned_area_m2"],
                "QZNYDMJ": 0.0,
                "QZGDMJ": 0.0,
                "XZYDZMJ": project["planned_area_m2"],
                "approval_id": f"VAPR-{i:05d}",
                "project_id": project["project_id"],
                "application_date": "2026-06-16",
                "decision_date": "2026-07-16",
                "approval_status": project["approval_status"],
                "decision_result": "审查中",
                "approved_area_m2": project["planned_area_m2"],
                "reviewing_department": "TWM工程测试审查组",
                "legal_basis": "用途管制审批契约测试",
                "standard_version": STANDARD_VERSION,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    approval = pd.DataFrame(approval_rows)

    hits = rule_eval[rule_eval["finding_status"] == "hit_requires_review"].copy()
    enforcement_rows = []
    for i, (_, hit) in enumerate(hits.iterrows(), start=1):
        project = projects[projects["project_id"] == hit["project_id"]].iloc[0]
        enforcement_rows.append(
            {
                "BSM": f"VENFBSM-{i:06d}",
                "YSDM": "8001010100",
                "WFXWZJ": f"WFXW-{i:06d}",
                "WFDKXH": f"VWFDK-{i:06d}",
                "YGTBZJ": f"VYGTB-{i:06d}",
                "XZQDM": project["SZXZQDM"],
                "JCSDQ": "20260601",
                "JCSDH": "20260616",
                "JCMJ": max(float(hit["metric_value"]), 0.0),
                "TDZL": project["SZXZQMC"],
                "TBLX": hit["rule_id"],
                "ND": "2026",
                "QSSJ": "20260601",
                "ZZSJ": "20260616",
                "GXZT": "待复核",
                "enforcement_id": f"VENF-{i:05d}",
                "project_id": hit["project_id"],
                "rule_eval_id": hit["rule_eval_id"],
                "event_type": "规则命中复核",
                "event_date": "2026-06-16",
                "event_status": "待复核",
                "severity": hit["severity"],
                "assigned_department": "TWM工程测试复核组",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    if not enforcement_rows and len(projects):
        project = projects.iloc[0]
        enforcement_rows.append(
            {
                "BSM": "VENFBSM-000001",
                "YSDM": "8001010100",
                "WFXWZJ": "WFXW-000001",
                "WFDKXH": "VWFDK-000001",
                "YGTBZJ": "VYGTB-000001",
                "XZQDM": project["SZXZQDM"],
                "JCSDQ": "20260601",
                "JCSDH": "20260616",
                "JCMJ": 0.0,
                "TDZL": project["SZXZQMC"],
                "TBLX": "contract_test",
                "ND": "2026",
                "QSSJ": "20260601",
                "ZZSJ": "20260616",
                "GXZT": "样例复核",
                "enforcement_id": "VENF-00001",
                "project_id": project["project_id"],
                "rule_eval_id": rule_eval.iloc[0]["rule_eval_id"],
                "event_type": "样例链路复核",
                "event_date": "2026-06-16",
                "event_status": "待复核",
                "severity": "info",
                "assigned_department": "TWM工程测试复核组",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    enforcement = pd.DataFrame(enforcement_rows)
    review = pd.DataFrame(
        [
            {
                "review_task_id": f"VREV-{i:05d}",
                "enforcement_id": row["enforcement_id"],
                "project_id": row["project_id"],
                "rule_eval_id": row["rule_eval_id"],
                "task_status": "open",
                "reviewer_role": "natural_resource_reviewer",
                "due_date": "2026-07-01",
                "review_result": "pending",
                "synthetic": True,
                "not_for_production": True,
            }
            for i, row in enumerate(enforcement_rows, start=1)
        ]
    )
    return {
        "rule_evaluation": rule_eval,
        "approval_records": approval,
        "enforcement_events": enforcement,
        "review_tasks": review,
    }


def _build_state_snapshots(parcels: gpd.GeoDataFrame, planning: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for category, group in parcels.groupby("category"):
        rows.append(
            {
                "snapshot_year": 2020,
                "temporal_stage": "current",
                "land_space_type": category,
                "feature_count": int(len(group)),
                "area_m2": round(float(group.geometry.area.sum()), 3),
                "area_delta_m2": 0.0,
                "source_dataset": "JQDLTB",
                "synthetic": False,
                "not_for_production": True,
            }
        )
    for zone, group in planning.groupby("GHFQMC"):
        rows.append(
            {
                "snapshot_year": 2035,
                "temporal_stage": "planning_target",
                "land_space_type": zone,
                "feature_count": int(len(group)),
                "area_m2": round(float(group.geometry.area.sum()), 3),
                "area_delta_m2": 0.0,
                "source_dataset": "TDGHDL",
                "synthetic": False,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(rows)


def _load_contract_assets() -> tuple[dict[str, Any], dict[str, str]]:
    contract = json.loads((STANDARD_CONTRACT_DIR / "one_map_role_contracts.zh.json").read_text(encoding="utf-8"))
    aliases_payload = json.loads((STANDARD_CONTRACT_DIR / "one_map_field_aliases.zh.json").read_text(encoding="utf-8"))
    aliases = dict(aliases_payload.get("field_aliases", {}))
    aliases.update(EXTRA_FIELD_ALIASES)
    return contract, aliases


def _build_standard_field_catalog(contract: dict[str, Any], aliases: dict[str, str]) -> pd.DataFrame:
    rows = []
    for role, role_contract in contract.get("roles", {}).items():
        for field in role_contract.get("required_fields", []):
            rows.append(
                {
                    "field_name": field,
                    "field_alias_zh": aliases.get(field, field),
                    "lifecycle_status": "active",
                    "introduced_version": contract.get("version", ""),
                    "deprecated_version": "",
                    "replacement_field": "",
                    "standard_version": STANDARD_VERSION,
                    "synthetic": False,
                    "not_for_production": True,
                }
            )
        for field in role_contract.get("recommended_fields", []):
            rows.append(
                {
                    "field_name": field,
                    "field_alias_zh": aliases.get(field, field),
                    "lifecycle_status": "recommended",
                    "introduced_version": contract.get("version", ""),
                    "deprecated_version": "",
                    "replacement_field": "",
                    "standard_version": STANDARD_VERSION,
                    "synthetic": False,
                    "not_for_production": True,
                }
            )
    rows.append(
        {
            "field_name": "OLD_PROJECT_CODE",
            "field_alias_zh": "旧项目编号",
            "lifecycle_status": "deprecated",
            "introduced_version": "legacy",
            "deprecated_version": contract.get("version", ""),
            "replacement_field": "XMDM",
            "standard_version": STANDARD_VERSION,
            "synthetic": True,
            "not_for_production": True,
        }
    )
    return pd.DataFrame(rows).drop_duplicates(subset=["field_name", "lifecycle_status"]).reset_index(drop=True)


def _build_metadata_vector(layers: dict[str, gpd.GeoDataFrame], output_dir: Path, aliases: dict[str, str]) -> pd.DataFrame:
    rows = []
    for i, (role, gdf) in enumerate(layers.items(), start=1):
        if gdf.empty:
            continue
        bounds = [round(float(v), 3) for v in gdf.total_bounds]
        layer_alias = LAYER_ALIASES.get(role, {}).get("alias_zh", role)
        rows.append(
            {
                "data_id": f"VMETA-{i:04d}",
                "resource_id": f"{DATASET_ID}:{role}",
                "data_name": role,
                "data_alias": layer_alias,
                "data_des": LAYER_ALIASES.get(role, {}).get("description_zh", ""),
                "data_format": "GeoJSON",
                "data_type": "vector",
                "data_size": int(len(gdf)),
                "cover_range_coor": json.dumps(bounds, ensure_ascii=False),
                "cover_range": "璧山区福禄镇村规划样例",
                "security_order": "internal_test",
                "is_multilayer": "0",
                "layer_count": 1,
                "layer_name": role,
                "layer_field": ",".join([c for c in gdf.columns if c != "geometry"][:80]),
                "geometry_type": ",".join(sorted(gdf.geom_type.unique())),
                "is_shareable": "1",
                "share_type": "engineering_test",
                "is_opentosociety": "0",
                "receive_mode": "local_file",
                "receive_batch": DATASET_ID,
                "import_time": datetime.now(timezone.utc).isoformat(),
                "wkid": "4523",
                "geodetic_datum": "CGCS2000",
                "projection": "CGCS2000 3-degree Gauss-Kruger Zone 35",
                "coordinate_unit": "metre",
                "product_date": "2020-01-01",
                "update_date": GENERATED_DATE,
                "update_cycle": "sample",
                "release_date": GENERATED_DATE,
                "producer": "自然资源一张图数据库标准1128样例包",
                "pro_unit_name": "TWM工程测试",
                "source_type": "standard_sample" if not bool(gdf.get("synthetic", pd.Series([False])).astype(bool).all()) else "synthetic_contract_substitute",
                "source_currency": "sample",
                "integrity": "complete_for_contract_test",
                "score": 88.0,
                "quality_check_date": GENERATED_DATE,
                "check_unit_name": "TWM QA",
                "quality_evaluation": "良",
                "quality_des": "标准结构样例，禁止作为生产权威数据使用。",
                "synthetic": False,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(rows)


def _write_raster(
    path: Path,
    array: np.ndarray,
    *,
    crs: str,
    transform: Any,
    nodata: float,
    description: str,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype("float32"), 1)
        dst.set_band_description(1, description)
    valid = array[np.isfinite(array) & (array != nodata)]
    return {
        "valid_pixels": int(valid.size),
        "min": round(float(valid.min()), 6) if valid.size else None,
        "mean": round(float(valid.mean()), 6) if valid.size else None,
        "max": round(float(valid.max()), 6) if valid.size else None,
    }


def _build_rasters(
    output_dir: Path,
    parcels: gpd.GeoDataFrame,
    changes: gpd.GeoDataFrame,
    project_crs: str,
) -> dict[str, Any]:
    if rasterio is None or rasterize is None or from_bounds is None:
        return {}
    minx, miny, maxx, maxy = parcels.total_bounds
    pad = max(maxx - minx, maxy - miny) * 0.02
    bounds = [minx - pad, miny - pad, maxx + pad, maxy + pad]
    width = 256
    height = 256
    transform = from_bounds(*bounds, width, height)
    nodata = -9999.0
    base_shapes = []
    values = {
        "Farmland": 0.68,
        "Forest": 0.82,
        "Orchard": 0.72,
        "Water": 0.12,
        "Built": 0.22,
        "Other": 0.45,
    }
    for _, row in parcels.iterrows():
        base_shapes.append((row.geometry, values.get(row["category"], 0.45)))
    ndvi = rasterize(base_shapes, out_shape=(height, width), transform=transform, fill=nodata, dtype="float32")
    intensity = np.where(ndvi == nodata, nodata, 0.05).astype("float32")
    if not changes.empty:
        change_shapes = [(geom, 0.55) for geom in changes.geometry]
        change_arr = rasterize(change_shapes, out_shape=(height, width), transform=transform, fill=0.0, dtype="float32")
        intensity = np.where((intensity != nodata) & (change_arr > 0), change_arr, intensity).astype("float32")
    raster_dir = output_dir / "rasters"
    ndvi_path = raster_dir / "synthetic_ndvi_2026.tif"
    change_path = raster_dir / "synthetic_change_intensity_2026.tif"
    ndvi_stats = _write_raster(
        ndvi_path,
        ndvi,
        crs=project_crs,
        transform=transform,
        nodata=nodata,
        description="Synthetic NDVI from village standard sample land-use classes",
    )
    change_stats = _write_raster(
        change_path,
        intensity,
        crs=project_crs,
        transform=transform,
        nodata=nodata,
        description="Synthetic change intensity from village planning differences",
    )
    common = {
        "crs": project_crs,
        "width": width,
        "height": height,
        "bounds": [round(float(v), 3) for v in bounds],
        "transform": [round(float(v), 9) for v in tuple(transform)[:6]],
        "nodata": nodata,
        "dtype": "float32",
        "synthetic": True,
        "not_for_production": True,
        "synthetic_method": "vector_semantic_fixture_rasterization",
        "source_layers": ["parcel_current", "synthetic_annual_change"],
    }
    return {
        "synthetic_ndvi_2026": {
            "product_id": "RASTER-NDVI-2026",
            "path": str(ndvi_path),
            "relative_path": str(ndvi_path.relative_to(output_dir)),
            "alias_zh": "合成NDVI观测栅格",
            "description_zh": "由村规划样例地类派生的归一化植被指数测试栅格。",
            "stats": ndvi_stats,
            **common,
        },
        "synthetic_change_intensity_2026": {
            "product_id": "RASTER-CHANGE-2026",
            "path": str(change_path),
            "relative_path": str(change_path.relative_to(output_dir)),
            "alias_zh": "合成变化强度栅格",
            "description_zh": "由村规划现状-规划差异派生的变化强度测试栅格。",
            "stats": change_stats,
            **common,
        },
    }


def _build_documents(output_dir: Path, projects: gpd.GeoDataFrame) -> Path:
    docs_dir = output_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "project_documents.zh.jsonl"
    lines = []
    for _, project in projects.iterrows():
        lines.append(
            json.dumps(
                {
                    "project_id": project["project_id"],
                    "title": project["project_name"],
                    "document_type": "contract_test_project_note",
                    "content": (
                        f"{project['project_name']}用于验证TWM项目范围、规划分区、控制线、审批和复核证据链。"
                        "该记录为工程测试替身，不代表真实审批材料。"
                    ),
                    "synthetic": True,
                    "not_for_production": True,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build_evidence_index(
    output_dir: Path,
    projects: gpd.GeoDataFrame,
    tiles: gpd.GeoDataFrame,
    raster_products: dict[str, Any],
    documents_path: Path,
) -> pd.DataFrame:
    rows = []
    for i, project_id in enumerate(projects["project_id"], start=1):
        rows.append(
            {
                "evidence_id": f"VEVD-DOC-{i:06d}",
                "evidence_type": "text_project_document",
                "evidence_uri": str(documents_path.relative_to(output_dir)),
                "linked_object_id": project_id,
                "linked_object_type": "project",
                "observed_date": GENERATED_DATE,
                "confidence": 0.86,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    for i, tile in enumerate(tiles["tile_id"], start=1):
        rows.append(
            {
                "evidence_id": f"VEVD-RSTILE-{i:06d}",
                "evidence_type": "remote_sensing_tile_index",
                "evidence_uri": "synthetic_remote_sensing_tiles.geojson",
                "linked_object_id": tile,
                "linked_object_type": "remote_sensing_tile",
                "observed_date": GENERATED_DATE,
                "confidence": 0.75,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    for i, product in enumerate(raster_products.values(), start=1):
        rows.append(
            {
                "evidence_id": f"VEVD-RASTER-{i:06d}",
                "evidence_type": "raster_observation",
                "evidence_uri": product["relative_path"],
                "linked_object_id": product["product_id"],
                "linked_object_type": "raster_product",
                "observed_date": GENERATED_DATE,
                "confidence": 0.72,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    rows.append(
        {
            "evidence_id": "VEVD-STD-000001",
            "evidence_type": "standard_rule_lifecycle",
            "evidence_uri": "standards/one_map_role_contracts.zh.json",
            "linked_object_id": STANDARD_VERSION,
            "linked_object_type": "standard_contract",
            "observed_date": GENERATED_DATE,
            "confidence": 0.95,
            "synthetic": False,
            "not_for_production": True,
        }
    )
    return pd.DataFrame(rows)


def _build_data_dictionary(layers: dict[str, gpd.GeoDataFrame], aliases: dict[str, str]) -> dict[str, Any]:
    fields: dict[str, dict[str, str]] = {}
    layer_fields: dict[str, list[str]] = {}
    for role, gdf in layers.items():
        layer_fields[role] = [c for c in gdf.columns if c != "geometry"]
        for field in layer_fields[role]:
            fields[field] = {
                "alias_zh": aliases.get(field, field),
                "description_zh": f"{aliases.get(field, field)}。"
            }
    return {
        "dataset_id": DATASET_ID,
        "dataset_alias_zh": DATASET_ALIAS_ZH,
        "description_zh": "用于验证自然资源一张图村规划标准结构与 TWM 角色契约兼容性的工程测试数据包。",
        "not_for_production": True,
        "layers": LAYER_ALIASES,
        "fields": fields,
        "roles": {
            "parcel_current": "parcel_current",
            "pbf": "synthetic_pbf",
            "eco_redline": "synthetic_eco_redline",
            "planning_zone": "synthetic_planning_zones",
            "urban_boundary": "synthetic_urban_boundary",
            "project": "synthetic_projects",
        },
        "layer_fields": layer_fields,
    }


def _write_layers(output_dir: Path, layers: dict[str, gpd.GeoDataFrame]) -> dict[str, Any]:
    manifest_layers = {}
    for role, filename in ROLE_LAYER_FILES.items():
        gdf = layers.get(role)
        if gdf is None or gdf.empty:
            continue
        path = output_dir / filename
        gdf.to_file(path, driver="GeoJSON")
        manifest_layers[role] = {
            "path": str(path),
            "rows": int(len(gdf)),
            "columns": [c for c in gdf.columns if c != "geometry"],
            "geometry_types": sorted(map(str, gdf.geom_type.unique().tolist())),
            "bounds": [round(float(v), 6) for v in gdf.to_crs("EPSG:4326").total_bounds],
            "alias_zh": LAYER_ALIASES.get(role, {}).get("alias_zh", role),
            "synthetic_counts": gdf["synthetic"].astype(str).value_counts().to_dict()
            if "synthetic" in gdf.columns
            else {},
        }
    return manifest_layers


def _write_tables(output_dir: Path, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    table_dir = output_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, df in tables.items():
        path = table_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        out[name] = {"path": str(path), "rows": int(len(df)), "columns": list(df.columns)}
    return out


def _write_relations(output_dir: Path, relations: dict[str, pd.DataFrame]) -> dict[str, Any]:
    relation_dir = output_dir / "relations"
    relation_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, df in relations.items():
        path = relation_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        out[name] = {"path": str(path), "rows": int(len(df)), "columns": list(df.columns)}
    return out


def _copy_standard_contracts(output_dir: Path) -> dict[str, Any]:
    standards_dir = output_dir / "standards"
    standards_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in STANDARD_FILES:
        src = STANDARD_CONTRACT_DIR / name
        dst = standards_dir / name
        shutil.copy2(src, dst)
        copied[name] = {"path": str(dst), "exists": dst.exists()}
    return copied


def _write_standard_rules(output_dir: Path) -> Path:
    path = output_dir / "standard_rules.lifecycle.json"
    payload = {
        "standard_version": STANDARD_VERSION,
        "rules": [
            {"rule_id": "TWM-FARM-001", "name_zh": "永久基本农田占用检查", "role": "pbf"},
            {"rule_id": "TWM-ECO-001", "name_zh": "生态保护红线占用检查", "role": "eco_redline"},
            {"rule_id": "TWM-PLAN-001", "name_zh": "规划用途一致性检查", "role": "planning_zone"},
        ],
        "lifecycle_versions": [
            {"version": "2026-06-16-draft", "status": "released_for_engineering_test"}
        ],
        "not_for_production": True,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_manifest(
    output_dir: Path,
    source_root: Path,
    db_records: list[dict[str, Any]],
    manifest_layers: dict[str, Any],
    relation_manifest: dict[str, Any],
    table_manifest: dict[str, Any],
    raster_products: dict[str, Any],
    standards: dict[str, Any],
    documents_path: Path,
    standard_rules_path: Path,
) -> None:
    payload = {
        "dataset_id": DATASET_ID,
        "dataset_alias_zh": DATASET_ALIAS_ZH,
        "version": GENERATED_DATE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "not_for_production": True,
        "description_zh": "自然资源一张图村规划汇交样例转换形成的 TWM 标准结构兼容性测试包。",
        "data_positioning_zh": (
            "该包用于验证标准字段、角色绑定、关系表、规则证据链和未来真实数据替换能力；"
            "其中源样例层为 source_sample=true，缺失权威角色由 synthetic=true 的契约测试替身补齐。"
        ),
        "inputs": {
            "source_root": str(source_root),
            "villages": [record["village"] for record in db_records],
            "project_crs": PROJECT_CRS,
        },
        "layers": manifest_layers,
        "relations": relation_manifest,
        "tables": table_manifest,
        "rasters": raster_products,
        "raster_manifest": {
            "path": str(output_dir / "raster_manifest.json"),
            "product_count": len(raster_products),
        },
        "standard_contracts": {
            "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
            "files": standards,
        },
        "documents": {
            "project_documents_zh": {
                "path": str(documents_path),
                "format": "jsonl",
            }
        },
        "standard_rules": {
            "path": str(standard_rules_path),
            "rules": 3,
            "lifecycle_versions": 1,
        },
        "quality_reports": {
            "json": str(output_dir / "data_quality_report.json"),
            "markdown": str(output_dir / "data_quality_report.md"),
            "generator": "scripts/qa_twm_demo_data.py",
        },
        "preview": {
            "html": str(output_dir / "preview" / "index.html"),
            "geopackage": str(output_dir / "preview" / f"{DATASET_ID}_layers.gpkg"),
            "generator": "scripts/preview_twm_demo_data.py",
        },
        "recommended_layer_bindings": [
            {"role": "parcel_current", "path": str(output_dir / "parcel_current.geojson")},
            {"role": "pbf", "path": str(output_dir / "synthetic_pbf.geojson")},
            {"role": "eco_redline", "path": str(output_dir / "synthetic_eco_redline.geojson")},
            {"role": "planning_zone", "path": str(output_dir / "synthetic_planning_zones.geojson")},
            {"role": "urban_boundary", "path": str(output_dir / "synthetic_urban_boundary.geojson")},
            {"role": "project", "path": str(output_dir / "synthetic_projects.geojson")},
            {"role": "approval", "path": str(output_dir / "tables" / "approval_records.csv")},
            {"role": "enforcement", "path": str(output_dir / "tables" / "enforcement_events.csv")},
            {"role": "metadata_vector", "path": str(output_dir / "tables" / "metadata_vector.csv")},
        ],
        "known_limitations": [
            "村规划样例只覆盖和平村、斑竹村，不代表全域权威自然资源库。",
            "永久基本农田、项目、审批、执法和遥感瓦片为契约测试替身，不能用于生产结论。",
            "该包重点验证标准结构兼容性；真实生产环境应替换为权威管控线、审批、执法和影像数据。",
        ],
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_readme(output_dir: Path) -> None:
    text = f"""# {DATASET_ALIAS_ZH}

该数据包用于验证自然资源一张图村规划样例能否按 TWM 角色契约接入。

- `source_sample=true`: 来自压缩包中的村规划汇交样例，保留源字段并补齐 TWM 必需字段。
- `synthetic=true`: 当前真实权威数据缺失时的契约测试替身，例如永久基本农田、项目、审批和执法记录。
- `not_for_production=true`: 所有数据均禁止作为生产级自然资源治理结论使用。

建议先查看：

- `preview/index.html`
- `data_quality_report.md`
- `dataset_manifest.json`
- `standards/one_map_role_contracts.zh.json`
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    source_root = Path(args.source_root)
    output_dir = Path(args.output_dir)
    db_records = _find_village_databases(source_root)
    if not db_records:
        raise FileNotFoundError(f"no village JQDLTB.shp found under {source_root}")
    if output_dir.exists() and not args.keep_existing:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    contract, aliases = _load_contract_assets()
    parcels = _build_parcels(db_records, args.project_crs)
    admin = _build_admin_units(db_records, args.project_crs)
    pbf = _build_pbf(parcels)
    eco = _build_eco_redline(db_records, args.project_crs)
    sensitive = _build_sensitive_areas(db_records, args.project_crs)
    planning = _build_planning_zones(db_records, args.project_crs)
    urban = _build_urban_boundary(db_records, args.project_crs)
    changes = _build_annual_change(planning)
    projects = _build_projects(changes, planning, admin, args.max_projects)
    tiles = _build_remote_sensing_tiles(list(parcels.total_bounds), args.project_crs)

    project_parcel = _positive_relation(
        projects,
        parcels,
        left_id="project_id",
        right_id="bsm_norm",
        relation_name="project_intersects_parcel",
        right_role="parcel_current",
    )
    project_pbf = _positive_relation(
        projects,
        pbf,
        left_id="project_id",
        right_id="control_id",
        relation_name="project_intersects_pbf",
        right_role="pbf",
    )
    project_eco = _positive_relation(
        projects,
        eco,
        left_id="project_id",
        right_id="redline_id",
        relation_name="project_intersects_eco_redline",
        right_role="eco_redline",
    )
    project_planning = _positive_relation(
        projects,
        planning,
        left_id="project_id",
        right_id="plan_zone_id",
        relation_name="project_intersects_planning_zone",
        right_role="planning_zone",
    )
    project_urban = _positive_relation(
        projects,
        urban,
        left_id="project_id",
        right_id="boundary_id",
        relation_name="project_intersects_urban_boundary",
        right_role="urban_boundary",
    )
    project_tiles = _positive_relation(
        projects,
        tiles,
        left_id="project_id",
        right_id="tile_id",
        relation_name="project_intersects_remote_sensing_tile",
        right_role="remote_sensing_tile",
    )
    change_parcel = _build_change_parcel_relation(changes, parcels)

    if not project_pbf.empty:
        projects.loc[projects["project_id"].isin(project_pbf["project_id"]), "risk_scenario"] = "pbf_overlap"
        projects.loc[projects["project_id"].isin(project_pbf["project_id"]), "review_priority"] = "high"
    if not project_eco.empty:
        projects.loc[projects["project_id"].isin(project_eco["project_id"]), "risk_scenario"] = "eco_redline_overlap"
        projects.loc[projects["project_id"].isin(project_eco["project_id"]), "review_priority"] = "critical"

    governance = _build_governance_tables(projects, pbf, eco, planning)
    state_snapshots = _build_state_snapshots(parcels, planning)
    field_catalog = _build_standard_field_catalog(contract, aliases)

    layers = {
        "parcel_current": parcels,
        "synthetic_pbf": pbf,
        "synthetic_eco_redline": eco,
        "admin_units": admin,
        "synthetic_annual_change": changes,
        "synthetic_projects": projects,
        "synthetic_planning_zones": planning,
        "synthetic_urban_boundary": urban,
        "synthetic_remote_sensing_tiles": tiles,
        "sensitive_areas": sensitive,
    }
    metadata = _build_metadata_vector(layers, output_dir, aliases)
    raster_products = _build_rasters(output_dir, parcels, changes, args.project_crs)
    documents_path = _build_documents(output_dir, projects)
    evidence = _build_evidence_index(output_dir, projects, tiles, raster_products, documents_path)

    manifest_layers = _write_layers(output_dir, layers)
    relations = {
        "project_parcel_rel": project_parcel,
        "project_pbf_rel": project_pbf,
        "project_eco_rel": project_eco,
        "project_planning_rel": project_planning,
        "project_urban_boundary_rel": project_urban,
        "project_rs_tile_rel": project_tiles,
        "change_parcel_rel": change_parcel,
    }
    relation_manifest = _write_relations(output_dir, relations)
    tables = {
        **governance,
        "state_snapshots": state_snapshots,
        "standard_field_catalog": field_catalog,
        "metadata_vector": metadata,
        "multimodal_evidence_index": evidence,
    }
    table_manifest = _write_tables(output_dir, tables)
    (output_dir / "raster_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": DATASET_ID,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "products": raster_products,
                "not_for_production": True,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    standards = _copy_standard_contracts(output_dir)
    standard_rules_path = _write_standard_rules(output_dir)
    dictionary = _build_data_dictionary(layers, aliases)
    (output_dir / "data_dictionary.zh.json").write_text(
        json.dumps(dictionary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _write_manifest(
        output_dir,
        source_root,
        db_records,
        manifest_layers,
        relation_manifest,
        table_manifest,
        raster_products,
        standards,
        documents_path,
        standard_rules_path,
    )
    _write_readme(output_dir)

    return {
        "status": "success",
        "output_dir": str(output_dir),
        "villages": [record["village"] for record in db_records],
        "layers": {role: int(len(gdf)) for role, gdf in layers.items()},
        "relations": {name: int(len(df)) for name, df in relations.items()},
        "tables": {name: int(len(df)) for name, df in tables.items()},
        "raster_products": sorted(raster_products.keys()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-crs", default=PROJECT_CRS)
    parser.add_argument("--max-projects", type=int, default=36)
    parser.add_argument("--keep-existing", action="store_true")
    return parser.parse_args()


def main() -> None:
    result = build_package(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
