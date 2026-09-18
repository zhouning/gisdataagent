"""Tests for the private-tensor Abu Dhabi GWM prototype boundary."""

from __future__ import annotations

import json

import numpy as np
import pytest

from data_agent.uwm.abu_dhabi_flood.gwm_surrogate import AbuDhabiGwmSurrogate


def _private_tensor_root(tmp_path):
    arrays: dict[str, np.ndarray] = {}
    for pilot_number in range(1, 3):
        pilot = f"pilot_{pilot_number:02d}"
        periods = 10 if pilot_number == 1 else 14
        elapsed = np.arange(1, periods + 1, dtype=np.int64) * 900
        node = np.zeros((periods, 2, 6), dtype=np.float32)
        edge = np.zeros((periods, 1, 4), dtype=np.float32)
        for step in range(periods):
            scale = float(step + pilot_number)
            node[step, :, 0] = scale * 0.02
            node[step, :, 1] = 2.0 + scale * 0.02
            node[step, :, 2] = scale * 0.1
            node[step, :, 3] = scale * 0.005
            node[step, :, 4] = scale * 0.008
            node[step, :, 5] = max(0.0, scale - 6.0) * 0.002
            edge[step, :, 0] = scale * 0.03
            edge[step, :, 1] = scale * 0.01
            edge[step, :, 2] = scale * 0.04
            edge[step, :, 3] = scale * 0.05
        arrays[f"{pilot}_elapsed_seconds"] = elapsed
        arrays[f"{pilot}_node_state"] = node
        arrays[f"{pilot}_edge_state"] = edge
    np.savez_compressed(tmp_path / "customer_swmm_gwm_dynamic_diagnostic.private.npz", **arrays)
    (tmp_path / "customer_swmm_gwm_dynamic_diagnostic_manifest.json").write_text(
        json.dumps(
            {
                "schema": "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1",
                "arrays": {
                    name: {"shape": list(array.shape), "dtype": str(array.dtype)}
                    for name, array in arrays.items()
                },
                "pilots": [{"pilot_id": "pilot_01"}, {"pilot_id": "pilot_02"}],
            }
        ),
        encoding="utf-8",
    )
    np.savez_compressed(
        tmp_path / "customer_swmm_gwm_pilot_alignment.private.npz",
        pilot_node_indices=np.asarray([0, 1, 2, 3], dtype=np.int64),
        pilot_node_offsets=np.asarray([0, 2, 4], dtype=np.int64),
    )
    return tmp_path


def test_train_rollout_and_node_timeline_are_private_tensor_backed(tmp_path, monkeypatch):
    surrogate = AbuDhabiGwmSurrogate(_private_tensor_root(tmp_path))
    monkeypatch.setattr(
        surrogate,
        "_load_geometry_index",
        lambda: {
            0: {"type": "Point", "coordinates": [54.40, 24.40]},
            1: {"type": "Point", "coordinates": [54.41, 24.41]},
            2: {"type": "Point", "coordinates": [54.42, 24.42]},
            3: {"type": "Point", "coordinates": [54.43, 24.43]},
        },
    )

    assert surrogate.status()["status"] == "ready_to_train"
    training = surrogate.train()
    assert training["pilot_count"] == 2
    assert training["pilot_ids"] == ["pilot_01", "pilot_02"]
    assert training["sample_count"] == 22
    assert set(training["metrics"]) == {"pilot_01", "pilot_02"}
    assert "tmp_path" not in json.dumps(training)
    assert surrogate._models["pilot_01"].duration_seconds == 9000.0
    assert surrogate._models["pilot_02"].duration_seconds == 12600.0

    baseline = surrogate.rollout({"pilot_id": "pilot_01", "steps": 5, "start_index": 2})
    stressed = surrogate.rollout(
        {
            "pilot_id": "pilot_01",
            "steps": 5,
            "start_index": 2,
            "rainfall_multiplier": 2.0,
            "pipe_capacity_multiplier": 0.5,
            "pump_capacity_multiplier": 0.75,
            "outfall_level_m": 0.5,
        }
    )
    assert stressed["run_id"] != baseline["run_id"]
    assert stressed["metadata"]["timeline"]["period_count"] == 5
    assert stressed["metadata"]["timeline"]["endpoint"].endswith("/timeseries")
    assert stressed["metadata"]["map_view"] == {
        "available": True,
        "center": [24.405, 54.405],
        "bounds": [[24.4, 54.4], [24.41, 54.41]],
        "zoom": 14,
        "node_feature_count": 2,
    }
    assert stressed["summary"]["peak_capacity_fraction"] != baseline["summary"]["peak_capacity_fraction"]

    frame = surrogate.timeseries(stressed["run_id"], 1)
    assert frame["metadata"]["schema"] == "gwm.abu_dhabi_flood.gwm_node_timeseries.v1"
    assert len(frame["features"]) == 2
    assert "gwm_water_depth_m" in frame["features"][0]["properties"]
    assert surrogate.bootstrap(stressed["run_id"])["timeline"]["run_id"] == stressed["run_id"]
    assert surrogate.status()["status"] == "trained"
    assert surrogate.status()["pilot_ids"] == ["pilot_01", "pilot_02"]


