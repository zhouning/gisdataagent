#!/usr/bin/env python3
"""Train a compact convolutional rollout baseline for the Abu Dhabi flood GWM."""

from __future__ import annotations

import argparse
import hashlib
import json
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
        _event_arrays,
        _grid_shape,
        _process_safe_training_events,
        _read_json,
    )
    from scripts.train_abu_dhabi_five_year_event_gwm import (
        EventLabel,
        _admit_labels,
        _select_events,
    )
except ModuleNotFoundError:
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        DEFAULT_OBSERVATION_ROOT,
        EXTERNAL_HOLDOUT_EVENT_ID,
        Metrics,
        _compare_model,
        _event_arrays,
        _grid_shape,
        _process_safe_training_events,
        _read_json,
    )
    from train_abu_dhabi_five_year_event_gwm import (
        EventLabel,
        _admit_labels,
        _select_events,
    )


DEFAULT_TERRAIN = Path(
    "/Users/zhouning/Downloads/阿布扎比/"
    "全市双向耦合试点_客户DTM_250m_20260910_v2高程门控/terrain_grid.npz"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_conv_baseline_20260916_v1"
)
SCHEMA = "gwm.abu_dhabi_flood.conv_rollout_baseline.v1"
SEED = 20260916
WIDTH = 16
TRAIN_STEPS = 1200
BATCH_SIZE = 2
ROLLOUT_STEPS = 6
VALIDATION_INTERVAL = 200
LEARNING_RATE = 2.0e-3
DELTA_LIMIT_M = 0.05
WET_THRESHOLD_M = 0.01
MAXIMUM_PLAUSIBLE_DEPTH_M = 10.0
INPUT_CHANNELS = (
    "current_depth_m",
    "previous_depth_m",
    "previous_delta_div_0_01m",
    "rainfall_intensity_mm_h_div_10",
    "cumulative_rainfall_mm_div_50",
    "trailing_3h_rainfall_mm_div_30",
    "peak_rainfall_so_far_mm_h_div_10",
    "terrain_robust_zscore",
    "terrain_slope_div_0_05",
    "training_max_depth_div_2m",
    "land_mask",
)


@dataclass(frozen=True)
class EventArrays:
    label: EventLabel
    depth: np.ndarray
    times: np.ndarray
    hourly: np.ndarray


class ResidualBlock(nn.Module):
    def __init__(self, width: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(width, width, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(width, width, kernel_size=3, padding=1),
        )
        self.activation = nn.GELU()

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.layers(inputs))


class ConvRolloutBaseline(nn.Module):
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
        return DELTA_LIMIT_M * torch.tanh(self.head(self.blocks(self.stem(inputs))))


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


