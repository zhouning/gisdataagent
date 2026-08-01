from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_adapter_contract import (
    TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
    TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
    build_traditional_routing_adapter_request,
)
from data_agent.uwm.geospatial_kernel_v2.traditional_routing_docker_executor import (
    DockerReadOnlyMount,
    TraditionalRoutingDockerExecutionError,
    execute_traditional_routing_adapter_in_docker,
)

IMAGE_ID = "sha256:" + "1" * 64
CONTAINER_ID = "c" * 64


def test_executor_uses_immutable_image_and_complete_isolation_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.bin"
    adapter = tmp_path / "adapter.py"
    runtime.write_bytes(b"runtime")
    adapter.write_text("# adapter\n", encoding="utf-8")
    calls: list[list[str]] = []
    request = _request()

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        _write_container_id_from_command(command)
        _write_response_from_command(command, _response(request))
        return subprocess.CompletedProcess(command, 0, stdout="adapter log", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = execute_traditional_routing_adapter_in_docker(
        request,
        image_id=IMAGE_ID,
        adapter_command=("python", "/opt/gwm-candidate/adapter.py"),
        read_only_mounts=(
            DockerReadOnlyMount(runtime, "/opt/gwm-candidate/runtime.bin"),
            DockerReadOnlyMount(adapter, "/opt/gwm-candidate/adapter.py"),
        ),
    )

    assert len(calls) == 2
    run_command = calls[1]
    assert run_command[:3] == ["docker", "run", "--rm"]
    assert _contains_adjacent(run_command, ("--pull", "never"))
    assert "--no-healthcheck" in run_command
    assert _contains_adjacent(run_command, ("--entrypoint", "python"))
    for required_pair in (
        ("--network", "none"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--cpus", "1.0"),
        ("--memory", "512m"),
        ("--pids-limit", "64"),
    ):
        assert _contains_adjacent(run_command, required_pair)
    assert "--read-only" in run_command
    assert IMAGE_ID in run_command
    mount_specs = [
        run_command[index + 1]
        for index, value in enumerate(run_command[:-1])
        if value == "--mount"
    ]
    assert len(mount_specs) == 4
    assert any("dst=/gwm/request,readonly" in value for value in mount_specs)
    assert any("dst=/gwm/response" in value and "readonly" not in value for value in mount_specs)
    assert all(
        "readonly" in value
        for value in mount_specs
        if "dst=/opt/gwm-candidate/" in value
    )
    assert result["status"] == "adapter_response_transport_validated"
    assert result["validated_trace"]["routed_discharge_m3s"] == [
        [2.0, 2.0],
        [3.0, 3.0],
    ]
    assert result["command_policy"]["network_mode"] == "none"
    assert result["command_policy"]["writable_host_mount_targets"] == [
        "/gwm/response"
    ]
    assert result["claim_boundary"]["professional_runtime_certified"] is False
    assert result["claim_boundary"]["runtime_admitted"] is False
    assert result["execution_receipt"]["container_id"] == CONTAINER_ID
    assert result["execution_receipt"]["image_platform"] == {
        "system": "Linux",
        "machine": "arm64",
    }


@pytest.mark.parametrize("image", ["candidate:latest", "candidate@sha256:" + "1" * 64, "1" * 64])
def test_mutable_or_noncanonical_image_references_are_rejected_before_docker(
    monkeypatch: pytest.MonkeyPatch, image: str
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("docker must not be invoked")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="image_id_must_be_immutable_sha256"):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=image, adapter_command=("adapter",)
        )


def test_wrong_inspected_image_identity_fails_before_container_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "Id": "sha256:" + "2" * 64,
                    "Config": {},
                    "Os": "linux",
                    "Architecture": "arm64",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TraditionalRoutingDockerExecutionError, match="identity_mismatch"):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=IMAGE_ID, adapter_command=("adapter",)
        )
    assert calls == 1


def test_image_declared_writable_volumes_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "Id": IMAGE_ID,
                    "Config": {"Volumes": {"/data": {}}},
                    "Os": "linux",
                    "Architecture": "arm64",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(
        TraditionalRoutingDockerExecutionError,
        match="image_declared_volumes_forbidden",
    ):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=IMAGE_ID, adapter_command=("adapter",)
        )


def test_tampered_response_is_rejected_by_host_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    response = _response(request)
    response["request_sha256"] = "0" * 64
    _install_successful_runner(monkeypatch, response)

    with pytest.raises(ValueError, match="adapter_response_binding_invalid"):
        execute_traditional_routing_adapter_in_docker(
            request, image_id=IMAGE_ID, adapter_command=("adapter",)
        )