def test_rollout_rejects_unknown_pilot_and_invalid_action(tmp_path):
    surrogate = AbuDhabiGwmSurrogate(_private_tensor_root(tmp_path))
    surrogate.train(ridge=0)
    with pytest.raises(ValueError, match="gwm_pilot_not_found"):
        surrogate.rollout({"pilot_id": "pilot_99"})
    with pytest.raises(ValueError, match="pipe_capacity_multiplier_below_minimum"):
        surrogate.rollout({"pilot_id": "pilot_01", "pipe_capacity_multiplier": 0})
    with pytest.raises(KeyError):
        surrogate.timeseries("not-a-run", 0)


def test_stressed_rollout_stays_on_the_empirical_pilot_scale(tmp_path):
    surrogate = AbuDhabiGwmSurrogate(_private_tensor_root(tmp_path))
    surrogate.train()

    rollout = surrogate.rollout(
        {
            "pilot_id": "pilot_01",
            "steps": 12,
            "rainfall_multiplier": 4.0,
            "pipe_capacity_multiplier": 0.25,
            "pump_capacity_multiplier": 0.25,
            "outfall_level_m": 2.0,
        }
    )
    stored = surrogate._runs[rollout["run_id"]]
    node_frames = stored["_node_array"]
    edge_frames = stored["_edge_array"]
    model = stored["_model"]

    assert np.isfinite(node_frames).all()
    assert np.isfinite(edge_frames).all()
    assert float(node_frames[:, :, 0].max()) <= max(float(model.node_states[:, :, 0].max()) * 12.0, 0.05) + 1e-6
    assert float(edge_frames[:, :, 3].max()) <= max(float(model.edge_states[:, :, 3].max()) * 12.0, 0.05) + 1e-6


def test_latest_or_default_rollout_restores_a_stable_map_result(tmp_path, monkeypatch):
    surrogate = AbuDhabiGwmSurrogate(_private_tensor_root(tmp_path))
    monkeypatch.setattr(
        surrogate,
        "_load_geometry_index",
        lambda: {
            0: {"type": "Point", "coordinates": [54.40, 24.40]},
            1: {"type": "Point", "coordinates": [54.41, 24.41]},
        },
    )

    restored = surrogate.latest_or_default()
    repeated = surrogate.latest_or_default()

    assert restored["run_id"] == repeated["run_id"]
    assert restored["status"] == "completed"
    assert restored["metadata"]["timeline"]["period_count"] == 24
    assert restored["metadata"]["map_view"]["node_feature_count"] == 2
    assert surrogate.timeseries(restored["run_id"], 0)["features"]
