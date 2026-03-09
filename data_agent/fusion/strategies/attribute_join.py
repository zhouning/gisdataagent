"""Attribute join strategy + auto-detect join column."""
import geopandas as gpd
import pandas as pd

from .spatial_join import _extract_geodataframe


def _auto_detect_join_column(gdf: gpd.GeoDataFrame, df: pd.DataFrame) -> str:
    """Auto-detect the best join column between GeoDataFrame and DataFrame."""
    gdf_cols = {c.lower(): c for c in gdf.columns if c != "geometry"}
    df_cols = {c.lower(): c for c in df.columns}

    # Exact matches (case-insensitive)
    common = set(gdf_cols.keys()) & set(df_cols.keys())
    if common:
        # Prefer ID-like columns
        id_cols = [c for c in common if any(kw in c for kw in ["id", "code", "bm", "dm", "fid"])]
        if id_cols:
            return gdf_cols[id_cols[0]]
        return gdf_cols[list(common)[0]]

    raise ValueError("Cannot auto-detect join column. Please specify join_column parameter.")


def _strategy_attribute_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Attribute join between vector/tabular data on a key column."""
    log = []
    join_column = params.get("join_column", "")

    # Find the vector and tabular sources
    gdf = None
    df = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            df = data

    if gdf is None or df is None:
        raise ValueError("attribute_join requires one vector and one tabular source.")

    # Auto-detect join column if not specified
    if not join_column:
        join_column = _auto_detect_join_column(gdf, df)
        log.append(f"Auto-detected join column: {join_column}")

    if join_column not in gdf.columns:
        raise ValueError(f"Join column '{join_column}' not found in vector data.")

    # Find matching column in tabular data
    right_col = join_column
    if right_col not in df.columns:
        # Try case-insensitive match
        for c in df.columns:
            if c.lower() == join_column.lower():
                right_col = c
                break
        else:
            # Try _right suffix (added by conflict resolution)
            right_suffixed = f"{join_column}_right"
            if right_suffixed in df.columns:
                right_col = right_suffixed
            else:
                for c in df.columns:
                    if c.lower() == right_suffixed.lower():
                        right_col = c
                        break
                else:
                    raise ValueError(f"Join column '{join_column}' not found in tabular data.")

    result = gdf.merge(df, left_on=join_column, right_on=right_col, how="left")
    if not isinstance(result, gpd.GeoDataFrame):
        result = gpd.GeoDataFrame(result, geometry="geometry", crs=gdf.crs)

    log.append(f"Attribute join on '{join_column}': {len(gdf)} rows → {len(result)} rows, "
               f"+{len(df.columns) - 1} columns")
    return result, log
