"""Nearest-neighbor spatial join strategy."""
import geopandas as gpd

from .spatial_join import _extract_geodataframe


def _strategy_nearest_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Nearest-neighbor spatial join."""
    log = []

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = gpd.sjoin_nearest(gdf_left, gdf_right, how="left")

    if "index_right" in result.columns:
        result = result.drop(columns=["index_right"])

    log.append(f"Nearest join: {len(gdf_left)} left × {len(gdf_right)} right → {len(result)} rows")
    return result, log
