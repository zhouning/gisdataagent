"""Quality validation for fusion output (10-point scoring)."""
import logging
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from .models import FusionSource

logger = logging.getLogger(__name__)


def validate_quality(
    data: gpd.GeoDataFrame | str,
    sources: Optional[list[FusionSource]] = None,
) -> dict:
    """Validate quality of fusion output.

    v5.6 enhancements (MGIM-inspired comprehensive validation):
      - Original: empty check, null rate, geometry validity, row completeness
      - New: attribute value range validation, micro-polygon detection,
             per-column completeness, statistical distribution comparison

    Args:
        data: GeoDataFrame or path to output file.
        sources: Original source profiles for completeness check.

    Returns:
        Dict with score (0-1), warnings list, and details dict.
    """
    if isinstance(data, str):
        data = gpd.read_file(data)

    warnings = []
    details = {}
    score = 1.0

    # 1. Check for empty result
    if len(data) == 0:
        warnings.append("Fusion result is empty (0 rows)")
        return {"score": 0.0, "warnings": warnings, "details": {"empty": True}}

    # 2. Null rate check (per-column)
    non_geom = [c for c in data.columns if c != "geometry"]
    null_cols = {}
    for col in non_geom:
        null_pct = data[col].isna().mean()
        null_cols[col] = round(null_pct, 3)
        if null_pct > 0.5:
            warnings.append(f"Column '{col}' has {null_pct:.0%} null values")
            score -= 0.1
        elif null_pct > 0.2:
            warnings.append(f"Column '{col}' has {null_pct:.0%} null values (moderate)")
            score -= 0.05
    details["null_rates"] = null_cols

    # 3. Geometry validity
    if "geometry" in data.columns and not data.geometry.isna().all():
        invalid = ~data.geometry.is_valid
        invalid_pct = invalid.mean()
        details["invalid_geometry_pct"] = round(invalid_pct, 3)
        if invalid_pct > 0:
            warnings.append(f"{invalid_pct:.0%} invalid geometries detected")
            score -= 0.15

    # 4. Row count completeness (compared to sources)
    if sources:
        max_source_rows = max((s.row_count for s in sources if s.row_count > 0), default=0)
        if max_source_rows > 0:
            completeness = len(data) / max_source_rows
            details["row_completeness"] = round(completeness, 3)
            if completeness < 0.5:
                warnings.append(f"Output has {len(data)} rows vs max source {max_source_rows} "
                                f"({completeness:.0%} completeness)")
                score -= 0.15

    # 5. v5.6: Attribute value range validation
    # Detect absurd numeric values that may indicate unit mismatch
    numeric_cols = [c for c in non_geom if pd.api.types.is_numeric_dtype(data[c])]
    outlier_cols = []
    for col in numeric_cols[:20]:  # cap at 20 columns
        valid = data[col].dropna()
        if len(valid) < 5:
            continue
        q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            extreme_low = (valid < q1 - 5 * iqr).sum()
            extreme_high = (valid > q3 + 5 * iqr).sum()
            extreme_pct = (extreme_low + extreme_high) / len(valid)
            if extreme_pct > 0.05:
                outlier_cols.append(col)
    if outlier_cols:
        warnings.append(f"Extreme outliers in {len(outlier_cols)} column(s): "
                        f"{outlier_cols[:3]} — possible unit mismatch")
        score -= 0.05
    details["outlier_columns"] = outlier_cols

    # 6. v5.6: Micro-polygon detection (topological integrity indicator)
    if "geometry" in data.columns and not data.geometry.isna().all():
        geom_types = data.geometry.geom_type.dropna()
        if len(geom_types) > 0 and geom_types.str.contains("Polygon").any():
            areas = data.geometry.area
            if areas.max() > 0:
                micro_threshold = areas.median() * 0.001
                micro_count = (areas < micro_threshold).sum() if micro_threshold > 0 else 0
                micro_pct = micro_count / len(data)
                details["micro_polygon_pct"] = round(micro_pct, 3)
                if micro_pct > 0.1:
                    warnings.append(f"{micro_pct:.0%} micro-polygons detected "
                                    f"(area < 0.1% of median) — possible sliver polygons")
                    score -= 0.05

    # 7. v5.6: Per-column completeness vs source (not just row count)
    if sources:
        source_col_count = max((len(s.columns) for s in sources), default=0)
        output_col_count = len(non_geom)
        if source_col_count > 0:
            col_completeness = output_col_count / (source_col_count + 1)  # +1 for joined cols
            details["column_completeness"] = round(min(col_completeness, 1.0), 3)

    # 8. CRS consistency check
    if sources and "geometry" in data.columns and data.crs:
        output_crs = str(data.crs)
        details["output_crs"] = output_crs
        source_crs_set = {s.crs for s in sources if s.crs}
        if source_crs_set and output_crs not in source_crs_set:
            # CRS was reprojected — informational, not penalized
            details["crs_reprojected"] = True

    # 9. Topological validation — check for self-intersections
    if "geometry" in data.columns and not data.geometry.isna().all():
        geom_types = data.geometry.geom_type.dropna()
        if len(geom_types) > 0 and geom_types.str.contains("Polygon").any():
            try:
                from shapely.validation import explain_validity
                invalid_reasons = []
                for idx, geom in data.geometry.items():
                    if geom is not None and not geom.is_valid:
                        reason = explain_validity(geom)
                        if reason != "Valid Geometry":
                            invalid_reasons.append(reason)
                if invalid_reasons:
                    # Deduplicate reasons
                    unique_reasons = list(set(invalid_reasons))[:5]
                    details["topology_issues"] = unique_reasons
                    warnings.append(f"Topology issues in {len(invalid_reasons)} geometries: "
                                    f"{unique_reasons[0]}")
                    score -= 0.1
            except ImportError:
                pass  # shapely.validation not available

    # 10. Distribution shift detection (KS test)
    if sources:
        try:
            from scipy.stats import ks_2samp
            shift_warnings = []
            for src in sources:
                for col_info in src.columns[:10]:  # cap at 10 columns per source
                    col_name = col_info["name"]
                    if col_name in data.columns and pd.api.types.is_numeric_dtype(data[col_name]):
                        src_stats = src.stats.get(col_name, {})
                        if "mean" in src_stats and "min" in src_stats and "max" in src_stats:
                            output_vals = data[col_name].dropna()
                            if len(output_vals) >= 10:
                                # Generate synthetic source distribution from stats
                                src_mean = src_stats["mean"]
                                src_min = src_stats["min"]
                                src_max = src_stats["max"]
                                src_std = (src_max - src_min) / 4 if src_max > src_min else 1.0
                                rng = np.random.default_rng(42)
                                synthetic_src = rng.normal(src_mean, src_std, size=len(output_vals))
                                stat, p_val = ks_2samp(output_vals.values, synthetic_src)
                                if p_val < 0.01:
                                    shift_warnings.append(col_name)
            if shift_warnings:
                details["distribution_shift_cols"] = shift_warnings[:5]
                if len(shift_warnings) > len(numeric_cols) * 0.5 and len(numeric_cols) > 2:
                    warnings.append(f"Distribution shift detected in {len(shift_warnings)} columns")
                    score -= 0.05
        except ImportError:
            pass  # scipy not available

    score = max(round(score, 2), 0.0)
    return {"score": score, "warnings": warnings, "details": details}
