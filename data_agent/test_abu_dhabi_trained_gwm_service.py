"""Tests for the frozen five-year GWM event-rollout service."""

from __future__ import annotations

import json

import numpy as np
import pytest

import data_agent.abu_dhabi_trained_gwm_service as trained


EVENT_ID = "noaa-isd-ae-202401010000-fixture"
EXTERNAL_ID = "noaa-isd-ae-202404151200-0327"


def _write_json(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path, monkeypatch) -> None:
    model_root = tmp_path / "model"
    labels = tmp_path / "labels"
    runs = tmp_path / "runs"
    observation = tmp_path / "sentinel-observation"
    monkeypatch.setenv("ABU_DHABI_TRAINED_GWM_MODEL_ROOT", str(model_root))
    monkeypatch.setenv("ABU_DHABI_TRAINED_GWM_LABEL_ROOT", str(labels))
    monkeypatch.setenv("ABU_DHABI_TRAINED_GWM_RUN_ROOT", str(runs))
    monkeypatch.setenv("ABU_DHABI_TRAINED_GWM_SENTINEL_OBSERVATION_ROOT", str(observation))
    trained._RUNS.clear()
    _write_json(
        model_root / "run_receipt.json",
        {"status": "completed", "events": {"train": [EVENT_ID]}, "conclusion": {"external_test_is_reported_only": True}},
    )
    _write_json(
        model_root / "gwm_model_card.json",
        {"schema": trained.MODEL_SCHEMA, "model_name": trained.MODEL_NAME, "target": "next_300_second_depth_m", "inputs": [], "selected_regularization": {"five_year_full_train": 1.0}},
    )
    _write_json(
        model_root / "split_manifest.json",
        {"event_disjoint": True, "external_holdout_excluded_from_training": True, "split": {"external_test_2024_april": [EXTERNAL_ID]}},
    )
    np.savez_compressed(
        model_root / "five_year_full_train_cellwise_ridge_coefficients.npz",
        coefficients=np.asarray([[0.0, 1.0, 1.0, 0.0], [1.0, 1.0, 0.0, 0.0]], dtype=np.float32),
        land_mask=np.asarray([True, False]),
    )
    events = [
        {"event_id": EVENT_ID, "split": "train", "external_holdout": False, "start_utc": "2024-01-01T00:00:00Z", "end_utc": "2024-01-01T01:00:00Z"},
        {"event_id": EXTERNAL_ID, "split": "external_test_2024_april", "external_holdout": True, "start_utc": "2024-04-15T12:00:00Z", "end_utc": "2024-04-15T13:00:00Z"},
    ]
    _write_json(
        labels / "batch_manifest.json",
        {"status": "completed", "failed_event_count": 0, "selection": {"events": events}, "events": [{"event_id": e["event_id"], "status": "completed", "quality_passed": True} for e in events]},
    )
    for event in events:
        event_root = labels / "events" / event["event_id"]
        _write_json(
            event_root / "run_receipt.json",
            {"status": "completed", "quality_passed": True, "event": {"event_id": event["event_id"], "split": event["split"], "external_holdout": event["external_holdout"]}, "outputs": {"depth_labels": "surface_depth_labels_250m.npz"}},
        )
        _write_json(event_root / "forcing.json", {"hourly_precipitation_mm": [10.0]})
        np.savez_compressed(
            event_root / "surface_depth_labels_250m.npz",
            x=np.asarray([227000.0, 227250.0, 227500.0]),
            y=np.asarray([2723750.0, 2723500.0]),
            land_mask=np.asarray([[True, False]]),
        )
    _write_json(
        observation / "run_receipt.json",
        {
            "status": "completed",
            "quality_passed": True,
            "event": {
                "event_id": EXTERNAL_ID,
                "external_holdout": True,
                "training_forbidden": True,
                "satellite_observation_utc": "2024-04-15T12:10:00Z",
                "observation_time_seconds_from_event_start": 600.0,
            },
            "external_evaluation": {"forcing_with_zero_rain_tail": "overpass_forcing.json"},
        },
    )
    _write_json(
        observation / "overpass_forcing.json",
        {
            "event_id": EXTERNAL_ID,
            "hourly_precipitation_mm": [10.0, 0.0],
            "nearest_300_second_model_frame_seconds": 600,
            "purpose": "external satellite-overpass evaluation only; forbidden from GWM training",
            "zero_rainfall_tail_hours": 1,
        },
    )


def test_trained_rollout_is_event_bound_and_has_a_300_second_timeline(tmp_path, monkeypatch) -> None:
    _fixture(tmp_path, monkeypatch)

    result = trained.start_rollout({"eventId": EVENT_ID})
    bootstrap = trained.map_bootstrap(result["run_id"])
    final = trained.map_timeseries(result["run_id"], 12)

    assert result["metadata"]["model_mode"] == "trained_event_rollout"
    assert result["metadata"]["model"]["release_id"] == trained.MODEL_RELEASE_ID
    assert result["metadata"]["model"]["training_event_count"] == 1
    assert result["metadata"]["model"]["training_period_start_utc"] == "2024-01-01T00:00:00Z"
    assert result["metadata"]["timeline"]["period_count"] == 13
    assert result["metadata"]["timeline"]["step_minutes"] == 5.0
    assert result["metrics"]["maximum_depth_m"] == pytest.approx(12.0)
    assert len(bootstrap["maximum_depth"]["features"]) == 1
    assert final["features"][0]["properties"]["depth_m"] == pytest.approx(12.0)


def test_trained_rollout_allows_external_inference_but_marks_it_forbidden_from_training(tmp_path, monkeypatch) -> None:
    _fixture(tmp_path, monkeypatch)

    result = trained.start_rollout({"event_id": EXTERNAL_ID})

    assert result["metadata"]["event"]["external_holdout"] is True
    assert result["metadata"]["quality"]["training_forbidden"] is True
    assert result["metadata"]["quality"]["external_holdout_is_reported_only"] is True
    assert result["metadata"]["timeline"]["period_count"] == 25
    assert result["metadata"]["timeline"]["initial_time_index"] == 2
    assert result["metadata"]["external_validation"]["satellite_observation_utc"] == "2024-04-15T12:10:00Z"


def test_trained_rollout_rejects_unknown_event(tmp_path, monkeypatch) -> None:
    _fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="trained_gwm_event_not_admitted"):
        trained.start_rollout({"eventId": "unregistered-event"})
