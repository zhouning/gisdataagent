"""Tool Evolution toolset: dynamic tool library management, metadata, failure-driven discovery."""
import json

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..tool_evolution import get_evolution_engine


# ---------------------------------------------------------------------------
# Tool functions (thin wrappers around ToolEvolutionEngine)
# ---------------------------------------------------------------------------

def get_tool_metadata(tool_name: str) -> str:
    """获取指定工具的详细元数据 (描述、成本、可靠性、适用场景、替代方案)。

    Args:
        tool_name: 工具名称 (如 "calculate_ndvi", "hotspot_analysis")
    Returns:
        JSON: 工具元数据详情
    """
    return get_evolution_engine().get_tool_metadata(tool_name)


def list_tools(category: str = "", sort_by: str = "name") -> str:
    """列出所有可用工具及其元数据。可按类别筛选，按名称/成本/可靠性排序。

    Args:
        category: 可选类别过滤 (spatial_processing/remote_sensing/database_management/quality_audit/advanced_analysis 等)
        sort_by: 排序字段 — "name" / "cost" / "reliability" / "category"
    Returns:
        JSON: 工具列表及元数据
    """
    return get_evolution_engine().list_tools_with_metadata(category, sort_by)


def suggest_tools_for_task(task_description: str) -> str:
    """根据任务描述智能推荐最佳工具组合。支持中英文任务描述。

    Args:
        task_description: 任务描述 (如 "分析农田植被变化", "水文流域提取", "spatial clustering analysis")
    Returns:
        JSON: 推荐的工具列表及理由
    """
    return get_evolution_engine().suggest_tools_for_task(task_description)


def analyze_tool_failures(tool_name: str = "") -> str:
    """分析工具失败模式，推荐改进措施。从历史失败数据库获取数据。

    Args:
        tool_name: 可选 — 指定工具名。为空则生成全局失败摘要。
    Returns:
        JSON: 失败分析报告及改进建议
    """
    return get_evolution_engine().analyze_tool_failures(tool_name)


def register_tool(name: str, description: str, category: str = "uncategorized",
                  cost_level: str = "low", scenarios: str = "[]") -> str:
    """注册一个新的动态工具到演化注册表。用于运行时扩展工具库。

    Args:
        name: 工具名称 (英文，snake_case)
        description: 工具功能描述
        category: 工具类别 (spatial_processing/remote_sensing/database_management 等)
        cost_level: 成本等级 (low/medium/high)
        scenarios: 适用场景列表 (JSON 数组字符串, 如 '["植被监测","农田评估"]')
    Returns:
        JSON: 注册结果
    """
    try:
        scenario_list = json.loads(scenarios) if scenarios else []
    except (json.JSONDecodeError, TypeError):
        scenario_list = []
    return get_evolution_engine().register_tool(name, description, category, cost_level, scenario_list)


def deactivate_tool(name: str, reason: str = "") -> str:
    """停用一个工具 (标记为不活跃)。用于淘汰过时或不可靠的工具。

    Args:
        name: 工具名称
        reason: 停用原因
    Returns:
        JSON: 操作结果
    """
    return get_evolution_engine().deactivate_tool(name, reason)


def get_failure_suggestions(failed_tool: str, error_message: str) -> str:
    """根据工具失败信息，推荐替代工具或前置修复工具。失败驱动的工具发现。

    Args:
        failed_tool: 失败的工具名称
        error_message: 错误信息
    Returns:
        JSON: 推荐的替代或修复工具
    """
    return get_evolution_engine().get_failure_driven_suggestions(failed_tool, error_message)


def tool_evolution_report() -> str:
    """生成工具生态系统健康报告 — 工具总数、类别分布、成本分布、活跃率等。

    Returns:
        JSON: 工具生态系统综合报告
    """
    return get_evolution_engine().get_evolution_report()


def run_self_evolution_cycle(
    limit: int = 50,
    days: int = 7,
    min_score: float = 0.5,
    include_prompt_suggestions: str = "false",
    apply: str = "false",
    environment: str = "dev",
    persist: str = "true",
    triggered_by: str = "",
    trigger_source: str = "tool",
) -> str:
    """运行一次自主进化周期，汇总反馈、失败、评测坏例并生成改进提案。

    默认 dry-run：只观察、分析和提出建议，不自动修改 prompt、工具或评测集。
    默认记录周期报告，便于后续人工审批和审计。

    Args:
        limit: 每类学习信号最多读取数量，范围 1-100。
        days: 反馈和失败窗口天数，范围 1-90。
        min_score: eval_history 中低于该分数的评测记录会进入坏例。
        include_prompt_suggestions: true 时生成 prompt 改进建议。
        apply: true 时才把 prompt 建议写入指定 environment。
        environment: prompt 写入环境，默认 dev。
        persist: true 时把进化周期报告保存到 agent_self_evolution_cycles。
        triggered_by: 触发人或系统标识，写入审计记录。
        trigger_source: 触发来源，如 tool / scheduler / api。
    Returns:
        JSON: 自主进化周期报告与待审改进提案。
    """
    import asyncio
    from ..self_evolution import SelfEvolutionEngine

    async def _run():
        return await SelfEvolutionEngine().run_cycle(
            limit=limit,
            days=days,
            min_score=min_score,
            include_prompt_suggestions=include_prompt_suggestions,
            apply=apply,
            environment=environment,
            persist=persist,
            triggered_by=triggered_by,
            trigger_source=trigger_source,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(_run())
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(lambda: asyncio.run(_run())).result()
    return json.dumps(result, ensure_ascii=False, default=str)


_ALL_FUNCS = [
    get_tool_metadata,
    list_tools,
    suggest_tools_for_task,
    analyze_tool_failures,
    register_tool,
    deactivate_tool,
    get_failure_suggestions,
    tool_evolution_report,
    run_self_evolution_cycle,
]


class ToolEvolutionToolset(BaseToolset):
    """Tool evolution: dynamic tool library management, metadata, failure-driven discovery."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
