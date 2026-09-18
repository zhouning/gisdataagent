from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import GwmEngine
from app.main import create_app


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token}"}


def test_api_is_headless_and_requires_bearer_auth(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/v1/model").status_code == 401
    response = client.get("/v1/model", headers=auth(settings))
    assert response.status_code == 200
    assert response.json()["model"]["releaseId"] == "TEST-R1"
    assert response.json()["resultRetention"] == "persistent_until_manually_removed"


def test_environment_rejects_short_api_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GWM_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("GWM_RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("GWM_API_TOKEN", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        Settings.from_environment()


def test_rollout_persists_and_survives_engine_restart(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/rollouts",
        headers=auth(settings),
        json={"totalRainfallMm": 15, "durationHours": 4},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    run_id = payload["runId"]
    run_dir = settings.run_dir / run_id
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "surface_depth_labels_250m.npz").is_file()
    assert payload["metrics"]["periodCount"] == 61
    assert payload["metrics"]["simulationDurationHours"] == 5
    assert client.delete(f"/v1/runs/{run_id}", headers=auth(settings)).status_code == 405

    restarted = TestClient(create_app(settings, GwmEngine(settings)))
    receipt = restarted.get(f"/v1/runs/{run_id}", headers=auth(settings))
    assert receipt.status_code == 200
    assert receipt.json()["runId"] == run_id
    artifact = restarted.get(
        f"/v1/runs/{run_id}/artifacts/surface_depth_labels_250m.npz",
        headers=auth(settings),
    )
    assert artifact.status_code == 200
    assert len(artifact.content) > 100


def test_idempotency_prevents_duplicate_results(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    headers = {**auth(settings), "Idempotency-Key": "same-client-request"}
    first = client.post(
        "/v1/rollouts",
        headers=headers,
        json={"totalRainfallMm": 15, "durationHours": 4},
    )
    second = client.post(
        "/v1/rollouts",
        headers=headers,
        json={"totalRainfallMm": 15, "durationHours": 4},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["runId"] == second.json()["runId"]
    assert len(list(settings.run_dir.glob("trained-gwm-*"))) == 1

    conflict = client.post(
        "/v1/rollouts",
        headers=headers,
        json={"totalRainfallMm": 16, "durationHours": 4},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "gwm_idempotency_key_conflict"


def test_map_timeseries_and_compatibility_routes(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    events = client.get(
        "/api/abu-dhabi/flood/gwm/trained/events",
        headers=auth(settings),
    )
    assert events.status_code == 200
    assert events.json()["model"]["training_event_count"] == 2
    assert events.json()["events"][0]["event_id"] == "test-event"
    response = client.post(
        "/api/abu-dhabi/flood/gwm/trained/rainfall-scenarios",
        headers=auth(settings),
        json={"eventId": "test-event", "totalRainfallMm": 10, "durationHours": 2},
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    bootstrap = client.get(
        f"/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map",
        headers=auth(settings),
    )
    assert bootstrap.status_code == 200
    assert bootstrap.json()["type"] == "FeatureCollection"
    frame = client.get(
        f"/v1/runs/{run_id}/timeseries?timeIndex=1",
        headers=auth(settings),
    )
    assert frame.status_code == 200
    assert frame.json()["metadata"]["time_index"] == 1

    rejected = client.post(
        "/api/abu-dhabi/flood/gwm/trained/rainfall-scenarios",
        headers=auth(settings),
        json={"eventId": "another-event", "totalRainfallMm": 10, "durationHours": 2},
    )
    assert rejected.status_code == 422


def test_low_disk_readiness_never_deletes_existing_runs(settings: Settings) -> None:
    normal = TestClient(create_app(settings))
    created = normal.post(
        "/v1/rollouts",
        headers=auth(settings),
        json={"totalRainfallMm": 10, "durationHours": 2},
    )
    run_id = created.json()["runId"]
    low_disk_settings = Settings(
        model_dir=settings.model_dir,
        run_dir=settings.run_dir,
        api_token=settings.api_token,
        min_free_disk_gb=10**9,
        max_concurrent_runs=1,
    )
    low_disk = TestClient(create_app(low_disk_settings))
    assert low_disk.get("/health/ready").status_code == 503
    rejected = low_disk.post(
        "/v1/rollouts",
        headers=auth(low_disk_settings),
        json={"totalRainfallMm": 10, "durationHours": 2},
    )
    assert rejected.status_code == 507
    assert (settings.run_dir / run_id / "run.json").is_file()


def test_missing_run_and_artifact_return_not_found(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    missing = client.get(
        "/v1/runs/trained-gwm-20260919T000000Z-deadbeef",
        headers=auth(settings),
    )
    assert missing.status_code == 404
    assert missing.json()["error"] == "gwm_run_not_found"

    created = client.post(
        "/v1/rollouts",
        headers=auth(settings),
        json={"totalRainfallMm": 10, "durationHours": 2},
    )
    run_id = created.json()["runId"]
    artifact = client.get(
        f"/v1/runs/{run_id}/artifacts/not-allowed.txt",
        headers=auth(settings),
    )
    assert artifact.status_code == 404
    assert artifact.json()["error"] == "gwm_artifact_not_found"
