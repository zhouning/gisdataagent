"""Location services toolset: geocoding, POI search, admin boundaries, population."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..geocoding import (
    batch_geocode,
    reverse_geocode,
    calculate_driving_distance,
    search_nearby_poi,
    search_poi_by_keyword,
    get_admin_boundary,
)
from ..population_data import get_population_data, aggregate_population


_ALL_FUNCS = [
    batch_geocode,
    reverse_geocode,
    calculate_driving_distance,
    search_nearby_poi,
    search_poi_by_keyword,
    get_admin_boundary,
    get_population_data,
    aggregate_population,
]


class LocationToolset(BaseToolset):
    """Geocoding, POI search, admin boundary, and population data tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
