"""
Code Exporter — Generate reproducible Python scripts from analysis pipelines.

PRD F8: Export the Agent's tool execution log as a standalone Python script
that imports and calls the project's tool functions with recorded arguments.
"""
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional

# --- Tool function name → import statement ---
TOOL_IMPORT_MAP = {
    # Exploration tools
    "describe_geodataframe": "from data_agent.toolsets.exploration_tools import describe_geodataframe",
    "reproject_spatial_data": "from data_agent.toolsets.exploration_tools import reproject_spatial_data",
    "engineer_spatial_features": "from data_agent.toolsets.exploration_tools import engineer_spatial_features",
    # GIS processors
    "check_topology": "from data_agent.gis_processors import check_topology",
    "check_field_standards": "from data_agent.gis_processors import check_field_standards",
    "generate_tessellation": "from data_agent.gis_processors import generate_tessellation",
    "raster_to_polygon": "from data_agent.gis_processors import raster_to_polygon",
    "pairwise_clip": "from data_agent.gis_processors import pairwise_clip",
    "tabulate_intersection": "from data_agent.gis_processors import tabulate_intersection",
    "surface_parameters": "from data_agent.gis_processors import surface_parameters",
    "zonal_statistics_as_table": "from data_agent.gis_processors import zonal_statistics_as_table",
    "perform_clustering": "from data_agent.gis_processors import perform_clustering",
    "create_buffer": "from data_agent.gis_processors import create_buffer",
    "summarize_within": "from data_agent.gis_processors import summarize_within",
    "overlay_difference": "from data_agent.gis_processors import overlay_difference",
    "find_within_distance": "from data_agent.gis_processors import find_within_distance",
    "generate_heatmap": "from data_agent.gis_processors import generate_heatmap",
    "polygon_neighbors": "from data_agent.gis_processors import polygon_neighbors",
    "add_field": "from data_agent.gis_processors import add_field",
    "add_join": "from data_agent.gis_processors import add_join",
    "calculate_field": "from data_agent.gis_processors import calculate_field",
    "summary_statistics": "from data_agent.gis_processors import summary_statistics",
    # Doc auditor
    "check_consistency": "from data_agent.doc_auditor import check_consistency",
    # Geocoding
    "batch_geocode": "from data_agent.geocoding import batch_geocode",
    "reverse_geocode": "from data_agent.geocoding import reverse_geocode",
    "calculate_driving_distance": "from data_agent.geocoding import calculate_driving_distance",
    "search_nearby_poi": "from data_agent.geocoding import search_nearby_poi",
    "search_poi_by_keyword": "from data_agent.geocoding import search_poi_by_keyword",
    "get_admin_boundary": "from data_agent.geocoding import get_admin_boundary",
    # Population data tools
    "get_population_data": "from data_agent.population_data import get_population_data",
    "aggregate_population": "from data_agent.population_data import aggregate_population",
    # Analysis tools
    "ffi": "from data_agent.toolsets.analysis_tools import ffi",
    "drl_model": "from data_agent.toolsets.analysis_tools import drl_model",
    # Visualization tools
    "visualize_geodataframe": "from data_agent.toolsets.visualization_tools import visualize_geodataframe",
    "visualize_interactive_map": "from data_agent.toolsets.visualization_tools import visualize_interactive_map",
    "visualize_optimization_comparison": "from data_agent.toolsets.visualization_tools import visualize_optimization_comparison",
    "generate_choropleth": "from data_agent.toolsets.visualization_tools import generate_choropleth",
    "generate_bubble_map": "from data_agent.toolsets.visualization_tools import generate_bubble_map",
    "export_map_png": "from data_agent.toolsets.visualization_tools import export_map_png",
    "compose_map": "from data_agent.toolsets.visualization_tools import compose_map",
    # Database tools
    "query_database": "from data_agent.database_tools import query_database",
    "list_tables": "from data_agent.database_tools import list_tables",
    "describe_table": "from data_agent.database_tools import describe_table",
    # ArcPy tools (require ArcGIS Pro)
    "arcpy_buffer": "from data_agent.arcpy_tools import arcpy_buffer",
    "arcpy_clip": "from data_agent.arcpy_tools import arcpy_clip",
    "arcpy_dissolve": "from data_agent.arcpy_tools import arcpy_dissolve",
    "arcpy_project": "from data_agent.arcpy_tools import arcpy_project",
    "arcpy_check_geometry": "from data_agent.arcpy_tools import arcpy_check_geometry",
    "arcpy_repair_geometry": "from data_agent.arcpy_tools import arcpy_repair_geometry",
    "arcpy_slope": "from data_agent.arcpy_tools import arcpy_slope",
    "arcpy_zonal_statistics": "from data_agent.arcpy_tools import arcpy_zonal_statistics",
    # Remote sensing tools
    "describe_raster": "from data_agent.remote_sensing import describe_raster",
    "calculate_ndvi": "from data_agent.remote_sensing import calculate_ndvi",
    "raster_band_math": "from data_agent.remote_sensing import raster_band_math",
    "classify_raster": "from data_agent.remote_sensing import classify_raster",
    "visualize_raster": "from data_agent.remote_sensing import visualize_raster",
    # Spatial statistics tools
    "spatial_autocorrelation": "from data_agent.spatial_statistics import spatial_autocorrelation",
    "local_moran": "from data_agent.spatial_statistics import local_moran",
    "hotspot_analysis": "from data_agent.spatial_statistics import hotspot_analysis",
}

