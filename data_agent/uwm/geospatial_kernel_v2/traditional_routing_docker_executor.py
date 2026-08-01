"""Fail-closed Docker executor for sealed traditional-routing adapters."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .traditional_routing_adapter_contract import (
    TRADITIONAL_ROUTING_ADAPTER_REQUEST_SCHEMA,
    TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
    validate_traditional_routing_adapter_response,
)

TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_docker_execution.v1"
)
REQUEST_CONTAINER_PATH = "/gwm/request/request.json"
RESPONSE_CONTAINER_PATH = "/gwm/response/response.json"
READ_ONLY_MOUNT_ROOT = PurePosixPath("/opt/gwm-candidate")
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN_ADAPTER_ARGUMENTS = {
    "--request",
    "--response",
    REQUEST_CONTAINER_PATH,
    RESPONSE_CONTAINER_PATH,
}


class TraditionalRoutingDockerExecutionError(RuntimeError):
    """Raised when isolated adapter execution cannot be proven valid."""


@dataclass(frozen=True)
class DockerReadOnlyMount:
    """A candidate artifact exposed below the fixed read-only mount root."""

    source: Path
    target: str


def execute_traditional_routing_adapter_in_docker(
    request: Mapping[str, object],
    *,
    image_id: str,
    adapter_command: Sequence[str],
    read_only_mounts: Sequence[DockerReadOnlyMount] = (),
    docker_binary: str = "docker",
    timeout_seconds: float = 300.0,
    inspect_timeout_seconds: float = 15.0,
    cpu_limit: float = 1.0,
    memory_limit: str = "512m",
    pids_limit: int = 64,
    maximum_response_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Run one adapter invocation without network or mutable image references.

    The returned receipt proves transport and isolation policy only. It does not
    certify routing semantics and never admits the candidate runtime.
    """

    _validate_image_id(image_id)
    command = _validate_adapter_command(adapter_command)
    mounts = _validate_read_only_mounts(read_only_mounts)
    _validate_limits(
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
        inspect_timeout_seconds=inspect_timeout_seconds,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        pids_limit=pids_limit,
        maximum_response_bytes=maximum_response_bytes,
    )
    request_bytes = _canonical_json(dict(request))
    _validate_request_transport_seal(request, request_bytes)
    inspected_image = _inspect_image_identity(
        docker_binary=docker_binary,
        image_id=image_id,
        timeout_seconds=inspect_timeout_seconds,
    )

    policy = _command_policy(
        image_id=image_id,
        adapter_command=command,
        mounts=mounts,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        pids_limit=pids_limit,
        timeout_seconds=timeout_seconds,
    )
    with tempfile.TemporaryDirectory(prefix="gwm-routing-adapter-") as temporary_root:
        root = Path(temporary_root)
        request_directory = root / "request"
        response_directory = root / "response"
        request_directory.mkdir(mode=0o755)
        response_directory.mkdir(mode=0o755)
        request_path = request_directory / "request.json"
        response_path = response_directory / "response.json"
        container_id_path = root / "container.cid"
        request_path.write_bytes(request_bytes)
        request_path.chmod(0o400)
        response_path.touch()
        response_path.chmod(0o666)
        response_directory.chmod(0o555)

        docker_command = _docker_run_command(
            docker_binary=docker_binary,
            image_id=image_id,
            adapter_command=command,
            request_directory=request_directory,
            response_directory=response_directory,
            container_id_path=container_id_path,
            read_only_mounts=mounts,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            pids_limit=pids_limit,
        )
        try:
            completed, container_id = _run_container(
                docker_command,
                docker_binary=docker_binary,
                container_id_path=container_id_path,
                timeout_seconds=timeout_seconds,
            )
            response_bytes = _read_response_bytes(
                response_directory=response_directory,
                response_path=response_path,
                maximum_response_bytes=maximum_response_bytes,
            )
        finally:
            response_directory.chmod(0o700)

    response = _decode_response(response_bytes)
    trace = validate_traditional_routing_adapter_response(request, response)
    return {
        "schema": TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA,
        "status": "adapter_response_transport_validated",
        "validated_trace": trace,
        "command_policy": policy,
        "execution_receipt": {
            "requested_image_id": image_id,
            "inspected_image_id": inspected_image["image_id"],
            "image_identity_matched_before_execution": True,
            "image_declared_volumes": False,
            "image_platform": inspected_image["platform"],
            "container_id": container_id,
            "container_returncode": completed.returncode,
            "request_document_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "response_document_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "stdout_sha256": _sha256_text(completed.stdout),
            "stderr_sha256": _sha256_text(completed.stderr),
            "response_validated_after_container_exit": True,
        },
        "claim_boundary": {
            "transport_isolation_validated": True,
            "synthetic_conformance_executed": False,
            "professional_runtime_certified": False,
            "matched_two_system_execution_permitted": False,
            "runtime_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_image_id(image_id: object) -> None:
    if not isinstance(image_id, str) or _IMAGE_ID_PATTERN.fullmatch(image_id) is None:
        raise ValueError("traditional_routing_docker_image_id_must_be_immutable_sha256")


def _validate_adapter_command(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not value:
        raise ValueError("traditional_routing_docker_adapter_command_invalid")
    command = tuple(value)
    if any(
        not isinstance(argument, str)
        or not argument
        or "\x00" in argument
        or argument in _FORBIDDEN_ADAPTER_ARGUMENTS
        for argument in command
    ):
        raise ValueError("traditional_routing_docker_adapter_command_invalid")
    return command


def _validate_read_only_mounts(
    values: Sequence[DockerReadOnlyMount],
) -> tuple[DockerReadOnlyMount, ...]:
    mounts: list[DockerReadOnlyMount] = []
    targets: set[str] = set()
    for value in values:
        if not isinstance(value, DockerReadOnlyMount):
            raise ValueError("traditional_routing_docker_read_only_mount_invalid")
        source = Path(value.source).expanduser().resolve()
        target = PurePosixPath(value.target)
        if (
            not source.exists()
            or "," in str(source)
            or not target.is_absolute()
            or target == READ_ONLY_MOUNT_ROOT
            or READ_ONLY_MOUNT_ROOT not in target.parents
            or ".." in target.parts
            or "," in str(target)
            or str(target) in targets
        ):
            raise ValueError("traditional_routing_docker_read_only_mount_invalid")
        targets.add(str(target))
        mounts.append(DockerReadOnlyMount(source=source, target=str(target)))
    return tuple(mounts)


def _validate_limits(
    *,
    docker_binary: object,
    timeout_seconds: object,
    inspect_timeout_seconds: object,
    cpu_limit: object,
    memory_limit: object,
    pids_limit: object,
    maximum_response_bytes: object,
) -> None:
    positive_numbers = (timeout_seconds, inspect_timeout_seconds, cpu_limit)
    if (
        not isinstance(docker_binary, str)
        or not docker_binary
        or "\x00" in docker_binary
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in positive_numbers
        )
        or not isinstance(memory_limit, str)
        or re.fullmatch(r"[1-9][0-9]*[kKmMgG]", memory_limit) is None
        or not isinstance(pids_limit, int)
        or isinstance(pids_limit, bool)
        or pids_limit <= 0
        or not isinstance(maximum_response_bytes, int)
        or isinstance(maximum_response_bytes, bool)
        or maximum_response_bytes <= 0
    ):
        raise ValueError("traditional_routing_docker_resource_limits_invalid")


def _validate_request_transport_seal(
    request: Mapping[str, object], request_bytes: bytes
) -> None:
    payload = dict(request)
    seal = payload.pop("request_seal", None)
    if (
        request.get("schema") != TRADITIONAL_ROUTING_ADAPTER_REQUEST_SCHEMA
        or request.get("adapter_protocol") != TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL
        or not isinstance(seal, dict)
        or seal.get("algorithm")
        != "sha256_canonical_json_without_request_seal"
        or seal.get("sha256") != hashlib.sha256(_canonical_json(payload)).hexdigest()
        or not request_bytes
    ):
        raise ValueError("traditional_routing_docker_request_seal_invalid")


def _inspect_image_identity(
    *, docker_binary: str, image_id: str, timeout_seconds: float
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [docker_binary, "image", "inspect", "--format", "{{json .}}", image_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_inspect_timeout"
        ) from error
    except OSError as error:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_inspect_failed"
        ) from error
    try:
        inspected = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_identity_mismatch"
        ) from error
    if (
        completed.returncode != 0
        or not isinstance(inspected, dict)
        or inspected.get("Id") != image_id
    ):
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_identity_mismatch"
        )
    config = inspected.get("Config")
    if not isinstance(config, dict):
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_identity_mismatch"
        )
    volumes = config.get("Volumes")
    if volumes not in (None, {}):
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_declared_volumes_forbidden"
        )
    operating_system = inspected.get("Os")
    architecture = inspected.get("Architecture")
    if operating_system != "linux" or architecture not in {"amd64", "arm64"}:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_image_platform_invalid"
        )
    return {
        "image_id": inspected["Id"],
        "declared_volumes": False,
        "platform": {"system": "Linux", "machine": architecture},
    }


