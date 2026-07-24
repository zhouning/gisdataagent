"""AR-0 contracts for cross-system resource and run correlation.

These models define the small control/evidence surface owned by GIS Data
Agent. They do not replace OpenMetadata, Gravitino, DolphinScheduler,
Temporal, or execution-provider state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, ClassVar
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


CONTRACT_SCHEMA_VERSION = "gda.platform_contracts.v1"
CONTROL_LEDGER_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "092_platform_control_ledger.sql"
)

_URN_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_RESOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_RESOURCE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/"
    r"[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$"
)
_ALLOWED_ARTIFACT_SCHEMES = frozenset(
    {"file", "gs", "https", "iceberg", "obs", "postgresql", "s3", "stac"}
)

TenantId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
ShortName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
ResourceURNText = Annotated[
    str,
    StringConstraints(min_length=12, max_length=256),
]


class PlatformContractError(ValueError):
    """A platform contract or state transition is invalid."""


class SubjectType(str, Enum):
    HUMAN = "human"
    WORKLOAD = "workload"
    AGENT = "agent"


class OrchestrationClass(str, Enum):
    DATAOPS = "dataops"
    DURABLE_AGENT = "durable_agent"
    DURABLE_GWM = "durable_gwm"
    ACTION = "action"
    SYNCHRONOUS = "synchronous"


class PortabilityClass(str, Enum):
    PORTABLE = "portable"
    ENGINE_FAMILY = "engine_family"
    PROVIDER_NATIVE = "provider_native"


class RunStatus(str, Enum):
    ACCEPTED = "accepted"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    CANCELLING = "cancelling"
    RECONCILING = "reconciling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class FrameworkKind(str, Enum):
    DOLPHINSCHEDULER = "dolphinscheduler"
    TEMPORAL = "temporal"
    SPARK = "spark"
    FLINK = "flink"
    KUBERNETES = "kubernetes"
    POSTGIS = "postgis"
    DUCKDB = "duckdb"
    ARCPY = "arcpy"
    CLOUD = "cloud"
    LEGACY = "legacy"


class ArtifactRole(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    CHECKPOINT = "checkpoint"
    LOG = "log"
    EVIDENCE = "evidence"
    EXECUTION_PLAN = "execution_plan"


class LineageEventType(str, Enum):
    READ = "read"
    WRITE = "write"
    DERIVE = "derive"
    COPY = "copy"
    MATERIALIZE = "materialize"
    PUBLISH = "publish"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
)
RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.ACCEPTED: frozenset(
        {RunStatus.DISPATCHING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.DISPATCHING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
            RunStatus.RECONCILING,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.CANCELLING,
            RunStatus.RECONCILING,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.CANCELLING: frozenset(
        {RunStatus.RECONCILING, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.RECONCILING: frozenset(
        {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }
    ),
}


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value with the platform-wide canonical encoding."""
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_json_fingerprint(value: Any) -> str:
    """Return the platform-wide SHA-256 for a canonical JSON value."""
    return _json_fingerprint(value)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def parse_resource_urn(resource_urn: str) -> dict[str, str]:
    """Parse the accepted gda:// tenant/kind/id resource identity."""
    if not _RESOURCE_URN_RE.fullmatch(resource_urn):
        raise PlatformContractError(
            "resource_urn must use gda://{tenant}/{kind}/{id} with canonical "
            "lowercase components"
        )
    parts = urlsplit(resource_urn)
    path_parts = parts.path.lstrip("/").split("/")
    if parts.scheme != "gda" or len(path_parts) != 2:
        raise PlatformContractError("resource_urn has an invalid structure")
    return {
        "tenant_id": parts.netloc,
        "resource_kind": path_parts[0],
        "resource_id": path_parts[1],
    }


def build_resource_urn(
    tenant_id: str, resource_kind: str, resource_id: str
) -> str:
    """Build and validate a canonical GDA resource identity."""
    if not _URN_COMPONENT_RE.fullmatch(tenant_id) or len(tenant_id) > 64:
        raise PlatformContractError("invalid tenant_id")
    if not _RESOURCE_KIND_RE.fullmatch(resource_kind):
        raise PlatformContractError("invalid resource_kind")
    if not _URN_COMPONENT_RE.fullmatch(resource_id):
        raise PlatformContractError("invalid resource_id")
    resource_urn = f"gda://{tenant_id}/{resource_kind}/{resource_id}"
    parse_resource_urn(resource_urn)
    return resource_urn


