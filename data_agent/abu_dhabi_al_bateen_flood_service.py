"""Local high-resolution Al Bateen flood-simulation service.

The service is deliberately separate from the citywide 250 m GWM.  It starts
auditable ANUGA runs on the customer 5 m DTM and uses matching native SWMM
outputs as the 1D surcharge forcing for the selected Zone-B design storm.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from .abu_dhabi_zone_b_design_storm import SUPPORTED_RETURN_PERIODS, official_depth_mm


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY_UTM = (
    REPOSITORY_ROOT / "data_agent/assets/abu_dhabi/al_bateen_boundary_utm40.json"
)
DEFAULT_BOUNDARY_WGS84 = (
    REPOSITORY_ROOT / "data_agent/assets/abu_dhabi/al_bateen_boundary_wgs84.json"
)
DEFAULT_DTM = Path.home() / "Downloads/阿布扎比/DTM_z40_customer/AUH_DTM_5m_Z40.TIF"
DEFAULT_LAND_COVER = (
    Path.home()
    / "gisdataagent/benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"
)
DEFAULT_SWMM_RUN_ROOT = (
    Path.home()
    / "Downloads/阿布扎比/GDB提交版_模型工作区_20260821/customer_interactive_swmm_runs"
)
DEFAULT_RUN_ROOT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/al_bateen_high_resolution_runs"
)
DEFAULT_LIBRARY_ROOT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/"
    "al_bateen_high_resolution_result_library_v2"
)
DEFAULT_RUNNER = REPOSITORY_ROOT / "scripts/run_abu_dhabi_al_bateen_2d.py"

SWMM_RUN_NAMES = {
    2: "abu-zone-b-ddf-180m-20260826-v2-rp002",
    5: "abu-zone-b-ddf-180m-20260826-v2-rp005",
    10: "abu-zone-b-ddf-180m-20260826-v2-rp010",
    25: "abu-zone-b-ddf-180m-20260826-v2-rp025",
    50: "abu-zone-b-ddf-180m-20260826-v2-rp050",
    100: "abu-zone-b-ddf-180m-20260826-v2-rp100",
}

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="al-bateen-anuga")
_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return (Path(value).expanduser() if value else default).resolve()


def _boundary_utm_path() -> Path:
    return _configured_path("AL_BATEEN_BOUNDARY_UTM", DEFAULT_BOUNDARY_UTM)


def _boundary_wgs84_path() -> Path:
    return _configured_path("AL_BATEEN_BOUNDARY_WGS84", DEFAULT_BOUNDARY_WGS84)


def _dtm_path() -> Path:
    return _configured_path("AL_BATEEN_CUSTOMER_DTM", DEFAULT_DTM)


def _land_cover_path() -> Path:
    configured = _configured_path("AL_BATEEN_LAND_COVER", DEFAULT_LAND_COVER)
    if configured.is_file():
        return configured
    worktree_candidate = (
        REPOSITORY_ROOT
        / "benchmarks/abu_dhabi_stormwater_data_v1/online/terrain/abu_dhabi_esa_worldcover_2021_10m.tif"
    )
    return worktree_candidate.resolve()


def _swmm_root() -> Path:
    return _configured_path("AL_BATEEN_SWMM_RUN_ROOT", DEFAULT_SWMM_RUN_ROOT)


def _run_root() -> Path:
    return _configured_path("AL_BATEEN_RUN_ROOT", DEFAULT_RUN_ROOT)


def _library_root() -> Path:
    return _configured_path("AL_BATEEN_LIBRARY_ROOT", DEFAULT_LIBRARY_ROOT)


def _runner_path() -> Path:
    return _configured_path("AL_BATEEN_RUNNER", DEFAULT_RUNNER)


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("al_bateen_json_object_required")
    return value


def _swmm_artifacts(return_period_years: int) -> tuple[Path, Path] | None:
    run_name = SWMM_RUN_NAMES[return_period_years]
    full_city = _swmm_root() / run_name / "full_city"
    input_path = full_city / "scenario.inp"
    output_dir = full_city / "native_swmm_results"
    candidates = [
        path
        for path in sorted(output_dir.glob("*.out"))
        if ".failed." not in path.name and path.stat().st_size > 1024
    ]
    if not input_path.is_file() or not candidates:
        return None
    return input_path, candidates[0]


def _asset_status() -> list[dict[str, Any]]:
    dtm = _dtm_path()
    land_cover = _land_cover_path()
    boundary_utm = _boundary_utm_path()
    boundary_wgs84 = _boundary_wgs84_path()
    runner = _runner_path()
    items = [
        {
            "key": "customer_dtm_5m",
            "label": "Customer 5 m DTM",
            "ready": dtm.is_file(),
            "filename": dtm.name,
            "size_bytes": dtm.stat().st_size if dtm.is_file() else None,
            "role": "terrain_source",
        },
        {
            "key": "al_bateen_boundary",
            "label": "AL BATEEN ADM district boundary",
            "ready": boundary_utm.is_file() and boundary_wgs84.is_file(),
            "filename": boundary_utm.name,
            "role": "authoritative_local_scope",
        },
        {
            "key": "land_water_mask",
            "label": "ESA WorldCover land/water mask",
            "ready": land_cover.is_file(),
            "filename": land_cover.name,
            "role": "permanent_water_mask",
        },
        {
            "key": "anuga_runner",
            "label": "ANUGA local high-resolution runner",
            "ready": runner.is_file(),
            "filename": runner.name,
            "role": "2d_solver",
        },
    ]
    available_forcings = [
        return_period
        for return_period in SUPPORTED_RETURN_PERIODS
        if _swmm_artifacts(return_period) is not None
    ]
    items.append(
        {
            "key": "matching_swmm_forcing",
            "label": "Matching native SWMM design-storm forcing",
            "ready": bool(available_forcings),
            "available_return_periods": available_forcings,
            "role": "1d_surface_exchange",
        }
    )
    return items


def _boundary_payload() -> dict[str, Any]:
    path = _boundary_wgs84_path()
    if not path.is_file():
        return {"type": "FeatureCollection", "features": []}
    return _json_object(path)


def _completed_run_from_delivery(run_dir: Path) -> dict[str, Any] | None:
    """Expose successfully completed direct runner outputs through the same API.

    The web service writes ``run_status.json`` around an asynchronous run, while
    operator/acceptance executions of the runner intentionally write only the
    immutable delivery summary and receipt.  Treating both layouts uniformly
    keeps verified local results visible after a service restart without
    copying or interpolating any citywide GWM artifact.
    """
    summary_path = run_dir / "delivery_summary.json"
    if not summary_path.is_file():
        return None
    try:
        summary = _json_object(summary_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not str(summary.get("status") or "").startswith("completed"):
        return None
    receipt_path = run_dir / "run_receipt.json"
    try:
        receipt = _json_object(receipt_path) if receipt_path.is_file() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        receipt = {}
    forcing = summary.get("forcing") if isinstance(summary.get("forcing"), dict) else {}
    terrain = summary.get("terrain") if isinstance(summary.get("terrain"), dict) else {}
    timeline = summary.get("timeline") if isinstance(summary.get("timeline"), dict) else {}
    finished_at = datetime.utcfromtimestamp(summary_path.stat().st_mtime).isoformat(timespec="seconds") + "Z"
    duration_minutes = float(forcing.get("duration_minutes") or 180)
    simulation_minutes = float(timeline.get("simulation_duration_minutes") or duration_minutes)
    return {
        "schema": "gisdataagent.al_bateen.high_resolution_run_status.v1",
        "run_id": str(summary.get("run_id") or receipt.get("run_id") or run_dir.name),
        "status": "completed",
        "created_at": finished_at,
        "started_at": None,
        "finished_at": finished_at,
        "scenario": {
            "return_period_years": forcing.get("return_period_years", receipt.get("return_period_years")),
            "total_depth_mm": forcing.get("published_total_depth_mm"),
            "duration_minutes": duration_minutes,
            "cell_size_m": terrain.get("computation_cell_size_m", receipt.get("cell_size_m")),
            "tail_minutes": max(0.0, simulation_minutes - duration_minutes),
            "output_step_minutes": timeline.get("output_step_minutes"),
            "uses_citywide_250m_gwm": False,
            "uses_250m_interpolation": False,
        },
        "progress": {"stage": "completed", "percent": 100},
        "summary": summary,
    }


def _library_run_directories() -> list[Path]:
    scenarios = _library_root() / "scenarios"
    if not scenarios.is_dir():
        return []
    return sorted(
        path
        for path in scenarios.glob("rp[0-9][0-9][0-9]/*m/al-bateen-*")
        if path.is_dir()
    )


def _find_run_dir(run_id: str) -> Path | None:
    direct = _run_root() / run_id
    if direct.is_dir():
        return direct
    for candidate in _library_run_directories():
        if candidate.name == run_id:
            return candidate
    return None


def _catalog_entry(run_dir: Path) -> dict[str, Any] | None:
    summary_path = run_dir / "delivery_summary.json"
    maximum_path = run_dir / "maximum_depth_wgs84.geojson"
    timeline_path = run_dir / "temporal_snapshots/manifest.json"
    if not summary_path.is_file():
        return None
    try:
        summary = _json_object(summary_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not str(summary.get("status") or "").startswith("completed"):
        return None
    forcing = summary.get("forcing") if isinstance(summary.get("forcing"), dict) else {}
    terrain = summary.get("terrain") if isinstance(summary.get("terrain"), dict) else {}
    timeline = summary.get("timeline") if isinstance(summary.get("timeline"), dict) else {}
    results = summary.get("results") if isinstance(summary.get("results"), dict) else {}
    dewatering = summary.get("dewatering") if isinstance(summary.get("dewatering"), dict) else {}
    try:
        return_period = int(forcing.get("return_period_years"))
        cell_size = int(float(terrain.get("computation_cell_size_m")))
    except (TypeError, ValueError):
        return None
    artifacts_ready = maximum_path.is_file() and timeline_path.is_file()
    return {
        "run_id": str(summary.get("run_id") or run_dir.name),
        "status": "ready" if artifacts_ready else "incomplete",
        "return_period_years": return_period,
        "cell_size_m": cell_size,
        "total_depth_mm": forcing.get("published_total_depth_mm"),
        "simulation_duration_minutes": timeline.get("simulation_duration_minutes"),
        "snapshot_count": timeline.get("snapshot_count"),
        "output_step_minutes": timeline.get("output_step_minutes"),
        "operational_complete_dewatering": bool(dewatering.get("operational_complete")),
        "final_wet_cells_ge_0_01m": results.get("final_wet_cells_ge_0_01m"),
        "maximum_depth_m": results.get("maximum_depth_m"),
        "artifacts": {
            "maximum_depth_ready": maximum_path.is_file(),
            "timeline_ready": timeline_path.is_file(),
            "native_sww_ready": (run_dir / "al_bateen_high_resolution_2d.sww").is_file(),
        },
        "completed_at": datetime.utcfromtimestamp(summary_path.stat().st_mtime).isoformat(timespec="seconds") + "Z",
    }


def precomputed_result_catalog() -> dict[str, Any]:
    variants = [
        entry
        for run_dir in _library_run_directories()
        if (entry := _catalog_entry(run_dir)) is not None
    ]
    preferred: dict[tuple[int, int], dict[str, Any]] = {}
    for entry in variants:
        if entry.get("status") != "ready":
            continue
        key = (int(entry["return_period_years"]), int(entry["cell_size_m"]))
        current = preferred.get(key)
        entry_rank = (
            float(entry.get("simulation_duration_minutes") or 0),
            str(entry.get("completed_at") or ""),
        )
        current_rank = (
            float(current.get("simulation_duration_minutes") or 0),
            str(current.get("completed_at") or ""),
        ) if current else (-1.0, "")
        if entry_rank > current_rank:
            preferred[key] = entry
    entries = sorted(
        preferred.values(),
        key=lambda item: (int(item["return_period_years"]), int(item["cell_size_m"])),
    )
    expected = [
        {"return_period_years": return_period, "cell_size_m": cell_size}
        for return_period in SUPPORTED_RETURN_PERIODS
        for cell_size in (20, 10)
    ]
    available_keys = {
        (int(item["return_period_years"]), int(item["cell_size_m"]))
        for item in entries
    }
    pending = [
        item
        for item in expected
        if (int(item["return_period_years"]), int(item["cell_size_m"])) not in available_keys
    ]
    return {
        "schema": "gisdataagent.al_bateen.precomputed_result_catalog.v1",
        "status": "ready" if not pending else "partial",
        "expected_combination_count": len(expected),
        "available_combination_count": len(entries),
        "entries": entries,
        "pending": pending,
        "variant_count": len(variants),
        "claim_boundary": (
            "Completed local high-resolution diagnostic results; longer-duration variants are preferred "
            "for the same return period and grid size."
        ),
    }


def _latest_completed_run() -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    run_directories: list[Path] = []
    root = _run_root()
    if root.is_dir():
        run_directories.extend(path for path in root.glob("al-bateen-*") if path.is_dir())
    if not run_directories:
        run_directories.extend(_library_run_directories())
    seen: set[Path] = set()
    for run_dir in run_directories:
        if not run_dir.is_dir():
            continue
        resolved = run_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        path = run_dir / "run_status.json"
        run: dict[str, Any] | None = None
        try:
            if path.is_file():
                loaded = _json_object(path)
                if loaded.get("status") == "completed":
                    run = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            run = None
        run = run or _completed_run_from_delivery(run_dir)
        if run is None:
            continue
        timestamp_path = path if path.is_file() else run_dir / "delivery_summary.json"
        candidates.append((timestamp_path.stat().st_mtime, run))
    if not candidates:
        return None
    return _public_run_payload(max(candidates, key=lambda value: value[0])[1])


def workflow_status() -> dict[str, Any]:
    assets = _asset_status()
    supported: list[dict[str, Any]] = []
    for return_period in SUPPORTED_RETURN_PERIODS:
        supported.append(
            {
                "return_period_years": return_period,
                "total_depth_mm": official_depth_mm(return_period, 180),
                "swmm_forcing_ready": _swmm_artifacts(return_period) is not None,
            }
        )
    return {
        "schema": "gisdataagent.al_bateen.high_resolution_workflow.v1",
        "status": "ready" if all(item["ready"] for item in assets) else "partial",
        "scope": {
            "name": "AL BATEEN",
            "name_ar": "البطين",
            "municipality": "ADM",
            "district_id": 147,
            "dmt_district_id": 1300,
            "classification": "highly urban",
            "area_km2": 14.0989603627955,
            "bounds_wgs84": [54.314635, 24.425793, 54.376712, 24.481891],
            "center": [24.453842, 54.345674],
        },
        "model": {
            "terrain_source_resolution_m": 5,
            "default_computation_cell_size_m": 20,
            "supported_computation_cell_sizes_m": [20, 10],
            "solver": "ANUGA 2D finite-volume shallow-water solver",
            "coupling": "matching native EPA SWMM node flooding to local ANUGA cells",
            "uses_citywide_250m_gwm": False,
            "uses_250m_interpolation": False,
        },
        "assets": assets,
        "supported_design_storms": supported,
        "precomputed_library": precomputed_result_catalog(),
        "boundary": _boundary_payload(),
        "latest_run": _latest_completed_run(),
        "claim_boundary": (
            "High-resolution local diagnostic based on the customer 5 m DTM. "
            "Calibration of local drainage, tide, microtopography and observed depths is still required for engineering admission."
        ),
    }


def _number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_invalid")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name}_invalid")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name}_below_minimum")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name}_above_maximum")
    return number


def validate_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("al_bateen_scenario_payload_invalid")
    try:
        return_period = int(payload.get("returnPeriodYears", payload.get("return_period_years", 10)))
    except (TypeError, ValueError) as error:
        raise ValueError("al_bateen_return_period_invalid") from error
    if return_period not in SUPPORTED_RETURN_PERIODS:
        raise ValueError("al_bateen_return_period_not_supported")
    cell_size = _number(
        payload.get("cellSizeM", payload.get("cell_size_m", 20)),
        "al_bateen_cell_size_m",
    )
    if cell_size not in {10.0, 20.0}:
        raise ValueError("al_bateen_cell_size_m_must_be_10_or_20")
    tail = int(
        _number(
            payload.get("tailMinutes", payload.get("tail_minutes", 120)),
            "al_bateen_tail_minutes",
            minimum=0,
            maximum=360,
        )
    )
    output_step = int(
        _number(
            payload.get("outputStepMinutes", payload.get("output_step_minutes", 15)),
            "al_bateen_output_step_minutes",
            minimum=5,
            maximum=30,
        )
    )
    if tail % 5 or output_step % 5:
        raise ValueError("al_bateen_time_steps_must_be_multiples_of_5")
    tide = _number(
        payload.get("tideLevelM", payload.get("tide_level_m", 0.0)),
        "al_bateen_tide_level_m",
        minimum=-1.0,
        maximum=3.0,
    )
    manning = _number(
        payload.get("manningN", payload.get("manning_n", 0.035)),
        "al_bateen_manning_n",
        minimum=0.015,
        maximum=0.15,
    )
    if _swmm_artifacts(return_period) is None:
        raise ValueError("al_bateen_matching_swmm_forcing_missing")
    return {
        "return_period_years": return_period,
        "total_depth_mm": official_depth_mm(return_period, 180),
        "duration_minutes": 180,
        "temporal_pattern": "official_zone_b_ddf_alternating_block",
        "cell_size_m": cell_size,
        "tail_minutes": tail,
        "output_step_minutes": output_step,
        "tide_level_m": tide,
        "manning_n": manning,
        "uses_citywide_250m_gwm": False,
        "uses_250m_interpolation": False,
    }


def _update_run(run_id: str, **changes: Any) -> dict[str, Any]:
    with _LOCK:
        current = dict(_RUNS.get(run_id, {"run_id": run_id}))
        current.update(changes)
        _RUNS[run_id] = current
    _json_write(_run_root() / run_id / "run_status.json", current)
    return current


def _run_worker(run_id: str, scenario: dict[str, Any]) -> None:
    run_dir = _run_root() / run_id
    _update_run(
        run_id,
        status="running",
        started_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        progress={"stage": "preparing_high_resolution_inputs", "percent": 10},
    )
    swmm = _swmm_artifacts(int(scenario["return_period_years"]))
    if swmm is None:
        _update_run(
            run_id,
            status="failed",
            finished_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            error="al_bateen_matching_swmm_forcing_missing",
        )
        return
    command = [
        sys.executable,
        str(_runner_path()),
        "--boundary",
        str(_boundary_utm_path()),
        "--dtm",
        str(_dtm_path()),
        "--land-cover",
        str(_land_cover_path()),
        "--output",
        str(run_dir),
        "--run-id",
        run_id,
        "--return-period-years",
        str(scenario["return_period_years"]),
        "--cell-size-m",
        str(scenario["cell_size_m"]),
        "--tail-minutes",
        str(scenario["tail_minutes"]),
        "--output-step-minutes",
        str(scenario["output_step_minutes"]),
        "--tide-level-m",
        str(scenario["tide_level_m"]),
        "--manning-n",
        str(scenario["manning_n"]),
        "--swmm-inp",
        str(swmm[0]),
        "--swmm-out",
        str(swmm[1]),
    ]
    _update_run(
        run_id,
        progress={"stage": "running_swmm_anuga_coupled_model", "percent": 35},
    )
    try:
        process = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("AL_BATEEN_SERVICE_TIMEOUT_SECONDS", "7500")),
        )
        (run_dir / "service_stdout.log").write_text(process.stdout, encoding="utf-8")
        (run_dir / "service_stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"al_bateen_runner_failed:{process.returncode}")
        summary = _json_object(run_dir / "delivery_summary.json")
        _update_run(
            run_id,
            status="completed",
            finished_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            progress={"stage": "completed", "percent": 100},
            summary=summary,
        )
    except Exception as error:
        _update_run(
            run_id,
            status="failed",
            finished_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            progress={"stage": "failed", "percent": 100},
            error=str(error)[:500],
        )


def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    scenario = validate_scenario(payload)
    prerequisites = _asset_status()
    if not all(item["ready"] for item in prerequisites):
        missing = [item["key"] for item in prerequisites if not item["ready"]]
        raise ValueError("al_bateen_prerequisites_missing:" + ",".join(missing))
    run_id = f"al-bateen-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    initial = {
        "schema": "gisdataagent.al_bateen.high_resolution_run_status.v1",
        "run_id": run_id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scenario": scenario,
        "progress": {"stage": "queued", "percent": 0},
    }
    with _LOCK:
        _RUNS[run_id] = initial
    _json_write(_run_root() / run_id / "scenario_request.json", scenario)
    _json_write(_run_root() / run_id / "run_status.json", initial)
    future: Future[None] = _EXECUTOR.submit(_run_worker, run_id, scenario)
    with _LOCK:
        _RUNS[run_id]["future"] = future
    return public_run(run_id)


def _public_summary(summary: Any) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    return {
        key: summary.get(key)
        for key in (
            "schema",
            "run_id",
            "status",
            "solver",
            "scope",
            "terrain",
            "forcing",
            "coupling",
            "runtime_balance",
            "timeline",
            "results",
            "dewatering",
            "outputs",
            "claim_boundary",
        )
    }


def _public_run_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": item.get("schema"),
        "run_id": item.get("run_id"),
        "status": item.get("status"),
        "created_at": item.get("created_at"),
        "started_at": item.get("started_at"),
        "finished_at": item.get("finished_at"),
        "scenario": item.get("scenario"),
        "progress": item.get("progress"),
        "summary": _public_summary(item.get("summary")),
        "error": item.get("error"),
    }


def public_run(run_id: str) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id.startswith("al-bateen-") or "/" in run_id:
        raise ValueError("al_bateen_run_id_invalid")
    with _LOCK:
        item = dict(_RUNS.get(run_id, {}))
    if not item:
        run_dir = _find_run_dir(run_id)
        if run_dir is None:
            raise KeyError(run_id)
        path = run_dir / "run_status.json"
        if path.is_file():
            item = _json_object(path)
        else:
            item = _completed_run_from_delivery(run_dir) or {}
        if not item:
            raise KeyError(run_id)
    return _public_run_payload(item)


def latest_run() -> dict[str, Any]:
    latest = _latest_completed_run()
    if latest is None:
        raise KeyError("al_bateen_run_not_found")
    return latest


def map_bootstrap(run_id: str) -> dict[str, Any]:
    run = public_run(run_id)
    if run.get("status") != "completed":
        raise ValueError("al_bateen_map_requires_completed_run")
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        raise KeyError(run_id)
    maximum = _json_object(run_dir / "maximum_depth_wgs84.geojson")
    manifest = _json_object(run_dir / "temporal_snapshots/manifest.json")
    summary = run.get("summary") or {}
    scope = summary.get("scope") or {}
    return {
        "type": "FeatureCollection",
        "name": f"{run_id}_map_bootstrap",
        "metadata": {
            "schema": "gisdataagent.al_bateen.map_bootstrap.v1",
            "run_id": run_id,
            "solver": summary.get("solver"),
            "cell_size_m": (summary.get("terrain") or {}).get("computation_cell_size_m"),
            "source_dtm_resolution_m": (summary.get("terrain") or {}).get("source_resolution_m"),
            "feature_count": len(maximum.get("features") or []),
            "timeline": manifest.get("snapshots") or [],
            "center": [24.453842, 54.345674],
            "scope": scope,
            "results": summary.get("results"),
            "claim_boundary": summary.get("claim_boundary"),
            "uses_citywide_250m_gwm": False,
            "uses_250m_interpolation": False,
        },
        "boundary": _boundary_payload(),
        "features": maximum.get("features") or [],
    }


def map_timeseries(run_id: str, time_index: int) -> dict[str, Any]:
    run = public_run(run_id)
    if run.get("status") != "completed":
        raise ValueError("al_bateen_timeseries_requires_completed_run")
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        raise KeyError(run_id)
    manifest = _json_object(run_dir / "temporal_snapshots/manifest.json")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or not 0 <= time_index < len(snapshots):
        raise ValueError("al_bateen_time_index_invalid")
    item = snapshots[time_index]
    relative = Path(str(item.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("al_bateen_snapshot_path_invalid")
    payload = _json_object(run_dir / relative)
    payload["metadata"] = {
        "schema": "gisdataagent.al_bateen.map_timeseries.v1",
        "run_id": run_id,
        "time_index": time_index,
        "time_minutes": item.get("time_minutes"),
        "feature_count": len(payload.get("features") or []),
        "cell_size_m": ((run.get("summary") or {}).get("terrain") or {}).get(
            "computation_cell_size_m"
        ),
        "uses_citywide_250m_gwm": False,
        "uses_250m_interpolation": False,
    }
    return payload