def _docker_run_command(
    *,
    docker_binary: str,
    image_id: str,
    adapter_command: tuple[str, ...],
    request_directory: Path,
    response_directory: Path,
    container_id_path: Path,
    read_only_mounts: tuple[DockerReadOnlyMount, ...],
    cpu_limit: float,
    memory_limit: str,
    pids_limit: int,
) -> list[str]:
    command = [
        docker_binary,
        "run",
        "--rm",
        "--pull",
        "never",
        "--cidfile",
        str(container_id_path),
        "--no-healthcheck",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        str(cpu_limit),
        "--memory",
        memory_limit,
        "--pids-limit",
        str(pids_limit),
        "--entrypoint",
        adapter_command[0],
        "--mount",
        _bind_mount(request_directory, PurePosixPath("/gwm/request"), read_only=True),
        "--mount",
        _bind_mount(response_directory, PurePosixPath("/gwm/response"), read_only=False),
    ]
    for mount in read_only_mounts:
        command.extend(
            [
                "--mount",
                _bind_mount(mount.source, PurePosixPath(mount.target), read_only=True),
            ]
        )
    command.extend(
        [
            image_id,
            *adapter_command[1:],
            "--request",
            REQUEST_CONTAINER_PATH,
            "--response",
            RESPONSE_CONTAINER_PATH,
        ]
    )
    return command


