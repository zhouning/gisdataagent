"""Streaming toolset: wraps IoT stream creation, management, and geofence alerts."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..stream_tools import (
    create_iot_stream,
    list_active_streams,
    stop_data_stream,
    get_stream_statistics,
    set_geofence_alert,
)


_ALL_FUNCS = [
    create_iot_stream,
    list_active_streams,
    stop_data_stream,
    get_stream_statistics,
    set_geofence_alert,
]


class StreamingToolset(BaseToolset):
    """Real-time IoT data stream and geofence alert tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
