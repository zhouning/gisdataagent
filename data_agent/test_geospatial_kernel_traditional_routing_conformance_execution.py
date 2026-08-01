from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_adapter_contract import (
    TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
    TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
    validate_traditional_routing_adapter_response,
)
from data_agent.uwm.geospatial_kernel_v2.traditional_routing_conformance_execution import (
    EXPECTED_EXECUTION_COUNT,
    EXPECTED_WARMUP_EXECUTION_COUNT,
    execute_traditional_routing_synthetic_conformance,
)
from data_agent.uwm.geospatial_kernel_v2.traditional_routing_docker_executor import (
    TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA,
    DockerReadOnlyMount,
)
from data_agent.uwm.geospatial_kernel_v2.traditional_routing_preexecution_audit import (
    ABI_AUDIT_KIND,
    ABI_AUDIT_REQUIREMENTS,
    EXPECTED_PROTOCOL_FILE_SHA256,
    EXPECTED_PROTOCOL_SEAL_SHA256,
    SOURCE_AUDIT_KIND,
    SOURCE_AUDIT_REQUIREMENTS,
    build_traditional_routing_preexecution_audit,
)

IMAGE_ID = "sha256:" + "4" * 64


def test_complete_matrix_is_generated_but_test_executor_cannot_certify(
    tmp_path: Path,
) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)
    requests: list[dict[str, object]] = []

    def fixture_executor(
        request: Mapping[str, object], **kwargs: object
    ) -> dict[str, object]:
        requests.append(dict(request))
        return _identity_execution(request, **kwargs)

    result = execute_traditional_routing_synthetic_conformance(
        candidate_registration=registration,
        source_initialization_audit=_source_audit(registration),
        abi_audit=_abi_audit(registration),
        image_id=IMAGE_ID,
        adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
        read_only_mounts=mounts,
        serialized_zero_state={"step": 0},
        adapter_executor_for_testing=fixture_executor,
    )

    evidence = result["evidence"]
    provenance = evidence["execution_provenance"]
    report = result["conformance_report"]
    assert len(requests) == EXPECTED_EXECUTION_COUNT
    assert provenance["execution_count"] == EXPECTED_EXECUTION_COUNT == 56
    assert provenance["warmup_execution_count"] == EXPECTED_WARMUP_EXECUTION_COUNT == 9
    assert provenance["preexecution_audit_artifact_files_recomputed"] is False
    assert len(evidence["pulse_response_cases"]) == 27
    assert len(evidence["step_response_cases"]) == 3
    assert report["pulse_matrix_complete"] is True
    assert report["step_matrix_complete"] is True
    failed_gates = [name for name, passed in report["gates"].items() if not passed]
    assert failed_gates == [
        "no_observed_outcome_or_fitted_target_parameter_is_loaded"
    ]
    assert result["status"] == "test_fixture_evidence_generated_not_professional_execution"
    assert result["claim_boundary"]["professional_executor_used"] is False
    assert result["claim_boundary"]["professional_runtime_certified"] is False
    assert result["claim_boundary"]["matched_two_system_execution_permitted"] is False
    assert evidence["data_isolation"]["network_isolation_enforced"] is False

    prefix = next(
        request for request in requests if str(request["request_id"]).endswith("restart-prefix")
    )
    resumed = next(
        request for request in requests if str(request["request_id"]).endswith("restart-resumed")
    )
    assert resumed["serialized_initial_state"]["step"] == (
        prefix["serialized_initial_state"]["step"] + prefix["step_count"]
    )


def test_professional_execution_requires_real_audit_artifact_recomputation(
    tmp_path: Path,
) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)

    with pytest.raises(ValueError, match="audit_artifact_recomputation_required"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=_source_audit(registration),
            abi_audit=_abi_audit(registration),
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
        )


