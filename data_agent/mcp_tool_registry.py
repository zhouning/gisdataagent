"""
MCP Tool Registry — Defines and registers GIS tools for the MCP Server.

Wraps existing GIS tool functions with MCP-safe error handling and
registers them with a FastMCP server instance.
"""
import functools
import inspect
import json
from typing import Callable, List, Dict, Any

from mcp.types import ToolAnnotations

# ---------------------------------------------------------------------------
# Wrapper factory
# ---------------------------------------------------------------------------

def _wrap_tool(fn: Callable) -> Callable:
    """Create MCP-safe wrapper: dict→JSON string, exceptions→error JSON.

    Uses functools.wraps to preserve __name__ and __doc__.
    Explicitly builds __signature__ with original input params but ``str``
    return type, since the wrapper always serializes results to strings.
    This avoids Pydantic errors from annotations like ``dict[str, any]``
    (lowercase ``any`` = built-in function).
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False, default=str)
            return str(result)
        except Exception as e:
            return json.dumps(
                {"status": "error", "message": str(e)},
                ensure_ascii=False,
            )

    # Build a clean signature: keep original input params, force return=str.
    # This prevents inspect.signature() from following __wrapped__ back to
    # the original function (which may have problematic return annotations).
    try:
        orig_sig = inspect.signature(fn)
        wrapper.__signature__ = orig_sig.replace(return_annotation=str)
    except (ValueError, TypeError):
        pass

    # Also update __annotations__ for any code that reads it directly
    ann = {}
    for name, param in inspect.signature(fn).parameters.items():
        if param.annotation is not inspect.Parameter.empty:
            ann[name] = param.annotation
    ann["return"] = str
    wrapper.__annotations__ = ann

    return wrapper


# ---------------------------------------------------------------------------
# Lazy imports — avoid importing heavy GIS libraries at registry definition
# ---------------------------------------------------------------------------

# --- High-level wrapper functions (v13.1) ---

def _mcp_list_skills() -> str:
    """列出所有可用的内置 ADK 技能（Skills），包括名称、描述、领域和触发关键词。

    Returns:
        JSON格式的技能列表。
    """
    from .capabilities import list_builtin_skills
    skills = list_builtin_skills()
    return json.dumps({"skills": skills, "count": len(skills)}, ensure_ascii=False)


def _mcp_list_toolsets() -> str:
    """列出所有可用的工具集（Toolsets），每个工具集包含多个专业 GIS 分析工具。

    Returns:
        JSON格式的工具集列表。
    """
    from .capabilities import list_toolsets
    toolsets = list_toolsets()
    return json.dumps({"toolsets": toolsets, "count": len(toolsets)}, ensure_ascii=False)


def _mcp_list_virtual_sources() -> str:
    """列出当前用户可访问的虚拟数据源（WFS/STAC/OGC API/自定义API），包括共享源。

    Returns:
        JSON格式的虚拟数据源列表。
    """
    from .virtual_sources import list_virtual_sources
    from .user_context import current_user_id
    username = current_user_id.get("mcp_user")
    sources = list_virtual_sources(username, include_shared=True)
    return json.dumps({"sources": sources, "count": len(sources)}, ensure_ascii=False)


def _mcp_run_pipeline(prompt: str, pipeline_type: str = "general") -> str:
    """执行完整的 GIS 分析管线。支持通用分析、治理报告、优化布局三种管线。

    Args:
        prompt: 用户分析需求描述（自然语言，如"分析北京市土地利用变化趋势"）。
        pipeline_type: 管线类型（general=通用分析, governance=治理报告, optimization=DRL优化）。

    Returns:
        JSON格式的分析结果，包含报告文本、生成文件、工具执行日志、Token消耗等。
    """
    import asyncio
    try:
        from .pipeline_runner import run_pipeline_headless
        from .user_context import current_user_id, current_session_id
        from .agent import general_pipeline, governance_pipeline, data_pipeline
        from google.adk.sessions import InMemorySessionService

        user_id = current_user_id.get("mcp_user")
        session_id = current_session_id.get(f"mcp_{user_id}")

        agents = {
            "general": general_pipeline,
            "governance": governance_pipeline,
            "optimization": data_pipeline,
        }
        agent = agents.get(pipeline_type, general_pipeline)
        session_service = InMemorySessionService()

        result = asyncio.run(run_pipeline_headless(
            agent=agent,
            session_service=session_service,
            user_id=user_id,
            session_id=session_id,
            prompt=prompt,
            pipeline_type=pipeline_type,
            intent=pipeline_type.upper(),
        ))

        return json.dumps({
            "status": "ok",
            "report": result.report_text[:5000],
            "files": result.generated_files,
            "pipeline_type": result.pipeline_type,
            "duration_seconds": round(result.duration_seconds, 1),
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "error": result.error,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def _get_tool_functions() -> Dict[str, Callable]:
    """Lazy-import all tool functions. Called once during registration."""
    from .toolsets.exploration_tools import (
        describe_geodataframe,
        reproject_spatial_data,
        engineer_spatial_features,
    )
    from .gis_processors import (
        perform_clustering,
        create_buffer,
        overlay_difference,
        summarize_within,
        find_within_distance,
        generate_tessellation,
        raster_to_polygon,
        pairwise_clip,
        check_topology,
        check_field_standards,
        polygon_neighbors,
        add_field,
        add_join,
        calculate_field,
        summary_statistics,
        surface_parameters,
        zonal_statistics_as_table,
        generate_heatmap,
    )
    from .geocoding import (
        batch_geocode,
        reverse_geocode,
        calculate_driving_distance,
        search_nearby_poi,
        search_poi_by_keyword,
        get_admin_boundary,
    )
    from .toolsets.visualization_tools import (
        visualize_geodataframe,
        visualize_interactive_map,
        generate_choropleth,
        generate_bubble_map,
        compose_map,
    )
    from .database_tools import (
        query_database,
        list_tables,
        describe_table,
    )
    from .remote_sensing import (
        describe_raster,
        calculate_ndvi,
        raster_band_math,
        classify_raster,
        visualize_raster,
    )
    from .spatial_statistics import (
        spatial_autocorrelation,
        local_moran,
        hotspot_analysis,
    )
    from .data_catalog import search_data_assets, get_data_lineage
    from .capabilities import list_builtin_skills, list_toolsets

    return {
        "describe_geodataframe": describe_geodataframe,
        "reproject_spatial_data": reproject_spatial_data,
        "engineer_spatial_features": engineer_spatial_features,
        "perform_clustering": perform_clustering,
        "create_buffer": create_buffer,
        "overlay_difference": overlay_difference,
        "summarize_within": summarize_within,
        "find_within_distance": find_within_distance,
        "generate_tessellation": generate_tessellation,
        "raster_to_polygon": raster_to_polygon,
        "pairwise_clip": pairwise_clip,
        "check_topology": check_topology,
        "check_field_standards": check_field_standards,
        "polygon_neighbors": polygon_neighbors,
        "add_field": add_field,
        "add_join": add_join,
        "calculate_field": calculate_field,
        "summary_statistics": summary_statistics,
        "surface_parameters": surface_parameters,
        "zonal_statistics_as_table": zonal_statistics_as_table,
        "generate_heatmap": generate_heatmap,
        "batch_geocode": batch_geocode,
        "reverse_geocode": reverse_geocode,
        "calculate_driving_distance": calculate_driving_distance,
        "search_nearby_poi": search_nearby_poi,
        "search_poi_by_keyword": search_poi_by_keyword,
        "get_admin_boundary": get_admin_boundary,
        "visualize_geodataframe": visualize_geodataframe,
        "visualize_interactive_map": visualize_interactive_map,
        "generate_choropleth": generate_choropleth,
        "generate_bubble_map": generate_bubble_map,
        "compose_map": compose_map,
        "query_database": query_database,
        "list_tables": list_tables,
        "describe_table": describe_table,
        "describe_raster": describe_raster,
        "calculate_ndvi": calculate_ndvi,
        "raster_band_math": raster_band_math,
        "classify_raster": classify_raster,
        "visualize_raster": visualize_raster,
        "spatial_autocorrelation": spatial_autocorrelation,
        "local_moran": local_moran,
        "hotspot_analysis": hotspot_analysis,
        # --- High-level metadata tools (v13.1) ---
        "search_catalog": search_data_assets,
        "get_data_lineage": get_data_lineage,
        "list_skills": _mcp_list_skills,
        "list_toolsets": _mcp_list_toolsets,
        "list_virtual_sources": _mcp_list_virtual_sources,
        "run_analysis_pipeline": _mcp_run_pipeline,
    }


# ---------------------------------------------------------------------------
# Tool definitions — metadata for each tool
# ---------------------------------------------------------------------------

# Annotation presets
_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_WRITE_SAFE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # --- Exploration (read-only) ---
    {
        "name": "describe_geodataframe",
        "description": "数据画像：统计空间数据的要素数、CRS、字段、空值率、坐标异常等质量问题。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "reproject_spatial_data",
        "description": "坐标重投影：将空间数据从当前CRS转换到目标CRS（如 EPSG:4326、EPSG:3857）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "engineer_spatial_features",
        "description": "特征工程：自动计算面积、周长、质心坐标、形状指数等空间特征。",
        "annotations": _WRITE_SAFE,
    },

    # --- Processing ---
    {
        "name": "perform_clustering",
        "description": "DBSCAN空间聚类：对点数据进行密度聚类分析。参数 eps（搜索半径）和 min_samples（最小样本数）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "create_buffer",
        "description": "缓冲区分析：在要素周围创建指定距离的缓冲区，可选融合。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "overlay_difference",
        "description": "叠置擦除：从 input_file 中擦除 erase_file 覆盖的区域。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "summarize_within",
        "description": "区域汇总：统计落在多边形区域内的要素数量和属性统计值。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "find_within_distance",
        "description": "距离筛选：根据与参考要素的距离筛选目标要素（within/outside模式）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_tessellation",
        "description": "格网生成：在输入范围内生成规则格网（SQUARE/HEXAGON/TRIANGLE）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "raster_to_polygon",
        "description": "栅格转面：将栅格数据（.tif）转换为矢量面要素。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "pairwise_clip",
        "description": "要素裁剪：用裁剪要素的范围裁剪输入要素。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "check_topology",
        "description": "拓扑检查：扫描自相交、重叠、多部件几何等拓扑错误。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "check_field_standards",
        "description": "字段标准化检查：验证属性数据是否符合指定的标准模式（字段名、类型、允许值）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "polygon_neighbors",
        "description": "面邻域分析：找出每个面要素的相邻面及共享边界长度。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "add_field",
        "description": "添加字段：在属性表中添加新字段（TEXT/FLOAT/INTEGER/DOUBLE），可设默认值。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "add_join",
        "description": "属性连接：基于共同字段将 join_file 的属性左连接到 target_file。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "calculate_field",
        "description": "字段计算：用表达式计算字段值，支持 !field! 语法引用其他字段。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "summary_statistics",
        "description": "汇总统计：按分组字段计算多种统计量（SUM/MEAN/MIN/MAX/COUNT/STD）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "surface_parameters",
        "description": "地表参数：从DEM栅格计算坡度（SLOPE）或坡向（ASPECT）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "zonal_statistics_as_table",
        "description": "分区统计：计算矢量区域内栅格值的统计摘要（均值、总和、计数等）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_heatmap",
        "description": "核密度热力图：基于点数据生成KDE热力图栅格。",
        "annotations": _WRITE_SAFE,
    },

    # --- Geocoding ---
    {
        "name": "batch_geocode",
        "description": "批量地理编码：将Excel/CSV中的地址列转换为经纬度坐标（高德+Nominatim）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "reverse_geocode",
        "description": "逆地理编码：将坐标转换为详细地址信息。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "calculate_driving_distance",
        "description": "驾车距离计算：计算两点之间的驾车距离和预计时间（高德路径规划API）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_nearby_poi",
        "description": "周边POI搜索：搜索指定坐标点附近的兴趣点（银行、学校、医院等）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_poi_by_keyword",
        "description": "关键字POI搜索：在指定城市/区域内搜索兴趣点。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_admin_boundary",
        "description": "行政区划边界：下载指定行政区的矢量边界数据（Shapefile）。",
        "annotations": _WRITE_SAFE,
    },

    # --- Visualization ---
    {
        "name": "visualize_geodataframe",
        "description": "静态地图：可视化单份地理数据为PNG图片。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "visualize_interactive_map",
        "description": "交互地图：生成多图层交互式HTML地图（Folium）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_choropleth",
        "description": "等值区域图：按属性值分级着色的专题地图（支持多种分类方法和色带）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_bubble_map",
        "description": "气泡地图：按属性值控制点大小和颜色的专题地图。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "compose_map",
        "description": "多图层合成：将多个数据源叠加为一张交互地图（点、面、等值、热力、气泡图层）。",
        "annotations": _WRITE_SAFE,
    },

    # --- Database ---
    {
        "name": "query_database",
        "description": "SQL查询：对PostgreSQL/PostGIS数据库执行SQL查询，空间结果返回SHP、非空间返回CSV。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_tables",
        "description": "列出数据表：查看当前用户可访问的数据库表（自有+共享）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "describe_table",
        "description": "表结构描述：查看指定数据表的列名和数据类型。",
        "annotations": _READ_ONLY,
    },

    # --- Remote Sensing ---
    {
        "name": "describe_raster",
        "description": "栅格数据画像：统计波段数、CRS、数据类型、NoData值，以及每个波段的统计信息。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "calculate_ndvi",
        "description": "NDVI植被指数计算：从多波段影像计算归一化植被指数。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "raster_band_math",
        "description": "波段代数运算：对栅格波段执行自定义数学表达式（如 (b4-b3)/(b4+b3)）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "classify_raster",
        "description": "非监督分类：对栅格数据进行KMeans聚类分类，输出分类栅格和类别统计。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "visualize_raster",
        "description": "栅格可视化：将栅格波段渲染为PNG图片（单波段伪彩色或RGB合成）。",
        "annotations": _WRITE_SAFE,
    },

    # --- Spatial Statistics ---
    {
        "name": "spatial_autocorrelation",
        "description": "全局空间自相关检验：计算 Moran's I 统计量，评估属性值的空间聚集/分散模式。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "local_moran",
        "description": "LISA 局部空间自相关：识别 HH（高-高热点）、LL（低-低冷点）等空间聚类，输出 SHP + PNG。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "hotspot_analysis",
        "description": "Getis-Ord Gi* 热点分析：识别统计显著的热点和冷点区域，输出 SHP + PNG。",
        "annotations": _WRITE_SAFE,
    },

    # --- High-level metadata & pipeline tools (v13.1) ---
    {
        "name": "search_catalog",
        "description": "语义搜索数据目录：结合模糊匹配和向量嵌入检索已注册的数据资产（支持自然语言查询）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_data_lineage",
        "description": "数据血缘追踪：查看数据资产的来源链（ancestors）和衍生链（descendants）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_skills",
        "description": "列出所有内置 ADK 技能：返回名称、描述、领域和触发关键词。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_toolsets",
        "description": "列出所有工具集：返回 24 个专业工具集的名称和功能描述。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_virtual_sources",
        "description": "列出虚拟数据源：返回已注册的远程 WFS/STAC/OGC API/自定义 API 数据源。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "run_analysis_pipeline",
        "description": "执行完整分析管线：将自然语言分析需求交给 GIS Agent 执行（通用分析/治理报告/DRL优化），返回分析报告和文件。",
        "annotations": _WRITE_SAFE,
    },
]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_tools(mcp_server) -> int:
    """Register all GIS tools with a FastMCP server instance.

    Returns:
        Number of tools registered.
    """
    fn_map = _get_tool_functions()
    count = 0
    for defn in TOOL_DEFINITIONS:
        name = defn["name"]
        fn = fn_map.get(name)
        if fn is None:
            print(f"[MCP Registry] WARNING: function '{name}' not found, skipping.")
            continue
        wrapped = _wrap_tool(fn)
        mcp_server.add_tool(
            wrapped,
            name=name,
            description=defn.get("description"),
            annotations=defn.get("annotations"),
        )
        count += 1
    return count
