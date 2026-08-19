"""Governed semantic query routing, execution, and evidence verification.

The LLM-facing boundary is deliberately narrow: callers submit a typed query
request, while only admitted deterministic adapters may execute it.  Candidate
plans produced by an LLM must pass the same Pydantic models before reaching an
adapter.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .gis_analysis_execution import (
    GISAnalysisBudget,
    GISAnalysisExecutionAuthority,
    GISAnalysisExecutionError,
    GISAnalysisPlanner,
    GISAnalysisRequest,
)
from .governed_query_security import (
    GOVERNED_QUERY_SECURITY_PURPOSE,
    GovernedQuerySecurityAuditPort,
    GovernedQuerySecurityCurrentReader,
    GovernedQuerySecurityError,
    build_query_security_request,
    require_query_security_ports,
)
from .governed_rag import (
    GovernedDocumentPin,
    GovernedRAGError,
    search_governed_knowledge_base,
)
from .metric_authority import MetricAuthorityError
from .metric_projection_authority import MetricProjectionAuthorityError
from .metric_query import (
    MetricQueryPlanner,
    MetricQueryPlanningError,
    MetricQueryRequest,
    MetricQuerySecurityContext,
)
from .metric_query_execution import (
    MetricQueryExecutionAuthority,
    MetricQueryExecutionError,
)
from .nl2sql_source_authority import (
    NL2SQLSourceAdmissionError,
    NL2SQLSourceAuthority,
    NL2SQLSourceAuthorityError,
)
from .ontology.contracts import ONTOLOGY_KEY
from .ontology.query_contracts import OntologyQueryPlan
from .ontology.service import get_ontology_service
from .platform_contracts import RunStatus, SubjectContext, canonical_json_fingerprint

GOVERNED_QUERY_CAPABILITY_ID = "semantic.query.execute"
GOVERNED_QUERY_CAPABILITY_VERSION = "4.1.0"


class GovernedQueryError(ValueError):
    """Base failure for the governed semantic query boundary."""


class QueryPolicyDeniedError(GovernedQueryError):
    """The authenticated subject is not allowed to invoke the capability."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QueryChannel(StrEnum):
    AUTO = "auto"
    ONTOLOGY = "ontology"
    METRIC = "metric"
    NL2SQL = "nl2sql"
    GIS = "gis"
    RAG = "rag"


class AdmissionState(StrEnum):
    ADMITTED = "admitted"
    NOT_ADMITTED = "not_admitted"


class QueryExecutionStatus(StrEnum):
    COMPLETED = "completed"
    PLANNED = "planned"
    RUN_ADMITTED = "run_admitted"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    NOT_ADMITTED = "not_admitted"


class RequestedResourceVersion(StrictModel):
    resource_kind: Literal[
        "ontology_package",
        "semantic_model",
        "dataset",
        "document",
        "metric_definition",
        "metric_projection",
        "data_product",
        "source_snapshot",
        "table",
    ]
    resource_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("resource_id", "version")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("resource identity fields cannot be blank")
        return value


class QueryBudget(StrictModel):
    max_latency_ms: int = Field(default=10_000, ge=100, le=120_000)
    max_evidence_items: int = Field(default=20, ge=1, le=100)
    max_result_items: int = Field(default=100, ge=1, le=1_000)
    max_gis_features: int = Field(default=1_000, ge=1, le=100_000)
    max_result_bytes: int = Field(default=50_000_000, ge=1_024, le=10_000_000_000)
    max_llm_tokens: int = Field(default=0, ge=0, le=200_000)
    max_cost_usd: float = Field(default=0.0, ge=0, le=1_000)


class NL2SQLQueryRequest(StrictModel):
    execution_engine: Literal["postgis", "lake"]
    semantic_source_names: tuple[str, ...] = Field(min_length=1, max_length=12)

    @field_validator("semantic_source_names")
    @classmethod
    def _valid_source_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(
            r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$"
        )
        normalized = tuple(value.strip() for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("semantic_source_names must be unique")
        if any(not pattern.fullmatch(value) for value in normalized):
            raise ValueError("semantic source name is not a valid SQL identifier")
        return normalized


class RAGQueryRequest(StrictModel):
    knowledge_base_ids: tuple[int, ...] = Field(min_length=1, max_length=20)
    top_k: int = Field(default=5, ge=1, le=100)

    @field_validator("knowledge_base_ids")
    @classmethod
    def _unique_positive_ids(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value <= 0 for value in values):
            raise ValueError("knowledge_base_ids must contain positive IDs")
        if len(set(values)) != len(values):
            raise ValueError("knowledge_base_ids must be unique")
        return values


class GovernedQueryRequest(StrictModel):
    request_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    question: str = Field(min_length=1, max_length=4_000)
    purpose: str = Field(min_length=1, max_length=512)
    purpose_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$",
    )
    channel: QueryChannel = QueryChannel.AUTO
    resource_version_refs: tuple[RequestedResourceVersion, ...] = Field(
        default=(),
        max_length=20,
    )
    budget: QueryBudget = Field(default_factory=QueryBudget)
    ontology_key: str = Field(default=ONTOLOGY_KEY, min_length=3, max_length=80)
    ontology_plan: OntologyQueryPlan | None = None
    metric_request: MetricQueryRequest | None = None
    metric_execution_mode: Literal["plan_only", "admit_run"] = "plan_only"
    nl2sql_request: NL2SQLQueryRequest | None = None
    gis_request: GISAnalysisRequest | None = None
    rag_request: RAGQueryRequest | None = None
    allow_non_equivalent_fallback: bool = False

    @field_validator("question", "purpose", "ontology_key")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query text fields cannot be blank")
        return value

    @model_validator(mode="after")
    def _plan_matches_channel(self) -> GovernedQueryRequest:
        if self.ontology_plan is not None and self.channel not in {
            QueryChannel.AUTO,
            QueryChannel.ONTOLOGY,
        }:
            raise ValueError("ontology_plan is only valid for auto or ontology channel")
        if self.metric_request is not None and self.channel not in {
            QueryChannel.AUTO,
            QueryChannel.METRIC,
        }:
            raise ValueError("metric_request is only valid for auto or metric channel")
        if self.rag_request is not None and self.channel not in {
            QueryChannel.AUTO,
            QueryChannel.RAG,
        }:
            raise ValueError("rag_request is only valid for auto or rag channel")
        typed_requests = sum(
            item is not None
            for item in (
                self.ontology_plan,
                self.metric_request,
                self.nl2sql_request,
                self.gis_request,
                self.rag_request,
            )
        )
        if typed_requests > 1:
            raise ValueError(
                "ontology_plan, metric_request, nl2sql_request, gis_request, and rag_request "
                "are mutually exclusive"
            )
        if self.channel is QueryChannel.METRIC and self.metric_request is None:
            raise ValueError("metric channel requires metric_request")
        if self.metric_request is not None and self.purpose_code is None:
            raise ValueError("metric channel requires purpose_code")
        if self.metric_execution_mode == "admit_run" and self.metric_request is None:
            raise ValueError("admit_run requires metric_request")
        if self.metric_execution_mode == "admit_run" and len(self.request_id) < 3:
            raise ValueError("admit_run request_id must be at least 3 characters")
        if self.nl2sql_request is not None and self.channel not in {
            QueryChannel.AUTO,
            QueryChannel.NL2SQL,
        }:
            raise ValueError("nl2sql_request is only valid for auto or nl2sql channel")
        if self.channel is QueryChannel.NL2SQL and self.nl2sql_request is None:
            raise ValueError("nl2sql channel requires nl2sql_request")
        if self.nl2sql_request is not None:
            if self.budget.max_llm_tokens < 128:
                raise ValueError("NL2SQL requires max_llm_tokens of at least 128")
            if self.budget.max_cost_usd <= 0:
                raise ValueError("NL2SQL requires an explicit positive max_cost_usd")
        if self.gis_request is not None and self.channel not in {
            QueryChannel.AUTO,
            QueryChannel.GIS,
        }:
            raise ValueError("gis_request is only valid for auto or GIS channel")
        if self.channel is QueryChannel.GIS and self.gis_request is None:
            raise ValueError("GIS channel requires gis_request")
        if self.channel is QueryChannel.RAG and self.rag_request is None:
            raise ValueError("RAG channel requires rag_request")
        if self.rag_request is not None:
            if not self.resource_version_refs:
                raise ValueError(
                    "RAG requires at least one pinned document resource_version_ref"
                )
            if any(ref.resource_kind != "document" for ref in self.resource_version_refs):
                raise ValueError("RAG resource_version_refs must all be documents")
            if any(ref.content_sha256 is None for ref in self.resource_version_refs):
                raise ValueError("RAG document pins require content_sha256")
            try:
                pins = tuple(
                    GovernedDocumentPin(
                        resource_id=ref.resource_id,
                        version=ref.version,
                        content_sha256=ref.content_sha256,
                    )
                    for ref in self.resource_version_refs
                )
            except ValueError as exc:
                raise ValueError(f"invalid RAG document pin: {exc}") from exc
            if any(pin.kb_id not in self.rag_request.knowledge_base_ids for pin in pins):
                raise ValueError("RAG document pins must belong to knowledge_base_ids")
            identities = {(pin.kb_id, pin.doc_id) for pin in pins}
            if len(identities) != len(pins):
                raise ValueError("RAG document pins must be unique")
            if self.rag_request.top_k > self.budget.max_result_items:
                raise ValueError("rag_request.top_k exceeds budget.max_result_items")
            if self.rag_request.top_k > self.budget.max_evidence_items:
                raise ValueError("rag_request.top_k exceeds budget.max_evidence_items")
        if (
            self.ontology_plan is not None
            and self.ontology_plan.limit > self.budget.max_result_items
        ):
            raise ValueError("ontology_plan.limit exceeds budget.max_result_items")
        return self


