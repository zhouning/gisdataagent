"""Fail-closed verification of Compose deployment profiles and runtime facts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from data_agent.migration_runner import catalog_fingerprint, discover_migrations

from .deployment_profile import DeploymentProfile

SENSITIVE_KEY_PARTS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "CREDENTIAL",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str
    body: bytes


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    status: str
    expected: Any
    actual: Any

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class VerificationReport:
    schema: str
    generated_at: str
    profile_id: str
    environment: str
    technical_pass: bool
    profile_contamination: bool
    promotion_ready: bool
    promotion_blockers: tuple[str, ...]
    capability_status: Mapping[str, str]
    checks: tuple[VerificationCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["promotion_blockers"] = list(self.promotion_blockers)
        payload["capability_status"] = dict(self.capability_status)
        payload["checks"] = [asdict(check) for check in self.checks]
        return payload


CommandRunner = Callable[[Sequence[str], Path], CommandResult]
HttpGetter = Callable[[str], HttpResult]


class DeploymentProfileVerifier:
    """Verify one profile without mutating Docker, databases, or services."""

    def __init__(
        self,
        *,
        profile: DeploymentProfile,
        profile_path: Path,
        repo_root: Path,
        command_runner: CommandRunner | None = None,
        http_getter: HttpGetter | None = None,
    ) -> None:
        self.profile = profile
        self.repo_root = repo_root.resolve()
        resolved_profile = profile_path.resolve()
        try:
            self.profile_relative_path = resolved_profile.relative_to(self.repo_root).as_posix()
        except ValueError as exc:
            raise ValueError("deployment profile must be inside the repository") from exc
        self.command_runner = command_runner or run_command
        self.http_getter = http_getter or get_http

    def verify(self, *, include_runtime: bool = True) -> VerificationReport:
        checks: list[VerificationCheck] = []
        capability_status: dict[str, str] = {}

        compose_model = self._load_compose_model(checks)
        if compose_model is not None:
            self._check_compose_contract(compose_model, checks)
        self._check_host_migration_catalog(checks)

        runtime_services: dict[str, dict[str, Any]] = {}
        internal_facts: dict[str, Any] | None = None
        if include_runtime and compose_model is not None:
            runtime_services = self._load_runtime_services(checks)
            self._check_runtime_services(compose_model, runtime_services, checks)
            internal_facts = self._load_internal_facts(runtime_services, checks)
            if internal_facts is not None:
                self._check_internal_facts(internal_facts, checks)
            self._check_http_probes(checks)

        self._derive_capability_status(
            checks=checks,
            runtime_services=runtime_services,
            include_runtime=include_runtime,
            output=capability_status,
        )
        technical_pass = bool(checks) and all(check.passed for check in checks)
        contamination = any(
            not check.passed
            and check.check_id.startswith(
                ("runtime.source_file.", "runtime.network.", "runtime.volume.")
            )
            for check in checks
        )
        blockers = tuple(self.profile.governance.promotion_blockers)
        if not include_runtime:
            blockers = (*blockers, "runtime_verification")
        promotion_ready = (
            include_runtime
            and technical_pass
            and self.profile.governance.status == "verified"
            and not blockers
        )
        return VerificationReport(
            schema="gis-data-agent.deployment-profile-verification.v1",
            generated_at=datetime.now(UTC).isoformat(),
            profile_id=self.profile.profile_id,
            environment=self.profile.environment,
            technical_pass=technical_pass,
            profile_contamination=contamination,
            promotion_ready=promotion_ready,
            promotion_blockers=blockers,
            capability_status=capability_status,
            checks=tuple(checks),
        )

    def _compose_command(self, *args: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.profile.compose.project_name,
        ]
        for compose_file in self.profile.compose.files:
            command.extend(("-f", compose_file))
        for compose_profile in self.profile.compose.model_profiles:
            command.extend(("--profile", compose_profile))
        command.extend(args)
        return command

    def _load_compose_model(
        self, checks: list[VerificationCheck]
    ) -> dict[str, Any] | None:
        result = self.command_runner(
            self._compose_command("config", "--format", "json"), self.repo_root
        )
        if result.returncode != 0:
            _append(checks, "compose.command", "pass", f"exit_{result.returncode}")
            return None
        try:
            model = json.loads(result.stdout)
        except json.JSONDecodeError:
            _append(checks, "compose.command", "valid_json", "invalid_json")
            return None
        _append(checks, "compose.command", "pass", "pass")
        return model

    def _check_compose_contract(
        self,
        model: Mapping[str, Any],
        checks: list[VerificationCheck],
    ) -> None:
        actual_fingerprint = canonical_compose_fingerprint(model, self.repo_root)
        _append(
            checks,
            "compose.config_sha256",
            self.profile.compose.config_sha256,
            actual_fingerprint,
        )
        _append(
            checks,
            "compose.project",
            self.profile.compose.project_name,
            model.get("name"),
        )
        services = model.get("services") or {}
        for service in self.profile.compose.services:
            _append(
                checks,
                f"compose.service.{service.name}",
                "configured",
                "configured" if service.name in services else "missing",
            )
        networks = model.get("networks") or {}
        network = networks.get(self.profile.compose.network)
        _append(
            checks,
            "compose.network",
            "configured",
            "configured" if isinstance(network, Mapping) else "missing",
        )
        for volume in self.profile.compose.volumes:
            service_model = services.get(volume.service) or {}
            service_volumes = service_model.get("volumes") or []
            matching = [
                item
                for item in service_volumes
                if item.get("type") == "volume" and item.get("target") == volume.target
            ]
            actual = matching[0].get("source") if len(matching) == 1 else "missing"
            _append(
                checks,
                f"compose.volume.{volume.service}.{_check_token(volume.target)}",
                volume.logical_name,
                actual,
            )

    def _check_host_migration_catalog(
        self, checks: list[VerificationCheck]
    ) -> None:
        migrations = discover_migrations()
        _append(
            checks,
            "host.migration.count",
            self.profile.migrations.count,
            len(migrations),
        )
        _append(
            checks,
            "host.migration.fingerprint",
            self.profile.migrations.fingerprint,
            catalog_fingerprint(migrations),
        )

    def _load_runtime_services(
        self, checks: list[VerificationCheck]
    ) -> dict[str, dict[str, Any]]:
        result = self.command_runner(
            self._compose_command("ps", "--all", "--format", "json"),
            self.repo_root,
        )
        if result.returncode != 0:
            _append(checks, "runtime.compose_ps", "pass", f"exit_{result.returncode}")
            return {}
        try:
            rows = _parse_json_stream(result.stdout)
        except (json.JSONDecodeError, TypeError, ValueError):
            _append(checks, "runtime.compose_ps", "valid_json", "invalid_json")
            return {}
        services = {
            str(row["Service"]): row
            for row in rows
            if isinstance(row, Mapping) and row.get("Service")
        }
        _append(checks, "runtime.compose_ps", "pass", "pass")
        return services

    def _check_runtime_services(
        self,
        compose_model: Mapping[str, Any],
        runtime_services: Mapping[str, dict[str, Any]],
        checks: list[VerificationCheck],
    ) -> dict[str, dict[str, Any]]:
        inspected: dict[str, dict[str, Any]] = {}
        configured_network = (
            (compose_model.get("networks") or {}).get(self.profile.compose.network) or {}
        ).get("name")
        for expectation in self.profile.compose.services:
            row = runtime_services.get(expectation.name)
            if row is None:
                expected = "optional" if expectation.runtime == "optional" else "present"
                actual = "optional_not_enabled" if expectation.runtime == "optional" else "missing"
                _append(
                    checks,
                    f"runtime.service.{expectation.name}",
                    expected,
                    actual,
                    passed=expectation.runtime == "optional",
                )
                continue

            if expectation.runtime == "one_shot":
                actual_state = (
                    "exited_0"
                    if row.get("State") == "exited" and int(row.get("ExitCode", 1)) == 0
                    else f"{row.get('State', 'unknown')}_{row.get('ExitCode', 'unknown')}"
                )
                _append(
                    checks,
                    f"runtime.service.{expectation.name}",
                    "exited_0",
                    actual_state,
                )
            elif expectation.runtime == "optional":
                actual_state = "running" if row.get("State") == "running" else row.get("State")
                _append(
                    checks,
                    f"runtime.service.{expectation.name}",
                    "running",
                    actual_state,
                )
            else:
                _append(
                    checks,
                    f"runtime.service.{expectation.name}",
                    "running",
                    row.get("State"),
                )
            if expectation.health_required and row.get("State") == "running":
                _append(
                    checks,
                    f"runtime.health.{expectation.name}",
                    "healthy",
                    row.get("Health") or "missing",
                )

            container_id = str(row.get("ID") or "")
            inspect_result = self.command_runner(
                ["docker", "inspect", container_id], self.repo_root
            )
            if inspect_result.returncode != 0:
                _append(
                    checks,
                    f"runtime.inspect.{expectation.name}",
                    "pass",
                    f"exit_{inspect_result.returncode}",
                )
                continue
            try:
                inspect_payload = json.loads(inspect_result.stdout)[0]
            except (json.JSONDecodeError, IndexError, TypeError):
                _append(
                    checks,
                    f"runtime.inspect.{expectation.name}",
                    "valid_json",
                    "invalid_json",
                )
                continue
            inspected[expectation.name] = inspect_payload
            labels = (inspect_payload.get("Config") or {}).get("Labels") or {}
            config_files = labels.get("com.docker.compose.project.config_files", "")
            actual_files = sorted(
                Path(item.strip()).name for item in config_files.split(",") if item.strip()
            )
            expected_files = sorted(Path(item).name for item in self.profile.compose.files)
            _append(
                checks,
                f"runtime.source_file.{expectation.name}",
                expected_files,
                actual_files,
            )
            actual_networks = sorted(
                ((inspect_payload.get("NetworkSettings") or {}).get("Networks") or {}).keys()
            )
            _append(
                checks,
                f"runtime.network.{expectation.name}",
                [configured_network],
                actual_networks,
            )

        volume_models = compose_model.get("volumes") or {}
        for volume in self.profile.compose.volumes:
            inspect_payload = inspected.get(volume.service) or {}
            mounts = inspect_payload.get("Mounts") or []
            matching = [
                mount
                for mount in mounts
                if mount.get("Type") == "volume" and mount.get("Destination") == volume.target
            ]
            actual_name = matching[0].get("Name") if len(matching) == 1 else "missing"
            expected_name = (volume_models.get(volume.logical_name) or {}).get("name")
            _append(
                checks,
                f"runtime.volume.{volume.service}.{_check_token(volume.target)}",
                expected_name,
                actual_name,
            )
        return inspected

    def _load_internal_facts(
        self,
        runtime_services: Mapping[str, dict[str, Any]],
        checks: list[VerificationCheck],
    ) -> dict[str, Any] | None:
        row = runtime_services.get(self.profile.compose.baseline_probe_service)
        container_id = str((row or {}).get("ID") or "")
        if not container_id:
            _append(checks, "runtime.internal_probe", "pass", "container_missing")
            return None
        result = self.command_runner(
            [
                "docker",
                "exec",
                container_id,
                "python",
                "-m",
                "data_agent.platform_runtime.internal_probe",
                "--profile",
                self.profile_relative_path,
            ],
            self.repo_root,
        )
        if result.returncode != 0:
            _append(
                checks,
                "runtime.internal_probe",
                "pass",
                f"exit_{result.returncode}",
            )
            return None
        try:
            facts = json.loads(result.stdout)
        except json.JSONDecodeError:
            _append(checks, "runtime.internal_probe", "valid_json", "invalid_json")
            return None
        _append(checks, "runtime.internal_probe", "pass", "pass")
        return facts

    def _check_internal_facts(
        self, facts: Mapping[str, Any], checks: list[VerificationCheck]
    ) -> None:
        _append(checks, "runtime.profile_id", self.profile.profile_id, facts.get("profile_id"))
        migration = facts.get("migration") or {}
        expected_migration = self.profile.migrations
        for key, expected in (
            ("status", "in_sync"),
            ("catalog_count", expected_migration.count),
            ("applied_count", expected_migration.count),
            ("catalog_fingerprint", expected_migration.fingerprint),
            ("database_fingerprint", expected_migration.fingerprint),
        ):
            _append(checks, f"runtime.migration.{key}", expected, migration.get(key))

        standard = facts.get("released_standard") or {}
        expected_standard = self.profile.released_standard
        for key, expected in (
            ("doc_code", expected_standard.doc_code),
            ("version_label", expected_standard.version_label),
            ("status", "released"),
            ("element_count", expected_standard.element_count),
            ("elements_sha256", expected_standard.elements_sha256),
        ):
            _append(checks, f"runtime.standard.{key}", expected, standard.get(key))
        route_paths = set(facts.get("route_paths") or [])
        for capability in self.profile.capabilities:
            if capability.internal_fact:
                dependency = (
                    (facts.get("dependencies") or {}).get(capability.internal_fact) or {}
                )
                _append(
                    checks,
                    f"runtime.internal.{capability.internal_fact}.status",
                    "ok",
                    dependency.get("status"),
                )
            if capability.configured_route and capability.configured_route.startswith(
                "/api/tiles/"
            ):
                _append(
                    checks,
                    f"runtime.route.{capability.capability}",
                    "configured",
                    "configured"
                    if capability.configured_route in route_paths
                    else "missing",
                )

    def _check_http_probes(self, checks: list[VerificationCheck]) -> None:
        for probe in self.profile.http_probes:
            try:
                result = self.http_getter(self.profile.base_url + probe.path)
            except Exception as exc:
                _append(
                    checks,
                    f"runtime.http.{probe.capability}",
                    list(probe.expected_status),
                    f"error:{type(exc).__name__}",
                )
                continue
            _append(
                checks,
                f"runtime.http.{probe.capability}",
                list(probe.expected_status),
                result.status,
                passed=result.status in probe.expected_status,
            )
            if probe.content_type_prefix:
                _append(
                    checks,
                    f"runtime.http_content_type.{probe.capability}",
                    probe.content_type_prefix,
                    result.content_type,
                    passed=result.content_type.startswith(probe.content_type_prefix),
                )
            if probe.expected_json_status is not None:
                try:
                    body = json.loads(result.body)
                    actual_status = body.get("status") if isinstance(body, Mapping) else None
                except (json.JSONDecodeError, UnicodeDecodeError):
                    actual_status = "invalid_json"
                _append(
                    checks,
                    f"runtime.http_json_status.{probe.capability}",
                    probe.expected_json_status,
                    actual_status,
                )

    def _derive_capability_status(
        self,
        *,
        checks: Sequence[VerificationCheck],
        runtime_services: Mapping[str, dict[str, Any]],
        include_runtime: bool,
        output: dict[str, str],
    ) -> None:
        by_id = {check.check_id: check for check in checks}
        service_expectations = {
            service.name: service for service in self.profile.compose.services
        }
        probes = {probe.capability: probe for probe in self.profile.http_probes}

        def service_is_available(service_name: str) -> bool:
            expectation = service_expectations[service_name]
            required_checks = [
                f"runtime.service.{service_name}",
                f"runtime.source_file.{service_name}",
                f"runtime.network.{service_name}",
            ]
            if expectation.health_required:
                required_checks.append(f"runtime.health.{service_name}")
            required_checks.extend(
                f"runtime.volume.{service_name}.{_check_token(volume.target)}"
                for volume in self.profile.compose.volumes
                if volume.service == service_name
            )
            return all(
                check_id in by_id and by_id[check_id].passed
                for check_id in required_checks
            )

        for capability in self.profile.capabilities:
            configured = True
            if capability.configured_service:
                configured = by_id.get(
                    f"compose.service.{capability.configured_service}",
                    VerificationCheck("missing", "fail", None, None),
                ).passed
            if capability.configured_route and include_runtime:
                route_check = by_id.get(f"runtime.route.{capability.capability}")
                if route_check is not None:
                    configured = configured and route_check.passed
            if not configured:
                output[capability.capability] = "not_configured"
                continue
            if not include_runtime:
                output[capability.capability] = "configured"
                continue
            if capability.runtime == "optional_not_enabled":
                if capability.configured_service not in runtime_services:
                    output[capability.capability] = "optional_not_enabled"
                else:
                    output[capability.capability] = (
                        "runtime"
                        if service_is_available(capability.configured_service)
                        else "runtime_failed"
                    )
            elif capability.runtime == "http_probe":
                probe = probes[capability.capability]
                required_checks = [f"runtime.http.{capability.capability}"]
                if probe.content_type_prefix:
                    required_checks.append(
                        f"runtime.http_content_type.{capability.capability}"
                    )
                if probe.expected_json_status is not None:
                    required_checks.append(
                        f"runtime.http_json_status.{capability.capability}"
                    )
                output[capability.capability] = (
                    "runtime"
                    if all(
                        check_id in by_id and by_id[check_id].passed
                        for check_id in required_checks
                    )
                    else "runtime_failed"
                )
            else:
                internal_check = (
                    by_id.get(f"runtime.internal.{capability.internal_fact}.status")
                    if capability.internal_fact
                    else None
                )
                internally_available = bool(
                    internal_check and internal_check.passed
                    if capability.internal_fact
                    else True
                )
                output[capability.capability] = (
                    "runtime"
                    if service_is_available(capability.configured_service)
                    and internally_available
                    else "runtime_failed"
                )


def canonical_compose_fingerprint(model: Mapping[str, Any], repo_root: Path) -> str:
    """Hash a deterministic Compose model after removing secrets and host paths."""
    sanitized = _sanitize_compose_value(model, repo_root.resolve())
    encoded = json.dumps(
        sanitized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_command(command: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def get_http(url: str) -> HttpResult:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - profile URL is validated
            return HttpResult(
                status=response.status,
                content_type=response.headers.get("content-type", ""),
                body=response.read(1_000_000),
            )
    except HTTPError as exc:
        return HttpResult(
            status=exc.code,
            content_type=exc.headers.get("content-type", ""),
            body=exc.read(1_000_000),
        )


def _append(
    checks: list[VerificationCheck],
    check_id: str,
    expected: Any,
    actual: Any,
    *,
    passed: bool | None = None,
) -> None:
    is_passed = expected == actual if passed is None else passed
    checks.append(
        VerificationCheck(
            check_id=check_id,
            status="pass" if is_passed else "fail",
            expected=expected,
            actual=actual,
        )
    )


def _parse_json_stream(raw: str) -> list[dict[str, Any]]:
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        payload = json.loads(stripped)
        if not isinstance(payload, list):
            raise TypeError("Compose ps JSON must be an array or NDJSON")
        return payload
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _sanitize_compose_value(value: Any, repo_root: Path) -> Any:
    if isinstance(value, list):
        return [_sanitize_compose_value(item, repo_root) for item in value]
    if not isinstance(value, Mapping):
        if isinstance(value, str) and value.startswith(str(repo_root)):
            return value.replace(str(repo_root), "<repo-root>", 1)
        return value

    result: dict[str, Any] = {}
    is_bind = value.get("type") == "bind"
    for key, item in value.items():
        upper_key = str(key).upper()
        if any(part in upper_key for part in SENSITIVE_KEY_PARTS):
            result[str(key)] = "<redacted>"
        elif is_bind and key == "source":
            result[str(key)] = "<host-bind>"
        elif key == "environment" and isinstance(item, Mapping):
            result[str(key)] = {
                str(env_key): _sanitize_environment_value(str(env_key), env_value)
                for env_key, env_value in item.items()
            }
        else:
            result[str(key)] = _sanitize_compose_value(item, repo_root)
    return result


def _sanitize_environment_value(name: str, value: Any) -> Any:
    upper_name = name.upper()
    if any(part in upper_name for part in SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, str) and "://" in value:
        authority = value.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            return "<redacted-url>"
    return value


def _check_token(value: str) -> str:
    return value.strip("/").replace("/", "_").replace(".", "_") or "root"
