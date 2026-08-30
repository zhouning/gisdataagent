"""Provider-neutral Temporal contracts for the AgentOps integration boundary.

The module deliberately has no temporalio dependency. It freezes the identity,
signal, retry and evidence rules that a Temporal adapter must obey, and includes
a deterministic in-memory harness for contract tests. A real worker can replace
the harness without changing AgentSpec/AgentRun evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from .agentops_contracts import (
    AgentDeploymentRevision,
    AgentRole,
    AgentRun,
    AgentRunStatus,
    AgentSideEffect,
    agent_run_fingerprint,
)
from .agentops_task_graph import AgentTaskGraph
from .platform_contracts import (
    FrozenContract,
    NonEmptyText,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)

TEMPORAL_NAMESPACE_SCHEMA = "gda.temporal_namespace_identity.v1"
TEMPORAL_TASK_QUEUE_SCHEMA = "gda.temporal_task_queue_identity.v1"
TEMPORAL_WORKFLOW_SCHEMA = "gda.temporal_workflow_identity.v1"
TEMPORAL_RETRY_SCHEMA = "gda.temporal_retry_policy.v1"
TEMPORAL_INPUT_SCHEMA = "gda.temporal_workflow_input.v1"
TEMPORAL_SIGNAL_SCHEMA = "gda.temporal_signal.v1"
TEMPORAL_ACTIVITY_REQUEST_SCHEMA = "gda.temporal_activity_request.v1"
TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA = "gda.temporal_activity_schedule.v1"
TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA = "gda.temporal_activity_evidence.v1"
TEMPORAL_PROVIDER_EXECUTION_SPEC_SCHEMA = "gda.temporal_provider_execution_spec.v1"
TEMPORAL_TRANSITION_SCHEMA = "gda.temporal_state_transition.v1"
TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA = "gda.temporal_specialist_activity_plan.v1"
TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA = "gda.temporal_task_graph_execution_manifest.v1"

_TEMPORAL_ACTIVITY_NAMESPACE = NAMESPACE_URL


class TemporalContractError(ValueError):
    """Raised when a Temporal binding or durable state boundary is invalid."""


class TemporalIsolationClass(StrEnum):
    SHARED = "shared"
    TENANT = "tenant"
    ISOLATED = "isolated"


class TemporalSignalKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RECONCILE = "reconcile"


class TemporalActivityOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TemporalActivityCancellationType(StrEnum):
    """Provider-neutral subset of Temporal activity cancellation behavior."""

    TRY_CANCEL = "try_cancel"
    WAIT_CANCELLATION_COMPLETED = "wait_cancellation_completed"
    ABANDON = "abandon"


TEMPORAL_TERMINAL_STATES = frozenset(
    {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }
)

TEMPORAL_RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.ACCEPTED: frozenset(
        {AgentRunStatus.PLANNING, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.PLANNING: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.WAITING_REVIEW,
            AgentRunStatus.PAUSED,
            AgentRunStatus.RECONCILING,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.WAITING_REVIEW,
            AgentRunStatus.PAUSED,
            AgentRunStatus.RECONCILING,
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.WAITING_REVIEW: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSED,
            AgentRunStatus.RECONCILING,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.PAUSED: frozenset(
        {AgentRunStatus.RUNNING, AgentRunStatus.RECONCILING, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.RECONCILING: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
}


def _fingerprint(schema_id: str, values: dict[str, object], field: str) -> str:
    payload = dict(values)
    payload.pop(field, None)
    return canonical_json_fingerprint({"schema": schema_id, "data": _json_ready(payload)})


def _json_ready(value: object) -> object:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        normalized = (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def temporal_contract_fingerprint(schema_id: str, values: dict[str, object], field: str) -> str:
    """Fingerprint a Temporal contract without its own hash field."""

    return _fingerprint(schema_id, values, field)


class TemporalNamespaceIdentity(FrozenContract):
    """The namespace/isolation tuple supplied to a Temporal adapter."""

    schema_id: ClassVar[str] = TEMPORAL_NAMESPACE_SCHEMA
    tenant_id: TenantId
    isolation_class: TemporalIsolationClass
    namespace_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    namespace_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_namespace(self) -> TemporalNamespaceIdentity:
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "namespace_sha256")
        if self.namespace_sha256 != expected:
            raise ValueError("namespace_sha256 does not match namespace identity")
        return self


class TemporalTaskQueueIdentity(FrozenContract):
    """Task queue and workload identity, without provider credentials."""

    schema_id: ClassVar[str] = TEMPORAL_TASK_QUEUE_SCHEMA
    tenant_id: TenantId
    namespace_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    queue_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    worker_identity_ref: NonEmptyText
    queue_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_queue(self) -> TemporalTaskQueueIdentity:
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "queue_sha256")
        if self.queue_sha256 != expected:
            raise ValueError("queue_sha256 does not match task queue identity")
        return self


def derive_temporal_workflow_id(
    *,
    tenant_id: str,
    isolation_class: TemporalIsolationClass | str,
    namespace_ref: str,
    workflow_type: str,
    agent_spec_sha256: str,
    deployment_revision_sha256: str,
    idempotency_key: str,
) -> str:
    """Derive an idempotent workflow identity from immutable AgentOps inputs."""

    digest = canonical_json_fingerprint(
        {
            "schema": TEMPORAL_WORKFLOW_SCHEMA,
            "tenant_id": tenant_id,
            "isolation_class": TemporalIsolationClass(isolation_class).value,
            "namespace_ref": namespace_ref,
            "workflow_type": workflow_type,
            "agent_spec_sha256": agent_spec_sha256,
            "deployment_revision_sha256": deployment_revision_sha256,
            "idempotency_key": idempotency_key,
        }
    )
    return f"gda-agent-{tenant_id}-{digest[:48]}"


class TemporalWorkflowIdentity(FrozenContract):
    """Provider-facing identity that remains stable across retries/restarts."""

    schema_id: ClassVar[str] = TEMPORAL_WORKFLOW_SCHEMA
    tenant_id: TenantId
    namespace: TemporalNamespaceIdentity
    task_queue: TemporalTaskQueueIdentity
    workflow_type: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    agent_spec_sha256: Sha256
    deployment_revision_sha256: Sha256
    idempotency_key: NonEmptyText
    workflow_id: str = Field(pattern=r"^[a-z][a-z0-9._:-]{1,254}$")
    identity_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_identity(self) -> TemporalWorkflowIdentity:
        if self.namespace.tenant_id != self.tenant_id:
            raise ValueError("workflow namespace tenant must match workflow tenant")
        if self.task_queue.tenant_id != self.tenant_id:
            raise ValueError("workflow task queue tenant must match workflow tenant")
        if self.task_queue.namespace_ref != self.namespace.namespace_ref:
            raise ValueError("workflow task queue must use the workflow namespace")
        expected_workflow_id = derive_temporal_workflow_id(
            tenant_id=self.tenant_id,
            isolation_class=self.namespace.isolation_class,
            namespace_ref=self.namespace.namespace_ref,
            workflow_type=self.workflow_type,
            agent_spec_sha256=self.agent_spec_sha256,
            deployment_revision_sha256=self.deployment_revision_sha256,
            idempotency_key=self.idempotency_key,
        )
        if self.workflow_id != expected_workflow_id:
            raise ValueError("workflow_id does not match immutable workflow inputs")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "identity_sha256")
        if self.identity_sha256 != expected:
            raise ValueError("identity_sha256 does not match workflow identity")
        return self


class TemporalRetryPolicy(FrozenContract):
    """Deterministic retry limits that can be translated to Temporal options."""

    schema_id: ClassVar[str] = TEMPORAL_RETRY_SCHEMA
    initial_interval_seconds: float = Field(gt=0, le=86_400)
    backoff_coefficient: float = Field(ge=1, le=10)
    max_interval_seconds: float = Field(gt=0, le=86_400)
    max_attempts: int = Field(ge=0, le=100)
    non_retryable_error_types: tuple[NonEmptyText, ...] = ()
    policy_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_policy(self) -> TemporalRetryPolicy:
        if self.max_interval_seconds < self.initial_interval_seconds:
            raise ValueError("retry max interval cannot precede initial interval")
        if self.non_retryable_error_types != tuple(sorted(set(self.non_retryable_error_types))):
            raise ValueError("non-retryable error types must be sorted and unique")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "policy_sha256")
        if self.policy_sha256 != expected:
            raise ValueError("policy_sha256 does not match retry policy")
        return self


class TemporalWorkflowInput(FrozenContract):
    """Input/evidence binding handed to a workflow starter."""

    schema_id: ClassVar[str] = TEMPORAL_INPUT_SCHEMA
    tenant_id: TenantId
    identity: TemporalWorkflowIdentity
    agent_run: AgentRun
    deployment_revision: AgentDeploymentRevision
    task_graph: AgentTaskGraph
    agent_spec_sha256: Sha256
    policy_decision_ref: NonEmptyText
    retry_policy: TemporalRetryPolicy
    subject_context: SubjectContext
    input_artifact_ids: tuple[UUID, ...] = ()
    input_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_input(self) -> TemporalWorkflowInput:
        if self.identity.tenant_id != self.tenant_id:
            raise ValueError("workflow input tenant must match identity tenant")
        if self.agent_run.tenant_id != self.tenant_id:
            raise ValueError("workflow input tenant must match AgentRun tenant")
        if self.deployment_revision.tenant_id != self.tenant_id:
            raise ValueError("workflow input deployment tenant must match workflow tenant")
        if self.agent_run.run_id != self.agent_run.root_run_id:
            raise ValueError("Temporal starter currently accepts a root AgentRun only")
        if (
            self.agent_run.status is not AgentRunStatus.ACCEPTED
            or self.agent_run.state_version != 0
        ):
            raise ValueError("Temporal starter requires an accepted AgentRun at state version zero")
        if self.agent_run.deployment_revision_sha256 != self.identity.deployment_revision_sha256:
            raise ValueError("AgentRun deployment revision must match workflow identity")
        if self.deployment_revision.revision_sha256 != self.identity.deployment_revision_sha256:
            raise ValueError("deployment revision must match workflow identity")
        if self.deployment_revision.agent_spec_sha256 != self.identity.agent_spec_sha256:
            raise ValueError("deployment AgentSpec must match workflow identity")
        if self.agent_spec_sha256 != self.identity.agent_spec_sha256:
            raise ValueError("workflow input AgentSpec must match workflow identity")
        if self.task_graph.tenant_id != self.tenant_id:
            raise ValueError("workflow task graph tenant must match workflow tenant")
        if self.task_graph.run_id != self.agent_run.run_id:
            raise ValueError("workflow task graph must match AgentRun")
        if self.task_graph.agent_spec_sha256 != self.identity.agent_spec_sha256:
            raise ValueError("workflow task graph AgentSpec must match workflow identity")
        if self.task_graph.deployment_revision_sha256 != self.identity.deployment_revision_sha256:
            raise ValueError("workflow task graph deployment must match workflow identity")
        if self.subject_context != self.agent_run.subject_context:
            raise ValueError("workflow input subject context must match AgentRun")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "input_sha256")
        if self.input_sha256 != expected:
            raise ValueError("input_sha256 does not match workflow input")
        return self


class TemporalSignal(FrozenContract):
    """A replayable signal accepted only for the current projected state."""

    schema_id: ClassVar[str] = TEMPORAL_SIGNAL_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    signal_id: UUID
    kind: TemporalSignalKind
    expected_state_version: int = Field(ge=0)
    requested_by: NonEmptyText
    reason: NonEmptyText
    signal_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_signal(self) -> TemporalSignal:
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "signal_sha256")
        if self.signal_sha256 != expected:
            raise ValueError("signal_sha256 does not match signal content")
        return self


def derive_temporal_activity_id(*, run_id: UUID, tool_call_id: UUID, attempt_no: int) -> UUID:
    """Derive a stable provider activity identity for one ToolCall attempt."""

    if attempt_no < 1:
        raise TemporalContractError("activity attempt_no must be positive")
    return uuid5(
        _TEMPORAL_ACTIVITY_NAMESPACE,
        f"gda-temporal-activity:{run_id}:{tool_call_id}:{attempt_no}",
    )


class TemporalProviderExecutionSpec(FrozenContract):
    """Immutable provider/operation binding carried by a specialist activity.

    The binding names a capability implementation, while artifact UUIDs remain the
    only input references.  A worker must resolve those references through the
    artifact authority; storage locations and credentials never become part of the
    workflow contract.
    """

    schema_id: ClassVar[str] = TEMPORAL_PROVIDER_EXECUTION_SPEC_SCHEMA
    provider_ref: NonEmptyText
    operation_ref: NonEmptyText
    parameters: dict[str, object] = Field(default_factory=dict)
    input_artifact_ids: tuple[UUID, ...] = ()
    output_media_type: NonEmptyText = "application/json"
    spec_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_spec(self) -> TemporalProviderExecutionSpec:
        if self.input_artifact_ids != tuple(sorted(set(self.input_artifact_ids), key=str)):
            raise ValueError("provider input artifact ids must be sorted and unique")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "spec_sha256")
        if self.spec_sha256 != expected:
            raise ValueError("spec_sha256 does not match provider execution spec")
        return self


class TemporalActivityRequest(FrozenContract):
    """Immutable dispatch input for one governed Temporal activity attempt."""

    schema_id: ClassVar[str] = TEMPORAL_ACTIVITY_REQUEST_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int = Field(ge=1)
    tool_ref: NonEmptyText
    capability_ref: NonEmptyText
    policy_decision_ref: NonEmptyText
    subject_context: SubjectContext
    side_effect: AgentSideEffect
    idempotency_key: NonEmptyText
    input_artifact_ids: tuple[UUID, ...] = ()
    provider_spec: TemporalProviderExecutionSpec | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    request_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_request(self) -> TemporalActivityRequest:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("activity request subject tenant must match tenant_id")
        if self.activity_id != derive_temporal_activity_id(
            run_id=self.run_id,
            tool_call_id=self.tool_call_id,
            attempt_no=self.attempt_no,
        ):
            raise ValueError("activity_id does not match ToolCall attempt identity")
        if self.provider_spec is not None and self.provider_spec.input_artifact_ids:
            if not set(self.provider_spec.input_artifact_ids).issubset(
                set(self.input_artifact_ids)
            ):
                raise ValueError(
                    "provider execution spec input artifacts are not present in activity request"
                )
        fingerprint_values = self.model_dump(mode="json")
        if self.provider_spec is None:
            fingerprint_values.pop("provider_spec", None)
        expected = _fingerprint(self.schema_id, fingerprint_values, "request_sha256")
        if self.request_sha256 != expected:
            raise ValueError("request_sha256 does not match activity request")
        return self


class TemporalActivitySchedulePlan(FrozenContract):
    """Replayable Temporal scheduling options for one explicit platform attempt."""

    schema_id: ClassVar[str] = TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int = Field(ge=1)
    activity_type: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    task_queue_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    task_queue_sha256: Sha256
    request: TemporalActivityRequest
    request_sha256: Sha256
    schedule_to_close_timeout_seconds: float = Field(gt=0, le=604_800)
    start_to_close_timeout_seconds: float = Field(gt=0, le=604_800)
    heartbeat_timeout_seconds: float = Field(gt=0, le=86_400)
    cancellation_type: TemporalActivityCancellationType
    sdk_maximum_attempts: Literal[1] = 1
    schedule_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_schedule(self) -> TemporalActivitySchedulePlan:
        request = self.request
        if (
            request.tenant_id != self.tenant_id
            or request.workflow_id != self.workflow_id
            or request.run_id != self.run_id
            or request.step_id != self.step_id
            or request.tool_call_id != self.tool_call_id
            or request.activity_id != self.activity_id
            or request.attempt_no != self.attempt_no
        ):
            raise ValueError("activity schedule correlation differs from request")
        if self.request_sha256 != request.request_sha256:
            raise ValueError("activity schedule request_sha256 differs from request")
        if self.schedule_to_close_timeout_seconds < self.start_to_close_timeout_seconds:
            raise ValueError("schedule-to-close timeout cannot precede start-to-close timeout")
        if self.heartbeat_timeout_seconds > self.start_to_close_timeout_seconds:
            raise ValueError("heartbeat timeout cannot exceed start-to-close timeout")
        if (
            request.side_effect is not AgentSideEffect.NONE
            and self.cancellation_type
            is not TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
        ):
            raise ValueError("side-effecting activity must wait for cancellation completion")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "schedule_sha256")
        if self.schedule_sha256 != expected:
            raise ValueError("schedule_sha256 does not match activity schedule")
        return self


class TemporalSpecialistActivityPlan(FrozenContract):
    """Immutable execution binding for one graph specialist.

    The task graph decides ordering and identity. This plan decides which governed tool
    invocation represents the specialist and how its activity is scheduled. Keeping the
    binding outside ``AgentTaskStep`` avoids turning the provider-neutral graph into a
    provider-specific scheduler contract.
    """

    schema_id: ClassVar[str] = TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    agent_id: str
    role: AgentRole
    sequence_no: int = Field(ge=0)
    activity_type: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    task_queue_ref: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,62}$")
    task_queue_sha256: Sha256
    tool_ref: NonEmptyText
    capability_ref: NonEmptyText
    policy_decision_ref: NonEmptyText
    subject_context: SubjectContext
    side_effect: AgentSideEffect
    idempotency_key: NonEmptyText
    provider_spec: TemporalProviderExecutionSpec | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    schedule_to_close_timeout_seconds: float = Field(gt=0, le=604_800)
    start_to_close_timeout_seconds: float = Field(gt=0, le=604_800)
    heartbeat_timeout_seconds: float = Field(gt=0, le=86_400)
    cancellation_type: TemporalActivityCancellationType = (
        TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
    )
    sdk_maximum_attempts: Literal[1] = 1
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> TemporalSpecialistActivityPlan:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("specialist activity subject tenant must match tenant_id")
        if self.schedule_to_close_timeout_seconds < self.start_to_close_timeout_seconds:
            raise ValueError("schedule-to-close timeout cannot precede start-to-close timeout")
        if self.heartbeat_timeout_seconds > self.start_to_close_timeout_seconds:
            raise ValueError("heartbeat timeout cannot exceed start-to-close timeout")
        if (
            self.side_effect is not AgentSideEffect.NONE
            and self.cancellation_type
            is not TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED
        ):
            raise ValueError(
                "side-effecting specialist activity must wait for cancellation completion"
            )
        fingerprint_values = self.model_dump(mode="json")
        if self.provider_spec is None:
            fingerprint_values.pop("provider_spec", None)
        expected = _fingerprint(self.schema_id, fingerprint_values, "plan_sha256")
        if self.plan_sha256 != expected:
            raise ValueError("plan_sha256 does not match specialist activity plan")
        return self


class TemporalTaskGraphExecutionManifest(FrozenContract):
    """Hash-bound activity bindings for one immutable multi-agent task graph."""

    schema_id: ClassVar[str] = TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    graph_sha256: Sha256
    plans: tuple[TemporalSpecialistActivityPlan, ...] = Field(min_length=2)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_manifest(self) -> TemporalTaskGraphExecutionManifest:
        if any(plan.tenant_id != self.tenant_id for plan in self.plans):
            raise ValueError("specialist activity plan tenant differs from manifest")
        if any(plan.workflow_id != self.workflow_id for plan in self.plans):
            raise ValueError("specialist activity plan workflow differs from manifest")
        if any(plan.run_id != self.run_id for plan in self.plans):
            raise ValueError("specialist activity plan run differs from manifest")
        step_ids = tuple(plan.step_id for plan in self.plans)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("specialist activity plan step ids must be unique")
        agent_ids = tuple(plan.agent_id for plan in self.plans)
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("specialist activity plan agent ids must be unique")
        if tuple(plan.sequence_no for plan in self.plans) != tuple(range(len(self.plans))):
            raise ValueError("specialist activity plans must follow contiguous graph sequence")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "manifest_sha256")
        if self.manifest_sha256 != expected:
            raise ValueError("manifest_sha256 does not match execution manifest")
        return self


class TemporalActivityEvidence(FrozenContract):
    """Provider outcome and evidence for one typed tool/activity attempt."""

    schema_id: ClassVar[str] = TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    activity_id: UUID
    tool_call_id: UUID
    idempotency_key: NonEmptyText
    side_effect: AgentSideEffect
    outcome: TemporalActivityOutcome
    policy_decision_ref: NonEmptyText
    output_artifact_id: UUID | None = None
    external_receipt_artifact_id: UUID | None = None
    provider_operation_ref: NonEmptyText | None = None
    failure_type: NonEmptyText | None = None
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_evidence(self) -> TemporalActivityEvidence:
        if self.side_effect is AgentSideEffect.NONE and self.external_receipt_artifact_id:
            raise ValueError("read-only activity cannot carry an external receipt")
        if self.outcome is TemporalActivityOutcome.SUCCEEDED:
            if self.output_artifact_id is None:
                raise ValueError("successful activity requires an output artifact")
            if self.side_effect is AgentSideEffect.EXTERNAL_WRITE and (
                self.external_receipt_artifact_id is None
            ):
                raise ValueError("external write requires an external receipt artifact")
        if self.outcome is TemporalActivityOutcome.UNKNOWN:
            if self.provider_operation_ref is None:
                raise ValueError("unknown activity outcome requires provider operation ref")
        if self.outcome is TemporalActivityOutcome.FAILED and self.failure_type is None:
            raise ValueError("failed activity requires a failure type")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "evidence_sha256")
        if self.evidence_sha256 != expected:
            raise ValueError("evidence_sha256 does not match activity evidence")
        return self


class TemporalStateTransition(FrozenContract):
    """Small immutable projection of a workflow state change."""

    schema_id: ClassVar[str] = TEMPORAL_TRANSITION_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    sequence_no: int = Field(ge=0)
    from_status: AgentRunStatus | None = None
    to_status: AgentRunStatus
    actor_ref: NonEmptyText
    reason: NonEmptyText
    transition_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_transition(self) -> TemporalStateTransition:
        if self.sequence_no == 0:
            if self.from_status is not None or self.to_status is not AgentRunStatus.ACCEPTED:
                raise ValueError("sequence zero must initialize accepted AgentRun")
        elif self.from_status is None:
            raise ValueError("non-initial Temporal transition requires from_status")
        elif self.to_status not in TEMPORAL_RUN_TRANSITIONS.get(self.from_status, frozenset()):
            raise ValueError(
                f"Temporal transition {self.from_status.value!r} -> "
                f"{self.to_status.value!r} is not allowed"
            )
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "transition_sha256")
        if self.transition_sha256 != expected:
            raise ValueError("transition_sha256 does not match transition content")
        return self


@dataclass(frozen=True)
class TemporalWorkflowSnapshot:
    """Deterministic harness projection; Temporal remains the future provider."""

    workflow_input: TemporalWorkflowInput
    run: AgentRun
    history: tuple[TemporalStateTransition, ...] = ()
    activity_evidence: tuple[TemporalActivityEvidence, ...] = ()
    signals: tuple[TemporalSignal, ...] = ()


def validate_temporal_run_transition(
    from_status: AgentRunStatus | str, to_status: AgentRunStatus | str
) -> None:
    try:
        source = AgentRunStatus(from_status)
        target = AgentRunStatus(to_status)
    except ValueError as exc:
        raise TemporalContractError(str(exc)) from exc
    if target not in TEMPORAL_RUN_TRANSITIONS.get(source, frozenset()):
        raise TemporalContractError(
            f"Temporal transition {source.value!r} -> {target.value!r} is not allowed"
        )


def _replace_run(run: AgentRun, *, status: AgentRunStatus, state_version: int) -> AgentRun:
    values = run.model_dump(mode="json")
    values["status"] = status.value
    values["state_version"] = state_version
    values["run_sha256"] = agent_run_fingerprint(values)
    return AgentRun(**values)


class TemporalIntegrationHarness:
    """Deterministic adapter contract for tests and future provider integration."""

    def __init__(self) -> None:
        self._workflows: dict[str, TemporalWorkflowSnapshot] = {}
        self._signals: dict[UUID, TemporalSignal] = {}

    def start(self, workflow_input: TemporalWorkflowInput) -> TemporalWorkflowSnapshot:
        workflow_id = workflow_input.identity.workflow_id
        existing = self._workflows.get(workflow_id)
        if existing is not None:
            if existing.run.run_id != workflow_input.agent_run.run_id:
                raise TemporalContractError(
                    "workflow id collision has a different AgentRun identity"
                )
            if existing.workflow_input.input_sha256 != workflow_input.input_sha256:
                raise TemporalContractError(
                    "workflow id was reused with different workflow input evidence"
                )
            return existing
        initial_values = {
            "tenant_id": workflow_input.tenant_id,
            "workflow_id": workflow_id,
            "run_id": workflow_input.agent_run.run_id,
            "sequence_no": 0,
            "from_status": None,
            "to_status": AgentRunStatus.ACCEPTED,
            "actor_ref": "workload:temporal-adapter",
            "reason": "workflow accepted",
        }
        initial_values["transition_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_TRANSITION_SCHEMA, initial_values, "transition_sha256"
        )
        transition = TemporalStateTransition(**initial_values)
        snapshot = TemporalWorkflowSnapshot(
            workflow_input=workflow_input,
            run=workflow_input.agent_run,
            history=(transition,),
            signals=(),
        )
        self._workflows[workflow_id] = snapshot
        return snapshot

    def get(self, workflow_id: str) -> TemporalWorkflowSnapshot:
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            raise TemporalContractError(f"unknown workflow id: {workflow_id}") from exc

    def transition(
        self,
        workflow_id: str,
        to_status: AgentRunStatus,
        *,
        actor_ref: str,
        reason: str,
    ) -> TemporalWorkflowSnapshot:
        snapshot = self.get(workflow_id)
        from_status = snapshot.run.status
        validate_temporal_run_transition(from_status, to_status)
        next_state_version = snapshot.run.state_version + 1
        values = {
            "tenant_id": snapshot.workflow_input.tenant_id,
            "workflow_id": workflow_id,
            "run_id": snapshot.run.run_id,
            "sequence_no": next_state_version,
            "from_status": from_status,
            "to_status": to_status,
            "actor_ref": actor_ref,
            "reason": reason,
        }
        values["transition_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_TRANSITION_SCHEMA, values, "transition_sha256"
        )
        event = TemporalStateTransition(**values)
        updated = TemporalWorkflowSnapshot(
            workflow_input=snapshot.workflow_input,
            run=_replace_run(snapshot.run, status=to_status, state_version=next_state_version),
            history=(*snapshot.history, event),
            activity_evidence=snapshot.activity_evidence,
            signals=snapshot.signals,
        )
        self._workflows[workflow_id] = updated
        return updated

    def apply_signal(self, signal: TemporalSignal) -> TemporalWorkflowSnapshot:
        previous_signal = self._signals.get(signal.signal_id)
        if previous_signal is not None:
            if previous_signal != signal:
                raise TemporalContractError("signal id was reused with different content")
            return self.get(signal.workflow_id)
        snapshot = self.get(signal.workflow_id)
        if snapshot.workflow_input.tenant_id != signal.tenant_id:
            raise TemporalContractError("signal tenant does not match workflow")
        if snapshot.run.run_id != signal.run_id:
            raise TemporalContractError("signal run does not match workflow")
        if snapshot.run.state_version != signal.expected_state_version:
            raise TemporalContractError("signal expected_state_version is stale")
        current = snapshot.run.status
        target_by_signal = {
            TemporalSignalKind.APPROVE: (AgentRunStatus.WAITING_REVIEW, AgentRunStatus.RUNNING),
            TemporalSignalKind.REJECT: (AgentRunStatus.WAITING_REVIEW, AgentRunStatus.CANCELLED),
            TemporalSignalKind.PAUSE: (
                frozenset(
                    {
                        AgentRunStatus.PLANNING,
                        AgentRunStatus.RUNNING,
                        AgentRunStatus.WAITING_REVIEW,
                    }
                ),
                AgentRunStatus.PAUSED,
            ),
            TemporalSignalKind.RESUME: (AgentRunStatus.PAUSED, AgentRunStatus.RUNNING),
            TemporalSignalKind.CANCEL: (
                frozenset(set(AgentRunStatus) - TEMPORAL_TERMINAL_STATES),
                AgentRunStatus.CANCELLED,
            ),
            TemporalSignalKind.RECONCILE: (
                frozenset(
                    {
                        AgentRunStatus.PLANNING,
                        AgentRunStatus.RUNNING,
                        AgentRunStatus.WAITING_REVIEW,
                        AgentRunStatus.PAUSED,
                    }
                ),
                AgentRunStatus.RECONCILING,
            ),
        }
        allowed_from, target = target_by_signal[signal.kind]
        allowed = (
            current is allowed_from
            if isinstance(allowed_from, AgentRunStatus)
            else current in allowed_from
        )
        if not allowed:
            raise TemporalContractError(
                f"signal {signal.kind.value!r} is not allowed from {current.value!r}"
            )
        updated = self.transition(
            signal.workflow_id,
            target,
            actor_ref=signal.requested_by,
            reason=signal.reason,
        )
        updated = TemporalWorkflowSnapshot(
            workflow_input=updated.workflow_input,
            run=updated.run,
            history=updated.history,
            activity_evidence=updated.activity_evidence,
            signals=(*updated.signals, signal),
        )
        self._workflows[signal.workflow_id] = updated
        self._signals[signal.signal_id] = signal
        return updated

    def restore(self, snapshot: TemporalWorkflowSnapshot) -> TemporalWorkflowSnapshot:
        """Restore a validated workflow snapshot and its signal idempotency index."""

        workflow_id = snapshot.workflow_input.identity.workflow_id
        if not snapshot.history:
            raise TemporalContractError("workflow restore history cannot be empty")
        if snapshot.history[-1].to_status is not snapshot.run.status:
            raise TemporalContractError("workflow restore run does not match latest transition")
        if snapshot.history[-1].sequence_no != snapshot.run.state_version:
            raise TemporalContractError("workflow restore state version does not match history")
        for expected_sequence, event in enumerate(snapshot.history):
            if (
                event.sequence_no != expected_sequence
                or event.tenant_id != snapshot.workflow_input.tenant_id
                or event.workflow_id != workflow_id
                or event.run_id != snapshot.run.run_id
            ):
                raise TemporalContractError(
                    "workflow restore history is not contiguous or correlated"
                )
        signal_ids = tuple(signal.signal_id for signal in snapshot.signals)
        if len(signal_ids) != len(set(signal_ids)):
            raise TemporalContractError("workflow restore signal ids must be unique")
        evidence_keys = tuple(evidence.idempotency_key for evidence in snapshot.activity_evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise TemporalContractError("workflow restore activity keys must be unique")
        for signal in snapshot.signals:
            if (
                signal.tenant_id != snapshot.workflow_input.tenant_id
                or signal.workflow_id != workflow_id
                or signal.run_id != snapshot.run.run_id
            ):
                raise TemporalContractError("workflow restore signal correlation differs")
        for evidence in snapshot.activity_evidence:
            if (
                evidence.tenant_id != snapshot.workflow_input.tenant_id
                or evidence.workflow_id != workflow_id
                or evidence.run_id != snapshot.run.run_id
            ):
                raise TemporalContractError("workflow restore activity correlation differs")
        existing = self._workflows.get(workflow_id)
        if existing is not None and existing != snapshot:
            raise TemporalContractError("workflow restore conflicts with existing state")
        self._workflows[workflow_id] = snapshot
        self._signals = {
            signal_id: signal
            for signal_id, signal in self._signals.items()
            if signal.workflow_id != workflow_id
        }
        self._signals.update({signal.signal_id: signal for signal in snapshot.signals})
        return snapshot

    def record_activity(
        self, workflow_id: str, evidence: TemporalActivityEvidence
    ) -> TemporalWorkflowSnapshot:
        snapshot = self.get(workflow_id)
        if evidence.workflow_id != workflow_id:
            raise TemporalContractError("activity evidence workflow does not match")
        if evidence.tenant_id != snapshot.workflow_input.tenant_id:
            raise TemporalContractError("activity evidence tenant does not match")
        if evidence.run_id != snapshot.run.run_id:
            raise TemporalContractError("activity evidence run does not match")
        for existing in snapshot.activity_evidence:
            if existing.idempotency_key == evidence.idempotency_key:
                if existing != evidence:
                    raise TemporalContractError(
                        "activity idempotency key was reused with different evidence"
                    )
                return snapshot
        if evidence.outcome is TemporalActivityOutcome.UNKNOWN:
            if snapshot.run.status is not AgentRunStatus.RECONCILING:
                snapshot = self.transition(
                    workflow_id,
                    AgentRunStatus.RECONCILING,
                    actor_ref="workload:temporal-adapter",
                    reason="provider outcome is unknown; reconcile before retry",
                )
        updated = TemporalWorkflowSnapshot(
            workflow_input=snapshot.workflow_input,
            run=snapshot.run,
            history=snapshot.history,
            activity_evidence=(*snapshot.activity_evidence, evidence),
            signals=snapshot.signals,
        )
        self._workflows[workflow_id] = updated
        return updated


__all__ = [
    "TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA",
    "TEMPORAL_ACTIVITY_REQUEST_SCHEMA",
    "TEMPORAL_ACTIVITY_SCHEDULE_SCHEMA",
    "TEMPORAL_PROVIDER_EXECUTION_SPEC_SCHEMA",
    "TEMPORAL_INPUT_SCHEMA",
    "TEMPORAL_NAMESPACE_SCHEMA",
    "TEMPORAL_RETRY_SCHEMA",
    "TEMPORAL_RUN_TRANSITIONS",
    "TEMPORAL_SIGNAL_SCHEMA",
    "TEMPORAL_SPECIALIST_ACTIVITY_PLAN_SCHEMA",
    "TEMPORAL_TASK_QUEUE_SCHEMA",
    "TEMPORAL_TASK_GRAPH_EXECUTION_MANIFEST_SCHEMA",
    "TEMPORAL_TRANSITION_SCHEMA",
    "TEMPORAL_WORKFLOW_SCHEMA",
    "TemporalActivityCancellationType",
    "TemporalActivityEvidence",
    "TemporalActivityOutcome",
    "TemporalActivityRequest",
    "TemporalActivitySchedulePlan",
    "TemporalProviderExecutionSpec",
    "TemporalContractError",
    "TemporalIntegrationHarness",
    "TemporalIsolationClass",
    "TemporalNamespaceIdentity",
    "TemporalRetryPolicy",
    "TemporalSignal",
    "TemporalSignalKind",
    "TemporalStateTransition",
    "TemporalTaskQueueIdentity",
    "TemporalSpecialistActivityPlan",
    "TemporalTaskGraphExecutionManifest",
    "TemporalWorkflowIdentity",
    "TemporalWorkflowInput",
    "TemporalWorkflowSnapshot",
    "derive_temporal_workflow_id",
    "derive_temporal_activity_id",
    "temporal_contract_fingerprint",
    "validate_temporal_run_transition",
]
