#!/usr/bin/env python3
"""Train an event-cross-validated Sentinel-2 observation operator.

The operator predicts satellite-visible *new surface water* from summaries of
the coupled-model depth trajectory.  It does not alter GWM dynamics and is not
an external-confirmation experiment: all events in this dataset are exposed
development events.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter, uniform_filter
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


WORKSPACE = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821"
)
DEFAULT_DEVELOPMENT_ROOT = WORKSPACE / "customer_gwm_observation_operator_development_20260917_v1"
DEFAULT_OBSERVATIONS = DEFAULT_DEVELOPMENT_ROOT / "observations"
DEFAULT_LABEL_ROOT = WORKSPACE / "customer_city_swmm_2d_coupled_labels_20260914_r1"
DEFAULT_OUTPUT = DEFAULT_DEVELOPMENT_ROOT / "operator_v1"
SCHEMA = "gwm.abu_dhabi_flood.sentinel2_observation_operator.v1"
WET_DEPTH_THRESHOLD_M = 0.01
MINIMUM_VALID_FRACTION = 0.70
MINIMUM_OBSERVED_FRACTION = 0.02
LOGISTIC_C = 1.0
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260917
PROBABILITY_THRESHOLDS = tuple(float(value) for value in np.geomspace(0.002, 0.2, 41))
FEATURE_NAMES = (
    "log1p_peak_depth_cm",
    "log1p_end_depth_cm",
    "log1p_mean_depth_cm",
    "wet_duration_fraction",
    "post_event_lag_days",
    "post_event_lag_days_squared",
    "log1p_lag_decayed_peak_depth_cm",
    "neighbor_log1p_peak_mean_cm",
    "neighbor_log1p_peak_max_cm",
    "neighbor_wet_duration_mean",
    "neighborhood_500m_log1p_peak_max_cm",
    "neighborhood_1000m_log1p_peak_max_cm",
    "neighborhood_1000m_log1p_peak_mean_cm",
    "neighborhood_500m_peak_wet_fraction",
    "neighborhood_1000m_peak_wet_fraction",
)
FEATURE_SETS = {
    "local_operator": FEATURE_NAMES[:7],
    "neighborhood_operator": FEATURE_NAMES[:10],
    "multiscale_neighborhood_operator": FEATURE_NAMES,
}


@dataclass(frozen=True)
class EventData:
    event_id: str
    cohort_role: str
    shape: tuple[int, int]
    eligible: np.ndarray
    target: np.ndarray
    features: np.ndarray
    peak_prediction: np.ndarray
    end_prediction: np.ndarray


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def neighbor_mean(values: np.ndarray, land: np.ndarray, *, size: int = 3) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    if values.shape != land.shape or values.ndim != 2:
        raise ValueError("observation_operator_neighbor_shape_invalid")
    if size <= 0 or size % 2 == 0:
        raise ValueError("observation_operator_neighbor_size_invalid")
    area = float(size * size)
    summed = uniform_filter(np.where(land, values, 0.0), size=size, mode="constant") * area
    count = uniform_filter(land.astype(np.float64), size=size, mode="constant") * area
    return np.divide(summed, count, out=np.zeros_like(summed), where=count > 0)


def event_balanced_weights(targets: list[np.ndarray]) -> list[np.ndarray]:
    total = sum(len(target) for target in targets)
    event_mass = total / len(targets)
    weights: list[np.ndarray] = []
    for target in targets:
        target = np.asarray(target, dtype=bool)
        positive = int(target.sum())
        negative = int((~target).sum())
        if positive == 0 or negative == 0:
            raise ValueError("observation_operator_event_class_missing")
        value = np.empty(len(target), dtype=np.float64)
        value[target] = 0.5 * event_mass / positive
        value[~target] = 0.5 * event_mass / negative
        weights.append(value)
    return weights


def binary_metrics(target: np.ndarray, predicted: np.ndarray, probability: np.ndarray | None = None) -> dict[str, Any]:
    target = np.asarray(target, dtype=bool)
    predicted = np.asarray(predicted, dtype=bool)
    tp = int(np.sum(target & predicted))
    fp = int(np.sum(~target & predicted))
    fn = int(np.sum(target & ~predicted))
    tn = int(np.sum(~target & ~predicted))
    union = tp + fp + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    result: dict[str, Any] = {
        "eligible_cell_count": int(len(target)),
        "observed_wet_cell_count": int(target.sum()),
        "predicted_wet_cell_count": int(predicted.sum()),
        "true_positive_cells": tp,
        "false_positive_cells": fp,
        "false_negative_cells": fn,
        "true_negative_cells": tn,
        "iou": float(tp / union) if union else 1.0,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(2.0 * precision * recall / (precision + recall)) if precision + recall else 0.0,
    }
    if probability is not None:
        probability = np.asarray(probability, dtype=np.float64)
        result["brier_score"] = float(np.mean((probability - target.astype(float)) ** 2))
        result["roc_auc"] = float(roc_auc_score(target, probability))
        result["average_precision"] = float(average_precision_score(target, probability))
        prevalence = float(target.mean())
        result["prevalence"] = prevalence
        result["average_precision_lift"] = (
            float(result["average_precision"] / prevalence) if prevalence else None
        )
    else:
        result["brier_score"] = None
        result["roc_auc"] = None
        result["average_precision"] = None
        result["prevalence"] = float(target.mean())
        result["average_precision_lift"] = None
    return result


def trajectory_feature_grid(
    depth: np.ndarray,
    times: np.ndarray,
    land: np.ndarray,
    observation_seconds: float,
) -> np.ndarray:
    """Build the frozen observation-operator features from one depth trajectory."""

    depth = np.asarray(depth, dtype=np.float64)
    times = np.asarray(times, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    if (
        depth.ndim != 2
        or times.ndim != 1
        or depth.shape[0] != len(times)
        or depth.shape[1] != land.size
        or not len(times)
    ):
        raise ValueError("observation_operator_trajectory_shape_invalid")
    peak = np.nanmax(depth, axis=0).reshape(land.shape)
    end = depth[-1].reshape(land.shape)
    mean = np.nanmean(depth, axis=0).reshape(land.shape)
    wet_duration = np.mean(depth >= WET_DEPTH_THRESHOLD_M, axis=0).reshape(land.shape)
    lag_days = max(0.0, float(observation_seconds) - float(times[-1])) / 86400.0
    decay = np.exp(-lag_days / 3.0)
    log_peak = np.log1p(np.maximum(peak, 0.0) * 100.0)
    log_end = np.log1p(np.maximum(end, 0.0) * 100.0)
    log_mean = np.log1p(np.maximum(mean, 0.0) * 100.0)
    neighbor_peak_mean = np.log1p(
        np.maximum(neighbor_mean(np.maximum(peak, 0.0) * 100.0, land), 0.0)
    )
    neighbor_peak_max = np.log1p(
        maximum_filter(np.where(land, peak * 100.0, 0.0), size=3, mode="constant")
    )
    neighbor_wet_duration = neighbor_mean(wet_duration, land)
    nonnegative_peak_cm = np.maximum(peak, 0.0) * 100.0
    peak_wet = peak >= WET_DEPTH_THRESHOLD_M
    neighborhood_500m_peak_max = np.log1p(
        maximum_filter(np.where(land, nonnegative_peak_cm, 0.0), size=5, mode="constant")
    )
    neighborhood_1000m_peak_max = np.log1p(
        maximum_filter(np.where(land, nonnegative_peak_cm, 0.0), size=9, mode="constant")
    )
    neighborhood_1000m_peak_mean = np.log1p(
        np.maximum(neighbor_mean(nonnegative_peak_cm, land, size=9), 0.0)
    )
    neighborhood_500m_peak_wet = neighbor_mean(peak_wet.astype(float), land, size=5)
    neighborhood_1000m_peak_wet = neighbor_mean(peak_wet.astype(float), land, size=9)
    return np.stack(
        (
            log_peak,
            log_end,
            log_mean,
            wet_duration,
            np.full(land.shape, lag_days),
            np.full(land.shape, lag_days**2),
            np.log1p(np.maximum(peak * decay, 0.0) * 100.0),
            neighbor_peak_mean,
            neighbor_peak_max,
            neighbor_wet_duration,
            neighborhood_500m_peak_max,
            neighborhood_1000m_peak_max,
            neighborhood_1000m_peak_mean,
            neighborhood_500m_peak_wet,
            neighborhood_1000m_peak_wet,
        ),
        axis=-1,
    )


def _load_event(
    event: dict[str, Any], observations_root: Path, label_root: Path
) -> EventData:
    event_id = str(event["event_id"])
    observation_path = observations_root / event_id / "observed_flood_250m.npz"
    label_path = label_root / "events" / event_id / "surface_depth_labels_250m.npz"
    with np.load(observation_path) as archive:
        valid_fraction = np.asarray(archive["valid_fraction"], dtype=np.float64)
        observed_fraction = np.asarray(
            archive["observed_new_surface_water_fraction_of_valid_pixels"], dtype=np.float64
        )
        observation_seconds = float(archive["observation_time_seconds_from_event_start"])
    with np.load(label_path) as archive:
        depth = np.asarray(archive["depth_m"], dtype=np.float64)
        times = np.asarray(archive["time_seconds"], dtype=np.float64)
        land = np.asarray(archive["land_mask"], dtype=bool)
    if depth.ndim != 2 or depth.shape[1] != land.size or valid_fraction.shape != land.shape:
        raise ValueError(f"observation_operator_event_shape_invalid:{event_id}")
    peak = np.nanmax(depth, axis=0).reshape(land.shape)
    end = depth[-1].reshape(land.shape)
    feature_grid = trajectory_feature_grid(
        depth,
        times,
        land,
        observation_seconds,
    )
    eligible_grid = (valid_fraction >= MINIMUM_VALID_FRACTION) & land
    target_grid = observed_fraction >= MINIMUM_OBSERVED_FRACTION
    return EventData(
        event_id=event_id,
        cohort_role=str(event["cohort_role"]),
        shape=land.shape,
        eligible=eligible_grid,
        target=target_grid[eligible_grid],
        features=feature_grid[eligible_grid],
        peak_prediction=(peak[eligible_grid] >= WET_DEPTH_THRESHOLD_M),
        end_prediction=(end[eligible_grid] >= WET_DEPTH_THRESHOLD_M),
    )


def _fit_operator(events: list[EventData], feature_indices: tuple[int, ...]) -> tuple[StandardScaler, LogisticRegression]:
    features = [event.features[:, feature_indices] for event in events]
    targets = [event.target for event in events]
    scaler = StandardScaler().fit(np.vstack(features))
    x = scaler.transform(np.vstack(features))
    y = np.concatenate(targets).astype(np.uint8)
    weights = np.concatenate(event_balanced_weights(targets))
    model = LogisticRegression(C=LOGISTIC_C, solver="lbfgs", max_iter=500, random_state=BOOTSTRAP_SEED)
    model.fit(x, y, sample_weight=weights)
    return scaler, model


def calibrate_balanced_probability(probability: np.ndarray, prevalence: float) -> np.ndarray:
    if not 0.0 < prevalence < 1.0:
        raise ValueError("observation_operator_prevalence_invalid")
    probability = np.clip(np.asarray(probability, dtype=np.float64), 1.0e-8, 1.0 - 1.0e-8)
    odds = probability / (1.0 - probability)
    prior_odds = prevalence / (1.0 - prevalence)
    adjusted = odds * prior_odds
    return adjusted / (1.0 + adjusted)


def _macro_prevalence(events: list[EventData]) -> float:
    return float(np.mean([event.target.mean() for event in events]))


def _operator_predictions(events: list[EventData], feature_names: tuple[str, ...]) -> dict[str, np.ndarray]:
    indices = tuple(FEATURE_NAMES.index(name) for name in feature_names)
    predictions: dict[str, np.ndarray] = {}
    for held_out in events:
        train = [event for event in events if event.event_id != held_out.event_id]
        scaler, model = _fit_operator(train, indices)
        raw = model.predict_proba(scaler.transform(held_out.features[:, indices]))[:, 1]
        predictions[held_out.event_id] = calibrate_balanced_probability(
            raw, _macro_prevalence(train)
        )
    return predictions


def select_probability_threshold(
    events: list[EventData], predictions: dict[str, np.ndarray]
) -> float:
    scored: list[tuple[float, float, float]] = []
    for threshold in PROBABILITY_THRESHOLDS:
        event_metrics = [
            binary_metrics(
                event.target,
                predictions[event.event_id] >= threshold,
            )
            for event in events
        ]
        mean_iou = float(np.mean([metric["iou"] for metric in event_metrics]))
        mean_precision = float(np.mean([metric["precision"] for metric in event_metrics]))
        scored.append((mean_iou, mean_precision, threshold))
    return max(scored, key=lambda item: (item[0], item[1], item[2]))[2]


def _nested_operator_predictions(
    events: list[EventData], feature_names: tuple[str, ...]
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    indices = tuple(FEATURE_NAMES.index(name) for name in feature_names)
    predictions: dict[str, np.ndarray] = {}
    thresholds: dict[str, float] = {}
    for held_out in events:
        outer_train = [event for event in events if event.event_id != held_out.event_id]
        inner_predictions: dict[str, np.ndarray] = {}
        for inner_held_out in outer_train:
            inner_train = [
                event for event in outer_train if event.event_id != inner_held_out.event_id
            ]
            scaler, model = _fit_operator(inner_train, indices)
            raw = model.predict_proba(
                scaler.transform(inner_held_out.features[:, indices])
            )[:, 1]
            inner_predictions[inner_held_out.event_id] = calibrate_balanced_probability(
                raw, _macro_prevalence(inner_train)
            )
        threshold = select_probability_threshold(outer_train, inner_predictions)
        scaler, model = _fit_operator(outer_train, indices)
        raw = model.predict_proba(scaler.transform(held_out.features[:, indices]))[:, 1]
        predictions[held_out.event_id] = calibrate_balanced_probability(
            raw, _macro_prevalence(outer_train)
        )
        thresholds[held_out.event_id] = threshold
    return predictions, thresholds


def _bootstrap_interval(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    sampled = rng.choice(values, size=(BOOTSTRAP_REPLICATES, len(values)), replace=True).mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95_low": float(np.quantile(sampled, 0.025)),
        "ci95_high": float(np.quantile(sampled, 0.975)),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    observations_root = args.observations.expanduser().resolve()
    batch_receipt_path = observations_root / "batch_receipt.json"
    label_root = args.label_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    batch = json.loads(batch_receipt_path.read_text(encoding="utf-8"))
    if (
        batch.get("status") != "completed"
        or batch.get("observation_purpose") != "observation_operator_development"
    ):
        raise ValueError("observation_operator_batch_receipt_invalid")
    admitted = [
        event
        for event in batch.get("events", [])
        if event.get("status") == "completed" and event.get("pixel_qc_passed") is True
    ]
    if len(admitted) < 5:
        raise ValueError("observation_operator_event_count_insufficient")
    events = [_load_event(event, observations_root, label_root) for event in admitted]
    event_rows: list[dict[str, Any]] = []
    probability_by_model: dict[str, dict[str, np.ndarray]] = {}
    threshold_by_model: dict[str, dict[str, float]] = {}
    for model_name, feature_names in FEATURE_SETS.items():
        probability_by_model[model_name], threshold_by_model[model_name] = (
            _nested_operator_predictions(events, feature_names)
        )
    for event in events:
        for model_name, prediction in (
            ("all_wet_prevalence", np.ones_like(event.target, dtype=bool)),
            ("peak_depth_0p01m", event.peak_prediction),
            ("end_depth_0p01m", event.end_prediction),
        ):
            event_rows.append(
                {
                    "event_id": event.event_id,
                    "cohort_role": event.cohort_role,
                    "model": model_name,
                    **binary_metrics(event.target, prediction),
                }
            )
        for model_name, predictions in probability_by_model.items():
            probability = predictions[event.event_id]
            threshold = threshold_by_model[model_name][event.event_id]
            event_rows.append(
                {
                    "event_id": event.event_id,
                    "cohort_role": event.cohort_role,
                    "model": model_name,
                    "probability_threshold": threshold,
                    **binary_metrics(event.target, probability >= threshold, probability),
                }
            )
    event_metrics = pd.DataFrame(event_rows)
    aggregate_rows: list[dict[str, Any]] = []
    for model_name, group in event_metrics.groupby("model", sort=False):
        row: dict[str, Any] = {"model": model_name, "event_count": int(len(group))}
        for metric in ("iou", "precision", "recall", "f1"):
            interval = _bootstrap_interval(group[metric].to_numpy(dtype=float))
            row[f"macro_{metric}"] = interval["mean"]
            row[f"macro_{metric}_ci95_low"] = interval["ci95_low"]
            row[f"macro_{metric}_ci95_high"] = interval["ci95_high"]
        probabilistic = group["brier_score"].dropna()
        row["macro_brier_score"] = None if probabilistic.empty else float(probabilistic.mean())
        row["macro_roc_auc"] = (
            None if group["roc_auc"].dropna().empty else float(group["roc_auc"].dropna().mean())
        )
        row["macro_average_precision"] = (
            None
            if group["average_precision"].dropna().empty
            else float(group["average_precision"].dropna().mean())
        )
        row["macro_average_precision_lift"] = (
            None
            if group["average_precision_lift"].dropna().empty
            else float(group["average_precision_lift"].dropna().mean())
        )
        aggregate_rows.append(row)
    aggregate = pd.DataFrame(aggregate_rows).sort_values("macro_iou", ascending=False).reset_index(drop=True)
    operator_rows = aggregate[aggregate["model"].isin(FEATURE_SETS)]
    binary_selected_name = str(
        operator_rows.sort_values("macro_iou", ascending=False).iloc[0]["model"]
    )
    ranking_selected_name = str(
        operator_rows.sort_values("macro_average_precision_lift", ascending=False).iloc[0][
            "model"
        ]
    )
    selected_name = ranking_selected_name
    baseline_iou = float(
        aggregate.loc[aggregate["model"].eq("peak_depth_0p01m"), "macro_iou"].iloc[0]
    )
    selected_row = operator_rows[operator_rows["model"].eq(selected_name)].iloc[0]
    selected_iou = float(selected_row["macro_iou"])
    selected_features = FEATURE_SETS[selected_name]
    selected_indices = tuple(FEATURE_NAMES.index(name) for name in selected_features)
    final_oof_predictions = _operator_predictions(events, selected_features)
    final_probability_threshold = select_probability_threshold(events, final_oof_predictions)
    final_calibration_prevalence = _macro_prevalence(events)
    scaler, final_model = _fit_operator(events, selected_indices)
    output.mkdir(parents=True, exist_ok=True)
    event_metrics.to_csv(output / "leave_one_event_out_metrics.csv", index=False)
    aggregate.to_csv(output / "aggregate_metrics.csv", index=False)
    prediction_root = output / "oof_predictions"
    prediction_root.mkdir(parents=True, exist_ok=True)
    for event in events:
        probability = probability_by_model[selected_name][event.event_id]
        full = np.full(event.shape, np.nan, dtype=np.float32)
        full[event.eligible] = probability.astype(np.float32)
        np.savez_compressed(
            prediction_root / f"{event.event_id}.npz",
            probability=full,
            eligible_mask=event.eligible,
            target=event.target,
        )
    np.savez_compressed(
        output / "selected_observation_operator.npz",
        feature_names=np.asarray(selected_features),
        scaler_mean=scaler.mean_,
        scaler_scale=scaler.scale_,
        coefficients=final_model.coef_[0],
        intercept=final_model.intercept_,
        calibration_prevalence=np.asarray([final_calibration_prevalence]),
        probability_threshold=np.asarray([final_probability_threshold]),
    )
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed_development_only",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event_count": len(events),
        "event_ids": [event.event_id for event in events],
        "validation": {
            "method": "leave-one-event-out cross-validation",
            "independent_unit": "rainfall event",
            "pixel_rows_treated_as_independent_for_claims": False,
            "fixed_logistic_c": LOGISTIC_C,
            "outer_threshold_selection": (
                "nested leave-one-event-out on outer-training events only"
            ),
            "final_probability_threshold": final_probability_threshold,
            "final_calibration_prevalence": final_calibration_prevalence,
            "event_and_class_balanced_training_weights": True,
        },
        "selected_operator": {
            "name": selected_name,
            "selection_metric": "macro leave-one-event-out average-precision lift",
            "feature_names": list(selected_features),
            "macro_iou": selected_iou,
            "macro_roc_auc": float(selected_row["macro_roc_auc"]),
            "macro_average_precision": float(selected_row["macro_average_precision"]),
            "macro_average_precision_lift": float(
                selected_row["macro_average_precision_lift"]
            ),
            "peak_depth_baseline_macro_iou": baseline_iou,
            "macro_iou_difference": selected_iou - baseline_iou,
            "final_probability_threshold": final_probability_threshold,
            "best_binary_iou_operator": binary_selected_name,
            "promote_to_gwm_runtime": False,
        },
        "inputs": {
            "batch_receipt": {
                "path": str(batch_receipt_path),
                "sha256": _sha256(batch_receipt_path),
            },
            "label_root": str(label_root),
        },
        "outputs": {
            "event_metrics": "leave_one_event_out_metrics.csv",
            "aggregate_metrics": "aggregate_metrics.csv",
            "selected_operator": "selected_observation_operator.npz",
            "oof_predictions": "oof_predictions",
        },
        "claim_boundary": [
            "This is post-hoc development on exposed events, not external confirmation.",
            "The target is Sentinel-2-visible new surface water, not observed water depth.",
            "The operator maps model trajectory summaries to an optical observation space and does not change GWM dynamics.",
            "A future unseen event cohort is required before runtime promotion or a high-level paper claim.",
        ],
    }
    result["receipt_sha256"] = _canonical_sha256(result)
    _write_json(output / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--label-root", type=Path, default=DEFAULT_LABEL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "event_count": result["event_count"],
                "selected_operator": result["selected_operator"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
