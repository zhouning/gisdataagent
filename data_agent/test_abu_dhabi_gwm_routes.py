"""HTTP contract tests for the Abu Dhabi GWM rollout API."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
from starlette.applications import Starlette
from starlette.testclient import TestClient

import data_agent.api.abu_dhabi_flood_routes as flood_routes
import data_agent.uwm.abu_dhabi_flood.gwm_surrogate as gwm_surrogate
from data_agent.uwm.abu_dhabi_flood.gwm_surrogate import AbuDhabiGwmSurrogate


def _tensor_root(tmp_path):
    periods = 5
    elapsed = np.arange(1, periods + 1, dtype=np.int64) * 900
    node = np.zeros((periods, 2, 6), dtype=np.float32)
    edge = np.zeros((periods, 1, 4), dtype=np.float32)
    for step in range(periods):
        value = float(step + 1)
        node[step, :, 0] = value * 0.02
        node[step, :, 1] = 2.0 + value * 0.02
        node[step, :, 2] = value * 0.1
        node[step, :, 3] = value * 0.005
        node[step, :, 4] = value * 0.008
        node[step, :, 5] = value * 0.001
        edge[step, :, :] = value * 0.02
    arrays = {
        "pilot_01_elapsed_seconds": elapsed,
        "pilot_01_node_state": node,
        "pilot_01_edge_state": edge,
    }
    np.savez_compressed(tmp_path / "customer_swmm_gwm_dynamic_diagnostic.private.npz", **arrays)
    (tmp_path / "customer_swmm_gwm_dynamic_diagnostic_manifest.json").write_text(
        json.dumps(
            {
                "schema": "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1",
                "arrays": {name: {"shape": list(value.shape)} for name, value in arrays.items()},
            }
        ),
        encoding="utf-8",
    )
    np.savez_compressed(
        tmp_path / "customer_swmm_gwm_pilot_alignment.private.npz",
        pilot_node_indices=np.asarray([0, 1], dtype=np.int64),
        pilot_node_offsets=np.asarray([0, 2], dtype=np.int64),
    )
    return tmp_path


def test_gwm_http_contract_serves_train_rollout_and_node_frames(tmp_path, monkeypatch):
    store = AbuDhabiGwmSurrogate(_tensor_root(tmp_path))
    monkeypatch.setattr(
        store,
        "_load_geometry_index",
        lambda: {
            0: {"type": "Point", "coordinates": [54.40, 24.40]},
            1: {"type": "Point", "coordinates": [54.41, 24.41]},
        },
    )
    monkeypatch.setattr(gwm_surrogate, "_STORE", store)
    monkeypatch.setattr(
        flood_routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="test-analyst", metadata={"role": "analyst"}),
    )
    monkeypatch.setattr(flood_routes, "_set_user_context", lambda user: (user.identifier, "analyst"))
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())

    with TestClient(app) as client:
        assert client.get("/api/abu-dhabi/flood/gwm/status").json()["status"] == "ready_to_train"
        training = client.post("/api/abu-dhabi/flood/gwm/train", json={"ridge": 0.0001})
        assert training.status_code == 200
        assert training.json()["sample_count"] == 4

        rollout = client.post(
            "/api/abu-dhabi/flood/gwm/rollout",
            json={"pilot_id": "pilot_01", "steps": 4, "rainfall_multiplier": 1.4},
        )
        assert rollout.status_code == 200
        run_id = rollout.json()["run_id"]

        bootstrap = client.get(f"/api/abu-dhabi/flood/gwm/runs/{run_id}/map/bootstrap")
        assert bootstrap.status_code == 200
        assert len(bootstrap.json()["frame"]["features"]) == 2

        frame = client.get(f"/api/abu-dhabi/flood/gwm/runs/{run_id}/timeseries?time_index=2")
        assert frame.status_code == 200
        assert frame.json()["metadata"]["time_index"] == 2
        assert len(frame.json()["features"]) == 2
