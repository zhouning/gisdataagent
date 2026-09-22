"""Isolated RD F hydraulic-model workflow for the Abu Dhabi V1 workbench.

The customer ``RD F.inp`` is a local, externally-forced SWMM model.  It is
kept separate from the existing citywide diagnostic model because its node
identifiers, forcing contract, spatial extent and quality gates are different.
This service preserves the source file byte-for-byte, runs EPA SWMM against a
private snapshot, and exposes an auditable five-stage readiness receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


RDF_WORKFLOW_SCHEMA = "gwm.abu_dhabi_flood.rdf_workflow.v1"
RDF_RUN_SCHEMA = "gwm.abu_dhabi_flood.rdf_swmm_run.v1"
DEFAULT_RDF_INPUT = Path.home() / "Downloads/阿布扎比/RD F.inp"
DEFAULT_RDF_RUN_ROOT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/rd_f_workflow"
)
DEFAULT_SWMM_EXECUTABLE = (
    Path.home()
    / "gisdataagent/external_models/swmm-5.2.4/build-local/bin/runswmm"
)

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abu-rdf-swmm")
_RUN_LOCK = threading.RLock()
_RUNS: dict[str, dict[str, Any]] = {}
_ACTIVE_RUN_ID: str | None = None
_FLOAT = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?"


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


def _source_path() -> Path:
    return _configured_path("ABU_DHABI_RDF_INPUT", DEFAULT_RDF_INPUT)


def _run_root() -> Path:
    return _configured_path("ABU_DHABI_RDF_RUN_ROOT", DEFAULT_RDF_RUN_ROOT)


def _executable_path() -> Path:
    return _configured_path("ABU_DHABI_RDF_SWMM_EXECUTABLE", DEFAULT_SWMM_EXECUTABLE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=4)
def _scan_cached(path_text: str, modified_ns: int, size: int) -> dict[str, Any]:
    del modified_ns
    path = Path(path_text)
    section = ""
    counts: dict[str, int] = {}
    options: dict[str, str] = {}
    inflow_series: set[str] = set()
    timeseries: set[str] = set()
    minimum_x = minimum_y = maximum_x = maximum_y = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.upper()
                counts.setdefault(section, 0)
                continue
            if not stripped or stripped.startswith(";") or not section:
                continue
            counts[section] = counts.get(section, 0) + 1
            parts = stripped.split()
            if section == "[OPTIONS]" and len(parts) >= 2:
                options[parts[0].upper()] = " ".join(parts[1:])
            elif section == "[INFLOWS]" and len(parts) >= 3:
                inflow_series.add(parts[2])
            elif section == "[TIMESERIES]":
                timeseries.add(parts[0])
            elif section == "[COORDINATES]" and len(parts) >= 3:
                try:
                    x_value, y_value = float(parts[1]), float(parts[2])
                except ValueError:
                    continue
                minimum_x = x_value if minimum_x is None else min(minimum_x, x_value)
                maximum_x = x_value if maximum_x is None else max(maximum_x, x_value)
                minimum_y = y_value if minimum_y is None else min(minimum_y, y_value)
                maximum_y = y_value if maximum_y is None else max(maximum_y, y_value)

    required_sections = {
        "[OPTIONS]",
        "[JUNCTIONS]",
        "[OUTFALLS]",
        "[CONDUITS]",
        "[XSECTIONS]",
        "[INFLOWS]",
        "[TIMESERIES]",
        "[COORDINATES]",
    }
    missing_sections = sorted(required_sections.difference(counts))
    missing_inflow_series = sorted(inflow_series.difference(timeseries))
    bbox = None
    if None not in {minimum_x, minimum_y, maximum_x, maximum_y}:
        bbox = [minimum_x, minimum_y, maximum_x, maximum_y]
    return {
        "path": str(path),
        "filename": path.name,
        "size_bytes": size,
        "sha256": _sha256(path),
        "sections": counts,
        "options": options,
        "bbox_epsg32640": bbox,
        "span_km": {
            "east_west": round((maximum_x - minimum_x) / 1000.0, 3) if bbox else None,
            "north_south": round((maximum_y - minimum_y) / 1000.0, 3) if bbox else None,
        },
        "inflow_series_count": len(inflow_series),
        "timeseries_count": len(timeseries),
        "missing_inflow_series_count": len(missing_inflow_series),
        "missing_inflow_series_sample": missing_inflow_series[:20],
        "missing_sections": missing_sections,
        "external_inflow_driven": bool(inflow_series) and counts.get("[SUBCATCHMENTS]", 0) == 0,
        "source_ready": not missing_sections and not missing_inflow_series,
    }


def inspect_source() -> dict[str, Any]:
    path = _source_path().expanduser().resolve()
    if not path.is_file():
        return {
            "path": str(path),
            "filename": path.name,
            "source_ready": False,
            "error": "rdf_input_missing",
        }
    stat = path.stat()
    return _scan_cached(str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _latest_manifest() -> dict[str, Any] | None:
    root = _run_root().expanduser().resolve()
    if not root.is_dir():
        return None
    manifests = sorted(
        root.glob("*/run_manifest.json"), key=lambda item: item.stat().st_mtime_ns
    )
    if not manifests:
        return None
    payload = _json_object(manifests[-1])
    return payload or None


def _artifact_state(name: str) -> bool:
    return (_run_root().expanduser().resolve() / "derived" / name).is_file()


def workflow_status() -> dict[str, Any]:
    source = inspect_source()
    latest = _latest_manifest()
    if latest and latest.get("status") in {"queued", "running"}:
        swmm_status = "partial"
        swmm_label = "运行中"
    elif latest and latest.get("status") == "completed":
        swmm_status = "ready"
        swmm_label = "基线运行通过"
    elif latest and latest.get("status") == "completed_with_warnings":
        swmm_status = "partial"
        swmm_label = "完成但质量门未通过"
    elif latest and latest.get("status") == "failed":
        swmm_status = "blocked"
        swmm_label = "运行失败"
    else:
        swmm_status = "partial" if source.get("source_ready") else "blocked"
        swmm_label = "等待首次基线运行" if source.get("source_ready") else "输入未就绪"

    surface_ready = _artifact_state("rd_f_surface_2d_manifest.json")
    gwm_ready = _artifact_state("rd_f_gwm_model_manifest.json")
    validation_ready = _artifact_state("rd_f_validation_report.json")
    stages = [
        {
            "key": "input",
            "index": "01",
            "title": "RD F 输入与空间登记",
            "status": "ready" if source.get("source_ready") else "blocked",
            "status_label": "输入已核验" if source.get("source_ready") else "输入不可用",
            "summary": "保留原始外部节点入流和泵站配置，不套用全市汇水区改写器。",
        },
        {
            "key": "swmm",
            "index": "02",
            "title": "原生一维水动力",
            "status": swmm_status,
            "status_label": swmm_label,
            "summary": "EPA SWMM 5.2.4 原样运行，输出独立 RPT / OUT 和质量回执。",
        },
        {
            "key": "surface",
            "index": "03",
            "title": "RD F 二维地表耦合",
            "status": "ready" if surface_ready else "blocked",
            "status_label": "二维产物已登记" if surface_ready else "等待接口映射与局部网格",
            "summary": "建立 CB 节点、客户DTM与ANUGA局部计算网格的交换关系。",
        },
        {
            "key": "gwm",
            "index": "04",
            "title": "RD F 局部GWM",
            "status": "ready" if gwm_ready else "blocked",
            "status_label": "局部模型已登记" if gwm_ready else "等待多情景二维标签",
            "summary": "训练独立的RD F局部模型，不复用全市250米冻结GWM参数。",
        },
        {
            "key": "validation",
            "index": "05",
            "title": "验证与交付",
            "status": "ready" if validation_ready else "blocked",
            "status_label": "验证包已登记" if validation_ready else "等待观测与质量门",
            "summary": "输出物理一致性、观测对比、不确定性和工程准入边界。",
        },
    ]
    return {
        "schema": RDF_WORKFLOW_SCHEMA,
        "status": "ready" if all(stage["status"] == "ready" for stage in stages) else "partial",
        "source": source,
        "latest_run": latest,
        "stages": stages,
        "ready_stage_count": sum(stage["status"] == "ready" for stage in stages),
        "stage_count": len(stages),
        "claim_boundary": (
            "RD F is a local hydraulic model covering roughly 3.55 by 3.21 km; "
            "it must not be represented as the Abu Dhabi citywide model."
        ),
    }


def _report_value(report_text: str, label: str) -> float | None:
    match = re.search(
        rf"(?im)^\s*{re.escape(label)}\s*\.{{2,}}\s*"
        rf"(?:{_FLOAT})\s+(?P<value>{_FLOAT})\s*$",
        report_text,
    )
    return float(match.group("value")) if match else None


def _single_report_value(report_text: str, label: str) -> float | None:
    match = re.search(
        rf"(?im)^\s*{re.escape(label)}\s*(?:\.{{2,}}|:)\s*"
        rf"(?P<value>{_FLOAT})",
        report_text,
    )
    return float(match.group("value")) if match else None


def _report_summary(report_path: Path, source: dict[str, Any]) -> dict[str, Any]:
    report = report_path.read_text(encoding="utf-8", errors="replace")
    version_match = re.search(
        r"EPA STORM WATER MANAGEMENT MODEL - VERSION\s+([0-9.]+)\s+\(Build\s+([0-9.]+)\)",
        report,
    )
    flow_units_match = re.search(r"(?im)^\s*Flow Units\s*\.{2,}\s*(\S+)", report)
    routing_match = re.search(r"(?im)^\s*Flow Routing Method\s*\.{2,}\s*(\S+)", report)
    routing_block_match = re.search(
        r"Flow Routing Continuity(?P<body>.*?)(?:Highest Continuity Errors|Highest Flow Instability Indexes)",
        report,
        flags=re.DOTALL,
    )
    routing_block = routing_block_match.group("body") if routing_block_match else report
    warning_lines = re.findall(r"(?im)^\s*WARNING[^\r\n]*", report)
    error_lines = re.findall(r"(?im)^\s*ERROR[^\r\n]*", report)
    routing_error = _single_report_value(routing_block, "Continuity Error (%)")
    nonconverging = _single_report_value(report, "% of Steps Not Converging")
    quality_checks = [
        {
            "key": "no_swmm_errors",
            "passed": not error_lines,
            "value": len(error_lines),
            "limit": 0,
        },
        {
            "key": "routing_continuity",
            "passed": routing_error is not None and abs(routing_error) <= 5.0,
            "value": routing_error,
            "limit": 5.0,
        },
        {
            "key": "nonconverging_steps",
            "passed": nonconverging is not None and nonconverging <= 5.0,
            "value": nonconverging,
            "limit": 5.0,
        },
    ]
    return {
        "solver": {
            "name": "EPA SWMM",
            "version_series": version_match.group(1) if version_match else None,
            "version": version_match.group(2) if version_match else None,
        },
        "flow_units": flow_units_match.group(1) if flow_units_match else None,
        "routing_method": routing_match.group(1) if routing_match else None,
        "node_count": int(source.get("sections", {}).get("[JUNCTIONS]", 0))
        + int(source.get("sections", {}).get("[OUTFALLS]", 0))
        + int(source.get("sections", {}).get("[STORAGE]", 0)),
        "link_count": int(source.get("sections", {}).get("[CONDUITS]", 0))
        + int(source.get("sections", {}).get("[PUMPS]", 0)),
        "external_outflow_million_litres": _report_value(routing_block, "External Outflow"),
        "flooding_loss_million_litres": _report_value(routing_block, "Flooding Loss"),
        "routing_continuity_error_percent": routing_error,
        "nonconverging_steps_percent": nonconverging,
        "warning_count": len(warning_lines),
        "error_count": len(error_lines),
        "warning_sample": [line.strip() for line in warning_lines[:12]],
        "quality": {
            "passed": all(check["passed"] for check in quality_checks),
            "checks": quality_checks,
            "admission_effect": "none_diagnostic_quality_only",
        },
    }


def _run_worker(run_id: str) -> None:
    global _ACTIVE_RUN_ID
    source = inspect_source()
    run_dir = _run_root().expanduser().resolve() / run_id
    manifest_path = run_dir / "run_manifest.json"
    manifest = _json_object(manifest_path)
    try:
        source_path = Path(source["path"])
        executable = _executable_path().expanduser().resolve()
        if not executable.is_file():
            raise FileNotFoundError("rdf_swmm_executable_missing")
        snapshot = run_dir / "RD_F.source.inp"
        report_path = run_dir / "RD_F.rpt"
        output_path = run_dir / "RD_F.out"
        stdout_path = run_dir / "swmm_stdout.log"
        manifest.update(
            {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
        )
        _json_write(manifest_path, manifest)
        with _RUN_LOCK:
            _RUNS[run_id] = dict(manifest)
        shutil.copy2(source_path, snapshot)
        completed = subprocess.run(
            [executable, snapshot, report_path, output_path],
            cwd=run_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(os.environ.get("ABU_DHABI_RDF_SWMM_TIMEOUT_SECONDS", "900")),
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        if completed.returncode != 0 or not report_path.is_file() or not output_path.is_file():
            raise RuntimeError(f"rdf_swmm_execution_failed:{completed.returncode}")
        summary = _report_summary(report_path, source)
        manifest.update(
            {
                "status": "completed" if summary["quality"]["passed"] else "completed_with_warnings",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "artifacts": {
                    "input_snapshot": {
                        "name": snapshot.name,
                        "size_bytes": snapshot.stat().st_size,
                        "sha256": _sha256(snapshot),
                    },
                    "report": {
                        "name": report_path.name,
                        "size_bytes": report_path.stat().st_size,
                        "sha256": _sha256(report_path),
                    },
                    "binary_output": {
                        "name": output_path.name,
                        "size_bytes": output_path.stat().st_size,
                        "sha256": _sha256(output_path),
                    },
                    "stdout": {
                        "name": stdout_path.name,
                        "size_bytes": stdout_path.stat().st_size,
                    },
                },
            }
        )
    except Exception as error:
        manifest.update(
            {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": str(error)[:500],
            }
        )
    finally:
        _json_write(manifest_path, manifest)
        with _RUN_LOCK:
            _RUNS[run_id] = manifest
            if _ACTIVE_RUN_ID == run_id:
                _ACTIVE_RUN_ID = None


def start_baseline_run() -> dict[str, Any]:
    global _ACTIVE_RUN_ID
    source = inspect_source()
    if not source.get("source_ready"):
        raise ValueError(str(source.get("error") or "rdf_input_preflight_failed"))
    with _RUN_LOCK:
        if _ACTIVE_RUN_ID:
            return public_run(_ACTIVE_RUN_ID)
        run_id = (
            "abu-rdf-swmm-"
            + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        run_dir = _run_root().expanduser().resolve() / run_id
        manifest = {
            "schema": RDF_RUN_SCHEMA,
            "run_id": run_id,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "filename": source["filename"],
                "size_bytes": source["size_bytes"],
                "sha256": source["sha256"],
                "forcing_mode": "preserved_external_node_inflows",
            },
            "claim_boundary": "Local RD F diagnostic; not citywide, calibrated or engineering-admitted.",
        }
        _json_write(run_dir / "run_manifest.json", manifest)
        _RUNS[run_id] = manifest
        _ACTIVE_RUN_ID = run_id
        _EXECUTOR.submit(_run_worker, run_id)
        return dict(manifest)


def public_run(run_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"abu-rdf-swmm-\d{14}-[0-9a-f]{8}", run_id):
        raise KeyError(run_id)
    with _RUN_LOCK:
        cached = _RUNS.get(run_id)
    if cached:
        return dict(cached)
    manifest = _json_object(_run_root().expanduser().resolve() / run_id / "run_manifest.json")
    if not manifest:
        raise KeyError(run_id)
    return manifest


@lru_cache(maxsize=4)
def _map_payload_cached(run_id: str, report_modified_ns: int) -> dict[str, Any]:
    del report_modified_ns
    from pyproj import Transformer

    from .abu_dhabi_flood_scenario_service import _parse_node_hydraulic_results

    run_dir = _run_root().expanduser().resolve() / run_id
    report_path = run_dir / "RD_F.rpt"
    input_path = run_dir / "RD_F.source.inp"
    hydraulic = _parse_node_hydraulic_results(report_path)
    coordinates: dict[str, tuple[float, float]] = {}
    section = ""
    with input_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.upper()
                continue
            if section != "[COORDINATES]" or not stripped or stripped.startswith(";"):
                continue
            parts = stripped.split()
            if len(parts) < 3:
                continue
            try:
                coordinates[parts[0]] = (float(parts[1]), float(parts[2]))
            except ValueError:
                continue
    transformer = Transformer.from_crs(32640, 4326, always_xy=True)
    features = []
    longitude_values: list[float] = []
    latitude_values: list[float] = []
    for node_id, values in hydraulic.items():
        coordinate = coordinates.get(node_id)
        if coordinate is None:
            continue
        longitude, latitude = transformer.transform(*coordinate)
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            continue
        longitude_values.append(longitude)
        latitude_values.append(latitude)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    **values,
                    "scenario_max_water_depth_m": values.get("max_water_depth_m", 0.0),
                    "scenario_max_hydraulic_head_m": values.get("max_hydraulic_head_m"),
                    "scenario_max_overflow_or_flooding_m3s": values.get("max_overflow_or_flooding_m3s", 0.0),
                    "scenario_flooded_hours": values.get("flooded_hours", 0.0),
                    "scenario_total_flood_volume_million_litres": values.get("total_flood_volume_million_litres", 0.0),
                    "scenario_node_flooding_detected": bool(values.get("max_overflow_or_flooding_m3s", 0.0) or values.get("flooded_hours", 0.0)),
                    "scenario_max_depth_time": f"Day {values.get('max_depth_day', 0)} {values.get('max_depth_time', '—')}",
                    "model_scope": "RD F local network",
                },
            }
        )
    center = (
        [
            (min(latitude_values) + max(latitude_values)) / 2.0,
            (min(longitude_values) + max(longitude_values)) / 2.0,
        ]
        if longitude_values
        else [24.46, 54.45]
    )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.rdf_swmm_map.v1",
            "run_id": run_id,
            "solver": "EPA SWMM 5.2.4",
            "scope": "RD F local network",
            "feature_count": len(features),
            "center": center,
            "claim_boundary": "Local diagnostic result; not an Abu Dhabi citywide prediction.",
        },
        "features": features,
    }


def run_map_payload(run_id: str) -> dict[str, Any]:
    run = public_run(run_id)
    if run.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError("rdf_run_map_requires_completed_run")
    report_path = _run_root().expanduser().resolve() / run_id / "RD_F.rpt"
    if not report_path.is_file():
        raise ValueError("rdf_run_report_missing")
    return _map_payload_cached(run_id, int(report_path.stat().st_mtime_ns))
