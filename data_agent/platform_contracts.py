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
from typing import Annotated, Any, ClassVar, Literal
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
    QUARANTINE = "quarantine"
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


class ApprovalCaseNotificationKind(StrEnum):
    REQUESTED = "requested"
    EXPIRED = "expired"
    DECIDED = "decided"


class ApprovalCaseNotificationStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class ApprovalCaseAssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    RELEASED = "released"
    CLOSED = "closed"


class ApprovalCaseAssignmentAction(StrEnum):
    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    DELEGATED = "delegated"
    RELEASED = "released"
    CLOSED = "closed"


class ApprovalCaseAssignmentOperation(StrEnum):
    ASSIGN = "assign"
    REASSIGN = "reassign"
    DELEGATE = "delegate"
    RELEASE = "release"


class ApprovalPrincipalType(StrEnum):
    HUMAN = "human"
    TEAM = "team"


class ApprovalPrincipalStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ApprovalAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


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


class SourceSyncTargetLayer(StrEnum):
    LANDING = "landing"
    ODS = "ods"
    SILVER = "silver"
    GOLD = "gold"


class SourceSyncDataKind(StrEnum):
    TABULAR = "tabular"
    VECTOR = "vector"
    RASTER = "raster"
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    POINT_CLOUD = "point_cloud"
    TIMESERIES = "timeseries"


class SourceSyncCaptureKind(StrEnum):
    BATCH = "batch"
    MICRO_BATCH = "micro_batch"
    CDC = "cdc"
    EVENT_STREAM = "event_stream"


class SourceSyncSchemaChangePolicy(StrEnum):
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"
    ADDITIVE_COMPATIBLE = "additive_compatible"


class SourceSyncPromotionMode(StrEnum):
    BLOCKED = "blocked"
    QUALITY_GATED = "quality_gated"
    APPROVAL_GATED = "approval_gated"


class QualityVerdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class PlatformCommandType(str, Enum):
    DOLPHINSCHEDULER_DISPATCH = "dolphinscheduler.dispatch"
    DOLPHINSCHEDULER_RECONCILE = "dolphinscheduler.reconcile"
    DOLPHINSCHEDULER_CANCEL = "dolphinscheduler.cancel"
    METRIC_QUERY_EXECUTE = "metric_query.execute"


class PlatformCommandStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class IncidentNotificationChannel(str, Enum):
    ALERTMANAGER = "alertmanager"


class IncidentNotificationStatus(str, Enum):
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

INCIDENT_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset(
        {IncidentStatus.ACKNOWLEDGED, IncidentStatus.RESOLVED}
    ),
    IncidentStatus.ACKNOWLEDGED: frozenset({IncidentStatus.RESOLVED}),
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


def validate_incident_transition(
    from_status: IncidentStatus | str, to_status: IncidentStatus | str
) -> None:
    """Reject incident reopen, self-transition, and post-resolution mutation."""
    try:
        source = IncidentStatus(from_status)
        target = IncidentStatus(to_status)
    except ValueError as exc:
        raise PlatformContractError(str(exc)) from exc
    if target not in INCIDENT_TRANSITIONS.get(source, frozenset()):
        raise PlatformContractError(
            f"incident transition {source.value!r} -> {target.value!r} is not allowed"
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


def data_incident_fingerprint(
    *,
    tenant_id: str,
    run_id: UUID | None,
    dedupe_key: str,
    incident_type: str,
    severity: IncidentSeverity | str,
    summary: str,
    trigger_observation_id: UUID | None,
    details: dict[str, Any],
    detected_by: str,
    opened_at: datetime,
    subject_resource_urn: str | None = None,
) -> str:
    """Fingerprint the immutable cause and evidence binding of a DataIncident."""
    opened_at = _aware_utc(opened_at)
    value = {
        "tenant_id": tenant_id,
        "run_id": str(run_id) if run_id is not None else None,
        "dedupe_key": dedupe_key,
        "incident_type": incident_type,
        "severity": IncidentSeverity(severity).value,
        "summary": summary,
        "trigger_observation_id": (
            str(trigger_observation_id) if trigger_observation_id is not None else None
        ),
        "details": details,
        "detected_by": detected_by,
        "opened_at": opened_at.isoformat().replace("+00:00", "Z"),
    }
    if subject_resource_urn is not None:
        value["subject_resource_urn"] = subject_resource_urn
    return _json_fingerprint(value)


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
    governance_contract: SourceSyncGovernanceContract | dict[str, Any] | None = None,
) -> str:
    """Fingerprint one immutable, provider-independent source sync definition."""

    value = {
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
    if governance_contract is not None:
        contract = SourceSyncGovernanceContract.model_validate(governance_contract)
        value["governance_contract"] = contract.model_dump(mode="json", by_alias=True)
    return _json_fingerprint(value)


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


def source_sync_commit_governance_evidence_fingerprint(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    target_resource_version_id: UUID,
    output_artifact_id: UUID,
    quality_result_ids: tuple[UUID, ...],
    lineage_event_id: UUID,
    metadata_change_id: UUID,
    approval_case_ref: str | None,
) -> str:
    """Fingerprint the complete governance chain authorizing one lake promotion."""

    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "sync_commit_id": str(sync_commit_id),
            "target_resource_version_id": str(target_resource_version_id),
            "output_artifact_id": str(output_artifact_id),
            "quality_result_ids": sorted(str(value) for value in quality_result_ids),
            "lineage_event_id": str(lineage_event_id),
            "metadata_change_id": str(metadata_change_id),
            "approval_case_ref": approval_case_ref,
        }
    )


