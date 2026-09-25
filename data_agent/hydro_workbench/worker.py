"""Kubernetes worker for real SWMM/ANUGA development runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse
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
    max_depths = list(_swmm_node_depths(report).values())
    peak_flows = list(_swmm_link_flows(report).values())
    maximum_node_depth = max(max_depths) if max_depths else None
    maximum_link_flow = max(peak_flows) if peak_flows else None
    return {
        "continuity_error_percent": float(continuity.group(1)) if continuity else None,
        "flooding_detected": flooding,
        "maximum_node_depth_m": maximum_node_depth,
        "maximum_link_flow_cms": maximum_link_flow,
        "quality_flags": (["extreme_node_depth_value_requires_source_review"] if maximum_node_depth is not None and maximum_node_depth > 50 else []),
    }


def _swmm_node_depths(report: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for node_id, raw_value in re.findall(
        r"^\s*(\S+)\s+JUNCTION\s+[-+0-9.eE]+\s+([-+0-9.eE]+)", report, flags=re.MULTILINE
    ):
        try:
            values[node_id] = float(raw_value)
        except ValueError:
            continue
    return values


def _swmm_link_flows(report: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for link_id, raw_value in re.findall(
        r"^\s*(\S+)\s+CONDUIT\s+([-+0-9.eE]+)", report, flags=re.MULTILINE
    ):
        try:
            values[link_id] = float(raw_value)
        except ValueError:
            continue
    return values


def _bbox(manifest: dict[str, Any]) -> list[float]:
    return manifest["area"]["result_display_extent"]["bbox"]


def _geojson_feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _download_uri(uri: str, destination: Path) -> dict[str, Any]:
    """Materialise one deployment-registered input into the Job workspace."""
    parsed = urlparse(str(uri))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if parsed.scheme == "file":
        shutil.copyfile(parsed.path, destination)
    elif parsed.scheme in {"s3", "minio"}:
        import boto3  # type: ignore
        from botocore.config import Config as BotoConfig  # type: ignore

        if not parsed.netloc or not parsed.path.strip("/"):
            raise RuntimeError(f"invalid_object_uri:{uri}")
        kwargs: dict[str, Any] = {
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
        }
        endpoint = str(os.environ.get("AWS_ENDPOINT_URL") or "").strip()
        if endpoint:
            kwargs["endpoint_url"] = endpoint
            kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})
        boto3.client("s3", **kwargs).download_file(
            parsed.netloc, parsed.path.lstrip("/"), str(destination)
        )
    else:
        raise RuntimeError(f"unsupported_input_uri_scheme:{parsed.scheme or 'none'}")
    return {"uri": uri, "path": str(destination), "size_bytes": destination.stat().st_size, "sha256": _sha256(destination)}


def _stage_customer_inputs(manifest: dict[str, Any], output: Path, names: list[str]) -> dict[str, Path]:
    staged: dict[str, Path] = {}
    records: dict[str, Any] = {}
    input_dir = output / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        source = manifest.get("data_sources", {}).get(name) or {}
        uri = str(source.get("uri") or "").strip()
        if not uri:
            continue
        source_name = str(source.get("source_name") or Path(urlparse(uri).path).name or f"{name}.dat")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name)
        target = input_dir / f"{name}__{safe_name}"
        receipt = _download_uri(uri, target)
        expected = str(source.get("sha256") or "").strip()
        if expected and expected != receipt["sha256"]:
            raise RuntimeError(f"input_sha256_mismatch:{name}")
        staged[name] = target
        records[name] = {**receipt, "expected_sha256": expected or None, "format": source.get("format"), "version": source.get("version")}
    atomic_json(input_dir / "provenance.json", records)
    return staged


def _read_inp_sections(path: Path) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = {}
    current = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line.upper()
            sections.setdefault(current, [])
            continue
        if not current:
            continue
        line = line.split(";", 1)[0].strip()
        if line:
            sections[current].append(line.split())
    return sections


def _network_geojson(inp_path: Path, report_text: str, output: Path) -> Path:
    sections = _read_inp_sections(inp_path)
    coordinates: dict[str, tuple[float, float]] = {}
    for row in sections.get("[COORDINATES]", []):
        if len(row) >= 3:
            try:
                coordinates[row[0]] = (float(row[1]), float(row[2]))
            except ValueError:
                continue
    vertices: dict[str, list[tuple[float, float]]] = {}
    for row in sections.get("[VERTICES]", []):
        if len(row) >= 3:
            try:
                vertices.setdefault(row[0], []).append((float(row[1]), float(row[2])))
            except ValueError:
                continue
    nodes: set[str] = set()
    node_kind: dict[str, str] = {}
    for section, kind in (("[JUNCTIONS]", "junction"), ("[OUTFALLS]", "outfall"), ("[STORAGE]", "storage"), ("[DIVIDERS]", "divider")):
        for row in sections.get(section, []):
            if row:
                nodes.add(row[0])
                node_kind[row[0]] = kind
    try:
        from pyproj import Transformer  # type: ignore

        transformer = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)
    except Exception:
        transformer = None

    def lonlat(xy: tuple[float, float]) -> list[float]:
        if transformer is None:
            return [xy[0], xy[1]]
        x, y = transformer.transform(xy[0], xy[1])
        return [float(x), float(y)]

    features: list[dict[str, Any]] = []
    node_depths = _swmm_node_depths(report_text)
    link_flows = _swmm_link_flows(report_text)
    for node in sorted(nodes):
        if node not in coordinates:
            continue
        props: dict[str, Any] = {"id": node, "kind": node_kind.get(node, "node")}
        if props["kind"] == "junction" and node in node_depths:
            props["maximum_depth_m"] = node_depths[node]
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": lonlat(coordinates[node])}, "properties": props})
    links: list[tuple[str, str, str, str]] = []
    for section, kind in (("[CONDUITS]", "conduit"), ("[PUMPS]", "pump"), ("[ORIFICES]", "orifice"), ("[WEIRS]", "weir"), ("[OUTLETS]", "outlet")):
        for row in sections.get(section, []):
            if len(row) >= 3:
                links.append((row[0], row[1], row[2], kind))
    for link_id, start, end, kind in links:
        if start not in coordinates or end not in coordinates:
            continue
        points = [coordinates[start], *vertices.get(link_id, []), coordinates[end]]
        props = {"id": link_id, "kind": kind, "from_node": start, "to_node": end}
        if link_id in link_flows:
            props["maximum_flow_lps"] = link_flows[link_id]
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [lonlat(point) for point in points]}, "properties": props})
    geojson_path = output / "network.geojson"
    atomic_json(geojson_path, _geojson_feature_collection(features))
    return geojson_path


def _run_1d(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if manifest["request"]["input_mode"] == "customer_mount":
        staged = _stage_customer_inputs(manifest, output, ["network", "rainfall"])
        input_path = staged.get("network")
        if input_path is None:
            raise RuntimeError("regional_network_input_missing")
        # Keep the solver-native filename stable for downstream report tools.
        solver_input = output / "model.inp"
        shutil.copyfile(input_path, solver_input)
        input_path = solver_input
    else:
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
    geojson_path = _network_geojson(input_path, report_text, output) if manifest["request"]["input_mode"] == "customer_mount" else output / "network.geojson"
    if manifest["request"]["input_mode"] != "customer_mount":
        min_lon, min_lat, max_lon, max_lat = _bbox(manifest)
        mid_lat = (min_lat + max_lat) / 2
        atomic_json(geojson_path, _geojson_feature_collection([
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [(min_lon + max_lon) / 2, mid_lat]}, "properties": {"id": "J1", "kind": "junction", **_parse_swmm_report(report_text)}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [max_lon, mid_lat]}, "properties": {"id": "O1", "kind": "outfall"}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[(min_lon + max_lon) / 2, mid_lat], [max_lon, mid_lat]]}, "properties": {"id": "C1", "kind": "conduit"}},
        ]))
    model_scope = "Musaffah_00 customer SWMM network" if manifest["request"]["input_mode"] == "customer_mount" else "single-subcatchment development fixture"
    return {
        "solver": "epa_swmm",
        "version": "5.2.4",
        "status": "completed",
        "model_scope": model_scope,
        "input": str(input_path),
        "report": str(report),
        "report_sha256": _sha256(report),
        "binary": str(binary),
        "binary_sha256": _sha256(binary),
        "quality": _parse_swmm_report(report_text),
        "map": str(geojson_path),
    }


def _run_2d(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run ANUGA on the registered DTM (or the explicit development fixture)."""
    import anuga  # type: ignore
    import numpy as np  # type: ignore

    output.mkdir(parents=True, exist_ok=True)
    min_lon, min_lat, max_lon, max_lat = _bbox(manifest)
    params = manifest["parameters"]["two_d"]
    rainfall = manifest["parameters"]["rainfall"]
    terrain_path: Path | None = None
    terrain_crs = "EPSG:4326"
    left = bottom = 0.0
    if manifest["request"]["input_mode"] == "customer_mount":
        staged = _stage_customer_inputs(manifest, output, ["terrain", "rainfall"])
        terrain_path = staged.get("terrain")
        if terrain_path is None:
            raise RuntimeError("regional_terrain_input_missing")

    elevation_grid: np.ndarray | None = None
    if terrain_path is not None:
        import rasterio  # type: ignore
        from rasterio.transform import array_bounds  # type: ignore

        with rasterio.open(terrain_path) as source:
            terrain_crs = str(source.crs or "EPSG:32640")
            max_cells = 120
            scale = max(1, int(max(source.width, source.height) / max_cells))
            sample_width = max(4, min(max_cells, int(math.ceil(source.width / scale))))
            sample_height = max(4, min(max_cells, int(math.ceil(source.height / scale))))
            elevation_grid = source.read(
                1,
                out_shape=(sample_height, sample_width),
                masked=True,
                resampling=rasterio.enums.Resampling.bilinear,
            ).filled(float(source.nodata or 0.0)).astype(float)
            # ANUGA evolves absolute stage values.  Use a local datum for the
            # bounded diagnostic domain so a large UTM/absolute elevation
            # offset cannot force a vanishing CFL timestep at the boundary.
            finite_elevation = elevation_grid[np.isfinite(elevation_grid)]
            if finite_elevation.size:
                elevation_grid = elevation_grid - float(np.nanmin(finite_elevation))
            scaled_transform = source.transform * source.transform.scale(
                source.width / sample_width, source.height / sample_height
            )
            left, bottom, right, top = array_bounds(sample_height, sample_width, scaled_transform)
        width_m = max(100.0, float(right - left))
        height_m = max(100.0, float(top - bottom))
        nx, ny = sample_width - 1, sample_height - 1
    else:
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
    if elevation_grid is None:
        def elevation_fn(x: Any, y: Any) -> Any:
            return 0.0005 * np.asarray(x, dtype=float) + 0.0003 * np.asarray(y, dtype=float)
    else:
        rows, cols = elevation_grid.shape
        def elevation_fn(x: Any, y: Any) -> Any:
            xx = np.clip((np.asarray(x, dtype=float) / width_m) * (cols - 1), 0, cols - 1)
            yy = np.clip((np.asarray(y, dtype=float) / height_m) * (rows - 1), 0, rows - 1)
            return elevation_grid[rows - 1 - np.rint(yy).astype(int), np.rint(xx).astype(int)]
    domain.set_quantity("elevation", elevation_fn)
    domain.set_quantity("friction", float(params["manning_n"]))
    domain.set_quantity("stage", elevation_fn)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary({"left": boundary, "right": boundary, "top": boundary, "bottom": boundary})
    rate = float(rainfall["total_mm"]) / max(float(rainfall["duration_minutes"]) * 60.0, 1.0) / 1000.0
    anuga.Rate_operator(domain, rate=rate, label="manifest_rainfall")
    final_time = float(rainfall["duration_minutes"]) * 60.0
    yieldstep = min(float(params["timestep_seconds"]), 300.0)
    for _ in domain.evolve(yieldstep=yieldstep, finaltime=final_time):
        pass
    elevation = np.asarray(domain.quantities["elevation"].centroid_values, dtype=float)
    stage = np.asarray(domain.quantities["stage"].centroid_values, dtype=float)
    depth = np.maximum(0.0, stage - elevation)
    centroids = np.asarray(domain.centroid_coordinates, dtype=float)
    try:
        from pyproj import Transformer  # type: ignore
        to_wgs84 = Transformer.from_crs(terrain_crs, "EPSG:4326", always_xy=True) if terrain_path else None
    except Exception:
        to_wgs84 = None
    features = []
    stride = max(1, int(len(depth) / 400))
    for index in range(0, len(depth), stride):
        x, y = centroids[index]
        if to_wgs84 is not None:
            lon, lat = to_wgs84.transform(float(x) + left, float(y) + bottom)
        else:
            lon = min_lon + (x / width_m) * (max_lon - min_lon)
            lat = min_lat + (y / height_m) * (max_lat - min_lat)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}, "properties": {"kind": "surface_depth", "depth_m": float(depth[index]), "cell_index": index}})
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
        "model_scope": "Musaffah_00 customer DTM diagnostic surface" if terrain_path else "single-subcatchment development fixture",
        "diagnostic_only": terrain_path is not None,
        "map": str(geojson_path),
    }
    atomic_json(output / "summary.json", summary)
    return summary


