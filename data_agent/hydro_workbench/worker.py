"""Kubernetes worker for real SWMM/ANUGA development runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import manifest_sha256
from .storage import atomic_json, read_manifest, run_dir, update_status


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration(value: int) -> str:
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}:00"


def _fixture_swmm_input(manifest: dict[str, Any], destination: Path) -> Path:
    rainfall = manifest["parameters"]["rainfall"]
    total = float(rainfall["total_mm"])
    duration = int(rainfall["duration_minutes"])
    intensity = total / max(duration / 60.0, 1.0 / 60.0)
    end = (datetime(2020, 1, 1) + timedelta(minutes=duration + 30)).strftime("%m/%d/%Y")
    end_time = (datetime(2020, 1, 1) + timedelta(minutes=duration + 30)).strftime("%H:%M:%S")
    text = f""";; GIS Data Agent development fixture generated from an immutable manifest.
[TITLE]
Abu Dhabi hydro workbench development run {manifest["run_id"]}

[OPTIONS]
FLOW_UNITS CMS
INFILTRATION HORTON
FLOW_ROUTING KINWAVE
LINK_OFFSETS DEPTH
MIN_SLOPE 0
ALLOW_PONDING YES
SKIP_STEADY_STATE NO
START_DATE 01/01/2020
START_TIME 00:00:00
REPORT_START_DATE 01/01/2020
REPORT_START_TIME 00:00:00
END_DATE {end}
END_TIME {end_time}
SWEEP_START 01/01
SWEEP_END 12/31
DRY_DAYS 0
REPORT_STEP 00:05:00
WET_STEP 00:01:00
DRY_STEP 01:00:00
ROUTING_STEP 00:01:00

[EVAPORATION]
CONSTANT 0.0

[RAINGAGES]
RG1 INTENSITY 00:05 1.0 TIMESERIES TS1

[SUBCATCHMENTS]
S1 RG1 J1 10.0 80 500 0.5 0

[SUBAREAS]
S1 0.015 0.25 0.05 0.15 25 OUTLET

[INFILTRATION]
S1 75 7 4 7 0

[JUNCTIONS]
J1 0 0.5 0 0 0

[OUTFALLS]
O1 -0.1 FREE

[CONDUITS]
C1 J1 O1 1000 0.013 0 0 0 0

[XSECTIONS]
C1 CIRCULAR 0.5 0 0 0 1

[COORDINATES]
J1 0 0
O1 1000 0

[TIMESERIES]
TS1 00:00 0
TS1 00:05 {intensity:.6f}
TS1 {_duration(duration)} {intensity:.6f}
TS1 {_duration(duration + 5)} 0
TS1 {_duration(duration + 30)} 0

