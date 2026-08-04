"""Governed admission contracts for externally materialized DataOps windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .dataops_invocation import (
    DATAOPS_INVOCATION_SEMANTIC_TYPE,
    DataOpsInvocation,
    build_dataops_invocation_resources,
)
from .platform_authorization import build_policy_decision_artifact
from .platform_contracts import (
    Artifact,
    PlatformCommand,
    PlatformRun,
    PolicyDecision,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunPolicyReferences,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)

DATAOPS_SCHEDULE_WINDOW_SCHEMA = "gda.dataops_schedule_window.v1"
DATAOPS_SCHEDULE_IDEMPOTENCY_PREFIX = "dataops-schedule-window:v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


class DataOpsScheduleWindowSpec(_FrozenModel):
    """One exact window supplied by an external schedule source or recovery scan."""

    tenant_id: TenantId
    definition_version_id: UUID
    schedule_ref: str = Field(min_length=3, max_length=512)
    scheduled_for: datetime
    logical_start: datetime
    logical_end: datetime
    input_bindings: tuple[ResourceBinding, ...] = ()
    execution_plan_artifact_id: UUID
    workload_subject_id: str = Field(min_length=3, max_length=512)
    workload_roles: tuple[str, ...] = ("platform_operator",)
    purpose: str = Field(min_length=3, max_length=1024)
    policy_version_ref: str = Field(min_length=3, max_length=1024)
    policy_evaluator_subject: str = Field(min_length=3, max_length=512)
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    config_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    invocation_owner_ref: str = Field(default="team:data-platform", min_length=3)

    @field_validator("scheduled_for", "logical_start", "logical_end")
    @classmethod
    def _utc_timestamp(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @field_validator(
        "schedule_ref",
        "workload_subject_id",
        "purpose",
        "policy_version_ref",
        "policy_evaluator_subject",
        "invocation_owner_ref",
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("schedule window text fields must not be blank")
        return normalized

    @field_validator("workload_roles")
    @classmethod
    def _canonical_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(item.strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("workload roles must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("workload roles must not contain duplicates")
        return normalized

    @field_validator("input_bindings")
    @classmethod
    def _canonical_bindings(
        cls, value: tuple[ResourceBinding, ...]
    ) -> tuple[ResourceBinding, ...]:
        names = [binding.binding_name for binding in value]
        if len(names) != len(set(names)):
            raise ValueError("schedule window input binding names must be unique")
        if "invocation" in names:
            raise ValueError("the controller owns the invocation input binding")
        return tuple(sorted(value, key=lambda item: item.binding_name))

    @model_validator(mode="after")
    def _consistent_window(self) -> DataOpsScheduleWindowSpec:
        if self.logical_start >= self.logical_end:
            raise ValueError("logical_start must be earlier than logical_end")
        workload_actor = f"workload:{self.workload_subject_id}"
        if self.policy_evaluator_subject == workload_actor:
            raise ValueError("policy evaluator must be independent from the workload")
        return self


def dataops_schedule_window_fingerprint(spec: DataOpsScheduleWindowSpec) -> str:
    """Return the stable identity of a window, independent of recovery time."""
    return canonical_json_fingerprint(
        {
            "schema": DATAOPS_SCHEDULE_WINDOW_SCHEMA,
            "tenant_id": spec.tenant_id,
            "definition_version_id": str(spec.definition_version_id),
            "schedule_ref": spec.schedule_ref,
            "scheduled_for": spec.scheduled_for.isoformat(),
            "logical_start": spec.logical_start.isoformat(),
            "logical_end": spec.logical_end.isoformat(),
            "window_semantics": "half_open",
        }
    )


def dataops_schedule_run_id(spec: DataOpsScheduleWindowSpec) -> UUID:
    fingerprint = dataops_schedule_window_fingerprint(spec)
    return uuid5(
        spec.definition_version_id,
        f"dataops-schedule-window:{spec.tenant_id}:{fingerprint}",
    )


def dataops_schedule_idempotency_key(spec: DataOpsScheduleWindowSpec) -> str:
    return (
        f"{DATAOPS_SCHEDULE_IDEMPOTENCY_PREFIX}:"
        f"{dataops_schedule_window_fingerprint(spec)}"
    )


def dataops_schedule_lock_keys(spec: DataOpsScheduleWindowSpec) -> tuple[int, int]:
    """Map a window identity to PostgreSQL's two signed advisory-lock integers."""
    raw = bytes.fromhex(dataops_schedule_window_fingerprint(spec))
    return (
        int.from_bytes(raw[:4], byteorder="big", signed=True),
        int.from_bytes(raw[4:8], byteorder="big", signed=True),
    )


class ScheduledDataOpsSubmission(_FrozenModel):
    """Complete immutable objects written by one atomic gateway transaction."""

    window_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_at: datetime
    invocation: DataOpsInvocation
    invocation_resource: Resource
    invocation_version: ResourceVersion
    policy_artifact: Artifact
    run: PlatformRun

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "admitted_at")

    @model_validator(mode="after")
    def _consistent_submission(self) -> ScheduledDataOpsSubmission:
        invocation = self.invocation
        run = self.run
        if invocation.trigger_kind != "schedule":
            raise ValueError("schedule controller requires a schedule invocation")
        if len(invocation.schedule_times) != 1:
            raise ValueError("schedule invocation requires exactly one schedule time")
        if invocation.requested_at != self.admitted_at:
            raise ValueError("invocation requested_at must equal admitted_at")
        if run.submitted_at != self.admitted_at:
            raise ValueError("Run submitted_at must equal admitted_at")
        if len({invocation.tenant_id, run.tenant_id}) != 1:
            raise ValueError("invocation and Run tenants must match")
        if invocation.definition_version_id != run.definition_version_id:
            raise ValueError("invocation and Run definitions must match")
        invocation_bindings = [
            binding
            for binding in run.input_bindings
            if binding.binding_name == "invocation"
        ]
        if len(invocation_bindings) != 1:
            raise ValueError("Run must bind exactly one invocation")
        binding = invocation_bindings[0]
        if (
            binding.resource_version_id
            != self.invocation_version.resource_version_id
            or binding.semantic_type != DATAOPS_INVOCATION_SEMANTIC_TYPE
        ):
            raise ValueError("Run invocation binding does not match its version")
        if (
            run.policy_refs is None
            or run.policy_refs.policy_decision_artifact_id
            != self.policy_artifact.artifact_id
        ):
            raise ValueError("Run must bind the generated policy artifact")
        return self