# Tools that depend on platform context and should not be exported
NON_EXPORTABLE_TOOLS = {
    "save_memory", "recall_memories", "list_memories", "delete_memory",
    "get_usage_summary", "list_user_files", "delete_user_file",
    "query_audit_log", "share_table",
    "save_as_template", "list_templates", "delete_template", "share_template",
}

PIPELINE_LABELS = {
    "optimization": "空间优化管线 (Optimization Pipeline)",
    "governance": "数据治理管线 (Governance Pipeline)",
    "general": "通用分析管线 (General Pipeline)",
    "planner": "动态规划管线 (Dynamic Planner)",
}

# Path-like argument names (use raw strings in output)
_PATH_ARG_NAMES = {
    "file_path", "input_path", "output_path", "raster_path",
    "target_path", "join_path", "zone_path", "value_path",
    "pdf_path", "shp_path", "data_path", "clip_path",
}

# Tools requiring special environment setup
COMPLEX_TOOLS = {
    "drl_model": "DRL 模型需要 PyTorch + scorer_weights_v7.pt 权重文件",
    "check_consistency": "多模态一致性检查，需要特定格式的 PDF 文档和 SHP 数据",
}

# Tools requiring API keys
API_KEY_TOOLS = {
    "batch_geocode": "GAODE_API_KEY",
    "reverse_geocode": "GAODE_API_KEY",
    "calculate_driving_distance": "GAODE_API_KEY",
    "search_nearby_poi": "GAODE_API_KEY",
    "search_poi_by_keyword": "GAODE_API_KEY",
    "get_admin_boundary": "GAODE_API_KEY",
    "get_population_data": "GAODE_API_KEY",
}


