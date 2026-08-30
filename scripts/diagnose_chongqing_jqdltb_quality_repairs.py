#!/usr/bin/env python3
"""Build an aggregate-only, approval-gated JQDLTB quality repair diagnostic."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
DIAGNOSTIC_SCHEMA = "gis-data-agent.vector-source-quality-repair-diagnostic.v1"


def _finite_round(value: Any) -> float | None:
    import math

    number = float(value)
    return round(number, 8) if math.isfinite(number) else None


def _field_profile(frame: Any, field: str) -> dict[str, Any]:
    import pandas as pd

    series = frame[field]
    non_null = series.dropna()
    blank_count = (
        int(series.fillna("").astype(str).str.strip().eq("").sum())
        if pd.api.types.is_string_dtype(series.dtype)
        or pd.api.types.is_object_dtype(series.dtype)
        else 0
    )
    return {
        "field": field,
        "dtype": str(series.dtype),
        "distinct_non_null": int(non_null.nunique()),
        "null_count": int(series.isna().sum()),
        "blank_count": blank_count,
        "unique_complete": bool(
            len(non_null) == len(frame)
            and blank_count == 0
            and non_null.nunique() == len(frame)
        ),
    }


def _candidate_key_profiles(
    frame: Any,
    primary_key: str,
    excluded_fields: set[str],
) -> list[dict[str, Any]]:
    candidates = []
    for field in frame.columns:
        if field == frame.geometry.name or field == primary_key or field in excluded_fields:
            continue
        profile = _field_profile(frame, str(field))
        if profile["unique_complete"]:
            profile["candidate_role"] = (
                "technical_unique_candidate_requires_business_approval"
            )
            candidates.append(profile)
    return sorted(candidates, key=lambda value: value["field"])


def _numeric_diagnostic(frame: Any, field: str) -> dict[str, Any]:
    import pandas as pd

    values = pd.to_numeric(frame[field], errors="coerce")
    return {
        "field": field,
        "invalid_count": int(values.isna().sum()),
        "nonpositive_count": int((values <= 0).fillna(False).sum()),
        "zero_count": int((values == 0).fillna(False).sum()),
        "negative_count": int((values < 0).fillna(False).sum()),
        "minimum": _finite_round(values.min()),
        "maximum": _finite_round(values.max()),
    }


def _area_diagnostic(frame: Any, declared_area_field: str, tolerance: float) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    declared = pd.to_numeric(frame[declared_area_field], errors="coerce")
    geometry = frame.geometry
    comparable = declared.notna() & (declared > 0) & geometry.notna()
    relative_error = (
        (geometry.area[comparable] - declared[comparable]).abs()
        / declared[comparable].abs()
    )
    finite = relative_error[np.isfinite(relative_error)]
    return {
        "declared_area_field": declared_area_field,
        "comparison_rule": f"abs(geometry_area - declared_area) / declared_area <= {tolerance}",
        "records_compared": int(len(finite)),
        "records_excluded": int(len(frame) - len(finite)),
        "outside_tolerance_count": int((finite > tolerance).sum()),
        "over_5_percent_count": int((finite > 0.05).sum()),
        "over_10_percent_count": int((finite > 0.10).sum()),
        "maximum_relative_error": _finite_round(finite.max()),
        "mean_relative_error": _finite_round(finite.mean()),
        "geometry_area_sum": _finite_round(geometry.area.sum()),
        "declared_area_sum": _finite_round(declared.sum()),
    }


def _derivation_candidate_profile(frame: Any, derivation: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    target = str(derivation)
    hints = {
        "SJNF": ("SJNF", "PZWH", "SM", "JQDLMC"),
        "MSSM": ("MSSM", "SM", "DLBZ", "PZWH", "JQDLMC"),
    }.get(target, (target,))
    for field in hints:
        if field in frame.columns:
            profile = _field_profile(frame, field)
            profile["candidate_role"] = "requires_semantic_approval"
            candidates.append(profile)
    return {
        "target_field": target,
        "status": "pending_approval",
        "candidates": candidates,
        "auto_derivation": False,
    }


def build_quality_repair_diagnostic(
    *, frame: Any, protocol: Mapping[str, Any], archive_sha256: str, bundle_sha256: str
) -> dict[str, Any]:
    """Return aggregate facts and proposals without changing source bytes."""
    source = protocol["source"]
    quality_rules = protocol["quality_rules"]
    standardization = protocol["standardization"]
    primary_key = str(quality_rules["primary_key"])
    numeric_fields = {
        str(rule["field"]) for rule in quality_rules["numeric_constraints"]
    }
    candidates = _candidate_key_profiles(frame, primary_key, numeric_fields)
    numeric = [
        _numeric_diagnostic(frame, str(rule["field"]))
        for rule in quality_rules["numeric_constraints"]
        if str(rule["field"]) in frame.columns
    ]
    area = _area_diagnostic(
        frame,
        str(quality_rules["area_consistency"]["declared_area_field"]),
        float(quality_rules["area_consistency"]["max_relative_error"]),
    )
    derivations = [
        _derivation_candidate_profile(frame, target)
        for target in standardization.get("derivations", {})
    ]
    proposed_actions = [
        {
            "id": "select_business_key",
            "status": "approval_required",
            "candidate": "TBBH" if any(item["field"] == "TBBH" for item in candidates) else None,
            "reason": "BSM is not unique; TBBH is unique and complete in this source snapshot",
            "side_effect": "none_in_diagnostic; requires approved mapping before materialization",
        },
        {
            "id": "quarantine_nonpositive_areas",
            "status": "approval_required",
            "fields": [item["field"] for item in numeric if item["nonpositive_count"]],
            "reason": "non-positive declared area cannot pass the frozen source-quality rule",
            "side_effect": "would exclude or quarantine records; no automatic choice",
        },
        {
            "id": "reconcile_declared_area",
            "status": "approval_required",
            "outside_tolerance_count": area["outside_tolerance_count"],
            "reason": (
                "geometry-derived area differs from declared TBMJ beyond the frozen "
                "tolerance"
            ),
            "side_effect": (
                "must preserve source value and record derivation/quality evidence if "
                "corrected"
            ),
        },
        {
            "id": "approve_standard_derivations",
            "status": "approval_required",
            "targets": [item["target_field"] for item in derivations],
            "reason": "SJNF and MSSM have no approved semantic derivation",
            "side_effect": "would change canonical product fields; no automatic derivation",
        },
    ]
    report = {
        "schema": DIAGNOSTIC_SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "source": {
            "archive_sha256": archive_sha256,
            "bundle_sha256": bundle_sha256,
            "relative_path": source["relative_path"],
            "feature_count": int(len(frame)),
            "crs": frame.crs.to_string() if frame.crs else None,
        },
        "diagnostic_policy": {
            "mode": "aggregate_only_read_only",
            "source_values_persisted": False,
            "source_bytes_modified": False,
            "auto_repair": False,
            "promotion_ready": False,
        },
        "primary_key": {
            "configured": primary_key,
            "configured_profile": _field_profile(frame, primary_key),
            "candidate_fields": candidates,
        },
        "numeric_constraints": numeric,
        "area_consistency": area,
        "standard_derivations": derivations,
        "proposed_actions": proposed_actions,
        "governance": {
            "business_steward": protocol["governance"].get("business_steward"),
            "license_status": protocol["governance"].get("license_status"),
            "approval_required": True,
        },
        "limitations": [
            "TBBH is a candidate key, not an approved business authority",
            "geometry-derived area is diagnostic evidence, not a replacement value",
            "SJNF/MSSM derivations remain unapproved",
            "no Raw, ODS, DWD, ADS or DataProductVersion was written",
        ],
    }
    from data_agent.platform_contracts import canonical_json_fingerprint

    report["diagnostic_sha256"] = canonical_json_fingerprint(report)
    return report


def diagnose(protocol_path: Path, dataset_root: Path) -> dict[str, Any]:
    import geopandas as gpd

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    root = dataset_root.resolve(strict=True)
    relative_path = Path(str(protocol["source"]["relative_path"]))
    source_path = (root / relative_path).resolve(strict=True)
    if not source_path.is_relative_to(root):
        raise ValueError("source path escapes dataset root")
    frame = gpd.read_file(source_path)
    from data_agent.standards_platform.application.acceptance import bundle_identity

    identity = bundle_identity(source_path)
    expected = str(protocol["source"]["bundle_sha256"])
    if identity["bundle_sha256"] != expected:
        raise ValueError("source bundle identity does not match the sealed protocol")
    return build_quality_repair_diagnostic(
        frame=frame,
        protocol=protocol,
        archive_sha256=str(protocol["source"]["archive_sha256"]),
        bundle_sha256=identity["bundle_sha256"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    protocol_path = args.protocol if args.protocol.is_absolute() else REPO_ROOT / args.protocol
    dataset_root = (
        args.dataset_root
        if args.dataset_root.is_absolute()
        else REPO_ROOT / args.dataset_root
    )
    report = diagnose(protocol_path, dataset_root)
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output": str(output),
                "feature_count": report["source"]["feature_count"],
                "configured_primary_key": report["primary_key"]["configured"],
                "candidate_key_fields": [
                    item["field"]
                    for item in report["primary_key"]["candidate_fields"]
                ],
                "outside_area_tolerance": report["area_consistency"][
                    "outside_tolerance_count"
                ],
                "promotion_ready": report["diagnostic_policy"]["promotion_ready"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
