# UWM TAP Observed Gridded Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real TAP gridded PM2.5 data to UWM and prove a bounded temporal state-prediction advantage over traditional static baselines.

**Architecture:** Add a separate TAP observed-data path beside the existing TAP-like semi-synthetic scaffold. The new path streams local TAP zip files into compact proxy summaries, then builds a deterministic sampled grid-time benchmark with strict claim boundaries.

**Tech Stack:** Python standard library (`csv`, `zipfile`, `json`, `pathlib`, `statistics`), existing UWM package conventions, pytest via `uv run`.

---

## File Structure

- Create `data_agent/uwm/tap_pm25_proxy.py`
  - TAP zip discovery, CSV parsing, GridID lon/lat join validation, 1 km and 10 km summary payloads.
- Create `data_agent/uwm/tap_temporal_benchmark.py`
  - Deterministic sampled grid series, static baselines, online/adaptive UWM state updates, sign tests, negative controls.
- Create `data_agent/test_uwm_tap_pm25_proxy.py`
  - Fixture zip tests for parser, species summaries, schema validation, claim boundary.
- Create `data_agent/test_uwm_tap_gridded_temporal_benchmark.py`
  - Fixture zip tests for benchmark math and policy-outcome claim guard.
- Create `scripts/build_uwm_tap_pm25_proxy.py`
  - Runs parser and benchmark against `/Users/zhouning/Downloads/tap_uwm`; writes snapshot artifacts.
- Modify `data_agent/uwm/__init__.py`
  - Export TAP schemas and builders if existing UWM package pattern requires it.
- Modify UWM reports after artifacts are generated:
  - `docs/reports/uwm_data_foundation_manifest.csv`
  - `docs/reports/uwm_data_foundation_manifest.md`
  - `docs/reports/uwm_data_foundation_coverage_audit.md`
  - `docs/reports/uwm_data_foundation_summary_2026-07-05.md`

---

### Task 1: TAP PM2.5 Proxy Parser

**Files:**
- Create: `data_agent/test_uwm_tap_pm25_proxy.py`
- Create: `data_agent/uwm/tap_pm25_proxy.py`

- [ ] **Step 1: Write the failing parser tests**

Add `data_agent/test_uwm_tap_pm25_proxy.py`:

```python
import csv
import json
import zipfile
from pathlib import Path

import pytest

from data_agent.uwm.tap_pm25_proxy import (
    TAP_PM25_PROXY_SCHEMA,
    build_tap_pm25_proxy,
    validate_tap_pm25_proxy,
)


def test_tap_pm25_proxy_joins_gridid_to_lonlat_and_summarizes_periods(tmp_path):
    tap_root = _write_tap_fixture(tmp_path)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="tap-fixture",
        created_at="2026-07-06T00:00:00Z",
        include_records=True,
        max_records_per_period=10,
    )

    validation = validate_tap_pm25_proxy(proxy)
    assert validation["valid"], validation["errors"]
    assert proxy["schema"] == TAP_PM25_PROXY_SCHEMA
    assert proxy["proxy_id"] == "tap-fixture"
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "tap_pm25_observed_gridded_chongqing_2018_2024", "status": "public_proxy"}
    ]
    assert proxy["empirical_superiority_claim"] is False
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "not_policy_intervention_outcome" in proxy["limitations"]

    period = proxy["periods_1km"][0]
    assert period["period_id"] == "chongqing_pm25_2024_07_01_07"
    assert period["year"] == "2024"
    assert period["doy_values"] == ["183", "184"]
    assert period["tile_ids"] == ["074", "075"]
    assert period["pm_file_count"] == 4
    assert period["tile_lonlat_file_count"] == 2
    assert period["join_missing_row_count"] == 0
    assert period["pm25_summary"] == {"count": 8, "min": 10.0, "max": 23.0, "mean": 16.5}
    assert period["joined_extent"] == {
        "lon_min": 103.0,
        "lon_max": 106.1,
        "lat_min": 29.0,
        "lat_max": 29.1,
    }
    assert len(period["sample_records"]) == 8
    assert period["sample_records"][0] == {
        "period_id": "chongqing_pm25_2024_07_01_07",
        "year": "2024",
        "doy": "183",
        "tile_id": "074",
        "grid_id": "1",
        "longitude": 103.0,
        "latitude": 29.0,
        "pm25_ugm3": 10.0,
    }


def test_tap_pm25_proxy_parses_species_zip(tmp_path):
    tap_root = _write_tap_fixture(tmp_path)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="tap-fixture",
        created_at="2026-07-06T00:00:00Z",
    )

    species = proxy["species_10km"]
    assert species["file_count"] == 2
    assert species["date_values"] == ["20240701", "20240702"]
    assert species["fields"] == ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"]
    assert species["overall_extent"] == {
        "lon_min": 108.75,
        "lon_max": 108.85,
        "lat_min": 28.25,
        "lat_max": 28.35,
    }
    assert species["overall_metrics"]["PM2.5"] == {"count": 4, "min": 15.0, "max": 18.0, "mean": 16.5}
    assert species["first7_metrics"]["BC"] == {"count": 4, "min": 0.5, "max": 0.8, "mean": 0.65}


def test_tap_pm25_proxy_raises_on_missing_lonlat_join(tmp_path):
    tap_root = _write_tap_fixture(tmp_path, omit_lonlat_for_tile="075")

    with pytest.raises(ValueError, match="missing lon/lat tile"):
        build_tap_pm25_proxy(
            tap_root=tap_root,
            proxy_id="tap-fixture",
            created_at="2026-07-06T00:00:00Z",
        )


def _write_tap_fixture(tmp_path: Path, omit_lonlat_for_tile: str | None = None) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)

    lonlat_by_tile = {
        "074": [
            {"GridID": "1", "Longitude": "103.0", "Latitude": "29.0", "TileID": "74"},
            {"GridID": "2", "Longitude": "103.1", "Latitude": "29.1", "TileID": "74"},
        ],
        "075": [
            {"GridID": "3", "Longitude": "106.0", "Latitude": "29.0", "TileID": "75"},
            {"GridID": "4", "Longitude": "106.1", "Latitude": "29.1", "TileID": "75"},
        ],
    }
    pm25_by_day_tile = {
        ("183", "074"): [("1", "10"), ("2", "11")],
        ("183", "075"): [("3", "12"), ("4", "13")],
        ("184", "074"): [("1", "20"), ("2", "21")],
        ("184", "075"): [("3", "22"), ("4", "23")],
    }
    for tile_id, rows in lonlat_by_tile.items():
        if tile_id == omit_lonlat_for_tile:
            continue
        _write_csv_zip(
            downloaded / f"Tile_{tile_id}_lonlat.csv.zip",
            f"Tile_{tile_id}_lonlat.csv",
            ["Longitude", "Latitude", "GridID", "TileID"],
            rows,
        )
    for (doy, tile_id), pairs in pm25_by_day_tile.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_{tile_id}.csv.zip",
            f"China_PM25_1km_2024_{doy}_{tile_id}.csv",
            ["GridID", "PM2.5"],
            [{"GridID": grid_id, "PM2.5": value} for grid_id, value in pairs],
        )

    _write_species_zip(tap_root / "d07f3d.zip")
    return tap_root


def _write_species_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        rows_by_name = {
            "20240701_PM25_and_species.csv": [
                ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"],
                ["1", "108.75", "28.25", "15", "1", "2", "3", "4", "0.5"],
                ["2", "108.85", "28.25", "16", "2", "3", "4", "5", "0.6"],
            ],
            "20240702_PM25_and_species.csv": [
                ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"],
                ["1", "108.75", "28.35", "17", "3", "4", "5", "6", "0.7"],
                ["2", "108.85", "28.35", "18", "4", "5", "6", "7", "0.8"],
            ],
        }
        for name, rows in rows_by_name.items():
            handle.writestr(name, "\n".join(",".join(row) for row in rows) + "\n")
        handle.writestr("readme.txt", "fixture")


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    lines = [",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(str(row.get(field, "")) for field in fieldnames))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_pm25_proxy.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'data_agent.uwm.tap_pm25_proxy'`.

- [ ] **Step 3: Implement the TAP parser**

Create `data_agent/uwm/tap_pm25_proxy.py` with:

```python
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
```

- [ ] **Step 4: Run parser tests to verify they pass**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_pm25_proxy.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit parser work**

Run:

```bash
git add data_agent/test_uwm_tap_pm25_proxy.py data_agent/uwm/tap_pm25_proxy.py
git commit -m "feat: parse tap observed pm25 proxy"
```

Expected: commit includes only the two TAP parser files.

---

### Task 2: TAP Gridded Temporal Benchmark

