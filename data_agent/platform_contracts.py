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
from enum import Enum, StrEnum
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
ResourceKind = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,31}$"),
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


class PolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class ApprovalVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalCaseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SourceSyncMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class SourceSyncWriteDisposition(StrEnum):
    OVERWRITE = "overwrite"
    APPEND = "append"
    MERGE = "merge"


class SourceSyncCursorKind(StrEnum):
    NONE = "none"
    FIELD = "field"
    PROVIDER_TOKEN = "provider_token"
    OFFSET = "offset"


class SourceSyncDeleteMode(StrEnum):
    IGNORE = "ignore"
    SOFT_DELETE = "soft_delete"
    HARD_DELETE = "hard_delete"


class QualityVerdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class PlatformCommandType(str, Enum):
    DOLPHINSCHEDULER_DISPATCH = "dolphinscheduler.dispatch"
    DOLPHINSCHEDULER_RECONCILE = "dolphinscheduler.reconcile"


class PlatformCommandStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"


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


def quality_result_fingerprint(
    *,
    tenant_id: str,
    run_id: UUID,
    resource_version_id: UUID,
    rule_version_ref: str,
    verdict: QualityVerdict | str,
    metrics: dict[str, Any],
    evidence_artifact_id: UUID,
    evaluated_by: str,
    evaluated_at: datetime,
) -> str:
    """Fingerprint the immutable quality verdict and its evidence binding."""
    evaluated_at = _aware_utc(evaluated_at)
    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "run_id": str(run_id),
            "resource_version_id": str(resource_version_id),
            "rule_version_ref": rule_version_ref,
            "verdict": QualityVerdict(verdict).value,
            "metrics": metrics,
            "evidence_artifact_id": str(evidence_artifact_id),
            "evaluated_by": evaluated_by,
            "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        }
    )


def run_success_evidence_fingerprint(
    *,
    tenant_id: str,
    run_id: UUID,
    attempt_observation_id: UUID,
    output_artifact_id: UUID,
    quality_result_id: UUID,
    lineage_event_id: UUID,
) -> str:
    """Fingerprint the exact evidence set used for a successful Run verdict."""
    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "run_id": str(run_id),
            "attempt_observation_id": str(attempt_observation_id),
            "output_artifact_id": str(output_artifact_id),
            "quality_result_id": str(quality_result_id),
            "lineage_event_id": str(lineage_event_id),
        }
    )


def source_sync_definition_fingerprint(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    source_resource_urn: str,
    source_definition_fingerprint: str,
    target_resource_urn: str,
    mode: SourceSyncMode | str,
    write_disposition: SourceSyncWriteDisposition | str,
    cursor_kind: SourceSyncCursorKind | str,
    cursor_field: str | None,
    primary_keys: tuple[str, ...],
    delete_mode: SourceSyncDeleteMode | str,
    config: dict[str, Any],
) -> str:
    """Fingerprint one immutable, provider-independent source sync definition."""

    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "sync_definition_urn": sync_definition_urn,
            "sync_definition_version_id": str(sync_definition_version_id),
            "platform_definition_version_id": str(platform_definition_version_id),
            "source_resource_urn": source_resource_urn,
            "source_definition_fingerprint": source_definition_fingerprint,
            "target_resource_urn": target_resource_urn,
            "mode": SourceSyncMode(mode).value,
            "write_disposition": SourceSyncWriteDisposition(write_disposition).value,
            "cursor_kind": SourceSyncCursorKind(cursor_kind).value,
            "cursor_field": cursor_field,
            "primary_keys": list(primary_keys),
            "delete_mode": SourceSyncDeleteMode(delete_mode).value,
            "config": config,
        }
    )


def source_sync_commit_fingerprint(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    sync_definition_version_id: UUID,
    run_id: UUID,
    from_state_version: int,
    to_state_version: int,
    previous_cursor: dict[str, Any],
    next_cursor: dict[str, Any],
    source_slice_sha256: str,
    target_commit_ref: dict[str, Any],
    target_content_sha256: str,
    records_read: int,
    records_inserted: int,
    records_updated: int,
    records_deleted: int,
    records_output: int,
    committed_by: str,
    committed_at: datetime,
) -> str:
    """Fingerprint the exact source slice, target commit, cursor move and actor."""

    committed_at = _aware_utc(committed_at)
    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "sync_commit_id": str(sync_commit_id),
            "sync_definition_version_id": str(sync_definition_version_id),
            "run_id": str(run_id),
            "from_state_version": from_state_version,
            "to_state_version": to_state_version,
            "previous_cursor": previous_cursor,
            "next_cursor": next_cursor,
            "source_slice_sha256": source_slice_sha256,
            "target_commit_ref": target_commit_ref,
            "target_content_sha256": target_content_sha256,
            "records_read": records_read,
            "records_inserted": records_inserted,
            "records_updated": records_updated,
            "records_deleted": records_deleted,
            "records_output": records_output,
            "committed_by": committed_by,
            "committed_at": committed_at.isoformat().replace("+00:00", "Z"),
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


