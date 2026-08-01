"""Sealed pre-execution audits for traditional-routing candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SOURCE_INITIALIZATION_AUDIT_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_source_initialization_audit.v1"
)
ABI_AUDIT_SCHEMA = "gwm.geospatial_kernel.traditional_routing_abi_audit.v1"
SOURCE_AUDIT_KIND = "source_initialization"
ABI_AUDIT_KIND = "adapter_abi"
EXPECTED_PROTOCOL_FILE_SHA256 = (
    "b674db451955d656f31719434a8aa0ac4f29525cc12acd553d594332e5dee744"
)
EXPECTED_PROTOCOL_SEAL_SHA256 = (
    "5a5031c95d245fcdd628d967fd0fd8f5a5ae7208c8236dee65511d46abb6a899"
)
SOURCE_AUDIT_REQUIREMENTS = {
    "all_reads_dominated_by_assignment": True,
    "uninitialized_read_check_passed": True,
    "all_restart_state_variables_documented": True,
}
ABI_AUDIT_REQUIREMENTS = {
    "signature_matches_registered_adapter": True,
    "input_arrays_remain_read_only": True,
    "feature_and_time_axes_preserved": True,
}
_AUDIT_KEYS = {
    "schema",
    "audit_kind",
    "candidate_binding",
    "findings",
    "auditor_identity",
    "supporting_evidence_artifacts",
    "claim_boundary",
    "audit_seal",
}
_FORBIDDEN_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "score_report",
    "future_target_observations",
}


def build_traditional_routing_preexecution_audit(
    *,
    audit_kind: str,
    candidate_registration: Mapping[str, object],
    findings: Mapping[str, object],
    auditor_identity: Mapping[str, object],
    supporting_evidence_artifacts: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Build a sealed audit envelope bound to one registered execution identity."""

    schema, requirements, claim = _audit_contract(audit_kind)
    findings_payload = dict(findings)
    if set(findings_payload) != set(requirements):
        raise ValueError("traditional_routing_preexecution_audit_findings_invalid")
    auditor = _auditor_identity(auditor_identity)
    evidence = [_artifact_identity(item) for item in supporting_evidence_artifacts]
    if not evidence:
        raise ValueError("traditional_routing_preexecution_audit_evidence_required")
    payload = {
        "schema": schema,
        "audit_kind": audit_kind,
        "candidate_binding": _candidate_binding(candidate_registration),
        "findings": findings_payload,
        "auditor_identity": auditor,
        "supporting_evidence_artifacts": evidence,
        "claim_boundary": claim,
    }
    if _find_forbidden_keys(payload):
        raise ValueError("traditional_routing_preexecution_audit_forbidden_content")
    payload["audit_seal"] = {
        "algorithm": "sha256_canonical_json_without_audit_seal",
        "sha256": _sha256_json(payload),
    }
    return payload


