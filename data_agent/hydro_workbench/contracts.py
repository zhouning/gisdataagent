"""Strict, serialisable contracts for the hydro calculation workbench.

The contract deliberately separates the user AOI, the expanded model domain,
and the display extent.  A run manifest is written once before a Kubernetes
Job is created and is never mutated afterwards.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any

SCHEMA = "gwm.abu_dhabi_flood.hydro_run_manifest.v1"
MODEL_TYPES = {"one_d", "two_d", "coupled_1d_2d"}
RESOURCE_PROFILES = {"cpu_small", "cpu_large", "gpu"}
INPUT_MODES = {"development_fixture", "customer_mount"}
DEFAULTS: dict[str, Any] = {
    "rainfall_total_mm": 50.0,
    "rainfall_duration_minutes": 60,
    "rainfall_pattern": "uniform",
    "one_d_routing_method": "KINWAVE",
    "one_d_infiltration_method": "HORTON",
    "two_d_grid_resolution_m": 5.0,
    "two_d_manning_n": 0.03,
    "two_d_timestep_seconds": 300,
    "coupling_mode": "two_way_swmm_anuga",
    "domain_buffer_m": 500.0,
    "resource_profile": "cpu_small",
    "input_mode": "development_fixture",
}


class ManifestValidationError(ValueError):
    """Validation failure with machine-readable issue details."""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("; ".join(f"{i['field']}: {i['message']}" for i in issues))


def _number(
    value: Any, field: str, minimum: float, maximum: float, issues: list[dict[str, Any]]
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append({"field": field, "message": "must be a number"})
        return minimum
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        issues.append({"field": field, "message": f"must be between {minimum} and {maximum}"})
    return result


def _integer(
    value: Any, field: str, minimum: int, maximum: int, issues: list[dict[str, Any]]
) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        issues.append({"field": field, "message": "must be an integer"})
        return minimum
    result = int(value)
    if result < minimum or result > maximum:
        issues.append({"field": field, "message": f"must be between {minimum} and {maximum}"})
    return result


def _bbox(payload: Any, issues: list[dict[str, Any]]) -> list[float]:
    if isinstance(payload, dict) and payload.get("type") == "Polygon":
        coordinates = payload.get("coordinates")
        if isinstance(coordinates, list) and coordinates and isinstance(coordinates[0], list):
            points = [
                point for point in coordinates[0] if isinstance(point, list) and len(point) >= 2
            ]
            if points:
                payload = [
                    min(float(point[0]) for point in points),
                    min(float(point[1]) for point in points),
                    max(float(point[0]) for point in points),
                    max(float(point[1]) for point in points),
                ]
    if not isinstance(payload, (list, tuple)) or len(payload) != 4:
        issues.append(
            {
                "field": "aoi",
                "message": "must be a bbox [min_lon,min_lat,max_lon,max_lat] or GeoJSON Polygon",
            }
        )
        return [54.35, 24.35, 54.45, 24.45]
    try:
        bbox = [float(value) for value in payload]
    except (TypeError, ValueError):
        issues.append({"field": "aoi", "message": "bbox coordinates must be numeric"})
        return [54.35, 24.35, 54.45, 24.45]
    min_lon, min_lat, max_lon, max_lat = bbox
    if not all(math.isfinite(value) for value in bbox):
        issues.append({"field": "aoi", "message": "bbox coordinates must be finite"})
    if min_lon >= max_lon or min_lat >= max_lat:
        issues.append({"field": "aoi", "message": "bbox min values must be less than max values"})
    if not (
        -180 <= min_lon <= 180
        and -180 <= max_lon <= 180
        and -90 <= min_lat <= 90
        and -90 <= max_lat <= 90
    ):
        issues.append({"field": "aoi", "message": "bbox is outside geographic coordinate bounds"})
    if max_lon - min_lon > 5 or max_lat - min_lat > 5:
        issues.append(
            {"field": "aoi", "message": "local MVP AOI cannot exceed 5 degrees in either dimension"}
        )
    return bbox


def _expand_bbox(bbox: list[float], buffer_m: float) -> list[float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_delta = buffer_m / 111_320.0
    lon_scale = max(0.2, math.cos(math.radians((min_lat + max_lat) / 2)))
    lon_delta = buffer_m / (111_320.0 * lon_scale)
    return [min_lon - lon_delta, min_lat - lat_delta, max_lon + lon_delta, max_lat + lat_delta]


def _source_record(value: Any, default_format: str, *, fixture: bool) -> dict[str, Any]:
    if isinstance(value, dict):
        record = {
            "uri": str(value.get("uri") or ""),
            "format": str(value.get("format") or default_format),
            "version": str(value.get("version") or "unversioned"),
            "provided_by_customer": bool(value.get("provided_by_customer", not fixture)),
            "etl_required": bool(value.get("etl_required", True)),
        }
    else:
        record = {
            "uri": str(value or ""),
            "format": default_format,
            "version": "unversioned",
            "provided_by_customer": not fixture,
            "etl_required": True,
        }
    if fixture:
        record.update(
            {"status": "development_fixture", "uri": record["uri"] or "runtime://fixtures"}
        )
    else:
        record.setdefault("status", "customer_reference")
    return record


def build_run_manifest(payload: dict[str, Any], *, strict_sources: bool = True) -> dict[str, Any]:
    """Validate a user request and return a complete immutable run manifest."""

    if not isinstance(payload, dict):
        raise ManifestValidationError([{"field": "body", "message": "JSON object required"}])
    issues: list[dict[str, Any]] = []
    model_type = str(payload.get("model_type") or "coupled_1d_2d")
    if model_type not in MODEL_TYPES:
        issues.append({"field": "model_type", "message": f"must be one of {sorted(MODEL_TYPES)}"})
        model_type = "coupled_1d_2d"
    input_mode = str(payload.get("input_mode") or DEFAULTS["input_mode"])
    if input_mode not in INPUT_MODES:
        issues.append({"field": "input_mode", "message": f"must be one of {sorted(INPUT_MODES)}"})
        input_mode = DEFAULTS["input_mode"]
    resource_profile = str(payload.get("resource_profile") or DEFAULTS["resource_profile"])
    if resource_profile not in RESOURCE_PROFILES:
        issues.append(
            {"field": "resource_profile", "message": f"must be one of {sorted(RESOURCE_PROFILES)}"}
        )
        resource_profile = DEFAULTS["resource_profile"]
    aoi = _bbox(payload.get("aoi") or payload.get("bbox"), issues)
    buffer_m = _number(
        payload.get("domain_buffer_m", DEFAULTS["domain_buffer_m"]),
        "domain_buffer_m",
        0,
        10_000,
        issues,
    )
    model_domain = _expand_bbox(aoi, buffer_m)
    rainfall_total = _number(
        payload.get("rainfall_total_mm", DEFAULTS["rainfall_total_mm"]),
        "rainfall_total_mm",
        0.01,
        2_000,
        issues,
    )
    rainfall_duration = _integer(
        payload.get("rainfall_duration_minutes", DEFAULTS["rainfall_duration_minutes"]),
        "rainfall_duration_minutes",
        1,
        1_440,
        issues,
    )
    grid_resolution = _number(
        payload.get("two_d_grid_resolution_m", DEFAULTS["two_d_grid_resolution_m"]),
        "two_d_grid_resolution_m",
        0.5,
        100,
        issues,
    )
    manning_n = _number(
        payload.get("two_d_manning_n", DEFAULTS["two_d_manning_n"]),
        "two_d_manning_n",
        0.005,
        0.3,
        issues,
    )
    timestep = _integer(
        payload.get("two_d_timestep_seconds", DEFAULTS["two_d_timestep_seconds"]),
        "two_d_timestep_seconds",
        1,
        3_600,
        issues,
    )
    coupling_mode = str(payload.get("coupling_mode") or DEFAULTS["coupling_mode"])
    if coupling_mode not in {"one_way_swmm_to_anuga", "two_way_swmm_anuga"}:
        issues.append({"field": "coupling_mode", "message": "unsupported coupling mode"})
        coupling_mode = DEFAULTS["coupling_mode"]
    if issues:
        raise ManifestValidationError(issues)

    # The server owns run identifiers.  Client-supplied paths or Kubernetes
    # names are never admitted into the storage or orchestration boundary.
    run_id = f"hydro-{uuid.uuid4().hex[:16]}"
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    user_keys = {
        "aoi",
        "bbox",
        "model_type",
        "input_mode",
        "resource_profile",
        "rainfall_total_mm",
        "rainfall_duration_minutes",
        "rainfall_pattern",
        "domain_buffer_m",
        "two_d_grid_resolution_m",
        "two_d_manning_n",
        "two_d_timestep_seconds",
        "coupling_mode",
    }
    provided = {key: key in payload for key in user_keys}
    data_payload = (
        payload.get("data_sources") if isinstance(payload.get("data_sources"), dict) else {}
    )
    fixture = input_mode == "development_fixture"
    data_sources = {
        "network": _source_record(data_payload.get("network"), "SWMM_INP/GDB", fixture=fixture),
        "terrain": _source_record(data_payload.get("terrain"), "GeoTIFF/NPZ", fixture=fixture),
        "rainfall": _source_record(
            data_payload.get("rainfall"), "CSV/JSON time series", fixture=fixture
        ),
        "tide": _source_record(data_payload.get("tide"), "CSV/JSON time series", fixture=fixture),
        "outfalls": _source_record(
            data_payload.get("outfalls"), "GeoPackage/GeoJSON", fixture=fixture
        ),
        "pumps": _source_record(data_payload.get("pumps"), "CSV/GeoPackage", fixture=fixture),
    }
    required_sources = {
        "one_d": ["network"],
        "two_d": ["terrain"],
        "coupled_1d_2d": ["network", "terrain"],
    }[model_type]
    if input_mode == "customer_mount" and strict_sources:
        missing = [name for name in required_sources if not data_sources[name]["uri"]]
        if missing:
            raise ManifestValidationError(
                [
                    {"field": f"data_sources.{name}", "message": "customer_mount requires a URI"}
                    for name in missing
                ]
            )

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "manifest_version": 1,
        "run_id": run_id,
        "created_at": created_at,
        "immutability": {"state": "frozen", "hash_algorithm": "sha256"},
        "request": {
            "model_type": model_type,
            "input_mode": input_mode,
            "resource_profile": resource_profile,
        },
        "area": {
            "user_aoi": {"type": "bbox", "bbox": aoi, "crs": "EPSG:4326"},
            "model_calculation_domain": {
                "type": "bbox",
                "bbox": model_domain,
                "crs": "EPSG:4326",
                "buffer_m": buffer_m,
            },
            "result_display_extent": {"type": "bbox", "bbox": aoi, "crs": "EPSG:4326"},
        },
        "data_sources": data_sources,
        "parameters": {
            "rainfall": {
                "total_mm": rainfall_total,
                "duration_minutes": rainfall_duration,
                "pattern": str(payload.get("rainfall_pattern") or DEFAULTS["rainfall_pattern"]),
            },
            "one_d": {
                "routing_method": str(
                    payload.get("one_d_routing_method") or DEFAULTS["one_d_routing_method"]
                ),
                "infiltration_method": str(
                    payload.get("one_d_infiltration_method")
                    or DEFAULTS["one_d_infiltration_method"]
                ),
            },
            "two_d": {
                "grid_resolution_m": grid_resolution,
                "manning_n": manning_n,
                "timestep_seconds": timestep,
            },
            "coupling": {"mode": coupling_mode, "window_seconds": min(600, max(60, timestep))},
        },
        "parameter_provenance": {
            "rainfall.total_mm": "user" if provided["rainfall_total_mm"] else "system_default",
            "rainfall.duration_minutes": "user"
            if provided["rainfall_duration_minutes"]
            else "system_default",
            "rainfall.pattern": "user" if provided["rainfall_pattern"] else "system_default",
            "one_d.routing_method": "user"
            if "one_d_routing_method" in payload
            else "system_default",
            "one_d.infiltration_method": "user"
            if "one_d_infiltration_method" in payload
            else "system_default",
            "two_d.grid_resolution_m": "user"
            if provided["two_d_grid_resolution_m"]
            else "system_default",
            "two_d.manning_n": "user" if provided["two_d_manning_n"] else "system_default",
            "two_d.timestep_seconds": "user"
            if provided["two_d_timestep_seconds"]
            else "system_default",
            "coupling.mode": "user" if provided["coupling_mode"] else "system_default",
            "area.domain_buffer_m": "user" if provided["domain_buffer_m"] else "system_default",
        },
        "solver_contract": {
            "one_d": "EPA SWMM 5.2.4" if model_type in {"one_d", "coupled_1d_2d"} else None,
            "two_d": "ANUGA" if model_type in {"two_d", "coupled_1d_2d"} else None,
            "coupling": coupling_mode if model_type == "coupled_1d_2d" else None,
            "development_disclosure": (
                "customer_mount runs are required for engineering interpretation; "
                "development_fixture outputs are execution smoke results only"
            ),
        },
        "runtime": {
            "namespace": "gis-agent-hydro-dev",
            "job_name": f"hydro-run-{run_id.removeprefix('hydro-')[:36]}",
        },
    }
    unsigned = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest["immutability"]["sha256"] = hashlib.sha256(unsigned).hexdigest()
    return manifest


def manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a non-mutating data/parameter readiness report for the UI.

    Preflight intentionally does not create a run directory or a Kubernetes
    object.  Customer-mounted inputs remain blocked until the ETL adapter has
    materialised model-native files.
    """

    manifest = build_run_manifest(payload, strict_sources=False)
    model_type = str(manifest["request"]["model_type"])
    required = {
        "one_d": ["network"],
        "two_d": ["terrain"],
        "coupled_1d_2d": ["network", "terrain"],
    }[model_type]
    fixture = manifest["request"]["input_mode"] == "development_fixture"
    checks: list[dict[str, Any]] = [
        {
            "key": "aoi",
            "label": "AOI and model domain",
            "status": "ready",
            "detail": "User AOI is valid; model domain includes the configured hydraulic buffer.",
        },
        {
            "key": "parameters",
            "label": "Core model parameters",
            "status": "ready",
            "detail": "Rainfall, duration, grid and coupling values passed contract validation.",
        },
    ]
    if fixture:
        checks.append(
            {
                "key": "model_native_inputs",
                "label": "Model-native development inputs",
                "status": "ready",
                "detail": "Pinned development fixtures are available to the local worker image.",
            }
        )
    else:
        checks.append(
            {
                "key": "customer_etl",
                "label": "Customer GDB/DTM ETL",
                "status": "blocked",
                "detail": (
                    "Customer references are registered, but the ETL adapter has not yet "
                    "produced model-ready SWMM INP and ANUGA grid inputs."
                ),
            }
        )
    source_checks = []
    for name in required:
        source = manifest["data_sources"][name]
        source_checks.append(
            {
                "key": name,
                "label": name,
                "status": "ready" if fixture else "blocked",
                "uri": source["uri"],
                "format": source["format"],
                "etl_required": source["etl_required"],
                "detail": (
                    "Development fixture"
                    if fixture
                    else "URI required"
                    if not source["uri"]
                    else "Awaiting regional ETL output"
                ),
            }
        )
    warnings = [
        (
            "Results from development fixtures are execution evidence only and are "
            "not calibrated engineering predictions."
        )
    ]
    if not fixture:
        warnings.append(
            "Customer data execution is fail-closed until source validation, field mapping, "
            "topology checks and model-native export pass."
        )
    return {
        "schema": "gwm.abu_dhabi_flood.hydro_preflight.v1",
        "status": "ready" if fixture else "blocked",
        "can_submit": fixture,
        "manifest_preview": manifest,
        "checks": checks,
        "required_sources": source_checks,
        "warnings": warnings,
        "resource_estimate": {
            "profile": manifest["request"]["resource_profile"],
            "gpu_requested": manifest["request"]["resource_profile"] == "gpu",
            "two_d_requested_resolution_m": manifest["parameters"]["two_d"]["grid_resolution_m"],
            "scope": "AOI plus hydraulic buffer",
        },
    }