def source_sync_quarantine_evidence_fingerprint(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    source_slice_sha256: str,
    quarantine_resource_version_id: UUID,
    quarantine_artifact_id: UUID,
    records_rejected: int,
    reason_counts: dict[str, int],
) -> str:
    """Fingerprint the physical rejected-record receipt for one source slice."""

    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "sync_commit_id": str(sync_commit_id),
            "source_slice_sha256": source_slice_sha256,
            "quarantine_resource_version_id": str(quarantine_resource_version_id),
            "quarantine_artifact_id": str(quarantine_artifact_id),
            "records_rejected": records_rejected,
            "reason_counts": reason_counts,
        }
    )


def postgresql_cdc_failover_recovery_plan_fingerprint(
    *,
    tenant_id: str,
    sync_definition_urn: str,
    sync_definition_version_id: UUID,
    source_resource_urn: str,
    target_resource_urn: str,
    checkpoint_state_version: int,
    checkpoint_cursor: dict[str, Any],
    admission_reason_codes: tuple[str, ...],
    admission_evidence_sha256: str,
    created_by: str,
    created_at: datetime,
) -> str:
    """Fingerprint a failover rejection and the only safe recovery boundary."""

    created_at = _aware_utc(created_at)
    return _json_fingerprint(
        {
            "tenant_id": tenant_id,
            "sync_definition_urn": sync_definition_urn,
            "sync_definition_version_id": str(sync_definition_version_id),
            "source_resource_urn": source_resource_urn,
            "target_resource_urn": target_resource_urn,
            "checkpoint_state_version": checkpoint_state_version,
            "checkpoint_cursor": checkpoint_cursor,
            "admission_reason_codes": list(admission_reason_codes),
            "admission_evidence_sha256": admission_evidence_sha256,
            "recovery_mode": "resnapshot_and_reconcile",
            "cursor_disposition": "do_not_advance",
            "requires_new_run": True,
            "created_by": created_by,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }
    )


