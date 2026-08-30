"""Versioned AgentOps contracts for a governed multi-agent runtime.

These contracts describe the control/evidence boundary for a future
Temporal-backed AgentOps runtime. They do not execute an agent, replace the
existing registry, or create a second data-product authority. Every agent
specialist remains tied to a capability, policy, run and artifact reference.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from pydantic import Field, model_validator

from .platform_contracts import (
    FrozenContract,
    NonEmptyText,
    ResourceURNText,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

AGENT_SPEC_SCHEMA = "gda.agent_spec_version.v1"
AGENT_DEPLOYMENT_SCHEMA = "gda.agent_deployment_revision.v1"
AGENT_RUN_SCHEMA = "gda.agent_run.v1"
AGENT_TASK_STEP_SCHEMA = "gda.agent_task_step.v1"
AGENT_TOOL_CALL_SCHEMA = "gda.agent_tool_call.v1"
AGENT_EVALUATION_SCHEMA = "gda.agent_evaluation_binding.v1"
AGENT_ONLINE_VERDICT_SCHEMA = "gda.agent_online_verdict.v1"


class AgentOpsContractError(ValueError):
    """Raised when an AgentOps identity, topology or evidence link is invalid."""


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    PLANNER = "planner"
    DATA_ENGINEER = "data_engineer"
    GIS_ANALYST = "gis_analyst"
    QUALITY_GUARDIAN = "quality_guardian"
    MULTIMODAL_FUSION = "multimodal_fusion"
    GWM_SPECIALIST = "gwm_specialist"
    VISUALIZER = "visualizer"
    REVIEWER = "reviewer"


class AgentEdgeKind(StrEnum):
    DELEGATES = "delegates"
    HANDOFF = "handoff"
    REVIEWS = "reviews"
    FEEDS = "feeds"
    PARALLEL_JOIN = "parallel_join"


class AgentDeploymentEnvironment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"
    CUSTOMER = "customer"


class AgentRolloutStrategy(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"


class AgentRunStatus(StrEnum):
    ACCEPTED = "accepted"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RECONCILING = "reconciling"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentToolCallStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    RECONCILING = "reconciling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class AgentVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class AgentSideEffect(StrEnum):
    NONE = "none"
    CONTROL_WRITE = "control_write"
    DATA_WRITE = "data_write"
    EXTERNAL_WRITE = "external_write"


class AgentBudget(FrozenContract):
    """Upper bounds enforced by the runtime before tool execution."""

    schema_id: ClassVar[str] = "gda.agent_budget.v1"
    max_steps: int = Field(gt=0, le=100_000)
    max_tool_calls: int = Field(gt=0, le=100_000)
    max_tokens: int = Field(gt=0, le=100_000_000)
    max_cost_usd: float = Field(gt=0, le=1_000_000)
    max_wall_seconds: int = Field(gt=0, le=86_400)


class AgentNodeSpec(FrozenContract):
    """One specialist in a versioned multi-agent topology."""

    schema_id: ClassVar[str] = "gda.agent_node_spec.v1"
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    role: AgentRole
    capability_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    model_binding_ref: NonEmptyText
    policy_ref: NonEmptyText
    max_parallel_steps: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def _canonical_refs(self) -> AgentNodeSpec:
        if self.capability_refs != tuple(sorted(set(self.capability_refs))):
            raise ValueError("agent capability refs must be sorted and unique")
        return self


class AgentTopologyEdge(FrozenContract):
    schema_id: ClassVar[str] = "gda.agent_topology_edge.v1"
    from_agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    to_agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    kind: AgentEdgeKind

    @model_validator(mode="after")
    def _not_self_edge(self) -> AgentTopologyEdge:
        if self.from_agent_id == self.to_agent_id:
            raise ValueError("agent topology cannot contain a self edge")
        return self


class AgentTopology(FrozenContract):
    """Acyclic specialist graph; long-lived loops belong to Temporal state."""

    schema_id: ClassVar[str] = "gda.agent_topology.v1"
    coordinator_agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    nodes: tuple[AgentNodeSpec, ...] = Field(min_length=2)
    edges: tuple[AgentTopologyEdge, ...] = ()

    @model_validator(mode="after")
    def _validate_graph(self) -> AgentTopology:
        node_ids = tuple(node.agent_id for node in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("agent topology node ids must be unique")
        if self.coordinator_agent_id not in node_ids:
            raise ValueError("agent topology coordinator is not declared")
        coordinator = next(
            node for node in self.nodes if node.agent_id == self.coordinator_agent_id
        )
        if coordinator.role is not AgentRole.SUPERVISOR:
            raise ValueError("agent topology coordinator must have supervisor role")
        edge_keys = tuple(
            (edge.from_agent_id, edge.to_agent_id, edge.kind.value) for edge in self.edges
        )
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("agent topology edges must be unique")
        node_set = set(node_ids)
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in self.edges:
            if edge.from_agent_id not in node_set or edge.to_agent_id not in node_set:
                raise ValueError("agent topology edge references an unknown node")
            adjacency[edge.from_agent_id].add(edge.to_agent_id)
            incoming[edge.to_agent_id].add(edge.from_agent_id)

        visited: set[str] = set()
        active: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in active:
                raise ValueError("agent topology must be acyclic")
            if node_id in visited:
                return
            active.add(node_id)
            for child in sorted(adjacency[node_id]):
                visit(child)
            active.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)
        reachable = {self.coordinator_agent_id}
        frontier = [self.coordinator_agent_id]
        while frontier:
            current = frontier.pop()
            for child in adjacency[current]:
                if child not in reachable:
                    reachable.add(child)
                    frontier.append(child)
        if reachable != node_set:
            raise ValueError("every agent specialist must be reachable from coordinator")
        non_coordinators = node_set - {self.coordinator_agent_id}
        if any(not incoming[node_id] for node_id in non_coordinators):
            raise ValueError("every specialist must have an incoming coordination edge")
        return self


def _json_ready(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema_id: str, values: dict[str, Any], field: str) -> str:
    data = dict(values)
    data.pop(field, None)
    return canonical_json_fingerprint(
        {"schema": schema_id, "data": _json_ready(data)}
    )


def agent_contract_fingerprint(
    schema_id: str, values: dict[str, Any], field: str
) -> str:
    """Fingerprint a canonical AgentOps contract payload without its hash field."""

    return _fingerprint(schema_id, values, field)


class AgentSpecVersion(FrozenContract):
    """Immutable bundle for a coordinated group of specialist agents."""

    schema_id: ClassVar[str] = AGENT_SPEC_SCHEMA
    tenant_id: TenantId
    agent_urn: ResourceURNText
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    topology: AgentTopology
    prompt_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    tool_refs: tuple[NonEmptyText, ...] = Field(min_length=1)
    memory_context_ref: NonEmptyText | None = None
    budget: AgentBudget
    evaluation_set_ref: NonEmptyText
    spec_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_spec(self) -> AgentSpecVersion:
        components = parse_resource_urn(self.agent_urn)
        if components["tenant_id"] != self.tenant_id:
            raise ValueError("agent urn tenant must match tenant_id")
        if components["resource_kind"] != "agent":
            raise ValueError("agent_urn must use resource kind 'agent'")
        if self.prompt_refs != tuple(sorted(set(self.prompt_refs))):
            raise ValueError("prompt refs must be sorted and unique")
        if self.tool_refs != tuple(sorted(set(self.tool_refs))):
            raise ValueError("tool refs must be sorted and unique")
        expected = _fingerprint(
            self.schema_id, self.model_dump(mode="json"), "spec_sha256"
        )
        if self.spec_sha256 != expected:
            raise ValueError("spec_sha256 does not match agent bundle content")
        return self


def agent_spec_fingerprint(values: AgentSpecVersion | dict[str, Any]) -> str:
    payload = (
        values.model_dump(mode="json")
        if isinstance(values, AgentSpecVersion)
        else dict(values)
    )
    return _fingerprint(AGENT_SPEC_SCHEMA, payload, "spec_sha256")


class AgentDeploymentRevision(FrozenContract):
    """One evaluated and policy-bound deployment of an AgentSpecVersion."""

    schema_id: ClassVar[str] = AGENT_DEPLOYMENT_SCHEMA
    tenant_id: TenantId
    deployment_urn: ResourceURNText
    agent_spec_sha256: Sha256
    environment: AgentDeploymentEnvironment
    rollout_strategy: AgentRolloutStrategy
    traffic_percent: int = Field(ge=0, le=100)
    evaluation_binding_sha256: Sha256
    policy_ref: NonEmptyText
    owner_ref: NonEmptyText
    rollback_pointer_sha256: Sha256 | None = None
    revision_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_revision(self) -> AgentDeploymentRevision:
        components = parse_resource_urn(self.deployment_urn)
        if components["tenant_id"] != self.tenant_id:
            raise ValueError("deployment urn tenant must match tenant_id")
        if components["resource_kind"] != "agent_deployment":
            raise ValueError("deployment_urn must use resource kind 'agent_deployment'")
        strategy = self.rollout_strategy
        if strategy is AgentRolloutStrategy.ACTIVE and self.traffic_percent != 100:
            raise ValueError("active agent deployment must receive 100 percent traffic")
        if (
            strategy in {AgentRolloutStrategy.DISABLED, AgentRolloutStrategy.SHADOW}
            and self.traffic_percent != 0
        ):
            raise ValueError("disabled and shadow deployments must receive zero traffic")
        if strategy is AgentRolloutStrategy.CANARY and not 0 < self.traffic_percent < 100:
            raise ValueError("canary traffic must be between zero and one hundred")
        expected = _fingerprint(
            self.schema_id, self.model_dump(mode="json"), "revision_sha256"
        )
        if self.revision_sha256 != expected:
            raise ValueError("revision_sha256 does not match deployment content")
        return self


def agent_deployment_revision_fingerprint(
    values: AgentDeploymentRevision | dict[str, Any],
) -> str:
    payload = (
        values.model_dump(mode="json")
        if isinstance(values, AgentDeploymentRevision)
        else dict(values)
    )
    return _fingerprint(AGENT_DEPLOYMENT_SCHEMA, payload, "revision_sha256")


class AgentRun(FrozenContract):
    """Durable correlation identity for one multi-agent execution."""

    schema_id: ClassVar[str] = AGENT_RUN_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    root_run_id: UUID
    parent_run_id: UUID | None = None
    deployment_revision_sha256: Sha256
    subject_context: SubjectContext
    data_product_version_refs: tuple[NonEmptyText, ...] = ()
    idempotency_key: NonEmptyText
    status: AgentRunStatus = AgentRunStatus.ACCEPTED
    state_version: int = Field(ge=0)
    run_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_run(self) -> AgentRun:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("agent run subject tenant must match tenant_id")
        if self.parent_run_id == self.run_id:
            raise ValueError("agent run cannot parent itself")
        if self.parent_run_id is None and self.root_run_id != self.run_id:
            raise ValueError("root agent run must point root_run_id to itself")
        if self.parent_run_id is not None and self.root_run_id == self.run_id:
            raise ValueError("child agent run must point to an existing root run")
        if self.state_version == 0 and self.status is not AgentRunStatus.ACCEPTED:
            raise ValueError("accepted agent run must start at state version zero")
        if self.state_version > 0 and self.status is AgentRunStatus.ACCEPTED:
            raise ValueError("nonzero agent run state cannot remain accepted")
        if self.data_product_version_refs != tuple(
            sorted(set(self.data_product_version_refs))
        ):
            raise ValueError("data product references must be sorted and unique")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "run_sha256")
        if self.run_sha256 != expected:
            raise ValueError("run_sha256 does not match agent run content")
        return self


def agent_run_fingerprint(values: AgentRun | dict[str, Any]) -> str:
    payload = values.model_dump(mode="json") if isinstance(values, AgentRun) else dict(values)
    return _fingerprint(AGENT_RUN_SCHEMA, payload, "run_sha256")


class AgentTaskStep(FrozenContract):
    """One typed specialist step within an AgentRun."""

    schema_id: ClassVar[str] = AGENT_TASK_STEP_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    step_id: UUID
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    role: AgentRole
    sequence_no: int = Field(ge=0)
    depends_on_step_ids: tuple[UUID, ...] = ()
    status: AgentStepStatus = AgentStepStatus.PENDING
    attempt_no: int = Field(default=1, ge=1)
    input_artifact_ids: tuple[UUID, ...] = ()
    output_artifact_ids: tuple[UUID, ...] = ()
    step_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_step(self) -> AgentTaskStep:
        if self.step_id in self.depends_on_step_ids:
            raise ValueError("agent task step cannot depend on itself")
        if len(self.depends_on_step_ids) != len(set(self.depends_on_step_ids)):
            raise ValueError("agent task step dependencies must be unique")
        expected = _fingerprint(self.schema_id, self.model_dump(mode="json"), "step_sha256")
        if self.step_sha256 != expected:
            raise ValueError("step_sha256 does not match task step content")
        return self


class AgentToolCall(FrozenContract):
    """Governed tool invocation; side effects require an external policy decision."""

    schema_id: ClassVar[str] = AGENT_TOOL_CALL_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    tool_ref: NonEmptyText
    capability_ref: NonEmptyText
    subject_context: SubjectContext
    side_effect: AgentSideEffect
    policy_decision_ref: NonEmptyText
    idempotency_key: NonEmptyText
    status: AgentToolCallStatus = AgentToolCallStatus.REQUESTED
    input_artifact_ids: tuple[UUID, ...] = ()
    output_artifact_id: UUID | None = None
    external_receipt_artifact_id: UUID | None = None
    tool_call_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_tool_call(self) -> AgentToolCall:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("tool call subject tenant must match tenant_id")
        if (
            self.side_effect is AgentSideEffect.NONE
            and self.external_receipt_artifact_id is not None
        ):
            raise ValueError("read-only tool call cannot carry external receipt")
        if self.status is AgentToolCallStatus.SUCCEEDED and self.output_artifact_id is None:
            raise ValueError("successful tool call requires an output artifact")
        expected = _fingerprint(
            self.schema_id, self.model_dump(mode="json"), "tool_call_sha256"
        )
        if self.tool_call_sha256 != expected:
            raise ValueError("tool_call_sha256 does not match tool call content")
        return self


class AgentEvaluationBinding(FrozenContract):
    """Immutable offline evaluation gate required by a deployment revision."""

    schema_id: ClassVar[str] = AGENT_EVALUATION_SCHEMA
    tenant_id: TenantId
    agent_spec_sha256: Sha256
    evaluation_set_ref: NonEmptyText
    evaluator_ref: NonEmptyText
    min_pass_rate: float = Field(ge=0, le=1)
    max_failure_rate: float = Field(ge=0, le=1)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_binding(self) -> AgentEvaluationBinding:
        if self.min_pass_rate + self.max_failure_rate < 1:
            raise ValueError("evaluation thresholds leave an undefined verdict range")
        expected = _fingerprint(
            self.schema_id, self.model_dump(mode="json"), "binding_sha256"
        )
        if self.binding_sha256 != expected:
            raise ValueError("binding_sha256 does not match evaluation content")
        return self


class AgentOnlineVerdict(FrozenContract):
    """Independent online quality/safety verdict for an AgentRun."""

    schema_id: ClassVar[str] = AGENT_ONLINE_VERDICT_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    deployment_revision_sha256: Sha256
    verdict: AgentVerdict
    evaluator_ref: NonEmptyText
    evidence_artifact_id: UUID
    metrics: dict[str, float] = Field(default_factory=dict)
    verdict_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_verdict(self) -> AgentOnlineVerdict:
        if any(
            value != value or value in {float("inf"), float("-inf")}
            for value in self.metrics.values()
        ):
            raise ValueError("online verdict metrics must be finite")
        expected = _fingerprint(
            self.schema_id, self.model_dump(mode="json"), "verdict_sha256"
        )
        if self.verdict_sha256 != expected:
            raise ValueError("verdict_sha256 does not match online verdict content")
        return self


__all__ = [
    "AGENT_DEPLOYMENT_SCHEMA",
    "AGENT_EVALUATION_SCHEMA",
    "AGENT_ONLINE_VERDICT_SCHEMA",
    "AGENT_RUN_SCHEMA",
    "AGENT_SPEC_SCHEMA",
    "AGENT_TASK_STEP_SCHEMA",
    "AGENT_TOOL_CALL_SCHEMA",
    "AgentBudget",
    "AgentDeploymentEnvironment",
    "AgentDeploymentRevision",
    "AgentEdgeKind",
    "AgentEvaluationBinding",
    "AgentNodeSpec",
    "AgentOnlineVerdict",
    "AgentRole",
    "AgentRolloutStrategy",
    "AgentRun",
    "AgentRunStatus",
    "AgentSideEffect",
    "AgentSpecVersion",
    "AgentStepStatus",
    "AgentTaskStep",
    "AgentToolCall",
    "AgentToolCallStatus",
    "AgentTopology",
    "AgentTopologyEdge",
    "AgentVerdict",
    "AgentOpsContractError",
    "agent_deployment_revision_fingerprint",
    "agent_contract_fingerprint",
    "agent_run_fingerprint",
    "agent_spec_fingerprint",
]
