#!/usr/bin/env python3
"""Frozen evaluator implementation for the GWM Benchmark V4 ACTION-A4 track."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROTOCOL = DRAFT_ROOT / "suite_protocol.json"
DEFAULT_CONTRACT = DRAFT_ROOT / "submission_contract.json"
DEFAULT_HISTORY = DRAFT_ROOT / "rc1_bundle/test_input/weekly_state_history.parquet"
DEFAULT_KEYS = DRAFT_ROOT / "rc1_bundle/test_input/submission_keys.parquet"
DEFAULT_TARGETS = DRAFT_ROOT / "rc1_bundle/test_targets/weekly_targets.parquet"
DEFAULT_OUTPUT = DRAFT_ROOT / "final_results/action_a4_results.json"
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
REPORT_HORIZONS = [1, 2, 4, 8, 12]


class SubmissionError(ValueError):
    """Raised when a prediction submission violates the frozen contract."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def validate_submission(
    submission: pd.DataFrame,
    expected_keys: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    key_columns = contract["key_columns"]
    prediction_columns = contract["prediction_columns"]
    required = [*key_columns, *prediction_columns]
    missing_columns = [column for column in required if column not in submission.columns]
    if missing_columns:
        raise SubmissionError(f"missing columns: {missing_columns}")
    frame = submission[required + [
        column
        for column in contract["optional_uncertainty_columns"]
        if column in submission.columns
    ]].copy()
    if len(frame) != contract["expected_key_count"]:
        raise SubmissionError(
            f"expected {contract['expected_key_count']} rows, found {len(frame)}"
        )
    if frame.duplicated(key_columns).any():
        raise SubmissionError("duplicate submission keys")
    actual_keys = frame[key_columns].sort_values(key_columns).reset_index(drop=True)
    frozen_keys = expected_keys[key_columns].sort_values(key_columns).reset_index(drop=True)
    if not actual_keys.equals(frozen_keys):
        raise SubmissionError("missing or extra submission keys")
    predictions = frame[prediction_columns].to_numpy(dtype=np.float64)
    if not np.isfinite(predictions).all():
        raise SubmissionError("non-finite prediction")
    if (predictions < 0).any():
        raise SubmissionError("negative prediction")

    optional = contract["optional_uncertainty_columns"]
    present = [column for column in optional if column in frame.columns]
    if present and len(present) != len(optional):
        raise SubmissionError("uncertainty columns must be omitted or submitted as a complete set")
    if present:
        uncertainty = frame[optional].to_numpy(dtype=np.float64)
        if not np.isfinite(uncertainty).all() or (uncertainty < 0).any():
            raise SubmissionError("invalid uncertainty value")
        for target in TARGETS:
            lower = frame[f"{target}_p10"].to_numpy(dtype=float)
            point = frame[f"{target}_prediction"].to_numpy(dtype=float)
            upper = frame[f"{target}_p90"].to_numpy(dtype=float)
            if ((lower > point) | (point > upper)).any():
                raise SubmissionError(f"uncertainty order violation for {target}")
    return frame.sort_values(key_columns).reset_index(drop=True)


