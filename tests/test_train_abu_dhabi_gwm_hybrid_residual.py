from __future__ import annotations

import numpy as np
import torch

from scripts.train_abu_dhabi_gwm_hybrid_residual import (
    INPUT_CHANNELS,
    HybridResidualCorrection,
    _hybrid_inputs,
    _hybrid_next,
    _linear_prediction,
    _load_linear_model,
)


def test_hybrid_correction_starts_at_exact_zero() -> None:
    model = HybridResidualCorrection()

    result = model(torch.randn(2, len(INPUT_CHANNELS), 8, 9))

    assert result.shape == (2, 1, 8, 9)
    assert torch.count_nonzero(result) == 0


def test_linear_model_prediction_matches_cellwise_formula(tmp_path) -> None:
    path = tmp_path / "linear.npz"
    coefficients = np.asarray([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
    np.savez_compressed(
        path,
        coefficients=coefficients,
        land_mask=np.ones((1, 1), dtype=bool),
        feature_names=np.asarray(
            [
                "intercept",
                "depth_m",
                "rainfall_intensity_mm_h_div_10",
                "cumulative_rainfall_mm_div_50",
            ]
        ),
    )
    linear = _load_linear_model(path, (1, 1), np.ones(1, dtype=bool))

    result = _linear_prediction(torch.ones(1, 1, 1, 1), (0.5, 0.25, 0.0, 0.0), linear)

    assert result.item() == 5.5


def test_hybrid_inputs_include_linear_state() -> None:
    current = torch.ones(1, 1, 2, 3)
    previous = torch.zeros_like(current)
    linear_next = torch.full_like(current, 1.02)
    static = torch.zeros(4, 2, 3)

    result = _hybrid_inputs(current, previous, linear_next, (1.0, 2.0, 3.0, 4.0), static)

    assert result.shape == (1, len(INPUT_CHANNELS), 2, 3)
    assert torch.allclose(result[:, 3], linear_next[:, 0])
    assert torch.allclose(result[:, 4], torch.full((1, 2, 3), 2.0))


def test_zero_gate_returns_exact_linear_prediction(tmp_path) -> None:
    path = tmp_path / "linear.npz"
    np.savez_compressed(
        path,
        coefficients=np.asarray([[0.0, 1.0, 0.0, 0.0]], dtype=np.float32),
        land_mask=np.ones((1, 1), dtype=bool),
        feature_names=np.asarray(
            [
                "intercept",
                "depth_m",
                "rainfall_intensity_mm_h_div_10",
                "cumulative_rainfall_mm_div_50",
            ]
        ),
    )
    linear = _load_linear_model(path, (1, 1), np.ones(1, dtype=bool))
    model = HybridResidualCorrection()
    with torch.no_grad():
        model.head.bias.fill_(1.0)
    current = torch.ones(1, 1, 1, 1)

    result = _hybrid_next(
        model,
        current,
        current,
        (1.0, 1.0, 1.0, 1.0),
        torch.zeros(4, 1, 1),
        linear,
        gate_scale_mm=0.0,
    )

    assert result.item() == 1.0
