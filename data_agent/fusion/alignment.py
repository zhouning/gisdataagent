"""Source alignment — CRS unification, unit conversion, column conflict resolution."""
import logging
import os
from typing import Optional

import geopandas as gpd
import pandas as pd

from .models import FusionSource, CompatibilityReport
from .constants import UNIT_CONVERSIONS
from .io import _read_vector_chunked, _read_tabular_lazy, _materialize_df
from .raster_utils import _reproject_raster
from .matching import _detect_unit

logger = logging.getLogger(__name__)


def align_sources(
    sources: list[FusionSource],
    report: CompatibilityReport,
    target_crs: Optional[str] = None,
) -> tuple[list, list[str]]:
    """Align data sources for fusion: CRS unification, unit conversion, field renaming.

    Args:
        sources: Profiled source list.
        report: Compatibility report (used for unit-aware field matches).
        target_crs: Target CRS (default: use first source's CRS).

    Returns:
        Tuple of (loaded data objects, alignment log messages).
    """
    log = []
    loaded = []

    # Determine target CRS
    if target_crs is None:
        crs_sources = [s for s in sources if s.crs is not None]
        target_crs = crs_sources[0].crs if crs_sources else "EPSG:4326"

    for src in sources:
        if src.data_type == "vector":
            gdf = _read_vector_chunked(src.file_path)
            if gdf.crs and str(gdf.crs) != target_crs:
                gdf = gdf.to_crs(target_crs)
                log.append(f"Reprojected {os.path.basename(src.file_path)} "
                           f"from {src.crs} to {target_crs}")
            loaded.append(("vector", gdf))

        elif src.data_type == "raster":
            raster_path = src.file_path
            if src.crs and src.crs != target_crs:
                try:
                    raster_path = _reproject_raster(src.file_path, target_crs)
                    log.append(f"Reprojected raster {os.path.basename(src.file_path)} "
                               f"from {src.crs} to {target_crs}")
                except Exception as e:
                    log.append(f"Raster reprojection failed for "
                               f"{os.path.basename(src.file_path)}: {e} — using original")
            loaded.append(("raster", raster_path))

        elif src.data_type == "tabular":
            df = _materialize_df(_read_tabular_lazy(src.file_path))
            loaded.append(("tabular", df))

        elif src.data_type == "point_cloud":
            loaded.append(("point_cloud", src.file_path))

        else:
            loaded.append((src.data_type, src.file_path))

    # Resolve naming conflicts between vector/tabular pairs
    if len(loaded) >= 2:
        _resolve_column_conflicts(loaded, log)

    # Apply unit conversions for unit-aware field matches
    if report and report.field_matches:
        _apply_unit_conversions(loaded, report.field_matches, log)

    return loaded, log


def _apply_unit_conversions(
    loaded: list,
    field_matches: list[dict],
    log: list[str],
) -> None:
    """Apply unit conversions for field matches with different units (in-place).

    Converts the second source's column to match the first source's unit.
    """
    for match in field_matches:
        if match.get("match_type") != "unit_aware":
            continue
        left_unit = match.get("left_unit")
        right_unit = match.get("right_unit")
        right_col = match.get("right", "")
        if not (left_unit and right_unit and right_col):
            continue

        # Find the second data source (where conversion should happen)
        for dtype, data in loaded:
            if isinstance(data, (gpd.GeoDataFrame, pd.DataFrame)):
                if right_col in data.columns:
                    _convert_column_units(data, right_col, right_unit, left_unit, log)
                    break


def _convert_column_units(
    data: pd.DataFrame,
    column: str,
    from_unit: str,
    to_unit: str,
    log: list[str],
) -> None:
    """Convert numeric column values from one unit to another (in-place)."""
    factor = UNIT_CONVERSIONS.get((from_unit, to_unit))
    if factor is None:
        log.append(f"No conversion factor for {from_unit} → {to_unit}")
        return
    if column not in data.columns:
        return
    if pd.api.types.is_numeric_dtype(data[column]):
        data[column] = data[column] * factor
        log.append(f"Converted '{column}': {from_unit} → {to_unit} (×{factor:.6g})")


def _resolve_column_conflicts(loaded: list, log: list[str]) -> None:
    """Rename conflicting columns between data sources (in-place)."""
    if len(loaded) < 2:
        return

    def _get_columns(item):
        dtype, data = item
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            return set(c for c in data.columns if c != "geometry")
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            return set(data.columns)
        return set()

    cols_0 = _get_columns(loaded[0])
    cols_1 = _get_columns(loaded[1])
    conflicts = cols_0 & cols_1

    if conflicts:
        # Rename in the second source by adding _right suffix
        dtype_1, data_1 = loaded[1]
        if isinstance(data_1, (gpd.GeoDataFrame, pd.DataFrame)):
            rename_map = {c: f"{c}_right" for c in conflicts if c != "geometry"}
            if rename_map:
                data_1.rename(columns=rename_map, inplace=True)
                log.append(f"Renamed conflicting columns in source 2: "
                           f"{list(rename_map.keys())} → {list(rename_map.values())}")
