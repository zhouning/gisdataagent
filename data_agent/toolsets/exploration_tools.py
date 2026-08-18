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
    list_fgdb_layers,
    list_dxf_layers,
    _generate_output_path,
    _resolve_path,
)
from ..doc_auditor import check_consistency
from ..i18n import t as translate


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def describe_geodataframe(file_path: str) -> dict:
    """数据探查画像：全面质量预检。"""
    try:
        gdf = _load_spatial_data(file_path)
        warns, recs = [], []

        if not gdf.crs:
            warns.append(translate("exploration.missing_crs"))
            recs.append(translate("exploration.set_crs"))
        elif gdf.crs.is_geographic:
            warns.append(translate("exploration.geographic_crs", crs=gdf.crs))
            recs.append(translate("exploration.reproject_recommended"))

        null_cols = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            n_null = int(gdf[col].isna().sum())
            if n_null > 0:
                null_cols[col] = n_null
        if null_cols:
            worst = max(null_cols, key=null_cols.get)
            warns.append(translate(
                "exploration.null_columns",
                count=len(null_cols),
                worst=worst,
                nulls=null_cols[worst],
            ))
            recs.append(translate("exploration.clean_nulls"))

        n_null_geom = int(gdf.geometry.isna().sum())
        n_empty_geom = int(gdf.geometry.is_empty.sum()) if n_null_geom < len(gdf) else 0
        total_bad_geom = n_null_geom + n_empty_geom
        if total_bad_geom > 0:
            warns.append(translate(
                "exploration.bad_geometries",
                total=total_bad_geom,
                nulls=n_null_geom,
                empty=n_empty_geom,
            ))
            recs.append(translate("exploration.remove_bad_geometries"))

        if gdf.crs and gdf.crs.is_geographic:
            valid_geom = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            if len(valid_geom) > 0:
                bounds = valid_geom.geometry.bounds
                near_origin = (bounds["minx"].abs() < 0.01) & (bounds["miny"].abs() < 0.01)
                n_origin = int(near_origin.sum())
                if n_origin > 0:
                    warns.append(translate("exploration.near_origin", count=n_origin))
                    recs.append(translate("exploration.check_origin"))

                out_of_bounds = (
                    (bounds["minx"] < -180) | (bounds["maxx"] > 180)
                    | (bounds["miny"] < -90) | (bounds["maxy"] > 90)
                )
                n_oob = int(out_of_bounds.sum())
                if n_oob > 0:
                    warns.append(translate("exploration.out_of_bounds", count=n_oob))
                    recs.append(translate("exploration.check_crs"))

        n_dup = 0
        try:
            wkt_series = gdf.geometry.dropna().apply(lambda g: g.wkt if not g.is_empty else None)
            n_dup = int(wkt_series.duplicated().sum())
            if n_dup > 0:
                warns.append(translate("exploration.duplicate_geometries", count=n_dup))
                recs.append(translate("exploration.deduplicate"))
        except Exception:
            pass

        geom_types = gdf.geometry.dropna().geom_type.unique().tolist()
        if len(geom_types) > 1:
            warns.append(translate("exploration.mixed_geometry", types=geom_types))
            recs.append(translate("exploration.normalize_geometry"))

        # Geocoding confidence check
        gc_conf_counts = None
        if "gc_match" in gdf.columns:
            gc_conf_counts = gdf["gc_match"].value_counts().to_dict()
            low_conf = gc_conf_counts.get("低", 0) + gc_conf_counts.get("未知", 0)
            if low_conf > 0:
                warns.append(translate(
                    "exploration.geocoding_confidence",
                    counts=gc_conf_counts,
                    low_count=low_conf,
                ))
                recs.append(translate("exploration.review_geocoding"))

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
            "null_values_per_column": null_cols if null_cols else translate("exploration.none"),
            "null_empty_geometries": total_bad_geom,
            "duplicate_geometries": n_dup,
            "attribute_statistics": attr_stats if attr_stats else translate(
                "exploration.no_numeric_columns"),
            "data_health": {
                "severity": severity,
                "warnings": warns if warns else [translate("exploration.quality_good")],
                "recommendations": recs if recs else [translate("exploration.ready")],
                "ready_for_analysis": not warns,
            },
            "geocoding_confidence": gc_conf_counts,
            "file_path": _resolve_path(file_path),
        }
        return {"status": "success", "summary": summary}
    except FileNotFoundError:
        return {
            "status": "error",
            "error_message": translate("exploration.file_not_found", path=file_path),
            "recovery": translate("exploration.recovery_files"),
        }
    except Exception as e:
        err = str(e)
        recovery = ""
        if "No such file" in err or "does not exist" in err:
            recovery = translate("exploration.recovery_files")
        elif "CRS" in err or "crs" in err:
            recovery = translate("exploration.recovery_crs")
        elif "geometry" in err.lower():
            recovery = translate("exploration.recovery_geometry")
        return {"status": "error", "error_message": translate(
                    "exploration.profile_failed", error=err),
                **({"recovery": recovery} if recovery else {})}