def _cumulative_rainfall(hourly: np.ndarray, seconds: float) -> float:
    bounded = min(max(float(seconds), 0.0), float(len(hourly)) * 3600.0)
    complete_hours = min(int(bounded // 3600.0), len(hourly))
    cumulative = float(hourly[:complete_hours].sum())
    if complete_hours < len(hourly):
        cumulative += float(hourly[complete_hours]) * ((bounded / 3600.0) - complete_hours)
    return cumulative


def _rain_features(hourly: np.ndarray, seconds: float) -> tuple[float, float, float, float]:
    hour_index = min(len(hourly) - 1, int(seconds // 3600.0))
    cumulative = _cumulative_rainfall(hourly, seconds)
    trailing = cumulative - _cumulative_rainfall(hourly, seconds - 3.0 * 3600.0)
    return (
        float(hourly[hour_index] / 10.0),
        cumulative / 50.0,
        trailing / 30.0,
        float(np.max(hourly[: hour_index + 1]) / 10.0),
    )


def _terrain_features(path: Path, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path) as archive:
        vertices = np.asarray(archive["values"], dtype=np.float32)
    if vertices.shape != (shape[0] + 1, shape[1] + 1):
        raise ValueError("gwm_conv_terrain_grid_shape_invalid")
    cells = 0.25 * (
        vertices[:-1, :-1]
        + vertices[1:, :-1]
        + vertices[:-1, 1:]
        + vertices[1:, 1:]
    )
    median = float(np.nanmedian(cells))
    scale = float(np.nanpercentile(cells, 75) - np.nanpercentile(cells, 25))
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("gwm_conv_terrain_scale_invalid")
    elevation = np.clip((cells - median) / scale, -5.0, 5.0).astype(np.float32)
    gradient_y, gradient_x = np.gradient(cells, 250.0, 250.0)
    slope = np.clip(np.hypot(gradient_x, gradient_y) / 0.05, 0.0, 5.0).astype(np.float32)
    return elevation, slope


def _load_events(labels: list[EventLabel]) -> tuple[list[EventArrays], np.ndarray]:
    events: list[EventArrays] = []
    land: np.ndarray | None = None
    for label in labels:
        depth, times, event_land, hourly = _event_arrays(label)
        if land is None:
            land = event_land
        elif not np.array_equal(land, event_land):
            raise ValueError(f"gwm_conv_grid_contract_mismatch:{label.event_id}")
        events.append(
            EventArrays(
                label=label,
                depth=depth.astype(np.float32, copy=False),
                times=times,
                hourly=hourly,
            )
        )
    if land is None:
        raise ValueError("gwm_conv_events_empty")
    return events, land


def _training_max_depth(events: list[EventArrays], shape: tuple[int, int]) -> np.ndarray:
    maximum = np.zeros(int(np.prod(shape)), dtype=np.float32)
    for event in events:
        maximum = np.maximum(maximum, np.max(event.depth, axis=0))
    return np.clip(maximum.reshape(shape) / 2.0, 0.0, 2.0).astype(np.float32)


def _static_tensor(
    land: np.ndarray,
    elevation: np.ndarray,
    slope: np.ndarray,
    susceptibility: np.ndarray,
) -> torch.Tensor:
    shape = elevation.shape
    return torch.from_numpy(
        np.stack(
            (
                elevation,
                slope,
                susceptibility,
                land.reshape(shape).astype(np.float32),
            )
        )
    )


def _model_inputs(
    current: torch.Tensor,
    previous: torch.Tensor,
    rain: tuple[float, float, float, float],
    static: torch.Tensor,
) -> torch.Tensor:
    if current.ndim != 4 or current.shape[1] != 1:
        raise ValueError("gwm_conv_current_shape_invalid")
    batch = current.shape[0]
    static_batch = static.unsqueeze(0).expand(batch, -1, -1, -1)
    rain_maps = torch.as_tensor(
        rain,
        dtype=current.dtype,
        device=current.device,
    ).reshape(1, 4, 1, 1)
    rain_maps = rain_maps.expand(batch, -1, current.shape[2], current.shape[3])
    previous_delta = torch.clamp((current - previous) / 0.01, -5.0, 5.0)
    return torch.cat((current, previous, previous_delta, rain_maps, static_batch), dim=1)


def _sample_batch(
    events: list[EventArrays],
    batch_size: int,
    rollout_steps: int,
    rng: random.Random,
    shape: tuple[int, int],
) -> tuple[list[EventArrays], list[int], torch.Tensor, torch.Tensor]:
    selected: list[EventArrays] = []
    indices: list[int] = []
    current: list[np.ndarray] = []
    previous: list[np.ndarray] = []
    eligible = [event for event in events if len(event.times) > rollout_steps + 1]
    for _ in range(batch_size):
        event = rng.choice(eligible)
        index = rng.randrange(0, len(event.times) - rollout_steps - 1)
        selected.append(event)
        indices.append(index)
        current.append(event.depth[index].reshape(shape))
        previous.append(event.depth[max(0, index - 1)].reshape(shape))
    return (
        selected,
        indices,
        torch.from_numpy(np.stack(current)[:, None]),
        torch.from_numpy(np.stack(previous)[:, None]),
    )


def _rollout_loss(
    model: ConvRolloutBaseline,
    selected: list[EventArrays],
    indices: list[int],
    current: torch.Tensor,
    previous: torch.Tensor,
    static: torch.Tensor,
    land: torch.Tensor,
    rollout_steps: int,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    for offset in range(rollout_steps):
        predictions: list[torch.Tensor] = []
        truths: list[torch.Tensor] = []
        for batch_index, (event, start_index) in enumerate(zip(selected, indices, strict=True)):
            frame_index = start_index + offset
            rain = _rain_features(event.hourly, float(event.times[frame_index]))
            inputs = _model_inputs(
                current[batch_index : batch_index + 1],
                previous[batch_index : batch_index + 1],
                rain,
                static,
            )
            delta = model(inputs)
            prediction = torch.clamp(current[batch_index : batch_index + 1] + delta, min=0.0)
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
    model: ConvRolloutBaseline,
    event: EventArrays,
    static: torch.Tensor,
    land: np.ndarray,
    shape: tuple[int, int],
) -> tuple[Metrics, float, np.ndarray]:
    active = np.flatnonzero(land)
    land_tensor = torch.from_numpy(land.reshape(shape).astype(np.float32))[None, None]
    current = torch.from_numpy(event.depth[0].reshape(shape))[None, None]
    previous = current.clone()
    metrics = Metrics()
    maximum = 0.0
    frames = [event.depth[0].copy()]
    with torch.inference_mode():
        for index in range(len(event.times) - 1):
            rain = _rain_features(event.hourly, float(event.times[index]))
            delta = model(_model_inputs(current, previous, rain, static))
            prediction = torch.clamp(current + delta, min=0.0) * land_tensor
            flat = prediction.numpy().reshape(-1)
            maximum = max(maximum, float(flat.max()))
            metrics.update(event.depth[index + 1, active], flat[active])
            frames.append(flat.astype(np.float32))
            previous = current
            current = prediction
    return metrics, maximum, np.stack(frames)


def _evaluate(
    model: ConvRolloutBaseline,
    events: list[EventArrays],
    static: torch.Tensor,
    land: np.ndarray,
    shape: tuple[int, int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aggregate = Metrics()
    event_rows: list[dict[str, Any]] = []
    maximum = 0.0
    for event in events:
        metrics, event_maximum, _ = _rollout_event(model, event, static, land, shape)
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
    aggregate_row = {
        **aggregate.as_dict(),
        "event_count": len(events),
        "macro_rmse_m": float(np.mean([row["rmse_m"] for row in event_rows])),
        "macro_mae_m": float(np.mean([row["mae_m"] for row in event_rows])),
        "macro_inundation_iou": float(np.mean([row["inundation_iou"] for row in event_rows])),
        "macro_inundation_f1": float(np.mean([row["inundation_f1"] for row in event_rows])),
        "maximum_predicted_depth_m": maximum,
        "stability_violation": maximum > MAXIMUM_PLAUSIBLE_DEPTH_M,
    }
    return aggregate_row, event_rows


def _sentinel_comparison(
    model: ConvRolloutBaseline,
    static: torch.Tensor,
    land: np.ndarray,
    shape: tuple[int, int],
    observation_root: Path,
    output_root: Path,
) -> list[dict[str, Any]]:
    receipt = _read_json(
        observation_root / "run_receipt.json",
        "gwm_conv_observation_receipt_invalid",
    )
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or receipt.get("event", {}).get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID
        or receipt.get("event", {}).get("training_forbidden") is not True
    ):
        raise ValueError("gwm_conv_observation_contract_invalid")
    forcing_path = observation_root / str(
        receipt["external_evaluation"]["forcing_with_zero_rain_tail"]
    )
    forcing = _read_json(forcing_path, "gwm_conv_observation_forcing_invalid")
    hourly = np.asarray(forcing["hourly_precipitation_mm"], dtype=np.float64)
    target_seconds = float(
        round(float(receipt["event"]["observation_time_seconds_from_event_start"]) / 300.0)
        * 300.0
    )
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
    _, _, frames = _rollout_event(model, event, static, land, shape)
    rollout_path = output_root / "conv_sentinel2_phase_depth_250m.npz"
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
            observation_seconds=float(receipt["event"]["observation_time_seconds_from_event_start"]),
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
    observation_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    matrix_path = matrix_path.expanduser().resolve()
    label_root = label_root.expanduser().resolve()
    terrain_path = terrain_path.expanduser().resolve()
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
    process_safe_labels, quarantined = _process_safe_training_events(matrix, by_split["train"])
    protocol = {
        "schema": f"{SCHEMA}.protocol",
        "status": "frozen_before_training",
        "random_seed": SEED,
        "process_safe_training_events": [label.event_id for label in process_safe_labels],
        "quarantined_events": quarantined,
        "validation_events": [label.event_id for label in by_split["validation"]],
        "legacy_test_events": [label.event_id for label in by_split["test"]],
        "external_holdout": EXTERNAL_HOLDOUT_EVENT_ID,
        "external_holdout_training_forbidden": True,
        "input_channels": list(INPUT_CHANNELS),
        "architecture": "two 3x3 residual blocks, width 16, bounded 5-minute depth residual",
        "training": {
            "steps": TRAIN_STEPS,
            "batch_size": BATCH_SIZE,
            "rollout_steps": ROLLOUT_STEPS,
            "validation_interval": VALIDATION_INTERVAL,
            "learning_rate": LEARNING_RATE,
            "delta_limit_m": DELTA_LIMIT_M,
            "loss": "wet-weighted Huber loss in millimetres over autoregressive rollout",
        },
        "checkpoint_selection": "validation macro rollout RMSE then macro rollout MAE",
        "claim_boundary": (
            "The two legacy test events and April 2024 score were exposed during earlier "
            "research; their new-model results are post-hoc and require a future untouched "
            "confirmatory cohort."
        ),
    }
    _write_json(output_root / "experiment_protocol.json", protocol)
    train_events, land = _load_events(process_safe_labels)
    validation_events, validation_land = _load_events(by_split["validation"])
    if not np.array_equal(land, validation_land):
        raise ValueError("gwm_conv_validation_grid_contract_mismatch")
    shape = _grid_shape(labels[0])
    elevation, slope = _terrain_features(terrain_path, shape)
    susceptibility = _training_max_depth(train_events, shape)
    static = _static_tensor(land, elevation, slope, susceptibility)
    land_tensor = torch.from_numpy(land.reshape(shape).astype(np.float32))[None, None]
    model = ConvRolloutBaseline()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1.0e-5)
    rng = random.Random(SEED)
    history: list[dict[str, Any]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_score = (float("inf"), float("inf"))
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
            land_tensor,
            ROLLOUT_STEPS,
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        if step == 1 or step % VALIDATION_INTERVAL == 0:
            model.eval()
            validation, _ = _evaluate(model, validation_events, static, land, shape)
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
                for row in history:
                    row["selected"] = False
                history[-1]["selected"] = True
    if best_state is None:
        raise ValueError("gwm_conv_no_stable_checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    training_seconds = time.perf_counter() - started
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_channels": INPUT_CHANNELS,
            "width": WIDTH,
            "delta_limit_m": DELTA_LIMIT_M,
            "shape": shape,
        },
        output_root / "conv_rollout_baseline.pt",
    )
    np.savez_compressed(
        output_root / "static_features.npz",
        elevation=elevation,
        slope=slope,
        training_max_depth=susceptibility,
        land_mask=land.reshape(shape),
    )
    split_events = {
        "validation": validation_events,
        "test": _load_events(by_split["test"])[0],
        "external_test_2024_april": _load_events(by_split["external_test_2024_april"])[0],
    }
    aggregate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for split, events in split_events.items():
        aggregate, rows = _evaluate(model, events, static, land, shape)
        aggregate_rows.append({"split": split, **aggregate})
        event_rows.extend({"split": split, **row} for row in rows)
    inference_event = split_events["external_test_2024_april"][0]
    timings: list[float] = []
    for _ in range(5):
        inference_started = time.perf_counter()
        _rollout_event(model, inference_event, static, land, shape)
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
        "selected_checkpoint_step": next(row["step"] for row in history if row["selected"]),
        "training_seconds": training_seconds,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "metrics": {row["split"]: row for row in aggregate_rows},
        "sentinel2_posthoc_sensitivity": sentinel_rows,
        "inference_benchmark": benchmark,
        "confirmatory_external_validation_required": True,
        "outputs": {
            "protocol": "experiment_protocol.json",
            "model": "conv_rollout_baseline.pt",
            "static_features": "static_features.npz",
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
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(
        args.matrix,
        args.label_root,
        args.terrain,
        args.observation_root,
        args.output_root,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_checkpoint_step": result["selected_checkpoint_step"],
                "parameter_count": result["parameter_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