def validate_traditional_routing_preexecution_audit(
    candidate_registration: Mapping[str, object],
    audit: Mapping[str, object],
    *,
    expected_audit_kind: str,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate an audit seal and return only bound findings plus a receipt."""

    schema, requirements, claim = _audit_contract(expected_audit_kind)
    payload = dict(audit)
    seal = payload.pop("audit_seal", None)
    valid_seal = (
        isinstance(seal, dict)
        and seal.get("algorithm") == "sha256_canonical_json_without_audit_seal"
        and seal.get("sha256") == _sha256_json(payload)
    )
    findings = payload.get("findings")
    auditor = payload.get("auditor_identity")
    evidence = payload.get("supporting_evidence_artifacts")
    valid = (
        set(audit) == _AUDIT_KEYS
        and payload.get("schema") == schema
        and payload.get("audit_kind") == expected_audit_kind
        and payload.get("candidate_binding") == _candidate_binding(candidate_registration)
        and isinstance(findings, dict)
        and findings == requirements
        and isinstance(auditor, dict)
        and auditor == _auditor_identity(auditor)
        and isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, dict) and item == _artifact_identity(item)
            for item in evidence
        )
        and payload.get("claim_boundary") == claim
        and not _find_forbidden_keys(audit)
        and valid_seal
    )
    if not valid:
        raise ValueError("traditional_routing_preexecution_audit_invalid")
    artifact_recomputation = _recompute_audit_artifact_identities(
        auditor,
        evidence,
        artifact_root=artifact_root,
    )
    return {
        "findings": dict(findings),
        "receipt": {
            "audit_kind": expected_audit_kind,
            "audit_seal_sha256": seal["sha256"],
            "candidate_binding_sha256": _sha256_json(
                payload["candidate_binding"]
            ),
            "auditor_implementation_sha256": auditor["implementation_artifact"][
                "sha256"
            ],
            "supporting_evidence_sha256": [item["sha256"] for item in evidence],
            **artifact_recomputation,
        },
    }


def _recompute_audit_artifact_identities(
    auditor: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    *,
    artifact_root: Path | None,
) -> dict[str, object]:
    if artifact_root is None:
        return {
            "artifact_file_identities_recomputed": False,
            "recomputed_artifact_count": 0,
        }
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        raise ValueError("traditional_routing_preexecution_audit_artifact_root_invalid")
    descriptors = [
        _mapping(auditor.get("implementation_artifact")),
        *[_mapping(item) for item in evidence],
    ]
    recomputed = [
        _recompute_audit_artifact_identity(root, descriptor)
        for descriptor in descriptors
    ]
    return {
        "artifact_file_identities_recomputed": True,
        "recomputed_artifact_count": len(recomputed),
        "recomputed_artifact_sha256": [item["sha256"] for item in recomputed],
    }


def _recompute_audit_artifact_identity(
    root: Path, descriptor: Mapping[str, object]
) -> dict[str, object]:
    declared_path = descriptor.get("path")
    if not isinstance(declared_path, str) or not declared_path:
        raise ValueError("traditional_routing_preexecution_audit_artifact_invalid")
    relative = Path(declared_path)
    if relative.is_absolute():
        raise ValueError(
            "traditional_routing_preexecution_audit_artifact_outside_repository"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "traditional_routing_preexecution_audit_artifact_outside_repository"
        ) from error
    try:
        body = path.read_bytes()
    except OSError as error:
        raise ValueError(
            "traditional_routing_preexecution_audit_artifact_identity_mismatch"
        ) from error
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != descriptor.get("sha256") or len(body) != descriptor.get("size_bytes"):
        raise ValueError(
            "traditional_routing_preexecution_audit_artifact_identity_mismatch"
        )
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256,
        "size_bytes": len(body),
    }


def _audit_contract(
    audit_kind: str,
) -> tuple[str, dict[str, bool], dict[str, object]]:
    common_claim = {
        "synthetic_inputs_only": True,
        "outcome_values_loaded": False,
        "real_two_system_inputs_loaded": False,
        "score_report_loaded": False,
        "target_parameters_fitted": 0,
    }
    if audit_kind == SOURCE_AUDIT_KIND:
        return (
            SOURCE_INITIALIZATION_AUDIT_SCHEMA,
            dict(SOURCE_AUDIT_REQUIREMENTS),
            {
                **common_claim,
                "candidate_runtime_invoked": False,
                "network_isolation_enforced": False,
            },
        )
    if audit_kind == ABI_AUDIT_KIND:
        return (
            ABI_AUDIT_SCHEMA,
            dict(ABI_AUDIT_REQUIREMENTS),
            {
                **common_claim,
                "candidate_runtime_invoked": True,
                "network_isolation_enforced": True,
            },
        )
    raise ValueError("traditional_routing_preexecution_audit_kind_invalid")


def _candidate_binding(registration: Mapping[str, object]) -> dict[str, object]:
    protocol = _mapping(registration.get("protocol"))
    manifest = _mapping(registration.get("manifest_artifact"))
    source_value = registration.get("source_artifacts")
    sources = (
        [_mapping(item) for item in source_value]
        if isinstance(source_value, list)
        else []
    )
    artifacts = _mapping(registration.get("artifacts"))
    license_artifact = _mapping(artifacts.get("license"))
    dependency_lock = _mapping(artifacts.get("dependency_lock"))
    runtime = _mapping(artifacts.get("runtime"))
    adapter = _mapping(artifacts.get("adapter_source"))
    zero_state = _mapping(artifacts.get("serialized_zero_state"))
    execution = _mapping(registration.get("execution_binding"))
    candidate_id = registration.get("candidate_id")
    command = execution.get("adapter_command")
    platform = execution.get("container_platform")
    valid = (
        registration.get("candidate_registration_ready") is True
        and isinstance(candidate_id, str)
        and bool(candidate_id.strip())
        and protocol.get("sha256") == EXPECTED_PROTOCOL_FILE_SHA256
        and protocol.get("protocol_seal_sha256") == EXPECTED_PROTOCOL_SEAL_SHA256
        and _manifest_artifact(manifest)
        and bool(sources)
        and all(_registered_artifact(source) for source in sources)
        and _registered_artifact(license_artifact)
        and _registered_artifact(dependency_lock)
        and _registered_artifact(runtime)
        and _registered_artifact(adapter)
        and _registered_artifact(zero_state)
        and _sha256(zero_state.get("canonical_sha256"))
        and execution.get("identity_matches") is True
        and execution.get("backend") == "docker_network_none_v1"
        and execution.get("network_mode") == "none"
        and isinstance(execution.get("image_id"), str)
        and isinstance(command, list)
        and bool(command)
        and isinstance(platform, dict)
    )
    if not valid:
        raise ValueError("traditional_routing_preexecution_candidate_binding_invalid")
    return {
        "candidate_id": candidate_id,
        "protocol_file_sha256": protocol["sha256"],
        "protocol_seal_sha256": protocol["protocol_seal_sha256"],
        "candidate_manifest_sha256": manifest["sha256"],
        "candidate_manifest_size_bytes": manifest["size_bytes"],
        "source_artifacts": [_bound_registered_artifact(source) for source in sources],
        "license_sha256": license_artifact["actual_sha256"],
        "license_size_bytes": license_artifact["actual_size_bytes"],
        "dependency_lock_sha256": dependency_lock["actual_sha256"],
        "dependency_lock_size_bytes": dependency_lock["actual_size_bytes"],
        "runtime_sha256": runtime["actual_sha256"],
        "runtime_size_bytes": runtime["actual_size_bytes"],
        "adapter_source_sha256": adapter["actual_sha256"],
        "adapter_source_size_bytes": adapter["actual_size_bytes"],
        "serialized_zero_state_sha256": zero_state["actual_sha256"],
        "serialized_zero_state_size_bytes": zero_state["actual_size_bytes"],
        "serialized_zero_state_canonical_sha256": zero_state["canonical_sha256"],
        "docker_image_id": execution["image_id"],
        "container_platform": dict(platform),
        "adapter_command_sha256": hashlib.sha256(
            _canonical_json(command)
        ).hexdigest(),
    }


def _manifest_artifact(value: Mapping[str, object]) -> bool:
    return (
        isinstance(value.get("path"), str)
        and bool(str(value["path"]).strip())
        and _sha256(value.get("sha256"))
        and isinstance(value.get("size_bytes"), int)
        and not isinstance(value.get("size_bytes"), bool)
        and int(value["size_bytes"]) > 0
    )


def _registered_artifact(value: Mapping[str, object]) -> bool:
    return (
        value.get("identity_matches") is True
        and _sha256(value.get("actual_sha256"))
        and isinstance(value.get("actual_size_bytes"), int)
        and not isinstance(value.get("actual_size_bytes"), bool)
        and int(value["actual_size_bytes"]) > 0
    )


def _bound_registered_artifact(value: Mapping[str, object]) -> dict[str, object]:
    if not _registered_artifact(value):
        raise ValueError("traditional_routing_preexecution_candidate_binding_invalid")
    return {
        "sha256": value["actual_sha256"],
        "size_bytes": value["actual_size_bytes"],
    }


def _auditor_identity(value: Mapping[str, object]) -> dict[str, object]:
    name = value.get("name")
    version = value.get("version")
    artifact = value.get("implementation_artifact")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(version, str)
        or not version.strip()
        or not isinstance(artifact, Mapping)
    ):
        raise ValueError("traditional_routing_preexecution_auditor_identity_invalid")
    return {
        "name": name,
        "version": version,
        "implementation_artifact": _artifact_identity(artifact),
    }


def _artifact_identity(value: Mapping[str, object]) -> dict[str, object]:
    path = value.get("path")
    sha256 = value.get("sha256", value.get("actual_sha256"))
    size = value.get("size_bytes", value.get("actual_size_bytes"))
    identity_matches = value.get("identity_matches")
    if (
        not isinstance(path, str)
        or not path.strip()
        or not _sha256(sha256)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or identity_matches is not True
    ):
        raise ValueError("traditional_routing_preexecution_audit_artifact_invalid")
    return {
        "path": path,
        "sha256": sha256,
        "size_bytes": size,
        "identity_matches": True,
    }


def _find_forbidden_keys(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in _FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        folded = value.casefold()
        if any(key in folded for key in _FORBIDDEN_KEYS):
            found.append(path)
    return found


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
