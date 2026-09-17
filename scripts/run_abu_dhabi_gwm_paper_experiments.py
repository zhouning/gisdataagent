#!/usr/bin/env python3
"""Run leakage-aware, publication-oriented Abu Dhabi flood GWM experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scripts.extract_abu_dhabi_sentinel2_observed_flood import _compare_model
    from scripts.train_abu_dhabi_five_year_event_gwm import (
        EXTERNAL_HOLDOUT_EVENT_ID,
        SEED_EVENT_IDS,
        EventLabel,
        Metrics,
        Statistics,
        _admit_labels,
        _event_arrays,
        _select_events,
    )
except ModuleNotFoundError:
    from extract_abu_dhabi_sentinel2_observed_flood import _compare_model
    from train_abu_dhabi_five_year_event_gwm import (
        EXTERNAL_HOLDOUT_EVENT_ID,
        SEED_EVENT_IDS,
        EventLabel,
        Metrics,
        Statistics,
        _admit_labels,
        _event_arrays,
        _select_events,
    )


DEFAULT_MATRIX = Path(
    "/Users/zhouning/Downloads/阿布扎比/GWM管网版本化训练清单_20260914/"
    "event_network_training_matrix.csv"
)
DEFAULT_LABEL_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_city_swmm_2d_coupled_labels_20260914_r1"
)
DEFAULT_OBSERVATION_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_sentinel2_observed_flood_202404_r1"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_paper_experiments_20260916_v1"
)
ALPHAS = (0.01, 0.1, 1.0, 10.0)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260916
PROCESS_BUFFER_DAYS = 7
WET_THRESHOLD_M = 0.01
MAXIMUM_PLAUSIBLE_DEPTH_M = 10.0
SCHEMA = "gwm.abu_dhabi_flood.paper_experiments.v1"
FULL_FEATURE_NAMES = (
    "intercept",
    "depth_m",
    "depth_delta_m",
    "cardinal_neighbor_mean_depth_m",
    "cardinal_neighbor_mean_delta_m",
    "rainfall_intensity_mm_h_div_10",
    "cumulative_rainfall_mm_div_50",
    "trailing_3h_rainfall_mm_div_30",
    "peak_rainfall_so_far_mm_h_div_10",
    "rainfall_intensity_scaled_squared",
    "depth_x_rainfall_intensity_scaled",
)
FEATURE_INDEX = {name: index for index, name in enumerate(FULL_FEATURE_NAMES)}
FEATURE_SETS = {
    "local_linear": (
        "intercept",
        "depth_m",
        "rainfall_intensity_mm_h_div_10",
        "cumulative_rainfall_mm_div_50",
    ),
    "local_inertia_rain_memory": (
        "intercept",
        "depth_m",
        "depth_delta_m",
        "rainfall_intensity_mm_h_div_10",
        "cumulative_rainfall_mm_div_50",
        "trailing_3h_rainfall_mm_div_30",
        "peak_rainfall_so_far_mm_h_div_10",
        "rainfall_intensity_scaled_squared",
        "depth_x_rainfall_intensity_scaled",
    ),
    "spatiotemporal_rain_memory": FULL_FEATURE_NAMES,
}


@dataclass(frozen=True)
class ModelDefinition:
    name: str
    training_cohort: str
    feature_set: str
    eligible_for_selection: bool


@dataclass(frozen=True)
class FittedModel:
    definition: ModelDefinition
    alpha: float
    feature_indices: tuple[int, ...]
    coefficients: np.ndarray


@dataclass
class EvaluationResult:
    metrics: Metrics
    maximum_predicted_depth_m: float = 0.0
    stability_violation: bool = False


MODEL_DEFINITIONS = (
    ModelDefinition("three_event_seed", "seed", "local_linear", False),
    ModelDefinition("all17_local_linear", "all17", "local_linear", False),
    ModelDefinition("process_safe_local_linear", "process_safe", "local_linear", True),
    ModelDefinition(
        "process_safe_local_inertia_rain_memory",
        "process_safe",
        "local_inertia_rain_memory",
        True,
    ),
    ModelDefinition(
        "process_safe_spatiotemporal_rain_memory",
        "process_safe",
        "spatiotemporal_rain_memory",
        True,
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _grid_shape(label: EventLabel) -> tuple[int, int]:
    with np.load(label.depth_path) as archive:
        shape = tuple(int(value) for value in archive["land_mask"].shape)
    if len(shape) != 2:
        raise ValueError("gwm_paper_grid_shape_invalid")
    return shape


def _neighbor_mean(values: np.ndarray, land: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    grid = np.asarray(values, dtype=np.float64).reshape(shape)
    valid = np.asarray(land, dtype=bool).reshape(shape)
    total = np.zeros(shape, dtype=np.float64)
    count = np.zeros(shape, dtype=np.float64)
    total[1:, :] += grid[:-1, :] * valid[:-1, :]
    count[1:, :] += valid[:-1, :]
    total[:-1, :] += grid[1:, :] * valid[1:, :]
    count[:-1, :] += valid[1:, :]
    total[:, 1:] += grid[:, :-1] * valid[:, :-1]
    count[:, 1:] += valid[:, :-1]
    total[:, :-1] += grid[:, 1:] * valid[:, 1:]
    count[:, :-1] += valid[:, 1:]
    result = grid.copy()
    np.divide(total, count, out=result, where=count > 0)
    return result.reshape(-1)


def _cumulative_rainfall(hourly: np.ndarray, seconds: float) -> float:
    bounded = min(max(float(seconds), 0.0), float(len(hourly)) * 3600.0)
    complete_hours = min(int(bounded // 3600.0), len(hourly))
    cumulative = float(hourly[:complete_hours].sum())
    if complete_hours < len(hourly):
        cumulative += float(hourly[complete_hours]) * ((bounded / 3600.0) - complete_hours)
    return cumulative


def _rain_features(hourly: np.ndarray, seconds: float) -> tuple[float, float, float, float]:
    hour_index = min(len(hourly) - 1, int(seconds // 3600.0))
    intensity = float(hourly[hour_index] / 10.0)
    cumulative = _cumulative_rainfall(hourly, seconds)
    trailing = cumulative - _cumulative_rainfall(hourly, seconds - 3.0 * 3600.0)
    peak = float(np.max(hourly[: hour_index + 1]) / 10.0)
    return intensity, cumulative / 50.0, trailing / 30.0, peak


def _feature_matrix(
    current: np.ndarray,
    previous: np.ndarray,
    land: np.ndarray,
    shape: tuple[int, int],
    hourly: np.ndarray,
    seconds: float,
) -> np.ndarray:
    current = np.asarray(current, dtype=np.float64).reshape(-1)
    previous = np.asarray(previous, dtype=np.float64).reshape(-1)
    delta = current - previous
    neighbor_depth = _neighbor_mean(current, land, shape)
    neighbor_delta = _neighbor_mean(delta, land, shape)
    intensity, cumulative, trailing, peak = _rain_features(hourly, seconds)
    return np.stack(
        (
            np.ones_like(current),
            current,
            delta,
            neighbor_depth,
            neighbor_delta,
            np.full_like(current, intensity),
            np.full_like(current, cumulative),
            np.full_like(current, trailing),
            np.full_like(current, peak),
            np.full_like(current, intensity * intensity),
            current * intensity,
        ),
        axis=1,
    )


def _new_statistics(cell_count: int) -> Statistics:
    feature_count = len(FULL_FEATURE_NAMES)
    return Statistics(
        np.zeros((cell_count, feature_count, feature_count), dtype=np.float64),
        np.zeros((cell_count, feature_count), dtype=np.float64),
    )


def _update_statistics(
    targets: Iterable[Statistics],
    depth: np.ndarray,
    times: np.ndarray,
    land: np.ndarray,
    hourly: np.ndarray,
    shape: tuple[int, int],
) -> None:
    target_list = list(targets)
    active = np.flatnonzero(land)
    previous = depth[0]
    for index in range(len(times) - 1):
        current = depth[index]
        truth = depth[index + 1, active]
        features = _feature_matrix(
            current,
            previous,
            land,
            shape,
            hourly,
            float(times[index]),
        )[active]
        weight = 1.0 + 4.0 * ((current[active] >= WET_THRESHOLD_M) | (truth >= WET_THRESHOLD_M))
        xtx = np.einsum("ni,nj,n->nij", features, features, weight, optimize=True)
        xty = features * (weight * truth)[:, None]
        for statistics in target_list:
            statistics.xtx[active] += xtx
            statistics.xty[active] += xty
            statistics.transition_count += int(len(active))
        previous = current


def _fit(
    statistics: Statistics,
    feature_names: tuple[str, ...],
    alpha: float,
) -> tuple[np.ndarray, tuple[int, ...]]:
    feature_indices = tuple(FEATURE_INDEX[name] for name in feature_names)
    matrices = statistics.xtx[:, feature_indices, :][:, :, feature_indices].copy()
    matrices += np.eye(len(feature_indices), dtype=np.float64)[None, :, :] * alpha
    targets = statistics.xty[:, feature_indices]
    coefficients = np.linalg.solve(matrices, targets[..., None]).squeeze(-1)
    return coefficients, feature_indices


def _predict(
    model: FittedModel,
    current: np.ndarray,
    previous: np.ndarray,
    land: np.ndarray,
    shape: tuple[int, int],
    hourly: np.ndarray,
    seconds: float,
) -> np.ndarray:
    active = np.flatnonzero(land)
    features = _feature_matrix(current, previous, land, shape, hourly, seconds)
    prediction = np.einsum(
        "ij,ij->i",
        model.coefficients[active],
        features[active][:, model.feature_indices],
        optimize=True,
    )
    return np.nan_to_num(prediction, nan=1.0e6, posinf=1.0e6, neginf=0.0).clip(min=0.0)


def _merge_metrics(destination: Metrics, source: Metrics) -> None:
    destination.sample_count += source.sample_count
    destination.sum_squared_error += source.sum_squared_error
    destination.sum_absolute_error += source.sum_absolute_error
    destination.intersection += source.intersection
    destination.union += source.union
    destination.predicted_wet += source.predicted_wet
    destination.truth_wet += source.truth_wet


def _evaluate_event(
    label: EventLabel,
    model: FittedModel | None,
    mode: str,
    shape: tuple[int, int],
) -> EvaluationResult:
    if mode not in {"one_step", "rollout"}:
        raise ValueError("gwm_paper_evaluation_mode_invalid")
    depth, times, land, hourly = _event_arrays(label)
    active = np.flatnonzero(land)
    metrics = Metrics()
    current_rollout = depth[0].copy()
    previous_rollout = depth[0].copy()
    maximum = 0.0
    violation = False
    for index in range(len(times) - 1):
        truth = depth[index + 1, active]
        if mode == "one_step":
            current = depth[index]
            previous = depth[max(0, index - 1)]
        else:
            current = current_rollout
            previous = previous_rollout
        if model is None:
            prediction = current[active]
        else:
            prediction = _predict(
                model,
                current,
                previous,
                land,
                shape,
                hourly,
                float(times[index]),
            )
        if prediction.size:
            maximum = max(maximum, float(np.max(prediction)))
        if maximum > MAXIMUM_PLAUSIBLE_DEPTH_M:
            violation = True
        metrics.update(truth, prediction)
        if mode == "rollout":
            previous_rollout = current_rollout
            current_rollout = np.zeros_like(current_rollout)
            current_rollout[active] = prediction
    return EvaluationResult(metrics, maximum, violation)


def _evaluate_events(
    labels: list[EventLabel],
    model: FittedModel | None,
    mode: str,
    shape: tuple[int, int],
) -> tuple[EvaluationResult, list[dict[str, Any]]]:
    aggregate = EvaluationResult(Metrics())
    event_rows: list[dict[str, Any]] = []
    for label in labels:
        result = _evaluate_event(label, model, mode, shape)
        _merge_metrics(aggregate.metrics, result.metrics)
        aggregate.maximum_predicted_depth_m = max(
            aggregate.maximum_predicted_depth_m,
            result.maximum_predicted_depth_m,
        )
        aggregate.stability_violation = aggregate.stability_violation or result.stability_violation
        event_rows.append(
            {
                "event_id": label.event_id,
                "split": label.split,
                "evaluation_mode": mode,
                **result.metrics.as_dict(),
                "maximum_predicted_depth_m": result.maximum_predicted_depth_m,
                "stability_violation": result.stability_violation,
            }
        )
    return aggregate, event_rows


def _macro_metrics(event_rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        f"macro_{metric}": float(np.mean([float(row[metric]) for row in event_rows]))
        for metric in ("rmse_m", "mae_m", "inundation_iou", "inundation_f1")
    }


def _process_safe_training_events(
    matrix: pd.DataFrame,
    train: list[EventLabel],
) -> tuple[list[EventLabel], list[dict[str, Any]]]:
    indexed = matrix.set_index("event_id", drop=False)
    external = indexed.loc[EXTERNAL_HOLDOUT_EVENT_ID]
    external_start = pd.Timestamp(external["event_start_utc"])
    external_end = pd.Timestamp(external["event_end_utc"])
    buffer = pd.Timedelta(days=PROCESS_BUFFER_DAYS)
    safe: list[EventLabel] = []
    quarantined: list[dict[str, Any]] = []
    for label in train:
        row = indexed.loc[label.event_id]
        start = pd.Timestamp(row["event_start_utc"])
        end = pd.Timestamp(row["event_end_utc"])
        within_buffer = end >= external_start - buffer and start <= external_end + buffer
        if within_buffer:
            quarantined.append(
                {
                    "event_id": label.event_id,
                    "event_start_utc": start.isoformat(),
                    "event_end_utc": end.isoformat(),
                    "reason": f"within_{PROCESS_BUFFER_DAYS}d_of_external_holdout_window",
                }
            )
        else:
            safe.append(label)
    if not safe or not quarantined:
        raise ValueError("gwm_paper_process_buffer_contract_invalid")
    return safe, quarantined


def _rainfall_distribution(labels: list[EventLabel]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in labels:
        forcing = _read_json(label.forcing_path, "gwm_paper_forcing_invalid")
        hourly = np.asarray(forcing.get("hourly_precipitation_mm"), dtype=np.float64)
        rows.append(
            {
                "event_id": label.event_id,
                "split": label.split,
                "duration_hours": len(hourly),
                "total_rainfall_mm": float(hourly.sum()),
                "peak_hourly_rainfall_mm_h": float(hourly.max()),
            }
        )
    return rows


def _fit_model(
    definition: ModelDefinition,
    statistics: dict[str, Statistics],
    alpha: float,
) -> FittedModel:
    feature_names = FEATURE_SETS[definition.feature_set]
    coefficients, indices = _fit(statistics[definition.training_cohort], feature_names, alpha)
    return FittedModel(definition, alpha, indices, coefficients)


def _select_hyperparameters(
    statistics: dict[str, Statistics],
    validation: list[EventLabel],
    shape: tuple[int, int],
) -> tuple[dict[str, FittedModel], list[dict[str, Any]], str]:
    selected: dict[str, FittedModel] = {}
    rows: list[dict[str, Any]] = []
    for definition in MODEL_DEFINITIONS:
        candidates: list[tuple[tuple[float, float], FittedModel]] = []
        for alpha in ALPHAS:
            model = _fit_model(definition, statistics, alpha)
            result, events = _evaluate_events(validation, model, "rollout", shape)
            macro = _macro_metrics(events)
            row = {
                "model": definition.name,
                "training_cohort": definition.training_cohort,
                "feature_set": definition.feature_set,
                "alpha": alpha,
                **result.metrics.as_dict(),
                **macro,
                "maximum_predicted_depth_m": result.maximum_predicted_depth_m,
                "stability_violation": result.stability_violation,
            }
            rows.append(row)
            score = (
                math.inf if result.stability_violation else macro["macro_rmse_m"],
                math.inf if result.stability_violation else macro["macro_mae_m"],
            )
            candidates.append((score, model))
        best_score, best_model = min(candidates, key=lambda item: item[0])
        if not math.isfinite(best_score[0]):
            raise ValueError(f"gwm_paper_all_candidates_unstable:{definition.name}")
        selected[definition.name] = best_model
    eligible = [
        row
        for row in rows
        if selected[row["model"]].alpha == row["alpha"]
        and selected[row["model"]].definition.eligible_for_selection
    ]
    chosen = min(eligible, key=lambda row: (row["macro_rmse_m"], row["macro_mae_m"]))["model"]
    return selected, rows, str(chosen)


def _evaluate_selected_models(
    models: dict[str, FittedModel],
    by_split: dict[str, list[EventLabel]],
    shape: tuple[int, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    aggregate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    variants: list[tuple[str, FittedModel | None]] = [("persistence", None), *models.items()]
    for split in ("validation", "test", "external_test_2024_april"):
        for mode in ("one_step", "rollout"):
            for name, model in variants:
                result, events = _evaluate_events(by_split[split], model, mode, shape)
                macro = _macro_metrics(events)
                aggregate_rows.append(
                    {
                        "model": name,
                        "alpha": None if model is None else model.alpha,
                        "feature_set": (
                            "persistence" if model is None else model.definition.feature_set
                        ),
                        "split": split,
                        "evaluation_mode": mode,
                        "event_count": len(events),
                        **result.metrics.as_dict(),
                        **macro,
                        "maximum_predicted_depth_m": result.maximum_predicted_depth_m,
                        "stability_violation": result.stability_violation,
                    }
                )
                for row in events:
                    event_rows.append(
                        {
                            "model": name,
                            "alpha": None if model is None else model.alpha,
                            "feature_set": (
                                "persistence" if model is None else model.definition.feature_set
                            ),
                            **row,
                        }
                    )
    return aggregate_rows, event_rows


def _bootstrap_intervals(
    event_rows: list[dict[str, Any]],
    selected_name: str,
    reference_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(event_rows)
    frame = frame[frame["evaluation_mode"] == "rollout"]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        target = frame[frame["split"] == split]
        for reference_name in reference_names:
            if reference_name == selected_name:
                continue
            for metric in ("rmse_m", "mae_m", "inundation_iou", "inundation_f1"):
                selected = target[target["model"] == selected_name].set_index("event_id")[metric]
                reference = target[target["model"] == reference_name].set_index("event_id")[metric]
                common = selected.index.intersection(reference.index).sort_values()
                if common.empty:
                    continue
                differences = (
                    selected.loc[common].to_numpy(dtype=float)
                    - reference.loc[common].to_numpy(dtype=float)
                )
                indices = rng.integers(
                    0,
                    len(differences),
                    size=(BOOTSTRAP_REPLICATES, len(differences)),
                )
                samples = differences[indices].mean(axis=1)
                rows.append(
                    {
                        "split": split,
                        "selected_model": selected_name,
                        "reference_model": reference_name,
                        "metric": metric,
                        "event_count": len(differences),
                        "paired_macro_difference": float(differences.mean()),
                        "bootstrap_95_ci_low": float(np.quantile(samples, 0.025)),
                        "bootstrap_95_ci_high": float(np.quantile(samples, 0.975)),
                        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                        "interpretation": (
                            "descriptive_only_small_n"
                            if len(differences) < 5
                            else "paired_event_bootstrap"
                        ),
                    }
                )
    return rows


def _rollout_depth(
    model: FittedModel,
    hourly: np.ndarray,
    land: np.ndarray,
    shape: tuple[int, int],
    target_seconds: float,
) -> np.ndarray:
    active = np.flatnonzero(land)
    current = np.zeros(land.size, dtype=np.float64)
    previous = current.copy()
    for seconds in np.arange(0.0, target_seconds, 300.0):
        prediction = _predict(model, current, previous, land, shape, hourly, float(seconds))
        previous = current
        current = np.zeros_like(current)
        current[active] = prediction
    return current


def _sentinel_sensitivity(
    observation_root: Path,
    output_root: Path,
    model: FittedModel,
    land: np.ndarray,
    shape: tuple[int, int],
) -> list[dict[str, Any]]:
    receipt = _read_json(
        observation_root / "run_receipt.json",
        "gwm_paper_observation_receipt_invalid",
    )
    event = receipt.get("event", {})
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or event.get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID
        or event.get("training_forbidden") is not True
    ):
        raise ValueError("gwm_paper_observation_contract_invalid")
    forcing_path = observation_root / str(
        receipt["external_evaluation"]["forcing_with_zero_rain_tail"]
    )
    observation_path = observation_root / str(receipt["outputs"]["observed_flood_250m"])
    forcing = _read_json(forcing_path, "gwm_paper_observation_forcing_invalid")
    hourly = np.asarray(forcing["hourly_precipitation_mm"], dtype=np.float64)
    seconds = float(event["observation_time_seconds_from_event_start"])
    target_seconds = float(round(seconds / 300.0) * 300.0)
    depth = _rollout_depth(model, hourly, land, shape, target_seconds)
    rollout_path = output_root / "selected_model_sentinel2_phase_depth_250m.npz"
    np.savez_compressed(
        rollout_path,
        depth_m=depth[None, :].astype(np.float32),
        time_seconds=np.asarray([target_seconds], dtype=np.float64),
        land_mask=land.reshape(shape),
    )
    with np.load(observation_path) as archive:
        observation = {
            "valid_fraction": np.asarray(archive["valid_fraction"], dtype=np.float32),
            "observed_fraction_of_all": np.asarray(
                archive["observed_new_surface_water_fraction_of_all_pixels"], dtype=np.float32
            ),
            "observed_fraction_of_valid": np.asarray(
                archive["observed_new_surface_water_fraction_of_valid_pixels"], dtype=np.float32
            ),
        }
    rows: list[dict[str, Any]] = []
    for threshold in (0.01, 0.05, 0.10):
        comparison = _compare_model(
            rollout_path,
            observation,
            observation_seconds=seconds,
            minimum_valid_fraction=float(receipt["method"]["minimum_250m_valid_fraction"]),
            minimum_observed_fraction=float(receipt["method"]["minimum_250m_observed_water_fraction"]),
            depth_threshold_m=threshold,
        )
        rows.append(
            {
                "model": model.definition.name,
                "depth_threshold_m": threshold,
                **comparison["metrics"],
                "selection_use": "forbidden_posthoc_sensitivity_only",
            }
        )
    return rows


def _benchmark_inference(
    model: FittedModel,
    label: EventLabel,
    shape: tuple[int, int],
) -> dict[str, Any]:
    depth, times, land, hourly = _event_arrays(label)
    target_seconds = float(times[-1])
    durations: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        _rollout_depth(model, hourly, land, shape, target_seconds)
        durations.append(time.perf_counter() - started)
    median = float(np.median(durations))
    return {
        "event_id": label.event_id,
        "model": model.definition.name,
        "simulated_duration_seconds": target_seconds,
        "time_step_seconds": 300,
        "frame_count": len(times),
        "cell_count": int(land.size),
        "repeat_count": len(durations),
        "wall_seconds": durations,
        "median_wall_seconds": median,
        "realtime_factor": None if median == 0.0 else target_seconds / median,
        "physics_speedup": None,
        "physics_speedup_reason": (
            "physics wall-clock timing was not retained in the frozen label receipts"
        ),
    }


def _protocol(
    matrix_path: Path,
    label_root: Path,
    process_safe: list[EventLabel],
    quarantined: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.protocol",
        "status": "frozen_before_candidate_test_and_external_scoring",
        "matrix_sha256": _sha256(matrix_path),
        "label_batch_manifest_sha256": _sha256(label_root / "batch_manifest.json"),
        "primary_selection_metric": "validation event-macro rollout RMSE",
        "secondary_selection_metric": "validation event-macro rollout MAE",
        "regularization_grid": list(ALPHAS),
        "wet_transition_weight": 5.0,
        "wet_threshold_m": WET_THRESHOLD_M,
        "maximum_plausible_depth_guard_m": MAXIMUM_PLAUSIBLE_DEPTH_M,
        "process_buffer_days": PROCESS_BUFFER_DAYS,
        "process_safe_training_events": [label.event_id for label in process_safe],
        "quarantined_events": quarantined,
        "candidate_models": [
            {
                "name": definition.name,
                "training_cohort": definition.training_cohort,
                "feature_set": definition.feature_set,
                "features": list(FEATURE_SETS[definition.feature_set]),
                "eligible_for_selection": definition.eligible_for_selection,
            }
            for definition in MODEL_DEFINITIONS
        ],
        "test_policy": "blind test is report-only and never selects alpha or architecture",
        "external_policy": (
            "April 2024 is immutable and training-forbidden, but its earlier frozen-model "
            "score was already inspected; all new-model April 2024 results are post-hoc "
            "stress tests and cannot "
            "serve as confirmatory evidence"
        ),
        "sentinel_threshold_policy": (
            "0.01, 0.05, and 0.10 m are reported as sensitivity; none selects the model"
        ),
    }


def run(
    matrix_path: Path,
    label_root: Path,
    observation_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    matrix_path = matrix_path.expanduser().resolve()
    label_root = label_root.expanduser().resolve()
    observation_root = observation_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    matrix = _select_events(matrix_path)
    labels = _admit_labels(matrix, label_root)
    by_split = {
        split: [label for label in labels if label.split == split]
        for split in ("train", "validation", "test", "external_test_2024_april")
    }
    process_safe, quarantined = _process_safe_training_events(matrix, by_split["train"])
    seed = [label for label in by_split["train"] if label.event_id in SEED_EVENT_IDS]
    if {label.event_id for label in seed} != set(SEED_EVENT_IDS):
        raise ValueError("gwm_paper_seed_events_missing")
    protocol = _protocol(matrix_path, label_root, process_safe, quarantined)
    _write_json(output_root / "experiment_protocol.json", protocol)
    shape = _grid_shape(labels[0])
    sample_depth, _, land, _ = _event_arrays(labels[0])
    statistics = {
        "seed": _new_statistics(sample_depth.shape[1]),
        "all17": _new_statistics(sample_depth.shape[1]),
        "process_safe": _new_statistics(sample_depth.shape[1]),
    }
    safe_ids = {label.event_id for label in process_safe}
    seed_ids = set(SEED_EVENT_IDS)
    for label in by_split["train"]:
        depth, times, event_land, hourly = _event_arrays(label)
        if depth.shape[1] != sample_depth.shape[1] or not np.array_equal(event_land, land):
            raise ValueError(f"gwm_paper_grid_contract_mismatch:{label.event_id}")
        targets = [statistics["all17"]]
        if label.event_id in safe_ids:
            targets.append(statistics["process_safe"])
        if label.event_id in seed_ids:
            targets.append(statistics["seed"])
        _update_statistics(targets, depth, times, event_land, hourly, shape)
    models, selection_rows, selected_name = _select_hyperparameters(
        statistics,
        by_split["validation"],
        shape,
    )
    aggregate_rows, event_rows = _evaluate_selected_models(models, by_split, shape)
    bootstrap_rows = _bootstrap_intervals(
        event_rows,
        selected_name,
        ("three_event_seed", "all17_local_linear"),
    )
    selected_model = models[selected_name]
    np.savez_compressed(
        output_root / "selected_model_coefficients.npz",
        coefficients=selected_model.coefficients.astype(np.float32),
        land_mask=land.reshape(shape),
        feature_indices=np.asarray(selected_model.feature_indices, dtype=np.int16),
        feature_names=np.asarray(FEATURE_SETS[selected_model.definition.feature_set]),
    )
    rainfall_rows = _rainfall_distribution(labels)
    sentinel_rows = _sentinel_sensitivity(
        observation_root,
        output_root,
        selected_model,
        land,
        shape,
    )
    benchmark = _benchmark_inference(
        selected_model,
        by_split["external_test_2024_april"][0],
        shape,
    )
    pd.DataFrame(selection_rows).to_csv(output_root / "validation_model_selection.csv", index=False)
    pd.DataFrame(aggregate_rows).to_csv(output_root / "aggregate_metrics.csv", index=False)
    pd.DataFrame(event_rows).to_csv(output_root / "event_metrics.csv", index=False)
    pd.DataFrame(bootstrap_rows).to_csv(output_root / "paired_bootstrap_intervals.csv", index=False)
    pd.DataFrame(rainfall_rows).to_csv(output_root / "rainfall_distribution.csv", index=False)
    pd.DataFrame(sentinel_rows).to_csv(
        output_root / "sentinel2_posthoc_sensitivity.csv",
        index=False,
    )
    _write_json(output_root / "inference_benchmark.json", benchmark)
    model_card = {
        "schema": f"{SCHEMA}.model_card",
        "model_name": selected_name,
        "alpha": selected_model.alpha,
        "feature_set": selected_model.definition.feature_set,
        "features": list(FEATURE_SETS[selected_model.definition.feature_set]),
        "training_events": [label.event_id for label in process_safe],
        "quarantined_events": quarantined,
        "selection": "validation event-macro rollout RMSE, then MAE",
        "terrain": "customer 5 m DTM fixed source; physics-label and GWM grid is 250 m",
        "target": "next 300-second SWMM--ANUGA candidate physics-label depth",
        "external_status": (
            "April 2024 result is post-hoc stress testing, not confirmatory validation"
        ),
        "claim_boundary": (
            "Research emulator of candidate physics labels. It is not directly trained on "
            "observed flood depth and is not an engineering replacement for SWMM--ANUGA."
        ),
    }
    _write_json(output_root / "model_card.json", model_card)
    selected_metrics = [
        row
        for row in aggregate_rows
        if row["model"] == selected_name and row["evaluation_mode"] == "rollout"
    ]
    result = {
        "schema": SCHEMA,
        "status": "completed",
        "selected_model": selected_name,
        "selected_alpha": selected_model.alpha,
        "selected_feature_set": selected_model.definition.feature_set,
        "training_event_count": len(process_safe),
        "quarantined_event_count": len(quarantined),
        "metrics": {row["split"]: row for row in selected_metrics},
        "sentinel2_posthoc_sensitivity": sentinel_rows,
        "inference_benchmark": benchmark,
        "confirmatory_external_validation_required": True,
        "outputs": {
            "protocol": "experiment_protocol.json",
            "model_card": "model_card.json",
            "coefficients": "selected_model_coefficients.npz",
            "model_selection": "validation_model_selection.csv",
            "aggregate_metrics": "aggregate_metrics.csv",
            "event_metrics": "event_metrics.csv",
            "paired_bootstrap": "paired_bootstrap_intervals.csv",
            "rainfall_distribution": "rainfall_distribution.csv",
            "sentinel2_sensitivity": "sentinel2_posthoc_sensitivity.csv",
            "inference_benchmark": "inference_benchmark.json",
        },
    }
    result["receipt_sha256"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    _write_json(output_root / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--label-root", type=Path, default=DEFAULT_LABEL_ROOT)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.matrix, args.label_root, args.observation_root, args.output_root)
    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_model": result["selected_model"],
                "selected_alpha": result["selected_alpha"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
