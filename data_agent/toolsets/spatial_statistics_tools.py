"""Spatial statistics toolset: Global Moran's I, LISA, Getis-Ord Gi* hotspot analysis."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..spatial_statistics import (
    spatial_autocorrelation,
    local_moran,
    hotspot_analysis,
)

_ALL_FUNCS = [spatial_autocorrelation, local_moran, hotspot_analysis]


class SpatialStatisticsToolset(BaseToolset):
    """Spatial autocorrelation and hotspot analysis tools (PySAL)."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