class QueryRoutePlan(StrictModel):
    requested_channel: QueryChannel
    selected_channel: QueryChannel | None
    admission: AdmissionState
    adapter_id: str | None = None
    reasons: tuple[str, ...] = Field(min_length=1)
    fallback_used: bool = False
    fallback_equivalent: bool | None = None


class EvidenceItem(StrictModel):
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    source_kind: Literal[
        "ontology_package",
        "semantic_model",
        "dataset",
        "document",
        "tool_result",
        "metric_definition",
        "metric_projection",
        "data_product",
        "source_snapshot",
        "table",
        "execution_plan",
        "query_result",
    ]
    source_id: str = Field(min_length=1, max_length=256)
    resource_version_ref: str = Field(min_length=1, max_length=256)
    locator: str = Field(min_length=1, max_length=1_024)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime


class EvidenceCitation(StrictModel):
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^claim_[0-9]{3}$")
    statement: str = Field(min_length=1, max_length=2_000)
    citations: tuple[EvidenceCitation, ...] = Field(default=(), max_length=20)


class CitationValidationIssue(StrictModel):
    claim_id: str
    evidence_id: str | None = None
    code: Literal[
        "uncited_claim",
        "unknown_evidence",
        "digest_mismatch",
        "duplicate_evidence_id",
    ]
    message: str


class CitationVerification(StrictModel):
    valid: bool
    verified_claim_count: int = Field(ge=0)
    issues: tuple[CitationValidationIssue, ...] = ()


class EvidenceBundle(StrictModel):
    request_id: str
    generated_at: datetime
    evidence: tuple[EvidenceItem, ...] = ()
    claims: tuple[Claim, ...] = ()
    verification: CitationVerification
    missing_evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


class QueryUsage(StrictModel):
    latency_ms: int = Field(ge=0)
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=0.0, ge=0)
    cost_status: Literal[
        "actual", "estimated", "not_applicable", "unavailable"
    ] = "not_applicable"
    within_budget: bool = True
    exceeded_limits: tuple[
        Literal[
            "max_latency_ms",
            "max_evidence_items",
            "max_result_items",
            "max_gis_features",
            "max_result_bytes",
            "max_llm_tokens",
            "max_cost_usd",
        ],
        ...,
    ] = ()
    budget_verification_issues: tuple[Literal["llm_cost_unavailable"], ...] = ()


class QueryPolicyBinding(StrictModel):
    action: Literal["semantic.query.execute"] = GOVERNED_QUERY_CAPABILITY_ID
    effect: Literal["allow"] = "allow"
    policy_version_ref: Literal["gda.semantic-query-policy.v1"] = (
        "gda.semantic-query-policy.v1"
    )
    tenant_scoped: Literal[True] = True
    evaluated_roles: tuple[str, ...]


class QueryRunReference(StrictModel):
    run_id: UUID
    client_request_id: str = Field(min_length=3, max_length=128)
    plan_artifact_id: UUID
    execution_mode: Literal["synchronous", "asynchronous"]
    run_status: RunStatus
    observation_status: Literal["not_started", "started", "completed"]
    outcome: Literal["succeeded", "failed"] | None = None
    result_artifact_id: UUID | None = None
    result_access_path: str | None = Field(default=None, pattern=r"^/api/")


class GovernedQueryResponse(StrictModel):
    schema_version: Literal["gda.governed-query-result.v4"] = Field(
        default="gda.governed-query-result.v4",
        alias="schema",
    )
    capability_id: Literal["semantic.query.execute"] = GOVERNED_QUERY_CAPABILITY_ID
    capability_version: Literal["4.1.0"] = GOVERNED_QUERY_CAPABILITY_VERSION
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: GovernedQueryRequest
    subject_context: SubjectContext
    policy: QueryPolicyBinding
    route_plan: QueryRoutePlan
    status: QueryExecutionStatus
    result: dict[str, Any] | None = None
    run_ref: QueryRunReference | None = None
    evidence_bundle: EvidenceBundle
    usage: QueryUsage

    @model_validator(mode="after")
    def _consistent_run_state(self) -> GovernedQueryResponse:
        run_statuses = {
            QueryExecutionStatus.RUN_ADMITTED,
            QueryExecutionStatus.RUN_SUCCEEDED,
            QueryExecutionStatus.RUN_FAILED,
        }
        if self.status in run_statuses and self.run_ref is None:
            raise ValueError(f"{self.status.value} requires run_ref")
        if self.status is QueryExecutionStatus.RUN_SUCCEEDED:
            assert self.run_ref is not None
            if (
                self.run_ref.run_status is not RunStatus.SUCCEEDED
                or self.run_ref.observation_status != "completed"
                or self.run_ref.outcome != "succeeded"
                or self.run_ref.result_artifact_id is None
                or self.run_ref.result_access_path is None
            ):
                raise ValueError(
                    "run_succeeded requires a completed successful observation "
                    "with result artifact access"
                )
        if self.status is QueryExecutionStatus.RUN_FAILED:
            assert self.run_ref is not None
            if self.run_ref.run_status not in {
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.TIMED_OUT,
            }:
                raise ValueError("run_failed requires a terminal unsuccessful run status")
            if (
                self.run_ref.outcome == "succeeded"
                or self.run_ref.result_artifact_id is not None
                or self.run_ref.result_access_path is not None
            ):
                raise ValueError("run_failed cannot expose a query result artifact")
        return self


class QueryAdapter(Protocol):
    channel: QueryChannel
    adapter_id: str

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]: ...


class OntologyQueryAdapter:
    channel = QueryChannel.ONTOLOGY
    adapter_id = "gda.ontology.typed-query.v1"

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]:
        if request.ontology_plan is None:
            raise GovernedQueryError("ontology channel requires ontology_plan")
        service = get_ontology_service(request.ontology_key)
        return service.execute_query(request.ontology_plan)


