"""Versioned REST boundary for the AR-1 platform control gateway."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseAuthorityError,
    ApprovalCaseConfigurationError,
    ApprovalCaseConflictError,
    ApprovalCaseForbiddenError,
    ApprovalCaseNotFoundError,
    ApprovalCaseValidationError,
)
from ..dataops_cancel import DataOpsCancelSpec
from ..dataops_invocation import DataOpsInvocation
from ..dataops_manual import DataOpsManualTriggerSpec
from ..metadata_fabric import MetadataFabricBinding, MetadataFabricSystem
from ..platform_contracts import (
    ApprovalCase,
    ApprovalCaseEvent,
    ApprovalCaseStatus,
    Artifact,
    DataIncident,
    FrameworkAttemptObservation,
    IncidentStatus,
    LineageEvent,
    NonEmptyText,
    OrchestrationClass,
    PlatformCommand,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunPolicyReferences,
    RunStatus,
    RunSuccessEvidence,
    Sha256,
    ShortName,
    SubjectContext,
    SubjectType,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
    run_success_evidence_fingerprint,
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
from ..platform_lineage import ImpactChangeType, LineageQuerySpec
from ..platform_openlineage import (
    OpenLineageIngestionItem,
    OpenLineageIngestionResult,
    OpenLineageRunEvent,
    openlineage_to_lineage_events,
)
from .helpers import _get_user_from_request

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


class ManualDataOpsRunRequest(StrictRequest):
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
    purpose: NonEmptyText
    config_fingerprint: Sha256 | None = None


class ManualDataOpsRuntimeProfile(StrictRequest):
    workload_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    workload_roles: tuple[ShortName, ...] = Field(default=("platform_operator",), min_length=1)
    policy_version_ref: NonEmptyText
    policy_evaluator_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    invocation_owner_ref: NonEmptyText = "team:data-platform"

    @model_validator(mode="after")
    def _independent_policy_evaluator(self) -> ManualDataOpsRuntimeProfile:
        if self.policy_evaluator_subject == self.workload_subject:
            raise ValueError("policy evaluator must be independent from the workload")
        return self


class ManualDataOpsRunResponse(StrictRequest):
    request_sha256: Sha256
    admitted_at: datetime
    invocation: DataOpsInvocation
    run: PlatformRun
    command: PlatformCommand
    invocation_resource_created: bool
    invocation_version_created: bool
    policy_artifact_created: bool
    run_created: bool
    command_created: bool


class DataOpsCancelRequest(StrictRequest):
    client_request_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    expected_state_version: int = Field(ge=1)
    reason: NonEmptyText


class DataOpsCancelRuntimeProfile(StrictRequest):
    workload_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_version_ref: NonEmptyText
    policy_evaluator_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)

    @model_validator(mode="after")
    def _independent_policy_evaluator(self) -> DataOpsCancelRuntimeProfile:
        if self.policy_evaluator_subject == self.workload_subject:
            raise ValueError("policy evaluator must be independent from the workload")
        return self


class DataOpsCancelResponse(StrictRequest):
    request_sha256: Sha256
    admitted_at: datetime
    run: PlatformRun
    policy_artifact: Artifact
    command: PlatformCommand
    policy_artifact_created: bool
    command_created: bool


class DolphinSchedulerCallbackResponse(StrictRequest):
    observation: FrameworkAttemptObservation
    command: PlatformCommand | None
    observation_created: bool
    command_created: bool
    ignored_terminal: bool


class DataIncidentListResponse(StrictRequest):
    items: tuple[DataIncident, ...]
    count: int = Field(ge=0)


class DataIncidentTransitionRequest(StrictRequest):
    expected_state_version: int = Field(ge=0)
    to_status: IncidentStatus
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalCaseCreateRequest(StrictRequest):
    case_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    target_resource_urn: str = Field(min_length=12, max_length=256)
    target_fingerprint: Sha256
    action: ShortName
    request_reason: NonEmptyText
    request_context: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    expires_at: datetime


class ApprovalCaseDecisionRequest(StrictRequest):
    expected_state_version: int = Field(ge=0)
    verdict: ApprovalCaseStatus
    reason: NonEmptyText
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalCaseEventListResponse(StrictRequest):
    items: tuple[ApprovalCaseEvent, ...]
    count: int = Field(ge=0)


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


class RunSuccessRequest(StrictRequest):
    expected_state_version: int = Field(ge=0)
    attempt_observation_id: UUID
    output_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    reason: NonEmptyText


class LineageImpactQuery(StrictRequest):
    change_type: ImpactChangeType
    max_depth: int = Field(default=6, ge=1, le=12)
    max_edges: int = Field(default=500, ge=1, le=1000)


class MetadataFabricBindingListResponse(StrictRequest):
    items: tuple[MetadataFabricBinding, ...]
    count: int = Field(ge=0)


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


def _approval_case_authority() -> ApprovalCaseAuthority:
    return ApprovalCaseAuthority()


def _manual_runtime_profile() -> ManualDataOpsRuntimeProfile:
    required = {
        "workload_subject": os.environ.get("GDA_DATAOPS_MANUAL_WORKLOAD_SUBJECT"),
        "policy_version_ref": os.environ.get("GDA_DATAOPS_MANUAL_POLICY_VERSION_REF"),
        "policy_evaluator_subject": os.environ.get("GDA_DATAOPS_MANUAL_POLICY_EVALUATOR_SUBJECT"),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise GatewayConfigurationError("manual DataOps admission profile is incomplete")
    raw_roles = os.environ.get("GDA_DATAOPS_MANUAL_WORKLOAD_ROLES", "platform_operator")
    try:
        return ManualDataOpsRuntimeProfile(
            **required,
            workload_roles=tuple(role.strip() for role in raw_roles.split(",") if role.strip()),
            policy_ttl_seconds=int(
                os.environ.get("GDA_DATAOPS_MANUAL_POLICY_TTL_SECONDS", "86400")
            ),
            invocation_owner_ref=os.environ.get(
                "GDA_DATAOPS_MANUAL_INVOCATION_OWNER_REF", "team:data-platform"
            ),
        )
    except (ValidationError, ValueError) as exc:
        raise GatewayConfigurationError("manual DataOps admission profile is invalid") from exc


def _cancel_runtime_profile() -> DataOpsCancelRuntimeProfile:
    required = {
        "workload_subject": os.environ.get("GDA_DATAOPS_CANCEL_WORKLOAD_SUBJECT")
        or os.environ.get("GDA_DATAOPS_MANUAL_WORKLOAD_SUBJECT"),
        "policy_version_ref": os.environ.get("GDA_DATAOPS_CANCEL_POLICY_VERSION_REF")
        or os.environ.get("GDA_DATAOPS_MANUAL_POLICY_VERSION_REF"),
        "policy_evaluator_subject": os.environ.get("GDA_DATAOPS_CANCEL_POLICY_EVALUATOR_SUBJECT")
        or os.environ.get("GDA_DATAOPS_MANUAL_POLICY_EVALUATOR_SUBJECT"),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise GatewayConfigurationError("DataOps cancel admission profile is incomplete")
    try:
        return DataOpsCancelRuntimeProfile(
            **required,
            policy_ttl_seconds=int(
                os.environ.get("GDA_DATAOPS_CANCEL_POLICY_TTL_SECONDS")
                or os.environ.get("GDA_DATAOPS_MANUAL_POLICY_TTL_SECONDS", "86400")
            ),
        )
    except (ValidationError, ValueError) as exc:
        raise GatewayConfigurationError("DataOps cancel admission profile is invalid") from exc


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


def _approval_case_error(
    request: Request, error: ApprovalCaseAuthorityError
) -> JSONResponse:
    if isinstance(error, ApprovalCaseConflictError):
        status = 409
    elif isinstance(error, ApprovalCaseNotFoundError):
        status = 404
    elif isinstance(error, ApprovalCaseForbiddenError):
        status = 403
    elif isinstance(error, ApprovalCaseValidationError):
        status = 422
    elif isinstance(error, ApprovalCaseConfigurationError):
        status = 503
    else:
        status = 500
    return _error(request, status, error.code, str(error))


def _approval_case_ref(request: Request, principal: GatewayPrincipal) -> str | JSONResponse:
    case_id = request.path_params.get("case_id", "")
    try:
        return build_resource_urn(principal.tenant_id, "approval_case", case_id)
    except ValueError:
        return _error(
            request,
            400,
            "invalid_approval_case_id",
            "case_id must be a canonical lowercase resource identifier",
        )


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


async def create_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, ApprovalCaseCreateRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        approval_case = ApprovalCase(
            tenant_id=principal.tenant_id,
            approval_case_ref=build_resource_urn(
                principal.tenant_id,
                "approval_case",
                submission.case_id,
            ),
            target_resource_urn=submission.target_resource_urn,
            target_fingerprint=submission.target_fingerprint,
            action=submission.action,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            request_context=submission.request_context,
            requested_at=submission.requested_at,
            expires_at=submission.expires_at,
        )
        result = await asyncio.to_thread(
            _approval_case_authority().create,
            approval_case,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
        return _success(
            request,
            result.approval_case,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "ApprovalCase does not satisfy the platform contract",
            details,
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def get_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        approval_case = await asyncio.to_thread(
            _approval_case_authority().get,
            principal.tenant_id,
            approval_case_ref,
        )
        return _success(request, approval_case)
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def list_approval_case_events(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        events = await asyncio.to_thread(
            _approval_case_authority().events,
            principal.tenant_id,
            approval_case_ref,
        )
        return _success(
            request,
            ApprovalCaseEventListResponse(items=events, count=len(events)),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def decide_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "ApprovalCase decision requires a human identity",
        )
    decision = await _parse(request, ApprovalCaseDecisionRequest)
    if isinstance(decision, JSONResponse):
        return decision
    if decision.verdict is ApprovalCaseStatus.PENDING:
        return _error(
            request,
            422,
            "terminal_verdict_required",
            "ApprovalCase decision must be approved, rejected, or cancelled",
        )
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        approval_case = await asyncio.to_thread(
            _approval_case_authority().decide,
            tenant_id=principal.tenant_id,
            approval_case_ref=approval_case_ref,
            expected_state_version=decision.expected_state_version,
            verdict=decision.verdict,
            actor_subject=principal.actor_ref,
            reason=decision.reason,
            details=decision.details,
        )
        return _success(request, approval_case)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "ApprovalCase decision does not satisfy the platform contract",
            details,
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


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
        return _error(request, 403, "actor_mismatch", "created_by must match authenticated actor")
    try:
        result = await asyncio.to_thread(_gateway().register_resource_version, version)
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
    if mismatch := _tenant_matches(request, principal, registration.resource.tenant_id):
        return mismatch
    if registration.resource_version.created_by != principal.actor_ref:
        return _error(request, 403, "actor_mismatch", "created_by must match authenticated actor")
    try:
        result = await asyncio.to_thread(_gateway().register_definition, registration)
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


async def create_manual_dataops_run(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "Manual DataOps admission requires a human identity",
        )
    submission = await _parse(request, ManualDataOpsRunRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        profile = _manual_runtime_profile()
        spec = DataOpsManualTriggerSpec(
            tenant_id=principal.tenant_id,
            client_request_id=submission.client_request_id,
            definition_version_id=submission.definition_version_id,
            logical_start=submission.logical_start,
            logical_end=submission.logical_end,
            input_bindings=submission.input_bindings,
            execution_plan_artifact_id=submission.execution_plan_artifact_id,
            requester_subject=principal.actor_ref,
            workload_subject_id=profile.workload_subject.removeprefix("workload:"),
            workload_roles=profile.workload_roles,
            purpose=submission.purpose,
            policy_version_ref=profile.policy_version_ref,
            policy_evaluator_subject=profile.policy_evaluator_subject,
            policy_ttl_seconds=profile.policy_ttl_seconds,
            config_fingerprint=submission.config_fingerprint,
            invocation_owner_ref=profile.invocation_owner_ref,
        )
        result = await asyncio.to_thread(_gateway().submit_manual_trigger, spec)
        response = ManualDataOpsRunResponse(
            request_sha256=result.request_sha256,
            admitted_at=result.admitted_at,
            invocation=result.invocation,
            run=result.run,
            command=result.command,
            invocation_resource_created=result.invocation_resource_created,
            invocation_version_created=result.invocation_version_created,
            policy_artifact_created=result.policy_artifact_created,
            run_created=result.run_created,
            command_created=result.command_created,
        )
        return _success(
            request,
            response,
            status_code=202 if result.created else 200,
            created=result.created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Manual DataOps request does not satisfy the platform contract",
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
        run = await asyncio.to_thread(_gateway().get_run, principal.tenant_id, run_id)
        return _success(request, run)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_dataops_cancel(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "DataOps cancellation requires a human identity",
        )
    cancellation = await _parse(request, DataOpsCancelRequest)
    if isinstance(cancellation, JSONResponse):
        return cancellation
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    try:
        profile = _cancel_runtime_profile()
        spec = DataOpsCancelSpec(
            tenant_id=principal.tenant_id,
            run_id=run_id,
            client_request_id=cancellation.client_request_id,
            expected_state_version=cancellation.expected_state_version,
            requester_subject=principal.actor_ref,
            reason=cancellation.reason,
            workload_subject=profile.workload_subject,
            policy_version_ref=profile.policy_version_ref,
            policy_evaluator_subject=profile.policy_evaluator_subject,
            policy_ttl_seconds=profile.policy_ttl_seconds,
        )
        result = await asyncio.to_thread(_gateway().admit_dataops_cancel, spec)
        response = DataOpsCancelResponse(
            request_sha256=result.request_sha256,
            admitted_at=result.admitted_at,
            run=result.run,
            policy_artifact=result.policy_artifact,
            command=result.command,
            policy_artifact_created=result.policy_artifact_created,
            command_created=result.command_created,
        )
        return _success(
            request,
            response,
            status_code=202 if result.created else 200,
            created=result.created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "DataOps cancel request does not satisfy the platform contract",
            _validation_details(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def list_data_incidents(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    raw_status = request.query_params.get("status")
    raw_run_id = request.query_params.get("run_id")
    try:
        status = IncidentStatus(raw_status) if raw_status else None
        run_id = UUID(raw_run_id) if raw_run_id else None
        limit = int(request.query_params.get("limit", "100"))
    except (ValueError, TypeError):
        return _error(
            request,
            400,
            "invalid_incident_query",
            "status, run_id, or limit is invalid",
        )
    try:
        incidents = await asyncio.to_thread(
            _gateway().list_incidents,
            principal.tenant_id,
            status=status,
            run_id=run_id,
            limit=limit,
        )
        return _success(
            request,
            DataIncidentListResponse(items=incidents, count=len(incidents)),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_data_incident(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        incident_id = UUID(request.path_params["incident_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_incident_id", "incident_id must be a UUID")
    try:
        incident = await asyncio.to_thread(
            _gateway().get_incident,
            principal.tenant_id,
            incident_id,
        )
        return _success(request, incident)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def transition_data_incident(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "DataIncident remediation requires a human identity",
        )
    transition = await _parse(request, DataIncidentTransitionRequest)
    if isinstance(transition, JSONResponse):
        return transition
    if transition.to_status == IncidentStatus.OPEN:
        return _error(
            request,
            422,
            "incident_reopen_forbidden",
            "Resolved incidents cannot be reopened",
        )
    try:
        incident_id = UUID(request.path_params["incident_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_incident_id", "incident_id must be a UUID")
    try:
        incident = await asyncio.to_thread(
            _gateway().transition_incident,
            principal.tenant_id,
            incident_id,
            transition.expected_state_version,
            transition.to_status,
            principal.actor_ref,
            transition.reason,
            transition.details,
        )
        return _success(request, incident)
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
    if transition.to_status in {RunStatus.CANCELLING, RunStatus.CANCELLED}:
        return _error(
            request,
            422,
            "governed_cancel_required",
            "Cancellation must use the governed DataOps cancel endpoint",
        )
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
        response = DolphinSchedulerCallbackResponse(
            observation=result.observation,
            command=result.command,
            observation_created=result.observation_created,
            command_created=result.command_created,
            ignored_terminal=result.ignored_terminal,
        )
        return _success(
            request,
            response,
            status_code=202 if result.command_created else 200,
            created=result.command_created,
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
        return _error(request, 403, "actor_mismatch", "created_by must match authenticated actor")
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


async def create_quality_result(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Quality evaluation requires workload identity",
        )
    quality = await _parse(request, QualityResult)
    if isinstance(quality, JSONResponse):
        return quality
    if mismatch := _tenant_matches(request, principal, quality.tenant_id):
        return mismatch
    if quality.evaluated_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "evaluated_by must match authenticated actor",
        )
    try:
        result = await asyncio.to_thread(_gateway().record_quality_result, quality)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def finalize_run_success(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Run finalization requires workload identity",
        )
    finalization = await _parse(request, RunSuccessRequest)
    if isinstance(finalization, JSONResponse):
        return finalization
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    evidence_sha256 = run_success_evidence_fingerprint(
        tenant_id=principal.tenant_id,
        run_id=run_id,
        attempt_observation_id=finalization.attempt_observation_id,
        output_artifact_id=finalization.output_artifact_id,
        quality_result_id=finalization.quality_result_id,
        lineage_event_id=finalization.lineage_event_id,
    )
    evidence = RunSuccessEvidence(
        tenant_id=principal.tenant_id,
        run_id=run_id,
        attempt_observation_id=finalization.attempt_observation_id,
        output_artifact_id=finalization.output_artifact_id,
        quality_result_id=finalization.quality_result_id,
        lineage_event_id=finalization.lineage_event_id,
        evidence_sha256=evidence_sha256,
    )
    try:
        run = await asyncio.to_thread(
            _gateway().finalize_run_success,
            evidence,
            expected_state_version=finalization.expected_state_version,
            actor_subject=principal.actor_ref,
            reason=finalization.reason,
        )
        return _success(request, run)
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
        return _error(request, 403, "actor_mismatch", "producer must match authenticated actor")
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


async def create_metadata_fabric_binding(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    binding = await _parse(request, MetadataFabricBinding)
    if isinstance(binding, JSONResponse):
        return binding
    if mismatch := _tenant_matches(request, principal, binding.tenant_id):
        return mismatch
    if binding.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().register_metadata_fabric_binding,
            binding,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def list_metadata_fabric_bindings(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    resource_urn = request.query_params.get("resource_urn", "")
    raw_system = request.query_params.get("system")
    try:
        urn_tenant = parse_resource_urn(resource_urn)["tenant_id"]
        system = MetadataFabricSystem(raw_system) if raw_system is not None else None
    except ValueError:
        return _error(
            request,
            400,
            "invalid_metadata_fabric_query",
            "resource_urn or Metadata Fabric system is invalid",
        )
    if mismatch := _tenant_matches(request, principal, urn_tenant):
        return mismatch
    try:
        bindings = await asyncio.to_thread(
            _gateway().list_metadata_fabric_bindings,
            principal.tenant_id,
            resource_urn,
            system=system,
        )
        return _success(
            request,
            MetadataFabricBindingListResponse(
                items=bindings,
                count=len(bindings),
            ),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_openlineage_event(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "OpenLineage ingestion requires workload identity",
        )
    openlineage_event = await _parse(request, OpenLineageRunEvent)
    if isinstance(openlineage_event, JSONResponse):
        return openlineage_event
    platform = openlineage_event.run.gda_platform()
    if mismatch := _tenant_matches(request, principal, platform.tenant_id):
        return mismatch

    events = openlineage_to_lineage_events(
        openlineage_event,
        authenticated_producer=principal.actor_ref,
    )
    try:
        write_results = await asyncio.to_thread(
            _gateway().record_lineage_batch,
            events,
        )
        items = tuple(
            OpenLineageIngestionItem(
                lineage_event=result.value,
                created=result.created,
            )
            for result in write_results
        )
        created_count = sum(item.created for item in items)
        response = OpenLineageIngestionResult(
            run_id=openlineage_event.run.run_id,
            event_count=len(items),
            created_count=created_count,
            replayed_count=len(items) - created_count,
            items=items,
        )
        return _success(
            request,
            response,
            status_code=201 if created_count else 200,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_resource_version_lineage(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        resource_version_id = UUID(request.path_params["resource_version_id"])
    except (KeyError, ValueError):
        return _error(
            request,
            400,
            "invalid_resource_version_id",
            "resource_version_id must be a UUID",
        )
    try:
        query = LineageQuerySpec(
            direction=request.query_params.get("direction", "both"),
            max_depth=request.query_params.get("max_depth", "6"),
            max_edges=request.query_params.get("max_edges", "500"),
            require_complete=request.query_params.get("require_complete", "false"),
        )
    except ValidationError as exc:
        return _error(
            request,
            400,
            "invalid_lineage_query",
            "direction, max_depth, max_edges, or require_complete is invalid",
            _validation_details(exc),
        )
    try:
        graph = await asyncio.to_thread(
            _gateway().query_lineage,
            principal.tenant_id,
            resource_version_id,
            direction=query.direction,
            max_depth=query.max_depth,
            max_edges=query.max_edges,
            require_complete=query.require_complete,
        )
        return _success(request, graph)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_resource_version_impact(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        resource_version_id = UUID(request.path_params["resource_version_id"])
    except (KeyError, ValueError):
        return _error(
            request,
            400,
            "invalid_resource_version_id",
            "resource_version_id must be a UUID",
        )
    try:
        query = LineageImpactQuery(
            change_type=request.query_params.get("change_type"),
            max_depth=request.query_params.get("max_depth", "6"),
            max_edges=request.query_params.get("max_edges", "500"),
        )
    except ValidationError as exc:
        return _error(
            request,
            400,
            "invalid_lineage_impact_query",
            "change_type, max_depth, or max_edges is invalid",
            _validation_details(exc),
        )
    try:
        assessment = await asyncio.to_thread(
            _gateway().assess_lineage_impact,
            principal.tenant_id,
            resource_version_id,
            change_type=query.change_type,
            max_depth=query.max_depth,
            max_edges=query.max_edges,
        )
        return _success(request, assessment)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


def _platform_route(
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
        tags=["Platform Control Plane"],
        response_class=JSONResponse,
        openapi_extra={
            "security": [{"OAuth2PasswordBearerWithCookie": []}],
        },
    )


def get_platform_gateway_routes() -> list[APIRoute]:
    base = "/api/platform/v1"
    return [
        _platform_route(
            f"{base}/resources",
            create_resource,
            method="POST",
            operation_id="platform_create_resource",
        ),
        _platform_route(
            f"{base}/approval-cases",
            create_approval_case,
            method="POST",
            operation_id="platform_create_approval_case",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}",
            get_approval_case,
            method="GET",
            operation_id="platform_get_approval_case",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/events",
            list_approval_case_events,
            method="GET",
            operation_id="platform_list_approval_case_events",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/decision",
            decide_approval_case,
            method="POST",
            operation_id="platform_decide_approval_case",
        ),
        _platform_route(
            f"{base}/resource-versions",
            create_resource_version,
            method="POST",
            operation_id="platform_create_resource_version",
        ),
        _platform_route(
            f"{base}/definitions",
            create_definition,
            method="POST",
            operation_id="platform_create_definition",
        ),
        _platform_route(
            f"{base}/runs",
            create_run,
            method="POST",
            operation_id="platform_create_run",
        ),
        _platform_route(
            f"{base}/dataops/manual-runs",
            create_manual_dataops_run,
            method="POST",
            operation_id="platform_create_manual_dataops_run",
        ),
        _platform_route(
            f"{base}/runs/{{run_id}}",
            get_run,
            method="GET",
            operation_id="platform_get_run",
        ),
        _platform_route(
            f"{base}/runs/{{run_id}}/cancel",
            create_dataops_cancel,
            method="POST",
            operation_id="platform_cancel_run",
        ),
        _platform_route(
            f"{base}/incidents",
            list_data_incidents,
            method="GET",
            operation_id="platform_list_data_incidents",
        ),
        _platform_route(
            f"{base}/incidents/{{incident_id}}",
            get_data_incident,
            method="GET",
            operation_id="platform_get_data_incident",
        ),
        _platform_route(
            f"{base}/incidents/{{incident_id}}/transitions",
            transition_data_incident,
            method="POST",
            operation_id="platform_transition_data_incident",
        ),
        _platform_route(
            f"{base}/runs/{{run_id}}/transitions",
            create_run_transition,
            method="POST",
            operation_id="platform_transition_run",
        ),
        _platform_route(
            f"{base}/attempt-observations",
            create_attempt_observation,
            method="POST",
            operation_id="platform_create_attempt_observation",
        ),
        _platform_route(
            f"{base}/runs/{{run_id}}/callbacks/dolphinscheduler",
            create_dolphinscheduler_callback,
            method="POST",
            operation_id="platform_create_dolphinscheduler_callback",
        ),
        _platform_route(
            f"{base}/artifacts",
            create_artifact,
            method="POST",
            operation_id="platform_create_artifact",
        ),
        _platform_route(
            f"{base}/quality-results",
            create_quality_result,
            method="POST",
            operation_id="platform_create_quality_result",
        ),
        _platform_route(
            f"{base}/runs/{{run_id}}/finalize-success",
            finalize_run_success,
            method="POST",
            operation_id="platform_finalize_run_success",
        ),
        _platform_route(
            f"{base}/lineage-events",
            create_lineage_event,
            method="POST",
            operation_id="platform_create_lineage_event",
        ),
        _platform_route(
            f"{base}/metadata-fabric/bindings",
            create_metadata_fabric_binding,
            method="POST",
            operation_id="platform_create_metadata_fabric_binding",
        ),
        _platform_route(
            f"{base}/metadata-fabric/bindings",
            list_metadata_fabric_bindings,
            method="GET",
            operation_id="platform_list_metadata_fabric_bindings",
        ),
        _platform_route(
            f"{base}/openlineage/events",
            create_openlineage_event,
            method="POST",
            operation_id="platform_create_openlineage_event",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/lineage",
            get_resource_version_lineage,
            method="GET",
            operation_id="platform_get_resource_version_lineage",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/impact",
            get_resource_version_impact,
            method="GET",
            operation_id="platform_get_resource_version_impact",
        ),
    ]
