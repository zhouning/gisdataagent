from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent import abu_dhabi_surface_run_service as service


def test_validate_surface_request_exposes_real_runner_parameters() -> None:
    scenario = service.validate_surface_request(
        {
            "return_period_years": 25,
            "cell_size_m": 250,
            "peak_position_percent": 45,
            "land_manning_n": 0.04,
            "water_manning_n": 0.02,
            "initial_depth_m": 0.03,
            "minimum_output_depth_m": 0.015,
            "tail_minutes": 180,
            "output_interval_minutes": 15,
            "sea_boundary_level_m": 0.25,
            "water_cell_fraction_threshold": 0.25,
        }
    )

    assert scenario["solver"] == "anuga"
    assert scenario["return_period_years"] == 25
    assert scenario["peak_position_percent"] == 45
    assert scenario["land_manning_n"] == 0.04
    assert scenario["tail_minutes"] == 180
    assert scenario["sea_boundary_level_m"] == 0.25


def test_validate_surface_request_rejects_unwired_coupling() -> None:
    with pytest.raises(ValueError, match="surface_coupling_mode_not_available"):
        service.validate_surface_request({"coupling_mode": "two_way"})


def test_surface_worker_keeps_new_run_separate_and_publishes_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "runs"
    terrain = tmp_path / "customer_dtm.tif"
    land_cover = tmp_path / "land_cover.tif"
    terrain.touch()
    land_cover.touch()

    class FakeRunner:
        @staticmethod
        def run(dem_path: Path, land_cover_path: Path, output: Path, **kwargs):
            assert dem_path == terrain
            assert land_cover_path == land_cover
            output.mkdir(parents=True, exist_ok=True)
            maximum = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": []},
                        "properties": {"maximum_depth_m": 0.4},
                    }
                ],
            }
            (output / "maximum_depth_wgs84.geojson").write_text(json.dumps(maximum), encoding="utf-8")
            snapshot_dir = output / "temporal_snapshots"
            snapshot_dir.mkdir()
            snapshot = {"type": "FeatureCollection", "features": maximum["features"]}
            (snapshot_dir / "surface_depth_t000.geojson").write_text(json.dumps(snapshot), encoding="utf-8")
            (snapshot_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "index": 0,
                                "time_seconds": 0,
                                "time_minutes": 0,
                                "path": "temporal_snapshots/surface_depth_t000.geojson",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            summary = {
                "status": "completed",
                "solver": "ANUGA 2D",
                "surface": {
                    "product": "placeholder",
                    "evidence_class": "placeholder",
                    "source_resolution_m": [5, 5],
                    "land_water_mask": {"product": "test-mask"},
                },
                "domain": {
                    "bounds_epsg32640": [0, 0, 1, 1],
                    "area_m2": 1,
                    "cell_size_m": kwargs["cell_size_m"],
                    "active_land_cells": 1,
                    "excluded_permanent_water_cells": 0,
                    "output_step_minutes": kwargs["output_interval_minutes"],
                },
                "forcing": {"return_period_years": kwargs["return_period_years"]},
                "land_water_treatment": {
                    "product": "test-mask",
                    "water_cell_fraction_threshold": kwargs["water_cell_fraction_threshold"],
                    "sea_boundary_level_m": kwargs["sea_boundary_level_m"],
                },
                "results": {"maximum_depth_m": 0.4, "inundated_area_ge_0_01m2": 1},
            }
            (output / "delivery_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            return summary

    monkeypatch.setattr(service, "_run_root", lambda: run_root)
    monkeypatch.setattr(service, "_terrain_path", lambda _: (terrain, "Customer test DTM", "customer_authoritative"))
    monkeypatch.setattr(service, "DEFAULT_LAND_COVER", land_cover)
    monkeypatch.setattr(service, "_load_runner", lambda: FakeRunner)
    service._RUNS.clear()

    created = service.start_surface_run({"return_period_years": 10, "cell_size_m": 250})
    run_id = created["run_id"]
    service._RUNS[run_id]["future"].result(timeout=5)

    completed = service.public_surface_run(run_id)
    bootstrap = service.surface_map_bootstrap(run_id)
    frame = service.surface_map_timeseries(run_id, 0)

    assert completed["status"] == "completed"
    assert (run_root / run_id / "surface_manifest.json").is_file()
    assert bootstrap["metadata"]["model_configuration"]["execution_mode"] == "interactive_anuga_run"
    assert bootstrap["metadata"]["timeline"]["run_id"] == run_id
    assert bootstrap["maximum_depth"]["type"] == "FeatureCollection"
    assert frame["metadata"]["run_id"] == run_id
