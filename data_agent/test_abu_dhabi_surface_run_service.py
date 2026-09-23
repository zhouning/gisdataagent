from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("one_way_swmm_to_anuga", "one_way_swmm_to_anuga"),
        ("two_way", "two_way_swmm_anuga"),
        ("two_way_swmm_anuga", "two_way_swmm_anuga"),
    ],
)
def test_validate_surface_request_accepts_wired_coupling_modes(
    requested: str, expected: str
) -> None:
    scenario = service.validate_surface_request(
        {
            "coupling_mode": requested,
            "cell_size_m": 250,
            "terrain_source": "customer_dtm_5m",
            "exchange_window_seconds": 300,
        }
    )

    assert scenario["coupling_mode"] == expected
    assert scenario["solver_label"] == "EPA SWMM 5.2.4 + ANUGA 2D"
    assert scenario["exchange_window_seconds"] == 300


def test_validate_surface_request_rejects_unknown_coupling() -> None:
    with pytest.raises(ValueError, match="surface_coupling_mode_invalid"):
        service.validate_surface_request({"coupling_mode": "not_a_solver"})


def test_validate_surface_request_rejects_non_five_minute_coupling_window() -> None:
    with pytest.raises(ValueError, match="surface_coupling_exchange_window_not_supported"):
        service.validate_surface_request(
            {
                "coupling_mode": "two_way_swmm_anuga",
                "cell_size_m": 250,
                "terrain_source": "customer_dtm_5m",
                "exchange_window_seconds": 420,
            }
        )


def test_coupled_runner_receives_generated_return_period_specific_swmm_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "deploy/abu-dhabi-hydrodynamics/fixtures/swmm_synthetic.inp"
    )
    base_input = tmp_path / "abu_dhabi_city_full_topology.inp"
    base_input.write_text(
        fixture.read_text(encoding="utf-8").replace("RG1", "RG_PUBLIC"),
        encoding="utf-8",
    )
    runtime_paths = {
        "python": tmp_path / "python",
        "runner": tmp_path / "runner.py",
        "swmm_input": base_input,
        "swmm_library": tmp_path / "libswmm5.so",
        "terrain_grid": tmp_path / "terrain_grid_250m.npz",
        "bindings": tmp_path / "interface_bindings.jsonl.gz",
    }
    for name, path in runtime_paths.items():
        if name != "swmm_input":
            path.touch()
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "delivery_summary.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "model_configuration": {
                        "execution_mode": "interactive_swmm_anuga_coupled_run"
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="completed\n", stderr="")

    monkeypatch.setattr(service, "_coupled_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(service.subprocess, "run", fake_run)

    summaries = []
    generated_inputs = []
    for return_period in (2, 100):
        output = tmp_path / f"rp{return_period:03d}"
        scenario = service.validate_surface_request(
            {
                "coupling_mode": "two_way_swmm_anuga",
                "cell_size_m": 250,
                "terrain_source": "customer_dtm_5m",
                "return_period_years": return_period,
                "tail_minutes": 0,
                "exchange_window_seconds": 300,
            }
        )
        summaries.append(
            service._run_coupled_model(f"test-rp{return_period}", scenario, output)
        )
        generated_inputs.append(output / "coupled_scenario.inp")

    assert all(path.is_file() for path in generated_inputs)
    assert generated_inputs[0].read_bytes() != generated_inputs[1].read_bytes()
    assert summaries[0]["forcing"]["generated_total_depth_mm"] == pytest.approx(11.31)
    assert summaries[1]["forcing"]["generated_total_depth_mm"] == pytest.approx(60.33)
    assert summaries[0]["input_provenance"]["base_swmm_input"]["sha256"] == summaries[1][
        "input_provenance"
    ]["base_swmm_input"]["sha256"]
    assert summaries[0]["input_provenance"]["generated_swmm_input"]["sha256"] != summaries[1][
        "input_provenance"
    ]["generated_swmm_input"]["sha256"]
    for command, generated_input in zip(commands, generated_inputs, strict=True):
        assert command[command.index("--swmm-inp") + 1] == str(generated_input)


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


def test_coupled_surface_worker_uses_real_runner_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "runs"

    def fake_coupled(run_id: str, scenario: dict, output: Path) -> dict:
        assert scenario["coupling_mode"] == "two_way_swmm_anuga"
        output.mkdir(parents=True, exist_ok=True)
        maximum = {"type": "FeatureCollection", "features": []}
        (output / "maximum_depth_wgs84.geojson").write_text(
            json.dumps(maximum), encoding="utf-8"
        )
        snapshot_dir = output / "temporal_snapshots"
        snapshot_dir.mkdir()
        (snapshot_dir / "surface_depth_t000.geojson").write_text(
            json.dumps(maximum), encoding="utf-8"
        )
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "index": 0,
                            "time_seconds": 300,
                            "time_minutes": 5,
                            "path": "temporal_snapshots/surface_depth_t000.geojson",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "solver": "EPA SWMM 5.2.4 + ANUGA 2D",
            "surface": {
                "product": "Customer test grid",
                "evidence_class": "mounted_customer_runtime_artifact",
            },
            "domain": {
                "cell_size_m": 250,
                "active_land_cells": 4,
                "output_step_minutes": 5,
            },
            "results": {"maximum_depth_m": 0.2},
            "coupling_summary": {
                "window_count": 1,
                "interface_count": 1,
                "quality_passed": True,
            },
            "forcing": {
                "return_period_years": 10,
                "generated_total_depth_mm": 28.71,
            },
            "input_provenance": {
                "base_swmm_input": {"sha256": "a" * 64},
                "generated_swmm_input": {"sha256": "b" * 64},
            },
        }

    monkeypatch.setattr(service, "_run_root", lambda: run_root)
    monkeypatch.setattr(service, "_run_coupled_model", fake_coupled)
    service._RUNS.clear()

    created = service.start_surface_run(
        {
            "coupling_mode": "two_way_swmm_anuga",
            "cell_size_m": 250,
            "terrain_source": "customer_dtm_5m",
            "tail_minutes": 0,
        }
    )
    run_id = created["run_id"]
    service._RUNS[run_id]["future"].result(timeout=5)

    completed = service.public_surface_run(run_id)
    bootstrap = service.surface_map_bootstrap(run_id)

    assert completed["status"] == "completed"
    assert bootstrap["metadata"]["model_configuration"]["execution_mode"] == (
        "interactive_swmm_anuga_coupled_run"
    )
    assert bootstrap["metadata"]["coupling_summary"]["quality_passed"] is True
    manifest = json.loads(
        (run_root / run_id / "surface_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["forcing"]["generated_total_depth_mm"] == 28.71
    assert manifest["input_provenance"]["generated_swmm_input"]["sha256"] == "b" * 64
