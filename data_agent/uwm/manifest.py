"""UWM data-foundation manifest validation."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


UWM_MANIFEST_REQUIRED_COLUMNS = [
    "dataset_id",
    "dataset_name",
    "source_type",
    "source_ref",
    "access_status",
    "spatial_extent",
    "temporal_extent",
    "geometry_type",
    "crs",
    "license",
    "lineage",
    "quality_status",
    "synthetic_status",
    "used_by",
    "claim_boundary",
]

ALLOWED_SOURCE_TYPES = {
    "public",
    "restricted_local",
    "restricted_expected",
    "synthetic",
    "paper6",
    "paper58",
    "planning_sample",
}

ALLOWED_SYNTHETIC_STATUS = {
    "real",
    "public_proxy",
    "fitted_proxy",
    "restricted_expected",
    "synthetic",
    "semi_synthetic",
    "smoke_only",
}

ALLOWED_CLAIM_BOUNDARIES = {
    "core_support",
    "bounded_support",
    "fragile",
    "exploratory_only",
    "not_for_claim",
}


def validate_manifest_row(row: dict[str, Any]) -> dict[str, Any]:
    """Validate one UWM data-foundation manifest row."""

    errors: list[str] = []
    for column in UWM_MANIFEST_REQUIRED_COLUMNS:
        if not str(row.get(column, "")).strip():
            errors.append(f"{column} is required")

    source_type = str(row.get("source_type", "")).strip()
    synthetic_status = str(row.get("synthetic_status", "")).strip()
    claim_boundary = str(row.get("claim_boundary", "")).strip()
    if source_type and source_type not in ALLOWED_SOURCE_TYPES:
        errors.append(f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}")
    if synthetic_status and synthetic_status not in ALLOWED_SYNTHETIC_STATUS:
        errors.append(f"synthetic_status must be one of {sorted(ALLOWED_SYNTHETIC_STATUS)}")
    if claim_boundary and claim_boundary not in ALLOWED_CLAIM_BOUNDARIES:
        errors.append(f"claim_boundary must be one of {sorted(ALLOWED_CLAIM_BOUNDARIES)}")
    if synthetic_status in {"fitted_proxy", "synthetic", "semi_synthetic", "smoke_only"} and claim_boundary == "core_support":
        errors.append("synthetic/fitted rows cannot use core_support claim_boundary")
    return {"valid": not errors, "errors": errors}


def audit_uwm_manifest(path: str | Path) -> dict[str, Any]:
    """Audit a UWM data-foundation manifest CSV."""

    manifest_path = Path(path)
    errors: list[str] = []
    rows: list[dict[str, str]] = []
    if not manifest_path.exists():
        return {"valid": False, "errors": [f"manifest not found: {manifest_path}"], "row_count": 0}

    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in UWM_MANIFEST_REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            errors.append(f"missing required columns: {', '.join(missing)}")
        for line_number, row in enumerate(reader, start=2):
            rows.append(row)
            row_validation = validate_manifest_row(row)
            if not row_validation["valid"]:
                for error in row_validation["errors"]:
                    errors.append(f"line {line_number}: {error}")

    return {
        "schema": "uwm.data_foundation_manifest_audit.v1",
        "valid": not errors,
        "errors": errors,
        "path": str(manifest_path),
        "row_count": len(rows),
        "source_type_counts": dict(Counter(row.get("source_type", "") for row in rows)),
        "synthetic_status_counts": dict(Counter(row.get("synthetic_status", "") for row in rows)),
        "claim_boundary_counts": dict(Counter(row.get("claim_boundary", "") for row in rows)),
    }