class RunPolicyReferences(FrozenContract):
    schema_id = "run_policy_references"

    policy_decision_artifact_id: UUID
    approval_artifact_id: UUID | None = None


class PolicyDecision(FrozenContract):
    schema_id = "policy_decision"

    tenant_id: TenantId
    run_id: UUID
    subject_context: SubjectContext
    action: ShortName
    definition_version_id: UUID
    resource_version_ids: tuple[UUID, ...] = Field(min_length=1)
    execution_plan_artifact_id: UUID
    effect: PolicyEffect
    policy_version_ref: NonEmptyText
    evaluator_subject: NonEmptyText
    requires_approval: bool = False
    obligations: tuple[ShortName, ...] = ()
    decided_at: datetime
    expires_at: datetime

    @field_validator("resource_version_ids")
    @classmethod
    def _canonical_resource_versions(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("resource_version_ids must not contain duplicates")
        return tuple(sorted(value, key=str))

    @field_validator("obligations")
    @classmethod
    def _canonical_obligations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("obligations must not contain duplicates")
        return tuple(sorted(value))

    @field_validator("decided_at", "expires_at")
    @classmethod
    def _utc_decision_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_scope(self) -> PolicyDecision:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("policy subject tenant must match decision tenant")
        if self.definition_version_id not in self.resource_version_ids:
            raise ValueError("policy scope must include the definition version")
        if not self.evaluator_subject.startswith("workload:"):
            raise ValueError("policy evaluator must use workload identity")
        if self.expires_at <= self.decided_at:
            raise ValueError("policy decision expiry must follow decision time")
        return self


class ApprovalRecord(FrozenContract):
    schema_id = "approval_record"

    tenant_id: TenantId
    run_id: UUID
    definition_version_id: UUID
    policy_decision_artifact_id: UUID
    policy_decision_sha256: Sha256
    verdict: ApprovalVerdict
    approver_subject: NonEmptyText
    reason: NonEmptyText
    decided_at: datetime
    expires_at: datetime

    @field_validator("decided_at", "expires_at")
    @classmethod
    def _utc_approval_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_approval(self) -> ApprovalRecord:
        if not self.approver_subject.startswith("human:"):
            raise ValueError("approval must use human identity")
        if self.expires_at <= self.decided_at:
            raise ValueError("approval expiry must follow decision time")
        return self


class ApprovalCase(FrozenContract):
    """Generic approval authority bound to one immutable resource action."""

    schema_id = "approval_case"

    tenant_id: TenantId
    approval_case_ref: ResourceURNText
    target_resource_urn: ResourceURNText
    target_fingerprint: Sha256
    action: ShortName
    requester_subject: NonEmptyText
    request_reason: NonEmptyText
    request_context: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalCaseStatus = ApprovalCaseStatus.PENDING
    state_version: Annotated[int, Field(ge=0)] = 0
    requested_at: datetime
    expires_at: datetime
    decided_by: NonEmptyText | None = None
    decision_reason: NonEmptyText | None = None
    decided_at: datetime | None = None

    @field_validator("requested_at", "expires_at", "decided_at")
    @classmethod
    def _utc_case_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_case(self) -> "ApprovalCase":
        case_identity = parse_resource_urn(self.approval_case_ref)
        target_identity = parse_resource_urn(self.target_resource_urn)
        if case_identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval_case_ref tenant must match tenant_id")
        if case_identity["resource_kind"] != "approval_case":
            raise ValueError("approval_case_ref must use resource kind 'approval_case'")
        if target_identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval target tenant must match tenant_id")
        if not self.requester_subject.startswith(("human:", "workload:", "agent:")):
            raise ValueError("approval requester must use a typed subject identity")
        if self.expires_at <= self.requested_at:
            raise ValueError("approval case expiry must follow request time")

        decision_values = (self.decided_by, self.decision_reason, self.decided_at)
        decided = self.status is not ApprovalCaseStatus.PENDING
        if decided != all(value is not None for value in decision_values):
            raise ValueError("approval decision fields must be set together for terminal state")
        if self.state_version == 0:
            if self.status is not ApprovalCaseStatus.PENDING:
                raise ValueError("approval case state version zero must be pending")
        elif self.state_version == 1:
            if not decided:
                raise ValueError("approval case state version one must be terminal")
        else:
            raise ValueError("approval case supports exactly one terminal decision")

        if self.decided_at is not None:
            if self.decided_at < self.requested_at:
                raise ValueError("approval decision cannot predate its request")
            if self.decided_at >= self.expires_at:
                raise ValueError("approval decision must occur before case expiry")
        if self.status in {ApprovalCaseStatus.APPROVED, ApprovalCaseStatus.REJECTED}:
            if self.decided_by is None or not self.decided_by.startswith("human:"):
                raise ValueError("approval verdict must use human identity")
            if self.decided_by == self.requester_subject:
                raise ValueError("approval verdict must be independent from requester")
        return self


class ApprovalCaseEvent(FrozenContract):
    schema_id = "approval_case_event"

    tenant_id: TenantId
    approval_event_id: UUID
    approval_case_ref: ResourceURNText
    sequence_no: Annotated[int, Field(ge=0)]
    from_status: ApprovalCaseStatus | None = None
    to_status: ApprovalCaseStatus
    actor_subject: NonEmptyText
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_event_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_event(self) -> "ApprovalCaseEvent":
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval event tenant must match case tenant")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("approval event must reference an ApprovalCase")
        if self.sequence_no == 0:
            if self.from_status is not None or self.to_status is not ApprovalCaseStatus.PENDING:
                raise ValueError("approval event sequence zero must initialize pending state")
        elif (
            self.sequence_no != 1
            or self.from_status is not ApprovalCaseStatus.PENDING
            or self.to_status is ApprovalCaseStatus.PENDING
        ):
            raise ValueError("approval event sequence one must record one terminal decision")
        if self.to_status in {ApprovalCaseStatus.APPROVED, ApprovalCaseStatus.REJECTED}:
            if not self.actor_subject.startswith("human:"):
                raise ValueError("approval verdict event must use human identity")
        return self


class SourceSyncDefinitionVersion(FrozenContract):
    """Immutable source-to-target synchronization semantics."""

    schema_id = "source_sync_definition_version"

    tenant_id: TenantId
    sync_definition_urn: ResourceURNText
    sync_definition_version_id: UUID
    platform_definition_version_id: UUID
    source_resource_urn: ResourceURNText
    source_definition_fingerprint: Sha256
    target_resource_urn: ResourceURNText
    mode: SourceSyncMode
    write_disposition: SourceSyncWriteDisposition
    cursor_kind: SourceSyncCursorKind
    cursor_field: ShortName | None = None
    primary_keys: tuple[ShortName, ...] = ()
    delete_mode: SourceSyncDeleteMode = SourceSyncDeleteMode.IGNORE
    config: dict[str, Any] = Field(default_factory=dict)
    definition_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_definition(self) -> "SourceSyncDefinitionVersion":
        sync_identity = parse_resource_urn(self.sync_definition_urn)
        source_identity = parse_resource_urn(self.source_resource_urn)
        target_identity = parse_resource_urn(self.target_resource_urn)
        if sync_identity["tenant_id"] != self.tenant_id:
            raise ValueError("sync definition tenant must match tenant_id")
        if sync_identity["resource_kind"] != "sync_definition":
            raise ValueError("sync definition must use resource kind 'sync_definition'")
        if source_identity["tenant_id"] != self.tenant_id:
            raise ValueError("sync source tenant must match tenant_id")
        if target_identity["tenant_id"] != self.tenant_id:
            raise ValueError("sync target tenant must match tenant_id")
        if not self.created_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("sync definition creator must use a typed subject identity")
        if len(set(self.primary_keys)) != len(self.primary_keys):
            raise ValueError("sync primary keys must be unique")

        if self.mode is SourceSyncMode.FULL:
            if self.cursor_kind is not SourceSyncCursorKind.NONE or self.cursor_field is not None:
                raise ValueError("full sync must not declare a cursor")
            if self.write_disposition is not SourceSyncWriteDisposition.OVERWRITE:
                raise ValueError("full sync must use overwrite disposition")
        else:
            if self.cursor_kind is SourceSyncCursorKind.NONE:
                raise ValueError("incremental sync requires a cursor")
            has_field = self.cursor_field is not None
            if (self.cursor_kind is SourceSyncCursorKind.FIELD) != has_field:
                raise ValueError("field cursor requires exactly one cursor_field")

        if self.write_disposition is SourceSyncWriteDisposition.MERGE and not self.primary_keys:
            raise ValueError("merge sync requires primary keys")
        if self.delete_mode is not SourceSyncDeleteMode.IGNORE:
            if self.write_disposition is not SourceSyncWriteDisposition.MERGE:
                raise ValueError("source deletes require merge disposition")

        expected = source_sync_definition_fingerprint(
            tenant_id=self.tenant_id,
            sync_definition_urn=self.sync_definition_urn,
            sync_definition_version_id=self.sync_definition_version_id,
            platform_definition_version_id=self.platform_definition_version_id,
            source_resource_urn=self.source_resource_urn,
            source_definition_fingerprint=self.source_definition_fingerprint,
            target_resource_urn=self.target_resource_urn,
            mode=self.mode,
            write_disposition=self.write_disposition,
            cursor_kind=self.cursor_kind,
            cursor_field=self.cursor_field,
            primary_keys=self.primary_keys,
            delete_mode=self.delete_mode,
            config=self.config,
        )
        if self.definition_sha256 != expected:
            raise ValueError("sync definition fingerprint does not match its immutable content")
        return self


class SourceSyncCheckpoint(FrozenContract):
    """Current cursor projection advanced only by a committed source sync."""

    schema_id = "source_sync_checkpoint"

    tenant_id: TenantId
    sync_definition_version_id: UUID
    state_version: Annotated[int, Field(ge=0)] = 0
    cursor: dict[str, Any] = Field(default_factory=dict)
    cursor_sha256: Sha256
    last_sync_commit_id: UUID | None = None
    last_run_id: UUID | None = None
    target_commit_ref: dict[str, Any] | None = None
    target_content_sha256: Sha256 | None = None
    updated_by: NonEmptyText
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _utc_updated_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_checkpoint(self) -> "SourceSyncCheckpoint":
        if self.cursor_sha256 != canonical_json_fingerprint(self.cursor):
            raise ValueError("sync checkpoint cursor fingerprint does not match cursor")
        if not self.updated_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("sync checkpoint updater must use a typed subject identity")
        commit_values = (
            self.last_sync_commit_id,
            self.last_run_id,
            self.target_commit_ref,
            self.target_content_sha256,
        )
        if self.state_version == 0:
            if any(value is not None for value in commit_values):
                raise ValueError("initial sync checkpoint must not contain commit evidence")
        elif not all(value is not None for value in commit_values):
            raise ValueError("advanced sync checkpoint requires complete commit evidence")
        return self


class SourceSyncCommit(FrozenContract):
    """Append-only evidence for one atomic provider commit and cursor advance."""

    schema_id = "source_sync_commit"

    tenant_id: TenantId
    sync_commit_id: UUID
    sync_definition_version_id: UUID
    run_id: UUID
    from_state_version: Annotated[int, Field(ge=0)]
    to_state_version: Annotated[int, Field(ge=1)]
    previous_cursor: dict[str, Any]
    previous_cursor_sha256: Sha256
    next_cursor: dict[str, Any]
    next_cursor_sha256: Sha256
    source_slice_sha256: Sha256
    target_commit_ref: dict[str, Any]
    target_content_sha256: Sha256
    records_read: Annotated[int, Field(ge=0)]
    records_inserted: Annotated[int, Field(ge=0)]
    records_updated: Annotated[int, Field(ge=0)]
    records_deleted: Annotated[int, Field(ge=0)]
    records_output: Annotated[int, Field(ge=0)]
    committed_by: NonEmptyText
    committed_at: datetime
    commit_sha256: Sha256

    @field_validator("committed_at")
    @classmethod
    def _utc_committed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_commit(self) -> "SourceSyncCommit":
        if self.to_state_version != self.from_state_version + 1:
            raise ValueError("sync commit must advance checkpoint by exactly one version")
        if self.previous_cursor_sha256 != canonical_json_fingerprint(self.previous_cursor):
            raise ValueError("previous cursor fingerprint does not match cursor")
        if self.next_cursor_sha256 != canonical_json_fingerprint(self.next_cursor):
            raise ValueError("next cursor fingerprint does not match cursor")
        if self.next_cursor_sha256 == self.previous_cursor_sha256:
            raise ValueError("sync commit must advance to a different cursor")
        if not self.target_commit_ref:
            raise ValueError("sync commit requires provider target commit evidence")
        if not self.committed_by.startswith("workload:"):
            raise ValueError("sync commit must use workload identity")
        if self.records_inserted + self.records_updated + self.records_deleted > self.records_read:
            raise ValueError("sync mutation counts cannot exceed records read")
        expected = source_sync_commit_fingerprint(
            tenant_id=self.tenant_id,
            sync_commit_id=self.sync_commit_id,
            sync_definition_version_id=self.sync_definition_version_id,
            run_id=self.run_id,
            from_state_version=self.from_state_version,
            to_state_version=self.to_state_version,
            previous_cursor=self.previous_cursor,
            next_cursor=self.next_cursor,
            source_slice_sha256=self.source_slice_sha256,
            target_commit_ref=self.target_commit_ref,
            target_content_sha256=self.target_content_sha256,
            records_read=self.records_read,
            records_inserted=self.records_inserted,
            records_updated=self.records_updated,
            records_deleted=self.records_deleted,
            records_output=self.records_output,
            committed_by=self.committed_by,
            committed_at=self.committed_at,
        )
        if self.commit_sha256 != expected:
            raise ValueError("sync commit fingerprint does not match immutable evidence")
        return self


class PlatformCommand(FrozenContract):
    schema_id = "platform_command"

    tenant_id: TenantId
    command_id: UUID
    run_id: UUID
    command_type: PlatformCommandType
    execution_plan_artifact_id: UUID
    trigger_observation_id: UUID | None = None
    dedupe_key: NonEmptyText
    actor_subject: NonEmptyText
    payload: dict[str, Any] = Field(default_factory=dict)
    status: PlatformCommandStatus = PlatformCommandStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=100)] = 5
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: NonEmptyText | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator(
        "available_at", "claimed_until", "created_at", "completed_at"
    )
    @classmethod
    def _utc_command_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_delivery_state(self) -> PlatformCommand:
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("command claim owner and expiry must be set together")
        if self.status == PlatformCommandStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending command cannot be claimed or completed")
        elif self.status == PlatformCommandStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight command requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("completed command must release its claim")
        if self.command_type == PlatformCommandType.DOLPHINSCHEDULER_DISPATCH:
            if self.trigger_observation_id is not None:
                raise ValueError("dispatch command cannot reference a callback observation")
        return self


