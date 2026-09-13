"""Station-aligned air-quality holdout evidence for UWM."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA = (
    "uwm.station_aligned_air_quality_holdout.v1"
)


def build_uwm_station_aligned_air_quality_holdout(
    *,
    openaq_measurements_path: str | Path,
    openaq_station_proxy_path: str | Path,
    openaq_scene_attempt_path: str | Path,
    tap_root: str | Path,
    holdout_id: str,
    created_at: str,
    train_fraction: float = 0.7,
) -> dict[str, Any]:
    """Build historical station-aligned PM2.5 validation from real OpenAQ and TAP data."""

    measurements_path = Path(openaq_measurements_path)
    station_proxy_path = Path(openaq_station_proxy_path)
    scene_attempt_path = Path(openaq_scene_attempt_path)
    tap_period = Path(tap_root) / "chongqing_pm25_2018_10_17_23"
    station_proxy = _read_json(station_proxy_path)
    scene_attempt = _read_json(scene_attempt_path)
    nearest_station = station_proxy.get("nearest_station") or {}
    station_lon = _float(nearest_station.get("longitude"))
    station_lat = _float(nearest_station.get("latitude"))
    if station_lon is None or station_lat is None:
        raise ValueError("OpenAQ station proxy must include nearest_station longitude and latitude")
    station_rows = _load_openaq_pm25_station_rows(measurements_path)
    nearest_grid = _nearest_tap_grid(tap_period / "downloaded", station_lon, station_lat)
    tap_daily = _load_tap_daily_grid_values(
        tap_period / "downloaded",
        tile_id=nearest_grid["tile_id"],
        grid_id=nearest_grid["grid_id"],
    )
    aligned_rows = [
        {
            "timestamp_utc": row["timestamp_utc"],
            "station_pm25": row["value"],
            "tap_pm25": tap_daily[row["timestamp_utc"].date()],
        }
        for row in station_rows
        if row["timestamp_utc"].date() in tap_daily
    ]
    benchmark = _holdout_benchmark(aligned_rows, train_fraction=train_fraction)
    historical_ready = (
        benchmark["holdout_count"] >= 20
        and benchmark["raw_tap_beats_static_station_baselines"] is True
    )
    scene_counts = scene_attempt.get("record_counts") or {}
    scene_measurements = _int(scene_counts.get("measurements"))
    scene_ready = bool(scene_attempt.get("scene_holdout_ready")) and scene_measurements > 0
    limitations = [
        "scene_station_measurements_missing",
        "historical_2018_validation_not_2024_scene_holdout",
        "tap_gridded_product_not_station_observation",
        "not_policy_intervention_outcome",
    ]
    return {
        "schema": UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA,
        "holdout_id": holdout_id,
        "created_at": created_at,
        "source_artifacts": {
            "openaq_measurements": str(measurements_path),
            "openaq_station_proxy": str(station_proxy_path),
            "openaq_scene_attempt": str(scene_attempt_path),
            "tap_period_root": str(tap_period),
        },
        "source_dataset_ids": [
            "openaq_air_quality_station_observation_proxy",
            "tap_pm25_observed_gridded_chongqing_2018_2024",
        ],
        "station_alignment": {
            "station_id": nearest_station.get("id"),
            "station_name": nearest_station.get("name"),
            "station_longitude": station_lon,
            "station_latitude": station_lat,
            "station_observation_count": len(station_rows),
            "tap_aligned_observation_count": len(aligned_rows),
            "nearest_tap_tile_id": nearest_grid["tile_id"],
            "nearest_tap_grid_id": nearest_grid["grid_id"],
            "nearest_tap_grid_longitude": _round(nearest_grid["longitude"]),
            "nearest_tap_grid_latitude": _round(nearest_grid["latitude"]),
            "nearest_tap_grid_distance_m": _round(nearest_grid["distance_m"]),
        },
        "holdout_benchmark": benchmark,
        "scene_attempt_evidence": {
            "scene_time_range": scene_attempt.get("scene_time_range") or {},
            "scene_station_measurement_count": scene_measurements,
            "scene_holdout_ready": scene_ready,
        },
        "historical_station_aligned_holdout_ready": historical_ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": _supported_claims(historical_ready),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if historical_ready else "not_for_claim",
            "policy_outcome_claim": False,
            "rule": (
                "Historical OpenAQ station observations can validate station-aligned TAP PM2.5 "
                "against static station baselines; zero 2024 scene OpenAQ measurements means this "
                "does not close the scene-aligned station-calibrated holdout gate."
            ),
        },
        "limitations": limitations,
        "remaining_gates": [
            "scene_aligned_station_calibrated_air_quality_holdout_required",
            "observed_policy_outcome_required",
        ],
    }


def validate_uwm_station_aligned_air_quality_holdout(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate station-aligned holdout claim boundaries."""

    errors: list[str] = []
    if payload.get("schema") != UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    if payload.get("scene_aligned_station_calibrated_air_quality_holdout_ready") is not False:
        errors.append("scene_aligned_station_calibrated_ready_must_be_false")
    if payload.get("historical_station_aligned_holdout_ready"):
        benchmark = payload.get("holdout_benchmark") or {}
        if benchmark.get("raw_tap_beats_static_station_baselines") is not True:
            errors.append("historical_ready_requires_raw_tap_static_baseline_advantage")
        if _float(benchmark.get("raw_tap_mae"), default=float("inf")) >= _float(
            benchmark.get("static_train_mean_mae"), default=0.0
        ):
            errors.append("raw_tap_mae_must_be_below_static_train_mean")
    for claim in payload.get("supported_claims") or []:
        if claim.get("policy_outcome_claim") is not False:
            errors.append("supported_claim_policy_outcome_must_be_false")
    for limitation in [
        "scene_station_measurements_missing",
        "historical_2018_validation_not_2024_scene_holdout",
    ]:
        if limitation not in (payload.get("limitations") or []):
            errors.append(f"{limitation}_limitation_required")
    return {"valid": not errors, "errors": errors}