class MetricQueryAdapter:
    """Admit a deterministic metric plan without claiming a provider result."""

    channel = QueryChannel.METRIC
    adapter_id = "gda.metric.typed-plan.v1"

    def __init__(
        self,
        planner: MetricQueryPlanner | None = None,
        execution_authority: MetricQueryExecutionAuthority | None = None,
    ):
        self._planner = planner or MetricQueryPlanner()
        self._execution_authority = execution_authority

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]:
        if request.metric_request is None:
            raise GovernedQueryError("metric channel requires metric_request")
        if request.purpose_code is None:
            raise GovernedQueryError("metric channel requires purpose_code")
        security = MetricQuerySecurityContext(
            tenant_id=subject_context.tenant_id,
            subject_ref=(
                f"{subject_context.subject_type.value}:{subject_context.subject_id}"
            ),
            roles=subject_context.roles,
            purpose=request.purpose_code,
        )
        plan = self._planner.plan(request.metric_request, security)
        payload: dict[str, Any] = {
            "status": "planned",
            "metric_plan": plan.model_dump(mode="json"),
            "metric_request": request.metric_request.model_dump(mode="json"),
        }
        if request.metric_execution_mode == "admit_run":
            authority = self._execution_authority or MetricQueryExecutionAuthority()
            record = authority.admit(
                plan,
                security,
                request.request_id,
            )
            payload["status"] = "run_admitted"
            payload["metric_run"] = record.model_dump(mode="json")
        return payload


class NL2SQLQueryAdapter:
    """Execute NL2SQL only against version-locked immutable source bindings."""

    channel = QueryChannel.NL2SQL
    adapter_id = "gda.nl2sql.version-locked.v1"

    def __init__(self, source_authority: NL2SQLSourceAuthority | None = None):
        self._source_authority = source_authority

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]:
        if request.nl2sql_request is None:
            raise GovernedQueryError("NL2SQL channel requires nl2sql_request")
        source_authority = self._source_authority or NL2SQLSourceAuthority()
        bindings = {}
        for source_name in request.nl2sql_request.semantic_source_names:
            binding = source_authority.resolve(
                subject_context.tenant_id,
                source_name,
                request.nl2sql_request.execution_engine,
            )
            if binding.source_mode != "immutable_snapshot":
                raise NL2SQLSourceAdmissionError(
                    f"NL2SQL source {source_name} is mutable and cannot prove a snapshot"
                )
            bindings[source_name] = binding.model_dump(mode="json", by_alias=True)
        if len(bindings) + 1 > request.budget.max_evidence_items:
            raise NL2SQLSourceAdmissionError(
                "NL2SQL source evidence exceeds budget.max_evidence_items"
            )
        mismatches = _nl2sql_requested_binding_mismatches(request, bindings.values())
        if mismatches:
            raise NL2SQLSourceAdmissionError("; ".join(mismatches))

        from .nl2sql_executor import _referenced_sql_tables, run_nl2semantic2sql

        raw = run_nl2semantic2sql(
            request.question,
            request.nl2sql_request.execution_engine,
            governed_source_bindings=bindings,
            max_result_items=request.budget.max_result_items,
        )
        try:
            result = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise GovernedQueryError("NL2SQL executor returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise GovernedQueryError("NL2SQL executor returned a non-object result")
        sql = str(result.get("sql") or "")
        referenced = {
            _normalized_nl2sql_source_name(value)
            for value in _referenced_sql_tables(sql)
        }
        actual_bindings = [
            binding
            for name, binding in bindings.items()
            if _normalized_nl2sql_source_name(name) in referenced
        ]
        result["nl2sql_sources"] = actual_bindings
        if result.get("status") == "ok" and not actual_bindings:
            result["status"] = "rejected"
            result["error"] = "source_admission:no_versioned_source_referenced"
        if (
            result.get("status") == "ok"
            and int((result.get("llm_usage") or {}).get("calls") or 0) < 1
        ):
            result["status"] = "rejected"
            result["error"] = "llm_usage_evidence_unavailable"
        return result


class GISAnalysisQueryAdapter:
    """Admit a version-bound GIS Run without executing a provider inline."""

    channel = QueryChannel.GIS
    adapter_id = "gda.gis.typed-analysis.v1"

    def __init__(
        self,
        planner: GISAnalysisPlanner | None = None,
        execution_authority: GISAnalysisExecutionAuthority | None = None,
    ):
        self._planner = planner or GISAnalysisPlanner()
        self._execution_authority = execution_authority or GISAnalysisExecutionAuthority()

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]:
        if request.gis_request is None:
            raise GovernedQueryError("GIS channel requires gis_request")
        plan = self._planner.plan(
            request.gis_request,
            subject_context,
            GISAnalysisBudget(
                max_features=request.budget.max_gis_features,
                max_output_bytes=request.budget.max_result_bytes,
                max_duration_ms=request.budget.max_latency_ms,
            ),
        )
        record = self._execution_authority.admit(
            plan,
            subject_context,
            request.request_id,
        )
        return {
            "status": "run_admitted",
            "gis_request": request.gis_request.model_dump(mode="json"),
            "gis_plan": plan.model_dump(mode="json"),
            "gis_run": record.model_dump(mode="json"),
        }


class RAGQueryAdapter:
    """Retrieve only tenant-authorized chunks from pinned immutable documents."""

    channel = QueryChannel.RAG
    adapter_id = "gda.rag.versioned-evidence.v1"

    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ) -> dict[str, Any]:
        if request.rag_request is None:
            raise GovernedQueryError("RAG channel requires rag_request")
        pins = tuple(
            GovernedDocumentPin(
                resource_id=ref.resource_id,
                version=ref.version,
                content_sha256=ref.content_sha256,
            )
            for ref in request.resource_version_refs
            if ref.resource_kind == "document" and ref.content_sha256 is not None
        )
        hits = search_governed_knowledge_base(
            query=request.question,
            tenant_id=subject_context.tenant_id,
            subject_id=subject_context.subject_id,
            knowledge_base_ids=request.rag_request.knowledge_base_ids,
            document_pins=pins,
            top_k=request.rag_request.top_k,
        )
        return {
            "status": "ok",
            "query_mode": "governed_rag_retrieval",
            "execution": {"status": "ok", "rows": len(hits)},
            "hits": [hit.model_dump(mode="json") for hit in hits],
            "document_pins": [pin.model_dump(mode="json") for pin in pins],
            "llm_usage": {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "cost_status": "not_applicable",
            },
        }


_ADMITTED_ADAPTERS: dict[QueryChannel, QueryAdapter] = {
    QueryChannel.ONTOLOGY: OntologyQueryAdapter(),
    QueryChannel.METRIC: MetricQueryAdapter(),
    QueryChannel.NL2SQL: NL2SQLQueryAdapter(),
    QueryChannel.GIS: GISAnalysisQueryAdapter(),
    QueryChannel.RAG: RAGQueryAdapter(),
}
_PLANNED_ADAPTER_REASONS: dict[QueryChannel, str] = {}


