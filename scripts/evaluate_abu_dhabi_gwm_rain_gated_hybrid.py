#!/usr/bin/env python3
"""Select a validation-only rainfall gate for the frozen hybrid GWM checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

try:
    from scripts.run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        DEFAULT_OBSERVATION_ROOT,
        EXTERNAL_HOLDOUT_EVENT_ID,
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
    from scripts.train_abu_dhabi_gwm_hybrid_residual import (
        DEFAULT_LINEAR_MODEL,
        HybridResidualCorrection,
        _evaluate,
        _load_linear_model,
        _rollout_event,
        _sentinel_comparison,
    )
except ModuleNotFoundError:
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        DEFAULT_OBSERVATION_ROOT,
        EXTERNAL_HOLDOUT_EVENT_ID,
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
    from train_abu_dhabi_gwm_hybrid_residual import (
        DEFAULT_LINEAR_MODEL,
        HybridResidualCorrection,
        _evaluate,
        _load_linear_model,
        _rollout_event,
        _sentinel_comparison,
    )


DEFAULT_HYBRID_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_hybrid_residual_20260916_v1"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_rain_gated_hybrid_20260916_v1"
)
GATE_SCALES_MM: tuple[float | None, ...] = (0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, None)
SCHEMA = "gwm.abu_dhabi_flood.rain_gated_hybrid.v1"


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


def _gate_name(scale: float | None) -> str:
    if scale is None:
        return "ungated"
    if scale == 0.0:
        return "linear_fallback"
    return f"exp_cumulative_rain_scale_{scale:g}mm"


def _load_checkpoint(root: Path) -> HybridResidualCorrection:
    checkpoint_path = root / "hybrid_residual.pt"
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = HybridResidualCorrection()
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model


def run(
    matrix_path: Path,
    label_root: Path,
    terrain_path: Path,
    linear_model_path: Path,
    hybrid_root: Path,
    observation_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    matrix_path = matrix_path.expanduser().resolve()
    label_root = label_root.expanduser().resolve()
    terrain_path = terrain_path.expanduser().resolve()
    linear_model_path = linear_model_path.expanduser().resolve()
    hybrid_root = hybrid_root.expanduser().resolve()
    observation_root = observation_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    hybrid_receipt = json.loads((hybrid_root / "run_receipt.json").read_text(encoding="utf-8"))
    if hybrid_receipt.get("status") != "completed":
        raise ValueError("gwm_gated_hybrid_checkpoint_not_completed")
    protocol = {
        "schema": f"{SCHEMA}.protocol",
        "status": "frozen_before_gate_scoring",
        "hybrid_checkpoint_sha256": _sha256(hybrid_root / "hybrid_residual.pt"),
        "linear_model_sha256": _sha256(linear_model_path),
        "gate_scales_mm": ["ungated" if scale is None else scale for scale in GATE_SCALES_MM],
        "gate_formula": "correction_multiplier=exp(-cumulative_rainfall_mm/gate_scale_mm)",
        "gate_zero_policy": "scale 0 is exact linear-model fallback",
        "selection": "validation macro rollout RMSE then macro rollout MAE",
        "external_holdout": EXTERNAL_HOLDOUT_EVENT_ID,
        "external_holdout_training_forbidden": True,
        "claim_boundary": (
            "This gate was designed after legacy test and April 2024 model results had been "
            "inspected. Test and external scores are exploratory post-hoc evidence only."
        ),
    }
    _write_json(output_root / "experiment_protocol.json", protocol)
    matrix = _select_events(matrix_path)
    labels = _admit_labels(matrix, label_root)
    by_split = {
        split: [label for label in labels if label.split == split]
        for split in ("train", "validation", "test", "external_test_2024_april")
    }
    train_labels, _ = _process_safe_training_events(matrix, by_split["train"])
    train_events, land = _load_events(train_labels)
    validation_events, validation_land = _load_events(by_split["validation"])
    if not np.array_equal(land, validation_land):
        raise ValueError("gwm_gated_hybrid_validation_grid_contract_mismatch")
    shape = _grid_shape(labels[0])
    elevation, slope = _terrain_features(terrain_path, shape)
    susceptibility = _training_max_depth(train_events, shape)
    static = _static_tensor(land, elevation, slope, susceptibility)
    linear = _load_linear_model(linear_model_path, shape, land)
    model = _load_checkpoint(hybrid_root)
    selection_rows: list[dict[str, Any]] = []
    for scale in GATE_SCALES_MM:
        metrics, _ = _evaluate(
            model,
            validation_events,
            static,
            linear,
            land,
            shape,
            scale,
        )
        selection_rows.append(
            {
                "gate": _gate_name(scale),
                "gate_scale_mm": scale,
                **metrics,
            }
        )
    selected_row = min(
        selection_rows,
        key=lambda row: (float(row["macro_rmse_m"]), float(row["macro_mae_m"])),
    )
    selected_scale = next(
        scale for scale in GATE_SCALES_MM if _gate_name(scale) == selected_row["gate"]
    )
    aggregate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    split_events = {
        "validation": validation_events,
        "test": _load_events(by_split["test"])[0],
        "external_test_2024_april": _load_events(by_split["external_test_2024_april"])[0],
    }
    for split, events in split_events.items():
        metrics, rows = _evaluate(
            model,
            events,
            static,
            linear,
            land,
            shape,
            selected_scale,
        )
        aggregate_rows.append({"split": split, **metrics})
        event_rows.extend({"split": split, **row} for row in rows)
    inference_event = split_events["external_test_2024_april"][0]
    timings: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        _rollout_event(
            model,
            inference_event,
            static,
            linear,
            land,
            shape,
            selected_scale,
        )
        timings.append(time.perf_counter() - started)
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
        selected_scale,
    )
    pd.DataFrame(selection_rows).to_csv(output_root / "gate_selection.csv", index=False)
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
        "selected_gate": selected_row["gate"],
        "selected_gate_scale_mm": selected_scale,
        "linear_fallback_selected": selected_scale == 0.0,
        "metrics": {row["split"]: row for row in aggregate_rows},
        "sentinel2_posthoc_sensitivity": sentinel_rows,
        "inference_benchmark": benchmark,
        "confirmatory_external_validation_required": True,
        "outputs": {
            "protocol": "experiment_protocol.json",
            "gate_selection": "gate_selection.csv",
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
    parser.add_argument("--hybrid-root", type=Path, default=DEFAULT_HYBRID_ROOT)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(
        args.matrix,
        args.label_root,
        args.terrain,
        args.linear_model,
        args.hybrid_root,
        args.observation_root,
        args.output_root,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_gate": result["selected_gate"],
                "linear_fallback_selected": result["linear_fallback_selected"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