def validate_run_transition(
    from_status: RunStatus | str, to_status: RunStatus | str
) -> None:
    """Reject terminal, unknown, self, or otherwise invalid transitions."""
    try:
        source = RunStatus(from_status)
        target = RunStatus(to_status)
    except ValueError as exc:
        raise PlatformContractError(str(exc)) from exc
    if target not in RUN_TRANSITIONS.get(source, frozenset()):
        raise PlatformContractError(
            f"run transition {source.value!r} -> {target.value!r} is not allowed"
        )


def platform_definition_fingerprint(
    *,
    orchestration_class: OrchestrationClass | str,
    capability_id: str,
    portability_class: PortabilityClass | str,
    definition_document: dict[str, Any],
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
) -> str:
    """Fingerprint the complete provider-independent logical definition."""
    return _json_fingerprint(
        {
            "orchestration_class": OrchestrationClass(
                orchestration_class
            ).value,
            "capability_id": capability_id,
            "portability_class": PortabilityClass(portability_class).value,
            "definition_document": definition_document,
            "input_contract": input_contract,
            "output_contract": output_contract,
        }
    )


class FrozenContract(BaseModel):
    """Immutable, extra-forbidden base for fingerprinted contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: ClassVar[str]

    def contract_fingerprint(self) -> str:
        return _json_fingerprint(
            {
                "schema": self.schema_id,
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "data": self.model_dump(mode="json"),
            }
        )


class SubjectContext(FrozenContract):
    schema_id = "subject_context"

    tenant_id: TenantId
    subject_id: NonEmptyText
    subject_type: SubjectType
    roles: tuple[ShortName, ...] = ()
    purpose: NonEmptyText
    trace_id: ShortName | None = None
    delegated_by: NonEmptyText | None = None

    @field_validator("roles")
    @classmethod
    def _canonical_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("roles must not contain duplicates")
        return tuple(sorted(value))


class ResourceVersion(FrozenContract):
    schema_id = "resource_version"

    tenant_id: TenantId
    resource_urn: ResourceURNText
    resource_version_id: UUID
    version_key: ShortName
    predecessor_version_id: UUID | None = None
    content_sha256: Sha256
    authority_version_ref: dict[str, Any]
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("resource_urn")
    @classmethod
    def _valid_urn(cls, value: str) -> str:
        parse_resource_urn(value)
        return value

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_identity(self) -> "ResourceVersion":
        components = parse_resource_urn(self.resource_urn)
        if components["tenant_id"] != self.tenant_id:
            raise ValueError("resource_urn tenant must match tenant_id")
        if self.predecessor_version_id == self.resource_version_id:
            raise ValueError("a resource version cannot be its own predecessor")
        return self


class PlatformDefinitionVersion(FrozenContract):
    schema_id = "platform_definition_version"

    tenant_id: TenantId
    definition_urn: ResourceURNText
    definition_version_id: UUID
    orchestration_class: OrchestrationClass
    capability_id: ShortName
    portability_class: PortabilityClass
    definition_document: dict[str, Any]
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    definition_sha256: Sha256

    @field_validator("definition_urn")
    @classmethod
    def _valid_definition_urn(cls, value: str) -> str:
        components = parse_resource_urn(value)
        if components["resource_kind"] != "definition":
            raise ValueError("definition_urn must use resource kind 'definition'")
        return value

    @model_validator(mode="after")
    def _consistent_tenant(self) -> "PlatformDefinitionVersion":
        if parse_resource_urn(self.definition_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("definition_urn tenant must match tenant_id")
        expected = platform_definition_fingerprint(
            orchestration_class=self.orchestration_class,
            capability_id=self.capability_id,
            portability_class=self.portability_class,
            definition_document=self.definition_document,
            input_contract=self.input_contract,
            output_contract=self.output_contract,
        )
        if self.definition_sha256 != expected:
            raise ValueError("definition_sha256 does not match logical definition")
        return self


class ResourceBinding(FrozenContract):
    schema_id = "resource_binding"

    binding_name: ShortName
    resource_version_id: UUID
    semantic_type: NonEmptyText


class PlatformRun(FrozenContract):
    schema_id = "platform_run"

    tenant_id: TenantId
    run_id: UUID
    definition_version_id: UUID
    orchestration_class: OrchestrationClass
    subject_context: SubjectContext
    input_bindings: tuple[ResourceBinding, ...] = ()
    idempotency_key: NonEmptyText
    config_fingerprint: Sha256 | None = None
    status: RunStatus = RunStatus.ACCEPTED
    state_version: Annotated[int, Field(ge=0)] = 0
    submitted_at: datetime

    @field_validator("submitted_at")
    @classmethod
    def _utc_submitted_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_run(self) -> "PlatformRun":
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("subject_context tenant must match run tenant")
        binding_names = [binding.binding_name for binding in self.input_bindings]
        if len(binding_names) != len(set(binding_names)):
            raise ValueError("input binding names must be unique")
        if (self.state_version == 0) != (self.status == RunStatus.ACCEPTED):
            raise ValueError("accepted status is only valid at state version zero")
        return self


class PlatformRunEvent(FrozenContract):
    schema_id = "platform_run_event"

    tenant_id: TenantId
    event_id: UUID
    run_id: UUID
    sequence_no: Annotated[int, Field(ge=0)]
    from_status: RunStatus | None = None
    to_status: RunStatus
    actor_subject: NonEmptyText
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _valid_event(self) -> "PlatformRunEvent":
        if self.sequence_no == 0:
            if self.from_status is not None or self.to_status != RunStatus.ACCEPTED:
                raise ValueError("sequence zero must initialize accepted status")
        else:
            if self.from_status is None:
                raise ValueError("non-initial events require from_status")
            validate_run_transition(self.from_status, self.to_status)
        return self


class FrameworkAttemptObservation(FrozenContract):
    schema_id = "framework_attempt_observation"

    tenant_id: TenantId
    observation_id: UUID
    run_id: UUID
    attempt_no: Annotated[int, Field(ge=1)]
    framework_kind: FrameworkKind
    external_namespace: NonEmptyText
    external_run_id: NonEmptyText
    external_attempt_id: NonEmptyText | None = None
    observed_state: NonEmptyText
    observation_sha256: Sha256
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class Artifact(FrozenContract):
    schema_id = "artifact"

    tenant_id: TenantId
    artifact_id: UUID
    artifact_key: ShortName
    artifact_role: ArtifactRole
    storage_uri: NonEmptyText
    media_type: NonEmptyText
    content_sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]
    run_id: UUID | None = None
    resource_version_id: UUID | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("storage_uri")
    @classmethod
    def _safe_storage_uri(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in _ALLOWED_ARTIFACT_SCHEMES:
            raise ValueError("unsupported artifact storage URI scheme")
        if parts.username or parts.password:
            raise ValueError("artifact storage URI must not contain credentials")
        if parts.query or parts.fragment:
            raise ValueError(
                "artifact storage URI must be stable, not signed or fragmented"
            )
        if parts.scheme == "file":
            if parts.netloc or not parts.path.startswith("/"):
                raise ValueError("file artifact URI must use an absolute path")
        elif not parts.netloc:
            raise ValueError("artifact storage URI must identify an authority")
        return value

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class LineageEvent(FrozenContract):
    schema_id = "lineage_event"

    tenant_id: TenantId
    lineage_event_id: UUID
    event_type: LineageEventType
    source_resource_version_id: UUID
    target_resource_version_id: UUID
    producer: NonEmptyText
    event_sha256: Sha256
    run_id: UUID | None = None
    definition_version_id: UUID | None = None
    artifact_id: UUID | None = None
    facets: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _not_self_lineage(self) -> "LineageEvent":
        if self.source_resource_version_id == self.target_resource_version_id:
            raise ValueError("lineage source and target versions must differ")
        return self


CONTRACT_MODELS = (
    SubjectContext,
    ResourceVersion,
    PlatformDefinitionVersion,
    ResourceBinding,
    PlatformRun,
    PlatformRunEvent,
    FrameworkAttemptObservation,
    Artifact,
    LineageEvent,
)

_REQUIRED_MIGRATION_MARKERS = (
    "CREATE SCHEMA IF NOT EXISTS gda_control",
    "CREATE TABLE IF NOT EXISTS gda_control.resource (",
    "CREATE TABLE IF NOT EXISTS gda_control.resource_version (",
    "CREATE TABLE IF NOT EXISTS gda_control.platform_definition_version (",
    "CREATE TABLE IF NOT EXISTS gda_control.platform_run (",
    "CREATE TABLE IF NOT EXISTS gda_control.platform_run_input_binding (",
    "CREATE TABLE IF NOT EXISTS gda_control.platform_run_event (",
    "CREATE TABLE IF NOT EXISTS gda_control.framework_attempt_observation (",
    "CREATE TABLE IF NOT EXISTS gda_control.artifact (",
    "CREATE TABLE IF NOT EXISTS gda_control.lineage_event (",
    "CREATE OR REPLACE FUNCTION gda_control.transition_platform_run(",
    "ENABLE ROW LEVEL SECURITY",
    "FORCE ROW LEVEL SECURITY",
    "gda_control.reject_immutable_mutation()",
)


def contract_schemas() -> dict[str, dict[str, Any]]:
    """Return JSON Schemas keyed by stable contract schema ID."""
    return {
        model.schema_id: model.model_json_schema()
        for model in CONTRACT_MODELS
    }


def build_contract_report(
    migration_path: Path | None = None,
) -> dict[str, Any]:
    """Validate contract registry, state graph, and SQL ledger evidence."""
    errors: list[str] = []
    schema_ids = [model.schema_id for model in CONTRACT_MODELS]
    if len(schema_ids) != len(set(schema_ids)):
        errors.append("contract schema IDs must be unique")

    all_statuses = set(RunStatus)
    expected_sources = all_statuses - set(TERMINAL_RUN_STATUSES)
    if set(RUN_TRANSITIONS) != expected_sources:
        errors.append("run transition graph must cover every non-terminal status")
    for source, targets in RUN_TRANSITIONS.items():
        if source in TERMINAL_RUN_STATUSES:
            errors.append(f"terminal status {source.value} must not have transitions")
        if source in targets:
            errors.append(f"status {source.value} must not transition to itself")
        unknown = set(targets) - all_statuses
        if unknown:
            errors.append(f"status {source.value} has unknown transition targets")

    path = (migration_path or CONTROL_LEDGER_MIGRATION).resolve()
    migration_sha256: str | None = None
    missing_markers: list[str] = []
    if not path.exists():
        errors.append(f"control ledger migration is missing: {path}")
    else:
        migration_bytes = path.read_bytes()
        migration_sha256 = hashlib.sha256(migration_bytes).hexdigest()
        migration_text = migration_bytes.decode("utf-8")
        missing_markers = [
            marker for marker in _REQUIRED_MIGRATION_MARKERS
            if marker not in migration_text
        ]
        if missing_markers:
            errors.append("control ledger migration is missing required markers")

    schemas = contract_schemas()
    return {
        "schema": CONTRACT_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "contract_count": len(schemas),
        "contract_schema_fingerprint": _json_fingerprint(schemas),
        "run_transition_fingerprint": _json_fingerprint(
            {
                source.value: sorted(target.value for target in targets)
                for source, targets in sorted(
                    RUN_TRANSITIONS.items(), key=lambda item: item[0].value
                )
            }
        ),
        "migration": {
            "path": path.as_posix(),
            "sha256": migration_sha256,
            "missing_markers": missing_markers,
        },
        "errors": errors,
    }


def _print_json(value: Any, output: str | None = None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--migration", default=str(CONTROL_LEDGER_MIGRATION))
    validate_parser.add_argument("--output")
    schema_parser = subparsers.add_parser("schema")
    schema_parser.add_argument("--output")
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report(Path(args.migration))
        _print_json(report, args.output)
        return 0 if report["status"] == "valid" else 1
    _print_json(
        {
            "schema": CONTRACT_SCHEMA_VERSION,
            "contracts": contract_schemas(),
        },
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
