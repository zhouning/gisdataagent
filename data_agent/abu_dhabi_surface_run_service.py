"""Private, auditable ANUGA surface-model jobs for Abu Dhabi phase 3.

The interactive endpoint creates new output directories and never mutates the
registered 2/5/10/25/50/100-year products.  Only capabilities that are wired
to the current new-job runner are accepted.  LISFLOOD-FP and synchronous
bidirectional coupling are not accepted by this runner, while separately
registered historical/validation assets may still be loaded read-only by the
phase-3 result service.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIVATE_ROOT = Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater"
DEFAULT_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "customer_interactive_surface_runs"
DEFAULT_CUSTOMER_DTM = Path.home() / "Downloads/阿布扎比/DTM_z40_customer/AUH_DTM_5m_Z40.TIF"
DEFAULT_PUBLIC_DEM = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif"
DEFAULT_LAND_COVER = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"
RUNNER_PATH = REPOSITORY_ROOT / "scripts/run_abu_dhabi_public_citywide_2d.py"
SUPPORTED_RETURN_PERIODS = {2, 5, 10, 25, 50, 100}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abu-surface")
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_LOCK = threading.RLock()


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
    if payload.get("coupling_mode", "surface_rainfall_only") != "surface_rainfall_only":
        raise ValueError("surface_coupling_mode_not_available_for_new_web_run")
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
    scenario = {
        "solver": "anuga",
        "solver_label": "ANUGA 2D",
        "coupling_mode": "surface_rainfall_only",
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
        "tail_minutes": int(_number(payload, "tail_minutes", 120, 0, 1440)),
        "output_interval_minutes": output_interval,
        "boundary_type": "fixed_stage",
        "sea_boundary_level_m": _number(payload, "sea_boundary_level_m", 0.0, -5.0, 10.0),
        "water_cell_fraction_threshold": _number(payload, "water_cell_fraction_threshold", 0.2, 0.0, 1.0),
    }
    return scenario


def _load_runner():
    spec = importlib.util.spec_from_file_location("abu_dhabi_interactive_surface_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("surface_runner_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        summary["run_id"] = run_id
        summary["status"] = "completed_interactive_surface_run_not_engineering_admitted"
        summary["model_configuration"] = scenario
        _json_write(output / "delivery_summary.json", summary)
        manifest.update(
            {
                "status": "completed",
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
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
            "solver": "ANUGA 2D",
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
            "model_configuration": {"execution_mode": "interactive_anuga_run", **scenario},
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
