#!/usr/bin/env python3
"""Evaluate frozen physics and GWM outputs on source-specific supplementary events."""

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
    from scripts.evaluate_abu_dhabi_gwm_observation_operator_confirmatory import (
        _depth_agreement,
        _load_operator,
        _load_trajectory,
        _nearest_depth,
        _operator_probability,
        _rollout_trajectories,
        _verify_protocol,
        original_event_window,
    )
    from scripts.evaluate_abu_dhabi_gwm_rain_gated_hybrid import _load_checkpoint
    from scripts.run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        _grid_shape,
        _process_safe_training_events,
    )
    from scripts.train_abu_dhabi_five_year_event_gwm import _admit_labels, _select_events
    from scripts.train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        _load_events,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )
    from scripts.train_abu_dhabi_gwm_hybrid_residual import _load_linear_model
    from scripts.train_abu_dhabi_gwm_sentinel2_observation_operator import (
        binary_metrics,
        trajectory_feature_grid,
    )
except ModuleNotFoundError:
    from evaluate_abu_dhabi_gwm_observation_operator_confirmatory import (
        _depth_agreement,
        _load_operator,
        _load_trajectory,
        _nearest_depth,
        _operator_probability,
        _rollout_trajectories,
        _verify_protocol,
        original_event_window,
    )
    from evaluate_abu_dhabi_gwm_rain_gated_hybrid import _load_checkpoint
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        _grid_shape,
        _process_safe_training_events,
    )
    from train_abu_dhabi_five_year_event_gwm import _admit_labels, _select_events
    from train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        _load_events,
        _static_tensor,
        _terrain_features,
        _training_max_depth,
    )
    from train_abu_dhabi_gwm_hybrid_residual import _load_linear_model
    from train_abu_dhabi_gwm_sentinel2_observation_operator import (
        binary_metrics,
        trajectory_feature_grid,
    )


WORKSPACE = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821"
)
DEFAULT_ROOT = WORKSPACE / "customer_gwm_supplementary_external_validation_20260917_v1"
DEFAULT_COHORT = DEFAULT_ROOT / "frozen_supplementary_final_cohort_v1.json"
DEFAULT_OBSERVATIONS = DEFAULT_ROOT / "observations_final_v1"
DEFAULT_PHYSICS = DEFAULT_ROOT / "physics_final_v1"
DEFAULT_OUTPUT = DEFAULT_ROOT / "evaluation_final_v1"
COHORT_SCHEMA = "gwm.abu_dhabi_flood.supplementary_final_cohort.v1"
SCHEMA = "gwm.abu_dhabi_flood.supplementary_external_validation_evaluation.v1"


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
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"supplementary_evaluation_json_invalid:{path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _verify_cohort(path: Path) -> dict[str, Any]:
    cohort = _read(path)
    claimed = str(cohort.get("freeze_sha256", ""))
    unhashed = dict(cohort)
    unhashed.pop("freeze_sha256", None)
    if cohort.get("schema") != COHORT_SCHEMA or claimed != _canonical_sha256(unhashed):
        raise ValueError("supplementary_evaluation_cohort_freeze_invalid")
    if cohort.get("status") != "frozen_before_supplementary_model_outputs":
        raise ValueError("supplementary_evaluation_cohort_status_invalid")
    return cohort


