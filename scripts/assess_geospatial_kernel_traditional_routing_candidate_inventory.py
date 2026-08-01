#!/usr/bin/env python3
"""Inventory and fail-closed registration preflight for routing comparators."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_comparator_protocol.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_candidate_inventory_report.json"
)
SCHEMA = "gwm.geospatial_kernel.traditional_routing_candidate_inventory.v1"
MANIFEST_SCHEMA = "gwm.geospatial_kernel.traditional_routing_candidate_manifest.v1"
ADAPTER_PROTOCOL = "gwm.geospatial_kernel.traditional_routing_json_adapter.v1"
DOCKER_EXECUTION_BACKEND = "docker_network_none_v1"
CONTAINER_ARTIFACT_ROOT = PurePosixPath("/opt/gwm-candidate")
EXPECTED_PROTOCOL_FILE_SHA256 = (
    "b674db451955d656f31719434a8aa0ac4f29525cc12acd553d594332e5dee744"
)
EXPECTED_PROTOCOL_SEAL_SHA256 = (
    "5a5031c95d245fcdd628d967fd0fd8f5a5ae7208c8236dee65511d46abb6a899"
)
KNOWN_LICENSE = {
    "path": "data/geotransport_v0_1/t_route_mc_source_audit/raw/LICENSE",
    "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "size_bytes": 11358,
}
HYDROLOGIC_EXECUTABLE_NAMES = (
    "troute",
    "rapid",
    "swmm5",
    "raven",
    "mizuroute",
    "hec-hms",
)
HYDROLOGIC_DISTRIBUTION_NAMES = (
    "troute",
    "pyswmm",
    "swmm-toolkit",
    "rapidpy",
    "mizuroute",
)
ROUTING_DOCKER_IMAGE_TOKENS = (
    "troute",
    "t-route",
    "rapid",
    "mizuroute",
    "raven",
    "swmm",
    "hec-hms",
    "muskingum",
)
KNOWN_REJECTED_DOCKER_IMAGES = {
    "sha256:afa5e3952d81fed3836e370fa780e3f904d99823c27be2b6622cd35433477c1c": {
        "source_revision": "12a8eae0cdfed437143c590659fa7077605a5e70",
        "reason": "official_fixed_commit_uninitialized_carry_reads",
    }
}
FORBIDDEN_EXECUTOR_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "score_report",
    "future_target_observations",
}
FORBIDDEN_LEARNED_CODE_TOKENS = (
    b"conservative_edge_flux_innovation",
    b"action_innovation_transition",
    b"action_innovation_prospective",
    b"physical_residual_decay",
)
REQUIRED_INDEPENDENCE_ASSERTIONS = (
    "routing_equations_external_to_geospatial_kernel_learned_code",
    "no_learned_innovation_operator_imports_or_calls",
    "no_shared_fitted_parameters_with_gwm_wwm",
    "adapter_is_axis_and_unit_translation_only",
)
REQUIRED_INTERFACE_DECLARATIONS = (
    "abi_or_api_signature",
    "explicit_initialization_semantics",
    "restart_state_serialization",
    "mass_ledger_capability",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def assess_inventory(
    candidate_manifest_paths: tuple[Path, ...] = (),
    *,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    protocol = _protocol_identity(root, protocol_path)
    candidates = {
        f"{index}:{Path(path).name}": assess_candidate_manifest(
            Path(path),
            repo_root=root,
            protocol_path=protocol_path,
        )
        for index, path in enumerate(candidate_manifest_paths)
    }
    all_submitted_registered = bool(candidates) and all(
        value["candidate_registration_ready"] is True for value in candidates.values()
    )
    host_inventory = _host_inventory()
    local_isolation_available = host_inventory["execution_isolation"][
        "professional_backend_available"
    ]
    assessment_integrity_passed = protocol["identity_matches"] is True and (
        not candidates or all_submitted_registered
    )
    if not protocol["identity_matches"]:
        status = "blocked_protocol_identity_failure"
    elif not candidates:
        status = "blocked_no_registered_independent_candidate"
    elif not all_submitted_registered:
        status = "blocked_candidate_registration_failure"
    else:
        status = "registered_candidates_ready_for_synthetic_conformance"
    registered_ids = [
        str(value["candidate_id"])
        for value in candidates.values()
        if value["candidate_registration_ready"] is True
    ]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "protocol": protocol,
        "host_inventory": host_inventory,
        "known_repository_runtimes": _known_repository_runtimes(root, protocol),
        "submitted_candidate_count": len(candidates),
        "candidates": candidates,
        "registration_contract": {
            "manifest_schema": MANIFEST_SCHEMA,
            "artifacts_must_be_inside_repository": True,
            "every_artifact_hash_and_size_recomputed": True,
            "required_independence_assertions": list(REQUIRED_INDEPENDENCE_ASSERTIONS),
            "required_interface_declarations": list(REQUIRED_INTERFACE_DECLARATIONS),
            "registration_executes_candidate_runtime": False,
            "registration_implies_semantic_certification": False,
            "registration_implies_runtime_admission": False,
            "required_execution_backend": DOCKER_EXECUTION_BACKEND,
            "immutable_docker_image_id_required": True,
            "runtime_and_adapter_mount_targets_hash_bound": True,
            "synthetic_zero_state_artifact_hash_bound": True,
            "sealed_source_and_abi_audits_required_before_conformance": True,
            "production_execution_recomputes_audit_artifact_files": True,
            "preexecution_audits_bind_complete_registration_identity": True,
        },
        "assessment_integrity_passed": assessment_integrity_passed,
        "decision": {
            "registered_candidate_ids": registered_ids,
            "candidate_registration_ready": all_submitted_registered,
            "professional_runtime_available": False,
            "synthetic_conformance_execution_permitted": (
                all_submitted_registered and local_isolation_available
            ),
            "local_network_isolation_available": local_isolation_available,
            "synthetic_conformance_executed": False,
            "matched_two_system_execution_permitted": False,
            "traditional_predictions_executed": False,
            "runtime_admitted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
            "recommended_next_action": (
                "register_one_versioned_independent_runtime_then_execute_the_frozen_"
                "outcome_free_synthetic_conformance_suite"
            ),
        },
        "execution_boundary": {
            "network_requests_performed": False,
            "candidate_runtime_invoked": False,
            "two_system_dynamic_inputs_opened": False,
            "outcome_artifacts_opened": False,
            "candidate_parameters_fitted": False,
        },
    }


def assess_candidate_manifest(
    manifest_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    path = _inside_root(root, manifest_path)
    manifest, manifest_error = _read_json(path)
    protocol = _protocol_identity(root, protocol_path)
    forbidden_locations = _find_forbidden_keys(manifest)

    implementation = _mapping(manifest.get("implementation_identity"))
    license_record = _mapping(manifest.get("license"))
    build = _mapping(manifest.get("build"))
    runtime = _mapping(manifest.get("runtime"))
    independence = _mapping(manifest.get("independence"))
    interface = _mapping(manifest.get("interface"))
    execution_binding = _docker_execution_binding(runtime)

    source_descriptors = implementation.get("source_artifacts")
    if not isinstance(source_descriptors, list):
        source_descriptors = []
    source_artifacts = [
        _descriptor_identity(root, descriptor) for descriptor in source_descriptors
    ]
    artifacts = {
        "license": _descriptor_identity(root, license_record.get("artifact")),
        "dependency_lock": _descriptor_identity(root, build.get("dependency_lock")),
        "runtime": _descriptor_identity(root, runtime.get("artifact")),
        "adapter_source": _descriptor_identity(root, runtime.get("adapter_source")),
        "serialized_zero_state": _json_object_descriptor_identity(
            root, runtime.get("serialized_zero_state")
        ),
    }
    all_artifacts = source_artifacts + list(artifacts.values())
    artifact_identities_match = bool(source_artifacts) and all(
        item["identity_matches"] is True for item in all_artifacts
    )
    learned_code_tokens = _scan_forbidden_source_tokens(
        root,
        source_descriptors + [runtime.get("adapter_source")],
    )
    zero_state_forbidden_locations = list(
        artifacts["serialized_zero_state"].get("forbidden_content_locations", [])
    )
    forbidden_locations.extend(
        f"$.runtime.serialized_zero_state{location[1:]}"
        for location in zero_state_forbidden_locations
    )
    identity_valid = (
        manifest_error is None
        and manifest.get("schema") == MANIFEST_SCHEMA
        and _nonempty(manifest.get("candidate_id"))
        and manifest.get("method_family")
        in {"muskingum_cunge", "documented_close_traditional_routing"}
        and _nonempty(implementation.get("upstream_project"))
        and str(implementation.get("repository", "")).startswith("https://")
        and _immutable_revision(implementation.get("immutable_revision"))
        and _nonempty(implementation.get("release_or_version"))
    )
    license_valid = (
        _nonempty(license_record.get("spdx_identifier"))
        and license_record.get("benchmark_use_permitted") is True
        and license_record.get("redistribution_permitted") is True
        and artifacts["license"]["identity_matches"] is True
    )
    build_valid = (
        _nonempty(build.get("compiler_or_interpreter_identity"))
        and isinstance(build.get("flags"), list)
        and artifacts["dependency_lock"]["identity_matches"] is True
        and _container_platform(runtime.get("platform"))
        and runtime.get("interface_kind") in {"shared_library", "command_line", "python_api"}
        and runtime.get("adapter_protocol") == ADAPTER_PROTOCOL
        and _nonempty(runtime.get("entrypoint"))
        and artifacts["runtime"]["identity_matches"] is True
        and artifacts["adapter_source"]["identity_matches"] is True
        and artifacts["serialized_zero_state"]["identity_matches"] is True
        and artifacts["serialized_zero_state"]["json_object_valid"] is True
        and execution_binding["identity_matches"] is True
    )
    independence_valid = (
        all(independence.get(name) is True for name in REQUIRED_INDEPENDENCE_ASSERTIONS)
        and not learned_code_tokens
    )
    interface_declared = all(
        interface.get(name) is True for name in REQUIRED_INTERFACE_DECLARATIONS
    )
    claim_boundary_valid = manifest.get("claim_boundary") == {
        "outcome_inputs_included": False,
        "target_parameters_fitted": False,
        "synthetic_conformance_executed": False,
        "candidate_certified": False,
        "runtime_admitted": False,
    }
    gates = {
        "frozen_protocol_identity_valid": protocol["identity_matches"] is True,
        "manifest_schema_and_implementation_identity_valid": identity_valid,
        "all_source_build_runtime_license_and_adapter_artifacts_hash_bound": (
            artifact_identities_match
        ),
        "license_and_use_rights_documented": license_valid,
        "build_runtime_interface_and_container_identity_valid": build_valid,
        "docker_image_command_and_artifact_mounts_identity_bound": execution_binding[
            "identity_matches"
        ],
        "synthetic_zero_state_artifact_identity_and_json_valid": (
            artifacts["serialized_zero_state"]["identity_matches"] is True
            and artifacts["serialized_zero_state"]["json_object_valid"] is True
            and not zero_state_forbidden_locations
        ),
        "independence_assertions_and_source_scan_pass": independence_valid,
        "required_interface_capabilities_declared_for_later_certification": (
            interface_declared
        ),
        "no_forbidden_outcome_or_score_inputs_declared": not forbidden_locations,
        "claim_boundary_is_fail_closed": claim_boundary_valid,
    }
    registration_ready = all(gates.values())
    return {
        "schema": SCHEMA,
        "candidate_id": manifest.get("candidate_id"),
        "manifest_artifact": _file_identity(root, path),
        "manifest_error": manifest_error,
        "protocol": protocol,
        "source_artifacts": source_artifacts,
        "artifacts": artifacts,
        "execution_binding": execution_binding,
        "forbidden_content_locations": forbidden_locations,
        "forbidden_learned_code_tokens": learned_code_tokens,
        "gates": gates,
        "candidate_registration_ready": registration_ready,
        "decision": (
            "ready_for_outcome_free_synthetic_conformance"
            if registration_ready
            else "blocked_before_candidate_runtime_execution"
        ),
        "claim_boundary": {
            "candidate_runtime_invoked": False,
            "synthetic_conformance_executed": False,
            "professional_runtime_certified": False,
            "matched_two_system_execution_permitted": False,
            "runtime_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _docker_execution_binding(runtime: Mapping[str, object]) -> dict[str, object]:
    execution = _mapping(runtime.get("execution"))
    image_id = execution.get("image_id")
    command_value = execution.get("adapter_command")
    command = command_value if isinstance(command_value, list) else []
    mount_value = execution.get("read_only_mount_targets")
    mount_targets = mount_value if isinstance(mount_value, dict) else {}
    runtime_target = mount_targets.get("runtime")
    adapter_target = mount_targets.get("adapter_source")
    targets_valid = (
        _container_artifact_target(runtime_target)
        and _container_artifact_target(adapter_target)
        and runtime_target != adapter_target
    )
    command_valid = (
        bool(command)
        and all(
            isinstance(argument, str) and bool(argument) and "\x00" not in argument
            for argument in command
        )
        and adapter_target in command
    )
    identity_matches = (
        execution.get("backend") == DOCKER_EXECUTION_BACKEND
        and _immutable_docker_image_id(image_id)
        and targets_valid
        and command_valid
    )
    return {
        "backend": execution.get("backend"),
        "image_id": image_id,
        "container_platform": dict(_mapping(runtime.get("platform"))),
        "adapter_command": list(command),
        "read_only_mount_targets": {
            "runtime": runtime_target,
            "adapter_source": adapter_target,
        },
        "network_mode": "none" if identity_matches else None,
        "identity_matches": identity_matches,
    }


def _container_platform(value: object) -> bool:
    platform_identity = _mapping(value)
    return (
        platform_identity.get("system") == "Linux"
        and platform_identity.get("machine") in {"amd64", "arm64"}
    )


def _container_artifact_target(value: object) -> bool:
    if not isinstance(value, str) or not value or "," in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return (
        path.is_absolute()
        and path != CONTAINER_ARTIFACT_ROOT
        and CONTAINER_ARTIFACT_ROOT in path.parents
        and ".." not in path.parts
    )


def _immutable_docker_image_id(value: object) -> bool:
    prefix = "sha256:"
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and len(value) == len(prefix) + 64
        and all(character in "0123456789abcdef" for character in value[len(prefix) :])
    )


def _protocol_identity(root: Path, protocol_path: Path) -> dict[str, object]:
    path = _inside_root(root, protocol_path)
    body = path.read_bytes()
    actual_sha256 = hashlib.sha256(body).hexdigest()
    payload, error = _read_json(path)
    seal = _mapping(payload.get("protocol_seal"))
    body_without_seal = dict(payload)
    body_without_seal.pop("protocol_seal", None)
    canonical = json.dumps(
        body_without_seal,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    actual_seal = hashlib.sha256(canonical).hexdigest()
    contract_matches = (
        error is None
        and payload.get("schema")
        == "gwm.geospatial_kernel.traditional_routing_comparator_protocol.v1"
        and payload.get("status") == "frozen_before_independent_runtime_selection"
        and payload.get("method_scope", {}).get("candidate_selected") is False
        and payload.get("admission_decision", {}).get("runtime_admitted") is False
        and payload.get("claim_boundary", {}).get("traditional_predictions_executed")
        is False
    )
    identity_matches = (
        actual_sha256 == EXPECTED_PROTOCOL_FILE_SHA256
        and seal.get("sha256") == EXPECTED_PROTOCOL_SEAL_SHA256
        and actual_seal == EXPECTED_PROTOCOL_SEAL_SHA256
        and contract_matches
    )
    return {
        "path": _display_path(root, path),
        "sha256": actual_sha256,
        "size_bytes": len(body),
        "expected_sha256": EXPECTED_PROTOCOL_FILE_SHA256,
        "protocol_seal_sha256": seal.get("sha256"),
        "recomputed_protocol_seal_sha256": actual_seal,
        "identity_matches": identity_matches,
        "json_error": error,
        "frozen_at": payload.get("frozen_at"),
    }


def _known_repository_runtimes(
    root: Path,
    protocol: dict[str, object],
) -> dict[str, Any]:
    protocol_path = _inside_root(root, Path(str(protocol["path"])))
    payload, _ = _read_json(protocol_path)
    evidence = _mapping(payload.get("bound_evidence"))
    disposition = _mapping(payload.get("previous_runtime_disposition"))
    official = _known_runtime(
        root,
        evidence.get("official_runtime_build"),
        _mapping(disposition.get("official_fixed_commit")),
    )
    derived = _known_runtime(
        root,
        evidence.get("derived_runtime_build"),
        _mapping(disposition.get("derived_initialized_diagnostic")),
    )
    license_identity = _descriptor_identity(root, KNOWN_LICENSE)
    return {
        "official_fixed_commit": official,
        "derived_initialized_diagnostic": derived,
        "shared_upstream_license": {
            **license_identity,
            "spdx_identifier": "Apache-2.0",
        },
        "any_professional_runtime_available": False,
    }


def _known_runtime(
    root: Path,
    descriptor: object,
    disposition: dict[str, Any],
) -> dict[str, object]:
    identity = _descriptor_identity(root, descriptor)
    payload: dict[str, Any] = {}
    if identity["identity_matches"] is True:
        payload, _ = _read_json(_inside_root(root, Path(str(identity["path"]))))
    runtime_platform = _mapping(payload.get("platform"))
    return {
        "build_manifest": identity,
        "source_commit": disposition.get("source_commit"),
        "runtime_platform": runtime_platform,
        "current_host_direct_execution_compatible": (
            runtime_platform.get("system") == platform.system()
            and runtime_platform.get("machine") == platform.machine()
        ),
        "professional_runtime_eligible": False,
        "rejection_reason": disposition.get("reason"),
    }


def _host_inventory() -> dict[str, Any]:
    executables = {name: shutil.which(name) for name in HYDROLOGIC_EXECUTABLE_NAMES}
    distributions = {
        name: _distribution_version(name) for name in HYDROLOGIC_DISTRIBUTION_NAMES
    }
    os_route = shutil.which("route")
    execution_isolation = _execution_isolation_inventory()
    docker_images = _docker_image_inventory(shutil.which("docker"))
    return {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "hydrologic_executables": executables,
        "hydrologic_python_distributions": distributions,
        "os_network_route_false_positive": {
            "path": os_route,
            "is_hydrologic_routing_candidate": False,
        },
        "discovered_hydrologic_executable_count": sum(
            value is not None for value in executables.values()
        ),
        "discovered_hydrologic_distribution_count": sum(
            value is not None for value in distributions.values()
        ),
        "ambient_discovery_alone_can_register_a_candidate": False,
        "execution_isolation": execution_isolation,
        "docker_routing_image_inventory": docker_images,
    }


def _docker_image_inventory(docker_executable: str | None) -> dict[str, Any]:
    if docker_executable is None:
        return _parse_docker_image_inventory(None, attempted=False, returncode=None)
    try:
        completed = subprocess.run(
            [
                docker_executable,
                "image",
                "ls",
                "--no-trunc",
                "--format",
                "{{json .}}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _parse_docker_image_inventory(None, attempted=True, returncode=None)
    return _parse_docker_image_inventory(
        completed.stdout if completed.returncode == 0 else None,
        attempted=True,
        returncode=completed.returncode,
    )


def _parse_docker_image_inventory(
    output: str | None,
    *,
    attempted: bool,
    returncode: int | None,
) -> dict[str, Any]:
    by_image: dict[str, set[str]] = {}
    malformed_row_count = 0
    if output is not None:
        for line in output.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed_row_count += 1
                continue
            if not isinstance(row, dict):
                malformed_row_count += 1
                continue
            image_id = row.get("ID")
            repository = row.get("Repository")
            tag = row.get("Tag")
            if not _immutable_docker_image_id(image_id):
                malformed_row_count += 1
                continue
            references = by_image.setdefault(str(image_id), set())
            if (
                isinstance(repository, str)
                and repository not in {"", "<none>"}
                and isinstance(tag, str)
                and tag not in {"", "<none>"}
            ):
                references.add(f"{repository}:{tag}")
    routing_images: list[dict[str, object]] = []
    for image_id, references in sorted(by_image.items()):
        matched = sorted(
            reference
            for reference in references
            if any(
                token in reference.casefold() for token in ROUTING_DOCKER_IMAGE_TOKENS
            )
        )
        if not matched:
            continue
        rejection = KNOWN_REJECTED_DOCKER_IMAGES.get(image_id)
        routing_images.append(
            {
                "image_id": image_id,
                "matching_references": matched,
                "known_rejected_runtime": rejection is not None,
                "known_rejection": rejection,
                "candidate_manifest_registered": False,
                "professional_candidate_eligible": False,
                "disposition": (
                    "known_rejected_runtime"
                    if rejection is not None
                    else "unregistered_requires_identity_review"
                ),
            }
        )
    unknown_count = sum(
        item["known_rejected_runtime"] is False for item in routing_images
    )
    if output is None:
        status = "docker_image_inventory_unavailable"
    elif not routing_images:
        status = "no_routing_named_local_image"
    elif unknown_count:
        status = "unregistered_routing_named_images_require_identity_review"
    else:
        status = "only_known_rejected_routing_images_found"
    return {
        "status": status,
        "probe_attempted": attempted,
        "probe_returncode": returncode,
        "total_unique_local_image_count": len(by_image),
        "malformed_row_count": malformed_row_count,
        "routing_name_tokens": list(ROUTING_DOCKER_IMAGE_TOKENS),
        "routing_named_image_count": len(routing_images),
        "unregistered_unreviewed_routing_named_image_count": unknown_count,
        "routing_named_images": routing_images,
        "discovery_scope": "repository_and_tag_names_only",
        "image_filesystem_or_layer_contents_inspected": False,
        "name_discovery_implies_candidate_registration": False,
        "network_requests_performed": False,
        "candidate_runtime_invoked": False,
    }


def _execution_isolation_inventory() -> dict[str, Any]:
    sandbox_executable = shutil.which("sandbox-exec")
    docker_executable = shutil.which("docker")
    sandbox_profile_probe = _command_probe(
        None
        if sandbox_executable is None
        else [
            sandbox_executable,
            "-p",
            "(version 1) (allow default) (deny network*)",
            "/usr/bin/true",
        ]
    )
    socket_control_probe = _command_probe(
        [
            sys.executable,
            "-c",
            "import socket; value = socket.socket(); value.close()",
        ]
    )
    sandbox_socket_probe = _command_probe(
        None
        if sandbox_executable is None
        else [
            sandbox_executable,
            "-p",
            "(version 1) (allow default) (deny network*)",
            sys.executable,
            "-c",
            "import socket; value = socket.socket(); value.close()",
        ]
    )
    sandbox_network_deny_verified = (
        sandbox_profile_probe["succeeded"]
        and socket_control_probe["succeeded"]
        and sandbox_socket_probe["attempted"]
        and sandbox_socket_probe["succeeded"] is False
        and sandbox_socket_probe["returncode"] is not None
    )
    docker_probe = _command_probe(
        None
        if docker_executable is None
        else [docker_executable, "info", "--format", "{{.ServerVersion}}"]
    )
    return {
        "sandbox_exec": {
            "path": sandbox_executable,
            "profile_probe_attempted": sandbox_profile_probe["attempted"],
            "profile_probe_returncode": sandbox_profile_probe["returncode"],
            "socket_control_succeeded": socket_control_probe["succeeded"],
            "sandboxed_socket_probe_returncode": sandbox_socket_probe[
                "returncode"
            ],
            "network_deny_verified": sandbox_network_deny_verified,
        },
        "docker": {
            "path": docker_executable,
            "probe_attempted": docker_probe["attempted"],
            "daemon_available": docker_probe["succeeded"],
            "probe_returncode": docker_probe["returncode"],
            "required_network_mode": "none",
        },
        "professional_backend_available": (
            sandbox_network_deny_verified or docker_probe["succeeded"]
        ),
        "plain_subprocess_is_professional_execution": False,
    }


def _command_probe(command: list[str] | None) -> dict[str, object]:
    if command is None:
        return {"attempted": False, "succeeded": False, "returncode": None}
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"attempted": True, "succeeded": False, "returncode": None}
    return {
        "attempted": True,
        "succeeded": completed.returncode == 0,
        "returncode": completed.returncode,
    }


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _descriptor_identity(root: Path, value: object) -> dict[str, object]:
    descriptor = _mapping(value)
    declared_path = descriptor.get("path")
    declared_sha256 = descriptor.get("sha256")
    declared_size = descriptor.get("size_bytes")
    result: dict[str, object] = {
        "path": declared_path,
        "declared_sha256": declared_sha256,
        "declared_size_bytes": declared_size,
        "actual_sha256": None,
        "actual_size_bytes": None,
        "identity_matches": False,
    }
    if not isinstance(declared_path, str):
        return result
    try:
        path = _inside_root(root, Path(declared_path))
        body = path.read_bytes()
    except (OSError, ValueError):
        return result
    actual_sha256 = hashlib.sha256(body).hexdigest()
    result.update(
        {
            "path": _display_path(root, path),
            "actual_sha256": actual_sha256,
            "actual_size_bytes": len(body),
            "identity_matches": (
                declared_sha256 == actual_sha256
                and declared_size == len(body)
                and isinstance(declared_size, int)
                and not isinstance(declared_size, bool)
            ),
        }
    )
    return result


def _json_object_descriptor_identity(root: Path, value: object) -> dict[str, object]:
    result = _descriptor_identity(root, value)
    result.update(
        {
            "json_object_valid": False,
            "canonical_sha256": None,
            "forbidden_content_locations": [],
        }
    )
    if result["identity_matches"] is not True:
        return result
    try:
        path = _inside_root(root, Path(str(result["path"])))
        payload = _read_strict_json_object(path)
        canonical = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (OSError, UnicodeError, ValueError):
        return result
    result.update(
        {
            "json_object_valid": True,
            "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
            "forbidden_content_locations": _find_forbidden_keys(payload),
        }
    )
    return result


def _file_identity(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": _display_path(root, path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _scan_forbidden_source_tokens(root: Path, descriptors: list[object]) -> list[str]:
    found: set[str] = set()
    for descriptor_value in descriptors:
        descriptor = _mapping(descriptor_value)
        if not isinstance(descriptor.get("path"), str):
            continue
        try:
            body = _inside_root(root, Path(str(descriptor["path"]))).read_bytes().lower()
        except (OSError, ValueError):
            continue
        for token in FORBIDDEN_LEARNED_CODE_TOKENS:
            if token in body:
                found.add(token.decode("ascii"))
    return sorted(found)


def _find_forbidden_keys(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in FORBIDDEN_EXECUTOR_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        folded = value.casefold()
        if any(key in folded for key in FORBIDDEN_EXECUTOR_KEYS):
            found.append(path)
    return found


def _inside_root(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("traditional_routing_candidate_artifact_outside_repository") from error
    return resolved


def _display_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {}, f"{type(error).__name__}:{error}"
    if not isinstance(payload, dict):
        return {}, "json_root_not_object"
    return payload, None


def _read_strict_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"nonfinite_json_number:{value}")

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError("json_root_not_object")
    return payload


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _immutable_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def main() -> int:
    args = parse_args()
    report = assess_inventory(tuple(args.candidate_manifest))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"submitted_candidate_count={report['submitted_candidate_count']}")
    print(
        "candidate_registration_ready="
        f"{report['decision']['candidate_registration_ready']}"
    )
    return 0 if report["assessment_integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
