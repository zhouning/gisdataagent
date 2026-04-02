"""Geo-processing toolset: spatial GIS operations and optional ArcPy tools."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..gis_processors import (
    generate_tessellation,
    raster_to_polygon,
    pairwise_clip,
    tabulate_intersection,
    surface_parameters,
    zonal_statistics_as_table,
    perform_clustering,
    create_buffer,
    summarize_within,
    overlay_difference,
    generate_heatmap,
    find_within_distance,
    polygon_neighbors,
    add_field,
    add_join,
    calculate_field,
    summary_statistics,
    filter_vector_data,
)

# ArcPy tools (optional)
ARCPY_AVAILABLE = False
_arcpy_funcs = []
_arcpy_gov_explore_funcs = []
_arcpy_gov_process_funcs = []

try:
    from ..arcpy_tools import (
        is_arcpy_available,
        arcpy_buffer, arcpy_clip, arcpy_dissolve, arcpy_project,
        arcpy_check_geometry, arcpy_repair_geometry,
        arcpy_slope, arcpy_zonal_statistics, arcpy_extract_watershed,
    )
    if is_arcpy_available():
        ARCPY_AVAILABLE = True
        _arcpy_funcs = [
            arcpy_buffer, arcpy_clip, arcpy_dissolve, arcpy_project,
            arcpy_repair_geometry, arcpy_slope, arcpy_zonal_statistics,
            arcpy_extract_watershed,
        ]
        _arcpy_gov_explore_funcs = [arcpy_check_geometry]
        _arcpy_gov_process_funcs = [arcpy_repair_geometry, arcpy_project]
        print(f"[ArcPy] {len(_arcpy_funcs)} ArcPy tools registered.")
except Exception as e:
    print(f"[ArcPy] ArcPy integration not available: {e}")


def retry_arcpy_init():
    """Retry ArcPy initialization (called after app startup if first attempt failed)."""
    global ARCPY_AVAILABLE, _arcpy_funcs, _arcpy_gov_explore_funcs, _arcpy_gov_process_funcs
    if ARCPY_AVAILABLE:
        return True
    try:
        from ..arcpy_tools import is_arcpy_available
        if is_arcpy_available():
            from ..arcpy_tools import (
                arcpy_buffer, arcpy_clip, arcpy_dissolve, arcpy_project,
                arcpy_check_geometry, arcpy_repair_geometry,
                arcpy_slope, arcpy_zonal_statistics, arcpy_extract_watershed,
            )
            ARCPY_AVAILABLE = True
            _arcpy_funcs[:] = [
                arcpy_buffer, arcpy_clip, arcpy_dissolve, arcpy_project,
                arcpy_repair_geometry, arcpy_slope, arcpy_zonal_statistics,
                arcpy_extract_watershed,
            ]
            _arcpy_gov_explore_funcs[:] = [arcpy_check_geometry]
            _arcpy_gov_process_funcs[:] = [arcpy_repair_geometry, arcpy_project]
            print(f"[ArcPy] Retry succeeded: {len(_arcpy_funcs)} ArcPy tools registered.")
            return True
    except Exception:
        pass
    return False


_CORE_FUNCS = [
    generate_tessellation,
    raster_to_polygon,
    pairwise_clip,
    tabulate_intersection,
    surface_parameters,
    zonal_statistics_as_table,
    perform_clustering,
    create_buffer,
    summarize_within,
    overlay_difference,
    find_within_distance,
    polygon_neighbors,
    add_field,
    add_join,
    calculate_field,
    summary_statistics,
    filter_vector_data,
]


class GeoProcessingToolset(BaseToolset):
    """Spatial GIS processing and optional ArcPy tools."""

    def __init__(self, *, include_arcpy: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._include_arcpy = include_arcpy

    async def get_tools(self, readonly_context=None):
        funcs = list(_CORE_FUNCS)
        if self._include_arcpy:
            funcs.extend(_arcpy_funcs)
        all_tools = [FunctionTool(f) for f in funcs]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
