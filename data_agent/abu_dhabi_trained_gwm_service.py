"""Serve frozen five-year rainfall-conditioned GWM event rollouts.

This service is intentionally separate from the phase-4 rule-based scenario
adapter.  It loads the completed, quality-gated five-year cellwise ridge model
and runs it only against an admitted historical event forcing.  The April 2024
event remains an external holdout: it may be inferred and displayed, but never
used to fit or select this frozen model.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_five_year_event_gwm_20260914_r1"
)
DEFAULT_LABEL_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_city_swmm_2d_coupled_labels_20260914_r1"
)
DEFAULT_SENTINEL_OBSERVATION_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_sentinel2_observed_flood_202404_r1"
)
DEFAULT_RUN_ROOT = (
    Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater/trained_gwm_runs"
)
EXTERNAL_HOLDOUT_EVENT_ID = "noaa-isd-ae-202404151200-0327"
MODEL_NAME = "cellwise_ridge_rainfall_conditioned_dynamics"
MODEL_SCHEMA = "gwm.abu_dhabi_flood.five_year_event_emulator.v1"
MODEL_RELEASE_ID = "GWM-R1-20260914"
RUN_SCHEMA = "gwm.abu_dhabi_flood.trained_event_rollout.v1"
WET_THRESHOLD_M = 0.01
GRID_CRS = "EPSG:32640"
GRID_CELL_SIZE_M = 250.0

_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.expanduser().resolve()


def _model_root() -> Path:
    return _configured_path("ABU_DHABI_TRAINED_GWM_MODEL_ROOT", DEFAULT_MODEL_ROOT)


def _label_root() -> Path:
    return _configured_path("ABU_DHABI_TRAINED_GWM_LABEL_ROOT", DEFAULT_LABEL_ROOT)


def _sentinel_observation_root() -> Path:
    return _configured_path(
        "ABU_DHABI_TRAINED_GWM_SENTINEL_OBSERVATION_ROOT",
        DEFAULT_SENTINEL_OBSERVATION_ROOT,
    )


def _run_root() -> Path:
    return _configured_path("ABU_DHABI_TRAINED_GWM_RUN_ROOT", DEFAULT_RUN_ROOT)


def _read_json(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_name(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(error_code)
    return str(path)


def _load_model_contract() -> tuple[dict[str, Any], dict[str, Any], Path]:
    root = _model_root()
    receipt = _read_json(root / "run_receipt.json", "trained_gwm_receipt_invalid")
    card = _read_json(root / "gwm_model_card.json", "trained_gwm_model_card_invalid")
    split = _read_json(root / "split_manifest.json", "trained_gwm_split_manifest_invalid")
    coefficients = root / "five_year_full_train_cellwise_ridge_coefficients.npz"
    train = {str(value) for value in receipt.get("events", {}).get("train", [])}
    external = split.get("split", {}).get("external_test_2024_april")
    if (
        receipt.get("status") != "completed"
        or receipt.get("conclusion", {}).get("external_test_is_reported_only") is not True
        or card.get("schema") != MODEL_SCHEMA
        or card.get("model_name") != MODEL_NAME
        or split.get("event_disjoint") is not True
        or split.get("external_holdout_excluded_from_training") is not True
        or external != [EXTERNAL_HOLDOUT_EVENT_ID]
        or EXTERNAL_HOLDOUT_EVENT_ID in train
        or not coefficients.is_file()
    ):
        raise ValueError("trained_gwm_model_contract_invalid")
    return receipt, card, coefficients


def _event_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    root = _label_root()
    batch = _read_json(root / "batch_manifest.json", "trained_gwm_batch_manifest_invalid")
    selection = batch.get("selection")
    summary_rows = batch.get("events")
    if batch.get("status") != "completed" or int(batch.get("failed_event_count", -1)) != 0:
        raise ValueError("trained_gwm_batch_not_completed")
    if not isinstance(selection, dict) or not isinstance(selection.get("events"), list) or not isinstance(summary_rows, list):
        raise ValueError("trained_gwm_batch_event_catalog_invalid")
    summaries = {str(row.get("event_id")): row for row in summary_rows if isinstance(row, dict)}
    catalog: dict[str, dict[str, Any]] = {}
    for item in selection["events"]:
        if not isinstance(item, dict):
            raise ValueError("trained_gwm_batch_event_catalog_invalid")
        event_id = str(item.get("event_id") or "")
        split = str(item.get("split") or "")
        if not event_id or split not in {"train", "validation", "test", "external_test_2024_april"}:
            raise ValueError("trained_gwm_batch_event_catalog_invalid")
        summary = summaries.get(event_id)
        if (
            summary is None
            or summary.get("status") not in {"completed", "skipped_completed"}
            or summary.get("quality_passed") is not True
        ):
            raise ValueError("trained_gwm_batch_event_quality_invalid")
        catalog[event_id] = {
            "event_id": event_id,
            "split": split,
            "external_holdout": bool(item.get("external_holdout")),
            "start_utc": str(item.get("start_utc") or ""),
            "end_utc": str(item.get("end_utc") or ""),
        }
    if EXTERNAL_HOLDOUT_EVENT_ID not in catalog or catalog[EXTERNAL_HOLDOUT_EVENT_ID]["external_holdout"] is not True:
        raise ValueError("trained_gwm_external_holdout_contract_invalid")
    return catalog, batch


def _model_split_summary(receipt: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event_groups = receipt.get("events") or {}
    training_ids = {str(value) for value in event_groups.get("train", [])}
    training_events = [catalog[event_id] for event_id in training_ids if event_id in catalog]
    starts = sorted(str(event.get("start_utc") or "") for event in training_events if event.get("start_utc"))
    ends = sorted(str(event.get("end_utc") or "") for event in training_events if event.get("end_utc"))
    return {
        "release_id": MODEL_RELEASE_ID,
        "training_event_count": len(training_ids),
        "validation_event_count": len(event_groups.get("validation", [])),
        "blind_test_event_count": len(event_groups.get("test", [])),
        "external_holdout_event_count": len(event_groups.get("external_test_2024_april", [])),
        "training_period_start_utc": starts[0] if starts else None,
        "training_period_end_utc": ends[-1] if ends else None,
    }


def _load_event_assets(event: dict[str, Any]) -> tuple[dict[str, Any], Path, Path]:
    event_id = str(event["event_id"])
    event_root = _label_root() / "events" / event_id
    receipt = _read_json(event_root / "run_receipt.json", "trained_gwm_event_receipt_invalid")
    receipt_event = receipt.get("event") or {}
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or receipt_event.get("event_id") != event_id
        or receipt_event.get("split") != event["split"]
        or bool(receipt_event.get("external_holdout")) != bool(event["external_holdout"])
    ):
        raise ValueError("trained_gwm_event_receipt_contract_invalid")
    depth_name = _safe_relative_name(
        (receipt.get("outputs") or {}).get("depth_labels"),
        "trained_gwm_event_depth_asset_invalid",
    )
    depth_path = event_root / depth_name
    forcing_path = event_root / "forcing.json"
    if not depth_path.is_file() or not forcing_path.is_file():
        raise ValueError("trained_gwm_event_assets_missing")
    return receipt, depth_path, forcing_path


def _external_holdout_forcing(event: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Load the only forcing that reaches the frozen Sentinel-2 observation."""

    if event.get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID or not event.get("external_holdout"):
        raise ValueError("trained_gwm_external_holdout_contract_invalid")
    root = _sentinel_observation_root()
    receipt = _read_json(root / "run_receipt.json", "trained_gwm_sentinel_observation_receipt_invalid")
    observation_event = receipt.get("event")
    external_evaluation = receipt.get("external_evaluation")
    if (
        receipt.get("status") != "completed"
        or receipt.get("quality_passed") is not True
        or not isinstance(observation_event, dict)
        or observation_event.get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID
        or observation_event.get("external_holdout") is not True
        or observation_event.get("training_forbidden") is not True
        or not isinstance(external_evaluation, dict)
    ):
        raise ValueError("trained_gwm_sentinel_observation_contract_invalid")
    forcing_name = _safe_relative_name(
        external_evaluation.get("forcing_with_zero_rain_tail"),
        "trained_gwm_sentinel_forcing_invalid",
    )
    forcing_path = root / forcing_name
    forcing = _read_json(forcing_path, "trained_gwm_sentinel_forcing_invalid")
    model_frame_seconds = forcing.get("nearest_300_second_model_frame_seconds")
    satellite_seconds = observation_event.get("observation_time_seconds_from_event_start")
    satellite_utc = observation_event.get("satellite_observation_utc")
    if (
        not forcing_path.is_file()
        or forcing.get("event_id") != EXTERNAL_HOLDOUT_EVENT_ID
        or forcing.get("purpose") != "external satellite-overpass evaluation only; forbidden from GWM training"
        or isinstance(model_frame_seconds, bool)
        or not isinstance(model_frame_seconds, (int, float))
        or not math.isfinite(float(model_frame_seconds))
        or float(model_frame_seconds) < 0.0
        or float(model_frame_seconds) % 300.0 != 0.0
        or isinstance(satellite_seconds, bool)
        or not isinstance(satellite_seconds, (int, float))
        or not math.isfinite(float(satellite_seconds))
        or float(satellite_seconds) < 0.0
        or not isinstance(satellite_utc, str)
        or not satellite_utc
    ):
        raise ValueError("trained_gwm_sentinel_forcing_invalid")
    return forcing_path, {
        "satellite_observation_utc": satellite_utc,
        "satellite_observation_seconds": float(satellite_seconds),
        "model_frame_seconds": float(model_frame_seconds),
        "model_frame_index": int(float(model_frame_seconds) // 300.0),
        "zero_rainfall_tail_hours": forcing.get("zero_rainfall_tail_hours"),
        "forcing_sha256": _sha256(forcing_path),
    }


def _load_grid_and_forcing(depth_path: Path, forcing_path: Path) -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("trained_gwm_numpy_dependency_missing") from error
    forcing = _read_json(forcing_path, "trained_gwm_forcing_invalid")
    hourly = np.asarray(forcing.get("hourly_precipitation_mm"), dtype=np.float64)
    if hourly.ndim != 1 or not len(hourly) or not np.isfinite(hourly).all() or (hourly < 0).any():
        raise ValueError("trained_gwm_forcing_invalid")
    try:
        with np.load(depth_path, allow_pickle=False) as archive:
            x = np.asarray(archive["x"], dtype=np.float64)
            y = np.asarray(archive["y"], dtype=np.float64)
            land = np.asarray(archive["land_mask"], dtype=bool)
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("trained_gwm_grid_asset_invalid") from error
    if (
        x.ndim != 1
        or y.ndim != 1
        or len(x) < 2
        or len(y) < 2
        or land.shape != (len(y) - 1, len(x) - 1)
        or not np.allclose(np.diff(x), GRID_CELL_SIZE_M)
        or not np.allclose(np.diff(y), -GRID_CELL_SIZE_M)
    ):
        raise ValueError("trained_gwm_grid_contract_invalid")
    return hourly, x, y, land


def _rain_features(hourly: Any, seconds: float) -> tuple[float, float]:
    hour_index = min(len(hourly) - 1, int(seconds // 3600.0))
    fraction = (seconds - hour_index * 3600.0) / 3600.0
    cumulative = float(hourly[:hour_index].sum() + hourly[hour_index] * fraction)
    return float(hourly[hour_index] / 10.0), float(cumulative / 50.0)


def _rollout(coefficients_path: Path, hourly: Any, land: Any) -> tuple[Any, Any]:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("trained_gwm_numpy_dependency_missing") from error
    try:
        with np.load(coefficients_path, allow_pickle=False) as archive:
            coefficients = np.asarray(archive["coefficients"], dtype=np.float64)
            model_land = np.asarray(archive["land_mask"], dtype=bool).reshape(-1)
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("trained_gwm_coefficients_invalid") from error
    flat_land = land.reshape(-1)
    if coefficients.shape != (flat_land.size, 4) or not np.array_equal(model_land, flat_land):
        raise ValueError("trained_gwm_coefficient_grid_mismatch")
    step_count = int(len(hourly) * 12)
    times = np.arange(step_count + 1, dtype=np.float64) * 300.0
    depth = np.zeros((step_count + 1, flat_land.size), dtype=np.float32)
    active = np.flatnonzero(flat_land)
    current = np.zeros(len(active), dtype=np.float64)
    active_coefficients = coefficients[active]
    for index, seconds in enumerate(times[:-1]):
        intensity, cumulative = _rain_features(hourly, float(seconds))
        current = np.maximum(
            active_coefficients[:, 0]
            + active_coefficients[:, 1] * current
            + active_coefficients[:, 2] * intensity
            + active_coefficients[:, 3] * cumulative,
            0.0,
        )
        depth[index + 1, active] = current.astype(np.float32)
    return depth, times


def _persist_rollout(run_dir: Path, depth: Any, times: Any, x: Any, y: Any, land: Any) -> str:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("trained_gwm_numpy_dependency_missing") from error
    filename = "surface_depth_labels_250m.npz"
    temporary = run_dir / f".{filename}.tmp.npz"
    run_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        temporary,
        depth_m=depth,
        time_seconds=times,
        x=x,
        y=y,
        land_mask=land,
    )
    temporary.replace(run_dir / filename)
    return filename


def _event_public(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "split": event["split"],
        "external_holdout": event["external_holdout"],
        "training_forbidden": bool(event["external_holdout"]),
        "start_utc": event["start_utc"],
        "end_utc": event["end_utc"],
    }


def available_events() -> dict[str, Any]:
    receipt, card, _ = _load_model_contract()
    catalog, _ = _event_catalog()
    split_summary = _model_split_summary(receipt, catalog)
    events = [_event_public(event) for event in catalog.values()]
    events.sort(key=lambda item: (item["start_utc"], item["event_id"]))
    return {
        "schema": RUN_SCHEMA,
        "status": "available",
        "model": {
            "model_name": card["model_name"],
            **split_summary,
            "target": card.get("target"),
            "time_step_seconds": 300,
            "grid_cell_size_m": GRID_CELL_SIZE_M,
            "terrain": card.get("terrain"),
            "claim_boundary": card.get("claim_boundary"),
        },
        "events": events,
        "external_holdout_policy": {
            "event_id": EXTERNAL_HOLDOUT_EVENT_ID,
            "training_forbidden": True,
            "allowed_operation": "frozen_model_inference_and_external_reporting_only",
        },
    }


def _event_from_payload(payload: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("trained_gwm_payload_invalid")
    event_id = payload.get("eventId", payload.get("event_id"))
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("trained_gwm_event_id_required")
    event = catalog.get(event_id)
    if event is None:
        raise ValueError("trained_gwm_event_not_admitted")
    return event


def start_rollout(payload: dict[str, Any]) -> dict[str, Any]:
    receipt, card, coefficients_path = _load_model_contract()
    catalog, _ = _event_catalog()
    split_summary = _model_split_summary(receipt, catalog)
    event = _event_from_payload(payload, catalog)
    event_receipt, depth_path, forcing_path = _load_event_assets(event)
    external_validation: dict[str, Any] | None = None
    if event["external_holdout"]:
        forcing_path, external_validation = _external_holdout_forcing(event)
    hourly, x, y, land = _load_grid_and_forcing(depth_path, forcing_path)
    depth, times = _rollout(coefficients_path, hourly, land)
    if external_validation is not None:
        reference_index = int(external_validation["model_frame_index"])
        if reference_index >= len(times):
            raise ValueError("trained_gwm_sentinel_forcing_does_not_cover_overpass")
    else:
        reference_index = -1
    run_id = f"trained-gwm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = _run_root() / run_id
    depth_asset = _persist_rollout(run_dir, depth, times, x, y, land)
    maximum = depth.max(axis=0)
    affected = (maximum >= WET_THRESHOLD_M) & land.reshape(-1)
    frame_wet = (depth >= WET_THRESHOLD_M).sum(axis=1)
    first_renderable = int(next((index for index, count in enumerate(frame_wet) if count), 0))
    initial_time_index = reference_index if reference_index >= 0 else first_renderable
    time_values = [f"T+{int(seconds // 60)} min" for seconds in times]
    if external_validation is not None:
        time_values[reference_index] = f"T+{int(times[reference_index] // 60)} min · Sentinel-2 同相位"
    metadata = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "status": "completed",
        "model_mode": "trained_event_rollout",
        "solver": MODEL_NAME,
        "event": _event_public(event),
        "model": {
            "schema": card["schema"],
            "name": card["model_name"],
            **split_summary,
            "target": card.get("target"),
            "inputs": card.get("inputs"),
            "selected_regularization": card.get("selected_regularization", {}).get("five_year_full_train"),
        },
        "terrain": card.get("terrain"),
        "external_validation": external_validation,
        "grid": {"crs": GRID_CRS, "cell_size_m": GRID_CELL_SIZE_M, "rows": int(land.shape[0]), "columns": int(land.shape[1])},
        "timeline": {
            "available": True,
            "run_id": run_id,
            "endpoint": f"/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map/timeseries",
            "time_values": time_values,
            "elapsed_minutes": [float(seconds / 60.0) for seconds in times],
            "period_count": int(len(times)),
            "step_minutes": 5.0,
            "total_cell_count": int(land.sum()),
            "initial_time_index": initial_time_index,
        },
        "quality": {
            "model_run_receipt_sha256": _sha256(_model_root() / "run_receipt.json"),
            "event_run_receipt_sha256": _sha256(_label_root() / "events" / event["event_id"] / "run_receipt.json"),
            "event_physics_label_quality_passed": event_receipt["quality_passed"],
            "external_holdout_is_reported_only": bool(event["external_holdout"]),
            "training_forbidden": bool(event["external_holdout"]),
            "external_evaluation_forcing_sha256": external_validation["forcing_sha256"] if external_validation else None,
        },
        "claim_boundary": "Frozen five-year research GWM inference over an admitted historical rainfall forcing. It emulates 250 m SWMM--ANUGA labels and is not an engineering replacement for the physical solver.",
    }
    record = {
        "run_id": run_id,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_mode": "trained_event_rollout",
        "metadata": metadata,
        "assets": {"depth_labels": depth_asset},
    }
    _write_json(run_dir / "run.json", record)
    with _LOCK:
        _RUNS[run_id] = record
    return public_run(run_id)


def _get(run_id: str) -> dict[str, Any]:
    with _LOCK:
        record = _RUNS.get(run_id)
    if record is None:
        record = _read_json(_run_root() / run_id / "run.json", "trained_gwm_run_invalid")
        with _LOCK:
            _RUNS[run_id] = record
    if record.get("model_mode") != "trained_event_rollout" or record.get("status") != "completed":
        raise ValueError("trained_gwm_run_contract_invalid")
    return record


def _load_depth_record(record: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("trained_gwm_numpy_dependency_missing") from error
    run_id = str(record.get("run_id") or "")
    name = _safe_relative_name((record.get("assets") or {}).get("depth_labels"), "trained_gwm_run_asset_invalid")
    path = _run_root() / run_id / name
    if not path.is_file():
        raise ValueError("trained_gwm_run_asset_missing")
    try:
        with np.load(path, allow_pickle=False) as archive:
            depth = np.asarray(archive["depth_m"], dtype=np.float32)
            times = np.asarray(archive["time_seconds"], dtype=np.float64)
            x = np.asarray(archive["x"], dtype=np.float64)
            y = np.asarray(archive["y"], dtype=np.float64)
            land = np.asarray(archive["land_mask"], dtype=bool)
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("trained_gwm_run_asset_invalid") from error
    if (
        depth.ndim != 2
        or depth.shape != (len(times), land.size)
        or land.shape != (len(y) - 1, len(x) - 1)
        or not np.allclose(np.diff(times), 300.0)
        or not np.allclose(np.diff(x), GRID_CELL_SIZE_M)
        or not np.allclose(np.diff(y), -GRID_CELL_SIZE_M)
    ):
        raise ValueError("trained_gwm_run_grid_invalid")
    return depth, times, x, y, land


def _features(values: Any, x: Any, y: Any, land: Any, *, event: dict[str, Any], time_seconds: float | None) -> dict[str, Any]:
    try:
        import numpy as np
        from pyproj import Transformer
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("trained_gwm_map_dependencies_missing") from error
    grid = np.asarray(values, dtype=np.float32).reshape(land.shape)
    selected = np.argwhere((grid >= WET_THRESHOLD_M) & land)
    transformer = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
    features: list[dict[str, Any]] = []
    for row, col in selected:
        left, right = float(x[col]), float(x[col + 1])
        top, bottom = float(y[row]), float(y[row + 1])
        easting = [left, right, right, left, left]
        northing = [top, top, bottom, bottom, top]
        longitude, latitude = transformer.transform(easting, northing)
        properties: dict[str, Any] = {
            "cell_id": int(row * land.shape[1] + col),
            "depth_m": round(float(grid[row, col]), 5),
            "maximum_depth_m": round(float(grid[row, col]), 5),
            "prototype_cell_size_m": GRID_CELL_SIZE_M,
            "event_id": event["event_id"],
            "event_split": event["split"],
            "external_holdout": event["external_holdout"],
        }
        if time_seconds is not None:
            properties.update({"time_seconds": float(time_seconds), "time_minutes": float(time_seconds / 60.0)})
        features.append(
            {
                "type": "Feature",
                "id": f"trained_gwm_{int(row):03d}_{int(col):03d}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [round(float(lon), 7), round(float(lat), 7)]
                        for lon, lat in zip(longitude, latitude)
                    ]],
                },
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def public_run(run_id: str) -> dict[str, Any]:
    record = _get(run_id)
    depth, _, _, _, land = _load_depth_record(record)
    maximum = depth.max(axis=0)
    affected = (maximum >= WET_THRESHOLD_M) & land.reshape(-1)
    storage = depth[:, land.reshape(-1)].sum(axis=1, dtype=float) * GRID_CELL_SIZE_M**2
    return {
        "run_id": run_id,
        "status": record["status"],
        "created_at": record["created_at"],
        "metadata": record["metadata"],
        "metrics": {
            "maximum_depth_m": float(maximum.max(initial=0.0)),
            "affected_cell_count": int(affected.sum()),
            "affected_area_m2": float(affected.sum() * GRID_CELL_SIZE_M**2),
            "peak_surface_storage_m3_proxy": float(storage.max(initial=0.0)),
        },
    }


def map_bootstrap(run_id: str) -> dict[str, Any]:
    record = _get(run_id)
    depth, times, x, y, land = _load_depth_record(record)
    metadata = dict(record["metadata"])
    event = metadata["event"]
    maximum = _features(depth.max(axis=0), x, y, land, event=event, time_seconds=None)
    index = int(metadata["timeline"]["initial_time_index"])
    surface = _features(depth[index], x, y, land, event=event, time_seconds=float(times[index]))
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_trained_gwm_{run_id}",
        "features": surface["features"],
        "metadata": {**metadata, "bootstrap_time_index": index},
        "maximum_depth": maximum,
        "surface": surface,
    }


def map_timeseries(run_id: str, time_index: int) -> dict[str, Any]:
    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("trained_gwm_time_index_invalid")
    record = _get(run_id)
    depth, times, x, y, land = _load_depth_record(record)
    if time_index < 0 or time_index >= len(times):
        raise ValueError("trained_gwm_time_index_out_of_range")
    metadata = dict(record["metadata"])
    payload = _features(depth[time_index], x, y, land, event=metadata["event"], time_seconds=float(times[time_index]))
    payload["name"] = f"abu_dhabi_trained_gwm_time_{time_index:03d}"
    payload["metadata"] = {**metadata, "time_index": time_index, "time_seconds": float(times[time_index]), "time_minutes": float(times[time_index] / 60.0)}
    return payload


__all__ = ["available_events", "start_rollout", "public_run", "map_bootstrap", "map_timeseries"]
