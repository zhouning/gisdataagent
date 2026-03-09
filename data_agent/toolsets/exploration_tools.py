"""Exploration toolset: data profiling, topology, field standards, reproject, feature engineering."""
import os
import numpy as np
import geopandas as gpd

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..utils import _load_spatial_data, _configure_fonts
from ..gis_processors import (
    check_topology,
    check_field_standards,
    _generate_output_path,
    _resolve_path,
)
from ..doc_auditor import check_consistency


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def describe_geodataframe(file_path: str) -> dict:
    """数据探查画像：全面质量预检。"""
    try:
        gdf = _load_spatial_data(file_path)
        warns, recs = [], []

        if not gdf.crs:
            warns.append("缺少坐标参考系 (No CRS)")
            recs.append("请指定坐标系，如 EPSG:4326 或 EPSG:4490")
        elif gdf.crs.is_geographic:
            warns.append(f"当前为地理坐标系 ({gdf.crs})，面积/距离计算将不准确")
            recs.append("建议重投影至投影坐标系")

        null_cols = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            n_null = int(gdf[col].isna().sum())
            if n_null > 0:
                null_cols[col] = n_null
        if null_cols:
            worst = max(null_cols, key=null_cols.get)
            warns.append(f"发现 {len(null_cols)} 列存在空值，最严重: {worst} ({null_cols[worst]}个空值)")
            recs.append("建议清除或填充空值后再进行分析")

        n_null_geom = int(gdf.geometry.isna().sum())
        n_empty_geom = int(gdf.geometry.is_empty.sum()) if n_null_geom < len(gdf) else 0
        total_bad_geom = n_null_geom + n_empty_geom
        if total_bad_geom > 0:
            warns.append(f"发现 {total_bad_geom} 个空几何要素 (null={n_null_geom}, empty={n_empty_geom})")
            recs.append("建议删除空几何要素")

        if gdf.crs and gdf.crs.is_geographic:
            valid_geom = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            if len(valid_geom) > 0:
                bounds = valid_geom.geometry.bounds
                near_origin = (bounds["minx"].abs() < 0.01) & (bounds["miny"].abs() < 0.01)
                n_origin = int(near_origin.sum())
                if n_origin > 0:
                    warns.append(f"发现 {n_origin} 个要素坐标接近原点 (0,0)，疑似异常")
                    recs.append("请核查坐标为(0,0)附近的要素是否为数据错误")

                out_of_bounds = (
                    (bounds["minx"] < -180) | (bounds["maxx"] > 180)
                    | (bounds["miny"] < -90) | (bounds["maxy"] > 90)
                )
                n_oob = int(out_of_bounds.sum())
                if n_oob > 0:
                    warns.append(f"发现 {n_oob} 个要素坐标超出经纬度范围 (-180~180, -90~90)")
                    recs.append("请核查坐标系是否正确设置")

        n_dup = 0
        try:
            wkt_series = gdf.geometry.dropna().apply(lambda g: g.wkt if not g.is_empty else None)
            n_dup = int(wkt_series.duplicated().sum())
            if n_dup > 0:
                warns.append(f"发现 {n_dup} 个重复几何要素")
                recs.append("建议去重")
        except Exception:
            pass

        geom_types = gdf.geometry.dropna().geom_type.unique().tolist()
        if len(geom_types) > 1:
            warns.append(f"数据包含混合几何类型: {geom_types}")
            recs.append("建议统一几何类型后再分析")

        # Geocoding confidence check
        gc_conf_counts = None
        if "gc_match" in gdf.columns:
            gc_conf_counts = gdf["gc_match"].value_counts().to_dict()
            low_conf = gc_conf_counts.get("低", 0) + gc_conf_counts.get("未知", 0)
            if low_conf > 0:
                warns.append(f"地理编码置信度: {gc_conf_counts}，其中 {low_conf} 条低置信/未知")
                recs.append("低置信度编码结果可能定位不准确，建议人工核查")

        numeric_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
        attr_stats = {}
        for col in numeric_cols[:10]:
            if not gdf[col].isna().all():
                attr_stats[col] = {
                    "min": float(gdf[col].min()),
                    "max": float(gdf[col].max()),
                    "mean": round(float(gdf[col].mean()), 4),
                }

        severity = "pass"
        if warns:
            severity = "warning"
        if total_bad_geom > len(gdf) * 0.1:
            severity = "critical"

        summary = {
            "num_features": len(gdf),
            "crs": str(gdf.crs),
            "geometry_types": geom_types,
            "file_type": os.path.splitext(file_path)[1],
            "columns": list(gdf.columns),
            "null_values_per_column": null_cols if null_cols else "无",
            "null_empty_geometries": total_bad_geom,
            "duplicate_geometries": n_dup,
            "attribute_statistics": attr_stats if attr_stats else "无数值列",
            "data_health": {
                "severity": severity,
                "warnings": warns if warns else ["数据质量良好"],
                "recommendations": recs if recs else ["可直接进行分析"],
                "ready_for_analysis": not warns,
            },
            "geocoding_confidence": gc_conf_counts,
            "file_path": _resolve_path(file_path),
        }
        return {"status": "success", "summary": summary}
    except FileNotFoundError:
        return {"status": "error", "error_message": f"文件未找到: {file_path}",
                "recovery": "请先调用 search_data_assets 或 list_user_files 检查可用文件"}
    except Exception as e:
        err = str(e)
        recovery = ""
        if "No such file" in err or "does not exist" in err:
            recovery = "请先调用 search_data_assets 或 list_user_files 检查可用文件"
        elif "CRS" in err or "crs" in err:
            recovery = "请先调用 reproject_spatial_data 统一坐标系后再试"
        elif "geometry" in err.lower():
            recovery = "数据可能缺少有效几何列，请检查文件格式是否为空间数据"
        return {"status": "error", "error_message": err,
                **({"recovery": recovery} if recovery else {})}


def reproject_spatial_data(file_path: str, target_crs: str = "EPSG:3857") -> str:
    """重投影。"""
    try:
        gdf = _load_spatial_data(file_path).to_crs(target_crs)
        out = _generate_output_path("reprojected", "shp")
        gdf.to_file(out); return out
    except Exception as e: return f"Error: {str(e)}"


def engineer_spatial_features(file_path: str) -> dict[str, any]:
    """特征工程。"""
    try:
        gdf = _load_spatial_data(file_path)
        gdf_calc = gdf.to_crs(epsg=3857) if gdf.crs and gdf.crs.is_geographic else gdf
        area = gdf_calc.geometry.area
        gdf['S_Idx'] = gdf_calc.geometry.length / (2 * np.sqrt(np.pi * area))
        gdf['CX'] = gdf_calc.geometry.centroid.x
        gdf['CY'] = gdf_calc.geometry.centroid.y
        out = _generate_output_path("enhanced", "shp")
        gdf.to_file(out)
        return {"status": "success", "output_path": out, "message": "Standardized to SHP with features"}
    except Exception as e: return {"status": "error", "error_message": str(e)}


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    describe_geodataframe,
    reproject_spatial_data,
    engineer_spatial_features,
    check_topology,
    check_field_standards,
    check_consistency,
]


class ExplorationToolset(BaseToolset):
    """Data exploration, profiling, and quality audit tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
