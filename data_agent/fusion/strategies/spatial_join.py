"""Spatial join strategy + chunked large-dataset spatial join."""
import logging

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


def _fuse_large_datasets_spatial(
    gdf_left: gpd.GeoDataFrame,
    gdf_right: gpd.GeoDataFrame,
    predicate: str = "intersects",
    chunk_size: int = 50_000,
) -> gpd.GeoDataFrame:
    """Chunked spatial join for large datasets.

    Splits the left GeoDataFrame into chunks, joins each chunk
    with the right GeoDataFrame (using its spatial index), then concatenates.
    """
    if len(gdf_left) <= chunk_size:
        return gpd.sjoin(gdf_left, gdf_right, how="left", predicate=predicate)

    logger.info("Using chunked spatial join: %d left rows in %d-row chunks",
                len(gdf_left), chunk_size)
    results = []
    for start in range(0, len(gdf_left), chunk_size):
        chunk = gdf_left.iloc[start:start + chunk_size]
        joined = gpd.sjoin(chunk, gdf_right, how="left", predicate=predicate)
        results.append(joined)

    return pd.concat(results, ignore_index=True)


def _extract_geodataframe(aligned: list, index: int) -> gpd.GeoDataFrame:
    """Extract a GeoDataFrame from aligned data at the given index."""
    dtype, data = aligned[index]
    if isinstance(data, gpd.GeoDataFrame):
        return data
    raise ValueError(f"Expected GeoDataFrame at index {index}, got {type(data)}")


def _strategy_spatial_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Spatial join between two vector datasets."""
    log = []
    predicate = params.get("spatial_predicate", "intersects")

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = _fuse_large_datasets_spatial(gdf_left, gdf_right, predicate=predicate)

    # Clean up index_right column
    if "index_right" in result.columns:
        result = result.drop(columns=["index_right"])

    log.append(f"Spatial join ({predicate}): {len(gdf_left)} left × {len(gdf_right)} right → {len(result)} rows")
    return result, log
