from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_preexecution_audit import (
    ABI_AUDIT_KIND,
    ABI_AUDIT_REQUIREMENTS,
    EXPECTED_PROTOCOL_FILE_SHA256,
    EXPECTED_PROTOCOL_SEAL_SHA256,
    SOURCE_AUDIT_KIND,
    SOURCE_AUDIT_REQUIREMENTS,
    build_traditional_routing_preexecution_audit,
    validate_traditional_routing_preexecution_audit,
)


def test_source_and_abi_audits_are_sealed_to_candidate_execution_identity() -> None:
    registration = _registration()
    source = _audit(registration, SOURCE_AUDIT_KIND, SOURCE_AUDIT_REQUIREMENTS)
    abi = _audit(registration, ABI_AUDIT_KIND, ABI_AUDIT_REQUIREMENTS)

    source_result = validate_traditional_routing_preexecution_audit(
        registration,
        source,
        expected_audit_kind=SOURCE_AUDIT_KIND,
    )
    abi_result = validate_traditional_routing_preexecution_audit(
        registration,
        abi,
        expected_audit_kind=ABI_AUDIT_KIND,
    )

    assert source_result["findings"] == SOURCE_AUDIT_REQUIREMENTS
    assert abi_result["findings"] == ABI_AUDIT_REQUIREMENTS
    assert len(source_result["receipt"]["audit_seal_sha256"]) == 64
    assert source_result["receipt"]["candidate_binding_sha256"] == abi_result[
        "receipt"
    ]["candidate_binding_sha256"]
    assert source["claim_boundary"]["candidate_runtime_invoked"] is False
    assert abi["claim_boundary"]["candidate_runtime_invoked"] is True
    assert abi["claim_boundary"]["network_isolation_enforced"] is True
    assert source_result["receipt"]["artifact_file_identities_recomputed"] is False


def test_audit_artifact_files_are_recomputed_and_tampering_is_rejected(
    tmp_path: Path,
) -> None:
    registration = _registration()
    tool = tmp_path / "audit/tool.py"
    evidence = tmp_path / "audit/source-evidence.json"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"fixture audit tool\n")
    evidence.write_bytes(b'{"initialized":true}\n')
    audit = build_traditional_routing_preexecution_audit(
        audit_kind=SOURCE_AUDIT_KIND,
        candidate_registration=registration,
        findings=SOURCE_AUDIT_REQUIREMENTS,
        auditor_identity={
            "name": "fixture-auditor",
            "version": "1.0",
            "implementation_artifact": _file_artifact(tmp_path, tool),
        },
        supporting_evidence_artifacts=(_file_artifact(tmp_path, evidence),),
    )

    result = validate_traditional_routing_preexecution_audit(
        registration,
        audit,
        expected_audit_kind=SOURCE_AUDIT_KIND,
        artifact_root=tmp_path,
    )
    assert result["receipt"]["artifact_file_identities_recomputed"] is True
    assert result["receipt"]["recomputed_artifact_count"] == 2

    evidence.write_bytes(b'{"initialized":false}\n')
    with pytest.raises(ValueError, match="audit_artifact_identity_mismatch"):
        validate_traditional_routing_preexecution_audit(
            registration,
            audit,
            expected_audit_kind=SOURCE_AUDIT_KIND,
            artifact_root=tmp_path,
        )


def test_audit_artifact_recomputation_rejects_repository_escape(
    tmp_path: Path,
) -> None:
    registration = _registration()
    audit = build_traditional_routing_preexecution_audit(
        audit_kind=SOURCE_AUDIT_KIND,
        candidate_registration=registration,
        findings=SOURCE_AUDIT_REQUIREMENTS,
        auditor_identity={
            "name": "fixture-auditor",
            "version": "1.0",
            "implementation_artifact": _artifact("../outside/tool.py", "7"),
        },
        supporting_evidence_artifacts=(_artifact("audit/evidence.json", "8"),),
    )

    with pytest.raises(ValueError, match="audit_artifact_outside_repository"):
        validate_traditional_routing_preexecution_audit(
            registration,
            audit,
            expected_audit_kind=SOURCE_AUDIT_KIND,
            artifact_root=tmp_path,
        )


def test_post_audit_finding_tampering_is_rejected() -> None:
    registration = _registration()
    audit = _audit(registration, SOURCE_AUDIT_KIND, SOURCE_AUDIT_REQUIREMENTS)
    audit["findings"]["uninitialized_read_check_passed"] = False

    with pytest.raises(ValueError, match="preexecution_audit_invalid"):
        validate_traditional_routing_preexecution_audit(
            registration,
            audit,
            expected_audit_kind=SOURCE_AUDIT_KIND,
        )