def generate_python_script(
    tool_log: List[Dict],
    pipeline_type: str = "general",
    user_message: str = "",
    uploaded_files: Optional[List[str]] = None,
    intent: str = "GENERAL",
    tool_descriptions: Optional[Dict] = None,
) -> str:
    """
    Generate a reproducible Python script from a tool execution log.

    Args:
        tool_log: List of dicts with keys: step, agent_name, tool_name, args,
                  output_path, result_summary, duration, is_error.
        pipeline_type: 'optimization', 'governance', 'general', or 'planner'.
        user_message: The original user query text.
        uploaded_files: List of uploaded filenames.
        intent: Router intent string (GENERAL, GOVERNANCE, OPTIMIZATION).
        tool_descriptions: TOOL_DESCRIPTIONS dict from app.py for Chinese labels.

    Returns:
        Complete Python script as a string.
    """
    parts = []
    parts.append(_build_header(pipeline_type, user_message, intent, uploaded_files))
    parts.append(_build_setup_block(tool_log))
    parts.append(_build_imports(tool_log))
    parts.append("")

    # Count exportable steps for display
    exportable = [r for r in tool_log
                  if r["tool_name"] not in NON_EXPORTABLE_TOOLS and not r.get("is_error")]
    total_exportable = len(exportable)
    export_step = 0

    # Data flow tracing: map output_path → variable name
    path_map = {}  # {output_path_string: "result_N"}

    for record in tool_log:
        tool_name = record["tool_name"]

        if tool_name in NON_EXPORTABLE_TOOLS:
            desc = tool_descriptions.get(tool_name, {}).get("method", tool_name) if tool_descriptions else tool_name
            parts.append(f"# {'═' * 50}")
            parts.append(f"# [跳过] {desc}")
            parts.append(f"# 平台功能，脚本模式下不适用")
            parts.append("")
            continue

        if record.get("is_error"):
            desc = tool_descriptions.get(tool_name, {}).get("method", tool_name) if tool_descriptions else tool_name
            parts.append(f"# {'═' * 50}")
            parts.append(f"# [失败，已跳过] {desc}")
            parts.append(f"# 原始错误: {record.get('result_summary', '')[:100]}")
            parts.append("")
            continue

        export_step += 1
        parts.append(_build_step(record, export_step, total_exportable,
                                 tool_descriptions, path_map))

        # Register output_path for data flow chaining
        output_path = record.get("output_path")
        if output_path:
            var_name = f"result_{export_step}"
            path_map[output_path] = var_name
            # Also register basename for fuzzy matching
            basename = os.path.basename(output_path)
            if basename:
                path_map[basename] = var_name

    parts.append(f'print(f"\\n\\u2713 分析完成，共 {total_exportable} 个步骤。")')
    parts.append("")

    return "\n".join(parts)