def build_scheduled_dataops_submission(
    spec: DataOpsScheduleWindowSpec,
    *,
    admitted_at: datetime,
) -> ScheduledDataOpsSubmission:
    """Build one content-bound schedule submission using its first admission time."""
    admitted = _aware_utc(admitted_at, "admitted_at")
    window_sha256 = dataops_schedule_window_fingerprint(spec)
    run_id = dataops_schedule_run_id(spec)
    actor = f"workload:{spec.workload_subject_id}"
    invocation = DataOpsInvocation.create(
        tenant_id=spec.tenant_id,
        definition_version_id=spec.definition_version_id,
        trigger_kind="schedule",
        logical_start=spec.logical_start,
        logical_end=spec.logical_end,
        schedule_times=(spec.scheduled_for,),
        schedule_ref=spec.schedule_ref,
        requested_by=actor,
        requested_at=admitted,
    )
    invocation_resource, invocation_version = build_dataops_invocation_resources(
        invocation,
        owner_ref=spec.invocation_owner_ref,
    )
    subject = SubjectContext(
        tenant_id=spec.tenant_id,
        subject_id=spec.workload_subject_id,
        subject_type="workload",
        roles=spec.workload_roles,
        purpose=spec.purpose,
        trace_id=f"schedule-{window_sha256[:16]}",
    )
    bindings = tuple(
        sorted(
            (
                *spec.input_bindings,
                ResourceBinding(
                    binding_name="invocation",
                    resource_version_id=invocation_version.resource_version_id,
                    semantic_type=DATAOPS_INVOCATION_SEMANTIC_TYPE,
                ),
            ),
            key=lambda item: item.binding_name,
        )
    )
    decision = PolicyDecision(
        tenant_id=spec.tenant_id,
        run_id=run_id,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=spec.definition_version_id,
        resource_version_ids=tuple(
            sorted(
                {
                    spec.definition_version_id,
                    *(binding.resource_version_id for binding in bindings),
                },
                key=str,
            )
        ),
        execution_plan_artifact_id=spec.execution_plan_artifact_id,
        effect="allow",
        policy_version_ref=spec.policy_version_ref,
        evaluator_subject=spec.policy_evaluator_subject,
        requires_approval=False,
        obligations=(),
        decided_at=admitted,
        expires_at=admitted + timedelta(seconds=spec.policy_ttl_seconds),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    run = PlatformRun(
        tenant_id=spec.tenant_id,
        run_id=run_id,
        definition_version_id=spec.definition_version_id,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=bindings,
        idempotency_key=dataops_schedule_idempotency_key(spec),
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_artifact.artifact_id
        ),
        config_fingerprint=spec.config_fingerprint,
        submitted_at=admitted,
    )
    return ScheduledDataOpsSubmission(
        window_sha256=window_sha256,
        admitted_at=admitted,
        invocation=invocation,
        invocation_resource=invocation_resource,
        invocation_version=invocation_version,
        policy_artifact=policy_artifact,
        run=run,
    )


@dataclass(frozen=True)
class ScheduleWindowWriteResult:
    window_sha256: str
    admitted_at: datetime
    invocation: DataOpsInvocation
    run: PlatformRun
    command: PlatformCommand
    invocation_resource_created: bool
    invocation_version_created: bool
    policy_artifact_created: bool
    run_created: bool
    command_created: bool

    @property
    def created(self) -> bool:
        return any(
            (
                self.invocation_resource_created,
                self.invocation_version_created,
                self.policy_artifact_created,
                self.run_created,
                self.command_created,
            )
        )

    def recovery_lag_seconds(self, scheduled_for: datetime) -> float:
        scheduled = _aware_utc(scheduled_for, "scheduled_for")
        return max(0.0, (self.admitted_at - scheduled).total_seconds())


class ScheduleWindowGateway(Protocol):
    def submit_schedule_window(
        self, spec: DataOpsScheduleWindowSpec
    ) -> ScheduleWindowWriteResult: ...


class DataOpsScheduleController:
    """Admit exact windows without owning cron, timers, or provider execution."""

    def __init__(self, gateway: ScheduleWindowGateway):
        self.gateway = gateway

    def submit_window(
        self, spec: DataOpsScheduleWindowSpec
    ) -> ScheduleWindowWriteResult:
        return self.gateway.submit_schedule_window(spec)

    def recover_windows(
        self, specs: tuple[DataOpsScheduleWindowSpec, ...]
    ) -> tuple[ScheduleWindowWriteResult, ...]:
        identities = [dataops_schedule_window_fingerprint(spec) for spec in specs]
        if len(identities) != len(set(identities)):
            raise ValueError("recovery input contains duplicate schedule windows")
        ordered = sorted(
            specs,
            key=lambda item: (
                item.scheduled_for,
                item.logical_start,
                dataops_schedule_window_fingerprint(item),
            ),
        )
        return tuple(self.submit_window(spec) for spec in ordered)
