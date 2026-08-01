#!/usr/bin/env python3
"""Run the frozen outcome-free routing conformance suite for one candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_conformance_execution import (
    execute_traditional_routing_synthetic_conformance,
)
from data_agent.uwm.geospatial_kernel_v2.traditional_routing_docker_executor import (
    DockerReadOnlyMount,
)

if __package__:
    from scripts.assess_geospatial_kernel_traditional_routing_candidate_inventory import (
        PROTOCOL_PATH,
        REPO_ROOT,
        assess_candidate_manifest,
    )
else:
    from assess_geospatial_kernel_traditional_routing_candidate_inventory import (
        PROTOCOL_PATH,
        REPO_ROOT,
        assess_candidate_manifest,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--source-initialization-audit", type=Path, required=True)
    parser.add_argument("--abi-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def run_registered_candidate_synthetic_conformance(
    *,
    candidate_manifest_path: Path,
    source_initialization_audit_path: Path,
    abi_audit_path: Path,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    """Resolve sealed candidate artifacts and execute only synthetic cases."""

    root = Path(repo_root).resolve()
    manifest_path = _inside_root(root, candidate_manifest_path)
    source_audit_path = _inside_root(root, source_initialization_audit_path)
    adapter_audit_path = _inside_root(root, abi_audit_path)
    registration = assess_candidate_manifest(
        manifest_path,
        repo_root=root,
        protocol_path=protocol_path,
    )
    if registration.get("candidate_registration_ready") is not True:
        raise ValueError("traditional_routing_conformance_candidate_not_registered")

    artifacts = _mapping(registration.get("artifacts"))
    execution = _mapping(registration.get("execution_binding"))
    targets = _mapping(execution.get("read_only_mount_targets"))
    runtime = _mapping(artifacts.get("runtime"))
    adapter = _mapping(artifacts.get("adapter_source"))
    zero_state_artifact = _mapping(artifacts.get("serialized_zero_state"))
    mounts = (
        DockerReadOnlyMount(
            source=_artifact_path(root, runtime),
            target=_required_string(targets.get("runtime")),
        ),
        DockerReadOnlyMount(
            source=_artifact_path(root, adapter),
            target=_required_string(targets.get("adapter_source")),
        ),
    )
    zero_state_path = _artifact_path(root, zero_state_artifact)
    zero_state = _read_strict_json_object(zero_state_path)
    if _sha256_json(zero_state) != zero_state_artifact.get("canonical_sha256"):
        raise ValueError("traditional_routing_conformance_zero_state_identity_mismatch")

    command = execution.get("adapter_command")
    if not isinstance(command, list) or not command:
        raise ValueError("traditional_routing_conformance_candidate_not_registered")
    return execute_traditional_routing_synthetic_conformance(
        candidate_registration=registration,
        source_initialization_audit=_read_strict_json_object(source_audit_path),
        abi_audit=_read_strict_json_object(adapter_audit_path),
        image_id=_required_string(execution.get("image_id")),
        adapter_command=tuple(_required_string(value) for value in command),
        read_only_mounts=mounts,
        serialized_zero_state=zero_state,
        preexecution_audit_artifact_root=root,
    )


def write_execution_report_exclusive(
    result: Mapping[str, object], *, output_path: Path, repo_root: Path = REPO_ROOT
) -> Path:
    """Write one immutable adjudication artifact without replacing prior evidence."""

    root = Path(repo_root).resolve()
    path = _inside_root(root, output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps(
            dict(result),
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(body)
    except FileExistsError as error:
        raise ValueError(
            "traditional_routing_conformance_output_already_exists"
        ) from error
    return path


def _artifact_path(root: Path, descriptor: Mapping[str, object]) -> Path:
    if descriptor.get("identity_matches") is not True:
        raise ValueError("traditional_routing_conformance_candidate_not_registered")
    path = _inside_root(root, Path(_required_string(descriptor.get("path"))))
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("actual_sha256")
        or len(body) != descriptor.get("actual_size_bytes")
    ):
        raise ValueError("traditional_routing_conformance_artifact_identity_mismatch")
    return path


def _read_strict_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("traditional_routing_conformance_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"traditional_routing_conformance_json_nonfinite:{value}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("traditional_routing_conformance_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("traditional_routing_conformance_json_root_not_object")
    return payload


def _inside_root(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "traditional_routing_conformance_artifact_outside_repository"
        ) from error
    return resolved


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("traditional_routing_conformance_candidate_not_registered")
    return value


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sha256_json(value: Mapping[str, object]) -> str:
    body = json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def main() -> int:
    args = parse_args()
    result = run_registered_candidate_synthetic_conformance(
        candidate_manifest_path=args.candidate_manifest,
        source_initialization_audit_path=args.source_initialization_audit,
        abi_audit_path=args.abi_audit,
    )
    output = write_execution_report_exclusive(result, output_path=args.output)
    print(output)
    print(f"status={result['status']}")
    certified = result.get("claim_boundary", {}).get(
        "professional_runtime_certified"
    )
    print(f"professional_runtime_certified={certified}")
    return 0 if certified is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
