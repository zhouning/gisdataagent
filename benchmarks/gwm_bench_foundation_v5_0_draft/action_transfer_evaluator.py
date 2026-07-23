#!/usr/bin/env python3
"""Frozen multi-fold evaluator for GWM-Bench Foundation V5 ACTION-TRANSFER."""

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
DEFAULT_RUNTIME = DRAFT_ROOT / "runtime_r4_contract.json"
DEFAULT_OUTPUT = DRAFT_ROOT / "final_results/action_transfer_results.json"
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
REPORT_HORIZONS = [1, 2, 4, 8, 12]
CANDIDATE_ID = "uwm_dam_gk_action_residual"
HISTORY_BASELINE_ID = "history_ar_backbone"


class SubmissionError(ValueError):
    """Raised when a prediction or commitment violates the frozen contract."""


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


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def normalized_keys(frame: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    if "fold_id" in key_columns:
        if result["fold_id"].isna().any():
            raise SubmissionError("null fold_id")
        result["fold_id"] = result["fold_id"].astype(str)
    for column in ("zone_id", "horizon_week"):
        if column not in key_columns:
            continue
        values = pd.to_numeric(result[column], errors="raise").to_numpy(dtype=np.float64)
        if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
            raise SubmissionError(f"non-integral submission key: {column}")
        result[column] = values.astype(np.int64)
    return result


def validate_submission(
    submission: pd.DataFrame,
    expected_keys: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    key_columns = contract["key_columns"]
    prediction_columns = contract["prediction_columns"]
    optional_columns = contract["optional_uncertainty_columns"]
    required = [*key_columns, *prediction_columns]
    missing_columns = [column for column in required if column not in submission.columns]
    if missing_columns:
        raise SubmissionError(f"missing columns: {missing_columns}")
    present_optional = [column for column in optional_columns if column in submission.columns]
    if present_optional and len(present_optional) != len(optional_columns):
        raise SubmissionError("uncertainty columns must be omitted or submitted as a complete set")
    allowed = set(required + present_optional)
    extra_columns = sorted(set(submission.columns) - allowed)
    if extra_columns:
        raise SubmissionError(f"unexpected columns: {extra_columns}")
    frame = normalized_keys(submission[required + present_optional], key_columns)
    frozen_keys = normalized_keys(expected_keys[key_columns], key_columns)
    if len(frame) != contract["expected_key_count"]:
        raise SubmissionError(
            f"expected {contract['expected_key_count']} rows, found {len(frame)}"
        )
    if frame.duplicated(key_columns).any():
        raise SubmissionError("duplicate submission keys")
    actual_keys = frame[key_columns].sort_values(key_columns).reset_index(drop=True)
    frozen_keys = frozen_keys.sort_values(key_columns).reset_index(drop=True)
    if not actual_keys.equals(frozen_keys):
        raise SubmissionError("missing or extra submission keys")
    if sorted(frame["fold_id"].unique().tolist()) != sorted(contract["expected_fold_ids"]):
        raise SubmissionError("unexpected fold IDs")
    if not frame.groupby("fold_id", observed=True).size().eq(
        contract["expected_key_count_per_fold"]
    ).all():
        raise SubmissionError("wrong key count in at least one fold")
    predictions = frame[prediction_columns].to_numpy(dtype=np.float64)
    if not np.isfinite(predictions).all():
        raise SubmissionError("non-finite prediction")
    if (predictions < 0).any():
        raise SubmissionError("negative prediction")
    if present_optional:
        uncertainty = frame[optional_columns].to_numpy(dtype=np.float64)
        if not np.isfinite(uncertainty).all() or (uncertainty < 0).any():
            raise SubmissionError("invalid uncertainty value")
        for target in TARGETS:
            lower = frame[f"{target}_p10"].to_numpy(dtype=float)
            point = frame[f"{target}_prediction"].to_numpy(dtype=float)
            upper = frame[f"{target}_p90"].to_numpy(dtype=float)
            if ((lower > point) | (point > upper)).any():
                raise SubmissionError(f"uncertainty order violation for {target}")
    return frame.sort_values(key_columns).reset_index(drop=True)


def load_fold_inputs(
    runtime_contract: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    all_keys: list[pd.DataFrame] = []
    histories: dict[str, pd.DataFrame] = {}
    all_targets: list[pd.DataFrame] = []
    hashes: dict[str, Any] = {}
    firewall = runtime_contract["contracts"]["OuterFoldFirewall"]
    for fold in runtime_contract["outer_folds"]:
        fold_id = fold["fold_id"]
        root = resolve_path(fold["fold_root"])
        history_path = root / firewall["history_relative_path"]
        keys_path = root / firewall["submission_keys_relative_path"]
        targets_path = root / firewall["targets_relative_path"]
        history = pd.read_parquet(history_path)
        keys = pd.read_parquet(keys_path)
        targets = pd.read_parquet(targets_path)
        keys.insert(0, "fold_id", fold_id)
        targets.insert(0, "fold_id", fold_id)
        histories[fold_id] = history
        all_keys.append(keys)
        all_targets.append(targets)
        hashes[fold_id] = {
            "history": artifact(history_path),
            "keys": artifact(keys_path),
            "targets": artifact(targets_path),
        }
    return (
        pd.concat(all_keys, ignore_index=True),
        histories,
        pd.concat(all_targets, ignore_index=True),
        hashes,
    )


def normalized_error_frame(
    submission: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    targets: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for fold_id, history in histories.items():
        scales = history.groupby("zone_id", observed=True)[TARGETS].mean().clip(lower=1.0)
        fold_targets = targets.loc[targets["fold_id"].eq(fold_id)]
        fold_submission = submission.loc[submission["fold_id"].eq(fold_id)]
        joined = fold_targets.merge(
            fold_submission,
            on=["fold_id", "zone_id", "horizon_week"],
            validate="one_to_one",
        )
        for target in TARGETS:
            scale = joined["zone_id"].map(scales[target]).to_numpy(dtype=float)
            prediction = joined[f"{target}_prediction"].to_numpy(dtype=float)
            observation = joined[target].to_numpy(dtype=float)
            rows.append(
                pd.DataFrame(
                    {
                        "fold_id": fold_id,
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
    histories: dict[str, pd.DataFrame],
    targets: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    errors = normalized_error_frame(submission, histories, targets)
    primary_rows = errors.loc[errors["horizon_week"].isin(REPORT_HORIZONS)]
    fold_scores = primary_rows.groupby("fold_id", observed=True)[
        "normalized_abs_error"
    ].mean()
    fold_target_scores = primary_rows.groupby(["fold_id", "target"], observed=True)[
        "normalized_abs_error"
    ].mean()
    fold_horizon_scores = primary_rows.groupby(
        ["fold_id", "horizon_week"], observed=True
    )["normalized_abs_error"].mean()
    by_target = fold_target_scores.groupby("target", observed=True).mean()
    by_horizon = fold_horizon_scores.groupby("horizon_week", observed=True).mean()
    metrics: dict[str, Any] = {
        "primary_equal_event_macro_pre_action_normalized_mae": float(fold_scores.mean()),
        "reported_horizons": REPORT_HORIZONS,
        "by_fold": {key: float(value) for key, value in fold_scores.items()},
        "by_target_equal_event": {key: float(value) for key, value in by_target.items()},
        "by_horizon_equal_event": {
            str(int(key)): float(value) for key, value in by_horizon.items()
        },
        "by_fold_target": {
            f"{fold_id}|{target}": float(value)
            for (fold_id, target), value in fold_target_scores.items()
        },
    }
    system_totals: dict[str, Any] = {}
    for (fold_id, target, horizon), group in errors.groupby(
        ["fold_id", "target", "horizon_week"], observed=True
    ):
        observed_total = float(group["observation"].sum())
        predicted_total = float(group["prediction"].sum())
        system_totals[f"{fold_id}|{target}|{int(horizon)}"] = abs(
            predicted_total - observed_total
        ) / max(abs(observed_total), 1.0)
    metrics["system_total_absolute_percentage_error"] = system_totals
    if all(f"{target}_p10" in submission.columns for target in TARGETS):
        joined = targets.merge(
            submission,
            on=["fold_id", "zone_id", "horizon_week"],
            validate="one_to_one",
        )
        coverage: dict[str, float] = {}
        for target in TARGETS:
            fold_coverage = joined.assign(
                covered=joined[target].between(
                    joined[f"{target}_p10"], joined[f"{target}_p90"]
                )
            ).groupby("fold_id", observed=True)["covered"].mean()
            coverage[target] = float(fold_coverage.mean())
        metrics["interval_80_coverage_equal_event"] = coverage
    return metrics, errors


def paired_comparison(
    candidate_errors: pd.DataFrame,
    baseline_errors: pd.DataFrame,
    *,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    keys = ["fold_id", "zone_id", "horizon_week", "target"]
    left = candidate_errors.loc[
        candidate_errors["horizon_week"].isin(REPORT_HORIZONS),
        keys + ["normalized_abs_error"],
    ]
    right = baseline_errors.loc[
        baseline_errors["horizon_week"].isin(REPORT_HORIZONS),
        keys + ["normalized_abs_error"],
    ]
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
    fold_zone = merged.groupby(["fold_id", "zone_id"], observed=True)["difference"].mean()
    by_fold = fold_zone.groupby("fold_id", observed=True).mean()
    rng = np.random.default_rng(seed)
    bootstrap = np.zeros(draws, dtype=np.float64)
    fold_ids = sorted(merged["fold_id"].unique().tolist())
    for fold_id in fold_ids:
        values = fold_zone.loc[fold_id].sort_index().to_numpy(dtype=float)
        indices = rng.integers(0, len(values), size=(draws, len(values)))
        bootstrap += values[indices].mean(axis=1) / len(fold_ids)
    fold_target = merged.groupby(["fold_id", "target"], observed=True)["difference"].mean()
    fold_horizon = merged.groupby(["fold_id", "horizon_week"], observed=True)[
        "difference"
    ].mean()
    return {
        "candidate_minus_baseline_equal_event": float(by_fold.mean()),
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
        "bootstrap_95_percentile_interval": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
        "by_fold": {key: float(value) for key, value in by_fold.items()},
        "by_target_equal_event": {
            key: float(value)
            for key, value in fold_target.groupby("target", observed=True).mean().items()
        },
        "by_horizon_equal_event": {
            str(int(key)): float(value)
            for key, value in fold_horizon.groupby("horizon_week", observed=True).mean().items()
        },
        "by_fold_target": {
            f"{fold_id}|{target}": float(value)
            for (fold_id, target), value in fold_target.items()
        },
    }


def action_transfer_decision(
    metrics: dict[str, dict[str, Any]],
    errors: dict[str, pd.DataFrame],
    protocol: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    comparison_spec = protocol["evaluation"]["paired_bootstrap"]
    candidate_metrics = metrics[CANDIDATE_ID]
    history_metrics = metrics[HISTORY_BASELINE_ID]
    candidate_by_fold = candidate_metrics["by_fold"]
    history_by_fold = history_metrics["by_fold"]
    fold_skill = {
        fold_id: 1.0 - candidate_by_fold[fold_id] / history_by_fold[fold_id]
        if history_by_fold[fold_id] > 0
        else float("nan")
        for fold_id in sorted(history_by_fold)
    }
    history_comparison = paired_comparison(
        errors[CANDIDATE_ID],
        errors[HISTORY_BASELINE_ID],
        draws=int(comparison_spec["draws"]),
        seed=int(comparison_spec["seed"]),
    )
    control_ids = protocol["required_controls"]
    control_comparisons = {
        control_id: paired_comparison(
            errors[CANDIDATE_ID],
            errors[control_id],
            draws=int(comparison_spec["draws"]),
            seed=int(comparison_spec["seed"]),
        )
        for control_id in control_ids
    }
    fold_improvement_count = sum(value > 0 for value in fold_skill.values())
    fold_target_improvement_count = sum(
        candidate_metrics["by_fold_target"][key] < history_metrics["by_fold_target"][key]
        for key in history_metrics["by_fold_target"]
    )
    horizon_improvement_count = sum(
        candidate_metrics["by_horizon_equal_event"][key]
        < history_metrics["by_horizon_equal_event"][key]
        for key in history_metrics["by_horizon_equal_event"]
    )
    control_fold_wins = {
        control_id: sum(value < 0 for value in comparison["by_fold"].values())
        for control_id, comparison in control_comparisons.items()
    }
    candidate_primary = candidate_metrics[
        "primary_equal_event_macro_pre_action_normalized_mae"
    ]
    conditions = {
        "mean_fold_skill_at_least_one_percent": np.isfinite(list(fold_skill.values())).all()
        and float(np.mean(list(fold_skill.values())))
        >= protocol["evaluation"]["minimum_practical_mean_skill"],
        "paired_bootstrap_interval_entirely_below_zero": history_comparison[
            "bootstrap_95_percentile_interval"
        ][1]
        < 0,
        "at_least_three_of_four_events_improve": fold_improvement_count >= 3,
        "no_fold_degrades_more_than_two_percent": np.isfinite(list(fold_skill.values())).all()
        and min(fold_skill.values())
        >= -protocol["evaluation"]["maximum_allowed_single_fold_relative_degradation"],
        "at_least_twelve_of_sixteen_event_target_pairs_improve": fold_target_improvement_count
        >= 12,
        "at_least_four_of_five_reported_horizons_improve": horizon_improvement_count >= 4,
        "correct_action_beats_every_frozen_control_equal_event": all(
            candidate_primary
            < metrics[control_id]["primary_equal_event_macro_pre_action_normalized_mae"]
            for control_id in control_ids
        ),
        "correct_action_beats_every_control_in_three_of_four_folds": all(
            wins >= 3 for wins in control_fold_wins.values()
        ),
    }
    conditions = {key: bool(value) for key, value in conditions.items()}
    gate = {
        "conditions": conditions,
        "all_required": True,
        "passed": all(conditions.values()),
        "fold_skill": {key: float(value) for key, value in fold_skill.items()},
        "mean_fold_skill": float(np.mean(list(fold_skill.values()))),
        "fold_improvement_count": fold_improvement_count,
        "event_target_improvement_count": fold_target_improvement_count,
        "horizon_improvement_count": horizon_improvement_count,
        "control_fold_wins": control_fold_wins,
    }
    comparisons = {
        "history_ar_backbone": history_comparison,
        "controls": control_comparisons,
    }
    return gate, comparisons


def verify_prediction_artifact(entry: dict[str, Any]) -> Path:
    if "prediction_artifact" not in entry:
        raise SubmissionError("commitment entry lacks prediction_artifact")
    expected = entry["prediction_artifact"]
    path = resolve_path(expected["path"])
    if not path.is_file():
        raise SubmissionError(f"missing committed prediction: {path}")
    if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
        raise SubmissionError(f"committed prediction changed: {path}")
    return path


def evaluate_manifest(
    commitment_path: Path,
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    runtime_path: Path = DEFAULT_RUNTIME,
) -> dict[str, Any]:
    protocol = load_json(protocol_path)
    contract = load_json(contract_path)
    runtime_contract = load_json(runtime_path)
    commitment = load_json(commitment_path)
    required_status = runtime_contract["contracts"]["MultiFoldPredictionCommitment"][
        "required_status"
    ]
    if commitment.get("status") != required_status:
        raise SubmissionError("formal evaluator cannot read targets before complete commitment")
    required_ids = [
        *runtime_contract["required_models"],
        *runtime_contract["required_controls"],
    ]
    entries = commitment.get("submissions", {})
    if set(entries) != set(required_ids):
        raise SubmissionError("commitment IDs do not exactly match the frozen runtime contract")

    expected_keys, histories, targets, fold_input_artifacts = load_fold_inputs(runtime_contract)
    metrics: dict[str, dict[str, Any]] = {}
    errors: dict[str, pd.DataFrame] = {}
    prediction_artifacts: dict[str, Any] = {}
    for model_id in required_ids:
        prediction_path = verify_prediction_artifact(entries[model_id])
        submission = validate_submission(
            pd.read_parquet(prediction_path), expected_keys, contract
        )
        model_metrics, model_errors = evaluate_submission(submission, histories, targets)
        metrics[model_id] = model_metrics
        errors[model_id] = model_errors
        prediction_artifacts[model_id] = artifact(prediction_path)
    gate, comparisons = action_transfer_decision(metrics, errors, protocol)
    return {
        "schema": "gwm_bench.foundation_v5_action_transfer_results.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTION_TRANSFER_SUPPORTED" if gate["passed"] else "ACTION_TRANSFER_NOT_SUPPORTED",
        "benchmark_completed": True,
        "protocol_sha256": sha256_file(protocol_path),
        "submission_contract_sha256": sha256_file(contract_path),
        "runtime_r4_contract_sha256": sha256_file(runtime_path),
        "prediction_commitment_sha256": sha256_file(commitment_path),
        "fold_input_artifacts": fold_input_artifacts,
        "prediction_artifacts": prediction_artifacts,
        "metrics": metrics,
        "comparisons_to_action_model": comparisons,
        "action_transfer_gate": gate,
        "claim_boundary": protocol["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-commitment", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate_manifest(args.prediction_commitment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V5.0 ACTION-TRANSFER: {report['status']}")
    print(f"Results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