def plan_query_route(request: GovernedQueryRequest | dict[str, Any]) -> QueryRoutePlan:
    """Create a deterministic route plan without executing any query tool."""
    if not isinstance(request, GovernedQueryRequest):
        request = GovernedQueryRequest.model_validate(request)

    selected = request.channel
    reasons: list[str] = []
    if selected is QueryChannel.AUTO:
        if request.ontology_plan is not None:
            selected = QueryChannel.ONTOLOGY
            reasons.append("validated ontology_plan deterministically selects ontology")
        elif request.metric_request is not None:
            selected = QueryChannel.METRIC
            reasons.append("validated metric_request deterministically selects metric")
        elif request.nl2sql_request is not None:
            selected = QueryChannel.NL2SQL
            reasons.append("validated nl2sql_request deterministically selects NL2SQL")
        elif request.gis_request is not None:
            selected = QueryChannel.GIS
            reasons.append("validated gis_request deterministically selects GIS")
        elif request.rag_request is not None:
            selected = QueryChannel.RAG
            reasons.append("validated rag_request deterministically selects RAG")
        else:
            return QueryRoutePlan(
                requested_channel=QueryChannel.AUTO,
                selected_channel=None,
                admission=AdmissionState.NOT_ADMITTED,
                reasons=(
                    "auto routing requires a validated typed plan; "
                    "question text alone is not executable",
                ),
                fallback_used=False,
                fallback_equivalent=None,
            )
    else:
        reasons.append(f"caller explicitly selected {selected.value}")

    adapter = _ADMITTED_ADAPTERS.get(selected)
    if adapter is None:
        reasons.append(_PLANNED_ADAPTER_REASONS[selected])
        if request.allow_non_equivalent_fallback:
            reasons.append("no semantically equivalent admitted fallback is registered")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    if selected is QueryChannel.ONTOLOGY and request.ontology_plan is None:
        reasons.append("ontology execution requires a closed OntologyQueryPlan")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            adapter_id=adapter.adapter_id,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    if selected is QueryChannel.METRIC and request.metric_request is None:
        reasons.append("metric execution requires a closed MetricQueryRequest")
        if request.allow_non_equivalent_fallback:
            reasons.append("no semantically equivalent admitted fallback is registered")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            adapter_id=adapter.adapter_id,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    if selected is QueryChannel.NL2SQL and request.nl2sql_request is None:
        reasons.append("NL2SQL execution requires a closed NL2SQLQueryRequest")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            adapter_id=adapter.adapter_id,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    if selected is QueryChannel.GIS and request.gis_request is None:
        reasons.append("GIS execution requires a closed GISAnalysisRequest")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            adapter_id=adapter.adapter_id,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    if selected is QueryChannel.RAG and request.rag_request is None:
        reasons.append("RAG execution requires a closed RAGQueryRequest")
        return QueryRoutePlan(
            requested_channel=request.channel,
            selected_channel=selected,
            admission=AdmissionState.NOT_ADMITTED,
            adapter_id=adapter.adapter_id,
            reasons=tuple(reasons),
            fallback_used=False,
            fallback_equivalent=False,
        )
    reasons.append(f"adapter {adapter.adapter_id} is admitted for deterministic execution")
    return QueryRoutePlan(
        requested_channel=request.channel,
        selected_channel=selected,
        admission=AdmissionState.ADMITTED,
        adapter_id=adapter.adapter_id,
        reasons=tuple(reasons),
        fallback_used=False,
        fallback_equivalent=None,
    )


def verify_claim_citations(
    evidence: tuple[EvidenceItem, ...] | list[EvidenceItem],
    claims: tuple[Claim, ...] | list[Claim],
) -> CitationVerification:
    """Verify that every claim cites an existing item with the exact digest."""
    evidence_by_id: dict[str, EvidenceItem] = {}
    issues: list[CitationValidationIssue] = []
    for item in evidence:
        if item.evidence_id in evidence_by_id:
            issues.append(CitationValidationIssue(
                claim_id="bundle",
                evidence_id=item.evidence_id,
                code="duplicate_evidence_id",
                message="evidence IDs must be unique within a bundle",
            ))
        evidence_by_id[item.evidence_id] = item

    verified = 0
    for claim in claims:
        claim_valid = bool(claim.citations)
        if not claim.citations:
            issues.append(CitationValidationIssue(
                claim_id=claim.claim_id,
                code="uncited_claim",
                message="factual claim has no evidence citation",
            ))
        for citation in claim.citations:
            item = evidence_by_id.get(citation.evidence_id)
            if item is None:
                claim_valid = False
                issues.append(CitationValidationIssue(
                    claim_id=claim.claim_id,
                    evidence_id=citation.evidence_id,
                    code="unknown_evidence",
                    message="citation references evidence absent from the bundle",
                ))
            elif item.content_sha256 != citation.content_sha256:
                claim_valid = False
                issues.append(CitationValidationIssue(
                    claim_id=claim.claim_id,
                    evidence_id=citation.evidence_id,
                    code="digest_mismatch",
                    message="citation digest does not match the evidence item",
                ))
        if claim_valid:
            verified += 1
    return CitationVerification(
        valid=not issues,
        verified_claim_count=verified,
        issues=tuple(issues),
    )


def _capability_fingerprint() -> str:
    from .capability_registry import get_capability_registry

    return get_capability_registry().get(GOVERNED_QUERY_CAPABILITY_ID).fingerprint


def _normalized_nl2sql_source_name(value: str) -> str:
    normalized = str(value or "").strip().strip('"')
    if normalized.casefold().startswith("public."):
        normalized = normalized[len("public.") :]
    return normalized.casefold()


def _empty_bundle(request_id: str, reasons: tuple[str, ...]) -> EvidenceBundle:
    return EvidenceBundle(
        request_id=request_id,
        generated_at=datetime.now(UTC),
        verification=CitationVerification(valid=True, verified_claim_count=0),
        missing_evidence=reasons,
    )


