"""Governed admission contracts for human-requested DataOps runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

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

DATAOPS_MANUAL_REQUEST_SCHEMA = "gda.dataops_manual_request.v1"
DATAOPS_MANUAL_IDEMPOTENCY_PREFIX = "dataops-manual:v1"
_DATAOPS_MANUAL_RUN_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/dataops-manual-run/v1",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


class DataOpsManualTriggerSpec(_FrozenModel):
    """One authenticated human request delegated to a workload executor."""

    tenant_id: TenantId
    client_request_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    definition_version_id: UUID
    logical_start: datetime
    logical_end: datetime
    input_bindings: tuple[ResourceBinding, ...] = ()
    execution_plan_artifact_id: UUID
    requester_subject: str = Field(
        min_length=7,
        max_length=512,
        pattern=r"^human:[^\s]+$",
    )
    workload_subject_id: str = Field(
        min_length=3,
        max_length=512,
        pattern=r"^[^\s]+$",
    )
    workload_roles: tuple[str, ...] = Field(
        default=("platform_operator",), min_length=1
    )
    purpose: str = Field(min_length=3, max_length=1024)
    policy_version_ref: str = Field(min_length=3, max_length=1024)
    policy_evaluator_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    config_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    invocation_owner_ref: str = Field(default="team:data-platform", min_length=3)

    @field_validator("logical_start", "logical_end")
    @classmethod
    def _utc_timestamp(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @field_validator(
        "client_request_id",
        "requester_subject",
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
            raise ValueError("manual request text fields must not be blank")
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
            raise ValueError("manual request input binding names must be unique")
        if "invocation" in names:
            raise ValueError("the gateway owns the invocation input binding")
        return tuple(sorted(value, key=lambda item: item.binding_name))

    @model_validator(mode="after")
    def _consistent_request(self) -> DataOpsManualTriggerSpec:
        if self.logical_start >= self.logical_end:
            raise ValueError("logical_start must be earlier than logical_end")
        if not self.requester_subject.startswith("human:"):
            raise ValueError("manual requester must use a human subject")
        workload_actor = f"workload:{self.workload_subject_id}"
        if self.policy_evaluator_subject == workload_actor:
            raise ValueError("policy evaluator must be independent from the workload")
        return self


def dataops_manual_request_identity(spec: DataOpsManualTriggerSpec) -> str:
    """Return the tenant-scoped retry identity, independent of request payload."""
    return canonical_json_fingerprint(
        {
            "schema": DATAOPS_MANUAL_REQUEST_SCHEMA,
            "tenant_id": spec.tenant_id,
            "client_request_id": spec.client_request_id,
        }
    )


def dataops_manual_request_fingerprint(spec: DataOpsManualTriggerSpec) -> str:
    """Fingerprint every immutable field bound to a client request identity."""
    return canonical_json_fingerprint(
        {
            "schema": DATAOPS_MANUAL_REQUEST_SCHEMA,
            **spec.model_dump(mode="json"),
        }
    )


def dataops_manual_run_id(spec: DataOpsManualTriggerSpec) -> UUID:
    return uuid5(
        _DATAOPS_MANUAL_RUN_NAMESPACE,
        f"{spec.tenant_id}:{spec.client_request_id}",
    )


def dataops_manual_idempotency_key(spec: DataOpsManualTriggerSpec) -> str:
    return f"{DATAOPS_MANUAL_IDEMPOTENCY_PREFIX}:{dataops_manual_request_identity(spec)}"


def dataops_manual_lock_keys(spec: DataOpsManualTriggerSpec) -> tuple[int, int]:
    raw = bytes.fromhex(dataops_manual_request_identity(spec))
    return (
        int.from_bytes(raw[:4], byteorder="big", signed=True),
        int.from_bytes(raw[4:8], byteorder="big", signed=True),
    )


class ManualDataOpsSubmission(_FrozenModel):
    """Complete immutable objects written by one atomic gateway transaction."""

    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    def _consistent_submission(self) -> ManualDataOpsSubmission:
        invocation = self.invocation
        run = self.run
        if invocation.trigger_kind != "manual":
            raise ValueError("manual admission requires a manual invocation")
        if invocation.schedule_times or invocation.schedule_ref is not None:
            raise ValueError("manual invocation must not claim schedule metadata")
        if invocation.requested_at != self.admitted_at:
            raise ValueError("invocation requested_at must equal admitted_at")
        if run.submitted_at != self.admitted_at:
            raise ValueError("Run submitted_at must equal admitted_at")
        if len({invocation.tenant_id, run.tenant_id}) != 1:
            raise ValueError("invocation and Run tenants must match")
        if invocation.definition_version_id != run.definition_version_id:
            raise ValueError("invocation and Run definitions must match")
        if run.subject_context.subject_type.value != "workload":
            raise ValueError("manual Run must execute as a workload")
        if run.subject_context.delegated_by != invocation.requested_by:
            raise ValueError("Run delegation must identify the manual requester")
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


def build_manual_dataops_submission(
    spec: DataOpsManualTriggerSpec,
    *,
    admitted_at: datetime,
) -> ManualDataOpsSubmission:
    """Build one content-bound manual submission using its first admission time."""
    admitted = _aware_utc(admitted_at, "admitted_at")
    request_sha256 = dataops_manual_request_fingerprint(spec)
    request_identity = dataops_manual_request_identity(spec)
    run_id = dataops_manual_run_id(spec)
    invocation = DataOpsInvocation.create(
        tenant_id=spec.tenant_id,
        definition_version_id=spec.definition_version_id,
        trigger_kind="manual",
        logical_start=spec.logical_start,
        logical_end=spec.logical_end,
        requested_by=spec.requester_subject,
        requested_at=admitted,
        client_request_id=spec.client_request_id,
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
        trace_id=f"manual-{request_identity[:16]}",
        delegated_by=spec.requester_subject,
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
        idempotency_key=dataops_manual_idempotency_key(spec),
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_artifact.artifact_id
        ),
        config_fingerprint=spec.config_fingerprint,
        submitted_at=admitted,
    )
    return ManualDataOpsSubmission(
        request_sha256=request_sha256,
        admitted_at=admitted,
        invocation=invocation,
        invocation_resource=invocation_resource,
        invocation_version=invocation_version,
        policy_artifact=policy_artifact,
        run=run,
    )


@dataclass(frozen=True)
class ManualTriggerWriteResult:
    request_sha256: str
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
