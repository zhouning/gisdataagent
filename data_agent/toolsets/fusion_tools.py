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
    enable_temporal: str = "auto",
    conflict_strategy: str = "",
    enable_explainability: str = "true",
    use_llm_semantic: str = "false",
) -> str:
    """融合多个数据源。支持空间连接、属性合并、分区统计等10种策略，含v2增强能力。

    Args:
        file_paths: 逗号分隔的文件路径列表
        strategy: 融合策略 (auto/spatial_join/attribute_join/zonal_statistics/
                  point_sampling/band_stack/overlay/nearest_join/
                  time_snapshot/height_assign/raster_vectorize)。
                  auto: 根据数据特征和用户意图自动选择最佳策略。
        join_column: 属性连接的键字段 (attribute_join时需要)
        spatial_predicate: 空间谓词 (intersects/contains/within, 用于spatial_join)
        user_hint: 用户意图描述（如"按人口密度筛选"）
        enable_temporal: 时序对齐 (auto/true/false)。auto=自动检测时间列并对齐，
                        true=强制启用，false=关闭。
        conflict_strategy: 冲突解决策略。留空=不启用。可选:
                          source_priority(源优先级)/latest_wins(最新值优先)/
                          voting(投票法)/llm_arbitration(LLM仲裁)。
        enable_explainability: 可解释性注解 (true/false, 默认true)。启用后在融合结果中
                              添加 _fusion_confidence、_fusion_sources 等字段，并生成质量热力图。
        use_llm_semantic: LLM增强语义匹配 (true/false, 默认false)。启用后使用Gemini
                         深度理解字段语义，提升跨源字段匹配准确度。

    Returns:
        融合结果摘要，包含输出路径、行列数、质量评分、对齐日志、时序日志、冲突摘要和可解释性路径。
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if len(paths) < 2:
        return "Error: 至少需要2个数据源进行融合。"

    params = {"spatial_predicate": spatial_predicate}
    if join_column:
        params["join_column"] = join_column

    explainability = enable_explainability.lower() == "true"
    llm_semantic = use_llm_semantic.lower() == "true"

    def _run():
        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))
        report = fusion_engine.assess_compatibility(
            sources, use_llm_schema=llm_semantic,
        )
        aligned, align_log = fusion_engine.align_sources(sources, report)

        # v2: Build temporal config
        temporal_config = None
        temporal_flag = enable_temporal.lower()
        if temporal_flag == "true":
            temporal_config = {"method": "linear"}
        elif temporal_flag == "auto":
            from data_agent.fusion.temporal import TemporalAligner
            ta = TemporalAligner()
            for _, data_obj in aligned:
                if hasattr(data_obj, "columns"):
                    detected = ta.detect_temporal_columns(data_obj)
                    if detected:
                        temporal_config = {
                            "time_column": detected[0],
                            "method": "linear",
                        }
                        break

        # v2: Build conflict config
        conflict_config = None
        if conflict_strategy:
            conflict_config = {"strategy": conflict_strategy}

        result = fusion_engine.execute_fusion(
            aligned, strategy, sources, params,
            report=report, user_hint=user_hint,
            temporal_config=temporal_config,
            conflict_config=conflict_config,
            enable_explainability=explainability,
        )
        fusion_engine.record_operation(
            sources=sources,
            strategy=result.strategy_used,
            output_path=result.output_path,
            quality_score=result.quality_score,
            quality_warnings=result.quality_warnings,
            duration_s=result.duration_s,
            params=params,
            temporal_log="\n".join(result.temporal_log) if result.temporal_log else None,
            conflict_log=json.dumps(result.conflict_summary) if result.conflict_summary else None,
            explainability_metadata=(
                {"explainability_path": result.explainability_path}
                if result.explainability_path else None
            ),
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
        # v2 fields
        if result.temporal_log:
            summary["temporal_log"] = result.temporal_log
        if result.conflict_summary:
            summary["conflict_summary"] = result.conflict_summary
        if result.explainability_path:
            summary["explainability_path"] = result.explainability_path
        if result.output_asset_code:
            summary["asset_code"] = result.output_asset_code
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
# v2.0: Document context injection for fusion
# ---------------------------------------------------------------------------


async def inject_document_context(
    document_paths: str,
    fusion_task: str = "",
) -> str:
    """从 PDF/Word/Excel 文档中提取结构化元数据，作为融合的上下文信息。

    可提取：数据来源说明、字段含义、时间范围、坐标系信息、数据质量声明等。
    输出可直接用于融合时的冲突解决源优先级判定。

    Args:
        document_paths: 逗号分隔的文档路径列表 (如: "规划说明.pdf, 数据字典.docx, 统计表.xlsx")
        fusion_task: 融合任务描述（如"城市规划多源数据融合"），帮助LLM聚焦提取相关信息。

    Returns:
        JSON 结构化元数据，包含每个文档的数据来源、时间范围、质量声明等信息。
    """
    paths = [p.strip() for p in document_paths.split(",") if p.strip()]
    if not paths:
        return json.dumps({"status": "error", "message": "请提供至少一个文档路径"})

    async def _extract_and_analyze():
        from ..gis_processors import _resolve_path

        doc_summaries = []
        for p in paths:
            resolved = _resolve_path(p)
            ext = os.path.splitext(resolved)[1].lower()
            text = ""

            try:
                if ext == ".pdf":
                    from ..multimodal import extract_pdf_text
                    text = extract_pdf_text(resolved, max_pages=10)
                elif ext in (".docx", ".doc"):
                    try:
                        import docx
                        doc = docx.Document(resolved)
                        text = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
                    except Exception:
                        text = f"[无法解析Word文档: {os.path.basename(resolved)}]"
                elif ext in (".xlsx", ".xls"):
                    import pandas as pd
                    df = pd.read_excel(resolved, nrows=20)
                    text = f"列名: {list(df.columns)}\n前5行:\n{df.head().to_string()}"
                elif ext == ".csv":
                    import pandas as pd
                    df = pd.read_csv(resolved, nrows=20)
                    text = f"列名: {list(df.columns)}\n前5行:\n{df.head().to_string()}"
                else:
                    text = f"[不支持的文档格式: {ext}]"
            except Exception as e:
                text = f"[读取失败: {e}]"

            # Truncate to 1500 chars per document
            if len(text) > 1500:
                text = text[:1500] + "..."

            doc_summaries.append({
                "file": os.path.basename(resolved),
                "format": ext,
                "text_preview": text[:200],
                "full_text": text,
            })

        # Use Gemini Flash to extract structured metadata from documents
        combined_text = ""
        for ds in doc_summaries:
            combined_text += f"\n--- 文档: {ds['file']} ({ds['format']}) ---\n{ds['full_text']}\n"

        task_context = f"融合任务: {fusion_task}" if fusion_task else "通用数据融合"

        prompt = f"""请从以下文档内容中提取与地理空间数据融合相关的结构化元数据。

