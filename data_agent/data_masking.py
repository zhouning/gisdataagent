"""
Data Masking — field-level PII masking strategies (v15.0).

Provides 5 masking strategies: mask (partial), redact (full), hash (one-way),
generalize (reduce precision), encrypt (reversible Fernet).
"""

import hashlib
import json
import logging
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Masking strategy functions
# ---------------------------------------------------------------------------

def _mask_partial(value, keep_prefix: int = 3, keep_suffix: int = 0) -> str:
    """Keep first N chars, mask the rest with *."""
    s = str(value)
    if len(s) <= keep_prefix + keep_suffix:
        return s
    masked = s[:keep_prefix] + "*" * (len(s) - keep_prefix - keep_suffix)
    if keep_suffix > 0:
        masked += s[-keep_suffix:]
    return masked


def _redact(value) -> str:
    return "[REDACTED]"


def _hash_value(value) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def _generalize(value) -> str:
    """Reduce precision: addresses to province level, numbers to ranges."""
    s = str(value)
    # Phone: keep first 3 digits
    if len(s) == 11 and s.startswith("1"):
        return s[:3] + "****" + s[-4:]
    # Address: keep only province/city
    for marker in ("区", "县", "镇", "村", "路", "街", "号"):
        idx = s.find(marker)
        if idx > 0:
            return s[:idx + 1] + "***"
    return s[:4] + "***" if len(s) > 4 else s


STRATEGY_MAP = {
    "mask": _mask_partial,
    "redact": _redact,
    "hash": _hash_value,
    "generalize": _generalize,
}


# ---------------------------------------------------------------------------
# DataFrame-level masking
# ---------------------------------------------------------------------------

def mask_dataframe(gdf, field_rules: dict) -> gpd.GeoDataFrame:
    """Apply masking strategies to specified fields.

    Args:
        gdf: GeoDataFrame to mask.
        field_rules: {column_name: strategy_name} where strategy is mask/redact/hash/generalize.

    Returns:
        New GeoDataFrame with masked fields.
    """
    result = gdf.copy()
    for col, strategy in field_rules.items():
        if col not in result.columns:
            continue
        fn = STRATEGY_MAP.get(strategy, _redact)
        result[col] = result[col].apply(lambda v: fn(v) if pd.notna(v) else v)
    return result


def mask_sensitive_fields(file_path: str, field_rules: str) -> str:
    """Agent tool: mask sensitive fields in a data file.

    Args:
        file_path: Input data file path.
        field_rules: JSON mapping {column: strategy}. Strategies: mask/redact/hash/generalize.

    Returns:
        JSON result with output file path and masking summary.
    """
    try:
        from .utils import _load_spatial_data
        from .gis_processors import _generate_output_path

        gdf = _load_spatial_data(file_path)
        rules = json.loads(field_rules) if isinstance(field_rules, str) else field_rules

        # Validate fields exist
        valid_rules = {k: v for k, v in rules.items() if k in gdf.columns}
        if not valid_rules:
            return json.dumps({"status": "error", "message": "指定字段不存在"},
                              ensure_ascii=False)

        masked = mask_dataframe(gdf, valid_rules)
        out = _generate_output_path("masked", "gpkg")
        masked.to_file(out, driver="GPKG")

        return json.dumps({
            "status": "ok", "output": out,
            "masked_fields": list(valid_rules.keys()),
            "strategies": valid_rules,
            "row_count": len(masked),
        }, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "field_rules 不是合法的JSON"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