def _load_observation(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {
            "valid_fraction": np.asarray(archive["valid_fraction"], dtype=np.float64),
            "observed_fraction": np.asarray(
                archive["observed_new_surface_water_fraction_of_valid_pixels"],
                dtype=np.float64,
            ),
            "evaluable_land_mask": np.asarray(
                archive["evaluable_land_mask"], dtype=bool
            ),
        }


def _aggregate_source_specific(frame: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = ("iou", "precision", "recall", "f1", "brier_score")
    rows: list[dict[str, Any]] = []
    for (source, space, model), group in frame.groupby(
        ["observation_source", "space", "model"], sort=False
    ):
        row: dict[str, Any] = {
            "observation_source": source,
            "space": space,
            "model": model,
            "event_count": int(len(group)),
        }
        for metric in metrics:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            row[f"macro_{metric}"] = None if values.empty else float(values.mean())
        rows.append(row)
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    cohort_path = args.cohort.expanduser().resolve()
    observation_root = args.observation_root.expanduser().resolve()
    physics_root = args.physics_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    cohort = _verify_cohort(cohort_path)
    protocol_path = Path(
        cohort["inputs"]["supplementary_protocol"]["path"]
    ).expanduser().resolve()
    if _sha256(protocol_path) != cohort["inputs"]["supplementary_protocol"]["sha256"]:
        raise ValueError("supplementary_evaluation_protocol_hash_mismatch")
    protocol, frozen_paths = _verify_protocol(protocol_path)
    operator = _load_operator(frozen_paths["operator"], protocol)
    physics_batch_path = physics_root / "batch_receipt.json"
    physics_batch = _read(physics_batch_path)
    if physics_batch.get("status") not in {"completed_underpowered", "completed"}:
        raise ValueError("supplementary_evaluation_physics_incomplete")
    physics_events = {
        str(event["event_id"]): event
        for event in physics_batch.get("events", [])
        if event.get("status") in {"completed", "skipped_completed"}
        and event.get("quality_passed") is True
    }
    cohort_events = {str(event["event_id"]): event for event in cohort["events"]}
    if set(physics_events) != set(cohort_events):
        raise ValueError("supplementary_evaluation_event_set_mismatch")

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
    gate_scale_mm = float(protocol["frozen_models"]["gated_hybrid_residual"]["gate_scale_mm"])
    depth_threshold_m = float(protocol["frozen_models"]["raw_model_flood_depth_threshold_m"])

    event_rows: list[dict[str, Any]] = []
    depth_rows: list[dict[str, Any]] = []
    prediction_files: dict[str, str] = {}
    for event in sorted(cohort["events"], key=lambda item: int(item["cohort_order"])):
        event_id = str(event["event_id"])
        source = str(event["observation_source"])
        observation_receipt_path = Path(event["observation_receipt"]["path"])
        if _sha256(observation_receipt_path) != event["observation_receipt"]["sha256"]:
            raise ValueError(f"supplementary_evaluation_observation_hash_mismatch:{event_id}")
        observation_receipt = _read(observation_receipt_path)
        observation_path = Path(event["observation_250m"]["path"])
        if _sha256(observation_path) != event["observation_250m"]["sha256"]:
            raise ValueError(f"supplementary_evaluation_mask_hash_mismatch:{event_id}")
        observation = _load_observation(observation_path)
        minimum_observed = float(
            observation_receipt["pixel_quality"][
                "minimum_250m_observed_new_water_fraction"
            ]
        )
        target_grid = observation["observed_fraction"] >= minimum_observed
        forcing_path = (
            observation_root / event_id / "satellite_overpass_external_evaluation_forcing.json"
        )
        forcing = _read(forcing_path)
        observation_seconds = float(
            forcing["satellite_observation_time_seconds_from_event_start"]
        )
        original_duration_seconds = (
            datetime.fromisoformat(str(event["end_utc"]).replace("Z", "+00:00"))
            - datetime.fromisoformat(str(event["start_utc"]).replace("Z", "+00:00"))
        ).total_seconds()
        physics_event = physics_events[event_id]
        physics_depth, physics_times, physics_land = _load_trajectory(
            Path(str(physics_event["depth_labels"]))
        )
        if not np.array_equal(physics_land.reshape(-1), land.reshape(-1)):
            raise ValueError(f"supplementary_evaluation_grid_mismatch:{event_id}")
        eligible = observation["evaluable_land_mask"] & physics_land
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
            raise ValueError(f"supplementary_evaluation_model_time_mismatch:{event_id}")
        trajectories = {
            "physics": (physics_depth, physics_times, physics_at_observation),
            "linear_gwm": (linear_depth, rollout_times, linear_at_observation),
            "gated_hybrid_gwm": (gated_depth, rollout_times, gated_at_observation),
        }
        operator_probabilities: dict[str, np.ndarray] = {}
        for name, (depth, times, observation_depth) in trajectories.items():
            raw = binary_metrics(
                target,
                observation_depth.reshape(shape)[eligible] >= depth_threshold_m,
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "cohort_role": event["cohort_role"],
                    "observation_source": source,
                    "space": "raw_depth_primary",
                    "model": name,
                    "threshold": depth_threshold_m,
                    **raw,
                }
            )
            if source == "landsat_c2_l2_partial_aoi":
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
                operator_probabilities[name] = probability
                sensitivity = binary_metrics(
                    target,
                    probability[eligible] >= operator["probability_threshold"],
                    probability[eligible],
                )
                event_rows.append(
                    {
                        "event_id": event_id,
                        "cohort_role": event["cohort_role"],
                        "observation_source": source,
                        "space": "sentinel2_operator_cross_optical_sensitivity",
                        "model": name,
                        "threshold": operator["probability_threshold"],
                        **sensitivity,
                    }
                )
        for name, candidate in (
            ("linear_gwm", linear_at_observation),
            ("gated_hybrid_gwm", gated_at_observation),
        ):
            depth_rows.append(
                {
                    "event_id": event_id,
                    "observation_source": source,
                    "model": name,
                    **_depth_agreement(
                        physics_at_observation.reshape(shape),
                        candidate.reshape(shape),
                        eligible,
                        depth_threshold_m,
                    ),
                }
            )
        event_output = output / event_id / "supplementary_predictions_250m.npz"
        event_output.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "land_mask": physics_land,
            "eligible_mask": eligible,
            "observed_target": target_grid,
            "observation_frame_seconds": np.asarray([chosen_seconds]),
            "physics_depth_m": physics_at_observation.reshape(shape),
            "linear_gwm_depth_m": linear_at_observation.reshape(shape),
            "gated_hybrid_gwm_depth_m": gated_at_observation.reshape(shape),
        }
        for name, probability in operator_probabilities.items():
            payload[f"{name}_cross_optical_operator_probability"] = probability
        np.savez_compressed(event_output, **payload)
        prediction_files[event_id] = str(event_output)

    event_frame = pd.DataFrame(event_rows)
    depth_frame = pd.DataFrame(depth_rows)
    aggregate = _aggregate_source_specific(event_frame)
    event_frame.to_csv(output / "source_specific_event_metrics.csv", index=False)
    pd.DataFrame(aggregate).to_csv(
        output / "source_specific_aggregate_metrics.csv", index=False
    )
    depth_frame.to_csv(output / "physics_emulation_event_metrics.csv", index=False)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed_exploratory_supplementary_underpowered",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event_count": len(cohort["events"]),
        "target_event_count": int(cohort["selection"]["target_event_count"]),
        "target_sample_size_reached": False,
        "event_ids": [str(event["event_id"]) for event in cohort["events"]],
        "source_specific_metrics": aggregate,
        "physics_emulation_metrics": depth_rows,
        "prediction_files": prediction_files,
        "frozen_contract": {
            "cohort_path": str(cohort_path),
            "cohort_freeze_sha256": cohort["freeze_sha256"],
            "protocol_freeze_sha256": protocol["freeze_sha256"],
            "linear_model_sha256": _sha256(frozen_paths["linear"]),
            "hybrid_model_sha256": _sha256(frozen_paths["hybrid"]),
            "operator_sha256": _sha256(frozen_paths["operator"]),
            "raw_depth_threshold_m": depth_threshold_m,
            "gate_scale_mm": gate_scale_mm,
        },
        "input_receipts": {
            "physics_batch": str(physics_batch_path),
            "physics_batch_sha256": _sha256(physics_batch_path),
        },
        "claim_boundary": [
            "The two supplementary events remain below the frozen five-event target.",
            "Optical and SAR metrics are source-specific and are not pooled.",
            "The Sentinel-2 observation operator on Landsat is reported only as cross-optical sensitivity; raw-depth comparison is primary.",
            "SAR low-backscatter evidence is vulnerable to urban shadow and smooth non-water false positives.",
            "Neither optical nor SAR masks are observed water depth.",
            "The strict confirmatory cohort remains separate and unchanged.",
        ],
        "outputs": {
            "source_specific_event_metrics": "source_specific_event_metrics.csv",
            "source_specific_aggregate_metrics": "source_specific_aggregate_metrics.csv",
            "physics_emulation_event_metrics": "physics_emulation_event_metrics.csv",
        },
    }
    result["receipt_sha256"] = _canonical_sha256(result)
    _write(output / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--physics-root", type=Path, default=DEFAULT_PHYSICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
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
                "source_specific_metrics": result["source_specific_metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
