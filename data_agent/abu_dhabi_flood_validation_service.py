"""Read-only validation and delivery contract for the Abu Dhabi flood model.

This module exposes the completed customer-DTM April 2024 replay without
changing the state or result contracts of phases 1-4.  Source artifacts stay
outside the repository; only derived GeoJSON and audit metadata are returned.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

try:
    # The ASGI locale middleware binds this per-request.  Keeping the import
    # optional makes the validation service usable from its standalone tests.
    from .i18n import get_language
except Exception:  # pragma: no cover - standalone execution fallback
    def get_language() -> str:
        return "en"


_HYDRO_DATA_ROOT = Path(
    os.environ.get(
        "ABU_DHABI_HYDRO_DATA_ROOT",
        str(Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater"),
    )
).expanduser()
DEFAULT_HISTORICAL_REPLAY_ROOT = Path(
    os.environ.get(
        "ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT",
        str(_HYDRO_DATA_ROOT / "surface/historical_replay_2024_04/anuga_2d"),
    )
).expanduser()


def _root() -> Path:
    configured = os.environ.get("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_HISTORICAL_REPLAY_ROOT.expanduser().resolve()


def _read_json(path: Path, error_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(payload, dict):
        raise ValueError(error_code)
    return payload


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    """Read an adjacent audit receipt without making it a delivery prerequisite."""

    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _swmm_quality_contract(root: Path) -> dict[str, Any]:
    """Expose the native SWMM quality gate while keeping source files private.

    The phase-5 delivery directory contains derived 2D products, while the
    native SWMM receipt lives beside it under ``swmm/``.  The receipt is
    optional for fixture compatibility, but when present its strict gates are
    authoritative for the validation status shown to users.
    """

    receipt = _read_optional_json(root.parent / "swmm" / "swmm_execution_receipt.json")
    if receipt is None:
        return {
            "available": False,
            "status": "pending",
            "passed": None,
            "source": "SWMM execution receipt unavailable",
            "checks": [],
            "failed_checks": [],
            "admission_effect": "none_diagnostic_quality_only",
        }
    gates = receipt.get("strict_quality_gates")
    if not isinstance(gates, dict):
        gates = receipt.get("quality_gates")
    if not isinstance(gates, dict):
        gates = {}
    checks = gates.get("checks") if isinstance(gates.get("checks"), list) else []
    normalized_checks = [
        {
            "check_id": item.get("check_id", "unknown") if isinstance(item, dict) else "unknown",
            "observed": item.get("observed") if isinstance(item, dict) else None,
            "passed": bool(item.get("passed")) if isinstance(item, dict) else False,
            "threshold_or_required": item.get("threshold_or_required") if isinstance(item, dict) else None,
        }
        for item in checks
    ]
    failed_checks = [item["check_id"] for item in normalized_checks if not item["passed"]]
    passed = bool(gates.get("passed")) if "passed" in gates else not failed_checks
    return {
        "available": True,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "source": "SWMM execution receipt",
        "solver_status": receipt.get("status"),
        "checks": normalized_checks,
        "failed_checks": failed_checks,
        "admission_effect": gates.get("admission_effect", "none_diagnostic_quality_only"),
    }


def _safe_relative_path(value: Any, error_code: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(error_code)
    return relative


def _feature_collection(path: Path, error_code: str) -> dict[str, Any]:
    payload = _read_json(path, error_code)
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError(error_code)
    return payload


def _first_renderable_snapshot_index(
    root: Path, snapshots: list[dict[str, Any]]
) -> int:
    """Return the first frame containing a non-empty surface result.

    A numerical replay commonly starts with several dry frames.  Keeping the
    dry frames in the timeline is important, but using frame zero as the map
    bootstrap makes a successful run look empty.  Read only until the first
    non-empty frame; the full frame contract is still validated separately.
    """

    for index, item in enumerate(snapshots):
        relative = _safe_relative_path(
            item.get("path"), "historical_replay_snapshot_path_invalid"
        )
        payload = _feature_collection(
            root / relative, "historical_replay_snapshot_invalid"
        )
        if payload.get("features"):
            return index
    return 0


def _check(name: str, passed: bool, observed: Any, requirement: Any) -> dict[str, Any]:
    return {"check_id": name, "passed": bool(passed), "observed": observed, "threshold_or_required": requirement}


def _delivery_assets(root: Path, delivery: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(asset: dict[str, Any]) -> None:
        # ``delivery_summary.outputs`` repeats the two canonical assets.  Keep
        # one row per file so the customer-facing report reads like a package
        # manifest instead of showing duplicate files.
        name = str(asset.get("asset") or "")
        if not name or name in seen:
            return
        seen.add(name)
        assets.append(asset)

    maximum = root / "maximum_depth_wgs84.geojson"
    add({"asset": "maximum_depth_wgs84.geojson", "kind": "maximum_depth", "exists": maximum.is_file(), "feature_count": None})
    if maximum.is_file():
        try:
            assets[0]["feature_count"] = len(json.loads(maximum.read_text(encoding="utf-8")).get("features", []))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            assets[0]["exists"] = False
    snapshots = manifest.get("snapshots") or []
    add({
        "asset": "temporal_snapshots/manifest.json",
        "kind": "timeline_manifest",
        "exists": (root / "temporal_snapshots" / "manifest.json").is_file(),
        "snapshot_count": len(snapshots),
    })
    add({
        "asset": "abu_dhabi_public_citywide_2d.sww",
        "kind": "native_2d_result",
        "exists": (root / "abu_dhabi_public_citywide_2d.sww").is_file(),
        "delivery_only": True,
    })
    outputs = delivery.get("outputs") or {}
    for key, value in outputs.items():
        if not isinstance(value, str):
            continue
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            add({"asset": key, "kind": "declared_output", "exists": False, "error": "unsafe_output_path"})
            continue
        add({"asset": value, "kind": key, "exists": (root / relative).is_file()})
    return assets


def _load_contract() -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _root()
    maximum_path = root / "maximum_depth_wgs84.geojson"
    manifest_path = root / "temporal_snapshots" / "manifest.json"
    delivery_path = root / "delivery_summary.json"
    for path, code in (
        (maximum_path, "historical_replay_maximum_depth_missing"),
        (manifest_path, "historical_replay_timeline_missing"),
        (delivery_path, "historical_replay_delivery_summary_missing"),
    ):
        if not path.is_file():
            raise ValueError(code)
    maximum = _feature_collection(maximum_path, "historical_replay_maximum_depth_invalid")
    manifest = _read_json(manifest_path, "historical_replay_timeline_invalid")
    delivery = _read_json(delivery_path, "historical_replay_delivery_summary_invalid")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("historical_replay_timeline_invalid")
    for item in snapshots:
        if not isinstance(item, dict):
            raise ValueError("historical_replay_snapshot_invalid")
        relative = _safe_relative_path(item.get("path"), "historical_replay_snapshot_path_invalid")
        if not (root / relative).is_file():
            raise ValueError("historical_replay_snapshot_missing")
    return root, maximum, manifest, delivery


def historical_replay_bootstrap_payload() -> dict[str, Any]:
    root, maximum, manifest, delivery = _load_contract()
    snapshots = manifest["snapshots"]
    domain = delivery.get("domain") or {}
    forcing = delivery.get("forcing") or {}
    coupling = delivery.get("coupling") or {}
    results = delivery.get("results") or {}
    surface = delivery.get("surface") or {}
    admission = delivery.get("admission") or {}
    swmm_quality = _swmm_quality_contract(root)
    prescribed = float(coupling.get("prescribed_swmm_to_anuga_volume_m3") or 0.0)
    actual = float((coupling.get("runtime") or {}).get("actual_swmm_to_anuga_volume_m3") or 0.0)
    relative_error = abs(actual - prescribed) / prescribed if prescribed else math.inf
    checks = [
        _check("maximum_depth_asset_complete", maximum.get("type") == "FeatureCollection", len(maximum.get("features", [])), ">= 1 feature"),
        _check("timeline_manifest_complete", bool(snapshots), len(snapshots), ">= 1 snapshot"),
        _check("timeline_asset_paths_safe_and_present", True, len(snapshots), "all relative paths present"),
        _check("swmm_to_anuga_volume_reconciliation", math.isfinite(relative_error) and relative_error <= 0.01, relative_error, "<= 0.01"),
    ]
    validation_status = (
        "artifacts_complete_swmm_quality_gate_failed"
        if swmm_quality["status"] == "failed"
        else "numerical_replay_complete_observation_comparison_pending"
    )
    gates = [
        {"gate_id": "artifact_completeness", "status": "passed", "label": "结果资产与时间片完整"},
        {"gate_id": "coupling_reconciliation", "status": "passed" if relative_error <= 0.01 else "warning", "label": "SWMM→二维体积交换对账"},
        {"gate_id": "swmm_numerical_quality", "status": swmm_quality["status"], "label": "SWMM 严格数值质量门"},
        {"gate_id": "observation_comparison", "status": "pending", "label": "积水深度、范围和退水观测对比"},
        {"gate_id": "independent_2d_crosscheck", "status": "pending", "label": "LISFLOOD-FP 独立二维复核"},
        {"gate_id": "impact_overlay_admission", "status": "pending", "label": "道路、设施和人口影响叠加准入"},
    ]
    all_asset_checks_passed = all(item["passed"] for item in checks)
    elapsed = [float(item.get("time_minutes", item.get("time_seconds", 0.0) / 60.0)) for item in snapshots]
    time_values = [f"{value:.0f} min" for value in elapsed]
    initial_time_index = _first_renderable_snapshot_index(root, snapshots)
    return {
        "type": "FeatureCollection",
        "name": "abu_dhabi_historical_replay_validation",
        "features": [],
        "maximum_depth": maximum,
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.historical_replay_validation.v1",
            "run_id": delivery.get("run_id", "abu-dhabi-april-2024-reconstructed-swmm-anuga-2d"),
            "solver": "EPA SWMM 5.2.4 + ANUGA 2D",
            "result_status": delivery.get("status", "completed_customer_dtm_citywide_2d_validation"),
            "validation_status": validation_status,
            "surface_product": surface.get("product", "Customer AUH_DTM_5m_Z40"),
            "surface_evidence_class": surface.get("evidence_class", "customer_dtm_5m"),
            "source_resolution_m": surface.get("source_resolution_m", [5.0, 5.0]),
            "forcing": forcing,
            "domain": {
                "simulation_duration_hours": domain.get("simulation_duration_hours"),
                "cell_size_m": domain.get("cell_size_m"),
                "active_land_cells": domain.get("active_land_cells"),
                "excluded_permanent_water_cells": domain.get("excluded_permanent_water_cells"),
            },
            "results": results,
            "coupling": {
                "mode": coupling.get("mode"),
                "prescribed_swmm_to_anuga_volume_m3": prescribed,
                "actual_swmm_to_anuga_volume_m3": actual,
                "relative_volume_error": relative_error,
                "mapped_node_count": coupling.get("mapped_node_count"),
                "swmm_node_count": coupling.get("swmm_node_count"),
            },
            "timeline": {
                "available": True,
                "run_id": delivery.get("run_id", "abu-dhabi-april-2024-reconstructed-swmm-anuga-2d"),
                "endpoint": "/api/abu-dhabi/flood/validation/historical-replay/timeseries",
                "time_values": time_values,
                "elapsed_minutes": elapsed,
                "period_count": len(snapshots),
                "step_minutes": float(domain.get("output_step_minutes", 120.0)),
                "total_cell_count": int(domain.get("active_land_cells", len(maximum.get("features", []))) or 0),
                "initial_time_index": initial_time_index,
            },
            "validation": {
                "status": validation_status,
                "checks": checks,
                "gates": gates,
                "numerical_validation_completed": bool(admission.get("numerical_validation_completed", all_asset_checks_passed)),
                "swmm_quality": swmm_quality,
                "swmm_quality_gate_passed": swmm_quality["passed"],
                "observation_comparison": "pending",
                "engineering_admission": "pending",
            },
            "delivery_assets": _delivery_assets(root, delivery, manifest),
            "claim_boundary": delivery.get("claim_boundary", "Historical replay numerical validation; observation comparison and engineering admission remain pending."),
        },
    }


def historical_replay_timeseries_payload(time_index: int) -> dict[str, Any]:
    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("time_index_invalid")
    root, _, manifest, _ = _load_contract()
    snapshots = manifest["snapshots"]
    if time_index < 0 or time_index >= len(snapshots):
        raise ValueError("time_index_out_of_range")
    item = snapshots[time_index]
    relative = _safe_relative_path(item.get("path"), "historical_replay_snapshot_path_invalid")
    payload = _feature_collection(root / relative, "historical_replay_snapshot_invalid")
    payload["name"] = f"abu_dhabi_historical_replay_surface_depth_t{time_index:03d}"
    payload["metadata"] = {
        "schema": "gwm.abu_dhabi_flood.historical_replay_timeseries.v1",
        "solver": "ANUGA 2D",
        "time_index": time_index,
        "time_minutes": float(item.get("time_minutes", item.get("time_seconds", 0.0) / 60.0)),
        "elapsed_minutes": float(item.get("time_minutes", item.get("time_seconds", 0.0) / 60.0)),
        "depth_field": "depth_m",
        "crs": "EPSG:4326",
        "result_status": "historical_replay_numerical_validation",
    }
    return payload


def historical_replay_report_payload() -> dict[str, Any]:
    """Build the customer-facing, path-safe phase-5 delivery summary.

    This is intentionally derived from the same read-only bootstrap contract
    used by the map.  It does not inspect or expose customer source files.
    """

    replay = historical_replay_bootstrap_payload()
    root, _, manifest, delivery = _load_contract()
    metadata = replay["metadata"]
    validation = metadata["validation"]
    quality = validation["swmm_quality"]
    return {
        "schema": "gwm.abu_dhabi_flood.phase5_delivery_report.v1",
        "title": "Abu Dhabi Urban Pluvial Flood World Model - Phase 5 Delivery Report",
        "run_id": metadata["run_id"],
        "solver": metadata["solver"],
        "surface_product": metadata["surface_product"],
        "results": metadata["results"],
        "domain": metadata["domain"],
        "timeline": metadata["timeline"],
        "coupling": metadata["coupling"],
        "validation": {
            "status": validation["status"],
            "gates": validation["gates"],
            "swmm_quality": quality,
            "observation_comparison": validation["observation_comparison"],
            "engineering_admission": validation["engineering_admission"],
        },
        "delivery_assets": metadata["delivery_assets"],
        "claim_boundary": metadata["claim_boundary"],
        "maximum_depth": replay["maximum_depth"],
        "rainfall": _rainfall_series(root, replay["metadata"].get("forcing") or {}),
        "evolution": _surface_evolution_series(root, manifest, replay["metadata"].get("domain") or {}),
        "phases": [
            {
                "number": "01",
                "name": "Data and admission",
                "purpose": "Build a traceable model input contract from drainage, terrain, rainfall, boundary and observation data.",
                "output": "Source register, field mapping, issue list and receipt checks.",
                "status": "partial",
            },
            {
                "number": "02",
                "name": "1D drainage hydraulics",
                "purpose": "Use EPA SWMM to calculate rainfall-runoff, node surcharge and pipe-network hydraulics.",
                "output": "Native SWMM RPT/OUT, node and pipe time series, and numerical quality receipt.",
                "status": "quality_gate_failed" if quality["status"] == "failed" else "partial",
            },
            {
                "number": "03",
                "name": "2D surface hydraulics",
                "purpose": "Use ANUGA 2D to route exchanged drainage volume across the terrain surface.",
                "output": "Maximum depth, time-varying depth and SWMM-to-2D volume reconciliation.",
                "status": "complete",
            },
            {
                "number": "04",
                "name": "GWM rapid rollout",
                "purpose": "Learn approved physical-model states to screen intervention scenarios with uncertainty gating.",
                "output": "Rapid scenario comparison, uncertainty and physical-model fallback signal.",
                "status": "prototype",
            },
            {
                "number": "05",
                "name": "Validation and delivery",
                "purpose": "Replay an independent event, assemble the result package and show admission evidence.",
                "output": "This replay report, map/time-series assets, gates and next evidence requirements.",
                "status": "partial",
            },
        ],
    }


def _rainfall_series(root: Path, forcing: dict[str, Any]) -> list[dict[str, float]]:
    """Read the model forcing as a compact, report-safe rainfall series.

    The INP is a private source artifact and is never linked in the report;
    only timestamp/intensity values are emitted.  A metadata-only fallback is
    provided for test fixtures that do not include the native input file.
    """
    inp = root.parent / "swmm" / "historical_replay.inp"
    values: list[tuple[datetime | None, float]] = []
    if inp.is_file():
        try:
            lines = inp.read_text(encoding="utf-8", errors="ignore").splitlines()
            in_ts = False
            for line in lines:
                stripped = line.strip()
                if stripped.upper() == "[TIMESERIES]":
                    in_ts = True
                    continue
                if in_ts and stripped.startswith("["):
                    break
                parts = stripped.split()
                if in_ts and len(parts) >= 4 and parts[0] == "TS_INTERACTIVE":
                    try:
                        value = float(parts[3])
                    except ValueError:
                        continue
                    if math.isfinite(value):
                        timestamp: datetime | None = None
                        if len(parts) >= 3:
                            try:
                                timestamp = datetime.strptime(f"{parts[1]} {parts[2]}", "%m/%d/%Y %H:%M")
                            except ValueError:
                                timestamp = None
                        values.append((timestamp, max(0.0, value)))
        except OSError:
            values = []
    if not values:
        total = float(forcing.get("generated_total_depth_mm") or 0.0)
        peak = float(forcing.get("peak_intensity_mm_per_hour") or 0.0)
        values = [(None, 0.0), (None, peak), (None, 0.0)] if peak else [(None, 0.0)]
        if total and len(values) == 3:
            # Preserve the supplied total in the fallback's metadata while
            # keeping the visual honest about the absence of a source series.
            values[1] = peak
    # The event package metadata describes the source interval (often hourly),
    # while the SWMM time series may have been expanded to five-minute rows.
    # Prefer timestamps in the input file so the chart reflects the actual
    # model forcing.  The simulation window is authoritative: source rows
    # outside that window must not stretch the report axis beyond the model run.
    origin = next((timestamp for timestamp, _ in values if timestamp is not None), None)
    duration_limit = forcing.get("simulation_window_minutes") or forcing.get("duration_minutes")
    try:
        duration_limit_f = max(0.0, float(duration_limit)) if duration_limit is not None else None
    except (TypeError, ValueError):
        duration_limit_f = None
    timed_values: list[tuple[float, float]] = []
    if origin is not None:
        for timestamp, value in values:
            if timestamp is None:
                continue
            elapsed = (timestamp - origin).total_seconds() / 60.0
            if elapsed < -1e-6 or (duration_limit_f is not None and elapsed > duration_limit_f + 1e-6):
                continue
            timed_values.append((max(0.0, elapsed), value))
    if not timed_values:
        step = float(forcing.get("native_interval_minutes") or 5.0)
        timed_values = [(i * step, value) for i, (_, value) in enumerate(values)]
        if duration_limit_f is not None:
            timed_values = [item for item in timed_values if item[0] <= duration_limit_f + 1e-6]
    # Keep the SVG small while retaining the storm shape.  Preserve the first
    # and last samples so the displayed window always matches the run.
    stride = max(1, math.ceil(len(timed_values) / 180))
    sampled = timed_values[::stride]
    if timed_values and sampled[-1] != timed_values[-1]:
        sampled.append(timed_values[-1])
    return [{"time_minutes": float(time), "intensity_mm_h": float(value)} for time, value in sampled]


def _surface_evolution_series(root: Path, manifest: dict[str, Any], domain: dict[str, Any]) -> list[dict[str, float]]:
    """Derive per-frame maximum depth and inundated area for the report chart."""
    cell_area = float(domain.get("cell_size_m") or 250.0) ** 2
    result: list[dict[str, float]] = []
    for item in manifest.get("snapshots") or []:
        try:
            path = root / _safe_relative_path(item.get("path"), "historical_replay_snapshot_path_invalid")
            payload = _feature_collection(path, "historical_replay_snapshot_invalid")
        except ValueError:
            continue
        depths = [_numeric_depth((feature.get("properties") or {}).get("depth_m")) for feature in payload.get("features", []) if isinstance(feature, dict)]
        result.append({
            "time_minutes": float(item.get("time_minutes", item.get("time_seconds", 0.0) / 60.0)),
            "maximum_depth_m": max(depths, default=0.0),
            "inundated_area_ge_0_01m2": sum(1 for depth in depths if depth >= 0.01) * cell_area,
            "inundated_area_ge_0_05m2": sum(1 for depth in depths if depth >= 0.05) * cell_area,
        })
    return result


def _numeric_depth(value: Any) -> float:
    try:
        depth = float(value)
    except (TypeError, ValueError):
        return 0.0
    return depth if math.isfinite(depth) and depth > 0 else 0.0


def _first_ring(geometry: Any) -> list[list[float]]:
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return []
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon" and coordinates and isinstance(coordinates[0], list):
        return [point for point in coordinates[0] if isinstance(point, list) and len(point) >= 2]
    if geometry_type == "MultiPolygon" and coordinates and isinstance(coordinates[0], list):
        polygon = coordinates[0]
        if polygon and isinstance(polygon[0], list):
            return [point for point in polygon[0] if isinstance(point, list) and len(point) >= 2]
    return []


def _overview_map_svg(maximum_depth: dict[str, Any], labels: dict[str, str] | None = None) -> str:
    """Render a compact, derived SVG overview without returning source geometry.

    The full maximum-depth GeoJSON remains in the machine-readable package.
    Sampling keeps the report responsive even for a city-wide mesh.
    """

    labels = labels or {
        "no_data": "No maximum-depth features are available.",
        "aria": "Maximum surface-water depth map",
        "lower": "Lower depth",
        "higher": "Higher depth",
        "legend_title": "Depth (m)",
        "legend_ranges": "<0.01|0.01–0.05|0.05–0.10|0.10–0.20|0.20–0.50|0.50–1.00|≥1.00",
        "cells": "cells",
        "north": "N",
        "scale": "10 km",
        "wet": "Inundated cells",
        "peak": "Maximum",
        "grid": "250 m grid",
        "depth_unit": "m",
    }
    sampled: list[tuple[list[list[float]], float]] = []
    features = maximum_depth.get("features") if isinstance(maximum_depth, dict) else []
    if not isinstance(features, list) or not features:
        return f"<p class='empty-chart'>{escape(labels['no_data'])}</p>"
    # Render the complete 250 m mesh for this report-sized asset whenever it
    # is reasonably small.  The previous 1,800-feature stride produced a
    # dotted/diagonal pattern that looked like missing flood coverage.  A
    # very large future mesh is still bounded to keep the standalone report
    # responsive.
    stride = max(1, math.ceil(len(features) / 20000))
    for feature in features[::stride]:
        if not isinstance(feature, dict):
            continue
        ring = _first_ring(feature.get("geometry"))
        if len(ring) < 3:
            continue
        points: list[list[float]] = []
        for point in ring:
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append([x, y])
        if len(points) >= 3:
            depth = _numeric_depth((feature.get("properties") or {}).get("depth_m"))
            sampled.append((points, depth))
    if not sampled:
        return f"<p class='empty-chart'>{escape(labels['no_data'])}</p>"
    xs = [point[0] for ring, _ in sampled for point in ring]
    ys = [point[1] for ring, _ in sampled for point in ring]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    max_depth = max(depth for _, depth in sampled) or 1.0
    wet_count = sum(1 for _, depth in sampled if depth >= 0.01)

    # Keep the first swatch neutral: the maximum-depth asset is a wet-cell
    # union, so empty areas in the figure are either dry/not exported or
    # permanent water.  A neutral swatch makes that coverage boundary clear.
    palette = ["#edf2f4", "#b8e2f0", "#73c5df", "#3d99cf", "#ffb45c", "#ef7054", "#c6283d"]
    thresholds = [0.01, 0.05, 0.10, 0.20, 0.50, 1.00]

    def color(depth: float) -> str:
        for index, threshold in enumerate(thresholds):
            if depth < threshold:
                return palette[index]
        return palette[-1]

    paths: list[str] = []
    plot_left, plot_top, plot_size = 84, 116, 816
    for ring, depth in sampled:
        commands = []
        for index, point in enumerate(ring):
            x = plot_left + (point[0] - min_x) / span_x * plot_size
            y = plot_top + plot_size - (point[1] - min_y) / span_y * plot_size
            commands.append(("M" if index == 0 else "L") + f"{x:.2f},{y:.2f}")
        paths.append(f"<path d='{''.join(commands)}Z' fill='{color(depth)}' fill-opacity='0.82' stroke='#7c9cac' stroke-width='0.28' />")
    legend_ranges = [item.strip() for item in str(labels.get("legend_ranges", "")).split("|") if item.strip()]
    legend = [
        "<g aria-label='depth legend'>",
        f"<rect x='930' y='116' width='174' height='350' rx='8' fill='#ffffff' fill-opacity='.96' stroke='#b9ccd6' />",
        f"<text x='946' y='146' font-size='18' font-weight='700' fill='#18324a'>{escape(str(labels.get('legend_title', 'Depth (m)')))}</text>",
    ]
    for index, item in enumerate(legend_ranges[: len(palette)]):
        y = 176 + index * 30
        legend.append(f"<rect x='950' y='{y - 14}' width='17' height='17' rx='2' fill='{palette[index]}' stroke='#7c9cac' stroke-width='.3' /><text x='976' y='{y}' font-size='15' fill='#18324a'>{escape(item)}</text>")
    legend.extend([
        f"<text x='946' y='430' font-size='13' fill='#587083'>{escape(str(labels.get('coverage', 'Wet-cell result coverage')))}</text>",
        "</g>",
        "<g aria-label='north arrow'><line x1='1018' y1='540' x2='1018' y2='490' stroke='#18324a' stroke-width='3'/><path d='M1018 478 L1009 495 L1027 495 Z' fill='#18324a'/><text x='1010' y='566' font-size='18' font-weight='700' fill='#18324a'>" + escape(str(labels.get("north", "N"))) + "</text></g>",
        "<g aria-label='scale bar'><line x1='660' y1='962' x2='870' y2='962' stroke='#18324a' stroke-width='5'/><line x1='660' y1='955' x2='660' y2='969' stroke='#18324a' stroke-width='3'/><line x1='870' y1='955' x2='870' y2='969' stroke='#18324a' stroke-width='3'/><text x='748' y='992' font-size='17' fill='#18324a'>" + escape(str(labels.get("scale", "10 km"))) + "</text></g>",
    ])
    # A small information band makes the spatial graphic self-explanatory in
    # a printed report: what is coloured, the peak value, and the mesh size.
    info = (
        f"<rect x='84' y='48' width='816' height='48' rx='7' fill='#ffffff' fill-opacity='.96' stroke='#b9ccd6' />"
        f"<text x='102' y='79' font-size='17' font-weight='700' fill='#18324a'>{escape(str(labels.get('wet', 'Inundated cells')))}: {wet_count:,} / {escape(str(labels.get('land_cells', 'land cells')))}: {escape(str(labels.get('land_cells_count', '—')))}"
        f"  ·  {escape(str(labels.get('peak', 'Maximum')))}: {max_depth:.2f} {escape(str(labels.get('depth_unit', 'm')))}  ·  {escape(str(labels.get('grid', '250 m grid')))}</text>"
    )
    # Add a light frame and coordinate-like ticks.  These are deliberately
    # derived from the result extent (no external basemap is required), so a
    # customer can still orient the figure when it is copied out of the app.
    frame = f"<rect x='{plot_left - 2}' y='{plot_top - 2}' width='{plot_size + 4}' height='{plot_size + 4}' fill='none' stroke='#7893a3' stroke-width='1.3'/>"
    ticks = []
    for fraction in (0.0, 0.5, 1.0):
        tx = plot_left + plot_size * fraction
        ty = plot_top + plot_size - plot_size * fraction
        lon = min_x + span_x * fraction
        lat = min_y + span_y * fraction
        ticks.append(f"<text x='{tx:.1f}' y='986' text-anchor='middle' font-size='13' fill='#587083'>{lon:.3f}°E</text>")
        ticks.append(f"<text x='64' y='{ty + 5:.1f}' text-anchor='end' font-size='13' fill='#587083'>{lat:.3f}°N</text>")
    return "".join([
        f"<svg class='depth-map' viewBox='0 0 1120 1040' role='img' aria-label='{escape(labels['aria'])}'>",
        "<rect width='1120' height='1040' fill='#eff6ff' />",
        info,
        frame,
        *paths,
        *ticks,
        *legend,
        f"<text x='84' y='32' font-size='17' fill='#486276'>{escape(labels['lower'])}</text><text x='760' y='32' font-size='17' fill='#486276'>{escape(labels['higher'])}</text>",
        f"<text x='84' y='1022' font-size='13' fill='#587083'>{escape(str(labels.get('blank', 'Blank = dry / permanent water / not in maximum-depth asset')))}</text>",
        "</svg>",
    ])


def _rainfall_svg(series: list[dict[str, float]], labels: dict[str, str]) -> str:
    if not series:
        return f"<p class='empty-chart'>{escape(labels['no_data'])}</p>"
    peak = max((float(item.get("intensity_mm_h") or 0.0) for item in series), default=0.0)
    scale_peak = peak or 1.0
    width, height, left, right, top, bottom = 1000, 380, 70, 28, 56, 60
    end = float(series[-1].get("time_minutes") or 0.0)
    interval_minutes = max(0.0, (float(series[-1].get("time_minutes") or 0.0) - float(series[-2].get("time_minutes") or 0.0)) if len(series) > 1 else 0.0)
    # Integrate the displayed forcing with the trapezoidal rule.  This keeps
    # the cumulative value consistent with irregular time steps and avoids
    # overstating rainfall when a long series has been down-sampled.
    total_mm = 0.0
    for previous, current in zip(series, series[1:]):
        previous_time = float(previous.get("time_minutes") or 0.0)
        current_time = float(current.get("time_minutes") or 0.0)
        delta_minutes = max(0.0, current_time - previous_time)
        previous_intensity = max(0.0, float(previous.get("intensity_mm_h") or 0.0))
        current_intensity = max(0.0, float(current.get("intensity_mm_h") or 0.0))
        total_mm += (previous_intensity + current_intensity) * 0.5 * delta_minutes / 60.0
    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + (width - left - right) * index / max(len(series) - 1, 1)
        y = height - bottom - (height - top - bottom) * max(0.0, value) / scale_peak
        return x, y
    line_points = [xy(i, float(item.get("intensity_mm_h") or 0.0)) for i, item in enumerate(series)]
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in line_points)
    area = f"{left},{height-bottom} " + points + f" {width-right},{height-bottom}"
    # Keep the chart readable at a glance: five vertical time guides, three
    # horizontal intensity guides, a filled storm profile and a labelled peak.
    guides: list[str] = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = left + (width-left-right) * fraction
        value = end * fraction
        guides.append(f"<line x1='{x:.2f}' y1='{top}' x2='{x:.2f}' y2='{height-bottom}' stroke='#d7e5eb' stroke-width='1'/><text x='{x:.2f}' y='{height-20}' text-anchor='middle' font-size='15' fill='#587083'>{value:.0f} {escape(labels.get('time_unit', 'min'))}</text>")
    for fraction in (0.0, 0.5, 1.0):
        y = height - bottom - (height-top-bottom) * fraction
        value = scale_peak * fraction
        guides.append(f"<line x1='{left}' y1='{y:.2f}' x2='{width-right}' y2='{y:.2f}' stroke='#d7e5eb' stroke-width='1'/><text x='{left-10}' y='{y+5:.2f}' text-anchor='end' font-size='15' fill='#587083'>{value:.1f}</text>")
    peak_index = max(range(len(series)), key=lambda i: float(series[i].get("intensity_mm_h") or 0.0))
    peak_x, peak_y = line_points[peak_index]
    time_unit = escape(labels.get("time_unit", "min"))
    intensity_unit = escape(labels.get("intensity_unit", "mm/h"))
    return "".join([
        f"<svg class='rainfall-chart' viewBox='0 0 {width} {height}' role='img' aria-label='{escape(labels['aria'])}'>",
        f"<text x='{left}' y='25' font-size='18' font-weight='700' fill='#18324a'>{escape(labels.get('peak', 'Peak'))}: {peak:.2f} {intensity_unit}  ·  {escape(labels.get('total', 'Total'))}: {total_mm:.1f} {escape(labels.get('depth_unit', 'mm'))}</text>",
        *guides,
        f"<polygon points='{area}' fill='#168aad' fill-opacity='.16' stroke='none'/>",
        f"<polyline points='{points}' fill='none' stroke='#0b7898' stroke-width='4' stroke-linejoin='round' stroke-linecap='round'/>",
        f"<line x1='{peak_x:.2f}' y1='{top}' x2='{peak_x:.2f}' y2='{height-bottom}' stroke='#dc4c3f' stroke-width='2' stroke-dasharray='6 5'/>",
        f"<circle cx='{peak_x:.2f}' cy='{peak_y:.2f}' r='6' fill='#dc4c3f'><title>{float(series[peak_index].get('time_minutes') or 0):.0f} {time_unit}: {peak:.2f} {intensity_unit}</title></circle>",
        f"<text x='{peak_x+9:.2f}' y='{max(top+24, peak_y-10):.2f}' font-size='15' font-weight='700' fill='#b42318'>{peak:.2f} {intensity_unit}</text>",
        f"<line x1='{left}' y1='{height-bottom}' x2='{width-right}' y2='{height-bottom}' stroke='#6c8295' stroke-width='2'/><line x1='{left}' y1='{top}' x2='{left}' y2='{height-bottom}' stroke='#6c8295' stroke-width='2'/>",
        f"<text x='{left+(width-left-right)/2:.0f}' y='{height-2}' text-anchor='middle' font-size='15' fill='#486276'>{escape(labels.get('axis_x_unit', 'Time (min)'))}</text>",
        f"<text x='12' y='{(top+height-bottom)/2:.0f}' transform='rotate(-90 12 {(top+height-bottom)/2:.0f})' text-anchor='middle' font-size='15' fill='#486276'>{escape(labels.get('axis_y_unit', 'Intensity (mm/h)'))}</text>",
        "</svg>",
    ])


def _evolution_svg(series: list[dict[str, float]], labels: dict[str, str]) -> str:
    if not series:
        return f"<p class='empty-chart'>{escape(labels['no_data'])}</p>"
    width, height, left, right, top, bottom = 1000, 440, 72, 28, 42, 48
    max_depth = max(float(item.get("maximum_depth_m") or 0.0) for item in series) or 1.0
    max_area_km2 = max(float(item.get("inundated_area_ge_0_01m2") or 0.0) for item in series) / 1_000_000 or 1.0
    end = float(series[-1].get("time_minutes") or 0.0)
    upper_top, upper_bottom = top + 18, 195
    lower_top, lower_bottom = 252, height - bottom
    def points(field: str, maximum: float, y0: float, y1: float, divisor: float = 1.0) -> str:
        coords = []
        for i, item in enumerate(series):
            x = left + (width-left-right) * i / max(len(series)-1, 1)
            value = float(item.get(field) or 0.0) / divisor
            y = y1 - (y1-y0) * value / maximum
            coords.append(f"{x:.2f},{y:.2f}")
        return " ".join(coords)
    depth_points = points("maximum_depth_m", max_depth, upper_top, upper_bottom)
    area_points = points("inundated_area_ge_0_01m2", max_area_km2, lower_top, lower_bottom, 1_000_000)
    guides: list[str] = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = left + (width-left-right) * fraction
        value = end * fraction
        guides.append(f"<line x1='{x:.2f}' y1='{upper_top}' x2='{x:.2f}' y2='{lower_bottom}' stroke='#e0e9ee' stroke-width='1'/><text x='{x:.2f}' y='{height-12}' text-anchor='middle' font-size='14' fill='#587083'>{value:.0f}</text>")
    for y0, y1, maximum, color, unit in ((upper_top, upper_bottom, max_depth, '#dc4c3f', labels.get('depth_unit', 'm')), (lower_top, lower_bottom, max_area_km2, '#2364aa', labels.get('area_unit', 'km²'))):
        for fraction in (0.0, 0.5, 1.0):
            y = y1 - (y1-y0) * fraction
            guides.append(f"<line x1='{left}' y1='{y:.2f}' x2='{width-right}' y2='{y:.2f}' stroke='#e0e9ee' stroke-width='1'/><text x='{left-10}' y='{y+5:.2f}' text-anchor='end' font-size='14' fill='{color}'>{maximum*fraction:.2f}</text>")
    return "".join([
        f"<svg class='evolution-chart' viewBox='0 0 {width} {height}' role='img' aria-label='{escape(labels['aria'])}'>",
        f"<text x='{left}' y='22' font-size='18' font-weight='700' fill='#dc4c3f'>● {escape(labels['depth'])} ({escape(str(labels.get('depth_unit', 'm')))}) · 0–{max_depth:.2f}</text>",
        f"<text x='{left}' y='232' font-size='18' font-weight='700' fill='#2364aa'>● {escape(labels['area'])} ({escape(str(labels.get('area_unit', 'km²')))}) · 0–{max_area_km2:,.2f}</text>",
        *guides,
        f"<polyline points='{depth_points}' fill='none' stroke='#dc4c3f' stroke-width='4' stroke-linejoin='round' stroke-linecap='round'/>",
        f"<polyline points='{area_points}' fill='none' stroke='#2364aa' stroke-width='4' stroke-linejoin='round' stroke-linecap='round'/>",
        f"<text x='{left+(width-left-right)/2:.0f}' y='{height-1}' text-anchor='middle' font-size='14' fill='#486276'>{escape(labels.get('axis_x_unit', 'Time (min)'))}</text>",
        "</svg>",
    ])


def _timeline_svg(timeline: dict[str, Any], labels: dict[str, str]) -> str:
    values = timeline.get("elapsed_minutes") if isinstance(timeline, dict) else []
    if not isinstance(values, list) or not values:
        return f"<p class='empty-chart'>{escape(labels['no_data'])}</p>"
    count = len(values)
    ticks = []
    for index, value in enumerate(values):
        x = 50 + (900 * index / max(count - 1, 1))
        ticks.append(f"<circle cx='{x:.2f}' cy='115' r='5' fill='#0f87a8'><title>{float(value):.0f} {escape(labels.get('time_unit', 'min'))}</title></circle>")
    start, end = float(values[0]), float(values[-1])
    time_unit = escape(labels.get("time_unit", "min"))
    return "".join([
        f"<svg class='timeline-chart' viewBox='0 0 1000 230' role='img' aria-label='{escape(labels['aria'])}'>",
        "<line x1='50' y1='115' x2='950' y2='115' stroke='#6c8295' stroke-width='2' />",
        *ticks,
        f"<text x='50' y='210' font-size='22' fill='#18324a'>{start:.0f} {time_unit}</text>",
        f"<text x='870' y='210' font-size='22' fill='#18324a'>{end:.0f} {time_unit}</text>",
        f"<text x='50' y='68' font-size='20' fill='#486276'>{count} {escape(labels['frames'])}</text>",
        f"<text x='50' y='92' font-size='15' fill='#587083'>{escape(labels.get('point_note', 'Each dot is one output frame'))}</text></svg>",
    ])


def historical_replay_report_html(language: str | None = None) -> str:
    """Render a standalone phase-5 report in one language (browser locale)."""

    # Direct callers (including the report unit tests) retain the historical
    # English default; authenticated API calls pass the middleware locale.
    lang = (language or "en").lower()
    zh = lang.startswith("zh")
    text = {
        "title": "阿布扎比城市暴雨内涝世界模型 · 阶段5交付报告" if zh else "Abu Dhabi Urban Pluvial Flood World Model - Phase 5 Delivery Report",
        "eyebrow": "城市暴雨内涝世界模型 / 阶段5" if zh else "URBAN PLUVIAL FLOOD WORLD MODEL / PHASE 5",
        "heading": "2024年4月历史暴雨重演与交付报告" if zh else "2024 April Historical Replay and Delivery Report",
        "sub": "展示排水管网水动力、二维地表积水、快速世界模型推演及验证门的可追溯交付结果。" if zh else "A traceable delivery view of drainage-network hydraulics, 2D surface-water simulation, GWM scenario screening and validation gates.",
        "run": "运行编号（机器标识）" if zh else "Run ID (machine identifier)",
        "solver": "求解器" if zh else "Solver",
        "status_label": "交付状态" if zh else "Delivery status",
        "status": "结果资产及一维→二维体积对账已生成，可用于查看和播放。" if zh else "Result assets and SWMM-to-ANUGA volume reconciliation are available.",
        "summary": "结果摘要" if zh else "Executive result summary",
        "duration": "模拟时长" if zh else "Simulation duration",
        "frames": "输出时间片" if zh else "Output frames",
        "cells": "二维陆域单元" if zh else "Active 2D land cells",
        "max_depth": "最大积水深度" if zh else "Maximum depth",
        "volume_error": "交换体积误差" if zh else "Exchange volume error",
        "hours": "小时" if zh else "hours", "slices": "帧" if zh else "time slices", "cells_unit": "个" if zh else "cells", "depth_unit": "米" if zh else "m",
        "chain": "五阶段模型链路" if zh else "Five-stage model delivery chain",
        "visuals": "结果图件" if zh else "Result visuals",
        "map_title": "最大积水深度空间分布（阿布扎比全市陆域范围）— 有积水网格结果" if zh else "Maximum surface-water depth (citywide land grid) — wet-cell result",
        "map_desc": "彩色单元是约 250 米网格，不是采样点；颜色越深表示该网格的最大积水越深。图中显示本次结果包写出的有积水网格，空白区域表示无积水、永久水体或未写入最大深度资产，不应解读为缺测。坐标、北箭头和比例尺用于定位，完整空间数据文件保存在结果包中。" if zh else "Coloured cells are approximately 250 m grid cells, not sample points; darker colours indicate greater maximum depth. The figure shows wet cells written to this result package. Blank areas represent dry cells, permanent water or cells omitted from the maximum-depth asset, and must not be read as missing data. Coordinates, north arrow and scale bar provide orientation; the complete spatial file remains in the result package.",
        "rain_title": "降雨过程（模型输入）" if zh else "Rainfall process (model input)",
        "rain_desc": "横轴为模拟时间，纵轴为雨强；红色标线和圆点标出峰值，顶部同时给出峰值与累计雨量。" if zh else "The x-axis is model time and the y-axis is rainfall intensity. The red marker identifies the peak; peak and cumulative rainfall are shown above the chart.",
        "evo_title": "积水演变（二维输出）" if zh else "Flood evolution (2D output)",
        "evo_desc": "红线表示全市网格中的最大积水深度，蓝线表示积水面积（深度不小于 0.01 米）；两条曲线共用同一时间轴。" if zh else "The red line is the maximum depth across the citywide grid; the blue line is inundated area (depth ≥ 0.01 m). Both curves use the same time axis.",
        "axis_title": "时间轴" if zh else "Replay time axis",
        "axis_desc": "" if zh else "",
        "validation": "验证与准入状态" if zh else "Validation and admission status",
        "quality": "SWMM 严格数值质量门" if zh else "SWMM strict numerical quality gate",
        "failed": "失败检查" if zh else "Failed check",
        "assets": "机器可读交付资产" if zh else "Machine-readable delivery assets",
        "boundary": "结果解释边界" if zh else "Interpretation boundary",
        "supports": "本报告支持查看 2024 年重演结果、二维积水演变和一二维体积对账。" if zh else "This report supports inspection of the 2024 replay, 2D evolution and 1D–2D volume accounting.",
        "next": "后续证据：完成 SWMM 数值质量复核、观测对比、独立二维复核及影响叠加准入。" if zh else "Next: resolve the SWMM quality receipt, compare observations, perform an independent 2D cross-check and complete impact admission.",
        "no_data": "暂无可用数据" if zh else "No data available",
        "lower": "较浅" if zh else "Lower depth", "higher": "较深" if zh else "Higher depth",
        "rain_aria": "降雨强度随时间变化图" if zh else "Rainfall intensity over time",
        "evo_aria": "最大积水深度和积水面积随时间变化图" if zh else "Maximum depth and inundated area over time",
        "axis_aria": "历史重演时间轴" if zh else "Historical replay time axis",
    }
    # Avoid interpolating a placeholder into user-visible copy.
    report = historical_replay_report_payload()
    validation, quality = report["validation"], report["validation"]["swmm_quality"]
    results, domain, timeline, coupling = report["results"], report["domain"], report["timeline"], report["coupling"]
    duration, cells = _numeric_depth(domain.get("simulation_duration_hours")), int(domain.get("active_land_cells") or 0)
    frames = int(timeline.get("period_count") or 0)
    error_pct = _numeric_depth(coupling.get("relative_volume_error")) * 100
    text["axis_desc"] = (f"{frames:,} 个时间片，间隔 {float(timeline.get('step_minutes') or 0):.0f} 分钟。" if zh else f"{frames:,} output frames at {float(timeline.get('step_minutes') or 0):.0f}-minute intervals.")
    quality_label = "未通过" if zh and quality.get("status") == "failed" else "待定" if zh else ("NOT PASSED" if quality.get("status") == "failed" else "PENDING" if quality.get("status") != "passed" else "PASSED")
    quality_class = "fail" if quality.get("status") == "failed" else "pending" if quality.get("status") != "passed" else "pass"
    def metric(label: str, value: str, unit: str = "") -> str:
        return f"<article class='metric'><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(unit)}</small></article>"
    phase_names_zh = ["数据与准入", "一维排水水动力", "二维地表水动力", "世界模型快速推演", "验证与交付"]
    phase_names_en = ["Data and admission", "1D drainage hydraulics", "2D surface hydraulics", "GWM rapid rollout", "Validation and delivery"]
    phase_purpose_zh = ["建立可追溯的排水、地形、降雨、边界和观测数据输入契约。", "使用美国环保署 SWMM 模型计算降雨产流、节点溢流和管网水力过程。", "使用 ANUGA 二维模型在地形表面传播交换的排水体积。", "学习已批准的物理模型状态，用于快速筛查干预方案并给出不确定性信号。", "重演独立事件，汇总结果包并展示准入证据。"]
    phase_purpose_en = ["Build a traceable input contract from drainage, terrain, rainfall, boundary and observation data.", "Use EPA SWMM to calculate rainfall-runoff, node surcharge and pipe-network hydraulics.", "Use ANUGA 2D to route exchanged drainage volume across the terrain surface.", "Learn approved physical-model states to screen interventions with uncertainty gating.", "Replay an independent event, assemble the result package and show admission evidence."]
    phase_output_zh = ["数据源登记、字段映射、问题清单和接收检查。", "排水模型报告与结果文件（RPT/OUT）、节点和管段时间序列及数值质量回执。", "最大积水深度、动态深度和一维→二维体积对账。", "快速场景对比、不确定性和物理模型回退信号。", "本报告、地图/时间序列资产、验证门和下一步证据要求。"]
    phase_output_en = ["Source register, field mapping, issue list and receipt checks.", "Native SWMM RPT/OUT, node/pipe time series and numerical quality receipt.", "Maximum depth, time-varying depth and SWMM-to-2D volume reconciliation.", "Rapid scenario comparison, uncertainty and physical-model fallback signal.", "This report, map/time-series assets, gates and next evidence requirements."]
    names, purposes, outputs = (phase_names_zh, phase_purpose_zh, phase_output_zh) if zh else (phase_names_en, phase_purpose_en, phase_output_en)
    phase_cards = "".join(f"<article class='phase {escape(str(item['status']))}'><span>{escape(str(item['number']))}</span><h3>{escape(names[i])}</h3><p>{escape(purposes[i])}</p><small>{escape(outputs[i])}</small></article>" for i, item in enumerate(report["phases"]))
    gate_labels_zh = {"artifact_completeness": "结果资产与时间片完整", "coupling_reconciliation": "一维→二维体积交换对账", "swmm_numerical_quality": "SWMM 严格数值质量门", "observation_comparison": "积水深度、范围和退水观测对比", "independent_2d_crosscheck": "独立二维复核", "impact_overlay_admission": "道路、设施和人口影响叠加准入"}
    gate_labels_en = {"artifact_completeness": "Result assets and timeline completeness", "coupling_reconciliation": "SWMM-to-2D volume reconciliation", "swmm_numerical_quality": "SWMM strict numerical quality", "observation_comparison": "Observed depth, extent and recession comparison", "independent_2d_crosscheck": "Independent 2D cross-check", "impact_overlay_admission": "Road, facility and population impact admission"}
    status_labels_zh = {"passed": "通过", "failed": "失败", "pending": "待定", "warning": "警告"}
    gate_rows = "".join(f"<tr><td>{escape((gate_labels_zh if zh else gate_labels_en).get(str(gate.get('gate_id')), str(gate.get('gate_id', 'Gate'))))}</td><td class='{escape(str(gate.get('status', 'pending')))}'>{escape((status_labels_zh if zh else {}).get(str(gate.get('status', 'pending')), str(gate.get('status', 'pending')).upper()))}</td></tr>" for gate in validation["gates"])
    kind_labels_zh = {"maximum_depth": "最大积水深度图层", "timeline_manifest": "时间轴清单", "native_2d_result": "二维原生结果", "native_sww": "二维原生结果文件", "declared_output": "模型输出"}
    kind_labels_en = {"maximum_depth": "Maximum depth layer", "timeline_manifest": "Timeline manifest", "native_2d_result": "Native 2D result", "native_sww": "Native 2D result file", "declared_output": "Model output"}
    kind_labels = kind_labels_zh if zh else kind_labels_en
    assets = "".join(f"<li><strong>{escape(str(asset.get('asset', 'asset')))}</strong><span>{escape(kind_labels.get(str(asset.get('kind')), str(asset.get('kind', 'result')).replace('_', ' ')))}</span></li>" for asset in report["delivery_assets"] if asset.get("exists"))
    failed_checks = quality.get("failed_checks") if isinstance(quality.get("failed_checks"), list) else []
    quality_check_labels_zh = {
        "nonconverging_steps_within_threshold": "不收敛步数超过阈值",
        "report_contains_no_swmm_errors": "报告不含 SWMM 错误",
    }
    failure_detail = ", ".join((quality_check_labels_zh.get(str(item), str(item)) if zh else str(item)) for item in failed_checks) or ("可用回执中未声明失败检查。" if zh else "No failed SWMM check is declared in the available receipt.")
    map_labels = {
        "no_data": text["no_data"],
        "aria": "最大积水深度空间分布图" if zh else "Maximum surface-water depth map",
        "lower": text["lower"],
        "higher": text["higher"],
        "legend_title": "积水深度（米）" if zh else "Depth (m)",
        "legend_ranges": "无积水/未写入|0.01–0.05|0.05–0.10|0.10–0.20|0.20–0.50|0.50–1.00|≥1.00" if zh else "No inundation / not written|0.01–0.05|0.05–0.10|0.10–0.20|0.20–0.50|0.50–1.00|≥1.00",
        "cells": "个单元" if zh else "cells",
        "land_cells": "陆域网格" if zh else "land cells",
        "land_cells_count": f"{cells:,}",
        "coverage": "彩色网格为积水结果；空白=无积水/永久水体/未写入" if zh else "Colour = wet result; blank = dry / permanent water / not written",
        "blank": "空白 = 无积水、永久水体或未写入最大深度资产" if zh else "Blank = dry, permanent water or not in maximum-depth asset",
        "north": "北" if zh else "N",
        "scale": "10 千米" if zh else "10 km",
        "wet": "积水单元" if zh else "Inundated cells",
        "peak": "最大深度" if zh else "Maximum",
        "grid": "250 米网格" if zh else "250 m grid",
        "depth_unit": "米" if zh else "m",
    }
    rain_labels = {
        "no_data": text["no_data"], "aria": text["rain_aria"],
        "time_unit": "分钟" if zh else "min", "axis_y": "雨强" if zh else "Intensity", "axis_x": "时间" if zh else "Time",
        "axis_x_unit": "时间（分钟）" if zh else "Time (min)",
        "axis_y_unit": "雨强（毫米/小时）" if zh else "Intensity (mm/h)",
        "intensity_unit": "毫米/小时" if zh else "mm/h", "depth_unit": "毫米" if zh else "mm",
        "peak": "峰值" if zh else "Peak", "total": "累计" if zh else "Total",
    }
    evo_labels = {
        "no_data": text["no_data"], "aria": text["evo_aria"],
        "depth": "最大深度" if zh else "Max depth", "area": "积水面积" if zh else "Inundated area",
        "depth_unit": "米" if zh else "m", "area_unit": "平方千米" if zh else "km²",
        "time_unit": "分钟" if zh else "min", "axis_x_unit": "时间（分钟）" if zh else "Time (min)",
    }
    boundary_text = "客户 5 米数字地形模型（DTM）城市级数值验证；高程基准、潮位边界、城市微地形、下渗参数和观测数据仍需校准。" if zh else str(report["claim_boundary"])
    solver_display = "美国环保署 SWMM 5.2.4（排水管网一维水动力） + ANUGA 二维模型（地表二维水动力）" if zh else str(report["solver"])
    footer_label = "GIS 数据代理 · 阶段5交付报告" if zh else "GIS Data Agent · Phase 5 Delivery Report"
    return f"""<!doctype html><html lang='{'zh-CN' if zh else 'en'}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{escape(text['title'])}</title><style>