def test_registered_runtime_or_adapter_mount_tampering_blocks_all_execution(
    tmp_path: Path,
) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)
    mounts[0].source.write_bytes(b"tampered runtime")
    called = False

    def unexpected_executor(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("candidate must not execute")

    with pytest.raises(ValueError, match="artifact_mount_binding_invalid"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=_source_audit(registration),
            abi_audit=_abi_audit(registration),
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
            adapter_executor_for_testing=unexpected_executor,
        )
    assert called is False


def test_failed_registration_or_initialization_audit_blocks_execution(
    tmp_path: Path,
) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)
    source_audit = _source_audit(registration)
    abi_audit = _abi_audit(registration)
    registration["candidate_registration_ready"] = False
    with pytest.raises(ValueError, match="candidate_not_registered"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=source_audit,
            abi_audit=abi_audit,
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
            adapter_executor_for_testing=_identity_execution,
        )

    registration, mounts = _registration_and_mounts(tmp_path)
    findings = dict(SOURCE_AUDIT_REQUIREMENTS)
    findings["uninitialized_read_check_passed"] = False
    audit = _source_audit(registration, findings=findings)
    with pytest.raises(ValueError, match="preexecution_audit_invalid"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=audit,
            abi_audit=_abi_audit(registration),
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
            adapter_executor_for_testing=_identity_execution,
        )


def test_invalid_adapter_execution_receipt_fails_closed(tmp_path: Path) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)

    def invalid_executor(
        request: Mapping[str, object], **kwargs: object
    ) -> dict[str, object]:
        result = _identity_execution(request, **kwargs)
        result["command_policy"]["network_mode"] = "bridge"
        return result

    with pytest.raises(RuntimeError, match="execution_receipt_invalid"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=_source_audit(registration),
            abi_audit=_abi_audit(registration),
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
            adapter_executor_for_testing=invalid_executor,
        )


def test_execution_image_drift_from_registration_blocks_all_execution(
    tmp_path: Path,
) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)

    with pytest.raises(ValueError, match="artifact_mount_binding_invalid"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=_source_audit(registration),
            abi_audit=_abi_audit(registration),
            image_id="sha256:" + "5" * 64,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 0},
            adapter_executor_for_testing=_identity_execution,
        )


def test_zero_state_semantic_drift_blocks_all_execution(tmp_path: Path) -> None:
    registration, mounts = _registration_and_mounts(tmp_path)
    called = False

    def unexpected_executor(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("candidate must not execute")

    with pytest.raises(ValueError, match="zero_state_identity_mismatch"):
        execute_traditional_routing_synthetic_conformance(
            candidate_registration=registration,
            source_initialization_audit=_source_audit(registration),
            abi_audit=_abi_audit(registration),
            image_id=IMAGE_ID,
            adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
            read_only_mounts=mounts,
            serialized_zero_state={"step": 1},
            adapter_executor_for_testing=unexpected_executor,
        )
    assert called is False


def _registration_and_mounts(
    root: Path,
) -> tuple[dict[str, Any], tuple[DockerReadOnlyMount, ...]]:
    runtime = root / "runtime.bin"
    adapter = root / "adapter.py"
    zero_state = root / "zero_state.json"
    manifest = root / "manifest.json"
    source = root / "source.f90"
    license_path = root / "LICENSE"
    dependency_lock = root / "dependencies.lock"
    runtime.write_bytes(b"registered runtime\n")
    adapter.write_bytes(b"registered adapter\n")
    zero_state.write_bytes(b'{"step":0}\n')
    manifest.write_bytes(b'{"candidate":"fixture"}\n')
    source.write_bytes(b"subroutine route()\nend subroutine route\n")
    license_path.write_bytes(b"fixture license\n")
    dependency_lock.write_bytes(b"fixture dependency lock\n")
    artifacts = {
        "license": _artifact(root, license_path),
        "dependency_lock": _artifact(root, dependency_lock),
        "runtime": _artifact(root, runtime),
        "adapter_source": _artifact(root, adapter),
        "serialized_zero_state": {
            **_artifact(root, zero_state),
            "canonical_sha256": hashlib.sha256(b'{"step":0}').hexdigest(),
        },
    }
    registration = {
        "candidate_id": "fixture-independent-mc",
        "candidate_registration_ready": True,
        "manifest_artifact": _manifest_artifact(root, manifest),
        "source_artifacts": [_artifact(root, source)],
        "gates": {
            "frozen_protocol_identity_valid": True,
            "all_artifact_identities_match": True,
        },
        "artifacts": artifacts,
        "protocol": {
            "sha256": EXPECTED_PROTOCOL_FILE_SHA256,
            "protocol_seal_sha256": EXPECTED_PROTOCOL_SEAL_SHA256,
        },
        "execution_binding": {
            "backend": "docker_network_none_v1",
            "image_id": IMAGE_ID,
            "container_platform": {"system": "Linux", "machine": "arm64"},
            "adapter_command": ["python", "/opt/gwm-candidate/adapter.py"],
            "read_only_mount_targets": {
                "runtime": "/opt/gwm-candidate/runtime.bin",
                "adapter_source": "/opt/gwm-candidate/adapter.py",
            },
            "network_mode": "none",
            "identity_matches": True,
        },
    }
    mounts = (
        DockerReadOnlyMount(runtime, "/opt/gwm-candidate/runtime.bin"),
        DockerReadOnlyMount(adapter, "/opt/gwm-candidate/adapter.py"),
    )
    return registration, mounts


def _artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "declared_sha256": hashlib.sha256(body).hexdigest(),
        "declared_size_bytes": len(body),
        "actual_sha256": hashlib.sha256(body).hexdigest(),
        "actual_size_bytes": len(body),
        "identity_matches": True,
    }