def test_candidate_image_or_protocol_drift_invalidates_existing_audit() -> None:
    registration = _registration()
    audit = _audit(registration, ABI_AUDIT_KIND, ABI_AUDIT_REQUIREMENTS)

    changed = deepcopy(registration)
    changed["execution_binding"]["image_id"] = "sha256:" + "5" * 64
    with pytest.raises(ValueError, match="preexecution_audit_invalid"):
        validate_traditional_routing_preexecution_audit(
            changed,
            audit,
            expected_audit_kind=ABI_AUDIT_KIND,
        )

    changed = deepcopy(registration)
    changed["protocol"]["protocol_seal_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="candidate_binding_invalid"):
        validate_traditional_routing_preexecution_audit(
            changed,
            audit,
            expected_audit_kind=ABI_AUDIT_KIND,
        )

    changed = deepcopy(registration)
    changed["artifacts"]["serialized_zero_state"]["canonical_sha256"] = "6" * 64
    with pytest.raises(ValueError, match="preexecution_audit_invalid"):
        validate_traditional_routing_preexecution_audit(
            changed,
            audit,
            expected_audit_kind=ABI_AUDIT_KIND,
        )

    for changed in (
        _changed_registration(registration, "manifest"),
        _changed_registration(registration, "source"),
        _changed_registration(registration, "license"),
        _changed_registration(registration, "dependency_lock"),
    ):
        with pytest.raises(ValueError, match="preexecution_audit_invalid"):
            validate_traditional_routing_preexecution_audit(
                changed,
                audit,
                expected_audit_kind=ABI_AUDIT_KIND,
            )


def test_unverified_auditor_or_forbidden_outcome_evidence_cannot_be_sealed() -> None:
    registration = _registration()
    auditor = _artifact("audit/tool.py", "7")
    auditor["identity_matches"] = False
    with pytest.raises(ValueError, match="audit_artifact_invalid"):
        build_traditional_routing_preexecution_audit(
            audit_kind=SOURCE_AUDIT_KIND,
            candidate_registration=registration,
            findings=SOURCE_AUDIT_REQUIREMENTS,
            auditor_identity={
                "name": "fixture-auditor",
                "version": "1.0",
                "implementation_artifact": auditor,
            },
            supporting_evidence_artifacts=(_artifact("audit/evidence.json", "8"),),
        )

    with pytest.raises(ValueError, match="forbidden_content"):
        build_traditional_routing_preexecution_audit(
            audit_kind=SOURCE_AUDIT_KIND,
            candidate_registration=registration,
            findings=SOURCE_AUDIT_REQUIREMENTS,
            auditor_identity={
                "name": "fixture-auditor",
                "version": "1.0",
                "implementation_artifact": _artifact("audit/tool.py", "7"),
            },
            supporting_evidence_artifacts=(
                _artifact("audit/outcome_values", "8"),
            ),
        )


def _audit(
    registration: dict[str, object],
    audit_kind: str,
    findings: dict[str, bool],
) -> dict[str, object]:
    return build_traditional_routing_preexecution_audit(
        audit_kind=audit_kind,
        candidate_registration=registration,
        findings=findings,
        auditor_identity={
            "name": "fixture-auditor",
            "version": "1.0",
            "implementation_artifact": _artifact("audit/tool.py", "7"),
        },
        supporting_evidence_artifacts=(_artifact("audit/evidence.json", "8"),),
    )


def _registration() -> dict[str, object]:
    return {
        "candidate_id": "fixture-independent-mc",
        "candidate_registration_ready": True,
        "manifest_artifact": {
            "path": "candidate/manifest.json",
            "sha256": "a" * 64,
            "size_bytes": 23,
        },
        "source_artifacts": [
            _registered_artifact("candidate/source.f90", "b"),
        ],
        "protocol": {
            "sha256": EXPECTED_PROTOCOL_FILE_SHA256,
            "protocol_seal_sha256": EXPECTED_PROTOCOL_SEAL_SHA256,
        },
        "artifacts": {
            "license": _registered_artifact("candidate/LICENSE", "c"),
            "dependency_lock": _registered_artifact(
                "candidate/dependencies.lock", "d"
            ),
            "runtime": _registered_artifact("candidate/runtime.bin", "1"),
            "adapter_source": _registered_artifact("candidate/adapter.py", "2"),
            "serialized_zero_state": {
                **_registered_artifact("candidate/zero_state.json", "3"),
                "canonical_sha256": "4" * 64,
            },
        },
        "execution_binding": {
            "backend": "docker_network_none_v1",
            "image_id": "sha256:" + "4" * 64,
            "container_platform": {"system": "Linux", "machine": "arm64"},
            "adapter_command": ["python", "/opt/gwm-candidate/adapter.py"],
            "network_mode": "none",
            "identity_matches": True,
        },
    }


def _changed_registration(
    registration: dict[str, object], artifact: str
) -> dict[str, object]:
    changed = deepcopy(registration)
    if artifact == "manifest":
        changed["manifest_artifact"]["sha256"] = "e" * 64
    elif artifact == "source":
        changed["source_artifacts"][0]["actual_sha256"] = "e" * 64
    else:
        changed["artifacts"][artifact]["actual_sha256"] = "e" * 64
    return changed


def _registered_artifact(path: str, digit: str) -> dict[str, object]:
    return {
        "path": path,
        "actual_sha256": digit * 64,
        "actual_size_bytes": 17,
        "identity_matches": True,
    }


def _artifact(path: str, digit: str) -> dict[str, object]:
    return {
        "path": path,
        "sha256": digit * 64,
        "size_bytes": 17,
        "identity_matches": True,
    }


def _file_artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "identity_matches": True,
    }
