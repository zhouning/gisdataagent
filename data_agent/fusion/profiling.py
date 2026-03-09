"""Data source profiling — detect type, CRS, bounds, columns, statistics."""
import logging
import os

import geopandas as gpd
import numpy as np
import pandas as pd

from ..gis_processors import _resolve_path
from .models import FusionSource
from .io import _read_vector_chunked, _read_tabular_lazy, _materialize_df

logger = logging.getLogger(__name__)


def _detect_data_type(file_path: str) -> str:
    """Detect data type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    vector_exts = {".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".json"}
    raster_exts = {".tif", ".tiff", ".img", ".nc", ".hdf", ".jp2"}
    tabular_exts = {".csv", ".xlsx", ".xls", ".tsv"}
    point_cloud_exts = {".las", ".laz"}

    if ext in vector_exts:
        return "vector"
    elif ext in raster_exts:
        return "raster"
    elif ext in tabular_exts:
        return "tabular"
    elif ext in point_cloud_exts:
        return "point_cloud"
    else:
        return "tabular"  # default fallback


def profile_source(file_path: str) -> FusionSource:
    """Profile a data source: detect type, CRS, bounds, columns, statistics.

    Args:
        file_path: Path to the data file.

    Returns:
        FusionSource with full metadata.
    """
    resolved = _resolve_path(file_path)
    data_type = _detect_data_type(resolved)

    if data_type == "vector":
        return _profile_vector(resolved)
    elif data_type == "raster":
        return _profile_raster(resolved)
    elif data_type == "tabular":
        return _profile_tabular(resolved)
    elif data_type == "point_cloud":
        return _profile_point_cloud(resolved)
    else:
        return FusionSource(file_path=resolved, data_type="tabular")


def _profile_vector(path: str) -> FusionSource:
    """Profile a vector data source."""
    gdf = _read_vector_chunked(path)
    crs_str = str(gdf.crs) if gdf.crs else None
    bounds = tuple(gdf.total_bounds) if len(gdf) > 0 else None

    # Column info
    columns = []
    stats = {}
    non_geom_cols = [c for c in gdf.columns if c != "geometry"]
    for col in non_geom_cols:
        null_pct = round(gdf[col].isna().mean() * 100, 1)
        columns.append({"name": col, "dtype": str(gdf[col].dtype), "null_pct": null_pct})
        if pd.api.types.is_numeric_dtype(gdf[col]):
            stats[col] = {
                "min": float(gdf[col].min()) if not gdf[col].isna().all() else None,
                "max": float(gdf[col].max()) if not gdf[col].isna().all() else None,
                "mean": float(gdf[col].mean()) if not gdf[col].isna().all() else None,
            }
        else:
            stats[col] = {"unique": int(gdf[col].nunique())}

    geom_type = None
    if "geometry" in gdf.columns and not gdf.geometry.isna().all():
        geom_type = gdf.geometry.geom_type.mode().iloc[0] if len(gdf) > 0 else None

    return FusionSource(
        file_path=path,
        data_type="vector",
        crs=crs_str,
        bounds=bounds,
        row_count=len(gdf),
        columns=columns,
        geometry_type=geom_type,
        stats=stats,
    )


def _profile_raster(path: str) -> FusionSource:
    """Profile a raster data source.

    For large rasters (>1M pixels per band), uses windowed sampling of the
    centre region to avoid loading entire bands into memory.
    """
    import rasterio
    from rasterio.windows import Window

    LARGE_PIXEL_THRESHOLD = 1_000_000

    with rasterio.open(path) as ds:
        crs_str = str(ds.crs) if ds.crs else None
        bounds = tuple(ds.bounds)
        band_count = ds.count
        resolution = (ds.res[0], ds.res[1])
        total_pixels = ds.width * ds.height
        use_window = total_pixels > LARGE_PIXEL_THRESHOLD

        # For large rasters, sample a centre window (~1024×1024)
        if use_window:
            win_size = min(1024, ds.width, ds.height)
            col_off = max(0, (ds.width - win_size) // 2)
            row_off = max(0, (ds.height - win_size) // 2)
            window = Window(col_off, row_off, win_size, win_size)
        else:
            window = None

        columns = []
        stats = {}
        for i in range(1, min(band_count + 1, 11)):  # cap at 10 bands
            band_data = ds.read(i, window=window)
            valid = band_data[band_data != ds.nodata] if ds.nodata is not None else band_data
            band_name = f"band_{i}"
            columns.append({"name": band_name, "dtype": str(ds.dtypes[i - 1]), "null_pct": 0})
            if len(valid) > 0:
                stats[band_name] = {
                    "min": float(np.nanmin(valid)),
                    "max": float(np.nanmax(valid)),
                    "mean": float(np.nanmean(valid)),
                }

    return FusionSource(
        file_path=path,
        data_type="raster",
        crs=crs_str,
        bounds=bounds,
        row_count=0,
        columns=columns,
        stats=stats,
        band_count=band_count,
        resolution=resolution,
    )


def _profile_tabular(path: str) -> FusionSource:
    """Profile a tabular (CSV/Excel) data source."""
    df = _materialize_df(_read_tabular_lazy(path))

    columns = []
    stats = {}
    for col in df.columns:
        null_pct = round(df[col].isna().mean() * 100, 1)
        columns.append({"name": col, "dtype": str(df[col].dtype), "null_pct": null_pct})
        if pd.api.types.is_numeric_dtype(df[col]):
            stats[col] = {
                "min": float(df[col].min()) if not df[col].isna().all() else None,
                "max": float(df[col].max()) if not df[col].isna().all() else None,
                "mean": float(df[col].mean()) if not df[col].isna().all() else None,
            }
        else:
            stats[col] = {"unique": int(df[col].nunique())}

    return FusionSource(
        file_path=path,
        data_type="tabular",
        row_count=len(df),
        columns=columns,
        stats=stats,
    )


def _profile_point_cloud(path: str) -> FusionSource:
    """Profile a point cloud (LAS/LAZ) data source — metadata only."""
    try:
        import laspy
        with laspy.read(path) as las:
            bounds = (
                float(las.header.x_min), float(las.header.y_min),
                float(las.header.x_max), float(las.header.y_max),
            )
            row_count = las.header.point_count
            crs_str = None
            if hasattr(las.header, "parse_crs") and las.header.parse_crs():
                crs_str = str(las.header.parse_crs())
    except Exception:
        bounds = None
        row_count = 0
        crs_str = None

    return FusionSource(
        file_path=path,
        data_type="point_cloud",
        crs=crs_str,
        bounds=bounds,
        row_count=row_count,
        columns=[{"name": "x", "dtype": "float64", "null_pct": 0},
                 {"name": "y", "dtype": "float64", "null_pct": 0},
                 {"name": "z", "dtype": "float64", "null_pct": 0}],
        geometry_type="Point",
    )


def profile_postgis_source(table_name: str) -> FusionSource:
    """Profile a PostGIS table as a FusionSource.

    Queries the database for row count, SRID, bounding box, and column metadata.

    Args:
        table_name: PostGIS table name (optionally schema-qualified).

    Returns:
        FusionSource with postgis_table and postgis_srid populated.
    """
    import re
    from sqlalchemy import text
    from ..db_engine import get_engine

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]{0,126}$', table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")

    engine = get_engine()
    if not engine:
        raise ValueError("Database engine not available")

    with engine.connect() as conn:
        # Row count
        row = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).fetchone()
        row_count = row[0] if row else 0

        # SRID and bounds from geometry column
        srid = None
        bounds = None
        geometry_type = None
        try:
            meta = conn.execute(text(
                "SELECT srid, type FROM geometry_columns "
                f"WHERE f_table_name = :tbl"
            ), {"tbl": table_name.split(".")[-1]}).fetchone()
            if meta:
                srid = meta[0]
                geometry_type = meta[1]

            bbox = conn.execute(text(
                f'SELECT ST_XMin(ext), ST_YMin(ext), ST_XMax(ext), ST_YMax(ext) '
                f'FROM (SELECT ST_Extent(geom) AS ext FROM "{table_name}") sub'
            )).fetchone()
            if bbox and bbox[0] is not None:
                bounds = tuple(float(v) for v in bbox)
        except Exception as e:
            logger.warning("PostGIS metadata query failed for %s: %s", table_name, e)

        # Column metadata
        cols_rows = conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = :tbl ORDER BY ordinal_position"
        ), {"tbl": table_name.split(".")[-1]}).fetchall()

        columns = [
            {"name": c[0], "dtype": c[1], "null_pct": 0}
            for c in cols_rows if c[0] != "geom"
        ]

    crs_str = f"EPSG:{srid}" if srid else None

    return FusionSource(
        file_path=f"postgis://{table_name}",
        data_type="vector",
        crs=crs_str,
        bounds=bounds,
        row_count=row_count,
        columns=columns,
        geometry_type=geometry_type,
        postgis_table=table_name,
        postgis_srid=srid,
    )
