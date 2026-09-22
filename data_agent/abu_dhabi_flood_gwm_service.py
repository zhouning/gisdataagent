"""Abu Dhabi phase-4 GWM rapid rollout service.

This module is deliberately separate from the EPA SWMM and ANUGA services.
It consumes an existing phase-3 surface result, applies transparent
action-conditioned response factors, and emits an auditable baseline /
intervention / delta contract.  It is a rapid world-model adapter for
scenario screening; it does not overwrite or masquerade as a native solver.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .abu_dhabi_zone_b_design_storm import SUPPORTED_RETURN_PERIODS


DEFAULT_GWM_ROOT = Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater/gwm_runs"
DEFAULT_2D_ROOT = Path.home() / ".local/share/gisdataagent/public/abu_dhabi_stormwater/copernicus_citywide_2d"
LOCAL_RESULT_ROOT = Path.home() / "Downloads/阿布扎比/二维水动力_客户DTM_SWMM耦合_多年一遇_250m_20260910"
GWM_SCHEMA = "gwm.abu_dhabi_flood.phase4_rapid_rollout.v1"
# Phase-3 already applies the public land/water mask.  Keep the same
# conservative threshold in the GWM adapter so a partially-water cell cannot
# reappear as a coloured urban-flood result when the phase-4 layer is built.
GWM_LAND_FRACTION_THRESHOLD = 0.5
GWM_PERMANENT_WATER_FRACTION_THRESHOLD = 0.5
GWM_AFFECTED_DEPTH_THRESHOLD_M = 0.01
_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


def _gwm_root() -> Path:
    return _configured_path("ABU_DHABI_GWM_RUN_ROOT", DEFAULT_GWM_ROOT).expanduser().resolve()


def _period_root(return_period: int) -> Path:
    configured = os.environ.get("ABU_DHABI_GWM_2D_ROOT", "").strip()
    candidates = []
    if configured:
        base = Path(configured).expanduser().resolve()
        candidates.extend([base / f"rp{return_period:03d}", base])
    configured_public = os.environ.get("ABU_DHABI_PUBLIC_CITYWIDE_2D_ROOT", "").strip()
    if configured_public:
        base = Path(configured_public).expanduser().resolve()
        candidates.extend([base / f"rp{return_period:03d}", base])
    # Customer 5 m DTM phase-3 products are the default GWM baseline.  The
    # public Copernicus product is retained only as a fallback when the
    # selected customer return-period result is not provisioned.
    candidates.extend([
        LOCAL_RESULT_ROOT / f"rp{return_period:03d}",
        DEFAULT_2D_ROOT / f"rp{return_period:03d}",
    ])
    for candidate in candidates:
        if (candidate / "maximum_depth_wgs84.geojson").is_file() and (candidate / "temporal_snapshots/manifest.json").is_file():
            return candidate
    raise ValueError("gwm_phase3_surface_result_not_available")


def _json_read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("gwm_phase3_payload_invalid") from error


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _gzip_json_write(path: Path, payload: Any) -> None:
    """Persist large GeoJSON assets without duplicating them in run.json.

    Phase-3 surface products can contain tens of thousands of polygons.  The
    run receipt should stay small and auditable; the map products are stored as
    independently addressable gzip assets and loaded lazily on restart.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(temporary, "wb", compresslevel=6) as stream:
        stream.write(encoded)
    temporary.replace(path)


def _gzip_json_read(path: Path) -> Any:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("gwm_run_asset_invalid") from error


