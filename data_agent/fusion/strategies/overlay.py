"""Vector overlay analysis strategy."""
import geopandas as gpd

from .spatial_join import _extract_geodataframe


def _strategy_overlay(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Vector overlay analysis."""
    log = []
    how = params.get("overlay_how", "union")

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = gpd.overlay(gdf_left, gdf_right, how=how)
    log.append(f"Overlay ({how}): {len(gdf_left)} + {len(gdf_right)} → {len(result)} features")
    return result, log
