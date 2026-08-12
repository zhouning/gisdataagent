"""Strict, non-secret deployment profile contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
PROFILE_SCHEMA = "gis-data-agent.deployment-profile.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServiceExpectation(StrictModel):
    name: str
    source_file: str
    runtime: Literal["required", "one_shot", "optional"]
    health_required: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("service name must be a lowercase identifier")
        return value

    @field_validator("source_file")
    @classmethod
    def validate_source_file(cls, value: str) -> str:
        return _relative_file(value, "source_file")

    @model_validator(mode="after")
    def validate_health_mode(self) -> ServiceExpectation:
        if self.runtime == "one_shot" and self.health_required:
            raise ValueError("one-shot services cannot require runtime health")
        return self


class VolumeExpectation(StrictModel):
    service: str
    target: str
    logical_name: str

    @field_validator("service", "logical_name")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("volume service/name must be a lowercase identifier")
        return value

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("volume target must be an absolute container path")
        return value


class ComposeContract(StrictModel):
    project_name: str
    files: tuple[str, ...]
    model_profiles: tuple[str, ...] = ()
    network: str
    baseline_probe_service: str
    config_sha256: str
    services: tuple[ServiceExpectation, ...]
    volumes: tuple[VolumeExpectation, ...]

    @field_validator("project_name", "network", "baseline_probe_service")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("Compose project/network must be a lowercase identifier")
        return value

    @field_validator("files")
    @classmethod
    def validate_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("at least one Compose file is required")
        normalized = tuple(_relative_file(value, "compose file") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Compose files must be unique")
        return normalized

    @field_validator("model_profiles")
    @classmethod
    def validate_profiles(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not IDENTIFIER_RE.fullmatch(value) for value in values):
            raise ValueError("Compose profiles must be lowercase identifiers")
        if len(set(values)) != len(values):
            raise ValueError("Compose profiles must be unique")
        return values

    @field_validator("config_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("config_sha256 must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> ComposeContract:
        service_names = [service.name for service in self.services]
        if len(set(service_names)) != len(service_names):
            raise ValueError("service expectations must be unique")
        compose_files = set(self.files)
        for service in self.services:
            if service.source_file not in compose_files:
                raise ValueError(
                    f"service {service.name!r} references an undeclared Compose file"
                )
        volume_keys = [(volume.service, volume.target) for volume in self.volumes]
        if len(set(volume_keys)) != len(volume_keys):
            raise ValueError("volume service/target expectations must be unique")
        unknown_services = {
            volume.service for volume in self.volumes if volume.service not in service_names
        }
        if unknown_services:
            raise ValueError(
                "volume expectations reference unknown services: "
                + ", ".join(sorted(unknown_services))
            )
        probe_services = [
            service
            for service in self.services
            if service.name == self.baseline_probe_service
        ]
        if not probe_services or probe_services[0].runtime != "required":
            raise ValueError("baseline_probe_service must be a required service")
        return self


class MigrationBaseline(StrictModel):
    count: int = Field(gt=0)
    fingerprint: str

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("migration fingerprint must be a lowercase SHA-256")
        return value


class StandardBaseline(StrictModel):
    doc_code: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    element_count: int = Field(gt=0)
    elements_sha256: str

    @field_validator("elements_sha256")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("standard fingerprint must be a lowercase SHA-256")
        return value


class HttpProbe(StrictModel):
    capability: str
    path: str
    expected_status: tuple[int, ...]
    expected_json_status: str | None = None
    content_type_prefix: str | None = None

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("HTTP capability must be a lowercase identifier")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not value.startswith("/") or ".." in path.parts or "?" in value or "#" in value:
            raise ValueError("HTTP probe path must be an absolute path without query/fragment")
        return value

    @field_validator("expected_status")
    @classmethod
    def validate_statuses(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if not values or any(value < 100 or value > 599 for value in values):
            raise ValueError("expected_status must contain valid HTTP status codes")
        return values


class CapabilityExpectation(StrictModel):
    capability: str
    configured_service: str | None = None
    configured_route: str | None = None
    internal_fact: Literal["redis"] | None = None
    runtime: Literal["required", "optional_not_enabled", "http_probe"]

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("capability must be a lowercase identifier")
        return value

    @field_validator("configured_route")
    @classmethod
    def validate_route(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith("/") or ".." in PurePosixPath(value).parts:
            raise ValueError("configured_route must be an absolute route path")
        return value

    @model_validator(mode="after")
    def validate_runtime_binding(self) -> CapabilityExpectation:
        if self.runtime == "http_probe" and not self.configured_route:
            raise ValueError("http_probe capabilities require configured_route")
        if self.runtime != "http_probe" and self.configured_route:
            raise ValueError("configured_route is only valid for http_probe capabilities")
        if self.runtime != "http_probe" and not self.configured_service:
            raise ValueError("service capabilities require configured_service")
        if self.internal_fact and self.runtime != "required":
            raise ValueError("internal_fact is only valid for required capabilities")
        return self


class GovernanceContract(StrictModel):
    platform_owner: str = Field(min_length=1)
    status: Literal["in_progress", "verified"]
    promotion_blockers: tuple[str, ...]


class DeploymentProfile(StrictModel):
    schema_name: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    profile_id: str
    environment: Literal["dev", "test", "staging", "production", "customer"]
    deployment_type: Literal["compose"]
    llm_mode: Literal["disabled", "optional", "required_for_agent_feature"]
    base_url: str
    compose: ComposeContract
    migrations: MigrationBaseline
    released_standard: StandardBaseline
    capabilities: tuple[CapabilityExpectation, ...]
    http_probes: tuple[HttpProbe, ...]
    governance: GovernanceContract

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("profile_id must be a lowercase identifier")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be HTTP(S)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, query, or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_capabilities(self) -> DeploymentProfile:
        capability_ids = [item.capability for item in self.capabilities]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("capability expectations must be unique")
        service_names = {service.name for service in self.compose.services}
        for item in self.capabilities:
            if item.configured_service and item.configured_service not in service_names:
                raise ValueError(
                    f"capability {item.capability!r} references an unknown service"
                )
        probe_capabilities = {probe.capability for probe in self.http_probes}
        declared_http = {
            item.capability for item in self.capabilities if item.runtime == "http_probe"
        }
        if probe_capabilities != declared_http:
            raise ValueError("HTTP probes must exactly cover http_probe capabilities")
        if self.governance.status == "verified" and self.governance.promotion_blockers:
            raise ValueError("a verified profile cannot retain promotion blockers")
        return self


def load_deployment_profile(path: str | Path) -> DeploymentProfile:
    """Load a deployment profile with strict schema and unknown-field rejection."""
    profile_path = Path(path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    return DeploymentProfile.model_validate(payload)


def _relative_file(value: str, field_name: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError(f"{field_name} must be a repository-relative file")
    return path.as_posix()
