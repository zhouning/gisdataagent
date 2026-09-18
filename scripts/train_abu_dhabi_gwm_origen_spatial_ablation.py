#!/usr/bin/env python3
"""Run a leakage-aware spatial ablation of the Origen GWM static prior."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from scipy.ndimage import binary_dilation

try:
    from scripts.run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        Metrics,
        _grid_shape,
        _process_safe_training_events,
    )
    from scripts.train_abu_dhabi_five_year_event_gwm import _admit_labels, _select_events
    from scripts.train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        _load_events,
        _rain_features,
        _sample_batch,
        _terrain_features,
    )
    from scripts.train_abu_dhabi_gwm_hybrid_residual import (
        BATCH_SIZE,
        CORRECTION_LIMIT_M,
        DEFAULT_LINEAR_MODEL,
        LEARNING_RATE,
        MAXIMUM_PLAUSIBLE_DEPTH_M,
        ROLLOUT_STEPS,
        WET_THRESHOLD_M,
        WIDTH,
        HybridResidualCorrection,
        LinearModel,
        _hybrid_next,
        _load_linear_model,
    )
except ModuleNotFoundError:
    from run_abu_dhabi_gwm_paper_experiments import (
        DEFAULT_LABEL_ROOT,
        DEFAULT_MATRIX,
        Metrics,
        _grid_shape,
        _process_safe_training_events,
    )
    from train_abu_dhabi_five_year_event_gwm import _admit_labels, _select_events
    from train_abu_dhabi_gwm_conv_baseline import (
        DEFAULT_TERRAIN,
        EventArrays,
        _load_events,
        _rain_features,
        _sample_batch,
        _terrain_features,
    )
    from train_abu_dhabi_gwm_hybrid_residual import (
        BATCH_SIZE,
        CORRECTION_LIMIT_M,
        DEFAULT_LINEAR_MODEL,
        LEARNING_RATE,
        MAXIMUM_PLAUSIBLE_DEPTH_M,
        ROLLOUT_STEPS,
        WET_THRESHOLD_M,
        WIDTH,
        HybridResidualCorrection,
        LinearModel,
        _hybrid_next,
        _load_linear_model,
    )


DEFAULT_ORIGEN_PRIOR = Path(
    "~/.local/share/gisdataagent/private/abu_dhabi_stormwater/"
    "origen_hotspots_batch1/gwm_static_prior_250m.npz"
).expanduser()
DEFAULT_ORIGEN_RECEIPT = DEFAULT_ORIGEN_PRIOR.with_name("gwm_static_prior_receipt.json")
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_origen_spatial_ablation_20260918_v1"
)
SCHEMA = "gwm.abu_dhabi_flood.origen_spatial_ablation.v1"
SEED = 20260918
TRAINING_STEPS = 200
VALIDATION_INTERVAL = 50
SPATIAL_FOLDS = 4
SPATIAL_BLOCK_SIZE_CELLS = 20
SPATIAL_BUFFER_CELLS = 5
BASE_INPUT_CHANNELS = (
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
    "land_mask",
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


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()


def _read_hashed_receipt(path: Path, expected_schema: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"gwm_origen_receipt_invalid:{path.name}") from exc
    if not isinstance(value, dict) or value.get("schema") != expected_schema:
        raise ValueError(f"gwm_origen_receipt_schema_invalid:{path.name}")
    declared = value.get("receipt_sha256")
    unhashed = dict(value)
    unhashed.pop("receipt_sha256", None)
    if not isinstance(declared, str) or declared != _canonical_hash(unhashed):
        raise ValueError(f"gwm_origen_receipt_hash_mismatch:{path.name}")
    return value


def _load_origen_prior(
    prior_path: Path,
    receipt_path: Path,
    terrain_path: Path,
    shape: tuple[int, int],
    land: np.ndarray,
) -> tuple[np.ndarray, tuple[str, ...], dict[str, Any]]:
    prior_path = prior_path.expanduser().resolve()
    receipt_path = receipt_path.expanduser().resolve()
    terrain_path = terrain_path.expanduser().resolve()
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("gwm_origen_prior_receipt_invalid") from exc
    if not isinstance(receipt, dict):
        raise ValueError("gwm_origen_prior_receipt_invalid")
    if receipt.get("status") != "ready_prospective_training_only":
        raise ValueError("gwm_origen_prior_not_prospective")
    admission = receipt.get("admission")
    if not isinstance(admission, dict) or admission.get("required_validation") != (
        "spatially_blocked_ablation_against_the_same_model_without_origen_features"
    ):
        raise ValueError("gwm_origen_prior_admission_invalid")
    if receipt.get("artifact", {}).get("sha256") != _sha256(prior_path):
        raise ValueError("gwm_origen_prior_hash_mismatch")
    if receipt.get("grid", {}).get("source_sha256") != _sha256(terrain_path):
        raise ValueError("gwm_origen_prior_terrain_hash_mismatch")

    with np.load(prior_path) as archive:
        features = np.asarray(archive["features"], dtype=np.float32)
        feature_names = tuple(str(value) for value in archive["feature_names"].tolist())
        prior_land = np.asarray(archive["land_mask"], dtype=bool)
        prior_x = np.asarray(archive["x"], dtype=np.float64)
        prior_y = np.asarray(archive["y"], dtype=np.float64)
        epsg = int(np.asarray(archive["epsg"]).item())
    with np.load(terrain_path) as archive:
        terrain_x = np.asarray(archive["x"], dtype=np.float64)
        terrain_y = np.asarray(archive["y"], dtype=np.float64)
    expected_x = 0.5 * (terrain_x[:-1] + terrain_x[1:])
    expected_y = 0.5 * (terrain_y[:-1] + terrain_y[1:])
    if features.ndim != 3 or features.shape[1:] != shape:
        raise ValueError("gwm_origen_prior_shape_invalid")
    if len(feature_names) != features.shape[0]:
        raise ValueError("gwm_origen_prior_feature_names_invalid")
    if tuple(receipt.get("feature_names", [])) != feature_names:
        raise ValueError("gwm_origen_prior_receipt_features_mismatch")
    if not np.array_equal(prior_land, land.reshape(shape)):
        raise ValueError("gwm_origen_prior_land_mask_mismatch")
    if not np.allclose(prior_x, expected_x) or not np.allclose(prior_y, expected_y):
        raise ValueError("gwm_origen_prior_coordinates_mismatch")
    if epsg != 32640 or not np.isfinite(features).all():
        raise ValueError("gwm_origen_prior_values_invalid")
    if float(features.min()) < 0.0 or float(features.max()) > 1.0 + 1.0e-6:
        raise ValueError("gwm_origen_prior_values_out_of_range")
    features[:, ~prior_land] = 0.0
    active = int(np.count_nonzero(np.any(features[:, prior_land] > 0.0, axis=1)))
    if active != int(receipt.get("active_feature_count", -1)):
        raise ValueError("gwm_origen_prior_active_feature_count_mismatch")
    evidence = {
        "prior_filename": prior_path.name,
        "prior_sha256": _sha256(prior_path),
        "receipt_filename": receipt_path.name,
        "receipt_sha256": _sha256(receipt_path),
        "terrain_filename": terrain_path.name,
        "terrain_sha256": _sha256(terrain_path),
        "feature_count": len(feature_names),
        "active_feature_count": active,
        "epsg": epsg,
        "shape": list(shape),
    }
    return features, feature_names, evidence


def _spatial_fold_masks(
    land: np.ndarray,
    shape: tuple[int, int],
    *,
    fold_count: int,
    block_size_cells: int,
    buffer_cells: int,
) -> list[dict[str, np.ndarray]]:
    if fold_count < 2 or block_size_cells <= 2 * buffer_cells or buffer_cells < 0:
        raise ValueError("gwm_origen_spatial_fold_parameters_invalid")
    land_grid = land.reshape(shape).astype(bool)
    row, column = np.indices(shape)
    fold_ids = ((row // block_size_cells) * 3 + column // block_size_cells) % fold_count
    masks: list[dict[str, np.ndarray]] = []
    for fold in range(fold_count):
        holdout = land_grid & (fold_ids == fold)
        excluded = binary_dilation(holdout, iterations=buffer_cells) if buffer_cells else holdout
        training = land_grid & ~excluded
        buffer = land_grid & excluded & ~holdout
        if not np.any(holdout) or not np.any(training):
            raise ValueError(f"gwm_origen_spatial_fold_empty:{fold}")
        if np.any(training & holdout):
            raise ValueError(f"gwm_origen_spatial_fold_overlap:{fold}")
        masks.append({"training": training, "holdout": holdout, "buffer": buffer})
    return masks


def _static_tensor(
    land: np.ndarray,
    elevation: np.ndarray,
    slope: np.ndarray,
    origen: np.ndarray,
) -> torch.Tensor:
    return torch.from_numpy(
        np.concatenate(
            (
                elevation[None],
                slope[None],
                land.reshape(elevation.shape).astype(np.float32)[None],
                origen,
            ),
            axis=0,
        ).astype(np.float32)
    )


def _masked_rollout_loss(
    model: HybridResidualCorrection,
    selected: list[EventArrays],
    indices: list[int],
    current: torch.Tensor,
    previous: torch.Tensor,
    static: torch.Tensor,
    linear: LinearModel,
    training_mask: torch.Tensor,
    rollout_steps: int,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    mask = training_mask.to(current.device)
    for offset in range(rollout_steps):
        predictions: list[torch.Tensor] = []
        truths: list[torch.Tensor] = []
        for batch_index, (event, start_index) in enumerate(zip(selected, indices, strict=True)):
            frame_index = start_index + offset
            prediction = _hybrid_next(
                model,
                current[batch_index : batch_index + 1],
                previous[batch_index : batch_index + 1],
                _rain_features(event.hourly, float(event.times[frame_index])),
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
        weighted_mask = wet_weight * mask
        losses.append((huber * weighted_mask).sum() / weighted_mask.sum())
        previous = current
        current = prediction_batch
    return torch.stack(losses).mean()


def _masked_rollout_event(
    model: HybridResidualCorrection,
    event: EventArrays,
    static: torch.Tensor,
    linear: LinearModel,
    evaluation_mask: np.ndarray,
    shape: tuple[int, int],
) -> tuple[Metrics, float]:
    active = np.flatnonzero(evaluation_mask.reshape(-1))
    current = torch.from_numpy(event.depth[0].reshape(shape))[None, None]
    previous = current.clone()
    metrics = Metrics()
    maximum = 0.0
    with torch.inference_mode():
        for index in range(len(event.times) - 1):
            prediction = _hybrid_next(
                model,
                current,
                previous,
                _rain_features(event.hourly, float(event.times[index])),
                static,
                linear,
            )
            flat = prediction.numpy().reshape(-1)
            metrics.update(event.depth[index + 1, active], flat[active])
            maximum = max(maximum, float(np.max(flat[active])))
            previous = current
            current = prediction
    return metrics, maximum


def _evaluate(
    model: HybridResidualCorrection,
    events: list[EventArrays],
    static: torch.Tensor,
    linear: LinearModel,
    evaluation_mask: np.ndarray,
    shape: tuple[int, int],
) -> dict[str, Any]:
    aggregate = Metrics()
    event_rows: list[dict[str, Any]] = []
    maximum = 0.0
    for event in events:
        metrics, event_maximum = _masked_rollout_event(
            model, event, static, linear, evaluation_mask, shape
        )
        aggregate.sample_count += metrics.sample_count
        aggregate.sum_squared_error += metrics.sum_squared_error
        aggregate.sum_absolute_error += metrics.sum_absolute_error
        aggregate.intersection += metrics.intersection
        aggregate.union += metrics.union
        aggregate.predicted_wet += metrics.predicted_wet
        aggregate.truth_wet += metrics.truth_wet
        maximum = max(maximum, event_maximum)
        event_rows.append(metrics.as_dict())
    return {
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
    }


def _train_variant(
    *,
    variant: str,
    fold: int,
    seed: int,
    train_events: list[EventArrays],
    validation_events: list[EventArrays],
    test_events: list[EventArrays],
    land: np.ndarray,
    shape: tuple[int, int],
    elevation: np.ndarray,
    slope: np.ndarray,
    origen_features: np.ndarray,
    origen_names: tuple[str, ...],
    linear: LinearModel,
    training_mask: np.ndarray,
    holdout_mask: np.ndarray,
    training_steps: int,
    validation_interval: int,
    protocol_sha256: str,
    output_root: Path,
    resume: bool,
) -> dict[str, Any]:
    variant_root = output_root / f"fold_{fold}" / variant
    receipt_path = variant_root / "run_receipt.json"
    if resume and receipt_path.is_file():
        receipt = _read_hashed_receipt(receipt_path, f"{SCHEMA}.variant")
        model_path = output_root / str(receipt.get("outputs", {}).get("model") or "")
        if (
            receipt.get("variant") != variant
            or receipt.get("fold") != fold
            or receipt.get("protocol_sha256") != protocol_sha256
            or not model_path.is_file()
            or receipt.get("model_sha256") != _sha256(model_path)
        ):
            raise ValueError(f"gwm_origen_resume_variant_invalid:{fold}:{variant}")
        return receipt
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    used_origen = origen_features if variant == "origen_static_prior" else np.zeros_like(
        origen_features
    )
    static = _static_tensor(land, elevation, slope, used_origen)
    input_channels = BASE_INPUT_CHANNELS + tuple(f"origen::{name}" for name in origen_names)
    model = HybridResidualCorrection(input_channels=len(input_channels), width=WIDTH)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1.0e-5)
    training_mask_tensor = torch.from_numpy(training_mask.astype(np.float32))[None, None]
    rng = random.Random(seed)
    history: list[dict[str, Any]] = []
    model.eval()
    baseline = _evaluate(model, validation_events, static, linear, holdout_mask, shape)
    history.append({"step": 0, "training_loss": None, **baseline, "selected": False})
    started = time.perf_counter()
    for step in range(1, training_steps + 1):
        model.train()
        selected, indices, current, previous = _sample_batch(
            train_events, BATCH_SIZE, ROLLOUT_STEPS, rng, shape
        )
        optimizer.zero_grad(set_to_none=True)
        loss = _masked_rollout_loss(
            model,
            selected,
            indices,
            current,
            previous,
            static,
            linear,
            training_mask_tensor,
            ROLLOUT_STEPS,
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        if step % validation_interval == 0 or step == training_steps:
            model.eval()
            validation = _evaluate(
                model, validation_events, static, linear, holdout_mask, shape
            )
            history.append(
                {
                    "step": step,
                    "training_loss": float(loss.detach()),
                    **validation,
                    "selected": step == training_steps,
                }
            )
    model.eval()
    validation = _evaluate(model, validation_events, static, linear, holdout_mask, shape)
    test = _evaluate(model, test_events, static, linear, holdout_mask, shape)
    variant_root.mkdir(parents=True, exist_ok=True)
    model_path = variant_root / "hybrid_residual.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_channels": input_channels,
            "width": WIDTH,
            "correction_limit_m": CORRECTION_LIMIT_M,
            "shape": shape,
            "variant": variant,
            "fold": fold,
            "protocol_sha256": protocol_sha256,
        },
        model_path,
    )
    pd.DataFrame(history).to_csv(variant_root / "training_history.csv", index=False)
    receipt = {
        "schema": f"{SCHEMA}.variant",
        "status": "completed_exploratory",
        "variant": variant,
        "fold": fold,
        "seed": seed,
        "selected_checkpoint_step": training_steps,
        "linear_fallback_selected": False,
        "training_seconds": time.perf_counter() - started,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "input_channels": list(input_channels),
        "origen_values": (
            "observed_static_prior" if variant == "origen_static_prior" else "all_zero"
        ),
        "metrics": {"validation_holdout": validation, "legacy_test_holdout": test},
        "protocol_sha256": protocol_sha256,
        "outputs": {
            "model": str(model_path.relative_to(output_root)),
            "training_history": str(
                (variant_root / "training_history.csv").relative_to(output_root)
            ),
        },
    }
    receipt["model_sha256"] = _sha256(model_path)
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    _write_json(variant_root / "run_receipt.json", receipt)
    return receipt


def run(
    matrix_path: Path,
    label_root: Path,
    terrain_path: Path,
    linear_model_path: Path,
    origen_prior_path: Path,
    origen_receipt_path: Path,
    output_root: Path,
    *,
    training_steps: int = TRAINING_STEPS,
    validation_interval: int = VALIDATION_INTERVAL,
    spatial_folds: int = SPATIAL_FOLDS,
    spatial_block_size_cells: int = SPATIAL_BLOCK_SIZE_CELLS,
    spatial_buffer_cells: int = SPATIAL_BUFFER_CELLS,
    resume: bool = False,
) -> dict[str, Any]:
    paths = [matrix_path, label_root, terrain_path, linear_model_path]
    matrix_path, label_root, terrain_path, linear_model_path = [
        path.expanduser().resolve() for path in paths
    ]
    output_root = output_root.expanduser().resolve()
    if training_steps <= 0 or validation_interval <= 0:
        raise ValueError("gwm_origen_training_schedule_invalid")
    if output_root.exists() and any(output_root.iterdir()) and not resume:
        raise ValueError(f"gwm_origen_output_not_empty:{output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))

    matrix = _select_events(matrix_path)
    labels = _admit_labels(matrix, label_root)
    by_split = {
        split: [label for label in labels if label.split == split]
        for split in ("train", "validation", "test")
    }
    train_labels, quarantined = _process_safe_training_events(matrix, by_split["train"])
    train_events, land = _load_events(train_labels)
    validation_events, validation_land = _load_events(by_split["validation"])
    test_events, test_land = _load_events(by_split["test"])
    if not np.array_equal(land, validation_land) or not np.array_equal(land, test_land):
        raise ValueError("gwm_origen_event_grid_contract_mismatch")
    shape = _grid_shape(labels[0])
    elevation, slope = _terrain_features(terrain_path, shape)
    origen, origen_names, prior_evidence = _load_origen_prior(
        origen_prior_path, origen_receipt_path, terrain_path, shape, land
    )
    masks = _spatial_fold_masks(
        land,
        shape,
        fold_count=spatial_folds,
        block_size_cells=spatial_block_size_cells,
        buffer_cells=spatial_buffer_cells,
    )
    linear = _load_linear_model(linear_model_path, shape, land)
    fold_inventory = []
    active_any = np.any(origen > 0.0, axis=0)
    for fold, masks_for_fold in enumerate(masks):
        fold_inventory.append(
            {
                "fold": fold,
                "training_land_cell_count": int(np.count_nonzero(masks_for_fold["training"])),
                "holdout_land_cell_count": int(np.count_nonzero(masks_for_fold["holdout"])),
                "buffer_land_cell_count": int(np.count_nonzero(masks_for_fold["buffer"])),
                "holdout_cells_with_any_origen_feature": int(
                    np.count_nonzero(masks_for_fold["holdout"] & active_any)
                ),
            }
        )
    if any(row["holdout_cells_with_any_origen_feature"] == 0 for row in fold_inventory):
        raise ValueError("gwm_origen_spatial_fold_without_prior_support")

    existing_protocol: dict[str, Any] | None = None
    protocol_path = output_root / "experiment_protocol.json"
    if resume:
        try:
            existing_protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("gwm_origen_resume_protocol_invalid") from exc
        if not isinstance(existing_protocol, dict):
            raise ValueError("gwm_origen_resume_protocol_invalid")
    protocol = {
        "schema": f"{SCHEMA}.protocol",
        "status": "frozen_before_training",
        "created_at_utc": (
            existing_protocol.get("created_at_utc")
            if existing_protocol
            else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ),
        "random_seed": SEED,
        "source_artifacts": {
            "matrix": {"filename": matrix_path.name, "sha256": _sha256(matrix_path)},
            "terrain": {"filename": terrain_path.name, "sha256": _sha256(terrain_path)},
            "linear_model": {
                "filename": linear_model_path.name,
                "sha256": _sha256(linear_model_path),
            },
            "origen": prior_evidence,
        },
        "events": {
            "training": [label.event_id for label in train_labels],
            "quarantined": quarantined,
            "validation": [label.event_id for label in by_split["validation"]],
            "legacy_test": [label.event_id for label in by_split["test"]],
        },
        "variants": ["zero_origen", "origen_static_prior"],
        "paired_design": (
            "Identical architecture, initialization seed, event batches, optimizer, spatial "
            "masks, and checkpoint rule; only the 15 Origen channel values differ."
        ),
        "input_channels": list(BASE_INPUT_CHANNELS)
        + [f"origen::{name}" for name in origen_names],
        "label_derived_static_channels": [],
        "spatial_blocking": {
            "fold_count": spatial_folds,
            "block_size_cells": spatial_block_size_cells,
            "block_size_m": spatial_block_size_cells * 250,
            "buffer_cells": spatial_buffer_cells,
            "buffer_m": spatial_buffer_cells * 250,
            "assignment": "((row // block_size) * 3 + column // block_size) % fold_count",
            "fold_inventory": fold_inventory,
        },
        "training": {
            "steps": training_steps,
            "validation_interval": validation_interval,
            "batch_size": BATCH_SIZE,
            "rollout_steps": ROLLOUT_STEPS,
            "learning_rate": LEARNING_RATE,
            "checkpoint_selection": (
                "fixed final step shared by both variants; validation is diagnostic only"
            ),
        },
        "external_validation": {
            "used_for_training_or_selection": False,
            "current_confirmatory_cohort_use": "forbidden_model_postdates_existing_cohort",
            "required_next_step": "future_independent_event_cohort_frozen_before_scoring",
        },
        "claim_boundary": (
            "This is a prospective exploratory spatial ablation against hydraulic simulation "
            "labels. It is not independent observed-depth validation or engineering admission."
        ),
    }
    protocol["protocol_sha256"] = _canonical_hash(protocol)
    if existing_protocol is not None:
        if existing_protocol != protocol:
            raise ValueError("gwm_origen_resume_protocol_mismatch")
    else:
        _write_json(protocol_path, protocol)

    receipts: list[dict[str, Any]] = []
    for fold, masks_for_fold in enumerate(masks):
        for variant in ("zero_origen", "origen_static_prior"):
            receipt = _train_variant(
                variant=variant,
                fold=fold,
                seed=SEED + fold,
                train_events=train_events,
                validation_events=validation_events,
                test_events=test_events,
                land=land,
                shape=shape,
                elevation=elevation,
                slope=slope,
                origen_features=origen,
                origen_names=origen_names,
                linear=linear,
                training_mask=masks_for_fold["training"],
                holdout_mask=masks_for_fold["holdout"],
                training_steps=training_steps,
                validation_interval=validation_interval,
                protocol_sha256=protocol["protocol_sha256"],
                output_root=output_root,
                resume=resume,
            )
            receipts.append(receipt)
            print(
                json.dumps(
                    {
                        "progress": "variant_completed",
                        "fold": fold,
                        "variant": variant,
                        "selected_checkpoint_step": receipt[
                            "selected_checkpoint_step"
                        ],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    rows: list[dict[str, Any]] = []
    for fold in range(spatial_folds):
        by_variant = {row["variant"]: row for row in receipts if row["fold"] == fold}
        baseline = by_variant["zero_origen"]
        treated = by_variant["origen_static_prior"]
        for split in ("validation_holdout", "legacy_test_holdout"):
            baseline_metrics = baseline["metrics"][split]
            treated_metrics = treated["metrics"][split]
            rows.append(
                {
                    "fold": fold,
                    "split": split,
                    "baseline_macro_rmse_m": baseline_metrics["macro_rmse_m"],
                    "origen_macro_rmse_m": treated_metrics["macro_rmse_m"],
                    "delta_macro_rmse_m": (
                        treated_metrics["macro_rmse_m"] - baseline_metrics["macro_rmse_m"]
                    ),
                    "baseline_macro_mae_m": baseline_metrics["macro_mae_m"],
                    "origen_macro_mae_m": treated_metrics["macro_mae_m"],
                    "delta_macro_mae_m": (
                        treated_metrics["macro_mae_m"] - baseline_metrics["macro_mae_m"]
                    ),
                    "baseline_macro_inundation_iou": baseline_metrics[
                        "macro_inundation_iou"
                    ],
                    "origen_macro_inundation_iou": treated_metrics[
                        "macro_inundation_iou"
                    ],
                    "delta_macro_inundation_iou": (
                        treated_metrics["macro_inundation_iou"]
                        - baseline_metrics["macro_inundation_iou"]
                    ),
                }
            )
    summary_frame = pd.DataFrame(rows)
    metrics_path = output_root / "spatial_ablation_metrics.csv"
    summary_frame.to_csv(metrics_path, index=False)
    test_rows = summary_frame[summary_frame["split"] == "legacy_test_holdout"]
    legacy_summary = {
        "mean_delta_macro_rmse_m": float(test_rows["delta_macro_rmse_m"].mean()),
        "mean_delta_macro_mae_m": float(test_rows["delta_macro_mae_m"].mean()),
        "mean_delta_macro_inundation_iou": float(
            test_rows["delta_macro_inundation_iou"].mean()
        ),
        "rmse_improved_fold_count": int(
            np.count_nonzero(test_rows["delta_macro_rmse_m"] < 0.0)
        ),
        "iou_improved_fold_count": int(
            np.count_nonzero(test_rows["delta_macro_inundation_iou"] > 0.0)
        ),
    }
    consistent_benefit = bool(
        legacy_summary["mean_delta_macro_rmse_m"] < 0.0
        and legacy_summary["mean_delta_macro_mae_m"] < 0.0
        and legacy_summary["mean_delta_macro_inundation_iou"] > 0.0
        and legacy_summary["rmse_improved_fold_count"] == spatial_folds
        and legacy_summary["iou_improved_fold_count"] == spatial_folds
    )
    variant_artifacts = []
    for receipt in receipts:
        receipt_path = (
            output_root
            / f"fold_{receipt['fold']}"
            / str(receipt["variant"])
            / "run_receipt.json"
        )
        variant_artifacts.append(
            {
                "fold": receipt["fold"],
                "variant": receipt["variant"],
                "receipt": str(receipt_path.relative_to(output_root)),
                "receipt_file_sha256": _sha256(receipt_path),
                "declared_receipt_sha256": receipt["receipt_sha256"],
                "model_sha256": receipt["model_sha256"],
            }
        )
    result = {
        "schema": SCHEMA,
        "status": "completed_exploratory_spatial_ablation",
        "protocol_sha256": protocol["protocol_sha256"],
        "fold_count": spatial_folds,
        "paired_variant_count": len(receipts),
        "legacy_test_holdout_summary": legacy_summary,
        "interpretation": (
            "consistent_exploratory_benefit"
            if consistent_benefit
            else "mixed_no_consistent_benefit"
        ),
        "promotion_decision": "not_promoted_pending_future_independent_external_validation",
        "external_validation": protocol["external_validation"],
        "engineering_admission": False,
        "claim_boundary": protocol["claim_boundary"],
        "outputs": {
            "protocol": "experiment_protocol.json",
            "protocol_file_sha256": _sha256(protocol_path),
            "metrics": "spatial_ablation_metrics.csv",
            "metrics_sha256": _sha256(metrics_path),
            "variant_receipt_count": len(receipts),
            "variant_artifacts": variant_artifacts,
        },
    }
    result["receipt_sha256"] = _canonical_hash(result)
    _write_json(output_root / "run_receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--label-root", type=Path, default=DEFAULT_LABEL_ROOT)
    parser.add_argument("--terrain", type=Path, default=DEFAULT_TERRAIN)
    parser.add_argument("--linear-model", type=Path, default=DEFAULT_LINEAR_MODEL)
    parser.add_argument("--origen-prior", type=Path, default=DEFAULT_ORIGEN_PRIOR)
    parser.add_argument("--origen-receipt", type=Path, default=DEFAULT_ORIGEN_RECEIPT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--training-steps", type=int, default=TRAINING_STEPS)
    parser.add_argument("--validation-interval", type=int, default=VALIDATION_INTERVAL)
    parser.add_argument("--spatial-folds", type=int, default=SPATIAL_FOLDS)
    parser.add_argument(
        "--spatial-block-size-cells", type=int, default=SPATIAL_BLOCK_SIZE_CELLS
    )
    parser.add_argument("--spatial-buffer-cells", type=int, default=SPATIAL_BUFFER_CELLS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run(
        args.matrix,
        args.label_root,
        args.terrain,
        args.linear_model,
        args.origen_prior,
        args.origen_receipt,
        args.output_root,
        training_steps=args.training_steps,
        validation_interval=args.validation_interval,
        spatial_folds=args.spatial_folds,
        spatial_block_size_cells=args.spatial_block_size_cells,
        spatial_buffer_cells=args.spatial_buffer_cells,
        resume=args.resume,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "fold_count": result["fold_count"],
                "legacy_test_holdout_summary": result["legacy_test_holdout_summary"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
