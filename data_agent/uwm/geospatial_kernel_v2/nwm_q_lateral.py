"""Bounded extraction of modeled NWM v3 retrospective ``q_lateral`` chunks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

import numpy as np

from .public_data import (
    ADMITTED_NWM_CROSSWALK_STATUS,
    NWM_Q_LATERAL_FEATURE_CHUNK_WIDTH,
    PublicDataRegistry,
)


NWM_ZARR_ROOT = (
    "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
    "CONUS/zarr/chrtout.zarr"
)
NWM_Q_LATERAL_EXTRACT_SCHEMA = "gwm.geotransport.nwm_q_lateral_extract.v1"
NWM_VELOCITY_EXTRACT_SCHEMA = "gwm.geotransport.nwm_velocity_extract.v1"
NWM_STREAMFLOW_EXTRACT_SCHEMA = "gwm.geotransport.nwm_streamflow_extract.v1"


@dataclass(frozen=True)
class NwmZarrSchema:
    q_shape: tuple[int, int]
    q_chunks: tuple[int, int]
    q_dtype: np.dtype[Any]
    q_fill_value: int
    scale_factor: float
    add_offset: float
    valid_range: tuple[int, int]
    time_shape: int
    time_chunk_size: int
    time_dtype: np.dtype[Any]
    time_origin: datetime
    metadata_sha256: Mapping[str, str]


@dataclass(frozen=True)
class NwmQlatPlan:
    system_id: str
    start: datetime
    end: datetime
    start_time_index: int
    end_time_index: int
    feature_ids: tuple[int, ...]
    feature_indices: tuple[int, ...]
    time_chunk_indices: tuple[int, ...]
    feature_chunk_indices: tuple[int, ...]
    q_chunk_keys: tuple[tuple[int, int], ...]

    @property
    def time_count(self) -> int:
        return self.end_time_index - self.start_time_index


@dataclass(frozen=True)
class NwmQlatResult:
    system_id: str
    timestamps: tuple[str, ...]
    feature_ids: tuple[int, ...]
    values_m3s: np.ndarray
    fill_value_count: int
    source: str = "noaa_nwm_v3_retrospective"
    variable: str = "q_lateral"
    variable_role: str = "modeled_forcing"
    modeled: bool = True
    ground_truth: bool = False


@dataclass(frozen=True)
class NwmVelocitySchema:
    base: NwmZarrSchema
    velocity_shape: tuple[int, int]
    velocity_chunks: tuple[int, int]
    velocity_dtype: np.dtype[Any]
    velocity_fill_value: int
    scale_factor: float
    add_offset: float
    valid_range: tuple[int, int]
    metadata_sha256: Mapping[str, str]


@dataclass(frozen=True)
class NwmVelocityResult:
    system_id: str
    timestamps: tuple[str, ...]
    feature_ids: tuple[int, ...]
    values_ms: np.ndarray
    fill_value_count: int
    source: str = "noaa_nwm_v3_retrospective"
    variable: str = "velocity"
    variable_role: str = "modeled_state_context"
    modeled: bool = True
    ground_truth: bool = False


@dataclass(frozen=True)
class NwmStreamflowSchema:
    base: NwmZarrSchema
    streamflow_shape: tuple[int, int]
    streamflow_chunks: tuple[int, int]
    streamflow_dtype: np.dtype[Any]
    streamflow_fill_value: int
    scale_factor: float
    add_offset: float
    valid_range: tuple[int, int]
    valid_range_attribute_present: bool
    metadata_sha256: Mapping[str, str]


@dataclass(frozen=True)
class NwmStreamflowResult:
    system_id: str
    timestamps: tuple[str, ...]
    feature_ids: tuple[int, ...]
    values_m3s: np.ndarray
    fill_value_count: int
    source: str = "noaa_nwm_v3_retrospective"
    variable: str = "streamflow"
    variable_role: str = "modeled_initial_state"
    modeled: bool = True
    ground_truth: bool = False


def load_nwm_zarr_schema(metadata_root: Path) -> NwmZarrSchema:
    paths = {
        "q_array": metadata_root / "nwm-q-lateral-zarray.json",
        "q_attrs": metadata_root / "nwm-q-lateral-zattrs.json",
        "time_array": metadata_root / "nwm-time-zarray.json",
        "time_attrs": metadata_root / "nwm-time-zattrs.json",
    }
    bodies = {key: path.read_bytes() for key, path in paths.items()}
    payloads = {key: json.loads(body) for key, body in bodies.items()}
    q_array = payloads["q_array"]
    q_attrs = payloads["q_attrs"]
    time_array = payloads["time_array"]
    time_attrs = payloads["time_attrs"]
    if (
        q_array.get("zarr_format") != 2
        or q_array.get("shape") != [385704, 2776734]
        or q_array.get("chunks") != [672, NWM_Q_LATERAL_FEATURE_CHUNK_WIDTH]
        or q_array.get("dtype") != "<i4"
        or q_array.get("fill_value") != -99990
        or q_array.get("order") != "C"
        or q_array.get("filters") is not None
        or (q_array.get("compressor") or {}).get("id") != "zstd"
    ):
        raise ValueError("nwm_q_lateral_zarr_schema_mismatch")
    if (
        q_attrs.get("_ARRAY_DIMENSIONS") != ["time", "feature_id"]
        or q_attrs.get("units") != "m3 s-1"
        or q_attrs.get("missing_value") != q_array["fill_value"]
        or q_attrs.get("valid_range") != [0, 500000]
    ):
        raise ValueError("nwm_q_lateral_attributes_mismatch")
    if (
        time_array.get("zarr_format") != 2
        or time_array.get("shape") != [q_array["shape"][0]]
        or time_array.get("chunks") != [q_array["chunks"][0]]
        or time_array.get("dtype") != "<i8"
        or time_array.get("order") != "C"
        or time_array.get("filters") is not None
        or (time_array.get("compressor") or {}).get("id") != "zstd"
    ):
        raise ValueError("nwm_time_zarr_schema_mismatch")
    if (
        time_attrs.get("_ARRAY_DIMENSIONS") != ["time"]
        or time_attrs.get("calendar") != "proleptic_gregorian"
    ):
        raise ValueError("nwm_time_attributes_mismatch")
    time_origin = _parse_time_units(time_attrs.get("units"))
    return NwmZarrSchema(
        q_shape=tuple(q_array["shape"]),
        q_chunks=tuple(q_array["chunks"]),
        q_dtype=np.dtype(q_array["dtype"]),
        q_fill_value=int(q_array["fill_value"]),
        scale_factor=float(q_attrs.get("scale_factor", 1.0)),
        add_offset=float(q_attrs.get("add_offset", 0.0)),
        valid_range=tuple(q_attrs["valid_range"]),
        time_shape=int(time_array["shape"][0]),
        time_chunk_size=int(time_array["chunks"][0]),
        time_dtype=np.dtype(time_array["dtype"]),
        time_origin=time_origin,
        metadata_sha256={
            key: hashlib.sha256(body).hexdigest() for key, body in bodies.items()
        },
    )


def load_nwm_velocity_schema(metadata_root: Path) -> NwmVelocitySchema:
    base = load_nwm_zarr_schema(metadata_root)
    paths = {
        "velocity_array": metadata_root / "nwm-velocity-zarray.json",
        "velocity_attrs": metadata_root / "nwm-velocity-zattrs.json",
        "consolidated_metadata": metadata_root / "nwm-chrtout-zmetadata.json",
    }
    bodies = {key: path.read_bytes() for key, path in paths.items()}
    payloads = {key: json.loads(body) for key, body in bodies.items()}
    array = payloads["velocity_array"]
    attrs = payloads["velocity_attrs"]
    consolidated = (payloads["consolidated_metadata"].get("metadata") or {})
    consolidated_array = consolidated.get("velocity/.zarray") or {}
    consolidated_attrs = consolidated.get("velocity/.zattrs") or {}
    if (
        array.get("zarr_format") != 2
        or tuple(array.get("shape") or ()) != base.q_shape
        or tuple(array.get("chunks") or ()) != base.q_chunks
        or array.get("dtype") != "<i4"
        or array.get("fill_value") != -999900
        or array.get("order") != "C"
        or array.get("filters") is not None
        or (array.get("compressor") or {}).get("id") != "zstd"
        or consolidated_array != array
    ):
        raise ValueError("nwm_velocity_zarr_schema_mismatch")
    if (
        attrs.get("_ARRAY_DIMENSIONS") != ["time", "feature_id"]
        or attrs.get("long_name") != "River Velocity"
        or attrs.get("units") != "m s-1"
        or attrs.get("missing_value") != array["fill_value"]
        or consolidated_attrs != attrs
    ):
        raise ValueError("nwm_velocity_attributes_mismatch")
    return NwmVelocitySchema(
        base=base,
        velocity_shape=tuple(array["shape"]),
        velocity_chunks=tuple(array["chunks"]),
        velocity_dtype=np.dtype(array["dtype"]),
        velocity_fill_value=int(array["fill_value"]),
        scale_factor=float(attrs.get("scale_factor", 1.0)),
        add_offset=float(attrs.get("add_offset", 0.0)),
        valid_range=(0, int(np.iinfo(np.int32).max)),
        metadata_sha256={
            **dict(base.metadata_sha256),
            **{key: hashlib.sha256(body).hexdigest() for key, body in bodies.items()},
        },
    )


def load_nwm_streamflow_schema(metadata_root: Path) -> NwmStreamflowSchema:
    base = load_nwm_zarr_schema(metadata_root)
    path = metadata_root / "nwm-chrtout-zmetadata.json"
    body = path.read_bytes()
    consolidated = (json.loads(body).get("metadata") or {})
    array = consolidated.get("streamflow/.zarray") or {}
    attrs = consolidated.get("streamflow/.zattrs") or {}
    if (
        array.get("zarr_format") != 2
        or tuple(array.get("shape") or ()) != base.q_shape
        or tuple(array.get("chunks") or ()) != base.q_chunks
        or array.get("dtype") != "<i4"
        or array.get("fill_value") != -999900
        or array.get("order") != "C"
        or array.get("filters") is not None
        or (array.get("compressor") or {}).get("id") != "zstd"
    ):
        raise ValueError("nwm_streamflow_zarr_schema_mismatch")
    if (
        attrs.get("_ARRAY_DIMENSIONS") != ["time", "feature_id"]
        or attrs.get("long_name") != "River Flow"
        or attrs.get("units") != "m3 s-1"
        or attrs.get("missing_value") != array["fill_value"]
        or "valid_range" in attrs
    ):
        raise ValueError("nwm_streamflow_attributes_mismatch")
    return NwmStreamflowSchema(
        base=base,
        streamflow_shape=tuple(array["shape"]),
        streamflow_chunks=tuple(array["chunks"]),
        streamflow_dtype=np.dtype(array["dtype"]),
        streamflow_fill_value=int(array["fill_value"]),
        scale_factor=float(attrs.get("scale_factor", 1.0)),
        add_offset=float(attrs.get("add_offset", 0.0)),
        valid_range=(0, int(np.iinfo(np.int32).max)),
        valid_range_attribute_present=False,
        metadata_sha256={
            **dict(base.metadata_sha256),
            "consolidated_metadata": hashlib.sha256(body).hexdigest(),
        },
    )


def build_nwm_q_lateral_plan(
    registry: PublicDataRegistry,
    schema: NwmZarrSchema,
    *,
    system_id: str,
    start: str,
    end: str,
) -> NwmQlatPlan:
    by_id = {system["system_id"]: system for system in registry.payload["systems"]}
    if system_id not in by_id:
        raise ValueError("unknown_nwm_system")
    system = by_id[system_id]
    if not system["track"].startswith("GeoTransport"):
        raise ValueError("nwm_forcing_requires_transport_system")
    forcing = system.get("forcing") or {}
    if forcing.get("crosswalk_status") != ADMITTED_NWM_CROSSWALK_STATUS:
        raise ValueError(f"nwm_feature_crosswalk_required:{system_id}")
    feature_ids = tuple(int(value) for value in forcing.get("feature_ids") or ())
    feature_indices = tuple(int(value) for value in forcing.get("feature_indices") or ())
    if not feature_ids or len(feature_ids) != len(feature_indices):
        raise ValueError(f"nwm_feature_crosswalk_required:{system_id}")
    start_at = _parse_utc(start)
    end_at = _parse_utc(end)
    if start_at >= end_at:
        raise ValueError("nwm_extraction_interval_invalid")
    if not _is_hour_aligned(start_at) or not _is_hour_aligned(end_at):
        raise ValueError("nwm_extraction_interval_must_align_to_hours")
    study_start, study_end = map(_parse_utc, system["study_window"])
    archive_end = schema.time_origin + timedelta(hours=schema.time_shape)
    if start_at < max(study_start, schema.time_origin) or end_at > min(
        study_end, archive_end
    ):
        raise ValueError("nwm_extraction_outside_frozen_window")
    start_index = _hour_index(start_at, schema.time_origin)
    end_index = _hour_index(end_at, schema.time_origin)
    time_chunks = tuple(
        range(
            start_index // schema.time_chunk_size,
            (end_index - 1) // schema.time_chunk_size + 1,
        )
    )
    feature_chunks = tuple(sorted({index // schema.q_chunks[1] for index in feature_indices}))
    if feature_chunks != tuple(forcing["q_lateral_feature_chunk_indices"]):
        raise ValueError(f"nwm_feature_chunk_registry_mismatch:{system_id}")
    return NwmQlatPlan(
        system_id=system_id,
        start=start_at,
        end=end_at,
        start_time_index=start_index,
        end_time_index=end_index,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
        time_chunk_indices=time_chunks,
        feature_chunk_indices=feature_chunks,
        q_chunk_keys=tuple(
            (time_chunk, feature_chunk)
            for time_chunk in time_chunks
            for feature_chunk in feature_chunks
        ),
    )


def extract_nwm_q_lateral(
    plan: NwmQlatPlan,
    schema: NwmZarrSchema,
    *,
    time_chunks: Mapping[int, bytes],
    q_chunks: Mapping[tuple[int, int], bytes],
    zstd_executable: str | None = None,
) -> NwmQlatResult:
    missing_time = set(plan.time_chunk_indices) - set(time_chunks)
    missing_q = set(plan.q_chunk_keys) - set(q_chunks)
    if missing_time:
        raise ValueError(f"nwm_time_chunks_missing:{sorted(missing_time)}")
    if missing_q:
        raise ValueError(f"nwm_q_lateral_chunks_missing:{sorted(missing_q)}")
    timestamps, values, fill_count = _extract_packed_reach_values(
        plan,
        time_shape=schema.time_shape,
        time_chunk_size=schema.time_chunk_size,
        time_dtype=schema.time_dtype,
        time_origin=schema.time_origin,
        variable_name="q_lateral",
        variable_shape=schema.q_shape,
        variable_chunks=schema.q_chunks,
        variable_dtype=schema.q_dtype,
        variable_fill_value=schema.q_fill_value,
        scale_factor=schema.scale_factor,
        add_offset=schema.add_offset,
        valid_range=schema.valid_range,
        time_chunks=time_chunks,
        variable_chunks_bodies=q_chunks,
        zstd_executable=zstd_executable,
    )
    return NwmQlatResult(
        system_id=plan.system_id,
        timestamps=timestamps,
        feature_ids=plan.feature_ids,
        values_m3s=values,
        fill_value_count=fill_count,
    )


def extract_nwm_velocity(
    plan: NwmQlatPlan,
    schema: NwmVelocitySchema,
    *,
    time_chunks: Mapping[int, bytes],
    velocity_chunks: Mapping[tuple[int, int], bytes],
    zstd_executable: str | None = None,
) -> NwmVelocityResult:
    missing_time = set(plan.time_chunk_indices) - set(time_chunks)
    missing_velocity = set(plan.q_chunk_keys) - set(velocity_chunks)
    if missing_time:
        raise ValueError(f"nwm_time_chunks_missing:{sorted(missing_time)}")
    if missing_velocity:
        raise ValueError(f"nwm_velocity_chunks_missing:{sorted(missing_velocity)}")
    timestamps, values, fill_count = _extract_packed_reach_values(
        plan,
        time_shape=schema.base.time_shape,
        time_chunk_size=schema.base.time_chunk_size,
        time_dtype=schema.base.time_dtype,
        time_origin=schema.base.time_origin,
        variable_name="velocity",
        variable_shape=schema.velocity_shape,
        variable_chunks=schema.velocity_chunks,
        variable_dtype=schema.velocity_dtype,
        variable_fill_value=schema.velocity_fill_value,
        scale_factor=schema.scale_factor,
        add_offset=schema.add_offset,
        valid_range=schema.valid_range,
        time_chunks=time_chunks,
        variable_chunks_bodies=velocity_chunks,
        zstd_executable=zstd_executable,
    )
    return NwmVelocityResult(
        system_id=plan.system_id,
        timestamps=timestamps,
        feature_ids=plan.feature_ids,
        values_ms=values,
        fill_value_count=fill_count,
    )


def extract_nwm_streamflow(
    plan: NwmQlatPlan,
    schema: NwmStreamflowSchema,
    *,
    time_chunks: Mapping[int, bytes],
    streamflow_chunks: Mapping[tuple[int, int], bytes],
    zstd_executable: str | None = None,
) -> NwmStreamflowResult:
    missing_time = set(plan.time_chunk_indices) - set(time_chunks)
    missing_streamflow = set(plan.q_chunk_keys) - set(streamflow_chunks)
    if missing_time:
        raise ValueError(f"nwm_time_chunks_missing:{sorted(missing_time)}")
    if missing_streamflow:
        raise ValueError(
            f"nwm_streamflow_chunks_missing:{sorted(missing_streamflow)}"
        )
    timestamps, values, fill_count = _extract_packed_reach_values(
        plan,
        time_shape=schema.base.time_shape,
        time_chunk_size=schema.base.time_chunk_size,
        time_dtype=schema.base.time_dtype,
        time_origin=schema.base.time_origin,
        variable_name="streamflow",
        variable_shape=schema.streamflow_shape,
        variable_chunks=schema.streamflow_chunks,
        variable_dtype=schema.streamflow_dtype,
        variable_fill_value=schema.streamflow_fill_value,
        scale_factor=schema.scale_factor,
        add_offset=schema.add_offset,
        valid_range=schema.valid_range,
        time_chunks=time_chunks,
        variable_chunks_bodies=streamflow_chunks,
        zstd_executable=zstd_executable,
    )
    return NwmStreamflowResult(
        system_id=plan.system_id,
        timestamps=timestamps,
        feature_ids=plan.feature_ids,
        values_m3s=values,
        fill_value_count=fill_count,
    )


def _extract_packed_reach_values(
    plan: NwmQlatPlan,
    *,
    time_shape: int,
    time_chunk_size: int,
    time_dtype: np.dtype[Any],
    time_origin: datetime,
    variable_name: str,
    variable_shape: tuple[int, int],
    variable_chunks: tuple[int, int],
    variable_dtype: np.dtype[Any],
    variable_fill_value: int,
    scale_factor: float,
    add_offset: float,
    valid_range: tuple[int, int],
    time_chunks: Mapping[int, bytes],
    variable_chunks_bodies: Mapping[tuple[int, int], bytes],
    zstd_executable: str | None,
) -> tuple[tuple[str, ...], np.ndarray, int]:
    executable = _resolve_zstd(zstd_executable)
    decoded_time = {
        index: decode_zstd_array(
            time_chunks[index],
            dtype=time_dtype,
            shape=(_chunk_length(time_shape, time_chunk_size, index),),
            zstd_executable=executable,
        )
        for index in plan.time_chunk_indices
    }
    expected_indices = np.arange(
        plan.start_time_index, plan.end_time_index, dtype=np.int64
    )
    observed_hours = np.empty(plan.time_count, dtype=np.int64)
    for output_row, global_index in enumerate(expected_indices):
        chunk_index, local_index = divmod(int(global_index), time_chunk_size)
        observed_hours[output_row] = decoded_time[chunk_index][local_index]
    if not np.array_equal(observed_hours, expected_indices):
        raise ValueError("nwm_time_coordinate_not_contiguous_hourly")

    values = np.full((plan.time_count, len(plan.feature_ids)), np.nan, dtype=np.float64)
    fill_count = 0
    features_by_chunk: dict[int, list[tuple[int, int]]] = {}
    for output_column, feature_index in enumerate(plan.feature_indices):
        chunk_index, local_index = divmod(feature_index, variable_chunks[1])
        features_by_chunk.setdefault(chunk_index, []).append((output_column, local_index))
    for time_chunk_index in plan.time_chunk_indices:
        chunk_start = time_chunk_index * time_chunk_size
        selected_start = max(plan.start_time_index, chunk_start)
        selected_end = min(plan.end_time_index, chunk_start + time_chunk_size)
        input_rows = slice(selected_start - chunk_start, selected_end - chunk_start)
        output_rows = slice(
            selected_start - plan.start_time_index,
            selected_end - plan.start_time_index,
        )
        for feature_chunk_index, selected_features in features_by_chunk.items():
            shape = (
                _chunk_length(variable_shape[0], variable_chunks[0], time_chunk_index),
                _chunk_length(variable_shape[1], variable_chunks[1], feature_chunk_index),
            )
            packed = decode_zstd_array(
                variable_chunks_bodies[(time_chunk_index, feature_chunk_index)],
                dtype=variable_dtype,
                shape=shape,
                zstd_executable=executable,
            )
            output_columns = [item[0] for item in selected_features]
            input_columns = [item[1] for item in selected_features]
            selected = packed[input_rows][:, input_columns]
            fill = selected == variable_fill_value
            valid = selected[~fill]
            if valid.size and (
                int(valid.min()) < valid_range[0] or int(valid.max()) > valid_range[1]
            ):
                raise ValueError(f"nwm_{variable_name}_packed_value_outside_valid_range")
            decoded = selected.astype(np.float64) * scale_factor + add_offset
            decoded[fill] = np.nan
            values[output_rows, output_columns] = decoded
            fill_count += int(fill.sum())
    timestamps = tuple(
        _iso(time_origin + timedelta(hours=int(value))) for value in observed_hours
    )
    return timestamps, values, fill_count


def decode_zstd_array(
    body: bytes,
    *,
    dtype: np.dtype[Any],
    shape: tuple[int, ...],
    zstd_executable: str | None = None,
) -> np.ndarray:
    executable = _resolve_zstd(zstd_executable)
    result = subprocess.run(
        [executable, "--decompress", "--stdout", "--quiet"],
        input=body,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    expected_size = int(np.prod(shape)) * dtype.itemsize
    if len(result.stdout) != expected_size:
        raise ValueError("decoded_nwm_zarr_chunk_size_mismatch")
    return np.frombuffer(result.stdout, dtype=dtype).reshape(shape)


def nwm_chunk_url(variable: str, chunk_key: str) -> str:
    if variable not in {"time", "q_lateral", "streamflow", "velocity"}:
        raise ValueError("unsupported_nwm_zarr_variable")
    return f"{NWM_ZARR_ROOT}/{variable}/{chunk_key}"


def _resolve_zstd(executable: str | None) -> str:
    resolved = executable or shutil.which("zstd")
    if resolved is None:
        raise RuntimeError("zstd_executable_required")
    return resolved


def _chunk_length(total: int, chunk_size: int, chunk_index: int) -> int:
    start = chunk_index * chunk_size
    if start < 0 or start >= total:
        raise ValueError("nwm_zarr_chunk_index_out_of_range")
    return min(chunk_size, total - start)


def _parse_time_units(value: Any) -> datetime:
    prefix = "hours since "
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("unsupported_nwm_time_units")
    parsed = datetime.fromisoformat(value.removeprefix(prefix).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return parsed.astimezone(timezone.utc)


def _hour_index(value: datetime, origin: datetime) -> int:
    hours = (value - origin).total_seconds() / 3600.0
    if not hours.is_integer():
        raise ValueError("nwm_timestamp_not_on_hour_index")
    return int(hours)


def _is_hour_aligned(value: datetime) -> bool:
    return value.minute == 0 and value.second == 0 and value.microsecond == 0


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
