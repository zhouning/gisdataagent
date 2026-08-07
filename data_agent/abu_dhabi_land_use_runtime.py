"""Executable runtime and map handoff for the Abu Dhabi land-use benchmark."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import rasterio
from rasterio.warp import transform_bounds

from .abu_dhabi_land_use import (
    CLASS_LEGEND,
    MODEL_IDS,
    MODEL_PRESENTATION,
    SCENARIO_IDS,
    AbuDhabiLandUseService,
)

RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
TRACK_IDS = ("historical", "planning")
EXECUTION_SEEDS = (31, 47, 73)
HISTORICAL_YEARS = (2023, 2024)
PLANNING_YEARS = tuple(range(2025, 2031))
_RUN_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="abu-dhabi-model")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("abu_dhabi_run_record_invalid")
    return payload


def configured_run_root(benchmark_root: Path) -> Path:
    configured = os.environ.get("ABU_DHABI_LAND_USE_RUN_DIR", "").strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else (benchmark_root / "runtime_runs").resolve()
    )


def _paper58_runner(benchmark_root: Path) -> Path:
    configured = os.environ.get("ABU_DHABI_PAPER58_RUNNER", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        benchmark_root.parents[2]
        / "paper58-geofm-world-model-rl/experiments/abu_dhabi/run_paper58_abu_dhabi.py"
    ).resolve()


def _flus_binary() -> Path:
    configured = os.environ.get("GEOSOS_FLUS_EXECUTABLE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(
        "/Users/zhouning/FLUS_console_crossplatform/build/cmake-release/flus_console"
    )


def validate_request(
    model_id: str,
    track: str,
    seed: int,
    scenario: str | None,
) -> None:
    if model_id not in MODEL_IDS:
        raise ValueError("unsupported_model")
    if track not in TRACK_IDS:
        raise ValueError("unsupported_track")
    if seed not in EXECUTION_SEEDS:
        raise ValueError("unsupported_execution_seed")
    if track == "planning" and scenario not in SCENARIO_IDS:
        raise ValueError("unsupported_scenario")
    if track == "historical" and scenario is not None:
        raise ValueError("scenario_not_allowed_for_historical")


def _command_for_run(record: dict[str, Any], benchmark_root: Path, run_dir: Path) -> list[str]:
    model_id = str(record["model_id"])
    track = str(record["track"])
    seed = int(record["seed"])
    if track == "planning":
        return [
            sys.executable,
            str(benchmark_root / "run_planning_scenarios.py"),
            "--models",
            model_id,
            "--seeds",
            str(seed),
            "--output",
            str(run_dir / "planning"),
            "--report",
            str(run_dir / "planning_report.json"),
            "--binary",
            str(_flus_binary()),
            "--device",
            "cpu",
        ]
    if model_id == "geospatial_kernel":
        script = benchmark_root / "run_geospatial_kernel.py"
        extra: list[str] = []
    elif model_id == "geosos_flus":
        script = benchmark_root / "run_geosos_flus.py"
        extra = ["--binary", str(_flus_binary())]
    else:
        script = _paper58_runner(benchmark_root)
        extra = ["--benchmark-root", str(benchmark_root), "--device", "cpu"]
    return [
        sys.executable,
        str(script),
        "--seeds",
        str(seed),
        "--output",
        str(run_dir / "historical"),
        *extra,
    ]


def _expected_path(record: dict[str, Any], run_dir: Path, year: int) -> Path:
    model_id = str(record["model_id"])
    seed = int(record["seed"])
    if record["track"] == "historical":
        return run_dir / "historical" / f"seed_{seed}" / f"prediction_{year}.tif"
    return (
        run_dir
        / "planning"
        / model_id
        / str(record["scenario"])
        / f"seed_{seed}"
        / f"prediction_{year}.tif"
    )


def _execute_run(run_id: str, benchmark_root: Path, run_root: Path) -> None:
    run_dir = run_root / run_id
    record_path = run_dir / "run.json"
    with _RUN_LOCK:
        record = _read_json(record_path)
        record.update(status="running", stage="model_execution", started_at=_now())
        _write_json(record_path, record)
    command = _command_for_run(record, benchmark_root, run_dir)
    log_path = run_dir / "runner.log"
    try:
        completed = subprocess.run(
            command,
            cwd=benchmark_root,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"model_process_failed:{completed.returncode}")
        years = HISTORICAL_YEARS if record["track"] == "historical" else PLANNING_YEARS
        missing = [year for year in years if not _expected_path(record, run_dir, year).is_file()]
        if missing:
            raise FileNotFoundError(f"model_outputs_missing:{missing}")
        with _RUN_LOCK:
            record = _read_json(record_path)
            record.update(
                status="complete",
                stage="ready_for_map",
                completed_at=_now(),
                years=list(years),
                output_count=len(years),
            )
            _write_json(record_path, record)
    except Exception as exc:
        with _RUN_LOCK:
            record = _read_json(record_path)
            record.update(
                status="failed",
                stage="failed",
                completed_at=_now(),
                error=str(exc),
            )
            _write_json(record_path, record)


def start_run(
    service: AbuDhabiLandUseService,
    *,
    model_id: str,
    track: str,
    seed: int,
    scenario: str | None,
    username: str,
) -> dict[str, Any]:
    validate_request(model_id, track, seed, scenario)
    run_root = configured_run_root(service.root)
    run_root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": "gwm.abu_dhabi_land_use_runtime.v1",
        "run_id": run_id,
        "status": "queued",
        "stage": "queued",
        "model_id": model_id,
        "model_label": MODEL_PRESENTATION[model_id]["label"],
        "track": track,
        "seed": seed,
        "scenario": scenario,
        "requested_by": username,
        "requested_at": _now(),
        "years": [],
    }
    _write_json(run_dir / "run.json", record)
    _RUN_EXECUTOR.submit(_execute_run, run_id, service.root, run_root)
    return record


def load_run(service: AbuDhabiLandUseService, run_id: str) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("unsupported_run_id")
    run_root = configured_run_root(service.root)
    path = (run_root / run_id / "run.json").resolve()
    if run_root not in path.parents or not path.is_file():
        raise FileNotFoundError("abu_dhabi_run_not_found")
    return _read_json(path)


def resolve_run_raster(
    service: AbuDhabiLandUseService,
    run_id: str,
    year: int,
) -> Path:
    record = load_run(service, run_id)
    if record.get("status") != "complete":
        raise ValueError("run_not_complete")
    allowed = HISTORICAL_YEARS if record["track"] == "historical" else PLANNING_YEARS
    if year not in allowed:
        raise ValueError("unsupported_run_year")
    run_root = configured_run_root(service.root)
    run_dir = (run_root / run_id).resolve()
    path = _expected_path(record, run_dir, year).resolve()
    if run_dir not in path.parents or not path.is_file():
        raise FileNotFoundError("abu_dhabi_run_raster_missing")
    return path


def _bounds(path: Path) -> list[list[float]]:
    with rasterio.open(path) as dataset:
        west, south, east, north = transform_bounds(
            dataset.crs,
            "EPSG:4326",
            *dataset.bounds,
            densify_pts=21,
        )
    return [[south, west], [north, east]]


def _legend_maps() -> tuple[dict[str, str], dict[str, str]]:
    return (
        {str(item["value"]): str(item["color"]) for item in CLASS_LEGEND},
        {str(item["value"]): str(item["label"]) for item in CLASS_LEGEND},
    )


def build_map_config(
    service: AbuDhabiLandUseService,
    *,
    model_id: str,
    track: str,
    seed: str,
    scenario: str | None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if model_id not in MODEL_IDS:
        raise ValueError("unsupported_model")
    if track not in TRACK_IDS:
        raise ValueError("unsupported_track")
    if run_id:
        record = load_run(service, run_id)
        if record.get("status") != "complete":
            raise ValueError("run_not_complete")
        if record.get("model_id") != model_id or record.get("track") != track:
            raise ValueError("run_request_mismatch")
        scenario = record.get("scenario")
        seed = str(record["seed"])
    origin_year = 2022 if track == "historical" else 2024
    years = HISTORICAL_YEARS if track == "historical" else PLANNING_YEARS
    origin_path = service.resolve_raster(
        "observed", track="historical", year=origin_year, seed="ensemble"
    )
    image_bounds = _bounds(origin_path)
    colors, labels = _legend_maps()
    layers: list[dict[str, Any]] = [
        {
            "name": f"{MODEL_PRESENTATION[model_id]['label']} {origin_year} 起点观测",
            "type": "image",
            "image_url": (
                "/api/benchmarks/abu-dhabi-land-use/rasters/observed?"
                + urlencode({"track": "historical", "year": origin_year, "seed": "ensemble"})
            ),
            "image_bounds": image_bounds,
            "visible": False,
            "category_colors": colors,
            "category_labels": labels,
            "legend_title": "土地覆盖",
        }
    ]
    for year in years:
        if run_id:
            image_url = (
                f"/api/benchmarks/abu-dhabi-land-use/runs/{run_id}/rasters/{year}"
            )
        else:
            params: dict[str, Any] = {"track": track, "year": year, "seed": seed}
            if scenario:
                params["scenario"] = scenario
            image_url = (
                f"/api/benchmarks/abu-dhabi-land-use/rasters/{model_id}?"
                + urlencode(params)
            )
        layers.append(
            {
                "name": f"{MODEL_PRESENTATION[model_id]['label']} {year}",
                "type": "image",
                "image_url": image_url,
                "image_bounds": image_bounds,
                "visible": year == years[-1],
                "category_colors": colors,
                "category_labels": labels,
                "legend_title": "土地覆盖",
            }
        )
    south, west = image_bounds[0]
    north, east = image_bounds[1]
    return {
        "layers": layers,
        "center": [(south + north) / 2, (west + east) / 2],
        "zoom": 10,
        "summary": {
            "model_id": model_id,
            "track": track,
            "scenario": scenario,
            "seed": seed,
            "run_id": run_id,
            "temporal_years": [origin_year, *years],
        },
    }
