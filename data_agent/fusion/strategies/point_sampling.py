"""Point sampling strategy — sample raster values at point locations."""
import geopandas as gpd


def _strategy_point_sampling(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Sample raster values at point locations."""
    import rasterio

    log = []

    gdf = None
    raster_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "raster" and isinstance(data, str):
            raster_path = data

    if gdf is None or raster_path is None:
        raise ValueError("point_sampling requires one vector (point) and one raster source.")

    with rasterio.open(raster_path) as src:
        coords = [(geom.x, geom.y) for geom in gdf.geometry if geom is not None]
        samples = list(src.sample(coords))

    result = gdf.copy()
    for band_idx in range(len(samples[0]) if samples else 0):
        result[f"raster_band_{band_idx + 1}"] = [s[band_idx] for s in samples]

    log.append(f"Point sampling: {len(gdf)} points × {len(samples[0]) if samples else 0} bands")
    return result, log
