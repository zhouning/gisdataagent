"""Database toolset: wraps query_database, list_tables, describe_table, share_table."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..database_tools import query_database, list_tables, describe_table, share_table


_ALL_FUNCS = [query_database, list_tables, describe_table, share_table]


class DatabaseToolset(BaseToolset):
    """PostgreSQL/PostGIS database query and management tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
