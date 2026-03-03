"""MCP Hub Toolset — BaseToolset wrapper for MCP Hub Manager tools.

Aggregates tools from all connected MCP servers, compatible with
ADK agent tools=[] list alongside other BaseToolset instances.
"""
from typing import List, Optional

from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.base_tool import BaseTool


class McpHubToolset(BaseToolset):
    """Provides MCP tools from connected servers to ADK agents.

    Delegates to McpHubManager for tool discovery. When no MCP servers
    are connected, returns an empty list (safe no-op).

    Args:
        pipeline: Only include tools from servers configured for this pipeline.
        tool_filter: Optional list of tool names to include.
    """

    def __init__(self, *, pipeline: str = None, tool_filter=None):
        super().__init__(tool_filter=tool_filter)
        self._pipeline = pipeline

    async def get_tools(
        self, readonly_context=None
    ) -> List[BaseTool]:
        from ..mcp_hub import get_mcp_hub

        hub = get_mcp_hub()
        try:
            all_tools = await hub.get_all_tools(pipeline=self._pipeline)
        except Exception:
            return []

        if self.tool_filter is None:
            return all_tools
        return [
            tool for tool in all_tools
            if self._is_tool_selected(tool, readonly_context)
        ]

    async def close(self):
        """Cleanup handled by McpHubManager.shutdown(), not per-toolset."""
        pass
