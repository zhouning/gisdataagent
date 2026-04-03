"""Fusion toolset: multi-modal data fusion tools for ADK agents.

v7.1: All tool functions are async — CPU-intensive work offloaded to thread pool
via asyncio.to_thread() to avoid blocking the ASGI event loop.
"""
import asyncio
import os
import json
import traceback

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import fusion_engine
from ..gis_processors import _resolve_path


# ---------------------------------------------------------------------------
# Tool functions (async — heavy compute runs in thread pool)
# ---------------------------------------------------------------------------

async def profile_fusion_sources(file_paths: str) -> str:
    """分析多个数据源的特征画像，包括数据类型、坐标系、字段信息和统计摘要。

    Args:
        file_paths: 逗号分隔的文件路径列表 (如: "data1.geojson, data2.csv")

    Returns:
        每个数据源的详细画像信息。
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if not paths:
        return "Error: 请提供至少一个文件路径。"

    def _run():
        profiles = []
        for p in paths:
            resolved = _resolve_path(p)
            src = fusion_engine.profile_source(resolved)
            info = {
                "file": os.path.basename(src.file_path),
                "type": src.data_type,
                "crs": src.crs,
                "rows": src.row_count,
                "columns": len(src.columns),
                "geometry_type": src.geometry_type,
                "bounds": src.bounds,
            }
            if src.band_count:
                info["bands"] = src.band_count
                info["resolution"] = src.resolution
            if src.columns:
                info["column_details"] = src.columns[:15]
            if src.stats:
                info["stats"] = {k: v for k, v in list(src.stats.items())[:10]}
            profiles.append(info)
        return profiles

    try:
        profiles = await asyncio.to_thread(_run)
        return json.dumps(profiles, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


async def assess_fusion_compatibility(
    file_paths: str,
    use_embedding: str = "false",
    use_llm_schema: str = "false",
) -> str:
    """评估多个数据源的融合兼容性，包括坐标系一致性、空间重叠度、字段匹配和推荐策略。

    Args:
        file_paths: 逗号分隔的文件路径列表
        use_embedding: 是否启用Gemini语义嵌入匹配 (true/false, 默认false)
        use_llm_schema: 是否启用LLM全Schema对齐 (true/false, 默认false)。
                       启用后用LLM替代启发式规则做字段映射，准确度更高但增加API调用。

    Returns:
        兼容性评估报告：CRS一致性、空间重叠IoU、语义字段匹配、推荐融合策略。
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if len(paths) < 2:
        return "Error: 至少需要2个数据源进行兼容性评估。"

    embed = use_embedding.lower() == "true"
    llm_schema = use_llm_schema.lower() == "true"

    def _run():
        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))
        report = fusion_engine.assess_compatibility(
            sources, use_embedding=embed, use_llm_schema=llm_schema
        )
        return {
            "crs_compatible": report.crs_compatible,
            "spatial_overlap_iou": report.spatial_overlap_iou,
            "field_matches": report.field_matches,
            "overall_score": report.overall_score,
            "recommended_strategies": report.recommended_strategies,
            "warnings": report.warnings,
        }

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


