from __future__ import annotations

import numpy as np
import pytest

from scripts.evaluate_abu_dhabi_gwm_observation_operator_confirmatory import (
    _operator_probability,
    original_event_window,
)
from scripts.train_abu_dhabi_gwm_sentinel2_observation_operator import (
    FEATURE_NAMES,
    trajectory_feature_grid,
)


def test_original_event_window_excludes_zero_rain_tail() -> None:
    times = np.asarray([0.0, 300.0, 600.0, 900.0])
    depth = np.arange(8, dtype=np.float32).reshape(4, 2)

    selected_depth, selected_times = original_event_window(depth, times, 600.0)

    np.testing.assert_array_equal(selected_times, [0.0, 300.0, 600.0])
    np.testing.assert_array_equal(selected_depth, depth[:3])


def test_original_event_window_requires_matching_frame() -> None:
    with pytest.raises(ValueError, match="observation_operator_confirmation_event_window_mismatch"):
        original_event_window(
            np.zeros((2, 1), dtype=np.float32),
            np.asarray([0.0, 300.0]),
            600.0,
        )


def test_frozen_operator_probability_uses_selected_features() -> None:
    land = np.ones((2, 2), dtype=bool)
    depth = np.asarray(
        [
            [0.0, 0.0, 0.0, 0.0],
            [0.01, 0.02, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    features = trajectory_feature_grid(
        depth,
        np.asarray([0.0, 300.0]),
        land,
        600.0,
    )
    operator = {
        "feature_names": (FEATURE_NAMES[0],),
        "scaler_mean": np.asarray([0.0]),
        "scaler_scale": np.asarray([1.0]),
        "coefficients": np.asarray([1.0]),
        "intercept": 0.0,
        "calibration_prevalence": 0.1,
    }

    probability = _operator_probability(features, operator)

    assert probability.shape == land.shape
    assert probability[0, 1] > probability[0, 0] > probability[1, 0]