**Files:**
- Create: `data_agent/test_uwm_tap_gridded_temporal_benchmark.py`
- Create: `data_agent/uwm/tap_temporal_benchmark.py`

- [ ] **Step 1: Write the failing benchmark tests**

Add `data_agent/test_uwm_tap_gridded_temporal_benchmark.py`:

```python
import zipfile
from pathlib import Path

from data_agent.uwm.tap_temporal_benchmark import (
    TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA,
    build_tap_gridded_temporal_benchmark,
    validate_tap_gridded_temporal_benchmark,
)


def test_tap_benchmark_online_state_update_beats_static_baselines(tmp_path):
    tap_root = _write_benchmark_fixture(tmp_path)

    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="tap-benchmark-fixture",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=10,
    )

    validation = validate_tap_gridded_temporal_benchmark(benchmark)
    assert validation["valid"], validation["errors"]
    assert benchmark["schema"] == TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA
    assert benchmark["benchmark_id"] == "tap-benchmark-fixture"
    assert benchmark["traditional_baseline_suite"] == [
        "static_train_mean",
        "static_last_train_observation",
        "period_static_mean",
    ]
    assert benchmark["uwm_state_update_suite"] == [
        "online_persistence_state_update",
        "adaptive_online_state_update",
    ]
    assert benchmark["overall_results"]["series_count"] == 2
    assert benchmark["overall_results"]["holdout_count"] == 6
    assert benchmark["overall_results"]["best_uwm_method"] == "online_persistence_state_update"
    assert benchmark["overall_results"]["best_uwm_mae"] == 8.333333
    assert benchmark["overall_results"]["best_static_baseline_mae"] == 25.0
    assert benchmark["overall_results"]["best_uwm_mae_reduction"] == 16.666667
    assert benchmark["overall_results"]["beats_all_traditional_static_baselines"] is True
    assert benchmark["supported_claim"] == "tap_gridded_temporal_state_prediction_advantage_over_static_baseline"
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_tap_benchmark_keeps_policy_outcome_claim_false(tmp_path):
    tap_root = _write_benchmark_fixture(tmp_path)

    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="tap-benchmark-fixture",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=10,
    )

    assert benchmark["empirical_superiority_claim"] is False
    assert benchmark["observed_policy_outcome_superiority_claim"] is False
    assert "not_policy_intervention_outcome" in benchmark["limitations"]
    assert "tap_gridded_product_not_station_observation" in benchmark["limitations"]


def _write_benchmark_fixture(tmp_path: Path) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)
    _write_csv_zip(
        downloaded / "Tile_074_lonlat.csv.zip",
        "Tile_074_lonlat.csv",
        ["Longitude", "Latitude", "GridID", "TileID"],
        [
            ["103.0", "29.0", "1", "74"],
            ["103.1", "29.1", "2", "74"],
        ],
    )
    values_by_doy = {
        "183": ["10", "20"],
        "184": ["10", "20"],
        "185": ["10", "20"],
        "186": ["40", "50"],
        "187": ["41", "51"],
        "188": ["42", "52"],
    }
    for doy, values in values_by_doy.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_074.csv.zip",
            f"China_PM25_1km_2024_{doy}_074.csv",
            ["GridID", "PM2.5"],
            [["1", values[0]], ["2", values[1]]],
        )
    return tap_root


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(fieldnames)]
    lines.extend(",".join(row) for row in rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_gridded_temporal_benchmark.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'data_agent.uwm.tap_temporal_benchmark'`.

- [ ] **Step 3: Implement the TAP benchmark**

Create `data_agent/uwm/tap_temporal_benchmark.py` with:

