"""Causal inference toolset: PSM, ERF, DiD, Granger, GCCM, Causal Forest."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..causal_inference import (
    propensity_score_matching,
    exposure_response_function,
    difference_in_differences,
    spatial_granger_causality,
    geographic_causal_mapping,
    causal_forest_analysis,
)

_ALL_FUNCS = [
    propensity_score_matching,
    exposure_response_function,
    difference_in_differences,
    spatial_granger_causality,
    geographic_causal_mapping,
    causal_forest_analysis,
]


class CausalInferenceToolset(BaseToolset):
    """Spatial-temporal causal inference: PSM, DiD, Granger, GCCM, ERF, Causal Forest."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
