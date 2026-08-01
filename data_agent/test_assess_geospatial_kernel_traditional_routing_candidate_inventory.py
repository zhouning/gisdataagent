from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from scripts import assess_geospatial_kernel_traditional_routing_candidate_inventory as assess

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_empty_inventory_fails_closed_without_touching_inputs_or_outcomes() -> None:
    report = assess.assess_inventory()

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == "blocked_no_registered_independent_candidate"
    assert report["protocol"]["identity_matches"] is True
    assert report["submitted_candidate_count"] == 0
    assert report["decision"]["candidate_registration_ready"] is False
    assert report["decision"]["professional_runtime_available"] is False
    assert report["decision"]["matched_two_system_execution_permitted"] is False
    assert report["registration_contract"][
        "sealed_source_and_abi_audits_required_before_conformance"
    ] is True
    assert report["registration_contract"][
        "synthetic_zero_state_artifact_hash_bound"
    ] is True
    assert report["known_repository_runtimes"]["any_professional_runtime_available"] is False
    assert report["known_repository_runtimes"]["official_fixed_commit"][
        "professional_runtime_eligible"
    ] is False
    assert report["known_repository_runtimes"]["derived_initialized_diagnostic"][
        "professional_runtime_eligible"
    ] is False
    assert report["execution_boundary"] == {
        "network_requests_performed": False,
        "candidate_runtime_invoked": False,
        "two_system_dynamic_inputs_opened": False,
        "outcome_artifacts_opened": False,
        "candidate_parameters_fitted": False,
    }
    docker_images = report["host_inventory"]["docker_routing_image_inventory"]
    assert docker_images["name_discovery_implies_candidate_registration"] is False
    assert docker_images["network_requests_performed"] is False
    assert docker_images["candidate_runtime_invoked"] is False
    assert all(
        image["professional_candidate_eligible"] is False
        for image in docker_images["routing_named_images"]
    )


def test_complete_candidate_registration_only_opens_synthetic_conformance(
    tmp_path: Path,
) -> None:
    manifest, protocol = _candidate_fixture(tmp_path)

    report = assess.assess_inventory(
        (manifest,),
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == "registered_candidates_ready_for_synthetic_conformance"
    assert report["decision"]["registered_candidate_ids"] == ["fixture-mc-v1"]
    assert report["decision"]["candidate_registration_ready"] is True
    assert report["decision"]["synthetic_conformance_execution_permitted"] is (
        report["host_inventory"]["execution_isolation"][
            "professional_backend_available"
        ]
    )
    assert report["decision"]["synthetic_conformance_executed"] is False
    assert report["decision"]["professional_runtime_available"] is False
    assert report["decision"]["matched_two_system_execution_permitted"] is False
    candidate = next(iter(report["candidates"].values()))
    assert candidate["candidate_registration_ready"] is True
    assert all(candidate["gates"].values())
    assert candidate["execution_binding"] == {
        "backend": assess.DOCKER_EXECUTION_BACKEND,
        "image_id": "sha256:" + "1" * 64,
        "container_platform": {
            "system": "Linux",
            "machine": "arm64" if platform.machine() == "arm64" else "amd64",
        },
        "adapter_command": ["python", "/opt/gwm-candidate/adapter.py"],
        "read_only_mount_targets": {
            "runtime": "/opt/gwm-candidate/runtime.bin",
            "adapter_source": "/opt/gwm-candidate/adapter.py",
        },
        "network_mode": "none",
        "identity_matches": True,
    }
    assert candidate["claim_boundary"]["runtime_admitted"] is False
    assert candidate["artifacts"]["serialized_zero_state"]["json_object_valid"] is True


def test_zero_state_tampering_or_forbidden_content_blocks_registration(
    tmp_path: Path,
) -> None:
    manifest_path, protocol = _candidate_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    zero_state_path = tmp_path / manifest["runtime"]["serialized_zero_state"]["path"]
    zero_state_path.write_text('{"step": 1}\n', encoding="utf-8")

    tampered = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )
    assert tampered["candidate_registration_ready"] is False
    assert tampered["gates"][
        "synthetic_zero_state_artifact_identity_and_json_valid"
    ] is False

    _write_json(zero_state_path, {"outcome_path": "hidden.csv"})
    manifest["runtime"]["serialized_zero_state"] = _descriptor(
        tmp_path, zero_state_path
    )
    _write_json(manifest_path, manifest)
    forbidden = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )
    assert forbidden["candidate_registration_ready"] is False
    assert forbidden["forbidden_content_locations"] == [
        "$.runtime.serialized_zero_state.outcome_path"
    ]


def test_candidate_source_identity_tampering_fails_before_execution(tmp_path: Path) -> None:
    manifest_path, protocol = _candidate_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = tmp_path / manifest["implementation_identity"]["source_artifacts"][0][
        "path"
    ]
    source_path.write_text("tampered source\n", encoding="utf-8")

    report = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["candidate_registration_ready"] is False
    assert report["gates"][
        "all_source_build_runtime_license_and_adapter_artifacts_hash_bound"
    ] is False
    assert report["claim_boundary"]["candidate_runtime_invoked"] is False


