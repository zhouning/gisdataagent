import json
from pathlib import Path

import pytest

from data_agent.world_model_v21 import (
    WorldModelV21Service,
    WorldModelV21ValidationError,
)
import data_agent.world_model_v21 as world_model_v21_module


def test_status_missing_repo(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path / "missing")
    status = svc.status()
    assert status["status"] == "unavailable"
    assert status["paper9"]["repo_exists"] is False
    assert status["paper9"]["importable"] is False


def test_onnx_discovery_accepts_standard_and_shipped_names(tmp_path):
    (tmp_path / "ensemble_member0.onnx").write_bytes(b"onnx")
    (tmp_path / "ensemble_lam5.0_member1.onnx").write_bytes(b"onnx")
    svc = WorldModelV21Service(repo_path=tmp_path)
    members = svc.find_onnx_members(tmp_path)
    assert [p.name for p in members] == [
        "ensemble_lam5.0_member1.onnx",
        "ensemble_member0.onnx",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("horizon", 0, "horizon must be between 1 and 20"),
        ("top_k", 0, "top_k must be between 1 and 500"),
        ("n_episodes", 0, "n_episodes must be between 1 and 20"),
        ("continuation", "beam", "continuation must be 'random' or 'greedy'"),
        ("scoring", "score", "scoring must be 'reward' or 'slope'"),
        ("env_kind", "other", "env_kind must be 'county' or 'restoration'"),
    ],
)
def test_validation_rejects_bad_ranges(tmp_path, field, value, message):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    payload = {
        "prepared_dir": str(prepared),
        "ensemble_dir": str(ensemble),
        "horizon": 5,
        "top_k": 50,
        "n_episodes": 1,
        "continuation": "random",
        "scoring": "reward",
        "env_kind": "county",
    }
    payload[field] = value

    svc = WorldModelV21Service(repo_path=tmp_path)
    with pytest.raises(WorldModelV21ValidationError, match=message):
        svc.validate_plan_request(payload)


def test_run_plan_calls_paper9_with_expected_args(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    calls = {}

    def fake_run(**kwargs):
        calls.update(kwargs)
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "config": {"n_blocks": 562, "n_parcels": 562, "max_steps": 50},
            "ensemble": {"n_members": 1, "paths": ["ensemble_member0.onnx"]},
            "results": [{"episode": 0, "total_reward": 12.5, "steps_run": 50}],
            "aggregate": {
                "slope_pct_mean": 0.0,
                "cont_mean": 0.0,
                "baimu_ha_mean": 0.0,
            },
        }
        (out_dir / "mpc_summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        return summary

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_plan_run", lambda: fake_run)
    result = svc.run_plan(
        {
            "prepared_dir": str(prepared),
            "ensemble_dir": str(ensemble),
            "horizon": 2,
            "top_k": 5,
            "n_episodes": 1,
            "continuation": "greedy",
            "scoring": "reward",
            "env_kind": "restoration",
        },
        user_id="pytest",
    )

    assert calls["prepared_dir"] == str(prepared)
    assert calls["ensemble_dir"] == str(ensemble)
    assert calls["env_kind"] == "restoration"
    assert calls["horizon"] == 2
    assert calls["top_k"] == 5
    assert result["status"] == "ok"
    assert result["summary"]["total_reward"] == 12.5
    assert result["summary"]["steps_run"] == 50


def test_map_conversion_failure_is_warning(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path)
    bad_shp = tmp_path / "missing.shp"
    warnings = []

    assert svc._convert_optimized_shp_to_fgb(bad_shp, tmp_path, warnings) is None
    assert warnings and "optimized shapefile not found" in warnings[0]


def test_upload_relative_path_strips_user_directory(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path)
    uploads = Path(world_model_v21_module.__file__).resolve().parent / "uploads"
    map_layer = uploads / "admin" / "world_model_v21" / "run1" / "optimized_dltb.fgb"

    assert (
        svc._upload_relative_path(map_layer)
        == "world_model_v21/run1/optimized_dltb.fgb"
    )


def test_build_restoration_grid_geojson_from_selected_units(tmp_path):
    import numpy as np
    import pandas as pd

    prepared = tmp_path / "prepared"
    out_dir = tmp_path / "out"
    prepared.mkdir()
    out_dir.mkdir()
    pd.DataFrame({
        "unit_id": [0, 1],
        "row": [0, 1],
        "col": [0, 1],
        "area_ha": [10.0, 20.0],
        "candidate": [1, 1],
    }).to_csv(prepared / "attributes.csv", index=False)
    selected_path = out_dir / "mpc_land_use.npy"
    np.save(selected_path, np.array([0, 1], dtype="int8"))

    warnings = []
    svc = WorldModelV21Service(repo_path=tmp_path)
    geojson_path = svc._build_restoration_grid_geojson(
        prepared, out_dir, selected_path, warnings
    )

    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    labels = [f["properties"]["selected_label"] for f in data["features"]]
    assert warnings == []
    assert labels == ["not_selected", "selected"]
    assert data["features"][0]["geometry"]["type"] == "Polygon"
