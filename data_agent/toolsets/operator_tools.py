"""
OperatorToolset — exposes 4 high-level semantic operator tools to ADK agents.

The Planner can call `clean_data`, `integrate_data`, `analyze_data`,
`visualize_data` instead of managing dozens of low-level tools.
Each tool auto-profiles the data, plans a strategy, and executes it.
"""
import json

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..agent_composer import DataProfile, extract_profile
from ..semantic_operators import (
    OperatorRegistry,
    OperatorResult,
)
from ..observability import get_logger

logger = get_logger("operator_tools")


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def clean_data(file_path: str, standard: str = "", strategy: str = "",
               task_description: str = "") -> str:
    """数据清洗语义算子: 根据数据特征自动选择清洗策略并执行。

    自动检测 CRS 不一致、空值、PII、拓扑错误等问题并修复。
    可选指定标准 (如 dltb_2023, gb_t_21010_2017) 进行标准校验。

    Args:
        file_path: 待清洗的数据文件路径
        standard: 可选, 数据标准ID (如 dltb_2023)
        strategy: 可选, 强制策略 (auto_fix/crs_standardize/masking)
        task_description: 可选, 清洗任务的自然语言描述
    Returns:
        JSON 结果: status, output_files, metrics, summary, details
    """
    op = OperatorRegistry.get("clean")
    if not op:
        return json.dumps({"status": "error", "message": "CleanOperator not registered"})

    desc = task_description
    if standard:
        desc += f" 标准: {standard}"

    profile = extract_profile(file_path)
    plan = op.plan(profile, desc)
    result = op.execute(plan)
    return json.dumps(result.to_dict(), ensure_ascii=False, default=str)


def integrate_data(file_paths: str, join_type: str = "auto",
                   target_crs: str = "", task_description: str = "") -> str:
    """数据集成语义算子: 多源数据融合、Schema 对齐、CRS 统一。

    自动探查源数据特征,评估兼容性,选择最优融合策略并执行。

    Args:
        file_paths: 逗号分隔的数据文件路径列表
        join_type: 可选, 连接类型 (auto/spatial_join/attribute_join/overlay)
        target_crs: 可选, 目标坐标系 (默认自动检测)
        task_description: 可选, 集成任务的自然语言描述
    Returns:
        JSON 结果: status, output_files, metrics, summary, details
    """
    op = OperatorRegistry.get("integrate")
    if not op:
        return json.dumps({"status": "error", "message": "IntegrateOperator not registered"})

    first_file = file_paths.split(",")[0].strip()
    profile = extract_profile(first_file) if first_file else DataProfile()
    profile.file_path = file_paths  # pass all paths

    desc = task_description
    if join_type != "auto":
        desc += f" {join_type}"

    plan = op.plan(profile, desc)
    result = op.execute(plan)
    return json.dumps(result.to_dict(), ensure_ascii=False, default=str)


def analyze_data(file_path: str, analysis_type: str = "",
                 params: str = "", task_description: str = "") -> str:
    """空间分析语义算子: 根据数据特征和分析意图自动选择分析方法。

    支持: 空间统计(Moran/热点), DRL优化, 因果推断, 地形分析, 缓冲叠加, 时空预测。

    Args:
        file_path: 待分析的数据文件路径
        analysis_type: 可选, 分析类型 (spatial_stats/drl_optimize/causal/terrain/geoprocessing/world_model/governance)
        params: 可选, JSON 格式的额外参数
        task_description: 可选, 分析任务的自然语言描述
    Returns:
        JSON 结果: status, output_files, metrics, summary, details
    """
    op = OperatorRegistry.get("analyze")
    if not op:
        return json.dumps({"status": "error", "message": "AnalyzeOperator not registered"})

    desc = task_description
    if analysis_type:
        desc += f" {analysis_type}"

    profile = extract_profile(file_path)
    plan = op.plan(profile, desc)
    result = op.execute(plan)
    return json.dumps(result.to_dict(), ensure_ascii=False, default=str)


def visualize_data(file_path: str, viz_type: str = "",
                   params: str = "", task_description: str = "") -> str:
    """可视化语义算子: 根据数据特征自动选择可视化方式。

    支持: 交互地图/分类着色/热力图/统计图表/雷达图/报告导出。

    Args:
        file_path: 待可视化的数据文件路径
        viz_type: 可选, 可视化类型 (interactive_map/choropleth/heatmap/charts/radar/report)
        params: 可选, JSON 格式的额外参数
        task_description: 可选, 可视化任务的自然语言描述
    Returns:
        JSON 结果: status, output_files, metrics, summary, details
    """
    op = OperatorRegistry.get("visualize")
    if not op:
        return json.dumps({"status": "error", "message": "VisualizeOperator not registered"})

    desc = task_description
    if viz_type:
        desc += f" {viz_type}"

    profile = extract_profile(file_path)
    plan = op.plan(profile, desc)
    result = op.execute(plan)
    return json.dumps(result.to_dict(), ensure_ascii=False, default=str)


def list_operators() -> str:
    """列出所有可用的语义算子及其描述。

    Returns:
        JSON 列表: [{name, description}, ...]
    """
    operators = OperatorRegistry.list_all()
    return json.dumps(operators, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset
# ---------------------------------------------------------------------------

_ALL_FUNCS = [clean_data, integrate_data, analyze_data, visualize_data, list_operators]


class OperatorToolset(BaseToolset):
    """Semantic operator toolset — 5 high-level data operation tools."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_tools(self, readonly_context=None) -> list:
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter:
            return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
        return all_tools
