"""Band stack strategy — stack multiple raster bands."""
import os

import geopandas as gpd
import numpy as np

from ..raster_utils import _resample_raster_to_match


def _strategy_band_stack(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Stack multiple raster bands (returns vectorized result as GeoDataFrame).

    When rasters have different shapes, automatically resamples the second raster
    to match the first raster's grid before band stacking.
    """
    import rasterio
    from rasterio.features import shapes

    log = []

    raster_paths = [data for dtype, data in aligned if dtype == "raster" and isinstance(data, str)]
    if len(raster_paths) < 2:
        raise ValueError("band_stack requires at least 2 raster sources.")

    ref_path = raster_paths[0]
    second_path = raster_paths[1]

    # Read first raster as reference
    with rasterio.open(ref_path) as src:
        data_0 = src.read(1)
        transform = src.transform
        crs = src.crs
        ref_shape = data_0.shape

    # Read second raster
    with rasterio.open(second_path) as src:
        data_1 = src.read(1)

    # Auto-resample if shapes differ
    if data_0.shape != data_1.shape:
        resampling = params.get("resampling", "bilinear")
        try:
            resampled_path = _resample_raster_to_match(second_path, ref_path, resampling)
            with rasterio.open(resampled_path) as src:
                data_1 = src.read(1)
            log.append(f"Auto-resampled raster from {data_1.shape} to {ref_shape} "
                       f"(method={resampling})")
            # Clean up temp file
            try:
                os.remove(resampled_path)
            except OSError:
                pass
        except Exception as e:
            raise ValueError(
                f"Raster dimensions don't match ({ref_shape} vs {data_1.shape}) "
                f"and auto-resampling failed: {e}"
            )

    # Band ratio classification and vectorization
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(data_0 + data_1 > 0,
                         (data_0.astype(float) - data_1.astype(float)) /
                         (data_0.astype(float) + data_1.astype(float)),
                         0)
    classified = np.digitize(ratio, bins=[-0.5, -0.2, 0.0, 0.2, 0.5])
    mask = classified > 0

    geoms = []
    vals = []
    for geom, val in shapes(classified.astype(np.int32), mask=mask, transform=transform):
        geoms.append(geom)
        vals.append(val)

    if geoms:
        from shapely.geometry import shape as shapely_shape
        result = gpd.GeoDataFrame(
            {"class": vals},
            geometry=[shapely_shape(g) for g in geoms],
            crs=crs,
        )
    else:
        result = gpd.GeoDataFrame(columns=["class", "geometry"], crs=crs)

    log.append(f"Band stack: {len(raster_paths)} rasters → {len(result)} polygons (classified)")

    return result, log
