"""Shared action, feasibility and evaluation logic for all three candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from sklearn.metrics import f1_score

try:
    from .contract import BenchmarkContractError
except ImportError:  # Direct script execution from the benchmark directory.
    from contract import BenchmarkContractError


CLASSES = tuple(range(1, 7))


def apportion(weights: np.ndarray, total: int) -> np.ndarray:
    values = np.asarray(weights, dtype=np.float64)
    if values.ndim != 1 or np.any(values < 0) or not np.all(np.isfinite(values)):
        raise BenchmarkContractError("invalid_apportionment_weights")
    if total < 0:
        raise BenchmarkContractError("apportionment_total_must_be_nonnegative")
    if values.sum() <= 0:
        values = np.ones_like(values)
    raw = values / values.sum() * total
    result = np.floor(raw).astype(np.int64)
    remainder = int(total - result.sum())
    if remainder:
        order = np.argsort(-(raw - result), kind="stable")
        result[order[:remainder]] += 1
    return result


def feasible_target_counts(
    desired_counts: Mapping[int, int],
    *,
    origin_state: np.ndarray,
    valid_mask: np.ndarray,
    hard_exclusion_mask: np.ndarray,
    classes: Sequence[int] = CLASSES,
    locked_classes: Sequence[int] = (1, 4),
) -> dict[int, int]:
    """Project desired totals onto counts compatible with immutable pixels."""

    origin = np.asarray(origin_state)
    valid = np.asarray(valid_mask, dtype=bool)
    hard = np.asarray(hard_exclusion_mask, dtype=bool)
    if origin.shape != valid.shape or origin.shape != hard.shape:
        raise BenchmarkContractError("feasible_demand_shape_mismatch")
    normalized_classes = tuple(int(value) for value in classes)
    locked = {int(value) for value in locked_classes}
    active = valid & np.isin(origin, normalized_classes)
    fixed = active & hard
    mutable = active & ~hard
    fixed_counts = np.array(
        [np.count_nonzero(fixed & (origin == value)) for value in normalized_classes],
        dtype=np.int64,
    )
    desired = np.array(
        [max(0, int(desired_counts.get(value, 0))) for value in normalized_classes],
        dtype=np.int64,
    )
    mutable_preferences = np.maximum(desired - fixed_counts, 0)
    eligible = np.array([value not in locked for value in normalized_classes], dtype=bool)
    mutable_preferences[~eligible] = 0
    mutable_total = int(mutable.sum())
    if mutable_preferences.sum() == 0:
        mutable_preferences = np.array(
            [np.count_nonzero(mutable & (origin == value)) for value in normalized_classes],
            dtype=np.int64,
        )
        mutable_preferences[~eligible] = 0
    mutable_projection = np.zeros(len(normalized_classes), dtype=np.int64)
    mutable_projection[eligible] = apportion(
        mutable_preferences[eligible], mutable_total
    )
    projected = fixed_counts + mutable_projection
    if int(projected.sum()) != int(active.sum()) or np.any(projected < fixed_counts):
        raise AssertionError("feasible_demand_projection_failed")
    return {value: int(projected[index]) for index, value in enumerate(normalized_classes)}


def class_counts(
    state: np.ndarray,
    valid_mask: np.ndarray,
    classes: Sequence[int] = CLASSES,
) -> dict[int, int]:
    values = np.asarray(state)
    valid = np.asarray(valid_mask, dtype=bool)
    return {int(cls): int(np.count_nonzero(valid & (values == cls))) for cls in classes}


def evaluate_prediction(
    prediction: np.ndarray,
    *,
    origin_state: np.ndarray,
    observed_target: np.ndarray,
    valid_mask: np.ndarray,
    hard_exclusion_mask: np.ndarray,
    requested_counts: Mapping[int, int],
    reliability_mask: np.ndarray | None = None,
    classes: Sequence[int] = CLASSES,
) -> dict[str, Any]:
    predicted = np.asarray(prediction)
    origin = np.asarray(origin_state)
    target = np.asarray(observed_target)
    valid = np.asarray(valid_mask, dtype=bool)
    hard = np.asarray(hard_exclusion_mask, dtype=bool)
    if not (predicted.shape == origin.shape == target.shape == valid.shape == hard.shape):
        raise BenchmarkContractError("evaluation_shape_mismatch")
    normalized_classes = tuple(int(value) for value in classes)
    evaluation_mask = (
        valid
        & np.isin(origin, normalized_classes)
        & np.isin(target, normalized_classes)
        & np.isin(predicted, normalized_classes)
    )
    result = _metrics(
        predicted,
        origin=origin,
        target=target,
        mask=evaluation_mask,
        classes=normalized_classes,
    )
    if reliability_mask is not None:
        reliable = evaluation_mask & np.asarray(reliability_mask, dtype=bool)
        result["reliability_sensitivity"] = _metrics(
            predicted,
            origin=origin,
            target=target,
            mask=reliable,
            classes=normalized_classes,
        )
    actual_counts = class_counts(predicted, evaluation_mask, normalized_classes)
    requested = {int(key): int(value) for key, value in requested_counts.items()}
    total = max(1, int(evaluation_mask.sum()))
    result.update(
        {
            "evaluation_pixel_count": int(evaluation_mask.sum()),
            "constraint_violation_pixels": int(
                np.count_nonzero(evaluation_mask & hard & (predicted != origin))
            ),
            "constraint_violation_rate": float(
                np.count_nonzero(evaluation_mask & hard & (predicted != origin)) / total
            ),
            "actual_class_counts": {str(key): value for key, value in actual_counts.items()},
            "requested_class_counts": {str(key): value for key, value in requested.items()},
            "demand_l1_error_pixels": int(
                sum(
                    abs(actual_counts.get(cls, 0) - requested.get(cls, 0))
                    for cls in normalized_classes
                )
            ),
            "demand_total_variation": float(
                sum(
                    abs(actual_counts.get(cls, 0) - requested.get(cls, 0))
                    for cls in normalized_classes
                )
                / (2 * total)
            ),
        }
    )
    return result


def _metrics(
    prediction: np.ndarray,
    *,
    origin: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
    classes: tuple[int, ...],
) -> dict[str, Any]:
    count = int(mask.sum())
    if count <= 0:
        raise BenchmarkContractError("evaluation_mask_is_empty")
    predicted_change = prediction[mask] != origin[mask]
    observed_change = target[mask] != origin[mask]
    hits = int(np.count_nonzero(predicted_change & observed_change))
    misses = int(np.count_nonzero(~predicted_change & observed_change))
    false_alarms = int(np.count_nonzero(predicted_change & ~observed_change))
    denominator = hits + misses + false_alarms
    change_fom = float(hits / denominator) if denominator else 1.0
    change_f1 = float(
        f1_score(observed_change, predicted_change, zero_division=1)
    )
    return {
        "pixel_count": count,
        "overall_accuracy": float(np.mean(prediction[mask] == target[mask])),
        "macro_f1": float(
            f1_score(
                target[mask],
                prediction[mask],
                labels=list(classes),
                average="macro",
                zero_division=0,
            )
        ),
        "change_figure_of_merit": change_fom,
        "change_f1": change_f1,
        "change_hits": hits,
        "change_misses": misses,
        "change_false_alarms": false_alarms,
        "predicted_change_pixels": int(predicted_change.sum()),
        "observed_change_pixels": int(observed_change.sum()),
    }
