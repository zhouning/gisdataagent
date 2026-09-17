from __future__ import annotations

import numpy as np
import torch

from scripts.train_abu_dhabi_gwm_conv_baseline import (
    DELTA_LIMIT_M,
    INPUT_CHANNELS,
    ConvRolloutBaseline,
    _model_inputs,
    _rain_features,
    _terrain_features,
)


def test_conv_model_starts_as_persistence_residual() -> None:
    model = ConvRolloutBaseline()
    inputs = torch.randn(2, len(INPUT_CHANNELS), 8, 9)

    result = model(inputs)

    assert result.shape == (2, 1, 8, 9)
    assert torch.count_nonzero(result) == 0


def test_model_inputs_are_causal_and_channel_complete() -> None:
    current = torch.ones(1, 1, 3, 4)
    previous = torch.zeros_like(current)
    static = torch.zeros(4, 3, 4)

    result = _model_inputs(current, previous, (1.0, 2.0, 3.0, 4.0), static)

    assert result.shape == (1, len(INPUT_CHANNELS), 3, 4)
    assert torch.all(result[:, 2] == 5.0)
    assert torch.all(result[:, 3] == 1.0)
    assert float(DELTA_LIMIT_M) == 0.05


def test_rain_features_do_not_use_future_hours() -> None:
    hourly = np.asarray([1.0, 2.0, 100.0])

    intensity, cumulative, trailing, peak = _rain_features(hourly, 1.5 * 3600.0)

    assert intensity == 0.2
    assert cumulative == 0.04
    assert trailing == (1.0 + 1.0) / 30.0
    assert peak == 0.2


def test_terrain_features_convert_vertices_to_cells(tmp_path) -> None:
    path = tmp_path / "terrain.npz"
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    np.savez_compressed(path, values=values)

    elevation, slope = _terrain_features(path, (2, 3))

    assert elevation.shape == (2, 3)
    assert slope.shape == (2, 3)
    assert np.isfinite(elevation).all()
    assert np.isfinite(slope).all()
