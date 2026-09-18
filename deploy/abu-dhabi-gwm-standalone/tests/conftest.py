from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.config import Settings


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    root = tmp_path / "model"
    root.mkdir()
    x = np.array([500000.0, 500250.0, 500500.0], dtype=np.float64)
    y = np.array([2700000.0, 2699750.0, 2699500.0], dtype=np.float64)
    land = np.ones((2, 2), dtype=bool)
    coefficients = np.array(
        [
            [0.0, 0.80, 0.10, 0.010],
            [0.0, 0.75, 0.12, 0.012],
            [0.0, 0.70, 0.14, 0.014],
            [0.0, 0.65, 0.16, 0.016],
        ],
        dtype=np.float64,
    )
    np.savez_compressed(root / "coefficients.npz", coefficients=coefficients, land_mask=land)
    np.savez_compressed(root / "grid_250m.npz", x=x, y=y, land_mask=land)
    _write_json(
        root / "default_forcing.json",
        {
            "schema": "gwm.abu_dhabi_flood.default_forcing.v1",
            "profile_id": "test-event",
            "hourly_precipitation_mm": [5.0, 5.0, 0.0],
            "base_rainfall_duration_hours": 2,
            "post_rainfall_tail_hours": 1,
        },
    )
    _write_json(root / "model_card.json", {"model_name": "test-model"})
    _write_json(root / "provenance.json", {"external_holdout_excluded_from_training": True})
    files = {
        name: _sha256(root / name)
        for name in [
            "coefficients.npz",
            "grid_250m.npz",
            "default_forcing.json",
            "model_card.json",
            "provenance.json",
        ]
    }
    _write_json(
        root / "manifest.json",
        {
            "schema": "gwm.abu_dhabi_flood.inference_bundle.v1",
            "status": "ready",
            "model": {
                "release_id": "TEST-R1",
                "schema": "test.schema.v1",
                "name": "test-model",
                "coefficients_file": "coefficients.npz",
                "training_event_count": 2,
                "validation_event_count": 1,
                "blind_test_event_count": 1,
                "external_holdout_event_count": 1,
                "target": "next_depth",
                "terrain": "synthetic",
            },
            "grid": {
                "grid_file": "grid_250m.npz",
                "crs": "EPSG:32640",
                "cell_size_m": 250.0,
                "rows": 2,
                "columns": 2,
                "land_cell_count": 4,
            },
            "default_profile": {
                "profile_id": "test-event",
                "forcing_file": "default_forcing.json",
                "external_holdout": True,
                "training_forbidden": True,
                "start_utc": "2024-04-15T12:00:00Z",
                "end_utc": "2024-04-15T14:00:00Z",
                "base_total_precipitation_mm": 10.0,
                "maximum_total_precipitation_mm": 30.0,
                "base_rainfall_duration_hours": 2,
                "post_rainfall_tail_hours": 1,
                "minimum_rainfall_duration_hours": 1,
                "maximum_rainfall_duration_hours": 72,
            },
            "files": files,
            "claim_boundary": "Synthetic test model only.",
        },
    )
    return root


@pytest.fixture
def settings(tmp_path: Path, model_dir: Path) -> Settings:
    return Settings(
        model_dir=model_dir,
        run_dir=tmp_path / "runs",
        api_token="test-token-at-least-32-characters-long",
        min_free_disk_gb=0.0,
        max_concurrent_runs=1,
    )
