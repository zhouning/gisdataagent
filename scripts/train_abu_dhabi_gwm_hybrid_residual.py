#!/usr/bin/env python3
"""Train a bounded convolutional residual on the validated linear Abu Dhabi GWM."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn

try:
    from scripts.run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        DEFAULT_OBSERVATION_ROOT,
        EXTERNAL_HOLDOUT_EVENT_ID,
        Metrics,
        _compare_model,
        _grid_shape,
        _process_safe_training_events,
        _read_json,
    )
    from scripts.train_abu_dhabi_five_year_event_gwm import (
        EventLabel,
        _admit_labels,
        _select_events,
    )
    from scripts.train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        ResidualBlock,
        _load_events,
        _rain_features,
        _sample_batch,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )
except ModuleNotFoundError:
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        DEFAULT_OBSERVATION_ROOT,
        EXTERNAL_HOLDOUT_EVENT_ID,
        Metrics,
        _compare_model,
        _grid_shape,
        _process_safe_training_events,
        _read_json,
    )
    from train_abu_dhabi_five_year_event_gwm import (
        EventLabel,
        _admit_labels,
        _select_events,
    )
    from train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        ResidualBlock,
        _load_events,
        _rain_features,
        _sample_batch,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )


DEFAULT_LINEAR_MODEL = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_paper_experiments_20260916_v1/selected_model_coefficients.npz"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_hybrid_residual_20260916_v1"
)
SCHEMA = "gwm.abu_dhabi_flood.linear_conv_hybrid.v1"
SEED = 20260916
WIDTH = 16
TRAIN_STEPS = 800
BATCH_SIZE = 2
ROLLOUT_STEPS = 6
VALIDATION_INTERVAL = 200
LEARNING_RATE = 1.0e-3
CORRECTION_LIMIT_M = 0.01
WET_THRESHOLD_M = 0.01
MAXIMUM_PLAUSIBLE_DEPTH_M = 10.0
INPUT_CHANNELS = (
    "current_depth_m",
    "previous_depth_m",
    "previous_delta_div_0_01m",
    "linear_next_depth_m",
    "linear_delta_div_0_01m",
    "rainfall_intensity_mm_h_div_10",
    "cumulative_rainfall_mm_div_50",
    "trailing_3h_rainfall_mm_div_30",
    "peak_rainfall_so_far_mm_h_div_10",
    "terrain_robust_zscore",
    "terrain_slope_div_0_05",
    "training_max_depth_div_2m",
    "land_mask",
)


class HybridResidualCorrection(nn.Module):
    def __init__(self, input_channels: int = len(INPUT_CHANNELS), width: int = WIDTH) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(input_channels, width, kernel_size=3, padding=1),
            nn.GELU(),
        )
        self.blocks = nn.Sequential(ResidualBlock(width), ResidualBlock(width))
        self.head = nn.Conv2d(width, 1, kernel_size=1)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return CORRECTION_LIMIT_M * torch.tanh(self.head(self.blocks(self.stem(inputs))))


@dataclass(frozen=True)
class LinearModel:
    coefficients: torch.Tensor
    land: torch.Tensor


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


def _load_linear_model(path: Path, shape: tuple[int, int], land: np.ndarray) -> LinearModel:
    with np.load(path) as archive:
        coefficients = np.asarray(archive["coefficients"], dtype=np.float32)
        model_land = np.asarray(archive["land_mask"], dtype=bool).reshape(-1)
        feature_names = tuple(str(value) for value in archive["feature_names"])
    if coefficients.shape != (land.size, 4) or not np.array_equal(model_land, land):
        raise ValueError("gwm_hybrid_linear_model_grid_invalid")
    if feature_names != (
        "intercept",
        "depth_m",
        "rainfall_intensity_mm_h_div_10",
        "cumulative_rainfall_mm_div_50",
    ):
        raise ValueError("gwm_hybrid_linear_model_features_invalid")
    coefficient_tensor = torch.from_numpy(coefficients.reshape(*shape, 4).transpose(2, 0, 1))
    land_tensor = torch.from_numpy(land.reshape(shape).astype(np.float32))[None, None]
    return LinearModel(coefficient_tensor[None], land_tensor)


def _linear_prediction(
    current: torch.Tensor,
    rain: tuple[float, float, float, float],
    linear: LinearModel,
) -> torch.Tensor:
    coefficients = linear.coefficients.to(current.device)
    prediction = (
        coefficients[:, 0:1]
        + coefficients[:, 1:2] * current
        + coefficients[:, 2:3] * rain[0]
        + coefficients[:, 3:4] * rain[1]
    )
    return torch.clamp(prediction, min=0.0) * linear.land.to(current.device)


def _hybrid_inputs(
    current: torch.Tensor,
    previous: torch.Tensor,
    linear_next: torch.Tensor,
    rain: tuple[float, float, float, float],
    static: torch.Tensor,
) -> torch.Tensor:
    batch = current.shape[0]
    rain_maps = torch.as_tensor(
        rain,
        dtype=current.dtype,
        device=current.device,
    ).reshape(1, 4, 1, 1)
    rain_maps = rain_maps.expand(batch, -1, current.shape[2], current.shape[3])
    static_batch = static.unsqueeze(0).expand(batch, -1, -1, -1)
    previous_delta = torch.clamp((current - previous) / 0.01, -5.0, 5.0)
    linear_delta = torch.clamp((linear_next - current) / 0.01, -5.0, 5.0)
    return torch.cat(
        (
            current,
            previous,
            previous_delta,
            linear_next,
            linear_delta,
            rain_maps,
            static_batch,
        ),
        dim=1,
    )


def _hybrid_next(
    model: HybridResidualCorrection,
    current: torch.Tensor,
    previous: torch.Tensor,
    rain: tuple[float, float, float, float],
    static: torch.Tensor,
    linear: LinearModel,
    gate_scale_mm: float | None = None,
) -> torch.Tensor:
    linear_next = _linear_prediction(current, rain, linear)
    correction = model(_hybrid_inputs(current, previous, linear_next, rain, static))
    if gate_scale_mm is not None:
        if gate_scale_mm < 0.0:
            raise ValueError("gwm_hybrid_gate_scale_invalid")
        gate = 0.0 if gate_scale_mm == 0.0 else math.exp(-(rain[1] * 50.0) / gate_scale_mm)
        correction = correction * gate
    return torch.clamp(linear_next + correction, min=0.0) * linear.land.to(current.device)


def _rollout_loss(
    model: HybridResidualCorrection,
    selected: list[EventArrays],
    indices: list[int],
    current: torch.Tensor,
    previous: torch.Tensor,
    static: torch.Tensor,
    linear: LinearModel,
    rollout_steps: int,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    land = linear.land.to(current.device)
    for offset in range(rollout_steps):
        predictions: list[torch.Tensor] = []
        truths: list[torch.Tensor] = []
        for batch_index, (event, start_index) in enumerate(zip(selected, indices, strict=True)):
            frame_index = start_index + offset
            rain = _rain_features(event.hourly, float(event.times[frame_index]))
            prediction = _hybrid_next(
                model,
                current[batch_index : batch_index + 1],
                previous[batch_index : batch_index + 1],
                rain,
                static,
                linear,
            )
            predictions.append(prediction)
            truth = torch.from_numpy(event.depth[frame_index + 1].reshape(static.shape[1:]))
            truths.append(truth[None, None])
        prediction_batch = torch.cat(predictions)
        truth_batch = torch.cat(truths).to(prediction_batch.device)
        wet_weight = 1.0 + 4.0 * (
            (truth_batch >= WET_THRESHOLD_M) | (current >= WET_THRESHOLD_M)
        )
        error_mm = (prediction_batch - truth_batch) * 1000.0
        absolute = torch.abs(error_mm)
        huber = torch.where(absolute < 1.0, 0.5 * absolute.square(), absolute - 0.5)
        losses.append((huber * wet_weight * land).sum() / (wet_weight * land).sum())
        previous = current
        current = prediction_batch
    return torch.stack(losses).mean()


def _rollout_event(
    model: HybridResidualCorrection,
    event: EventArrays,
    static: torch.Tensor,
    linear: LinearModel,
    land: np.ndarray,
    shape: tuple[int, int],
    gate_scale_mm: float | None = None,
) -> tuple[Metrics, float, np.ndarray]:
    active = np.flatnonzero(land)
    current = torch.from_numpy(event.depth[0].reshape(shape))[None, None]
    previous = current.clone()
    metrics = Metrics()
    maximum = 0.0
    frames = [event.depth[0].copy()]
    with torch.inference_mode():
        for index in range(len(event.times) - 1):
            rain = _rain_features(event.hourly, float(event.times[index]))
            prediction = _hybrid_next(
                model,
                current,
                previous,
                rain,
                static,
                linear,
                gate_scale_mm,
            )
            flat = prediction.numpy().reshape(-1)
            metrics.update(event.depth[index + 1, active], flat[active])
            maximum = max(maximum, float(flat.max()))
            frames.append(flat.astype(np.float32))
            previous = current
            current = prediction
    return metrics, maximum, np.stack(frames)


def _evaluate(
    model: HybridResidualCorrection,
    events: list[EventArrays],
    static: torch.Tensor,
    linear: LinearModel,
    land: np.ndarray,
    shape: tuple[int, int],
    gate_scale_mm: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aggregate = Metrics()
    event_rows: list[dict[str, Any]] = []
    maximum = 0.0
    for event in events:
        metrics, event_maximum, _ = _rollout_event(
            model,
            event,
            static,
            linear,
            land,
            shape,
            gate_scale_mm,
        )
        aggregate.sample_count += metrics.sample_count
        aggregate.sum_squared_error += metrics.sum_squared_error
        aggregate.sum_absolute_error += metrics.sum_absolute_error
        aggregate.intersection += metrics.intersection
        aggregate.union += metrics.union
        aggregate.predicted_wet += metrics.predicted_wet
        aggregate.truth_wet += metrics.truth_wet
        maximum = max(maximum, event_maximum)
        event_rows.append(
            {
                "event_id": event.label.event_id,
                "split": event.label.split,
                **metrics.as_dict(),
                "maximum_predicted_depth_m": event_maximum,
            }
        )
    return (
        {
            **aggregate.as_dict(),
            "event_count": len(events),
            "macro_rmse_m": float(np.mean([row["rmse_m"] for row in event_rows])),
            "macro_mae_m": float(np.mean([row["mae_m"] for row in event_rows])),
            "macro_inundation_iou": float(
                np.mean([row["inundation_iou"] for row in event_rows])
            ),
            "macro_inundation_f1": float(
                np.mean([row["inundation_f1"] for row in event_rows])
            ),
            "maximum_predicted_depth_m": maximum,
            "stability_violation": maximum > MAXIMUM_PLAUSIBLE_DEPTH_M,
        },
        event_rows,
    )


def _sentinel_comparison(
    model: HybridResidualCorrection,
    static: torch.Tensor,
    linear: LinearModel,
    land: np.ndarray,
    shape: tuple[int, int],
    observation_root: Path,
    output_root: Path,
    gate_scale_mm: float | None = None,
) -> list[dict[str, Any]]:
    receipt = _read_json(
        observation_root / "run_receipt.json",
        "gwm_hybrid_observation_receipt_invalid",
    )
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or receipt.get("event", {}).get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID
        or receipt.get("event", {}).get("training_forbidden") is not True
    ):
        raise ValueError("gwm_hybrid_observation_contract_invalid")
    forcing_path = observation_root / str(
        receipt["external_evaluation"]["forcing_with_zero_rain_tail"]
    )
    forcing = _read_json(forcing_path, "gwm_hybrid_observation_forcing_invalid")
    hourly = np.asarray(forcing["hourly_precipitation_mm"], dtype=np.float64)
    observation_seconds = float(receipt["event"]["observation_time_seconds_from_event_start"])
    target_seconds = float(round(observation_seconds / 300.0) * 300.0)
    times = np.arange(0.0, target_seconds + 300.0, 300.0)
    event = EventArrays(
        label=EventLabel(
            EXTERNAL_HOLDOUT_EVENT_ID,
            "external_test_2024_april",
            output_root,
            output_root / "none.json",
            output_root / "none.npz",
            forcing_path,
        ),
        depth=np.zeros((len(times), land.size), dtype=np.float32),
        times=times,
        hourly=hourly,
    )
    _, _, frames = _rollout_event(
        model,
        event,
        static,
        linear,
        land,
        shape,
        gate_scale_mm,
    )
    rollout_path = output_root / "hybrid_sentinel2_phase_depth_250m.npz"
    np.savez_compressed(
        rollout_path,
        depth_m=frames[-1:],
        time_seconds=np.asarray([target_seconds]),
        land_mask=land.reshape(shape),
    )
    observation_path = observation_root / str(receipt["outputs"]["observed_flood_250m"])
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
            observation_seconds=observation_seconds,
            minimum_valid_fraction=float(receipt["method"]["minimum_250m_valid_fraction"]),
            minimum_observed_fraction=float(
                receipt["method"]["minimum_250m_observed_water_fraction"]
            ),
            depth_threshold_m=threshold,
        )
        rows.append(
            {
                "depth_threshold_m": threshold,
                **comparison["metrics"],
                "selection_use": "forbidden_posthoc_sensitivity_only",
            }
        )
    return rows


def run(
    matrix_path: Path,
    label_root: Path,
    terrain_path: Path,
    linear_model_path: Path,
    observation_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    matrix_path = matrix_path.expanduser().resolve()
    label_root = label_root.expanduser().resolve()
    terrain_path = terrain_path.expanduser().resolve()
    linear_model_path = linear_model_path.expanduser().resolve()
    observation_root = observation_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    matrix = _select_events(matrix_path)
    labels = _admit_labels(matrix, label_root)
    by_split = {
        split: [label for label in labels if label.split == split]
        for split in ("train", "validation", "test", "external_test_2024_april")
    }
    train_labels, quarantined = _process_safe_training_events(matrix, by_split["train"])
    protocol = {
        "schema": f"{SCHEMA}.protocol",
        "status": "frozen_before_training",
        "random_seed": SEED,
        "linear_model_path": str(linear_model_path),
        "linear_model_sha256": _sha256(linear_model_path),
        "process_safe_training_events": [label.event_id for label in train_labels],
        "quarantined_events": quarantined,
        "validation_events": [label.event_id for label in by_split["validation"]],
        "legacy_test_events": [label.event_id for label in by_split["test"]],
        "external_holdout": EXTERNAL_HOLDOUT_EVENT_ID,
        "external_holdout_training_forbidden": True,
        "input_channels": list(INPUT_CHANNELS),
        "architecture": (
            "validated cellwise linear GWM plus two-block convolutional correction bounded "
            "to +/-0.01 m per 300-second step"
        ),
        "training": {
            "steps": TRAIN_STEPS,
            "batch_size": BATCH_SIZE,
            "rollout_steps": ROLLOUT_STEPS,
            "validation_interval": VALIDATION_INTERVAL,
            "learning_rate": LEARNING_RATE,
            "loss": "wet-weighted Huber in millimetres over autoregressive rollout",
        },
        "checkpoint_selection": (
            "validation macro rollout RMSE then MAE; checkpoint 0 is the unchanged linear GWM"
        ),
        "claim_boundary": (
            "Legacy test and April 2024 results are post-hoc because prior model results were "
            "already inspected; a future untouched cohort is required for confirmation."
        ),
    }
    _write_json(output_root / "experiment_protocol.json", protocol)
    train_events, land = _load_events(train_labels)
    validation_events, validation_land = _load_events(by_split["validation"])
    if not np.array_equal(land, validation_land):
        raise ValueError("gwm_hybrid_validation_grid_contract_mismatch")
    shape = _grid_shape(labels[0])
    elevation, slope = _terrain_features(terrain_path, shape)
    susceptibility = _training_max_depth(train_events, shape)
    static = _static_tensor(land, elevation, slope, susceptibility)
    linear = _load_linear_model(linear_model_path, shape, land)
    model = HybridResidualCorrection()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1.0e-5)
    rng = random.Random(SEED)
    history: list[dict[str, Any]] = []
    baseline_validation, _ = _evaluate(model, validation_events, static, linear, land, shape)
    history.append(
        {
            "step": 0,
            "training_loss": None,
            **baseline_validation,
            "selected": True,
        }
    )
    best_score = (
        float(baseline_validation["macro_rmse_m"]),
        float(baseline_validation["macro_mae_m"]),
    )
    best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    selected_step = 0
    started = time.perf_counter()
    for step in range(1, TRAIN_STEPS + 1):
        model.train()
        selected, indices, current, previous = _sample_batch(
            train_events,
            BATCH_SIZE,
            ROLLOUT_STEPS,
            rng,
            shape,
        )
        optimizer.zero_grad(set_to_none=True)
        loss = _rollout_loss(
            model,
            selected,
            indices,
            current,
            previous,
            static,
            linear,
            ROLLOUT_STEPS,
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        if step % VALIDATION_INTERVAL == 0:
            model.eval()
            validation, _ = _evaluate(model, validation_events, static, linear, land, shape)
            score = (float(validation["macro_rmse_m"]), float(validation["macro_mae_m"]))
            history.append(
                {
                    "step": step,
                    "training_loss": float(loss.detach()),
                    **validation,
                    "selected": False,
                }
            )
            if not validation["stability_violation"] and score < best_score:
                best_score = score
                best_state = {
                    key: value.detach().clone()
                    for key, value in model.state_dict().items()
                }
                selected_step = step
                for row in history:
                    row["selected"] = False
                history[-1]["selected"] = True
    model.load_state_dict(best_state)
    model.eval()
    training_seconds = time.perf_counter() - started
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_channels": INPUT_CHANNELS,
            "width": WIDTH,
            "correction_limit_m": CORRECTION_LIMIT_M,
            "shape": shape,
            "linear_model_sha256": _sha256(linear_model_path),
        },
        output_root / "hybrid_residual.pt",
    )
    split_events = {
        "validation": validation_events,
        "test": _load_events(by_split["test"])[0],
        "external_test_2024_april": _load_events(by_split["external_test_2024_april"])[0],
    }
    aggregate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for split, events in split_events.items():
        aggregate, rows = _evaluate(model, events, static, linear, land, shape)
        aggregate_rows.append({"split": split, **aggregate})
        event_rows.extend({"split": split, **row} for row in rows)
    inference_event = split_events["external_test_2024_april"][0]
    timings: list[float] = []
    for _ in range(5):
        inference_started = time.perf_counter()
        _rollout_event(model, inference_event, static, linear, land, shape)
        timings.append(time.perf_counter() - inference_started)
    benchmark = {
        "event_id": inference_event.label.event_id,
        "repeat_count": len(timings),
        "wall_seconds": timings,
        "median_wall_seconds": float(np.median(timings)),
        "simulated_duration_seconds": float(inference_event.times[-1]),
        "realtime_factor": float(inference_event.times[-1] / np.median(timings)),
        "physics_speedup": None,
        "physics_speedup_reason": (
            "physics wall-clock timing was not retained in the frozen label receipts"
        ),
    }
    sentinel_rows = _sentinel_comparison(
        model,
        static,
        linear,
        land,
        shape,
        observation_root,
        output_root,
    )
    pd.DataFrame(history).to_csv(output_root / "training_history.csv", index=False)
    pd.DataFrame(aggregate_rows).to_csv(output_root / "aggregate_metrics.csv", index=False)
    pd.DataFrame(event_rows).to_csv(output_root / "event_metrics.csv", index=False)
    pd.DataFrame(sentinel_rows).to_csv(
        output_root / "sentinel2_posthoc_sensitivity.csv",
        index=False,
    )
    _write_json(output_root / "inference_benchmark.json", benchmark)
    result = {
        "schema": SCHEMA,
        "status": "completed",
        "selected_checkpoint_step": selected_step,
        "linear_fallback_selected": selected_step == 0,
        "training_seconds": training_seconds,
        "correction_parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "metrics": {row["split"]: row for row in aggregate_rows},
        "sentinel2_posthoc_sensitivity": sentinel_rows,
        "inference_benchmark": benchmark,
        "confirmatory_external_validation_required": True,
        "outputs": {
            "protocol": "experiment_protocol.json",
            "model": "hybrid_residual.pt",
            "training_history": "training_history.csv",
            "aggregate_metrics": "aggregate_metrics.csv",
            "event_metrics": "event_metrics.csv",
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
    parser.add_argument("--terrain", type=Path, default=DEFAULT_TERRAIN)
    parser.add_argument("--linear-model", type=Path, default=DEFAULT_LINEAR_MODEL)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(
        args.matrix,
        args.label_root,
        args.terrain,
        args.linear_model,
        args.observation_root,
        args.output_root,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_checkpoint_step": result["selected_checkpoint_step"],
                "linear_fallback_selected": result["linear_fallback_selected"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