def _load_openaq_pm25_station_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    rows: list[dict[str, Any]] = []
    for sensor_payload in payload.values():
        for row in sensor_payload.get("results") or []:
            if (row.get("parameter") or {}).get("name") != "pm25":
                continue
            timestamp = ((row.get("period") or {}).get("datetimeFrom") or {}).get("utc")
            value = _float(row.get("value"))
            if timestamp and value is not None:
                rows.append(
                    {
                        "timestamp_utc": datetime.fromisoformat(
                            timestamp.replace("Z", "+00:00")
                        ),
                        "value": value,
                    }
                )
    rows.sort(key=lambda item: item["timestamp_utc"])
    return rows


def _nearest_tap_grid(downloaded: Path, station_lon: float, station_lat: float) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for tile_file in sorted(downloaded.glob("Tile_*_lonlat.csv.zip")):
        match = re.search(r"Tile_(\d{3})_lonlat", tile_file.name)
        if not match:
            continue
        tile_id = match.group(1)
        for row in _read_single_csv_zip(tile_file):
            grid_id = str(row.get("GridID") or "").strip()
            lon = _float(row.get("Longitude"))
            lat = _float(row.get("Latitude"))
            if not grid_id or lon is None or lat is None:
                continue
            distance_m = _haversine_m(station_lon, station_lat, lon, lat)
            if best is None or distance_m < best["distance_m"]:
                best = {
                    "tile_id": tile_id,
                    "grid_id": grid_id,
                    "longitude": lon,
                    "latitude": lat,
                    "distance_m": distance_m,
                }
    if best is None:
        raise ValueError(f"no TAP lon/lat grid found under {downloaded}")
    return best