def _build_header(
    pipeline_type: str,
    user_message: str,
    intent: str,
    uploaded_files: Optional[List[str]],
) -> str:
    """Build the script file header with metadata."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pipeline_label = PIPELINE_LABELS.get(pipeline_type, pipeline_type)
    files_str = ", ".join(uploaded_files) if uploaded_files else "(none)"
    user_msg_display = user_message[:200] if user_message else "(none)"

    return f'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GIS Data Agent — 分析流程导出
==============================
任务: {user_msg_display}
管线: {pipeline_label} ({intent})
导出时间: {now}
输入文件: {files_str}

使用方法:
  1. 安装依赖: pip install geopandas pandas folium matplotlib scikit-learn
  2. 确保 data_agent 项目在 Python 路径中
  3. 运行: python <this_script>.py
"""
'''


def _build_setup_block(tool_log: Optional[List[Dict]] = None) -> str:
    """Build the sys.path and user_context initialization block."""
    lines = [
        'import os, sys',
        '',
        '# 将项目根目录加入 Python 路径',
        '_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
        'if _project_root not in sys.path:',
        '    sys.path.insert(0, _project_root)',
        '',
        'from data_agent.user_context import current_user_id',
        'current_user_id.set("script_export")',
    ]

    # Check if any API-key-dependent tools are used
    if tool_log:
        needed_keys = set()
        for record in tool_log:
            key = API_KEY_TOOLS.get(record.get("tool_name"))
            if key and not record.get("is_error"):
                needed_keys.add(key)
        if needed_keys:
            lines.append('')
            lines.append('# --- 检查必要的 API 密钥 ---')
            for key in sorted(needed_keys):
                lines.append(f'if not os.environ.get("{key}"):')
                lines.append(f'    print("WARNING: {key} 未设置，相关工具将无法运行。")')

    return '\n'.join(lines) + '\n'


def _build_imports(tool_log: List[Dict]) -> str:
    """Collect and deduplicate import statements from the tool log."""
    seen_imports = set()
    import_lines = []

    for record in tool_log:
        tool_name = record["tool_name"]
        if tool_name in NON_EXPORTABLE_TOOLS:
            continue
        if record.get("is_error"):
            continue
        imp = TOOL_IMPORT_MAP.get(tool_name)
        if imp and imp not in seen_imports:
            seen_imports.add(imp)
            import_lines.append(imp)

    if not import_lines:
        return "# (no tool imports needed)"

    return "# --- 导入工具函数 ---\n" + "\n".join(import_lines)


def _build_step(
    record: Dict,
    step_num: int,
    total: int,
    tool_descriptions: Optional[Dict],
    path_map: Optional[Dict[str, str]] = None,
) -> str:
    """Build a single tool call code block."""
    tool_name = record["tool_name"]
    args = record.get("args", {})

    # Get Chinese description
    if tool_descriptions and tool_name in tool_descriptions:
        desc = tool_descriptions[tool_name].get("method", tool_name)
    else:
        desc = tool_name

    lines = []
    lines.append(f"# {'═' * 50}")
    lines.append(f"# 步骤 {step_num}/{total}: {desc}")

    # Add agent context if available
    agent_name = record.get("agent_name")
    if agent_name:
        lines.append(f"# Agent: {agent_name}")

    # Warnings for complex tools
    if tool_name in COMPLEX_TOOLS:
        lines.append(f"# WARNING: {COMPLEX_TOOLS[tool_name]}")
        lines.append("# TODO: 运行前请确认环境依赖已安装")

    # Warnings for API-key-dependent tools
    if tool_name in API_KEY_TOOLS:
        lines.append(f"# IMPORTANT: 此工具需要 {API_KEY_TOOLS[tool_name]} 环境变量")

    lines.append(f'print("步骤 {step_num}/{total}: {desc}...")')

    # Build function call
    if not args:
        lines.append(f"result_{step_num} = {tool_name}()")
    else:
        # Check if any arg value is long (JSON, etc.)
        pre_vars = []
        call_args = []
        for key, value in args.items():
            # Data flow tracing: check if value matches a previous output_path
            chained_var = _check_path_chain(key, value, path_map)
            if chained_var:
                call_args.append(f"    {key}={chained_var},  # 来自前序步骤的输出")
                continue

            formatted = _format_arg_value(key, value)
            if len(formatted) > 120 or "\n" in str(value):
                var_name = f"_{key}_{step_num}"
                pre_vars.append(f"{var_name} = {formatted}")
                call_args.append(f"    {key}={var_name},")
            else:
                call_args.append(f"    {key}={formatted},")

        for pv in pre_vars:
            lines.append(pv)

        lines.append(f"result_{step_num} = {tool_name}(")
        lines.extend(call_args)
        lines.append(")")

    lines.append(f'print(f"  -> {{result_{step_num}}}")')
    lines.append("")

    return "\n".join(lines)


def _check_path_chain(
    key: str, value, path_map: Optional[Dict[str, str]]
) -> Optional[str]:
    """Check if an argument value matches a previous step's output_path.

    Returns the variable name (e.g. 'result_1') if matched, else None.
    """
    if not path_map or not isinstance(value, str):
        return None
    # Exact match
    if value in path_map:
        return path_map[value]
    # Basename match
    basename = os.path.basename(value)
    if basename and basename in path_map:
        return path_map[basename]
    # Normalized path match (handle mixed slashes)
    norm = os.path.normpath(value)
    for stored_path, var_name in path_map.items():
        if os.path.normpath(stored_path) == norm:
            return var_name
    return None


def _format_arg_value(key: str, value) -> str:
    """
    Format an argument value for code generation.

    - Path-like args → raw strings r"..."
    - Strings → repr()
    - Numbers/bools → str()
    - Long JSON strings → multi-line
    """
    if value is None:
        return "None"

    if isinstance(value, bool):
        return "True" if value else "False"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        # Path-like argument names get raw strings
        if key in _PATH_ARG_NAMES or (
            os.sep in value or "/" in value or value.endswith((".shp", ".csv", ".tif", ".geojson", ".gpkg"))
        ):
            return f'r"{value}"'

        # Long JSON-like strings
        if len(value) > 120 and (value.startswith("[") or value.startswith("{")):
            return f'"""{value}"""'

        return repr(value)

    if isinstance(value, dict):
        import json
        json_str = json.dumps(value, ensure_ascii=False, indent=2)
        if len(json_str) > 80:
            return json_str
        return repr(value)

    if isinstance(value, list):
        return repr(value)

    return repr(value)


def save_script_to_file(script: str, output_dir: str) -> str:
    """
    Save the generated script to a .py file.

    Args:
        script: The Python script content.
        output_dir: Directory to save the file in.

    Returns:
        Full path to the saved file.
    """
    os.makedirs(output_dir, exist_ok=True)
    uid = uuid.uuid4().hex[:8]
    filename = f"analysis_script_{uid}.py"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(script)
    return filepath
