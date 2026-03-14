"""Spatial Analysis Tier 2 toolset: IDW, Kriging, GWR, Change Detection, Viewshed."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..spatial_analysis_tier2 import (
    idw_interpolation,
    kriging_interpolation,
    gwr_analysis,
    spatial_change_detection,
    viewshed_analysis,
)

_ALL_FUNCS = [
    idw_interpolation,
    kriging_interpolation,
    gwr_analysis,
    spatial_change_detection,
    viewshed_analysis,
]


class SpatialAnalysisTier2Toolset(BaseToolset):
    """Advanced spatial analysis: interpolation, GWR, change detection, viewshed."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