def _ontology_resource_mismatches(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    actual = payload.get("ontology_evidence") or {}
    package_id = str(actual.get("package_id") or "")
    version = str(actual.get("semantic_version") or "")
    digest = str(actual.get("content_sha256") or "")
    mismatches: list[str] = []
    for resource in request.resource_version_refs:
        if resource.resource_kind != "ontology_package":
            mismatches.append(
                f"requested {resource.resource_kind} resource is not consumed by ontology adapter"
            )
            continue
        if resource.resource_id not in {request.ontology_key, package_id}:
            mismatches.append(f"ontology resource {resource.resource_id} is not the active package")
        if resource.version != version:
            mismatches.append(
                f"ontology version {resource.version} does not match active version {version}"
            )
        if resource.content_sha256 and resource.content_sha256 != digest:
            mismatches.append("ontology content digest does not match the active package")
    return tuple(mismatches)


def _metric_resource_mismatches(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    plan = payload.get("metric_plan") or {}
    bindings = {
        "metric_definition": (
            plan.get("metric_version_ref"),
            plan.get("metric_fingerprint"),
        ),
        "metric_projection": (
            plan.get("projection_version_ref"),
            plan.get("projection_fingerprint"),
        ),
        "data_product": (
            plan.get("data_product_version_id"),
            None,
        ),
        "source_snapshot": (
            plan.get("source_snapshot_ref"),
            plan.get("source_manifest_sha256"),
        ),
    }
    mismatches: list[str] = []
    for resource in request.resource_version_refs:
        expected = bindings.get(resource.resource_kind)
        if expected is None:
            mismatches.append(
                f"requested {resource.resource_kind} resource is not consumed by metric adapter"
            )
            continue
        actual_ref, actual_digest = expected
        if resource.resource_id not in {str(actual_ref), str(actual_ref).split(".v")[0]}:
            mismatches.append(
                f"metric resource {resource.resource_id} is not bound by the active plan"
            )
        if resource.version not in {str(actual_ref), str(actual_ref).rsplit(".v", 1)[-1]}:
            mismatches.append(
                f"metric resource version {resource.version} does not match the active plan"
            )
        if resource.content_sha256 and resource.content_sha256 != actual_digest:
            mismatches.append("metric resource content digest does not match the active plan")
    return tuple(mismatches)


def _gis_resource_mismatches(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    plan = payload.get("gis_plan") or {}
    sources = plan.get("sources") or []
    mismatches: list[str] = []
    for resource in request.resource_version_refs:
        if resource.resource_kind not in {"dataset", "source_snapshot", "table"}:
            mismatches.append(
                f"requested {resource.resource_kind} resource is not consumed by GIS adapter"
            )
            continue
        matches = [
            source
            for source in sources
            if resource.resource_id
            in {
                str(source.get("resource_version_id") or ""),
                str(source.get("resource_urn") or ""),
                str(source.get("semantic_source_name") or ""),
            }
            and resource.version
            in {
                str(source.get("version_key") or ""),
                str(source.get("resource_version_id") or ""),
            }
        ]
        if resource.content_sha256 and not any(
            resource.content_sha256 == source.get("content_sha256") for source in matches
        ):
            matches = []
        if not matches:
            mismatches.append(
                f"requested GIS resource {resource.resource_id}@{resource.version} "
                "is not bound by the admitted plan"
            )
    return tuple(mismatches)


def _nl2sql_binding_matches_resource(
    binding: dict[str, Any],
    resource: RequestedResourceVersion,
) -> bool:
    urn = str(binding.get("resource_urn") or "")
    version_id = str(binding.get("resource_version_id") or "")
    source_name = str(binding.get("semantic_source_name") or "")
    resource_kind = urn.split("/", 4)[-2] if urn.startswith("gda://") else ""
    if resource.resource_kind != resource_kind:
        return False
    identities = {
        urn,
        version_id,
        source_name,
        urn.rsplit("/", 1)[-1],
    }
    if resource.resource_id not in identities:
        return False
    if resource.version not in {str(binding.get("version_key") or ""), version_id}:
        return False
    return (
        resource.content_sha256 is None
        or resource.content_sha256 == binding.get("content_sha256")
    )


def _nl2sql_requested_binding_mismatches(
    request: GovernedQueryRequest,
    bindings: Any,
) -> tuple[str, ...]:
    requested = tuple(request.resource_version_refs)
    if not requested:
        return ()
    values = tuple(bindings)
    mismatches: list[str] = []
    for binding in values:
        if not any(
            _nl2sql_binding_matches_resource(binding, resource)
            for resource in requested
        ):
            mismatches.append(
                "NL2SQL source "
                f"{binding.get('semantic_source_name')} is not pinned by "
                "resource_version_refs"
            )
    for resource in requested:
        if not any(
            _nl2sql_binding_matches_resource(binding, resource)
            for binding in values
        ):
            mismatches.append(
                f"requested {resource.resource_kind} resource "
                f"{resource.resource_id}@{resource.version} is not an active NL2SQL binding"
            )
    return tuple(mismatches)


def _rag_resource_mismatches(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> tuple[str, ...]:
    requested = {
        resource.resource_id: resource
        for resource in request.resource_version_refs
        if resource.resource_kind == "document"
    }
    actual_pins = {
        str(pin.get("resource_id") or ""): pin
        for pin in payload.get("document_pins") or []
    }
    mismatches: list[str] = []
    if set(actual_pins) != set(requested):
        mismatches.append("RAG adapter did not consume exactly the requested document pins")
    for resource_id, resource in requested.items():
        pin = actual_pins.get(resource_id) or {}
        if (
            pin.get("version") != resource.version
            or pin.get("content_sha256") != resource.content_sha256
        ):
            mismatches.append(
                f"RAG document {resource_id} does not match the requested immutable version"
            )
    for hit in payload.get("hits") or []:
        resource = requested.get(str(hit.get("document_resource_id") or ""))
        if resource is None or (
            hit.get("document_version") != resource.version
            or hit.get("document_content_sha256") != resource.content_sha256
        ):
            mismatches.append("RAG hit is not bound to a requested document version")
    return tuple(dict.fromkeys(mismatches))


def _ontology_bundle(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> EvidenceBundle:
    ontology_evidence = payload.get("ontology_evidence") or {}
    provenance = payload.get("query_provenance") or {}
    sources = provenance.get("sources") or []
    source = sources[0] if sources else {}
    package_id = str(ontology_evidence.get("package_id") or source.get("id") or "")
    version = str(ontology_evidence.get("semantic_version") or "")
    digest = str(ontology_evidence.get("content_sha256") or "")
    locator = str(source.get("resource") or "")
    if not package_id or not version or not locator or len(digest) != 64:
        return _empty_bundle(
            request.request_id,
            ("ontology adapter did not return complete versioned source evidence",),
        )

    evidence_id = "ev_" + canonical_json_fingerprint({
        "source_id": package_id,
        "version": version,
        "locator": locator,
        "sha256": digest,
    })[:24]
    item = EvidenceItem(
        evidence_id=evidence_id,
        source_kind="ontology_package",
        source_id=package_id,
        resource_version_ref=f"{package_id}@{version}",
        locator=locator,
        content_sha256=digest,
        retrieved_at=datetime.now(UTC),
    )
    facts = [
        str(value).strip()
        for value in (payload.get("result") or {}).get("answer_facts") or []
        if str(value).strip()
    ][: request.budget.max_evidence_items]
    claims = (
        Claim(
            claim_id=f"claim_{index:03d}",
            statement=fact,
            citations=(EvidenceCitation(evidence_id=evidence_id, content_sha256=digest),),
        )
        for index, fact in enumerate(facts, start=1)
    )
    evidence = (item,)
    verification = verify_claim_citations(evidence, claims)
    missing: tuple[str, ...] = ()
    if not claims and payload.get("status") == "ok":
        missing = ("ontology result returned no citable answer facts",)
    return EvidenceBundle(
        request_id=request.request_id,
        generated_at=datetime.now(UTC),
        evidence=evidence,
        claims=claims,
        verification=verification,
        missing_evidence=missing,
    )


def _metric_bundle(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> EvidenceBundle:
    plan = payload.get("metric_plan") or {}
    required = (
        ("metric_version_ref", "metric_definition", "metric_fingerprint"),
        ("projection_version_ref", "metric_projection", "projection_fingerprint"),
        ("source_snapshot_ref", "source_snapshot", "source_manifest_sha256"),
    )
    if not plan or any(not plan.get(field) for field, _, _ in required):
        return _empty_bundle(
            request.request_id,
            ("metric planner did not return complete versioned plan evidence",),
        )
    generated_at = datetime.now(UTC)
    evidence: list[EvidenceItem] = []
    for field, kind, digest_field in required:
        value = str(plan[field])
        digest = str(plan.get(digest_field) or "")
        if len(digest) != 64:
            return _empty_bundle(
                request.request_id,
                (f"metric plan evidence {field} has no valid content digest",),
            )
        evidence_id = "ev_" + canonical_json_fingerprint({
            "kind": kind,
            "version": value,
            "digest": digest,
        })[:24]
        evidence.append(EvidenceItem(
            evidence_id=evidence_id,
            source_kind=kind,
            source_id=value,
            resource_version_ref=value,
            locator=f"metric-plan:{field}",
            content_sha256=digest,
            retrieved_at=generated_at,
        ))
    run = payload.get("metric_run") or {}
    plan_artifact = run.get("plan_artifact") or {}
    observation = run.get("observation") or {}
    run_id = str((run.get("admission") or {}).get("run_id") or "")
    if plan_artifact:
        artifact_digest = str(plan_artifact.get("content_sha256") or "")
        artifact_id = str(plan_artifact.get("artifact_id") or "")
        storage_uri = str(plan_artifact.get("storage_uri") or "")
        if len(artifact_digest) != 64 or not artifact_id or not storage_uri:
            return _empty_bundle(
                request.request_id,
                ("metric run did not return complete execution plan artifact evidence",),
            )
        evidence.append(EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "kind": "execution_plan",
                "artifact_id": artifact_id,
                "digest": artifact_digest,
            })[:24],
            source_kind="execution_plan",
            source_id=artifact_id,
            resource_version_ref=f"metric-query-run:{run_id}",
            locator=storage_uri,
            content_sha256=artifact_digest,
            retrieved_at=generated_at,
        ))
    result_artifact_id = str(observation.get("result_artifact_id") or "")
    result_digest = str(observation.get("result_sha256") or "")
    if result_artifact_id or result_digest:
        if not result_artifact_id or len(result_digest) != 64:
            return _empty_bundle(
                request.request_id,
                ("metric completion returned incomplete result artifact evidence",),
            )
        evidence.append(EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "kind": "query_result",
                "artifact_id": result_artifact_id,
                "digest": result_digest,
            })[:24],
            source_kind="query_result",
            source_id=result_artifact_id,
            resource_version_ref=f"metric-query-run:{run_id}",
            locator=(
                f"/api/platform/v1/metric-query-runs/{run_id}/result-access"
            ),
            content_sha256=result_digest,
            retrieved_at=generated_at,
        ))
    claims = (
        Claim(
            claim_id="claim_001",
            statement=(
                f"Metric {plan['metric_version_ref']} is planned against "
                f"projection {plan['projection_version_ref']} using "
                f"{plan['execution_mode']} execution."
            ),
            citations=tuple(
                EvidenceCitation(
                    evidence_id=item.evidence_id,
                    content_sha256=item.content_sha256,
                )
                for item in evidence
            ),
        ),
    )
    missing = () if plan_artifact else (
        "metric execution plan artifact, run reference, provider observation and result "
        "artifact are not available; use metric-query-runs for provider execution",
    )
    if result_artifact_id:
        missing = ()
    elif plan_artifact:
        missing = (
            "metric provider result artifact and execution observation are not yet available; "
            "start and complete the admitted metric-query-run",
        )
    return EvidenceBundle(
        request_id=request.request_id,
        generated_at=generated_at,
        evidence=tuple(evidence),
        claims=claims,
        verification=verify_claim_citations(evidence, claims),
        missing_evidence=missing,
    )


