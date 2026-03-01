"""Semantic layer toolset: wraps semantic catalog, annotation, and export functions."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..semantic_layer import (
    resolve_semantic_context,
    describe_table_semantic,
    register_semantic_annotation,
    register_source_metadata,
    list_semantic_sources,
    register_semantic_domain,
    discover_column_equivalences,
    export_semantic_model,
)


_ALL_FUNCS = [
    resolve_semantic_context,
    describe_table_semantic,
    register_semantic_annotation,
    register_source_metadata,
    list_semantic_sources,
    register_semantic_domain,
    discover_column_equivalences,
    export_semantic_model,
]


class SemanticLayerToolset(BaseToolset):
    """Semantic catalog resolution, annotation, and model export tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
