"""Enhanced NL2SQL toolset: semantic grounding + SQL postprocessing."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset


class NL2SQLEnhancedToolset(BaseToolset):
    """Enhanced NL2SQL toolset: grounding first, execution second."""

    def __init__(self, *, single_tool: bool = False, tool_filter=None):
        super().__init__(tool_filter=tool_filter)
        self.single_tool = single_tool

    async def get_tools(self, readonly_context=None):
        # Lazy import to avoid a top-level circular import with nl2sql_executor,
        # which imports from this package's __init__ via `.toolsets.nl2sql_tools`.
        from ..nl2sql_executor import (
            execute_nl2sql,
            prepare_nl2sql_context,
            run_nl2semantic2sql,
        )
        if self.single_tool:
            return [FunctionTool(run_nl2semantic2sql)]
        all_tools = [
            FunctionTool(prepare_nl2sql_context),
            FunctionTool(execute_nl2sql),
        ]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