def _run_coupled(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run the bounded customer diagnostic as two solver-native branches.

    The current Musaffah package has no dynamic tide/SCADA boundary and is not
    admitted for engineering two-way coupling.  We therefore execute the real
    SWMM network and real-DTM ANUGA surface branches independently, then
    publish both result layers together.  The fixture path retains the pinned
    synchronous pilot for contract tests.
    """
    if manifest["request"]["input_mode"] == "customer_mount":
        output.mkdir(parents=True, exist_ok=True)
        one_d = _run_1d(manifest, output / "one_d")
        two_d = _run_2d(manifest, output / "two_d")
        combined_features: list[dict[str, Any]] = []
        for path in (Path(one_d["map"]), Path(two_d["map"])):
            payload = json.loads(path.read_text(encoding="utf-8"))
            combined_features.extend(payload.get("features") or [])
        combined_path = output / "maximum_depth_wgs84.geojson"
        atomic_json(combined_path, _geojson_feature_collection(combined_features))
        summary = {
            "solver": "epa_swmm_plus_anuga_regional_diagnostic",
            "status": "completed",
            "model_scope": "Musaffah_00 bounded regional diagnostic",
            "coupling_mode": "parallel_diagnostic_layers",
            "dynamic_tide_available": False,
            "scada_available": False,
            "engineering_use": False,
            "one_d": one_d,
            "two_d": two_d,
            "map": str(combined_path),
        }
        atomic_json(output / "summary.json", summary)
        return summary
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
