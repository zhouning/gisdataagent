"""Metric projection lifecycle and deterministic query-planning routes."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..metric_authority import MetricAuthorityError, MetricDefinitionAuthority
from ..metric_projection_authority import (
    ActiveMetricProjection,
    MetricProjectionActivation,
    MetricProjectionAuthority,
    MetricProjectionAuthorityError,
    MetricProjectionConfigurationError,
    MetricProjectionConflictError,
    MetricProjectionDocument,
    MetricProjectionDraft,
    MetricProjectionEvent,
    MetricProjectionForbiddenError,
    MetricProjectionNotFoundError,
    MetricProjectionValidationError,
    MetricProjectionVersion,
    MetricProjectionVersionPage,
)
from ..metric_query import (
    MetricQueryPlan,
    MetricQueryPlanner,
    MetricQueryPlanningError,
    MetricQueryRequest,
    MetricQuerySecurityContext,
)
from ..metric_query_execution import (
    ClientRequestId,
    MetricQueryCompletionSpec,
    MetricQueryExecutionAuthority,
    MetricQueryExecutionConfigurationError,
    MetricQueryExecutionConflictError,
    MetricQueryExecutionError,
    MetricQueryExecutionForbiddenError,
    MetricQueryExecutionNotFoundError,
    MetricQueryExecutionValidationError,
    MetricQueryRunRecord,
    MetricQueryStartSpec,
)
from ..metric_query_result_access import (
    DEFAULT_RESULT_ACCESS_TTL_SECONDS,
    MAX_RESULT_ACCESS_TTL_SECONDS,
    MIN_RESULT_ACCESS_TTL_SECONDS,
    MetricQueryResultAccessError,
    MetricQueryResultAccessForbidden,
    MetricQueryResultAccessNotFound,
    MetricQueryResultAccessService,
    MetricQueryResultAccessUnavailable,
    MetricQueryResultIntegrityError,
    MetricQueryResultNotReady,
)
from ..platform_contracts import SubjectType, TenantId, build_resource_urn
from .helpers import _get_user_from_request
from .metric_routes import _metric_error, _metric_ref, _metric_route
from .platform_gateway_routes import (
    GatewayPrincipal,
    _error,
    _identifier,
    _metadata,
    _parse,
    _principal,
    _success,
    _utc_now,
    _validation_details,
)

_TENANT_ADAPTER = TypeAdapter(TenantId)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricProjectionStageRequest(_StrictRequest):
    version: int = Field(ge=1, le=1_000_000)
    projection: MetricProjectionDocument
    creation_reason: str = Field(min_length=1, max_length=512)


class MetricProjectionActivateRequest(_StrictRequest):
    expected_activation_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=512)


class MetricProjectionVersionListResponse(_StrictRequest):
    items: tuple[MetricProjectionVersion, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class ActiveMetricProjectionListResponse(_StrictRequest):
    items: tuple[ActiveMetricProjection, ...]
    count: int = Field(ge=0)


class MetricProjectionEventListResponse(_StrictRequest):
    items: tuple[MetricProjectionEvent, ...]
    count: int = Field(ge=0)


class MetricQueryRunAdmissionRequest(_StrictRequest):
    client_request_id: ClientRequestId
    query: MetricQueryRequest


class MetricQueryRunStartRequest(MetricQueryStartSpec):
    expected_state_version: int = Field(default=0, ge=0)


class MetricQueryRunCompletionRequest(MetricQueryCompletionSpec):
    expected_state_version: int = Field(default=2, ge=0)


class MetricQueryResultAccessRequest(_StrictRequest):
    expires_in_seconds: int = Field(
        default=DEFAULT_RESULT_ACCESS_TTL_SECONDS,
        ge=MIN_RESULT_ACCESS_TTL_SECONDS,
        le=MAX_RESULT_ACCESS_TTL_SECONDS,
    )


def _projection_authority() -> MetricProjectionAuthority:
    return MetricProjectionAuthority()


def _query_planner() -> MetricQueryPlanner:
    return MetricQueryPlanner()


def _query_execution_authority() -> MetricQueryExecutionAuthority:
    return MetricQueryExecutionAuthority()


def _query_result_access_service() -> MetricQueryResultAccessService:
    return MetricQueryResultAccessService()


def _projection_ref(
    request: Request, principal: GatewayPrincipal
) -> str | JSONResponse:
    projection_id = str(request.path_params.get("metric_projection_id") or "")
    try:
        return build_resource_urn(
            principal.tenant_id, "metric_projection", projection_id
        )
    except ValueError:
        return _error(
            request,
            400,
            "invalid_metric_projection_id",
            "metric_projection_id must be a canonical lowercase resource identifier",
        )


def _projection_version_refs(
    request: Request, principal: GatewayPrincipal
) -> tuple[str, str] | JSONResponse:
    projection_ref = _projection_ref(request, principal)
    if isinstance(projection_ref, JSONResponse):
        return projection_ref
    raw_version = str(request.path_params.get("version") or "")
    if (
        re.fullmatch(r"[1-9][0-9]{0,6}", raw_version) is None
        or int(raw_version) > 1_000_000
    ):
        return _error(
            request,
            400,
            "invalid_metric_projection_version",
            "metric projection version must be a positive integer",
        )
    return projection_ref, f"{projection_ref}.v{int(raw_version)}"


def _projection_error(
    request: Request, exc: MetricProjectionAuthorityError
) -> JSONResponse:
    if isinstance(exc, MetricProjectionNotFoundError):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, MetricProjectionConflictError):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, MetricProjectionForbiddenError):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, MetricProjectionValidationError):
        return _error(request, 422, exc.code, str(exc))
    if isinstance(exc, MetricProjectionConfigurationError):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


def _query_principal(request: Request) -> GatewayPrincipal | JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return _error(request, 401, "unauthorized", "Authentication is required")
    metadata = _metadata(user)
    role = str(metadata.get("role") or "").strip()
    if not role or len(role) > 128:
        return _error(request, 403, "role_context_required", "A valid role is required")
    try:
        tenant_id = _TENANT_ADAPTER.validate_python(metadata.get("tenant_id"))
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
    return GatewayPrincipal(tenant_id, subject_id, subject_type, role)


def _query_security(
    request: Request, principal: GatewayPrincipal
) -> MetricQuerySecurityContext:
    return MetricQuerySecurityContext(
        tenant_id=principal.tenant_id,
        subject_ref=principal.actor_ref,
        roles=(principal.role,),
        purpose=request.headers.get("x-gda-query-purpose", "metric_query"),
    )


def _run_id(request: Request) -> UUID | JSONResponse:
    try:
        return UUID(str(request.path_params["run_id"]))
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")


def _query_execution_error(
    request: Request, exc: MetricQueryExecutionError
) -> JSONResponse:
    if isinstance(exc, MetricQueryExecutionNotFoundError):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, MetricQueryExecutionConflictError):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, MetricQueryExecutionForbiddenError):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, MetricQueryExecutionValidationError):
        return _error(request, 422, exc.code, str(exc))
    if isinstance(exc, MetricQueryExecutionConfigurationError):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


def _query_result_access_error(
    request: Request, exc: MetricQueryResultAccessError
) -> JSONResponse:
    if isinstance(exc, MetricQueryResultAccessNotFound):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, MetricQueryResultAccessForbidden):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, (MetricQueryResultNotReady, MetricQueryResultIntegrityError)):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, MetricQueryResultAccessUnavailable):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


async def stage_metric_projection_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricProjectionStageRequest)
    if isinstance(submission, JSONResponse):
        return submission
    projection_ref = _projection_ref(request, principal)
    if isinstance(projection_ref, JSONResponse):
        return projection_ref
    try:
        draft = MetricProjectionDraft(
            tenant_id=principal.tenant_id,
            projection_ref=projection_ref,
            projection_version_ref=f"{projection_ref}.v{submission.version}",
            version=submission.version,
            projection=submission.projection,
            created_by=principal.actor_ref,
            creation_reason=submission.creation_reason,
            created_at=_utc_now(),
        )
        stored = await asyncio.to_thread(_projection_authority().stage, draft)
        return _success(request, stored)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric projection does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def list_metric_projection_versions(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    projection_ref = _projection_ref(request, principal)
    if isinstance(projection_ref, JSONResponse):
        return projection_ref
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 0, -1
    try:
        page: MetricProjectionVersionPage = await asyncio.to_thread(
            _projection_authority().list_versions,
            principal.tenant_id,
            projection_ref,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            MetricProjectionVersionListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            400,
            "invalid_metric_projection_query",
            str(exc),
            details,
        )
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def activate_metric_projection_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "metric_projection_activation_admin_required",
            "Metric projection activation requires an administrator",
        )
    submission = await _parse(request, MetricProjectionActivateRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _projection_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    _, version_ref = refs
    try:
        authority = _projection_authority()
        version = await asyncio.to_thread(
            authority.get, principal.tenant_id, version_ref
        )
        activation: MetricProjectionActivation = await asyncio.to_thread(
            authority.activate,
            tenant_id=principal.tenant_id,
            projection_version_ref=version.projection_version_ref,
            projection_fingerprint=version.projection_fingerprint,
            expected_activation_version=submission.expected_activation_version,
            actor_subject=principal.actor_ref,
            reason=submission.reason,
        )
        return _success(request, activation)
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def list_active_metric_projections(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    try:
        metric, _ = await asyncio.to_thread(
            MetricDefinitionAuthority().active, principal.tenant_id, metric_ref
        )
        projections = await asyncio.to_thread(
            _projection_authority().active_for_metric,
            principal.tenant_id,
            metric.metric_version_ref,
            metric.definition_fingerprint,
        )
        return _success(
            request,
            ActiveMetricProjectionListResponse(
                items=projections, count=len(projections)
            ),
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def list_metric_projection_events(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    projection_ref = _projection_ref(request, principal)
    if isinstance(projection_ref, JSONResponse):
        return projection_ref
    try:
        events = await asyncio.to_thread(
            _projection_authority().events, principal.tenant_id, projection_ref
        )
        return _success(
            request,
            MetricProjectionEventListResponse(items=events, count=len(events)),
        )
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def create_metric_query_plan(request: Request) -> JSONResponse:
    principal = _query_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricQueryRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        security = _query_security(request, principal)
        plan: MetricQueryPlan = await asyncio.to_thread(
            _query_planner().plan, submission, security
        )
        return _success(request, plan)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric query does not satisfy the governed planning contract",
            _validation_details(exc),
        )
    except MetricQueryPlanningError as exc:
        details: list[dict[str, str]] = [
            {"rejection": reason} for reason in exc.rejections[:20]
        ]
        return _error(request, 409, exc.code, str(exc), details)
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)


async def create_metric_query_run(request: Request) -> JSONResponse:
    principal = _query_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricQueryRunAdmissionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        security = _query_security(request, principal)
        plan = await asyncio.to_thread(
            _query_planner().plan, submission.query, security
        )
        record = await asyncio.to_thread(
            _query_execution_authority().admit,
            plan,
            security,
            submission.client_request_id,
        )
        return _success(request, record, status_code=202)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric query run does not satisfy the governed execution contract",
            _validation_details(exc),
        )
    except MetricQueryPlanningError as exc:
        details: list[dict[str, str]] = [
            {"rejection": reason} for reason in exc.rejections[:20]
        ]
        return _error(request, 409, exc.code, str(exc), details)
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)
    except MetricProjectionAuthorityError as exc:
        return _projection_error(request, exc)
    except MetricQueryExecutionError as exc:
        return _query_execution_error(request, exc)


async def get_metric_query_run(request: Request) -> JSONResponse:
    principal = _query_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    try:
        record: MetricQueryRunRecord = await asyncio.to_thread(
            _query_execution_authority().get, principal.tenant_id, run_id
        )
        if (
            record.admission.admitted_by != principal.actor_ref
            and principal.role not in {"admin", "platform_operator"}
        ):
            return _error(
                request,
                403,
                "metric_query_run_owner_required",
                "Metric query run access requires its submitter or a platform operator",
            )
        return _success(request, record)
    except MetricQueryExecutionError as exc:
        return _query_execution_error(request, exc)


async def create_metric_query_result_access(request: Request) -> JSONResponse:
    principal = _query_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, MetricQueryResultAccessRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        grant = await asyncio.to_thread(
            _query_result_access_service().issue,
            tenant_id=principal.tenant_id,
            run_id=run_id,
            actor_subject=principal.actor_ref,
            role=principal.role,
            expires_in_seconds=submission.expires_in_seconds,
        )
        response = _success(request, grant, status_code=201)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
    except MetricQueryResultAccessError as exc:
        return _query_result_access_error(request, exc)


async def start_metric_query_run(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Metric query provider receipt requires workload identity",
        )
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, MetricQueryRunStartRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        spec = MetricQueryStartSpec.model_validate(
            submission.model_dump(exclude={"expected_state_version"})
        )
        record = await asyncio.to_thread(
            _query_execution_authority().start,
            principal.tenant_id,
            run_id,
            spec,
            actor_subject=principal.actor_ref,
            expected_state_version=submission.expected_state_version,
        )
        return _success(request, record)
    except (ValidationError, MetricQueryExecutionValidationError) as exc:
        if isinstance(exc, MetricQueryExecutionValidationError):
            return _query_execution_error(request, exc)
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric query start receipt does not satisfy the execution contract",
            _validation_details(exc),
        )
    except MetricQueryExecutionError as exc:
        return _query_execution_error(request, exc)


async def complete_metric_query_run(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Metric query provider receipt requires workload identity",
        )
    run_id = _run_id(request)
    if isinstance(run_id, JSONResponse):
        return run_id
    submission = await _parse(request, MetricQueryRunCompletionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        spec = MetricQueryCompletionSpec.model_validate(
            submission.model_dump(exclude={"expected_state_version"})
        )
        record = await asyncio.to_thread(
            _query_execution_authority().complete,
            principal.tenant_id,
            run_id,
            spec,
            actor_subject=principal.actor_ref,
            expected_state_version=submission.expected_state_version,
        )
        return _success(request, record)
    except (ValidationError, MetricQueryExecutionValidationError) as exc:
        if isinstance(exc, MetricQueryExecutionValidationError):
            return _query_execution_error(request, exc)
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric query completion receipt does not satisfy the execution contract",
            _validation_details(exc),
        )
    except MetricQueryExecutionError as exc:
        return _query_execution_error(request, exc)


def get_metric_query_routes() -> list[APIRoute]:
    base = "/api/platform/v1"
    projections = f"{base}/metric-projections/{{metric_projection_id}}"
    definitions = f"{base}/metric-definitions/{{metric_definition_id}}"
    routes: list[tuple[str, Any, str, str]] = [
        (
            f"{projections}/versions",
            stage_metric_projection_version,
            "POST",
            "platform_stage_metric_projection_version",
        ),
        (
            f"{projections}/versions",
            list_metric_projection_versions,
            "GET",
            "platform_list_metric_projection_versions",
        ),
        (
            f"{projections}/versions/{{version}}/activation",
            activate_metric_projection_version,
            "POST",
            "platform_activate_metric_projection_version",
        ),
        (
            f"{projections}/events",
            list_metric_projection_events,
            "GET",
            "platform_list_metric_projection_events",
        ),
        (
            f"{definitions}/active-projections",
            list_active_metric_projections,
            "GET",
            "platform_list_active_metric_projections",
        ),
        (
            f"{base}/metric-query-plans",
            create_metric_query_plan,
            "POST",
            "platform_create_metric_query_plan",
        ),
        (
            f"{base}/metric-query-runs",
            create_metric_query_run,
            "POST",
            "platform_create_metric_query_run",
        ),
        (
            f"{base}/metric-query-runs/{{run_id}}",
            get_metric_query_run,
            "GET",
            "platform_get_metric_query_run",
        ),
        (
            f"{base}/metric-query-runs/{{run_id}}/result-access",
            create_metric_query_result_access,
            "POST",
            "platform_create_metric_query_result_access",
        ),
        (
            f"{base}/metric-query-runs/{{run_id}}/start",
            start_metric_query_run,
            "POST",
            "platform_start_metric_query_run",
        ),
        (
            f"{base}/metric-query-runs/{{run_id}}/complete",
            complete_metric_query_run,
            "POST",
            "platform_complete_metric_query_run",
        ),
    ]
    return [
        _metric_route(path, endpoint, method=method, operation_id=operation_id)
        for path, endpoint, method, operation_id in routes
    ]
