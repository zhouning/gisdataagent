#!/usr/bin/env python3
"""Verify the frozen GWM-Bench Foundation Historical v1.0 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = RELEASE_ROOT / "release_manifest.json"
DEFAULT_OUTPUT = RELEASE_ROOT / "acceptance_report.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_artifact(row: dict[str, Any]) -> dict[str, Any]:
    path = REPO_ROOT / row["path"]
    exists = path.is_file()
    actual_size = path.stat().st_size if exists else None
    actual_hash = _sha256(path) if exists else None
    errors = []
    if not exists:
        errors.append("missing")
    if exists and "size_bytes" in row and actual_size != row["size_bytes"]:
        errors.append("size_mismatch")
    if exists and actual_hash != row["sha256"]:
        errors.append("sha256_mismatch")
    return {
        "role": row.get("role", "dataset_resource"),
        "path": row["path"],
        "exists": exists,
        "expected_size_bytes": row.get("size_bytes"),
        "actual_size_bytes": actual_size,
        "expected_sha256": row["sha256"],
        "actual_sha256": actual_hash,
        "passed": not errors,
        "errors": errors,
    }


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)


def _semantic_checks(manifest: dict[str, Any]) -> dict[str, bool]:
    benchmark_root = REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1"
    validation = _load_json(benchmark_root / "development/data_validation_report.json")
    readiness = _load_json(benchmark_root / "readiness_report.json")
    bundle = _load_json(benchmark_root / "development/bundle_manifest.json")
    evaluation = _load_json(
        benchmark_root / "development/twm_v3_historical_backtest/evaluation.json"
    )
    twm_metrics = evaluation["evaluations"]["twm_v3"]
    flus_metrics = evaluation["evaluations"]["flus_full_grid"]
    comparison = evaluation["primary_comparison"]["paired_region_bootstrap"][
        "flus_full_grid"
    ]
    expected = manifest["final_comparison"]

    bundle_resources = {
        str(benchmark_root / row["path"]): row for row in bundle["resources"]
    }
    release_resources = {
        str(REPO_ROOT / row["path"]): row for row in manifest["dataset_resources"]
    }
    bundle_matches_release = bundle_resources.keys() == release_resources.keys()
    if bundle_matches_release:
        bundle_matches_release = all(
            bundle_resources[path]["row_count"] == release_resources[path]["row_count"]
            and bundle_resources[path]["sha256"] == release_resources[path]["sha256"]
            for path in bundle_resources
        )

    word_path = REPO_ROOT / next(
        row["path"] for row in manifest["artifacts"] if row["role"] == "report_word"
    )
    with zipfile.ZipFile(word_path) as archive:
        embedded_image_count = sum(
            name.startswith("word/media/") and not name.endswith("/")
            for name in archive.namelist()
        )

    return {
        "release_status_is_historical_ready": manifest["status"]
        == "historical_backtest_ready",
        "all_13_data_checks_passed": validation["status"]
        == "data_validation_passed"
        and len(validation["checks"]) == 13
        and all(validation["checks"].values()),
        "value_comparison_count_is_271698": validation["counts"][
            "total_value_comparisons"
        ]
        == 271698,
        "internal_foundation_is_ready": readiness["readiness_tiers"][
            "internal_foundation_ready"
        ],
        "public_prospective_track_is_not_misrepresented": not readiness[
            "readiness_tiers"
        ]["public_foundation_ready"]
        and readiness["hidden_evaluation_audit"]["status"]
        == manifest["prospective_track"]["status"]
        and readiness["hidden_evaluation_audit"]["earliest_valid_export_date"]
        == manifest["prospective_track"]["earliest_valid_export_date"],
        "bundle_resources_match_release_manifest": bundle_matches_release,
        "twm_primary_metric_matches": _close(
            twm_metrics["primary_metric"]["value"], expected["twm"]
        ),
        "flus_primary_metric_matches": _close(
            flus_metrics["primary_metric"]["value"], expected["flus"]
        ),
        "comparison_interval_matches": all(
            _close(actual, frozen)
            for actual, frozen in zip(
                comparison["bootstrap_95_percent_interval"],
                expected["bootstrap_95_percent_interval"],
                strict=True,
            )
        ),
        "historical_row_count_is_2110": twm_metrics["overall_secondary_metrics"][
            "row_count"
        ]
        == flus_metrics["overall_secondary_metrics"]["row_count"]
        == manifest["dataset_summary"]["scored_row_count"],
        "word_report_embeds_5_images": embedded_image_count == 5,
        "claim_boundary_is_preserved": manifest["claim_boundary"][
            "historical_dataset_integrity_supported"
        ]
        and manifest["claim_boundary"]["historical_twm_flus_comparison_supported"]
        and not manifest["claim_boundary"]["prospective_2026_acceptance_supported"]
        and not manifest["claim_boundary"]["general_gwm_validity_supported"],
    }


def verify_release(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    manifest = _load_json(MANIFEST_PATH)
    artifact_checks = [_check_artifact(row) for row in manifest["artifacts"]]
    resource_checks = [
        _check_artifact(row) for row in manifest["dataset_resources"]
    ]
    semantic_checks = _semantic_checks(manifest)
    passed = (
        all(row["passed"] for row in artifact_checks)
        and all(row["passed"] for row in resource_checks)
        and all(semantic_checks.values())
    )
    report = {
        "schema": "gwm_bench.foundation_historical_acceptance.v1",
        "release_id": manifest["release_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "artifact_check_count": len(artifact_checks),
        "dataset_resource_check_count": len(resource_checks),
        "semantic_check_count": len(semantic_checks),
        "artifact_checks": artifact_checks,
        "dataset_resource_checks": resource_checks,
        "semantic_checks": semantic_checks,
        "prospective_track_status": manifest["prospective_track"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"GWM-Bench Foundation Historical v1.0: {report['status']}")
    print(f"Acceptance report: {output_path}")
    if not passed:
        failed = [
            row["path"]
            for row in artifact_checks + resource_checks
            if not row["passed"]
        ]
        failed.extend(name for name, value in semantic_checks.items() if not value)
        print("Failed checks:", file=sys.stderr)
        for name in failed:
            print(f"- {name}", file=sys.stderr)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = verify_release(args.output.resolve())
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