def _nl2sql_bundle(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> EvidenceBundle:
    generated_at = datetime.now(UTC)
    bindings = payload.get("nl2sql_sources") or []
    if payload.get("status") != "ok" or not bindings:
        return _empty_bundle(
            request.request_id,
            (str(payload.get("error") or "NL2SQL did not produce an admitted result"),),
        )
    evidence: list[EvidenceItem] = []
    for binding in bindings:
        urn = str(binding.get("resource_urn") or "")
        version_id = str(binding.get("resource_version_id") or "")
        version_key = str(binding.get("version_key") or "")
        digest = str(binding.get("content_sha256") or "")
        locator = str(binding.get("physical_locator") or "")
        kind = urn.split("/", 4)[-2] if urn.startswith("gda://") else ""
        if (
            kind not in {"dataset", "data_product", "source_snapshot", "table"}
            or not urn
            or not version_id
            or not version_key
            or len(digest) != 64
            or not locator
        ):
            return _empty_bundle(
                request.request_id,
                ("NL2SQL adapter returned incomplete source-version evidence",),
            )
        evidence.append(EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "version_id": version_id,
                "digest": digest,
                "physical_binding": binding.get("physical_binding_sha256"),
            })[:24],
            source_kind=kind,
            source_id=urn,
            resource_version_ref=version_id,
            locator=locator,
            content_sha256=digest,
            retrieved_at=generated_at,
        ))
    execution = payload.get("execution") or {}
    result_digest = canonical_json_fingerprint(execution)
    result_item = EvidenceItem(
        evidence_id="ev_" + canonical_json_fingerprint({
            "request_id": request.request_id,
            "result_digest": result_digest,
        })[:24],
        source_kind="query_result",
        source_id=request.request_id,
        resource_version_ref=f"governed-query:{request.request_id}",
        locator=f"response:result.execution:{request.request_id}",
        content_sha256=result_digest,
        retrieved_at=generated_at,
    )
    evidence.append(result_item)
    rows = execution.get("rows")
    statement = (
        f"NL2SQL executed a read-only {payload.get('execution_engine')} query against "
        f"{len(bindings)} immutable source version(s)"
        + (f" and returned {rows} row(s)." if rows is not None else ".")
    )
    claims = (
        Claim(
            claim_id="claim_001",
            statement=statement,
            citations=tuple(
                EvidenceCitation(
                    evidence_id=item.evidence_id,
                    content_sha256=item.content_sha256,
                )
                for item in evidence
            ),
        ),
    )
    return EvidenceBundle(
        request_id=request.request_id,
        generated_at=generated_at,
        evidence=tuple(evidence),
        claims=claims,
        verification=verify_claim_citations(evidence, claims),
    )


def _rag_bundle(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> EvidenceBundle:
    generated_at = datetime.now(UTC)
    hits = payload.get("hits") or []
    if payload.get("status") != "ok" or not hits:
        return _empty_bundle(
            request.request_id,
            ("RAG retrieval did not return versioned document evidence",),
        )
    evidence: list[EvidenceItem] = []
    claims: list[Claim] = []
    for index, hit in enumerate(hits, start=1):
        resource_id = str(hit.get("document_resource_id") or "")
        version = str(hit.get("document_version") or "")
        digest = str(hit.get("chunk_content_sha256") or "")
        locator = str(hit.get("locator") or "")
        content = str(hit.get("content") or "").strip()
        if (
            not resource_id
            or not version
            or len(digest) != 64
            or not locator
            or not content
        ):
            return _empty_bundle(
                request.request_id,
                ("RAG adapter returned incomplete chunk-level evidence",),
            )
        item = EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "resource_id": resource_id,
                "version": version,
                "locator": locator,
                "digest": digest,
            })[:24],
            source_kind="document",
            source_id=resource_id,
            resource_version_ref=f"{resource_id}@{version}",
            locator=locator,
            content_sha256=digest,
            retrieved_at=generated_at,
        )
        evidence.append(item)
        claims.append(Claim(
            claim_id=f"claim_{index:03d}",
            statement=content[:2_000],
            citations=(EvidenceCitation(
                evidence_id=item.evidence_id,
                content_sha256=item.content_sha256,
            ),),
        ))
    return EvidenceBundle(
        request_id=request.request_id,
        generated_at=generated_at,
        evidence=tuple(evidence),
        claims=tuple(claims),
        verification=verify_claim_citations(evidence, claims),
    )


def _metric_run_reference(payload: dict[str, Any]) -> QueryRunReference | None:
    run_record = payload.get("metric_run")
    if not isinstance(run_record, dict):
        return None
    admission = run_record.get("admission") or {}
    run = run_record.get("run") or {}
    observation = run_record.get("observation")
    if observation is None:
        observation_status = "not_started"
        outcome = None
        result_artifact_id = None
    else:
        observation_status = "completed"
        outcome = observation.get("outcome")
        result_artifact_id = observation.get("result_artifact_id")
    if run.get("status") == RunStatus.RUNNING.value and observation is None:
        observation_status = "started"
    return QueryRunReference(
        run_id=admission["run_id"],
        client_request_id=admission["client_request_id"],
        plan_artifact_id=admission["plan_artifact_id"],
        execution_mode=admission["execution_mode"],
        run_status=run["status"],
        observation_status=observation_status,
        outcome=outcome,
        result_artifact_id=result_artifact_id,
        result_access_path=(
            f"/api/platform/v1/metric-query-runs/{admission['run_id']}/result-access"
            if result_artifact_id is not None
            else None
        ),
    )


def _gis_run_reference(payload: dict[str, Any]) -> QueryRunReference | None:
    run_record = payload.get("gis_run")
    if not isinstance(run_record, dict):
        return None
    admission = run_record.get("admission") or {}
    run = run_record.get("run") or {}
    observation = run_record.get("observation")
    result_artifact_id = None
    outcome = None
    observation_status = "not_started"
    if isinstance(observation, dict):
        observation_status = "completed"
        outcome = observation.get("outcome")
        result_artifact_id = observation.get("result_artifact_id")
    elif run.get("status") == RunStatus.RUNNING.value:
        observation_status = "started"
    run_id = admission.get("run_id")
    if not run_id or not run.get("status"):
        return None
    return QueryRunReference(
        run_id=run_id,
        client_request_id=admission["client_request_id"],
        plan_artifact_id=admission["plan_artifact_id"],
        execution_mode="asynchronous",
        run_status=run["status"],
        observation_status=observation_status,
        outcome=outcome,
        result_artifact_id=result_artifact_id,
        result_access_path=(
            f"/api/platform/v1/gis-analysis-runs/{run_id}/result-access"
            if result_artifact_id is not None
            else None
        ),
    )