def test_forbidden_outcome_input_and_learned_operator_reference_fail_closed(
    tmp_path: Path,
) -> None:
    manifest_path, protocol = _candidate_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime"]["outcome_path"] = "forbidden.csv"
    source_path = tmp_path / manifest["implementation_identity"]["source_artifacts"][0][
        "path"
    ]
    source_path.write_text("import conservative_edge_flux_innovation\n", encoding="utf-8")
    manifest["implementation_identity"]["source_artifacts"][0] = _descriptor(
        tmp_path, source_path
    )
    _write_json(manifest_path, manifest)

    report = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["candidate_registration_ready"] is False
    assert report["forbidden_content_locations"] == ["$.runtime.outcome_path"]
    assert report["forbidden_learned_code_tokens"] == [
        "conservative_edge_flux_innovation"
    ]
    assert report["gates"]["independence_assertions_and_source_scan_pass"] is False
    assert report["gates"]["no_forbidden_outcome_or_score_inputs_declared"] is False


def test_tampered_protocol_blocks_candidate_registration(tmp_path: Path) -> None:
    manifest_path, protocol = _candidate_fixture(tmp_path)
    payload = json.loads(protocol.read_text(encoding="utf-8"))
    payload["admission_decision"]["runtime_admitted"] = True
    _write_json(protocol, payload)

    report = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["candidate_registration_ready"] is False
    assert report["gates"]["frozen_protocol_identity_valid"] is False
    assert report["claim_boundary"]["candidate_runtime_invoked"] is False


def test_mutable_image_or_unbound_adapter_command_blocks_registration(
    tmp_path: Path,
) -> None:
    manifest_path, protocol = _candidate_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime"]["execution"]["image_id"] = "candidate:latest"
    manifest["runtime"]["execution"]["adapter_command"] = ["python", "/image/adapter.py"]
    _write_json(manifest_path, manifest)

    report = assess.assess_candidate_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["candidate_registration_ready"] is False
    assert report["execution_binding"]["identity_matches"] is False
    assert report["gates"][
        "docker_image_command_and_artifact_mounts_identity_bound"
    ] is False
    assert report["claim_boundary"]["candidate_runtime_invoked"] is False


def test_docker_image_inventory_deduplicates_tags_and_preserves_rejections() -> None:
    rejected_id = next(iter(assess.KNOWN_REJECTED_DOCKER_IMAGES))
    rapid_id = "sha256:" + "6" * 64
    unrelated_id = "sha256:" + "7" * 64
    rows = [
        {"ID": rejected_id, "Repository": "gisdataagent-troute-mc", "Tag": "12a8eae"},
        {"ID": rejected_id, "Repository": "local/troute", "Tag": "diagnostic"},
        {"ID": rapid_id, "Repository": "routing/rapid", "Tag": "v1"},
        {"ID": unrelated_id, "Repository": "postgres", "Tag": "16"},
    ]
    output = "\n".join(json.dumps(row) for row in rows) + "\nnot-json\n"

    report = assess._parse_docker_image_inventory(  # noqa: SLF001
        output,
        attempted=True,
        returncode=0,
    )

    assert report["status"] == "unregistered_routing_named_images_require_identity_review"
    assert report["total_unique_local_image_count"] == 3
    assert report["routing_named_image_count"] == 2
    assert report["unregistered_unreviewed_routing_named_image_count"] == 1
    assert report["malformed_row_count"] == 1
    rejected = next(
        image for image in report["routing_named_images"] if image["image_id"] == rejected_id
    )
    assert rejected["known_rejected_runtime"] is True
    assert rejected["professional_candidate_eligible"] is False
    assert rejected["matching_references"] == [
        "gisdataagent-troute-mc:12a8eae",
        "local/troute:diagnostic",
    ]


def _candidate_fixture(root: Path) -> tuple[Path, Path]:
    protocol = root / "protocol.json"
    protocol.write_bytes(assess.PROTOCOL_PATH.read_bytes())
    source = root / "candidate/source/mc.f90"
    license_path = root / "candidate/LICENSE"
    dependency_lock = root / "candidate/dependencies.lock"
    runtime = root / "candidate/libmc.dylib"
    adapter = root / "candidate/adapter.py"
    zero_state = root / "candidate/zero_state.json"
    for path, body in (
        (source, b"subroutine route()\nend subroutine route\n"),
        (license_path, b"Apache License 2.0 fixture\n"),
        (dependency_lock, b"compiler=fixture-1.0\n"),
        (runtime, b"fixture-binary\n"),
        (adapter, b"def route(inputs): return inputs\n"),
        (zero_state, b'{"step":0}\n'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
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
                "source_artifacts": [_descriptor(root, source)],
            },
            "license": {
                "spdx_identifier": "Apache-2.0",
                "artifact": _descriptor(root, license_path),
                "benchmark_use_permitted": True,
                "redistribution_permitted": True,
            },
            "build": {
                "compiler_or_interpreter_identity": "fixture-compiler 1.0",
                "flags": ["-O2"],
                "dependency_lock": _descriptor(root, dependency_lock),
            },
            "runtime": {
                "platform": {
                    "system": "Linux",
                    "machine": "arm64" if platform.machine() == "arm64" else "amd64",
                },
                "interface_kind": "shared_library",
                "adapter_protocol": assess.ADAPTER_PROTOCOL,
                "entrypoint": "route",
                "artifact": _descriptor(root, runtime),
                "adapter_source": _descriptor(root, adapter),
                "serialized_zero_state": _descriptor(root, zero_state),
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


def _descriptor(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