@page{{size:A4;margin:12mm}}*{{box-sizing:border-box}}body{{margin:0;color:#18324a;font:14px/1.55 Arial,'PingFang SC','Microsoft YaHei',sans-serif;background:#eef4f7}}main{{width:min(1180px,100%);margin:auto;background:#fff;padding:42px}}h1,h2,h3,p{{margin-top:0}}h1{{font-size:31px;line-height:1.16;margin-bottom:10px}}h2{{margin:34px 0 14px;font-size:21px}}h3{{font-size:15px;margin:8px 0}}.eyebrow{{color:#147b9b;font-weight:700;letter-spacing:.08em;font-size:11px}}.hero{{border-bottom:5px solid #0f87a8;padding-bottom:22px}}.sub{{max-width:900px;color:#486276}}.run{{font-family:monospace;color:#486276;font-size:12px}}.notice{{margin:20px 0;border-left:5px solid #ca8a04;background:#fffbeb;padding:14px 16px}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.metric{{border:1px solid #d9e4ea;padding:12px;min-height:91px}}.metric span,.metric small{{display:block;color:#587083;font-size:12px}}.metric strong{{display:inline-block;color:#0a5470;font-size:25px;margin:3px 4px 0 0}}.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}.phase{{border:1px solid #ccdce5;padding:13px;min-height:198px}}.phase>span{{color:#0f87a8;font-weight:700}}.phase small{{color:#486276}}.phase.complete{{border-top:5px solid #15803d}}.phase.partial,.phase.prototype{{border-top:5px solid #ca8a04}}.phase.quality_gate_failed{{border-top:5px solid #dc2626}}.visuals{{display:grid;grid-template-columns:1fr;gap:18px}}.chart{{border:1px solid #d9e4ea;padding:14px;background:#fcfeff}}.chart p{{color:#587083;font-size:13px;max-width:980px}}.chart:nth-child(1){{min-height:620px}}.chart:nth-child(n+2){{min-height:300px}}.depth-map,.timeline-chart,.rainfall-chart,.evolution-chart{{display:block;width:100%;height:auto;background:#f8fbfd}}.quality{{border:1px solid #d9e4ea;padding:16px}}.quality strong{{display:inline-block;padding:3px 7px;border-radius:3px;font-size:12px}}.quality .fail{{background:#fee2e2;color:#991b1b}}.quality .pass{{background:#dcfce7;color:#166534}}.quality .pending{{background:#fef3c7;color:#92400e}}table{{width:100%;border-collapse:collapse}}td{{padding:9px;border-bottom:1px solid #d9e4ea}}td:last-child{{text-align:right;font-weight:700}}td.passed{{color:#15803d}}td.failed{{color:#b91c1c}}td.pending,td.warning{{color:#a16207}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.asset-list{{list-style:none;padding:0;margin:0;columns:2}}.asset-list li{{break-inside:avoid;padding:8px 0;border-bottom:1px solid #e4edf1}}.asset-list span{{display:block;color:#587083;font-size:12px}}.boundary{{border:1px solid #f1c7c7;background:#fff8f8;padding:14px}}.boundary strong{{color:#991b1b}}.footer{{margin-top:34px;padding-top:15px;border-top:1px solid #ccdce5;color:#587083;font-size:12px}}@media(max-width:800px){{main{{padding:22px}}.metrics,.flow,.split{{grid-template-columns:1fr}}.asset-list{{columns:1}}}}@media print{{body{{background:#fff}}main{{width:100%;padding:0}}.phase,.metric,.chart,.quality,.boundary{{break-inside:avoid}}}}</style></head><body><main>
<section class='hero'><div class='eyebrow'>{escape(text['eyebrow'])}</div><h1>{escape(text['heading'])}</h1><p class='sub'>{escape(text['sub'])}</p><div class='run'>{escape(text['run'])}: <bdi dir='ltr'>{escape(str(report['run_id']))}</bdi> &nbsp; | &nbsp; {escape(text['solver'])}: {escape(solver_display)}</div></section>
<div class='notice'><strong>{escape(text['status_label'])}{'：' if zh else ':'}</strong> {escape(text['status'])}</div><h2>{escape(text['summary'])}</h2><section class='metrics'>{metric(text['duration'],f'{duration:.0f}',text['hours'])}{metric(text['frames'],f'{frames:,}',text['slices'])}{metric(text['cells'],f'{cells:,}',text['cells_unit'])}{metric(text['max_depth'],f"{_numeric_depth(results.get('maximum_depth_m')):.2f}",text['depth_unit'])}{metric(text['volume_error'],f'{error_pct:.3f}','%')}</section>
<h2>{escape(text['chain'])}</h2><section class='flow'>{phase_cards}</section><h2>{escape(text['visuals'])}</h2><section class='visuals'><article class='chart'><h3>{escape(text['map_title'])}</h3><p>{escape(text['map_desc'])}</p>{_overview_map_svg(report['maximum_depth'],map_labels)}</article><article class='chart'><h3>{escape(text['rain_title'])}</h3><p>{escape(text['rain_desc'])}</p>{_rainfall_svg(report['rainfall'],rain_labels)}</article><article class='chart'><h3>{escape(text['evo_title'])}</h3><p>{escape(text['evo_desc'])}</p>{_evolution_svg(report['evolution'],evo_labels)}</article><article class='chart'><h3>{escape(text['axis_title'])}</h3><p>{escape(text['axis_desc'])}</p>{_timeline_svg(timeline,{"no_data":text['no_data'],"aria":text['axis_aria'],"frames":text['slices'],"time_unit":"分钟" if zh else "min","point_note":"每个圆点代表一个输出时间片" if zh else "Each dot is one output frame"})}</article></section>
<h2>{escape(text['validation'])}</h2><section class='split'><article class='quality'><h3>{escape(text['quality'])}</h3><strong class='{quality_class}'>{escape(quality_label)}</strong><p>{escape(text['failed'])}: {escape(failure_detail)}</p></article><article><table><tbody>{gate_rows}</tbody></table></article></section><h2>{escape(text['assets'])}</h2><ul class='asset-list'>{assets}</ul><h2>{escape(text['boundary'])}</h2><section class='boundary'><strong>{escape(text['supports'])}</strong><p>{escape(text['next'])}</p><p>{escape(boundary_text)}</p></section><footer class='footer'>{escape(footer_label)}</footer></main></body></html>"""
