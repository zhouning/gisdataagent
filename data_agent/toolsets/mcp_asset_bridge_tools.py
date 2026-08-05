"""High-level governed MCP asset tools exposed to GIS agents."""

from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool

from ..mcp_asset_bridge import describe_mcp_asset_workflow, run_mcp_asset_workflow


class McpAssetBridgeToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        return [
            FunctionTool(describe_mcp_asset_workflow),
            FunctionTool(run_mcp_asset_workflow),
        ]

    async def close(self):
        return None
