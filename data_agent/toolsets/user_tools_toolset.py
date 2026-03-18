"""UserToolset — exposes user-defined custom tools to ADK agents."""
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset


class UserToolset(BaseToolset):
    """Provides user-defined declarative tools (http_call, sql_query, etc.)."""

    def __init__(self, *, tool_filter=None):
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None) -> list[BaseTool]:
        from ..user_tools import list_user_tools
        from ..user_tool_engines import build_function_tool

        tool_defs = list_user_tools(include_shared=True)
        tools = [build_function_tool(td) for td in tool_defs]
        tools = [t for t in tools if t is not None]

        if self.tool_filter is None:
            return tools
        return [t for t in tools if self._is_tool_selected(t, readonly_context)]
