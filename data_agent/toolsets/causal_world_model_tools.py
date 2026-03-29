"""Causal World Model toolset (Angle C): intervention, counterfactual, embedding effects."""
import asyncio

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..causal_world_model import (
    intervention_predict,
    counterfactual_comparison,
    embedding_treatment_effect,
    integrate_statistical_prior,
)


# -- Async wrappers for long-running tools (world model inference x2) --

async def _intervention_predict_async(
    bbox: str,
    intervention_sub_bbox: str,
    intervention_type: str = "ecological_restoration",
    baseline_scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """干预预测：对子区域施加干预情景，其余区域用基线，分析空间溢出效应。"""
    return await asyncio.to_thread(
        intervention_predict, bbox, intervention_sub_bbox,
        intervention_type, baseline_scenario, start_year, n_years,
    )


async def _counterfactual_comparison_async(
    bbox: str,
    scenario_a: str = "baseline",
    scenario_b: str = "ecological_restoration",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """反事实对比：平行运行两个情景，计算因果效应图。"""
    return await asyncio.to_thread(
        counterfactual_comparison, bbox, scenario_a, scenario_b,
        start_year, n_years,
    )


class CausalWorldModelToolset(BaseToolset):
    """因果世界模型: 干预预测、反事实对比、嵌入效应、统计先验整合 (Angle C)."""

    async def get_tools(self, readonly_context=None):
        all_tools = [
            LongRunningFunctionTool(_intervention_predict_async),
            LongRunningFunctionTool(_counterfactual_comparison_async),
            FunctionTool(embedding_treatment_effect),
            FunctionTool(integrate_statistical_prior),
        ]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
