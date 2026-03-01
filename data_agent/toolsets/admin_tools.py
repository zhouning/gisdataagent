"""Admin toolset: usage tracking, audit log queries, and template management."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..token_tracker import get_usage_summary
from ..audit_logger import query_audit_log
from ..template_manager import list_templates, delete_template, share_template


_ALL_FUNCS = [
    get_usage_summary,
    query_audit_log,
    list_templates,
    delete_template,
    share_template,
]


class AdminToolset(BaseToolset):
    """Token usage, audit log, and analysis template management tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
