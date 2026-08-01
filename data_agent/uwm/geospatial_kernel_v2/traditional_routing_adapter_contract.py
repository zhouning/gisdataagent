"""Sealed JSON exchange contract for independent traditional routing adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL = (
    "gwm.geospatial_kernel.traditional_routing_json_adapter.v1"
)
TRADITIONAL_ROUTING_ADAPTER_REQUEST_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_adapter_request.v1"
)
TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_adapter_response.v1"
)
TRADITIONAL_ROUTING_TRACE_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_adapter_trace.v1"
)
REQUIRED_GEOMETRY_FIELDS = (
    "length_m",
    "bottom_width_m",
    "slope",
    "manning_n",
)
FORBIDDEN_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "score_report",
    "future_target_observations",
}
RESPONSE_KEYS = {
    "schema",
    "adapter_protocol",
    "request_id",
    "request_sha256",
    "routed_discharge_m3s",
    "total_storage_m3",
    "serialized_final_state",
}


def build_traditional_routing_adapter_request(
    *,
    request_id: str,
    candidate_id: str,
    runtime_artifact: Mapping[str, object],
    feature_ids: Sequence[int],
    downstream_feature_ids: Sequence[int | None],
    geometry: Mapping[str, Sequence[float]],
    timestep_seconds: float,
    boundary_inflow_m3s: Sequence[Sequence[float]],
    lateral_inflow_m3s: Sequence[Sequence[float]],
    serialized_initial_state: Mapping[str, object],
) -> dict[str, Any]:
    """Build a canonical request whose inputs cannot be replaced by the adapter."""

    if not _nonempty(request_id) or not _nonempty(candidate_id):
        raise ValueError("traditional_routing_adapter_request_identity_required")
    features = tuple(feature_ids)
    downstream = tuple(downstream_feature_ids)
    if not _network_valid(features, downstream):
        raise ValueError("traditional_routing_adapter_request_network_invalid")
    count = len(features)
    geometry_payload: dict[str, list[float]] = {}
    for field in REQUIRED_GEOMETRY_FIELDS:
        values = _positive_vector(geometry.get(field), count)
        if values is None:
            raise ValueError(
                f"traditional_routing_adapter_request_geometry_invalid:{field}"
            )
        geometry_payload[field] = values.tolist()
    timestep = _positive_float(timestep_seconds)
    if timestep is None:
        raise ValueError("traditional_routing_adapter_request_timestep_invalid")
    boundary = _nonnegative_matrix(boundary_inflow_m3s, count)
    lateral = _nonnegative_matrix(lateral_inflow_m3s, count)
    if boundary is None or lateral is None or boundary.shape != lateral.shape:
        raise ValueError("traditional_routing_adapter_request_dynamic_inputs_invalid")
    runtime = _artifact_descriptor(runtime_artifact)
    if runtime is None:
        raise ValueError("traditional_routing_adapter_request_runtime_identity_invalid")
    initial_state = dict(serialized_initial_state)
    _canonical_json(initial_state)
    geometry_identity = _sha256_json(
        {
            "feature_ids": list(features),
            "downstream_feature_ids": list(downstream),
            "geometry": geometry_payload,
        }
    )
    request: dict[str, Any] = {
        "schema": TRADITIONAL_ROUTING_ADAPTER_REQUEST_SCHEMA,
        "adapter_protocol": TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
        "request_id": request_id,
        "candidate_id": candidate_id,
        "runtime_artifact": runtime,
        "feature_ids": list(features),
        "downstream_feature_ids": list(downstream),
        "geometry": geometry_payload,
        "geometry_identity": geometry_identity,
        "timestep_seconds": timestep,
        "boundary_inflow_m3s": boundary.tolist(),
        "lateral_inflow_m3s": lateral.tolist(),
        "serialized_initial_state": initial_state,
        "step_count": int(boundary.shape[0]),
        "feature_count": count,
        "claim_boundary": {
            "synthetic_inputs_only": True,
            "outcome_inputs_included": False,
            "target_parameters_fitted": False,
        },
    }
    if _find_forbidden_keys(request):
        raise ValueError("traditional_routing_adapter_request_forbidden_content")
    request["request_seal"] = {
        "algorithm": "sha256_canonical_json_without_request_seal",
        "sha256": _sha256_json(request),
    }
    return request


def validate_traditional_routing_adapter_response(
    request: Mapping[str, object],
    response: Mapping[str, object],
) -> dict[str, Any]:
    """Validate output-only response data and assemble an immutable input trace."""

    request_payload = dict(request)
    seal = _mapping(request_payload.pop("request_seal", None))
    request_sha256 = _sha256_json(request_payload)
    request_valid = (
        request.get("schema") == TRADITIONAL_ROUTING_ADAPTER_REQUEST_SCHEMA
        and request.get("adapter_protocol")
        == TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL
        and seal.get("algorithm")
        == "sha256_canonical_json_without_request_seal"
        and seal.get("sha256") == request_sha256
        and not _find_forbidden_keys(request)
    )
    if not request_valid:
        raise ValueError("traditional_routing_adapter_request_seal_invalid")
    response_payload = dict(response)
    if set(response_payload) != RESPONSE_KEYS:
        raise ValueError("traditional_routing_adapter_response_fields_invalid")
    if _find_forbidden_keys(response_payload):
        raise ValueError("traditional_routing_adapter_response_forbidden_content")
    if (
        response.get("schema") != TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA
        or response.get("adapter_protocol")
        != TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL
        or response.get("request_id") != request.get("request_id")
        or response.get("request_sha256") != request_sha256
    ):
        raise ValueError("traditional_routing_adapter_response_binding_invalid")
    step_count = request.get("step_count")
    feature_count = request.get("feature_count")
    if (
        not isinstance(step_count, int)
        or isinstance(step_count, bool)
        or not isinstance(feature_count, int)
        or isinstance(feature_count, bool)
    ):
        raise ValueError("traditional_routing_adapter_request_shape_contract_invalid")
    routed = _finite_matrix(
        response.get("routed_discharge_m3s"),
        (step_count, feature_count),
    )
    storage = _finite_vector(response.get("total_storage_m3"), step_count + 1)
    final_state = response.get("serialized_final_state")
    if routed is None or storage is None or not isinstance(final_state, dict):
        raise ValueError("traditional_routing_adapter_response_values_invalid")
    _canonical_json(final_state)
    trace = {
        "schema": TRADITIONAL_ROUTING_TRACE_SCHEMA,
        "request_id": request["request_id"],
        "candidate_id": request["candidate_id"],
        "runtime_artifact": request["runtime_artifact"],
        "feature_ids": request["feature_ids"],
        "downstream_feature_ids": request["downstream_feature_ids"],
        "geometry_identity": request["geometry_identity"],
        "timestep_seconds": request["timestep_seconds"],
        "boundary_inflow_m3s": request["boundary_inflow_m3s"],
        "lateral_inflow_m3s": request["lateral_inflow_m3s"],
        "serialized_initial_state": request["serialized_initial_state"],
        "routed_discharge_m3s": routed.tolist(),
        "total_storage_m3": storage.tolist(),
        "serialized_final_state": dict(final_state),
        "exchange_receipt": {
            "request_sha256": request_sha256,
            "response_sha256": _sha256_json(response_payload),
            "adapter_supplied_input_fields": False,
        },
    }
    return trace


def _artifact_descriptor(value: Mapping[str, object]) -> dict[str, object] | None:
    path = value.get("path")
    sha256 = value.get("sha256")
    size = value.get("size_bytes")
    if (
        not _nonempty(path)
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
    ):
        return None
    return {"path": path, "sha256": sha256, "size_bytes": size}


def _network_valid(
    feature_ids: tuple[int, ...],
    downstream_feature_ids: tuple[int | None, ...],
) -> bool:
    if (
        not feature_ids
        or len(feature_ids) != len(downstream_feature_ids)
        or len(feature_ids) != len(set(feature_ids))
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in feature_ids
        )
        or any(
            target is not None and target not in feature_ids
            for target in downstream_feature_ids
        )
        or sum(target is None for target in downstream_feature_ids) != 1
    ):
        return False
    index = {feature_id: offset for offset, feature_id in enumerate(feature_ids)}
    indegree = [0] * len(feature_ids)
    for source, target in zip(feature_ids, downstream_feature_ids, strict=True):
        if source == target:
            return False
        if target is not None:
            indegree[index[target]] += 1
    ready = [offset for offset, degree in enumerate(indegree) if degree == 0]
    visited = 0
    while ready:
        source_index = ready.pop()
        visited += 1
        target = downstream_feature_ids[source_index]
        if target is not None:
            target_index = index[target]
            indegree[target_index] -= 1
            if indegree[target_index] == 0:
                ready.append(target_index)
    return visited == len(feature_ids)


def _positive_vector(value: object, size: int) -> np.ndarray | None:
    vector = _finite_vector(value, size)
    if vector is None or bool((vector <= 0.0).any()):
        return None
    return vector


def _finite_vector(value: object, size: int) -> np.ndarray | None:
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if vector.shape != (size,) or not np.isfinite(vector).all():
        return None
    return vector


def _nonnegative_matrix(value: object, columns: int) -> np.ndarray | None:
    matrix = _finite_matrix(value, None)
    if (
        matrix is None
        or matrix.ndim != 2
        or matrix.shape[0] == 0
        or matrix.shape[1] != columns
        or bool((matrix < 0.0).any())
    ):
        return None
    return matrix


def _finite_matrix(
    value: object,
    shape: tuple[int, int] | None,
) -> np.ndarray | None:
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        return None
    if shape is not None and matrix.shape != shape:
        return None
    return matrix


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) and result > 0.0 else None


def _find_forbidden_keys(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return found


def _sha256_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