```python
"""TAP gridded temporal state-prediction benchmark for UWM."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from math import comb
from pathlib import Path
from statistics import fmean
from typing import Any


TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA = "uwm.tap_gridded_temporal_benchmark.v1"
TRADITIONAL_STATIC_BASELINE_SUITE = [
    "static_train_mean",
    "static_last_train_observation",
    "period_static_mean",
]
UWM_STATE_UPDATE_SUITE = [
    "online_persistence_state_update",
    "adaptive_online_state_update",
]


def build_tap_gridded_temporal_benchmark(
    *,
    tap_root: str | Path,
    benchmark_id: str,
    created_at: str,
    train_days: int = 3,
    max_grid_series_per_period: int = 5000,
) -> dict[str, Any]:
    root = Path(tap_root)
    if not root.exists():
        raise FileNotFoundError(f"TAP root not found: {root}")
    period_results = [
        _benchmark_period(path, train_days=train_days, max_series=max_grid_series_per_period)
        for path in _period_dirs(root)
    ]
    period_results = [result for result in period_results if result["series_count"] > 0]
    if not period_results:
        raise ValueError("no benchmarkable TAP grid series found")
    overall = _overall_results(period_results)
    return {
        "schema": TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA,
        "version": "0.1",
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "source_dataset_ids": ["tap_pm25_observed_gridded_chongqing_2018_2024"],
        "traditional_baseline_suite": TRADITIONAL_STATIC_BASELINE_SUITE,
        "uwm_state_update_suite": UWM_STATE_UPDATE_SUITE,
        "state_update_parameters": {"adaptive_online_state_update_alpha": 0.7},
        "period_results": period_results,
        "overall_results": overall,
        "overall_sign_tests": _overall_sign_tests(period_results),
        "temporal_order_negative_control_summary": _negative_control_summary(period_results),
        "supported_claim": (
            "tap_gridded_temporal_state_prediction_advantage_over_static_baseline"
            if overall["beats_all_traditional_static_baselines"]
            else "no_tap_gridded_temporal_state_prediction_advantage_claim"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if overall["beats_all_traditional_static_baselines"] else "not_for_claim",
            "reason": (
                "TAP gridded PM2.5 supports temporal state-prediction comparison over static baselines; "
                "it is not a station-observed policy intervention outcome benchmark."
            ),
        },
        "limitations": [
            "tap_gridded_product_not_station_observation",
            "not_policy_intervention_outcome",
            "short_daily_holdout_window",
            "sampled_grid_series_for_runtime_control",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_tap_gridded_temporal_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA:
        errors.append(f"schema must be {TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA}")
    for key in ["benchmark_id", "period_results", "overall_results", "claim_boundary", "limitations"]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false for TAP temporal benchmark")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must stay false")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("limitations must include not_policy_intervention_outcome")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _benchmark_period(path: Path, *, train_days: int, max_series: int) -> dict[str, Any]:
    series = _load_period_series(path)
    selected_keys = sorted(series)[:max_series]
    selected = {key: series[key] for key in selected_keys}
    period_train_values = [
        row["value"]
        for rows in selected.values()
        for row in sorted(rows, key=lambda item: item["doy"])[:train_days]
    ]
    period_train_mean = fmean(period_train_values) if period_train_values else 0.0
    series_results = []
    for key, rows in selected.items():
        result = _benchmark_series(key, sorted(rows, key=lambda item: item["doy"]), train_days, period_train_mean)
        if result:
            series_results.append(result)
    return _period_result(path.name, series_results)


def _load_period_series(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    downloaded = path / "downloaded"
    series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pm_file in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        year, doy, tile_id = _parse_pm25_filename(pm_file)
        for row in _read_single_csv_zip(pm_file):
            grid_id = str(row.get("GridID") or "").strip()
            value = _float(row.get("PM2.5"))
            if not grid_id or value is None:
                continue
            series[(tile_id, grid_id)].append({"year": year, "doy": doy, "value": value})
    return series


def _benchmark_series(
    key: tuple[str, str],
    rows: list[dict[str, Any]],
    train_days: int,
    period_train_mean: float,
) -> dict[str, Any]:
    if len(rows) <= train_days:
        return {}
    train = rows[:train_days]
    holdout = rows[train_days:]
    train_values = [row["value"] for row in train]
    holdout_values = [row["value"] for row in holdout]
    online_predictions = [train_values[-1]] + holdout_values[:-1]
    adaptive_predictions = _adaptive_predictions(train_values, holdout_values, alpha=0.7)
    online_errors = _errors(holdout_values, online_predictions)
    adaptive_errors = _errors(holdout_values, adaptive_predictions)
    baselines = _baseline_suite(train_values, holdout_values, period_train_mean, online_errors)
    online_mae = _mean(online_errors)
    adaptive_mae = _mean(adaptive_errors)
    best_uwm_method = "online_persistence_state_update" if online_mae <= adaptive_mae else "adaptive_online_state_update"
    best_uwm_errors = online_errors if best_uwm_method == "online_persistence_state_update" else adaptive_errors
    best_static = min(baselines.values(), key=lambda item: item["mae"])
    return {
        "tile_id": key[0],
        "grid_id": key[1],
        "observation_count": len(rows),
        "train_count": len(train),
        "holdout_count": len(holdout),
        "time_range": {"start_doy": rows[0]["doy"], "end_doy": rows[-1]["doy"]},
        "uwm_state_updates": {
            "online_persistence_state_update": {
                "mae": _round(online_mae),
                "uses_prior_holdout_observations_online": True,
                "uses_current_or_future_holdout_labels": False,
            },
            "adaptive_online_state_update": {
                "mae": _round(adaptive_mae),
                "alpha": 0.7,
                "uses_prior_holdout_observations_online": True,
                "uses_current_or_future_holdout_labels": False,
            },
        },
        "best_uwm_method": best_uwm_method,
        "best_uwm_mae": _round(_mean(best_uwm_errors)),
        "traditional_static_baseline_suite": baselines,
        "best_traditional_static_baseline": best_static,
        "best_uwm_mae_reduction": _round(best_static["mae"] - _mean(best_uwm_errors)),
        "beats_all_traditional_static_baselines": all(_mean(best_uwm_errors) < row["mae"] for row in baselines.values()),
        "dynamic_sign_tests": {name: _dynamic_sign_test(row["errors"], best_uwm_errors) for name, row in baselines.items()},
        "temporal_order_negative_control": _negative_control(train_values, holdout_values, _mean(best_uwm_errors)),
    }


def _period_result(period_id: str, series_results: list[dict[str, Any]]) -> dict[str, Any]:
    holdout_count = sum(row["holdout_count"] for row in series_results)
    best_uwm_errors = [row["best_uwm_mae"] for row in series_results]
    best_static_errors = [row["best_traditional_static_baseline"]["mae"] for row in series_results]
    return {
        "period_id": period_id,
        "series_count": len(series_results),
        "holdout_count": holdout_count,
        "series_results": series_results,
        "best_uwm_mae": _round(fmean(best_uwm_errors)) if best_uwm_errors else None,
        "best_static_baseline_mae": _round(fmean(best_static_errors)) if best_static_errors else None,
        "beats_all_traditional_static_baselines": bool(series_results) and all(row["beats_all_traditional_static_baselines"] for row in series_results),
    }


def _baseline_suite(train_values: list[float], holdout_values: list[float], period_train_mean: float, dynamic_errors: list[float]) -> dict[str, dict[str, Any]]:
    predictions = {
        "static_train_mean": [fmean(train_values)] * len(holdout_values),
        "static_last_train_observation": [train_values[-1]] * len(holdout_values),
        "period_static_mean": [period_train_mean] * len(holdout_values),
    }
    suite = {}
    for method in TRADITIONAL_STATIC_BASELINE_SUITE:
        errors = _errors(holdout_values, predictions[method])
        suite[method] = {
            "method": method,
            "mae": _round(_mean(errors)),
            "errors": errors,
            "dynamic_mae_reduction": _round(_mean(errors) - _mean(dynamic_errors)),
            "dynamic_win_count": len([1 for static_error, dynamic_error in zip(errors, dynamic_errors) if dynamic_error < static_error]),
        }
    return suite


def _overall_results(period_results: list[dict[str, Any]]) -> dict[str, Any]:
    series_results = [series for period in period_results for series in period["series_results"]]
    best_uwm_method_counts: dict[str, int] = defaultdict(int)
    for series in series_results:
        best_uwm_method_counts[series["best_uwm_method"]] += 1
    best_method = max(best_uwm_method_counts, key=best_uwm_method_counts.get) if best_uwm_method_counts else ""
    best_uwm_maes = [series["best_uwm_mae"] for series in series_results]
    best_static_maes = [series["best_traditional_static_baseline"]["mae"] for series in series_results]
    best_uwm_mae = _round(fmean(best_uwm_maes)) if best_uwm_maes else None
    best_static_mae = _round(fmean(best_static_maes)) if best_static_maes else None
    return {
        "series_count": len(series_results),
        "holdout_count": sum(series["holdout_count"] for series in series_results),
        "best_uwm_method": best_method,
        "best_uwm_mae": best_uwm_mae,
        "best_static_baseline_mae": best_static_mae,
        "best_uwm_mae_reduction": _round(best_static_mae - best_uwm_mae) if best_uwm_mae is not None and best_static_mae is not None else None,
        "beats_all_traditional_static_baselines": bool(series_results) and all(series["beats_all_traditional_static_baselines"] for series in series_results),
    }


def _overall_sign_tests(period_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    series_results = [series for period in period_results for series in period["series_results"]]
    return {
        method: _aggregate_sign_tests([series["dynamic_sign_tests"][method] for series in series_results])
        for method in TRADITIONAL_STATIC_BASELINE_SUITE
    }


def _negative_control_summary(period_results: list[dict[str, Any]]) -> dict[str, Any]:
    controls = [
        series["temporal_order_negative_control"]
        for period in period_results
        for series in period["series_results"]
    ]
    advantage_count = len([control for control in controls if control["ordered_temporal_state_advantage"]])
    return {
        "series_count": len(controls),
        "ordered_advantage_count": advantage_count,
        "ordered_advantage_rate": _round(advantage_count / len(controls)) if controls else 0.0,
    }


def _adaptive_predictions(train_values: list[float], holdout_values: list[float], *, alpha: float) -> list[float]:
    anchor = fmean(train_values)
    previous = train_values[-1]
    predictions = []
    for index, value in enumerate(holdout_values):
        prediction = alpha * previous + (1.0 - alpha) * anchor
        predictions.append(prediction)
        previous = value
    return predictions


def _negative_control(train_values: list[float], holdout_values: list[float], ordered_mae: float) -> dict[str, Any]:
    rotated = _rotate(holdout_values)
    predictions = [train_values[-1]] + rotated[:-1]
    rotated_mae = _mean(_errors(rotated, predictions))
    return {
        "method": "deterministic_holdout_order_rotation",
        "rotated_dynamic_mae": _round(rotated_mae),
        "ordered_dynamic_mae": _round(ordered_mae),
        "ordered_mae_advantage": _round(rotated_mae - ordered_mae),
        "ordered_temporal_state_advantage": rotated_mae > ordered_mae,
    }


def _rotate(values: list[float]) -> list[float]:
    if not values:
        return []
    offset = len(values) // 2
    if offset == 0:
        return list(reversed(values))
    return values[offset:] + values[:offset]


def _errors(values: list[float], predictions: list[float]) -> list[float]:
    return [abs(value - prediction) for value, prediction in zip(values, predictions)]


def _dynamic_sign_test(static_errors: list[float], dynamic_errors: list[float]) -> dict[str, Any]:
    wins = losses = ties = 0
    for static_error, dynamic_error in zip(static_errors, dynamic_errors):
        if dynamic_error < static_error:
            wins += 1
        elif dynamic_error > static_error:
            losses += 1
        else:
            ties += 1
    return _sign_test_result(wins=wins, losses=losses, ties=ties)


def _aggregate_sign_tests(sign_tests: list[dict[str, Any]]) -> dict[str, Any]:
    return _sign_test_result(
        wins=sum(int(test.get("wins", 0)) for test in sign_tests),
        losses=sum(int(test.get("losses", 0)) for test in sign_tests),
        ties=sum(int(test.get("ties", 0)) for test in sign_tests),
    )


def _sign_test_result(*, wins: int, losses: int, ties: int) -> dict[str, Any]:
    effective_n = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "effective_n": effective_n,
        "one_sided_p_value": _one_sided_sign_test_p_value(wins, effective_n),
    }


def _one_sided_sign_test_p_value(wins: int, effective_n: int) -> float:
    if effective_n <= 0:
        return 1.0
    favorable = sum(comb(effective_n, k) for k in range(wins, effective_n + 1))
    return favorable / (2**effective_n)


def _period_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("chongqing_pm25_"))


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


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _round(value: Any) -> float:
    return round(float(value), 6)
```

