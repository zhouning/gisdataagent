"""Paper58 benchmark visualization helpers for World Model v1.1."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_bounds


DEFAULT_METHOD = "paper58_spatial_demand_ratio_claim_robustness_v4"
BASELINE_METHOD = "geosos_flus_console"
SCHEMA = "territory_world_model.paper58_visualization.v1"
MAP_SCHEMA = "territory_world_model.paper58_visualization_map.v1"
METHOD_METRICS = [
    "mean_change_f1",
    "mean_fom",
    "mean_transition_accuracy",
    "mean_allocation_disagreement",
]
AREA_METRICS = [
    "change_f1",
    "fom",
    "transition_accuracy",
    "allocation_disagreement",
]


def _layer_names(start_year: int = 2020, end_year: int = 2021) -> list[str]:
    return [
        f"Paper58 土地利用 {start_year}",
        f"Paper58 土地利用 {end_year}",
        f"GeoSOS-FLUS 土地利用 {end_year}",
        f"Paper58 与 GeoSOS-FLUS 差异 {end_year}",
    ]


LAYER_NAMES = _layer_names()

CLASS_LABELS = {
    0: "水体",
    1: "树木",
    2: "草地",
    4: "草地",
    5: "灌木",
    7: "耕地",
    8: "建设用地",
    9: "裸地",
    10: "冰雪",
    11: "湿地",
}
CLASS_COLORS = {
    0: "#4169E1",
    1: "#228B22",
    2: "#90EE90",
    4: "#90EE90",
    5: "#DEB887",
    7: "#FFD700",
    8: "#DC143C",
    9: "#D2B48C",
    10: "#F8FAFC",
    11: "#20B2AA",
}
DIFFERENCE_LABELS = {
    1: "一致预测",
    2: "Paper58变化 / FLUS稳定",
    3: "FLUS变化 / Paper58稳定",
    4: "不同变化目标",
}
DIFFERENCE_COLORS = {
    1: "#9CA3AF",
    2: "#2563EB",
    3: "#F97316",
    4: "#7C3AED",
}


def build_paper58_visualization(
    root: Path | str | None,
    selected_area: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Build the visualization summary returned by the v1.1 tab."""
    root_path = _normalize_root(root)
    if root_path is None:
        return _missing_payload(["paper58_benchmark_dir_not_provided"])
    if not root_path.exists():
        return _missing_payload(["paper58_benchmark_dir_not_found"], root_path)

    method_summary_path = root_path / "metric_summary_by_method.csv"
    metrics_path = root_path / "metrics_by_method.csv"
    missing = [
        str(path.name)
        for path in (method_summary_path, metrics_path)
        if not path.exists()
    ]
    if missing:
        return _missing_payload(missing, root_path)

    method_rows = _read_csv(method_summary_path)
    area_rows = _read_csv(metrics_path)
    selected_method = _select_method(method_rows, area_rows, method)
    baseline_method = _select_baseline_method(method_rows, area_rows)

    selected_rows = [row for row in area_rows if row.get("method") == selected_method]
    baseline_rows = [row for row in area_rows if row.get("method") == baseline_method]
    baseline_by_area = {str(row.get("area") or ""): row for row in baseline_rows}
    areas = [_area_summary(row, baseline_by_area.get(str(row.get("area") or ""))) for row in selected_rows]
    areas = [area for area in areas if area]
    areas.sort(key=lambda item: item["area"])

    if not areas:
        return _missing_payload(["paper58_selected_method_has_no_area_rows"], root_path)

    area_names = {item["area"] for item in areas}
    selected_area_name = selected_area if selected_area in area_names else areas[0]["area"]
    selected_row = next(row for row in selected_rows if row.get("area") == selected_area_name)
    selected_baseline = baseline_by_area.get(selected_area_name, {})
    start_year = _safe_int(selected_row.get("start_year"), 2020)
    end_year = _safe_int(selected_row.get("end_year"), 2021)
    georef = _resolve_area_georef(root_path, selected_area_name, start_year, end_year)

    return {
        "schema": SCHEMA,
        "status": "ready",
        "source_dir": str(root_path),
        "selected_area": selected_area_name,
        "selected_method": selected_method,
        "baseline_method": baseline_method,
        "years": [start_year, end_year],
        "areas": areas,
        "method_summary": [_method_summary(row) for row in method_rows],
        "selected_area_metrics": _selected_area_metrics(selected_row, selected_baseline),
        "visualization": {
            "map_action": "POST /api/twm/paper58-visualization/map",
            "available_layers": _layer_names(start_year, end_year),
            "display_crs": georef["display_crs"],
            "georeferenced": georef["georeferenced"],
            "georef_source": georef.get("source_path"),
            "class_legend": {str(key): value for key, value in CLASS_LABELS.items()},
            "difference_legend": {
                str(key): value for key, value in DIFFERENCE_LABELS.items()
            },
        },
        "source_files": {
            "paper58_benchmark_dir": str(root_path),
            "metric_summary_by_method": str(method_summary_path),
            "metrics_by_method": str(metrics_path),
        },
        "missing": [],
    }


