from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.train_abu_dhabi_gwm_origen_spatial_ablation import (
    _load_origen_prior,
    _sha256,
    _spatial_fold_masks,
    _static_tensor,
)


def _write_prior_fixture(tmp_path):
    terrain_path = tmp_path / "terrain_grid.npz"
    x = np.arange(5, dtype=np.float64) * 250.0
    y = np.arange(5, dtype=np.float64) * 250.0
    land = np.ones((4, 4), dtype=bool)
    np.savez_compressed(
        terrain_path,
        values=np.zeros((5, 5), dtype=np.float32),
        x=x,
        y=y,
        land_mask=land,
    )
    features = np.zeros((2, 4, 4), dtype=np.float32)
    features[0, 0, 0] = 1.0
    features[1, 3, 3] = 0.5
    prior_path = tmp_path / "gwm_static_prior_250m.npz"
    np.savez_compressed(
        prior_path,
        features=features,
        feature_names=np.asarray(["hotspot", "history"]),
        x=0.5 * (x[:-1] + x[1:]),
        y=0.5 * (y[:-1] + y[1:]),
        land_mask=land,
        epsg=np.asarray(32640, dtype=np.int32),
    )
    receipt_path = tmp_path / "gwm_static_prior_receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "status": "ready_prospective_training_only",
                "artifact": {"sha256": _sha256(prior_path)},
                "grid": {"source_sha256": _sha256(terrain_path)},
                "feature_names": ["hotspot", "history"],
                "active_feature_count": 2,
                "admission": {
                    "required_validation": (
                        "spatially_blocked_ablation_against_the_same_model_without_origen_features"
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    return terrain_path, prior_path, receipt_path, land


def test_load_origen_prior_verifies_grid_and_receipt(tmp_path) -> None:
    terrain_path, prior_path, receipt_path, land = _write_prior_fixture(tmp_path)

    features, names, evidence = _load_origen_prior(
        prior_path, receipt_path, terrain_path, land.shape, land.reshape(-1)
    )

    assert features.shape == (2, 4, 4)
    assert names == ("hotspot", "history")
    assert evidence["active_feature_count"] == 2
    assert evidence["prior_sha256"] == _sha256(prior_path)


def test_load_origen_prior_rejects_wrong_terrain(tmp_path) -> None:
    terrain_path, prior_path, receipt_path, land = _write_prior_fixture(tmp_path)
    with np.load(terrain_path) as archive:
        payload = {name: archive[name] for name in archive.files}
    payload["values"] = np.ones((5, 5), dtype=np.float32)
    np.savez_compressed(terrain_path, **payload)

    with pytest.raises(ValueError, match="gwm_origen_prior_terrain_hash_mismatch"):
        _load_origen_prior(
            prior_path, receipt_path, terrain_path, land.shape, land.reshape(-1)
        )


def test_spatial_folds_are_disjoint_and_buffered() -> None:
    land = np.ones((24, 24), dtype=bool)

    folds = _spatial_fold_masks(
        land.reshape(-1), land.shape, fold_count=4, block_size_cells=6, buffer_cells=2
    )

    assert len(folds) == 4
    for masks in folds:
        assert np.any(masks["training"])
        assert np.any(masks["holdout"])
        assert np.any(masks["buffer"])
        assert not np.any(masks["training"] & masks["holdout"])
        assert not np.any(masks["training"] & masks["buffer"])


def test_static_tensor_excludes_label_derived_susceptibility() -> None:
    land = np.ones(6, dtype=bool)
    elevation = np.zeros((2, 3), dtype=np.float32)
    slope = np.ones((2, 3), dtype=np.float32)
    origen = np.full((2, 2, 3), 0.25, dtype=np.float32)

    result = _static_tensor(land, elevation, slope, origen)

    assert result.shape == (5, 2, 3)
    assert np.allclose(result[0].numpy(), elevation)
    assert np.allclose(result[1].numpy(), slope)
    assert np.allclose(result[2].numpy(), 1.0)
    assert np.allclose(result[3:].numpy(), origen)
