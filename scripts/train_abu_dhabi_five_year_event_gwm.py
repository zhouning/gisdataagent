#!/usr/bin/env python3
"""Train and evaluate a leakage-safe GWM emulator from five-year 2D labels.

This is a research emulator of the coupled SWMM--ANUGA labels, not an
engineering replacement for the physical solver.  The comparison is explicit:
the initial three-event seed model and the full five-year training model use
the same cellwise, rainfall-conditioned dynamics and are evaluated on the same
events.  Validation selects regularization; test and April 2024 external test
remain untouched until final scoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


DEFAULT_MATRIX = Path(
    "/Users/zhouning/Downloads/阿布扎比/GWM管网版本化训练清单_20260914/"
    "event_network_training_matrix.csv"
)
DEFAULT_LABEL_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_city_swmm_2d_coupled_labels_20260914_r1"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_five_year_event_gwm_20260914_r1"
)
EXTERNAL_HOLDOUT_EVENT_ID = "noaa-isd-ae-202404151200-0327"
SEED_EVENT_IDS = (
    "noaa-isd-ae-202402110000-0317",
    "noaa-isd-ae-202403041800-0319",
    "noaa-isd-ae-202403080000-0320",
)
ALLOWED_SPLITS = frozenset({"train", "validation", "test", "external_test_2024_april"})
ALPHAS = (1.0e-4, 1.0e-3, 1.0e-2, 1.0e-1, 1.0)
FEATURE_NAMES = ("intercept", "depth_m", "rainfall_intensity_mm_h_div_10", "cumulative_rainfall_mm_div_50")
WET_THRESHOLD_M = 0.01
SCHEMA = "gwm.abu_dhabi_flood.five_year_event_emulator.v1"


@dataclass(frozen=True)
class EventLabel:
    event_id: str
    split: str
    path: Path
    receipt_path: Path
    depth_path: Path
    forcing_path: Path


@dataclass
class Statistics:
    xtx: np.ndarray
    xty: np.ndarray
    transition_count: int = 0


@dataclass
class Metrics:
    sample_count: int = 0
    sum_squared_error: float = 0.0
    sum_absolute_error: float = 0.0
    intersection: int = 0
    union: int = 0
    predicted_wet: int = 0
    truth_wet: int = 0

    def update(self, truth: np.ndarray, prediction: np.ndarray) -> None:
        truth = np.asarray(truth, dtype=np.float64)
        prediction = np.maximum(np.asarray(prediction, dtype=np.float64), 0.0)
        finite = np.isfinite(truth) & np.isfinite(prediction)
        truth = truth[finite]
        prediction = prediction[finite]
        error = prediction - truth
        self.sample_count += int(len(truth))
        self.sum_squared_error += float(np.dot(error, error))
        self.sum_absolute_error += float(np.abs(error).sum())
        truth_wet = truth >= WET_THRESHOLD_M
        predicted_wet = prediction >= WET_THRESHOLD_M
        self.intersection += int(np.sum(truth_wet & predicted_wet))
        self.union += int(np.sum(truth_wet | predicted_wet))
        self.predicted_wet += int(np.sum(predicted_wet))
        self.truth_wet += int(np.sum(truth_wet))

    def as_dict(self) -> dict[str, float | int | None]:
        if not self.sample_count:
            return {"n": 0, "rmse_m": None, "mae_m": None, "inundation_iou": None, "inundation_f1": None}
        precision = self.intersection / self.predicted_wet if self.predicted_wet else 0.0
        recall = self.intersection / self.truth_wet if self.truth_wet else 0.0
        return {
            "n": int(self.sample_count),
            "rmse_m": float(np.sqrt(self.sum_squared_error / self.sample_count)),
            "mae_m": float(self.sum_absolute_error / self.sample_count),
            "inundation_iou": float(self.intersection / self.union) if self.union else 1.0,
            "inundation_f1": float(2.0 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().eq("true")


def _select_events(matrix_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(matrix_path)
    required = {"event_id", "event_start_utc", "rainfall_forcing_admitted", "standardized_experiment_ready", "split", "external_holdout"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"five_year_gwm_matrix_columns_missing:{','.join(missing)}")
    starts = pd.to_datetime(frame["event_start_utc"], utc=True, errors="raise")
    result = frame[
        (starts >= pd.Timestamp("2021-01-01", tz="UTC"))
        & (starts < pd.Timestamp("2026-01-01", tz="UTC"))
        & _as_bool(frame["rainfall_forcing_admitted"])
        & _as_bool(frame["standardized_experiment_ready"])
        & frame["split"].astype(str).isin(ALLOWED_SPLITS)
    ].copy()
    result["_start"] = pd.to_datetime(result["event_start_utc"], utc=True, errors="raise")
    result = result.sort_values("_start").reset_index(drop=True)
    if result.empty:
        raise ValueError("five_year_gwm_event_selection_empty")
    return result


def _load_receipt(path: Path, event_id: str) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"five_year_gwm_receipt_invalid:{event_id}") from exc
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or receipt.get("event", {}).get("event_id") != event_id
    ):
        raise ValueError(f"five_year_gwm_receipt_not_quality_completed:{event_id}")
    return receipt


def _admit_labels(matrix: pd.DataFrame, label_root: Path) -> list[EventLabel]:
    batch_path = label_root / "batch_manifest.json"
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("five_year_gwm_batch_manifest_missing_or_invalid") from exc
    if batch.get("status") != "completed":
        raise ValueError("five_year_gwm_batch_not_completed")
    expected = set(matrix["event_id"].astype(str))
    recorded = {str(item.get("event_id")) for item in batch.get("events", []) if isinstance(item, dict)}
    if expected != recorded or int(batch.get("failed_event_count", -1)) != 0:
        raise ValueError("five_year_gwm_batch_event_coverage_invalid")
    runner_sha256 = str(batch.get("inputs", {}).get("runner_sha256", ""))
    if not runner_sha256:
        raise ValueError("five_year_gwm_batch_runner_identity_missing")
    labels: list[EventLabel] = []
    for event in matrix.itertuples(index=False):
        event_id = str(event.event_id)
        path = label_root / "events" / event_id
        receipt_path = path / "run_receipt.json"
        receipt = _load_receipt(receipt_path, event_id)
        if receipt.get("implementation", {}).get("runner_sha256") != runner_sha256:
            raise ValueError(f"five_year_gwm_receipt_runner_mismatch:{event_id}")
        split = str(event.split)
        if receipt.get("event", {}).get("split") != split:
            raise ValueError(f"five_year_gwm_receipt_split_mismatch:{event_id}")
        external = bool(receipt.get("event", {}).get("external_holdout"))
        if external != (event_id == EXTERNAL_HOLDOUT_EVENT_ID):
            raise ValueError(f"five_year_gwm_receipt_external_holdout_mismatch:{event_id}")
        depth_path = path / str(receipt.get("outputs", {}).get("depth_labels", ""))
        forcing_path = path / "forcing.json"
        if not depth_path.is_file() or not forcing_path.is_file():
            raise ValueError(f"five_year_gwm_label_or_forcing_missing:{event_id}")
        labels.append(EventLabel(event_id, split, path, receipt_path, depth_path, forcing_path))
    return labels


def _event_arrays(label: EventLabel) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    forcing = json.loads(label.forcing_path.read_text(encoding="utf-8"))
    hourly = np.asarray(forcing.get("hourly_precipitation_mm"), dtype=np.float64)
    if hourly.ndim != 1 or not len(hourly) or not np.isfinite(hourly).all() or (hourly < 0).any():
        raise ValueError(f"five_year_gwm_forcing_invalid:{label.event_id}")
    with np.load(label.depth_path) as archive:
        depth = np.asarray(archive["depth_m"], dtype=np.float64)
        times = np.asarray(archive["time_seconds"], dtype=np.float64)
        land = np.asarray(archive["land_mask"], dtype=bool).reshape(-1)
    if depth.ndim not in {2, 3} or depth.shape[0] != len(times) or int(np.prod(depth.shape[1:])) != len(land):
        raise ValueError(f"five_year_gwm_label_shape_invalid:{label.event_id}")
    expected_frames = len(hourly) * 12 + 1
    if len(times) != expected_frames or not np.allclose(np.diff(times), 300.0):
        raise ValueError(f"five_year_gwm_label_temporal_contract_invalid:{label.event_id}")
    return depth.reshape(len(times), -1), times, land, hourly


def _rain_features(hourly: np.ndarray, seconds: float) -> tuple[float, float]:
    hour_index = min(len(hourly) - 1, int(seconds // 3600.0))
    fraction = (seconds - hour_index * 3600.0) / 3600.0
    cumulative = float(hourly[:hour_index].sum() + hourly[hour_index] * fraction)
    return float(hourly[hour_index] / 10.0), float(cumulative / 50.0)


def _new_statistics(cell_count: int) -> Statistics:
    return Statistics(np.zeros((cell_count, 4, 4), dtype=np.float64), np.zeros((cell_count, 4), dtype=np.float64))


def _update_statistics(statistics: Statistics, depth: np.ndarray, times: np.ndarray, land: np.ndarray, hourly: np.ndarray) -> None:
    active = np.flatnonzero(land)
    if not len(active):
        raise ValueError("five_year_gwm_land_mask_empty")
    for index in range(len(times) - 1):
        current = depth[index, active]
        target = depth[index + 1, active]
        intensity, cumulative = _rain_features(hourly, float(times[index]))
        # Upweight wet transitions so a city-wide dry-cell majority does not
        # suppress the inundation dynamics we need the emulator to reproduce.
        weight = 1.0 + 4.0 * ((current >= WET_THRESHOLD_M) | (target >= WET_THRESHOLD_M))
        features = np.stack((np.ones_like(current), current, np.full_like(current, intensity), np.full_like(current, cumulative)), axis=1)
        statistics.xtx[active] += np.einsum("ni,nj,n->nij", features, features, weight, optimize=True)
        statistics.xty[active] += features * (weight * target)[:, None]
        statistics.transition_count += int(len(active))


def _fit(statistics: Statistics, alpha: float) -> np.ndarray:
    if alpha <= 0:
        raise ValueError("five_year_gwm_alpha_invalid")
    # A small intercept penalty also makes water-mask cells, whose sufficient
    # statistics are intentionally all zero, well-defined zero predictors.
    regularizer = np.eye(4, dtype=np.float64) * alpha
    matrices = statistics.xtx + regularizer[None, :, :]
    try:
        return np.linalg.solve(matrices, statistics.xty[..., None]).squeeze(-1)
    except np.linalg.LinAlgError as exc:
        raise ValueError("five_year_gwm_ridge_fit_failed") from exc


def _predict(coefficients: np.ndarray, current: np.ndarray, intensity: float, cumulative: float) -> np.ndarray:
    return np.maximum(
        coefficients[:, 0]
        + coefficients[:, 1] * current
        + coefficients[:, 2] * intensity
        + coefficients[:, 3] * cumulative,
        0.0,
    )


def _evaluate(labels: Iterable[EventLabel], coefficients: np.ndarray | None, *, mode: str) -> Metrics:
    if mode not in {"one_step", "rollout"}:
        raise ValueError("five_year_gwm_evaluation_mode_invalid")
    metrics = Metrics()
    for label in labels:
        depth, times, land, hourly = _event_arrays(label)
        active = np.flatnonzero(land)
        current_rollout = depth[0, active].copy()
        for index in range(len(times) - 1):
            truth = depth[index + 1, active]
            current = depth[index, active] if mode == "one_step" else current_rollout
            intensity, cumulative = _rain_features(hourly, float(times[index]))
            prediction = current if coefficients is None else _predict(coefficients[active], current, intensity, cumulative)
            metrics.update(truth, prediction)
            if mode == "rollout":
                current_rollout = prediction
    return metrics


def _metric_row(variant: str, alpha: float | None, mode: str, split: str, labels: list[EventLabel], metrics: Metrics) -> dict[str, Any]:
    return {
        "variant": variant,
        "alpha": alpha,
        "evaluation_mode": mode,
        "split": split,
        "event_count": len(labels),
        "events": ",".join(item.event_id for item in labels),
        **metrics.as_dict(),
    }


def _lookup(rows: list[dict[str, Any]], variant: str, split: str, mode: str) -> dict[str, Any]:
    matches = [row for row in rows if row["variant"] == variant and row["split"] == split and row["evaluation_mode"] == mode]
    if len(matches) != 1:
        raise ValueError("five_year_gwm_metric_lookup_invalid")
    return matches[0]


def run(matrix_path: Path, label_root: Path, output_root: Path) -> dict[str, Any]:
    matrix_path = matrix_path.expanduser().resolve()
    label_root = label_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    matrix = _select_events(matrix_path)
    labels = _admit_labels(matrix, label_root)
    by_split = {split: [label for label in labels if label.split == split] for split in sorted(ALLOWED_SPLITS)}
    train = by_split["train"]
    seed = [label for label in train if label.event_id in SEED_EVENT_IDS]
    if {label.event_id for label in seed} != set(SEED_EVENT_IDS):
        raise ValueError("five_year_gwm_seed_events_missing")
    if not by_split["validation"] or not by_split["test"] or not by_split["external_test_2024_april"]:
        raise ValueError("five_year_gwm_required_evaluation_split_missing")

    # Accumulate sufficient statistics in streaming event/frame order.  This
    # avoids materializing a multi-hundred-million-row dense training table.
    sample_depth, _, sample_land, _ = _event_arrays(train[0])
    cell_count = sample_depth.shape[1]
    statistics = {"three_event_seed": _new_statistics(cell_count), "five_year_full_train": _new_statistics(cell_count)}
    for label in train:
        depth, times, land, hourly = _event_arrays(label)
        if depth.shape[1] != cell_count or not np.array_equal(land, sample_land):
            raise ValueError(f"five_year_gwm_grid_contract_mismatch:{label.event_id}")
        _update_statistics(statistics["five_year_full_train"], depth, times, land, hourly)
        if label.event_id in SEED_EVENT_IDS:
            _update_statistics(statistics["three_event_seed"], depth, times, land, hourly)

    chosen: dict[str, dict[str, Any]] = {}
    coefficients: dict[str, np.ndarray] = {}
    for variant, stat in statistics.items():
        candidates: list[dict[str, Any]] = []
        for alpha in ALPHAS:
            candidate = _fit(stat, alpha)
            validation_metrics = _evaluate(by_split["validation"], candidate, mode="rollout").as_dict()
            candidates.append({"alpha": alpha, **validation_metrics})
        best = min(candidates, key=lambda item: (float(item["rmse_m"]), float(item["mae_m"])))
        chosen[variant] = {"selected_alpha": best["alpha"], "validation_candidates": candidates}
        coefficients[variant] = _fit(stat, float(best["alpha"]))

    metric_rows: list[dict[str, Any]] = []
    for split in ("validation", "test", "external_test_2024_april"):
        target = by_split[split]
        for mode in ("one_step", "rollout"):
            metric_rows.append(_metric_row("persistence", None, mode, split, target, _evaluate(target, None, mode=mode)))
            for variant in ("three_event_seed", "five_year_full_train"):
                metric_rows.append(_metric_row(variant, chosen[variant]["selected_alpha"], mode, split, target, _evaluate(target, coefficients[variant], mode=mode)))

    comparisons: list[dict[str, Any]] = []
    for split in ("validation", "test", "external_test_2024_april"):
        for mode in ("one_step", "rollout"):
            seed_row = _lookup(metric_rows, "three_event_seed", split, mode)
            full_row = _lookup(metric_rows, "five_year_full_train", split, mode)
            seed_rmse = float(seed_row["rmse_m"])
            seed_mae = float(seed_row["mae_m"])
            comparisons.append(
                {
                    "split": split,
                    "evaluation_mode": mode,
                    "rmse_relative_reduction_vs_three_event": None if seed_rmse == 0 else float(1.0 - float(full_row["rmse_m"]) / seed_rmse),
                    "mae_relative_reduction_vs_three_event": None if seed_mae == 0 else float(1.0 - float(full_row["mae_m"]) / seed_mae),
                    "iou_change_vs_three_event": float(full_row["inundation_iou"]) - float(seed_row["inundation_iou"]),
                }
            )
    validation = _lookup(metric_rows, "five_year_full_train", "validation", "rollout")
    validation_seed = _lookup(metric_rows, "three_event_seed", "validation", "rollout")
    test = _lookup(metric_rows, "five_year_full_train", "test", "rollout")
    test_seed = _lookup(metric_rows, "three_event_seed", "test", "rollout")
    improved_validation = float(validation["rmse_m"]) < float(validation_seed["rmse_m"])
    improved_test = float(test["rmse_m"]) < float(test_seed["rmse_m"])
    conclusion = "improved_over_three_event_seed" if improved_validation and improved_test else "not_demonstrated_over_three_event_seed"

    output_root.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_root / "five_year_full_train_cellwise_ridge_coefficients.npz",
        coefficients=coefficients["five_year_full_train"].astype(np.float32),
        land_mask=sample_land,
    )
    # The mask is also recorded in the model card; coefficients remain aligned
    # to the declared 250 m label-cell ordering, never to an implicit geometry.
    pd.DataFrame(metric_rows).to_csv(output_root / "gwm_metrics.csv", index=False)
    pd.DataFrame(comparisons).to_csv(output_root / "five_year_vs_three_event_comparison.csv", index=False)
    split_manifest = {
        "schema": "gwm.abu_dhabi_flood.five_year_event_split.v1",
        "split": {key: [label.event_id for label in value] for key, value in by_split.items()},
        "seed_baseline_events": list(SEED_EVENT_IDS),
        "event_disjoint": True,
        "external_holdout_excluded_from_training": EXTERNAL_HOLDOUT_EVENT_ID not in {label.event_id for label in train},
    }
    _write_json(output_root / "split_manifest.json", split_manifest)
    _write_json(
        output_root / "gwm_model_card.json",
        {
            "schema": SCHEMA,
            "model_name": "cellwise_ridge_rainfall_conditioned_dynamics",
            "training_events": [label.event_id for label in train],
            "seed_baseline_events": list(SEED_EVENT_IDS),
            "inputs": list(FEATURE_NAMES),
            "target": "next_300_second_depth_m",
            "training_label": "quality-passing current-network SWMM--ANUGA 250m coupled candidate physics labels",
            "terrain": "customer 5m DTM is the fixed terrain source; the 2D computation grid remains 250m",
            "selected_regularization": {key: value["selected_alpha"] for key, value in chosen.items()},
            "claim_boundary": "Research emulator comparison only. It predicts physical-model labels, not directly observed historical inundation, and remains outside engineering admission.",
        },
    )
    result = {
        "schema": SCHEMA,
        "status": "completed",
        "matrix_sha256": _sha256(matrix_path),
        "label_batch_manifest_sha256": _sha256(label_root / "batch_manifest.json"),
        "events": {key: [label.event_id for label in value] for key, value in by_split.items()},
        "training_transition_counts": {key: value.transition_count for key, value in statistics.items()},
        "regularization_selection": chosen,
        "conclusion": {
            "outcome": conclusion,
            "full_model_lower_rollout_rmse_on_validation": improved_validation,
            "full_model_lower_rollout_rmse_on_blind_test": improved_test,
            "external_test_is_reported_only": True,
        },
    }
    _write_json(output_root / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--label-root", type=Path, default=DEFAULT_LABEL_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.matrix, args.label_root, args.output_root)
    print(json.dumps({"status": result["status"], "conclusion": result["conclusion"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
