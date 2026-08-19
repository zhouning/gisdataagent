"""Authenticated HTTP projection for semantic planning and evidence fusion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..capability_registry import CapabilityRegistry, get_capability_registry
from ..governed_query import (
    AdmissionState,
    GovernedQueryRequest,
    QueryChannel,
    RequestedResourceVersion,
    execute_governed_query,
    plan_query_route,
)
from ..governed_query_security import resolve_governed_query_security_ports
from ..platform_contracts import (
    NonEmptyText,
    ShortName,
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
)
from ..semantic_query_orchestration import (
    GOVERNED_QUERY_CAPABILITY_ID,
    GOVERNED_QUERY_EVALUATOR_REF,
    AutomaticSemanticPlanner,
    ClarificationResolution,
    GovernedQueryNodeExecutor,
    PlannerModelBinding,
    PlanningInvocationSurface,
    PlanningStatus,
    SemanticCandidateProposer,
    SemanticClarificationError,
    SemanticExecutionPlan,
    SemanticPlanAdmissionError,
    SemanticPlanExecutor,
    SemanticPlanningBudget,
    SemanticPlanningOutcome,
    build_planner_model_binding,
    build_semantic_planning_request,
)
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context

RequestModel = TypeVar("RequestModel", bound=BaseModel)
_ADMITTED_ROLES = frozenset({"viewer", "analyst", "admin", "platform_operator"})


class SemanticPlanningHttpError(RuntimeError):
    """Base error for the authenticated semantic planning projection."""


class SemanticPlanningPortsUnavailableError(SemanticPlanningHttpError):
    """Server-owned planner or executor ports cannot be resolved."""


class SemanticPlanNotFoundError(SemanticPlanningHttpError):
    """No plan is visible in the authenticated tenant scope."""


class SemanticPlanConflictError(SemanticPlanningHttpError):
    """A stored plan no longer matches its authenticated serving context."""


class SemanticPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: ShortName
    question: str = Field(min_length=1, max_length=4_000)
    purpose: NonEmptyText
    purpose_code: ShortName
    allowed_channels: tuple[QueryChannel, ...] = Field(min_length=1, max_length=5)
    resource_version_refs: tuple[RequestedResourceVersion, ...] = Field(
        min_length=1,
        max_length=64,
    )
    budget: SemanticPlanningBudget = Field(default_factory=SemanticPlanningBudget)
    deterministic_seed_requests: tuple[GovernedQueryRequest, ...] = Field(
        default=(),
        max_length=5,
    )

    @model_validator(mode="after")
    def _bounded_and_pinned(self) -> SemanticPlanCreateRequest:
        if QueryChannel.AUTO in self.allowed_channels:
            raise ValueError("allowed_channels must be deterministic")
        if len(self.allowed_channels) != len(set(self.allowed_channels)):
            raise ValueError("allowed_channels must be unique")
        if any(item.content_sha256 is None for item in self.resource_version_refs):
            raise ValueError("all planning resources require immutable content pins")
        return self


class SemanticClarificationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clarification_id: ShortName
    selected_option_id: ShortName


class SemanticPlanClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selections: tuple[SemanticClarificationSelection, ...] = Field(
        min_length=1,
        max_length=16,
    )

    @model_validator(mode="after")
    def _unique_selections(self) -> SemanticPlanClarificationRequest:
        identities = tuple(item.clarification_id for item in self.selections)
        if len(identities) != len(set(identities)):
            raise ValueError("clarification selections must be unique")
        return self


class SemanticPlanExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticPlanRepository(Protocol):
    def put(self, plan: SemanticExecutionPlan) -> SemanticExecutionPlan: ...

    def get(self, tenant_id: str, plan_sha256: str) -> SemanticExecutionPlan: ...

    def assert_replan_allowed(self, tenant_id: str, plan_sha256: str) -> None: ...

    def put_successor(
        self,
        prior: SemanticExecutionPlan,
        successor: SemanticExecutionPlan,
    ) -> SemanticExecutionPlan: ...


class InMemorySemanticPlanRepository:
    """Tenant-scoped development repository; it is not a durable authority."""

    def __init__(self) -> None:
        self._plans: dict[tuple[str, str], SemanticExecutionPlan] = {}
        self._successors: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def put(self, plan: SemanticExecutionPlan) -> SemanticExecutionPlan:
        key = (plan.request.tenant_id, plan.plan_sha256)
        with self._lock:
            current = self._plans.get(key)
            if current is not None and current != plan:
                raise SemanticPlanConflictError("semantic plan identity drifted")
            self._plans[key] = plan
        return plan

    def get(self, tenant_id: str, plan_sha256: str) -> SemanticExecutionPlan:
        with self._lock:
            plan = self._plans.get((tenant_id, plan_sha256))
        if plan is None:
            raise SemanticPlanNotFoundError("semantic plan was not found")
        return plan

    def assert_replan_allowed(self, tenant_id: str, plan_sha256: str) -> None:
        with self._lock:
            if (tenant_id, plan_sha256) in self._successors:
                raise SemanticPlanConflictError("semantic plan was superseded")

    def put_successor(
        self,
        prior: SemanticExecutionPlan,
        successor: SemanticExecutionPlan,
    ) -> SemanticExecutionPlan:
        key = (prior.request.tenant_id, prior.plan_sha256)
        successor_key = (successor.request.tenant_id, successor.plan_sha256)
        if (
            successor.request.tenant_id != prior.request.tenant_id
            or successor.supersedes_plan_sha256 != prior.plan_sha256
        ):
            raise SemanticPlanConflictError("semantic plan successor binding drifted")
        with self._lock:
            current = self._plans.get(key)
            if current != prior:
                raise SemanticPlanConflictError("semantic prior plan drifted")
            recorded_successor = self._successors.get(key)
            if recorded_successor is not None:
                if (
                    recorded_successor == successor.plan_sha256
                    and self._plans.get(successor_key) == successor
                ):
                    return successor
                raise SemanticPlanConflictError("semantic plan was superseded")
            existing = self._plans.get(successor_key)
            if existing is not None and existing != successor:
                raise SemanticPlanConflictError("semantic plan identity drifted")
            self._plans[successor_key] = successor
            self._successors[key] = successor.plan_sha256
        return successor


@dataclass(frozen=True, slots=True)
class SemanticPlanningPorts:
    tenant_id: str
    planner_binding: PlannerModelBinding
    proposer: SemanticCandidateProposer
    executor: GovernedQueryNodeExecutor
    repository: SemanticPlanRepository


class SemanticPlanningPortResolver(Protocol):
    def resolve(self, tenant_id: str) -> SemanticPlanningPorts: ...


class _UnavailableCandidateProposer:
    def propose(self, request, *, previous_plan, resolutions):
        raise RuntimeError("semantic planning model provider is not configured")


class _GovernedQueryNodeExecutor:
    def execute(
        self,
        request: GovernedQueryRequest,
        subject_context: SubjectContext,
    ):
        security_ports = resolve_governed_query_security_ports(subject_context.tenant_id)
        security_kwargs = (
            {}
            if security_ports is None
            else {
                "security_reader": security_ports[0],
                "security_audit_port": security_ports[1],
            }
        )
        return execute_governed_query(
            request,
            subject_context,
            **security_kwargs,
        )


class DevelopmentSemanticPlanningPortResolver:
    """Seed-only development binding until a real model proposer is installed."""

    def __init__(
        self,
        repository: SemanticPlanRepository | None = None,
    ) -> None:
        self._repository = repository or InMemorySemanticPlanRepository()
        self._binding = build_planner_model_binding(
            provider="deterministic",
            model="typed-seed-fallback",
            model_version="1.0.0",
            prompt_version="semantic-plan.v1",
        )
        self._proposer = _UnavailableCandidateProposer()
        self._executor = _GovernedQueryNodeExecutor()

    def resolve(self, tenant_id: str) -> SemanticPlanningPorts:
        return SemanticPlanningPorts(
            tenant_id=tenant_id,
            planner_binding=self._binding,
            proposer=self._proposer,
            executor=self._executor,
            repository=self._repository,
        )


_semantic_planning_port_resolver: SemanticPlanningPortResolver | None = None


def configure_semantic_planning_port_resolver(
    resolver: SemanticPlanningPortResolver | None,
) -> None:
    """Install the application-owned planner, executor, and repository resolver."""

    global _semantic_planning_port_resolver
    if resolver is not None and not callable(getattr(resolver, "resolve", None)):
        raise SemanticPlanningPortsUnavailableError("semantic planning port resolver is invalid")
    _semantic_planning_port_resolver = resolver


def semantic_planning_port_resolver_configured() -> bool:
    return _semantic_planning_port_resolver is not None


def configure_default_semantic_planning_port_resolver() -> bool:
    """Install the honest seed-only development projection when unconfigured."""

    if semantic_planning_port_resolver_configured():
        return False
    configure_semantic_planning_port_resolver(DevelopmentSemanticPlanningPortResolver())
    return True


def resolve_semantic_planning_ports(tenant_id: str) -> SemanticPlanningPorts:
    resolver = _semantic_planning_port_resolver
    if resolver is None:
        raise SemanticPlanningPortsUnavailableError("semantic planning ports are not configured")
    try:
        ports = resolver.resolve(tenant_id)
    except SemanticPlanningHttpError:
        raise
    except Exception as exc:
        raise SemanticPlanningPortsUnavailableError(
            "semantic planning port resolution failed"
        ) from exc
    if not isinstance(ports, SemanticPlanningPorts):
        raise SemanticPlanningPortsUnavailableError(
            "semantic planning resolver returned invalid ports"
        )
    if ports.tenant_id != tenant_id:
        raise SemanticPlanningPortsUnavailableError(
            "semantic planning resolver returned a different tenant"
        )
    if not callable(getattr(ports.proposer, "propose", None)):
        raise SemanticPlanningPortsUnavailableError("semantic planning proposer is invalid")
    if not callable(getattr(ports.executor, "execute", None)):
        raise SemanticPlanningPortsUnavailableError("semantic planning executor is invalid")
    if not all(
        callable(getattr(ports.repository, operation, None))
        for operation in (
            "put",
            "get",
            "assert_replan_allowed",
            "put_successor",
        )
    ):
        raise SemanticPlanningPortsUnavailableError("semantic planning repository is invalid")
    return ports


def _metadata(user: Any) -> dict[str, Any]:
    value = getattr(user, "metadata", None)
    return value if isinstance(value, dict) else {}


def _roles(user: Any, default_role: str) -> tuple[str, ...]:
    configured = _metadata(user).get("roles", ())
    if isinstance(configured, str):
        configured = (configured,)
    if not isinstance(configured, (list, tuple, set)):
        configured = ()
    return tuple(
        sorted({str(role).strip() for role in (*configured, default_role) if str(role).strip()})
    )


def _authenticated_context(
    request: Request,
) -> tuple[str, str, tuple[str, ...], JSONResponse | None]:
    user = _get_user_from_request(request)
    if not user:
        return (
            "",
            "",
            (),
            JSONResponse(
                {"error": "Unauthorized", "code": "authentication_required"},
                status_code=401,
            ),
        )
    username, default_role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return (
            "",
            "",
            (),
            JSONResponse(
                {
                    "error": "Authenticated identity has no tenant binding",
                    "code": "tenant_context_required",
                },
                status_code=403,
            ),
        )
    roles = _roles(user, str(default_role))
    if not set(roles) & _ADMITTED_ROLES:
        return (
            "",
            "",
            (),
            JSONResponse(
                {
                    "error": "Authenticated identity cannot use semantic planning",
                    "code": "semantic_planning_role_required",
                },
                status_code=403,
            ),
        )
    return tenant_id, str(username).strip(), roles, None


async def _parse_request(
    request: Request,
    model_type: type[RequestModel],
) -> RequestModel:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError("Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return model_type.model_validate(payload)


def _subject(
    *,
    tenant_id: str,
    username: str,
    roles: tuple[str, ...],
    purpose: str,
    trace_id: str,
) -> SubjectContext:
    return SubjectContext(
        tenant_id=tenant_id,
        subject_id=username,
        subject_type=SubjectType.HUMAN,
        roles=roles,
        purpose=purpose,
        trace_id=trace_id,
    )


def _path_plan_sha256(request: Request) -> str:
    value = str(request.path_params.get("plan_sha256") or "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("plan_sha256 must be a lowercase SHA-256")
    return value


def _assert_current_plan(
    plan: SemanticExecutionPlan,
    *,
    plan_sha256: str,
    tenant_id: str,
    username: str,
    roles: tuple[str, ...],
    ports: SemanticPlanningPorts,
    registry: CapabilityRegistry,
    require_executable: bool,
) -> None:
    if plan.plan_sha256 != plan_sha256:
        raise SemanticPlanConflictError("semantic plan identity drifted")
    expected_subject = _subject(
        tenant_id=tenant_id,
        username=username,
        roles=roles,
        purpose=plan.request.purpose,
        trace_id=plan.request.request_id,
    )
    if (
        plan.request.tenant_id != tenant_id
        or plan.request.subject_context != expected_subject
        or plan.request.invocation_surface is not PlanningInvocationSurface.API
    ):
        raise SemanticPlanConflictError("semantic plan authentication context drifted")
    if plan.request.planner_binding != ports.planner_binding:
        raise SemanticPlanConflictError("semantic planner binding drifted")
    if any(item.content_sha256 is None for item in plan.request.resource_version_refs):
        raise SemanticPlanConflictError("semantic plan resource pin drifted")
    spec = registry.get(GOVERNED_QUERY_CAPABILITY_ID)
    expected_output = canonical_json_fingerprint(spec.output.json_schema)
    pinned = {
        (
            item.resource_kind,
            item.resource_id,
            item.version,
            item.content_sha256,
        )
        for item in plan.request.resource_version_refs
    }
    for node in plan.nodes:
        node_pins = {
            (
                item.resource_kind,
                item.resource_id,
                item.version,
                item.content_sha256,
            )
            for item in node.query_request.resource_version_refs
        }
        route = plan_query_route(node.query_request)
        if (
            node.capability_id != spec.capability_id
            or node.capability_version != spec.version
            or node.capability_fingerprint != spec.fingerprint
            or node.output_schema_sha256 != expected_output
            or node.evaluator_ref != GOVERNED_QUERY_EVALUATOR_REF
        ):
            raise SemanticPlanConflictError("semantic plan capability binding drifted")
        if (
            node.query_request.purpose != plan.request.purpose
            or node.query_request.purpose_code != plan.request.purpose_code
            or not node_pins
            or not node_pins.issubset(pinned)
            or any(identity[-1] is None for identity in node_pins)
            or route.admission is not AdmissionState.ADMITTED
            or route.selected_channel is not node.channel
        ):
            raise SemanticPlanConflictError("semantic plan node admission drifted")
    if require_executable and (
        plan.status is not PlanningStatus.READY or not plan.execution_allowed
    ):
        raise SemanticPlanAdmissionError("semantic plan is not executable")


def _store_initial_outcome(
    outcome: SemanticPlanningOutcome,
    ports: SemanticPlanningPorts,
) -> None:
    if outcome.plan is not None:
        ports.repository.put(outcome.plan)


def _outcome_response(
    outcome: SemanticPlanningOutcome,
    *,
    created: bool,
) -> JSONResponse:
    if outcome.status is PlanningStatus.NEEDS_CLARIFICATION:
        status_code = 202
    elif created and outcome.status is PlanningStatus.READY:
        status_code = 201
    else:
        status_code = 200
    return JSONResponse(
        outcome.model_dump(mode="json", by_alias=True),
        status_code=status_code,
    )


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, SemanticPlanNotFoundError):
        return JSONResponse(
            {"error": "Semantic plan not found", "code": "semantic_plan_not_found"},
            status_code=404,
        )
    if isinstance(exc, (SemanticPlanConflictError, SemanticPlanAdmissionError)):
        return JSONResponse(
            {
                "error": "Semantic plan is not current or executable",
                "code": "semantic_plan_conflict",
            },
            status_code=409,
        )
    if isinstance(exc, SemanticPlanningPortsUnavailableError):
        return JSONResponse(
            {
                "error": "Semantic planning service is unavailable",
                "code": "semantic_planning_unavailable",
            },
            status_code=503,
        )
    if isinstance(
        exc,
        (SemanticClarificationError, ValidationError, ValueError, TypeError),
    ):
        return JSONResponse(
            {
                "error": "Semantic planning request is invalid",
                "code": "semantic_planning_request_invalid",
            },
            status_code=400,
        )
    return JSONResponse(
        {
            "error": "Semantic planning service is unavailable",
            "code": "semantic_planning_unavailable",
        },
        status_code=503,
    )


async def create_semantic_plan(request: Request) -> JSONResponse:
    tenant_id, username, roles, error = _authenticated_context(request)
    if error is not None:
        return error
    try:
        body = await _parse_request(request, SemanticPlanCreateRequest)
        ports = resolve_semantic_planning_ports(tenant_id)
        subject = _subject(
            tenant_id=tenant_id,
            username=username,
            roles=roles,
            purpose=body.purpose,
            trace_id=body.request_id,
        )
        planning_request = build_semantic_planning_request(
            tenant_id=tenant_id,
            request_id=body.request_id,
            question=body.question,
            purpose=body.purpose,
            purpose_code=body.purpose_code,
            subject_context=subject,
            invocation_surface=PlanningInvocationSurface.API,
            allowed_channels=body.allowed_channels,
            resource_version_refs=body.resource_version_refs,
            planner_binding=ports.planner_binding,
            budget=body.budget,
            deterministic_seed_requests=body.deterministic_seed_requests,
        )
        outcome = AutomaticSemanticPlanner(
            get_capability_registry(),
            ports.proposer,
        ).plan(planning_request)
        _store_initial_outcome(outcome, ports)
        return _outcome_response(outcome, created=True)
    except Exception as exc:
        return _error_response(exc)


async def clarify_semantic_plan(request: Request) -> JSONResponse:
    tenant_id, username, roles, error = _authenticated_context(request)
    if error is not None:
        return error
    try:
        plan_sha256 = _path_plan_sha256(request)
        body = await _parse_request(request, SemanticPlanClarificationRequest)
        ports = resolve_semantic_planning_ports(tenant_id)
        prior = ports.repository.get(tenant_id, plan_sha256)
        _assert_current_plan(
            prior,
            plan_sha256=plan_sha256,
            tenant_id=tenant_id,
            username=username,
            roles=roles,
            ports=ports,
            registry=get_capability_registry(),
            require_executable=False,
        )
        if prior.status is not PlanningStatus.NEEDS_CLARIFICATION:
            raise SemanticPlanConflictError("semantic plan is not awaiting clarification")
        ports.repository.assert_replan_allowed(tenant_id, prior.plan_sha256)
        expected = {item.clarification_id: item for item in prior.clarifications}
        selected = {item.clarification_id: item for item in body.selections}
        if set(selected) != set(expected):
            raise ValueError("clarification selection set is incomplete")
        confirmed_at = datetime.now(UTC)
        resolutions = tuple(
            ClarificationResolution(
                request_sha256=prior.request.request_sha256,
                prior_plan_sha256=prior.plan_sha256,
                clarification_id=clarification_id,
                selected_option_id=selection.selected_option_id,
                confirmed_by=f"human:{username}",
                confirmed_at=confirmed_at,
            )
            for clarification_id, selection in selected.items()
            if selection.selected_option_id in expected[clarification_id].option_ids
        )
        if len(resolutions) != len(expected):
            raise ValueError("clarification option is not admitted")
        outcome = AutomaticSemanticPlanner(
            get_capability_registry(),
            ports.proposer,
        ).replan(prior.request, prior, resolutions)
        if outcome.plan is not None:
            ports.repository.put_successor(prior, outcome.plan)
        return _outcome_response(outcome, created=False)
    except Exception as exc:
        return _error_response(exc)


async def execute_semantic_plan(request: Request) -> JSONResponse:
    tenant_id, username, roles, error = _authenticated_context(request)
    if error is not None:
        return error
    try:
        plan_sha256 = _path_plan_sha256(request)
        await _parse_request(request, SemanticPlanExecutionRequest)
        ports = resolve_semantic_planning_ports(tenant_id)
        plan = ports.repository.get(tenant_id, plan_sha256)
        _assert_current_plan(
            plan,
            plan_sha256=plan_sha256,
            tenant_id=tenant_id,
            username=username,
            roles=roles,
            ports=ports,
            registry=get_capability_registry(),
            require_executable=True,
        )
        result = SemanticPlanExecutor(ports.executor).execute(plan)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))
    except Exception as exc:
        return _error_response(exc)


def get_semantic_planning_routes() -> list[Route]:
    return [
        Route(
            "/api/semantic-plans",
            endpoint=create_semantic_plan,
            methods=["POST"],
        ),
        Route(
            "/api/semantic-plans/{plan_sha256}/clarifications",
            endpoint=clarify_semantic_plan,
            methods=["POST"],
        ),
        Route(
            "/api/semantic-plans/{plan_sha256}/execute",
            endpoint=execute_semantic_plan,
            methods=["POST"],
        ),
    ]


__all__ = [
    "DevelopmentSemanticPlanningPortResolver",
    "InMemorySemanticPlanRepository",
    "SemanticPlanningPorts",
    "configure_default_semantic_planning_port_resolver",
    "configure_semantic_planning_port_resolver",
    "get_semantic_planning_routes",
    "resolve_semantic_planning_ports",
    "semantic_planning_port_resolver_configured",
]