def _gis_bundle(
    request: GovernedQueryRequest,
    payload: dict[str, Any],
) -> EvidenceBundle:
    generated_at = datetime.now(UTC)
    plan = payload.get("gis_plan") or {}
    run = payload.get("gis_run") or {}
    if not plan or not run:
        return _empty_bundle(
            request.request_id,
            ("GIS admission did not return plan and Run evidence",),
        )
    evidence: list[EvidenceItem] = []
    for source in plan.get("sources") or []:
        version_id = str(source.get("resource_version_id") or "")
        digest = str(source.get("content_sha256") or "")
        locator = str(source.get("physical_relation") or "")
        if not version_id or len(digest) != 64 or not locator:
            return _empty_bundle(
                request.request_id,
                ("GIS plan returned incomplete source-version evidence",),
            )
        evidence.append(EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "resource_version_id": version_id,
                "content_sha256": digest,
                "physical_binding_sha256": source.get("physical_binding_sha256"),
            })[:24],
            source_kind="source_snapshot",
            source_id=str(source.get("resource_urn") or version_id),
            resource_version_ref=version_id,
            locator=locator,
            content_sha256=digest,
            retrieved_at=generated_at,
        ))
    admission = run.get("admission") or {}
    plan_artifact = run.get("plan_artifact") or {}
    plan_digest = str(plan_artifact.get("content_sha256") or "")
    if len(plan_digest) != 64:
        return _empty_bundle(
            request.request_id,
            ("GIS run did not return execution plan artifact evidence",),
        )
    evidence.append(EvidenceItem(
        evidence_id="ev_" + canonical_json_fingerprint({
            "artifact_id": plan_artifact.get("artifact_id"),
            "digest": plan_digest,
        })[:24],
        source_kind="execution_plan",
        source_id=str(plan_artifact.get("artifact_id") or ""),
        resource_version_ref=f"gis-analysis-run:{admission.get('run_id')}",
        locator=str(plan_artifact.get("storage_uri") or ""),
        content_sha256=plan_digest,
        retrieved_at=generated_at,
    ))
    observation = run.get("observation") or {}
    result_id = str(observation.get("result_artifact_id") or "")
    result_digest = str(observation.get("result_sha256") or "")
    if result_id or result_digest:
        if not result_id or len(result_digest) != 64:
            return _empty_bundle(
                request.request_id,
                ("GIS completion returned incomplete result artifact evidence",),
            )
        evidence.append(EvidenceItem(
            evidence_id="ev_" + canonical_json_fingerprint({
                "artifact_id": result_id,
                "digest": result_digest,
            })[:24],
            source_kind="query_result",
            source_id=result_id,
            resource_version_ref=f"gis-analysis-run:{admission.get('run_id')}",
            locator=(
                f"/api/platform/v1/gis-analysis-runs/{admission.get('run_id')}"
                "/result-access"
            ),
            content_sha256=result_digest,
            retrieved_at=generated_at,
        ))
    claim = Claim(
        claim_id="claim_001",
        statement=(
            f"GIS {plan.get('operation')} analysis is admitted against "
            f"{len(plan.get('sources') or [])} immutable PostGIS source version(s)."
        ),
        citations=tuple(
            EvidenceCitation(
                evidence_id=item.evidence_id,
                content_sha256=item.content_sha256,
            )
            for item in evidence
        ),
    )
    return EvidenceBundle(
        request_id=request.request_id,
        generated_at=generated_at,
        evidence=tuple(evidence),
        claims=(claim,),
        verification=verify_claim_citations(evidence, (claim,)),
        missing_evidence=(
            ()
            if result_id
            else ("GIS provider result Artifact is not yet available",)
        ),
    )


