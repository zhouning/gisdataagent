"""Contracts for the Al Bateen high-resolution local flood workflow."""

from __future__ import annotations

import json

from data_agent import abu_dhabi_al_bateen_flood_service as service
from data_agent.api.abu_dhabi_flood_routes import get_abu_dhabi_flood_routes


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_workflow_uses_customer_dtm_without_citywide_gwm_interpolation():
    status = service.workflow_status()

    assert status["scope"]["name"] == "AL BATEEN"
    assert status["scope"]["district_id"] == 147
    assert status["model"]["terrain_source_resolution_m"] == 5
    assert status["model"]["default_computation_cell_size_m"] == 20
    assert status["model"]["uses_citywide_250m_gwm"] is False
    assert status["model"]["uses_250m_interpolation"] is False
    assert {item["return_period_years"] for item in status["supported_design_storms"]} == {
        2,
        5,
        10,
        25,
        50,
        100,
    }


def test_scenario_accepts_only_true_local_high_resolution_grids(monkeypatch, tmp_path):
    swmm_input = tmp_path / "scenario.inp"
    swmm_output = tmp_path / "scenario.out"
    swmm_input.write_text("[TITLE]\nfixture\n", encoding="utf-8")
    swmm_output.write_bytes(b"fixture output")
    monkeypatch.setattr(service, "_swmm_artifacts", lambda _return_period: (swmm_input, swmm_output))

    scenario = service.validate_scenario(
        {
            "returnPeriodYears": 10,
            "cellSizeM": 20,
            "tailMinutes": 120,
            "outputStepMinutes": 15,
            "tideLevelM": 0.2,
            "manningN": 0.04,
        }
    )

    assert scenario["total_depth_mm"] == 28.71
    assert scenario["cell_size_m"] == 20.0
    assert scenario["uses_citywide_250m_gwm"] is False
    assert scenario["uses_250m_interpolation"] is False

    try:
        service.validate_scenario({"returnPeriodYears": 10, "cellSizeM": 250})
    except ValueError as error:
        assert str(error) == "al_bateen_cell_size_m_must_be_10_or_20"
    else:
        raise AssertionError("250 m must not be accepted as an Al Bateen high-resolution grid")


def test_map_contract_exposes_maximum_and_time_series(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DEFAULT_RUN_ROOT", tmp_path)
    run_id = "al-bateen-fixture-run"
    run_dir = tmp_path / run_id
    summary = {
        "schema": "gisdataagent.al_bateen.high_resolution_run.v1",
        "run_id": run_id,
        "status": "completed_diagnostic_not_engineering_admitted",
        "solver": "ANUGA 2D",
        "scope": {"name": "AL BATEEN", "district_id": 147},
        "terrain": {"source_resolution_m": 5, "computation_cell_size_m": 20},
        "timeline": {"snapshot_count": 1, "output_step_minutes": 15},
        "results": {"maximum_depth_m": 0.42, "mapped_maximum_feature_count": 1},
        "claim_boundary": "Local diagnostic; no 250 m GWM interpolation.",
    }
    feature = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[54.34, 24.45], [54.341, 24.45], [54.341, 24.451], [54.34, 24.45]]]},
        "properties": {"depth_m": 0.42, "cell_size_m": 20},
    }
    _write_json(
        run_dir / "run_status.json",
        {"schema": "status", "run_id": run_id, "status": "completed", "summary": summary},
    )
    _write_json(run_dir / "maximum_depth_wgs84.geojson", {"type": "FeatureCollection", "features": [feature]})
    _write_json(
        run_dir / "temporal_snapshots/manifest.json",
        {"snapshots": [{"index": 0, "time_minutes": 0, "path": "temporal_snapshots/surface_depth_t000.geojson"}]},
    )
    _write_json(
        run_dir / "temporal_snapshots/surface_depth_t000.geojson",
        {"type": "FeatureCollection", "features": [feature]},
    )

    bootstrap = service.map_bootstrap(run_id)
    frame = service.map_timeseries(run_id, 0)

    assert bootstrap["metadata"]["cell_size_m"] == 20
    assert bootstrap["metadata"]["source_dtm_resolution_m"] == 5
    assert bootstrap["metadata"]["uses_citywide_250m_gwm"] is False
    assert len(bootstrap["features"]) == 1
    assert frame["metadata"]["time_minutes"] == 0
    assert frame["metadata"]["uses_250m_interpolation"] is False