def postgresql_cdc_failover_resnapshot_admission_fingerprint(
    *,
    recovery_plan_sha256: str,
    previous_sync_definition_version_id: UUID,
    new_sync_definition: SourceSyncDefinitionVersion,
    new_run_id: UUID,
    admitted_by: str,
    admitted_at: datetime,
) -> str:
    """Fingerprint a new full-sync admission without advancing the old cursor."""

    admitted_at = _aware_utc(admitted_at)
    return _json_fingerprint(
        {
            "recovery_plan_sha256": recovery_plan_sha256,
            "previous_sync_definition_version_id": str(
                previous_sync_definition_version_id
            ),
            "new_sync_definition": new_sync_definition.model_dump(mode="json"),
            "new_run_id": str(new_run_id),
            "admission_mode": "resnapshot_and_reconcile",
            "cursor_disposition": "old_checkpoint_unchanged",
            "admitted_by": admitted_by,
            "admitted_at": admitted_at.isoformat().replace("+00:00", "Z"),
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
    def _consistent_case(self) -> ApprovalCase:
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
    def _consistent_event(self) -> ApprovalCaseEvent:
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


class ApprovalCaseAssignment(FrozenContract):
    """Current operational routing projection for an ApprovalCase."""

    schema_id = "approval_case_assignment"

    tenant_id: TenantId
    approval_case_ref: ResourceURNText
    assignment_version: Annotated[int, Field(ge=1)]
    status: ApprovalCaseAssignmentStatus
    assignee_subject: NonEmptyText | None = None
    last_actor_subject: NonEmptyText
    last_reason: NonEmptyText
    delegation_depth: Annotated[int, Field(ge=0, le=5)] = 0
    assigned_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None

    @field_validator("assigned_at", "updated_at", "closed_at")
    @classmethod
    def _utc_assignment_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_assignment(self) -> ApprovalCaseAssignment:
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval assignment tenant must match case tenant")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("approval assignment must reference an ApprovalCase")
        if not self.last_actor_subject.startswith(("human:", "workload:", "agent:")):
            raise ValueError("approval assignment actor must use a typed identity")
        if self.updated_at < self.assigned_at:
            raise ValueError("approval assignment update cannot predate assignment")
        if self.status is ApprovalCaseAssignmentStatus.ASSIGNED:
            if self.assignee_subject is None or not self.assignee_subject.startswith(
                ("human:", "team:")
            ):
                raise ValueError(
                    "active approval assignment requires a human or team assignee"
                )
            if self.closed_at is not None:
                raise ValueError("active approval assignment cannot be closed")
        elif self.status is ApprovalCaseAssignmentStatus.RELEASED:
            if self.assignee_subject is not None or self.closed_at is not None:
                raise ValueError("released approval assignment must be unassigned and open")
        elif self.closed_at is None:
            raise ValueError("closed approval assignment requires closed_at")
        return self


class ApprovalCaseAssignmentEvent(FrozenContract):
    """Immutable audit evidence for one ApprovalCase routing transition."""

    schema_id = "approval_case_assignment_event"

    tenant_id: TenantId
    assignment_event_id: UUID
    approval_case_ref: ResourceURNText
    assignment_version: Annotated[int, Field(ge=1)]
    action: ApprovalCaseAssignmentAction
    from_assignee_subject: NonEmptyText | None = None
    to_assignee_subject: NonEmptyText | None = None
    actor_subject: NonEmptyText
    reason: NonEmptyText
    delegation_depth: Annotated[int, Field(ge=0, le=5)] = 0
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_assignment_event_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_assignment_event(self) -> ApprovalCaseAssignmentEvent:
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval assignment event tenant must match case tenant")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("approval assignment event must reference an ApprovalCase")
        if not self.actor_subject.startswith(("human:", "workload:", "agent:")):
            raise ValueError("approval assignment event actor must use a typed identity")
        for assignee in (self.from_assignee_subject, self.to_assignee_subject):
            if assignee is not None and not assignee.startswith(("human:", "team:")):
                raise ValueError(
                    "approval assignment event assignees must be human or team subjects"
                )
        if self.action is ApprovalCaseAssignmentAction.ASSIGNED:
            valid = self.from_assignee_subject is None and self.to_assignee_subject is not None
        elif self.action in {
            ApprovalCaseAssignmentAction.REASSIGNED,
            ApprovalCaseAssignmentAction.DELEGATED,
        }:
            valid = (
                self.from_assignee_subject is not None
                and self.to_assignee_subject is not None
                and self.from_assignee_subject != self.to_assignee_subject
            )
        elif self.action is ApprovalCaseAssignmentAction.RELEASED:
            valid = self.from_assignee_subject is not None and self.to_assignee_subject is None
        else:
            valid = self.from_assignee_subject == self.to_assignee_subject
        if not valid:
            raise ValueError("approval assignment event action does not match assignee transition")
        if self.action is ApprovalCaseAssignmentAction.DELEGATED:
            if self.delegation_depth < 1:
                raise ValueError("delegation event requires positive delegation depth")
        elif (
            self.action is not ApprovalCaseAssignmentAction.CLOSED
            and self.delegation_depth != 0
        ):
            raise ValueError("non-delegation routing event must reset delegation depth")
        if (
            self.action is not ApprovalCaseAssignmentAction.CLOSED
            and not self.actor_subject.startswith("human:")
        ):
            raise ValueError("approval routing transition requires a human actor")
        return self


class ApprovalPrincipal(FrozenContract):
    """Versioned tenant directory entry used for approval eligibility."""

    schema_id = "approval_principal"

    tenant_id: TenantId
    principal_subject: NonEmptyText
    principal_type: ApprovalPrincipalType
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    directory_version: Annotated[int, Field(ge=1)]
    status: ApprovalPrincipalStatus
    approval_eligible: bool
    availability_status: ApprovalAvailabilityStatus
    valid_from: datetime
    valid_until: datetime | None = None
    last_actor_subject: NonEmptyText
    last_reason: NonEmptyText
    updated_at: datetime
    eligible_now: bool
    eligibility_reason: NonEmptyText

    @field_validator("valid_from", "valid_until", "updated_at")
    @classmethod
    def _utc_directory_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_principal(self) -> ApprovalPrincipal:
        if not self.principal_subject.startswith(f"{self.principal_type.value}:"):
            raise ValueError("approval principal type must match its typed subject")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("approval principal validity must have positive duration")
        if not self.last_actor_subject.startswith("human:"):
            raise ValueError("approval principal changes require a human actor")
        if self.eligible_now != (self.eligibility_reason == "eligible"):
            raise ValueError("approval principal eligibility result is inconsistent")
        return self


class ApprovalTeamMembership(FrozenContract):
    """Versioned effective-time membership in an approval team."""

    schema_id = "approval_team_membership"

    tenant_id: TenantId
    team_subject: NonEmptyText
    member_subject: NonEmptyText
    membership_version: Annotated[int, Field(ge=1)]
    status: ApprovalPrincipalStatus
    can_delegate: bool
    valid_from: datetime
    valid_until: datetime | None = None
    last_actor_subject: NonEmptyText
    last_reason: NonEmptyText
    updated_at: datetime

    @field_validator("valid_from", "valid_until", "updated_at")
    @classmethod
    def _utc_membership_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_membership(self) -> ApprovalTeamMembership:
        if not self.team_subject.startswith("team:"):
            raise ValueError("approval membership requires a team subject")
        if not self.member_subject.startswith("human:"):
            raise ValueError("approval membership requires a human member")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("approval membership validity must have positive duration")
        if not self.last_actor_subject.startswith("human:"):
            raise ValueError("approval membership changes require a human actor")
        return self


class ApprovalAssignmentActorAccess(FrozenContract):
    """Current resolved access for one human and one ApprovalCase assignment."""

    schema_id = "approval_assignment_actor_access"

    actor_subject: NonEmptyText
    can_decide: bool
    can_delegate: bool
    access_reason: NonEmptyText

    @model_validator(mode="after")
    def _consistent_access(self) -> ApprovalAssignmentActorAccess:
        if not self.actor_subject.startswith("human:"):
            raise ValueError("approval assignment access requires a human actor")
        if self.can_delegate and not self.can_decide:
            raise ValueError("approval delegation access requires decision access")
        return self


class ApprovalCaseNotification(FrozenContract):
    """Durable delivery projection for ApprovalCase lifecycle and SLA facts."""

    schema_id = "approval_case_notification"

    tenant_id: TenantId
    notification_id: UUID
    approval_case_ref: ResourceURNText
    approval_event_sequence_no: Annotated[int, Field(ge=0)] | None = None
    notification_kind: ApprovalCaseNotificationKind
    channel: IncidentNotificationChannel
    destination_ref: ShortName
    delivery_order: Annotated[int, Field(ge=0, le=1)]
    status: ApprovalCaseNotificationStatus = ApprovalCaseNotificationStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=100)] = 10
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: NonEmptyText | None = None
    created_at: datetime
    completed_at: datetime | None = None
    recovery_count: Annotated[int, Field(ge=0, le=10)] = 0
    last_recovered_by: NonEmptyText | None = None
    last_recovery_reason: NonEmptyText | None = None
    last_recovered_at: datetime | None = None

    @field_validator(
        "available_at",
        "claimed_until",
        "created_at",
        "completed_at",
        "last_recovered_at",
    )
    @classmethod
    def _utc_notification_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_notification(self) -> ApprovalCaseNotification:
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval notification tenant must match case tenant")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("approval notification must reference an ApprovalCase")
        if not self.destination_ref.startswith(f"{self.channel.value}:"):
            raise ValueError("approval notification destination must match its channel")
        expected_sequence = {
            ApprovalCaseNotificationKind.REQUESTED: 0,
            ApprovalCaseNotificationKind.EXPIRED: None,
            ApprovalCaseNotificationKind.DECIDED: 1,
        }[self.notification_kind]
        if self.approval_event_sequence_no != expected_sequence:
            raise ValueError("approval notification event binding does not match its kind")
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("notification claim owner and expiry must be set together")
        if self.status is ApprovalCaseNotificationStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending notification cannot be claimed or completed")
        elif self.status is ApprovalCaseNotificationStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight notification requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("terminal notification must release its claim")
        if (
            self.status is ApprovalCaseNotificationStatus.SUPPRESSED
            and self.notification_kind is not ApprovalCaseNotificationKind.EXPIRED
        ):
            raise ValueError("only an expiry notification may be suppressed")
        recovery_values = (
            self.last_recovered_by,
            self.last_recovery_reason,
            self.last_recovered_at,
        )
        if self.recovery_count == 0 and any(value is not None for value in recovery_values):
            raise ValueError("unrecovered notification cannot have recovery evidence")
        if self.recovery_count > 0:
            if not all(value is not None for value in recovery_values):
                raise ValueError("recovered notification requires complete recovery evidence")
            if not self.last_recovered_by.startswith("human:"):
                raise ValueError("notification recovery must use human identity")
        return self


