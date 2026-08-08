"""Versioned REST boundary for the AR-1 platform control gateway."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
from starlette.responses import JSONResponse, Response

from ..approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseAuthorityError,
    ApprovalCaseConfigurationError,
    ApprovalCaseConflictError,
    ApprovalCaseForbiddenError,
    ApprovalCaseNotFoundError,
    ApprovalCasePage,
    ApprovalCaseValidationError,
)
from ..architecture_change_approval import (
    ArchitectureChangeApprovalError,
    ArchitectureChangeApprovalService,
    ArchitectureChangeReview,
)
from ..capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    DATAOPS_MANUAL_RUN_SUBMIT,
    DATAOPS_RUN_CANCEL,
    CapabilityFingerprintMismatchError,
    CapabilitySpec,
)
from ..data_architecture_ledger import ResourceVersionArchitectureReconciliation
from ..dataops_cancel import (
    DataOpsCancelRequest,
    DataOpsCancelResponse,
    DataOpsCancelSpec,
)
from ..dataops_manual import (
    DataOpsManualTriggerSpec,
    ManualDataOpsRunRequest,
    ManualDataOpsRunResponse,
)
from ..gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    martin_provider_manifest,
)
from ..gis_service_control_plane import EndpointProtocol, GISServiceType
from ..master_data_authority import (
    MASTER_DATA_ACTIVATION_ACTION,
    MasterDataAuthority,
    MasterDataAuthorityError,
    MasterDataConfigurationError,
    MasterDataConflictError,
    MasterDataDomain,
    MasterDataEvent,
    MasterDataForbiddenError,
    MasterDataNotFoundError,
    MasterDataValidationError,
    MasterEntityActivation,
    MasterEntityVersion,
    MasterEntityVersionDraft,
    MasterEntityVersionPage,
    MasterMatchResult,
    MasterResourceProjection,
    MasterResourceProjectionPage,
    MasterSourceRecordDraft,
)
from ..metadata_fabric import MetadataFabricBinding, MetadataFabricSystem
from ..platform_contracts import (
    ApprovalAssignmentActorAccess,
    ApprovalAvailabilityStatus,
    ApprovalCase,
    ApprovalCaseAssignment,
    ApprovalCaseAssignmentEvent,
    ApprovalCaseAssignmentOperation,
    ApprovalCaseEvent,
    ApprovalCaseNotification,
    ApprovalCaseNotificationRecoveryEvent,
    ApprovalCaseStatus,
    ApprovalPrincipal,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    ApprovalTeamMembership,
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
    ResourceURNText,
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
from ..slo_authority import (
    SLO_ACTIVATION_ACTION,
    SLOAuthorityError,
    SLOBurnRateWindow,
    SLOCompilationError,
    SLOConfigurationError,
    SLOConflictError,
    SLODefinitionActivation,
    SLODefinitionAuthority,
    SLODefinitionDraft,
    SLODefinitionEvent,
    SLODefinitionVersion,
    SLODefinitionVersionPage,
    SLOEventRatioIndicator,
    SLOForbiddenError,
    SLONotFoundError,
    SLOValidationError,
    compile_slo_prometheus_rules,
)
from ..slo_incident import (
    AlertmanagerSLOWebhook,
    SLOAlertReconciliationResult,
    SLOIncidentReconciler,
    SLOIncidentValidationError,
)
from .helpers import _get_user_from_request

_TENANT_ADAPTER = TypeAdapter(TenantId)
_APPROVAL_ACTION_ADAPTER = TypeAdapter(ShortName)
_PLATFORM_ROLES = frozenset({"admin", "platform_operator"})


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MVTGatewayEndpointContract(StrictRequest):
    """Provider placement contract consumed by the operator-only tile route."""

    contract_schema: Literal["gda.mvt_endpoint.v1"] = Field(alias="schema")
    provider_layer_ref: str = Field(
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$"
    )
    provider_query: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def _governed_publication_query(self) -> MVTGatewayEndpointContract:
        publication_id = self.provider_query.get("publication_id")
        if publication_id is None:
            raise ValueError("MVT provider_query must bind publication_id")
        try:
            UUID(publication_id)
        except ValueError as exc:
            raise ValueError("MVT publication_id must be a UUID") from exc
        return self


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


class DataOpsCancelHttpBody(StrictRequest):
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


class DolphinSchedulerCallbackResponse(StrictRequest):
    observation: FrameworkAttemptObservation
    command: PlatformCommand | None
    observation_created: bool
    command_created: bool
    ignored_terminal: bool


class DataIncidentListResponse(StrictRequest):
    items: tuple[DataIncident, ...]
    count: int = Field(ge=0)


class ResourceVersionListResponse(StrictRequest):
    items: tuple[ResourceVersion, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class ArchitectureChangeReviewRequest(StrictRequest):
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class ArchitectureChangeReviewResponse(StrictRequest):
    reconciliation: ResourceVersionArchitectureReconciliation
    review: ArchitectureChangeReview
    approval_case: ApprovalCase


class SLODefinitionStageRequest(StrictRequest):
    version: int = Field(ge=1, le=1_000_000)
    service_resource_urn: ResourceURNText
    indicator: SLOEventRatioIndicator
    objective_basis_points: int = Field(ge=1, le=9999)
    objective_window_seconds: int = Field(
        ge=3600,
        le=366 * 24 * 60 * 60,
    )
    owner_subject: str
    oncall_ref: str
    burn_rate_windows: tuple[SLOBurnRateWindow, ...]
    creation_reason: NonEmptyText


class SLODefinitionVersionListResponse(StrictRequest):
    items: tuple[SLODefinitionVersion, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class SLOActivationApprovalRequest(StrictRequest):
    case_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class SLODefinitionActivateRequest(StrictRequest):
    approval_case_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    expected_activation_version: int = Field(ge=0)
    reason: NonEmptyText


class SLOActiveDefinitionResponse(StrictRequest):
    definition: SLODefinitionVersion
    activation: SLODefinitionActivation


class SLOPrometheusRulePreviewResponse(SLOActiveDefinitionResponse):
    prometheus_rules: dict[str, Any]


class SLODefinitionEventListResponse(StrictRequest):
    items: tuple[SLODefinitionEvent, ...]
    count: int = Field(ge=0)


class MasterSourceObservationRequest(StrictRequest):
    domain: MasterDataDomain
    source_system_ref: ResourceURNText
    source_record_id: str = Field(min_length=1, max_length=256)
    source_revision: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    business_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    display_name: str = Field(min_length=1, max_length=256)
    parent_business_key: str | None = Field(default=None, max_length=128)
    attributes: dict[str, Any] = Field(default_factory=dict)


class MasterMatchRequest(StrictRequest):
    limit: int = Field(default=5, ge=1, le=20)


class MasterEntityVersionStageRequest(StrictRequest):
    version: int = Field(ge=1, le=1_000_000)
    domain: MasterDataDomain
    business_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    canonical_name: str = Field(min_length=1, max_length=256)
    parent_entity_ref: ResourceURNText | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_record_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    match_candidate_refs: tuple[ResourceURNText, ...] = Field(
        default=(),
        max_length=100,
    )
    valid_from: date
    valid_to: date | None = None
    owner_subject: str
    creation_reason: NonEmptyText


class MasterEntityVersionListResponse(StrictRequest):
    items: tuple[MasterEntityVersion, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class MasterActivationApprovalRequest(StrictRequest):
    case_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class MasterEntityActivateRequest(StrictRequest):
    approval_case_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    expected_activation_version: int = Field(ge=0)
    reason: NonEmptyText


class MasterActiveEntityResponse(StrictRequest):
    entity: MasterEntityVersion
    activation: MasterEntityActivation


class MasterDataEventListResponse(StrictRequest):
    items: tuple[MasterDataEvent, ...]
    count: int = Field(ge=0)


class MasterResourceProjectionListResponse(StrictRequest):
    items: tuple[MasterResourceProjection, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


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


class ApprovalCaseListResponse(StrictRequest):
    items: tuple[ApprovalCase, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class ApprovalCaseNotificationListResponse(StrictRequest):
    items: tuple[ApprovalCaseNotification, ...]
    count: int = Field(ge=0)
    recoveries: tuple[ApprovalCaseNotificationRecoveryEvent, ...] = ()
    recovery_count: int = Field(default=0, ge=0)


class ApprovalCaseNotificationRetryRequest(StrictRequest):
    expected_attempt_count: int = Field(ge=1)
    reason: NonEmptyText


class ApprovalCaseAssignmentRequest(StrictRequest):
    expected_assignment_version: int = Field(ge=0)
    operation: ApprovalCaseAssignmentOperation
    assignee_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[^\s:][^\s]{0,127}$",
    )
    assignee_subject: str | None = Field(
        default=None,
        min_length=7,
        max_length=133,
        pattern=r"^(human|team):[a-z0-9][a-z0-9._-]{0,127}$",
    )
    reason: NonEmptyText

    @model_validator(mode="after")
    def _consistent_assignment_request(self) -> ApprovalCaseAssignmentRequest:
        if self.operation is ApprovalCaseAssignmentOperation.RELEASE:
            if self.assignee_id is not None or self.assignee_subject is not None:
                raise ValueError("release must not specify an assignee")
        elif (self.assignee_id is None) == (self.assignee_subject is None):
            raise ValueError(
                "assignment operation requires exactly one typed assignee"
            )
        return self

    @property
    def resolved_assignee_subject(self) -> str | None:
        if self.assignee_subject is not None:
            return self.assignee_subject
        return f"human:{self.assignee_id}" if self.assignee_id is not None else None


class ApprovalCaseAssignmentResponse(StrictRequest):
    current: ApprovalCaseAssignment | None = None
    events: tuple[ApprovalCaseAssignmentEvent, ...] = ()
    event_count: int = Field(default=0, ge=0)
    actor_access: ApprovalAssignmentActorAccess | None = None


class ApprovalPrincipalListResponse(StrictRequest):
    items: tuple[ApprovalPrincipal, ...]
    count: int = Field(ge=0)


class ApprovalTeamMembershipListResponse(StrictRequest):
    items: tuple[ApprovalTeamMembership, ...]
    count: int = Field(ge=0)


class ApprovalPrincipalUpsertRequest(StrictRequest):
    expected_directory_version: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=200)
    status: ApprovalPrincipalStatus = ApprovalPrincipalStatus.ACTIVE
    approval_eligible: bool = True
    availability_status: ApprovalAvailabilityStatus = (
        ApprovalAvailabilityStatus.AVAILABLE
    )
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: NonEmptyText

    @model_validator(mode="after")
    def _consistent_validity(self) -> ApprovalPrincipalUpsertRequest:
        for value in (self.valid_from, self.valid_until):
            if value is not None and value.utcoffset() is None:
                raise ValueError("approval principal validity must include timezone")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("approval principal validity must have positive duration")
        return self


class ApprovalTeamMembershipUpsertRequest(StrictRequest):
    expected_membership_version: int = Field(ge=0)
    status: ApprovalPrincipalStatus = ApprovalPrincipalStatus.ACTIVE
    can_delegate: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: NonEmptyText

    @model_validator(mode="after")
    def _consistent_validity(self) -> ApprovalTeamMembershipUpsertRequest:
        for value in (self.valid_from, self.valid_until):
            if value is not None and value.utcoffset() is None:
                raise ValueError("approval membership validity must include timezone")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("approval membership validity must have positive duration")
        return self


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
        "data": value.model_dump(mode="json", by_alias=True),
        "error": None,
        "request_id": _request_id(request),
    }
    if created is not None:
        body["created"] = created
    return JSONResponse(body, status_code=status_code)


def _capability_contract_guard(
    request: Request,
    spec: CapabilitySpec,
) -> JSONResponse | None:
    fingerprint = request.headers.get(CAPABILITY_FINGERPRINT_HEADER)
    if fingerprint is None:
        fingerprint = request.headers.get(CAPABILITY_FINGERPRINT_HEADER.lower())
    try:
        spec.assert_invocation_fingerprint(fingerprint)
    except CapabilityFingerprintMismatchError:
        return _error(
            request,
            409,
            "capability_contract_mismatch",
            "Client CapabilitySpec fingerprint does not match the serving contract",
            [
                {
                    "capability_id": spec.capability_id,
                    "version": spec.version,
                    "fingerprint": spec.fingerprint,
                }
            ],
        )
    return None


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


def _slo_authority() -> SLODefinitionAuthority:
    return SLODefinitionAuthority()


def _master_data_authority() -> MasterDataAuthority:
    return MasterDataAuthority()


def _slo_incident_reconciler() -> SLOIncidentReconciler:
    return SLOIncidentReconciler(_slo_authority(), _gateway())


def _slo_alert_detector_subject() -> str:
    subject = os.environ.get("GDA_SLO_ALERT_DETECTOR_SUBJECT", "")
    if re.fullmatch(r"workload:[^\s]{1,128}", subject) is None:
        raise GatewayConfigurationError(
            "SLO alert detector workload identity is not configured"
        )
    return subject


def _architecture_change_approval_service() -> ArchitectureChangeApprovalService:
    return ArchitectureChangeApprovalService(
        _gateway(),
        _approval_case_authority(),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


def _slo_error(request: Request, error: SLOAuthorityError) -> JSONResponse:
    if isinstance(error, SLOConflictError):
        status = 409
    elif isinstance(error, SLONotFoundError):
        status = 404
    elif isinstance(error, SLOForbiddenError):
        status = 403
    elif isinstance(error, SLOValidationError):
        status = 422
    elif isinstance(error, SLOConfigurationError):
        status = 503
    else:
        status = 500
    return _error(request, status, error.code, str(error))


def _master_data_error(
    request: Request,
    error: MasterDataAuthorityError,
) -> JSONResponse:
    if isinstance(error, MasterDataConflictError):
        status = 409
    elif isinstance(error, MasterDataNotFoundError):
        status = 404
    elif isinstance(error, MasterDataForbiddenError):
        status = 403
    elif isinstance(error, MasterDataValidationError):
        status = 422
    elif isinstance(error, MasterDataConfigurationError):
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


def _slo_definition_ref(
    request: Request,
    principal: GatewayPrincipal,
) -> str | JSONResponse:
    definition_id = request.path_params.get("slo_definition_id", "")
    try:
        return build_resource_urn(
            principal.tenant_id,
            "slo_definition",
            definition_id,
        )
    except ValueError:
        return _error(
            request,
            400,
            "invalid_slo_definition_id",
            "slo_definition_id must be a canonical lowercase resource identifier",
        )


def _slo_version_refs(
    request: Request,
    principal: GatewayPrincipal,
) -> tuple[str, str] | JSONResponse:
    definition_ref = _slo_definition_ref(request, principal)
    if isinstance(definition_ref, JSONResponse):
        return definition_ref
    try:
        version = int(request.path_params.get("version", ""))
    except (TypeError, ValueError):
        version = 0
    if not 1 <= version <= 1_000_000:
        return _error(
            request,
            400,
            "invalid_slo_version",
            "version must be an integer between 1 and 1000000",
        )
    return definition_ref, f"{definition_ref}.v{version}"


def _master_entity_ref(
    request: Request,
    principal: GatewayPrincipal,
) -> str | JSONResponse:
    entity_id = request.path_params.get("entity_id", "")
    try:
        return build_resource_urn(principal.tenant_id, "master_entity", entity_id)
    except ValueError:
        return _error(
            request,
            400,
            "invalid_master_entity_id",
            "entity_id must be a canonical lowercase resource identifier",
        )


def _master_entity_version_refs(
    request: Request,
    principal: GatewayPrincipal,
) -> tuple[str, str] | JSONResponse:
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        version = int(request.path_params.get("version", ""))
    except (TypeError, ValueError):
        version = 0
    if not 1 <= version <= 1_000_000:
        return _error(
            request,
            400,
            "invalid_master_entity_version",
            "version must be an integer between 1 and 1000000",
        )
    return entity_ref, f"{entity_ref}.v{version}"


def _master_source_record_ref(
    request: Request,
    principal: GatewayPrincipal,
) -> str | JSONResponse:
    source_record_key = request.path_params.get("source_record_key", "")
    try:
        return build_resource_urn(
            principal.tenant_id,
            "master_source_record",
            source_record_key,
        )
    except ValueError:
        return _error(
            request,
            400,
            "invalid_master_source_record_key",
            "source_record_key must be a canonical lowercase resource identifier",
        )


def _approval_subject(subject_type: str, subject_id: str) -> str:
    if subject_type not in {"human", "team"} or re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,127}", subject_id
    ) is None:
        raise ValueError("approval subject must be a canonical human or team identity")
    return f"{subject_type}:{subject_id}"


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


async def get_gis_mvt_tile(request: Request) -> Response:
    """Serve an active, release-versioned MVT tile through the control gateway.

    This first route is deliberately operator-only. Consumer policy, cache
    namespace and service-level ConsumerBinding are separate gates and must
    be added before exposing the route as a general data-plane endpoint.
    """

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal

    service_urn = request.query_params.get("service_urn")
    if not service_urn:
        return _error(
            request,
            400,
            "service_urn_required",
            "service_urn query parameter is required",
        )
    try:
        parsed_service = parse_resource_urn(service_urn)
    except ValueError:
        return _error(request, 400, "invalid_service_urn", "service_urn is invalid")
    if (
        parsed_service["tenant_id"] != principal.tenant_id
        or parsed_service["resource_kind"] != "gis_service"
    ):
        return _error(
            request,
            403,
            "service_tenant_mismatch",
            "service_urn does not belong to the authenticated tenant",
        )

    release_key = request.path_params.get("release_key", "")
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release_key) is None:
        return _error(request, 400, "invalid_release_key", "release_key is invalid")
    try:
        z = int(request.path_params["z"])
        x = int(request.path_params["x"])
        y = int(request.path_params["y"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_tile_coordinate", "tile coordinate is invalid")

    try:
        projection = await asyncio.to_thread(
            _gateway().get_gis_service_control_projection,
            principal.tenant_id,
            service_urn,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)

    endpoint = projection.active_endpoint_revision
    deployment = projection.active_deployment_revision
    definition = projection.active_service_definition_version
    release = projection.active_release_binding
    tile_matrix_set = projection.active_tile_matrix_set_definition_version
    if any(value is None for value in (endpoint, deployment, definition, release, tile_matrix_set)):
        return _error(
            request,
            409,
            "gis_service_not_tile_ready",
            "active GIS service projection is incomplete for MVT",
        )
    if release.release_key != release_key:
        return _error(
            request,
            409,
            "active_release_mismatch",
            "requested release_key is not the active release",
        )
    if (
        z < tile_matrix_set.min_zoom
        or z > tile_matrix_set.max_zoom
        or z < 0
        or x < 0
        or y < 0
        or x >= 2**z
        or y >= 2**z
    ):
        return _error(
            request,
            400,
            "invalid_tile_coordinate",
            "tile coordinate is outside the active tile matrix set",
        )
    if endpoint.endpoint_protocol is not EndpointProtocol.MVT:
        return _error(
            request,
            409,
            "endpoint_protocol_mismatch",
            "active endpoint is not an MVT endpoint",
        )
    if definition.service_type is not GISServiceType.VECTOR_TILE:
        return _error(
            request,
            409,
            "service_type_mismatch",
            "active GIS service is not a vector-tile service",
        )
    if deployment.state.value != "ready":
        return _error(
            request,
            409,
            "deployment_not_ready",
            "active GIS deployment is not ready",
        )
    if deployment.provider_system != "martin":
        return _error(
            request,
            409,
            "provider_not_supported",
            "the governed MVT route currently supports Martin only",
        )

    try:
        endpoint_contract = MVTGatewayEndpointContract.model_validate(
            endpoint.endpoint_contract
        )
        context = MVTProviderReleaseContext.from_release(
            release,
            tile_matrix_set,
            service_type=definition.service_type,
            provider_layer_ref=endpoint_contract.provider_layer_ref,
            provider_query=endpoint_contract.provider_query,
        )
        tile = await MartinVectorTileProvider(
            endpoint.endpoint_uri,
            manifest=martin_provider_manifest(),
        ).fetch_tile(context, z, x, y)
    except ValidationError as exc:
        return _error(
            request,
            409,
            "invalid_mvt_endpoint_contract",
            "active endpoint contract is not admissible",
            _validation_details(exc),
        )
    except GISProviderContractError as exc:
        return _error(request, 502, "provider_contract_error", str(exc))
    except GISProviderUnavailable as exc:
        return _error(request, 503, "provider_unavailable", str(exc))

    headers = {
        "Cache-Control": "private, no-store",
        "Vary": "Authorization, Accept-Encoding",
        "X-Content-Type-Options": "nosniff",
        "X-GDA-Service-Release": release.release_key,
        "X-GDA-Endpoint-State-Version": str(projection.endpoint_state_version),
    }
    if tile.etag is not None:
        headers["ETag"] = tile.etag
    return Response(
        tile.content,
        status_code=tile.status_code,
        media_type=tile.media_type,
        headers=headers,
    )


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


async def list_approval_cases(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    raw_status = request.query_params.get("status")
    raw_action = request.query_params.get("action")
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
        status = ApprovalCaseStatus(raw_status) if raw_status else None
        action = (
            _APPROVAL_ACTION_ADAPTER.validate_python(raw_action)
            if raw_action
            else None
        )
    except (TypeError, ValueError, ValidationError):
        return _error(
            request,
            400,
            "invalid_approval_case_query",
            "status, limit, or offset is invalid",
        )
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_approval_case_query",
            "approval case query is outside the supported range",
        )
    try:
        page: ApprovalCasePage = await asyncio.to_thread(
            _approval_case_authority().list,
            principal.tenant_id,
            status=status,
            action=action,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            ApprovalCaseListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
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


async def list_approval_case_notifications(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        notifications = await asyncio.to_thread(
            _approval_case_authority().notifications,
            principal.tenant_id,
            approval_case_ref,
        )
        recoveries = await asyncio.to_thread(
            _approval_case_authority().notification_recoveries,
            principal.tenant_id,
            approval_case_ref,
        )
        return _success(
            request,
            ApprovalCaseNotificationListResponse(
                items=notifications,
                count=len(notifications),
                recoveries=recoveries,
                recovery_count=len(recoveries),
            ),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def get_approval_case_assignment(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        authority = _approval_case_authority()
        current = await asyncio.to_thread(
            authority.assignment,
            principal.tenant_id,
            approval_case_ref,
        )
        events = await asyncio.to_thread(
            authority.assignment_events,
            principal.tenant_id,
            approval_case_ref,
        )
        actor_access = None
        if principal.subject_type is SubjectType.HUMAN:
            actor_access = await asyncio.to_thread(
                authority.assignment_actor_access,
                tenant_id=principal.tenant_id,
                approval_case_ref=approval_case_ref,
                actor_subject=principal.actor_ref,
            )
        return _success(
            request,
            ApprovalCaseAssignmentResponse(
                current=current,
                events=events,
                event_count=len(events),
                actor_access=actor_access,
            ),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def transition_approval_case_assignment(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "ApprovalCase assignment requires a human identity",
        )
    transition = await _parse(request, ApprovalCaseAssignmentRequest)
    if isinstance(transition, JSONResponse):
        return transition
    if (
        transition.operation is not ApprovalCaseAssignmentOperation.DELEGATE
        and principal.role != "admin"
    ):
        return _error(
            request,
            403,
            "approval_assignment_admin_required",
            "ApprovalCase assign, reassign, and release require an administrator",
        )
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    assignee_subject = transition.resolved_assignee_subject
    try:
        assignment = await asyncio.to_thread(
            _approval_case_authority().transition_assignment,
            tenant_id=principal.tenant_id,
            approval_case_ref=approval_case_ref,
            expected_assignment_version=transition.expected_assignment_version,
            operation=transition.operation,
            actor_subject=principal.actor_ref,
            assignee_subject=assignee_subject,
            reason=transition.reason,
        )
        return _success(request, assignment)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "ApprovalCase assignment does not satisfy the platform contract",
            details,
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def list_approval_principals(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    raw_eligible_only = request.query_params.get("eligible_only", "true").lower()
    if raw_eligible_only not in {"true", "false"}:
        return _error(
            request,
            400,
            "invalid_eligible_only",
            "eligible_only must be true or false",
        )
    try:
        items = await asyncio.to_thread(
            _approval_case_authority().list_principals,
            principal.tenant_id,
            eligible_only=raw_eligible_only == "true",
        )
        return _success(
            request,
            ApprovalPrincipalListResponse(items=items, count=len(items)),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def upsert_approval_principal(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin" or principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "approval_directory_admin_required",
            "Approval directory changes require a human administrator",
        )
    update = await _parse(request, ApprovalPrincipalUpsertRequest)
    if isinstance(update, JSONResponse):
        return update
    try:
        principal_type = ApprovalPrincipalType(request.path_params.get("principal_type"))
        principal_subject = _approval_subject(
            principal_type.value,
            request.path_params.get("principal_id", ""),
        )
        stored = await asyncio.to_thread(
            _approval_case_authority().upsert_principal,
            tenant_id=principal.tenant_id,
            principal_subject=principal_subject,
            expected_directory_version=update.expected_directory_version,
            principal_type=principal_type,
            display_name=update.display_name,
            status=update.status,
            approval_eligible=update.approval_eligible,
            availability_status=update.availability_status,
            valid_from=update.valid_from or _utc_now(),
            valid_until=update.valid_until,
            actor_subject=principal.actor_ref,
            reason=update.reason,
        )
        return _success(
            request,
            stored,
            created=update.expected_directory_version == 0,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Approval principal does not satisfy the platform contract",
            details,
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def upsert_approval_team_membership(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin" or principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "approval_directory_admin_required",
            "Approval directory changes require a human administrator",
        )
    update = await _parse(request, ApprovalTeamMembershipUpsertRequest)
    if isinstance(update, JSONResponse):
        return update
    try:
        team_subject = _approval_subject(
            "team", request.path_params.get("team_id", "")
        )
        member_subject = _approval_subject(
            "human", request.path_params.get("member_id", "")
        )
        stored = await asyncio.to_thread(
            _approval_case_authority().upsert_team_membership,
            tenant_id=principal.tenant_id,
            team_subject=team_subject,
            member_subject=member_subject,
            expected_membership_version=update.expected_membership_version,
            status=update.status,
            can_delegate=update.can_delegate,
            valid_from=update.valid_from or _utc_now(),
            valid_until=update.valid_until,
            actor_subject=principal.actor_ref,
            reason=update.reason,
        )
        return _success(
            request,
            stored,
            created=update.expected_membership_version == 0,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Approval team membership does not satisfy the platform contract",
            details,
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def list_approval_team_memberships(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        team_subject = _approval_subject(
            "team", request.path_params.get("team_id", "")
        )
        items = await asyncio.to_thread(
            _approval_case_authority().list_team_memberships,
            principal.tenant_id,
            team_subject,
        )
        return _success(
            request,
            ApprovalTeamMembershipListResponse(items=items, count=len(items)),
        )
    except ValueError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            str(exc),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def retry_approval_case_notification(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "ApprovalCase notification recovery requires a human identity",
        )
    if principal.role != "admin":
        return _error(
            request,
            403,
            "approval_notification_recovery_admin_required",
            "ApprovalCase notification recovery requires an administrator",
        )
    recovery = await _parse(request, ApprovalCaseNotificationRetryRequest)
    if isinstance(recovery, JSONResponse):
        return recovery
    approval_case_ref = _approval_case_ref(request, principal)
    if isinstance(approval_case_ref, JSONResponse):
        return approval_case_ref
    try:
        notification_id = UUID(request.path_params.get("notification_id", ""))
    except ValueError:
        return _error(
            request,
            400,
            "invalid_approval_notification_id",
            "notification_id must be a UUID",
        )
    try:
        notification = await asyncio.to_thread(
            _approval_case_authority().retry_notification,
            tenant_id=principal.tenant_id,
            approval_case_ref=approval_case_ref,
            notification_id=notification_id,
            expected_attempt_count=recovery.expected_attempt_count,
            actor_subject=principal.actor_ref,
            reason=recovery.reason,
        )
        return _success(request, notification)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Notification recovery does not satisfy the platform contract",
            details,
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


async def stage_slo_definition_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, SLODefinitionStageRequest)
    if isinstance(submission, JSONResponse):
        return submission
    definition_ref = _slo_definition_ref(request, principal)
    if isinstance(definition_ref, JSONResponse):
        return definition_ref
    try:
        draft = SLODefinitionDraft(
            tenant_id=principal.tenant_id,
            slo_definition_ref=definition_ref,
            slo_version_ref=f"{definition_ref}.v{submission.version}",
            version=submission.version,
            service_resource_urn=submission.service_resource_urn,
            indicator=submission.indicator,
            objective_basis_points=submission.objective_basis_points,
            objective_window_seconds=submission.objective_window_seconds,
            owner_subject=submission.owner_subject,
            oncall_ref=submission.oncall_ref,
            burn_rate_windows=submission.burn_rate_windows,
            created_by=principal.actor_ref,
            creation_reason=submission.creation_reason,
            created_at=_utc_now(),
        )
        definition = await asyncio.to_thread(_slo_authority().stage, draft)
        return _success(request, definition)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "SLO definition does not satisfy the platform contract",
            _validation_details(exc),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def list_slo_definition_versions(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    definition_ref = _slo_definition_ref(request, principal)
    if isinstance(definition_ref, JSONResponse):
        return definition_ref
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 0, -1
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_slo_version_query",
            "SLO version query is outside the supported range",
        )
    try:
        page: SLODefinitionVersionPage = await asyncio.to_thread(
            _slo_authority().list_versions,
            principal.tenant_id,
            definition_ref,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            SLODefinitionVersionListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def create_slo_activation_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, SLOActivationApprovalRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _slo_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    definition_ref, version_ref = refs
    try:
        definition = await asyncio.to_thread(
            _slo_authority().get,
            principal.tenant_id,
            version_ref,
        )
        requested_at = _utc_now()
        approval_case = ApprovalCase(
            tenant_id=principal.tenant_id,
            approval_case_ref=build_resource_urn(
                principal.tenant_id,
                "approval_case",
                submission.case_id,
            ),
            target_resource_urn=definition.slo_version_ref,
            target_fingerprint=definition.definition_fingerprint,
            action=SLO_ACTIVATION_ACTION,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            request_context={
                "schema": "gda.slo_activation_approval.v1",
                "slo_definition_ref": definition_ref,
                "slo_version_ref": definition.slo_version_ref,
                "definition_fingerprint": definition.definition_fingerprint,
                "service_resource_urn": definition.service_resource_urn,
            },
            requested_at=requested_at,
            expires_at=requested_at + timedelta(hours=submission.expires_in_hours),
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
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "SLO activation approval does not satisfy the platform contract",
            _validation_details(exc),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def activate_slo_definition_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "slo_activation_admin_required",
            "SLO activation requires an administrator",
        )
    submission = await _parse(request, SLODefinitionActivateRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _slo_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    _, version_ref = refs
    try:
        authority = _slo_authority()
        definition = await asyncio.to_thread(
            authority.get,
            principal.tenant_id,
            version_ref,
        )
        approval_case_ref = build_resource_urn(
            principal.tenant_id,
            "approval_case",
            submission.approval_case_id,
        )
        activation = await asyncio.to_thread(
            authority.activate,
            tenant_id=principal.tenant_id,
            slo_version_ref=definition.slo_version_ref,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=approval_case_ref,
            expected_activation_version=submission.expected_activation_version,
            actor_subject=principal.actor_ref,
            reason=submission.reason,
        )
        return _success(request, activation)
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def get_active_slo_definition(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    definition_ref = _slo_definition_ref(request, principal)
    if isinstance(definition_ref, JSONResponse):
        return definition_ref
    try:
        definition, activation = await asyncio.to_thread(
            _slo_authority().active,
            principal.tenant_id,
            definition_ref,
        )
        return _success(
            request,
            SLOActiveDefinitionResponse(
                definition=definition,
                activation=activation,
            ),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def preview_slo_prometheus_rules(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    refs = _slo_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    definition_ref, version_ref = refs
    try:
        authority = _slo_authority()
        definition = await asyncio.to_thread(
            authority.get,
            principal.tenant_id,
            version_ref,
        )
        _, activation = await asyncio.to_thread(
            authority.active,
            principal.tenant_id,
            definition_ref,
        )
        prometheus_rules = compile_slo_prometheus_rules(definition, activation)
        return _success(
            request,
            SLOPrometheusRulePreviewResponse(
                definition=definition,
                activation=activation,
                prometheus_rules=prometheus_rules,
            ),
        )
    except SLOCompilationError as exc:
        return _error(
            request,
            409,
            "slo_version_not_active",
            str(exc),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def list_slo_definition_events(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    definition_ref = _slo_definition_ref(request, principal)
    if isinstance(definition_ref, JSONResponse):
        return definition_ref
    try:
        events = await asyncio.to_thread(
            _slo_authority().events,
            principal.tenant_id,
            definition_ref,
        )
        return _success(
            request,
            SLODefinitionEventListResponse(items=events, count=len(events)),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)


async def observe_master_source_record(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MasterSourceObservationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    source_record_key = uuid5(
        NAMESPACE_URL,
        "|".join(
            (
                principal.tenant_id,
                submission.source_system_ref,
                submission.source_record_id,
                submission.source_revision,
            )
        ),
    ).hex
    try:
        draft = MasterSourceRecordDraft(
            tenant_id=principal.tenant_id,
            source_record_ref=build_resource_urn(
                principal.tenant_id,
                "master_source_record",
                source_record_key,
            ),
            domain=submission.domain,
            source_system_ref=submission.source_system_ref,
            source_record_id=submission.source_record_id,
            source_revision=submission.source_revision,
            business_key=submission.business_key,
            display_name=submission.display_name,
            parent_business_key=submission.parent_business_key,
            attributes=submission.attributes,
            observed_by=principal.actor_ref,
            observed_at=_utc_now(),
        )
        record = await asyncio.to_thread(_master_data_authority().observe, draft)
        return _success(request, record)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Master source observation does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def propose_master_source_matches(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type not in {SubjectType.WORKLOAD, SubjectType.AGENT}:
        return _error(
            request,
            403,
            "master_match_machine_identity_required",
            "Master match proposals require a workload or agent identity",
        )
    submission = await _parse(request, MasterMatchRequest)
    if isinstance(submission, JSONResponse):
        return submission
    source_record_ref = _master_source_record_ref(request, principal)
    if isinstance(source_record_ref, JSONResponse):
        return source_record_ref
    try:
        result: MasterMatchResult = await asyncio.to_thread(
            _master_data_authority().match,
            principal.tenant_id,
            source_record_ref,
            proposed_by=principal.actor_ref,
            proposed_at=_utc_now(),
            limit=submission.limit,
        )
        return _success(request, result)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Master match request does not satisfy the platform contract",
            details,
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def stage_master_entity_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MasterEntityVersionStageRequest)
    if isinstance(submission, JSONResponse):
        return submission
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        draft = MasterEntityVersionDraft(
            tenant_id=principal.tenant_id,
            entity_ref=entity_ref,
            entity_version_ref=f"{entity_ref}.v{submission.version}",
            version=submission.version,
            domain=submission.domain,
            business_key=submission.business_key,
            canonical_name=submission.canonical_name,
            parent_entity_ref=submission.parent_entity_ref,
            attributes=submission.attributes,
            source_record_refs=submission.source_record_refs,
            match_candidate_refs=submission.match_candidate_refs,
            valid_from=submission.valid_from,
            valid_to=submission.valid_to,
            owner_subject=submission.owner_subject,
            created_by=principal.actor_ref,
            creation_reason=submission.creation_reason,
            created_at=_utc_now(),
        )
        version = await asyncio.to_thread(_master_data_authority().stage, draft)
        return _success(request, version)
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Master entity version does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def list_master_entity_versions(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 0, -1
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_master_version_query",
            "Master version query is outside the supported range",
        )
    try:
        page: MasterEntityVersionPage = await asyncio.to_thread(
            _master_data_authority().list_versions,
            principal.tenant_id,
            entity_ref,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            MasterEntityVersionListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def create_master_activation_approval_case(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, MasterActivationApprovalRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _master_entity_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    entity_ref, version_ref = refs
    try:
        version = await asyncio.to_thread(
            _master_data_authority().get,
            principal.tenant_id,
            version_ref,
        )
        requested_at = _utc_now()
        approval_case = ApprovalCase(
            tenant_id=principal.tenant_id,
            approval_case_ref=build_resource_urn(
                principal.tenant_id,
                "approval_case",
                submission.case_id,
            ),
            target_resource_urn=version.entity_version_ref,
            target_fingerprint=version.entity_fingerprint,
            action=MASTER_DATA_ACTIVATION_ACTION,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            request_context={
                "schema": "gda.master_entity_activation_approval.v1",
                "entity_ref": entity_ref,
                "entity_version_ref": version.entity_version_ref,
                "entity_fingerprint": version.entity_fingerprint,
                "domain": version.domain.value,
                "business_key": version.business_key,
                "source_record_refs": list(version.source_record_refs),
                "match_candidate_refs": list(version.match_candidate_refs),
            },
            requested_at=requested_at,
            expires_at=requested_at + timedelta(hours=submission.expires_in_hours),
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
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Master activation approval does not satisfy the platform contract",
            _validation_details(exc),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def activate_master_entity_version(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "master_activation_admin_required",
            "Master entity activation requires an administrator",
        )
    submission = await _parse(request, MasterEntityActivateRequest)
    if isinstance(submission, JSONResponse):
        return submission
    refs = _master_entity_version_refs(request, principal)
    if isinstance(refs, JSONResponse):
        return refs
    _, version_ref = refs
    try:
        authority = _master_data_authority()
        version = await asyncio.to_thread(
            authority.get,
            principal.tenant_id,
            version_ref,
        )
        activation = await asyncio.to_thread(
            authority.activate,
            tenant_id=principal.tenant_id,
            entity_version_ref=version.entity_version_ref,
            entity_fingerprint=version.entity_fingerprint,
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
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def get_active_master_entity(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        entity, activation = await asyncio.to_thread(
            _master_data_authority().active,
            principal.tenant_id,
            entity_ref,
        )
        return _success(
            request,
            MasterActiveEntityResponse(entity=entity, activation=activation),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def list_master_data_events(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        events = await asyncio.to_thread(
            _master_data_authority().events,
            principal.tenant_id,
            entity_ref,
        )
        return _success(
            request,
            MasterDataEventListResponse(items=events, count=len(events)),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def list_master_resource_projections(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    entity_ref = _master_entity_ref(request, principal)
    if isinstance(entity_ref, JSONResponse):
        return entity_ref
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        limit, offset = 0, -1
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_master_resource_projection_query",
            "Master resource projection query is outside the supported range",
        )
    try:
        page: MasterResourceProjectionPage = await asyncio.to_thread(
            _master_data_authority().resource_projections,
            principal.tenant_id,
            entity_ref,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            MasterResourceProjectionListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
    except MasterDataAuthorityError as exc:
        return _master_data_error(request, exc)


async def reconcile_slo_alertmanager_webhook(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "slo_alert_workload_required",
            "SLO alert reconciliation requires a workload identity",
        )
    webhook = await _parse(request, AlertmanagerSLOWebhook)
    if isinstance(webhook, JSONResponse):
        return webhook
    try:
        detector_subject = _slo_alert_detector_subject()
        if principal.actor_ref != detector_subject:
            return _error(
                request,
                403,
                "slo_alert_detector_mismatch",
                "Authenticated workload is not the configured SLO alert detector",
            )
        result: SLOAlertReconciliationResult = await asyncio.to_thread(
            _slo_incident_reconciler().reconcile,
            principal.tenant_id,
            webhook,
            detector_subject=detector_subject,
        )
        return _success(request, result)
    except SLOIncidentValidationError as exc:
        return _error(request, 422, exc.code, str(exc))
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)
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


async def list_resource_versions(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        return _error(
            request,
            400,
            "invalid_resource_version_query",
            "limit or offset is invalid",
        )
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_resource_version_query",
            "limit or offset is outside the supported range",
        )
    try:
        page = await asyncio.to_thread(
            _gateway().list_resource_versions,
            principal.tenant_id,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            ResourceVersionListResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
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
    contract_error = _capability_contract_guard(
        request,
        DATAOPS_MANUAL_RUN_SUBMIT,
    )
    if contract_error is not None:
        return contract_error
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
    contract_error = _capability_contract_guard(request, DATAOPS_RUN_CANCEL)
    if contract_error is not None:
        return contract_error
    try:
        run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    body = await _parse(request, DataOpsCancelHttpBody)
    if isinstance(body, JSONResponse):
        return body
    try:
        cancellation = DataOpsCancelRequest(
            run_id=run_id,
            **body.model_dump(mode="python"),
        )
        profile = _cancel_runtime_profile()
        spec = DataOpsCancelSpec(
            tenant_id=principal.tenant_id,
            run_id=cancellation.run_id,
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


async def get_postgresql_cdc_recovery_observation(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        artifact_id = UUID(request.path_params["artifact_id"])
    except (KeyError, ValueError):
        return _error(
            request,
            400,
            "invalid_artifact_id",
            "artifact_id must be a UUID",
        )
    try:
        observation = await asyncio.to_thread(
            _gateway().get_postgresql_cdc_recovery_observation,
            principal.tenant_id,
            artifact_id,
        )
        return _success(request, observation)
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


async def get_resource_version_architecture(request: Request) -> JSONResponse:
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
        architecture = await asyncio.to_thread(
            _gateway().get_resource_version_architecture,
            principal.tenant_id,
            resource_version_id,
        )
        return _success(request, architecture)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_resource_version_architecture_reconciliation(
    request: Request,
) -> JSONResponse:
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
        reconciliation = await asyncio.to_thread(
            _gateway().reconcile_resource_version_architecture,
            principal.tenant_id,
            resource_version_id,
        )
        return _success(request, reconciliation)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_resource_version_architecture_review(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, ArchitectureChangeReviewRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        resource_version_id = UUID(request.path_params["resource_version_id"])
    except (KeyError, ValueError):
        return _error(
            request,
            400,
            "invalid_resource_version_id",
            "resource_version_id must be a UUID",
        )
    requested_at = _utc_now()
    try:
        result = await asyncio.to_thread(
            _architecture_change_approval_service().request_review,
            tenant_id=principal.tenant_id,
            resource_version_id=resource_version_id,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
            requested_at=requested_at,
            expires_at=requested_at + timedelta(hours=submission.expires_in_hours),
        )
        return _success(
            request,
            ArchitectureChangeReviewResponse(
                reconciliation=result.reconciliation,
                review=result.review,
                approval_case=result.approval_case,
            ),
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ArchitectureChangeApprovalError as exc:
        return _error(
            request,
            422,
            "architecture_change_not_reviewable",
            str(exc),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "architecture_change_review_invalid",
            "Architecture change review does not satisfy the platform contract",
            details,
        )


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
            f"{base}/approval-principals",
            list_approval_principals,
            method="GET",
            operation_id="platform_list_approval_principals",
        ),
        _platform_route(
            f"{base}/approval-principals/{{principal_type}}/{{principal_id}}",
            upsert_approval_principal,
            method="PUT",
            operation_id="platform_upsert_approval_principal",
        ),
        _platform_route(
            f"{base}/approval-teams/{{team_id}}/members/{{member_id}}",
            upsert_approval_team_membership,
            method="PUT",
            operation_id="platform_upsert_approval_team_membership",
        ),
        _platform_route(
            f"{base}/approval-teams/{{team_id}}/members",
            list_approval_team_memberships,
            method="GET",
            operation_id="platform_list_approval_team_memberships",
        ),
        _platform_route(
            f"{base}/approval-cases",
            create_approval_case,
            method="POST",
            operation_id="platform_create_approval_case",
        ),
        _platform_route(
            f"{base}/approval-cases",
            list_approval_cases,
            method="GET",
            operation_id="platform_list_approval_cases",
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
            f"{base}/approval-cases/{{case_id}}/notifications",
            list_approval_case_notifications,
            method="GET",
            operation_id="platform_list_approval_case_notifications",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/assignment",
            get_approval_case_assignment,
            method="GET",
            operation_id="platform_get_approval_case_assignment",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/assignment",
            transition_approval_case_assignment,
            method="POST",
            operation_id="platform_transition_approval_case_assignment",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/notifications/{{notification_id}}/retry",
            retry_approval_case_notification,
            method="POST",
            operation_id="platform_retry_approval_case_notification",
        ),
        _platform_route(
            f"{base}/approval-cases/{{case_id}}/decision",
            decide_approval_case,
            method="POST",
            operation_id="platform_decide_approval_case",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/versions",
            stage_slo_definition_version,
            method="POST",
            operation_id="platform_stage_slo_definition_version",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/versions",
            list_slo_definition_versions,
            method="GET",
            operation_id="platform_list_slo_definition_versions",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/versions/{{version}}/approval-cases",
            create_slo_activation_approval_case,
            method="POST",
            operation_id="platform_create_slo_activation_approval_case",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/versions/{{version}}/activation",
            activate_slo_definition_version,
            method="POST",
            operation_id="platform_activate_slo_definition_version",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/active",
            get_active_slo_definition,
            method="GET",
            operation_id="platform_get_active_slo_definition",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/versions/{{version}}/prometheus-rules",
            preview_slo_prometheus_rules,
            method="GET",
            operation_id="platform_preview_slo_prometheus_rules",
        ),
        _platform_route(
            f"{base}/slo-definitions/{{slo_definition_id}}/events",
            list_slo_definition_events,
            method="GET",
            operation_id="platform_list_slo_definition_events",
        ),
        _platform_route(
            f"{base}/slo-alerts/alertmanager",
            reconcile_slo_alertmanager_webhook,
            method="POST",
            operation_id="platform_reconcile_slo_alertmanager_webhook",
        ),
        _platform_route(
            f"{base}/master-data/source-records",
            observe_master_source_record,
            method="POST",
            operation_id="platform_observe_master_source_record",
        ),
        _platform_route(
            f"{base}/master-data/source-records/{{source_record_key}}/match-candidates",
            propose_master_source_matches,
            method="POST",
            operation_id="platform_propose_master_source_matches",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/versions",
            stage_master_entity_version,
            method="POST",
            operation_id="platform_stage_master_entity_version",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/versions",
            list_master_entity_versions,
            method="GET",
            operation_id="platform_list_master_entity_versions",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/versions/{{version}}/approval-cases",
            create_master_activation_approval_case,
            method="POST",
            operation_id="platform_create_master_activation_approval_case",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/versions/{{version}}/activation",
            activate_master_entity_version,
            method="POST",
            operation_id="platform_activate_master_entity_version",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/active",
            get_active_master_entity,
            method="GET",
            operation_id="platform_get_active_master_entity",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/events",
            list_master_data_events,
            method="GET",
            operation_id="platform_list_master_data_events",
        ),
        _platform_route(
            f"{base}/master-data/entities/{{entity_id}}/resource-projections",
            list_master_resource_projections,
            method="GET",
            operation_id="platform_list_master_resource_projections",
        ),
        _platform_route(
            f"{base}/resource-versions",
            create_resource_version,
            method="POST",
            operation_id="platform_create_resource_version",
        ),
        _platform_route(
            f"{base}/resource-versions",
            list_resource_versions,
            method="GET",
            operation_id="platform_list_resource_versions",
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
            f"{base}/recovery-observations/{{artifact_id}}",
            get_postgresql_cdc_recovery_observation,
            method="GET",
            operation_id="platform_get_postgresql_cdc_recovery_observation",
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
            f"{base}/resource-versions/{{resource_version_id}}/architecture",
            get_resource_version_architecture,
            method="GET",
            operation_id="platform_get_resource_version_architecture",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/architecture/reconciliation",
            get_resource_version_architecture_reconciliation,
            method="GET",
            operation_id="platform_get_resource_version_architecture_reconciliation",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/architecture/reconciliation/approval-cases",
            create_resource_version_architecture_review,
            method="POST",
            operation_id="platform_create_resource_version_architecture_review",
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
        _platform_route(
            f"{base}/gis/tiles/{{release_key}}/{{z:int}}/{{x:int}}/{{y:int}}.pbf",
            get_gis_mvt_tile,
            method="GET",
            operation_id="platform_get_gis_mvt_tile",
        ),
    ]