def reproject_spatial_data(file_path: str, target_crs: str = "EPSG:3857") -> str:
    """重投影。"""
    try:
        gdf = _load_spatial_data(file_path).to_crs(target_crs)
        out = _generate_output_path("reprojected", "shp")
        gdf.to_file(out); return out
    except Exception as e:
        return translate("exploration.reproject_failed", error=e)


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
        return {
            "status": "success",
            "output_path": out,
            "message": translate("exploration.features_engineered"),
        }
    except Exception as e:
        return {"status": "error", "error_message": translate(
            "exploration.feature_engineering_failed", error=e)}


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

def batch_profile_datasets(directory_path: str, standard_id: str = "") -> str:
    """批量探查目录下所有空间数据文件，生成汇总报告。支持 SHP/GeoJSON/GPKG/FGDB/CSV/Excel/KML。

    Args:
        directory_path: 数据目录路径。
        standard_id: 可选标准ID（如 "dltb_2023"），探查时同时进行标准对照。

    Returns:
        JSON格式的汇总报告：文件总数、总记录数、格式分布、CRS 分布、关键问题列表。
    """
    import json as _json

    SPATIAL_EXTS = {'.shp', '.geojson', '.gpkg', '.gdb', '.csv', '.xlsx', '.xls', '.kml', '.kmz', '.dxf'}

    try:
        resolved = _resolve_path(directory_path)
        if not os.path.isdir(resolved):
            return _json.dumps({"status": "error", "message": translate(
                                   "exploration.directory_not_found",
                                   path=directory_path,
                               )},
                               ensure_ascii=False)

        files = []
        for root, dirs, fnames in os.walk(resolved):
            # Detect .gdb directories
            for d in dirs:
                if d.endswith('.gdb'):
                    files.append(os.path.join(root, d))
            for fn in fnames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in SPATIAL_EXTS and ext != '.gdb':
                    # Skip .shp sidecars
                    if ext in ('.dbf', '.shx', '.prj', '.cpg'):
                        continue
                    files.append(os.path.join(root, fn))

        if not files:
            return _json.dumps({
                "status": "ok",
                "message": translate("exploration.directory_empty"),
                "file_count": 0,
            },
                               ensure_ascii=False)

        profiles = []
        total_records = 0
        format_dist: dict[str, int] = {}
        crs_dist: dict[str, int] = {}
        issues = []

        for fp in files:
            ext = os.path.splitext(fp)[1].lower() or ".gdb"
            format_dist[ext] = format_dist.get(ext, 0) + 1
            try:
                result = describe_geodataframe(fp)
                if result.get("status") == "success":
                    summ = result.get("summary", {})
                    nf = summ.get("num_features", 0)
                    total_records += nf
                    crs = summ.get("crs", "Unknown")
                    crs_dist[crs] = crs_dist.get(crs, 0) + 1
                    entry = {
                        "file": os.path.basename(fp), "format": ext,
                        "features": nf, "crs": crs,
                        "severity": summ.get("data_health", {}).get("severity", "unknown"),
                    }
                    # Optional standard check
                    if standard_id:
                        std_result = check_field_standards(fp, standard_id)
                        entry["compliance_rate"] = std_result.get("compliance_rate", 0)
                        entry["missing_mandatory"] = len(std_result.get("missing_mandatory", []))
                    profiles.append(entry)

                    # Collect issues
                    warns = summ.get("data_health", {}).get("warnings", [])
                    for w in warns[:3]:
                        issues.append({"file": os.path.basename(fp), "issue": w})
                else:
                    profiles.append({
                        "file": os.path.basename(fp),
                        "format": ext,
                        "error": result.get(
                            "error_message",
                            translate("exploration.load_failed"),
                        ),
                    })
            except Exception as e:
                profiles.append({"file": os.path.basename(fp), "format": ext, "error": str(e)[:100]})

        summary = {
            "file_count": len(files),
            "total_records": total_records,
            "format_distribution": format_dist,
            "crs_distribution": crs_dist,
            "issue_count": len(issues),
        }
        if standard_id:
            rates = [p.get("compliance_rate", 0) for p in profiles if "compliance_rate" in p]
            summary["avg_compliance_rate"] = round(sum(rates) / len(rates), 1) if rates else 0

        return _json.dumps({"status": "ok", "summary": summary, "files": profiles, "issues": issues[:20]},
                           ensure_ascii=False, default=str)
    except Exception as e:
        return _json.dumps({"status": "error", "message": translate(
                               "exploration.batch_failed", error=e)}, ensure_ascii=False)


_ALL_FUNCS = [
    describe_geodataframe,
    reproject_spatial_data,
    engineer_spatial_features,
    check_topology,
    check_field_standards,
    check_consistency,
    list_fgdb_layers,
    batch_profile_datasets,
    list_dxf_layers,
]


class ExplorationToolset(BaseToolset):
    """Data exploration, profiling, and quality audit tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