[REPORT]
INPUT YES
CONTROLS NO
SUBCATCHMENTS ALL
NODES ALL
LINKS ALL
"""
    destination.write_text(text, encoding="utf-8")
    return destination


def _parse_swmm_report(report: str) -> dict[str, Any]:
    continuity = re.search(r"Continuity Error \(%\)\s*\.\.\.\.\.\s*([-+0-9.]+)", report)
    flooding = "No nodes were flooded" not in report
    max_depths = [
        float(value)
        for value in re.findall(
            r"^\s*\w+\s+JUNCTION\s+[-+0-9.]+\s+([-+0-9.]+)", report, flags=re.MULTILINE
        )
    ]
    peak_flows = [
        float(value)
        for value in re.findall(r"^\s*\w+\s+CONDUIT\s+([-+0-9.]+)", report, flags=re.MULTILINE)
    ]
    return {
        "continuity_error_percent": float(continuity.group(1)) if continuity else None,
        "flooding_detected": flooding,
        "maximum_node_depth_m": max(max_depths) if max_depths else None,
        "maximum_link_flow_cms": max(peak_flows) if peak_flows else None,
    }


def _bbox(manifest: dict[str, Any]) -> list[float]:
    return manifest["area"]["result_display_extent"]["bbox"]


def _geojson_feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _run_1d(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    input_path = _fixture_swmm_input(manifest, output / "model.inp")
    report = output / "model.rpt"
    binary = output / "model.out"
    executable = os.environ.get("ABU_DHABI_SWMM_EXECUTABLE", "/opt/swmm/bin/runswmm")
    result = subprocess.run(
        [executable, str(input_path), str(report), str(binary)],
        capture_output=True,
        text=True,
        check=False,
        timeout=3_600,
    )
    (output / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output / "stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0 or not report.exists() or not binary.exists():
        raise RuntimeError(f"swmm_failed:{result.returncode}:{result.stderr[-500:]}")
    report_text = report.read_text(encoding="utf-8", errors="replace")
    min_lon, min_lat, max_lon, max_lat = _bbox(manifest)
    mid_lat = (min_lat + max_lat) / 2
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [(min_lon + max_lon) / 2, mid_lat]},
            "properties": {"id": "J1", "kind": "junction", **_parse_swmm_report(report_text)},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [max_lon, mid_lat]},
            "properties": {"id": "O1", "kind": "outfall"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[(min_lon + max_lon) / 2, mid_lat], [max_lon, mid_lat]],
            },
            "properties": {"id": "C1", "kind": "conduit"},
        },
    ]
    geojson_path = output / "network.geojson"
    atomic_json(geojson_path, _geojson_feature_collection(features))
    return {
        "solver": "epa_swmm",
        "version": "5.2.4",
        "status": "completed",
        "model_scope": "single-subcatchment development fixture",
        "input": str(input_path),
        "report": str(report),
        "report_sha256": _sha256(report),
        "binary": str(binary),
        "binary_sha256": _sha256(binary),
        "quality": _parse_swmm_report(report_text),
        "map": str(geojson_path),
    }


def _run_2d(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run ANUGA on a bounded development grid and emit point depth GeoJSON."""
    import anuga  # type: ignore
    import numpy as np  # type: ignore

    output.mkdir(parents=True, exist_ok=True)
    min_lon, min_lat, max_lon, max_lat = _bbox(manifest)
    params = manifest["parameters"]["two_d"]
    rainfall = manifest["parameters"]["rainfall"]
    lon_scale = max(0.2, math.cos(math.radians((min_lat + max_lat) / 2)))
    width_m = max(100.0, (max_lon - min_lon) * 111_320.0 * lon_scale)
    height_m = max(100.0, (max_lat - min_lat) * 111_320.0)
    requested = max(4, int(max(width_m, height_m) / float(params["grid_resolution_m"])))
    nx = min(32, requested)
    ny = min(32, max(4, int(nx * height_m / width_m)))
    dx = width_m / nx
    dy = height_m / ny
    domain = anuga.rectangular_cross_domain(nx, ny, len1=width_m, len2=height_m)
    domain.set_name("abu_dhabi_hydro_workbench_2d")
    domain.set_datadir(str(output))
    domain.set_quantity(
        "elevation",
        lambda x, y: 0.0005 * np.asarray(x, dtype=float) + 0.0003 * np.asarray(y, dtype=float),
    )
    domain.set_quantity("friction", float(params["manning_n"]))
    domain.set_quantity("stage", 0.0)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary({"left": boundary, "right": boundary, "top": boundary, "bottom": boundary})
    rate = (
        float(rainfall["total_mm"]) / max(float(rainfall["duration_minutes"]) * 60.0, 1.0) / 1000.0
    )
    anuga.Rate_operator(domain, rate=rate, label="manifest_rainfall")
    final_time = float(rainfall["duration_minutes"]) * 60.0
    yieldstep = min(float(params["timestep_seconds"]), 300.0)
    for _ in domain.evolve(yieldstep=yieldstep, finaltime=final_time):
        pass
    elevation = np.asarray(domain.quantities["elevation"].centroid_values, dtype=float)
    stage = np.asarray(domain.quantities["stage"].centroid_values, dtype=float)
    depth = stage - elevation
    centroids = np.asarray(domain.centroid_coordinates, dtype=float)
    features = []
    stride = max(1, int(len(depth) / 400))
    for index in range(0, len(depth), stride):
        x, y = centroids[index]
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        min_lon + (x / width_m) * (max_lon - min_lon),
                        min_lat + (y / height_m) * (max_lat - min_lat),
                    ],
                },
                "properties": {"depth_m": max(0.0, float(depth[index])), "cell_index": index},
            }
        )
    geojson_path = output / "depth_points.geojson"
    atomic_json(geojson_path, _geojson_feature_collection(features))
    summary = {
        "solver": "anuga_2d",
        "status": "completed",
        "anuga_version": str(getattr(anuga, "__version__", "unknown")),
        "triangle_count": int(len(depth)),
        "minimum_depth_m": float(np.min(depth)),
        "maximum_depth_m": float(np.max(depth)),
        "finite": bool(np.isfinite(depth).all()),
        "grid": {"nx": nx, "ny": ny, "effective_resolution_m": max(dx, dy)},
        "map": str(geojson_path),
    }
    atomic_json(output / "summary.json", summary)
    return summary


