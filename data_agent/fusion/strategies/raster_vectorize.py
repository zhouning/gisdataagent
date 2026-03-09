"""Raster vectorize strategy — vectorize raster then join with tabular data."""
import geopandas as gpd
import numpy as np
import pandas as pd


def _strategy_raster_vectorize(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Vectorize raster then join with tabular data."""
    import rasterio
    from rasterio.features import shapes as rasterio_shapes
    from shapely.geometry import shape as shapely_shape

    log = []

    raster_path = None
    df = None
    for dtype, data in aligned:
        if dtype == "raster" and isinstance(data, str):
            raster_path = data
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            df = data

    if raster_path is None:
        raise ValueError("raster_vectorize requires a raster source.")

    with rasterio.open(raster_path) as src:
        band = src.read(1)
        transform = src.transform
        crs = src.crs

    mask = band != (src.nodata if hasattr(src, 'nodata') and src.nodata else 0)
    geoms = []
    vals = []
    for geom, val in rasterio_shapes(band.astype(np.int32), mask=mask, transform=transform):
        geoms.append(shapely_shape(geom))
        vals.append(int(val))

    result = gpd.GeoDataFrame(
        {"raster_value": vals},
        geometry=geoms,
        crs=crs,
    )

    if df is not None:
        # Simple concat if no obvious join key
        for col in df.columns:
            if col not in result.columns:
                if len(df) == len(result):
                    result[col] = df[col].values
                else:
                    log.append(f"Tabular row count ({len(df)}) differs from vectorized "
                               f"({len(result)}), skipping attribute join")
                    break

    log.append(f"Raster vectorize: → {len(result)} polygons")
    return result, log