def _bind_mount(source: Path, target: PurePosixPath, *, read_only: bool) -> str:
    options = f"type=bind,src={source},dst={target}"
    return f"{options},readonly" if read_only else options


def _run_container(
    command: list[str],
    *,
    docker_binary: str,
    container_id_path: Path,
    timeout_seconds: float,
) -> tuple[subprocess.CompletedProcess[str], str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        _remove_timed_out_container(
            docker_binary=docker_binary,
            container_id_path=container_id_path,
        )
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_adapter_timeout"
        ) from error
    except OSError as error:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_adapter_execution_failed"
        ) from error
    if completed.returncode != 0:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_adapter_nonzero_exit"
        )
    container_id = _read_container_id(container_id_path)
    if container_id is None:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_container_identity_missing"
        )
    return completed, container_id


def _read_container_id(path: Path) -> str | None:
    try:
        container_id = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return container_id if _CONTAINER_ID_PATTERN.fullmatch(container_id) else None


def _remove_timed_out_container(*, docker_binary: str, container_id_path: Path) -> None:
    container_id = _read_container_id(container_id_path)
    if container_id is None:
        return
    try:
        subprocess.run(
            [docker_binary, "rm", "--force", container_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _read_response_bytes(
    *, response_directory: Path, response_path: Path, maximum_response_bytes: int
) -> bytes:
    entries = list(response_directory.iterdir())
    if (
        len(entries) != 1
        or entries[0] != response_path
        or response_path.is_symlink()
        or not response_path.is_file()
    ):
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_response_artifacts_invalid"
        )
    size = response_path.stat().st_size
    if size <= 0 or size > maximum_response_bytes:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_response_size_invalid"
        )
    return response_path.read_bytes()


def _decode_response(body: bytes) -> dict[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("traditional_routing_docker_response_duplicate_key")
            result[key] = value
        return result

    try:
        response = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_response_json_invalid"
        ) from error
    if not isinstance(response, dict):
        raise TraditionalRoutingDockerExecutionError(
            "traditional_routing_docker_response_json_invalid"
        )
    return response


def _command_policy(
    *,
    image_id: str,
    adapter_command: tuple[str, ...],
    mounts: tuple[DockerReadOnlyMount, ...],
    cpu_limit: float,
    memory_limit: str,
    pids_limit: int,
    timeout_seconds: float,
) -> dict[str, object]:
    return {
        "image_reference": image_id,
        "immutable_image_id_required": True,
        "image_identity_inspected_before_execution": True,
        "image_entrypoint_overridden": True,
        "image_healthcheck_disabled": True,
        "network_mode": "none",
        "root_filesystem_read_only": True,
        "capabilities_dropped": "ALL",
        "no_new_privileges": True,
        "cpu_limit": cpu_limit,
        "memory_limit": memory_limit,
        "pids_limit": pids_limit,
        "timeout_seconds": timeout_seconds,
        "shell_invocation": False,
        "host_environment_forwarded": False,
        "request_mount_read_only": True,
        "response_directory_mode_during_execution": "0555",
        "response_file_mode_during_execution": "0666",
        "writable_host_mount_targets": ["/gwm/response"],
        "candidate_read_only_mount_targets": [mount.target for mount in mounts],
        "adapter_command_argv_sha256": hashlib.sha256(
            _canonical_json(list(adapter_command))
        ).hexdigest(),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