- [ ] **Step 4: Run benchmark tests to verify they pass**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_gridded_temporal_benchmark.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit benchmark work**

Run:

```bash
git add data_agent/test_uwm_tap_gridded_temporal_benchmark.py data_agent/uwm/tap_temporal_benchmark.py
git commit -m "feat: benchmark tap gridded temporal state updates"
```

Expected: commit includes only the TAP benchmark files.

---

### Task 3: Build Script and Package Exports

**Files:**
- Create: `scripts/build_uwm_tap_pm25_proxy.py`
- Modify: `data_agent/uwm/__init__.py`

- [ ] **Step 1: Write the failing smoke test through direct script invocation**

Run:

```bash
uv run python scripts/build_uwm_tap_pm25_proxy.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06 --max-grid-series-per-period 250
```

Expected: fails because `scripts/build_uwm_tap_pm25_proxy.py` does not exist.

- [ ] **Step 2: Add exports**

Modify `data_agent/uwm/__init__.py` to import and export:

```python
from .tap_pm25_proxy import TAP_PM25_PROXY_SCHEMA, build_tap_pm25_proxy, validate_tap_pm25_proxy
from .tap_temporal_benchmark import (
    TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA,
    build_tap_gridded_temporal_benchmark,
    validate_tap_gridded_temporal_benchmark,
)
```

