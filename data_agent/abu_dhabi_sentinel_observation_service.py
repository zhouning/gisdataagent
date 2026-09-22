"""Read-only summary contract for the April 2024 Sentinel-2 holdout.

The raster products remain in the controlled customer workspace.  The web
client receives only audited aggregate statistics, scene provenance and the
external-holdout state required to operate the validation workspace.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


DEFAULT_SENTINEL_OBSERVATION_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_sentinel2_observed_flood_202404_r1"
)
EXPECTED_EVENT_ID = "noaa-isd-ae-202404151200-0327"
EXPECTED_SCHEMA = "gwm.abu_dhabi_flood.sentinel2_observed_flood.v1"


def _root() -> Path:
    configured = os.environ.get("ABU_DHABI_SENTINEL2_OBSERVED_FLOOD_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_SENTINEL_OBSERVATION_ROOT


def _read_json(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _safe_asset_name(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(error_code)
    return str(path)


def _number(value: Any, error_code: str, *, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(error_code) from error
    if not math.isfinite(number) or number < minimum:
        raise ValueError(error_code)
    return number


def _string(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    return value


def _integer_list(value: Any, error_code: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(error_code)
    values: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(error_code)
        values.append(item)
    return values


def _scene_summary(value: Any, error_code: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(error_code)
    scenes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(error_code)
        item_id = item.get("item_id")
        datetime_utc = item.get("datetime_utc")
        if not isinstance(item_id, str) or not item_id or not isinstance(datetime_utc, str) or not datetime_utc:
            raise ValueError(error_code)
        scenes.append(
            {
                "item_id": item_id,
                "datetime_utc": datetime_utc,
                "grid_code": str(item.get("grid_code") or ""),
                "cloud_cover_percent": _number(item.get("cloud_cover_percent"), error_code),
            }
        )
    return scenes


def _comparison_metrics(value: Any, error_code: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(error_code)
    metrics = value.get("metrics", value)
    if not isinstance(metrics, dict):
        raise ValueError(error_code)
    return {
        key: _number(metrics.get(key), error_code)
        for key in ("iou", "precision", "recall")
    }


def _external_comparison(root: Path) -> dict[str, Any]:
    """Expose a completed external score only after its isolated receipt exists."""

    receipt_path = root / "external_holdout_replay" / "run_receipt.json"
    if not receipt_path.is_file():
        return {
            "status": "pending_physics_replay",
            "physics_replay": "pending",
            "gwm_comparison": "pending_frozen_model",
            "comparison": None,
        }
    receipt = _read_json(receipt_path, "sentinel_external_comparison_receipt_invalid")
    if (
        receipt.get("status") != "completed"
        or receipt.get("event_id") != EXPECTED_EVENT_ID
        or receipt.get("external_holdout") is not True
        or receipt.get("training_forbidden") is not True
        or not isinstance(receipt.get("comparison"), dict)
    ):
        raise ValueError("sentinel_external_comparison_contract_invalid")
    physics_metrics = _comparison_metrics(receipt["comparison"], "sentinel_external_comparison_contract_invalid")
    gwm_value = receipt.get("gwm_comparison")
    if not isinstance(gwm_value, dict):
        return {
            "status": "completed_external_physics_comparison",
            "physics_replay": "completed",
            "gwm_comparison": "pending_frozen_model",
            "comparison": physics_metrics,
            "gwm_metrics": None,
        }
    gwm_metrics = _comparison_metrics(gwm_value, "sentinel_external_comparison_contract_invalid")
    return {
        "status": "completed_external_comparisons",
        "physics_replay": "completed",
        "gwm_comparison": "completed_frozen_model",
        "comparison": physics_metrics,
        "gwm_metrics": gwm_metrics,
    }


def observed_flood_dashboard_payload() -> dict[str, Any]:
    """Return the approved, non-spatial April 2024 observation dashboard data."""

    root = _root()
    receipt = _read_json(root / "run_receipt.json", "sentinel_observation_receipt_missing")
    event = receipt.get("event")
    outputs = receipt.get("outputs")
    method = receipt.get("method")
    scenes = receipt.get("scenes")
    if not isinstance(event, dict) or not isinstance(outputs, dict) or not isinstance(method, dict) or not isinstance(scenes, dict):
        raise ValueError("sentinel_observation_receipt_invalid")
    if (
        receipt.get("schema") != EXPECTED_SCHEMA
        or receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or event.get("event_id") != EXPECTED_EVENT_ID
        or event.get("external_holdout") is not True
        or event.get("training_forbidden") is not True
    ):
        raise ValueError("sentinel_observation_holdout_contract_invalid")

    asset_keys = (
        "observed_new_surface_water_10m",
        "paired_valid_observation_10m",
        "mndwi_change_10m",
        "observed_flood_250m",
    )
    assets: list[dict[str, Any]] = []
    for key in asset_keys:
        asset = _safe_asset_name(outputs.get(key), "sentinel_observation_asset_invalid")
        if not (root / asset).is_file():
            raise ValueError("sentinel_observation_asset_missing")
        assets.append({"kind": key, "asset": asset, "available": True})
    forcing_name = _safe_asset_name(
        (receipt.get("external_evaluation") or {}).get("forcing_with_zero_rain_tail"),
        "sentinel_observation_forcing_invalid",
    )
    forcing_path = root / forcing_name
    if not forcing_path.is_file():
        raise ValueError("sentinel_observation_forcing_missing")
    forcing = _read_json(forcing_path, "sentinel_observation_forcing_invalid")
    assets.append({"kind": "external_evaluation_forcing", "asset": forcing_name, "available": True})

    valid_area_m2 = _number(outputs.get("valid_observation_area_m2"), "sentinel_observation_statistics_invalid")
    new_water_area_m2 = _number(outputs.get("observed_new_surface_water_area_m2"), "sentinel_observation_statistics_invalid")
    valid_cells = int(_number(outputs.get("valid_250m_cell_count"), "sentinel_observation_statistics_invalid"))
    observed_cells = int(_number(outputs.get("observed_flood_250m_cell_count"), "sentinel_observation_statistics_invalid"))
    if observed_cells > valid_cells or new_water_area_m2 > valid_area_m2:
        raise ValueError("sentinel_observation_statistics_invalid")

    return {
        "schema": "gwm.abu_dhabi_flood.sentinel2_observation_dashboard.v1",
        "status": "available_external_holdout_observation",
        "event": {
            "event_id": EXPECTED_EVENT_ID,
            "external_holdout": True,
            "training_forbidden": True,
            "satellite_observation_utc": _string(event.get("satellite_observation_utc"), "sentinel_observation_time_invalid"),
            "observation_time_seconds_from_event_start": _number(
                event.get("observation_time_seconds_from_event_start"), "sentinel_observation_time_invalid"
            ),
        },
        "forcing": {
            "start_utc": _string(forcing.get("start_utc"), "sentinel_observation_forcing_invalid"),
            "source": _string(forcing.get("source"), "sentinel_observation_forcing_invalid"),
            "support_point_count": int(_number(forcing.get("support_point_count"), "sentinel_observation_forcing_invalid")),
            "zero_rainfall_tail_hours": _number(forcing.get("zero_rainfall_tail_hours"), "sentinel_observation_forcing_invalid"),
            "nearest_300_second_model_frame_seconds": _number(
                forcing.get("nearest_300_second_model_frame_seconds"), "sentinel_observation_forcing_invalid"
            ),
        },
        "observation": {
            "source": _string(method.get("source"), "sentinel_observation_method_invalid"),
            "before_date": _string(method.get("before_date"), "sentinel_observation_method_invalid"),
            "after_date": _string(method.get("after_date"), "sentinel_observation_method_invalid"),
            "valid_observation_area_m2": valid_area_m2,
            "observed_new_surface_water_area_m2": new_water_area_m2,
            "valid_250m_cell_count": valid_cells,
            "observed_flood_250m_cell_count": observed_cells,
            "minimum_250m_valid_fraction": _number(method.get("minimum_250m_valid_fraction"), "sentinel_observation_method_invalid"),
            "minimum_250m_observed_water_fraction": _number(method.get("minimum_250m_observed_water_fraction"), "sentinel_observation_method_invalid"),
            "mndwi_change_threshold": _number(method.get("mndwi_change_threshold"), "sentinel_observation_method_invalid"),
            "valid_scl_classes": _integer_list(method.get("valid_scl_classes"), "sentinel_observation_method_invalid"),
            "water_condition": _string(method.get("water_condition"), "sentinel_observation_method_invalid"),
        },
        "scenes": {
            "before": _scene_summary(scenes.get("before"), "sentinel_observation_scene_invalid"),
            "after": _scene_summary(scenes.get("after"), "sentinel_observation_scene_invalid"),
        },
        "external_comparison": _external_comparison(root),
        "assets": assets,
        "receipt_sha256": receipt.get("receipt_sha256"),
        "claim_boundary": receipt.get("claim_boundary") if isinstance(receipt.get("claim_boundary"), list) else [],
    }


def observed_flood_map_payload() -> dict[str, Any]:
    """Return the 250 m observed-water cells as a WGS84 GeoJSON layer.

    The browser must not receive the source Sentinel-2 rasters or the local
    customer-workspace path.  The 250 m aggregation is deliberately used for
    the map because it is the comparison grid shared by the physical replay
    and the future frozen-GWM test; the 10 m raster remains an audited
    download/lineage asset rather than a browser-sized vector layer.
    """

    dashboard = observed_flood_dashboard_payload()
    root = _root()
    observed_asset = next(
        asset["asset"]
        for asset in dashboard["assets"]
        if asset.get("kind") == "observed_flood_250m"
    )
    observed_path = root / observed_asset
    try:
        import numpy as np
        from pyproj import Transformer
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("sentinel_observation_map_dependencies_missing") from error

    try:
        with np.load(observed_path, allow_pickle=False) as archive:
            labels = np.asarray(archive["observed_flood_label"], dtype=bool)
            valid_fraction = np.asarray(archive["valid_fraction"], dtype=np.float32)
            observed_fraction = np.asarray(
                archive["observed_new_surface_water_fraction_of_valid_pixels"], dtype=np.float32
            )
            x = np.asarray(archive["x"], dtype=np.float64)
            y = np.asarray(archive["y"], dtype=np.float64)
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("sentinel_observation_map_archive_invalid") from error

    if (
        labels.ndim != 2
        or valid_fraction.shape != labels.shape
        or observed_fraction.shape != labels.shape
        or x.ndim != 1
        or y.ndim != 1
        or labels.shape != (len(y) - 1, len(x) - 1)
        or len(x) < 2
        or len(y) < 2
    ):
        raise ValueError("sentinel_observation_map_grid_invalid")
    cell_size = float(x[1] - x[0])
    if not math.isfinite(cell_size) or cell_size <= 0 or not np.allclose(np.diff(x), cell_size) or not np.allclose(np.diff(y), -cell_size):
        raise ValueError("sentinel_observation_map_grid_spacing_invalid")

    transformer = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)

    def coordinate(easting: float, northing: float) -> list[float]:
        longitude, latitude = transformer.transform(easting, northing)
        return [round(float(longitude), 7), round(float(latitude), 7)]

    features: list[dict[str, Any]] = []
    for row, col in zip(*np.where(labels)):
        left = float(x[col])
        right = float(x[col + 1])
        top = float(y[row])
        bottom = float(y[row + 1])
        features.append(
            {
                "type": "Feature",
                "id": f"sentinel_250m_{int(row):03d}_{int(col):03d}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        coordinate(left, top),
                        coordinate(right, top),
                        coordinate(right, bottom),
                        coordinate(left, bottom),
                        coordinate(left, top),
                    ]],
                },
                "properties": {
                    "cell_id": f"sentinel_250m_{int(row):03d}_{int(col):03d}",
                    "observed_flood_label": True,
                    "valid_fraction": round(float(valid_fraction[row, col]), 4),
                    "observed_water_fraction_of_valid_pixels": round(float(observed_fraction[row, col]), 4),
                    "observation_time_utc": dashboard["event"]["satellite_observation_utc"],
                    "source_resolution_m": 250,
                },
            }
        )

    return {
        "schema": "gwm.abu_dhabi_flood.sentinel2_observation_map.v1",
        "status": "available_external_holdout_observation_map",
        "event": dashboard["event"],
        "observation": dashboard["observation"],
        "geojson": {"type": "FeatureCollection", "features": features},
        "feature_count": len(features),
        "claim_boundary": dashboard["claim_boundary"],
    }