def queue_paper58_visualization_map(
    root: Path | str | None,
    username: str,
    selected_area: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Write selected Paper58 layers to the user's uploads and queue a map update."""
    summary = build_paper58_visualization(root, selected_area=selected_area, method=method)
    if summary.get("status") != "ready":
        return {
            "schema": MAP_SCHEMA,
            "status": summary.get("status", "missing"),
            "selected_area": selected_area,
            "selected_method": method,
            "map_update_queued": False,
            "missing": summary.get("missing", []),
        }

    root_path = Path(str(summary["source_dir"]))
    area = str(summary["selected_area"])
    selected_method = str(summary["selected_method"])
    start_year, end_year = summary["years"]

    initial_grid = _load_initial_grid(root_path, area, start_year, end_year)
    paper58_grid = _load_paper58_grid(root_path, area, start_year, end_year, selected_method)
    flus_grid = _load_flus_grid(root_path, area, start_year, end_year)
    _assert_same_shape(initial_grid, paper58_grid, flus_grid)
    difference_grid = _difference_grid(initial_grid, paper58_grid, flus_grid)
    georef = _resolve_area_georef(
        root_path,
        area,
        start_year,
        end_year,
        shape=initial_grid.shape,
    )

    upload_dir = Path(__file__).resolve().parent / "uploads" / username
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_prefix = _safe_filename(f"paper58_v11_{area}_{selected_method}")
    layer_names = _layer_names(start_year, end_year)
    layer_specs = [
        (
            layer_names[0],
            f"{safe_prefix}_lulc_{start_year}.geojson",
            _grid_to_geojson(initial_grid, CLASS_LABELS, "lulc", georef),
            _lulc_style_map(initial_grid),
            "土地利用",
            True,
        ),
        (
            layer_names[1],
            f"{safe_prefix}_paper58_{end_year}.geojson",
            _grid_to_geojson(paper58_grid, CLASS_LABELS, "lulc", georef),
            _lulc_style_map(paper58_grid),
            "土地利用",
            True,
        ),
        (
            layer_names[2],
            f"{safe_prefix}_geosos_flus_{end_year}.geojson",
            _grid_to_geojson(flus_grid, CLASS_LABELS, "lulc", georef),
            _lulc_style_map(flus_grid),
            "土地利用",
            True,
        ),
        (
            layer_names[3],
            f"{safe_prefix}_paper58_vs_flus_{end_year}.geojson",
            _grid_to_geojson(difference_grid, DIFFERENCE_LABELS, "difference", georef),
            _difference_style_map(difference_grid),
            "Paper58 与 GeoSOS-FLUS 差异",
            False,
        ),
    ]

    layers = []
    for name, filename, geojson, style_map, legend_title, visible in layer_specs:
        (upload_dir / filename).write_text(
            json.dumps(geojson, ensure_ascii=False),
            encoding="utf-8",
        )
        layers.append(
            {
                "name": name,
                "type": "categorized",
                "geojson": filename,
                "category_column": "class_name",
                "style_map": style_map,
                "category_labels": {key: key for key in style_map},
                "legend_title": legend_title,
                "tooltip_fields": ["layer", "class_name", "class_id"],
                "visible": visible,
            }
        )

    center, zoom = _map_view(initial_grid.shape, georef)
    map_update = {
        "layers": layers,
        "center": center,
        "zoom": zoom,
        "display_crs": georef["display_crs"],
        "georeferenced": georef["georeferenced"],
        "georef_source": georef.get("source_path"),
        "layerControl": {"collapsed": False},
    }

    from .frontend_api import _pending_lock, pending_map_updates

    with _pending_lock:
        pending_map_updates[username] = map_update

    return {
        "schema": MAP_SCHEMA,
        "status": "queued",
        "selected_area": area,
        "selected_method": selected_method,
        "map_update_queued": True,
        "map_update": map_update,
    }


def _normalize_root(root: Path | str | None) -> Path | None:
    if root is None:
        return None
    text = str(root).strip()
    return Path(text).expanduser() if text else None


def _missing_payload(missing: list[str], root: Path | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "missing",
        "provided": root is not None,
        "source_dir": str(root) if root else None,
        "selected_area": None,
        "selected_method": DEFAULT_METHOD,
        "baseline_method": BASELINE_METHOD,
        "years": [2020, 2021],
        "areas": [],
        "method_summary": [],
        "selected_area_metrics": {},
        "visualization": {
            "map_action": "POST /api/twm/paper58-visualization/map",
            "available_layers": _layer_names(),
            "display_crs": "local_same_grid_normalized",
            "georeferenced": False,
        },
        "missing": missing,
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _select_method(
    method_rows: list[dict[str, Any]],
    area_rows: list[dict[str, Any]],
    requested: str | None,
) -> str:
    methods = {str(row.get("method") or "") for row in method_rows + area_rows}
    methods.discard("")
    if requested and requested in methods:
        return requested
    if DEFAULT_METHOD in methods:
        return DEFAULT_METHOD
    paper58_methods = sorted(method for method in methods if "paper58" in method.lower())
    if paper58_methods:
        return paper58_methods[0]
    return sorted(methods)[0] if methods else DEFAULT_METHOD


def _select_baseline_method(
    method_rows: list[dict[str, Any]],
    area_rows: list[dict[str, Any]],
) -> str:
    methods = {str(row.get("method") or "") for row in method_rows + area_rows}
    if BASELINE_METHOD in methods:
        return BASELINE_METHOD
    for method in sorted(methods):
        text = method.lower()
        if ("geosos" in text or "flus" in text) and "paper58" not in text:
            return method
    return BASELINE_METHOD


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else default


def _round_metric(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _delta(left: Any, right: Any) -> float | None:
    left_float = _safe_float(left)
    right_float = _safe_float(right)
    if left_float is None or right_float is None:
        return None
    return _round_metric(left_float - right_float)


def _metric_value(row: dict[str, Any], key: str) -> float | None:
    return _round_metric(_safe_float(row.get(key)))


def _method_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary = {"method": row.get("method"), "n": _safe_int(row.get("n"), 0)}
    for key in METHOD_METRICS:
        summary[key] = _metric_value(row, key)
    return summary


def _area_summary(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    area = str(row.get("area") or "")
    if not area:
        return None
    change_delta = _delta(row.get("change_f1"), (baseline or {}).get("change_f1"))
    return {
        "area": area,
        "display_name": area.replace("xiangzhen_record_", ""),
        "start_year": _safe_int(row.get("start_year"), 2020),
        "end_year": _safe_int(row.get("end_year"), 2021),
        "n_pixels": _safe_int(row.get("n_pixels"), 0),
        "paper58_change_f1": _metric_value(row, "change_f1"),
        "baseline_change_f1": _metric_value(baseline or {}, "change_f1"),
        "paper58_delta_change_f1": change_delta,
        "paper58_wins": bool(change_delta is not None and change_delta > 0),
    }


def _selected_area_metrics(
    paper58: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    paper58_metrics = {key: _metric_value(paper58, key) for key in AREA_METRICS}
    baseline_metrics = {key: _metric_value(baseline, key) for key in AREA_METRICS}
    deltas = {key: _delta(paper58.get(key), baseline.get(key)) for key in AREA_METRICS}
    winners = {}
    for key in AREA_METRICS:
        left = paper58_metrics.get(key)
        right = baseline_metrics.get(key)
        if left is None or right is None:
            winners[key] = None
        elif key == "allocation_disagreement":
            winners[key] = "paper58" if left < right else "geosos_flus"
        else:
            winners[key] = "paper58" if left > right else "geosos_flus"
    return {
        "paper58": paper58_metrics,
        "baseline": baseline_metrics,
        "deltas": deltas,
        "winner_by_metric": winners,
    }


def _load_initial_grid(root: Path, area: str, start_year: int, end_year: int) -> np.ndarray:
    case_dir = root / "flus_cases" / f"{area}_{start_year}_{end_year}"
    grid = _read_tif(case_dir / "landuse.tif")
    mapping_path = case_dir / "class_mapping.json"
    if not mapping_path.exists():
        return grid
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    encoded_to_original = mapping.get("encoded_to_original") if isinstance(mapping, dict) else {}
    if not isinstance(encoded_to_original, dict):
        return grid
    mapped = grid.copy()
    for encoded, original in encoded_to_original.items():
        mapped[grid == int(encoded)] = int(original)
    return mapped


def _load_paper58_grid(
    root: Path,
    area: str,
    start_year: int,
    end_year: int,
    method: str,
) -> np.ndarray:
    path = root / "maps" / method / f"{area}_{start_year}_{end_year}_{method}.npy"
    return _coerce_grid(np.load(path))


def _load_flus_grid(root: Path, area: str, start_year: int, end_year: int) -> np.ndarray:
    return _read_tif(
        root / "maps" / BASELINE_METHOD / f"{area}_{start_year}_{end_year}_flus.tif"
    )


def _read_tif(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return _coerce_grid(dataset.read(1))


def _coerce_grid(value: Any) -> np.ndarray:
    grid = np.squeeze(np.asarray(value))
    if grid.ndim != 2:
        raise ValueError(f"expected a 2D grid, got shape {grid.shape}")
    return grid.astype(np.int16, copy=False)


def _assert_same_shape(*grids: np.ndarray) -> None:
    shapes_seen = {grid.shape for grid in grids}
    if len(shapes_seen) != 1:
        raise ValueError(f"Paper58 visualization grids are not aligned: {sorted(shapes_seen)}")


def _difference_grid(
    initial_grid: np.ndarray,
    paper58_grid: np.ndarray,
    flus_grid: np.ndarray,
) -> np.ndarray:
    paper58_changed = paper58_grid != initial_grid
    flus_changed = flus_grid != initial_grid
    same_prediction = paper58_grid == flus_grid
    diff = np.full(initial_grid.shape, 4, dtype=np.int16)
    diff[same_prediction] = 1
    diff[paper58_changed & ~flus_changed] = 2
    diff[flus_changed & ~paper58_changed] = 3
    return diff


def _local_georef() -> dict[str, Any]:
    return {
        "bounds": None,
        "display_crs": "local_same_grid_normalized",
        "georeferenced": False,
        "source_path": None,
    }


def _resolve_area_georef(
    root: Path,
    area: str,
    start_year: int,
    end_year: int,
    shape: tuple[int, int] | None = None,
) -> dict[str, Any]:
    manifest = _read_manifest(root)
    for candidate in _georef_candidates(root, manifest, area, start_year, end_year):
        georef = _georef_from_tif(candidate, shape)
        if georef:
            return georef
    return _local_georef()


def _read_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _georef_candidates(
    root: Path,
    manifest: dict[str, Any],
    area: str,
    start_year: int,
    end_year: int,
) -> list[Path]:
    roots: list[Path] = []
    for key in ("labels_dir", "paper58_predictions_dir"):
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            roots.append(path.parent if path.name in {"labels", "predictions"} else path)

    samples = manifest.get("samples")
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict) or sample.get("area") != area:
                continue
            if _safe_int(sample.get("start_year"), start_year) != start_year:
                continue
            if _safe_int(sample.get("end_year"), end_year) != end_year:
                continue
            prediction_path = sample.get("prediction_path")
            if isinstance(prediction_path, str) and prediction_path.strip():
                roots.append(Path(prediction_path).expanduser().parent.parent)

    roots.extend([root, root.parent])

    seen: set[str] = set()
    unique_roots = []
    for candidate_root in roots:
        key = str(candidate_root)
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(candidate_root)

    candidates = []
    for candidate_root in unique_roots:
        for year in (start_year, end_year):
            filename = f"{area}_esri_lulc_{year}.tif"
            candidates.append(candidate_root / "downloads" / area / filename)
            candidates.append(candidate_root / area / filename)
    return candidates


def _georef_from_tif(
    path: Path,
    expected_shape: tuple[int, int] | None,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with rasterio.open(path) as dataset:
            if expected_shape and (dataset.height, dataset.width) != expected_shape:
                return None
            crs = dataset.crs
            if crs is None or crs.to_epsg() != 4326:
                return None
            bounds = dataset.bounds
    except (OSError, rasterio.errors.RasterioIOError):
        return None

    left, bottom, right, top = (
        float(bounds.left),
        float(bounds.bottom),
        float(bounds.right),
        float(bounds.top),
    )
    if not _valid_epsg4326_bounds(left, bottom, right, top):
        return None
    return {
        "bounds": (left, bottom, right, top),
        "display_crs": "EPSG:4326",
        "georeferenced": True,
        "source_path": str(path),
    }


def _valid_epsg4326_bounds(left: float, bottom: float, right: float, top: float) -> bool:
    values = (left, bottom, right, top)
    if not all(math.isfinite(value) for value in values):
        return False
    return -180.0 <= left < right <= 180.0 and -90.0 <= bottom < top <= 90.0


def _grid_to_geojson(
    grid: np.ndarray,
    labels: dict[int, str],
    layer_kind: str,
    georef: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grid = _coerce_grid(grid)
    georef = georef or _local_georef()
    bounds = georef.get("bounds")
    if bounds:
        left, bottom, right, top = bounds
        transform = from_bounds(left, bottom, right, top, grid.shape[1], grid.shape[0])
    else:
        transform = _local_transform(grid.shape)
    features = []
    for geom, value in shapes(grid, transform=transform):
        class_id = int(value)
        class_name = labels.get(class_id, f"类别 {class_id}")
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "class_id": class_id,
                    "class_name": class_name,
                    "layer": layer_kind,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "display_crs": georef["display_crs"],
            "georeferenced": georef["georeferenced"],
            "georef_source": georef.get("source_path"),
            "height": int(grid.shape[0]),
            "width": int(grid.shape[1]),
        },
    }


def _local_transform(shape: tuple[int, int]):
    height, width = shape
    max_dim = max(height, width, 1)
    return from_bounds(0.0, 0.0, width / max_dim, height / max_dim, width, height)


def _map_view(
    shape: tuple[int, int],
    georef: dict[str, Any] | None = None,
) -> tuple[list[float], int]:
    georef = georef or _local_georef()
    bounds = georef.get("bounds")
    if bounds:
        left, bottom, right, top = bounds
        center = [
            round((bottom + top) / 2.0, 6),
            round((left + right) / 2.0, 6),
        ]
        return center, 13

    height, width = shape
    max_dim = max(height, width, 1)
    center = [
        round((height / max_dim) / 2.0, 6),
        round((width / max_dim) / 2.0, 6),
    ]
    return center, 13


def _lulc_style_map(grid: np.ndarray) -> dict[str, dict[str, Any]]:
    style_map = {}
    for raw_value in sorted(int(value) for value in np.unique(grid)):
        label = CLASS_LABELS.get(raw_value, f"类别 {raw_value}")
        color = CLASS_COLORS.get(raw_value, "#6B7280")
        style_map[label] = {
            "fillColor": color,
            "color": color,
            "fillOpacity": 0.72,
            "weight": 0.25,
        }
    return style_map


def _difference_style_map(grid: np.ndarray) -> dict[str, dict[str, Any]]:
    style_map = {}
    for raw_value in sorted(int(value) for value in np.unique(grid)):
        label = DIFFERENCE_LABELS.get(raw_value, f"差异 {raw_value}")
        color = DIFFERENCE_COLORS.get(raw_value, "#6B7280")
        style_map[label] = {
            "fillColor": color,
            "color": color,
            "fillOpacity": 0.66,
            "weight": 0.25,
        }
    return style_map


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe[:180] or "paper58_v11"
