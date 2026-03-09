"""Large dataset detection and chunked I/O (v7.0)."""
import logging
import os

import geopandas as gpd
import pandas as pd

from .constants import LARGE_ROW_THRESHOLD, LARGE_FILE_MB

logger = logging.getLogger(__name__)


def _is_large_dataset(file_path: str, row_hint: int = 0) -> bool:
    """Check if a dataset exceeds the large-data threshold.

    Returns True if row_hint > 500K or file size > 500MB.
    """
    if row_hint > LARGE_ROW_THRESHOLD:
        return True
    try:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        return size_mb > LARGE_FILE_MB
    except OSError:
        return False


def _read_vector_chunked(path: str, chunk_size: int = 100_000) -> gpd.GeoDataFrame:
    """Read a vector file, using chunked reading for large files.

    For files below the threshold, uses standard gpd.read_file().
    For large files, reads in chunks via fiona row slicing.
    """
    if not _is_large_dataset(path):
        return gpd.read_file(path)

    logger.info("Large vector file detected (%s), using chunked reading", path)
    import fiona

    chunks = []
    with fiona.open(path) as src:
        total = len(src)
        if total <= chunk_size:
            return gpd.read_file(path)
        for start in range(0, total, chunk_size):
            chunk = gpd.read_file(path, rows=slice(start, start + chunk_size))
            chunks.append(chunk)

    return pd.concat(chunks, ignore_index=True)


def _read_tabular_lazy(path: str):
    """Read a tabular file, using dask for large CSV files.

    Returns a dask DataFrame for large CSVs, pandas DataFrame otherwise.
    Callers that need pandas can call .compute() on dask results.
    """
    ext = os.path.splitext(path)[1].lower()
    if not _is_large_dataset(path):
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(path)
        return pd.read_csv(path, encoding="utf-8")

    logger.info("Large tabular file detected (%s), using lazy reading", path)
    if ext == ".csv":
        import dask.dataframe as dd
        return dd.read_csv(path, encoding="utf-8")
    # Excel not supported by dask — fallback to pandas
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8")


def _materialize_df(df) -> pd.DataFrame:
    """Convert dask DataFrame to pandas if needed."""
    if hasattr(df, "compute"):
        return df.compute()
    return df