def _load_tap_daily_grid_values(
    downloaded: Path,
    *,
    tile_id: str,
    grid_id: str,
) -> dict[Any, float]:
    values = {}
    pattern = f"China_PM25_1km_*_{tile_id}.csv.zip"
    for pm_file in sorted(downloaded.glob(pattern)):
        match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})", pm_file.name)
        if not match:
            continue
        year = int(match.group(1))
        doy = int(match.group(2))
        for row in _read_single_csv_zip(pm_file):
            if str(row.get("GridID") or "").strip() != grid_id:
                continue
            pm25 = _float(row.get("PM2.5"))
            if pm25 is not None:
                values[datetime.strptime(f"{year} {doy}", "%Y %j").date()] = pm25
            break
    return values


def _holdout_benchmark(rows: list[dict[str, Any]], *, train_fraction: float) -> dict[str, Any]:
    if len(rows) < 4:
        raise ValueError("station-aligned holdout requires at least 4 aligned observations")
    split = max(2, min(len(rows) - 1, int(len(rows) * train_fraction)))
    train = rows[:split]
    holdout = rows[split:]
    train_y = [row["station_pm25"] for row in train]
    train_x = [row["tap_pm25"] for row in train]
    intercept, slope = _linear_fit(train_x, train_y)
    raw_tap_mae = _mae(
        (row["station_pm25"] for row in holdout),
        (row["tap_pm25"] for row in holdout),
    )
    calibrated_mae = _mae(
        (row["station_pm25"] for row in holdout),
        (intercept + slope * row["tap_pm25"] for row in holdout),
    )
    train_mean = sum(train_y) / len(train_y)
    last_observation = train_y[-1]
    static_mean_mae = _mae(
        (row["station_pm25"] for row in holdout),
        (train_mean for _ in holdout),
    )
    static_last_mae = _mae(
        (row["station_pm25"] for row in holdout),
        (last_observation for _ in holdout),
    )
    raw_beats_static = raw_tap_mae < static_mean_mae and raw_tap_mae < static_last_mae
    candidate_maes = {
        "raw_tap_nearest_grid": raw_tap_mae,
        "linear_station_calibrated_tap": calibrated_mae,
        "static_train_mean": static_mean_mae,
        "static_last_observation": static_last_mae,
    }
    return {
        "train_count": len(train),
        "holdout_count": len(holdout),
        "train_fraction": train_fraction,
        "linear_calibration_intercept": _round(intercept),
        "linear_calibration_slope": _round(slope),
        "raw_tap_mae": _round(raw_tap_mae),
        "linear_station_calibrated_tap_mae": _round(calibrated_mae),
        "static_train_mean_mae": _round(static_mean_mae),
        "static_last_observation_mae": _round(static_last_mae),
        "best_station_aligned_method": min(candidate_maes, key=candidate_maes.get),
        "raw_tap_beats_static_station_baselines": raw_beats_static,
        "linear_calibration_beats_raw_tap": calibrated_mae < raw_tap_mae,
    }


def _supported_claims(historical_ready: bool) -> list[dict[str, Any]]:
    if not historical_ready:
        return []
    return [
        {
            "claim": "historical_station_aligned_tap_pm25_beats_static_station_baselines",
            "scope": "historical_2018_station_aligned_pm25_holdout_not_2024_scene",
            "claim_level": "bounded_support",
            "policy_outcome_claim": False,
            "scene_aligned_claim": False,
        }
    ]


def _read_single_csv_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as handle:
        names = [name for name in handle.namelist() if name.lower().endswith(".csv")]
        if not names:
            return []
        with handle.open(names[0]) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig")))


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return mean_y, 0.0
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = covariance / variance
    return mean_y - slope * mean_x, slope


def _mae(actual_values: Any, predicted_values: Any) -> float:
    pairs = list(zip(actual_values, predicted_values))
    return sum(abs(actual - predicted) for actual, predicted in pairs) / len(pairs)


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        d_lambda / 2
    ) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _float(value: Any, default: float | None = None) -> float | None:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _round(value: float | None, digits: int = 6) -> float:
    return round(float(value or 0.0), digits)
