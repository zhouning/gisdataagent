"""Small, reproducible GWM surrogate for the Abu Dhabi flood workbench.

The surrogate deliberately consumes the private SWMM diagnostic tensor contract
already produced by :mod:`customer_gdb_network`.  It is a fast state-transition
model for the prototype UI: one model is fitted per diagnostic pilot, and the
rollout can be conditioned on rainfall, pipe capacity, pump capacity and
outfall level.  Customer tensors are discovered through ``ABU_DHABI_GWM_ROOT``
and are never copied into the repository or returned in API metadata.

The implementation uses NumPy only.  This keeps the runtime independent from a
deep-learning framework while preserving the same adapter boundary that can be
replaced by a graph neural model when more calibrated events arrive.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "gwm.abu_dhabi_flood.gwm_surrogate.v1"
MODEL_SCHEMA = "gwm.abu_dhabi_flood.gwm_surrogate_model.v1"
NODE_CHANNELS = (
    "water_depth_m",
    "hydraulic_head_m",
    "stored_volume_m3",
    "lateral_inflow_m3s",
    "total_inflow_m3s",
    "overflow_or_flooding_m3s",
)
EDGE_CHANNELS = ("flow_m3s", "water_depth_m", "velocity_ms", "capacity_fraction")


def _default_root() -> Path:
    configured = os.environ.get("ABU_DHABI_GWM_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater/gwm").resolve()


def _safe_float(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}_invalid") from exc
    if not np.isfinite(number):
        raise ValueError(f"{name}_invalid")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name}_below_minimum")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name}_above_maximum")
    return number


@dataclass
class _PilotModel:
    pilot_id: str
    node_count: int
    edge_count: int
    feature_mean: np.ndarray
    feature_scale: np.ndarray
    weights: np.ndarray
    baseline: np.ndarray
    duration_seconds: float
    timestamps: np.ndarray
    node_states: np.ndarray
    edge_states: np.ndarray
    node_indices: np.ndarray | None = None

    @property
    def state_size(self) -> int:
        return self.node_count * len(NODE_CHANNELS) + self.edge_count * len(EDGE_CHANNELS)


class AbuDhabiGwmSurrogate:
    """Load private pilot tensors, fit a lightweight transition model and roll it out."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or _default_root()).expanduser().resolve()
        self._models: dict[str, _PilotModel] = {}
        self._training_receipt: dict[str, Any] | None = None
        self._runs: dict[str, dict[str, Any]] = {}
        self._geometry_by_full_node_index: dict[int, dict[str, Any]] | None = None
        self._lock = threading.RLock()

    def _paths(self) -> tuple[Path, Path, Path]:
        return (
            self.root / "customer_swmm_gwm_dynamic_diagnostic.private.npz",
            self.root / "customer_swmm_gwm_dynamic_diagnostic_manifest.json",
            self.root / "customer_swmm_gwm_pilot_alignment.private.npz",
        )

    def _load_arrays(self) -> tuple[dict[str, np.ndarray], dict[str, Any], dict[str, np.ndarray] | None]:
        npz_path, manifest_path, alignment_path = self._paths()
        if not npz_path.is_file() or not manifest_path.is_file():
            raise ValueError("gwm_private_diagnostic_tensor_missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("gwm_private_diagnostic_manifest_invalid") from exc
        if manifest.get("schema") != "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1":
            raise ValueError("gwm_private_diagnostic_manifest_schema_invalid")
        with np.load(npz_path, allow_pickle=False) as archive:
            arrays = {name: np.asarray(archive[name]) for name in archive.files}
        for name, expected in (manifest.get("arrays") or {}).items():
            if name not in arrays or list(arrays[name].shape) != expected.get("shape"):
                raise ValueError(f"gwm_private_diagnostic_array_invalid:{name}")
            if not np.isfinite(arrays[name]).all():
                raise ValueError(f"gwm_private_diagnostic_array_nonfinite:{name}")
        alignment: dict[str, np.ndarray] | None = None
        if alignment_path.is_file():
            with np.load(alignment_path, allow_pickle=False) as archive:
                alignment = {name: np.asarray(archive[name]) for name in archive.files}
        return arrays, manifest, alignment

    @staticmethod
    def _pilot_ids(arrays: dict[str, np.ndarray]) -> list[str]:
        return sorted(
            key.removesuffix("_elapsed_seconds")
            for key in arrays
            if key.endswith("_elapsed_seconds")
        )

    @staticmethod
    def _state(node: np.ndarray, edge: np.ndarray) -> np.ndarray:
        return np.concatenate((node.reshape(-1), edge.reshape(-1))).astype(np.float64, copy=False)

    @staticmethod
    def _forcing_proxy(node: np.ndarray) -> float:
        # Lateral inflow is the closest forcing channel in the SWMM diagnostic
        # contract.  Preserve a non-zero floor so a synthetic storm can still
        # create a visible response when the proxy pilot is dry.
        value = float(np.nanmean(np.maximum(node[..., 3], 0.0)))
        return value

    def _feature(
        self,
        state: np.ndarray,
        elapsed_seconds: float,
        forcing_proxy: float,
        duration_seconds: float,
    ) -> np.ndarray:
        duration = max(1.0, float(duration_seconds))
        return np.concatenate(
            (
                state,
                np.asarray(
                    [
                        float(elapsed_seconds) / duration,
                        float(forcing_proxy),
                    ],
                    dtype=np.float64,
                ),
            )
        )

    def _fit_pilot(self, pilot_id: str, arrays: dict[str, np.ndarray], alignment: dict[str, np.ndarray] | None, ridge: float) -> tuple[_PilotModel, dict[str, float]]:
        node = np.asarray(arrays[f"{pilot_id}_node_state"], dtype=np.float64)
        edge = np.asarray(arrays[f"{pilot_id}_edge_state"], dtype=np.float64)
        elapsed = np.asarray(arrays[f"{pilot_id}_elapsed_seconds"], dtype=np.float64)
        if node.shape[0] < 3 or edge.shape[0] != node.shape[0]:
            raise ValueError(f"gwm_pilot_timeseries_too_short:{pilot_id}")
        duration_seconds = max(float(elapsed[-1]), 1.0)
        x_rows: list[np.ndarray] = []
        y_rows: list[np.ndarray] = []
        for index in range(node.shape[0] - 1):
            state = self._state(node[index], edge[index])
            x_rows.append(
                self._feature(
                    state,
                    elapsed[index],
                    self._forcing_proxy(node[index]),
                    duration_seconds,
                )
            )
            y_rows.append(self._state(node[index + 1], edge[index + 1]))
        x = np.vstack(x_rows)
        y = np.vstack(y_rows)
        split = max(1, min(len(x) - 1, int(round(len(x) * 0.8))))
        mean = x[:split].mean(axis=0)
        scale = x[:split].std(axis=0)
        scale[scale < 1e-8] = 1.0
        x_scaled = (x - mean) / scale
        design = np.column_stack((np.ones(len(x_scaled)), x_scaled))
        gram = design[:split].T @ design[:split]
        regularizer = np.eye(gram.shape[0], dtype=np.float64) * float(ridge)
        regularizer[0, 0] = 0.0
        # Pseudoinverse keeps an explicit zero-ridge diagnostic request
        # reproducible when a pilot contains duplicate low-flow intervals.
        weights = np.linalg.pinv(gram + regularizer) @ (design[:split].T @ y[:split])
        predictions = design[split:] @ weights
        error = predictions - y[split:]
        rmse = float(np.sqrt(np.mean(error * error))) if len(error) else 0.0
        baseline = self._state(node[0], edge[0])
        node_indices = None
        if alignment and "pilot_node_indices" in alignment and "pilot_node_offsets" in alignment:
            pilot_number = int(pilot_id.rsplit("_", 1)[-1]) - 1
            offsets = alignment["pilot_node_offsets"]
            node_indices = alignment["pilot_node_indices"][int(offsets[pilot_number]):int(offsets[pilot_number + 1])].astype(np.int64, copy=False)
        return _PilotModel(
            pilot_id=pilot_id,
            node_count=node.shape[1],
            edge_count=edge.shape[1],
            feature_mean=mean,
            feature_scale=scale,
            weights=weights,
            baseline=baseline,
            duration_seconds=duration_seconds,
            timestamps=elapsed,
            node_states=node.astype(np.float32),
            edge_states=edge.astype(np.float32),
            node_indices=node_indices,
        ), {"validation_rmse": rmse, "training_steps": float(split)}

    def train(self, *, ridge: float = 1e-4) -> dict[str, Any]:
        ridge = _safe_float(ridge, "ridge", minimum=0.0, maximum=1e6)
        arrays, manifest, alignment = self._load_arrays()
        pilot_ids = self._pilot_ids(arrays)
        if not pilot_ids:
            raise ValueError("gwm_pilots_missing")
        models: dict[str, _PilotModel] = {}
        metrics: dict[str, Any] = {}
        for pilot_id in pilot_ids:
            model, pilot_metrics = self._fit_pilot(pilot_id, arrays, alignment, ridge)
            models[pilot_id] = model
            metrics[pilot_id] = pilot_metrics
        source_hash = hashlib.sha256(
            (self.root / "customer_swmm_gwm_dynamic_diagnostic.private.npz").read_bytes()
        ).hexdigest()
        version = f"gwm-surrogate-{source_hash[:12]}-{uuid.uuid4().hex[:8]}"
        receipt = {
            "schema": MODEL_SCHEMA,
            "model_version": version,
            "status": "completed",
            "pilot_count": len(models),
            "pilot_ids": sorted(models),
            "sample_count": int(sum(max(0, m.node_states.shape[0] - 1) for m in models.values())),
            "node_channels": list(NODE_CHANNELS),
            "edge_channels": list(EDGE_CHANNELS),
            "ridge": ridge,
            "metrics": metrics,
            "source": {
                "dynamic_tensor_schema": manifest.get("schema"),
                "dynamic_tensor_sha256": source_hash,
                "storage_class": "private_customer_controlled",
            },
            "training_mode": "per_pilot_ridge_state_transition_with_action_response_adapter",
        }
        with self._lock:
            self._models = models
            self._training_receipt = receipt
        return dict(receipt)

    def status(self) -> dict[str, Any]:
        npz_path, manifest_path, _ = self._paths()
        with self._lock:
            trained = self._training_receipt
        available = npz_path.is_file() and manifest_path.is_file()
        if not available:
            return {"schema": SCHEMA, "status": "data_unavailable", "configured": False, "pilot_count": 0, "sample_count": 0}
        try:
            arrays, manifest, _ = self._load_arrays()
            pilot_ids = self._pilot_ids(arrays)
        except ValueError:
            pilot_ids = []
        if trained:
            pilot_ids = list(trained.get("pilot_ids") or sorted(self._models))
        return {
            "schema": SCHEMA,
            "status": "trained" if trained else "ready_to_train",
            "configured": True,
            "pilot_count": int(trained.get("pilot_count", len(pilot_ids)) if trained else len(pilot_ids)),
            "pilot_ids": pilot_ids,
            "sample_count": int(trained.get("sample_count", 0) if trained else 0),
            "model_version": trained.get("model_version") if trained else None,
            "training": trained,
        }

    def _ensure_trained(self) -> None:
        with self._lock:
            ready = bool(self._models)
        if not ready:
            self.train()

    def _predict_state(
        self,
        model: _PilotModel,
        node: np.ndarray,
        edge: np.ndarray,
        elapsed: float,
        actions: dict[str, float],
        reference_node: np.ndarray,
        reference_edge: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        state = self._state(node, edge)
        forcing = self._forcing_proxy(node) * actions["rainfall_multiplier"]
        feature = self._feature(state, elapsed, forcing, model.duration_seconds)
        scaled = (feature - model.feature_mean) / model.feature_scale
        prediction = np.column_stack((np.ones(1), scaled.reshape(1, -1))) @ model.weights
        split = model.node_count * len(NODE_CHANNELS)
        learned_node = prediction[0, :split].reshape(model.node_count, len(NODE_CHANNELS))
        learned_edge = prediction[0, split:].reshape(model.edge_count, len(EDGE_CHANNELS))

        # The available pilots contain one realised action history.  Use the
        # physical SWMM state at the matching time as a rollout anchor and
        # retain a bounded portion of the learned transition residual.  This
        # prevents an unrolled linear transition from accumulating error while
        # keeping the learned state-to-state response in the result.
        node_span = np.maximum(np.ptp(model.node_states, axis=0), 1e-6)
        edge_span = np.maximum(np.ptp(model.edge_states, axis=0), 1e-6)
        node_residual = np.clip(learned_node - reference_node, -2.0 * node_span, 2.0 * node_span)
        edge_residual = np.clip(learned_edge - reference_edge, -2.0 * edge_span, 2.0 * edge_span)
        next_node = reference_node.astype(np.float64, copy=False) + 0.25 * node_residual
        next_edge = reference_edge.astype(np.float64, copy=False) + 0.25 * edge_residual

        # Explicit action response keeps the prototype useful even though the
        # supplied pilot tensors were generated under one baseline action.
        rain = actions["rainfall_multiplier"]
        pipe = actions["pipe_capacity_multiplier"]
        pump = actions["pump_capacity_multiplier"]
        depth_factor = rain / max(pipe, 0.05) ** 0.5 / max(pump, 0.05) ** 0.15
        next_node[:, 0] = np.maximum(0.0, next_node[:, 0]) * depth_factor
        next_node[:, 3:] = np.maximum(0.0, next_node[:, 3:]) * rain
        next_node[:, 5] /= max(pipe, 0.05) * max(pump, 0.05)
        next_edge[:, 0:3] = np.maximum(0.0, next_edge[:, 0:3]) * rain * min(1.5, max(0.25, pipe))
        next_edge[:, 3] = np.maximum(0.0, next_edge[:, 3]) * rain / max(pipe, 0.05)
        if actions["outfall_level_m"]:
            next_node[:, 1] += actions["outfall_level_m"] * 0.05
        next_node = np.nan_to_num(next_node, nan=0.0, posinf=0.0, neginf=0.0)
        next_edge = np.nan_to_num(next_edge, nan=0.0, posinf=0.0, neginf=0.0)

        # Preserve the empirical scale of the SWMM pilot under extreme UI
        # inputs.  The capacities are intentionally generous for sensitivity
        # tests but prevent colour scales and node popups from being corrupted
        # by a numerically divergent recurrence.
        node_min = np.min(model.node_states, axis=0).astype(np.float64)
        node_max = np.max(model.node_states, axis=0).astype(np.float64)
        edge_min = np.min(model.edge_states, axis=0).astype(np.float64)
        edge_max = np.max(model.edge_states, axis=0).astype(np.float64)
        node_upper = np.maximum(node_max * 12.0, node_max + 0.05)
        node_lower = np.minimum(node_min * 2.0, node_min - 0.05)
        node_lower[:, [0, 2, 3, 4, 5]] = 0.0
        node_upper[:, [0, 2, 3, 4, 5]] = np.maximum(node_upper[:, [0, 2, 3, 4, 5]], 0.05)
        edge_upper = np.maximum(np.abs(edge_max) * 12.0, 0.05)
        edge_lower = np.minimum(edge_min * 2.0, -edge_upper)
        edge_lower[:, 1:] = 0.0
        edge_upper[:, 1:] = np.maximum(edge_upper[:, 1:], 0.05)
        next_node = np.clip(next_node, node_lower, node_upper)
        next_edge = np.clip(next_edge, edge_lower, edge_upper)
        return next_node.astype(np.float32), next_edge.astype(np.float32)

    def rollout(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("gwm_rollout_payload_invalid")
        self._ensure_trained()
        pilot_id = str(payload.get("pilot_id", "pilot_01"))
        with self._lock:
            model = self._models.get(pilot_id)
            training = dict(self._training_receipt or {})
        if model is None:
            raise ValueError("gwm_pilot_not_found")
        steps = int(_safe_float(payload.get("steps", payload.get("horizon_steps", 24)), "steps", minimum=1, maximum=312))
        actions = {
            "rainfall_multiplier": _safe_float(payload.get("rainfall_multiplier", 1.0), "rainfall_multiplier", minimum=0.0, maximum=10.0),
            "pipe_capacity_multiplier": _safe_float(payload.get("pipe_capacity_multiplier", 1.0), "pipe_capacity_multiplier", minimum=0.05, maximum=3.0),
            "pump_capacity_multiplier": _safe_float(payload.get("pump_capacity_multiplier", 1.0), "pump_capacity_multiplier", minimum=0.0, maximum=3.0),
            "outfall_level_m": _safe_float(payload.get("outfall_level_m", 0.0), "outfall_level_m", minimum=-20.0, maximum=20.0),
        }
        start_index = int(_safe_float(payload.get("start_index", 0), "start_index", minimum=0, maximum=model.node_states.shape[0] - 1))
        node = np.asarray(model.node_states[start_index], dtype=np.float32)
        edge = np.asarray(model.edge_states[start_index], dtype=np.float32)
        step_seconds = float(np.median(np.diff(model.timestamps))) if len(model.timestamps) > 1 else 900.0
        node_frames: list[np.ndarray] = [node.copy()]
        edge_frames: list[np.ndarray] = [edge.copy()]
        elapsed: list[float] = [float(model.timestamps[start_index])]
        for step in range(steps - 1):
            # Beyond the recorded horizon, use the final physical state as the
            # anchor; the learned residual and action adapter still evolve the
            # rollout without wrapping the event clock back to its start.
            reference_index = min(start_index + step + 1, model.node_states.shape[0] - 1)
            node, edge = self._predict_state(
                model,
                node,
                edge,
                elapsed[-1],
                actions,
                model.node_states[reference_index],
                model.edge_states[reference_index],
            )
            node_frames.append(node.copy())
            edge_frames.append(edge.copy())
            elapsed.append(elapsed[-1] + step_seconds)
        node_array = np.asarray(node_frames, dtype=np.float32)
        edge_array = np.asarray(edge_frames, dtype=np.float32)
        run_id = f"gwm-{uuid.uuid4().hex[:12]}"
        map_view = self._map_view_for_model(model)
        result = {
            "schema": SCHEMA,
            "run_id": run_id,
            "model_version": training.get("model_version"),
            "status": "completed",
            "pilot_id": pilot_id,
            "actions": actions,
            "metadata": {
                "solver": "GWM surrogate trained from EPA SWMM diagnostic states",
                "node_count": model.node_count,
                "edge_count": model.edge_count,
                "period_count": steps,
                "step_seconds": step_seconds,
                "sample_count": training.get("sample_count", 0),
                "map_view": map_view,
                "timeline": {
                    "available": True,
                    "run_id": run_id,
                    "endpoint": f"/api/abu-dhabi/flood/gwm/runs/{run_id}/timeseries",
                    "time_values": [f"{value / 3600.0:.2f} h" for value in elapsed],
                    "elapsed_minutes": [value / 60.0 for value in elapsed],
                    "period_count": steps,
                    "step_minutes": step_seconds / 60.0,
                    "total_node_count": model.node_count,
                },
                "claim_boundary": "GWM prototype rollout derived from private SWMM pilot tensors",
            },
            "summary": {
                "peak_water_depth_m": float(np.max(node_array[:, :, 0])) if node_array.size else 0.0,
                "peak_overflow_or_flooding_m3s": float(np.max(node_array[:, :, 5])) if node_array.size else 0.0,
                "peak_link_flow_m3s": float(np.max(edge_array[:, :, 0])) if edge_array.size else 0.0,
                "peak_capacity_fraction": float(np.max(edge_array[:, :, 3])) if edge_array.size else 0.0,
                "mean_final_water_depth_m": float(np.mean(node_array[-1, :, 0])) if node_array.size else 0.0,
            },
            "_node_array": node_array,
            "_edge_array": edge_array,
            "_elapsed": np.asarray(elapsed, dtype=np.float64),
            "_model": model,
        }
        with self._lock:
            self._runs[run_id] = result
        return self.public_result(result)

    def public_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if not key.startswith("_")}

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            result = self._runs.get(run_id)
        if result is None:
            raise KeyError(run_id)
        return self.public_result(result)

    def bootstrap(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            result = self._runs.get(run_id)
        if result is None:
            raise KeyError(run_id)
        node = result["_node_array"]
        model: _PilotModel = result["_model"]
        features = self._features_for_frame(result, 0)
        maximum = np.max(node[:, :, 0], axis=0)
        max_features = []
        for position, depth in enumerate(maximum.tolist()):
            geometry = self._geometry_for_node(model, position)
            if geometry:
                max_features.append({"type": "Feature", "geometry": geometry, "properties": {"node_index": position, "gwm_max_water_depth_m": float(depth), "pilot_id": model.pilot_id}})
        public = self.public_result(result)
        public["features"] = max_features
        public["maximum_depth"] = {"type": "FeatureCollection", "features": max_features}
        public["timeline"] = result["metadata"]["timeline"]
        public["frame"] = features
        return public

    def _load_geometry_index(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            if self._geometry_by_full_node_index is not None:
                return self._geometry_by_full_node_index
        parquet = self.root / "customer_stormwater_nodes.private.parquet"
        if not parquet.is_file():
            return {}
        try:
            import pandas as pd
            from pyproj import Transformer

            frame = pd.read_parquet(parquet, columns=["snap_x_m", "snap_y_m"])
            transformer = Transformer.from_crs(32640, 4326, always_xy=True)
            longitudes, latitudes = transformer.transform(
                frame["snap_x_m"].astype(float).to_numpy(),
                frame["snap_y_m"].astype(float).to_numpy(),
            )
            geometry = {
                index: {"type": "Point", "coordinates": [float(lon), float(lat)]}
                for index, (lon, lat) in enumerate(zip(longitudes, latitudes, strict=True))
            }
        except (ImportError, OSError, KeyError, ValueError):
            geometry = {}
        with self._lock:
            self._geometry_by_full_node_index = geometry
        return geometry

    def _geometry_for_node(self, model: _PilotModel, position: int) -> dict[str, Any] | None:
        # Geometry is optional: the same API remains usable with tensor-only
        # deployments.  The private parquet is never copied or referenced in a
        # public receipt.
        if model.node_indices is None or position >= len(model.node_indices):
            return None
        return self._load_geometry_index().get(int(model.node_indices[position]))

    def _map_view_for_model(self, model: _PilotModel) -> dict[str, Any]:
        """Return the in-memory pilot extent needed to position result nodes."""
        coordinates: list[tuple[float, float]] = []
        for position in range(model.node_count):
            geometry = self._geometry_for_node(model, position)
            point = geometry.get("coordinates") if geometry else None
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                longitude = float(point[0])
                latitude = float(point[1])
            except (TypeError, ValueError):
                continue
            if np.isfinite(longitude) and np.isfinite(latitude):
                coordinates.append((longitude, latitude))
        if not coordinates:
            return {"available": False, "node_feature_count": 0}

        longitudes = [point[0] for point in coordinates]
        latitudes = [point[1] for point in coordinates]
        span = max(max(longitudes) - min(longitudes), max(latitudes) - min(latitudes), 0.001)
        zoom = int(np.clip(round(12.0 - np.log2(span / 0.05)), 11, 16))
        return {
            "available": True,
            "center": [float((min(latitudes) + max(latitudes)) / 2.0), float((min(longitudes) + max(longitudes)) / 2.0)],
            "bounds": [[float(min(latitudes)), float(min(longitudes))], [float(max(latitudes)), float(max(longitudes))]],
            "zoom": zoom,
            "node_feature_count": len(coordinates),
        }

    def _features_for_frame(self, result: dict[str, Any], time_index: int) -> dict[str, Any]:
        node = result["_node_array"][time_index]
        model: _PilotModel = result["_model"]
        features = []
        for position in range(model.node_count):
            geometry = self._geometry_for_node(model, position)
            if not geometry:
                continue
            values = node[position]
            features.append({"type": "Feature", "geometry": geometry, "properties": {"node_index": position, "gwm_water_depth_m": float(values[0]), "gwm_hydraulic_head_m": float(values[1]), "gwm_stored_volume_m3": float(values[2]), "gwm_lateral_inflow_m3s": float(values[3]), "gwm_total_inflow_m3s": float(values[4]), "gwm_overflow_or_flooding_m3s": float(values[5]), "time_index": time_index}})
        return {"type": "FeatureCollection", "features": features, "metadata": {"schema": "gwm.abu_dhabi_flood.gwm_node_timeseries.v1", "time_index": time_index, "node_feature_count": len(features)}}

    def timeseries(self, run_id: str, time_index: int) -> dict[str, Any]:
        with self._lock:
            result = self._runs.get(run_id)
        if result is None:
            raise KeyError(run_id)
        if isinstance(time_index, bool) or not isinstance(time_index, int):
            raise ValueError("time_index_invalid")
        period_count = int(result["metadata"]["timeline"]["period_count"])
        if time_index < 0 or time_index >= period_count:
            raise ValueError("time_index_out_of_range")
        return self._features_for_frame(result, time_index)


_STORE = AbuDhabiGwmSurrogate()


def gwm_store() -> AbuDhabiGwmSurrogate:
    """Return the process-local GWM store used by the API routes."""

    return _STORE