def _manifest_artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _source_audit(
    registration: Mapping[str, object],
    *,
    findings: Mapping[str, object] = SOURCE_AUDIT_REQUIREMENTS,
) -> dict[str, object]:
    return _audit(registration, audit_kind=SOURCE_AUDIT_KIND, findings=findings)


def _abi_audit(registration: Mapping[str, object]) -> dict[str, object]:
    return _audit(
        registration,
        audit_kind=ABI_AUDIT_KIND,
        findings=ABI_AUDIT_REQUIREMENTS,
    )


def _audit(
    registration: Mapping[str, object],
    *,
    audit_kind: str,
    findings: Mapping[str, object],
) -> dict[str, object]:
    return build_traditional_routing_preexecution_audit(
        audit_kind=audit_kind,
        candidate_registration=registration,
        findings=findings,
        auditor_identity={
            "name": "fixture-auditor",
            "version": "1.0",
            "implementation_artifact": _audit_artifact("fixture/auditor.py", "8"),
        },
        supporting_evidence_artifacts=(
            _audit_artifact(f"fixture/{audit_kind}.json", "9"),
        ),
    )


def _audit_artifact(path: str, digit: str) -> dict[str, object]:
    return {
        "path": path,
        "sha256": digit * 64,
        "size_bytes": 17,
        "identity_matches": True,
    }


def _identity_execution(
    request: Mapping[str, object], **kwargs: object
) -> dict[str, object]:
    feature_ids = list(request["feature_ids"])
    downstream = list(request["downstream_feature_ids"])
    boundary = np.asarray(request["boundary_inflow_m3s"], dtype=float)
    lateral = np.asarray(request["lateral_inflow_m3s"], dtype=float)
    routed = boundary + lateral
    index = {feature_id: offset for offset, feature_id in enumerate(feature_ids)}
    indegree = [0] * len(feature_ids)
    for target in downstream:
        if target is not None:
            indegree[index[target]] += 1
    ready = [offset for offset, degree in enumerate(indegree) if degree == 0]
    while ready:
        source = ready.pop(0)
        target = downstream[source]
        if target is not None:
            target_index = index[target]
            routed[:, target_index] += routed[:, source]
            indegree[target_index] -= 1
            if indegree[target_index] == 0:
                ready.append(target_index)
    initial = dict(request["serialized_initial_state"])
    final = dict(initial)
    final["step"] = int(initial.get("step", 0)) + int(request["step_count"])
    response = {
        "schema": TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
        "adapter_protocol": TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
        "request_id": request["request_id"],
        "request_sha256": request["request_seal"]["sha256"],
        "routed_discharge_m3s": routed.tolist(),
        "total_storage_m3": np.zeros(len(boundary) + 1).tolist(),
        "serialized_final_state": final,
    }
    trace = validate_traditional_routing_adapter_response(request, response)
    image_id = kwargs["image_id"]
    return {
        "schema": TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA,
        "status": "adapter_response_transport_validated",
        "validated_trace": trace,
        "command_policy": {
            "network_mode": "none",
            "root_filesystem_read_only": True,
            "host_environment_forwarded": False,
        },
        "execution_receipt": {
            "requested_image_id": image_id,
            "image_identity_matched_before_execution": True,
            "image_platform": {"system": "Linux", "machine": "arm64"},
            "response_validated_after_container_exit": True,
            "container_id": "e" * 64,
        },
        "claim_boundary": {
            "transport_isolation_validated": True,
            "professional_runtime_certified": False,
            "runtime_admitted": False,
        },
    }