async def fuse_datasets(
    file_paths: str,
    strategy: str = "auto",
    join_column: str = "",
    spatial_predicate: str = "intersects",
    user_hint: str = "",
) -> str:
    """融合多个数据源。支持空间连接、属性合并、分区统计等10种策略。

    Args:
        file_paths: 逗号分隔的文件路径列表
        strategy: 融合策略 (auto/spatial_join/attribute_join/zonal_statistics/
                  point_sampling/band_stack/overlay/nearest_join/
                  time_snapshot/height_assign/raster_vectorize)。
                  auto: 根据数据特征和用户意图自动选择最佳策略。
        join_column: 属性连接的键字段 (attribute_join时需要)
        spatial_predicate: 空间谓词 (intersects/contains/within, 用于spatial_join)
        user_hint: 用户意图描述（如"按人口密度筛选"）

    Returns:
        融合结果摘要，包含输出路径、行列数、质量评分和对齐日志。
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if len(paths) < 2:
        return "Error: 至少需要2个数据源进行融合。"

    params = {"spatial_predicate": spatial_predicate}
    if join_column:
        params["join_column"] = join_column

    def _run():
        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))
        report = fusion_engine.assess_compatibility(sources)
        aligned, align_log = fusion_engine.align_sources(sources, report)
        result = fusion_engine.execute_fusion(
            aligned, strategy, sources, params,
            report=report, user_hint=user_hint,
        )
        fusion_engine.record_operation(
            sources=sources,
            strategy=result.strategy_used,
            output_path=result.output_path,
            quality_score=result.quality_score,
            quality_warnings=result.quality_warnings,
            duration_s=result.duration_s,
            params=params,
        )
        return result, align_log

    try:
        result, align_log = await asyncio.to_thread(_run)
        summary = {
            "output_path": result.output_path,
            "strategy_used": result.strategy_used,
            "rows": result.row_count,
            "columns": result.column_count,
            "quality_score": result.quality_score,
            "quality_warnings": result.quality_warnings,
            "alignment_log": result.alignment_log + align_log,
            "duration_s": result.duration_s,
        }
        return json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        err = str(e)
        recovery = ""
        if "No such file" in err or "not found" in err.lower() or "does not exist" in err:
            recovery = " Recovery: 请先调用 search_data_assets 或 list_user_files 检查可用文件"
        elif "CRS" in err or "crs" in err or "坐标" in err:
            recovery = " Recovery: 两个数据源坐标系不一致，请先调用 reproject_spatial_data 统一坐标系"
        elif "column" in err.lower() or "KeyError" in err or "字段" in err:
            recovery = " Recovery: 连接字段不存在，请先调用 describe_geodataframe 查看可用字段"
        elif "empty" in err.lower() or "0 records" in err:
            recovery = " Recovery: 数据为空，请检查输入文件或筛选条件是否过于严格"
        return f"Error: {e}{recovery}"


async def validate_fusion_quality(file_path: str) -> str:
    """验证融合结果的数据质量，检查完整性、空值率和几何有效性。

    Args:
        file_path: 融合输出文件路径

    Returns:
        质量评分(0-1)、问题列表和修复建议。
    """
    def _run():
        resolved = _resolve_path(file_path)
        quality = fusion_engine.validate_quality(resolved)
        result = {
            "file": os.path.basename(resolved),
            "quality_score": quality["score"],
            "warnings": quality["warnings"],
            "status": "GOOD" if quality["score"] >= 0.8 else
                      "FAIR" if quality["score"] >= 0.5 else "POOR",
        }
        if quality["score"] < 0.8 and quality["warnings"]:
            suggestions = []
            for w in quality["warnings"]:
                if "null" in w.lower():
                    suggestions.append("考虑使用 fillna 或插值填补空值")
                if "invalid geometr" in w.lower():
                    suggestions.append("使用 buffer(0) 修复无效几何")
                if "empty" in w.lower():
                    suggestions.append("检查输入数据的空间范围是否重叠")
            result["suggestions"] = suggestions
        return result

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------
# v2.0: Temporal Alignment tools
# ---------------------------------------------------------------------------


async def standardize_timestamps(
    file_path: str,
    time_column: str,
    target_tz: str = "UTC",
) -> str:
    """标准化时间戳格式。将异构时间格式统一为 UTC ISO8601。

    Args:
        file_path: 输入文件路径（GeoJSON/Shapefile/CSV）
        time_column: 时间列名
        target_tz: 目标时区（默认UTC）

    Returns:
        JSON 标准化报告，包含输出文件路径
    """
    def _run():
        import geopandas as gpd
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.read_file(file_path)
        result = ta.standardize_timestamps(gdf, time_column, target_tz)
        report = ta.validate_temporal_consistency(result)
        from data_agent.gis_processors import _generate_output_path
        out = _generate_output_path("temporal_standardized", "geojson")
        result.to_file(out, driver="GeoJSON")
        return {"status": "ok", "output_path": out, "consistency": report}

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def validate_temporal_consistency(
    file_path: str,
    time_column: str = "",
) -> str:
    """验证数据集的时序一致性。检测空值、重复、间断和乱序。

    Args:
        file_path: 输入文件路径
        time_column: 时间列名（为空则自动检测）

    Returns:
        JSON 时序一致性报告
    """
    def _run():
        import geopandas as gpd
        from data_agent.fusion.temporal import TemporalAligner
        ta = TemporalAligner()
        gdf = gpd.read_file(file_path)
        if not time_column:
            detected = ta.detect_temporal_columns(gdf)
            if not detected:
                return {"status": "error", "message": "未检测到时间列"}
            col = detected[0]
        else:
            col = time_column
        standardized = ta.standardize_timestamps(gdf, col)
        report = ta.validate_temporal_consistency(standardized)
        report["detected_column"] = col
        report["status"] = "ok"
        return report

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    profile_fusion_sources,
    assess_fusion_compatibility,
    fuse_datasets,
    validate_fusion_quality,
    standardize_timestamps,
    validate_temporal_consistency,
]


class FusionToolset(BaseToolset):
    """Multi-modal data fusion toolset — profile, assess, fuse, validate."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
