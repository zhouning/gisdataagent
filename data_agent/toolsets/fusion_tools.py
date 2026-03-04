"""Fusion toolset: multi-modal data fusion tools for ADK agents."""
import os
import json
import traceback

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import fusion_engine
from ..gis_processors import _resolve_path


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def profile_fusion_sources(file_paths: str) -> str:
    """分析多个数据源的特征画像，包括数据类型、坐标系、字段信息和统计摘要。

    Args:
        file_paths: 逗号分隔的文件路径列表 (如: "data1.geojson, data2.csv")

    Returns:
        每个数据源的详细画像信息。
    """
    try:
        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        if not paths:
            return "Error: 请提供至少一个文件路径。"

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
                info["column_details"] = src.columns[:15]  # cap display
            if src.stats:
                info["stats"] = {k: v for k, v in list(src.stats.items())[:10]}
            profiles.append(info)

        return json.dumps(profiles, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def assess_fusion_compatibility(file_paths: str) -> str:
    """评估多个数据源的融合兼容性，包括坐标系一致性、空间重叠度、字段匹配和推荐策略。

    Args:
        file_paths: 逗号分隔的文件路径列表

    Returns:
        兼容性评估报告：CRS一致性、空间重叠IoU、语义字段匹配、推荐融合策略。
    """
    try:
        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        if len(paths) < 2:
            return "Error: 至少需要2个数据源进行兼容性评估。"

        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))

        report = fusion_engine.assess_compatibility(sources)

        result = {
            "crs_compatible": report.crs_compatible,
            "spatial_overlap_iou": report.spatial_overlap_iou,
            "field_matches": report.field_matches,
            "overall_score": report.overall_score,
            "recommended_strategies": report.recommended_strategies,
            "warnings": report.warnings,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def fuse_datasets(
    file_paths: str,
    strategy: str = "auto",
    join_column: str = "",
    spatial_predicate: str = "intersects",
) -> str:
    """融合多个数据源。支持空间连接、属性合并、分区统计等10种策略。

    Args:
        file_paths: 逗号分隔的文件路径列表
        strategy: 融合策略 (auto/spatial_join/attribute_join/zonal_statistics/
                  point_sampling/band_stack/overlay/nearest_join/
                  time_snapshot/height_assign/raster_vectorize)
        join_column: 属性连接的键字段 (attribute_join时需要)
        spatial_predicate: 空间谓词 (intersects/contains/within, 用于spatial_join)

    Returns:
        融合结果摘要，包含输出路径、行列数、质量评分和对齐日志。
    """
    try:
        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        if len(paths) < 2:
            return "Error: 至少需要2个数据源进行融合。"

        # Profile sources
        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))

        # Assess compatibility
        report = fusion_engine.assess_compatibility(sources)

        # Align
        aligned, align_log = fusion_engine.align_sources(sources, report)

        # Build params
        params = {"spatial_predicate": spatial_predicate}
        if join_column:
            params["join_column"] = join_column

        # Execute
        result = fusion_engine.execute_fusion(aligned, strategy, sources, params)

        # Record operation
        fusion_engine.record_operation(
            sources=sources,
            strategy=result.strategy_used,
            output_path=result.output_path,
            quality_score=result.quality_score,
            quality_warnings=result.quality_warnings,
            duration_s=result.duration_s,
            params=params,
        )

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
        return f"Error: {e}"


def validate_fusion_quality(file_path: str) -> str:
    """验证融合结果的数据质量，检查完整性、空值率和几何有效性。

    Args:
        file_path: 融合输出文件路径

    Returns:
        质量评分(0-1)、问题列表和修复建议。
    """
    try:
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

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    profile_fusion_sources,
    assess_fusion_compatibility,
    fuse_datasets,
    validate_fusion_quality,
]


class FusionToolset(BaseToolset):
    """Multi-modal data fusion toolset — profile, assess, fuse, validate."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
