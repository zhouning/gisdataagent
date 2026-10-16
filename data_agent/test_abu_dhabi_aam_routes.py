"""AAM result access must preserve quality flags and native download boundaries."""

import json

import numpy as np
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import abu_dhabi_aam_routes as aam


PREFIX = "/api/abu-dhabi/flood/aam"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(aam, "_AAM_DIR", tmp_path)
    monkeypatch.setattr(aam, "_get_user_from_request", lambda request: object())
    monkeypatch.setattr(aam, "_set_user_context", lambda user: None)
    aam._aam_grid_metadata.cache_clear()
    aam._maximum_depth_cached.cache_clear()
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "configuration.json").write_text(json.dumps({
        "rainfall": {"total_depth_mm": 60, "rain_duration_seconds": 3600,
                     "recession_seconds": 14400},
    }))
    for scenario in ("L1", "L2"):
        folder = tmp_path / "results" / scenario
        folder.mkdir(parents=True)
        (folder / "run_receipt.json").write_text(json.dumps({
            "status": "completed", "quality_passed": False,
            "duration_seconds": 18000, "output_seconds": 300,
            "swmm_routing_error_percent": 1.27,
        }))
        np.savez(folder / "cell_results.npz", x=[350000, 350100, 350200, 350300],
                 y=[2677700, 2677600], active_cells=[0, 1, 2],
                 maximum_depth_m=[0.02, 0.2, 0.8])
        np.save(folder / "depth_frames.npy", [[0., 0., 0.], [0.02, 0.1, 0.8]])
        (folder / f"AAM_{scenario}_1D.out").write_bytes(b"native-out-fixture")
        (folder / "private.json").write_text('{"private": true}')
    with TestClient(Starlette(routes=aam.get_aam_routes())) as http:
        yield http
    aam._aam_grid_metadata.cache_clear()
    aam._maximum_depth_cached.cache_clear()


@pytest.mark.parametrize("path", [
    "/scenarios", "/boundary", "/pond", "/hotspots", "/pipelines",
    "/connection-gap", "/L1/frame", "/L2/maximum-depth",
    "/assets/L1/AAM_L1_1D.out",
])
def test_all_result_routes_require_authentication(client, monkeypatch, path):
    monkeypatch.setattr(aam, "_get_user_from_request", lambda request: None)
    assert client.get(PREFIX + path).status_code == 401


def test_completed_does_not_mean_quality_passed(client):
    response = client.get(PREFIX + "/scenarios")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    rows = response.json()["scenarios"]
    assert [row["key"] for row in rows] == ["L1", "L2"]
    for row in rows:
        assert row["ready"] is True
        assert row["quality_passed"] is False
        assert row["engineering_admitted"] is False
        assert row["quality_gates"]["swmm_routing_error_percent"] == 1.27
        assert row["manifest"]["period_count"] == 61
        assert row["manifest"]["elapsed_minutes"][-1] == 300


def test_frame_preview_keeps_depth_time_and_geographic_coordinates(client):
    initial = client.get(PREFIX + "/L1/frame?time_index=0").json()
    assert initial["features"] == []
    response = client.get(PREFIX + "/L1/frame?time_index=1")
    assert response.status_code == 200
    frame = response.json()
    assert [f["properties"]["cell_id"] for f in frame["features"]] == [1, 2]
    assert frame["metadata"]["time_minutes"] == 5
    assert frame["metadata"]["native_active_cell_count"] == 3
    lon, lat = frame["features"][0]["geometry"]["coordinates"][0][0]
    assert 55 < lon < 56 and 24 < lat < 25
    maximum = client.get(PREFIX + "/L2/maximum-depth").json()
    assert maximum["features"][-1]["properties"]["maximum_depth_m"] == 0.8


@pytest.mark.parametrize("index", ["-1", "2", "invalid"])
def test_frame_rejects_invalid_indices(client, index):
    response = client.get(PREFIX + f"/L1/frame?time_index={index}")
    assert response.status_code == 416


def test_native_download_uses_range_and_rejects_non_allowlisted_file(client):
    response = client.get(PREFIX + "/assets/L1/AAM_L1_1D.out",
                          headers={"Range": "bytes=0-5"})
    assert response.status_code == 206
    assert response.content == b"native"
    assert response.headers["content-range"] == "bytes 0-5/18"
    assert client.get(PREFIX + "/assets/L1/private.json").status_code == 404
    assert client.get(PREFIX + "/assets/L1/AAM_L2_1D.out").status_code == 404


def test_preview_limit_keeps_deepest_cell():
    values = np.linspace(0.05, 2., 100)
    values[37] = 99.
    selected = aam._sample_indices(values, limit=10)
    assert len(selected) <= 10
    assert 37 in selected
