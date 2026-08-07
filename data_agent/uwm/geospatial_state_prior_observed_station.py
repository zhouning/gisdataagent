"""Observed-station multi-geometry dataset adapter for state-prior evaluation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from shapely.geometry import shape
from shapely.ops import unary_union

from .geospatial_kernel.station_admin_crosswalk import (
    validate_station_admin_crosswalk,
)
from .geospatial_state_prior_benchmark import (
    UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
    validate_uwm_geospatial_state_prior_dataset,
)

ADMIN_GRAPH_SCHEMA = "uwm.admin_spatial_adjacency_graph.v1"
TAP_DATASET_ID = "tap_pm25_observed_gridded_chongqing_2018_2024"
OPENAQ_DATASET_ID = "openaq_air_quality_station_observation_proxy"


def build_observed_station_pm25_state_prior_dataset(
    *,
    locations_payload: Mapping[str, Any],
    sensor_measurement_payloads: Mapping[str, Mapping[str, Any]],
    station_admin_crosswalk: Mapping[str, Any],
    admin_feature_collection: Mapping[str, Any],
    admin_spatial_graph: Mapping[str, Any],
    tap_downloaded_dir: str | Path,
    dataset_id: str,
    created_at: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    """Build daily station targets with lagged TAP, admin geometry, and graph features."""

    crosswalk_validation = validate_station_admin_crosswalk(station_admin_crosswalk)
    if not crosswalk_validation["valid"] or not station_admin_crosswalk.get("crosswalk_complete"):
        raise ValueError("complete_valid_station_admin_crosswalk_required")
    if admin_spatial_graph.get("schema") != ADMIN_GRAPH_SCHEMA:
        raise ValueError(f"admin_spatial_graph.schema must be {ADMIN_GRAPH_SCHEMA}")
    refs = _unique_strings(evidence_refs)
    if not refs:
        raise ValueError("observed_station_dataset_evidence_refs_required")

    stations, sensor_to_station = _station_index(locations_payload)
    targets = _daily_station_targets(sensor_measurement_payloads, sensor_to_station)
    measured_station_ids = sorted({station_id for station_id, _ in targets})
    if not measured_station_ids:
        raise ValueError("observed_station_dataset_pm25_targets_required")
    assignment_by_station = {
        str(row["station_id"]): dict(row["assignment"])
        for row in station_admin_crosswalk["assignments"]
        if row["status"] == "matched"
    }
    missing_assignments = sorted(set(measured_station_ids) - set(assignment_by_station))
    if missing_assignments:
        raise ValueError(
            "observed_station_dataset_crosswalk_incomplete:" + ",".join(missing_assignments)
        )

    admin_geometry = _admin_geometry_index(admin_feature_collection)
    graph_nodes = _graph_node_index(admin_spatial_graph)
    measured_stations = [stations[station_id] for station_id in measured_station_ids]
    tap_support = _load_tap_support(Path(tap_downloaded_dir), measured_stations)

    rows = []
    dropped_missing_lag = []
    for (station_id, target_date), values in sorted(targets.items()):
        station = stations[station_id]
        assignment = assignment_by_station[station_id]
        admin_id = str(assignment["admin_id"])
        unit_key = (str(assignment["county"]), str(assignment["township"]))
        if admin_id not in admin_geometry:
            raise ValueError(f"observed_station_dataset_admin_geometry_missing:{admin_id}")
        if unit_key not in graph_nodes:
            raise ValueError("observed_station_dataset_graph_node_missing:" + "|".join(unit_key))
        lag_date = target_date - timedelta(days=1)
        lag_key = (station_id, lag_date)
        if lag_key not in tap_support["values"]:
            dropped_missing_lag.append(f"{station_id}|{target_date.isoformat()}")
            continue
        geometry = admin_geometry[admin_id]
        graph_node = graph_nodes[unit_key]
        rows.append(
            {
                "sample_id": f"{station_id}|{target_date.isoformat()}",
                "x": station["longitude"],
                "y": station["latitude"],
                "time_id": target_date.isoformat(),
                "admin_unit_id": admin_id,
                "target": float(fmean(values)),
                "raster_features": {
                    "lag1_tap_pm25_ugm3": tap_support["values"][lag_key],
                    "tap_grid_distance_degrees": tap_support["stations"][station_id][
                        "distance_degrees"
                    ],
                },
                "admin_features": {
                    "polygon_area_square_degrees": float(geometry.area),
                    "polygon_perimeter_degrees": float(geometry.length),
                },
                "graph_object_features": {
                    "admin_adjacency_degree": _finite_float(graph_node.get("degree")),
                },
            }
        )

    dataset = {
        "schema": UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
        "dataset_id": str(dataset_id),
        "created_at": str(created_at),
        "source_evidence_kind": "observed_holdout",
        "source_dataset_ids": [OPENAQ_DATASET_ID, TAP_DATASET_ID],
        "evidence_refs": refs,
        "target": {
            "name": "openaq_daily_pm25_mean_ugm3",
            "geometry_type": "point",
            "spatial_support": {"support_type": "sensor_footprint"},
            "temporal_support": {
                "start_date": min(row["time_id"] for row in rows) if rows else None,
                "end_date": max(row["time_id"] for row in rows) if rows else None,
            },
            "observation_semantics": "observed",
            "source_boundary": "daily_mean_of_actual_openaq_pm25_measurements",
        },
        "geometry_routes": {
            "raster": {
                "geometry_type": "raster",
                "spatial_support": {"support_type": "grid_cell"},
                "feature_names": [
                    "lag1_tap_pm25_ugm3",
                    "tap_grid_distance_degrees",
                ],
            },
            "admin": {
                "geometry_type": "polygon",
                "spatial_support": {"support_type": "admin_unit"},
                "feature_names": [
                    "polygon_area_square_degrees",
                    "polygon_perimeter_degrees",
                ],
            },
            "graph_object": {
                "geometry_type": "network",
                "spatial_support": {"support_type": "network_node"},
                "feature_names": ["admin_adjacency_degree"],
            },
        },
        "rows": rows,
        "adapter_audit": {
            "input_artifact_sha256": {
                "locations_payload_sha256": _canonical_sha256(locations_payload),
                "sensor_measurements_sha256": _canonical_sha256(sensor_measurement_payloads),
                "station_admin_crosswalk_sha256": station_admin_crosswalk["crosswalk_sha256"],
                "admin_feature_collection_sha256": _canonical_sha256(admin_feature_collection),
                "admin_spatial_graph_sha256": _canonical_sha256(admin_spatial_graph),
            },
            "measured_station_count": len(measured_station_ids),
            "daily_target_count_before_lag_join": len(targets),
            "dropped_missing_lag_sample_count": len(dropped_missing_lag),
            "dropped_missing_lag_sample_ids": dropped_missing_lag,
            "row_count": len(rows),
            "time_group_count": len({row["time_id"] for row in rows}),
            "admin_group_count": len({row["admin_unit_id"] for row in rows}),
            "tap_feature_lag_days": 1,
            "uses_current_or_future_target_values_in_features": False,
            "tap_station_grid_assignments": tap_support["stations"],
        },
        "claim_boundary": {
            "max_claim_level": "not_for_claim",
            "reason": (
                "This is an observed-target P1 candidate. TAP may share upstream monitoring "
                "sources, so only lagged TAP values are used and independent-source claims "
                "remain prohibited pending benchmark and provenance review."
            ),
        },
        "limitations": [
            "tap_product_may_assimilate_related_monitoring_sources",
            "lagged_tap_feature_not_independent_source_proof",
            "local_admin_boundary_vintage_and_license_not_verified",
            "state_reconstruction_only_not_action_conditioned_dynamics",
        ],
    }
    validation = validate_uwm_geospatial_state_prior_dataset(dataset)
    if not validation["valid"]:
        raise ValueError("invalid_observed_station_dataset:" + ";".join(validation["errors"]))
    return dataset


def _station_index(
    payload: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("observed_station_dataset_locations_results_invalid")
    stations = {}
    sensor_to_station = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        station_id = str(row.get("id") or "").strip()
        coordinates = row.get("coordinates")
        if not station_id or not isinstance(coordinates, Mapping):
            continue
        station = {
            "station_id": station_id,
            "station_name": str(row.get("name") or "") or None,
            "longitude": _finite_float(coordinates.get("longitude")),
            "latitude": _finite_float(coordinates.get("latitude")),
        }
        stations[station_id] = station
        for sensor in row.get("sensors") or []:
            if isinstance(sensor, Mapping) and sensor.get("id") is not None:
                sensor_to_station[str(sensor["id"])] = station_id
    return stations, sensor_to_station


def _daily_station_targets(
    payloads: Mapping[str, Mapping[str, Any]], sensor_to_station: Mapping[str, str]
) -> dict[tuple[str, date], list[float]]:
    values: dict[tuple[str, date], list[float]] = defaultdict(list)
    for sensor_id, payload in payloads.items():
        station_id = sensor_to_station.get(str(sensor_id))
        if station_id is None:
            continue
        for row in payload.get("results") or []:
            if not isinstance(row, Mapping) or _normalize_parameter(row) != "pm25":
                continue
            timestamp = _measurement_start(row)
            value = _optional_float(row.get("value"))
            if timestamp is not None and value is not None:
                values[(station_id, timestamp.date())].append(value)
    return dict(values)


def _admin_geometry_index(payload: Mapping[str, Any]) -> dict[str, Any]:
    features = payload.get("features")
    if payload.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("observed_station_dataset_admin_feature_collection_invalid")
    grouped: dict[str, list[Any]] = defaultdict(list)
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        fields = [
            str(properties.get(field) or "").strip() for field in ("province", "county", "township")
        ]
        if not all(fields):
            continue
        geometry = shape(feature.get("geometry"))
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("observed_station_dataset_admin_geometry_invalid")
        grouped["|".join(fields)].append(geometry)
    return {admin_id: unary_union(geometries) for admin_id, geometries in grouped.items()}


def _graph_node_index(payload: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in payload.get("nodes") or []:
        if not isinstance(row, Mapping):
            continue
        key = (str(row.get("county") or "").strip(), str(row.get("township") or "").strip())
        if not all(key):
            continue
        if key in result:
            raise ValueError("observed_station_dataset_duplicate_graph_node:" + "|".join(key))
        result[key] = row
    return result


def _load_tap_support(downloaded: Path, stations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not downloaded.is_dir():
        raise FileNotFoundError(f"TAP downloaded directory not found: {downloaded}")
    nearest = {
        str(station["station_id"]): {
            "tile_id": None,
            "grid_id": None,
            "grid_longitude": None,
            "grid_latitude": None,
            "distance_degrees": float("inf"),
        }
        for station in stations
    }
    for path in sorted(downloaded.glob("Tile_*_lonlat.csv.zip")):
        match = re.search(r"Tile_(\d{3})_lonlat", path.name)
        if not match:
            continue
        tile_id = match.group(1)
        for grid in _read_csv_zip(path):
            grid_id = str(grid.get("GridID") or "").strip()
            longitude = _optional_float(grid.get("Longitude"))
            latitude = _optional_float(grid.get("Latitude"))
            if not grid_id or longitude is None or latitude is None:
                continue
            for station in stations:
                station_id = str(station["station_id"])
                distance = math.hypot(
                    longitude - float(station["longitude"]),
                    latitude - float(station["latitude"]),
                )
                if distance < nearest[station_id]["distance_degrees"]:
                    nearest[station_id] = {
                        "tile_id": tile_id,
                        "grid_id": grid_id,
                        "grid_longitude": longitude,
                        "grid_latitude": latitude,
                        "distance_degrees": distance,
                    }
    if any(row["grid_id"] is None for row in nearest.values()):
        raise ValueError("observed_station_dataset_tap_grid_assignment_incomplete")

    grid_to_stations: dict[tuple[str, str], list[str]] = defaultdict(list)
    for station_id, row in nearest.items():
        grid_to_stations[(str(row["tile_id"]), str(row["grid_id"]))].append(station_id)
    values: dict[tuple[str, date], float] = {}
    for path in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})", path.name)
        if not match:
            continue
        year, day_of_year, tile_id = match.groups()
        wanted = {
            grid_id: station_ids
            for (candidate_tile, grid_id), station_ids in grid_to_stations.items()
            if candidate_tile == tile_id
        }
        if not wanted:
            continue
        value_date = datetime.strptime(f"{year} {day_of_year}", "%Y %j").date()
        for grid in _read_csv_zip(path):
            grid_id = str(grid.get("GridID") or "").strip()
            if grid_id not in wanted:
                continue
            value = _optional_float(grid.get("PM2.5"))
            if value is not None:
                for station_id in wanted[grid_id]:
                    values[(station_id, value_date)] = value
    return {"stations": nearest, "values": values}


def _read_csv_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as handle:
        names = [name for name in handle.namelist() if name.lower().endswith(".csv")]
        if not names:
            return []
        with handle.open(names[0]) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig")))


def _measurement_start(row: Mapping[str, Any]) -> datetime | None:
    period = row.get("period")
    period = period if isinstance(period, Mapping) else {}
    value = period.get("datetimeFrom") or row.get("datetime")
    if isinstance(value, Mapping):
        value = value.get("utc") or value.get("local")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _normalize_parameter(row: Mapping[str, Any]) -> str:
    parameter = row.get("parameter")
    value = parameter.get("name") if isinstance(parameter, Mapping) else parameter
    return str(value or "").strip().lower().replace(".", "").replace("_", "")


def _finite_float(value: Any) -> float:
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError("finite_numeric_value_required")
    return number


def _optional_float(value: Any) -> float | None:
    try:
        return _finite_float(value)
    except (TypeError, ValueError):
        return None


def _unique_strings(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
