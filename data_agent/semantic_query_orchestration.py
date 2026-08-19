"""Automatic semantic planning, clarification, and evidence-safe fusion.

Models may propose a bounded typed DAG, but they never receive an execution
callback. Every node is revalidated against CapabilitySpec and the existing
governed-query route before a deterministic executor can be invoked.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capability_registry import CapabilityRegistry, Surface, SurfaceStatus
from .governed_query import (
    AdmissionState,
    Claim,
    EvidenceItem,
    GovernedQueryRequest,
    GovernedQueryResponse,
    QueryChannel,
    QueryExecutionStatus,
    RequestedResourceVersion,
    plan_query_route,
    verify_claim_citations,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)

GOVERNED_QUERY_CAPABILITY_ID = "semantic.query.execute"
GOVERNED_QUERY_EVALUATOR_REF = "evaluator:governed-query-evidence@1.0.0"


class SemanticOrchestrationError(RuntimeError):
    """Base failure for semantic planning or fusion."""


class SemanticPlanAdmissionError(SemanticOrchestrationError):
    """A candidate plan cannot enter deterministic execution."""


class SemanticClarificationError(SemanticOrchestrationError):
    """Clarification evidence does not bind the prior plan."""


class PlanningStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    NOT_ADMITTED = "not_admitted"


class PlanningInvocationSurface(StrEnum):
    WEB = "web"
    API = "api"
    MCP = "mcp"
    AGENT = "agent"

    @property
    def capability_surface(self) -> Surface:
        return {
            PlanningInvocationSurface.WEB: Surface.API,
            PlanningInvocationSurface.API: Surface.API,
            PlanningInvocationSurface.MCP: Surface.AGENT,
            PlanningInvocationSurface.AGENT: Surface.AGENT,
        }[self]


class ClarificationCode(StrEnum):
    AMBIGUOUS_CONCEPT = "ambiguous_concept"
    AMBIGUOUS_METRIC = "ambiguous_metric"
    AMBIGUOUS_SPATIAL_RELATION = "ambiguous_spatial_relation"
    AMBIGUOUS_TIME_SCOPE = "ambiguous_time_scope"
    NON_EQUIVALENT_FALLBACK = "non_equivalent_fallback"
    CONFLICT_RESOLUTION = "conflict_resolution"
    MISSING_RESOURCE_VERSION = "missing_resource_version"


class FusionSupportStatus(StrEnum):
    SUPPORTED = "supported"
    CORROBORATED = "corroborated"
    CONFLICTED = "conflicted"
    MISSING = "missing"


class FusionStatus(StrEnum):
    COMPLETED = "completed"
    CONFLICTED = "conflicted"
    NEEDS_CLARIFICATION = "needs_clarification"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("semantic orchestration timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat().replace("+00:00", "Z")
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _jsonable(payload)})


class SemanticPlanningBudget(_FrozenModel):
    max_nodes: int = Field(default=5, ge=1, le=12)
    max_channels: int = Field(default=3, ge=1, le=5)
    max_tool_calls: int = Field(default=5, ge=1, le=20)
    max_llm_tokens: int = Field(default=4_000, ge=0, le=200_000)
    max_cost_usd: float = Field(default=2.0, ge=0, le=1_000)


class PlannerModelBinding(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-planner-model-binding.v1"
    provider: ShortName
    model: NonEmptyText
    model_version: NonEmptyText
    prompt_version: NonEmptyText
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> PlannerModelBinding:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"binding_sha256"}),
            "binding_sha256",
        )
        if self.binding_sha256 != expected:
            raise ValueError("planner model binding fingerprint is invalid")
        return self


def build_planner_model_binding(
    *,
    provider: str,
    model: str,
    model_version: str,
    prompt_version: str,
) -> PlannerModelBinding:
    values = {
        "provider": provider,
        "model": model,
        "model_version": model_version,
        "prompt_version": prompt_version,
    }
    return PlannerModelBinding(
        **values,
        binding_sha256=_fingerprint(
            PlannerModelBinding.schema_id,
            values,
            "binding_sha256",
        ),
    )


class SemanticPlanningRequest(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-planning-request.v1"
    tenant_id: TenantId
    request_id: ShortName
    question: str = Field(min_length=1, max_length=4_000)
    purpose: NonEmptyText
    purpose_code: ShortName
    subject_context: SubjectContext
    invocation_surface: PlanningInvocationSurface
    allowed_channels: tuple[QueryChannel, ...] = Field(min_length=1, max_length=5)
    resource_version_refs: tuple[RequestedResourceVersion, ...] = Field(
        min_length=1,
        max_length=64,
    )
    budget: SemanticPlanningBudget = Field(default_factory=SemanticPlanningBudget)
    planner_binding: PlannerModelBinding
    deterministic_seed_requests: tuple[GovernedQueryRequest, ...] = Field(
        default=(),
        max_length=5,
    )
    request_sha256: Sha256

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("semantic planning question cannot be blank")
        return value

    @model_validator(mode="after")
    def _sealed(self) -> SemanticPlanningRequest:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("semantic planning subject tenant differs")
        if self.subject_context.purpose != self.purpose:
            raise ValueError("semantic planning subject purpose differs")
        if QueryChannel.AUTO in self.allowed_channels:
            raise ValueError("allowed_channels must contain deterministic channels")
        if len(self.allowed_channels) != len(set(self.allowed_channels)):
            raise ValueError("allowed_channels must be unique")
        resources = tuple(
            (item.resource_kind, item.resource_id, item.version, item.content_sha256)
            for item in self.resource_version_refs
        )
        if len(resources) != len(set(resources)):
            raise ValueError("planning resource versions must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("semantic planning request fingerprint is invalid")
        return self


def build_semantic_planning_request(
    *,
    tenant_id: str,
    request_id: str,
    question: str,
    purpose: str,
    purpose_code: str,
    subject_context: SubjectContext,
    invocation_surface: PlanningInvocationSurface,
    allowed_channels: tuple[QueryChannel, ...],
    resource_version_refs: tuple[RequestedResourceVersion, ...],
    planner_binding: PlannerModelBinding,
    budget: SemanticPlanningBudget | None = None,
    deterministic_seed_requests: tuple[GovernedQueryRequest, ...] = (),
) -> SemanticPlanningRequest:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "request_id": request_id,
        "question": question,
        "purpose": purpose,
        "purpose_code": purpose_code,
        "subject_context": subject_context,
        "invocation_surface": invocation_surface,
        "allowed_channels": allowed_channels,
        "resource_version_refs": resource_version_refs,
        "budget": budget or SemanticPlanningBudget(),
        "planner_binding": planner_binding,
        "deterministic_seed_requests": deterministic_seed_requests,
    }
    return SemanticPlanningRequest(
        **values,
        request_sha256=_fingerprint(
            SemanticPlanningRequest.schema_id,
            values,
            "request_sha256",
        ),
    )


class SemanticPlanNode(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-plan-node.v1"
    node_id: str = Field(pattern=r"^node_[a-z0-9][a-z0-9_]{0,47}$")
    channel: QueryChannel
    query_request: GovernedQueryRequest
    depends_on: tuple[str, ...] = Field(default=(), max_length=8)
    capability_id: NonEmptyText
    capability_version: NonEmptyText
    capability_fingerprint: Sha256
    output_schema_sha256: Sha256
    evaluator_ref: NonEmptyText

    @model_validator(mode="after")
    def _typed_node(self) -> SemanticPlanNode:
        if self.channel is QueryChannel.AUTO or self.query_request.channel is not self.channel:
            raise ValueError("semantic plan node requires one explicit matching channel")
        if self.node_id in self.depends_on:
            raise ValueError("semantic plan node cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("semantic plan dependencies must be unique")
        return self


class FusionClaimSelector(_FrozenModel):
    node_id: str = Field(pattern=r"^node_[a-z0-9][a-z0-9_]{0,47}$")
    claim_id: str = Field(pattern=r"^claim_[0-9]{3}$")


class FusionClaimRule(_FrozenModel):
    claim_key: ShortName
    selectors: tuple[FusionClaimSelector, ...] = Field(min_length=1, max_length=16)
    required: bool = True

    @model_validator(mode="after")
    def _unique_selectors(self) -> FusionClaimRule:
        identities = tuple((item.node_id, item.claim_id) for item in self.selectors)
        if len(identities) != len(set(identities)):
            raise ValueError("fusion selectors must be unique")
        return self


class ClarificationRequirement(_FrozenModel):
    clarification_id: ShortName
    code: ClarificationCode
    affected_node_ids: tuple[str, ...] = Field(default=(), max_length=8)
    option_ids: tuple[ShortName, ...] = Field(min_length=2, max_length=12)
    free_text_allowed: bool = False

    @model_validator(mode="after")
    def _bounded_options(self) -> ClarificationRequirement:
        if len(self.option_ids) != len(set(self.option_ids)):
            raise ValueError("clarification options must be unique")
        if len(self.affected_node_ids) != len(set(self.affected_node_ids)):
            raise ValueError("clarification nodes must be unique")
        return self


class ClarificationResolution(_FrozenModel):
    request_sha256: Sha256
    prior_plan_sha256: Sha256
    clarification_id: ShortName
    selected_option_id: ShortName
    confirmed_by: NonEmptyText
    confirmed_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _human_confirmation(self) -> ClarificationResolution:
        if not self.confirmed_by.startswith("human:"):
            raise ValueError("semantic clarification requires a human confirmer")
        return self


class SemanticPlanCandidate(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-plan-candidate.v1"
    request_sha256: Sha256
    revision: int = Field(ge=0, le=32)
    supersedes_plan_sha256: Sha256 | None = None
    nodes: tuple[SemanticPlanNode, ...] = Field(min_length=1, max_length=12)
    fusion_rules: tuple[FusionClaimRule, ...] = Field(default=(), max_length=32)
    clarifications: tuple[ClarificationRequirement, ...] = Field(
        default=(),
        max_length=16,
    )
    planner_binding: PlannerModelBinding | None
    llm_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    proposed_at: datetime
    candidate_sha256: Sha256

    @field_validator("proposed_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> SemanticPlanCandidate:
        node_ids = tuple(node.node_id for node in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("semantic plan node IDs must be unique")
        clarification_ids = tuple(item.clarification_id for item in self.clarifications)
        if len(clarification_ids) != len(set(clarification_ids)):
            raise ValueError("semantic clarification IDs must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"candidate_sha256"}),
            "candidate_sha256",
        )
        if self.candidate_sha256 != expected:
            raise ValueError("semantic plan candidate fingerprint is invalid")
        return self


def build_semantic_plan_candidate(
    *,
    request_sha256: str,
    revision: int,
    nodes: tuple[SemanticPlanNode, ...],
    fusion_rules: tuple[FusionClaimRule, ...],
    clarifications: tuple[ClarificationRequirement, ...],
    planner_binding: PlannerModelBinding | None,
    proposed_at: datetime,
    supersedes_plan_sha256: str | None = None,
    llm_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> SemanticPlanCandidate:
    values: dict[str, Any] = {
        "request_sha256": request_sha256,
        "revision": revision,
        "supersedes_plan_sha256": supersedes_plan_sha256,
        "nodes": nodes,
        "fusion_rules": fusion_rules,
        "clarifications": clarifications,
        "planner_binding": planner_binding,
        "llm_tokens": llm_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "proposed_at": proposed_at,
    }
    return SemanticPlanCandidate(
        **values,
        candidate_sha256=_fingerprint(
            SemanticPlanCandidate.schema_id,
            values,
            "candidate_sha256",
        ),
    )


class SemanticExecutionPlan(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-execution-plan.v1"
    request: SemanticPlanningRequest
    revision: int = Field(ge=0, le=32)
    status: PlanningStatus
    nodes: tuple[SemanticPlanNode, ...]
    fusion_rules: tuple[FusionClaimRule, ...]
    clarifications: tuple[ClarificationRequirement, ...]
    resolutions: tuple[ClarificationResolution, ...] = ()
    planner_binding: PlannerModelBinding | None
    candidate_sha256: Sha256
    supersedes_plan_sha256: Sha256 | None = None
    reason_codes: tuple[ShortName, ...] = Field(min_length=1, max_length=32)
    execution_allowed: bool
    created_at: datetime
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> SemanticExecutionPlan:
        if self.execution_allowed != (self.status is PlanningStatus.READY):
            raise ValueError("only a ready semantic plan may execute")
        if self.status is PlanningStatus.NEEDS_CLARIFICATION and not self.clarifications:
            raise ValueError("clarification status requires structured requirements")
        if self.status is PlanningStatus.READY and self.clarifications:
            raise ValueError("ready semantic plan cannot retain unresolved clarification")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"plan_sha256"}),
            "plan_sha256",
        )
        if self.plan_sha256 != expected:
            raise ValueError("semantic execution plan fingerprint is invalid")
        return self


class SemanticClarificationRequest(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-clarification-request.v1"
    request_sha256: Sha256
    plan_sha256: Sha256
    requirements: tuple[ClarificationRequirement, ...] = Field(min_length=1)
    created_at: datetime
    clarification_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> SemanticClarificationRequest:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"clarification_sha256"}),
            "clarification_sha256",
        )
        if self.clarification_sha256 != expected:
            raise ValueError("semantic clarification request fingerprint is invalid")
        return self


class SemanticPlanningOutcome(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-planning-outcome.v1"
    status: PlanningStatus
    plan: SemanticExecutionPlan | None = None
    clarification: SemanticClarificationRequest | None = None
    reason_codes: tuple[ShortName, ...] = Field(min_length=1, max_length=32)
    model_invocations: int = Field(ge=0, le=2)
    deterministic_fallback_used: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> SemanticPlanningOutcome:
        if self.status is PlanningStatus.NOT_ADMITTED:
            if self.plan is not None or self.clarification is not None:
                raise ValueError("not-admitted planning outcome cannot expose a plan")
        elif self.plan is None or self.plan.status is not self.status:
            raise ValueError("planning outcome must bind a plan with the same status")
        if self.status is PlanningStatus.NEEDS_CLARIFICATION:
            if self.clarification is None:
                raise ValueError("clarification outcome lacks clarification contract")
        elif self.clarification is not None:
            raise ValueError("non-clarification outcome cannot include clarification")
        return self


class SemanticCandidateProposer(Protocol):
    def propose(
        self,
        request: SemanticPlanningRequest,
        *,
        previous_plan: SemanticExecutionPlan | None,
        resolutions: tuple[ClarificationResolution, ...],
    ) -> SemanticPlanCandidate | dict[str, Any]: ...


_BLOCKED_QUERY_PATTERNS = (
    re.compile(r"\b(ignore|bypass|override)\b.{0,40}\b(system|policy|guardrail)", re.I),
    re.compile(r"\b(update|delete|insert|drop|alter|truncate)\b", re.I),
    re.compile(r"(忽略|绕过|覆盖).{0,20}(系统|策略|权限|规则)"),
    re.compile(r"(直接|立即).{0,12}(更新|删除|写入|发布)"),
)


class AutomaticSemanticPlanner:
    """Admit only bounded candidates; candidate proposers have no tool access."""

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        proposer: SemanticCandidateProposer,
        *,
        now=lambda: datetime.now(UTC),
    ) -> None:
        self._capabilities = capability_registry
        self._proposer = proposer
        self._now = now

    def plan(self, request: SemanticPlanningRequest) -> SemanticPlanningOutcome:
        blocked = self._blocked_reason(request.question)
        if blocked is not None:
            return SemanticPlanningOutcome(
                status=PlanningStatus.NOT_ADMITTED,
                reason_codes=(blocked,),
                model_invocations=0,
            )
        try:
            candidate = self._proposer.propose(
                request,
                previous_plan=None,
                resolutions=(),
            )
            candidate = SemanticPlanCandidate.model_validate(candidate)
        except Exception:
            fallback = self._deterministic_fallback(request)
            if fallback is None:
                return SemanticPlanningOutcome(
                    status=PlanningStatus.NOT_ADMITTED,
                    reason_codes=("planner_unavailable",),
                    model_invocations=1,
                )
            return self._admit(
                request,
                fallback,
                resolutions=(),
                model_invocations=1,
                deterministic_fallback_used=True,
            )
        return self._admit(
            request,
            candidate,
            resolutions=(),
            model_invocations=1,
            deterministic_fallback_used=False,
        )

    def replan(
        self,
        request: SemanticPlanningRequest,
        prior: SemanticExecutionPlan,
        resolutions: tuple[ClarificationResolution, ...],
    ) -> SemanticPlanningOutcome:
        self._validate_resolutions(request, prior, resolutions)
        try:
            candidate = SemanticPlanCandidate.model_validate(
                self._proposer.propose(
                    request,
                    previous_plan=prior,
                    resolutions=resolutions,
                )
            )
        except Exception:
            return SemanticPlanningOutcome(
                status=PlanningStatus.NOT_ADMITTED,
                reason_codes=("replan_failed",),
                model_invocations=1,
            )
        if (
            candidate.revision != prior.revision + 1
            or candidate.supersedes_plan_sha256 != prior.plan_sha256
        ):
            return SemanticPlanningOutcome(
                status=PlanningStatus.NOT_ADMITTED,
                reason_codes=("replan_revision_drift",),
                model_invocations=1,
            )
        return self._admit(
            request,
            candidate,
            resolutions=resolutions,
            model_invocations=1,
            deterministic_fallback_used=False,
        )

    @staticmethod
    def _blocked_reason(question: str) -> str | None:
        for index, pattern in enumerate(_BLOCKED_QUERY_PATTERNS, start=1):
            if pattern.search(question):
                return f"query_guardrail_{index}"
        return None

    def _deterministic_fallback(
        self,
        request: SemanticPlanningRequest,
    ) -> SemanticPlanCandidate | None:
        if (
            len(request.deterministic_seed_requests) != 1
            or request.deterministic_seed_requests[0].channel is QueryChannel.AUTO
        ):
            return None
        spec = self._capabilities.get(GOVERNED_QUERY_CAPABILITY_ID)
        nodes = tuple(
            SemanticPlanNode(
                node_id=f"node_seed_{index}",
                channel=query.channel,
                query_request=query,
                depends_on=(),
                capability_id=spec.capability_id,
                capability_version=spec.version,
                capability_fingerprint=spec.fingerprint,
                output_schema_sha256=canonical_json_fingerprint(spec.output.json_schema),
                evaluator_ref=GOVERNED_QUERY_EVALUATOR_REF,
            )
            for index, query in enumerate(request.deterministic_seed_requests, start=1)
        )
        return build_semantic_plan_candidate(
            request_sha256=request.request_sha256,
            revision=0,
            nodes=nodes,
            fusion_rules=(),
            clarifications=(),
            planner_binding=None,
            proposed_at=self._now(),
        )

    def _admit(
        self,
        request: SemanticPlanningRequest,
        candidate: SemanticPlanCandidate,
        *,
        resolutions: tuple[ClarificationResolution, ...],
        model_invocations: int,
        deterministic_fallback_used: bool,
    ) -> SemanticPlanningOutcome:
        if deterministic_fallback_used:
            reason = (
                "fallback_planner_binding_present"
                if candidate.planner_binding is not None
                else None
            )
        elif candidate.planner_binding is None:
            reason = "planner_binding_missing"
        else:
            reason = None
        if reason is None:
            reason = self._candidate_rejection(request, candidate)
        if reason is not None:
            return SemanticPlanningOutcome(
                status=PlanningStatus.NOT_ADMITTED,
                reason_codes=(reason,),
                model_invocations=model_invocations,
                deterministic_fallback_used=deterministic_fallback_used,
            )
        status = (
            PlanningStatus.NEEDS_CLARIFICATION if candidate.clarifications else PlanningStatus.READY
        )
        reasons = (
            ("structured_clarification_required",)
            if candidate.clarifications
            else ("typed_composite_plan_admitted",)
        )
        plan_values: dict[str, Any] = {
            "request": request,
            "revision": candidate.revision,
            "status": status,
            "nodes": candidate.nodes,
            "fusion_rules": candidate.fusion_rules,
            "clarifications": candidate.clarifications,
            "resolutions": resolutions,
            "planner_binding": candidate.planner_binding,
            "candidate_sha256": candidate.candidate_sha256,
            "supersedes_plan_sha256": candidate.supersedes_plan_sha256,
            "reason_codes": reasons,
            "execution_allowed": status is PlanningStatus.READY,
            "created_at": self._now(),
        }
        plan = SemanticExecutionPlan(
            **plan_values,
            plan_sha256=_fingerprint(
                SemanticExecutionPlan.schema_id,
                plan_values,
                "plan_sha256",
            ),
        )
        clarification = None
        if status is PlanningStatus.NEEDS_CLARIFICATION:
            clarification_values = {
                "request_sha256": request.request_sha256,
                "plan_sha256": plan.plan_sha256,
                "requirements": candidate.clarifications,
                "created_at": self._now(),
            }
            clarification = SemanticClarificationRequest(
                **clarification_values,
                clarification_sha256=_fingerprint(
                    SemanticClarificationRequest.schema_id,
                    clarification_values,
                    "clarification_sha256",
                ),
            )
        return SemanticPlanningOutcome(
            status=status,
            plan=plan,
            clarification=clarification,
            reason_codes=reasons,
            model_invocations=model_invocations,
            deterministic_fallback_used=deterministic_fallback_used,
        )

    def _candidate_rejection(
        self,
        request: SemanticPlanningRequest,
        candidate: SemanticPlanCandidate,
    ) -> str | None:
        if candidate.request_sha256 != request.request_sha256:
            return "candidate_request_drift"
        if candidate.revision == 0 and candidate.supersedes_plan_sha256 is not None:
            return "initial_plan_has_supersedes"
        if (
            candidate.planner_binding is not None
            and candidate.planner_binding != request.planner_binding
        ):
            return "planner_binding_drift"
        if len(candidate.nodes) > request.budget.max_nodes:
            return "node_budget_exceeded"
        channels = {node.channel for node in candidate.nodes}
        if len(channels) > request.budget.max_channels:
            return "channel_budget_exceeded"
        if candidate.llm_tokens > request.budget.max_llm_tokens:
            return "llm_token_budget_exceeded"
        if candidate.estimated_cost_usd > request.budget.max_cost_usd:
            return "llm_cost_budget_exceeded"
        if not channels.issubset(set(request.allowed_channels)):
            return "channel_not_allowed"
        if len(candidate.nodes) > 1 and not candidate.fusion_rules:
            return "multi_channel_fusion_rule_missing"
        if self._has_invalid_graph(candidate.nodes):
            return "invalid_or_cyclic_task_graph"

        pinned = {self._resource_identity(item) for item in request.resource_version_refs}
        node_ids = {node.node_id for node in candidate.nodes}
        spec = self._capabilities.get(GOVERNED_QUERY_CAPABILITY_ID)
        bindings = {item.surface: item for item in spec.surfaces}
        surface = request.invocation_surface.capability_surface
        if surface not in bindings or bindings[surface].status is not SurfaceStatus.IMPLEMENTED:
            return "invocation_surface_not_implemented"
        expected_output = canonical_json_fingerprint(spec.output.json_schema)
        total_tool_calls = 0
        for node in candidate.nodes:
            total_tool_calls += 1
            if (
                node.capability_id != spec.capability_id
                or node.capability_version != spec.version
                or node.capability_fingerprint != spec.fingerprint
                or node.output_schema_sha256 != expected_output
            ):
                return "capability_binding_drift"
            if node.evaluator_ref != GOVERNED_QUERY_EVALUATOR_REF:
                return "evaluator_binding_drift"
            if (
                node.query_request.purpose != request.purpose
                or node.query_request.purpose_code != request.purpose_code
            ):
                return "node_purpose_drift"
            node_resources = {
                self._resource_identity(item) for item in node.query_request.resource_version_refs
            }
            if not node_resources or not node_resources.issubset(pinned):
                return "resource_version_not_pinned"
            route = plan_query_route(node.query_request)
            if (
                route.admission is not AdmissionState.ADMITTED
                or route.selected_channel is not node.channel
            ):
                return "typed_node_not_admitted"
        if total_tool_calls > request.budget.max_tool_calls:
            return "tool_call_budget_exceeded"
        for rule in candidate.fusion_rules:
            if any(selector.node_id not in node_ids for selector in rule.selectors):
                return "fusion_selector_unknown_node"
        for clarification in candidate.clarifications:
            if any(node_id not in node_ids for node_id in clarification.affected_node_ids):
                return "clarification_unknown_node"
        return None

    @staticmethod
    def _resource_identity(item: RequestedResourceVersion) -> tuple[Any, ...]:
        return (
            item.resource_kind,
            item.resource_id,
            item.version,
            item.content_sha256,
        )

    @staticmethod
    def _has_invalid_graph(nodes: tuple[SemanticPlanNode, ...]) -> bool:
        dependencies = {node.node_id: set(node.depends_on) for node in nodes}
        node_ids = set(dependencies)
        if any(not values.issubset(node_ids) for values in dependencies.values()):
            return True
        pending = {key: set(values) for key, values in dependencies.items()}
        while pending:
            ready = {key for key, values in pending.items() if not values}
            if not ready:
                return True
            pending = {key: values - ready for key, values in pending.items() if key not in ready}
        return False

    @staticmethod
    def _validate_resolutions(
        request: SemanticPlanningRequest,
        prior: SemanticExecutionPlan,
        resolutions: tuple[ClarificationResolution, ...],
    ) -> None:
        if (
            prior.request != request
            or prior.status is not PlanningStatus.NEEDS_CLARIFICATION
            or not prior.clarifications
        ):
            raise SemanticClarificationError("prior plan is not awaiting clarification")
        expected = {item.clarification_id: item for item in prior.clarifications}
        supplied = {item.clarification_id: item for item in resolutions}
        if len(supplied) != len(resolutions) or set(supplied) != set(expected):
            raise SemanticClarificationError("clarification resolution set is incomplete")
        for clarification_id, resolution in supplied.items():
            requirement = expected[clarification_id]
            if (
                resolution.request_sha256 != request.request_sha256
                or resolution.prior_plan_sha256 != prior.plan_sha256
                or resolution.selected_option_id not in requirement.option_ids
            ):
                raise SemanticClarificationError("clarification binding or option drifted")


class GovernedQueryNodeExecutor(Protocol):
    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> GovernedQueryResponse: ...


class FusedEvidence(_FrozenModel):
    global_evidence_id: NonEmptyText
    node_id: NonEmptyText
    evidence: EvidenceItem


class FusedClaimVariant(_FrozenModel):
    node_id: NonEmptyText
    claim_id: NonEmptyText
    statement: NonEmptyText
    global_evidence_ids: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=32)


class FusedClaim(_FrozenModel):
    claim_key: ShortName
    support_status: FusionSupportStatus
    variants: tuple[FusedClaimVariant, ...] = Field(max_length=16)


class NodeExecutionReceipt(_FrozenModel):
    node_id: NonEmptyText
    channel: QueryChannel
    response_sha256: Sha256
    evidence_sha256: Sha256
    status: QueryExecutionStatus


class SemanticFusionResult(_FrozenModel):
    schema_id: ClassVar[str] = "gda.semantic-fusion-result.v1"
    request_sha256: Sha256
    plan_sha256: Sha256
    status: FusionStatus
    node_receipts: tuple[NodeExecutionReceipt, ...]
    evidence: tuple[FusedEvidence, ...]
    claims: tuple[FusedClaim, ...]
    conflict_claim_keys: tuple[ShortName, ...]
    missing_inputs: tuple[NonEmptyText, ...]
    generated_at: datetime
    result_sha256: Sha256

    @field_validator("generated_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed(self) -> SemanticFusionResult:
        if self.status is FusionStatus.COMPLETED and (
            self.conflict_claim_keys or self.missing_inputs
        ):
            raise ValueError("completed fusion cannot hide conflicts or missing inputs")
        if self.status is FusionStatus.CONFLICTED and not self.conflict_claim_keys:
            raise ValueError("conflicted fusion requires conflict claim keys")
        if self.status is FusionStatus.NEEDS_CLARIFICATION and not self.missing_inputs:
            raise ValueError("clarification fusion requires missing inputs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("semantic fusion result fingerprint is invalid")
        return self


class SemanticPlanExecutor:
    """Execute a ready DAG and fuse only citation-verified claims."""

    def __init__(self, executor: GovernedQueryNodeExecutor, *, now=lambda: datetime.now(UTC)):
        self._executor = executor
        self._now = now

    def execute(self, plan: SemanticExecutionPlan) -> SemanticFusionResult:
        if plan.status is not PlanningStatus.READY or not plan.execution_allowed:
            raise SemanticPlanAdmissionError("semantic plan is not executable")
        ordered = self._topological(plan.nodes)
        responses: dict[str, GovernedQueryResponse] = {}
        receipts: list[NodeExecutionReceipt] = []
        missing: list[str] = []
        failed_nodes: set[str] = set()
        for node in ordered:
            if any(dependency in failed_nodes for dependency in node.depends_on):
                missing.append(f"{node.node_id}:dependency_not_completed")
                failed_nodes.add(node.node_id)
                continue
            try:
                response = self._executor.execute(
                    node.query_request,
                    plan.request.subject_context,
                )
                response = GovernedQueryResponse.model_validate(response)
            except Exception:
                missing.append(f"{node.node_id}:execution_failed")
                failed_nodes.add(node.node_id)
                continue
            issue = self._response_issue(plan, node, response)
            if issue is not None:
                missing.append(f"{node.node_id}:{issue}")
                failed_nodes.add(node.node_id)
                continue
            responses[node.node_id] = response
            receipts.append(
                NodeExecutionReceipt(
                    node_id=node.node_id,
                    channel=node.channel,
                    response_sha256=canonical_json_fingerprint(
                        response.model_dump(mode="json", by_alias=True)
                    ),
                    evidence_sha256=canonical_json_fingerprint(
                        response.evidence_bundle.model_dump(mode="json")
                    ),
                    status=response.status,
                )
            )
        evidence = self._fused_evidence(responses)
        claims, claim_missing = self._fused_claims(plan.fusion_rules, responses)
        missing.extend(claim_missing)
        conflicts = tuple(
            claim.claim_key
            for claim in claims
            if claim.support_status is FusionSupportStatus.CONFLICTED
        )
        if missing:
            status = FusionStatus.NEEDS_CLARIFICATION
        elif conflicts:
            status = FusionStatus.CONFLICTED
        else:
            status = FusionStatus.COMPLETED
        values: dict[str, Any] = {
            "request_sha256": plan.request.request_sha256,
            "plan_sha256": plan.plan_sha256,
            "status": status,
            "node_receipts": tuple(receipts),
            "evidence": evidence,
            "claims": claims,
            "conflict_claim_keys": conflicts,
            "missing_inputs": tuple(dict.fromkeys(missing)),
            "generated_at": self._now(),
        }
        return SemanticFusionResult(
            **values,
            result_sha256=_fingerprint(
                SemanticFusionResult.schema_id,
                values,
                "result_sha256",
            ),
        )

    @staticmethod
    def _response_issue(
        plan: SemanticExecutionPlan,
        node: SemanticPlanNode,
        response: GovernedQueryResponse,
    ) -> str | None:
        if response.request != node.query_request:
            return "request_drift"
        if response.subject_context != plan.request.subject_context:
            return "subject_drift"
        if (
            response.capability_id != node.capability_id
            or response.capability_version != node.capability_version
            or response.capability_fingerprint != node.capability_fingerprint
        ):
            return "capability_drift"
        if (
            response.route_plan.requested_channel is not node.channel
            or response.route_plan.selected_channel is not node.channel
            or response.route_plan.admission is not AdmissionState.ADMITTED
        ):
            return "route_drift"
        if response.status not in {
            QueryExecutionStatus.COMPLETED,
            QueryExecutionStatus.RUN_SUCCEEDED,
        }:
            return f"node_status_{response.status.value}"
        bundle = response.evidence_bundle
        if (
            bundle.request_id != node.query_request.request_id
            or not bundle.verification.valid
            or bundle.missing_evidence
        ):
            return "evidence_not_complete"
        verification = verify_claim_citations(bundle.evidence, bundle.claims)
        if not verification.valid:
            return "citation_reverification_failed"
        return None

    @staticmethod
    def _topological(nodes: tuple[SemanticPlanNode, ...]) -> tuple[SemanticPlanNode, ...]:
        by_id = {node.node_id: node for node in nodes}
        pending = {node.node_id: set(node.depends_on) for node in nodes}
        ordered: list[SemanticPlanNode] = []
        while pending:
            ready = sorted(key for key, dependencies in pending.items() if not dependencies)
            if not ready:
                raise SemanticPlanAdmissionError("semantic plan graph is cyclic")
            for key in ready:
                ordered.append(by_id[key])
                pending.pop(key)
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return tuple(ordered)

    @staticmethod
    def _fused_evidence(
        responses: dict[str, GovernedQueryResponse],
    ) -> tuple[FusedEvidence, ...]:
        fused: list[FusedEvidence] = []
        seen: dict[str, EvidenceItem] = {}
        for node_id, response in sorted(responses.items()):
            for item in response.evidence_bundle.evidence:
                global_id = f"{node_id}.{item.evidence_id}"
                previous = seen.get(global_id)
                if previous is not None and previous != item:
                    raise SemanticPlanAdmissionError("fused evidence identity drifted")
                seen[global_id] = item
                fused.append(
                    FusedEvidence(
                        global_evidence_id=global_id,
                        node_id=node_id,
                        evidence=item,
                    )
                )
        return tuple(fused)

    @staticmethod
    def _fused_claims(
        rules: tuple[FusionClaimRule, ...],
        responses: dict[str, GovernedQueryResponse],
    ) -> tuple[tuple[FusedClaim, ...], tuple[str, ...]]:
        output: list[FusedClaim] = []
        missing: list[str] = []
        for rule in rules:
            variants: list[FusedClaimVariant] = []
            for selector in rule.selectors:
                response = responses.get(selector.node_id)
                claim = (
                    SemanticPlanExecutor._claim(response, selector.claim_id)
                    if response is not None
                    else None
                )
                if claim is None:
                    if rule.required:
                        missing.append(f"{rule.claim_key}:{selector.node_id}:{selector.claim_id}")
                    continue
                variants.append(
                    FusedClaimVariant(
                        node_id=selector.node_id,
                        claim_id=selector.claim_id,
                        statement=claim.statement,
                        global_evidence_ids=tuple(
                            f"{selector.node_id}.{citation.evidence_id}"
                            for citation in claim.citations
                        ),
                    )
                )
            normalized = {" ".join(variant.statement.casefold().split()) for variant in variants}
            if not variants:
                support = FusionSupportStatus.MISSING
            elif len(normalized) > 1:
                support = FusionSupportStatus.CONFLICTED
            elif len(variants) > 1:
                support = FusionSupportStatus.CORROBORATED
            else:
                support = FusionSupportStatus.SUPPORTED
            output.append(
                FusedClaim(
                    claim_key=rule.claim_key,
                    support_status=support,
                    variants=tuple(variants),
                )
            )
        return tuple(output), tuple(missing)

    @staticmethod
    def _claim(response: GovernedQueryResponse, claim_id: str) -> Claim | None:
        return next(
            (claim for claim in response.evidence_bundle.claims if claim.claim_id == claim_id),
            None,
        )


__all__ = [
    "AutomaticSemanticPlanner",
    "ClarificationCode",
    "ClarificationRequirement",
    "ClarificationResolution",
    "FusedClaim",
    "FusedEvidence",
    "FusionClaimRule",
    "FusionClaimSelector",
    "FusionStatus",
    "FusionSupportStatus",
    "GovernedQueryNodeExecutor",
    "NodeExecutionReceipt",
    "PlannerModelBinding",
    "PlanningInvocationSurface",
    "PlanningStatus",
    "SemanticCandidateProposer",
    "SemanticClarificationError",
    "SemanticClarificationRequest",
    "SemanticExecutionPlan",
    "SemanticFusionResult",
    "SemanticOrchestrationError",
    "SemanticPlanAdmissionError",
    "SemanticPlanCandidate",
    "SemanticPlanExecutor",
    "SemanticPlanNode",
    "SemanticPlanningBudget",
    "SemanticPlanningOutcome",
    "SemanticPlanningRequest",
    "build_planner_model_binding",
    "build_semantic_plan_candidate",
    "build_semantic_planning_request",
]
