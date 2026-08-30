#!/usr/bin/env python3
"""Preview the impact of unresolved JQDLTB transformation choices.

This command is deliberately read-only. It verifies the frozen source identity,
evaluates the policy combinations that do not require an unprovided correction
file or area-rule artifact, and records the remaining semantic blockers. It
never creates an ApprovalCase and never writes Raw/ODS/DIM/DWD/ADS data.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent.platform_contracts import (
    JqdltbTransformationContract,
    JqdltbTransformationMode,
    canonical_json_fingerprint,
)
from data_agent.standards_platform.application.acceptance import bundle_identity

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_DIAGNOSTIC = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
DEFAULT_BASELINE = (
    REPO_ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/jqdltb_transformation_impact_preview_2026-08-26.json"
SCHEMA = "gda.jqdltb_transformation_impact_preview.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _diagnostic_sha256(diagnostic: dict[str, Any]) -> str:
    value = dict(diagnostic)
    observed = value.pop("diagnostic_sha256", None)
    calculated = canonical_json_fingerprint(value)
    if observed != calculated:
        raise ValueError("JQDLTB diagnostic fingerprint is invalid")
    return calculated


def _source_path(protocol: dict[str, Any], dataset_root: Path) -> Path:
    root = dataset_root.resolve(strict=True)
    source = (root / Path(str(protocol["source"]["relative_path"]))).resolve(strict=True)
    if not source.is_relative_to(root):
        raise ValueError("JQDLTB source path escapes dataset root")
    return source


def _mask_series(frame: Any, field: str) -> pd.Series:
    return pd.to_numeric(frame[field], errors="coerce")


def _evaluate_policy(
    *,
    frame: Any,
    canonical_key: str,
    nonpositive_policy: str,
    area_deviation_policy: str,
    tolerance: float,
) -> dict[str, Any]:
    key_values = frame[canonical_key].fillna("").astype(str).str.strip()
    key_valid = key_values.ne("")
    key_duplicate = key_values.duplicated(keep=False)
    key_ready = key_valid & ~key_duplicate

    area_values = {
        field: _mask_series(frame, field)
        for field in ("TBMJ", "TBDLMJ")
    }
    nonpositive = pd.Series(False, index=frame.index)
    nonpositive_fields: dict[str, int] = {}
    for field, values in area_values.items():
        field_mask = values.isna() | values.le(0)
        nonpositive |= field_mask
        nonpositive_fields[field] = int(field_mask.sum())

    declared = area_values["TBMJ"]
    geometry_area = frame.geometry.area
    comparable = declared.notna() & declared.gt(0) & frame.geometry.notna()
    relative_error = pd.Series(float("nan"), index=frame.index)
    relative_error.loc[comparable] = (
        (geometry_area.loc[comparable] - declared.loc[comparable]).abs()
        / declared.loc[comparable].abs()
    )
    area_deviation = relative_error.gt(tolerance).fillna(False)

    policy_input_blockers: list[str] = []
    if nonpositive_policy == "business_correction":
        policy_input_blockers.append("business_correction_resource_version_missing")
    if area_deviation_policy == "use_geometry":
        policy_input_blockers.append("geometry_area_rule_missing")

    quarantine = pd.Series(False, index=frame.index)
    reason_counts: dict[str, int] = {}
    if nonpositive_policy == "quarantine":
        quarantine |= nonpositive
        reason_counts["nonpositive_declared_area"] = int(nonpositive.sum())
    if area_deviation_policy == "quarantine":
        affected = area_deviation & ~quarantine
        quarantine |= area_deviation
        reason_counts["area_deviation_outside_tolerance"] = int(affected.sum())

    area_eligible = key_ready & ~quarantine
    unresolved_derivations = ["SJNF", "MSSM"]
    projection_exact = nonpositive_policy != "business_correction"
    materializable_if_semantics_approved = (
        int(area_eligible.sum()) if projection_exact else None
    )
    return {
        "status": "impact_computed",
        "policy": {
            "canonical_key": canonical_key,
            "nonpositive_area_policy": nonpositive_policy,
            "area_deviation_policy": area_deviation_policy,
        },
        "policy_input_blockers": policy_input_blockers,
        "execution_blockers": [
            "canonical_key_business_approval_missing",
            *policy_input_blockers,
            "sjnf_semantic_derivation_pending",
            "mssm_semantic_derivation_pending",
            "strategy_selection_missing",
            "transformation_approval_case_missing",
        ],
        "observations": {
            "records_read": int(len(frame)),
            "canonical_key_ready": int(key_ready.sum()),
            "canonical_key_invalid": int((~key_valid).sum()),
            "canonical_key_duplicate_rows": int(key_duplicate.sum()),
            "nonpositive_area_by_field": nonpositive_fields,
            "nonpositive_area_union": int(nonpositive.sum()),
            "area_deviation_outside_tolerance": int(area_deviation.sum()),
            "area_deviation_over_10_percent": int(relative_error.gt(0.10).fillna(False).sum()),
            "area_records_compared": int(comparable.sum()),
            "static_quarantine_records": int(quarantine.sum()),
            "static_quarantine_reason_counts": reason_counts,
        },
        "projection": {
            "exact": projection_exact,
            "records_quarantined": int(quarantine.sum()) if projection_exact else None,
            "records_after_area_policy": (
                int(area_eligible.sum()) if projection_exact else None
            ),
            "records_materializable_if_semantics_approved": (
                materializable_if_semantics_approved
            ),
            "uncertainty": (
                None
                if projection_exact
                else "correction values may change both nonpositive and deviation membership"
            ),
        },
        "semantic_derivations": {
            "status": "pending_approval",
            "targets": unresolved_derivations,
            "source_records_in_scope": int(len(frame)),
        },
        "quality": {
            "verdict": "blocked",
            "promotion_ready": False,
            "data_product_version_created": False,
        },
    }


def build_preview(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    baseline_path: Path = DEFAULT_BASELINE,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    protocol = _read_json(protocol_path)
    diagnostic = _read_json(diagnostic_path)
    baseline = JqdltbTransformationContract.model_validate(_read_json(baseline_path))
    diagnostic_sha256 = _diagnostic_sha256(diagnostic)
    source_path = _source_path(protocol, dataset_root)

    if baseline.mode is not JqdltbTransformationMode.APPROVAL_REQUIRED:
        raise ValueError("impact preview requires the unresolved approval-gated baseline")
    expected_identities = {
        "archive_sha256": str(protocol["source"]["archive_sha256"]),
        "bundle_sha256": str(protocol["source"]["bundle_sha256"]),
        "diagnostic_sha256": diagnostic_sha256,
    }
    for field, expected in expected_identities.items():
        if str(getattr(baseline, field)) != expected:
            raise ValueError(f"baseline {field} differs from the frozen source evidence")

    import geopandas as gpd

    identity_before = bundle_identity(source_path)
    frame = gpd.read_file(source_path)
    identity_after = bundle_identity(source_path)
    if identity_before != identity_after:
        raise ValueError("source bundle changed while the impact preview was reading it")
    expected_bundle = str(protocol["source"]["bundle_sha256"])
    if identity_after["bundle_sha256"] != expected_bundle:
        raise ValueError("source bundle identity does not match the sealed protocol")
    if int(len(frame)) != int(diagnostic["source"]["feature_count"]):
        raise ValueError("source feature count differs from the frozen diagnostic")
    diagnostic_source = diagnostic["source"]
    source_facts = {
        "archive_sha256": str(protocol["source"]["archive_sha256"]),
        "bundle_sha256": expected_bundle,
        "relative_path": str(protocol["source"]["relative_path"]),
        "crs": frame.crs.to_string() if frame.crs else None,
    }
    if any(str(diagnostic_source[field]) != value for field, value in source_facts.items()):
        raise ValueError("source identity differs from the frozen diagnostic")

    tolerance = float(protocol["quality_rules"]["area_consistency"]["max_relative_error"])
    matrix = [
        _evaluate_policy(
            frame=frame,
            canonical_key="TBBH",
            nonpositive_policy=nonpositive,
            area_deviation_policy=deviation,
            tolerance=tolerance,
        )
        for nonpositive in ("quarantine", "business_correction")
        for deviation in ("preserve_source", "use_geometry", "quarantine")
    ]
    diagnostic_numeric = {
        str(item["field"]): int(item["nonpositive_count"])
        for item in diagnostic["numeric_constraints"]
    }
    observed = matrix[0]["observations"]
    if observed["nonpositive_area_by_field"] != diagnostic_numeric:
        raise ValueError("source nonpositive-area facts differ from the frozen diagnostic")
    candidates = {
        str(item["field"]): bool(item["unique_complete"])
        for item in diagnostic["primary_key"]["candidate_fields"]
    }
    if candidates.get("TBBH") is not True or observed["canonical_key_ready"] != len(frame):
        raise ValueError("TBBH candidate-key facts differ from the frozen diagnostic")
    diagnostic_area = diagnostic["area_consistency"]
    area_facts = {
        "area_deviation_outside_tolerance": int(
            diagnostic_area["outside_tolerance_count"]
        ),
        "area_deviation_over_10_percent": int(diagnostic_area["over_10_percent_count"]),
        "area_records_compared": int(diagnostic_area["records_compared"]),
    }
    if any(observed[field] != expected for field, expected in area_facts.items()):
        raise ValueError("source area-deviation facts differ from the frozen diagnostic")
    scenario_identity = {
        "source_resource_version_id": str(baseline.source_resource_version_id),
        "archive_sha256": baseline.archive_sha256,
        "bundle_sha256": baseline.bundle_sha256,
        "diagnostic_sha256": baseline.diagnostic_sha256,
        "baseline_contract_sha256": baseline.contract_sha256,
    }
    matrix = [
        item
        | {
            "scenario_sha256": canonical_json_fingerprint(
                scenario_identity | item["policy"]
            )
        }
        for item in matrix
    ]
    report = {
        "schema": SCHEMA,
        "scope": "ar0_first_jqdltb_vertical_slice",
        "mode": "aggregate_only_read_only",
        "source_values_persisted": False,
        "source_bytes_modified": False,
        "authority_state_created": False,
        "layer_artifacts_written": False,
        "identities": {
            "protocol_id": protocol["protocol_id"],
            "source_resource_version_id": str(baseline.source_resource_version_id),
            "archive_sha256": protocol["source"]["archive_sha256"],
            "bundle_sha256_before": identity_before["bundle_sha256"],
            "bundle_sha256_after": identity_after["bundle_sha256"],
            "diagnostic_sha256": diagnostic_sha256,
            "baseline_plan_sha256": baseline.plan_sha256,
            "baseline_contract_sha256": baseline.contract_sha256,
            "selected_strategy_sha256": None,
            "standard_version_ref": baseline.standard_version_ref,
            "standard_fingerprint": baseline.standard_fingerprint,
            "feature_count": int(len(frame)),
            "crs": frame.crs.to_string() if frame.crs else None,
        },
        "frozen_rules": {
            "canonical_key": "TBBH",
            "declared_area_fields": ["TBMJ", "TBDLMJ"],
            "area_deviation_field": "TBMJ",
            "area_tolerance": tolerance,
            "required_derivations": ["SJNF", "MSSM"],
        },
        "matrix": matrix,
        "conclusion": {
            "technical_preview_completed": True,
            "any_policy_promotable": False,
            "remaining_business_decisions": [
                "canonical_key_acceptance",
                "nonpositive_area_correction_or_quarantine",
                "area_deviation_policy_and_rule_if_geometry_is_used",
                "SJNF_semantic_derivation",
                "MSSM_semantic_derivation",
            ],
            "next_gate": "business_strategy_then_approval_case_then_execute_contract",
        },
        "evaluated_at": (evaluated_at or datetime.now(UTC)).isoformat(),
    }
    return report | {"preview_sha256": canonical_json_fingerprint(report)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = build_preview(
        protocol_path=args.protocol if args.protocol.is_absolute() else REPO_ROOT / args.protocol,
        dataset_root=(
            args.dataset_root
            if args.dataset_root.is_absolute()
            else REPO_ROOT / args.dataset_root
        ),
        diagnostic_path=(
            args.diagnostic
            if args.diagnostic.is_absolute()
            else REPO_ROOT / args.diagnostic
        ),
        baseline_path=args.baseline if args.baseline.is_absolute() else REPO_ROOT / args.baseline,
    )
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    summary = {
        "schema": SCHEMA,
        "output": str(output),
        "preview_sha256": report["preview_sha256"],
        "policy_count": len(report["matrix"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
