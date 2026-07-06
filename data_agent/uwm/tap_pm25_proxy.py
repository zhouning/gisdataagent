"""TAP observed gridded PM2.5 proxy parsing for UWM."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from statistics import fmean
from typing import Any


TAP_PM25_PROXY_SCHEMA = "uwm.tap_pm25_proxy.v1"
TAP_PM25_OBSERVED_DATASET_ID = "tap_pm25_observed_gridded_chongqing_2018_2024"
TAP_PM25_SOURCE_DATASET_IDS = [TAP_PM25_OBSERVED_DATASET_ID]
TAP_PM25_LIMITATIONS = [
    "tap_gridded_multisource_fusion_product_not_station_observation",
    "not_policy_intervention_outcome",
    "tap_terms_noncommercial_no_redistribution",
]


def build_tap_pm25_proxy(
    *,
    tap_root: str | Path,
    proxy_id: str,
    created_at: str,
    include_records: bool = False,
    max_records_per_period: int | None = None,
) -> dict[str, Any]:
    root = Path(tap_root)
    if not root.exists():
        raise FileNotFoundError(f"TAP root not found: {root}")

    periods = [_summarise_1km_period(path, include_records, max_records_per_period) for path in _period_dirs(root)]
    if not periods:
        raise ValueError(f"no TAP 1km period directories found under {root}")
    species = _summarise_species_zip(root / "d07f3d.zip")
    total_rows = sum(period["pm_total_rows"] for period in periods)
    valid_rows = sum(period["pm25_summary"]["count"] for period in periods)

    return {
        "schema": TAP_PM25_PROXY_SCHEMA,
        "version": "0.1",
        "proxy_id": proxy_id,
        "created_at": created_at,
        "source_dataset_ids": TAP_PM25_SOURCE_DATASET_IDS,
        "source_root": str(root),
        "periods_1km": periods,
        "species_10km": species,
        "record_counts": {
            "periods_1km": len(periods),
            "pm25_1km_rows": total_rows,
            "valid_pm25_1km_rows": valid_rows,
            "species_10km_rows": species["record_count"],
        },
        "coverage": {
            "spatial_projection": "EPSG:4326",
            "grid_resolution": {"pm25_1km": "1 km", "species_10km": "10 km"},
            "pm25_1km_extent": _combined_extent([period["joined_extent"] for period in periods]),
        },
        "summary": {
            "pm25_1km": _combine_summaries([period["pm25_summary"] for period in periods]),
            "species_10km_pm25": species["overall_metrics"].get("PM2.5"),
        },
        "synthetic_flags": [{"dataset_id": TAP_PM25_OBSERVED_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "TAP PM2.5 is a gridded multisource retrieval/fusion product suitable for "
                "bounded air-pollution exposure and temporal state-prediction evidence; it is "
                "not a station-observed policy intervention outcome."
            ),
        },
        "limitations": list(TAP_PM25_LIMITATIONS),
        "empirical_superiority_claim": False,
    }


def validate_tap_pm25_proxy(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TAP_PM25_PROXY_SCHEMA:
        errors.append(f"schema must be {TAP_PM25_PROXY_SCHEMA}")
    for key in [
        "proxy_id",
        "source_dataset_ids",
        "periods_1km",
        "species_10km",
        "record_counts",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false for TAP proxy")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("limitations must include not_policy_intervention_outcome")
    return {"valid": not errors, "errors": errors}


def _period_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("chongqing_pm25_"))


def _summarise_1km_period(path: Path, include_records: bool, max_records: int | None) -> dict[str, Any]:
    downloaded = path / "downloaded"
    if not downloaded.exists():
        raise ValueError(f"missing downloaded directory: {downloaded}")
    tile_maps, tile_extents = _load_tile_lonlat_maps(downloaded)
    pm_files = sorted(downloaded.glob("China_PM25_1km_*.csv.zip"))
    if not pm_files:
        raise ValueError(f"no TAP PM2.5 files found under {downloaded}")

    values: list[float] = []
    all_lons: list[float] = []
    all_lats: list[float] = []
    sample_records: list[dict[str, Any]] = []
    join_missing = 0
    missing_values = 0
    total_rows = 0
    years: set[str] = set()
    doys: set[str] = set()
    tiles: set[str] = set()
    row_counts: list[int] = []
    for pm_file in pm_files:
        year, doy, tile_id = _parse_pm25_filename(pm_file)
        if tile_id not in tile_maps:
            raise ValueError(f"missing lon/lat tile {tile_id} for {pm_file.name}")
        years.add(year)
        doys.add(doy)
        tiles.add(tile_id)
        rows = 0
        for row in _read_single_csv_zip(pm_file):
            _require_columns(row, ["GridID", "PM2.5"], pm_file.name)
            rows += 1
            total_rows += 1
            grid_id = str(row.get("GridID") or "").strip()
            pm25 = _float(row.get("PM2.5"))
            xy = tile_maps[tile_id].get(grid_id)
            if xy is None:
                join_missing += 1
                continue
            lon, lat = xy
            all_lons.append(lon)
            all_lats.append(lat)
            if pm25 is None:
                missing_values += 1
                continue
            values.append(pm25)
            if include_records and (max_records is None or len(sample_records) < max_records):
                sample_records.append(
                    {
                        "period_id": path.name,
                        "year": year,
                        "doy": doy,
                        "tile_id": tile_id,
                        "grid_id": grid_id,
                        "longitude": _round(lon),
                        "latitude": _round(lat),
                        "pm25_ugm3": _round(pm25),
                    }
                )
        row_counts.append(rows)
    if join_missing:
        raise ValueError(f"{path.name} has {join_missing} PM2.5 rows without lon/lat coordinates")

    result = {
        "period_id": path.name,
        "year": sorted(years)[0] if len(years) == 1 else sorted(years),
        "doy_values": sorted(doys),
        "tile_ids": sorted(tiles),
        "pm_file_count": len(pm_files),
        "tile_lonlat_file_count": len(tile_maps),
        "pm_total_rows": total_rows,
        "pm_missing_values": missing_values,
        "pm_row_count_min": min(row_counts) if row_counts else None,
        "pm_row_count_max": max(row_counts) if row_counts else None,
        "join_missing_row_count": join_missing,
        "pm25_summary": _summary(values),
        "joined_extent": _extent(all_lons, all_lats),
        "tile_extents": dict(sorted(tile_extents.items())),
    }
    if include_records:
        result["sample_records"] = sample_records
    return result


def _load_tile_lonlat_maps(downloaded: Path) -> tuple[dict[str, dict[str, tuple[float, float]]], dict[str, dict[str, Any]]]:
    maps: dict[str, dict[str, tuple[float, float]]] = {}
    extents: dict[str, dict[str, Any]] = {}
    for tile_file in sorted(downloaded.glob("Tile_*_lonlat.csv.zip")):
        match = re.search(r"Tile_(\d{3})_lonlat", tile_file.name)
        if not match:
            continue
        tile_id = match.group(1)
        grid_to_xy: dict[str, tuple[float, float]] = {}
        lons: list[float] = []
        lats: list[float] = []
        for row in _read_single_csv_zip(tile_file):
            _require_columns(row, ["GridID", "Longitude", "Latitude"], tile_file.name)
            grid_id = str(row.get("GridID") or "").strip()
            lon = _float(row.get("Longitude"))
            lat = _float(row.get("Latitude"))
            if not grid_id or lon is None or lat is None:
                continue
            grid_to_xy[grid_id] = (lon, lat)
            lons.append(lon)
            lats.append(lat)
        maps[tile_id] = grid_to_xy
        extents[tile_id] = {"rows": len(grid_to_xy), **_extent(lons, lats)}
    return maps, extents


def _summarise_species_zip(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"file_count": 0, "date_values": [], "record_count": 0, "fields": [], "overall_metrics": {}, "first7_metrics": {}}
    metrics = {column: [] for column in ["PM2.5", "SO4", "NO3", "NH4", "OM", "BC"]}
    first7 = {column: [] for column in metrics}
    lons: list[float] = []
    lats: list[float] = []
    fields: list[str] = []
    dates: list[str] = []
    record_count = 0
    with zipfile.ZipFile(path) as handle:
        for name in sorted(n for n in handle.namelist() if n.lower().endswith(".csv")):
            date = name[:8]
            dates.append(date)
            with handle.open(name) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                fields = list(reader.fieldnames or fields)
                for row in reader:
                    record_count += 1
                    lon = _float(row.get("X_Lon"))
                    lat = _float(row.get("Y_Lat"))
                    if lon is not None:
                        lons.append(lon)
                    if lat is not None:
                        lats.append(lat)
                    for column in metrics:
                        value = _float(row.get(column))
                        if value is None:
                            continue
                        metrics[column].append(value)
                        if date <= "20240707":
                            first7[column].append(value)
    return {
        "file_count": len(dates),
        "date_values": dates,
        "record_count": record_count,
        "fields": fields,
        "overall_extent": _extent(lons, lats),
        "overall_metrics": {column: _summary(values) for column, values in metrics.items()},
        "first7_metrics": {column: _summary(values) for column, values in first7.items()},
    }


def _read_single_csv_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as handle:
        csv_names = [name for name in handle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"expected one CSV in {path}, found {csv_names}")
        with handle.open(csv_names[0]) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def _parse_pm25_filename(path: Path) -> tuple[str, str, str]:
    match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})\.csv\.zip$", path.name)
    if not match:
        raise ValueError(f"unexpected TAP PM2.5 filename: {path.name}")
    return match.group(1), match.group(2), match.group(3)


def _require_columns(row: dict[str, Any], columns: list[str], source: str) -> None:
    for column in columns:
        if column not in row:
            raise ValueError(f"{source} missing required column {column}")


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": len(values), "min": _round(min(values)), "max": _round(max(values)), "mean": _round(fmean(values))}


def _extent(lons: list[float], lats: list[float]) -> dict[str, Any]:
    if not lons or not lats:
        return {"lon_min": None, "lon_max": None, "lat_min": None, "lat_max": None}
    return {"lon_min": _round(min(lons)), "lon_max": _round(max(lons)), "lat_min": _round(min(lats)), "lat_max": _round(max(lats))}


def _combined_extent(extents: list[dict[str, Any]]) -> dict[str, Any]:
    lons_min = [value["lon_min"] for value in extents if value.get("lon_min") is not None]
    lons_max = [value["lon_max"] for value in extents if value.get("lon_max") is not None]
    lats_min = [value["lat_min"] for value in extents if value.get("lat_min") is not None]
    lats_max = [value["lat_max"] for value in extents if value.get("lat_max") is not None]
    return {"lon_min": _round(min(lons_min)), "lon_max": _round(max(lons_max)), "lat_min": _round(min(lats_min)), "lat_max": _round(max(lats_max))}


def _combine_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    count = sum(int(summary["count"]) for summary in summaries)
    if not count:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": count,
        "min": _round(min(summary["min"] for summary in summaries if summary["min"] is not None)),
        "max": _round(max(summary["max"] for summary in summaries if summary["max"] is not None)),
        "mean": _round(sum(summary["mean"] * summary["count"] for summary in summaries) / count),
    }


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
