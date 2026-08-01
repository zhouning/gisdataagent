from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_preexecution_audit import (
    ABI_AUDIT_KIND,
    ABI_AUDIT_REQUIREMENTS,
    SOURCE_AUDIT_KIND,
    SOURCE_AUDIT_REQUIREMENTS,
    build_traditional_routing_preexecution_audit,
)
from scripts import assess_geospatial_kernel_traditional_routing_candidate_inventory as assess
from scripts import run_geospatial_kernel_traditional_routing_synthetic_conformance as run


def test_runner_resolves_only_registered_artifacts_and_synthetic_zero_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, protocol = _candidate_fixture(tmp_path)
    registration = assess.assess_candidate_manifest(
        manifest, repo_root=tmp_path, protocol_path=protocol
    )
    source_audit = tmp_path / "candidate/source_audit.json"
    abi_audit = tmp_path / "candidate/abi_audit.json"
    _write_json(source_audit, _audit(registration, SOURCE_AUDIT_KIND))
    _write_json(abi_audit, _audit(registration, ABI_AUDIT_KIND))
    captured: dict[str, object] = {}

    def fixture_execution(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "fixture-complete",
            "claim_boundary": {"professional_runtime_certified": False},
        }

    monkeypatch.setattr(
        run, "execute_traditional_routing_synthetic_conformance", fixture_execution
    )
    result = run.run_registered_candidate_synthetic_conformance(
        candidate_manifest_path=manifest,
        source_initialization_audit_path=source_audit,
        abi_audit_path=abi_audit,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert result["status"] == "fixture-complete"
    assert set(captured) == {
        "candidate_registration",
        "source_initialization_audit",
        "abi_audit",
        "image_id",
        "adapter_command",
        "read_only_mounts",
        "serialized_zero_state",
        "preexecution_audit_artifact_root",
    }
    assert captured["serialized_zero_state"] == {"step": 0}
    assert captured["image_id"] == "sha256:" + "1" * 64
    assert captured["adapter_command"] == (
        "python",
        "/opt/gwm-candidate/adapter.py",
    )
    assert captured["preexecution_audit_artifact_root"] == tmp_path.resolve()
    assert [mount.target for mount in captured["read_only_mounts"]] == [
        "/opt/gwm-candidate/runtime.bin",
        "/opt/gwm-candidate/adapter.py",
    ]


def test_runner_blocks_zero_state_tampering_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, protocol = _candidate_fixture(tmp_path)
    registration = assess.assess_candidate_manifest(
        manifest, repo_root=tmp_path, protocol_path=protocol
    )
    source_audit = tmp_path / "candidate/source_audit.json"
    abi_audit = tmp_path / "candidate/abi_audit.json"
    _write_json(source_audit, _audit(registration, SOURCE_AUDIT_KIND))
    _write_json(abi_audit, _audit(registration, ABI_AUDIT_KIND))
    zero_state = tmp_path / "candidate/zero_state.json"
    _write_json(zero_state, {"step": 1})
    called = False

    def unexpected_execution(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("candidate must not execute")

    monkeypatch.setattr(
        run, "execute_traditional_routing_synthetic_conformance", unexpected_execution
    )
    with pytest.raises(ValueError, match="candidate_not_registered"):
        run.run_registered_candidate_synthetic_conformance(
            candidate_manifest_path=manifest,
            source_initialization_audit_path=source_audit,
            abi_audit_path=abi_audit,
            repo_root=tmp_path,
            protocol_path=protocol,
        )
    assert called is False


def test_execution_report_is_exclusive_and_cannot_replace_prior_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports/result.json"
    result = {
        "status": "blocked_traditional_routing_conformance_failure",
        "claim_boundary": {"professional_runtime_certified": False},
    }

    written = run.write_execution_report_exclusive(
        result, output_path=output, repo_root=tmp_path
    )
    assert json.loads(written.read_text(encoding="utf-8")) == result
    with pytest.raises(ValueError, match="output_already_exists"):
        run.write_execution_report_exclusive(
            result, output_path=output, repo_root=tmp_path
        )


def _candidate_fixture(root: Path) -> tuple[Path, Path]:
    protocol = root / "protocol.json"
    protocol.write_bytes(assess.PROTOCOL_PATH.read_bytes())
    artifact_bodies = {
        "source/mc.f90": b"subroutine route()\nend subroutine route\n",
        "LICENSE": b"Apache License 2.0 fixture\n",
        "dependencies.lock": b"compiler=fixture-1.0\n",
        "runtime.bin": b"fixture-binary\n",
        "adapter.py": b"def route(inputs): return inputs\n",
        "zero_state.json": b'{"step":0}\n',
    }
    paths: dict[str, Path] = {}
    for name, body in artifact_bodies.items():
        path = root / "candidate" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        paths[name] = path
    manifest = root / "candidate/manifest.json"
    _write_json(
        manifest,
        {
            "schema": assess.MANIFEST_SCHEMA,
            "candidate_id": "fixture-mc-v1",
            "method_family": "muskingum_cunge",
            "implementation_identity": {
                "upstream_project": "fixture-independent-routing",
                "repository": "https://example.invalid/fixture-independent-routing",
                "immutable_revision": "a" * 40,
                "release_or_version": "v1.0.0",
                "source_artifacts": [_descriptor(root, paths["source/mc.f90"])],
            },
            "license": {
                "spdx_identifier": "Apache-2.0",
                "artifact": _descriptor(root, paths["LICENSE"]),
                "benchmark_use_permitted": True,
                "redistribution_permitted": True,
            },
            "build": {
                "compiler_or_interpreter_identity": "fixture-compiler 1.0",
                "flags": ["-O2"],
                "dependency_lock": _descriptor(root, paths["dependencies.lock"]),
            },
            "runtime": {
                "platform": {
                    "system": "Linux",
                    "machine": "arm64" if platform.machine() == "arm64" else "amd64",
                },
                "interface_kind": "command_line",
                "adapter_protocol": assess.ADAPTER_PROTOCOL,
                "entrypoint": "route",
                "artifact": _descriptor(root, paths["runtime.bin"]),
                "adapter_source": _descriptor(root, paths["adapter.py"]),
                "serialized_zero_state": _descriptor(
                    root, paths["zero_state.json"]
                ),
                "execution": {
                    "backend": assess.DOCKER_EXECUTION_BACKEND,
                    "image_id": "sha256:" + "1" * 64,
                    "adapter_command": [
                        "python",
                        "/opt/gwm-candidate/adapter.py",
                    ],
                    "read_only_mount_targets": {
                        "runtime": "/opt/gwm-candidate/runtime.bin",
                        "adapter_source": "/opt/gwm-candidate/adapter.py",
                    },
                },
            },
            "independence": {
                name: True for name in assess.REQUIRED_INDEPENDENCE_ASSERTIONS
            },
            "interface": {
                name: True for name in assess.REQUIRED_INTERFACE_DECLARATIONS
            },
            "claim_boundary": {
                "outcome_inputs_included": False,
                "target_parameters_fitted": False,
                "synthetic_conformance_executed": False,
                "candidate_certified": False,
                "runtime_admitted": False,
            },
        },
    )
    return manifest, protocol


def _audit(registration: dict[str, object], audit_kind: str) -> dict[str, object]:
    findings = (
        SOURCE_AUDIT_REQUIREMENTS
        if audit_kind == SOURCE_AUDIT_KIND
        else ABI_AUDIT_REQUIREMENTS
    )
    return build_traditional_routing_preexecution_audit(
        audit_kind=audit_kind,
        candidate_registration=registration,
        findings=findings,
        auditor_identity={
            "name": "fixture-auditor",
            "version": "1.0",
            "implementation_artifact": _identity("audit/tool.py", "7"),
        },
        supporting_evidence_artifacts=(_identity("audit/evidence.json", "8"),),
    )


def _descriptor(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _identity(path: str, digit: str) -> dict[str, object]:
    return {
        "path": path,
        "sha256": digit * 64,
        "size_bytes": 17,
        "identity_matches": True,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