class ApprovalCaseNotificationRecoveryEvent(FrozenContract):
    """Immutable audit evidence for one governed dead-letter recovery."""

    schema_id = "approval_case_notification_recovery_event"

    tenant_id: TenantId
    recovery_event_id: UUID
    notification_id: UUID
    approval_case_ref: ResourceURNText
    recovery_no: Annotated[int, Field(ge=1, le=10)]
    actor_subject: NonEmptyText
    reason: NonEmptyText
    previous_attempt_count: Annotated[int, Field(ge=1)]
    previous_last_error: NonEmptyText | None = None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_recovery_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_recovery(self) -> ApprovalCaseNotificationRecoveryEvent:
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("notification recovery tenant must match case tenant")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("notification recovery must reference an ApprovalCase")
        if not self.actor_subject.startswith("human:"):
            raise ValueError("notification recovery must use human identity")
        return self


class ApprovalCaseNotificationEnvelope(FrozenContract):
    schema_id = "approval_case_notification_envelope"

    notification: ApprovalCaseNotification
    approval_case: ApprovalCase
    event: ApprovalCaseEvent | None = None

    @model_validator(mode="after")
    def _consistent_notification_binding(self) -> ApprovalCaseNotificationEnvelope:
        notification = self.notification
        approval_case = self.approval_case
        if notification.tenant_id != approval_case.tenant_id:
            raise ValueError("approval notification envelope tenants must match")
        if notification.approval_case_ref != approval_case.approval_case_ref:
            raise ValueError("approval notification must bind its ApprovalCase")
        if notification.notification_kind is ApprovalCaseNotificationKind.EXPIRED:
            if self.event is not None:
                raise ValueError("approval expiry notification must not bind a decision event")
            if approval_case.status is not ApprovalCaseStatus.PENDING:
                raise ValueError("approval expiry notification requires a pending case")
            if notification.available_at != approval_case.expires_at:
                raise ValueError("approval expiry notification must use the case expiry")
            return self
        if self.event is None:
            raise ValueError("approval lifecycle notification requires its immutable event")
        if self.event.tenant_id != approval_case.tenant_id:
            raise ValueError("approval notification event tenant must match")
        if self.event.approval_case_ref != approval_case.approval_case_ref:
            raise ValueError("approval notification event must belong to the case")
        if self.event.sequence_no != notification.approval_event_sequence_no:
            raise ValueError("approval notification sequence must match its event")
        if notification.notification_kind is ApprovalCaseNotificationKind.DECIDED:
            if approval_case.status is not self.event.to_status:
                raise ValueError("approval decision notification must match current case state")
        return self


