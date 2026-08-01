#!/usr/bin/env python3
"""Preflight prospective outcome-free episode manifests before execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_internal_innovation_rollout_protocol.json"
)
ADDENDUM_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_manning_execution_addendum.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_episode_preflight_report.json"
)
SCHEMA = "gwm.geospatial_kernel.internal_innovation_episode_preflight.v1"
MANIFEST_SCHEMA = "gwm.geospatial_kernel.prospective_episode_input_manifest.v1"
EXPECTED_PROTOCOL_FILE_SHA256 = "411071ad99c597358199710365e1267e2ce0847685484208b2a1169056ba8f41"
EXPECTED_PROTOCOL_SEAL_SHA256 = "9d69d960c43a972d77d42267fa4fe854e6b85f9f13dae9ea7cf50b7888901fd3"
ADDENDUM_SCHEMA = "gwm.geospatial_kernel.internal_innovation_manning_execution_addendum.v1"
ADDENDUM_CODE_PATHS = (
    "scripts/assess_geospatial_kernel_internal_innovation_episode_preflight.py",
    "scripts/run_geospatial_kernel_internal_innovation_manning_episode.py",
    "scripts/compile_geospatial_kernel_internal_innovation_execution_ledger.py",
)
SYSTEM_IDS = ("center_hill", "j_percy_priest")
OPERATOR_SCHEMAS = {
    "gwm.geospatial_kernel.branching_manning_network_storage.v1",
    "gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1",
}
REQUIRED_INPUT_ARTIFACTS = {
    "feature_axis": "gwm.geospatial_kernel.feature_axis.v1",
    "edge_axis": "gwm.geospatial_kernel.edge_axis.v1",
    "hydraulic_geometry": "gwm.geospatial_kernel.reach_hydraulic_geometry.v1",
    "initial_state": "gwm.geospatial_kernel.prospective_initial_state.v1",
    "reservoir_action_schedule": ("gwm.geospatial_kernel.prospective_reservoir_action_schedule.v1"),
    "distributed_forcing_forecast": (
        "gwm.geospatial_kernel.prospective_distributed_forcing_forecast.v1"
    ),
    "input_availability_receipts": ("gwm.geospatial_kernel.input_availability_receipts.v1"),
}
_RECEIPTED_ARTIFACTS = tuple(
    name for name in REQUIRED_INPUT_ARTIFACTS if name != "input_availability_receipts"
)
_FORBIDDEN_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "future_target_observations",
}
_FORBIDDEN_ROLES = {
    "outcome",
    "independent_observation",
    "target_observation",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = assess_queue(tuple(args.manifest))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"submitted_episode_count={report['submitted_episode_count']}")
    return 0 if report["assessment_integrity_passed"] else 1


def assess_queue(
    manifest_paths: tuple[Path, ...] = (),
    *,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    protocol = _protocol_identity(root, protocol_path)
    episodes = {
        f"{index}:{Path(path).name}": assess_manifest(
            Path(path),
            repo_root=root,
            protocol_path=protocol_path,
        )
        for index, path in enumerate(manifest_paths)
    }
    all_submitted_passed = bool(episodes) and all(
        value["episode_execution_ready"] is True for value in episodes.values()
    )
    assessment_integrity_passed = protocol["identity_matches"] is True and (
        not episodes or all_submitted_passed
    )
    if not protocol["identity_matches"]:
        status = "blocked_protocol_identity_failure"
    elif not episodes:
        status = "awaiting_prospective_episode_manifests"
    elif all_submitted_passed:
        status = "submitted_episodes_ready_for_outcome_free_execution"
    else:
        status = "blocked_invalid_prospective_episode_manifest"
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "protocol": protocol,
        "submitted_episode_count": len(episodes),
        "episodes": episodes,
        "all_submitted_episodes_ready": all_submitted_passed,
        "assessment_integrity_passed": assessment_integrity_passed,
        "execution_boundary": {
            "network_requests_performed": False,
            "outcome_artifacts_opened": False,
            "physical_rollout_executed": False,
            "candidate_fit_executed": False,
            "runtime_enabled": False,
        },
    }


def assess_manifest(
    manifest_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    path = _inside_root(root, manifest_path)
    manifest, manifest_error = _read_json(path)
    protocol = _protocol_identity(root, protocol_path)
    manifest_artifact = _file_identity(path, root=root)
    forbidden_locations = _find_forbidden_content(manifest)
    issue_time = _aware_datetime(manifest.get("forecast_issue_time"))
    support = manifest.get("support")
    if not isinstance(support, dict):
        support = {}
    support_start = _aware_datetime(support.get("start_inclusive"))
    support_end = _aware_datetime(support.get("end_exclusive"))
    frozen_at = _aware_datetime(protocol.get("frozen_at"))
    temporal_contract_valid = (
        issue_time is not None
        and support_start is not None
        and support_end is not None
        and frozen_at is not None
        and issue_time >= frozen_at
        and support_start > frozen_at
        and issue_time <= support_start
        and support_end == support_start + timedelta(hours=24)
        and support.get("time_step_seconds") == 3600
        and support.get("step_count") == 24
    )
    manifest_protocol = manifest.get("protocol")
    if not isinstance(manifest_protocol, dict):
        manifest_protocol = {}
    protocol_binding_valid = (
        protocol["identity_matches"] is True
        and manifest_protocol.get("path") == protocol.get("path")
        and manifest_protocol.get("sha256") == EXPECTED_PROTOCOL_FILE_SHA256
        and manifest_protocol.get("protocol_seal_sha256") == EXPECTED_PROTOCOL_SEAL_SHA256
    )
    execution_addendum = _execution_addendum_identity(
        root,
        manifest.get("execution_addendum"),
    )
    identity_valid = (
        manifest_error is None
        and manifest.get("schema") == MANIFEST_SCHEMA
        and isinstance(manifest.get("episode_id"), str)
        and bool(str(manifest.get("episode_id")).strip())
        and manifest.get("system_id") in SYSTEM_IDS
        and manifest.get("operator_schema") in OPERATOR_SCHEMAS
    )

    artifact_descriptors = manifest.get("artifacts")
    if not isinstance(artifact_descriptors, dict):
        artifact_descriptors = {}
    artifacts: dict[str, dict[str, object]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_name, expected_schema in REQUIRED_INPUT_ARTIFACTS.items():
        descriptor = artifact_descriptors.get(artifact_name)
        record = _descriptor_identity(root, descriptor, expected_schema)
        artifacts[artifact_name] = record
        if record["identity_matches"] is True and isinstance(descriptor, dict):
            payload, error = _read_json(_inside_root(root, Path(str(descriptor["path"]))))
            if error is None:
                payloads[artifact_name] = payload
    for artifact_name, payload in payloads.items():
        forbidden_locations.extend(
            f"$.artifacts.{artifact_name}{location[1:]}"
            for location in _find_forbidden_content(payload)
        )
    forbidden_locations = sorted(set(forbidden_locations))
    artifacts_hash_bound = len(artifacts) == len(REQUIRED_INPUT_ARTIFACTS) and all(
        value["identity_matches"] is True for value in artifacts.values()
    )
    descriptor_availability_valid = issue_time is not None and all(
        value["available_at"] is not None and value["available_at"] <= issue_time
        for value in artifacts.values()
    )
    semantic_checks = _validate_payloads(
        manifest=manifest,
        payloads=payloads,
        descriptors=artifact_descriptors,
        issue_time=issue_time,
        support_start=support_start,
        episode_id=manifest.get("episode_id"),
        system_id=manifest.get("system_id"),
        operator_schema=manifest.get("operator_schema"),
    )
    gates = {
        "manifest_json_and_identity_valid": identity_valid,
        "frozen_protocol_identity_and_binding_valid": protocol_binding_valid,
        "frozen_manning_execution_addendum_identity_and_binding_valid": (
            execution_addendum["identity_matches"] is True
        ),
        "support_is_future_causal_24_hour_grid": temporal_contract_valid,
        "no_forbidden_outcome_content": not forbidden_locations,
        "all_required_input_artifacts_hash_bound": artifacts_hash_bound,
        "all_input_descriptors_available_at_issue": descriptor_availability_valid,
        "input_payload_semantics_valid": semantic_checks["all_checks_passed"],
        "manifest_claim_boundary_valid": manifest.get("claim_boundary")
        == {
            "outcomes_included": False,
            "retrospective_replay": False,
            "inputs_frozen_before_execution": True,
        },
    }
    ready = all(gates.values())
    return {
        "schema": SCHEMA,
        "episode_id": manifest.get("episode_id"),
        "system_id": manifest.get("system_id"),
        "manifest_artifact": manifest_artifact,
        "manifest_error": manifest_error,
        "protocol": protocol,
        "execution_addendum": execution_addendum,
        "artifacts": artifacts,
        "forbidden_content_locations": forbidden_locations,
        "semantic_validation": semantic_checks,
        "gates": gates,
        "episode_execution_ready": ready,
        "decision": (
            "ready_for_outcome_free_physical_rollout"
            if ready
            else "blocked_before_physical_rollout"
        ),
        "execution_boundary": {
            "input_values_parsed_for_preflight": bool(payloads),
            "outcome_values_loaded": False,
            "physical_rollout_executed": False,
        },
    }


def _validate_payloads(
    *,
    manifest: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
    descriptors: dict[str, object],
    issue_time: datetime | None,
    support_start: datetime | None,
    episode_id: object,
    system_id: object,
    operator_schema: object,
) -> dict[str, object]:
    checks = {
        "all_payloads_are_typed_json_objects": (
            set(payloads) == set(REQUIRED_INPUT_ARTIFACTS)
            and all(
                payloads[name].get("schema") == schema
                for name, schema in REQUIRED_INPUT_ARTIFACTS.items()
            )
        ),
        "payload_episode_and_system_identity_match": False,
        "feature_and_edge_axes_valid": False,
        "geometry_and_initial_state_match_feature_axis": False,
        "action_schedule_is_causal_24_hour_grid": False,
        "forcing_forecast_is_modeled_causal_24_hour_grid": False,
        "availability_receipts_bind_every_input": False,
    }
    if not checks["all_payloads_are_typed_json_objects"]:
        return _checks_result(checks)
    checks["payload_episode_and_system_identity_match"] = all(
        payload.get("episode_id") == episode_id and payload.get("system_id") == system_id
        for payload in payloads.values()
    )
    feature_payload = payloads["feature_axis"]
    edge_payload = payloads["edge_axis"]
    feature_rows = feature_payload.get("features")
    edge_rows = edge_payload.get("edges")
    feature_ids: list[int] = []
    feature_valid = isinstance(feature_rows, list) and bool(feature_rows)
    if feature_valid:
        for index, row in enumerate(feature_rows):
            if (
                not isinstance(row, dict)
                or row.get("feature_index") != index
                or not _positive_integer(row.get("feature_id"))
            ):
                feature_valid = False
                break
            feature_ids.append(int(row["feature_id"]))
        feature_valid = feature_valid and len(feature_ids) == len(set(feature_ids))
    feature_valid = feature_valid and feature_payload.get("feature_count") == len(feature_ids)
    edge_valid = isinstance(edge_rows, list) and bool(edge_rows)
    if edge_valid:
        feature_set = set(feature_ids)
        edge_keys: list[str] = []
        for index, row in enumerate(edge_rows):
            if (
                not isinstance(row, dict)
                or row.get("edge_index") != index
                or not isinstance(row.get("edge_key"), str)
                or row.get("source_feature_id") not in feature_set
                or row.get("target_feature_id") not in feature_set
                or row.get("source_feature_id") == row.get("target_feature_id")
                or row.get("direction_role") != "authoritative_network_direction"
                or row.get("edge_admitted") is not True
            ):
                edge_valid = False
                break
            edge_keys.append(str(row["edge_key"]))
        edge_valid = edge_valid and len(edge_keys) == len(set(edge_keys))
        edge_valid = edge_valid and edge_payload.get("edge_count") == len(edge_keys)
    checks["feature_and_edge_axes_valid"] = feature_valid and edge_valid

    geometry = payloads["hydraulic_geometry"]
    initial = payloads["initial_state"]
    geometry_fields = (
        geometry.get("bottom_width_m"),
        geometry.get("side_slope_horizontal_per_vertical"),
        geometry.get("bed_slope"),
        geometry.get("manning_n"),
    )
    checks["geometry_and_initial_state_match_feature_axis"] = (
        geometry.get("feature_ids") == feature_ids
        and all(_positive_vector(value, len(feature_ids)) for value in geometry_fields)
        and geometry.get("admitted_as_hydraulic_geometry") is True
        and _initial_state_valid(
            initial,
            operator_schema=operator_schema,
            feature_ids=feature_ids,
        )
    )
    action = payloads["reservoir_action_schedule"]
    forcing = payloads["distributed_forcing_forecast"]
    checks["action_schedule_is_causal_24_hour_grid"] = (
        _dynamic_grid_valid(
            action,
            feature_ids=feature_ids,
            issue_time=issue_time,
            support_start=support_start,
            value_field="action_m3s",
        )
        and action.get("known_at_issue") is True
    )
    checks["forcing_forecast_is_modeled_causal_24_hour_grid"] = (
        _dynamic_grid_valid(
            forcing,
            feature_ids=feature_ids,
            issue_time=issue_time,
            support_start=support_start,
            value_field="forcing_m3s",
        )
        and forcing.get("modeled") is True
        and forcing.get("ground_truth") is False
    )
    receipts = payloads["input_availability_receipts"].get("receipts")
    receipt_valid = isinstance(receipts, list) and len(receipts) == len(_RECEIPTED_ARTIFACTS)
    if receipt_valid:
        by_name = {
            value.get("artifact_name"): value for value in receipts if isinstance(value, dict)
        }
        receipt_valid = set(by_name) == set(_RECEIPTED_ARTIFACTS)
        for artifact_name in _RECEIPTED_ARTIFACTS:
            descriptor = descriptors.get(artifact_name)
            receipt = by_name.get(artifact_name)
            if not isinstance(descriptor, dict) or not isinstance(receipt, dict):
                receipt_valid = False
                continue
            available_at = _aware_datetime(receipt.get("available_at"))
            receipt_valid = receipt_valid and (
                receipt.get("artifact_sha256") == descriptor.get("sha256")
                and receipt.get("available_at") == descriptor.get("available_at")
                and available_at is not None
                and issue_time is not None
                and available_at <= issue_time
                and isinstance(receipt.get("source_id"), str)
                and bool(str(receipt.get("source_id")).strip())
            )
    checks["availability_receipts_bind_every_input"] = bool(receipt_valid)
    return _checks_result(checks)


def _dynamic_grid_valid(
    payload: dict[str, Any],
    *,
    feature_ids: list[int],
    issue_time: datetime | None,
    support_start: datetime | None,
    value_field: str,
) -> bool:
    rows = payload.get("rows")
    if (
        issue_time is None
        or support_start is None
        or payload.get("feature_ids") != feature_ids
        or payload.get("step_count") != 24
        or not isinstance(rows, list)
        or len(rows) != 24
    ):
        return False
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return False
        start = support_start + timedelta(hours=index)
        if (
            row.get("step_index") != index
            or _aware_datetime(row.get("support_start_utc")) != start
            or _aware_datetime(row.get("support_end_utc")) != start + timedelta(hours=1)
            or not _nonnegative_vector(row.get(value_field), len(feature_ids))
        ):
            return False
    return True


def _initial_state_valid(
    payload: dict[str, Any],
    *,
    operator_schema: object,
    feature_ids: list[int],
) -> bool:
    common_valid = (
        payload.get("unit") == "m3"
        and payload.get("ground_truth") is False
        and isinstance(payload.get("possible_nudging"), bool)
    )
    if operator_schema == ("gwm.geospatial_kernel.branching_manning_network_storage.v1"):
        return (
            common_valid
            and payload.get("representation") == "reach_stock"
            and payload.get("feature_ids") == feature_ids
            and _nonnegative_vector(payload.get("stock_m3"), len(feature_ids))
        )
    if operator_schema != ("gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"):
        return False
    cell_features = payload.get("cell_feature_ids")
    cell_indices = payload.get("cell_index_within_reach")
    cell_volumes = payload.get("cell_volume_m3")
    return (
        common_valid
        and payload.get("representation") == "cell_volume"
        and _canonical_cell_axis_valid(
            cell_features,
            cell_indices,
            feature_ids=feature_ids,
        )
        and _nonnegative_vector(cell_volumes, len(cell_features))
    )


def _canonical_cell_axis_valid(
    cell_features: object,
    cell_indices: object,
    *,
    feature_ids: list[int],
) -> bool:
    if (
        not isinstance(cell_features, list)
        or not cell_features
        or not all(_positive_integer(value) for value in cell_features)
        or not isinstance(cell_indices, list)
        or len(cell_indices) != len(cell_features)
        or not all(_nonnegative_integer(value) for value in cell_indices)
    ):
        return False
    offset = 0
    for feature_id in feature_ids:
        start = offset
        while offset < len(cell_features) and cell_features[offset] == feature_id:
            offset += 1
        count = offset - start
        if count == 0 or cell_indices[start:offset] != list(range(count)):
            return False
    return offset == len(cell_features)


def _protocol_identity(root: Path, protocol_path: Path) -> dict[str, object]:
    path = _inside_root(root, protocol_path)
    payload, error = _read_json(path)
    artifact = _file_identity(path, root=root)
    seal = payload.get("protocol_seal")
    identity_matches = (
        error is None
        and artifact.get("sha256") == EXPECTED_PROTOCOL_FILE_SHA256
        and isinstance(seal, dict)
        and seal.get("sha256") == EXPECTED_PROTOCOL_SEAL_SHA256
        and payload.get("status") == "frozen_awaiting_prospective_outcome_free_inputs"
    )
    return {
        **artifact,
        "expected_sha256": EXPECTED_PROTOCOL_FILE_SHA256,
        "expected_protocol_seal_sha256": EXPECTED_PROTOCOL_SEAL_SHA256,
        "actual_protocol_seal_sha256": (seal.get("sha256") if isinstance(seal, dict) else None),
        "frozen_at": payload.get("frozen_at"),
        "identity_matches": identity_matches,
        "json_error": error,
    }


def _execution_addendum_identity(
    root: Path,
    descriptor: object,
) -> dict[str, object]:
    invalid = {
        "declared": isinstance(descriptor, dict),
        "path": descriptor.get("path") if isinstance(descriptor, dict) else None,
        "expected_schema": ADDENDUM_SCHEMA,
        "declared_schema": (
            descriptor.get("schema") if isinstance(descriptor, dict) else None
        ),
        "expected_sha256": (
            descriptor.get("sha256") if isinstance(descriptor, dict) else None
        ),
        "actual_sha256": None,
        "expected_size_bytes": (
            descriptor.get("size_bytes") if isinstance(descriptor, dict) else None
        ),
        "actual_size_bytes": None,
        "expected_addendum_seal_sha256": (
            descriptor.get("addendum_seal_sha256")
            if isinstance(descriptor, dict)
            else None
        ),
        "actual_addendum_seal_sha256": None,
        "seal_recomputed": False,
        "base_protocol_binding_verified": False,
        "all_frozen_code_identities_recomputed": False,
        "identity_matches": False,
        "json_error": None,
    }
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
        "schema",
        "addendum_seal_sha256",
    }:
        return invalid
    path_value = descriptor.get("path")
    path = _inside_root(root, Path(path_value)) if isinstance(path_value, str) else None
    artifact = _file_identity(path, root=root)
    payload, error = _read_json(path)
    invalid["actual_sha256"] = artifact.get("sha256")
    invalid["actual_size_bytes"] = artifact.get("size_bytes")
    invalid["json_error"] = error
    seal = payload.get("addendum_seal")
    if not isinstance(seal, dict):
        seal = {}
    invalid["actual_addendum_seal_sha256"] = seal.get("sha256")
    without_seal = dict(payload)
    without_seal.pop("addendum_seal", None)
    canonical = json.dumps(
        without_seal,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    seal_recomputed = (
        seal.get("algorithm") == "sha256_canonical_json_without_addendum_seal"
        and _valid_sha256(seal.get("sha256"))
        and hashlib.sha256(canonical).hexdigest() == seal.get("sha256")
    )
    invalid["seal_recomputed"] = seal_recomputed
    base = payload.get("base_rollout_protocol")
    production_protocol = _file_identity(PROTOCOL_PATH, root=REPO_ROOT)
    base_valid = (
        isinstance(base, dict)
        and base
        == {
            "path": PROTOCOL_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": EXPECTED_PROTOCOL_FILE_SHA256,
            "size_bytes": production_protocol.get("size_bytes"),
            "schema": "gwm.geospatial_kernel.internal_innovation_rollout_protocol.v1",
            "protocol_seal_sha256": EXPECTED_PROTOCOL_SEAL_SHA256,
            "bytes_modified": False,
        }
        and production_protocol.get("sha256") == EXPECTED_PROTOCOL_FILE_SHA256
    )
    invalid["base_protocol_binding_verified"] = base_valid
    frozen_code = payload.get("frozen_code")
    code_valid = isinstance(frozen_code, dict) and set(frozen_code) == set(
        ADDENDUM_CODE_PATHS
    )
    if code_valid:
        for relative_path in ADDENDUM_CODE_PATHS:
            expected = frozen_code[relative_path]
            actual = _file_identity(REPO_ROOT / relative_path, root=REPO_ROOT)
            if expected != actual:
                code_valid = False
                break
    invalid["all_frozen_code_identities_recomputed"] = code_valid
    claims = payload.get("claim_boundary")
    claims_valid = claims == {
        "base_rollout_protocol_modified": False,
        "manning_execution_chain_frozen": True,
        "prospective_manifests_acquired": False,
        "prospective_predictions_executed": False,
        "outcomes_loaded": False,
        "internal_innovation_fitted": False,
        "candidate_promoted": False,
        "runtime_enabled": False,
        "geospatial_kernel_validated": False,
    }
    identity_matches = (
        error is None
        and payload.get("schema") == ADDENDUM_SCHEMA
        and payload.get("status")
        == "frozen_before_prospective_manning_episode_execution"
        and descriptor.get("schema") == ADDENDUM_SCHEMA
        and _valid_sha256(descriptor.get("sha256"))
        and _nonnegative_integer(descriptor.get("size_bytes"))
        and descriptor.get("sha256") == artifact.get("sha256")
        and descriptor.get("size_bytes") == artifact.get("size_bytes")
        and descriptor.get("addendum_seal_sha256") == seal.get("sha256")
        and seal_recomputed
        and base_valid
        and code_valid
        and claims_valid
    )
    invalid["identity_matches"] = identity_matches
    return invalid


def _descriptor_identity(
    root: Path,
    descriptor: object,
    expected_schema: str,
) -> dict[str, object]:
    if not isinstance(descriptor, dict):
        return {
            "declared": False,
            "identity_matches": False,
            "available_at": None,
        }
    path_value = descriptor.get("path")
    path = _inside_root(root, Path(path_value)) if isinstance(path_value, str) else None
    artifact = _file_identity(path, root=root)
    available_at = _aware_datetime(descriptor.get("available_at"))
    valid_sha = _valid_sha256(descriptor.get("sha256"))
    valid_size = _nonnegative_integer(descriptor.get("size_bytes"))
    identity_matches = (
        path is not None
        and valid_sha
        and valid_size
        and descriptor.get("schema") == expected_schema
        and isinstance(descriptor.get("provenance_id"), str)
        and bool(str(descriptor.get("provenance_id")).strip())
        and available_at is not None
        and artifact.get("sha256") == descriptor.get("sha256")
        and artifact.get("size_bytes") == descriptor.get("size_bytes")
    )
    return {
        "declared": True,
        "path": path_value,
        "expected_schema": expected_schema,
        "declared_schema": descriptor.get("schema"),
        "expected_sha256": descriptor.get("sha256"),
        "actual_sha256": artifact.get("sha256"),
        "expected_size_bytes": descriptor.get("size_bytes"),
        "actual_size_bytes": artifact.get("size_bytes"),
        "available_at": available_at,
        "identity_matches": identity_matches,
    }


def _find_forbidden_content(value: object, location: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in _FORBIDDEN_KEYS:
                found.append(child_location)
            if key == "variable_role" and child in _FORBIDDEN_ROLES:
                found.append(child_location)
            found.extend(_find_forbidden_content(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_content(child, f"{location}[{index}]"))
    return found


def _inside_root(root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _read_json(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, "json_artifact_missing_or_outside_repository"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, f"json_artifact_invalid:{type(error).__name__}"
    if not isinstance(value, dict):
        return {}, "json_artifact_root_must_be_object"
    return value, None


def _file_identity(path: Path | None, *, root: Path) -> dict[str, object]:
    if path is None or not path.is_file():
        return {"path": None, "sha256": None, "size_bytes": None}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _checks_result(checks: dict[str, bool]) -> dict[str, object]:
    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
    }


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _positive_vector(value: object, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(_finite_number(item) and float(item) > 0.0 for item in value)
    )


def _nonnegative_vector(value: object, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(_finite_number(item) and float(item) >= 0.0 for item in value)
    )


if __name__ == "__main__":
    raise SystemExit(main())