def test_direct_runner_delivery_is_visible_after_service_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DEFAULT_RUN_ROOT", tmp_path)
    run_id = "al-bateen-acceptance-fixture"
    run_dir = tmp_path / run_id
    summary = {
        "schema": "gisdataagent.al_bateen.high_resolution_run.v1",
        "run_id": run_id,
        "status": "completed_diagnostic_not_engineering_admitted",
        "solver": "ANUGA 2D",
        "forcing": {
            "return_period_years": 10,
            "duration_minutes": 180,
            "published_total_depth_mm": 28.71,
        },
        "terrain": {"source_resolution_m": 5, "computation_cell_size_m": 20},
        "timeline": {"simulation_duration_minutes": 300, "output_step_minutes": 15},
        "results": {"maximum_depth_m": 0.42},
        "dewatering": {
            "operational_complete": False,
            "actual_tail_minutes": 120,
        },
    }
    _write_json(run_dir / "delivery_summary.json", summary)
    _write_json(
        run_dir / "run_receipt.json",
        {"status": "completed", "run_id": run_id, "return_period_years": 10, "cell_size_m": 20},
    )

    latest = service.latest_run()
    restored = service.public_run(run_id)

    assert latest["run_id"] == run_id
    assert restored["status"] == "completed"
    assert restored["scenario"]["tail_minutes"] == 120
    assert restored["scenario"]["uses_250m_interpolation"] is False
    assert restored["summary"]["dewatering"]["operational_complete"] is False


def test_precomputed_library_prefers_longer_variant_and_is_addressable(monkeypatch, tmp_path):
    run_root = tmp_path / "runs"
    library_root = tmp_path / "library"
    monkeypatch.setattr(service, "DEFAULT_RUN_ROOT", run_root)
    monkeypatch.setattr(service, "DEFAULT_LIBRARY_ROOT", library_root)

    def write_variant(run_id: str, duration_minutes: int, wet_cells: int):
        run_dir = library_root / "scenarios/rp100/20m" / run_id
        summary = {
            "schema": "gisdataagent.al_bateen.high_resolution_run.v1",
            "run_id": run_id,
            "status": "completed_diagnostic_not_engineering_admitted",
            "solver": "ANUGA 2D",
            "forcing": {
                "return_period_years": 100,
                "duration_minutes": 180,
                "published_total_depth_mm": 60.33,
            },
            "terrain": {"source_resolution_m": 5, "computation_cell_size_m": 20},
            "timeline": {
                "simulation_duration_minutes": duration_minutes,
                "snapshot_count": 2,
                "output_step_minutes": 15,
            },
            "results": {"maximum_depth_m": 1.2, "final_wet_cells_ge_0_01m": wet_cells},
            "dewatering": {"operational_complete": False},
        }
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [54.34, 24.45]},
            "properties": {"depth_m": 0.1},
        }
        _write_json(run_dir / "delivery_summary.json", summary)
        _write_json(run_dir / "maximum_depth_wgs84.geojson", {"type": "FeatureCollection", "features": [feature]})
        _write_json(
            run_dir / "temporal_snapshots/manifest.json",
            {"snapshots": [
                {"index": 0, "time_minutes": 0, "path": "temporal_snapshots/surface_depth_t000.geojson"},
                {"index": 1, "time_minutes": duration_minutes, "path": "temporal_snapshots/surface_depth_t001.geojson"},
            ]},
        )
        _write_json(run_dir / "temporal_snapshots/surface_depth_t000.geojson", {"type": "FeatureCollection", "features": []})
        _write_json(run_dir / "temporal_snapshots/surface_depth_t001.geojson", {"type": "FeatureCollection", "features": [feature]})

    write_variant("al-bateen-library-rp100-20m-48h", 3060, 7)
    write_variant("al-bateen-library-rp100-20m-96h", 5940, 4)

    catalog = service.precomputed_result_catalog()
    assert catalog["available_combination_count"] == 1
    assert catalog["entries"][0]["run_id"] == "al-bateen-library-rp100-20m-96h"
    assert catalog["entries"][0]["simulation_duration_minutes"] == 5940
    assert service.public_run("al-bateen-library-rp100-20m-96h")["status"] == "completed"
    assert service.map_bootstrap("al-bateen-library-rp100-20m-96h")["metadata"]["feature_count"] == 1
    assert service.map_timeseries("al-bateen-library-rp100-20m-96h", 1)["metadata"]["time_minutes"] == 5940


def test_al_bateen_routes_are_registered():
    paths = {route.path for route in get_abu_dhabi_flood_routes()}
    assert {
        "/api/abu-dhabi/flood/al-bateen/status",
        "/api/abu-dhabi/flood/al-bateen/library",
        "/api/abu-dhabi/flood/al-bateen/runs",
        "/api/abu-dhabi/flood/al-bateen/runs/latest",
        "/api/abu-dhabi/flood/al-bateen/runs/{run_id}",
        "/api/abu-dhabi/flood/al-bateen/runs/{run_id}/map",
        "/api/abu-dhabi/flood/al-bateen/runs/{run_id}/timeseries",
    } <= paths