class SourceAdapterBinding(FrozenContract):
    """Exact connector or ingestion adapter revision used by a source sync."""

    schema_id = "source_adapter_binding"

    adapter_id: ShortName
    adapter_version: ShortName
    adapter_fingerprint: Sha256


class SourceSyncGovernanceContract(FrozenContract):
    """Governance gates that travel with one immutable source sync definition."""

    schema_id = "source_sync_governance_contract"
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal["gda.source_sync_governance.v1"] = Field(alias="schema")
    target_layer: SourceSyncTargetLayer
    data_kind: SourceSyncDataKind
    capture_kind: SourceSyncCaptureKind
    source_adapter: SourceAdapterBinding
    standard_mapping_contract_id: UUID | None = None
    standard_version_id: UUID | None = None
    data_model_version_id: UUID | None = None
    quality_rule_version_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    classification_policy_version_ref: NonEmptyText
    retention_policy_version_ref: NonEmptyText
    schema_change_policy: SourceSyncSchemaChangePolicy
    promotion_mode: SourceSyncPromotionMode
    quarantine_resource_urn: ResourceURNText | None = None
    event_time_field: ShortName | None = None
    watermark_delay_seconds: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _consistent_governance(self) -> SourceSyncGovernanceContract:
        if len(set(self.quality_rule_version_refs)) != len(
            self.quality_rule_version_refs
        ):
            raise ValueError("source sync quality rule version refs must be unique")
        has_mapping = self.standard_mapping_contract_id is not None
        has_standard = self.standard_version_id is not None
        if has_mapping != has_standard:
            raise ValueError(
                "source sync standard mapping and standard version must be bound together"
            )

        if self.target_layer in {
            SourceSyncTargetLayer.LANDING,
            SourceSyncTargetLayer.ODS,
        }:
            if self.promotion_mode is not SourceSyncPromotionMode.BLOCKED:
                raise ValueError("landing and ODS sync promotion must be blocked")
        else:
            if not all(
                (
                    has_mapping,
                    self.data_model_version_id is not None,
                    self.quarantine_resource_urn is not None,
                )
            ):
                raise ValueError(
                    "Silver and Gold syncs require standard, model, and quarantine bindings"
                )
            if self.promotion_mode is SourceSyncPromotionMode.BLOCKED:
                raise ValueError("Silver and Gold sync promotion must be governed by a gate")
        if (
            self.target_layer is SourceSyncTargetLayer.GOLD
            and self.promotion_mode is not SourceSyncPromotionMode.APPROVAL_GATED
        ):
            raise ValueError("Gold sync promotion must be approval gated")

        has_event_time = self.event_time_field is not None
        has_watermark = self.watermark_delay_seconds is not None
        if self.capture_kind is SourceSyncCaptureKind.EVENT_STREAM:
            if not has_event_time or not has_watermark:
                raise ValueError("event stream sync requires event time and watermark")
        elif has_event_time or has_watermark:
            raise ValueError("only event stream sync may declare event time or watermark")
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
    governance_contract: SourceSyncGovernanceContract | None = None
    definition_sha256: Sha256
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_definition(self) -> SourceSyncDefinitionVersion:
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

        governance = self.governance_contract
        if governance is not None:
            if self.mode is SourceSyncMode.FULL:
                if governance.capture_kind is not SourceSyncCaptureKind.BATCH:
                    raise ValueError("full sync requires batch capture")
            if (
                governance.capture_kind is not SourceSyncCaptureKind.BATCH
                and self.mode is not SourceSyncMode.INCREMENTAL
            ):
                raise ValueError("non-batch capture requires incremental sync mode")
            if governance.capture_kind in {
                SourceSyncCaptureKind.CDC,
                SourceSyncCaptureKind.EVENT_STREAM,
            } and self.cursor_kind not in {
                SourceSyncCursorKind.PROVIDER_TOKEN,
                SourceSyncCursorKind.OFFSET,
            }:
                raise ValueError("CDC and event stream sync require token or offset cursor")
            if governance.data_kind in {
                SourceSyncDataKind.RASTER,
                SourceSyncDataKind.DOCUMENT,
                SourceSyncDataKind.IMAGE,
                SourceSyncDataKind.VIDEO,
                SourceSyncDataKind.POINT_CLOUD,
            }:
                if self.write_disposition is SourceSyncWriteDisposition.MERGE:
                    raise ValueError("object and raster data kinds cannot use merge sync")
                if governance.capture_kind is SourceSyncCaptureKind.EVENT_STREAM:
                    raise ValueError(
                        "object and raster data kinds cannot use event stream capture"
                    )
            if governance.quarantine_resource_urn is not None:
                quarantine = parse_resource_urn(governance.quarantine_resource_urn)
                if quarantine["tenant_id"] != self.tenant_id:
                    raise ValueError("sync quarantine tenant must match tenant_id")

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
            governance_contract=self.governance_contract,
        )
        if self.definition_sha256 != expected:
            raise ValueError("sync definition fingerprint does not match its immutable content")
        return self


