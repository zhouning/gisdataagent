#!/usr/bin/env python3
"""Verify GWM-Bench Foundation V2.0-rc1 without opening hidden labels."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (  # noqa: E402
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)


RELEASE_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = RELEASE_ROOT / "suite_protocol.json"
DEFAULT_OUTPUT = RELEASE_ROOT / "rc1_acceptance_report.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(artifact: dict[str, Any]) -> Path:
    path = Path(artifact["path"])
    if artifact.get("path_scope", "repository_relative") == "repository_relative":
        path = REPO_ROOT / path
    return path.resolve()


def _check_artifact(name: str, artifact: dict[str, Any]) -> dict[str, Any]:
    path = _path(artifact)
    exists = path.is_file()
    actual_size = path.stat().st_size if exists else None
    actual_hash = _sha256(path) if exists else None
    errors = []
    if not exists:
        errors.append("missing")
    elif actual_size != int(artifact["size_bytes"]):
        errors.append("size_mismatch")
    elif actual_hash != artifact["sha256"]:
        errors.append("sha256_mismatch")
    return {
        "name": name,
        "path": str(path),
        "exists": exists,
        "expected_size_bytes": artifact["size_bytes"],
        "actual_size_bytes": actual_size,
        "expected_sha256": artifact["sha256"],
        "actual_sha256": actual_hash,
        "passed": not errors,
        "errors": errors,
    }


def _prediction(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path).sort_values(KEY_COLUMNS, kind="mergesort")
    return frame.reset_index(drop=True)


def _prediction_valid(frame: pd.DataFrame) -> bool:
    if list(frame.columns) != KEY_COLUMNS + PROBABILITY_COLUMNS:
        return False
    if len(frame) != 6330 or frame.duplicated(KEY_COLUMNS).any():
        return False
    if set(frame["target_year"].astype(int)) != set(range(2021, 2027)):
        return False
    values = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    return bool(
        np.isfinite(values).all()
        and np.all((values >= 0.0) & (values <= 1.0))
        and np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0)
    )


def _predicted_changes(frame: pd.DataFrame) -> int:
    bridge = frame[frame["target_year"].isin((2025, 2026))].copy()
    bridge["predicted_class"] = np.argmax(
        bridge[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64), axis=1
    )
    wide = bridge.pivot(
        index=["fold_index", "region_id", "node_id"],
        columns="target_year",
        values="predicted_class",
    )
    return int((wide[2026] != wide[2025]).sum())


def verify_v2_rc1(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    artifact_checks = [
        _check_artifact(name, artifact)
        for name, artifact in protocol["artifacts"].items()
    ]
    artifact_by_name = {row["name"]: row for row in artifact_checks}

    data_validation = _load_json(
        _path(protocol["artifacts"]["data_validation"])
    )
    twm_protocol = _load_json(_path(protocol["artifacts"]["twm_protocol"]))
    twm_verification = _load_json(
        _path(protocol["artifacts"]["twm_verification"])
    )
    flus_protocol = _load_json(_path(protocol["artifacts"]["flus_protocol"]))
    twm = _prediction(_path(protocol["artifacts"]["twm_prediction"]))
    flus = _prediction(_path(protocol["artifacts"]["flus_prediction"]))
    hidden_manifest = REPO_ROOT / protocol["hidden_labels"]["manifest_path"]

    twm_commitment = protocol["prediction_commitments"]["twm"]
    flus_commitment = protocol["prediction_commitments"]["flus"]
    semantic_checks = {
        "suite_status_is_rc1_labels_pending": protocol["status"]
        == "rc1_candidates_and_evaluator_sealed_labels_pending",
        "all_direct_artifacts_match": all(
            row["passed"] for row in artifact_checks
        ),
        "all_13_data_checks_passed": data_validation["status"]
        == "data_validation_passed"
        and len(data_validation["checks"]) == 13
        and all(data_validation["checks"].values()),
        "value_comparison_count_is_271698": data_validation["counts"][
            "total_value_comparisons"
        ]
        == 271698,
        "runtime_replay_evidence_passed": twm_verification["status"]
        == "2026_precommit_integrity_verified_without_labels"
        and math.isclose(
            twm_verification[
                "ensemble_2021_2025_maximum_probability_absolute_error"
            ],
            0.0,
            rel_tol=0.0,
            abs_tol=0.0,
        ),
        "twm_candidate_sealed_without_labels": twm_protocol["status"]
        == "candidate_and_predictions_sealed_before_2026_labels"
        and not twm_protocol["integrity"]["2026_label_pixels_accessed"],
        "flus_candidate_sealed_without_labels": flus_protocol["status"]
        == "flus_candidate_and_predictions_sealed_before_2026_labels"
        and not flus_protocol["integrity"]["hidden_label_pixels_accessed"]
        and len(flus_protocol["artifacts"]["members"]) == 3,
        "twm_prediction_schema_and_keys_valid": _prediction_valid(twm),
        "flus_prediction_schema_and_keys_valid": _prediction_valid(flus),
        "twm_and_flus_keys_identical": twm[KEY_COLUMNS].equals(
            flus[KEY_COLUMNS]
        ),
        "twm_prediction_commitment_matches": artifact_by_name[
            "twm_prediction"
        ]["actual_sha256"]
        == twm_commitment["sha256"]
        and _predicted_changes(twm)
        == int(twm_commitment["predicted_2026_change_count"]),
        "flus_prediction_commitment_matches": artifact_by_name[
            "flus_prediction"
        ]["actual_sha256"]
        == flus_commitment["sha256"]
        and _predicted_changes(flus)
        == int(flus_commitment["predicted_2026_change_count"]),
        "hidden_label_manifest_absent": not hidden_manifest.exists(),
        "earliest_export_date_preserved": protocol["hidden_labels"][
            "earliest_valid_export_date"
        ]
        == "2027-01-01",
        "benchmark_completion_independent_of_model_win": not protocol[
            "benchmark_completion_rule"
        ]["model_win_required"]
        and protocol["benchmark_completion_rule"]["negative_result_publishable"],
        "shared_runtime_product_not_overclaimed": not protocol["tracks"][
            "RUNTIME-R1"
        ]["shared_cross_domain_runtime_product_claimed"],
    }
    passed = all(semantic_checks.values())
    report = {
        "schema": "gwm_bench.foundation_v2_rc1_acceptance.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_LABELS_PENDING" if passed else "FAIL",
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "artifact_check_count": len(artifact_checks),
        "semantic_check_count": len(semantic_checks),
        "artifact_checks": artifact_checks,
        "semantic_checks": semantic_checks,
        "prediction_summary": {
            "row_count_per_model": len(twm),
            "twm_predicted_2026_change_count": _predicted_changes(twm),
            "flus_predicted_2026_change_count": _predicted_changes(flus),
            "scores_available": False,
        },
        "remaining_gate": {
            "status": protocol["hidden_labels"]["status"],
            "earliest_valid_export_date": protocol["hidden_labels"][
                "earliest_valid_export_date"
            ],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"GWM-Bench Foundation V2.0-rc1: {report['status']}")
    print(f"Acceptance report: {output_path}")
    return report


if __name__ == "__main__":
    result = verify_v2_rc1()
    raise SystemExit(0 if result["status"] == "PASS_LABELS_PENDING" else 1)