def execute_governed_query(
    request: GovernedQueryRequest | dict[str, Any],
    subject_context: SubjectContext,
    *,
    security_reader: GovernedQuerySecurityCurrentReader | None = None,
    security_audit_port: GovernedQuerySecurityAuditPort | None = None,
) -> GovernedQueryResponse:
    """Validate, route, execute, and verify one read-only semantic query."""
    started = perf_counter()
    if not isinstance(request, GovernedQueryRequest):
        request = GovernedQueryRequest.model_validate(request)
    if subject_context.purpose != request.purpose:
        raise QueryPolicyDeniedError("subject purpose must match the validated query purpose")
    allowed_roles = {"viewer", "analyst", "admin", "platform_operator"}
    if not set(subject_context.roles) & allowed_roles:
        raise QueryPolicyDeniedError("subject has no role admitted for semantic query")

    route = plan_query_route(request)
    if route.admission is AdmissionState.NOT_ADMITTED:
        elapsed = int((perf_counter() - started) * 1_000)
        return GovernedQueryResponse(
            capability_fingerprint=_capability_fingerprint(),
            request=request,
            subject_context=subject_context,
            policy=QueryPolicyBinding(evaluated_roles=subject_context.roles),
            route_plan=route,
            status=QueryExecutionStatus.NOT_ADMITTED,
            evidence_bundle=_empty_bundle(request.request_id, route.reasons),
            usage=QueryUsage(latency_ms=elapsed),
        )

    security_admission = None
    security_request = None
    if security_reader is not None or security_audit_port is not None:
        try:
            reader, audit_port = require_query_security_ports(
                security_reader, security_audit_port, subject_context.tenant_id
            )
            resource_refs = tuple(
                f"{item.resource_kind}:{item.resource_id}@{item.version}"
                for item in request.resource_version_refs
            ) or (f"channel:{route.selected_channel.value}",)
            security_purpose_code = (
                request.purpose_code or GOVERNED_QUERY_SECURITY_PURPOSE
            )
            security_subject_context = subject_context.model_copy(
                update={"purpose": security_purpose_code}
            )
            security_request = build_query_security_request(
                request_payload_sha256=canonical_json_fingerprint(
                    request.model_dump(mode="json")
                ),
                request_id=request.request_id,
                tenant_id=subject_context.tenant_id,
                subject_context=security_subject_context,
                purpose_code=security_purpose_code,
                channel=route.selected_channel.value,
                adapter_id=route.adapter_id or "gda.unknown",
                resource_refs=resource_refs,
                evaluated_at=datetime.now(UTC),
            )
            try:
                decision = reader.governed_query_security_decision_current(security_request)
            except Exception as exc:
                raise GovernedQuerySecurityError(
                    "live governed query security reader failed"
                ) from exc
            if (
                decision.request != security_request
                or decision.effect != "allow"
                or decision.obligations
                or decision.expires_at <= datetime.now(UTC)
                or decision.decided_at > datetime.now(UTC)
            ):
                raise GovernedQuerySecurityError(
                    "live governed query security decision is not an exact current allow"
                )
            try:
                security_admission = audit_port.record_admission(
                    security_request, decision
                )
            except Exception as exc:
                raise GovernedQuerySecurityError(
                    "governed query admission audit failed"
                ) from exc
        except Exception as exc:
            reasons = (*route.reasons, str(exc))
            route = route.model_copy(update={
                "admission": AdmissionState.NOT_ADMITTED,
                "reasons": reasons,
            })
            elapsed = int((perf_counter() - started) * 1_000)
            return GovernedQueryResponse(
                capability_fingerprint=_capability_fingerprint(),
                request=request,
                subject_context=subject_context,
                policy=QueryPolicyBinding(evaluated_roles=subject_context.roles),
                route_plan=route,
                status=QueryExecutionStatus.NOT_ADMITTED,
                result=None,
                evidence_bundle=_empty_bundle(request.request_id, reasons),
                usage=QueryUsage(latency_ms=elapsed),
            )

    adapter = _ADMITTED_ADAPTERS[route.selected_channel]
    try:
        payload = adapter.execute(request, subject_context)
    except (
        GovernedQueryError,
        MetricQueryPlanningError,
        MetricAuthorityError,
        MetricProjectionAuthorityError,
        MetricQueryExecutionError,
        GISAnalysisExecutionError,
        NL2SQLSourceAuthorityError,
        GovernedRAGError,
    ) as exc:
        if security_admission is not None and security_audit_port is not None:
            try:
                security_audit_port.record_outcome(
                    security_admission,
                    outcome="failure",
                    evidence_sha256=canonical_json_fingerprint({"error": str(exc)}),
                    adapter_invocations=1,
                    recorded_at=datetime.now(UTC),
                )
            except Exception as audit_exc:
                raise QueryPolicyDeniedError(
                    "immutable query failure audit could not be recorded"
                ) from audit_exc
        reasons = (*route.reasons, str(exc), *getattr(exc, "rejections", ()))
        route = route.model_copy(update={
            "admission": AdmissionState.NOT_ADMITTED,
            "reasons": reasons,
        })
        elapsed = int((perf_counter() - started) * 1_000)
        return GovernedQueryResponse(
            capability_fingerprint=_capability_fingerprint(),
            request=request,
            subject_context=subject_context,
            policy=QueryPolicyBinding(evaluated_roles=subject_context.roles),
            route_plan=route,
            status=QueryExecutionStatus.NOT_ADMITTED,
            result=None,
            evidence_bundle=_empty_bundle(request.request_id, reasons),
            usage=QueryUsage(latency_ms=elapsed),
        )
    if route.selected_channel is QueryChannel.ONTOLOGY:
        mismatches = _ontology_resource_mismatches(request, payload)
    elif route.selected_channel is QueryChannel.METRIC:
        mismatches = _metric_resource_mismatches(request, payload)
    elif route.selected_channel is QueryChannel.GIS:
        mismatches = _gis_resource_mismatches(request, payload)
    elif route.selected_channel is QueryChannel.NL2SQL:
        mismatches = _nl2sql_requested_binding_mismatches(
            request,
            payload.get("nl2sql_sources") or [],
        )
    else:
        mismatches = _rag_resource_mismatches(request, payload)
    if mismatches:
        route = route.model_copy(update={
            "admission": AdmissionState.NOT_ADMITTED,
            "reasons": (*route.reasons, *mismatches),
        })
        elapsed = int((perf_counter() - started) * 1_000)
        if security_admission is not None and security_audit_port is not None:
            try:
                security_audit_port.record_outcome(
                    security_admission,
                    outcome="failure",
                    evidence_sha256=canonical_json_fingerprint({"mismatches": mismatches}),
                    adapter_invocations=1,
                    recorded_at=datetime.now(UTC),
                )
            except Exception as audit_exc:
                raise QueryPolicyDeniedError(
                    "immutable query binding audit could not be recorded"
                ) from audit_exc
        return GovernedQueryResponse(
            capability_fingerprint=_capability_fingerprint(),
            request=request,
            subject_context=subject_context,
            policy=QueryPolicyBinding(evaluated_roles=subject_context.roles),
            route_plan=route,
            status=QueryExecutionStatus.NOT_ADMITTED,
            result=None,
            evidence_bundle=_empty_bundle(request.request_id, mismatches),
            usage=QueryUsage(latency_ms=elapsed),
        )

    if route.selected_channel is QueryChannel.ONTOLOGY:
        bundle = _ontology_bundle(request, payload)
    elif route.selected_channel is QueryChannel.METRIC:
        bundle = _metric_bundle(request, payload)
    elif route.selected_channel is QueryChannel.GIS:
        bundle = _gis_bundle(request, payload)
    elif route.selected_channel is QueryChannel.NL2SQL:
        bundle = _nl2sql_bundle(request, payload)
    else:
        bundle = _rag_bundle(request, payload)
    payload_status = payload.get("status")
    if payload_status == "ok":
        status = QueryExecutionStatus.COMPLETED
    elif payload_status == "run_admitted":
        run_ref = (
            _metric_run_reference(payload)
            if route.selected_channel is QueryChannel.METRIC
            else _gis_run_reference(payload)
        )
        if run_ref is not None and run_ref.run_status is RunStatus.SUCCEEDED:
            status = QueryExecutionStatus.RUN_SUCCEEDED
        elif run_ref is not None and run_ref.run_status in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }:
            status = QueryExecutionStatus.RUN_FAILED
        else:
            status = QueryExecutionStatus.RUN_ADMITTED
    elif payload_status == "planned":
        status = QueryExecutionStatus.PLANNED
    else:
        status = QueryExecutionStatus.NEEDS_CLARIFICATION
    if not bundle.verification.valid:
        status = QueryExecutionStatus.NEEDS_CLARIFICATION
    elapsed = int((perf_counter() - started) * 1_000)
    llm_usage = payload.get("llm_usage") or {}
    llm_calls = int(llm_usage.get("calls") or 0)
    input_tokens = int(llm_usage.get("input_tokens") or 0)
    output_tokens = int(llm_usage.get("output_tokens") or 0)
    total_tokens = int(llm_usage.get("total_tokens") or input_tokens + output_tokens)
    estimated_cost = llm_usage.get("estimated_cost_usd")
    cost_status = str(llm_usage.get("cost_status") or "not_applicable")
    if llm_calls == 0:
        estimated_cost = 0.0
        cost_status = "not_applicable"
    exceeded: list[
        Literal[
            "max_latency_ms",
            "max_evidence_items",
            "max_result_items",
            "max_gis_features",
            "max_result_bytes",
            "max_llm_tokens",
            "max_cost_usd",
        ]
    ] = []
    if elapsed > request.budget.max_latency_ms:
        exceeded.append("max_latency_ms")
    if len(bundle.evidence) > request.budget.max_evidence_items:
        exceeded.append("max_evidence_items")
    result_rows = int((payload.get("execution") or {}).get("rows") or 0)
    if result_rows > request.budget.max_result_items:
        exceeded.append("max_result_items")
    result_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if result_bytes > request.budget.max_result_bytes:
        exceeded.append("max_result_bytes")
    if route.selected_channel is QueryChannel.GIS:
        gis_plan = payload.get("gis_plan") or {}
        gis_budget = gis_plan.get("budget") or {}
        if int(gis_budget.get("max_features") or 0) > request.budget.max_gis_features:
            exceeded.append("max_gis_features")
        if int(gis_budget.get("max_output_bytes") or 0) > request.budget.max_result_bytes:
            exceeded.append("max_result_bytes")
    if total_tokens > request.budget.max_llm_tokens:
        exceeded.append("max_llm_tokens")
    if estimated_cost is not None and float(estimated_cost) > request.budget.max_cost_usd:
        exceeded.append("max_cost_usd")
    budget_issues: tuple[Literal["llm_cost_unavailable"], ...] = ()
    if llm_calls and estimated_cost is None:
        budget_issues = ("llm_cost_unavailable",)
    exceeded_limits = tuple(dict.fromkeys(exceeded))
    if exceeded_limits or budget_issues:
        status = QueryExecutionStatus.NEEDS_CLARIFICATION
    response = GovernedQueryResponse(
        capability_fingerprint=_capability_fingerprint(),
        request=request,
        subject_context=subject_context,
        policy=QueryPolicyBinding(evaluated_roles=subject_context.roles),
        route_plan=route,
        status=status,
        result=payload,
        run_ref=(
            _metric_run_reference(payload)
            if route.selected_channel is QueryChannel.METRIC
            else _gis_run_reference(payload)
            if route.selected_channel is QueryChannel.GIS
            else None
        ),
        evidence_bundle=bundle,
        usage=QueryUsage(
            latency_ms=elapsed,
            llm_calls=llm_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=(
                float(estimated_cost) if estimated_cost is not None else None
            ),
            cost_status=cost_status,
            within_budget=not exceeded_limits and not budget_issues,
            exceeded_limits=exceeded_limits,
            budget_verification_issues=budget_issues,
        ),
    )
    if security_admission is not None and security_audit_port is not None:
        try:
            security_audit_port.record_outcome(
                security_admission,
                outcome=(
                    "success"
                    if response.status
                    in {
                        QueryExecutionStatus.COMPLETED,
                        QueryExecutionStatus.RUN_SUCCEEDED,
                        QueryExecutionStatus.PLANNED,
                        QueryExecutionStatus.RUN_ADMITTED,
                    }
                    else "failure"
                ),
                evidence_sha256=canonical_json_fingerprint(
                    response.evidence_bundle.model_dump(mode="json")
                ),
                adapter_invocations=1,
                recorded_at=datetime.now(UTC),
            )
        except Exception as exc:
            raise QueryPolicyDeniedError(
                "immutable query outcome audit could not be recorded"
            ) from exc
    return response
