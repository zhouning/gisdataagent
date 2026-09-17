from __future__ import annotations

import numpy as np

from scripts.train_abu_dhabi_gwm_sentinel2_observation_operator import (
    PROBABILITY_THRESHOLDS,
    binary_metrics,
    calibrate_balanced_probability,
    event_balanced_weights,
    neighbor_mean,
    select_probability_threshold,
)


def test_event_balanced_weights_give_each_event_and_class_equal_mass() -> None:
    targets = [
        np.array([True, False, False]),
        np.array([True, True, False, False, False]),
    ]

    weights = event_balanced_weights(targets)

    assert np.isclose(weights[0][targets[0]].sum(), weights[0][~targets[0]].sum())
    assert np.isclose(weights[1][targets[1]].sum(), weights[1][~targets[1]].sum())
    assert np.isclose(weights[0].sum(), weights[1].sum())


def test_neighbor_mean_respects_land_mask() -> None:
    values = np.array([[1.0, 100.0], [3.0, 5.0]])
    land = np.array([[True, False], [True, True]])

    result = neighbor_mean(values, land)

    assert np.allclose(result[land], 3.0)


def test_binary_metrics_computes_iou_and_f1() -> None:
    result = binary_metrics(
        np.array([True, True, False, False]),
        np.array([True, False, True, False]),
        np.array([0.9, 0.4, 0.6, 0.1]),
    )

    assert np.isclose(result["iou"], 1 / 3)
    assert np.isclose(result["f1"], 0.5)
    assert result["roc_auc"] == 0.75


def test_select_probability_threshold_uses_event_macro_iou() -> None:
    class Event:
        def __init__(self, event_id: str, target: list[bool]):
            self.event_id = event_id
            self.target = np.asarray(target, dtype=bool)

    events = [Event("a", [True, False]), Event("b", [True, False])]
    predictions = {
        "a": np.array([0.8, 0.4]),
        "b": np.array([0.7, 0.3]),
    }

    threshold = select_probability_threshold(events, predictions)

    assert threshold == max(PROBABILITY_THRESHOLDS)


def test_calibrate_balanced_probability_applies_low_event_prevalence() -> None:
    calibrated = calibrate_balanced_probability(np.array([0.5]), 0.02)

    assert np.isclose(calibrated[0], 0.02)
