from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer

from .config import Settings
from .errors import GwmApiError


BUNDLE_SCHEMA = "gwm.abu_dhabi_flood.inference_bundle.v1"
RUN_SCHEMA = "gwm.abu_dhabi_flood.standalone_rollout.v1"
WET_THRESHOLD_M = 0.01
RUN_ID_PATTERN = re.compile(r"^trained-gwm-\d{8}T\d{6}Z-[0-9a-f]{8}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GwmApiError(code, 500) from error
    if not isinstance(value, dict):
        raise GwmApiError(code, 500)
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_file(model_dir: Path, name: Any) -> Path:
    if not isinstance(name, str) or not name:
        raise GwmApiError("gwm_model_manifest_invalid", 500)
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise GwmApiError("gwm_model_manifest_invalid", 500)
    return model_dir / relative


def _mass_conserving_resample_hourly(source: list[float], target_hours: int) -> list[float]:
    if not source or target_hours < 1:
        raise GwmApiError("gwm_duration_invalid", 422)
    source_count = len(source)
    result: list[float] = []
    for target_index in range(target_hours):
        source_start = target_index * source_count / target_hours
        source_end = (target_index + 1) * source_count / target_hours
        first_source = int(math.floor(source_start))
        last_source = min(source_count - 1, int(math.ceil(source_end)) - 1)
        amount = 0.0
        for source_index in range(first_source, last_source + 1):
            overlap = max(
                0.0,
                min(source_end, source_index + 1.0)
                - max(source_start, float(source_index)),
            )
            amount += source[source_index] * overlap
        result.append(amount)
    if not math.isclose(sum(result), sum(source), rel_tol=1e-12, abs_tol=1e-9):
        raise GwmApiError("gwm_duration_resampling_failed", 500)
    return result


@dataclass(frozen=True)
class ModelBundle:
    manifest: dict[str, Any]
    coefficients: np.ndarray
    x: np.ndarray
    y: np.ndarray
    land_mask: np.ndarray
    hourly_precipitation_mm: list[float]
    manifest_sha256: str

    @classmethod
    def load(cls, model_dir: Path) -> "ModelBundle":
        manifest_path = model_dir / "manifest.json"
        manifest = _read_json(manifest_path, "gwm_model_manifest_invalid")
        if manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("status") != "ready":
            raise GwmApiError("gwm_model_manifest_invalid", 500)
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise GwmApiError("gwm_model_manifest_invalid", 500)
        for name, expected in files.items():
            path = _safe_file(model_dir, name)
            if not path.is_file() or not isinstance(expected, str) or not hmac.compare_digest(_sha256(path), expected):
                raise GwmApiError("gwm_model_checksum_mismatch", 500, str(name))

        coefficient_path = _safe_file(model_dir, manifest.get("model", {}).get("coefficients_file"))
        grid_path = _safe_file(model_dir, manifest.get("grid", {}).get("grid_file"))
        forcing_path = _safe_file(model_dir, manifest.get("default_profile", {}).get("forcing_file"))
        try:
            with np.load(coefficient_path, allow_pickle=False) as archive:
                coefficients = np.asarray(archive["coefficients"], dtype=np.float64)
                coefficient_land = np.asarray(archive["land_mask"], dtype=bool).reshape(-1)
            with np.load(grid_path, allow_pickle=False) as archive:
                x = np.asarray(archive["x"], dtype=np.float64)
                y = np.asarray(archive["y"], dtype=np.float64)
                land = np.asarray(archive["land_mask"], dtype=bool)
        except (OSError, ValueError, KeyError) as error:
            raise GwmApiError("gwm_model_assets_invalid", 500) from error

        forcing = _read_json(forcing_path, "gwm_forcing_invalid")
        hourly_raw = forcing.get("hourly_precipitation_mm")
        if not isinstance(hourly_raw, list) or not hourly_raw:
            raise GwmApiError("gwm_forcing_invalid", 500)
        hourly = [float(value) for value in hourly_raw]
        profile = manifest.get("default_profile") or {}
        base_hours = int(profile.get("base_rainfall_duration_hours", 0))
        tail_hours = int(profile.get("post_rainfall_tail_hours", -1))
        cell_size = float((manifest.get("grid") or {}).get("cell_size_m", 0.0))
        if (
            x.ndim != 1
            or y.ndim != 1
            or land.shape != (len(y) - 1, len(x) - 1)
            or coefficients.shape != (land.size, 4)
            or not np.array_equal(coefficient_land, land.reshape(-1))
            or cell_size <= 0.0
            or not np.allclose(np.diff(x), cell_size)
            or not np.allclose(np.diff(y), -cell_size)
            or base_hours < 1
            or tail_hours < 0
            or len(hourly) != base_hours + tail_hours
            or any(not math.isfinite(value) or value < 0.0 for value in hourly)
            or any(value > 1e-12 for value in hourly[base_hours:])
            or sum(hourly[:base_hours]) <= 0.0
        ):
            raise GwmApiError("gwm_model_contract_invalid", 500)
        return cls(
            manifest=manifest,
            coefficients=coefficients,
            x=x,
            y=y,
            land_mask=land,
            hourly_precipitation_mm=hourly,
            manifest_sha256=_sha256(manifest_path),
        )


class GwmEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bundle = ModelBundle.load(settings.model_dir)
        self.settings.run_dir.mkdir(parents=True, exist_ok=True)
        self._assert_writable()
        self._run_semaphore = threading.BoundedSemaphore(settings.max_concurrent_runs)
        self._index_lock = threading.RLock()

    def _assert_writable(self) -> None:
        probe = self.settings.run_dir / f".write-probe-{uuid.uuid4().hex}"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            raise RuntimeError("GWM_RUN_DIR is not writable") from error

    @property
    def profile(self) -> dict[str, Any]:
        return dict(self.bundle.manifest["default_profile"])

    @property
    def grid(self) -> dict[str, Any]:
        return dict(self.bundle.manifest["grid"])

    def disk_status(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.settings.run_dir)
        free_gb = usage.free / 1024**3
        return {
            "freeBytes": usage.free,
            "freeGb": round(free_gb, 3),
            "minimumFreeGb": self.settings.min_free_disk_gb,
            "sufficient": free_gb >= self.settings.min_free_disk_gb,
        }

    def readiness(self) -> dict[str, Any]:
        disk = self.disk_status()
        return {
            "status": "ready" if disk["sufficient"] else "not_ready",
            "modelReleaseId": self.bundle.manifest["model"]["release_id"],
            "modelManifestSha256": self.bundle.manifest_sha256,
            "runDirectoryWritable": True,
            "disk": disk,
        }

    def model_metadata(self) -> dict[str, Any]:
        manifest = self.bundle.manifest
        profile = self.profile
        return {
            "serviceSchema": RUN_SCHEMA,
            "model": {
                "releaseId": manifest["model"]["release_id"],
                "name": manifest["model"]["name"],
                "schema": manifest["model"]["schema"],
                "manifestSha256": self.bundle.manifest_sha256,
            },
            "grid": {
                "crs": self.grid["crs"],
                "cellSizeM": self.grid["cell_size_m"],
                "rows": int(self.bundle.land_mask.shape[0]),
                "columns": int(self.bundle.land_mask.shape[1]),
                "landCellCount": int(self.bundle.land_mask.sum()),
            },
            "inputs": {
                "totalRainfallMm": {
                    "minimum": 0.0,
                    "maximum": profile["maximum_total_precipitation_mm"],
                    "default": profile["base_total_precipitation_mm"],
                },
                "durationHours": {
                    "minimum": profile["minimum_rainfall_duration_hours"],
                    "maximum": profile["maximum_rainfall_duration_hours"],
                    "default": profile["base_rainfall_duration_hours"],
                },
            },
            "timeStepMinutes": 5,
            "resultRetention": "persistent_until_manually_removed",
            "claimBoundary": manifest["claim_boundary"],
        }

    def compatibility_events(self) -> dict[str, Any]:
        manifest = self.bundle.manifest
        model = manifest["model"]
        profile = self.profile
        adapter = {
            "schema": "gwm.abu_dhabi_flood.rainfall_amount_adapter.v1",
            "input_field": "totalRainfallMm",
            "input_unit": "mm",
            "base_total_precipitation_mm": profile["base_total_precipitation_mm"],
            "default_total_precipitation_mm": profile["base_total_precipitation_mm"],
            "minimum_total_precipitation_mm": 0.0,
            "maximum_total_precipitation_mm": profile["maximum_total_precipitation_mm"],
            "duration_input_field": "durationHours",
            "duration_unit": "hours",
            "base_rainfall_duration_hours": profile["base_rainfall_duration_hours"],
            "default_rainfall_duration_hours": profile["base_rainfall_duration_hours"],
            "minimum_rainfall_duration_hours": profile["minimum_rainfall_duration_hours"],
            "maximum_rainfall_duration_hours": profile["maximum_rainfall_duration_hours"],
            "post_rainfall_tail_hours": profile["post_rainfall_tail_hours"],
            "default_simulation_duration_hours": (
                profile["base_rainfall_duration_hours"] + profile["post_rainfall_tail_hours"]
            ),
            "mapped_parameter": "forcing.rainfallMultiplier",
            "mapping_formula": "totalRainfallMm / base_total_precipitation_mm",
        }
        return {
            "schema": "gwm.abu_dhabi_flood.trained_event_rollout.v1",
            "status": "available",
            "model": {
                "model_name": model["name"],
                "release_id": model["release_id"],
                "training_event_count": model["training_event_count"],
                "validation_event_count": model["validation_event_count"],
                "blind_test_event_count": model["blind_test_event_count"],
                "external_holdout_event_count": model["external_holdout_event_count"],
                "target": model.get("target"),
                "terrain": model.get("terrain"),
                "time_step_seconds": 300,
                "grid_cell_size_m": self.grid["cell_size_m"],
                "claim_boundary": manifest["claim_boundary"],
            },
            "events": [
                {
                    "event_id": profile["profile_id"],
                    "split": "external_test_2024_april",
                    "external_holdout": True,
                    "training_forbidden": True,
                    "start_utc": profile["start_utc"],
                    "end_utc": profile["end_utc"],
                    "rainfall_amount_adapter": adapter,
                }
            ],
            "external_holdout_policy": {
                "event_id": profile["profile_id"],
                "training_forbidden": True,
                "allowed_operation": "frozen_model_inference_only",
            },
        }

    def _run_path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise GwmApiError("gwm_run_id_invalid", 404)
        return self.settings.run_dir / run_id

    def _find_idempotent(self, key_hash: str, total: float, duration: int) -> dict[str, Any] | None:
        with self._index_lock:
            for path in self.settings.run_dir.glob("trained-gwm-*/run.json"):
                try:
                    record = _read_json(path, "gwm_run_record_invalid")
                except GwmApiError:
                    continue
                request = record.get("request") or {}
                if request.get("idempotency_key_sha256") != key_hash:
                    continue
                same = math.isclose(float(request.get("total_rainfall_mm", -1.0)), total, abs_tol=1e-9) and int(
                    request.get("duration_hours", -1)
                ) == duration
                if not same:
                    raise GwmApiError("gwm_idempotency_key_conflict", 409)
                return record
        return None

    def run(self, total_rainfall_mm: float, duration_hours: int, idempotency_key: str | None = None) -> dict[str, Any]:
        profile = self.profile
        maximum = float(profile["maximum_total_precipitation_mm"])
        minimum_duration = int(profile["minimum_rainfall_duration_hours"])
        maximum_duration = int(profile["maximum_rainfall_duration_hours"])
        if not math.isfinite(total_rainfall_mm) or total_rainfall_mm < 0.0:
            raise GwmApiError("gwm_total_rainfall_invalid", 422)
        if total_rainfall_mm > maximum and not math.isclose(total_rainfall_mm, maximum, abs_tol=1e-9):
            raise GwmApiError("gwm_total_rainfall_out_of_range", 422)
        if duration_hours < minimum_duration or duration_hours > maximum_duration:
            raise GwmApiError("gwm_duration_out_of_range", 422)

        key_hash: str | None = None
        if idempotency_key:
            if len(idempotency_key) > 200:
                raise GwmApiError("gwm_idempotency_key_invalid", 422)
            key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            existing = self._find_idempotent(key_hash, total_rainfall_mm, duration_hours)
            if existing is not None:
                return self.public_run(str(existing["run_id"]))

        if not self.disk_status()["sufficient"]:
            raise GwmApiError("gwm_insufficient_storage", 507)
        if not self._run_semaphore.acquire(blocking=False):
            raise GwmApiError("gwm_rollout_capacity_exceeded", 429)
        try:
            return self._execute(total_rainfall_mm, duration_hours, key_hash)
        finally:
            self._run_semaphore.release()

    def _execute(self, total: float, duration: int, key_hash: str | None) -> dict[str, Any]:
        profile = self.profile
        base_duration = int(profile["base_rainfall_duration_hours"])
        tail_hours = int(profile["post_rainfall_tail_hours"])
        base_pattern = self.bundle.hourly_precipitation_mm[:base_duration]
        resampled = _mass_conserving_resample_hourly(base_pattern, duration)
        scale = total / sum(resampled)
        hourly = np.asarray([value * scale for value in resampled] + [0.0] * tail_hours, dtype=np.float64)
        depth, times = self._rollout(hourly)
        run_id = f"trained-gwm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_dir = self._run_path(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        asset_name = "surface_depth_labels_250m.npz"
        temporary = run_dir / f".{asset_name}.{uuid.uuid4().hex}.tmp.npz"
        np.savez_compressed(
            temporary,
            depth_m=depth,
            time_seconds=times,
            x=self.bundle.x,
            y=self.bundle.y,
            land_mask=self.bundle.land_mask,
        )
        temporary.replace(run_dir / asset_name)

        land_flat = self.bundle.land_mask.reshape(-1)
        cell_size = float(self.grid["cell_size_m"])
        maximum_depth = depth.max(axis=0)
        affected = (maximum_depth >= WET_THRESHOLD_M) & land_flat
        storage = depth[:, land_flat].sum(axis=1, dtype=float) * cell_size**2
        frame_wet = (depth >= WET_THRESHOLD_M).sum(axis=1)
        first_renderable = int(next((index for index, count in enumerate(frame_wet) if count), 0))
        multiplier = total / float(profile["base_total_precipitation_mm"])
        temporal_modified = duration != base_duration
        created_at = datetime.now(timezone.utc).isoformat()
        period_count = int(len(times))
        metrics = {
            "maximum_depth_m": float(maximum_depth.max(initial=0.0)),
            "affected_cell_count": int(affected.sum()),
            "affected_area_m2": float(affected.sum() * cell_size**2),
            "peak_surface_storage_m3_proxy": float(storage.max(initial=0.0)),
        }
        scenario = {
            "kind": "rainfall_amount_duration_sensitivity" if temporal_modified else "rainfall_amount_sensitivity",
            "base_profile_id": profile["profile_id"],
            "base_total_precipitation_mm": profile["base_total_precipitation_mm"],
            "scenario_total_precipitation_mm": float(hourly.sum()),
            "rainfall_multiplier": multiplier,
            "rainfall_duration_hours": duration,
            "base_rainfall_duration_hours": base_duration,
            "post_rainfall_tail_hours": tail_hours,
            "simulation_duration_hours": duration + tail_hours,
            "mean_rainfall_intensity_mm_per_hour": total / duration,
            "temporal_scale_factor": duration / base_duration,
            "temporal_pattern_modified": temporal_modified,
            "temporal_resampling_method": "mass_conserving_piecewise_constant_hourly_overlap",
        }
        record = {
            "schema": RUN_SCHEMA,
            "run_id": run_id,
            "status": "completed",
            "created_at": created_at,
            "request": {
                "total_rainfall_mm": total,
                "duration_hours": duration,
                "idempotency_key_sha256": key_hash,
            },
            "metadata": {
                "run_id": run_id,
                "status": "completed",
                "model_mode": "standalone_frozen_inference",
                "solver": self.bundle.manifest["model"]["name"],
                "model": {
                    "release_id": self.bundle.manifest["model"]["release_id"],
                    "schema": self.bundle.manifest["model"]["schema"],
                    "manifest_sha256": self.bundle.manifest_sha256,
                },
                "event": {
                    "event_id": profile["profile_id"],
                    "external_holdout": profile["external_holdout"],
                    "training_forbidden": profile["training_forbidden"],
                },
                "scenario": scenario,
                "grid": {
                    "crs": self.grid["crs"],
                    "cell_size_m": cell_size,
                    "rows": int(self.bundle.land_mask.shape[0]),
                    "columns": int(self.bundle.land_mask.shape[1]),
                },
                "timeline": {
                    "available": True,
                    "run_id": run_id,
                    "endpoint": f"/v1/runs/{run_id}/timeseries",
                    "time_values": [f"T+{int(seconds // 60)} min" for seconds in times],
                    "elapsed_minutes": [float(seconds / 60.0) for seconds in times],
                    "period_count": period_count,
                    "step_minutes": 5.0,
                    "total_cell_count": int(self.bundle.land_mask.sum()),
                    "initial_time_index": first_renderable,
                },
                "input_adapter": {
                    "requested_total_precipitation_mm": total,
                    "requested_rainfall_duration_hours": duration,
                    "mapped_rainfall_multiplier": multiplier,
                },
                "quality": {
                    "model_manifest_sha256": self.bundle.manifest_sha256,
                    "deterministic_frozen_inference": True,
                },
                "claim_boundary": self.bundle.manifest["claim_boundary"],
            },
            "metrics": metrics,
            "assets": {"depth_labels": asset_name},
        }
        _write_json_atomic(run_dir / "run.json", record)
        return self.public_run(run_id)

    def _rollout(self, hourly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        land = self.bundle.land_mask.reshape(-1)
        step_count = int(len(hourly) * 12)
        times = np.arange(step_count + 1, dtype=np.float64) * 300.0
        depth = np.zeros((step_count + 1, land.size), dtype=np.float32)
        active = np.flatnonzero(land)
        current = np.zeros(len(active), dtype=np.float64)
        active_coefficients = self.bundle.coefficients[active]
        prefix = np.concatenate(([0.0], np.cumsum(hourly)))
        for index, seconds in enumerate(times[:-1]):
            hour_index = min(len(hourly) - 1, int(seconds // 3600.0))
            fraction = (seconds - hour_index * 3600.0) / 3600.0
            intensity = float(hourly[hour_index] / 10.0)
            cumulative = float((prefix[hour_index] + hourly[hour_index] * fraction) / 50.0)
            current = np.maximum(
                active_coefficients[:, 0]
                + active_coefficients[:, 1] * current
                + active_coefficients[:, 2] * intensity
                + active_coefficients[:, 3] * cumulative,
                0.0,
            )
            depth[index + 1, active] = current.astype(np.float32)
        return depth, times

    def _load_record(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id) / "run.json"
        if not path.is_file():
            raise GwmApiError("gwm_run_not_found", 404)
        record = _read_json(path, "gwm_run_record_invalid")
        if record.get("schema") != RUN_SCHEMA or record.get("status") != "completed":
            raise GwmApiError("gwm_run_record_invalid", 500)
        return record

    def _load_depth(self, record: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        run_id = str(record["run_id"])
        path = self._run_path(run_id) / str(record["assets"]["depth_labels"])
        try:
            with np.load(path, allow_pickle=False) as archive:
                depth = np.asarray(archive["depth_m"], dtype=np.float32)
                times = np.asarray(archive["time_seconds"], dtype=np.float64)
                x = np.asarray(archive["x"], dtype=np.float64)
                y = np.asarray(archive["y"], dtype=np.float64)
                land = np.asarray(archive["land_mask"], dtype=bool)
        except (OSError, ValueError, KeyError) as error:
            raise GwmApiError("gwm_run_asset_invalid", 500) from error
        if (
            depth.shape != (len(times), land.size)
            or not np.array_equal(x, self.bundle.x)
            or not np.array_equal(y, self.bundle.y)
            or not np.array_equal(land, self.bundle.land_mask)
        ):
            raise GwmApiError("gwm_run_asset_invalid", 500)
        return depth, times

    def public_run(self, run_id: str) -> dict[str, Any]:
        record = self._load_record(run_id)
        return {
            "run_id": run_id,
            "status": record["status"],
            "created_at": record["created_at"],
            "metadata": record["metadata"],
            "metrics": record["metrics"],
        }

    def v1_run(self, run_id: str) -> dict[str, Any]:
        public = self.public_run(run_id)
        metadata = public["metadata"]
        return {
            "runId": run_id,
            "status": public["status"],
            "createdAt": public["created_at"],
            "metrics": {
                "maximumDepthM": public["metrics"]["maximum_depth_m"],
                "affectedCellCount": public["metrics"]["affected_cell_count"],
                "affectedAreaM2": public["metrics"]["affected_area_m2"],
                "peakSurfaceStorageM3Proxy": public["metrics"]["peak_surface_storage_m3_proxy"],
                "periodCount": metadata["timeline"]["period_count"],
                "simulationDurationHours": metadata["scenario"]["simulation_duration_hours"],
            },
            "scenario": metadata["scenario"],
            "links": {
                "run": f"/v1/runs/{run_id}",
                "map": f"/v1/runs/{run_id}/map",
                "timeseries": f"/v1/runs/{run_id}/timeseries",
                "artifact": f"/v1/runs/{run_id}/artifacts/surface_depth_labels_250m.npz",
            },
        }

    def _features(self, values: np.ndarray, time_seconds: float | None) -> dict[str, Any]:
        grid = np.asarray(values, dtype=np.float32).reshape(self.bundle.land_mask.shape)
        selected = np.argwhere((grid >= WET_THRESHOLD_M) & self.bundle.land_mask)
        transformer = Transformer.from_crs(self.grid["crs"], "EPSG:4326", always_xy=True)
        features: list[dict[str, Any]] = []
        for row, col in selected:
            left, right = float(self.bundle.x[col]), float(self.bundle.x[col + 1])
            top, bottom = float(self.bundle.y[row]), float(self.bundle.y[row + 1])
            longitude, latitude = transformer.transform(
                [left, right, right, left, left],
                [top, top, bottom, bottom, top],
            )
            properties: dict[str, Any] = {
                "cell_id": int(row * self.bundle.land_mask.shape[1] + col),
                "depth_m": round(float(grid[row, col]), 5),
                "maximum_depth_m": round(float(grid[row, col]), 5),
                "cell_size_m": self.grid["cell_size_m"],
            }
            if time_seconds is not None:
                properties.update({"time_seconds": time_seconds, "time_minutes": time_seconds / 60.0})
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

    def map_bootstrap(self, run_id: str) -> dict[str, Any]:
        record = self._load_record(run_id)
        depth, times = self._load_depth(record)
        index = int(record["metadata"]["timeline"]["initial_time_index"])
        surface = self._features(depth[index], float(times[index]))
        maximum = self._features(depth.max(axis=0), None)
        return {
            "type": "FeatureCollection",
            "name": f"abu_dhabi_trained_gwm_{run_id}",
            "features": surface["features"],
            "surface": surface,
            "maximum_depth": maximum,
            "metadata": {**record["metadata"], "bootstrap_time_index": index},
        }

    def map_timeseries(self, run_id: str, time_index: int) -> dict[str, Any]:
        record = self._load_record(run_id)
        depth, times = self._load_depth(record)
        if time_index < 0 or time_index >= len(times):
            raise GwmApiError("gwm_time_index_out_of_range", 422)
        payload = self._features(depth[time_index], float(times[time_index]))
        payload["name"] = f"abu_dhabi_trained_gwm_time_{time_index:03d}"
        payload["metadata"] = {
            **record["metadata"],
            "time_index": time_index,
            "time_seconds": float(times[time_index]),
            "time_minutes": float(times[time_index] / 60.0),
        }
        return payload

    def artifact_path(self, run_id: str, artifact_name: str) -> Path:
        if artifact_name not in {"run.json", "surface_depth_labels_250m.npz"}:
            raise GwmApiError("gwm_artifact_not_found", 404)
        path = self._run_path(run_id) / artifact_name
        if not path.is_file():
            raise GwmApiError("gwm_artifact_not_found", 404)
        return path
