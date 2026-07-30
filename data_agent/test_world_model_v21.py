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


def test_validate_plan_request_uses_fast_demo_defaults(tmp_path):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")

    svc = WorldModelV21Service(repo_path=tmp_path)
    result = svc.validate_plan_request({
        "prepared_dir": str(prepared),
        "ensemble_dir": str(ensemble),
    })

    assert result["horizon"] == 1
    assert result["top_k"] == 1
    assert result["n_episodes"] == 1
    assert result["continuation"] == "greedy"
    assert result["scoring"] == "reward"
    assert result["env_kind"] == "county"
    assert result["threads"] == 0


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


def test_county_plan_uses_output_codes_matching_detected_input_scheme(
    tmp_path, monkeypatch
):
    prepared = tmp_path / "prepared"
    input_dir = prepared / "dem_slope_analysis" / "output"
    input_dir.mkdir(parents=True)
    (input_dir / "DLTB_with_slope.shp").write_bytes(b"shp")
    ensemble = tmp_path / "ensemble"
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    calls = {}

    def fake_run(**kwargs):
        calls.update(kwargs)
        out_dir = Path(kwargs["out_dir"])
        summary = {
            "config": {"n_blocks": 1, "n_parcels": 2, "max_steps": 1},
            "results": [
                {
                    "episode": 0,
                    "cultivated_area_change_ha": 0.0,
                    "slope_change_pct": -0.1,
                    "cont_change": 0.1,
                    "steps_run": 1,
                }
            ],
        }
        (out_dir / "mpc_summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        Path(kwargs["output_fc"]).write_bytes(b"shp")
        return summary

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_plan_run", lambda: fake_run)
    monkeypatch.setattr(
        svc,
        "_detect_land_use_code_contract",
        lambda path: {
            "compatible": True,
            "scheme": "legacy_three_digit_test_data",
            "farm_dlbm": "011",
            "forest_dlbm": "031",
            "code_counts": {"011": 1, "031": 1},
        },
    )
    monkeypatch.setattr(svc, "_convert_optimized_shp_to_fgb", lambda *args: None)

    result = svc.run_plan(
        {
            "prepared_dir": str(prepared),
            "ensemble_dir": str(ensemble),
            "env_kind": "county",
        },
        user_id="pytest",
    )

    assert calls["farm_dlbm"] == "011"
    assert calls["forest_dlbm"] == "031"
    assert result["land_use_code_contract"]["compatible"] is True


def test_run_prepare_calls_paper9_prepare_and_returns_artifacts(tmp_path, monkeypatch):
    dltb = tmp_path / "DLTB.shp"
    dem = tmp_path / "dem.tif"
    prepared = tmp_path / "prepared"
    dltb.write_bytes(b"shp")
    dem.write_bytes(b"tif")
    calls = {}

    def fake_prepare(**kwargs):
        calls.update(kwargs)
        out = Path(kwargs["prepared_dir"]) / "dem_slope_analysis" / "output"
        out.mkdir(parents=True, exist_ok=True)
        shp = out / "DLTB_with_slope.shp"
        shp.write_bytes(b"prepared")
        (Path(kwargs["prepared_dir"]) / "townships.json").write_text("{}", encoding="utf-8")
        (Path(kwargs["prepared_dir"]) / "prepare_data_summary.json").write_text(
            json.dumps({"n_parcels": 2}), encoding="utf-8"
        )
        return shp

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_prepare_run", lambda: fake_prepare)

    result = svc.run_prepare({
        "dltb_path": str(dltb),
        "dem_path": str(dem),
        "prepared_dir": str(prepared),
    }, user_id="pytest")

    assert calls["dltb_path"] == str(dltb)
    assert calls["dem_path"] == str(dem)
    assert calls["prepared_dir"] == str(prepared)
    assert result["mode"] == "tool1_prepare"
    assert result["summary"]["n_parcels"] == 2
    assert result["artifacts"]["townships"] == "townships.json"


def test_run_sample_calls_paper9_sample(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    calls = {}

    def fake_sample(**kwargs):
        calls.update(kwargs)
        out = Path(kwargs["prepared_dir"]) / "tool2"
        out.mkdir(parents=True, exist_ok=True)
        (out / "transitions.npz").write_bytes(b"tr")
        (out / "pairwise.npz").write_bytes(b"pw")
        (out / "sample_transitions_summary.json").write_text(
            json.dumps({"transitions": {"n_transitions": 3}}), encoding="utf-8"
        )
        return {"transitions": {"n_transitions": 3}}

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_sample_run", lambda: fake_sample)

    result = svc.run_sample({
        "prepared_dir": str(prepared),
        "n_transition_episodes": 2,
        "n_pairwise_states": 4,
        "n_pairwise_actions": 3,
    }, user_id="pytest")

    assert calls["prepared_dir"] == str(prepared)
    assert calls["n_transition_episodes"] == 2
    assert result["mode"] == "tool2_sample"
    assert result["artifacts"]["transitions_npz"] == "tool2/transitions.npz"


def test_run_train_calls_paper9_train_and_discovers_onnx(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    calls = {}

    def fake_train(**kwargs):
        calls.update(kwargs)
        out = Path(kwargs["prepared_dir"]) / kwargs["out_subdir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "ensemble_member0.onnx").write_bytes(b"onnx")
        (out / "train_summary.json").write_text(
            json.dumps({"members": [{"index": 0}]}), encoding="utf-8"
        )
        return {"members": [{"index": 0}]}

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_train_run", lambda: fake_train)

    result = svc.run_train({
        "prepared_dir": str(prepared),
        "n_members": 1,
        "epochs": 1,
        "out_subdir": "ensemble_seed0",
    }, user_id="pytest")

    assert calls["n_members"] == 1
    assert calls["epochs"] == 1
    assert result["mode"] == "tool3_train"
    assert result["onnx_member_count"] == 1
    assert result["ensemble_dir"].endswith("ensemble_seed0")


def test_map_config_styles_optimized_fgb_by_change_flag(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path)
    result = svc._build_map_config(tmp_path / "optimized_dltb.fgb")

    layer = result["layers"][0]
    assert layer["type"] == "fgb"
    assert layer["category_column"] == "CHG_FLAG"
    assert layer["legend_title"] == "耕地空间布局优化"
    assert layer["category_labels"] == {
        "0": "保持不变",
        "1": "耕地 -> 林地",
        "2": "林地 -> 耕地",
    }
    assert layer["style_map"]["0"]["fillOpacity"] < 0.2
    assert layer["style_map"]["1"]["fillColor"] == "#DC2626"
    assert layer["style_map"]["2"]["fillColor"] == "#16A34A"
    assert "OPT_DLBM" in layer["tooltip_fields"]
    assert layer["tooltip_labels"]["CHG_FLAG"] == "变化"


def test_run_pipeline_reuses_existing_prepared_and_ensemble_then_plans(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    (prepared / "dem_slope_analysis" / "output").mkdir(parents=True)
    (prepared / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp").write_bytes(b"shp")
    (prepared / "townships.json").write_text("{}", encoding="utf-8")
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(
        svc,
        "run_plan",
        lambda payload, user_id: {
            "status": "ok",
            "mode": "tool4_mpc",
            "prepared_dir": payload["prepared_dir"],
            "ensemble_dir": payload["ensemble_dir"],
            "summary": {"steps_run": 100},
        },
    )

    result = svc.run_pipeline({
        "prepared_dir": str(prepared),
        "ensemble_dir": str(ensemble),
        "reuse_existing": True,
        "run_prepare": True,
        "run_sample": False,
        "run_train": True,
        "run_plan": True,
    }, user_id="pytest")

    statuses = [(step["step"], step["status"]) for step in result["steps"][:2]]
    assert statuses == [("prepare", "skipped_reused"), ("train", "skipped_reused")]
    assert result["plan_result"]["summary"]["steps_run"] == 100


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