Add these names to `__all__`:

```python
"TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA",
"TAP_PM25_PROXY_SCHEMA",
"build_tap_gridded_temporal_benchmark",
"build_tap_pm25_proxy",
"validate_tap_gridded_temporal_benchmark",
"validate_tap_pm25_proxy",
```

- [ ] **Step 3: Create builder script**

Create `scripts/build_uwm_tap_pm25_proxy.py`:

```python
"""Build UWM TAP observed gridded PM2.5 proxy and benchmark artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.tap_pm25_proxy import build_tap_pm25_proxy
from data_agent.uwm.tap_temporal_benchmark import build_tap_gridded_temporal_benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM TAP PM2.5 observed gridded artifacts.")
    parser.add_argument("--tap-root", default=str(DEFAULT_TAP_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-grid-series-per-period", type=int, default=5000)
    args = parser.parse_args()

    tap_root = Path(args.tap_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="uwm-tap-pm25-observed-gridded-chongqing-2018-2024",
        created_at="2026-07-06T00:00:00Z",
    )
    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="uwm-tap-gridded-temporal-benchmark-chongqing-2018-2024",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=args.max_grid_series_per_period,
    )
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "tap_pm25_observed_gridded_chongqing_2018_2024",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "source_root": str(tap_root),
        "created_at": "2026-07-06T00:35:00Z",
        "files": {
            "tap_pm25_proxy": "tap_pm25_proxy.json",
            "tap_gridded_temporal_benchmark": "tap_gridded_temporal_benchmark.json",
        },
        "record_counts": proxy["record_counts"],
        "coverage": proxy["coverage"],
        "proxy_summary": proxy["summary"],
        "benchmark_summary": benchmark["overall_results"],
        "claim_boundary": benchmark["claim_boundary"],
        "limitations": sorted(set(proxy["limitations"] + benchmark["limitations"])),
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }

    _write_json(output_dir / "tap_pm25_proxy.json", proxy)
    _write_json(output_dir / "tap_gridded_temporal_benchmark.json", benchmark)
    _write_json(output_dir / "snapshot_manifest.json", manifest)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir),
                "record_counts": proxy["record_counts"],
                "benchmark_summary": benchmark["overall_results"],
                "claim_boundary": benchmark["claim_boundary"],
                "empirical_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run script against local TAP data**

Run:

```bash
uv run python scripts/build_uwm_tap_pm25_proxy.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06 --max-grid-series-per-period 250
```

Expected: writes `tap_pm25_proxy.json`, `tap_gridded_temporal_benchmark.json`, and `snapshot_manifest.json`; stdout contains `benchmark_summary` and `empirical_superiority_claim: false`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_pm25_proxy.py data_agent/test_uwm_tap_gridded_temporal_benchmark.py -q
```

