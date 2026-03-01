"""DataLake toolset: data asset catalog discovery, search, and management."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..data_catalog import (
    list_data_assets,
    describe_data_asset,
    search_data_assets,
    register_data_asset,
    tag_data_asset,
    delete_data_asset,
    share_data_asset,
)

_ALL_FUNCS = [list_data_assets, describe_data_asset, search_data_assets,
              register_data_asset, tag_data_asset, delete_data_asset,
              share_data_asset]


class DataLakeToolset(BaseToolset):
    """Data lake asset catalog tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