def normalized_error_frame(
    submission: pd.DataFrame,
    history: pd.DataFrame,
    targets: pd.DataFrame,
) -> pd.DataFrame:
    scales = history.groupby("zone_id", observed=True)[TARGETS].mean().clip(lower=1.0)
    joined = targets.merge(submission, on=["zone_id", "horizon_week"], validate="one_to_one")
    rows: list[pd.DataFrame] = []
    for target in TARGETS:
        scale = joined["zone_id"].map(scales[target]).to_numpy(dtype=float)
        prediction = joined[f"{target}_prediction"].to_numpy(dtype=float)
        observation = joined[target].to_numpy(dtype=float)
        rows.append(
            pd.DataFrame(
                {
                    "zone_id": joined["zone_id"].to_numpy(dtype=int),
                    "horizon_week": joined["horizon_week"].to_numpy(dtype=int),
                    "target": target,
                    "prediction": prediction,
                    "observation": observation,
                    "pre_event_scale": scale,
                    "normalized_abs_error": np.abs(prediction - observation) / scale,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def evaluate_submission(
    submission: pd.DataFrame,
    history: pd.DataFrame,
    targets: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    errors = normalized_error_frame(submission, history, targets)
    primary_rows = errors.loc[errors["horizon_week"].isin(REPORT_HORIZONS)]
    primary = float(primary_rows["normalized_abs_error"].mean())
    by_target = {
        key: float(value)
        for key, value in primary_rows.groupby("target", observed=True)[
            "normalized_abs_error"
        ].mean().items()
    }
    by_horizon = {
        str(int(key)): float(value)
        for key, value in primary_rows.groupby("horizon_week", observed=True)[
            "normalized_abs_error"
        ].mean().items()
    }
    system_total_ape: dict[str, dict[str, float]] = {}
    for target in TARGETS:
        target_rows = errors.loc[errors["target"].eq(target)]
        system_total_ape[target] = {}
        for horizon, group in target_rows.groupby("horizon_week", observed=True):
            observed_total = float(group["observation"].sum())
            predicted_total = float(group["prediction"].sum())
            denominator = max(abs(observed_total), 1.0)
            system_total_ape[target][str(int(horizon))] = abs(
                predicted_total - observed_total
            ) / denominator
    metrics: dict[str, Any] = {
        "primary_macro_pre_event_normalized_mae": primary,
        "reported_horizons": REPORT_HORIZONS,
        "by_target": by_target,
        "by_horizon": by_horizon,
        "system_total_absolute_percentage_error": system_total_ape,
    }
    optional_present = all(f"{target}_p10" in submission.columns for target in TARGETS)
    if optional_present:
        coverage: dict[str, float] = {}
        joined = targets.merge(submission, on=["zone_id", "horizon_week"], validate="one_to_one")
        for target in TARGETS:
            covered = joined[target].between(
                joined[f"{target}_p10"], joined[f"{target}_p90"]
            )
            coverage[target] = float(covered.mean())
        metrics["interval_80_coverage"] = coverage
    return metrics, errors


def paired_comparison(
    candidate_errors: pd.DataFrame,
    baseline_errors: pd.DataFrame,
    *,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    keys = ["zone_id", "horizon_week", "target"]
    left = candidate_errors.loc[candidate_errors["horizon_week"].isin(REPORT_HORIZONS), keys + ["normalized_abs_error"]]
    right = baseline_errors.loc[baseline_errors["horizon_week"].isin(REPORT_HORIZONS), keys + ["normalized_abs_error"]]
    merged = left.merge(
        right,
        on=keys,
        suffixes=("_candidate", "_baseline"),
        validate="one_to_one",
    )
    merged["difference"] = (
        merged["normalized_abs_error_candidate"]
        - merged["normalized_abs_error_baseline"]
    )
    zone_difference = merged.groupby("zone_id", observed=True)["difference"].mean().sort_index()
    values = zone_difference.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(draws, len(values)))
    bootstrap = values[indices].mean(axis=1)
    by_target = {
        key: float(value)
        for key, value in merged.groupby("target", observed=True)["difference"].mean().items()
    }
    by_horizon = {
        str(int(key)): float(value)
        for key, value in merged.groupby("horizon_week", observed=True)["difference"].mean().items()
    }
    return {
        "candidate_minus_baseline": float(values.mean()),
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
        "bootstrap_95_percentile_interval": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
        "by_target": by_target,
        "by_horizon": by_horizon,
    }


def evaluate_manifest(
    submission_manifest_path: Path,
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    history_path: Path = DEFAULT_HISTORY,
    keys_path: Path = DEFAULT_KEYS,
    targets_path: Path = DEFAULT_TARGETS,
) -> dict[str, Any]:
    protocol = load_json(protocol_path)
    contract = load_json(contract_path)
    submission_manifest = load_json(submission_manifest_path)
    history = pd.read_parquet(history_path)
    expected_keys = pd.read_parquet(keys_path)
    targets = pd.read_parquet(targets_path)
    required_ids = [
        *load_json(DRAFT_ROOT / "runtime_r3_contract.json")["required_models"],
        *load_json(DRAFT_ROOT / "runtime_r3_contract.json")["required_controls"],
    ]
    entries = submission_manifest["submissions"]
    missing_ids = [model_id for model_id in required_ids if model_id not in entries]
    if missing_ids:
        raise SubmissionError(f"submission manifest missing required IDs: {missing_ids}")

    metrics: dict[str, Any] = {}
    errors: dict[str, pd.DataFrame] = {}
    artifacts: dict[str, Any] = {}
    for model_id in required_ids:
        path = resolve_path(entries[model_id]["prediction_path"])
        submission = validate_submission(pd.read_parquet(path), expected_keys, contract)
        model_metrics, model_errors = evaluate_submission(submission, history, targets)
        metrics[model_id] = model_metrics
        errors[model_id] = model_errors
        artifacts[model_id] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    comparison_spec = protocol["evaluation"]["paired_comparison"]
    comparisons = {
        baseline_id: paired_comparison(
            errors["uwm_dam_gk_action"],
            errors[baseline_id],
            draws=int(comparison_spec["draws"]),
            seed=int(comparison_spec["seed"]),
        )
        for baseline_id in required_ids
        if baseline_id != "uwm_dam_gk_action"
    }
    no_action = comparisons["dam_gk_no_action"]
    target_win_count = sum(value < 0 for value in no_action["by_target"].values())
    horizon_win_count = sum(value < 0 for value in no_action["by_horizon"].values())
    action_primary = metrics["uwm_dam_gk_action"][
        "primary_macro_pre_event_normalized_mae"
    ]
    conditions = {
        "action_better_than_matched_no_action": no_action["candidate_minus_baseline"] < 0,
        "paired_interval_entirely_below_zero": no_action[
            "bootstrap_95_percentile_interval"
        ][1]
        < 0,
        "at_least_three_of_four_targets_improve": target_win_count >= 3,
        "at_least_four_of_five_reported_horizons_improve": horizon_win_count >= 4,
        "correct_action_beats_component_permutation": action_primary
        < metrics["action_component_permutation"][
            "primary_macro_pre_event_normalized_mae"
        ],
        "correct_action_beats_cbd_scope_rewire": action_primary
        < metrics["cbd_scope_rewire"]["primary_macro_pre_event_normalized_mae"],
    }
    conditions = {key: bool(value) for key, value in conditions.items()}
    return {
        "schema": "gwm_bench.foundation_v4_action_a4_results.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTION_TRANSFER_SUPPORTED" if all(conditions.values()) else "ACTION_TRANSFER_NOT_SUPPORTED",
        "benchmark_completed": True,
        "protocol_sha256": sha256_file(protocol_path),
        "submission_contract_sha256": sha256_file(contract_path),
        "submission_manifest_sha256": sha256_file(submission_manifest_path),
        "history_sha256": sha256_file(history_path),
        "keys_sha256": sha256_file(keys_path),
        "targets_sha256": sha256_file(targets_path),
        "prediction_artifacts": artifacts,
        "metrics": metrics,
        "comparisons_to_action_model": comparisons,
        "action_transfer_gate": {
            "conditions": conditions,
            "target_improvement_count": target_win_count,
            "horizon_improvement_count": horizon_win_count,
            "all_required": True,
            "passed": all(conditions.values()),
        },
        "claim_boundary": protocol["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate_manifest(args.submission_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0 ACTION-A4: {report['status']}")
    print(f"Results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
