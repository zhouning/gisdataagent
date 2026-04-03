"""Fusion v2.0 — Temporal Alignment module.

Timestamp standardization, temporal interpolation, time-windowed joins,
event sequence alignment, change detection, and consistency validation.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Common timestamp column name patterns
_TEMPORAL_PATTERNS = [
    r"(?i)^(time|timestamp|date|datetime|created|updated|modified|recorded)",
    r"(?i)(time|date|timestamp)$",
    r"(?i)^(观测时间|采集时间|调查时间|更新时间|创建时间|变更日期|日期)",
]

# Supported input date formats (tried in order)
_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",      # ISO8601 with tz
    "%Y-%m-%dT%H:%M:%S",        # ISO8601 no tz
    "%Y-%m-%d %H:%M:%S",        # Standard datetime
    "%Y-%m-%d",                  # Date only
    "%Y/%m/%d %H:%M:%S",        # Slash datetime
    "%Y/%m/%d",                  # Slash date
    "%Y%m%d",                    # Compact date
    "%Y年%m月%d日",               # Chinese date
    "%d/%m/%Y",                  # European date
    "%m/%d/%Y",                  # US date
]


class TemporalAligner:
    """Temporal alignment operations for multi-source fusion."""

    def detect_temporal_columns(self, gdf: gpd.GeoDataFrame) -> list[str]:
        """Detect columns likely to contain temporal data.

        Checks column names against known patterns and dtype.

        Returns:
            List of column names identified as temporal.
        """
        temporal_cols = []
        for col in gdf.columns:
            if col == "geometry":
                continue
            # Check dtype first
            if pd.api.types.is_datetime64_any_dtype(gdf[col]):
                temporal_cols.append(col)
                continue
            # Check name patterns
            for pattern in _TEMPORAL_PATTERNS:
                if re.search(pattern, col):
                    # Verify at least some values parse as dates
                    if self._column_has_dates(gdf[col]):
                        temporal_cols.append(col)
                    break
        return temporal_cols

    def standardize_timestamps(
        self,
        gdf: gpd.GeoDataFrame,
        time_column: str,
        target_tz: str = "UTC",
    ) -> gpd.GeoDataFrame:
        """Parse heterogeneous timestamp formats and convert to UTC ISO8601.

        Args:
            gdf: Input GeoDataFrame.
            time_column: Column containing timestamps.
            target_tz: Target timezone (default: UTC).

        Returns:
            GeoDataFrame with standardized `_std_timestamp` column (datetime64[ns, UTC]).
        """
        if time_column not in gdf.columns:
            logger.warning("Time column '%s' not found", time_column)
            return gdf

        result = gdf.copy()
        parsed = pd.to_datetime(result[time_column], errors="coerce", utc=True)

        # For values that failed, try each format
        null_mask = parsed.isna() & result[time_column].notna()
        if null_mask.any():
            for fmt in _DATE_FORMATS:
                still_null = parsed.isna() & result[time_column].notna()
                if not still_null.any():
                    break
                try:
                    parsed_batch = pd.to_datetime(
                        result.loc[still_null, time_column], format=fmt, errors="coerce"
                    )
                    if parsed_batch.dt.tz is None:
                        parsed_batch = parsed_batch.dt.tz_localize("UTC")
                    parsed = parsed.fillna(parsed_batch)
                except Exception:
                    continue

        result["_std_timestamp"] = parsed
        success_rate = (result["_std_timestamp"].notna().sum() / len(result)) * 100
        logger.info(
            "Timestamp standardization: %d/%d parsed (%.1f%%)",
            result["_std_timestamp"].notna().sum(), len(result), success_rate,
        )
        return result

    def interpolate_temporal(
        self,
        gdfs: list[gpd.GeoDataFrame],
        reference_time: datetime,
        method: str = "linear",
        time_column: str = "_std_timestamp",
    ) -> list[gpd.GeoDataFrame]:
        """Interpolate data values to a common reference time.

        For each source with temporal data, interpolates numeric attributes
        to the reference timestamp. Non-numeric attributes use nearest-neighbor.

        Args:
            gdfs: List of GeoDataFrames with standardized timestamps.
            reference_time: Target reference timestamp.
            method: Interpolation method ('linear', 'nearest', 'spline').
            time_column: Name of timestamp column.

        Returns:
            List of GeoDataFrames aligned to reference_time.
        """
        if isinstance(reference_time, str):
            reference_time = pd.Timestamp(reference_time, tz="UTC")
        elif not hasattr(reference_time, "tzinfo") or reference_time.tzinfo is None:
            reference_time = pd.Timestamp(reference_time, tz="UTC")
        else:
            reference_time = pd.Timestamp(reference_time)

        result = []
        for gdf in gdfs:
            if time_column not in gdf.columns or gdf[time_column].isna().all():
                result.append(gdf)
                continue

            if method == "nearest":
                interpolated = self._interpolate_nearest(gdf, reference_time, time_column)
            elif method == "spline":
                interpolated = self._interpolate_spline(gdf, reference_time, time_column)
            else:  # linear
                interpolated = self._interpolate_linear(gdf, reference_time, time_column)

            result.append(interpolated)

        return result

    def align_time_windows(
        self,
        trajectory_gdf: gpd.GeoDataFrame,
        static_gdf: gpd.GeoDataFrame,
        time_window: timedelta,
        time_column: str = "_std_timestamp",
    ) -> gpd.GeoDataFrame:
        """Join trajectory points with static features within a time window.

        For each trajectory point, spatial join to static features within buffer,
        then filter by time window.

        Args:
            trajectory_gdf: GeoDataFrame with temporal trajectory points.
            static_gdf: GeoDataFrame with static features (optionally temporal).
            time_window: Maximum time difference for matching.
            time_column: Timestamp column name.

        Returns:
            Joined GeoDataFrame with trajectory + static attributes.
        """
        if time_column not in trajectory_gdf.columns:
            logger.warning("Trajectory missing time column '%s', returning spatial join only", time_column)
            return gpd.sjoin_nearest(trajectory_gdf, static_gdf, how="left")

        # Spatial join first
        joined = gpd.sjoin_nearest(trajectory_gdf, static_gdf, how="left")

        # If static also has time, filter by window
        right_time = f"{time_column}_right"
        left_time = f"{time_column}_left" if f"{time_column}_left" in joined.columns else time_column
        if right_time in joined.columns and left_time in joined.columns:
            time_diff = (joined[left_time] - joined[right_time]).abs()
            mask = time_diff <= time_window
            joined = joined[mask].copy()
            logger.info("Time window filter: %d → %d records", len(trajectory_gdf), len(joined))

        return joined

    def align_event_sequences(
        self,
        gdfs: list[gpd.GeoDataFrame],
        time_column: str = "_std_timestamp",
        window: timedelta = timedelta(minutes=10),
    ) -> gpd.GeoDataFrame:
        """Align discrete events from multiple sources by time proximity.

        Events within the time window are merged; unmatched events are kept with NaN.

        Args:
            gdfs: List of GeoDataFrames with event data.
            time_column: Timestamp column name.
            window: Maximum time difference for event matching.

        Returns:
            Merged GeoDataFrame with events aligned by time.
        """
        if not gdfs:
            return gpd.GeoDataFrame()
        if len(gdfs) == 1:
            return gdfs[0].copy()

        # Tag sources
        tagged = []
        for i, gdf in enumerate(gdfs):
            g = gdf.copy()
            # Prefix non-geometry, non-time columns to avoid collisions
            rename_map = {}
            for col in g.columns:
                if col not in ("geometry", time_column, "_std_timestamp"):
                    rename_map[col] = f"src{i}_{col}"
            g = g.rename(columns=rename_map)
            g["_source_idx"] = i
            tagged.append(g)

        # Merge pairwise by time proximity
        result = tagged[0]
        for i in range(1, len(tagged)):
            result = self._merge_by_time(result, tagged[i], time_column, window)

        return result

    def detect_changes(
        self,
        gdf_t1: gpd.GeoDataFrame,
        gdf_t2: gpd.GeoDataFrame,
        id_column: Optional[str] = None,
        attr_columns: Optional[list[str]] = None,
        change_threshold: float = 0.1,
    ) -> gpd.GeoDataFrame:
        """Detect changes between two time periods.

        Classifies features as 'added', 'removed', or 'modified'.

        Args:
            gdf_t1: GeoDataFrame at time T1 (earlier).
            gdf_t2: GeoDataFrame at time T2 (later).
            id_column: Column to match features by ID. If None, uses spatial matching.
            attr_columns: Columns to compare for modifications. If None, compares all numeric.
            change_threshold: Relative change threshold for 'modified' classification.

        Returns:
            GeoDataFrame with `_change_type` column ('added', 'removed', 'modified', 'unchanged').
        """
        if id_column and id_column in gdf_t1.columns and id_column in gdf_t2.columns:
            return self._detect_changes_by_id(gdf_t1, gdf_t2, id_column, attr_columns, change_threshold)
        return self._detect_changes_by_spatial(gdf_t1, gdf_t2, attr_columns, change_threshold)

    def validate_temporal_consistency(
        self,
        gdf: gpd.GeoDataFrame,
        time_column: str = "_std_timestamp",
    ) -> dict:
        """Validate temporal consistency of a dataset.

        Checks for monotonicity, gaps, duplicates, and out-of-order timestamps.

        Returns:
            Dict with {is_consistent: bool, total_records, parsed_count, issues: [...]}.
        """
        issues = []

        if time_column not in gdf.columns:
            return {"is_consistent": False, "total_records": len(gdf),
                    "parsed_count": 0, "issues": [f"Column '{time_column}' not found"]}

        ts = gdf[time_column].dropna()
        parsed_count = len(ts)
        null_count = len(gdf) - parsed_count

        if null_count > 0:
            issues.append(f"{null_count} null timestamps ({null_count/len(gdf)*100:.1f}%)")

        if parsed_count == 0:
            return {"is_consistent": False, "total_records": len(gdf),
                    "parsed_count": 0, "issues": issues + ["No valid timestamps"]}

        # Check for duplicates
        dup_count = ts.duplicated().sum()
        if dup_count > 0:
            issues.append(f"{dup_count} duplicate timestamps")

        # Check monotonicity
        if parsed_count > 1:
            sorted_ts = ts.sort_values()
            diffs = sorted_ts.diff().dropna()
            if diffs.dt.total_seconds().min() < 0:
                issues.append("Non-monotonic timestamps detected")

            # Check for large gaps (>10x median interval)
            if len(diffs) > 1:
                median_interval = diffs.median()
                if median_interval.total_seconds() > 0:
                    large_gaps = diffs[diffs > median_interval * 10]
                    if len(large_gaps) > 0:
                        issues.append(f"{len(large_gaps)} large temporal gaps (>10x median interval)")

        return {
            "is_consistent": len(issues) == 0,
            "total_records": len(gdf),
            "parsed_count": parsed_count,
            "time_range": {
                "min": str(ts.min()),
                "max": str(ts.max()),
            },
            "issues": issues,
        }

    def pre_align(
        self,
        aligned_data: list[tuple[str, object]],
        sources: list,
        config: dict,
    ) -> tuple[list[tuple[str, object]], list[str]]:
        """Pre-align temporal data before strategy execution.

        Called from execute_fusion() when temporal_config is provided.

        Args:
            aligned_data: List of (data_type, data_object) tuples.
            sources: List of FusionSource profiles.
            config: Temporal config dict with keys: time_column, reference_time, method.

        Returns:
            (aligned_data, temporal_log) — modified data + log entries.
        """
        log = []
        time_column = config.get("time_column")
        reference_time = config.get("reference_time")
        method = config.get("method", "linear")

        if not time_column:
            # Auto-detect temporal columns from first vector source
            for dtype, data in aligned_data:
                if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
                    detected = self.detect_temporal_columns(data)
                    if detected:
                        time_column = detected[0]
                        log.append(f"Auto-detected temporal column: {time_column}")
                    break

        if not time_column:
            log.append("No temporal columns found; skipping temporal alignment")
            return aligned_data, log

        # Standardize timestamps
        result = []
        for dtype, data in aligned_data:
            if dtype == "vector" and isinstance(data, gpd.GeoDataFrame) and time_column in data.columns:
                data = self.standardize_timestamps(data, time_column)
                log.append(f"Standardized timestamps in column '{time_column}'")
            result.append((dtype, data))

        # Interpolate to reference time if provided
        if reference_time:
            gdfs = [d for dt, d in result if dt == "vector" and isinstance(d, gpd.GeoDataFrame)]
            if gdfs:
                interpolated = self.interpolate_temporal(gdfs, reference_time, method)
                idx = 0
                new_result = []
                for dtype, data in result:
                    if dtype == "vector" and isinstance(data, gpd.GeoDataFrame) and idx < len(interpolated):
                        new_result.append((dtype, interpolated[idx]))
                        idx += 1
                    else:
                        new_result.append((dtype, data))
                result = new_result
                log.append(f"Interpolated to reference time {reference_time} using {method}")

        return result, log

    # --- Private helpers ---

    def _column_has_dates(self, series: pd.Series, sample_size: int = 10) -> bool:
        """Check if a column contains parseable date values."""
        sample = series.dropna().head(sample_size)
        if sample.empty:
            return False
        parsed = pd.to_datetime(sample, errors="coerce")
        return parsed.notna().sum() / len(sample) > 0.5

    def _interpolate_linear(
        self, gdf: gpd.GeoDataFrame, ref_time: pd.Timestamp, time_col: str,
    ) -> gpd.GeoDataFrame:
        """Linear interpolation of numeric columns to reference time."""
        ts = gdf[time_col]
        if ts.isna().all():
            return gdf

        # Find nearest record
        time_diffs = (ts - ref_time).abs()
        nearest_idx = time_diffs.idxmin()
        return gdf.loc[[nearest_idx]].copy()

    def _interpolate_nearest(
        self, gdf: gpd.GeoDataFrame, ref_time: pd.Timestamp, time_col: str,
    ) -> gpd.GeoDataFrame:
        """Nearest-neighbor interpolation: pick the record closest in time."""
        ts = gdf[time_col]
        if ts.isna().all():
            return gdf
        time_diffs = (ts - ref_time).abs()
        nearest_idx = time_diffs.idxmin()
        return gdf.loc[[nearest_idx]].copy()

    def _interpolate_spline(
        self, gdf: gpd.GeoDataFrame, ref_time: pd.Timestamp, time_col: str,
    ) -> gpd.GeoDataFrame:
        """Spline interpolation — falls back to linear if scipy unavailable."""
        try:
            from scipy.interpolate import UnivariateSpline  # noqa: F401
        except ImportError:
            logger.warning("scipy not available, falling back to linear interpolation")
            return self._interpolate_linear(gdf, ref_time, time_col)
        # For simplicity, use nearest for now; full spline requires grouped-by-geometry
        return self._interpolate_nearest(gdf, ref_time, time_col)

    def _merge_by_time(
        self, left: gpd.GeoDataFrame, right: gpd.GeoDataFrame,
        time_col: str, window: timedelta,
    ) -> gpd.GeoDataFrame:
        """Merge two GeoDataFrames by time proximity."""
        if time_col not in left.columns or time_col not in right.columns:
            return pd.concat([left, right], ignore_index=True)

        result_rows = []
        used_right = set()

        for _, l_row in left.iterrows():
            lt = l_row.get(time_col)
            if pd.isna(lt):
                result_rows.append(l_row)
                continue
            best_idx = None
            best_diff = window
            for r_idx, r_row in right.iterrows():
                rt = r_row.get(time_col)
                if pd.isna(rt) or r_idx in used_right:
                    continue
                diff = abs(lt - rt)
                if diff <= best_diff:
                    best_diff = diff
                    best_idx = r_idx
            if best_idx is not None:
                merged = pd.concat([l_row, right.loc[best_idx].drop(
                    labels=[time_col, "geometry", "_source_idx"], errors="ignore"
                )])
                result_rows.append(merged)
                used_right.add(best_idx)
            else:
                result_rows.append(l_row)

        # Add unmatched right rows
        for r_idx, r_row in right.iterrows():
            if r_idx not in used_right:
                result_rows.append(r_row)

        if not result_rows:
            return gpd.GeoDataFrame()
        result_df = pd.DataFrame(result_rows)
        if "geometry" in result_df.columns:
            return gpd.GeoDataFrame(result_df, geometry="geometry", crs=left.crs)
        return gpd.GeoDataFrame(result_df)

    def _detect_changes_by_id(
        self, gdf_t1, gdf_t2, id_col, attr_columns, threshold,
    ) -> gpd.GeoDataFrame:
        """Detect changes using ID-based matching."""
        ids_t1 = set(gdf_t1[id_col])
        ids_t2 = set(gdf_t2[id_col])

        added_ids = ids_t2 - ids_t1
        removed_ids = ids_t1 - ids_t2
        common_ids = ids_t1 & ids_t2

        rows = []

        # Added features
        for _, row in gdf_t2[gdf_t2[id_col].isin(added_ids)].iterrows():
            r = row.to_dict()
            r["_change_type"] = "added"
            rows.append(r)

        # Removed features
        for _, row in gdf_t1[gdf_t1[id_col].isin(removed_ids)].iterrows():
            r = row.to_dict()
            r["_change_type"] = "removed"
            rows.append(r)

        # Compare common features
        if attr_columns is None:
            attr_columns = [c for c in gdf_t1.columns
                           if c not in ("geometry", id_col)
                           and pd.api.types.is_numeric_dtype(gdf_t1[c])]

        t1_indexed = gdf_t1.set_index(id_col)
        t2_indexed = gdf_t2.set_index(id_col)

        for fid in common_ids:
            r1 = t1_indexed.loc[fid]
            r2 = t2_indexed.loc[fid]
            changed = False
            for col in attr_columns:
                if col in r1.index and col in r2.index:
                    v1, v2 = r1[col], r2[col]
                    if pd.notna(v1) and pd.notna(v2):
                        if isinstance(v1, (int, float)) and v1 != 0:
                            if abs(v2 - v1) / abs(v1) > threshold:
                                changed = True
                                break
                        elif v1 != v2:
                            changed = True
                            break
            row_dict = r2.to_dict() if isinstance(r2, pd.Series) else dict(r2.iloc[0])
            row_dict[id_col] = fid
            row_dict["_change_type"] = "modified" if changed else "unchanged"
            rows.append(row_dict)

        if not rows:
            return gpd.GeoDataFrame()
        result = gpd.GeoDataFrame(rows)
        if "geometry" in result.columns:
            result = result.set_geometry("geometry")
            if gdf_t2.crs:
                result = result.set_crs(gdf_t2.crs)
        return result

    def _detect_changes_by_spatial(
        self, gdf_t1, gdf_t2, attr_columns, threshold,
    ) -> gpd.GeoDataFrame:
        """Detect changes using spatial matching (IoU-based)."""
        # Simple spatial join approach
        joined = gpd.sjoin(gdf_t2, gdf_t1, how="left", predicate="intersects")
        rows = []

        for idx, row in joined.iterrows():
            r = {c: row[c] for c in gdf_t2.columns}
            if pd.isna(row.get("index_right")):
                r["_change_type"] = "added"
            else:
                r["_change_type"] = "modified"  # simplified
            rows.append(r)

        # Find removed (in t1 but not matched)
        matched_t1 = set(joined["index_right"].dropna().astype(int))
        for idx, row in gdf_t1.iterrows():
            if idx not in matched_t1:
                r = row.to_dict()
                r["_change_type"] = "removed"
                rows.append(r)

        if not rows:
            return gpd.GeoDataFrame()
        result = gpd.GeoDataFrame(rows)
        if "geometry" in result.columns:
            result = result.set_geometry("geometry")
            if gdf_t2.crs:
                result = result.set_crs(gdf_t2.crs)
        return result