{task_context}

{combined_text}

请以JSON格式返回，每个文档一条记录，包含以下字段（如信息不存在则标记为null）：
- file: 文件名
- data_source: 数据来源机构/系统
- description: 数据内容简述（50字以内）
- time_range: 数据时间范围（如 "2020-2024"）
- crs_info: 坐标系信息（如 "CGCS2000/EPSG:4490"）
- field_definitions: 关键字段含义列表（最多10个）
- quality_notes: 数据质量声明
- timeliness: 时效性评分 0-1（越新越高）
- precision: 精度评分 0-1
- completeness: 完整性评分 0-1

仅返回JSON数组，不要其他文字。"""

        try:
            import google.genai as genai
            client = genai.Client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            raw = response.text.strip()
            # Extract JSON from possible markdown code block
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            metadata = json.loads(raw)
        except Exception as e:
            # Fallback: return basic file info without LLM analysis
            metadata = []
            for ds in doc_summaries:
                metadata.append({
                    "file": ds["file"],
                    "data_source": None,
                    "description": ds["text_preview"],
                    "time_range": None,
                    "crs_info": None,
                    "field_definitions": [],
                    "quality_notes": None,
                    "timeliness": 0.5,
                    "precision": 0.5,
                    "completeness": 0.5,
                    "llm_error": str(e),
                })

        return {
            "status": "ok",
            "document_count": len(paths),
            "source_metadata": metadata,
            "usage_hint": "将 source_metadata 中的 timeliness/precision/completeness "
                         "用于融合时的冲突解决权重。",
        }

    try:
        result = await _extract_and_analyze()
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    profile_fusion_sources,
    assess_fusion_compatibility,
    fuse_datasets,
    validate_fusion_quality,
    standardize_timestamps,
    validate_temporal_consistency,
    inject_document_context,
]


class FusionToolset(BaseToolset):
    """Multi-modal data fusion toolset — profile, assess, fuse, validate."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