def _run_coupled(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Use the pinned runtime pilot for a real two-way SWMM/ANUGA run."""
    import numpy as np  # type: ignore

    output.mkdir(parents=True, exist_ok=True)
    input_dir = output / "input"
    input_dir.mkdir(exist_ok=True)
    input_path = _fixture_swmm_input(manifest, input_dir / "model.inp")
    grid = input_dir / "terrain_grid.npz"
    np.savez_compressed(
        grid,
        values=np.zeros((3, 3), dtype=np.float32),
        x=np.asarray([0.0, 50.0, 100.0]),
        y=np.asarray([100.0, 50.0, 0.0]),
        land_mask=np.ones((2, 2), dtype=bool),
    )
    (input_dir / "grid_metadata.json").write_text(
        json.dumps({"selected_node_ids": ["J1"]}) + "\n", encoding="utf-8"
    )
    pilot = Path("/app/scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py")
    duration = int(manifest["parameters"]["rainfall"]["duration_minutes"]) * 60
    command = [
        sys.executable,
        str(pilot),
        "--swmm-inp",
        str(input_path),
        "--grid",
        str(grid),
        "--grid-metadata",
        str(input_dir / "grid_metadata.json"),
        "--output",
        str(output),
        "--swmm-library",
        os.environ.get("ABU_DHABI_SWMM_LIBRARY", "/opt/swmm/lib/libswmm5.so"),
        "--duration-seconds",
        str(min(duration, 3_600)),
        "--window-seconds",
        str(manifest["parameters"]["coupling"]["window_seconds"]),
        "--coupling-mode",
        str(manifest["parameters"]["coupling"]["mode"]),
        "--binding-limit",
        "1",
        "--interface-detail-limit",
        "1",
        "--run-id",
        manifest["run_id"],
        "--quiet",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3_600)
    (output / "pilot.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output / "pilot.stderr.log").write_text(result.stderr, encoding="utf-8")
    receipt = output / "bidirectional_coupling_receipt.json"
    summary = output / "delivery_summary.json"
    if result.returncode != 0 or not receipt.exists() or not summary.exists():
        raise RuntimeError(f"coupling_failed:{result.returncode}:{result.stderr[-1000:]}")
    return {
        "solver": "epa_swmm_anuga_synchronous_coupling",
        "status": "completed",
        "model_scope": "single-interface development pilot on a 2x2 surface grid",
        "coupling_mode": manifest["parameters"]["coupling"]["mode"],
        "receipt": str(receipt),
        "receipt_sha256": _sha256(receipt),
        "summary": str(summary),
        "map": str(output / "maximum_depth_wgs84.geojson")
        if (output / "maximum_depth_wgs84.geojson").exists()
        else None,
    }


def run(run_id: str) -> None:
    root = Path(os.environ.get("HYDRO_RUN_ROOT", "/data/runs"))
    manifest = read_manifest(run_id, root)
    output = run_dir(run_id, root) / "results"
    update_status(run_id, "running", progress=10, root=root, message="worker_started")
    try:
        expected_hash = str((manifest.get("immutability") or {}).get("sha256") or "")
        if not expected_hash or expected_hash != manifest_sha256(manifest):
            raise RuntimeError("manifest_integrity_check_failed")
        model_type = manifest["request"]["model_type"]
        results: dict[str, Any] = {
            "schema": "gwm.abu_dhabi_flood.hydro_run_result.v1",
            "run_id": run_id,
            "input_disclosure": manifest["request"]["input_mode"],
            "engineering_use": False,
            "qualification": (
                "MVP execution evidence only; engineering use requires customer-data ETL, "
                "calibration, validation and approval"
            ),
        }
        if model_type == "one_d":
            update_status(run_id, "running", progress=20, root=root, message="running_epa_swmm")
            results["one_d"] = _run_1d(manifest, output / "one_d")
        elif model_type == "two_d":
            update_status(run_id, "running", progress=20, root=root, message="running_anuga")
            results["two_d"] = _run_2d(manifest, output / "two_d")
        else:
            update_status(
                run_id, "running", progress=15, root=root, message="running_swmm_anuga_coupling"
            )
            results["coupled"] = _run_coupled(manifest, output / "coupled")
        atomic_json(output / "result.json", results)
        update_status(
            run_id,
            "completed",
            progress=100,
            root=root,
            message="results_persisted",
            result_path=str(output / "result.json"),
        )
    except Exception as error:
        update_status(
            run_id,
            "failed",
            progress=100,
            root=root,
            message="worker_failed",
            error=f"{type(error).__name__}: {error}",
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run(args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
