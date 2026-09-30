"""Research-panel and benchmark utilities for the Abu Dhabi flood GWM prototype.

The production service deliberately remains fail-closed and is not used as a
paper model.  This module reads *derived* SWMM--ANUGA map products from a
private results directory and assembles a dense, event-grouped panel suitable
for reproducible emulator experiments.  No customer file is copied into the
repository; the output manifest contains only relative scenario identifiers
and provenance classes.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


RETURN_PERIOD_RE = re.compile(r"^rp(?P<years>\d+)$", re.IGNORECASE)
REQUIRED_PANEL_COLUMNS = (
    "event_id",
    "return_period_years",
    "time_index",
    "time_minutes",
    "cell_id",
    "depth_m",
    "next_depth_m",
    "max_depth_m",
)


@dataclass(frozen=True)
class ScenarioRecord:
    event_id: str
    return_period_years: int
    path: Path
    duration_minutes: float
    total_rainfall_mm: float
    source_label: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def _first_number(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return default


def discover_scenarios(results_root: str | Path) -> list[ScenarioRecord]:
    """Discover rpXXX derived result directories and their forcing metadata."""

    root = Path(results_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"results_root_not_found:{root}")
    records: list[ScenarioRecord] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        match = RETURN_PERIOD_RE.fullmatch(path.name)
        if not match:
            continue
        years = int(match.group("years"))
        summary_path = path / "delivery_summary.json"
        receipt_path = path / "run_receipt.json"
        summary = _read_json(summary_path) if summary_path.exists() else {}
        receipt = _read_json(receipt_path) if receipt_path.exists() else {}
        forcing = summary.get("forcing") or receipt.get("forcing") or {}
        duration = _first_number(
            forcing.get("duration_minutes"),
            forcing.get("configured_storm_duration_minutes"),
            (summary.get("domain") or {}).get("simulation_duration_hours", 0) * 60,
            default=180.0,
        )
        total_mm = _first_number(
            forcing.get("published_total_depth_mm"),
            forcing.get("generated_total_depth_mm"),
            default=0.0,
        )
        source_label = str(
            (summary.get("coupling") or {}).get("mode")
            or (receipt.get("coupling") or {}).get("mode")
            or "derived_swmm_anuga_result"
        )
        records.append(
            ScenarioRecord(
                event_id=path.name,
                return_period_years=years,
                path=path,
                duration_minutes=duration,
                total_rainfall_mm=total_mm,
                source_label=source_label,
            )
        )
    if not records:
        raise FileNotFoundError(f"no_rp_scenarios_found:{root}")
    return records


def _centroid_lon_lat(geometry: Mapping[str, Any] | None) -> tuple[float, float]:
    if not geometry:
        return (float("nan"), float("nan"))
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            if all(isinstance(v, (int, float)) for v in value[:2]):
                points.append((float(value[0]), float(value[1])))
                return
            for child in value:
                walk(child)

    walk(coordinates)
    if not points:
        return (float("nan"), float("nan"))
    return (float(np.mean([p[0] for p in points])), float(np.mean([p[1] for p in points])))


def _storm_rainfall_features(time_minutes: float, duration_minutes: float, total_mm: float) -> tuple[float, float]:
    """Return deterministic cumulative depth and intensity proxies.

    The delivered map products contain 30-minute snapshots, not a complete
    gauge series.  These features are explicitly labelled proxies and are not
    presented as observed rainfall.  A 40% peak position matches the design
    storm convention recorded in the run receipts.
    """

    if duration_minutes <= 0 or total_mm <= 0:
        return 0.0, 0.0
    u = float(np.clip(time_minutes / duration_minutes, 0.0, 1.0))
    peak = 0.4
    if u <= peak:
        cumulative = total_mm * (u * u / peak)
    else:
        tail = (1.0 - u) / (1.0 - peak)
        cumulative = total_mm * (1.0 - 0.5 * tail * tail)
    # Triangular intensity, scaled to integrate to total_mm.
    scale = 2.0 * total_mm / max(duration_minutes / 60.0, 1e-9)
    intensity = scale * (u / peak if u <= peak else (1.0 - u) / (1.0 - peak))
    return float(cumulative), float(max(intensity, 0.0))


def _snapshot_paths(record: ScenarioRecord) -> list[tuple[int, float, Path]]:
    manifest_path = record.path / "temporal_snapshots" / "manifest.json"
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        snapshots = manifest.get("snapshots") or []
        result: list[tuple[int, float, Path]] = []
        for item in snapshots:
            index = int(item.get("index", len(result)))
            time_minutes = _first_number(item.get("time_minutes"), default=float(index))
            relative = item.get("path")
            if relative:
                path = record.path / str(relative)
                if path.exists():
                    result.append((index, time_minutes, path))
        if result:
            return sorted(result)
    paths = sorted((record.path / "temporal_snapshots").glob("*.geojson"))
    result = []
    for index, path in enumerate(paths):
        result.append((index, float(index), path))
    return result


def _load_geojson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    value = _read_json(path)
    features = value.get("features") or []
    return [feature for feature in features if isinstance(feature, dict)]


def assemble_panel(results_root: str | Path) -> pd.DataFrame:
    """Assemble a dense cell/time panel from all discovered scenarios."""

    records = discover_scenarios(results_root)
    rows: list[dict[str, Any]] = []
    for record in records:
        snapshots = _snapshot_paths(record)
        if not snapshots:
            continue
        by_time: dict[int, dict[int, dict[str, Any]]] = {}
        static: dict[int, dict[str, Any]] = {}
        times: dict[int, float] = {}
        for index, time_minutes, path in snapshots:
            times[index] = time_minutes
            cells: dict[int, dict[str, Any]] = {}
            for feature in _load_geojson(path):
                properties = feature.get("properties") or {}
                try:
                    cell_id = int(properties["cell_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                depth = _first_number(properties.get("depth_m"), default=0.0)
                lon, lat = _centroid_lon_lat(feature.get("geometry"))
                cells[cell_id] = {
                    "depth_m": max(depth, 0.0),
                    "land_fraction": _first_number(properties.get("land_fraction"), default=1.0),
                    "permanent_water_fraction": _first_number(
                        properties.get("permanent_water_fraction"), default=0.0
                    ),
                    "prototype_cell_size_m": _first_number(
                        properties.get("prototype_cell_size_m"), default=250.0
                    ),
                    "lon": lon,
                    "lat": lat,
                }
            by_time[index] = cells
            for cell_id, values in cells.items():
                static.setdefault(cell_id, values)
        # Include cells present only in the maximum-depth product.
        maximum_features = _load_geojson(record.path / "maximum_depth_wgs84.geojson")
        maximum: dict[int, float] = {}
        for feature in maximum_features:
            properties = feature.get("properties") or {}
            try:
                cell_id = int(properties["cell_id"])
            except (KeyError, TypeError, ValueError):
                continue
            maximum[cell_id] = max(
                _first_number(properties.get("maximum_depth_m"), properties.get("depth_m"), default=0.0),
                0.0,
            )
            if cell_id not in static:
                lon, lat = _centroid_lon_lat(feature.get("geometry"))
                static[cell_id] = {
                    "depth_m": 0.0,
                    "land_fraction": _first_number(properties.get("land_fraction"), default=1.0),
                    "permanent_water_fraction": _first_number(
                        properties.get("permanent_water_fraction"), default=0.0
                    ),
                    "prototype_cell_size_m": _first_number(
                        properties.get("prototype_cell_size_m"), default=250.0
                    ),
                    "lon": lon,
                    "lat": lat,
                }
        for cell_id, values in static.items():
            maximum.setdefault(cell_id, 0.0)
        ordered_cells = sorted(static)
        ordered_times = sorted(times)
        for position, time_index in enumerate(ordered_times[:-1]):
            next_index = ordered_times[position + 1]
            time_minutes = times[time_index]
            next_time_minutes = times[next_index]
            cumulative, intensity = _storm_rainfall_features(
                time_minutes, record.duration_minutes, record.total_rainfall_mm
            )
            next_cumulative, _ = _storm_rainfall_features(
                next_time_minutes, record.duration_minutes, record.total_rainfall_mm
            )
            for cell_id in ordered_cells:
                values = static[cell_id]
                current = by_time.get(time_index, {}).get(cell_id, {})
                following = by_time.get(next_index, {}).get(cell_id, {})
                rows.append(
                    {
                        "event_id": record.event_id,
                        "return_period_years": record.return_period_years,
                        "time_index": int(time_index),
                        "time_minutes": float(time_minutes),
                        "next_time_minutes": float(next_time_minutes),
                        "duration_minutes": record.duration_minutes,
                        "total_rainfall_mm": record.total_rainfall_mm,
                        "cumulative_rainfall_mm": cumulative,
                        "next_cumulative_rainfall_mm": next_cumulative,
                        "rainfall_intensity_mm_h": intensity,
                        "cell_id": cell_id,
                        "lon": values.get("lon", float("nan")),
                        "lat": values.get("lat", float("nan")),
                        "depth_m": max(_first_number(current.get("depth_m"), default=0.0), 0.0),
                        "next_depth_m": max(_first_number(following.get("depth_m"), default=0.0), 0.0),
                        "max_depth_m": maximum[cell_id],
                        "land_fraction": values.get("land_fraction", 1.0),
                        "permanent_water_fraction": values.get("permanent_water_fraction", 0.0),
                        "prototype_cell_size_m": values.get("prototype_cell_size_m", 250.0),
                        "label_source": record.source_label,
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"panel_empty:{results_root}")
    for column in REQUIRED_PANEL_COLUMNS:
        if column not in frame.columns:
            raise ValueError(f"panel_missing_column:{column}")
    return frame.sort_values(["event_id", "time_index", "cell_id"], ignore_index=True)


def build_event_split(
    event_metadata: pd.DataFrame | Iterable[Mapping[str, Any]],
    *,
    train_return_periods: Iterable[int] = (2, 5, 10, 25),
    validation_return_periods: Iterable[int] = (50,),
    test_return_periods: Iterable[int] = (100,),
) -> dict[str, list[str]]:
    """Create the pre-registered cross-return-period split."""

    if not isinstance(event_metadata, pd.DataFrame):
        event_metadata = pd.DataFrame(list(event_metadata))
    if "event_id" not in event_metadata or "return_period_years" not in event_metadata:
        raise ValueError("event_metadata_requires_event_id_and_return_period_years")
    events = event_metadata[["event_id", "return_period_years"]].drop_duplicates()
    train = set(map(int, train_return_periods))
    validation = set(map(int, validation_return_periods))
    test = set(map(int, test_return_periods))
    if (train & validation) or (train & test) or (validation & test):
        raise ValueError("event_split_return_period_sets_overlap")
    result = {
        "train": sorted(events.loc[events.return_period_years.isin(train), "event_id"].astype(str)),
        "validation": sorted(events.loc[events.return_period_years.isin(validation), "event_id"].astype(str)),
        "test": sorted(events.loc[events.return_period_years.isin(test), "event_id"].astype(str)),
    }
    assigned = set(result["train"] + result["validation"] + result["test"])
    all_events = set(events.event_id.astype(str))
    result["unassigned"] = sorted(all_events - assigned)
    return result


def validate_event_split(frame: pd.DataFrame, split: Mapping[str, Iterable[str]]) -> dict[str, Any]:
    """Audit event/time leakage; spatial overlap is reported, not treated as leakage."""

    groups = {name: set(map(str, values)) for name, values in split.items() if name != "unassigned"}
    overlap: dict[str, list[str]] = {}
    names = sorted(groups)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            common = sorted(groups[left] & groups[right])
            if common:
                overlap[f"{left}__{right}"] = common
    all_events = set(frame.event_id.astype(str))
    assigned = set().union(*groups.values()) if groups else set()
    event_cells = {name: set(frame.loc[frame.event_id.astype(str).isin(events), "cell_id"]) for name, events in groups.items()}
    spatial_overlap = {
        f"{left}__{right}": int(len(event_cells[left] & event_cells[right]))
        for index, left in enumerate(names)
        for right in names[index + 1 :]
    }
    return {
        "event_disjoint": not overlap,
        "events_exhaustive": assigned == all_events,
        "event_overlap": overlap,
        "spatial_overlap_cell_counts": spatial_overlap,
        "spatial_overlap_is_expected_for_same_city": True,
        "row_counts": {
            name: int(frame.event_id.astype(str).isin(events).sum()) for name, events in groups.items()
        },
        "valid": not overlap and assigned == all_events,
    }


def panel_manifest(frame: pd.DataFrame, split: Mapping[str, Iterable[str]], root: str | Path) -> dict[str, Any]:
    """Return a JSON-safe provenance manifest without customer file paths."""

    events = frame[["event_id", "return_period_years", "duration_minutes", "total_rainfall_mm", "label_source"]].drop_duplicates()
    return {
        "schema": "gwm.abu_dhabi_flood.research_panel.v1",
        "status": "derived_private_panel",
        "source_root_label": Path(root).name,
        "source_evidence": "customer_dtm_5m_with_derived_swmm_anuga_map_products",
        "row_count": int(len(frame)),
        "cell_count": int(frame.cell_id.nunique()),
        "event_count": int(frame.event_id.nunique()),
        "time_step_minutes": float(
            np.median(
                frame["next_time_minutes"].to_numpy(dtype=float)
                - frame["time_minutes"].to_numpy(dtype=float)
            )
        ),
        "events": events.to_dict(orient="records"),
        "split": {name: sorted(map(str, values)) for name, values in split.items()},
        "feature_columns": [
            "current_depth_m",
            "cumulative_rainfall_mm",
            "rainfall_intensity_mm_h",
            "return_period_years",
            "time_minutes",
            "land_fraction",
            "permanent_water_fraction",
            "lon",
            "lat",
        ],
        "target": "next_depth_m",
        "label_boundary": "Map-product labels are derived from completed physical-model runs; rainfall features are design-storm proxies where gauge time series are absent.",
    }
