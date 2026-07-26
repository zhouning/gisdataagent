"""Derive paper tables from the frozen NYC V5 action-transfer result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


MODEL_LABELS = {
    "history_ar_backbone": "History AR backbone",
    "fixed_adjacency_spatial_ar": "Fixed-adjacency spatial AR",
    "dam_gk_residual_no_action": "DAM-GK residual without action",
    "uwm_dam_gk_action_residual": "DAM-GK correct action residual",
    "action_deleted": "Action deleted",
    "effective_date_minus_4w": "Action date -4 weeks",
    "effective_date_plus_4w": "Action date +4 weeks",
    "action_component_permutation": "Action component permutation",
    "wrong_spatial_scope": "Wrong spatial scope",
    "cross_event_action_swap": "Cross-event action swap",
    "zone_exposure_shuffle_seed_20260723": "Zone exposure shuffle",
}

MODEL_TYPES = {
    "history_ar_backbone": "baseline",
    "fixed_adjacency_spatial_ar": "baseline",
    "dam_gk_residual_no_action": "matched_no_action",
    "uwm_dam_gk_action_residual": "candidate",
    "action_deleted": "negative_control",
    "effective_date_minus_4w": "negative_control",
    "effective_date_plus_4w": "negative_control",
    "action_component_permutation": "negative_control",
    "wrong_spatial_scope": "negative_control",
    "cross_event_action_swap": "negative_control",
    "zone_exposure_shuffle_seed_20260723": "negative_control",
}

CANDIDATE_ID = "uwm_dam_gk_action_residual"
HISTORY_ID = "history_ar_backbone"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_frozen_evidence_tables(repo_root: Path, output_root: Path) -> dict[str, Any]:
    """Extract authoritative, non-retuned paper tables from V5 artifacts."""

    benchmark_root = repo_root / "benchmarks/gwm_bench_foundation_v5_0_draft"
    result_path = benchmark_root / "final_results/action_transfer_results.json"
    completion_path = benchmark_root / "final_results/completion_verification.json"
    runtime_path = benchmark_root / "runtime_r4_contract.json"

    result = _load_json(result_path)
    completion = _load_json(completion_path)
    runtime = _load_json(runtime_path)
    output_root.mkdir(parents=True, exist_ok=True)

    if result.get("status") != "ACTION_TRANSFER_NOT_SUPPORTED":
        raise ValueError("Unexpected V5 result status")
    if completion.get("status") != "PASS_V5_BENCHMARK_COMPLETE_ACTION_TRANSFER_NOT_SUPPORTED":
        raise ValueError("V5 completion verification is not passing")
    if _sha256(result_path) != completion["artifacts"]["formal_result"]["sha256"]:
        raise ValueError("Formal result hash differs from completion verification")

    inventory_rows = []
    for role, artifact in completion["artifacts"].items():
        artifact_path = repo_root / artifact["path"]
        inventory_rows.append(
            {
                "role": role,
                "path": artifact["path"],
                "bytes": artifact["bytes"],
                "declared_sha256": artifact["sha256"],
                "observed_sha256": _sha256(artifact_path),
                "hash_matches": _sha256(artifact_path) == artifact["sha256"],
            }
        )
    _write_csv(inventory_rows, output_root / "evidence_inventory.csv")

    integrity_rows = [
        {"check": check, "passed": passed}
        for check, passed in completion["checks"].items()
    ]
    _write_csv(integrity_rows, output_root / "benchmark_integrity.csv")

    score_rows = []
    for model_id, metrics in result["metrics"].items():
        score_rows.append(
            {
                "model_id": model_id,
                "model_label": MODEL_LABELS[model_id],
                "model_type": MODEL_TYPES[model_id],
                "primary_error": metrics[
                    "primary_equal_event_macro_pre_action_normalized_mae"
                ],
            }
        )
    score_rows.sort(key=lambda row: row["primary_error"])
    for rank, row in enumerate(score_rows, start=1):
        row["rank"] = rank
    _write_csv(score_rows, output_root / "primary_scores.csv")

    candidate_metrics = result["metrics"][CANDIDATE_ID]
    history_metrics = result["metrics"][HISTORY_ID]
    gate = result["action_transfer_gate"]
    fold_rows = []
    for fold_id, skill in gate["fold_skill"].items():
        fold_rows.append(
            {
                "fold_id": fold_id,
                "history_error": history_metrics["by_fold"][fold_id],
                "candidate_error": candidate_metrics["by_fold"][fold_id],
                "candidate_minus_history": (
                    candidate_metrics["by_fold"][fold_id]
                    - history_metrics["by_fold"][fold_id]
                ),
                "skill": skill,
                "candidate_improves": skill > 0,
            }
        )
    _write_csv(fold_rows, output_root / "fold_skill.csv")

    gate_rows = [
        {"gate": gate_name, "passed": passed}
        for gate_name, passed in gate["conditions"].items()
    ]
    _write_csv(gate_rows, output_root / "gate_summary.csv")

    control_rows = []
    controls = result["comparisons_to_action_model"]["controls"]
    candidate_score = candidate_metrics[
        "primary_equal_event_macro_pre_action_normalized_mae"
    ]
    for control_id, comparison in controls.items():
        control_score = result["metrics"][control_id][
            "primary_equal_event_macro_pre_action_normalized_mae"
        ]
        control_rows.append(
            {
                "control_id": control_id,
                "control_label": MODEL_LABELS[control_id],
                "candidate_error": candidate_score,
                "control_error": control_score,
                "candidate_minus_control": comparison[
                    "candidate_minus_baseline_equal_event"
                ],
                "bootstrap_ci_low": comparison[
                    "bootstrap_95_percentile_interval"
                ][0],
                "bootstrap_ci_high": comparison[
                    "bootstrap_95_percentile_interval"
                ][1],
                "candidate_better": comparison[
                    "candidate_minus_baseline_equal_event"
                ]
                < 0,
                "candidate_fold_wins": gate["control_fold_wins"][control_id],
            }
        )
    control_rows.sort(key=lambda row: row["control_error"])
    _write_csv(control_rows, output_root / "action_controls.csv")

    history_comparison = result["comparisons_to_action_model"][HISTORY_ID]
    decomposition_rows = []
    for dimension, values in (
        ("event", history_comparison["by_fold"]),
        ("target", history_comparison["by_target_equal_event"]),
        ("horizon", history_comparison["by_horizon_equal_event"]),
        ("event_target", history_comparison["by_fold_target"]),
    ):
        for key, delta in values.items():
            decomposition_rows.append(
                {
                    "dimension": dimension,
                    "key": key,
                    "candidate_minus_history": delta,
                    "candidate_better": delta < 0,
                }
            )
    _write_csv(decomposition_rows, output_root / "error_decomposition.csv")

    bundle = runtime["contracts"]["EventWeekBundle"]
    support_rows = [
        {"quantity": "independent_action_events", "value": bundle["event_count"]},
        {"quantity": "training_actions_per_fold", "value": bundle["event_count"] - 1},
        {"quantity": "zones_per_event", "value": bundle["zones"]},
        {"quantity": "weeks_per_event", "value": bundle["pre_action_weeks"] + bundle["post_action_weeks"]},
        {"quantity": "rows_per_event", "value": bundle["rows_per_event"]},
        {"quantity": "total_zone_week_rows", "value": bundle["rows_per_event"] * bundle["event_count"]},
    ]
    _write_csv(support_rows, output_root / "support_units.csv")

    summary = {
        "schema": "uwm.nyc_action_transfer_paper_evidence.v1",
        "source_result_status": result["status"],
        "completion_status": completion["status"],
        "model_count": len(score_rows),
        "event_count": len(fold_rows),
        "control_count": len(control_rows),
        "gate_count": len(gate_rows),
        "passed_gate_count": sum(row["passed"] for row in gate_rows),
        "candidate_primary_error": candidate_score,
        "history_primary_error": history_metrics[
            "primary_equal_event_macro_pre_action_normalized_mae"
        ],
        "spatial_ar_primary_error": result["metrics"][
            "fixed_adjacency_spatial_ar"
        ]["primary_equal_event_macro_pre_action_normalized_mae"],
        "mean_fold_skill": gate["mean_fold_skill"],
        "fold_improvement_count": gate["fold_improvement_count"],
        "best_submission": score_rows[0]["model_id"],
        "all_inventory_hashes_match": all(
            row["hash_matches"] for row in inventory_rows
        ),
        "claim_boundary": result["claim_boundary"],
    }
    _write_json(summary, output_root / "frozen_evidence_summary.json")
    return summary