class PostgresqlCdcFailoverRecoveryPlan(FrozenContract):
    """Governed recovery boundary after a rejected PostgreSQL CDC failover."""

    schema_id = "postgresql_cdc_failover_recovery_plan"
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.postgresql_cdc_failover_recovery_plan.v1"
    ] = Field(alias="schema")
    tenant_id: TenantId
    sync_definition_urn: ResourceURNText
    sync_definition_version_id: UUID
    source_resource_urn: ResourceURNText
    target_resource_urn: ResourceURNText
    checkpoint_state_version: Annotated[int, Field(ge=0)]
    checkpoint_cursor: dict[str, Any]
    checkpoint_cursor_sha256: Sha256
    admission_schema: Literal["gda.postgres_cdc_failover_continuity_admission.v1"]
    admission_reason_codes: tuple[ShortName, ...] = Field(min_length=1)
    admission_evidence_sha256: Sha256
    recovery_mode: Literal["resnapshot_and_reconcile"]
    cursor_disposition: Literal["do_not_advance"]
    requires_new_run: Literal[True]
    created_by: NonEmptyText
    created_at: datetime
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @field_validator("admission_reason_codes")
    @classmethod
    def _canonical_reason_codes(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("failover recovery reason codes must be unique")
        ordered = tuple(sorted(value))
        if value != ordered:
            raise ValueError("failover recovery reason codes must be canonically sorted")
        return value

    @model_validator(mode="after")
    def _consistent_recovery_plan(self) -> PostgresqlCdcFailoverRecoveryPlan:
        sync_identity = parse_resource_urn(self.sync_definition_urn)
        source_identity = parse_resource_urn(self.source_resource_urn)
        target_identity = parse_resource_urn(self.target_resource_urn)
        if sync_identity["tenant_id"] != self.tenant_id:
            raise ValueError("failover recovery sync tenant must match tenant_id")
        if sync_identity["resource_kind"] != "sync_definition":
            raise ValueError("failover recovery must reference a sync_definition")
        if source_identity["tenant_id"] != self.tenant_id:
            raise ValueError("failover recovery source tenant must match tenant_id")
        if target_identity["tenant_id"] != self.tenant_id:
            raise ValueError("failover recovery target tenant must match tenant_id")
        if self.checkpoint_cursor_sha256 != canonical_json_fingerprint(
            self.checkpoint_cursor
        ):
            raise ValueError("failover recovery cursor fingerprint does not match cursor")
        if not self.created_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("failover recovery creator must use a typed subject identity")
        expected = postgresql_cdc_failover_recovery_plan_fingerprint(
            tenant_id=self.tenant_id,
            sync_definition_urn=self.sync_definition_urn,
            sync_definition_version_id=self.sync_definition_version_id,
            source_resource_urn=self.source_resource_urn,
            target_resource_urn=self.target_resource_urn,
            checkpoint_state_version=self.checkpoint_state_version,
            checkpoint_cursor=self.checkpoint_cursor,
            admission_reason_codes=self.admission_reason_codes,
            admission_evidence_sha256=self.admission_evidence_sha256,
            created_by=self.created_by,
            created_at=self.created_at,
        )
        if self.plan_sha256 != expected:
            raise ValueError("failover recovery plan fingerprint does not match content")
        return self


class PostgresqlCdcFailoverResnapshotAdmission(FrozenContract):
    """Admission for a new full-sync Run after a fail-closed CDC failover."""

    schema_id = "postgresql_cdc_failover_resnapshot_admission"
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.postgresql_cdc_failover_resnapshot_admission.v1"
    ] = Field(alias="schema")
    tenant_id: TenantId
    recovery_plan: PostgresqlCdcFailoverRecoveryPlan
    previous_sync_definition_version_id: UUID
    new_sync_definition: SourceSyncDefinitionVersion
    new_run_id: UUID
    admission_mode: Literal["resnapshot_and_reconcile"]
    cursor_disposition: Literal["old_checkpoint_unchanged"]
    admitted_by: NonEmptyText
    admitted_at: datetime
    admission_sha256: Sha256

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_admission(
        self,
    ) -> PostgresqlCdcFailoverResnapshotAdmission:
        plan = self.recovery_plan
        definition = self.new_sync_definition
        if plan.tenant_id != self.tenant_id or definition.tenant_id != self.tenant_id:
            raise ValueError("resnapshot admission tenants must match")
        if self.previous_sync_definition_version_id != plan.sync_definition_version_id:
            raise ValueError("resnapshot admission must reference the rejected definition")
        if definition.sync_definition_version_id == self.previous_sync_definition_version_id:
            raise ValueError("resnapshot admission requires a new definition version")
        if definition.sync_definition_urn == plan.sync_definition_urn:
            raise ValueError("resnapshot admission requires a new definition identity")
        if definition.source_resource_urn != plan.source_resource_urn:
            raise ValueError("resnapshot source must match the recovery plan")
        if definition.target_resource_urn != plan.target_resource_urn:
            raise ValueError("resnapshot target must match the recovery plan")
        if definition.mode is not SourceSyncMode.FULL:
            raise ValueError("resnapshot admission requires a full sync definition")
        if definition.write_disposition is not SourceSyncWriteDisposition.OVERWRITE:
            raise ValueError("resnapshot admission requires overwrite disposition")
        if definition.cursor_kind is not SourceSyncCursorKind.NONE:
            raise ValueError("resnapshot admission must not create a new cursor")
        if definition.delete_mode is not SourceSyncDeleteMode.IGNORE:
            raise ValueError("resnapshot admission must not apply source deletes")
        if (
            definition.governance_contract is None
            or definition.governance_contract.capture_kind
            is not SourceSyncCaptureKind.BATCH
        ):
            raise ValueError("resnapshot admission requires batch governance")
        if not self.admitted_by.startswith(("human:", "workload:", "agent:")):
            raise ValueError("resnapshot admission actor must use a typed subject identity")
        expected = postgresql_cdc_failover_resnapshot_admission_fingerprint(
            recovery_plan_sha256=plan.plan_sha256,
            previous_sync_definition_version_id=self.previous_sync_definition_version_id,
            new_sync_definition=definition,
            new_run_id=self.new_run_id,
            admitted_by=self.admitted_by,
            admitted_at=self.admitted_at,
        )
        if self.admission_sha256 != expected:
            raise ValueError("resnapshot admission fingerprint does not match content")
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
    def _consistent_checkpoint(self) -> SourceSyncCheckpoint:
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
    def _consistent_commit(self) -> SourceSyncCommit:
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


