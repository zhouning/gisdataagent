"""Non-retuned sensitivity diagnostics for the frozen NYC V5 predictions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
REPORT_HORIZONS = [1, 2, 4, 8, 12]
MODEL_IDS = [
    "history_ar_backbone",
    "fixed_adjacency_spatial_ar",
    "dam_gk_residual_no_action",
    "uwm_dam_gk_action_residual",
]
CANDIDATE_ID = "uwm_dam_gk_action_residual"
HISTORY_ID = "history_ar_backbone"
SPATIAL_ID = "fixed_adjacency_spatial_ar"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_targets(benchmark_root: Path) -> pd.DataFrame:
    frames = []
    folds_root = benchmark_root / "rc1_bundle/folds"
    for fold_root in sorted(folds_root.glob("holdout_*")):
        frame = pd.read_parquet(fold_root / "test_targets/weekly_targets.parquet")
        frame.insert(0, "fold_id", fold_root.name)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _load_scales(benchmark_root: Path) -> pd.DataFrame:
    frames = []
    folds_root = benchmark_root / "rc1_bundle/folds"
    for fold_root in sorted(folds_root.glob("holdout_*")):
        history = pd.read_parquet(
            fold_root / "test_input/weekly_state_history.parquet"
        )
        scales = history.groupby("zone_id", observed=True)[TARGETS].mean()
        scales = scales.rename(columns={target: f"{target}_scale" for target in TARGETS})
        scales.insert(0, "fold_id", fold_root.name)
        frames.append(scales.reset_index())
    return pd.concat(frames, ignore_index=True)


def _error_frame(
    predictions: pd.DataFrame, targets: pd.DataFrame, scales: pd.DataFrame
) -> pd.DataFrame:
    joined = targets.merge(
        predictions,
        on=["fold_id", "zone_id", "horizon_week"],
        validate="one_to_one",
    ).merge(scales, on=["fold_id", "zone_id"], validate="many_to_one")
    rows = []
    for target in TARGETS:
        observation = joined[target].to_numpy(dtype=float)
        prediction = joined[f"{target}_prediction"].to_numpy(dtype=float)
        scale = joined[f"{target}_scale"].to_numpy(dtype=float)
        rows.append(
            pd.DataFrame(
                {
                    "fold_id": joined["fold_id"],
                    "zone_id": joined["zone_id"],
                    "horizon_week": joined["horizon_week"],
                    "target": target,
                    "observation": observation,
                    "prediction": prediction,
                    "pre_event_scale_raw": scale,
                    "pre_event_scale": np.maximum(scale, 1.0),
                    "absolute_error": np.abs(prediction - observation),
                    "normalized_abs_error": (
                        np.abs(prediction - observation) / np.maximum(scale, 1.0)
                    ),
                    "log1p_abs_error": np.abs(
                        np.log1p(np.maximum(prediction, 0.0))
                        - np.log1p(np.maximum(observation, 0.0))
                    ),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _equal_event_mean(frame: pd.DataFrame, column: str) -> float:
    return float(frame.groupby("fold_id", observed=True)[column].mean().mean())


def _equal_event_median(frame: pd.DataFrame, column: str) -> float:
    return float(frame.groupby("fold_id", observed=True)[column].median().mean())


def _equal_event_wape(frame: pd.DataFrame) -> float:
    by_fold = frame.groupby("fold_id", observed=True).apply(
        lambda group: group["absolute_error"].sum()
        / max(float(group["observation"].abs().sum()), 1.0),
        include_groups=False,
    )
    return float(by_fold.mean())


Metric = tuple[str, Callable[[pd.DataFrame], float]]


def build_metric_sensitivity(repo_root: Path, output_root: Path) -> dict[str, Any]:
    """Evaluate fixed alternative metrics without changing any V5 prediction."""

    benchmark_root = repo_root / "benchmarks/gwm_bench_foundation_v5_0_draft"
    output_root.mkdir(parents=True, exist_ok=True)
    targets = _load_targets(benchmark_root)
    scales = _load_scales(benchmark_root)
    result = _load_json(benchmark_root / "final_results/action_transfer_results.json")

    metrics: list[Metric] = [
        (
            "equal_event_normalized_mae",
            lambda frame: _equal_event_mean(frame, "normalized_abs_error"),
        ),
        (
            "equal_event_median_normalized_ae",
            lambda frame: _equal_event_median(frame, "normalized_abs_error"),
        ),
        (
            "equal_event_log1p_mae",
            lambda frame: _equal_event_mean(frame, "log1p_abs_error"),
        ),
        ("equal_event_wape", _equal_event_wape),
    ]
    specifications = [
        {
            "specification": "reported_horizons_all_zones",
            "horizons": REPORT_HORIZONS,
            "minimum_pre_event_scale": None,
            "metrics": metrics,
        },
        {
            "specification": "all_12_horizons_all_zones",
            "horizons": list(range(1, 13)),
            "minimum_pre_event_scale": None,
            "metrics": [metrics[0]],
        },
        *[
            {
                "specification": f"reported_horizons_scale_at_least_{threshold}",
                "horizons": REPORT_HORIZONS,
                "minimum_pre_event_scale": threshold,
                "metrics": [metrics[0]],
            }
            for threshold in (10, 100)
        ],
    ]

    score_rows = []
    for model_id in MODEL_IDS:
        predictions = pd.read_parquet(
            benchmark_root / f"predictions/{model_id}/prediction.parquet"
        )
        errors = _error_frame(predictions, targets, scales)
        for spec in specifications:
            selected = errors.loc[errors["horizon_week"].isin(spec["horizons"])].copy()
            threshold = spec["minimum_pre_event_scale"]
            if threshold is not None:
                selected = selected.loc[selected["pre_event_scale_raw"].ge(threshold)]
            for metric_id, metric_fn in spec["metrics"]:
                score_rows.append(
                    {
                        "specification": spec["specification"],
                        "metric_id": metric_id,
                        "model_id": model_id,
                        "score": metric_fn(selected),
                        "row_count": len(selected),
                    }
                )

    scores = pd.DataFrame(score_rows)
    scores.to_csv(output_root / "metric_sensitivity_scores.csv", index=False)

    horizon_rows = []
    target_rows = []
    for model_id in MODEL_IDS:
        predictions = pd.read_parquet(
            benchmark_root / f"predictions/{model_id}/prediction.parquet"
        )
        errors = _error_frame(predictions, targets, scales)
        for horizon in range(1, 13):
            selected = errors.loc[errors["horizon_week"].eq(horizon)]
            horizon_rows.append(
                {
                    "model_id": model_id,
                    "horizon_week": horizon,
                    "equal_event_normalized_mae": _equal_event_mean(
                        selected, "normalized_abs_error"
                    ),
                }
            )
        reported = errors.loc[errors["horizon_week"].isin(REPORT_HORIZONS)]
        for target in TARGETS:
            selected = reported.loc[reported["target"].eq(target)]
            target_rows.append(
                {
                    "model_id": model_id,
                    "target": target,
                    "equal_event_normalized_mae": _equal_event_mean(
                        selected, "normalized_abs_error"
                    ),
                }
            )
    pd.DataFrame(horizon_rows).to_csv(
        output_root / "horizon_profile.csv", index=False
    )
    pd.DataFrame(target_rows).to_csv(output_root / "target_profile.csv", index=False)

    contrast_rows = []
    for (specification, metric_id), group in scores.groupby(
        ["specification", "metric_id"], observed=True
    ):
        indexed = group.set_index("model_id")["score"]
        candidate = float(indexed[CANDIDATE_ID])
        history = float(indexed[HISTORY_ID])
        spatial = float(indexed[SPATIAL_ID])
        contrast_rows.append(
            {
                "specification": specification,
                "metric_id": metric_id,
                "candidate_score": candidate,
                "history_score": history,
                "spatial_ar_score": spatial,
                "candidate_minus_history": candidate - history,
                "candidate_minus_spatial_ar": candidate - spatial,
                "candidate_beats_history": candidate < history,
                "candidate_beats_spatial_ar": candidate < spatial,
            }
        )
    contrasts = pd.DataFrame(contrast_rows)
    contrasts.to_csv(output_root / "metric_sensitivity_contrasts.csv", index=False)

    formal_row = scores.loc[
        scores["specification"].eq("reported_horizons_all_zones")
        & scores["metric_id"].eq("equal_event_normalized_mae")
        & scores["model_id"].eq(CANDIDATE_ID)
    ].iloc[0]
    formal_expected = result["metrics"][CANDIDATE_ID][
        "primary_equal_event_macro_pre_action_normalized_mae"
    ]
    formal_reproduced = bool(np.isclose(formal_row["score"], formal_expected))
    if not formal_reproduced:
        raise ValueError("Sensitivity implementation does not reproduce V5 primary score")

    uncertainty_audit = {
        "schema": "uwm.nyc_action_transfer_uncertainty_readiness.v1",
        "score_bootstrap_uncertainty_ready": True,
        "score_bootstrap_draws": result["comparisons_to_action_model"][HISTORY_ID][
            "bootstrap_draws"
        ],
        "calibrated_prediction_interval_ready": False,
        "reason": (
            "V5 stores scalar inner-fold validation metrics but not residual-level "
            "cross-fitted training-action predictions. Three seed predictions on "
            "the held-out actions measure ensemble spread and cannot be calibrated "
            "with the same held-out targets without leakage."
        ),
        "ensemble_spread_must_not_be_called_calibrated_interval": True,
        "paper_action": (
            "Report paired bootstrap uncertainty for score differences and state "
            "that calibrated predictive intervals are unavailable in V5."
        ),
    }
    _write_json(uncertainty_audit, output_root / "uncertainty_readiness.json")

    summary = {
        "schema": "uwm.nyc_action_transfer_metric_sensitivity.v1",
        "formal_metric_reproduced": formal_reproduced,
        "specification_count": len(contrasts),
        "candidate_beats_history_count": int(contrasts["candidate_beats_history"].sum()),
        "candidate_beats_spatial_ar_count": int(
            contrasts["candidate_beats_spatial_ar"].sum()
        ),
        "candidate_fails_to_beat_history_count": int(
            (~contrasts["candidate_beats_history"]).sum()
        ),
        "candidate_fails_to_beat_spatial_ar_count": int(
            (~contrasts["candidate_beats_spatial_ar"]).sum()
        ),
        "calibrated_prediction_interval_ready": False,
    }
    _write_json(summary, output_root / "metric_sensitivity_summary.json")
    return summary
