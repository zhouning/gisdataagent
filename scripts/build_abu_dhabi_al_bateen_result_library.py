#!/usr/bin/env python3
"""Build the 6-return-period x 2-resolution Al Bateen result library.

Every admitted entry must pass the operational complete-dewatering gate emitted
by ``run_abu_dhabi_al_bateen_2d.py``.  Existing admitted entries are retained
and skipped, so the batch can be resumed without deleting prior outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPOSITORY_ROOT / "scripts/run_abu_dhabi_al_bateen_2d.py"
PYTHON = Path.home() / "gisdataagent/.venv/bin/python"
DEFAULT_OUTPUT_ROOT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/"
    "al_bateen_high_resolution_result_library_v2"
)
SWMM_ROOT = (
    Path.home()
    / "Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_interactive_swmm_runs"
)
RETURN_PERIODS = (2, 5, 10, 25, 50, 100)
CELL_SIZES = (20, 10)
TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M = 0.15
SWMM_RUN_NAMES = {
    2: "abu-zone-b-ddf-180m-20260826-v2-rp002",
    5: "abu-zone-b-ddf-180m-20260826-v2-rp005",
    10: "abu-zone-b-ddf-180m-20260826-v2-rp010",
    25: "abu-zone-b-ddf-180m-20260826-v2-rp025",
    50: "abu-zone-b-ddf-180m-20260826-v2-rp050",
    100: "abu-zone-b-ddf-180m-20260826-v2-rp100",
}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _swmm_artifacts(return_period: int) -> tuple[Path, Path]:
    full_city = SWMM_ROOT / SWMM_RUN_NAMES[return_period] / "full_city"
    inp = full_city / "scenario.inp"
    candidates = [
        path
        for path in sorted((full_city / "native_swmm_results").glob("*.out"))
        if ".failed." not in path.name and path.stat().st_size > 1024
    ]
    if not inp.is_file() or not candidates:
        raise FileNotFoundError(f"SWMM artifacts missing for RP{return_period:03d}")
    return inp, candidates[0]


def _admitted_summary(path: Path) -> dict[str, Any] | None:
    try:
        summary = _json_read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not (summary.get("dewatering") or {}).get("operational_complete"):
        return None
    if int((summary.get("results") or {}).get("final_wet_cells_ge_0_01m", -1)) != 0:
        return None
    tolerance = (summary.get("terrain") or {}).get(
        "tidal_connectivity_vertical_tolerance_m"
    )
    if tolerance is None or abs(
        float(tolerance) - TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M
    ) > 1.0e-9:
        return None
    return summary


def _existing_entry(root: Path, return_period: int, cell_size: int) -> dict[str, Any] | None:
    scenario_root = root / "scenarios" / f"rp{return_period:03d}" / f"{cell_size}m"
    candidates = sorted(scenario_root.glob("*/delivery_summary.json"), reverse=True)
    for path in candidates:
        summary = _admitted_summary(path)
        if summary is not None:
            return _entry_from_summary(path.parent, summary, "completed")
    return None


def _entry_from_summary(run_dir: Path, summary: dict[str, Any], status: str) -> dict[str, Any]:
    summary_path = run_dir / "delivery_summary.json"
    sww_path = run_dir / "al_bateen_high_resolution_2d.sww"
    manifest_path = run_dir / "temporal_snapshots/manifest.json"
    return {
        "return_period_years": (summary.get("forcing") or {}).get("return_period_years"),
        "cell_size_m": (summary.get("terrain") or {}).get("computation_cell_size_m"),
        "status": status,
        "run_id": summary.get("run_id"),
        "result_directory": str(run_dir.resolve()),
        "delivery_summary": str(summary_path.resolve()),
        "native_sww": str(sww_path.resolve()),
        "timeline_manifest": str(manifest_path.resolve()),
        "snapshot_count": (summary.get("timeline") or {}).get("snapshot_count"),
        "simulation_duration_minutes": (summary.get("timeline") or {}).get(
            "simulation_duration_minutes"
        ),
        "actual_tail_minutes": (summary.get("dewatering") or {}).get("actual_tail_minutes"),
        "operational_complete_dewatering": (summary.get("dewatering") or {}).get(
            "operational_complete"
        ),
        "final_wet_cells_ge_0_01m": (summary.get("results") or {}).get(
            "final_wet_cells_ge_0_01m"
        ),
        "summary_sha256": _sha256(summary_path) if summary_path.is_file() else None,
        "sww_size_bytes": sww_path.stat().st_size if sww_path.is_file() else None,
    }


def _write_manifest(root: Path, state: dict[str, Any]) -> None:
    with _LOCK:
        entries = sorted(
            state["entries"].values(),
            key=lambda item: (int(item["return_period_years"]), -int(item["cell_size_m"])),
        )
        completed = sum(item.get("status") == "completed" for item in entries)
        failed = sum(item.get("status") == "failed" for item in entries)
        running = sum(item.get("status") == "running" for item in entries)
        manifest = {
            "schema": "gisdataagent.al_bateen.high_resolution_result_library.v2",
            "configuration_id": "al-bateen-hires-dewatering-v2-tidal-tolerance-0p15",
            "library_id": state["library_id"],
            "created_at": state["created_at"],
            "updated_at": _now(),
            "status": "completed" if completed == 12 else "running" if running else "incomplete",
            "scope": "AL BATEEN ADM District 147",
            "terrain_source": "customer AUH_DTM_5m_Z40.TIF",
            "return_periods_years": list(RETURN_PERIODS),
            "cell_sizes_m": list(CELL_SIZES),
            "expected_entry_count": 12,
            "completed_entry_count": completed,
            "failed_entry_count": failed,
            "running_entry_count": running,
            "uses_citywide_250m_gwm": False,
            "uses_250m_interpolation": False,
            "dewatering_quality_gate": {
                "wet_depth_threshold_m": state["dry_depth_threshold_m"],
                "mean_residual_depth_threshold_m": state["dry_mean_depth_threshold_m"],
                "consecutive_frames": state["dry_consecutive_frames"],
                "maximum_tail_minutes": state["maximum_tail_minutes"],
                "drainage_timescale_minutes": state["drainage_timescale_minutes"],
                "minimum_drainage_mm_per_hour": state["minimum_drainage_mm_per_hour"],
                "tidal_connectivity_vertical_tolerance_m": state[
                    "tidal_connectivity_vertical_tolerance_m"
                ],
                "calibration_status": "operational_assumption_pending_local_observed_recession_calibration",
            },
            "entries": entries,
        }
        _json_write(root / "library_manifest.json", manifest)


def _run_one(
    root: Path,
    state: dict[str, Any],
    return_period: int,
    cell_size: int,
) -> dict[str, Any]:
    key = f"rp{return_period:03d}-{cell_size}m"
    existing = _existing_entry(root, return_period, cell_size)
    if existing is not None:
        state["entries"][key] = existing
        _write_manifest(root, state)
        return existing

    run_id = (
        f"al-bateen-library-rp{return_period:03d}-{cell_size}m-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    )
    run_dir = root / "scenarios" / f"rp{return_period:03d}" / f"{cell_size}m" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    inp, out = _swmm_artifacts(return_period)
    state["entries"][key] = {
        "return_period_years": return_period,
        "cell_size_m": cell_size,
        "status": "running",
        "run_id": run_id,
        "result_directory": str(run_dir.resolve()),
        "started_at": _now(),
    }
    _write_manifest(root, state)

    command = [
        str(PYTHON),
        str(RUNNER),
        "--run-id", run_id,
        "--return-period-years", str(return_period),
        "--cell-size-m", str(cell_size),
        "--tail-minutes", str(state["maximum_tail_minutes"]),
        "--output-step-minutes", str(state["output_step_minutes"]),
        "--tide-level-m", str(state["tide_level_m"]),
        "--manning-n", str(state["manning_n"]),
        "--dewater-until-dry",
        "--drainage-timescale-minutes", str(state["drainage_timescale_minutes"]),
        "--minimum-drainage-mm-per-hour", str(state["minimum_drainage_mm_per_hour"]),
        "--dry-mean-depth-threshold-m", str(state["dry_mean_depth_threshold_m"]),
        "--dry-consecutive-frames", str(state["dry_consecutive_frames"]),
        "--tidal-connectivity-vertical-tolerance-m",
        str(state["tidal_connectivity_vertical_tolerance_m"]),
        "--output", str(run_dir),
        "--swmm-inp", str(inp),
        "--swmm-out", str(out),
    ]
    (run_dir / "batch_command.json").write_text(
        json.dumps(command, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        process = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=state["task_timeout_seconds"],
        )
        (run_dir / "batch_stdout.log").write_text(process.stdout, encoding="utf-8")
        (run_dir / "batch_stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"runner_exit_{process.returncode}")
        summary_path = run_dir / "delivery_summary.json"
        summary = _admitted_summary(summary_path)
        if summary is None:
            raise RuntimeError("operational_complete_dewatering_gate_failed")
        entry = _entry_from_summary(run_dir, summary, "completed")
        entry["finished_at"] = _now()
    except Exception as error:
        entry = {
            **state["entries"][key],
            "status": "failed",
            "finished_at": _now(),
            "error": f"{type(error).__name__}:{error}",
        }
    state["entries"][key] = entry
    _write_manifest(root, state)
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--maximum-tail-minutes", type=int, default=2880)
    parser.add_argument("--output-step-minutes", type=int, default=15)
    parser.add_argument("--drainage-timescale-minutes", type=float, default=120.0)
    parser.add_argument("--minimum-drainage-mm-per-hour", type=float, default=2.0)
    parser.add_argument("--dry-mean-depth-threshold-m", type=float, default=0.001)
    parser.add_argument("--dry-consecutive-frames", type=int, default=3)
    parser.add_argument("--tide-level-m", type=float, default=0.0)
    parser.add_argument("--manning-n", type=float, default=0.035)
    parser.add_argument("--task-timeout-seconds", type=int, default=21600)
    parser.add_argument("--only-return-period", type=int, choices=RETURN_PERIODS)
    parser.add_argument("--only-cell-size", type=int, choices=CELL_SIZES)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 6:
        raise ValueError("workers_must_be_between_1_and_6")

    root = args.output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "library_manifest.json"
    previous = _json_read(manifest_path) if manifest_path.is_file() else {}
    state = {
        "library_id": previous.get(
            "library_id",
            f"al-bateen-hires-v1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        ),
        "created_at": previous.get("created_at", _now()),
        "entries": {
            f"rp{int(item['return_period_years']):03d}-{int(item['cell_size_m'])}m": item
            for item in previous.get("entries", [])
            if isinstance(item, dict)
            and item.get("return_period_years") is not None
            and item.get("cell_size_m") is not None
        },
        "maximum_tail_minutes": args.maximum_tail_minutes,
        "output_step_minutes": args.output_step_minutes,
        "drainage_timescale_minutes": args.drainage_timescale_minutes,
        "minimum_drainage_mm_per_hour": args.minimum_drainage_mm_per_hour,
        "dry_depth_threshold_m": 0.01,
        "dry_mean_depth_threshold_m": args.dry_mean_depth_threshold_m,
        "dry_consecutive_frames": args.dry_consecutive_frames,
        "tidal_connectivity_vertical_tolerance_m": (
            TIDAL_CONNECTIVITY_VERTICAL_TOLERANCE_M
        ),
        "tide_level_m": args.tide_level_m,
        "manning_n": args.manning_n,
        "task_timeout_seconds": args.task_timeout_seconds,
    }
    jobs = [
        (return_period, cell_size)
        for return_period in RETURN_PERIODS
        for cell_size in CELL_SIZES
        if args.only_return_period in (None, return_period)
        and args.only_cell_size in (None, cell_size)
    ]
    _write_manifest(root, state)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_run_one, root, state, return_period, cell_size): (
                return_period,
                cell_size,
            )
            for return_period, cell_size in jobs
        }
        for future in as_completed(futures):
            result = future.result()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    _write_manifest(root, state)
    final = _json_read(root / "library_manifest.json")
    print(
        json.dumps(
            {
                "status": final["status"],
                "completed_entry_count": final["completed_entry_count"],
                "failed_entry_count": final["failed_entry_count"],
                "manifest": str((root / "library_manifest.json").resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