def _persist_record(run_dir: Path, record: dict[str, Any]) -> None:
    """Write a compact receipt plus compressed map assets.

    Older runs keep inline ``*_maximum`` fields and remain readable.  New runs
    use the ``assets`` index so a process restart does not require a multi-
    hundred-megabyte JSON receipt before the API can answer metadata calls.
    """
    compact = dict(record)
    assets: dict[str, str] = {}
    for key in ("baseline_maximum", "intervention_maximum", "delta_maximum"):
        payload = compact.pop(key, None)
        if payload is None:
            continue
        filename = f"{key}.geojson.json.gz"
        _gzip_json_write(run_dir / filename, payload)
        assets[key] = filename
    compact["assets"] = assets
    _json_write(run_dir / "run.json", compact)


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}_invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name}_invalid") from error
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{name}_out_of_range")
    return result


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("gwm_payload_invalid")
    try:
        return_period = int(payload.get("returnPeriodYears", payload.get("return_period_years", 100)))
    except (TypeError, ValueError) as error:
        raise ValueError("gwm_return_period_invalid") from error
    if return_period not in SUPPORTED_RETURN_PERIODS:
        raise ValueError("gwm_return_period_not_supported")
    pipe = _number(payload.get("pipeCapacityMultiplier", payload.get("pipe_capacity_multiplier", 1.0)), "pipe_capacity_multiplier", 0.1, 1.5)
    blockage = _number(payload.get("blockagePercent", payload.get("blockage_percent", 0.0)), "blockage_percent", 0.0, 90.0)
    pump = _number(payload.get("pumpCapacityMultiplier", payload.get("pump_capacity_multiplier", 1.0)), "pump_capacity_multiplier", 0.0, 1.5)
    outfall = _number(payload.get("outfallLevelAdjustment", payload.get("outfall_level_adjustment", 0.0)), "outfall_level_adjustment", -2.0, 2.0)
    # A positive intervention factor means more effective drainage. Keep the
    # formula explicit so operators can audit exactly what was screened.
    return {
        "return_period_years": return_period,
        "pipe_capacity_multiplier": pipe,
        "blockage_percent": blockage,
        "pump_capacity_multiplier": pump,
        "outfall_level_adjustment": outfall,
        "scenario_label": str(payload.get("scenarioLabel", payload.get("scenario_label", "GWM intervention"))).strip() or "GWM intervention",
    }


def _first_nonempty_snapshot_index(period_root: Path, snapshots: list[dict[str, Any]]) -> int:
    """Return the first frame that contains surface cells.

    ANUGA exports a valid empty FeatureCollection at the initial instant for
    several return periods.  That is physically meaningful (no ponding yet),
    but it is not a useful first frame for a map timeline because there are no
    geometries to render.  Inspect only frames until the first non-empty one;
    this keeps rollout startup cheap while preserving the source files and the
    explicit 0-minute frame in the API.
    """
    for index, item in enumerate(snapshots):
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("gwm_phase3_snapshot_path_invalid")
        payload = _json_read(period_root / relative)
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise ValueError("gwm_phase3_snapshot_invalid")
        features = payload.get("features")
        if isinstance(features, list) and features:
            return index
    return 0


def _read_source(period_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], int]:
    maximum = _json_read(period_root / "maximum_depth_wgs84.geojson")
    manifest = _json_read(period_root / "temporal_snapshots/manifest.json")
    summary_path = period_root / "delivery_summary.json"
    summary = _json_read(summary_path) if summary_path.is_file() else {}
    if not isinstance(maximum, dict) or maximum.get("type") != "FeatureCollection":
        raise ValueError("gwm_phase3_maximum_depth_invalid")
    snapshots = manifest.get("snapshots") if isinstance(manifest, dict) else None
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("gwm_phase3_timeline_invalid")
    initial_time_index = _first_nonempty_snapshot_index(period_root, snapshots)
    return maximum, snapshots, summary, initial_time_index


