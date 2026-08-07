"""Governed admission contracts for human-requested DataOps cancellation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_authorization import build_policy_decision_artifact
from .platform_contracts import (
    Artifact,
    NonEmptyText,
    PlatformCommand,
    PlatformRun,
    PolicyDecision,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

DATAOPS_CANCEL_REQUEST_SCHEMA = "gda.dataops_cancel_request.v1"
DATAOPS_CANCEL_COMMAND_SCHEMA = "gda.dolphinscheduler_cancel_command.v1"
_DATAOPS_CANCEL_COMMAND_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/dataops-cancel-command/v1",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataOpsCancelRequest(_FrozenModel):
    """Canonical client-owned fields for governed DataOps cancellation."""

    run_id: UUID
    client_request_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    expected_state_version: int = Field(ge=1)
    reason: NonEmptyText


class DataOpsCancelResponse(_FrozenModel):
    """Canonical cancellation admission returned by every client surface."""

    request_sha256: Sha256
    admitted_at: datetime
    run: PlatformRun
    policy_artifact: Artifact
    command: PlatformCommand
    policy_artifact_created: bool
    command_created: bool


class DataOpsCancelSpec(_FrozenModel):
    """One authenticated human cancellation request and its server profile."""

    tenant_id: TenantId
    run_id: UUID
    client_request_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    expected_state_version: int = Field(ge=1)
    requester_subject: str = Field(
        min_length=7,
        max_length=512,
        pattern=r"^human:[^\s]+$",
    )
    reason: str = Field(min_length=3, max_length=1024)
    workload_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_version_ref: str = Field(min_length=3, max_length=1024)
    policy_evaluator_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)

    @field_validator(
        "client_request_id",
        "requester_subject",
        "reason",
        "workload_subject",
        "policy_version_ref",
        "policy_evaluator_subject",
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cancel request text fields must not be blank")
        return normalized

    @model_validator(mode="after")
    def _independent_evaluator(self) -> DataOpsCancelSpec:
        if self.policy_evaluator_subject == self.workload_subject:
            raise ValueError("policy evaluator must be independent from the workload")
        return self


def dataops_cancel_request_identity(spec: DataOpsCancelSpec) -> str:
    """Return the tenant/run-scoped retry identity."""
    return canonical_json_fingerprint(
        {
            "schema": DATAOPS_CANCEL_REQUEST_SCHEMA,
            "tenant_id": spec.tenant_id,
            "run_id": str(spec.run_id),
            "client_request_id": spec.client_request_id,
        }
    )


def dataops_cancel_request_fingerprint(spec: DataOpsCancelSpec) -> str:
    """Fingerprint every immutable field bound to the retry identity."""
    return canonical_json_fingerprint(
        {
            "schema": DATAOPS_CANCEL_REQUEST_SCHEMA,
            **spec.model_dump(mode="json"),
        }
    )


def dataops_cancel_command_id(spec: DataOpsCancelSpec) -> UUID:
    return uuid5(
        _DATAOPS_CANCEL_COMMAND_NAMESPACE,
        f"{spec.tenant_id}:{spec.run_id}:{spec.client_request_id}",
    )


def dataops_cancel_lock_keys(spec: DataOpsCancelSpec) -> tuple[int, int]:
    raw = bytes.fromhex(dataops_cancel_request_identity(spec))
    return (
        int.from_bytes(raw[:4], byteorder="big", signed=True),
        int.from_bytes(raw[4:8], byteorder="big", signed=True),
    )


class DataOpsCancelSubmission(_FrozenModel):
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_at: datetime
    policy_artifact: Artifact
    command: PlatformCommand

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("admitted_at must include a timezone")
        return value.astimezone(UTC)


@dataclass(frozen=True)
class DataOpsCancelWriteResult:
    request_sha256: str
    admitted_at: datetime
    run: PlatformRun
    policy_artifact: Artifact
    command: PlatformCommand
    policy_artifact_created: bool
    command_created: bool

    @property
    def created(self) -> bool:
        return self.command_created


def build_dataops_cancel_submission(
    spec: DataOpsCancelSpec,
    run: PlatformRun,
    execution_plan: Artifact,
    *,
    admitted_at: datetime,
) -> DataOpsCancelSubmission:
    admitted = admitted_at.astimezone(UTC)
    run_actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    if run.tenant_id != spec.tenant_id or run.run_id != spec.run_id:
        raise ValueError("cancel request does not match the Run identity")
    if run.orchestration_class.value != "dataops":
        raise ValueError("only DataOps Runs can use DolphinScheduler cancellation")
    if run_actor != spec.workload_subject:
        raise ValueError("Run workload does not match the configured cancel executor")
    if execution_plan.tenant_id != run.tenant_id:
        raise ValueError("execution plan tenant does not match the Run")

    request_sha256 = dataops_cancel_request_fingerprint(spec)
    decision = PolicyDecision(
        tenant_id=run.tenant_id,
        run_id=run.run_id,
        subject_context=run.subject_context,
        action="dolphinscheduler.cancel",
        definition_version_id=run.definition_version_id,
        resource_version_ids=tuple(
            sorted(
                {
                    run.definition_version_id,
                    *(binding.resource_version_id for binding in run.input_bindings),
                },
                key=str,
            )
        ),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref=spec.policy_version_ref,
        evaluator_subject=spec.policy_evaluator_subject,
        requires_approval=False,
        obligations=(),
        decided_at=admitted,
        expires_at=admitted + timedelta(seconds=spec.policy_ttl_seconds),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    identity = dataops_cancel_request_identity(spec)
    dedupe_key = f"dolphinscheduler.cancel:{run.run_id}:{identity}"
    command = PlatformCommand(
        tenant_id=run.tenant_id,
        command_id=dataops_cancel_command_id(spec),
        run_id=run.run_id,
        command_type="dolphinscheduler.cancel",
        execution_plan_artifact_id=execution_plan.artifact_id,
        dedupe_key=dedupe_key,
        actor_subject=run_actor,
        payload={
            "schema": DATAOPS_CANCEL_COMMAND_SCHEMA,
            "client_request_id": spec.client_request_id,
            "request_sha256": request_sha256,
            "requester_subject": spec.requester_subject,
            "reason": spec.reason,
            "expected_state_version": spec.expected_state_version,
            "policy_decision_artifact_id": str(policy_artifact.artifact_id),
            "policy_decision_sha256": policy_artifact.content_sha256,
        },
        available_at=admitted,
        created_at=admitted,
    )
    return DataOpsCancelSubmission(
        request_sha256=request_sha256,
        admitted_at=admitted,
        policy_artifact=policy_artifact,
        command=command,
    )
