from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_abu_dhabi_gwm_paper_experiments import (
    EXTERNAL_HOLDOUT_EVENT_ID,
    EventLabel,
    _bootstrap_intervals,
    _feature_matrix,
    _neighbor_mean,
    _process_safe_training_events,
    _rain_features,
)


def _label(tmp_path, event_id: str) -> EventLabel:
    path = tmp_path / event_id
    return EventLabel(
        event_id,
        "train",
        path,
        path / "receipt.json",
        path / "depth.npz",
        path / "forcing.json",
    )


def test_neighbor_mean_uses_cardinal_land_neighbors() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0])
    land = np.ones(4, dtype=bool)

    result = _neighbor_mean(values, land, (2, 2))

    assert result.tolist() == [2.5, 2.5, 2.5, 2.5]


def test_rain_features_are_causal_and_include_trailing_memory() -> None:
    hourly = np.asarray([10.0, 20.0, 30.0, 40.0])

    intensity, cumulative, trailing, peak = _rain_features(hourly, 2.5 * 3600.0)

    assert intensity == 3.0
    assert cumulative == 0.9
    assert trailing == 1.5
    assert peak == 3.0


def test_feature_matrix_contains_inertia_and_spatial_state() -> None:
    current = np.asarray([1.0, 2.0, 3.0, 4.0])
    previous = np.asarray([0.5, 1.5, 2.5, 3.5])
    land = np.ones(4, dtype=bool)

    features = _feature_matrix(current, previous, land, (2, 2), np.asarray([10.0]), 0.0)

    assert features.shape == (4, 11)
    assert features[:, 2].tolist() == [0.5, 0.5, 0.5, 0.5]
    assert features[:, 3].tolist() == [2.5, 2.5, 2.5, 2.5]


def test_process_buffer_quarantines_nearby_training_events(tmp_path) -> None:
    rows = [
        {
            "event_id": "far",
            "event_start_utc": "2024-03-01T00:00:00Z",
            "event_end_utc": "2024-03-02T00:00:00Z",
        },
        {
            "event_id": "near",
            "event_start_utc": "2024-04-13T00:00:00Z",
            "event_end_utc": "2024-04-14T00:00:00Z",
        },
        {
            "event_id": EXTERNAL_HOLDOUT_EVENT_ID,
            "event_start_utc": "2024-04-15T12:00:00Z",
            "event_end_utc": "2024-04-17T00:00:00Z",
        },
    ]
    matrix = pd.DataFrame(rows)

    safe, quarantined = _process_safe_training_events(
        matrix,
        [_label(tmp_path, "far"), _label(tmp_path, "near")],
    )

    assert [label.event_id for label in safe] == ["far"]
    assert [row["event_id"] for row in quarantined] == ["near"]


def test_bootstrap_intervals_skip_self_and_compare_requested_baselines() -> None:
    rows = []
    for event_id in ("event-a", "event-b"):
        for model, rmse in (("selected", 1.0), ("baseline", 2.0)):
            rows.append(
                {
                    "model": model,
                    "split": "test",
                    "evaluation_mode": "rollout",
                    "event_id": event_id,
                    "rmse_m": rmse,
                    "mae_m": rmse,
                    "inundation_iou": 1.0 / rmse,
                    "inundation_f1": 1.0 / rmse,
                }
            )

    result = _bootstrap_intervals(rows, "selected", ("selected", "baseline"))

    assert len(result) == 4
    assert {row["reference_model"] for row in result} == {"baseline"}
