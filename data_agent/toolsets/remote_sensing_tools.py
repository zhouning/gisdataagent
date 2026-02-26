"""Remote sensing toolset: raster profiling, NDVI, band math, classification, visualization."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..remote_sensing import (
    describe_raster,
    calculate_ndvi,
    raster_band_math,
    classify_raster,
    visualize_raster,
)

_ALL_FUNCS = [describe_raster, calculate_ndvi, raster_band_math,
              classify_raster, visualize_raster]


class RemoteSensingToolset(BaseToolset):
    """Raster analysis and remote sensing tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
