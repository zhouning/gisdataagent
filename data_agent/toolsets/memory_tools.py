"""Memory toolset: persistent per-user spatial memory (save/recall/list/delete)."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..memory import save_memory, recall_memories, list_memories, delete_memory


_ALL_FUNCS = [save_memory, recall_memories, list_memories, delete_memory]


class MemoryToolset(BaseToolset):
    """Persistent spatial memory tools (region, viz preferences, analysis results)."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
