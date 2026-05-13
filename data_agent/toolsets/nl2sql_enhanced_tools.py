"""Enhanced NL2SQL toolset: semantic grounding + SQL postprocessing."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset


class NL2SQLEnhancedToolset(BaseToolset):
    """Enhanced NL2SQL toolset: grounding first, execution second."""

    async def get_tools(self, readonly_context=None):
        # Lazy import to avoid a top-level circular import with nl2sql_executor,
        # which imports from this package's __init__ via `.toolsets.nl2sql_tools`.
        from ..nl2sql_executor import prepare_nl2sql_context, execute_nl2sql
        return [
            FunctionTool(prepare_nl2sql_context),
            FunctionTool(execute_nl2sql),
        ]
