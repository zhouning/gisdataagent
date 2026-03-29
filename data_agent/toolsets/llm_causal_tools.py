"""LLM-based causal inference toolset (Angle B): DAG, counterfactual, mechanism, what-if."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..llm_causal import (
    construct_causal_dag,
    counterfactual_reasoning,
    explain_causal_mechanism,
    generate_what_if_scenarios,
)

_ALL_FUNCS = [
    construct_causal_dag,
    counterfactual_reasoning,
    explain_causal_mechanism,
    generate_what_if_scenarios,
]


class LLMCausalToolset(BaseToolset):
    """LLM因果推理: DAG构建、反事实推理、机制解释、情景生成 (Angle B)."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
