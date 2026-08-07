"""Governed metric-definition lifecycle routes."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import timedelta
from typing import Any

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..approval_case_authority import ApprovalCaseAuthorityError
from ..metric_authority import (
    METRIC_ACTIVATION_ACTION,
    MetricAuthorityError,
    MetricConfigurationError,
    MetricConflictError,
    MetricDefinitionActivation,
    MetricDefinitionAuthority,
    MetricDefinitionDocument,
    MetricDefinitionDraft,
    MetricDefinitionEvent,
    MetricDefinitionVersion,
    MetricDefinitionVersionPage,
    MetricForbiddenError,
    MetricNotFoundError,
    MetricResolution,
    MetricValidationError,
)
from ..platform_contracts import (
    ApprovalCase,
    build_resource_urn,
)
from .platform_gateway_routes import (
    GatewayPrincipal,
    _approval_case_authority,
    _approval_case_error,
    _error,
    _parse,
    _principal,
    _success,
    _utc_now,
    _validation_details,
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricDefinitionStageRequest(_StrictRequest):
    version: int = Field(ge=1, le=1_000_000)
    definition: MetricDefinitionDocument
    creation_reason: str = Field(min_length=1, max_length=512)


class MetricActivationApprovalRequest(_StrictRequest):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    request_reason: str = Field(min_length=1, max_length=512)
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class MetricDefinitionActivateRequest(_StrictRequest):
    approval_case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    expected_activation_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=512)


class MetricResolutionRequest(_StrictRequest):
    name: str = Field(min_length=1, max_length=256)
    domain: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,127}$"
    )


class MetricDefinitionVersionListResponse(_StrictRequest):
    items: tuple[MetricDefinitionVersion, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class MetricActiveDefinitionResponse(_StrictRequest):
    definition: MetricDefinitionVersion
    activation: MetricDefinitionActivation


class MetricDefinitionEventListResponse(_StrictRequest):
    items: tuple[MetricDefinitionEvent, ...]
    count: int = Field(ge=0)


def _metric_authority() -> MetricDefinitionAuthority:
    return MetricDefinitionAuthority()


def _metric_ref(
    request: Request, principal: GatewayPrincipal
) -> str | JSONResponse:
    metric_id = str(request.path_params.get("metric_definition_id") or "")
    try:
        return build_resource_urn(
            principal.tenant_id, "metric_definition", metric_id
        )
    except ValueError:
        return _error(
            request,
            400,
            "invalid_metric_definition_id",
            "metric_definition_id must be a canonical lowercase resource identifier",
        )


def _metric_version_refs(
    request: Request, principal: GatewayPrincipal
) -> tuple[str, str] | JSONResponse:
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    raw_version = str(request.path_params.get("version") or "")
    if (
        re.fullmatch(r"[1-9][0-9]{0,6}", raw_version) is None
        or int(raw_version) > 1_000_000
    ):
        return _error(
            request,
            400,
            "invalid_metric_definition_version",
            "metric definition version must be a positive integer",
        )
    return metric_ref, f"{metric_ref}.v{int(raw_version)}"


def _metric_error(request: Request, exc: MetricAuthorityError) -> JSONResponse:
    if isinstance(exc, MetricNotFoundError):
        return _error(request, 404, exc.code, str(exc))
    if isinstance(exc, MetricConflictError):
        return _error(request, 409, exc.code, str(exc))
    if isinstance(exc, MetricForbiddenError):
        return _error(request, 403, exc.code, str(exc))
    if isinstance(exc, MetricValidationError):
        return _error(request, 422, exc.code, str(exc))
    if isinstance(exc, MetricConfigurationError):
        return _error(request, 503, exc.code, str(exc))
    return _error(request, 503, exc.code, str(exc))


async def stage_metric_definition_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricDefinitionStageRequest)
    if isinstance(submission, JSONResponse):
        return submission
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    try:
        draft = MetricDefinitionDraft(
            tenant_id=principal.tenant_id,
            metric_ref=metric_ref,
            metric_version_ref=f"{metric_ref}.v{submission.version}",
            version=submission.version,
            definition=submission.definition,
            created_by=principal.actor_ref,
            creation_reason=submission.creation_reason,
            created_at=_utc_now(),
        )
        definition = await asyncio.to_thread(_metric_authority().stage, draft)
        return _success(request, definition)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric definition does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


async def list_metric_definition_versions(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 0, -1
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_metric_version_query",
            "Metric version query is outside the supported range",
        )
    try:
        page: MetricDefinitionVersionPage = await asyncio.to_thread(
            _metric_authority().list_versions,
            principal.tenant_id,
            metric_ref,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            MetricDefinitionVersionListResponse(
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
            "invalid_metric_version_query",
            str(exc),
            details,
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


async def create_metric_activation_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricActivationApprovalRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _metric_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    metric_ref, version_ref = refs
    try:
        definition = await asyncio.to_thread(
            _metric_authority().get, principal.tenant_id, version_ref
        )
        requested_at = _utc_now()
        approval_case = ApprovalCase(
            tenant_id=principal.tenant_id,
            approval_case_ref=build_resource_urn(
                principal.tenant_id, "approval_case", submission.case_id
            ),
            target_resource_urn=definition.metric_version_ref,
            target_fingerprint=definition.definition_fingerprint,
            action=METRIC_ACTIVATION_ACTION,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            request_context={
                "schema": "gda.metric_activation_approval.v1",
                "metric_ref": metric_ref,
                "metric_version_ref": definition.metric_version_ref,
                "definition_fingerprint": definition.definition_fingerprint,
                "canonical_name": definition.definition.canonical_name,
                "domain": definition.definition.domain,
                "semantic_model_version_ref": (
                    definition.definition.semantic_model_version_ref
                ),
                "source_bindings": [
                    item.model_dump(mode="json")
                    for item in definition.definition.source_bindings
                ],
                "dependency_version_refs": list(
                    definition.definition.dependency_version_refs
                ),
            },
            requested_at=requested_at,
            expires_at=requested_at + timedelta(hours=submission.expires_in_hours),
        )
        result = await asyncio.to_thread(
            _approval_case_authority().create,
            approval_case,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF", "team:data-platform"
            ),
        )
        return _success(
            request,
            result.approval_case,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Metric activation approval does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def activate_metric_definition_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "metric_activation_admin_required",
            "Metric activation requires an administrator",
        )
    submission = await _parse(request, MetricDefinitionActivateRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _metric_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    _, version_ref = refs
    try:
        authority = _metric_authority()
        definition = await asyncio.to_thread(
            authority.get, principal.tenant_id, version_ref
        )
        activation = await asyncio.to_thread(
            authority.activate,
            tenant_id=principal.tenant_id,
            metric_version_ref=definition.metric_version_ref,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=build_resource_urn(
                principal.tenant_id,
                "approval_case",
                submission.approval_case_id,
            ),
            expected_activation_version=submission.expected_activation_version,
            actor_subject=principal.actor_ref,
            reason=submission.reason,
        )
        return _success(request, activation)
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


async def get_active_metric_definition(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    try:
        definition, activation = await asyncio.to_thread(
            _metric_authority().active, principal.tenant_id, metric_ref
        )
        return _success(
            request,
            MetricActiveDefinitionResponse(
                definition=definition, activation=activation
            ),
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


async def resolve_active_metric(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MetricResolutionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        resolution: MetricResolution = await asyncio.to_thread(
            _metric_authority().resolve_active,
            principal.tenant_id,
            submission.name,
            domain=submission.domain,
        )
        return _success(request, resolution)
    except ValueError as exc:
        return _error(request, 400, "invalid_metric_resolution", str(exc))
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


async def list_metric_definition_events(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    metric_ref = _metric_ref(request, principal)
    if isinstance(metric_ref, JSONResponse):
        return metric_ref
    try:
        events = await asyncio.to_thread(
            _metric_authority().events, principal.tenant_id, metric_ref
        )
        return _success(
            request,
            MetricDefinitionEventListResponse(items=events, count=len(events)),
        )
    except MetricAuthorityError as exc:
        return _metric_error(request, exc)


def _metric_route(
    path: str,
    endpoint: Any,
    *,
    method: str,
    operation_id: str,
) -> APIRoute:
    return APIRoute(
        path,
        endpoint,
        methods={method},
        name=operation_id,
        operation_id=operation_id,
        tags=["Metric Control Plane"],
        response_class=JSONResponse,
        openapi_extra={"security": [{"OAuth2PasswordBearerWithCookie": []}]},
    )


def get_metric_routes() -> list[APIRoute]:
    from .metric_query_routes import get_metric_query_routes

    base = "/api/platform/v1"
    definitions = f"{base}/metric-definitions/{{metric_definition_id}}"
    return [
        _metric_route(
            f"{definitions}/versions",
            stage_metric_definition_version,
            method="POST",
            operation_id="platform_stage_metric_definition_version",
        ),
        _metric_route(
            f"{definitions}/versions",
            list_metric_definition_versions,
            method="GET",
            operation_id="platform_list_metric_definition_versions",
        ),
        _metric_route(
            f"{definitions}/versions/{{version}}/approval-cases",
            create_metric_activation_approval_case,
            method="POST",
            operation_id="platform_create_metric_activation_approval_case",
        ),
        _metric_route(
            f"{definitions}/versions/{{version}}/activation",
            activate_metric_definition_version,
            method="POST",
            operation_id="platform_activate_metric_definition_version",
        ),
        _metric_route(
            f"{definitions}/active",
            get_active_metric_definition,
            method="GET",
            operation_id="platform_get_active_metric_definition",
        ),
        _metric_route(
            f"{definitions}/events",
            list_metric_definition_events,
            method="GET",
            operation_id="platform_list_metric_definition_events",
        ),
        _metric_route(
            f"{base}/metric-resolution",
            resolve_active_metric,
            method="POST",
            operation_id="platform_resolve_active_metric",
        ),
        *get_metric_query_routes(),
    ]