def _load_frame(root: Path, item: dict[str, Any], index: int) -> dict[str, Any]:
    relative = Path(str(item.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("gwm_phase3_snapshot_path_invalid")
    payload = _json_read(root / relative)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("gwm_phase3_snapshot_invalid")
    payload["name"] = f"abu_dhabi_gwm_surface_time_{index:03d}"
    return payload


def _factor(actions: dict[str, Any]) -> tuple[float, float]:
    # Drainage improvement lowers surface depth. Blockage and raised outfall
    # increase it. The uncertainty is intentionally conservative and grows
    # with action distance from the phase-3 baseline.
    capacity = actions["pipe_capacity_multiplier"] * (1.0 - actions["blockage_percent"] / 100.0)
    pump = actions["pump_capacity_multiplier"]
    outfall = actions["outfall_level_adjustment"]
    improvement = max(-0.45, min(0.45, (capacity - 1.0) * 0.32 + (pump - 1.0) * 0.12 - outfall * 0.08))
    response_factor = max(0.35, min(1.8, 1.0 - improvement))
    uncertainty_fraction = min(0.35, 0.06 + abs(improvement) * 0.35 + (0.10 if actions["blockage_percent"] > 50 else 0.0))
    return response_factor, uncertainty_fraction


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Return a finite float without allowing malformed source attributes to
    break a whole rollout.

    The phase-3 GeoJSON is an external result contract.  A missing or invalid
    optional attribute should make the spatial proxy conservative, not make a
    valid baseline unavailable.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _feature_context(props: dict[str, Any]) -> dict[str, Any]:
    """Extract the small spatial context available in the phase-3 surface
    contract.

    This is intentionally not presented as a resolved pipe/network influence
    model.  It is a transparent spatial susceptibility proxy using attributes
    that are already emitted by the 2-D result: land fraction, permanent-water
    fraction and baseline depth.
    """
    source_depth = max(0.0, _safe_float(props.get("source_depth_m", props.get("maximum_depth_m", props.get("depth_m", 0.0)))))
    land_fraction = min(1.0, max(0.0, _safe_float(props.get("land_fraction", 1.0), 1.0)))
    permanent_water_fraction = min(1.0, max(0.0, _safe_float(props.get("permanent_water_fraction", 0.0))))
    water_dominated = (
        land_fraction < GWM_LAND_FRACTION_THRESHOLD
        or permanent_water_fraction >= GWM_PERMANENT_WATER_FRACTION_THRESHOLD
    )
    return {
        "source_depth_m": source_depth,
        "land_fraction": land_fraction,
        "permanent_water_fraction": permanent_water_fraction,
        "water_dominated": water_dominated,
    }


def _payload_depth_scale(payload: dict[str, Any]) -> float:
    depths = []
    for feature in payload.get("features", []):
        props = dict(feature.get("properties") or {})
        context = _feature_context(props)
        if not context["water_dominated"]:
            depths.append(context["source_depth_m"])
    return max(depths, default=0.0)


def _spatial_response_factor(response_factor: float, context: dict[str, Any], depth_scale: float) -> tuple[float, float]:
    """Localise the global action response without claiming network physics.

    Higher-risk, fully-land cells receive the stronger part of the action
    response; mixed/water-dominated cells are excluded before this function is
    called.  The resulting factor is deliberately bounded by the same range
    as the phase-4 global response factor.
    """
    depth_score = context["source_depth_m"] / max(depth_scale, GWM_AFFECTED_DEPTH_THRESHOLD_M)
    depth_score = min(1.0, max(0.0, depth_score))
    susceptibility = min(1.0, max(0.0, 0.55 * depth_score + 0.45 * context["land_fraction"]))
    # 0.70–1.00 keeps the adapter conservative while avoiding one identical
    # multiplier for every cell.  A negative improvement (blockage or raised
    # outfall) is spatialised in the same transparent way.
    locality = 0.70 + 0.30 * susceptibility
    improvement = 1.0 - response_factor
    local_factor = max(0.35, min(1.80, 1.0 - improvement * locality))
    return local_factor, susceptibility


def _transform(payload: dict[str, Any], response_factor: float, uncertainty_fraction: float, *, include_delta: bool = True) -> dict[str, Any]:
    transformed = dict(payload)
    features = []
    depth_scale = _payload_depth_scale(payload)
    for feature in payload.get("features", []):
        item = dict(feature)
        props = dict(feature.get("properties") or {})
        context = _feature_context(props)
        source_depth = context["source_depth_m"]
        props["source_depth_m"] = source_depth
        props["land_fraction"] = context["land_fraction"]
        props["permanent_water_fraction"] = context["permanent_water_fraction"]
        props["water_dominated"] = context["water_dominated"]
        if context["water_dominated"]:
            # Keep the source geometry and audit fields, but make water-only or
            # water-dominated cells non-renderable in the urban flood layer.
            baseline = 0.0
            intervention = 0.0
            local_factor = 1.0
            susceptibility = 0.0
            uncertainty = 0.0
        else:
            baseline = source_depth
            local_factor, susceptibility = _spatial_response_factor(response_factor, context, depth_scale)
            intervention = max(0.0, baseline * local_factor)
            uncertainty = baseline * uncertainty_fraction
        props["baseline_depth_m"] = baseline
        props["intervention_depth_m"] = intervention
        props["delta_depth_m"] = intervention - baseline if include_delta else 0.0
        props["spatial_response_factor"] = local_factor
        props["action_sensitivity_score"] = susceptibility
        props["uncertainty_m"] = uncertainty
        props["maximum_depth_m"] = intervention
        props["depth_m"] = intervention
        item["properties"] = props
        features.append(item)
    transformed["features"] = features
    return transformed


def _baseline_with_fields(payload: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(payload)
    features = []
    for feature in payload.get("features", []):
        item = dict(feature)
        props = dict(feature.get("properties") or {})
        context = _feature_context(props)
        baseline = 0.0 if context["water_dominated"] else context["source_depth_m"]
        props.update({
            "source_depth_m": context["source_depth_m"],
            "land_fraction": context["land_fraction"],
            "permanent_water_fraction": context["permanent_water_fraction"],
            "water_dominated": context["water_dominated"],
            "baseline_depth_m": baseline,
            "intervention_depth_m": baseline,
            "delta_depth_m": 0.0,
            "spatial_response_factor": 1.0,
            "action_sensitivity_score": 0.0,
            "uncertainty_m": 0.0,
        })
        props["maximum_depth_m"] = baseline
        props["depth_m"] = baseline
        item["properties"] = props
        features.append(item)
    transformed["features"] = features
    return transformed


def _mask_summary(payload: dict[str, Any]) -> dict[str, int]:
    active = 0
    excluded = 0
    for feature in payload.get("features", []):
        context = _feature_context(dict(feature.get("properties") or {}))
        if context["water_dominated"]:
            excluded += 1
        else:
            active += 1
    return {"active_cell_count": active, "excluded_water_cell_count": excluded}


def _surface_metrics(payload: dict[str, Any]) -> dict[str, float | int]:
    """Calculate map-level decision metrics from a maximum-depth product.

    Volume and area are explicitly labelled as cell-area proxies because the
    phase-3 contract is a GeoJSON surface grid, not a finite-volume export.
    """
    maximum_depth = 0.0
    affected = 0
    area_m2 = 0.0
    volume_m3 = 0.0
    for feature in payload.get("features", []):
        props = dict(feature.get("properties") or {})
        depth = max(0.0, _safe_float(props.get("maximum_depth_m", props.get("depth_m", 0.0))))
        if depth > maximum_depth:
            maximum_depth = depth
        if depth >= GWM_AFFECTED_DEPTH_THRESHOLD_M:
            affected += 1
        context = _feature_context(props)
        cell_size = max(1.0, _safe_float(props.get("prototype_cell_size_m", 250.0), 250.0))
        cell_area = cell_size * cell_size * context["land_fraction"]
        area_m2 += cell_area if depth >= GWM_AFFECTED_DEPTH_THRESHOLD_M else 0.0
        volume_m3 += depth * cell_area
    return {
        "maximum_depth_m": maximum_depth,
        "affected_cell_count": affected,
        "affected_area_m2_proxy": area_m2,
        "peak_surface_storage_m3_proxy": volume_m3,
    }


def _metadata(run_id: str, actions: dict[str, Any], root: Path, snapshots: list[dict[str, Any]], summary: dict[str, Any], source_features: int, factor: float, uncertainty: float, initial_time_index: int) -> dict[str, Any]:
    forcing = summary.get("forcing") if isinstance(summary, dict) else {}
    mask = _mask_summary(_json_read(root / "maximum_depth_wgs84.geojson"))
    surface = summary.get("surface") if isinstance(summary, dict) else {}
    if not isinstance(surface, dict):
        surface = {}
    surface_product = str(surface.get("product") or "")
    evidence_class = str(surface.get("evidence_class") or "").lower()
    is_customer_surface = (
        "customer" in evidence_class
        or "dtm" in evidence_class
        or "customer" in surface_product.lower()
        or "dtm" in surface_product.lower()
    )
    surface_source_class = "customer_authoritative" if is_customer_surface else "public_proxy"
    surface_source = "customer_dtm_5m" if is_customer_surface else "copernicus_dem_glo30"
    claim_boundary = (
        "GWM phase-4 rapid rollout uses the customer 5 m DTM phase-3 SWMM→ANUGA result as its baseline; high-risk cases must return to SWMM/ANUGA."
        if is_customer_surface
        else "GWM phase-4 rapid rollout uses the public Copernicus DEM phase-3 result as a fallback baseline; high-risk cases must return to SWMM/ANUGA."
    )
    return {
        "schema": GWM_SCHEMA,
        "run_id": run_id,
        "status": "completed",
        "solver": "GWM rapid rollout adapter",
        "phase": 4,
        "input_solver": "ANUGA 2D / SWMM coupled result",
        "input_source": str(root),
        "input_result_status": summary.get("claim_boundary") if isinstance(summary, dict) else None,
        "upstream_result_source": str(root),
        "surface_product": surface_product,
        "surface_source": surface_source,
        "surface_source_class": surface_source_class,
        "surface_source_authority": "customer_provided" if is_customer_surface else "ESA/Copernicus public product",
        "source_resolution_m": surface.get("source_resolution_m") or ([5.0, 5.0] if is_customer_surface else None),
        "return_period_years": actions["return_period_years"],
        "available_return_periods": list(SUPPORTED_RETURN_PERIODS),
        "actions": actions,
        "response_factor": factor,
        "uncertainty_fraction": uncertainty,
        "source_feature_count": source_features,
        "active_cell_count": mask["active_cell_count"],
        "excluded_water_cell_count": mask["excluded_water_cell_count"],
        "water_mask": {
            "land_fraction_threshold": GWM_LAND_FRACTION_THRESHOLD,
            "permanent_water_fraction_threshold": GWM_PERMANENT_WATER_FRACTION_THRESHOLD,
            "policy": "water-dominated cells remain in the audit payload but are rendered at zero urban-flood depth",
        },
        "spatial_response": {
            "model": "baseline_depth_land_fraction_susceptibility_proxy",
            "network_resolved": False,
            "purpose": "screening-level spatial differentiation of the phase-3 baseline",
            "locality_range": [0.70, 1.00],
        },
        "timeline": {
            "available": True,
            "run_id": run_id,
            "endpoint": f"/api/abu-dhabi/flood/gwm/runs/{run_id}/map/timeseries",
            "time_values": [f"{float(item.get('time_minutes', item.get('time_seconds', 0) / 60)):.0f} min" for item in snapshots],
            "elapsed_minutes": [float(item.get("time_minutes", item.get("time_seconds", 0) / 60)) for item in snapshots],
            "period_count": len(snapshots),
            # The source's t=0 frame remains available through the endpoint,
            # while the UI starts on the first frame with renderable cells.
            "initial_time_index": initial_time_index,
            "step_minutes": float((summary.get("domain") or {}).get("output_step_minutes", 30.0)) if isinstance(summary, dict) else 30.0,
            "total_cell_count": source_features,
        },
        "quality": {
            "source_frame_count": len(snapshots),
            "mass_balance_reused_from_phase3": True,
            "gwm_training": "not_trained",
            "uncertainty_gate": "screening_only",
            "fallback_signal": "high_risk_scenarios_return_to_swmm_anuga_review",
        },
        "claim_boundary": claim_boundary,
        "forcing": forcing,
    }


def start_gwm_rollout(payload: dict[str, Any]) -> dict[str, Any]:
    actions = _validate(payload)
    root = _period_root(actions["return_period_years"])
    maximum, snapshots, summary, initial_time_index = _read_source(root)
    run_id = f"gwm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    response_factor, uncertainty = _factor(actions)
    baseline = _baseline_with_fields(maximum)
    intervention = _transform(maximum, response_factor, uncertainty)
    delta = _transform(maximum, response_factor, uncertainty)
    for feature in delta.get("features", []):
        props = feature.setdefault("properties", {})
        props["maximum_depth_m"] = props.get("delta_depth_m", 0.0)
        props["depth_m"] = props.get("delta_depth_m", 0.0)
    record = {
        "run_id": run_id,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": _metadata(run_id, actions, root, snapshots, summary, len(maximum.get("features", [])), response_factor, uncertainty, initial_time_index),
        "baseline_maximum": baseline,
        "intervention_maximum": intervention,
        "delta_maximum": delta,
        "source_root": str(root),
        "snapshot_items": snapshots,
    }
    run_dir = _gwm_root() / run_id
    _persist_record(run_dir, record)
    with _LOCK:
        _RUNS[run_id] = record
    return public_run(run_id)


def _get(run_id: str) -> dict[str, Any]:
    with _LOCK:
        record = _RUNS.get(run_id)
    if record is not None:
        return record
    path = _gwm_root() / run_id / "run.json"
    if not path.is_file():
        raise KeyError(run_id)
    record = _json_read(path)
    if not isinstance(record, dict):
        raise ValueError("gwm_run_invalid")
    # New receipts index compressed map assets instead of embedding large
    # GeoJSON payloads.  Materialise them in memory only when a map endpoint
    # actually needs them, preserving the existing in-process contract.
    assets = record.get("assets")
    if isinstance(assets, dict):
        run_dir = path.parent
        for key in ("baseline_maximum", "intervention_maximum", "delta_maximum"):
            filename = assets.get(key)
            if not isinstance(filename, str):
                continue
            asset_path = (run_dir / filename).resolve()
            if run_dir.resolve() not in asset_path.parents or not asset_path.is_file():
                raise ValueError("gwm_run_asset_missing")
            record[key] = _gzip_json_read(asset_path)
    with _LOCK:
        _RUNS[run_id] = record
    return record


def public_run(run_id: str) -> dict[str, Any]:
    record = _get(run_id)
    metadata = dict(record.get("metadata") or {})
    baseline_metrics = _surface_metrics(record.get("baseline_maximum", {}))
    intervention_metrics = _surface_metrics(record.get("intervention_maximum", {}))
    return {
        "run_id": run_id,
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "metadata": metadata,
        "actions": metadata.get("actions", {}),
        "metrics": {
            "baseline_max_depth_m": baseline_metrics["maximum_depth_m"],
            "intervention_max_depth_m": intervention_metrics["maximum_depth_m"],
            "maximum_absolute_delta_m": max((abs(float((f.get("properties") or {}).get("delta_depth_m", 0.0))) for f in record.get("delta_maximum", {}).get("features", [])), default=0.0),
            "source_feature_count": int(metadata.get("source_feature_count", 0)),
            "active_cell_count": int(metadata.get("active_cell_count", 0)),
            "excluded_water_cell_count": int(metadata.get("excluded_water_cell_count", 0)),
            "baseline_affected_cell_count": baseline_metrics["affected_cell_count"],
            "intervention_affected_cell_count": intervention_metrics["affected_cell_count"],
            "baseline_affected_area_m2_proxy": baseline_metrics["affected_area_m2_proxy"],
            "intervention_affected_area_m2_proxy": intervention_metrics["affected_area_m2_proxy"],
            "baseline_peak_surface_storage_m3_proxy": baseline_metrics["peak_surface_storage_m3_proxy"],
            "intervention_peak_surface_storage_m3_proxy": intervention_metrics["peak_surface_storage_m3_proxy"],
            "peak_surface_storage_delta_m3_proxy": intervention_metrics["peak_surface_storage_m3_proxy"] - baseline_metrics["peak_surface_storage_m3_proxy"],
        },
    }


def map_bootstrap(run_id: str) -> dict[str, Any]:
    record = _get(run_id)
    metadata = dict(record.get("metadata") or {})
    # Keep the bootstrap payload useful to generic map clients as well as the
    # phase-4 UI.  The first non-empty source frame is the renderable initial
    # state; t=0 remains available through the explicit timeline endpoint.
    items = record.get("snapshot_items") or []
    initial_index = int((metadata.get("timeline") or {}).get("initial_time_index", 0) or 0)
    initial_frame: dict[str, Any] | None = None
    if items and 0 <= initial_index < len(items):
        root = Path(record["source_root"])
        initial_frame = _load_frame(root, items[initial_index], initial_index)
    initial_source = initial_frame or {"type": "FeatureCollection", "features": []}
    initial_baseline = _baseline_with_fields(initial_source)
    initial_intervention = _transform(
        initial_source,
        float(metadata.get("response_factor", 1.0)),
        float(metadata.get("uncertainty_fraction", 0.0)),
    )
    initial_delta = _transform(
        initial_source,
        float(metadata.get("response_factor", 1.0)),
        float(metadata.get("uncertainty_fraction", 0.0)),
    )
    for feature in initial_delta.get("features", []):
        props = feature.setdefault("properties", {})
        props["maximum_depth_m"] = props.get("delta_depth_m", 0.0)
        props["depth_m"] = props.get("delta_depth_m", 0.0)
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_gwm_phase4_{run_id}",
        # `features` is the initial intervention frame for clients that only
        # understand a plain FeatureCollection.  The named products below
        # remain the authoritative maxima and are what the phase-4 UI uses.
        "features": initial_intervention.get("features", []),
        "metadata": {**metadata, "bootstrap_time_index": initial_index},
        "baseline": initial_baseline,
        "intervention": initial_intervention,
        "delta": initial_delta,
        "baseline_maximum": record.get("baseline_maximum"),
        "intervention_maximum": record.get("intervention_maximum"),
        "delta_maximum": record.get("delta_maximum"),
    }


def map_timeseries(run_id: str, time_index: int) -> dict[str, Any]:
    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("time_index_invalid")
    record = _get(run_id)
    items = record.get("snapshot_items") or []
    if time_index < 0 or time_index >= len(items):
        raise ValueError("time_index_out_of_range")
    root = Path(record["source_root"])
    source = _load_frame(root, items[time_index], time_index)
    metadata = dict(record.get("metadata") or {})
    factor = float(metadata.get("response_factor", 1.0))
    uncertainty = float(metadata.get("uncertainty_fraction", 0.0))
    baseline = _baseline_with_fields(source)
    intervention = _transform(source, factor, uncertainty)
    delta = _transform(source, factor, uncertainty)
    for feature in delta.get("features", []):
        props = feature.setdefault("properties", {})
        props["maximum_depth_m"] = props.get("delta_depth_m", 0.0)
        props["depth_m"] = props.get("delta_depth_m", 0.0)
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_gwm_phase4_time_{time_index:03d}",
        "features": intervention.get("features", []),
        "baseline": baseline,
        "intervention": intervention,
        "delta": delta,
        "metadata": {**metadata, "time_index": time_index, "time_minutes": metadata.get("timeline", {}).get("elapsed_minutes", [0])[time_index]},
    }


__all__ = ["start_gwm_rollout", "public_run", "map_bootstrap", "map_timeseries"]