Expected: `5 passed`.

- [ ] **Step 6: Commit script and exports**

Run:

```bash
git add data_agent/uwm/__init__.py scripts/build_uwm_tap_pm25_proxy.py data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06
git commit -m "feat: build tap observed gridded artifacts"
```

Expected: commit includes script, export update, and generated TAP summary/benchmark artifacts, not raw TAP zips.

---

### Task 4: Manifest and Report Updates

**Files:**
- Modify: `docs/reports/uwm_data_foundation_manifest.csv`
- Modify: `docs/reports/uwm_data_foundation_manifest.md`
- Modify: `docs/reports/uwm_data_foundation_coverage_audit.md`
- Modify: `docs/reports/uwm_data_foundation_summary_2026-07-05.md`

- [ ] **Step 1: Add manifest row**

Append this row to `docs/reports/uwm_data_foundation_manifest.csv`:

```csv
tap_pm25_observed_gridded_chongqing_2018_2024,TAP observed gridded PM2.5 for Chongqing 2018 and 2024 windows,public,data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/snapshot_manifest.json;source_root=/Users/zhouning/Downloads/tap_uwm,available,Chongqing municipality and surrounding TAP tile bbox,2018-10-17_to_2018-10-23;2024-07-01_to_2024-07-07;2024-07_species_month,gridded_csv_zip_summary;temporal_benchmark_json,EPSG:4326,TAP_noncommercial_terms_no_redistribution,local TAP package parsed on 2026-07-06;1km PM25 grid tiles join cleanly to lonlat tiles by GridID;10km PM25 species package parsed;temporal benchmark generated with strict no-policy-outcome claim boundary,tap_gridded_fusion_product_not_station_or_policy_outcome,public_proxy,air_pollution_exposure;uwm_air;state_dynamics_validation;mmfe_alignment;evidence_gate,bounded_support
```

