"""Advanced analysis toolset: spatiotemporal, scenario simulation, network."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..advanced_analysis import (
    time_series_forecast,
    spatial_trend_analysis,
    what_if_analysis,
    scenario_compare,
    network_centrality,
    community_detection,
    accessibility_analysis,
)

_ALL_FUNCS = [
    time_series_forecast,
    spatial_trend_analysis,
    what_if_analysis,
    scenario_compare,
    network_centrality,
    community_detection,
    accessibility_analysis,
]


class AdvancedAnalysisToolset(BaseToolset):
    """Spatiotemporal forecasting, scenario simulation, and network analysis tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
