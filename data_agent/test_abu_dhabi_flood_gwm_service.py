"""Contract tests for the isolated Abu Dhabi phase-4 GWM adapter."""

from __future__ import annotations

import json

import pytest

import data_agent.abu_dhabi_flood_gwm_service as gwm


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _feature(depth: float = 0.4, **extra):
    properties = {"cell_id": 1, "maximum_depth_m": depth}
    properties.update(extra)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[54.4, 24.4], [54.41, 24.4], [54.41, 24.41], [54.4, 24.4]]],
        },
    }


def _source(root, return_period: int = 10, features=None):
    period = root / f"rp{return_period:03d}"
    temporal = period / "temporal_snapshots"
    empty = {"type": "FeatureCollection", "features": []}
    source_features = features or [_feature(0.4)]
    frame = {"type": "FeatureCollection", "features": source_features}
    _write_json(period / "maximum_depth_wgs84.geojson", frame)
    _write_json(
        temporal / "manifest.json",
        {
            "schema": "test",
            "snapshots": [
                {"index": 0, "path": "temporal_snapshots/surface_depth_t000.geojson", "time_minutes": 0},
                {"index": 1, "path": "temporal_snapshots/surface_depth_t001.geojson", "time_minutes": 30},
            ],
        },
    )
    _write_json(temporal / "surface_depth_t000.geojson", empty)
    _write_json(temporal / "surface_depth_t001.geojson", {**frame, "features": [_feature(0.2)]})


def test_gwm_skips_empty_initial_surface_frame_without_changing_api_semantics(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10, "pipeCapacityMultiplier": 1.5})
    assert result["status"] == "completed"
    assert result["metadata"]["timeline"]["initial_time_index"] == 1

    # t=0 is still explicitly available and remains an empty physical frame.
    assert gwm.map_timeseries(result["run_id"], 0)["features"] == []
    assert len(gwm.map_timeseries(result["run_id"], 1)["features"]) == 1


def test_gwm_emits_auditable_baseline_intervention_and_delta(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()
    result = gwm.start_gwm_rollout(
        {
            "returnPeriodYears": 10,
            "pipeCapacityMultiplier": 1.5,
            "pumpCapacityMultiplier": 1.5,
            "blockagePercent": 0,
        }
    )
    assert result["metrics"]["intervention_max_depth_m"] < result["metrics"]["baseline_max_depth_m"]
    assert result["metrics"]["maximum_absolute_delta_m"] > 0
    feature = result["metadata"]
    assert feature["quality"]["uncertainty_gate"] == "screening_only"


def test_gwm_masks_water_dominated_cells_but_preserves_source_depth(tmp_path, monkeypatch):
    features = [
        _feature(0.8, land_fraction=1.0, permanent_water_fraction=0.0),
        _feature(0.6, cell_id=2, land_fraction=0.2, permanent_water_fraction=0.8),
    ]
    _source(tmp_path, features=features)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10, "pipeCapacityMultiplier": 1.5})
    baseline = result["metrics"]
    record = gwm._get(result["run_id"])
    baseline_features = record["baseline_maximum"]["features"]
    water = next(item for item in baseline_features if item["properties"]["cell_id"] == 2)
    land = next(item for item in baseline_features if item["properties"]["cell_id"] == 1)

    assert water["properties"]["source_depth_m"] == pytest.approx(0.6)
    assert water["properties"]["water_dominated"] is True
    assert water["properties"]["baseline_depth_m"] == 0
    assert water["properties"]["maximum_depth_m"] == 0
    assert land["properties"]["baseline_depth_m"] == pytest.approx(0.8)
    assert baseline["active_cell_count"] == 1
    assert baseline["excluded_water_cell_count"] == 1


