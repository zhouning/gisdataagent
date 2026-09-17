from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.train_abu_dhabi_five_year_event_gwm import EventLabel, _event_arrays


def _label(tmp_path, depth: np.ndarray, land: np.ndarray) -> EventLabel:
    path = tmp_path / "event"
    path.mkdir()
    depth_path = path / "labels.npz"
    forcing_path = path / "forcing.json"
    np.savez_compressed(
        depth_path,
        depth_m=depth,
        time_seconds=np.arange(depth.shape[0], dtype=float) * 300.0,
        land_mask=land,
    )
    forcing_path.write_text(
        json.dumps({"hourly_precipitation_mm": [1.0]}),
        encoding="utf-8",
    )
    return EventLabel(
        event_id="fixture",
        split="train",
        path=path,
        receipt_path=path / "run_receipt.json",
        depth_path=depth_path,
        forcing_path=forcing_path,
    )


@pytest.mark.parametrize("spatial_shape", [(4,), (2, 2)])
def test_event_arrays_accepts_flat_and_gridded_depth_layouts(tmp_path, spatial_shape) -> None:
    depth = np.zeros((13, *spatial_shape), dtype=np.float32)
    land = np.ones((2, 2), dtype=bool)

    loaded_depth, times, loaded_land, hourly = _event_arrays(_label(tmp_path, depth, land))

    assert loaded_depth.shape == (13, 4)
    assert times.shape == (13,)
    assert loaded_land.shape == (4,)
    assert hourly.tolist() == [1.0]


def test_event_arrays_rejects_spatial_mask_mismatch(tmp_path) -> None:
    depth = np.zeros((13, 5), dtype=np.float32)

    with pytest.raises(ValueError, match="five_year_gwm_label_shape_invalid"):
        _event_arrays(_label(tmp_path, depth, np.ones((2, 2), dtype=bool)))
