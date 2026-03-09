"""Zonal statistics strategy — raster statistics within vector polygon zones."""
import geopandas as gpd
import pandas as pd


def _strategy_zonal_statistics(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Compute raster statistics within vector polygon zones."""
    from rasterstats import zonal_stats

    log = []
    stats_list = params.get("stats", ["mean", "min", "max", "count"])

    # Find vector and raster sources
    gdf = None
    raster_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "raster" and isinstance(data, str):
            raster_path = data

    if gdf is None or raster_path is None:
        raise ValueError("zonal_statistics requires one vector and one raster source.")

    zs = zonal_stats(gdf, raster_path, stats=stats_list)
    stats_df = pd.DataFrame(zs)

    # Prefix stats columns
    stats_df.columns = [f"raster_{c}" for c in stats_df.columns]

    result = gdf.copy()
    for col in stats_df.columns:
        result[col] = stats_df[col].values

    log.append(f"Zonal statistics: {len(gdf)} zones × {len(stats_list)} stats → "
               f"+{len(stats_df.columns)} columns")
    return result, log
