"""Fusion toolset: multi-modal data fusion tools for ADK agents.

v7.1: All tool functions are async — CPU-intensive work offloaded to thread pool
via asyncio.to_thread() to avoid blocking the ASGI event loop.
"""
import asyncio
from copy import deepcopy
import os
import json
import traceback
from pathlib import Path
from urllib.parse import urlparse

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import fusion_engine
from ..gis_processors import _resolve_path
from ..i18n import t as translate


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
        return translate("fusion.file_required")

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
        return translate("fusion.profile_failed", error=e)


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
        return translate("fusion.assessment_sources_required")

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
        return translate("fusion.assessment_failed", error=e)


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
    semantic_product: str = "true",
    document_context: str = "",
) -> str:
    """融合多个数据源。支持空间连接、属性合并、分区统计等10种策略，含v2增强能力。

    document_context accepts JSON returned by inject_document_context and uses it
    as semantic field-mapping evidence.

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
        semantic_product: 语义融合产品 (true/false, 默认true)。启用后生成本体增强字段、
                          AI-ready chunks 和 .semantic.json 产品清单。

    Returns:
        融合结果摘要，包含输出路径、行列数、质量评分、对齐日志、时序日志、冲突摘要和可解释性路径。
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if len(paths) < 2:
        return translate("fusion.sources_required")

    params = {"spatial_predicate": spatial_predicate}
    if join_column:
        params["join_column"] = join_column

    explainability = enable_explainability.lower() == "true"
    llm_semantic = use_llm_semantic.lower() == "true"
    semantic_product_enabled = semantic_product.lower() in ("1", "true", "yes", "on")
    document_context_payload = None
    if document_context.strip():
        try:
            document_context_payload = json.loads(document_context)
        except json.JSONDecodeError as e:
            return translate("fusion.invalid_document_context", error=e)

    def _run():
        sources = []
        for p in paths:
            resolved = _resolve_path(p)
            sources.append(fusion_engine.profile_source(resolved))

        semantic_config = None
        if semantic_product_enabled:
            semantic_config = {
                "enabled": True,
                "use_ontology": True,
                "derive_fields": True,
                "infer_fields": True,
                "feature_sample_limit": 25,
                "ai_chunks": True,
            }
            if document_context_payload is not None:
                semantic_config["document_context"] = document_context_payload

        report = fusion_engine.assess_compatibility(
            sources,
            use_embedding=llm_semantic,
            use_llm_schema=llm_semantic,
            use_ontology=semantic_config is not None,
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
            semantic_config=semantic_config,
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
        if result.semantic_product_path:
            summary["semantic_product_path"] = result.semantic_product_path
            summary["semantic_summary"] = result.semantic_summary
            summary["derived_fields"] = result.derived_fields
            summary["inferred_fields"] = result.inferred_fields
        return json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        err = str(e)
        recovery = ""
        if "No such file" in err or "not found" in err.lower() or "does not exist" in err:
            recovery = translate("fusion.recovery_files")
        elif "CRS" in err or "crs" in err or "坐标" in err:
            recovery = translate("fusion.recovery_crs")
        elif "column" in err.lower() or "KeyError" in err or "字段" in err:
            recovery = translate("fusion.recovery_column")
        elif "empty" in err.lower() or "0 records" in err:
            recovery = translate("fusion.recovery_empty")
        return translate("fusion.fuse_failed", error=e, recovery=recovery)


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
                    suggestions.append(translate("fusion.suggest_fill_nulls"))
                if "invalid geometr" in w.lower():
                    suggestions.append(translate("fusion.suggest_fix_geometry"))
                if "empty" in w.lower():
                    suggestions.append(translate("fusion.suggest_check_overlap"))
            result["suggestions"] = suggestions
        return result

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return translate("fusion.quality_failed", error=e)


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
        return json.dumps({
            "status": "error",
            "message": translate("fusion.temporal_standardize_failed", error=e),
        }, ensure_ascii=False)


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
                return {
                    "status": "error",
                    "message": translate("fusion.temporal_column_missing"),
                }
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
        return json.dumps({
            "status": "error",
            "message": translate("fusion.temporal_validate_failed", error=e),
        }, ensure_ascii=False)


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
        return json.dumps({
            "status": "error",
            "message": translate("fusion.document_required"),
        }, ensure_ascii=False)

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
                        text = translate(
                            "fusion.word_unreadable",
                            file=os.path.basename(resolved),
                        )
                elif ext in (".xlsx", ".xls"):
                    import pandas as pd
                    df = pd.read_excel(resolved, nrows=20)
                    text = translate(
                        "fusion.tabular_preview",
                        columns=list(df.columns),
                        preview=df.head().to_string(),
                    )
                elif ext == ".csv":
                    import pandas as pd
                    df = pd.read_csv(resolved, nrows=20)
                    text = translate(
                        "fusion.tabular_preview",
                        columns=list(df.columns),
                        preview=df.head().to_string(),
                    )
                else:
                    text = translate("fusion.unsupported_document", extension=ext)
            except Exception as e:
                text = translate("fusion.document_read_failed", error=e)

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
            combined_text += translate(
                "fusion.document_section",
                file=ds["file"],
                format=ds["format"],
                content=ds["full_text"],
            )

        task_context = fusion_task or translate("fusion.general_task")
        prompt = translate(
            "fusion.document_prompt",
            task_context=task_context,
            content=combined_text,
        )

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
            "usage_hint": translate("fusion.document_usage_hint"),
        }

    try:
        result = await _extract_and_analyze()
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "status": "error",
            "message": translate("fusion.document_context_failed", error=e),
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------


async def plan_semantic_product_publish(
    manifest_json: str = "",
    manifest_path: str = "",
    targets: str = "iceberg,stac,lancedb",
    iceberg_catalog: str = "",
    iceberg_namespace: str = "",
    iceberg_table: str = "",
    iceberg_warehouse_uri: str = "",
    iceberg_object_store: str = "s3",
    iceberg_spatial_engine: str = "sedona",
    iceberg_partition_by: str = "",
    stac_collection: str = "",
    stac_catalog_uri: str = "",
    stac_item_datetime: str = "",
    vector_target: str = "lancedb",
    vector_collection: str = "mmfe_semantic_products",
    embedding_model: str = "",
    use_lakehouse_env_defaults: str = "true",
    publish_environment: str = "production",
    require_production_ready: str = "auto",
    iceberg_publisher_configured: str = "false",
    stac_publisher_configured: str = "false",
    vector_publisher_configured: str = "false",
    embedder_configured: str = "false",
) -> str:
    """Build a dry-run MMFE semantic product publish plan without executing backends.

    Args:
        manifest_json: Semantic product manifest JSON. Used before manifest_path when provided.
        manifest_path: Path to a `.semantic.json` manifest when manifest_json is empty.
        targets: Comma-separated publish targets: iceberg, stac, pgvector, lancedb.
        iceberg_catalog: Iceberg catalog name for the authoritative analytical lakehouse.
        iceberg_namespace: Iceberg namespace/database.
        iceberg_table: Iceberg table name.
        iceberg_warehouse_uri: S3-backed Iceberg warehouse URI.
        iceberg_object_store: Object store type; currently s3.
        iceberg_spatial_engine: Spatial compute engine; sedona or none.
        iceberg_partition_by: Comma-separated Iceberg partition hints.
        stac_collection: STAC collection for discovery catalog publishing.
        stac_catalog_uri: STAC catalog or API base URI.
        stac_item_datetime: Optional STAC item datetime.
        vector_target: Vector target used when targets contains `vector`.
        vector_collection: pgvector/LanceDB collection or table grouping name.
        embedding_model: Embedding model identifier for vector publish specs.
        use_lakehouse_env_defaults: true to fill missing Iceberg/STAC values
            from MMFE_LAKEHOUSE_* and AWS_* environment variables.
        publish_environment: production, validation, or development.
        require_production_ready: true/false/auto. auto requires production
            readiness only when publish_environment=production.
        iceberg_publisher_configured: true when an Iceberg publisher adapter is configured.
        stac_publisher_configured: true when a STAC publisher adapter is configured.
        vector_publisher_configured: true when a vector publisher adapter is configured.
        embedder_configured: true when an embedding adapter is configured.

    Returns:
        JSON dry-run plan with target specs, dependency edges, validation errors,
        and adapter configuration flags.
    """
    try:
        manifest = await asyncio.to_thread(_load_semantic_manifest, manifest_json, manifest_path)
        manifest_for_plan = await asyncio.to_thread(
            _attach_semantic_diagnostic_for_publish_plan,
            manifest,
            manifest_json,
            manifest_path,
        )
        requested_targets = _parse_publish_targets(targets, vector_target=vector_target)
        env_defaults = (
            fusion_engine.build_lakehouse_publish_defaults()
            if _truthy(use_lakehouse_env_defaults)
            else {}
        )
        env_defaults = _normalize_lakehouse_env_defaults(
            env_defaults,
            iceberg_warehouse_uri=iceberg_warehouse_uri,
            stac_catalog_uri=stac_catalog_uri,
        )
        default_iceberg = env_defaults.get("iceberg", {}) if isinstance(env_defaults, dict) else {}
        default_stac = env_defaults.get("stac", {}) if isinstance(env_defaults, dict) else {}

        iceberg_config = {
            "catalog": iceberg_catalog or default_iceberg.get("catalog", ""),
            "namespace": iceberg_namespace or default_iceberg.get("namespace", ""),
            "table": iceberg_table or default_iceberg.get("table", ""),
            "warehouse_uri": iceberg_warehouse_uri or default_iceberg.get("warehouse_uri", ""),
            "object_store": iceberg_object_store or default_iceberg.get("object_store", "s3"),
            "spatial_engine": iceberg_spatial_engine or default_iceberg.get("spatial_engine", "sedona"),
            "partition_by": _parse_csv_list(iceberg_partition_by) or list(default_iceberg.get("partition_by") or []),
            "metadata": default_iceberg.get("metadata"),
            "publisher": object() if _truthy(iceberg_publisher_configured) else None,
        }
        stac_config = {
            "collection": stac_collection or default_stac.get("collection", ""),
            "catalog_uri": stac_catalog_uri or default_stac.get("catalog_uri", ""),
            "metadata": default_stac.get("metadata"),
            "publisher": object() if _truthy(stac_publisher_configured) else None,
        }
        if stac_item_datetime:
            stac_config["item_datetime"] = stac_item_datetime

        vector_config = {
            "collection": vector_collection,
            "embedding_model": embedding_model or None,
            "embedder": object() if _truthy(embedder_configured) else None,
            "publisher": object() if _truthy(vector_publisher_configured) else None,
        }

        plan = fusion_engine.build_semantic_product_publish_plan(
            manifest_for_plan,
            targets=requested_targets,
            iceberg=iceberg_config,
            stac=stac_config,
            vector=vector_config,
            publish_environment=publish_environment,
            require_production_ready=_parse_optional_bool(require_production_ready),
        )
        result = {
            "status": "ok",
            "summary": _publish_plan_summary(plan),
            "plan": plan,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def preflight_mmfe_lakehouse_infrastructure(
    config_json: str = "",
    environment: str = "development",
    env_json: str = "",
) -> str:
    """Build an MMFE lakehouse infrastructure preflight report without executing backends.

    Args:
        config_json: Optional full lakehouse config JSON with object_store,
            iceberg, stac, and sedona_spark_conf sections. When provided it is
            used directly instead of environment defaults.
        environment: production, validation, or development. Production fails
            local MinIO endpoints and local default credentials.
        env_json: Optional JSON object of environment-variable overrides used
            to build defaults when config_json is empty.

    Returns:
        JSON containing status, summary, errors, warnings, and the
        mmfe.infrastructure_preflight.v1 contract.
    """
    try:
        if config_json.strip():
            config = _parse_json_object(config_json, "config_json")
        else:
            env = _parse_string_mapping_json(env_json, "env_json") if env_json.strip() else None
            config = fusion_engine.build_lakehouse_publish_defaults(env)
        preflight = fusion_engine.build_lakehouse_infrastructure_preflight(
            config,
            environment=environment,
        )
        validation = fusion_engine.validate_lakehouse_infrastructure_preflight(preflight)
        summary = _infrastructure_preflight_summary(preflight)
        result = {
            "status": "ok" if validation.get("valid") else "error",
            "summary": summary,
            "errors": summary["errors"] + list(validation.get("errors") or []),
            "warnings": summary["warnings"],
            "preflight": preflight,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def export_semantic_product_okf(
    manifest_json: str = "",
    manifest_path: str = "",
    out_dir: str = "",
) -> str:
    """Export an MMFE semantic product as an OKF Markdown sidecar bundle.

    The semantic product JSON remains the machine contract. This tool creates
    a human- and agent-readable OKF review/exchange layer from that contract.

    Args:
        manifest_json: Semantic product manifest JSON. Used before manifest_path.
        manifest_path: Path to a semantic product manifest JSON when manifest_json is empty.
        out_dir: Output directory for the OKF bundle. Defaults to `okf_bundle`
            beside manifest_path, or `okf_bundle` in the current working directory
            when manifest_json is used.

    Returns:
        JSON export summary with validation status and generated entry paths.
    """
    try:
        manifest = await asyncio.to_thread(_load_semantic_manifest, manifest_json, manifest_path)
        result = await asyncio.to_thread(
            _export_semantic_product_okf,
            manifest,
            manifest_json,
            manifest_path,
            out_dir,
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def build_twm_state_input(
    manifest_json: str = "",
    manifest_path: str = "",
    out_path: str = "",
) -> str:
    """Build a TWM state-input JSON artifact from an MMFE semantic product.

    This derives a downstream state-builder input from MMFE role bindings,
    semantic relations, standard readiness, hard constraints and optimization
    objectives. It does not run TWM simulation or optimization.

    Args:
        manifest_json: Semantic product manifest JSON. Used before manifest_path.
        manifest_path: Path to a semantic product manifest JSON when manifest_json is empty.
        out_path: Optional output JSON path. Defaults to `twm_state_input.json`
            beside manifest_path, or `twm_state_input.json` in the current
            working directory when manifest_json is used.

    Returns:
        JSON summary with validation status and generated state-input path.
    """
    try:
        manifest = await asyncio.to_thread(_load_semantic_manifest, manifest_json, manifest_path)
        result = await asyncio.to_thread(
            _build_twm_state_input_sidecar,
            manifest,
            manifest_json,
            manifest_path,
            out_path,
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def build_mmfe_semantic_ontology(
    manifest_json: str = "",
    manifest_path: str = "",
    out_path: str = "",
) -> str:
    """Build a compact MMFE semantic ontology sidecar from a semantic product.

    The ontology sidecar normalizes standard roles, object types, fields, TWM
    semantic keys, value domains, standard sources, semantic relation types,
    rules and optimization objectives into a JSON-only concept package.

    Args:
        manifest_json: Semantic product manifest JSON. Used before manifest_path.
        manifest_path: Path to a semantic product manifest JSON when manifest_json is empty.
        out_path: Optional output JSON path. Defaults to
            `mmfe_semantic_ontology.json` beside manifest_path, or in the
            current working directory when manifest_json is used.

    Returns:
        JSON summary with validation status and generated ontology path.
    """
    try:
        manifest = await asyncio.to_thread(_load_semantic_manifest, manifest_json, manifest_path)
        result = await asyncio.to_thread(
            _build_mmfe_semantic_ontology_sidecar,
            manifest,
            manifest_json,
            manifest_path,
            out_path,
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def query_semantic_vectors(
    query_text: str,
    target: str = "lancedb",
    collection: str = "mmfe_semantic_products",
    top_k: str = "5",
    product_id: str = "",
    embedding_model: str = "",
    query_embedding_json: str = "",
    filters_json: str = "",
    execute_query: str = "false",
    lancedb_dataset_uri: str = "",
    lancedb_table: str = "semantic_products",
    pgvector_table: str = "agent_mmfe_semantic_vectors",
) -> str:
    """Build or execute an MMFE semantic vector retrieval query.

    This tool does not call an external embedding service by itself. To execute
    a query, pass `query_embedding_json` produced by the same embedding model
    used at publish time. Without an embedding it returns a validated query
    spec that can be embedded by a caller.

    Args:
        query_text: Natural-language query text.
        target: Retrieval backend: lancedb or pgvector.
        collection: Vector collection/table grouping.
        top_k: Maximum number of matches.
        product_id: Optional semantic product id filter.
        embedding_model: Embedding model identifier used for traceability.
        query_embedding_json: JSON numeric vector for direct backend execution.
        filters_json: Optional JSON object for future metadata filters.
        execute_query: true to execute against the configured backend.
        lancedb_dataset_uri: Local LanceDB database directory when target=lancedb.
        lancedb_table: LanceDB table name.
        pgvector_table: PostgreSQL pgvector table name.

    Returns:
        JSON query spec or retrieval result with normalized matches.
    """
    try:
        filters = _parse_json_object(filters_json, "filters_json") if filters_json.strip() else {}
        spec = fusion_engine.build_semantic_vector_query_spec(
            query_text=query_text,
            target=(target or "").strip().lower(),
            collection=collection,
            embedding_model=embedding_model or None,
            top_k=_safe_positive_int(top_k, 5),
            product_id=product_id or None,
            filters=filters,
        )
        if query_embedding_json.strip():
            spec = _attach_query_embedding(spec, query_embedding_json)

        validation_errors = fusion_engine.validate_semantic_vector_query_spec(spec)
        if validation_errors:
            return json.dumps(
                {"status": "error", "message": "invalid semantic vector query", "errors": validation_errors, "spec": spec},
                ensure_ascii=False,
                indent=2,
            )

        if not _truthy(execute_query):
            return json.dumps(
                {
                    "status": "ok",
                    "mode": "plan",
                    "requires_query_embedding": bool(spec.get("embedding_required", True)),
                    "spec": spec,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        if spec.get("embedding_required", True):
            raise ValueError("query_embedding_json is required when execute_query=true")

        result = await asyncio.to_thread(
            _execute_semantic_vector_query,
            spec,
            lancedb_dataset_uri,
            lancedb_table,
            pgvector_table,
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def trace_mmfe_semantics(
    node_id: str = "",
    layer_role: str = "",
    field_name: str = "",
    manifest_json: str = "",
    manifest_path: str = "",
    graph_path: str = "",
    trace_cards_path: str = "",
    max_depth: str = "4",
    max_paths: str = "8",
) -> str:
    """Explain one MMFE semantic graph node and trace it to standards/evidence.

    Args:
        node_id: Exact semantic graph node id, such as `field:parcel_current.DLBM`.
        layer_role: Layer role used with field_name when node_id is empty.
        field_name: Field name used with layer_role when node_id is empty.
        manifest_json: Semantic product manifest JSON. Used to find embedded or
            referenced semantic graph sidecars when graph_path is empty.
        manifest_path: Semantic product manifest path. For the TWM bundle this
            automatically loads sibling graph and trace-card sidecars.
        graph_path: Explicit semantic graph JSON path.
        trace_cards_path: Optional precomputed semantic trace-card bundle path.
        max_depth: Maximum graph traversal depth.
        max_paths: Maximum paths per target type.

    Returns:
        JSON explanation with direct relationships and paths to value domains,
        standard sources, rules, objectives and evidence indexes.
    """
    try:
        result = await asyncio.to_thread(
            _trace_mmfe_semantics,
            node_id,
            layer_role,
            field_name,
            manifest_json,
            manifest_path,
            graph_path,
            trace_cards_path,
            _safe_positive_int(max_depth, 4),
            _safe_positive_int(max_paths, 8),
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except (ValueError, KeyError) as e:
        message = e.args[0] if getattr(e, "args", None) else str(e)
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=message)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


async def diagnose_mmfe_semantic_product(
    manifest_json: str = "",
    manifest_path: str = "",
) -> str:
    """Diagnose whether an MMFE semantic product is ready for Agent/TWM use.

    The diagnostic separates validation-scaffold readiness from production
    readiness. A product can be useful for MMFE/TWM development while still
    carrying explicit production gaps such as synthetic data or pending official
    standard sources.

    Args:
        manifest_json: Semantic product manifest JSON. Used before manifest_path.
        manifest_path: Semantic product manifest path. For the TWM bundle this
            automatically loads sibling value-domain, standard, graph, trace,
            relation and state-input sidecars.

    Returns:
        JSON readiness diagnostic with capability summary, checks, top gaps and
        Chinese recommendations.
    """
    try:
        manifest = await asyncio.to_thread(_load_semantic_manifest, manifest_json, manifest_path)
        result = await asyncio.to_thread(
            _diagnose_mmfe_semantic_product,
            manifest,
            manifest_json,
            manifest_path,
        )
        return json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2, default=str)
    except ValueError as e:
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": translate(
                              "fusion.operation_failed", error=e)}, ensure_ascii=False, indent=2)


def _load_semantic_manifest(manifest_json: str, manifest_path: str) -> dict:
    if manifest_json.strip():
        try:
            manifest = json.loads(manifest_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid manifest_json: {exc}") from exc
    elif manifest_path.strip():
        resolved = _resolve_path(manifest_path.strip())
        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid manifest_path JSON: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"cannot read manifest_path: {exc}") from exc
    else:
        raise ValueError("manifest_json or manifest_path is required")

    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")
    return manifest


def _attach_semantic_diagnostic_for_publish_plan(
    manifest: dict,
    manifest_json: str,
    manifest_path: str,
) -> dict:
    updated = dict(manifest)
    bundle = dict(updated.get("mmfe_bundle") or {})
    if bundle.get("semantic_diagnostic") or bundle.get("semantic_diagnostic_summary"):
        updated["mmfe_bundle"] = bundle
        return updated
    resolved_manifest_path = ""
    if manifest_path.strip() and not manifest_json.strip():
        resolved_manifest_path = _resolve_path(manifest_path.strip())
    sidecars = _load_okf_sidecars(resolved_manifest_path)
    diagnostic = sidecars.get("semantic_diagnostic")
    if not diagnostic and sidecars:
        diagnostic = fusion_engine.diagnose_semantic_product_readiness(
            updated,
            value_domain_audits=sidecars.get("value_domain_audits"),
            standard_sources=sidecars.get("standard_sources"),
            semantic_relations=sidecars.get("semantic_relations"),
            state_input=sidecars.get("state_input"),
            semantic_graph=sidecars.get("semantic_graph"),
            semantic_trace_cards=sidecars.get("semantic_trace_cards"),
        )
    if diagnostic:
        bundle["semantic_diagnostic"] = diagnostic
        bundle["semantic_diagnostic_summary"] = diagnostic.get("summary") or {}
        bundle["semantic_diagnostic_top_gaps"] = diagnostic.get("top_gaps") or []
        bundle["semantic_diagnostic_recommendations_zh"] = diagnostic.get("recommendations_zh") or []
        updated["mmfe_bundle"] = bundle
    return updated


def _execute_semantic_vector_query(
    spec: dict,
    lancedb_dataset_uri: str,
    lancedb_table: str,
    pgvector_table: str,
) -> dict:
    target = spec.get("target")
    if target == "lancedb":
        if not lancedb_dataset_uri.strip():
            raise ValueError("lancedb_dataset_uri is required when target=lancedb and execute_query=true")
        executor = fusion_engine.build_local_lancedb_query_executor(lancedb_dataset_uri.strip())
        querier = fusion_engine.build_lancedb_querier(
            dataset_uri=lancedb_dataset_uri.strip(),
            table=lancedb_table,
            executor=executor,
        )
    elif target == "pgvector":
        executor = fusion_engine.build_pgvector_query_executor(table=pgvector_table)
        querier = fusion_engine.build_pgvector_querier(table=pgvector_table, executor=executor)
    else:
        raise ValueError("target must be one of: pgvector, lancedb")
    return fusion_engine.run_semantic_vector_query(spec, querier=querier)


def _trace_mmfe_semantics(
    node_id: str,
    layer_role: str,
    field_name: str,
    manifest_json: str,
    manifest_path: str,
    graph_path: str,
    trace_cards_path: str,
    max_depth: int,
    max_paths: int,
) -> dict:
    resolved_node_id = _resolve_trace_node_id(node_id, layer_role, field_name)
    if not resolved_node_id:
        raise ValueError("node_id or both layer_role and field_name are required")

    manifest = None
    resolved_manifest_path = ""
    if manifest_json.strip() or manifest_path.strip():
        manifest = _load_semantic_manifest(manifest_json, manifest_path)
        if manifest_path.strip() and not manifest_json.strip():
            resolved_manifest_path = _resolve_path(manifest_path.strip())

    graph, graph_source = _load_semantic_graph_for_trace(
        manifest=manifest,
        manifest_path=resolved_manifest_path,
        graph_path=graph_path,
    )
    trace_cards, trace_cards_source = _load_semantic_trace_cards_for_trace(
        manifest=manifest,
        manifest_path=resolved_manifest_path,
        trace_cards_path=trace_cards_path,
    )
    precomputed_card = _find_semantic_trace_card(trace_cards, resolved_node_id)

    if graph:
        trace = fusion_engine.trace_semantic_graph_node(
            graph,
            resolved_node_id,
            max_depth=max_depth,
            max_paths=max_paths,
        )
        source_mode = "computed_from_semantic_graph"
    elif precomputed_card:
        trace = precomputed_card
        source_mode = "precomputed_trace_card"
    else:
        raise ValueError("semantic graph is required when no matching precomputed trace card is available")

    counts = _semantic_trace_path_counts(trace)
    return {
        "schema": "mmfe.semantic_trace_tool.v1",
        "node_id": resolved_node_id,
        "source_mode": source_mode,
        "graph_source": graph_source,
        "trace_cards_source": trace_cards_source,
        "precomputed_trace_card_found": bool(precomputed_card),
        "summary": trace.get("summary_zh", ""),
        **counts,
        "trace": trace,
        "precomputed_trace_card": precomputed_card,
    }


def _diagnose_mmfe_semantic_product(
    manifest: dict,
    manifest_json: str,
    manifest_path: str,
) -> dict:
    resolved_manifest_path = ""
    if manifest_path.strip() and not manifest_json.strip():
        resolved_manifest_path = _resolve_path(manifest_path.strip())

    sidecars = _load_okf_sidecars(resolved_manifest_path)
    diagnostic = fusion_engine.diagnose_semantic_product_readiness(
        manifest,
        value_domain_audits=sidecars.get("value_domain_audits"),
        standard_sources=sidecars.get("standard_sources"),
        semantic_relations=sidecars.get("semantic_relations"),
        state_input=sidecars.get("state_input"),
        semantic_graph=sidecars.get("semantic_graph"),
        semantic_trace_cards=sidecars.get("semantic_trace_cards"),
    )
    validation = fusion_engine.validate_semantic_product_diagnostic(diagnostic)
    return {
        **diagnostic,
        "valid": validation["valid"],
        "errors": validation["errors"],
        "sidecar_sources": _diagnostic_sidecar_sources(resolved_manifest_path, sidecars),
    }


def _attach_query_embedding(spec: dict, query_embedding_json: str) -> dict:
    try:
        embedding = json.loads(query_embedding_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid query_embedding_json: {exc}") from exc
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("query_embedding_json must be a non-empty numeric JSON array")
    try:
        values = [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise ValueError("query_embedding_json must contain only numbers") from exc
    updated = dict(spec)
    updated["query_embedding"] = values
    updated["embedding_required"] = False
    updated["embedding_dimension"] = len(values)
    return updated


def _diagnostic_sidecar_sources(manifest_path: str, sidecars: dict) -> dict:
    if not manifest_path:
        return {}
    root = Path(manifest_path).parent
    conventional = {
        "value_domain_audits": root / "twm_mmfe_value_domain_audit.csv",
        "standard_sources": root / "twm_mmfe_standard_sources.csv",
        "semantic_relations": root / "twm_mmfe_semantic_relations.csv",
        "state_input": root / "twm_state_input.json",
        "semantic_graph": root / "twm_mmfe_semantic_graph.json",
        "semantic_trace_cards": root / "twm_mmfe_semantic_trace_cards.json",
        "semantic_ontology": root / "twm_mmfe_semantic_ontology.json",
    }
    return {
        key: str(path)
        for key, path in conventional.items()
        if sidecars.get(key) is not None or path.exists()
    }


def _resolve_trace_node_id(node_id: str, layer_role: str, field_name: str) -> str:
    if node_id.strip():
        return node_id.strip()
    role = layer_role.strip()
    field = field_name.strip()
    if role and field:
        return f"field:{role}.{field}"
    return ""


def _load_semantic_graph_for_trace(
    *,
    manifest: dict | None,
    manifest_path: str,
    graph_path: str,
) -> tuple[dict | None, str]:
    if graph_path.strip():
        resolved = _resolve_semantic_sidecar_path(graph_path.strip(), manifest_path)
        return _read_json_sidecar(resolved, "graph_path"), resolved

    if manifest_path:
        sidecars = _load_okf_sidecars(manifest_path)
        graph = sidecars.get("semantic_graph")
        if graph:
            return graph, str(Path(manifest_path).parent / "twm_mmfe_semantic_graph.json")
        inferred = Path(manifest_path).parent / "twm_mmfe_semantic_graph.json"
        if inferred.exists():
            return _read_json_sidecar(str(inferred), "semantic graph sidecar"), str(inferred)

    if manifest:
        embedded = (manifest.get("mmfe_bundle") or {}).get("semantic_graph")
        if isinstance(embedded, dict):
            return embedded, "manifest.mmfe_bundle.semantic_graph"
        ref = (manifest.get("business_outputs") or {}).get("semantic_graph")
        if ref:
            resolved = _resolve_semantic_sidecar_path(str(ref), manifest_path)
            return _read_json_sidecar(resolved, "manifest business_outputs.semantic_graph"), resolved

    return None, ""


def _load_semantic_trace_cards_for_trace(
    *,
    manifest: dict | None,
    manifest_path: str,
    trace_cards_path: str,
) -> tuple[dict | None, str]:
    if trace_cards_path.strip():
        resolved = _resolve_semantic_sidecar_path(trace_cards_path.strip(), manifest_path)
        return _read_json_sidecar(resolved, "trace_cards_path"), resolved

    if manifest_path:
        sidecars = _load_okf_sidecars(manifest_path)
        cards = sidecars.get("semantic_trace_cards")
        if cards:
            return cards, str(Path(manifest_path).parent / "twm_mmfe_semantic_trace_cards.json")
        inferred = Path(manifest_path).parent / "twm_mmfe_semantic_trace_cards.json"
        if inferred.exists():
            return _read_json_sidecar(str(inferred), "semantic trace-card sidecar"), str(inferred)

    if manifest:
        embedded = (manifest.get("mmfe_bundle") or {}).get("semantic_trace_cards")
        if isinstance(embedded, dict):
            return embedded, "manifest.mmfe_bundle.semantic_trace_cards"
        ref = (manifest.get("business_outputs") or {}).get("semantic_trace_cards")
        if ref:
            resolved = _resolve_semantic_sidecar_path(str(ref), manifest_path)
            return _read_json_sidecar(resolved, "manifest business_outputs.semantic_trace_cards"), resolved

    return None, ""


def _resolve_semantic_sidecar_path(path_value: str, manifest_path: str) -> str:
    raw = Path(path_value).expanduser()
    if raw.is_absolute() and raw.exists():
        return str(raw)
    if raw.exists():
        return str(raw.resolve())
    if manifest_path:
        sibling = Path(manifest_path).parent / path_value
        if sibling.exists():
            return str(sibling)
    return _resolve_path(path_value)


def _read_json_sidecar(path: str, label: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _find_semantic_trace_card(trace_cards: dict | None, node_id: str) -> dict | None:
    if not isinstance(trace_cards, dict):
        return None
    for card in trace_cards.get("cards") or []:
        if not isinstance(card, dict):
            continue
        node = card.get("node") or {}
        if node.get("id") == node_id:
            return card
    return None


def _semantic_trace_path_counts(trace: dict) -> dict:
    return {
        "standard_source_path_count": len(trace.get("standard_source_paths") or []),
        "value_domain_path_count": len(trace.get("value_domain_paths") or []),
        "rule_path_count": len(trace.get("rule_paths") or []),
        "objective_path_count": len(trace.get("objective_paths") or []),
        "evidence_path_count": len(trace.get("evidence_paths") or []),
        "direct_relationship_count": len(trace.get("direct_relationships") or []),
    }


def _export_semantic_product_okf(
    manifest: dict,
    manifest_json: str,
    manifest_path: str,
    out_dir: str,
) -> dict:
    resolved_manifest_path = ""
    if manifest_path.strip() and not manifest_json.strip():
        resolved_manifest_path = _resolve_path(manifest_path.strip())

    sidecars = _load_okf_sidecars(resolved_manifest_path)
    output_dir = _resolve_okf_out_dir(out_dir, resolved_manifest_path)
    return fusion_engine.export_semantic_product_okf_bundle(
        manifest,
        output_dir,
        field_semantics=sidecars.get("field_semantics"),
        value_domain_audits=sidecars.get("value_domain_audits"),
        standard_sources=sidecars.get("standard_sources"),
        semantic_relations=sidecars.get("semantic_relations"),
        input_contract=sidecars.get("input_contract"),
        state_input=sidecars.get("state_input"),
        semantic_graph=sidecars.get("semantic_graph"),
        semantic_trace_cards=sidecars.get("semantic_trace_cards"),
        semantic_ontology=sidecars.get("semantic_ontology"),
    )


def _build_twm_state_input_sidecar(
    manifest: dict,
    manifest_json: str,
    manifest_path: str,
    out_path: str,
) -> dict:
    resolved_manifest_path = ""
    if manifest_path.strip() and not manifest_json.strip():
        resolved_manifest_path = _resolve_path(manifest_path.strip())

    sidecars = _load_okf_sidecars(resolved_manifest_path)
    payload = fusion_engine.build_twm_state_input_from_semantic_product(
        manifest,
        semantic_relations=sidecars.get("semantic_relations"),
        input_contract=sidecars.get("input_contract"),
    )
    validation = fusion_engine.validate_twm_state_input(payload)
    output_path = _resolve_twm_state_input_out_path(out_path, resolved_manifest_path)
    fusion_engine.write_twm_state_input(payload, output_path)
    return {
        "schema": payload["schema"],
        "version": payload["version"],
        "valid": validation["valid"],
        "errors": validation["errors"],
        "out_path": output_path,
        "product_id": payload["source_product"]["product_id"],
        "role_count": len(payload["object_role_registry"]),
        "relation_count": payload["semantic_relation_summary"]["total_relation_count"],
        "relation_type_count": payload["semantic_relation_summary"]["registered_relation_type_count"],
        "hard_constraint_relation_count": payload["state_components"]["hard_constraints"]["relation_count"],
        "objective_binding_count": len(payload["optimization_interface"]["objective_bindings"]),
        "warning_count": len(payload["warnings"]),
    }


def _build_mmfe_semantic_ontology_sidecar(
    manifest: dict,
    manifest_json: str,
    manifest_path: str,
    out_path: str,
) -> dict:
    resolved_manifest_path = ""
    if manifest_path.strip() and not manifest_json.strip():
        resolved_manifest_path = _resolve_path(manifest_path.strip())

    sidecars = _load_okf_sidecars(resolved_manifest_path)
    payload = fusion_engine.build_semantic_ontology_package(
        manifest,
        field_semantics=sidecars.get("field_semantics"),
        value_domain_audits=sidecars.get("value_domain_audits"),
        standard_sources=sidecars.get("standard_sources"),
        semantic_relations=sidecars.get("semantic_relations"),
        state_input=sidecars.get("state_input"),
    )
    validation = fusion_engine.validate_semantic_ontology_package(payload)
    output_path = _resolve_semantic_ontology_out_path(out_path, resolved_manifest_path)
    fusion_engine.write_semantic_ontology_package(payload, output_path)
    summary = payload.get("summary") or {}
    return {
        "schema": payload["schema"],
        "version": payload["version"],
        "valid": validation["valid"],
        "errors": validation["errors"],
        "out_path": output_path,
        "product_id": payload["source_product"]["product_id"],
        "summary": summary,
    }


def _load_okf_sidecars(manifest_path: str) -> dict:
    if not manifest_path:
        return {}
    root = Path(manifest_path).parent
    if Path(manifest_path).name == "twm_mmfe_semantic_product.json":
        try:
            inputs = fusion_engine.load_semantic_product_okf_inputs(root)
            return {
                "field_semantics": inputs.get("field_semantics"),
                "value_domain_audits": inputs.get("value_domain_audits"),
                "standard_sources": inputs.get("standard_sources"),
                "semantic_relations": inputs.get("semantic_relations"),
                "input_contract": inputs.get("input_contract"),
                "state_input": inputs.get("state_input"),
                "semantic_graph": inputs.get("semantic_graph"),
                "semantic_trace_cards": inputs.get("semantic_trace_cards"),
                "semantic_ontology": inputs.get("semantic_ontology"),
                "semantic_diagnostic": inputs.get("semantic_diagnostic"),
            }
        except OSError:
            return {}
    return {}


def _resolve_okf_out_dir(out_dir: str, manifest_path: str) -> str:
    if out_dir.strip():
        return str(Path(out_dir.strip()).expanduser())
    if manifest_path:
        return str(Path(manifest_path).parent / "okf_bundle")
    return "okf_bundle"


def _resolve_twm_state_input_out_path(out_path: str, manifest_path: str) -> str:
    if out_path.strip():
        return str(Path(out_path.strip()).expanduser())
    if manifest_path:
        return str(Path(manifest_path).parent / "twm_state_input.json")
    return "twm_state_input.json"


def _resolve_semantic_ontology_out_path(out_path: str, manifest_path: str) -> str:
    if out_path.strip():
        return str(Path(out_path.strip()).expanduser())
    if manifest_path:
        return str(Path(manifest_path).parent / "mmfe_semantic_ontology.json")
    return "mmfe_semantic_ontology.json"


def _parse_publish_targets(targets: str, vector_target: str = "lancedb") -> list[str]:
    parsed = []
    vector_fallback = (vector_target or "lancedb").strip().lower()
    for target in _parse_csv_list(targets):
        normalized = target.lower()
        if normalized == "vector":
            normalized = vector_fallback
        parsed.append(normalized)
    return parsed


def _normalize_lakehouse_env_defaults(
    env_defaults: dict,
    *,
    iceberg_warehouse_uri: str = "",
    stac_catalog_uri: str = "",
) -> dict:
    if not isinstance(env_defaults, dict) or not env_defaults:
        return env_defaults
    normalized = deepcopy(env_defaults)
    object_store = normalized.get("object_store") if isinstance(normalized.get("object_store"), dict) else {}
    iceberg = normalized.get("iceberg") if isinstance(normalized.get("iceberg"), dict) else {}
    stac = normalized.get("stac") if isinstance(normalized.get("stac"), dict) else {}

    warehouse_bucket = _s3_bucket(iceberg_warehouse_uri)
    if iceberg_warehouse_uri:
        object_store["warehouse_uri"] = iceberg_warehouse_uri
        iceberg["warehouse_uri"] = iceberg_warehouse_uri
    if warehouse_bucket:
        object_store["lakehouse_bucket"] = warehouse_bucket
        metadata = dict(iceberg.get("metadata") or {})
        metadata["lakehouse_bucket"] = warehouse_bucket
        iceberg["metadata"] = metadata
        if not stac_catalog_uri:
            default_stac_catalog_uri = f"s3://{warehouse_bucket}/catalog/stac"
            object_store["stac_catalog_uri"] = default_stac_catalog_uri
            stac["catalog_uri"] = default_stac_catalog_uri
    if stac_catalog_uri:
        object_store["stac_catalog_uri"] = stac_catalog_uri
        stac["catalog_uri"] = stac_catalog_uri

    if object_store:
        normalized["object_store"] = object_store
    if iceberg:
        normalized["iceberg"] = iceberg
    if stac:
        normalized["stac"] = stac
    return normalized


def _parse_csv_list(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _parse_json_object(value: str, field_name: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {field_name}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def _parse_string_mapping_json(value: str, field_name: str) -> dict[str, str]:
    parsed = _parse_json_object(value, field_name)
    return {str(key): str(val) for key, val in parsed.items() if val is not None}


def _s3_bucket(value: object) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "s3":
        return ""
    return parsed.netloc


def _safe_positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1)


def _parse_optional_bool(value: str) -> bool | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "auto", "default"}:
        return None
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _publish_plan_summary(plan: dict) -> dict:
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    invalid_steps = [step for step in steps if isinstance(step, dict) and not step.get("valid")]
    return {
        "valid": bool(plan.get("valid")),
        "publish_environment": plan.get("publish_environment"),
        "production_gate_valid": bool((plan.get("production_gate") or {}).get("valid")),
        "infrastructure_preflight_valid": bool((plan.get("infrastructure_preflight") or {}).get("valid")),
        "production_ready": bool(
            ((plan.get("production_gate") or {}).get("diagnostic_summary") or {}).get("production_ready")
        ),
        "validation_ready": bool(
            ((plan.get("production_gate") or {}).get("diagnostic_summary") or {}).get("validation_ready")
        ),
        "target_count": len(plan.get("targets") or []),
        "step_count": len(steps),
        "valid_step_count": len(steps) - len(invalid_steps),
        "invalid_step_count": len(invalid_steps),
        "error_count": sum(len(error.get("errors") or []) for error in plan.get("errors") or [] if isinstance(error, dict)),
    }


def _infrastructure_preflight_summary(preflight: dict) -> dict:
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
    errors = [
        f"{check.get('check_id')}: {check.get('message')}"
        for check in checks
        if isinstance(check, dict) and check.get("status") == "fail"
    ]
    warnings = [
        f"{check.get('check_id')}: {check.get('message')}"
        for check in checks
        if isinstance(check, dict) and check.get("status") == "warn"
    ]
    raw_summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
    return {
        "valid": bool(preflight.get("valid")),
        "environment": preflight.get("environment"),
        "check_count": int(raw_summary.get("check_count") or len(checks)),
        "pass_count": int(raw_summary.get("pass_count") or 0),
        "warn_count": int(raw_summary.get("warn_count") or 0),
        "fail_count": int(raw_summary.get("fail_count") or 0),
        "critical_fail_count": int(raw_summary.get("critical_fail_count") or 0),
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    profile_fusion_sources,
    assess_fusion_compatibility,
    fuse_datasets,
    validate_fusion_quality,
    standardize_timestamps,
    validate_temporal_consistency,
    inject_document_context,
    preflight_mmfe_lakehouse_infrastructure,
    plan_semantic_product_publish,
    export_semantic_product_okf,
    build_twm_state_input,
    build_mmfe_semantic_ontology,
    query_semantic_vectors,
    trace_mmfe_semantics,
    diagnose_mmfe_semantic_product,
]


class FusionToolset(BaseToolset):
    """Multi-modal data fusion toolset — profile, assess, fuse, validate."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
