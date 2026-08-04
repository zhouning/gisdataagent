"""Readiness gate for observed multi-geometry state-prior candidates."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..geospatial_state_prior_benchmark import (
    REQUIRED_GEOMETRY_ROUTES,
    validate_uwm_geospatial_state_prior_dataset,
)
from ..openaq_station_observations import OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA

STATE_PRIOR_OBSERVED_READINESS_SCHEMA = (
    "uwm.geospatial_kernel.state_prior_observed_candidate_readiness.v1"
)
STATE_PRIOR_OBSERVED_READINESS_GATES = (
    "multi_geometry_dataset_contract_valid",
    "three_native_geometry_routes_present",
    "raw_observation_payloads_parseable",
    "target_parameter_observations_present",
    "minimum_observation_count_met",
    "measurement_sensor_locations_resolved",
    "minimum_measured_station_support_met",
    "minimum_spatial_band_support_met",
    "minimum_observation_time_support_met",
    "station_admin_crosswalk_complete",
    "minimum_admin_group_support_met",
    "observed_geometry_period_overlap",
    "normalized_proxy_matches_raw_measurements",
    "target_leakage_boundary_preserved",
    "evidence_refs_present",
)

_BLOCKED_CLAIM = "observed_state_prior_candidate_readiness_audit_only"
_READY_CLAIM = "observed_multi_geometry_candidate_ready_for_p1_execution_only"
_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "state_prior_input_readiness_only",
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


def build_state_prior_observed_candidate_readiness(
    *,
    assessment_id: str,
    created_at: str,
    target_parameter: str,
    locations_payload: Mapping[str, Any],
    sensor_measurement_payloads: Mapping[str, Mapping[str, Any]],
    multi_geometry_dataset: Mapping[str, Any],
    normalized_station_proxy: Mapping[str, Any] | None,
    station_admin_crosswalk: Mapping[str, str] | None,
    evidence_refs: Sequence[str],
    minimum_observation_count: int = 18,
    minimum_measured_stations: int = 5,
    minimum_spatial_bands: int = 5,
    minimum_time_groups: int = 5,
    minimum_admin_groups: int = 5,
) -> dict[str, Any]:
    """Assess whether real observations can enter the P1 benchmark builder."""

    if not _nonempty_string(assessment_id):
        raise ValueError("state_prior_observed_readiness_assessment_id_required")
    _require_aware_timestamp(created_at)
    normalized_parameter = _normalize_parameter(target_parameter)
    if not normalized_parameter:
        raise ValueError("state_prior_observed_readiness_target_parameter_required")
    thresholds = {
        "minimum_observation_count": _positive_int(
            minimum_observation_count, "minimum_observation_count"
        ),
        "minimum_measured_stations": _positive_int(
            minimum_measured_stations, "minimum_measured_stations"
        ),
        "minimum_spatial_bands": _positive_int(minimum_spatial_bands, "minimum_spatial_bands"),
        "minimum_time_groups": _positive_int(minimum_time_groups, "minimum_time_groups"),
        "minimum_admin_groups": _positive_int(minimum_admin_groups, "minimum_admin_groups"),
    }
    normalized_evidence = _unique_nonempty_strings(evidence_refs)
    locations = copy.deepcopy(dict(locations_payload))
    measurements = {
        str(sensor_id): copy.deepcopy(dict(payload))
        for sensor_id, payload in sensor_measurement_payloads.items()
        if isinstance(payload, Mapping)
    }
    dataset = copy.deepcopy(dict(multi_geometry_dataset))
    proxy = (
        copy.deepcopy(dict(normalized_station_proxy))
        if isinstance(normalized_station_proxy, Mapping)
        else None
    )
    crosswalk = (
        {str(station_id): str(admin_id) for station_id, admin_id in station_admin_crosswalk.items()}
        if isinstance(station_admin_crosswalk, Mapping)
        else {}
    )

    raw_parseable = _raw_payloads_parseable(locations, measurements)
    sensor_locations = _sensor_location_index(locations)
    raw_observations = _observations(measurements, target_parameter=None)
    observations = _observations(
        measurements,
        target_parameter=normalized_parameter,
    )
    measured_sensor_ids = sorted({row["sensor_id"] for row in observations})
    resolved_sensor_ids = sorted(
        sensor_id for sensor_id in measured_sensor_ids if sensor_id in sensor_locations
    )
    measured_station_ids = sorted(
        {sensor_locations[sensor_id]["station_id"] for sensor_id in resolved_sensor_ids}
    )
    longitudes = {
        round(float(sensor_locations[sensor_id]["longitude"]), 4)
        for sensor_id in resolved_sensor_ids
        if sensor_locations[sensor_id]["longitude"] is not None
    }
    observation_time_groups = sorted(
        {row["started_at"][:10] for row in observations if row["started_at"]}
    )
    observation_starts = sorted(row["started_at"] for row in observations if row["started_at"])
    observation_ends = sorted(row["ended_at"] for row in observations if row["ended_at"])
    target_observed_range = {
        "start": observation_starts[0] if observation_starts else None,
        "end": observation_ends[-1] if observation_ends else None,
    }
    raw_starts = sorted(row["started_at"] for row in raw_observations if row["started_at"])
    raw_ends = sorted(row["ended_at"] for row in raw_observations if row["ended_at"])
    raw_observed_range = {
        "start": raw_starts[0] if raw_starts else None,
        "end": raw_ends[-1] if raw_ends else None,
    }
    dataset_time_groups = sorted(
        {
            str(row.get("time_id") or "").strip()
            for row in dataset.get("rows") or []
            if isinstance(row, Mapping) and str(row.get("time_id") or "").strip()
        }
    )
    overlapping_groups = sorted(
        {
            observation_group
            for observation_group in observation_time_groups
            if any(
                _time_groups_overlap(observation_group, dataset_group)
                for dataset_group in dataset_time_groups
            )
        }
    )
    crosswalk_station_ids = sorted(
        station_id
        for station_id in measured_station_ids
        if _nonempty_string(crosswalk.get(station_id))
    )
    crosswalk_admin_ids = sorted({crosswalk[station_id] for station_id in crosswalk_station_ids})
    proxy_range = (
        copy.deepcopy(dict(proxy.get("observed_time_range") or {}))
        if isinstance(proxy, Mapping)
        else {}
    )
    proxy_matches = bool(
        isinstance(proxy, Mapping)
        and proxy.get("schema") == OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA
        and proxy_range == raw_observed_range
        and (proxy.get("record_counts") or {}).get("measurements") == len(raw_observations)
    )
    dataset_validation = validate_uwm_geospatial_state_prior_dataset(dataset)
    dynamic_context = dataset.get("dynamic_context")
    target_leakage_absent = dynamic_context is None or (
        isinstance(dynamic_context, Mapping) and dynamic_context.get("uses_target_values") is False
    )
    routes = dataset.get("geometry_routes")
    if not isinstance(routes, Mapping):
        routes = {}

    summary = {
        "target_observation_count": len(observations),
        "measured_sensor_count": len(measured_sensor_ids),
        "resolved_sensor_count": len(resolved_sensor_ids),
        "measured_station_count": len(measured_station_ids),
        "distinct_spatial_band_count": len(longitudes),
        "distinct_observation_time_group_count": len(observation_time_groups),
        "target_observed_time_range": target_observed_range,
        "raw_observed_time_range": raw_observed_range,
        "multi_geometry_time_group_count": len(dataset_time_groups),
        "multi_geometry_time_range": {
            "start": dataset_time_groups[0] if dataset_time_groups else None,
            "end": dataset_time_groups[-1] if dataset_time_groups else None,
        },
        "overlapping_time_groups": overlapping_groups,
        "crosswalk_covered_station_count": len(crosswalk_station_ids),
        "crosswalk_admin_group_count": len(crosswalk_admin_ids),
        "geometry_routes": sorted(str(route) for route in routes),
        "normalized_proxy_observed_time_range": proxy_range or None,
        "dataset_validation_errors": list(dataset_validation["errors"]),
    }
    gates = {
        "multi_geometry_dataset_contract_valid": dataset_validation["valid"],
        "three_native_geometry_routes_present": set(routes) >= set(REQUIRED_GEOMETRY_ROUTES),
        "raw_observation_payloads_parseable": raw_parseable,
        "target_parameter_observations_present": bool(observations),
        "minimum_observation_count_met": len(observations)
        >= thresholds["minimum_observation_count"],
        "measurement_sensor_locations_resolved": bool(measured_sensor_ids)
        and measured_sensor_ids == resolved_sensor_ids,
        "minimum_measured_station_support_met": len(measured_station_ids)
        >= thresholds["minimum_measured_stations"],
        "minimum_spatial_band_support_met": len(longitudes) >= thresholds["minimum_spatial_bands"],
        "minimum_observation_time_support_met": len(observation_time_groups)
        >= thresholds["minimum_time_groups"],
        "station_admin_crosswalk_complete": bool(measured_station_ids)
        and measured_station_ids == crosswalk_station_ids,
        "minimum_admin_group_support_met": len(crosswalk_admin_ids)
        >= thresholds["minimum_admin_groups"],
        "observed_geometry_period_overlap": bool(overlapping_groups),
        "normalized_proxy_matches_raw_measurements": proxy_matches,
        "target_leakage_boundary_preserved": target_leakage_absent,
        "evidence_refs_present": bool(normalized_evidence),
    }
    ready = all(gates.values())
    remaining = [gate for gate in STATE_PRIOR_OBSERVED_READINESS_GATES if not gates[gate]]
    assessment = {
        "schema": STATE_PRIOR_OBSERVED_READINESS_SCHEMA,
        "version": "0.1",
        "assessment_id": str(assessment_id),
        "created_at": str(created_at),
        "target_parameter": normalized_parameter,
        "thresholds": thresholds,
        "input_artifact_sha256": {
            "locations_payload_sha256": _canonical_sha256(locations),
            "sensor_measurements_sha256": _canonical_sha256(measurements),
            "multi_geometry_dataset_sha256": _canonical_sha256(dataset),
            "normalized_station_proxy_sha256": (
                _canonical_sha256(proxy) if proxy is not None else None
            ),
            "station_admin_crosswalk_sha256": (_canonical_sha256(crosswalk) if crosswalk else None),
        },
        "source_summary": summary,
        "gate_results": gates,
        "remaining_gates": remaining,
        "required_next_actions": _required_next_actions(remaining),
        "evidence_refs": list(normalized_evidence),
        "p1_benchmark_input_ready": ready,
        "p2_admission_permitted": False,
        "supported_claim": _READY_CLAIM if ready else _BLOCKED_CLAIM,
        "claim_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "empirical_policy_effect_claim": False,
    }
    assessment["readiness_sha256"] = compute_state_prior_observed_readiness_sha256(assessment)
    validation = validate_state_prior_observed_candidate_readiness(assessment)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_observed_candidate_readiness:" + ";".join(validation["errors"])
        )
    return assessment


def validate_state_prior_observed_candidate_readiness(payload: Any) -> dict[str, Any]:
    """Validate readiness consistency without upgrading it to empirical evidence."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["observed_readiness_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "assessment_id",
        "created_at",
        "target_parameter",
        "thresholds",
        "input_artifact_sha256",
        "source_summary",
        "gate_results",
        "remaining_gates",
        "required_next_actions",
        "evidence_refs",
        "p1_benchmark_input_ready",
        "p2_admission_permitted",
        "supported_claim",
        "claim_boundary",
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
        "empirical_policy_effect_claim",
        "readiness_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("observed_readiness_field_set_mismatch")
    if payload.get("schema") != STATE_PRIOR_OBSERVED_READINESS_SCHEMA:
        errors.append("observed_readiness_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("observed_readiness_version_mismatch")
    for field in ("assessment_id", "created_at", "target_parameter"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"observed_readiness_{field}_required")
    if _parse_aware_timestamp(payload.get("created_at")) is None:
        errors.append("observed_readiness_created_at_invalid")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {
        "minimum_observation_count",
        "minimum_measured_stations",
        "minimum_spatial_bands",
        "minimum_time_groups",
        "minimum_admin_groups",
    }:
        errors.append("observed_readiness_thresholds_invalid")
    elif any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in thresholds.values()
    ):
        errors.append("observed_readiness_threshold_values_invalid")
    hashes = payload.get("input_artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {
        "locations_payload_sha256",
        "sensor_measurements_sha256",
        "multi_geometry_dataset_sha256",
        "normalized_station_proxy_sha256",
        "station_admin_crosswalk_sha256",
    }:
        errors.append("observed_readiness_input_hashes_invalid")
    else:
        for name, value in hashes.items():
            if value is not None and not _valid_sha256(value):
                errors.append(f"observed_readiness_{name}_invalid")
    gates = payload.get("gate_results")
    if not isinstance(gates, dict) or tuple(gates) != STATE_PRIOR_OBSERVED_READINESS_GATES:
        errors.append("observed_readiness_gate_set_mismatch")
        expected_remaining: list[str] = []
        all_pass = False
    else:
        if any(value not in {True, False} for value in gates.values()):
            errors.append("observed_readiness_gate_values_invalid")
        expected_remaining = [
            gate for gate in STATE_PRIOR_OBSERVED_READINESS_GATES if gates.get(gate) is not True
        ]
        all_pass = not expected_remaining
    if payload.get("remaining_gates") != expected_remaining:
        errors.append("observed_readiness_remaining_gates_mismatch")
    if payload.get("required_next_actions") != _required_next_actions(expected_remaining):
        errors.append("observed_readiness_next_actions_mismatch")
    if payload.get("p1_benchmark_input_ready") is not all_pass:
        errors.append("observed_readiness_p1_ready_mismatch")
    if payload.get("p2_admission_permitted") is not False:
        errors.append("observed_readiness_p2_admission_must_be_false")
    expected_claim = _READY_CLAIM if all_pass else _BLOCKED_CLAIM
    if payload.get("supported_claim") != expected_claim:
        errors.append("observed_readiness_supported_claim_mismatch")
    if payload.get("claim_boundary") != _CLAIM_BOUNDARY:
        errors.append("observed_readiness_claim_boundary_invalid")
    for field in (
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
        "empirical_policy_effect_claim",
    ):
        if payload.get(field) is not False:
            errors.append(f"observed_readiness_{field}_must_be_false")
    readiness_sha256 = payload.get("readiness_sha256")
    if not _valid_sha256(readiness_sha256):
        errors.append("observed_readiness_sha256_invalid")
    elif readiness_sha256 != compute_state_prior_observed_readiness_sha256(payload):
        errors.append("observed_readiness_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_observed_readiness_sha256(payload: Mapping[str, Any]) -> str:
    """Compute the canonical digest of one observed-candidate readiness artifact."""

    values = copy.deepcopy(dict(payload))
    values.pop("readiness_sha256", None)
    return _canonical_sha256(values)


def _raw_payloads_parseable(
    locations: Mapping[str, Any],
    measurements: Mapping[str, Mapping[str, Any]],
) -> bool:
    location_rows = locations.get("results")
    return bool(
        isinstance(location_rows, list)
        and all(isinstance(row, Mapping) for row in location_rows)
        and measurements
        and all(
            isinstance(payload.get("results"), list)
            and all(isinstance(row, Mapping) for row in payload["results"])
            for payload in measurements.values()
        )
    )


def _sensor_location_index(locations: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for location in locations.get("results") or []:
        if not isinstance(location, Mapping):
            continue
        station_id = str(location.get("id") or "").strip()
        coordinates = location.get("coordinates") or {}
        longitude = _finite_float(coordinates.get("longitude"))
        latitude = _finite_float(coordinates.get("latitude"))
        for sensor in location.get("sensors") or []:
            if not isinstance(sensor, Mapping):
                continue
            sensor_id = str(sensor.get("id") or "").strip()
            if sensor_id and station_id:
                index[sensor_id] = {
                    "station_id": station_id,
                    "longitude": longitude,
                    "latitude": latitude,
                }
    return index


def _observations(
    measurements: Mapping[str, Mapping[str, Any]],
    *,
    target_parameter: str | None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for sensor_id, payload in measurements.items():
        for row in payload.get("results") or []:
            if not isinstance(row, Mapping):
                continue
            parameter = row.get("parameter") or {}
            parameter_name = parameter.get("name") if isinstance(parameter, Mapping) else parameter
            if (
                target_parameter is not None
                and _normalize_parameter(parameter_name) != target_parameter
            ):
                continue
            value = _finite_float(row.get("value"))
            started_at, ended_at = _measurement_bounds(row)
            if value is None or started_at is None or ended_at is None:
                continue
            observations.append(
                {
                    "sensor_id": str(sensor_id),
                    "started_at": started_at,
                    "ended_at": ended_at,
                }
            )
    return observations


def _measurement_bounds(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    instant = _datetime_string(row.get("datetime"))
    period = row.get("period") or {}
    if not isinstance(period, Mapping):
        period = {}
    start = _datetime_string(period.get("datetimeFrom")) or instant
    end = _datetime_string(period.get("datetimeTo")) or instant
    return start, end


def _datetime_string(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("utc", "local"):
            if _nonempty_string(value.get(key)):
                return str(value[key])
    return str(value) if _nonempty_string(value) else None


def _time_groups_overlap(left: str, right: str) -> bool:
    return left.startswith(right) or right.startswith(left)


def _required_next_actions(remaining_gates: Sequence[str]) -> list[str]:
    actions_by_gate = {
        "multi_geometry_dataset_contract_valid": "repair_multi_geometry_dataset_contract",
        "three_native_geometry_routes_present": "complete_raster_admin_graph_routes",
        "raw_observation_payloads_parseable": "repair_raw_observation_payloads",
        "target_parameter_observations_present": "acquire_target_parameter_observations",
        "minimum_observation_count_met": "acquire_minimum_observation_count",
        "measurement_sensor_locations_resolved": "resolve_measurement_sensor_locations",
        "minimum_measured_station_support_met": "acquire_multi_station_observations",
        "minimum_spatial_band_support_met": "expand_observed_spatial_support",
        "minimum_observation_time_support_met": "expand_observed_temporal_support",
        "station_admin_crosswalk_complete": "build_station_admin_crosswalk",
        "minimum_admin_group_support_met": "expand_crosswalk_admin_support",
        "observed_geometry_period_overlap": "acquire_period_aligned_geometry_features",
        "normalized_proxy_matches_raw_measurements": (
            "rebuild_normalized_proxy_from_raw_measurements"
        ),
        "target_leakage_boundary_preserved": "remove_target_leakage_from_features",
        "evidence_refs_present": "declare_observed_source_evidence_refs",
    }
    return [actions_by_gate[gate] for gate in remaining_gates]


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_parameter(value: Any) -> str:
    return str(value or "").strip().lower().replace(".", "").replace("_", "")


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"state_prior_observed_readiness_{field}_must_be_positive_integer")
    return value


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _unique_nonempty_strings(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("state_prior_observed_readiness_evidence_refs_must_be_sequence")
    normalized = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    return normalized


def _require_aware_timestamp(value: Any) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError("state_prior_observed_readiness_created_at_must_be_timezone_aware")
    return parsed


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
