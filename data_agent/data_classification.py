"""
Data Classification — PII detection + sensitivity level assignment (v15.0).

Scans DataFrame columns for personally identifiable information patterns
(Chinese-centric: phone, ID card, bank card, email, address) and assigns
sensitivity levels (public → secret).
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SENSITIVITY_LEVELS = ("public", "internal", "confidential", "restricted", "secret")

# PII detection patterns (Chinese-centric)
PII_PATTERNS = {
    "phone": (re.compile(r"\b1[3-9]\d{9}\b"), "confidential"),
    "id_card": (re.compile(r"\b\d{17}[\dXx]\b"), "restricted"),
    "email": (re.compile(r"\b[\w.-]+@[\w.-]+\.\w{2,}\b"), "internal"),
    "bank_card": (re.compile(r"\b(?:62|4|5)\d{15,18}\b"), "restricted"),
    "address": (re.compile(r"(?:省|市|区|县|镇|村|路|街|号|大道|小区)"), "internal"),
    "coordinate": (re.compile(r"\b\d{2,3}\.\d{4,}\b"), "internal"),
}


def classify_columns(df) -> dict:
    """Scan DataFrame columns for PII patterns.

    Returns: {col_name: {"pii_types": [...], "match_count": N, "suggested_level": "..."}}
    """
    results = {}
    for col in df.columns:
        if col in ("geometry",):
            continue
        col_str = df[col].dropna().astype(str)
        if col_str.empty:
            continue
        sample = col_str.head(200)  # sample for performance
        pii_found = []
        max_level_idx = 0
        for pii_name, (pattern, level) in PII_PATTERNS.items():
            matches = sample.apply(lambda v: bool(pattern.search(str(v))))
            match_count = int(matches.sum())
            if match_count > 0:
                pii_found.append({"type": pii_name, "matches": match_count})
                level_idx = SENSITIVITY_LEVELS.index(level) if level in SENSITIVITY_LEVELS else 0
                max_level_idx = max(max_level_idx, level_idx)
        if pii_found:
            results[col] = {
                "pii_types": pii_found,
                "match_count": sum(p["matches"] for p in pii_found),
                "suggested_level": SENSITIVITY_LEVELS[max_level_idx],
            }
    return results


def classify_asset(file_path: str) -> dict:
    """Full asset classification: column PII scan + overall sensitivity assignment."""
    try:
        from .utils import _load_spatial_data
        gdf = _load_spatial_data(file_path)
        field_classifications = classify_columns(gdf)

        # Aggregate to asset-level sensitivity
        if not field_classifications:
            overall_level = "public"
        else:
            max_idx = max(
                SENSITIVITY_LEVELS.index(fc["suggested_level"])
                for fc in field_classifications.values()
            )
            overall_level = SENSITIVITY_LEVELS[max_idx]

        return {
            "status": "ok",
            "file": file_path,
            "sensitivity_level": overall_level,
            "field_classifications": field_classifications,
            "fields_scanned": len([c for c in gdf.columns if c != "geometry"]),
            "pii_fields_found": len(field_classifications),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_asset_sensitivity(asset_id: int, level: str, username: str) -> dict:
    """Update data catalog asset with sensitivity level."""
    if level not in SENSITIVITY_LEVELS:
        return {"status": "error", "message": f"Invalid level. Must be one of {SENSITIVITY_LEVELS}"}
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return {"status": "error", "message": "Database unavailable"}
        with engine.connect() as conn:
            result = conn.execute(text(
                "UPDATE agent_data_catalog SET sensitivity_level = :level, updated_at = NOW() "
                "WHERE id = :id AND (owner_username = :owner OR :owner = 'admin')"
            ), {"level": level, "id": asset_id, "owner": username})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "Asset not found or no permission"}
        return {"status": "ok", "asset_id": asset_id, "sensitivity_level": level}
    except Exception as e:
        return {"status": "error", "message": str(e)}