def test_gwm_spatial_response_varies_with_baseline_susceptibility(tmp_path, monkeypatch):
    features = [
        _feature(0.8, land_fraction=1.0, permanent_water_fraction=0.0),
        _feature(0.2, cell_id=2, land_fraction=1.0, permanent_water_fraction=0.0),
    ]
    _source(tmp_path, features=features)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10, "pipeCapacityMultiplier": 1.5})
    record = gwm._get(result["run_id"])
    intervention_features = record["intervention_maximum"]["features"]
    high = next(item for item in intervention_features if item["properties"]["cell_id"] == 1)["properties"]
    low = next(item for item in intervention_features if item["properties"]["cell_id"] == 2)["properties"]

    assert high["spatial_response_factor"] != low["spatial_response_factor"]
    assert high["action_sensitivity_score"] > low["action_sensitivity_score"]
    assert high["intervention_depth_m"] < high["baseline_depth_m"]
    assert low["intervention_depth_m"] < low["baseline_depth_m"]


def test_gwm_public_run_exposes_surface_decision_metrics(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10, "pipeCapacityMultiplier": 1.5})
    metrics = result["metrics"]
    for key in (
        "baseline_affected_cell_count",
        "intervention_affected_cell_count",
        "baseline_affected_area_m2_proxy",
        "intervention_affected_area_m2_proxy",
        "baseline_peak_surface_storage_m3_proxy",
        "intervention_peak_surface_storage_m3_proxy",
        "peak_surface_storage_delta_m3_proxy",
    ):
        assert key in metrics
    assert metrics["baseline_affected_cell_count"] == 1
    assert metrics["baseline_affected_area_m2_proxy"] == pytest.approx(62500.0)


def test_gwm_missing_land_fraction_keeps_legacy_cells_as_land(tmp_path, monkeypatch):
    _source(tmp_path, features=[_feature(0.4)])
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10})
    record = gwm._get(result["run_id"])
    properties = record["baseline_maximum"]["features"][0]["properties"]
    assert properties["land_fraction"] == 1.0
    assert properties["water_dominated"] is False
    assert properties["baseline_depth_m"] == pytest.approx(0.4)


def test_gwm_persists_large_products_as_compressed_assets_and_reloads_them(tmp_path, monkeypatch):
    _source(tmp_path)
    run_root = tmp_path / "runs"
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(run_root))
    gwm._RUNS.clear()

    result = gwm.start_gwm_rollout({"returnPeriodYears": 10})
    run_dir = run_root / result["run_id"]
    receipt = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert "assets" in receipt
    assert "baseline_maximum" not in receipt
    assert (run_dir / receipt["assets"]["baseline_maximum"]).is_file()

    # Simulate a process restart: the compact receipt must be sufficient to
    # restore the public metrics and map products.
    gwm._RUNS.clear()
    reloaded = gwm.public_run(result["run_id"])
    assert reloaded["metrics"]["source_feature_count"] == 1
    assert len(gwm.map_bootstrap(result["run_id"])["baseline_maximum"]["features"]) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (("blockagePercent", -1), ("blockagePercent", 91), ("pipeCapacityMultiplier", 0.01)),
)
def test_gwm_rejects_out_of_range_actions(tmp_path, monkeypatch, field, value):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()
    with pytest.raises(ValueError):
        gwm.start_gwm_rollout({"returnPeriodYears": 10, field: value})


@pytest.mark.parametrize("return_period", (2, 5, 10, 25, 50, 100))
def test_gwm_accepts_all_supported_return_periods(tmp_path, monkeypatch, return_period):
    _source(tmp_path, return_period)
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()
    result = gwm.start_gwm_rollout({"returnPeriodYears": return_period})
    assert result["metadata"]["return_period_years"] == return_period
    assert result["metrics"]["source_feature_count"] == 1


def test_gwm_rejects_unsafe_snapshot_path(tmp_path, monkeypatch):
    _source(tmp_path)
    period = tmp_path / "rp010"
    _write_json(
        period / "temporal_snapshots/manifest.json",
        {"snapshots": [{"index": 0, "path": "../outside.geojson", "time_minutes": 0}]},
    )
    monkeypatch.setenv("ABU_DHABI_GWM_2D_ROOT", str(tmp_path))
    monkeypatch.setenv("ABU_DHABI_GWM_RUN_ROOT", str(tmp_path / "runs"))
    gwm._RUNS.clear()
    with pytest.raises(ValueError, match="gwm_phase3_snapshot_path_invalid"):
        gwm.start_gwm_rollout({"returnPeriodYears": 10})
