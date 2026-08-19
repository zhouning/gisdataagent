"""HTTP control plane for durable governed GIS analysis Runs."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..capability_registry import GIS_ANALYSIS_EXECUTE
from ..db_engine import get_engine
from ..gis_algorithm_registry import DEFAULT_GIS_ALGORITHM_REGISTRY
from ..gis_analysis_execution import (
    GIS_POSTGIS_WORKLOAD,
    GISAnalysisCompletionSpec,
    GISAnalysisExecutionAuthority,
    GISAnalysisExecutionConfigurationError,
    GISAnalysisExecutionConflictError,
    GISAnalysisExecutionError,
    GISAnalysisExecutionForbiddenError,
    GISAnalysisExecutionNotFoundError,
    GISAnalysisExecutionValidationError,
    GISAnalysisPlanner,
    GISAnalysisProviderStartSpec,
    GISAnalysisRunAdmissionRequest,
    GISAnalysisRunCancelRequest,
    GISAnalysisRunRecord,
)
from ..gis_analysis_result_access import (
    GISAnalysisResultAccessError,
    GISAnalysisResultAccessForbidden,
    GISAnalysisResultAccessNotFound,
    GISAnalysisResultAccessService,
    GISAnalysisResultAccessUnavailable,
    GISAnalysisResultIntegrityError,
    GISAnalysisResultNotReady,
)
from ..gis_workflow import (
    GISWorkflowError,
    GISWorkflowExecuteRequest,
    GISWorkflowExecutionError,
    GISWorkflowPlanner,
    GISWorkflowPreviewRequest,
    GISWorkflowUnavailableError,
    GISWorkflowValidationError,
    PostGISWorkflowProvider,
)
from ..gis_workflow_proposal import GISWorkflowProposalPlanner
from ..governed_query_result_access_security import (
    GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
)
from ..governed_query_security import (
    GovernedQuerySecurityError,
    resolve_governed_query_security_ports,
)
from ..metric_query_result_access import (
    DEFAULT_RESULT_ACCESS_TTL_SECONDS,
    MAX_RESULT_ACCESS_TTL_SECONDS,
    MIN_RESULT_ACCESS_TTL_SECONDS,
)
from ..platform_contracts import ShortName, SubjectContext, SubjectType, TenantId
from .helpers import _get_user_from_request
from .metric_routes import _metric_route
from .platform_gateway_routes import (
    GatewayPrincipal,
    _capability_contract_guard,
    _error,
    _identifier,
    _metadata,
    _parse,
    _success,
    _validation_details,
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_TENANT_ADAPTER = TypeAdapter(TenantId)
_GIS_ROLES = frozenset({"viewer", "analyst", "admin", "platform_operator"})


class GISAnalysisRunStartRequest(GISAnalysisProviderStartSpec):
    expected_state_version: int = Field(default=0, ge=0)


class GISAnalysisRunCompletionRequest(GISAnalysisCompletionSpec):
    expected_state_version: int = Field(default=2, ge=0)


class GISAnalysisResultAccessRequest(_StrictRequest):
    purpose_code: ShortName = GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE
    expires_in_seconds: int = Field(
        default=DEFAULT_RESULT_ACCESS_TTL_SECONDS,
        ge=MIN_RESULT_ACCESS_TTL_SECONDS,
        le=MAX_RESULT_ACCESS_TTL_SECONDS,
    )


class GISAnalysisReconciliationResolutionRequest(_StrictRequest):
    incident_id: UUID
    expected_run_state_version: int = Field(ge=0)
    expected_incident_state_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=512)


def _authority() -> GISAnalysisExecutionAuthority:
    return GISAnalysisExecutionAuthority()


def _planner() -> GISAnalysisPlanner:
    return GISAnalysisPlanner()


def _result_access() -> GISAnalysisResultAccessService:
    return GISAnalysisResultAccessService()


def _workflow_planner() -> GISWorkflowPlanner:
    return GISWorkflowPlanner()


def _workflow_proposal_planner() -> GISWorkflowProposalPlanner:
    return GISWorkflowProposalPlanner()


def _run_id(request: Request) -> UUID | JSONResponse:
    try:
        return UUID(str(request.path_params["run_id"]))
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")


def _gis_principal(request: Request) -> GatewayPrincipal | JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return _error(request, 401, "unauthorized", "Authentication is required")
    metadata = _metadata(user)
    role = str(metadata.get("role") or "").strip()
    if role not in _GIS_ROLES:
        return _error(request, 403, "gis_role_required", "A GIS query role is required")
    try:
        tenant = _TENANT_ADAPTER.validate_python(metadata.get("tenant_id"))
        subject_type = SubjectType(metadata.get("subject_type", "human"))
    except (ValidationError, ValueError):
        return _error(
            request,
            403,
            "tenant_context_required",
            "A valid tenant identity is required",
        )
    subject_id = _identifier(user)
    if not subject_id:
        return _error(request, 401, "invalid_identity", "Identity is incomplete")
    return GatewayPrincipal(tenant, subject_id, subject_type, role)


def _subject(request: Request, principal: GatewayPrincipal) -> SubjectContext:
    return SubjectContext(
        tenant_id=principal.tenant_id,
        subject_id=principal.subject_id,
        subject_type=principal.subject_type,
        roles=(principal.role,),
        purpose=request.headers.get("x-gda-query-purpose", "gis_analysis"),
        trace_id=None,
    )


def _execution_error(
    request: Request,
    exc: GISAnalysisExecutionError,
) -> JSONResponse:
    if isinstance(exc, GISAnalysisExecutionNotFoundError):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, GISAnalysisExecutionConflictError):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, GISAnalysisExecutionForbiddenError):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, GISAnalysisExecutionValidationError):
        return _error(request, 422, exc.code, str(exc))
    if isinstance(exc, GISAnalysisExecutionConfigurationError):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


def _access_error(
    request: Request,
    exc: GISAnalysisResultAccessError,
) -> JSONResponse:
    if isinstance(exc, GISAnalysisResultAccessNotFound):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, GISAnalysisResultAccessForbidden):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, (GISAnalysisResultNotReady, GISAnalysisResultIntegrityError)):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, GISAnalysisResultAccessUnavailable):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


def _owner_required(
    request: Request,
    principal: GatewayPrincipal,
    record: GISAnalysisRunRecord,
) -> JSONResponse | None:
    if (
        record.admission.admitted_by != principal.actor_ref
        and principal.role not in {"admin", "platform_operator"}
    ):
        return _error(
            request,
            403,
            "gis_analysis_run_owner_required",
            "GIS analysis Run access requires its submitter or a platform operator",
        )
    return None


async def create_gis_analysis_run(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if mismatch := _capability_contract_guard(request, GIS_ANALYSIS_EXECUTE):
        return mismatch
    submission = await _parse(request, GISAnalysisRunAdmissionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        subject = _subject(request, principal)
        plan = await asyncio.to_thread(
            _planner().plan,
            submission.analysis,
            subject,
            submission.budget,
        )
        record = await asyncio.to_thread(
            _authority().admit,
            plan,
            subject,
            submission.client_request_id,
        )
        return _success(request, record, status_code=202)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "GIS analysis does not satisfy the governed execution contract",
            _validation_details(exc),
        )
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def list_gis_analysis_algorithms(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    return _success(request, DEFAULT_GIS_ALGORITHM_REGISTRY.catalog())


def _workflow_error(request: Request, exc: GISWorkflowError) -> JSONResponse:
    if isinstance(exc, GISWorkflowValidationError):
        return _error(request, 422, exc.code, str(exc))
    if isinstance(exc, GISWorkflowExecutionError):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, GISWorkflowUnavailableError):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


class GISWorkflowProposalRequest(_StrictRequest):
    question: str = Field(min_length=8, max_length=2_000)


async def propose_gis_workflow(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, GISWorkflowProposalRequest)
    if isinstance(submission, JSONResponse):
        return submission
    proposal = await asyncio.to_thread(
        _workflow_proposal_planner().propose,
        submission.question,
    )
    response = _success(request, proposal)
    response.headers["Cache-Control"] = "no-store"
    return response


async def preview_gis_workflow(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, GISWorkflowPreviewRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        preview = await asyncio.to_thread(
            _workflow_planner().preview,
            submission,
            _subject(request, principal),
        )
        return _success(request, preview)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "GIS workflow preview does not satisfy its typed contract",
            _validation_details(exc),
        )
    except GISWorkflowError as exc:
        return _workflow_error(request, exc)


async def execute_gis_workflow(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role not in {"analyst", "admin", "platform_operator"}:
        return _error(
            request,
            403,
            "gis_workflow_execution_role_required",
            "GIS workflow execution requires an analyst or platform operator",
        )
    submission = await _parse(request, GISWorkflowExecuteRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        preview_request = GISWorkflowPreviewRequest.model_validate(
            submission.model_dump(
                exclude={"confirmed_plan_fingerprint", "confirm_assumptions"}
            )
        )
        preview = await asyncio.to_thread(
            _workflow_planner().preview,
            preview_request,
            _subject(request, principal),
        )
        if (
            not preview.executable
            or preview.plan is None
            or preview.plan_fingerprint != submission.confirmed_plan_fingerprint
        ):
            return _error(
                request,
                409,
                "gis_workflow_plan_changed",
                "The workflow or its governed source versions changed after preview",
                [
                    {
                        "confirmed_plan_fingerprint": submission.confirmed_plan_fingerprint,
                        "current_plan_fingerprint": preview.plan_fingerprint,
                        "blockers": [
                            blocker.model_dump(mode="json")
                            for blocker in preview.blockers
                        ],
                    }
                ],
            )
        engine = get_engine()
        result = await asyncio.to_thread(
            PostGISWorkflowProvider(engine).execute,
            preview.plan,
        )
        return _success(request, result)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "GIS workflow execution does not satisfy its typed contract",
            _validation_details(exc),
        )
    except GISWorkflowError as exc:
        return _workflow_error(request, exc)


async def get_gis_analysis_run(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    try:
        record = await asyncio.to_thread(
            _authority().get,
            principal.tenant_id,
            run_id,
        )
        denied = _owner_required(request, principal, record)
        return denied or _success(request, record)
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def start_gis_analysis_run(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.actor_ref != GIS_POSTGIS_WORKLOAD:
        return _error(
            request,
            403,
            "gis_provider_identity_required",
            "GIS provider start receipt requires the governed PostGIS workload",
        )
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, GISAnalysisRunStartRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        spec = GISAnalysisProviderStartSpec.model_validate(
            submission.model_dump(exclude={"expected_state_version"})
        )
        record = await asyncio.to_thread(
            _authority().start,
            principal.tenant_id,
            run_id,
            spec,
            actor_subject=principal.actor_ref,
            expected_state_version=submission.expected_state_version,
        )
        return _success(request, record)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "GIS start receipt does not satisfy the execution contract",
            _validation_details(exc),
        )
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def complete_gis_analysis_run(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.actor_ref != GIS_POSTGIS_WORKLOAD:
        return _error(
            request,
            403,
            "gis_provider_identity_required",
            "GIS provider completion receipt requires the governed PostGIS workload",
        )
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, GISAnalysisRunCompletionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        spec = GISAnalysisCompletionSpec.model_validate(
            submission.model_dump(exclude={"expected_state_version"})
        )
        record = await asyncio.to_thread(
            _authority().complete,
            principal.tenant_id,
            run_id,
            spec,
            actor_subject=principal.actor_ref,
            expected_state_version=submission.expected_state_version,
        )
        return _success(request, record)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "GIS completion receipt does not satisfy the execution contract",
            _validation_details(exc),
        )
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def cancel_gis_analysis_run(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, GISAnalysisRunCancelRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        record = await asyncio.to_thread(
            _authority().cancel,
            principal.tenant_id,
            run_id,
            cancel_request_id=submission.cancel_request_id,
            actor_subject=principal.actor_ref,
            roles=(principal.role,),
            reason=submission.reason,
            expected_state_version=submission.expected_state_version,
        )
        return _success(request, record)
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def resolve_gis_analysis_reconciliation(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "GIS reconciliation resolution requires a human identity",
        )
    if principal.role not in {"admin", "platform_operator"}:
        return _error(
            request,
            403,
            "platform_operator_required",
            "GIS reconciliation resolution requires a platform operator",
        )
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(
        request, GISAnalysisReconciliationResolutionRequest
    )
    if isinstance(submission, JSONResponse):
        return submission
    try:
        record = await asyncio.to_thread(
            _authority().resolve_reconciliation,
            principal.tenant_id,
            run_id,
            incident_id=submission.incident_id,
            expected_run_state_version=submission.expected_run_state_version,
            expected_incident_state_version=(
                submission.expected_incident_state_version
            ),
            actor_subject=principal.actor_ref,
            roles=(principal.role,),
            reason=submission.reason,
        )
        return _success(request, record)
    except GISAnalysisExecutionError as exc:
        return _execution_error(request, exc)


async def create_gis_analysis_result_access(request: Request) -> JSONResponse:
    principal = _gis_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, GISAnalysisResultAccessRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        security_ports = resolve_governed_query_security_ports(principal.tenant_id)
        grant = await asyncio.to_thread(
            _result_access().issue,
            tenant_id=principal.tenant_id,
            run_id=run_id,
            actor_subject=principal.actor_ref,
            role=principal.role,
            expires_in_seconds=submission.expires_in_seconds,
            purpose_code=submission.purpose_code,
            security_reader=None if security_ports is None else security_ports[0],
        )
        response = _success(request, grant, status_code=201)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
    except GISAnalysisResultAccessError as exc:
        return _access_error(request, exc)
    except GovernedQuerySecurityError as exc:
        return _error(
            request,
            503,
            "gis_result_security_unavailable",
            str(exc),
        )


def get_gis_analysis_routes() -> list[APIRoute]:
    base = "/api/platform/v1/gis-analysis-runs"
    routes: list[tuple[str, Any, str, str]] = [
        (
            "/api/platform/v1/gis-workflows/proposals",
            propose_gis_workflow,
            "POST",
            "platform_propose_gis_workflow",
        ),
        (
            "/api/platform/v1/gis-workflows/preview",
            preview_gis_workflow,
            "POST",
            "platform_preview_gis_workflow",
        ),
        (
            "/api/platform/v1/gis-workflows/execute",
            execute_gis_workflow,
            "POST",
            "platform_execute_gis_workflow",
        ),
        (
            "/api/platform/v1/gis-analysis-algorithms",
            list_gis_analysis_algorithms,
            "GET",
            "platform_list_gis_analysis_algorithms",
        ),
        (base, create_gis_analysis_run, "POST", "platform_create_gis_analysis_run"),
        (
            f"{base}/{{run_id}}",
            get_gis_analysis_run,
            "GET",
            "platform_get_gis_analysis_run",
        ),
        (
            f"{base}/{{run_id}}/start",
            start_gis_analysis_run,
            "POST",
            "platform_start_gis_analysis_run",
        ),
        (
            f"{base}/{{run_id}}/complete",
            complete_gis_analysis_run,
            "POST",
            "platform_complete_gis_analysis_run",
        ),
        (
            f"{base}/{{run_id}}/cancel",
            cancel_gis_analysis_run,
            "POST",
            "platform_cancel_gis_analysis_run",
        ),
        (
            f"{base}/{{run_id}}/reconciliation-resolution",
            resolve_gis_analysis_reconciliation,
            "POST",
            "platform_resolve_gis_analysis_reconciliation",
        ),
        (
            f"{base}/{{run_id}}/result-access",
            create_gis_analysis_result_access,
            "POST",
            "platform_create_gis_analysis_result_access",
        ),
    ]
    return [
        _metric_route(path, endpoint, method=method, operation_id=operation_id)
        for path, endpoint, method, operation_id in routes
    ]


__all__ = [
    "GISAnalysisReconciliationResolutionRequest",
    "GISAnalysisResultAccessRequest",
    "GISAnalysisRunCompletionRequest",
    "GISAnalysisRunStartRequest",
    "cancel_gis_analysis_run",
    "complete_gis_analysis_run",
    "create_gis_analysis_result_access",
    "create_gis_analysis_run",
    "get_gis_analysis_routes",
    "get_gis_analysis_run",
    "list_gis_analysis_algorithms",
    "execute_gis_workflow",
    "preview_gis_workflow",
    "propose_gis_workflow",
    "resolve_gis_analysis_reconciliation",
    "start_gis_analysis_run",
]