class Resource(FrozenContract):
    schema_id = "resource"

    tenant_id: TenantId
    resource_urn: ResourceURNText
    resource_kind: ResourceKind
    authority_system: ShortName
    authority_locator: NonEmptyText
    owner_ref: NonEmptyText
    governance_ref: dict[str, Any] = Field(default_factory=dict)
    technical_refs: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def _consistent_identity(self) -> "Resource":
        components = parse_resource_urn(self.resource_urn)
        if components["tenant_id"] != self.tenant_id:
            raise ValueError("resource_urn tenant must match tenant_id")
        if components["resource_kind"] != self.resource_kind:
            raise ValueError("resource_urn kind must match resource_kind")
        return self


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
    policy_refs: RunPolicyReferences | None = None
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


class QualityResult(FrozenContract):
    schema_id = "quality_result"

    tenant_id: TenantId
    quality_result_id: UUID
    run_id: UUID
    resource_version_id: UUID
    rule_version_ref: NonEmptyText
    verdict: QualityVerdict
    metrics: dict[str, Any] = Field(min_length=1)
    evidence_artifact_id: UUID
    result_sha256: Sha256
    evaluated_by: NonEmptyText
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def _utc_evaluated_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_result(self) -> QualityResult:
        if not self.evaluated_by.startswith("workload:"):
            raise ValueError("quality evaluator must use workload identity")
        expected = quality_result_fingerprint(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            resource_version_id=self.resource_version_id,
            rule_version_ref=self.rule_version_ref,
            verdict=self.verdict,
            metrics=self.metrics,
            evidence_artifact_id=self.evidence_artifact_id,
            evaluated_by=self.evaluated_by,
            evaluated_at=self.evaluated_at,
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match quality result")
        return self


class RunSuccessEvidence(FrozenContract):
    schema_id = "run_success_evidence"

    tenant_id: TenantId
    run_id: UUID
    attempt_observation_id: UUID
    output_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_evidence(self) -> RunSuccessEvidence:
        expected = run_success_evidence_fingerprint(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            attempt_observation_id=self.attempt_observation_id,
            output_artifact_id=self.output_artifact_id,
            quality_result_id=self.quality_result_id,
            lineage_event_id=self.lineage_event_id,
        )
        if self.evidence_sha256 != expected:
            raise ValueError("evidence_sha256 does not match success evidence")
        return self


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
    RunPolicyReferences,
    PolicyDecision,
    ApprovalRecord,
    ApprovalCase,
    ApprovalCaseEvent,
    SourceSyncDefinitionVersion,
    SourceSyncCheckpoint,
    SourceSyncCommit,
    PlatformCommand,
    Resource,
    ResourceVersion,
    PlatformDefinitionVersion,
    ResourceBinding,
    PlatformRun,
    PlatformRunEvent,
    FrameworkAttemptObservation,
    QualityResult,
    RunSuccessEvidence,
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
