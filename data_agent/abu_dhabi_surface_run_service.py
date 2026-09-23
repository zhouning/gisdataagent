"""Private, auditable ANUGA surface-model jobs for Abu Dhabi phase 3.

The interactive endpoint creates new output directories and never mutates the
registered 2/5/10/25/50/100-year products. It supports rainfall-only ANUGA,
one-way SWMM overflow transfer, and synchronous SWMM--ANUGA exchange when the
mounted customer runtime artifacts are present. LISFLOOD-FP remains a separate
GPL runtime image and is intentionally not executed inside this API process.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from .abu_dhabi_flood_scenario_service import render_scenario_input, validate_scenario


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HYDRO_DATA_ROOT = Path(
    os.environ.get(
        "ABU_DHABI_HYDRO_DATA_ROOT",
        str(Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater"),
    )
).expanduser()
DEFAULT_PRIVATE_ROOT = _HYDRO_DATA_ROOT
DEFAULT_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "customer_interactive_surface_runs"
DEFAULT_CUSTOMER_DTM = Path(
    os.environ.get(
        "ABU_DHABI_CUSTOMER_DTM_PATH",
        str(_HYDRO_DATA_ROOT / "source/AUH_DTM_5m_Z40.TIF"),
    )
).expanduser()
DEFAULT_PUBLIC_DEM = Path(
    os.environ.get(
        "ABU_DHABI_PUBLIC_DEM_PATH",
        str(REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif"),
    )
).expanduser()
DEFAULT_LAND_COVER = Path(
    os.environ.get(
        "ABU_DHABI_LAND_COVER_PATH",
        str(REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"),
    )
).expanduser()
RUNNER_PATH = Path(
    os.environ.get(
        "ABU_DHABI_SURFACE_RUNNER_PATH",
        str(REPOSITORY_ROOT / "scripts/run_abu_dhabi_public_citywide_2d.py"),
    )
).expanduser()
COUPLED_RUNNER_PATH = Path(
    os.environ.get(
        "ABU_DHABI_COUPLED_RUNNER_PATH",
        str(REPOSITORY_ROOT / "scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py"),
    )
).expanduser()
DEFAULT_SWMM_INPUT = Path(
    os.environ.get(
        "ABU_DHABI_SWMM_FULL_CITY_INPUT",
        str(_HYDRO_DATA_ROOT / "swmm/abu_dhabi_city_full_topology.inp"),
    )
).expanduser()
DEFAULT_TERRAIN_GRID = Path(
    os.environ.get(
        "ABU_DHABI_TERRAIN_GRID_PATH",
        str(_HYDRO_DATA_ROOT / "surface/terrain_grid_250m.npz"),
    )
).expanduser()
DEFAULT_INTERFACE_BINDINGS = Path(
    os.environ.get(
        "ABU_DHABI_COUPLING_BINDINGS_PATH",
        str(_HYDRO_DATA_ROOT / "coupling/interface_bindings.jsonl.gz"),
    )
).expanduser()
SUPPORTED_RETURN_PERIODS = {2, 5, 10, 25, 50, 100}
SUPPORTED_COUPLING_MODES = {
    "surface_rainfall_only",
    "one_way_swmm_to_anuga",
    "two_way_swmm_anuga",
}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abu-surface")
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_LOCK = threading.RLock()
_COUPLED_SCENARIO_START_TIME = "2024-04-16T00:00"


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


def _run_root() -> Path:
    return _configured_path("ABU_DHABI_SURFACE_INTERACTIVE_RUN_ROOT", DEFAULT_RUN_ROOT).resolve()


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(payload: dict[str, Any], name: str, default: float, minimum: float, maximum: float) -> float:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name}_invalid")
    result = float(value)
    if result < minimum or result > maximum:
        raise ValueError(f"{name}_out_of_range")
    return result


def validate_surface_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("surface_payload_invalid")
    if payload.get("solver", "anuga") != "anuga":
        raise ValueError("surface_solver_not_available")
    requested_coupling_mode = str(payload.get("coupling_mode", "surface_rainfall_only"))
    coupling_mode = {
        "two_way": "two_way_swmm_anuga",
        "bidirectional": "two_way_swmm_anuga",
    }.get(requested_coupling_mode, requested_coupling_mode)
    if coupling_mode not in SUPPORTED_COUPLING_MODES:
        raise ValueError("surface_coupling_mode_invalid")
    if payload.get("rainfall_source", "zone_b_design_storm") != "zone_b_design_storm":
        raise ValueError("surface_rainfall_source_not_available")
    if payload.get("domain", "citywide") != "citywide":
        raise ValueError("surface_domain_not_available")
    if payload.get("boundary_type", "fixed_stage") != "fixed_stage":
        raise ValueError("surface_boundary_type_not_available")
    if int(payload.get("rainfall_duration_minutes", 180)) != 180:
        raise ValueError("zone_b_ddf_duration_must_be_180_minutes")
    try:
        return_period = int(payload.get("return_period_years", 10))
    except (TypeError, ValueError) as error:
        raise ValueError("return_period_years_invalid") from error
    if return_period not in SUPPORTED_RETURN_PERIODS:
        raise ValueError("return_period_years_not_supported")
    terrain_source = str(payload.get("terrain_source", "customer_dtm_5m"))
    if terrain_source not in {"customer_dtm_5m", "copernicus_dem_glo30"}:
        raise ValueError("terrain_source_invalid")
    cell_size = _number(payload, "cell_size_m", 250.0, 50.0, 500.0)
    if cell_size not in {250.0, 500.0}:
        raise ValueError("cell_size_m_not_supported")
    output_interval = int(_number(payload, "output_interval_minutes", 30, 5, 60))
    if output_interval not in {5, 10, 15, 30, 60}:
        raise ValueError("output_interval_minutes_not_supported")
    exchange_window_seconds = int(_number(payload, "exchange_window_seconds", 300, 60, 3600))
    simulation_duration_seconds = (180 + int(_number(payload, "tail_minutes", 120, 0, 1440))) * 60
    if coupling_mode != "surface_rainfall_only" and exchange_window_seconds not in {
        300,
        600,
        900,
        1800,
        3600,
    }:
        raise ValueError("surface_coupling_exchange_window_not_supported")
    if coupling_mode != "surface_rainfall_only" and simulation_duration_seconds % exchange_window_seconds:
        raise ValueError("surface_coupling_duration_must_align_window")
    if coupling_mode != "surface_rainfall_only" and cell_size != 250.0:
        raise ValueError("surface_coupling_requires_250m_mounted_grid")
    if coupling_mode != "surface_rainfall_only" and terrain_source != "customer_dtm_5m":
        raise ValueError("surface_coupling_requires_customer_terrain_grid")
    binding_limit_value = payload.get("binding_limit")
    binding_limit = None
    if binding_limit_value not in (None, ""):
        binding_limit = int(_number(payload, "binding_limit", 1, 1, 200000))
    scenario = {
        "solver": "anuga",
        "solver_label": (
            "EPA SWMM 5.2.4 + ANUGA 2D"
            if coupling_mode != "surface_rainfall_only"
            else "ANUGA 2D"
        ),
        "coupling_mode": coupling_mode,
        "rainfall_source": "zone_b_design_storm",
        "return_period_years": return_period,
        "rainfall_duration_minutes": 180,
        "peak_position_percent": _number(payload, "peak_position_percent", 40, 5, 95),
        "terrain_source": terrain_source,
        "domain": "citywide",
        "cell_size_m": cell_size,
        "land_manning_n": _number(payload, "land_manning_n", 0.035, 0.005, 0.2),
        "water_manning_n": _number(payload, "water_manning_n", 0.02, 0.005, 0.2),
        "initial_depth_m": _number(payload, "initial_depth_m", 0.0, 0.0, 2.0),
        "minimum_output_depth_m": _number(payload, "minimum_output_depth_m", 0.01, 0.0001, 0.5),
        "tail_minutes": int((simulation_duration_seconds // 60) - 180),
        "output_interval_minutes": output_interval,
        "boundary_type": "fixed_stage",
        "sea_boundary_level_m": _number(payload, "sea_boundary_level_m", 0.0, -5.0, 10.0),
        "water_cell_fraction_threshold": _number(payload, "water_cell_fraction_threshold", 0.2, 0.0, 1.0),
        "exchange_window_seconds": exchange_window_seconds,
        "opening_area_m2": _number(payload, "opening_area_m2", 0.5, 0.0, 100.0),
        "discharge_coefficient": _number(payload, "discharge_coefficient", 0.61, 0.0, 1.0),
        "maximum_exchange_rate_m3s": _number(
            payload, "maximum_exchange_rate_m3s", 5.0, 0.0001, 1000.0
        ),
        "interface_detail_limit": int(
            _number(payload, "interface_detail_limit", 200, 0, 10000)
        ),
        "binding_limit": binding_limit,
    }
    return scenario


def _load_runner():
    spec = importlib.util.spec_from_file_location("abu_dhabi_interactive_surface_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("surface_runner_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coupled_runtime_paths() -> dict[str, Path]:
    return {
        "python": _configured_path(
            "ABU_DHABI_ANUGA_PYTHON", Path(sys.executable)
        ).resolve(),
        "runner": _configured_path(
            "ABU_DHABI_COUPLED_RUNNER_PATH", COUPLED_RUNNER_PATH
        ).resolve(),
        "swmm_input": _configured_path(
            "ABU_DHABI_SWMM_FULL_CITY_INPUT", DEFAULT_SWMM_INPUT
        ).resolve(),
        "swmm_library": _configured_path(
            "ABU_DHABI_SWMM_LIBRARY",
            REPOSITORY_ROOT / "external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib",
        ).resolve(),
        "terrain_grid": _configured_path(
            "ABU_DHABI_TERRAIN_GRID_PATH", DEFAULT_TERRAIN_GRID
        ).resolve(),
        "bindings": _configured_path(
            "ABU_DHABI_COUPLING_BINDINGS_PATH", DEFAULT_INTERFACE_BINDINGS
        ).resolve(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_coupled_swmm_input(
    base_input: Path,
    output: Path,
    scenario: dict[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    exchange_interval_minutes = int(scenario["exchange_window_seconds"] // 60)
    swmm_scenario = validate_scenario(
        {
            "scope": "citywide",
            "rainfallMode": "design_storm",
            "rainfallPattern": "official_zone_b_ddf_abm",
            "returnPeriodYears": scenario["return_period_years"],
            "startTime": _COUPLED_SCENARIO_START_TIME,
            "durationMinutes": scenario["rainfall_duration_minutes"],
            "tailMinutes": scenario["tail_minutes"],
            "peakPosition": scenario["peak_position_percent"],
            "spatialPattern": "uniform",
            "pipeScope": "none",
            "blockagePercent": 0,
            "pipeCapacityMultiplier": 1,
            "pumpEnabled": True,
            "pumpCapacityMultiplier": 1,
            "outfallMode": "open",
            "outfallLevelM": 0,
            "outputIntervalMinutes": exchange_interval_minutes,
        }
    )
    scenario_input = output / "coupled_scenario.inp"
    rewrite = render_scenario_input(base_input, scenario_input, swmm_scenario)
    rainfall = dict(rewrite.get("rainfall") or {})
    forcing = {
        **rainfall,
        "rainfall_mode": swmm_scenario["rainfall_mode"],
        "rainfall_pattern": swmm_scenario["rainfall_pattern"],
        "return_period_years": swmm_scenario["return_period_years"],
        "start_time": swmm_scenario["start_time"],
        "duration_minutes": swmm_scenario["duration_minutes"],
        "tail_minutes": swmm_scenario["tail_minutes"],
        "peak_position_percent": swmm_scenario["peak_position"],
        "swmm_report_interval_minutes": swmm_scenario["output_interval_minutes"],
    }
    provenance = {
        "base_swmm_input": {
            "source": "mounted_customer_runtime_artifact",
            "size_bytes": base_input.stat().st_size,
            "sha256": _sha256(base_input),
        },
        "generated_swmm_input": {
            "path": scenario_input.name,
            "size_bytes": scenario_input.stat().st_size,
            "sha256": _sha256(scenario_input),
        },
        "renderer": "abu_dhabi_flood_scenario_service.render_scenario_input",
    }
    return scenario_input, forcing, provenance


def _run_coupled_model(run_id: str, scenario: dict[str, Any], output: Path) -> dict[str, Any]:
    paths = _coupled_runtime_paths()
    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(f"surface_coupled_{name}_missing:{path}")
    scenario_input, forcing, input_provenance = _render_coupled_swmm_input(
        paths["swmm_input"], output, scenario
    )
    duration_seconds = int(
        (scenario["rainfall_duration_minutes"] + scenario["tail_minutes"]) * 60
    )
    command = [
        str(paths["python"]),
        str(paths["runner"]),
        "--swmm-inp",
        str(scenario_input),
        "--swmm-library",
        str(paths["swmm_library"]),
        "--grid",
        str(paths["terrain_grid"]),
        "--bindings",
        str(paths["bindings"]),
        "--output",
        str(output),
        "--duration-seconds",
        str(duration_seconds),
        "--window-seconds",
        str(scenario["exchange_window_seconds"]),
        "--coupling-mode",
        str(scenario["coupling_mode"]),
        "--return-period-years",
        str(scenario["return_period_years"]),
        "--opening-area-m2",
        str(scenario["opening_area_m2"]),
        "--discharge-coefficient",
        str(scenario["discharge_coefficient"]),
        "--maximum-exchange-rate-m3s",
        str(scenario["maximum_exchange_rate_m3s"]),
        "--surface-manning-n",
        str(scenario["land_manning_n"]),
        "--initial-depth-m",
        str(scenario["initial_depth_m"]),
        "--minimum-output-depth-m",
        str(scenario["minimum_output_depth_m"]),
        "--interface-detail-limit",
        str(scenario["interface_detail_limit"]),
        "--terrain-label",
        "Customer AUH_DTM 5 m derived 250 m grid",
        "--run-id",
        run_id,
        "--quiet",
    ]
    if scenario.get("binding_limit") is not None:
        command.extend(["--binding-limit", str(scenario["binding_limit"])])
    timeout_seconds = int(os.environ.get("ABU_DHABI_COUPLED_RUN_TIMEOUT_SECONDS", "21600"))
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    (output / "coupled_runner.log").write_text(
        (completed.stdout or "") + (completed.stderr or ""), encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(f"surface_coupled_runner_failed:{completed.returncode}")
    summary_path = output / "delivery_summary.json"
    if not summary_path.is_file():
        raise RuntimeError("surface_coupled_summary_missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise RuntimeError("surface_coupled_summary_invalid")
    summary["forcing"] = forcing
    summary["input_provenance"] = input_provenance
    model_configuration = dict(summary.get("model_configuration") or {})
    model_configuration.update(
        {
            "swmm_scenario_input": scenario_input.name,
            "swmm_scenario_input_sha256": input_provenance["generated_swmm_input"]["sha256"],
            "swmm_base_input_sha256": input_provenance["base_swmm_input"]["sha256"],
            "rainfall_pattern": forcing["rainfall_pattern"],
            "rainfall_start_time": forcing["start_time"],
            "rainfall_total_depth_mm": forcing.get("generated_total_depth_mm"),
        }
    )
    summary["model_configuration"] = model_configuration
    _json_write(summary_path, summary)
    return summary


def _terrain_path(terrain_source: str) -> tuple[Path, str, str]:
    if terrain_source == "customer_dtm_5m":
        return (
            _configured_path("ABU_DHABI_CUSTOMER_DTM_PATH", DEFAULT_CUSTOMER_DTM).resolve(),
            "Customer AUH_DTM_5m_Z40",
            "customer_authoritative",
        )
    return DEFAULT_PUBLIC_DEM.resolve(), "Copernicus DEM GLO-30", "public_proxy"


def _update_run(run_id: str, **changes: Any) -> None:
    with _RUN_LOCK:
        current = _RUNS.setdefault(run_id, {"run_id": run_id})
        current.update(changes)


def _worker(run_id: str, scenario: dict[str, Any]) -> None:
    output = _run_root() / run_id
    manifest_path = output / "surface_manifest.json"
    manifest = {
        "run_id": run_id,
        "status": "running",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scenario": scenario,
        "claim_boundary": "Diagnostic ANUGA surface run; not calibrated or engineering-admitted.",
    }
    _json_write(manifest_path, manifest)
    _update_run(run_id, status="running", manifest=manifest)
    try:
        if scenario["coupling_mode"] == "surface_rainfall_only":
            dem_path, product, evidence_class = _terrain_path(scenario["terrain_source"])
            if not dem_path.is_file():
                raise ValueError("surface_terrain_missing")
            if not DEFAULT_LAND_COVER.is_file():
                raise ValueError("surface_land_cover_missing")
            runner = _load_runner()
            summary = runner.run(
                dem_path,
                DEFAULT_LAND_COVER,
                output,
                return_period_years=scenario["return_period_years"],
                cell_size_m=scenario["cell_size_m"],
                peak_position_percent=scenario["peak_position_percent"],
                tail_minutes=scenario["tail_minutes"],
                output_interval_minutes=scenario["output_interval_minutes"],
                land_manning_n=scenario["land_manning_n"],
                water_manning_n=scenario["water_manning_n"],
                sea_boundary_level_m=scenario["sea_boundary_level_m"],
                initial_depth_m=scenario["initial_depth_m"],
                minimum_output_depth_m=scenario["minimum_output_depth_m"],
                water_cell_fraction_threshold=scenario["water_cell_fraction_threshold"],
            )
            surface = dict(summary.get("surface") or {})
            surface.update(
                {
                    "product": product,
                    "evidence_class": evidence_class,
                    "source_resolution_m": [5.0, 5.0] if scenario["terrain_source"] == "customer_dtm_5m" else surface.get("source_resolution_m"),
                }
            )
            summary["surface"] = surface
        else:
            summary = _run_coupled_model(run_id, scenario, output)
        summary["run_id"] = run_id
        summary["status"] = (
            "completed_interactive_surface_run_not_engineering_admitted"
            if scenario["coupling_mode"] == "surface_rainfall_only"
            else "completed_interactive_coupled_surface_run_not_engineering_admitted"
        )
        model_configuration = dict(summary.get("model_configuration") or {})
        model_configuration.update(scenario)
        summary["model_configuration"] = model_configuration
        _json_write(output / "delivery_summary.json", summary)
        manifest.update(
            {
                "status": "completed",
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "forcing": summary.get("forcing") or {},
                "input_provenance": summary.get("input_provenance") or {},
                "summary": summary,
            }
        )
    except Exception as error:
        manifest.update(
            {
                "status": "failed",
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "failure_reason": type(error).__name__,
                "failure_detail": str(error)[:1000],
            }
        )
    _json_write(manifest_path, manifest)
    _update_run(run_id, status=manifest["status"], manifest=manifest)


def start_surface_run(payload: dict[str, Any]) -> dict[str, Any]:
    scenario = validate_surface_request(payload)
    run_id = f"abu-surface-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    initial = {
        "run_id": run_id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scenario": scenario,
    }
    with _RUN_LOCK:
        _RUNS[run_id] = initial
    future: Future[None] = _EXECUTOR.submit(_worker, run_id, scenario)
    with _RUN_LOCK:
        _RUNS[run_id]["future"] = future
    return public_surface_run(run_id)


def public_surface_run(run_id: str) -> dict[str, Any]:
    if not isinstance(run_id, str) or not _IDENTIFIER.fullmatch(run_id):
        raise ValueError("surface_run_id_invalid")
    with _RUN_LOCK:
        item = dict(_RUNS.get(run_id, {}))
    if not item:
        manifest_path = _run_root() / run_id / "surface_manifest.json"
        if not manifest_path.is_file():
            raise KeyError("surface_run_not_found")
        item = json.loads(manifest_path.read_text(encoding="utf-8"))
    item.pop("future", None)
    manifest = item.get("manifest")
    if isinstance(manifest, dict):
        item = dict(manifest)
    return item


def _completed_root(run_id: str) -> tuple[Path, dict[str, Any]]:
    run = public_surface_run(run_id)
    if run.get("status") != "completed":
        raise ValueError("surface_map_requires_completed_run")
    root = _run_root() / run_id
    return root, run


def surface_map_bootstrap(run_id: str) -> dict[str, Any]:
    root, run = _completed_root(run_id)
    try:
        maximum = json.loads((root / "maximum_depth_wgs84.geojson").read_text(encoding="utf-8"))
        summary = json.loads((root / "delivery_summary.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "temporal_snapshots/manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("surface_map_assets_invalid") from error
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("surface_timeline_invalid")
    domain = summary.get("domain") or {}
    surface = summary.get("surface") or {}
    results = summary.get("results") or {}
    land_water = summary.get("land_water_treatment") or surface.get("land_water_mask") or {}
    scenario = run.get("scenario") or summary.get("model_configuration") or {}
    initial_index = 0
    for index, item in enumerate(snapshots):
        relative = Path(str(item.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("surface_snapshot_path_invalid")
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
        if payload.get("features"):
            initial_index = index
            break
    return {
        "type": "FeatureCollection",
        "name": f"{run_id}_bootstrap",
        "features": [],
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.interactive_surface_map_bootstrap.v1",
            "solver": summary.get("solver") or scenario.get("solver_label") or "ANUGA 2D",
            "result_status": summary.get("status"),
            "return_period_years": scenario.get("return_period_years"),
            "forcing": summary.get("forcing") or {},
            "surface_product": surface.get("product"),
            "surface_source": scenario.get("terrain_source"),
            "surface_source_class": surface.get("evidence_class"),
            "source_resolution_m": surface.get("source_resolution_m"),
            "model_cell_size_m": domain.get("cell_size_m"),
            "domain_bounds_epsg32640": domain.get("bounds_epsg32640"),
            "domain_area_m2": domain.get("area_m2"),
            "triangle_count": domain.get("triangle_count"),
            "model_configuration": {
                "execution_mode": (
                    "interactive_anuga_run"
                    if scenario.get("coupling_mode") == "surface_rainfall_only"
                    else "interactive_swmm_anuga_coupled_run"
                ),
                **scenario,
            },
            "coupling_summary": summary.get("coupling_summary") or {},
            "land_water_mask": {
                "applied": bool(land_water),
                "product": land_water.get("product"),
                "water_cell_fraction_threshold": land_water.get("water_cell_fraction_threshold"),
                "active_land_cells": domain.get("active_land_cells"),
                "excluded_permanent_water_cells": domain.get("excluded_permanent_water_cells"),
                "sea_boundary_level_m": land_water.get("sea_boundary_level_m"),
            },
            "maximum_depth_m": results.get("maximum_depth_m"),
            "inundated_area_ge_0_01m2": results.get("inundated_area_ge_0_01m2"),
            "inundated_area_ge_0_05m2": results.get("inundated_area_ge_0_05m2"),
            "timeline": {
                "available": True,
                "run_id": run_id,
                "endpoint": f"/api/abu-dhabi/flood/surface/runs/{run_id}/map/timeseries",
                "time_values": [f"{float(item.get('time_minutes', 0)):.0f} min" for item in snapshots],
                "elapsed_minutes": [float(item.get("time_minutes", 0)) for item in snapshots],
                "period_count": len(snapshots),
                "step_minutes": domain.get("output_step_minutes"),
                "total_cell_count": domain.get("active_land_cells"),
                "initial_time_index": initial_index,
            },
            "claim_boundary": run.get("claim_boundary"),
        },
        "maximum_depth": maximum,
    }


def surface_map_timeseries(run_id: str, time_index: int) -> dict[str, Any]:
    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("time_index_invalid")
    root, _ = _completed_root(run_id)
    try:
        manifest = json.loads((root / "temporal_snapshots/manifest.json").read_text(encoding="utf-8"))
        snapshots = manifest.get("snapshots")
        if not isinstance(snapshots, list) or time_index < 0 or time_index >= len(snapshots):
            raise ValueError("time_index_out_of_range")
        item = snapshots[time_index]
        relative = Path(str(item.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("surface_snapshot_path_invalid")
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("surface_snapshot_invalid") from error
    payload["metadata"] = {
        "schema": "gwm.abu_dhabi_flood.interactive_surface_timeseries.v1",
        "solver": "ANUGA 2D",
        "run_id": run_id,
        "time_index": time_index,
        "time_seconds": float(item.get("time_seconds", 0)),
        "time_minutes": float(item.get("time_minutes", 0)),
        "depth_field": "depth_m",
        "crs": "EPSG:4326",
        "result_status": "diagnostic_only_not_engineering_admitted",
    }
    return payload
