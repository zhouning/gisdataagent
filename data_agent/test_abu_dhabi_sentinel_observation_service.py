from __future__ import annotations

import json

import numpy as np
import pytest

import data_agent.abu_dhabi_sentinel_observation_service as observation


def _write_json(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(root) -> None:
    outputs = {
        "observed_new_surface_water_10m": "observed_new_surface_water_10m.tif",
        "paired_valid_observation_10m": "paired_valid_observation_10m.tif",
        "mndwi_change_10m": "mndwi_change_10m.tif",
        "observed_flood_250m": "observed_flood_250m.npz",
        "valid_observation_area_m2": 1000,
        "observed_new_surface_water_area_m2": 100,
        "valid_250m_cell_count": 10,
        "observed_flood_250m_cell_count": 2,
    }
    for name in outputs.values():
        if isinstance(name, str):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(b"fixture")
    np.savez_compressed(
        root / "observed_flood_250m.npz",
        valid_fraction=np.asarray([[0.8, 0.9], [0.2, 0.95]], dtype=np.float32),
        observed_new_surface_water_fraction_of_valid_pixels=np.asarray([[0.5, 0.25], [0.0, 0.9]], dtype=np.float32),
        observed_flood_label=np.asarray([[True, True], [False, False]], dtype=bool),
        x=np.asarray([227000.0, 227250.0, 227500.0]),
        y=np.asarray([2723750.0, 2723500.0, 2723250.0]),
    )
    _write_json(
        root / "satellite_overpass_external_evaluation_forcing.json",
        {
            "start_utc": "2024-04-15T12:00:00Z",
            "source": "ERA5",
            "support_point_count": 9,
            "zero_rainfall_tail_hours": 8,
            "nearest_300_second_model_frame_seconds": 155100,
        },
    )
    _write_json(
        root / "run_receipt.json",
        {
            "schema": observation.EXPECTED_SCHEMA,
            "status": "completed",
            "quality_passed": True,
            "event": {
                "event_id": observation.EXPECTED_EVENT_ID,
                "external_holdout": True,
                "training_forbidden": True,
                "satellite_observation_utc": "2024-04-17T07:02:47Z",
                "observation_time_seconds_from_event_start": 154967.729,
            },
            "outputs": outputs,
            "external_evaluation": {"forcing_with_zero_rain_tail": "satellite_overpass_external_evaluation_forcing.json"},
            "method": {
                "source": "Sentinel-2 L2A",
                "before_date": "2024-04-05",
                "after_date": "2024-04-17",
                "minimum_250m_valid_fraction": 0.7,
                "minimum_250m_observed_water_fraction": 0.02,
                "mndwi_change_threshold": 0.05,
                "valid_scl_classes": [4, 5, 6, 7],
                "water_condition": "new water",
            },
            "scenes": {
                "before": [{"item_id": "before", "datetime_utc": "2024-04-05T07:00:00Z", "grid_code": "40QBM", "cloud_cover_percent": 1.0}],
                "after": [{"item_id": "after", "datetime_utc": "2024-04-17T07:00:00Z", "grid_code": "40QBM", "cloud_cover_percent": 25.0}],
            },
            "claim_boundary": ["spectral observation only"],
            "receipt_sha256": "fixture",
        },
    )


def test_dashboard_exposes_only_summary_and_preserves_holdout(tmp_path, monkeypatch) -> None:
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", str(tmp_path))

    payload = observation.observed_flood_dashboard_payload()

    assert payload["event"]["external_holdout"] is True
    assert payload["event"]["training_forbidden"] is True
    assert payload["observation"]["observed_new_surface_water_area_m2"] == 100
    assert payload["external_comparison"]["status"] == "pending_physics_replay"
    assert all("path" not in asset for asset in payload["assets"])
    assert str(tmp_path) not in json.dumps(payload)


def test_dashboard_rejects_training_eligible_event(tmp_path, monkeypatch) -> None:
    _source(tmp_path)
    receipt_path = tmp_path / "run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["event"]["training_forbidden"] = False
    _write_json(receipt_path, receipt)
    monkeypatch.setenv("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="sentinel_observation_holdout_contract_invalid"):
        observation.observed_flood_dashboard_payload()


def test_dashboard_reads_completed_isolated_physics_comparison(tmp_path, monkeypatch) -> None:
    _source(tmp_path)
    _write_json(
        tmp_path / "external_holdout_replay/run_receipt.json",
        {
            "status": "completed",
            "event_id": observation.EXPECTED_EVENT_ID,
            "external_holdout": True,
            "training_forbidden": True,
            "comparison": {"iou": 0.5, "precision": 0.7, "recall": 0.6},
        },
    )
    monkeypatch.setenv("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", str(tmp_path))

    payload = observation.observed_flood_dashboard_payload()

    assert payload["external_comparison"]["status"] == "completed_external_physics_comparison"
    assert payload["external_comparison"]["comparison"]["iou"] == 0.5


def test_dashboard_reads_completed_frozen_gwm_comparison(tmp_path, monkeypatch) -> None:
    _source(tmp_path)
    _write_json(
        tmp_path / "external_holdout_replay/run_receipt.json",
        {
            "status": "completed",
            "event_id": observation.EXPECTED_EVENT_ID,
            "external_holdout": True,
            "training_forbidden": True,
            "comparison": {"metrics": {"iou": 0.25, "precision": 0.60, "recall": 0.30}},
            "gwm_comparison": {"metrics": {"iou": 0.28, "precision": 0.54, "recall": 0.36}},
        },
    )
    monkeypatch.setenv("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", str(tmp_path))

    payload = observation.observed_flood_dashboard_payload()

    assert payload["external_comparison"]["status"] == "completed_external_comparisons"
    assert payload["external_comparison"]["gwm_comparison"] == "completed_frozen_model"
    assert payload["external_comparison"]["gwm_metrics"] == {"iou": 0.28, "precision": 0.54, "recall": 0.36}


def test_observed_flood_map_returns_wgs84_250m_features(tmp_path, monkeypatch) -> None:
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", str(tmp_path))

    payload = observation.observed_flood_map_payload()

    assert payload["status"] == "available_external_holdout_observation_map"
    assert payload["feature_count"] == 2
    assert payload["geojson"]["type"] == "FeatureCollection"
    assert len(payload["geojson"]["features"]) == 2
    feature = payload["geojson"]["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["source_resolution_m"] == 250
    longitude, latitude = feature["geometry"]["coordinates"][0][0]
    assert 40 < longitude < 60
    assert 20 < latitude < 30
