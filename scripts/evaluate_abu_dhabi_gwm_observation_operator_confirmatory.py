#!/usr/bin/env python3
"""Evaluate frozen Abu Dhabi GWM products on the unseen optical cohort.

The queue was frozen before satellite pixels and model outcomes were inspected.
Only two events passed the optical quality gates, so this script produces an
exploratory underpowered audit and never a sufficient confirmatory claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scripts.evaluate_abu_dhabi_gwm_rain_gated_hybrid import _load_checkpoint
    from scripts.run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        _grid_shape,
        _process_safe_training_events,
    )
    from scripts.train_abu_dhabi_five_year_event_gwm import (
        EventLabel,
        _admit_labels,
        _select_events,
    )
    from scripts.train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        _load_events,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )
    from scripts.train_abu_dhabi_gwm_hybrid_residual import (
        _load_linear_model,
        _rollout_event,
    )
    from scripts.train_abu_dhabi_gwm_sentinel2_observation_operator import (
        FEATURE_NAMES,
        FEATURE_SETS,
        binary_metrics,
        calibrate_balanced_probability,
        trajectory_feature_grid,
    )
except ModuleNotFoundError:
    from evaluate_abu_dhabi_gwm_rain_gated_hybrid import _load_checkpoint
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        _grid_shape,
        _process_safe_training_events,
    )
    from train_abu_dhabi_five_year_event_gwm import EventLabel, _admit_labels, _select_events
    from train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        _load_events,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )
    from train_abu_dhabi_gwm_hybrid_residual import _load_linear_model, _rollout_event
    from train_abu_dhabi_gwm_sentinel2_observation_operator import (
        FEATURE_NAMES,
        FEATURE_SETS,
        binary_metrics,
        calibrate_balanced_probability,
        trajectory_feature_grid,
    )


WORKSPACE = Path("/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821")
DEFAULT_ROOT = WORKSPACE / "customer_gwm_observation_operator_confirmatory_validation_20260917_v1"
DEFAULT_PROTOCOL = DEFAULT_ROOT / "frozen_event_protocol.json"
DEFAULT_OBSERVATIONS = DEFAULT_ROOT / "observations_sentinel2"
DEFAULT_PHYSICS = DEFAULT_ROOT / "physics"
DEFAULT_OPERATOR = (
    WORKSPACE
    / "customer_gwm_observation_operator_development_20260917_v1"
    / "operator_v1"
    / "selected_observation_operator.npz"
)
SCHEMA = "gwm.abu_dhabi_flood.observation_operator_confirmatory_evaluation.v1"
REQUIRED_CONFIRMATORY_EVENT_COUNT = 5


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


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"observation_operator_confirmation_json_invalid:{path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _verify_protocol(protocol_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    protocol = _read_json(protocol_path)
    claimed = str(protocol.get("freeze_sha256", ""))
    unhashed = dict(protocol)
    unhashed.pop("freeze_sha256", None)
    if claimed != _canonical_sha256(unhashed):
        raise ValueError("observation_operator_confirmation_freeze_hash_mismatch")
    frozen = protocol.get("frozen_models", {})
    paths = {
        "linear": Path(str(frozen.get("linear_gwm", {}).get("path", ""))),
        "hybrid": Path(str(frozen.get("gated_hybrid_residual", {}).get("path", ""))),
        "operator": Path(str(frozen.get("sentinel2_observation_operator", {}).get("path", ""))),
        "operator_receipt": Path(
            str(frozen.get("sentinel2_observation_operator", {}).get("receipt_path", ""))
        ),
    }
    expected = {
        "linear": str(frozen.get("linear_gwm", {}).get("sha256", "")),
        "hybrid": str(frozen.get("gated_hybrid_residual", {}).get("sha256", "")),
        "operator": str(frozen.get("sentinel2_observation_operator", {}).get("sha256", "")),
        "operator_receipt": str(
            frozen.get("sentinel2_observation_operator", {}).get("receipt_sha256", "")
        ),
    }
    for name, path in paths.items():
        if not path.is_file() or _sha256(path) != expected[name]:
            raise ValueError(f"observation_operator_confirmation_frozen_asset_mismatch:{name}")
    return protocol, paths


def original_event_window(
    depth: np.ndarray,
    times: np.ndarray,
    original_duration_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    depth = np.asarray(depth)
    times = np.asarray(times, dtype=np.float64)
    indices = np.flatnonzero(times <= float(original_duration_seconds) + 1.0e-6)
    if not len(indices) or abs(float(times[indices[-1]]) - original_duration_seconds) > 150.0:
        raise ValueError("observation_operator_confirmation_event_window_mismatch")
    return depth[indices], times[indices]


def _load_operator(path: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    frozen = protocol["frozen_models"]["sentinel2_observation_operator"]
    with np.load(path) as archive:
        operator = {
            "feature_names": tuple(str(value) for value in archive["feature_names"]),
            "scaler_mean": np.asarray(archive["scaler_mean"], dtype=np.float64),
            "scaler_scale": np.asarray(archive["scaler_scale"], dtype=np.float64),
            "coefficients": np.asarray(archive["coefficients"], dtype=np.float64),
            "intercept": float(np.asarray(archive["intercept"]).reshape(-1)[0]),
            "calibration_prevalence": float(
                np.asarray(archive["calibration_prevalence"]).reshape(-1)[0]
            ),
            "probability_threshold": float(
                np.asarray(archive["probability_threshold"]).reshape(-1)[0]
            ),
        }
    size = len(operator["feature_names"])
    if (
        frozen["name"] not in FEATURE_SETS
        or operator["feature_names"] != tuple(FEATURE_SETS[frozen["name"]])
        or any(name not in FEATURE_NAMES for name in operator["feature_names"])
        or operator["scaler_mean"].shape != (size,)
        or operator["scaler_scale"].shape != (size,)
        or operator["coefficients"].shape != (size,)
        or np.any(operator["scaler_scale"] <= 0.0)
        or operator["probability_threshold"] != float(frozen["probability_threshold"])
    ):
        raise ValueError("observation_operator_confirmation_operator_contract_invalid")
    return operator


def _operator_probability(feature_grid: np.ndarray, operator: dict[str, Any]) -> np.ndarray:
    indices = tuple(FEATURE_NAMES.index(name) for name in operator["feature_names"])
    selected = np.asarray(feature_grid[..., indices], dtype=np.float64)
    standardized = (selected - operator["scaler_mean"]) / operator["scaler_scale"]
    logits = standardized @ operator["coefficients"] + operator["intercept"]
    raw = 1.0 / (1.0 + np.exp(-np.clip(logits, -50.0, 50.0)))
    return calibrate_balanced_probability(raw, operator["calibration_prevalence"])


def _load_observation(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {
            "valid_fraction": np.asarray(archive["valid_fraction"], dtype=np.float64),
            "observed_fraction": np.asarray(
                archive["observed_new_surface_water_fraction_of_valid_pixels"],
                dtype=np.float64,
            ),
        }


def _load_trajectory(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path) as archive:
        return (
            np.asarray(archive["depth_m"], dtype=np.float32),
            np.asarray(archive["time_seconds"], dtype=np.float64),
            np.asarray(archive["land_mask"], dtype=bool),
        )


def _nearest_depth(
    depth: np.ndarray, times: np.ndarray, observation_seconds: float
) -> tuple[np.ndarray, float]:
    index = int(np.argmin(np.abs(times - observation_seconds)))
    chosen = float(times[index])
    if abs(chosen - observation_seconds) > 150.0:
        raise ValueError("observation_operator_confirmation_overpass_frame_missing")
    return depth[index], chosen


def _depth_agreement(
    reference: np.ndarray,
    candidate: np.ndarray,
    eligible: np.ndarray,
    threshold_m: float,
) -> dict[str, float | int]:
    reference_values = np.asarray(reference).reshape(-1)[eligible.reshape(-1)]
    candidate_values = np.asarray(candidate).reshape(-1)[eligible.reshape(-1)]
    error = candidate_values - reference_values
    reference_wet = reference_values >= threshold_m
    candidate_wet = candidate_values >= threshold_m
    intersection = int(np.sum(reference_wet & candidate_wet))
    union = int(np.sum(reference_wet | candidate_wet))
    return {
        "eligible_cell_count": int(len(error)),
        "depth_rmse_m": float(np.sqrt(np.mean(error * error))),
        "depth_mae_m": float(np.mean(np.abs(error))),
        "physics_binary_iou": float(intersection / union) if union else 1.0,
    }


def _rollout_trajectories(
    event_id: str,
    forcing_path: Path,
    land: np.ndarray,
    shape: tuple[int, int],
    model: Any,
    static: Any,
    linear: Any,
    gate_scale_mm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    forcing = _read_json(forcing_path)
    hourly = np.asarray(forcing["hourly_precipitation_mm"], dtype=np.float64)
    target = float(forcing["nearest_300_second_model_frame_seconds"])
    times = np.arange(0.0, target + 300.0, 300.0, dtype=np.float64)
    event = EventArrays(
        label=EventLabel(
            event_id,
            "evaluation_only",
            forcing_path.parent,
            forcing_path.parent / "none.json",
            forcing_path.parent / "none.npz",
            forcing_path,
        ),
        depth=np.zeros((len(times), land.size), dtype=np.float32),
        times=times,
        hourly=hourly,
    )
    _, _, linear_frames = _rollout_event(model, event, static, linear, land, shape, 0.0)
    _, _, gated_frames = _rollout_event(model, event, static, linear, land, shape, gate_scale_mm)
    return times, linear_frames, gated_frames


def _aggregate_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = (
        "iou",
        "precision",
        "recall",
        "f1",
        "brier_score",
        "roc_auc",
        "average_precision",
        "average_precision_lift",
    )
    rows: list[dict[str, Any]] = []
    for (space, model_name), group in frame.groupby(["space", "model"], sort=False):
        row: dict[str, Any] = {
            "space": space,
            "model": model_name,
            "event_count": int(len(group)),
        }
        for metric in metrics:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            row[f"macro_{metric}"] = None if values.empty else float(values.mean())
        rows.append(row)
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol_path = args.protocol.expanduser().resolve()
    observation_root = args.observation_root.expanduser().resolve()
    physics_root = args.physics_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    protocol, frozen_paths = _verify_protocol(protocol_path)
    operator = _load_operator(frozen_paths["operator"], protocol)
    observation_batch_path = observation_root / "batch_receipt.json"
    physics_batch_path = physics_root / "batch_receipt.json"
    observation_batch = _read_json(observation_batch_path)
    physics_batch = _read_json(physics_batch_path)
    if physics_batch.get("status") != "completed_underpowered":
        raise ValueError("observation_operator_confirmation_physics_batch_incomplete")
    physics_events = [
        event
        for event in physics_batch.get("events", [])
        if event.get("status") in {"completed", "skipped_completed"}
        and event.get("quality_passed") is True
    ]
    observation_ids = {
        str(event["event_id"])
        for event in observation_batch.get("events", [])
        if event.get("status") == "completed" and event.get("pixel_qc_passed") is True
    }
    physics_ids = {str(event["event_id"]) for event in physics_events}
    if physics_ids != observation_ids or not physics_ids:
        raise ValueError("observation_operator_confirmation_event_set_mismatch")
    protocol_events = {str(event["event_id"]): event for event in protocol["events"]}
    if not physics_ids.issubset(protocol_events):
        raise ValueError("observation_operator_confirmation_event_not_frozen")

    matrix = _select_events(args.matrix.expanduser().resolve())
    labels = _admit_labels(matrix, args.label_root.expanduser().resolve())
    train_labels = [label for label in labels if label.split == "train"]
    process_safe, _ = _process_safe_training_events(matrix, train_labels)
    train_events, land = _load_events(process_safe)
    shape = _grid_shape(labels[0])
    elevation, slope = _terrain_features(args.terrain.expanduser().resolve(), shape)
    susceptibility = _training_max_depth(train_events, shape)
    static = _static_tensor(land, elevation, slope, susceptibility)
    linear = _load_linear_model(frozen_paths["linear"], shape, land)
    model = _load_checkpoint(frozen_paths["hybrid"].parent)
    frozen_models = protocol["frozen_models"]
    gate_scale_mm = float(frozen_models["gated_hybrid_residual"]["gate_scale_mm"])
    depth_threshold_m = float(frozen_models["raw_model_flood_depth_threshold_m"])
    satellite_contract = protocol["frozen_satellite_evaluation"]
    minimum_valid = float(satellite_contract["minimum_250m_paired_valid_fraction"])
    minimum_observed = float(satellite_contract["minimum_250m_observed_water_fraction"])

    output.mkdir(parents=True, exist_ok=True)
    event_rows: list[dict[str, Any]] = []
    depth_rows: list[dict[str, Any]] = []
    output_files: dict[str, str] = {}
    ordered_events = sorted(
        physics_events,
        key=lambda event: int(protocol_events[str(event["event_id"])]["cohort_order"]),
    )
    for physics_event in ordered_events:
        event_id = str(physics_event["event_id"])
        event_root = observation_root / event_id
        observation_receipt = _read_json(event_root / "run_receipt.json")
        forcing_path = event_root / str(
            observation_receipt["external_evaluation"]["forcing_with_zero_rain_tail"]
        )
        forcing = _read_json(forcing_path)
        protocol_event = protocol_events[event_id]
        if (
            forcing.get("event_id") != event_id
            or forcing.get("start_utc") != protocol_event["start_utc"]
        ):
            raise ValueError(
                f"observation_operator_confirmation_forcing_contract_mismatch:{event_id}"
            )
        if (
            float(observation_receipt["method"]["minimum_250m_valid_fraction"]) != minimum_valid
            or float(observation_receipt["method"]["minimum_250m_observed_water_fraction"])
            != minimum_observed
        ):
            raise ValueError(
                f"observation_operator_confirmation_satellite_threshold_mismatch:{event_id}"
            )
        observation_seconds = float(
            observation_receipt["event"]["observation_time_seconds_from_event_start"]
        )
        zero_tail_hours = int(forcing["zero_rainfall_tail_hours"])
        original_duration_hours = len(forcing["hourly_precipitation_mm"]) - zero_tail_hours
        original_duration_seconds = float(original_duration_hours * 3600)
        protocol_duration_seconds = (
            datetime.fromisoformat(protocol_event["end_utc"].replace("Z", "+00:00"))
            - datetime.fromisoformat(protocol_event["start_utc"].replace("Z", "+00:00"))
        ).total_seconds()
        if original_duration_seconds != protocol_duration_seconds:
            raise ValueError(
                f"observation_operator_confirmation_event_duration_mismatch:{event_id}"
            )

        observation_path = event_root / str(observation_receipt["outputs"]["observed_flood_250m"])
        observation = _load_observation(observation_path)
        target_grid = observation["observed_fraction"] >= minimum_observed
        physics_depth, physics_times, physics_land = _load_trajectory(
            Path(str(physics_event["depth_labels"]))
        )
        if not np.array_equal(physics_land.reshape(-1), land.reshape(-1)):
            raise ValueError(f"observation_operator_confirmation_grid_mismatch:{event_id}")
        eligible = (observation["valid_fraction"] >= minimum_valid) & physics_land
        target = target_grid[eligible]
        physics_at_observation, chosen_seconds = _nearest_depth(
            physics_depth, physics_times, observation_seconds
        )
        rollout_times, linear_depth, gated_depth = _rollout_trajectories(
            event_id,
            forcing_path,
            land,
            shape,
            model,
            static,
            linear,
            gate_scale_mm,
        )
        linear_at_observation, linear_seconds = _nearest_depth(
            linear_depth, rollout_times, observation_seconds
        )
        gated_at_observation, gated_seconds = _nearest_depth(
            gated_depth, rollout_times, observation_seconds
        )
        if linear_seconds != chosen_seconds or gated_seconds != chosen_seconds:
            raise ValueError(f"observation_operator_confirmation_model_time_mismatch:{event_id}")

        trajectories = {
            "physics": (physics_depth, physics_times, physics_at_observation),
            "linear_gwm": (linear_depth, rollout_times, linear_at_observation),
            "gated_hybrid_gwm": (gated_depth, rollout_times, gated_at_observation),
        }
        probabilities: dict[str, np.ndarray] = {}
        for name, (depth, times, observation_depth) in trajectories.items():
            raw = binary_metrics(
                target,
                observation_depth.reshape(shape)[eligible] >= depth_threshold_m,
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "cohort_role": protocol_event["cohort_role"],
                    "space": "raw_depth",
                    "model": name,
                    "threshold": depth_threshold_m,
                    **raw,
                }
            )
            event_depth, event_times = original_event_window(
                depth, times, original_duration_seconds
            )
            features = trajectory_feature_grid(
                event_depth,
                event_times,
                physics_land,
                observation_seconds,
            )
            probability = _operator_probability(features, operator)
            probabilities[name] = probability
            operator_metrics = binary_metrics(
                target,
                probability[eligible] >= operator["probability_threshold"],
                probability[eligible],
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "cohort_role": protocol_event["cohort_role"],
                    "space": "frozen_observation_operator",
                    "model": name,
                    "threshold": operator["probability_threshold"],
                    **operator_metrics,
                }
            )
        for name, candidate in (
            ("linear_gwm", linear_at_observation),
            ("gated_hybrid_gwm", gated_at_observation),
        ):
            depth_rows.append(
                {
                    "event_id": event_id,
                    "model": name,
                    **_depth_agreement(
                        physics_at_observation.reshape(shape),
                        candidate.reshape(shape),
                        eligible,
                        depth_threshold_m,
                    ),
                }
            )
        event_output = output / event_id / "blind_predictions_250m.npz"
        event_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            event_output,
            land_mask=physics_land,
            eligible_mask=eligible,
            observed_target=target_grid,
            observation_frame_seconds=np.asarray([chosen_seconds]),
            physics_depth_m=physics_at_observation.reshape(shape),
            linear_gwm_depth_m=linear_at_observation.reshape(shape),
            gated_hybrid_gwm_depth_m=gated_at_observation.reshape(shape),
            physics_operator_probability=probabilities["physics"],
            linear_gwm_operator_probability=probabilities["linear_gwm"],
            gated_hybrid_gwm_operator_probability=probabilities["gated_hybrid_gwm"],
        )
        output_files[event_id] = str(event_output)

    event_frame = pd.DataFrame(event_rows)
    depth_frame = pd.DataFrame(depth_rows)
    aggregate = _aggregate_metrics(event_frame)
    depth_aggregate = [
        {
            "model": model_name,
            "event_count": int(len(group)),
            "macro_depth_rmse_m": float(group["depth_rmse_m"].mean()),
            "macro_depth_mae_m": float(group["depth_mae_m"].mean()),
            "macro_physics_binary_iou": float(group["physics_binary_iou"].mean()),
        }
        for model_name, group in depth_frame.groupby("model", sort=False)
    ]
    iou_deltas: list[dict[str, Any]] = []
    for model_name in ("physics", "linear_gwm", "gated_hybrid_gwm"):
        raw = event_frame[
            (event_frame["model"] == model_name) & (event_frame["space"] == "raw_depth")
        ].set_index("event_id")["iou"]
        operated = event_frame[
            (event_frame["model"] == model_name)
            & (event_frame["space"] == "frozen_observation_operator")
        ].set_index("event_id")["iou"]
        difference = operated - raw
        iou_deltas.append(
            {
                "model": model_name,
                "event_count": int(len(difference)),
                "macro_iou_delta_operator_minus_raw": float(difference.mean()),
                "event_iou_deltas": {
                    str(event_id): float(value) for event_id, value in difference.items()
                },
            }
        )
    event_frame.to_csv(output / "event_metrics.csv", index=False)
    pd.DataFrame(aggregate).to_csv(output / "aggregate_metrics.csv", index=False)
    depth_frame.to_csv(output / "physics_emulation_event_metrics.csv", index=False)
    pd.DataFrame(depth_aggregate).to_csv(
        output / "physics_emulation_aggregate_metrics.csv", index=False
    )
    pd.DataFrame(iou_deltas).drop(columns=["event_iou_deltas"]).to_csv(
        output / "operator_iou_deltas.csv", index=False
    )
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed_exploratory_underpowered",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event_count": len(ordered_events),
        "required_confirmatory_event_count": REQUIRED_CONFIRMATORY_EVENT_COUNT,
        "confirmatory_sample_size_sufficient": False,
        "event_ids": [str(event["event_id"]) for event in ordered_events],
        "frozen_contract": {
            "protocol": str(protocol_path),
            "freeze_sha256": protocol["freeze_sha256"],
            "linear_model_sha256": _sha256(frozen_paths["linear"]),
            "hybrid_model_sha256": _sha256(frozen_paths["hybrid"]),
            "operator_sha256": _sha256(frozen_paths["operator"]),
            "operator_receipt_sha256": _sha256(frozen_paths["operator_receipt"]),
            "gate_scale_mm": gate_scale_mm,
            "raw_depth_threshold_m": depth_threshold_m,
            "operator_probability_threshold": operator["probability_threshold"],
            "operator_feature_names": list(operator["feature_names"]),
        },
        "input_receipts": {
            "observation_batch_sha256": _sha256(observation_batch_path),
            "physics_batch_sha256": _sha256(physics_batch_path),
        },
        "macro_metrics": aggregate,
        "physics_emulation_macro_metrics": depth_aggregate,
        "operator_iou_deltas": iou_deltas,
        "prediction_files": output_files,
        "claim_boundary": [
            (
                "Only two frozen unseen events passed the optical quality gates; "
                "results are exploratory and underpowered."
            ),
            (
                "No model weight, observation-operator weight, threshold, mask, "
                "or event order was changed after outcomes were inspected."
            ),
            (
                "Sentinel-2 is cloud-screened visible new surface water evidence, "
                "not water-depth ground truth."
            ),
            (
                "The observation operator uses the original rainfall-event trajectory "
                "and the frozen post-event satellite lag feature; zero-rain evaluation "
                "tails are excluded from its trajectory summaries."
            ),
            "Raw depth masks are evaluated independently at the satellite overpass frame.",
            (
                "Physics replay fixes the current network and customer 5 m DTM and is "
                "not a reconstruction of historical infrastructure."
            ),
            (
                "These two events cannot authorize runtime promotion or a high-level "
                "confirmatory performance claim."
            ),
        ],
        "outputs": {
            "event_metrics": "event_metrics.csv",
            "aggregate_metrics": "aggregate_metrics.csv",
            "physics_emulation_event_metrics": "physics_emulation_event_metrics.csv",
            "physics_emulation_aggregate_metrics": "physics_emulation_aggregate_metrics.csv",
            "operator_iou_deltas": "operator_iou_deltas.csv",
        },
    }
    result["receipt_sha256"] = _canonical_sha256(result)
    _write_json(output / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--physics-root", type=Path, default=DEFAULT_PHYSICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "evaluation")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--label-root", type=Path, default=DEFAULT_LABEL_ROOT)
    parser.add_argument("--terrain", type=Path, default=DEFAULT_TERRAIN)
    args = parser.parse_args()
    result = run(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "event_count": result["event_count"],
                "macro_metrics": result["macro_metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