- [ ] **Step 2: Update report text**

In the three markdown reports, add a concise section stating:

```text
TAP status update on 2026-07-06: local TAP PM2.5 package is now parsed and registered as
tap_pm25_observed_gridded_chongqing_2018_2024. It strengthens air_pollution_exposure
from TAP-pending to TAP gridded available and supports a bounded gridded temporal
state-prediction benchmark. It does not close the observed policy outcome gate because TAP is
a multisource gridded product, not a station-observed intervention outcome.
```

Also update counts where the reports state manifest row count from `64` to `65`.

- [ ] **Step 3: Verify manifest audit**

Run:

```bash
uv run python - <<'PY'
from data_agent.uwm.data_foundation import audit_uwm_data_foundation_manifest
audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")
print(audit["manifest_valid"] if "manifest_valid" in audit else audit["valid"])
print(audit.get("manifest_errors") or audit.get("errors"))
print(audit.get("manifest_row_count") or audit.get("row_count"))
PY
```

Expected:

```text
True
[]
65
```

- [ ] **Step 4: Run UWM data foundation tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_data_foundation.py data_agent/test_uwm_manifest.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit report updates**

Run:

```bash
git add docs/reports/uwm_data_foundation_manifest.csv docs/reports/uwm_data_foundation_manifest.md docs/reports/uwm_data_foundation_coverage_audit.md docs/reports/uwm_data_foundation_summary_2026-07-05.md
git commit -m "docs: register tap observed gridded foundation"
```

Expected: commit includes only manifest/report updates.

---

### Task 5: Full Verification and Completion Audit

**Files:**
- No new files unless verification reveals a failing test that requires a fix.

- [ ] **Step 1: Run all UWM tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass, including the new TAP tests.

- [ ] **Step 2: Run TAP artifact build at intended sample size**

Run:

```bash
uv run python scripts/build_uwm_tap_pm25_proxy.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06 --max-grid-series-per-period 5000
```

Expected: successful stdout with:

```text
"empirical_superiority_claim": false
"best_uwm_mae_reduction": positive numeric value
```

- [ ] **Step 3: Inspect benchmark JSON claim guard**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path("data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/tap_gridded_temporal_benchmark.json")
payload = json.loads(p.read_text(encoding="utf-8"))
print(payload["supported_claim"])
print(payload["claim_boundary"]["max_claim_level"])
print(payload["observed_policy_outcome_superiority_claim"])
print(payload["empirical_superiority_claim"])
print(payload["overall_results"])
PY
```

Expected:

```text
tap_gridded_temporal_state_prediction_advantage_over_static_baseline
bounded_support
False
False
```

The last printed line must show a positive `best_uwm_mae_reduction`.

- [ ] **Step 4: Check git diff for raw TAP data**

Run:

```bash
git status --short data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06 /Users/zhouning/Downloads/tap_uwm
```

Expected: only JSON artifacts under the repo path are tracked or modified; raw files under `/Users/zhouning/Downloads/tap_uwm` are outside the repo and not added.

- [ ] **Step 5: Final commit if verification changed generated artifacts**

Run:

```bash
git add data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06
git commit -m "data: refresh tap observed gridded benchmark artifacts"
```

Expected: commit only if the full-size artifact build changed files after Task 3.

---

## Self-Review

- Spec coverage: tasks cover TAP parser, benchmark, builder script, package exports, manifest/report updates, and verification.
- Placeholder scan: no `TBD`, `TODO`, or vague implementation steps remain.
- Type consistency: schema constants, function names, dataset IDs, and output filenames match the design spec.
- Scope check: admin polygon zonal aggregation and planner retraining are explicitly out of scope for this plan.
