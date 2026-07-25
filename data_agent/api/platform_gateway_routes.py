"""Versioned REST boundary for the AR-1 platform control gateway."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request
from ..platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    LineageEvent,
    NonEmptyText,
    OrchestrationClass,
    PlatformRun,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunPolicyReferences,
    RunStatus,
    Sha256,
    ShortName,
    SubjectContext,
    SubjectType,
    TenantId,
    canonical_json_fingerprint,
)
from ..platform_gateway import (
    DefinitionRegistration,
    GatewayConfigurationError,
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayUnavailableError,
    GatewayValidationError,
    PlatformGateway,
    PlatformGatewayError,
)


_TENANT_ADAPTER = TypeAdapter(TenantId)
_PLATFORM_ROLES = frozenset({"admin", "platform_operator"})


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunSubmissionRequest(StrictRequest):
    run_id: UUID
    definition_version_id: UUID
    orchestration_class: OrchestrationClass
    input_bindings: tuple[ResourceBinding, ...] = ()
    idempotency_key: NonEmptyText
    policy_refs: RunPolicyReferences | None = None
    request_dispatch: bool = False
    config_fingerprint: Sha256 | None = None
    purpose: NonEmptyText
    trace_id: ShortName | None = None
    submitted_at: datetime


class RunTransitionRequest(StrictRequest):
    expected_state_version: int = Field(ge=0)
    to_status: RunStatus
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)


class DolphinSchedulerCallbackRequest(StrictRequest):
    callback_id: UUID
    attempt_no: int = Field(default=1, ge=1)
    project_code: int = Field(gt=0)
    workflow_instance_id: int = Field(gt=0)
    workflow_definition_code: int = Field(gt=0)
    workflow_definition_version: int = Field(gt=0)
    provider_state: ShortName
    observed_at: datetime


@dataclass(frozen=True)
class GatewayPrincipal:
    tenant_id: str
    subject_id: str
    subject_type: SubjectType
    role: str

    @property
    def actor_ref(self) -> str:
        return f"{self.subject_type.value}:{self.subject_id}"


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id")
    return value or str(uuid4())


def _error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            },
            "request_id": _request_id(request),
        },
        status_code=status_code,
    )


def _success(
    request: Request,
    value: BaseModel,
    *,
    status_code: int = 200,
    created: bool | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "data": value.model_dump(mode="json"),
        "error": None,
        "request_id": _request_id(request),
    }
    if created is not None:
        body["created"] = created
    return JSONResponse(body, status_code=status_code)


def _metadata(user: Any) -> dict[str, Any]:
    if hasattr(user, "metadata") and isinstance(user.metadata, dict):
        return user.metadata
    if isinstance(user, dict) and isinstance(user.get("metadata"), dict):
        return user["metadata"]
    return {}


def _identifier(user: Any) -> str:
    if hasattr(user, "identifier"):
        return str(user.identifier)
    if isinstance(user, dict):
        return str(user.get("identifier") or user.get("id") or "")
    return ""


def _principal(request: Request) -> GatewayPrincipal | JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return _error(request, 401, "unauthorized", "Authentication is required")
    metadata = _metadata(user)
    role = str(metadata.get("role") or "")
    if role not in _PLATFORM_ROLES:
        return _error(
            request,
            403,
            "platform_role_required",
            "Platform operator role is required",
        )
    tenant_id = metadata.get("tenant_id")
    try:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
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


def _validation_details(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": ".".join(str(part) for part in item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]


async def _parse(request: Request, model: type[BaseModel]) -> BaseModel | JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _error(request, 400, "invalid_json", "Request body must be JSON")
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Request does not satisfy the platform contract",
            _validation_details(exc),
        )


def _gateway() -> PlatformGateway:
    return PlatformGateway()


def _gateway_error(request: Request, error: PlatformGatewayError) -> JSONResponse:
    if isinstance(error, (GatewayConflictError,)):
        status = 409
    elif isinstance(error, GatewayNotFoundError):
        status = 404
    elif isinstance(error, GatewayForbiddenError):
        status = 403
    elif isinstance(error, GatewayValidationError):
        status = 422
    elif isinstance(error, (GatewayConfigurationError, GatewayUnavailableError)):
        status = 503
    else:
        status = 500
    return _error(request, status, error.code, str(error))


def _tenant_matches(
    request: Request, principal: GatewayPrincipal, tenant_id: str
) -> JSONResponse | None:
    if tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Payload tenant does not match authenticated tenant",
        )
    return None


async def create_resource(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    resource = await _parse(request, Resource)
    if isinstance(resource, JSONResponse):
        return resource
    if mismatch := _tenant_matches(request, principal, resource.tenant_id):
        return mismatch
    try:
        result = await asyncio.to_thread(_gateway().register_resource, resource)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_resource_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    version = await _parse(request, ResourceVersion)
    if isinstance(version, JSONResponse):
        return version
    if mismatch := _tenant_matches(request, principal, version.tenant_id):
        return mismatch
    if version.created_by != principal.actor_ref:
        return _error(
            request, 403, "actor_mismatch", "created_by must match authenticated actor"
        )
    try:
        result = await asyncio.to_thread(
            _gateway().register_resource_version, version
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_definition(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    registration = await _parse(request, DefinitionRegistration)
    if isinstance(registration, JSONResponse):
        return registration
    if mismatch := _tenant_matches(
        request, principal, registration.resource.tenant_id
    ):
        return mismatch
    if registration.resource_version.created_by != principal.actor_ref:
        return _error(
            request, 403, "actor_mismatch", "created_by must match authenticated actor"
        )
    try:
        result = await asyncio.to_thread(
            _gateway().register_definition, registration
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_run(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, RunSubmissionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        run = PlatformRun(
            tenant_id=principal.tenant_id,
            run_id=submission.run_id,
            definition_version_id=submission.definition_version_id,
            orchestration_class=submission.orchestration_class,
            subject_context=SubjectContext(
                tenant_id=principal.tenant_id,
                subject_id=principal.subject_id,
                subject_type=principal.subject_type,
                roles=(principal.role,),
                purpose=submission.purpose,
                trace_id=submission.trace_id,
            ),
            input_bindings=submission.input_bindings,
            idempotency_key=submission.idempotency_key,
            policy_refs=submission.policy_refs,
            config_fingerprint=submission.config_fingerprint,
            submitted_at=submission.submitted_at,
        )
        result = await asyncio.to_thread(
            _gateway().submit_run,
            run,
            request_dispatch=submission.request_dispatch,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Run does not satisfy the platform contract",
            _validation_details(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_run(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    try:
        run = await asyncio.to_thread(
            _gateway().get_run, principal.tenant_id, run_id
        )
        return _success(request, run)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_run_transition(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    transition = await _parse(request, RunTransitionRequest)
    if isinstance(transition, JSONResponse):
        return transition
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    try:
        run = await asyncio.to_thread(
            _gateway().transition_run,
            principal.tenant_id,
            run_id,
            transition.expected_state_version,
            transition.to_status,
            principal.actor_ref,
            transition.reason,
            transition.details,
        )
        return _success(request, run)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_attempt_observation(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    observation = await _parse(request, FrameworkAttemptObservation)
    if isinstance(observation, JSONResponse):
        return observation
    if mismatch := _tenant_matches(request, principal, observation.tenant_id):
        return mismatch
    try:
        result = await asyncio.to_thread(_gateway().record_attempt, observation)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_dolphinscheduler_callback(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Provider callback requires workload identity",
        )
    callback = await _parse(request, DolphinSchedulerCallbackRequest)
    if isinstance(callback, JSONResponse):
        return callback
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    evidence = {
        "schema": "gda.dolphinscheduler_callback.v1",
        "source": "authenticated_callback_trigger",
        "correlation_verified": False,
        "callback_id": str(callback.callback_id),
        "project_code": callback.project_code,
        "workflow_instance_id": callback.workflow_instance_id,
        "workflow_definition_code": callback.workflow_definition_code,
        "workflow_definition_version": callback.workflow_definition_version,
        "provider_state": callback.provider_state,
    }
    try:
        observation = FrameworkAttemptObservation(
            tenant_id=principal.tenant_id,
            observation_id=callback.callback_id,
            run_id=run_id,
            attempt_no=callback.attempt_no,
            framework_kind="dolphinscheduler",
            external_namespace=str(callback.project_code),
            external_run_id=str(callback.workflow_instance_id),
            external_attempt_id=None,
            observed_state=callback.provider_state.lower(),
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=callback.observed_at,
        )
        result = await asyncio.to_thread(
            _gateway().record_attempt_and_enqueue_reconcile,
            observation,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=202 if result.created else 200,
            created=result.created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Callback does not satisfy the platform contract",
            _validation_details(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_artifact(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    artifact = await _parse(request, Artifact)
    if isinstance(artifact, JSONResponse):
        return artifact
    if mismatch := _tenant_matches(request, principal, artifact.tenant_id):
        return mismatch
    if artifact.created_by != principal.actor_ref:
        return _error(
            request, 403, "actor_mismatch", "created_by must match authenticated actor"
        )
    try:
        result = await asyncio.to_thread(_gateway().record_artifact, artifact)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_lineage_event(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    event = await _parse(request, LineageEvent)
    if isinstance(event, JSONResponse):
        return event
    if mismatch := _tenant_matches(request, principal, event.tenant_id):
        return mismatch
    if event.producer != principal.actor_ref:
        return _error(
            request, 403, "actor_mismatch", "producer must match authenticated actor"
        )
    try:
        result = await asyncio.to_thread(_gateway().record_lineage, event)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


def get_platform_gateway_routes() -> list[Route]:
    base = "/api/platform/v1"
    return [
        Route(f"{base}/resources", create_resource, methods=["POST"]),
        Route(
            f"{base}/resource-versions",
            create_resource_version,
            methods=["POST"],
        ),
        Route(f"{base}/definitions", create_definition, methods=["POST"]),
        Route(f"{base}/runs", create_run, methods=["POST"]),
        Route(f"{base}/runs/{{run_id}}", get_run, methods=["GET"]),
        Route(
            f"{base}/runs/{{run_id}}/transitions",
            create_run_transition,
            methods=["POST"],
        ),
        Route(
            f"{base}/attempt-observations",
            create_attempt_observation,
            methods=["POST"],
        ),
        Route(
            f"{base}/runs/{{run_id}}/callbacks/dolphinscheduler",
            create_dolphinscheduler_callback,
            methods=["POST"],
        ),
        Route(f"{base}/artifacts", create_artifact, methods=["POST"]),
        Route(f"{base}/lineage-events", create_lineage_event, methods=["POST"]),
    ]