class SourceSyncCommitGovernanceEvidence(FrozenContract):
    """Immutable quality, approval, lineage, and metadata promotion evidence."""

    schema_id = "source_sync_commit_governance_evidence"

    tenant_id: TenantId
    sync_commit_id: UUID
    target_resource_version_id: UUID
    output_artifact_id: UUID
    quality_result_ids: tuple[UUID, ...] = Field(min_length=1)
    lineage_event_id: UUID
    metadata_change_id: UUID
    approval_case_ref: ResourceURNText | None = None
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_governance_evidence(
        self,
    ) -> SourceSyncCommitGovernanceEvidence:
        if len(set(self.quality_result_ids)) != len(self.quality_result_ids):
            raise ValueError("source sync quality result ids must be unique")
        if self.quality_result_ids != tuple(
            sorted(self.quality_result_ids, key=lambda value: str(value))
        ):
            raise ValueError("source sync quality result ids must be canonically sorted")
        if self.approval_case_ref is not None:
            approval_identity = parse_resource_urn(self.approval_case_ref)
            if approval_identity["tenant_id"] != self.tenant_id:
                raise ValueError("source sync approval tenant must match tenant_id")
            if approval_identity["resource_kind"] != "approval_case":
                raise ValueError("source sync approval must reference an ApprovalCase")
        expected = source_sync_commit_governance_evidence_fingerprint(
            tenant_id=self.tenant_id,
            sync_commit_id=self.sync_commit_id,
            target_resource_version_id=self.target_resource_version_id,
            output_artifact_id=self.output_artifact_id,
            quality_result_ids=self.quality_result_ids,
            lineage_event_id=self.lineage_event_id,
            metadata_change_id=self.metadata_change_id,
            approval_case_ref=self.approval_case_ref,
        )
        if self.evidence_sha256 != expected:
            raise ValueError("source sync governance evidence fingerprint does not match")
        return self


class SourceSyncQuarantineEvidence(FrozenContract):
    """Immutable receipt for the provider's physical rejected-record artifact."""

    schema_id = "source_sync_quarantine_evidence"

    tenant_id: TenantId
    sync_commit_id: UUID
    source_slice_sha256: Sha256
    quarantine_resource_version_id: UUID
    quarantine_artifact_id: UUID
    records_rejected: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    reason_counts: dict[
        ShortName,
        Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)],
    ]
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_quarantine_evidence(self) -> SourceSyncQuarantineEvidence:
        if (self.records_rejected == 0) != (not self.reason_counts):
            raise ValueError(
                "zero rejected records requires empty reasons and positive rejects require reasons"
            )
        if sum(self.reason_counts.values()) != self.records_rejected:
            raise ValueError("quarantine reason counts must equal records rejected")
        expected = source_sync_quarantine_evidence_fingerprint(
            tenant_id=self.tenant_id,
            sync_commit_id=self.sync_commit_id,
            source_slice_sha256=self.source_slice_sha256,
            quarantine_resource_version_id=self.quarantine_resource_version_id,
            quarantine_artifact_id=self.quarantine_artifact_id,
            records_rejected=self.records_rejected,
            reason_counts=self.reason_counts,
        )
        if self.evidence_sha256 != expected:
            raise ValueError("source sync quarantine evidence fingerprint does not match")
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
        if self.command_type == PlatformCommandType.METRIC_QUERY_EXECUTE:
            payload = self.payload
            engine = payload.get("engine")
            expected_mode = {
                "postgis": "synchronous",
                "duckdb": "synchronous",
                "iceberg_spark": "asynchronous",
            }.get(engine)
            if (
                self.trigger_observation_id is not None
                or payload.get("schema") != "gda.metric_query_execute_command.v1"
                or payload.get("run_id") != str(self.run_id)
                or payload.get("plan_artifact_id")
                != str(self.execution_plan_artifact_id)
                or re.fullmatch(r"[0-9a-f]{64}", str(payload.get("plan_fingerprint")))
                is None
                or re.fullmatch(r"[0-9a-f]{64}", str(payload.get("cache_key")))
                is None
                or payload.get("execution_mode") != expected_mode
            ):
                raise ValueError("metric query command must bind an exact executable plan")
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