def test_nonzero_exit_missing_response_and_timeout_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def nonzero_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        return subprocess.CompletedProcess(command, 9, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", nonzero_run)
    with pytest.raises(TraditionalRoutingDockerExecutionError, match="nonzero_exit"):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=IMAGE_ID, adapter_command=("adapter",)
        )

    def missing_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        _write_container_id_from_command(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", missing_run)
    with pytest.raises(TraditionalRoutingDockerExecutionError, match="response_size_invalid"):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=IMAGE_ID, adapter_command=("adapter",)
        )

    def timeout_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        raise subprocess.TimeoutExpired(command, timeout=1.0)

    monkeypatch.setattr(subprocess, "run", timeout_run)
    with pytest.raises(TraditionalRoutingDockerExecutionError, match="adapter_timeout"):
        execute_traditional_routing_adapter_in_docker(
            _request(), image_id=IMAGE_ID, adapter_command=("adapter",)
        )


def test_extra_response_artifacts_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        _write_container_id_from_command(command)
        response_directory = _response_directory(command)
        response_directory.chmod(0o755)
        (response_directory / "response.json").write_text(
            json.dumps(_response(request)), encoding="utf-8"
        )
        (response_directory / "undeclared-output.bin").write_bytes(b"not allowed")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TraditionalRoutingDockerExecutionError, match="response_artifacts_invalid"):
        execute_traditional_routing_adapter_in_docker(
            request, image_id=IMAGE_ID, adapter_command=("adapter",)
        )


def test_unsealed_request_and_unsafe_mount_fail_before_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("docker must not be invoked")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    request = _request()
    request["boundary_inflow_m3s"][0][0] = 99.0
    with pytest.raises(ValueError, match="request_seal_invalid"):
        execute_traditional_routing_adapter_in_docker(
            request, image_id=IMAGE_ID, adapter_command=("adapter",)
        )

    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"runtime")
    with pytest.raises(ValueError, match="read_only_mount_invalid"):
        execute_traditional_routing_adapter_in_docker(
            _request(),
            image_id=IMAGE_ID,
            adapter_command=("adapter",),
            read_only_mounts=(DockerReadOnlyMount(artifact, "/gwm/response/runtime"),),
        )


def _install_successful_runner(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, object]
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["image", "inspect"]:
            return _inspect_result(command)
        _write_container_id_from_command(command)
        _write_response_from_command(command, response)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _write_response_from_command(
    command: list[str], response: dict[str, object]
) -> None:
    (_response_directory(command) / "response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )


def _write_container_id_from_command(command: list[str]) -> None:
    cidfile = Path(command[command.index("--cidfile") + 1])
    cidfile.write_text(CONTAINER_ID, encoding="ascii")


def _inspect_result(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            {
                "Id": IMAGE_ID,
                "Config": {"Volumes": None},
                "Os": "linux",
                "Architecture": "arm64",
            }
        ),
        stderr="",
    )


def _response_directory(command: list[str]) -> Path:
    mount_specs = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--mount"
    ]
    response_mount = next(value for value in mount_specs if "dst=/gwm/response" in value)
    source = next(part[4:] for part in response_mount.split(",") if part.startswith("src="))
    return Path(source)


def _contains_adjacent(command: list[str], values: tuple[str, str]) -> bool:
    return any(tuple(command[index : index + 2]) == values for index in range(len(command) - 1))


def _request() -> dict[str, object]:
    return build_traditional_routing_adapter_request(
        request_id="docker-fixture-request",
        candidate_id="docker-fixture-candidate",
        runtime_artifact={
            "path": "candidate/runtime.bin",
            "sha256": "a" * 64,
            "size_bytes": 17,
        },
        feature_ids=(10, 20),
        downstream_feature_ids=(20, None),
        geometry={
            "length_m": (1000.0, 1200.0),
            "bottom_width_m": (10.0, 12.0),
            "slope": (0.001, 0.002),
            "manning_n": (0.03, 0.035),
        },
        timestep_seconds=300.0,
        boundary_inflow_m3s=((2.0, 0.0), (3.0, 0.0)),
        lateral_inflow_m3s=((0.0, 0.0), (0.0, 0.0)),
        serialized_initial_state={"discharge_m3s": [2.0, 2.0]},
    )


def _response(request: dict[str, object]) -> dict[str, object]:
    request_copy = deepcopy(request)
    request_sha256 = request_copy.pop("request_seal")["sha256"]
    return {
        "schema": TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
        "adapter_protocol": TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
        "request_id": request["request_id"],
        "request_sha256": request_sha256,
        "routed_discharge_m3s": [[2.0, 2.0], [3.0, 3.0]],
        "total_storage_m3": [0.0, 0.0, 0.0],
        "serialized_final_state": {"discharge_m3s": [3.0, 3.0]},
    }
