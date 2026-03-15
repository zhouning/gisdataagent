"""Watershed analysis toolset: catchment extraction, stream network, flow accumulation."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..watershed_analysis import (
    extract_watershed,
    extract_stream_network,
    compute_flow_accumulation,
)

_ALL_FUNCS = [extract_watershed, extract_stream_network, compute_flow_accumulation]


class WatershedToolset(BaseToolset):
    """Hydrological watershed analysis: catchment delineation, stream extraction, flow accumulation."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