class DataIncident(FrozenContract):
    schema_id = "data_incident"

    tenant_id: TenantId
    incident_id: UUID
    run_id: UUID | None
    subject_resource_urn: ResourceURNText | None = None
    dedupe_key: ShortName
    incident_type: ShortName
    severity: IncidentSeverity
    summary: NonEmptyText
    trigger_observation_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    incident_sha256: Sha256
    detected_by: NonEmptyText
    status: IncidentStatus = IncidentStatus.OPEN
    state_version: Annotated[int, Field(ge=0)] = 0
    opened_at: datetime
    updated_at: datetime

    @field_validator("opened_at", "updated_at")
    @classmethod
    def _utc_timestamps(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _consistent_incident(self) -> "DataIncident":
        if not self.detected_by.startswith("workload:"):
            raise ValueError("incident detector must use workload identity")
        if (self.run_id is None) == (self.subject_resource_urn is None):
            raise ValueError("incident must bind exactly one Run or governed resource")
        if self.subject_resource_urn is not None:
            subject = parse_resource_urn(self.subject_resource_urn)
            if subject["tenant_id"] != self.tenant_id:
                raise ValueError("incident subject tenant must match incident tenant")
        if self.trigger_observation_id is not None and self.run_id is None:
            raise ValueError("attempt observation incidents must bind a Run")
        if (self.state_version == 0) != (self.status == IncidentStatus.OPEN):
            raise ValueError("open incident status is only valid at state version zero")
        if self.updated_at < self.opened_at:
            raise ValueError("incident updated_at cannot precede opened_at")
        expected = data_incident_fingerprint(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            dedupe_key=self.dedupe_key,
            incident_type=self.incident_type,
            severity=self.severity,
            summary=self.summary,
            trigger_observation_id=self.trigger_observation_id,
            details=self.details,
            detected_by=self.detected_by,
            opened_at=self.opened_at,
            subject_resource_urn=self.subject_resource_urn,
        )
        if self.incident_sha256 != expected:
            raise ValueError("incident_sha256 does not match immutable incident binding")
        return self


class DataIncidentEvent(FrozenContract):
    schema_id = "data_incident_event"

    tenant_id: TenantId
    event_id: UUID
    incident_id: UUID
    sequence_no: Annotated[int, Field(ge=0)]
    from_status: IncidentStatus | None = None
    to_status: IncidentStatus
    actor_subject: NonEmptyText
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _utc_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _valid_event(self) -> "DataIncidentEvent":
        if self.sequence_no == 0:
            if self.from_status is not None or self.to_status != IncidentStatus.OPEN:
                raise ValueError("sequence zero must initialize open incident status")
        else:
            if self.from_status is None:
                raise ValueError("non-initial incident events require from_status")
            validate_incident_transition(self.from_status, self.to_status)
        return self


class IncidentNotification(FrozenContract):
    schema_id = "incident_notification"

    tenant_id: TenantId
    notification_id: UUID
    incident_id: UUID
    incident_event_id: UUID
    incident_sequence_no: Annotated[int, Field(ge=0)]
    channel: IncidentNotificationChannel
    destination_ref: ShortName
    status: IncidentNotificationStatus = IncidentNotificationStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=100)] = 10
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
    def _utc_delivery_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_delivery(self) -> IncidentNotification:
        expected_destination_prefix = f"{self.channel.value}:"
        if not self.destination_ref.startswith(expected_destination_prefix):
            raise ValueError("notification destination must match its channel")
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("notification claim owner and expiry must be set together")
        if self.status == IncidentNotificationStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending notification cannot be claimed or completed")
        elif self.status == IncidentNotificationStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight notification requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("completed notification must release its claim")
        return self


class IncidentNotificationEnvelope(FrozenContract):
    schema_id = "incident_notification_envelope"

    notification: IncidentNotification
    incident: DataIncident
    event: DataIncidentEvent

    @model_validator(mode="after")
    def _consistent_binding(self) -> IncidentNotificationEnvelope:
        if len(
            {
                self.notification.tenant_id,
                self.incident.tenant_id,
                self.event.tenant_id,
            }
        ) != 1:
            raise ValueError("notification envelope tenants must match")
        if self.notification.incident_id != self.incident.incident_id:
            raise ValueError("notification must bind the incident")
        if self.notification.incident_event_id != self.event.event_id:
            raise ValueError("notification must bind the incident event")
        if self.event.incident_id != self.incident.incident_id:
            raise ValueError("notification event must belong to the incident")
        if self.notification.incident_sequence_no != self.event.sequence_no:
            raise ValueError("notification sequence must match the incident event")
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
    SourceAdapterBinding,
    SourceSyncGovernanceContract,
    SourceSyncDefinitionVersion,
    PostgresqlCdcFailoverRecoveryPlan,
    PostgresqlCdcFailoverResnapshotAdmission,
    SourceSyncCheckpoint,
    SourceSyncCommit,
    SourceSyncCommitGovernanceEvidence,
    SourceSyncQuarantineEvidence,
    PlatformCommand,
    Resource,
    ResourceVersion,
    PlatformDefinitionVersion,
    ResourceBinding,
    PlatformRun,
    PlatformRunEvent,
    DataIncident,
    DataIncidentEvent,
    IncidentNotification,
    IncidentNotificationEnvelope,
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
