"""Versioned REST boundary for the AR-1 platform control gateway."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
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
from ..approval_case_batch import (
    ApprovalCaseBatchEscalationRequest,
    execute_approval_case_batch_escalation,
)
from ..architecture_change_approval import (
    ArchitectureChangeApprovalError,
    ArchitectureChangeApprovalService,
    ArchitectureChangeReview,
)
from ..architecture_change_assessment import (
    ArchitectureChangeAssessmentError,
    ArchitectureChangeAssessmentService,
    AssessedArchitectureChangeReview,
)
from ..architecture_successor_adoption import (
    ArchitectureSuccessorAdoptionError,
    ArchitectureSuccessorAdoptionService,
    ArchitectureSuccessorPlan,
)
from ..architecture_successor_data_product_release import (
    ArchitectureSuccessorDataProductReleaseError,
    ArchitectureSuccessorDataProductReleasePlan,
    ArchitectureSuccessorDataProductReleaseService,
)
from ..capability_registry import (
    APPROVAL_CASE_BATCH_ESCALATION,
    CAPABILITY_FINGERPRINT_HEADER,
    CHONGQING_DATA_PACKAGE_RECONCILE,
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL,
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET,
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT,
    DATAOPS_MANUAL_RUN_SUBMIT,
    DATAOPS_RUN_CANCEL,
    ENTITY_AUTHORITY_BATCH_INGEST,
    ENTITY_LINEAGE_RECORD,
    FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST,
    FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST,
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET,
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ,
    FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS,
    FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS,
    FEDERATED_PROJECTION_COMPENSATION_RULE_GET,
    LAKEHOUSE_PROJECTION_REPAIR_EXECUTE,
    OBJECT_PROJECTION_REPAIR_EXECUTE,
    POSTGIS_PROJECTION_REPAIR_EXECUTE,
    RDF_PROJECTION_REPAIR_EXECUTE,
    VECTOR_PROJECTION_REPAIR_EXECUTE,
    CapabilityFingerprintMismatchError,
    CapabilitySpec,
)
from ..chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationError,
)
from ..chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJobCancelRequest,
    ChongqingDataPackageReconciliationJobConfigurationError,
    ChongqingDataPackageReconciliationJobError,
    ChongqingDataPackageReconciliationJobForbiddenError,
    ChongqingDataPackageReconciliationJobNotFoundError,
    ChongqingDataPackageReconciliationJobQuery,
    ChongqingDataPackageReconciliationJobValidationError,
    cancel_chongqing_data_package_reconciliation_job,
    get_chongqing_data_package_reconciliation_job,
    submit_chongqing_data_package_reconciliation_job,
)
from ..chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationServiceConfigurationError,
    ChongqingDataPackageReconciliationServiceConflictError,
    ChongqingDataPackageReconciliationServiceError,
    ChongqingDataPackageReconciliationServiceForbiddenError,
    ChongqingDataPackageReconciliationServiceValidationError,
    execute_chongqing_data_package_reconciliation,
)
from ..cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalCaseRequest,
    FederatedProjectionCompensationApprovalError,
    FederatedProjectionCompensationApprovalNotFoundError,
    FederatedProjectionCompensationApprovalService,
    FederatedProjectionCompensationExecutionApprovalRequest,
    FederatedProjectionCompensationExecutionApprovalService,
)
from ..cross_store_projection_compensation_proposal import (
    FederatedProjectionCompensationProposalError,
    FederatedProjectionCompensationProposalReadRequest,
    FederatedProjectionCompensationProposalRequest,
    build_federated_projection_compensation_proposal,
)
from ..cross_store_projection_compensation_proposal_authority import (
    FederatedProjectionCompensationProposalAuthorityError,
    FederatedProjectionCompensationProposalConfigurationError,
    FederatedProjectionCompensationProposalForbiddenError,
    FederatedProjectionCompensationProposalValidationError,
    PostgresFederatedProjectionCompensationProposalStore,
)
from ..cross_store_projection_compensation_rule_authority import (
    CustomerCompensationRuleAuthorityConfigurationError,
    CustomerCompensationRuleAuthorityError,
    CustomerCompensationRuleAuthorityForbiddenError,
    CustomerCompensationRuleAuthorityValidationError,
    PostgresCustomerCompensationRuleAuthorityStore,
)
from ..cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAuthorityReadRequest,
    CustomerCompensationRuleError,
    FederatedProjectionCompensationRuleAssessmentRequest,
    FederatedProjectionCompensationRuleAuthorityAssessmentRequest,
)
from ..cross_store_projection_compensation_rule_contract import (
    assess_federated_projection_compensation_rules as assess_customer_compensation_rules,
)
from ..cross_store_projection_compensation_trust import (
    CustomerCompensationApprovalTrustConfigurationError,
    load_customer_compensation_approval_trust_registry,
)
from ..data_architecture_ledger import (
    DataArchitectureRegistration,
    ResourceVersionArchitectureReconciliation,
)
from ..data_product_blueprint import (
    DataProductBlueprint,
    DataProductBlueprintProviderCancellationTimeoutRequest,
    DataProductBlueprintProviderReconcileRequest,
    DataProductBlueprintProviderRetryRequest,
    DataProductBlueprintReleaseBinding,
    DataProductBlueprintReview,
    DataProductBlueprintTestCancellationRequest,
    DataProductBlueprintTestExecutionFailureRequest,
    DataProductBlueprintTestExecutionRequest,
    DataProductBlueprintTestRunRequest,
    build_data_product_blueprint_approval_case,
    build_data_product_blueprint_preview,
    build_data_product_blueprint_test_report,
    compile_data_product_blueprint,
)
from ..data_product_registry import (
    DataProductConflictError,
    DataProductNotFoundError,
    DataProductRegistry,
    DataProductRegistryError,
    DataProductSpec,
    DataProductVersionSpec,
)
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
from ..duckdb_blueprint_provider import DuckDBBlueprintExecutionRequest
from ..entity_authority_batch import (
    EntityAuthorityBatchRequest,
    execute_entity_authority_batch,
)
from ..entity_lineage_authority import (
    EntityLineageAuthority,
    EntityLineageAuthorityError,
    EntityLineageConfigurationError,
    EntityLineageConflictError,
    EntityLineageForbiddenError,
    EntityLineageNotFoundError,
    EntityLineageRequest,
    EntityLineageValidationError,
)
from ..entity_link_authority import (
    EntityLinkAuthorityError,
    EntityLinkConfigurationError,
    EntityLinkConflictError,
    EntityLinkForbiddenError,
    EntityLinkNotFoundError,
    EntityLinkValidationError,
)
from ..gis_mvt_access import (
    GOVERNED_MVT_ACCESS_PURPOSE,
    MVTAccessDeniedError,
    MVTAccessService,
    MVTAccessUnavailableError,
)
from ..gis_mvt_response_cache import (
    MVTResponseCache,
    MVTResponseCacheEntry,
    get_mvt_response_cache,
    mvt_response_cache_key,
    mvt_response_cache_namespace,
)
from ..gis_ogc_api_features_access import (
    GOVERNED_OGC_FEATURES_ACCESS_ACTION,
    GOVERNED_OGC_FEATURES_ACCESS_PURPOSE,
    OGCFeaturesAccessDeniedError,
    OGCFeaturesAccessService,
    OGCFeaturesAccessUnavailableError,
)
from ..gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    OGCAPIFeaturesProvider,
    OGCAPIFeaturesReleaseContext,
    ProviderTileResponse,
    martin_provider_manifest,
    pygeoapi_provider_manifest,
)
from ..gis_service_control_plane import (
    EndpointProtocol,
    EndpointRevision,
    GISServiceSLOBinding,
    GISServiceType,
    ServiceDeploymentEvent,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    endpoint_revision_fingerprint,
    service_deployment_fingerprint,
)
from ..lakehouse_projection_service import (
    LakehouseProjectionRepairRequest,
    LakehouseProjectionServiceConfigurationError,
    LakehouseProjectionServiceConflictError,
    LakehouseProjectionServiceError,
    LakehouseProjectionServiceForbiddenError,
    LakehouseProjectionServiceValidationError,
    execute_lakehouse_projection_repair,
)
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
from ..metadata_provider_read import (
    MetadataProviderReadError,
    MetadataProviderReadService,
    ProviderReadResult,
)
from ..metadata_provider_search import (
    MetadataProviderSearchService,
    ProviderSearchPage,
)
from ..object_projection_service import (
    ObjectProjectionRepairRequest,
    ObjectProjectionServiceConfigurationError,
    ObjectProjectionServiceConflictError,
    ObjectProjectionServiceError,
    ObjectProjectionServiceForbiddenError,
    ObjectProjectionServiceValidationError,
    execute_object_projection_repair,
)
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
    FrameworkKind,
    IncidentNotification,
    IncidentNotificationRecoveryEvent,
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
    MetadataFabricBindingPage,
    PlatformGateway,
    PlatformGatewayError,
)
from ..platform_lineage import (
    ImpactChangeType,
    LineageImpactAssessment,
    LineageQuerySpec,
)
from ..platform_openlineage import (
    OpenLineageIngestionItem,
    OpenLineageIngestionResult,
    OpenLineageRunEvent,
    openlineage_to_lineage_events,
)
from ..postgis_projection_service import (
    PostGISProjectionRepairRequest,
    PostGISProjectionServiceConfigurationError,
    PostGISProjectionServiceConflictError,
    PostGISProjectionServiceError,
    PostGISProjectionServiceForbiddenError,
    PostGISProjectionServiceValidationError,
    execute_postgis_projection_repair,
)
from ..postgis_schema_evidence import (
    PostgisSchemaCompatibilityAssessment,
    PostgisSchemaSnapshot,
)
from ..rdf_projection_service import (
    RDFProjectionRepairRequest,
    RDFProjectionServiceConfigurationError,
    RDFProjectionServiceConflictError,
    RDFProjectionServiceError,
    RDFProjectionServiceForbiddenError,
    RDFProjectionServiceValidationError,
    execute_rdf_projection_repair,
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
from ..temporal_entity_authority import (
    TemporalEntityAuthorityError,
    TemporalEntityConfigurationError,
    TemporalEntityConflictError,
    TemporalEntityForbiddenError,
    TemporalEntityNotFoundError,
    TemporalEntityValidationError,
)
from ..vector_projection_service import (
    VectorProjectionRepairRequest,
    VectorProjectionServiceConfigurationError,
    VectorProjectionServiceConflictError,
    VectorProjectionServiceError,
    VectorProjectionServiceForbiddenError,
    VectorProjectionServiceValidationError,
    execute_vector_projection_repair,
)
from .helpers import _get_user_from_request

_TENANT_ADAPTER = TypeAdapter(TenantId)
_APPROVAL_ACTION_ADAPTER = TypeAdapter(ShortName)
_PLATFORM_ROLES = frozenset({"admin", "platform_operator"})
_GIS_CONSUMER_ROLES = frozenset(
    {"viewer", "analyst", "standard_editor", "standard_reviewer"}
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MVTGatewayEndpointContract(StrictRequest):
    """Provider placement contract consumed by the governed tile route."""

    contract_schema: Literal["gda.mvt_endpoint.v1"] = Field(alias="schema")
    provider_layer_ref: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
    provider_query: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def _governed_serving_projection_query(self) -> MVTGatewayEndpointContract:
        if self.provider_layer_ref != "gda_mvt_serving_projection":
            raise ValueError("MVT provider_layer_ref must be the governed serving projection")
        projection_id = self.provider_query.get("serving_projection_version_id")
        if projection_id is None or len(self.provider_query) != 1:
            raise ValueError("MVT provider_query must bind only serving_projection_version_id")
        try:
            UUID(projection_id)
        except ValueError as exc:
            raise ValueError("MVT serving_projection_version_id must be a UUID") from exc
        return self


class OGCAPIFeaturesGatewayEndpointContract(StrictRequest):
    """Release-bound collection identity consumed by the Features route."""

    contract_schema: Literal["gda.ogc_api_features_endpoint.v1"] = Field(alias="schema")
    collection_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class GISServiceEndpointActivationRequest(StrictRequest):
    """One immutable, compare-and-swap update to a GIS service endpoint pointer."""

    endpoint_revision_id: UUID
    expected_state_version: int = Field(ge=0)
    reason: NonEmptyText
    idempotency_key: NonEmptyText
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


class GISServiceDeploymentTransitionRequest(StrictRequest):
    """One immutable transition in the governed GIS deployment state machine."""

    expected_state_version: int = Field(ge=0)
    to_state: ServiceDeploymentState
    provider_observation_id: UUID | None = None
    reason: NonEmptyText
    idempotency_key: NonEmptyText
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _observation_matches_target_state(self) -> GISServiceDeploymentTransitionRequest:
        if self.to_state is ServiceDeploymentState.PLANNED:
            raise ValueError("a deployment cannot transition to planned")
        terminal = self.to_state in {
            ServiceDeploymentState.READY,
            ServiceDeploymentState.FAILED,
        }
        if terminal != (self.provider_observation_id is not None):
            raise ValueError(
                "ready or failed requires provider_observation_id; deploying forbids it"
            )
        return self


class GISServiceEndpointRegistrationRequest(StrictRequest):
    """Immutable endpoint metadata produced after a deployment is ready."""

    endpoint_revision_id: UUID
    endpoint_protocol: EndpointProtocol
    endpoint_uri: str = Field(min_length=1, max_length=2048)
    endpoint_contract: dict[str, Any]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)


class GISServiceDeploymentRegistrationRequest(StrictRequest):
    """An immutable, planned placement of one atomic GIS service release."""

    deployment_revision_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    run_id: UUID
    revision_key: str = Field(pattern=r"^r[0-9]+$")
    provider_system: str = Field(
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$"
    )
    provider_namespace: str = Field(min_length=1, max_length=512)
    provider_deployment_id: str = Field(min_length=1, max_length=512)
    provider_revision_ref: str = Field(min_length=1, max_length=512)
    config_sha256: Sha256
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)


class GISServiceDeploymentObservationRequest(StrictRequest):
    """Terminal provider evidence with server-owned GIS deployment bindings."""

    observation_id: UUID
    attempt_no: int = Field(ge=1)
    framework_kind: FrameworkKind
    observed_state: Literal[
        "success",
        "succeeded",
        "ready",
        "completed",
        "failed",
        "error",
        "cancelled",
        "timed_out",
    ]
    provider_version: NonEmptyText
    endpoint_uri: str = Field(min_length=1, max_length=2048)
    health_evidence_sha256: Sha256
    provider_receipt: dict[str, Any] = Field(min_length=1)
    observed_at: datetime

    @field_validator("endpoint_uri")
    @classmethod
    def _stable_endpoint_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint_uri must be a credential-free HTTPS URI")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)


class GISServiceDeploymentTerminalSettlementRequest(
    GISServiceDeploymentObservationRequest
):
    """Provider terminal evidence and deployment transition settled atomically."""

    expected_state_version: int = Field(ge=0)
    reason: NonEmptyText
    idempotency_key: NonEmptyText
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _settlement_follows_observation(
        self,
    ) -> GISServiceDeploymentTerminalSettlementRequest:
        if self.occurred_at < self.observed_at:
            raise ValueError("occurred_at cannot precede observed_at")
        return self


class GISServiceDeploymentEventListResponse(StrictRequest):
    """Immutable deployment lifecycle evidence, ordered by transition sequence."""

    items: tuple[ServiceDeploymentEvent, ...]
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_count(self) -> GISServiceDeploymentEventListResponse:
        if self.count != len(self.items):
            raise ValueError("count must equal the number of deployment events")
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


class IncidentNotificationListResponse(StrictRequest):
    items: tuple[IncidentNotification, ...]
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_count(self) -> IncidentNotificationListResponse:
        if self.count != len(self.items):
            raise ValueError("count must equal the number of notifications")
        return self


class IncidentNotificationRecoveryListResponse(StrictRequest):
    items: tuple[IncidentNotificationRecoveryEvent, ...]
    recovery_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_count(self) -> IncidentNotificationRecoveryListResponse:
        if self.recovery_count != len(self.items):
            raise ValueError("recovery_count must equal the number of recovery events")
        return self


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


class ArchitectureChangeAssessmentRequest(StrictRequest):
    """Evidence references and bounded traversal limits for a schema-drift review."""

    baseline_schema_snapshot: PostgisSchemaSnapshot
    candidate_schema_snapshot: PostgisSchemaSnapshot
    baseline_schema_artifact_id: UUID
    candidate_schema_artifact_id: UUID
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)
    max_lineage_depth: int = Field(default=6, ge=1, le=12)
    max_lineage_edges: int = Field(default=500, ge=1, le=1000)


class ArchitectureChangeAssessmentResponse(StrictRequest):
    base_review: ArchitectureChangeReview
    compatibility: PostgisSchemaCompatibilityAssessment
    impact: LineageImpactAssessment
    review: AssessedArchitectureChangeReview
    approval_case: ApprovalCase


class ArchitectureSuccessorAdoptionApprovalRequest(StrictRequest):
    """Submit one evidence-bound successor plan for an independent decision."""

    assessed_approval_case_ref: ResourceURNText
    successor_resource_version: ResourceVersion
    successor_architecture: DataArchitectureRegistration
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class ArchitectureSuccessorAdoptionApprovalResponse(StrictRequest):
    plan: ArchitectureSuccessorPlan
    approval_case: ApprovalCase


class ArchitectureSuccessorAdoptionExecuteRequest(StrictRequest):
    """Execute the exact successor plan bound by an approved AdoptionCase."""

    plan: ArchitectureSuccessorPlan
    adoption_approval_case_ref: ResourceURNText


class ArchitectureSuccessorDataProductReleaseApprovalRequest(StrictRequest):
    """Request publication approval for one adopted successor product version."""

    plan: ArchitectureSuccessorDataProductReleasePlan
    request_reason: NonEmptyText
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class ArchitectureSuccessorDataProductReleaseApprovalResponse(StrictRequest):
    plan: ArchitectureSuccessorDataProductReleasePlan
    approval_case: ApprovalCase


class ArchitectureSuccessorDataProductReleasePublishRequest(StrictRequest):
    """Publish the exact DataProduct release plan bound by a Release ApprovalCase."""

    plan: ArchitectureSuccessorDataProductReleasePlan
    release_approval_case_ref: ResourceURNText
    idempotency_key: NonEmptyText
    reason: NonEmptyText


class ArchitectureSuccessorDataProductReleasePublishResponse(StrictRequest):
    plan: ArchitectureSuccessorDataProductReleasePlan
    publication: dict[str, Any]


class DataProductBlueprintReleasePublishRequest(StrictRequest):
    """Publish one immutable Blueprint release through the product authority."""

    product: DataProductSpec
    version: DataProductVersionSpec
    blueprint_release_binding: DataProductBlueprintReleaseBinding
    idempotency_key: NonEmptyText
    reason: NonEmptyText

    @model_validator(mode="after")
    def _manifest_binding_matches(
        self,
    ) -> DataProductBlueprintReleasePublishRequest:
        manifest_binding = self.version.distribution_manifest.get("blueprint_release")
        if manifest_binding is None:
            raise ValueError(
                "version distribution_manifest must include blueprint_release"
            )
        if canonical_json_fingerprint(manifest_binding) != canonical_json_fingerprint(
            self.blueprint_release_binding.model_dump(mode="json", by_alias=True)
        ):
            raise ValueError(
                "blueprint_release_binding must match version distribution_manifest"
            )
        if (
            self.product.tenant_id != self.version.tenant_id
            or self.product.product_urn != self.version.product_urn
        ):
            raise ValueError("product and version identities must match")
        if self.blueprint_release_binding.tenant_id != self.product.tenant_id:
            raise ValueError("Blueprint release tenant must match product tenant")
        return self


class DataProductBlueprintReleasePublishResponse(StrictRequest):
    product: DataProductSpec
    version: DataProductVersionSpec
    blueprint_release_binding: DataProductBlueprintReleaseBinding
    publication: dict[str, Any]


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


class GISServiceSLOBindingRequest(StrictRequest):
    """Bind a service to the exact currently active generic SLO version."""

    slo_definition_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    version: int = Field(ge=1, le=1_000_000)
    expected_activation_version: int = Field(ge=1)
    reason: NonEmptyText


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


class IncidentNotificationRecoveryRequest(StrictRequest):
    expected_attempt_count: int = Field(ge=1)
    expected_receipt_sha256: Sha256
    reason: NonEmptyText


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


class DataProductBlueprintReviewRequest(StrictRequest):
    blueprint: DataProductBlueprint
    request_reason: NonEmptyText
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
            raise ValueError("assignment operation requires exactly one typed assignee")
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
    availability_status: ApprovalAvailabilityStatus = ApprovalAvailabilityStatus.AVAILABLE
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


class MetadataFabricBindingSearchResponse(StrictRequest):
    items: tuple[MetadataFabricBinding, ...]
    count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class MetadataProviderReadResponse(StrictRequest):
    result: ProviderReadResult


class MetadataProviderSearchResponse(StrictRequest):
    page: ProviderSearchPage


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


def _authenticated_principal(request: Request) -> GatewayPrincipal | JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return _error(request, 401, "unauthorized", "Authentication is required")
    metadata = _metadata(user)
    role = str(metadata.get("role") or "")
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


def _principal(request: Request) -> GatewayPrincipal | JSONResponse:
    principal = _authenticated_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role not in _PLATFORM_ROLES:
        return _error(
            request,
            403,
            "platform_role_required",
            "Platform operator role is required",
        )
    return principal


def _gis_mvt_principal(request: Request) -> GatewayPrincipal | JSONResponse:
    """Authenticate operators and bound data consumers for the MVT data plane."""
    principal = _authenticated_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role not in _PLATFORM_ROLES | _GIS_CONSUMER_ROLES:
        return _error(
            request,
            403,
            "gis_consumer_role_required",
            "A GIS operator or consumer role is required",
        )
    return principal


def _gis_ogc_features_principal(request: Request) -> GatewayPrincipal | JSONResponse:
    """Authenticate operators and bound data consumers for Features reads."""
    principal = _authenticated_principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role not in _PLATFORM_ROLES | _GIS_CONSUMER_ROLES:
        return _error(
            request,
            403,
            "gis_consumer_role_required",
            "A GIS operator or consumer role is required",
        )
    return principal


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


def _mvt_access_service() -> MVTAccessService:
    return MVTAccessService()


def _ogc_features_access_service() -> OGCFeaturesAccessService:
    return OGCFeaturesAccessService()


def _mvt_response_cache() -> MVTResponseCache:
    return get_mvt_response_cache()


def _approval_case_authority() -> ApprovalCaseAuthority:
    return ApprovalCaseAuthority()


def _slo_authority() -> SLODefinitionAuthority:
    return SLODefinitionAuthority()


def _master_data_authority() -> MasterDataAuthority:
    return MasterDataAuthority()


def _federated_compensation_proposal_store(
    tenant_id: str,
) -> PostgresFederatedProjectionCompensationProposalStore:
    return PostgresFederatedProjectionCompensationProposalStore(tenant_id)


def _federated_compensation_rule_store(
    tenant_id: str,
) -> PostgresCustomerCompensationRuleAuthorityStore:
    return PostgresCustomerCompensationRuleAuthorityStore(tenant_id)


def _federated_compensation_approval_service(
    tenant_id: str,
) -> FederatedProjectionCompensationApprovalService:
    return FederatedProjectionCompensationApprovalService(
        _federated_compensation_rule_store(tenant_id),
        _approval_case_authority(),
    )


def _federated_compensation_execution_approval_service(
    tenant_id: str,
) -> FederatedProjectionCompensationExecutionApprovalService:
    return FederatedProjectionCompensationExecutionApprovalService(
        _federated_compensation_rule_store(tenant_id),
        _approval_case_authority(),
    )


def _slo_incident_reconciler() -> SLOIncidentReconciler:
    return SLOIncidentReconciler(_slo_authority(), _gateway())


def _slo_alert_detector_subject() -> str:
    subject = os.environ.get("GDA_SLO_ALERT_DETECTOR_SUBJECT", "")
    if re.fullmatch(r"workload:[^\s]{1,128}", subject) is None:
        raise GatewayConfigurationError("SLO alert detector workload identity is not configured")
    return subject


def _architecture_change_approval_service() -> ArchitectureChangeApprovalService:
    return ArchitectureChangeApprovalService(
        _gateway(),
        _approval_case_authority(),
    )


def _architecture_change_assessment_service() -> ArchitectureChangeAssessmentService:
    return ArchitectureChangeAssessmentService(
        _gateway(),
        _approval_case_authority(),
    )


def _architecture_successor_adoption_service() -> ArchitectureSuccessorAdoptionService:
    return ArchitectureSuccessorAdoptionService(
        _gateway(),
        _approval_case_authority(),
    )


def _architecture_successor_data_product_release_service(
) -> ArchitectureSuccessorDataProductReleaseService:
    return ArchitectureSuccessorDataProductReleaseService(
        DataProductRegistry(),
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


def _approval_case_error(request: Request, error: ApprovalCaseAuthorityError) -> JSONResponse:
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


def _entity_authority_error(
    request: Request,
    error: (EntityLineageAuthorityError | EntityLinkAuthorityError | TemporalEntityAuthorityError),
) -> JSONResponse:
    if isinstance(
        error,
        (
            EntityLineageConflictError,
            EntityLinkConflictError,
            TemporalEntityConflictError,
        ),
    ):
        status = 409
    elif isinstance(
        error,
        (
            EntityLineageNotFoundError,
            EntityLinkNotFoundError,
            TemporalEntityNotFoundError,
        ),
    ):
        status = 404
    elif isinstance(
        error,
        (
            EntityLineageForbiddenError,
            EntityLinkForbiddenError,
            TemporalEntityForbiddenError,
        ),
    ):
        status = 403
    elif isinstance(
        error,
        (
            EntityLineageValidationError,
            EntityLinkValidationError,
            TemporalEntityValidationError,
        ),
    ):
        status = 422
    elif isinstance(
        error,
        (
            EntityLineageConfigurationError,
            EntityLinkConfigurationError,
            TemporalEntityConfigurationError,
        ),
    ):
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


def _gis_service_ref(
    request: Request,
    principal: GatewayPrincipal,
) -> str | JSONResponse:
    service_id = request.path_params.get("service_id", "")
    try:
        return build_resource_urn(principal.tenant_id, "gis_service", service_id)
    except ValueError:
        return _error(
            request,
            400,
            "invalid_gis_service_id",
            "service_id must be a canonical lowercase resource identifier",
        )


def _gis_deployment_revision_id(request: Request) -> UUID | JSONResponse:
    try:
        return UUID(request.path_params.get("deployment_revision_id", ""))
    except ValueError:
        return _error(
            request,
            400,
            "invalid_gis_deployment_revision_id",
            "deployment_revision_id must be a UUID",
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
    if (
        subject_type not in {"human", "team"}
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", subject_id) is None
    ):
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


async def get_gis_service_control_projection(request: Request) -> JSONResponse:
    """Return the tenant-scoped active GIS service projection."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    try:
        projection = await asyncio.to_thread(
            _gateway().get_gis_service_control_projection,
            principal.tenant_id,
            service_urn,
        )
        return _success(request, projection)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def get_gis_service_slo(request: Request) -> JSONResponse:
    """Return the latest exact active SLO binding for a GIS service."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    try:
        binding = await asyncio.to_thread(
            _gateway().get_gis_service_slo_binding,
            principal.tenant_id,
            service_urn,
        )
        return _success(request, binding)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def bind_gis_service_slo(request: Request) -> JSONResponse:
    """Bind a GIS service to an existing, independently approved active SLO."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "gis_service_slo_binding_admin_required",
            "GIS ServiceSLO binding requires an administrator",
        )
    submission = await _parse(request, GISServiceSLOBindingRequest)
    if isinstance(submission, JSONResponse):
        return submission
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    slo_definition_ref = build_resource_urn(
        principal.tenant_id,
        "slo_definition",
        submission.slo_definition_id,
    )
    try:
        definition, activation = await asyncio.to_thread(
            _slo_authority().active,
            principal.tenant_id,
            slo_definition_ref,
        )
        if definition.version != submission.version:
            return _error(
                request,
                409,
                "gis_service_slo_version_not_active",
                "Requested SLO version is not the active authority",
            )
        if activation.activation_version != submission.expected_activation_version:
            return _error(
                request,
                409,
                "gis_service_slo_activation_conflict",
                "SLO activation version changed before binding",
            )
        if definition.service_resource_urn != service_urn:
            return _error(
                request,
                422,
                "gis_service_slo_service_mismatch",
                "Active SLO belongs to a different service",
            )
        binding_id = uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    "gda.gis_service_slo_binding.v1",
                    principal.tenant_id,
                    service_urn,
                    definition.slo_version_ref,
                    str(activation.activation_version),
                )
            ),
        )
        binding = GISServiceSLOBinding(
            tenant_id=principal.tenant_id,
            binding_id=binding_id,
            service_urn=service_urn,
            slo_definition_ref=definition.slo_definition_ref,
            active_version_ref=definition.slo_version_ref,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=activation.approval_case_ref,
            activation_version=activation.activation_version,
            bound_by=principal.actor_ref,
            binding_reason=submission.reason,
            bound_at=_utc_now(),
        )
        result = await asyncio.to_thread(_gateway().bind_gis_service_slo, binding)
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
            "GIS ServiceSLO binding does not satisfy the platform contract",
            _validation_details(exc),
        )
    except SLOAuthorityError as exc:
        return _slo_error(request, exc)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def _bound_gis_service_deployment(
    request: Request,
    principal: GatewayPrincipal,
    gateway: PlatformGateway,
) -> BaseModel | JSONResponse:
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    deployment_revision_id = _gis_deployment_revision_id(request)
    if isinstance(deployment_revision_id, JSONResponse):
        return deployment_revision_id
    try:
        deployment = await asyncio.to_thread(
            gateway.get_service_deployment_revision,
            principal.tenant_id,
            deployment_revision_id,
        )
        definition = await asyncio.to_thread(
            gateway.get_gis_service_definition_version,
            principal.tenant_id,
            deployment.service_definition_version_id,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)
    if definition.service_urn != service_urn:
        return _error(
            request,
            404,
            "gis_service_deployment_not_found",
            "Deployment revision does not belong to this GIS service",
        )
    return deployment


async def get_gis_service_deployment(request: Request) -> JSONResponse:
    """Return one deployment revision after tenant and service ownership checks."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    deployment = await _bound_gis_service_deployment(
        request,
        principal,
        _gateway(),
    )
    if isinstance(deployment, JSONResponse):
        return deployment
    return _success(request, deployment)


async def list_gis_service_deployment_events(request: Request) -> JSONResponse:
    """Return the immutable transition timeline after service ownership checks."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    gateway = _gateway()
    deployment = await _bound_gis_service_deployment(request, principal, gateway)
    if isinstance(deployment, JSONResponse):
        return deployment
    try:
        events = await asyncio.to_thread(
            gateway.list_service_deployment_events,
            principal.tenant_id,
            deployment.deployment_revision_id,
        )
        return _success(
            request,
            GISServiceDeploymentEventListResponse(
                items=events,
                count=len(events),
            ),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


def _gis_service_deployment_observation(
    principal: GatewayPrincipal,
    deployment: ServiceDeploymentRevision,
    submission: GISServiceDeploymentObservationRequest,
) -> FrameworkAttemptObservation:
    evidence = {
        "schema": "gda.gis_service_deployment_observation.v2",
        "deployment_revision_id": str(deployment.deployment_revision_id),
        "service_definition_version_id": str(
            deployment.service_definition_version_id
        ),
        "service_release_binding_id": str(deployment.service_release_binding_id),
        "provider_system": deployment.provider_system,
        "provider_version": submission.provider_version,
        "provider_namespace": deployment.provider_namespace,
        "provider_deployment_id": deployment.provider_deployment_id,
        "provider_revision_ref": deployment.provider_revision_ref,
        "config_sha256": deployment.config_sha256,
        "endpoint_uri": submission.endpoint_uri,
        "health_evidence_sha256": submission.health_evidence_sha256,
        "provider_receipt": submission.provider_receipt,
        "reported_by": principal.actor_ref,
    }
    return FrameworkAttemptObservation(
        tenant_id=principal.tenant_id,
        observation_id=submission.observation_id,
        run_id=deployment.run_id,
        attempt_no=submission.attempt_no,
        framework_kind=submission.framework_kind,
        external_namespace=deployment.provider_namespace,
        external_run_id=deployment.provider_deployment_id,
        external_attempt_id=deployment.provider_revision_ref,
        observed_state=submission.observed_state,
        observation_sha256=canonical_json_fingerprint(evidence),
        evidence=evidence,
        observed_at=submission.observed_at,
    )


async def record_gis_service_deployment_observation(request: Request) -> JSONResponse:
    """Record terminal provider evidence without executing a provider operation."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "gis_service_deployment_workload_required",
            "GIS service deployment observations require workload identity",
        )
    submission = await _parse(request, GISServiceDeploymentObservationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    gateway = _gateway()
    deployment = await _bound_gis_service_deployment(request, principal, gateway)
    if isinstance(deployment, JSONResponse):
        return deployment
    try:
        observation = _gis_service_deployment_observation(
            principal,
            deployment,
            submission,
        )
        result = await asyncio.to_thread(
            gateway.record_gis_service_deployment_observation,
            deployment.deployment_revision_id,
            observation,
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
            "gis_service_deployment_observation_invalid",
            "GIS service deployment observation does not satisfy the platform contract",
            _validation_details(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def settle_gis_service_deployment_terminal(request: Request) -> JSONResponse:
    """Atomically admit terminal provider evidence and settle a deployment revision."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "gis_service_deployment_workload_required",
            "GIS service deployment terminal settlement requires workload identity",
        )
    submission = await _parse(request, GISServiceDeploymentTerminalSettlementRequest)
    if isinstance(submission, JSONResponse):
        return submission
    gateway = _gateway()
    deployment = await _bound_gis_service_deployment(request, principal, gateway)
    if isinstance(deployment, JSONResponse):
        return deployment
    try:
        observation = _gis_service_deployment_observation(
            principal,
            deployment,
            submission,
        )
        settlement = await asyncio.to_thread(
            gateway.settle_gis_service_deployment_terminal,
            deployment.deployment_revision_id,
            observation,
            expected_state_version=submission.expected_state_version,
            actor_subject=principal.actor_ref,
            reason=submission.reason,
            idempotency_key=submission.idempotency_key,
            occurred_at=submission.occurred_at,
        )
        return _success(
            request,
            settlement,
            status_code=201 if settlement.observation_created else 200,
            created=settlement.observation_created,
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "gis_service_deployment_settlement_invalid",
            "GIS service deployment terminal settlement does not satisfy the platform contract",
            _validation_details(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def register_gis_service_deployment(request: Request) -> JSONResponse:
    """Register one planned, release-bound deployment revision for a GIS service."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "gis_service_deployment_workload_required",
            "GIS service deployment registration requires workload identity",
        )
    submission = await _parse(request, GISServiceDeploymentRegistrationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    gateway = _gateway()
    try:
        definition = await asyncio.to_thread(
            gateway.get_gis_service_definition_version,
            principal.tenant_id,
            submission.service_definition_version_id,
        )
        release = await asyncio.to_thread(
            gateway.get_service_release_binding,
            principal.tenant_id,
            submission.service_release_binding_id,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)
    if definition.service_urn != service_urn or (
        release.service_definition_version_id
        != submission.service_definition_version_id
    ):
        return _error(
            request,
            404,
            "gis_service_release_not_found",
            "Service definition or release does not belong to this GIS service",
        )
    deployment_values = {
        "tenant_id": principal.tenant_id,
        "deployment_revision_id": submission.deployment_revision_id,
        "service_definition_version_id": submission.service_definition_version_id,
        "service_release_binding_id": submission.service_release_binding_id,
        "run_id": submission.run_id,
        "revision_key": submission.revision_key,
        "provider_system": submission.provider_system,
        "provider_namespace": submission.provider_namespace,
        "provider_deployment_id": submission.provider_deployment_id,
        "provider_revision_ref": submission.provider_revision_ref,
        "config_sha256": submission.config_sha256,
        "state": ServiceDeploymentState.PLANNED,
        "state_version": 0,
        "created_by": principal.actor_ref,
        "created_at": submission.created_at,
        "updated_at": submission.created_at,
    }
    try:
        deployment = ServiceDeploymentRevision(
            **deployment_values,
            deployment_sha256=service_deployment_fingerprint(deployment_values),
        )
        result = await asyncio.to_thread(
            gateway.register_service_deployment_revision,
            deployment,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "gis_service_deployment_invalid",
            "GIS service deployment does not satisfy the platform contract",
            details,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def transition_gis_service_deployment(request: Request) -> JSONResponse:
    """Advance a deployment using Run-bound provider evidence."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "gis_service_deployment_workload_required",
            "GIS service deployment transitions require workload identity",
        )
    transition = await _parse(request, GISServiceDeploymentTransitionRequest)
    if isinstance(transition, JSONResponse):
        return transition
    gateway = _gateway()
    deployment = await _bound_gis_service_deployment(request, principal, gateway)
    if isinstance(deployment, JSONResponse):
        return deployment
    try:
        updated = await asyncio.to_thread(
            gateway.transition_service_deployment_revision,
            principal.tenant_id,
            deployment.deployment_revision_id,
            expected_state_version=transition.expected_state_version,
            to_state=transition.to_state,
            provider_observation_id=transition.provider_observation_id,
            actor_subject=principal.actor_ref,
            reason=transition.reason,
            idempotency_key=transition.idempotency_key,
            occurred_at=transition.occurred_at,
        )
        return _success(request, updated)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def register_gis_service_endpoint(request: Request) -> JSONResponse:
    """Register an immutable provider endpoint for a ready GIS deployment."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "gis_service_endpoint_workload_required",
            "GIS service endpoint registration requires workload identity",
        )
    submission = await _parse(request, GISServiceEndpointRegistrationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    gateway = _gateway()
    deployment = await _bound_gis_service_deployment(request, principal, gateway)
    if isinstance(deployment, JSONResponse):
        return deployment
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    endpoint_values = {
        "tenant_id": principal.tenant_id,
        "endpoint_revision_id": submission.endpoint_revision_id,
        "service_urn": service_urn,
        "deployment_revision_id": deployment.deployment_revision_id,
        "endpoint_protocol": submission.endpoint_protocol,
        "endpoint_uri": submission.endpoint_uri,
        "endpoint_contract": submission.endpoint_contract,
        "created_by": principal.actor_ref,
        "created_at": submission.created_at,
    }
    try:
        endpoint = EndpointRevision(
            **endpoint_values,
            endpoint_sha256=endpoint_revision_fingerprint(endpoint_values),
        )
        result = await asyncio.to_thread(gateway.register_endpoint_revision, endpoint)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "gis_service_endpoint_invalid",
            "GIS service endpoint does not satisfy the platform contract",
            details,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def activate_gis_service_endpoint(request: Request) -> JSONResponse:
    """Atomically switch the active GIS endpoint pointer after deployment readiness."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.role != "admin":
        return _error(
            request,
            403,
            "gis_service_activation_admin_required",
            "GIS service endpoint activation requires an administrator",
        )
    submission = await _parse(request, GISServiceEndpointActivationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    service_urn = _gis_service_ref(request, principal)
    if isinstance(service_urn, JSONResponse):
        return service_urn
    try:
        projection = await asyncio.to_thread(
            _gateway().activate_gis_service_endpoint,
            principal.tenant_id,
            service_urn,
            submission.endpoint_revision_id,
            expected_state_version=submission.expected_state_version,
            actor_subject=principal.actor_ref,
            reason=submission.reason,
            idempotency_key=submission.idempotency_key,
            occurred_at=submission.occurred_at,
        )
        return _success(request, projection)
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


def _martin_provider_endpoint() -> str:
    """Return the trusted in-cluster Martin origin used by the Gateway.

    EndpointRevision.endpoint_uri is the consumer-visible HTTPS address.  It is
    intentionally not reused as a provider origin: doing so would let the
    Gateway bypass its own internal network boundary or recursively call the
    public route it is serving.
    """
    endpoint = os.environ.get("MARTIN_URL", "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        not endpoint
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GatewayConfigurationError(
            "MARTIN_URL must be a credential-free HTTP(S) provider origin"
        )
    return endpoint


def _pygeoapi_provider_endpoint() -> str:
    """Return the trusted in-cluster pygeoapi origin used by the Gateway."""
    endpoint = os.environ.get("PYGEOAPI_URL", "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        not endpoint
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GatewayConfigurationError(
            "PYGEOAPI_URL must be a credential-free HTTP(S) provider origin"
        )
    return endpoint


def _pygeoapi_provider_version(deployment: Any) -> str:
    """Resolve a manifest version from explicit config or deployment metadata."""
    configured = os.environ.get("PYGEOAPI_PROVIDER_VERSION", "").strip()
    if configured:
        return configured
    revision = str(getattr(deployment, "provider_revision_ref", ""))
    match = re.search(r"(?:pygeoapi[- /])?([0-9]+(?:\.[0-9A-Za-z]+)+)", revision)
    return match.group(1) if match else "0.21.0"


def _ogc_features_query(
    request: Request,
) -> tuple[int, tuple[float, float, float, float] | None] | JSONResponse:
    """Parse bounded OGC API Features query parameters at the Gateway edge."""
    limit_values = request.query_params.getlist("limit")
    if len(limit_values) > 1:
        return _error(request, 400, "invalid_limit", "limit must be specified once")
    limit_text = limit_values[0] if limit_values else "100"
    try:
        limit = int(limit_text)
    except (TypeError, ValueError):
        return _error(request, 400, "invalid_limit", "limit must be an integer")
    if limit < 1 or limit > 1000:
        return _error(request, 400, "invalid_limit", "limit must be between 1 and 1000")

    bbox_values = request.query_params.getlist("bbox")
    if len(bbox_values) > 1:
        return _error(request, 400, "invalid_bbox", "bbox must be specified once")
    if not bbox_values or not bbox_values[0].strip():
        return limit, None
    parts = [item.strip() for item in bbox_values[0].split(",")]
    if len(parts) != 4:
        return _error(
            request,
            400,
            "invalid_bbox",
            "bbox must contain four comma-separated coordinates",
        )
    try:
        bbox = tuple(float(item) for item in parts)
    except ValueError:
        return _error(request, 400, "invalid_bbox", "bbox coordinates must be numbers")
    if not all(isfinite(item) for item in bbox) or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
        return _error(request, 400, "invalid_bbox", "bbox must be a finite ordered extent")
    return limit, bbox


async def get_gis_mvt_tile(request: Request) -> Response:
    """Serve an active, release-versioned MVT tile through the control gateway.

    The authenticated HTTP principal, release policy, ConsumerBinding, and
    static serving projection are sealed into one audited access decision
    before the internal Martin request can occur.
    """

    principal = _gis_mvt_principal(request)
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
    cache_policy = projection.active_cache_policy_version
    service_policy = projection.active_service_policy_binding
    serving_projection = projection.active_mvt_serving_projection_version
    if any(
        value is None
        for value in (
            endpoint,
            deployment,
            definition,
            release,
            tile_matrix_set,
        )
    ):
        return _error(
            request,
            409,
            "gis_service_not_tile_ready",
            "active GIS service projection is incomplete for MVT",
        )
    if cache_policy is None:
        return _error(
            request,
            409,
            "cache_policy_required",
            "active MVT release does not have a cache policy",
        )
    if service_policy is None:
        return _error(
            request,
            409,
            "service_policy_required",
            "active MVT release does not have a Gateway service policy",
        )
    if serving_projection is None:
        return _error(
            request,
            409,
            "serving_projection_required",
            "active MVT release does not have a serving projection",
        )
    if release.release_key != release_key:
        return _error(
            request,
            409,
            "active_release_mismatch",
            "requested release_key is not the active release",
        )

    binding = None
    if principal.role in service_policy.consumer_binding_required_roles:
        try:
            binding = await asyncio.to_thread(
                _gateway().get_active_service_consumer_binding_for_release,
                principal.tenant_id,
                service_urn,
                definition.service_definition_version_id,
                release.service_release_binding_id,
                principal.actor_ref,
            )
        except PlatformGatewayError as exc:
            return _gateway_error(request, exc)
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
        endpoint_contract = MVTGatewayEndpointContract.model_validate(endpoint.endpoint_contract)
        if (
            endpoint_contract.provider_query.get("serving_projection_version_id")
            != str(serving_projection.mvt_serving_projection_version_id)
        ):
            raise ValueError("MVT endpoint serving projection does not match active release")
        context = MVTProviderReleaseContext.from_release(
            release,
            tile_matrix_set,
            serving_projection,
            service_type=definition.service_type,
            provider_layer_ref=endpoint_contract.provider_layer_ref,
            provider_query=endpoint_contract.provider_query,
        )
    except (ValidationError, ValueError) as exc:
        return _error(
            request,
            409,
            "invalid_mvt_endpoint_contract",
            "active endpoint contract is not admissible",
            _validation_details(exc) if isinstance(exc, ValidationError) else None,
        )
    except GatewayConfigurationError as exc:
        return _error(request, 503, "provider_configuration_error", str(exc))
    except GISProviderContractError as exc:
        return _error(request, 502, "provider_contract_error", str(exc))
    except GISProviderUnavailable as exc:
        return _error(request, 503, "provider_unavailable", str(exc))

    request_id = _request_id(request)
    try:
        subject_context = SubjectContext(
            tenant_id=principal.tenant_id,
            subject_id=principal.subject_id,
            subject_type=principal.subject_type,
            roles=(principal.role,),
            purpose=GOVERNED_MVT_ACCESS_PURPOSE,
            trace_id=request_id,
        )
    except ValidationError as exc:
        return _error(
            request,
            400,
            "invalid_mvt_request_context",
            "MVT request identity context is invalid",
            _validation_details(exc),
        )

    access_service = _mvt_access_service()
    try:
        admission = await asyncio.to_thread(
            access_service.admit,
            request_id=request_id,
            subject_context=subject_context,
            service_urn=service_urn,
            definition=definition,
            release=release,
            service_policy=service_policy,
            serving_projection=serving_projection,
            service_consumer_binding=binding,
            z=z,
            x=x,
            y=y,
        )
    except MVTAccessDeniedError as exc:
        return _error(request, 403, exc.code, exc.message)
    except MVTAccessUnavailableError:
        return _error(
            request,
            503,
            "mvt_access_audit_unavailable",
            "MVT access audit is unavailable",
        )

    # The request decision above remains the authorization boundary. The
    # shared key contains only stable release/policy/projection/identity
    # versions; the per-request decision hash is deliberately audit-only.
    cache_context = {
        "schema": "gda.gis_mvt_shared_cache_key.v3",
        "namespace": cache_policy.cache_namespace,
        "tenant_id": principal.tenant_id,
        "service_urn": service_urn,
        "service_release_binding_id": str(release.service_release_binding_id),
        "service_release_sha256": release.binding_sha256,
        "cache_policy_version_id": str(cache_policy.cache_policy_version_id),
        "cache_policy_sha256": cache_policy.policy_sha256,
        "service_policy_binding_id": str(service_policy.service_policy_binding_id),
        "service_policy_sha256": service_policy.policy_sha256,
        "mvt_serving_projection_version_id": str(
            serving_projection.mvt_serving_projection_version_id
        ),
        "mvt_serving_projection_sha256": serving_projection.projection_sha256,
        "endpoint_state_version": projection.endpoint_state_version,
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
        "endpoint_sha256": endpoint.endpoint_sha256,
        "principal": principal.actor_ref,
        "service_consumer_binding_id": (
            str(getattr(binding, "service_consumer_binding_id", "operator"))
            if binding is not None
            else "operator"
        ),
        "service_consumer_binding_sha256": (
            getattr(binding, "binding_sha256", "operator")
            if binding is not None
            else "operator"
        ),
        "tile": {"z": z, "x": x, "y": y},
    }
    cache_object_key = mvt_response_cache_key(cache_context)
    cache_namespace_token = mvt_response_cache_namespace(cache_context)
    response_cache = _mvt_response_cache()
    cached_entry = None
    try:
        cached_entry = await response_cache.get(cache_object_key)
    except Exception:
        # A cache is a performance projection. Authorization and its audit
        # remain fail-closed; a cache outage simply reads Martin.
        cached_entry = None

    delivery_source = "redis_cache" if cached_entry is not None else "provider"
    if cached_entry is not None:
        tile = ProviderTileResponse(
            content=cached_entry.content,
            status_code=200,
            media_type=cached_entry.media_type,
            etag=None,
        )
    else:
        try:
            tile = await MartinVectorTileProvider(
                _martin_provider_endpoint(),
                manifest=martin_provider_manifest(),
            ).fetch_tile(context, z, x, y)
        except GatewayConfigurationError as exc:
            try:
                await asyncio.to_thread(access_service.record_failure, admission, error=exc)
            except MVTAccessUnavailableError:
                return _error(
                    request,
                    503,
                    "mvt_access_audit_unavailable",
                    "MVT access audit is unavailable",
                )
            return _error(request, 503, "provider_configuration_error", str(exc))
        except GISProviderContractError as exc:
            try:
                await asyncio.to_thread(access_service.record_failure, admission, error=exc)
            except MVTAccessUnavailableError:
                return _error(
                    request,
                    503,
                    "mvt_access_audit_unavailable",
                    "MVT access audit is unavailable",
                )
            return _error(request, 502, "provider_contract_error", str(exc))
        except GISProviderUnavailable as exc:
            try:
                await asyncio.to_thread(access_service.record_failure, admission, error=exc)
            except MVTAccessUnavailableError:
                return _error(
                    request,
                    503,
                    "mvt_access_audit_unavailable",
                    "MVT access audit is unavailable",
                )
            return _error(request, 503, "provider_unavailable", str(exc))

    try:
        await asyncio.to_thread(
            access_service.record_success,
            admission,
            content=tile.content,
            status_code=tile.status_code,
            media_type=tile.media_type,
            delivery_source=delivery_source,
        )
    except MVTAccessUnavailableError:
        return _error(
            request,
            503,
            "mvt_access_audit_unavailable",
            "MVT access audit is unavailable",
        )

    base_headers = {
        "Vary": "Authorization, Cookie, Accept-Encoding",
        "X-Content-Type-Options": "nosniff",
        "X-GDA-Service-Release": release.release_key,
        "X-GDA-Endpoint-State-Version": str(projection.endpoint_state_version),
        "X-GDA-Shared-Cache": (
            "hit"
            if delivery_source == "redis_cache"
            else "miss" if response_cache.enabled else "bypass"
        ),
    }
    if tile.status_code != 200:
        headers = {**base_headers, "Cache-Control": "private, no-store"}
        return Response(
            tile.content,
            status_code=tile.status_code,
            media_type=tile.media_type,
            headers=headers,
        )

    if delivery_source == "provider" and tile.content:
        try:
            await response_cache.put(
                cache_object_key,
                MVTResponseCacheEntry.from_response(tile.content, tile.media_type),
                ttl_seconds=min(cache_policy.cache_max_age_seconds, 300),
            )
        except Exception:
            pass
    content_sha256 = hashlib.sha256(tile.content).hexdigest()
    etag = '"' + hashlib.sha256(
        f"{cache_object_key}:{content_sha256}".encode("ascii")
    ).hexdigest() + '"'
    headers = {
        **base_headers,
        "Cache-Control": (
            f"private, max-age={cache_policy.cache_max_age_seconds}, must-revalidate"
        ),
        "ETag": etag,
        "X-GDA-Cache-Generation": cache_namespace_token,
        "X-GDA-Cache-Namespace": (
            f"{cache_policy.cache_namespace}-{cache_namespace_token[:24]}"
        ),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(
        tile.content,
        status_code=tile.status_code,
        media_type=tile.media_type,
        headers=headers,
    )


async def get_gis_ogc_api_features_items(request: Request) -> Response:
    """Serve an audited, exact-release OGC API Features read through Gateway."""
    principal = _gis_ogc_features_principal(request)
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
    collection_id = request.path_params.get("collection_id", "")
    query = _ogc_features_query(request)
    if isinstance(query, JSONResponse):
        return query
    limit, bbox = query

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
    layer = projection.active_layer_definition_version
    service_policy = projection.active_service_policy_binding
    if any(value is None for value in (endpoint, deployment, definition, release, layer)):
        return _error(
            request,
            409,
            "gis_service_not_feature_ready",
            "active GIS service projection is incomplete for OGC API Features",
        )
    if service_policy is None:
        return _error(
            request,
            409,
            "service_policy_required",
            "active OGC API Features release does not have a Gateway service policy",
        )
    if service_policy.action != GOVERNED_OGC_FEATURES_ACCESS_ACTION:
        return _error(
            request,
            409,
            "service_policy_action_mismatch",
            "active service policy is not an OGC API Features read policy",
        )
    if release.release_key != release_key:
        return _error(
            request,
            409,
            "active_release_mismatch",
            "requested release_key is not the active release",
        )
    if endpoint.endpoint_protocol is not EndpointProtocol.OGC_API_FEATURES:
        return _error(
            request,
            409,
            "endpoint_protocol_mismatch",
            "active endpoint is not an OGC API Features endpoint",
        )
    if definition.service_type is not GISServiceType.FEATURE:
        return _error(
            request,
            409,
            "service_type_mismatch",
            "active GIS service is not a feature service",
        )
    if deployment.state.value != "ready":
        return _error(
            request,
            409,
            "deployment_not_ready",
            "active GIS deployment is not ready",
        )
    if deployment.provider_system != "pygeoapi":
        return _error(
            request,
            409,
            "provider_not_supported",
            "the governed OGC API Features route currently supports pygeoapi only",
        )

    binding = None
    if principal.role in service_policy.consumer_binding_required_roles:
        try:
            binding = await asyncio.to_thread(
                _gateway().get_active_service_consumer_binding_for_release,
                principal.tenant_id,
                service_urn,
                definition.service_definition_version_id,
                release.service_release_binding_id,
                principal.actor_ref,
            )
        except PlatformGatewayError as exc:
            return _gateway_error(request, exc)

    access_service = _ogc_features_access_service()
    try:
        contract = OGCAPIFeaturesGatewayEndpointContract.model_validate(
            endpoint.endpoint_contract
        )
        if contract.collection_id != layer.layer_key or contract.collection_id != collection_id:
            return _error(
                request,
                409,
                "collection_mismatch",
                "requested collection does not match the active release layer",
            )
        context = OGCAPIFeaturesReleaseContext.from_release(
            release,
            definition,
            layer,
            collection_id=contract.collection_id,
        )
        request_id = _request_id(request)
        subject_context = SubjectContext(
            tenant_id=principal.tenant_id,
            subject_id=principal.subject_id,
            subject_type=principal.subject_type,
            roles=(principal.role,),
            purpose=GOVERNED_OGC_FEATURES_ACCESS_PURPOSE,
            trace_id=request_id,
        )
        admission = await asyncio.to_thread(
            access_service.admit,
            request_id=request_id,
            subject_context=subject_context,
            service_urn=service_urn,
            definition=definition,
            release=release,
            service_policy=service_policy,
            service_consumer_binding=binding,
            collection_id=contract.collection_id,
            limit=limit,
            bbox=bbox,
        )
        provider_origin = _pygeoapi_provider_endpoint()
        provider = OGCAPIFeaturesProvider(
            provider_origin,
            manifest=pygeoapi_provider_manifest(
                _pygeoapi_provider_version(deployment)
            ),
        )
        try:
            items = await provider.fetch_items(context, limit=limit, bbox=bbox)
        except (GatewayConfigurationError, GISProviderContractError, GISProviderUnavailable) as exc:
            try:
                await asyncio.to_thread(access_service.record_failure, admission, error=exc)
            except OGCFeaturesAccessUnavailableError:
                return _error(
                    request,
                    503,
                    "ogc_features_access_audit_unavailable",
                    "OGC API Features access audit is unavailable",
                )
            if isinstance(exc, GatewayConfigurationError):
                return _error(request, 503, "provider_configuration_error", str(exc))
            if isinstance(exc, GISProviderContractError):
                return _error(request, 502, "provider_contract_error", str(exc))
            return _error(request, 503, "provider_unavailable", str(exc))
        try:
            await asyncio.to_thread(
                access_service.record_success,
                admission,
                content=items.content,
                status_code=items.status_code,
                media_type=items.media_type,
                feature_count=items.feature_count,
            )
        except OGCFeaturesAccessUnavailableError:
            return _error(
                request,
                503,
                "ogc_features_access_audit_unavailable",
                "OGC API Features access audit is unavailable",
            )
    except ValidationError as exc:
        return _error(
            request,
            409,
            "invalid_ogc_api_features_endpoint_contract",
            "active OGC API Features endpoint contract is not admissible",
            _validation_details(exc),
        )
    except (ValueError, GISProviderContractError) as exc:
        return _error(
            request,
            502,
            "provider_contract_error",
            str(exc),
        )
    except GatewayConfigurationError as exc:
        return _error(request, 503, "provider_configuration_error", str(exc))
    except GISProviderUnavailable as exc:
        return _error(request, 503, "provider_unavailable", str(exc))
    except OGCFeaturesAccessDeniedError as exc:
        return _error(request, 403, exc.code, exc.message)
    except OGCFeaturesAccessUnavailableError:
        return _error(
            request,
            503,
            "ogc_features_access_audit_unavailable",
            "OGC API Features access audit is unavailable",
        )

    headers = {
        "Cache-Control": "private, no-store",
        "Vary": "Authorization, Cookie, Accept",
        "X-Content-Type-Options": "nosniff",
        "X-GDA-Service-Release": release.release_key,
        "X-GDA-Endpoint-State-Version": str(projection.endpoint_state_version),
        "X-GDA-Collection-Id": context.collection_id,
    }
    if items.etag:
        headers["ETag"] = items.etag
    if request.headers.get("if-none-match") and items.etag == request.headers.get("if-none-match"):
        return Response(status_code=304, headers=headers)
    return Response(
        items.content,
        status_code=items.status_code,
        media_type=items.media_type,
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
        action = _APPROVAL_ACTION_ADAPTER.validate_python(raw_action) if raw_action else None
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


async def schedule_approval_case_batch_escalation(request: Request) -> JSONResponse:
    """Schedule a bounded set of independent ApprovalCase SLA escalations."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        APPROVAL_CASE_BATCH_ESCALATION,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, ApprovalCaseBatchEscalationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if mismatch := _tenant_matches(request, principal, submission.tenant_id):
        return mismatch
    if submission.actor_subject != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "Request actor_subject must match the authenticated actor",
        )
    try:
        result = await asyncio.to_thread(
            execute_approval_case_batch_escalation,
            submission,
        )
        return _success(request, result)
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
        team_subject = _approval_subject("team", request.path_params.get("team_id", ""))
        member_subject = _approval_subject("human", request.path_params.get("member_id", ""))
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
        team_subject = _approval_subject("team", request.path_params.get("team_id", ""))
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


async def create_data_product_blueprint(request: Request) -> JSONResponse:
    """Compile and register a blueprint through the existing definition authority."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    blueprint = await _parse(request, DataProductBlueprint)
    if isinstance(blueprint, JSONResponse):
        return blueprint
    if mismatch := _tenant_matches(request, principal, blueprint.tenant_id):
        return mismatch
    if blueprint.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        registration = compile_data_product_blueprint(blueprint)
        result = await asyncio.to_thread(_gateway().register_definition, registration)
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def preview_data_product_blueprint(request: Request) -> JSONResponse:
    """Compile and diff a blueprint without mutating definition authority."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    blueprint = await _parse(request, DataProductBlueprint)
    if isinstance(blueprint, JSONResponse):
        return blueprint
    if mismatch := _tenant_matches(request, principal, blueprint.tenant_id):
        return mismatch
    if blueprint.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        predecessor = None
        if blueprint.predecessor_definition_version_id is not None:
            predecessor = await asyncio.to_thread(
                _gateway().get_definition,
                principal.tenant_id,
                blueprint.predecessor_definition_version_id,
            )
        preview = build_data_product_blueprint_preview(
            blueprint,
            predecessor=predecessor,
        )
        return _success(request, preview)
    except ValueError as exc:
        return _error(
            request,
            422,
            "blueprint_preview_failed",
            str(exc),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def test_data_product_blueprint(request: Request) -> JSONResponse:
    """Run deterministic Blueprint contract tests without provider side effects."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    blueprint = await _parse(request, DataProductBlueprint)
    if isinstance(blueprint, JSONResponse):
        return blueprint
    if mismatch := _tenant_matches(request, principal, blueprint.tenant_id):
        return mismatch
    if blueprint.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        report = build_data_product_blueprint_test_report(blueprint)
        return _success(request, report)
    except ValueError as exc:
        return _error(request, 422, "blueprint_test_failed", str(exc))


async def admit_data_product_blueprint_test_run(request: Request) -> JSONResponse:
    """Admit a Blueprint test into the shared PlatformRun authority."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, DataProductBlueprintTestRunRequest)
    if isinstance(submission, JSONResponse):
        return submission
    blueprint = submission.blueprint
    if mismatch := _tenant_matches(request, principal, blueprint.tenant_id):
        return mismatch
    if blueprint.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        subject_context = SubjectContext(
            tenant_id=principal.tenant_id,
            subject_id=principal.subject_id,
            subject_type=principal.subject_type,
            roles=(principal.role,),
            purpose="data_product_blueprint_test_admission",
            trace_id=request.headers.get("x-request-id"),
        )
        result = await asyncio.to_thread(
            _gateway().admit_blueprint_test_run,
            submission,
            subject_context=subject_context,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "blueprint_test_admission_failed",
            str(exc),
            details,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def execute_data_product_blueprint_test_run(request: Request) -> JSONResponse:
    """Execute an admitted Blueprint test with the named deterministic local provider."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Deterministic Blueprint test execution requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintTestExecutionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().execute_blueprint_test_run,
            principal.tenant_id,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def execute_data_product_blueprint_duckdb_test_run(
    request: Request,
) -> JSONResponse:
    """Execute an admitted Blueprint through the bounded real DuckDB provider."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "DuckDB Blueprint execution requires workload identity",
        )
    submission = await _parse(request, DuckDBBlueprintExecutionRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().execute_blueprint_duckdb_test_run,
            principal.tenant_id,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def fail_data_product_blueprint_test_run(request: Request) -> JSONResponse:
    """Record a workload-owned deterministic Blueprint test failure."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Deterministic Blueprint test failure requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintTestExecutionFailureRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().fail_blueprint_test_run,
            principal.tenant_id,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def cancel_data_product_blueprint_test_run(request: Request) -> JSONResponse:
    """Converge a previously governed Blueprint test cancellation."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Deterministic Blueprint test cancellation requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintTestCancellationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().complete_blueprint_test_run_cancellation,
            principal.tenant_id,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def reconcile_data_product_blueprint_test_provider(
    request: Request,
) -> JSONResponse:
    """Apply an authenticated execution-provider receipt to a reconciling Run."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Blueprint provider reconciliation requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintProviderReconcileRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if mismatch := _tenant_matches(request, principal, submission.tenant_id):
        return mismatch
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().reconcile_blueprint_test_provider,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def record_data_product_blueprint_provider_cancellation_timeout(
    request: Request,
) -> JSONResponse:
    """Record a high-severity incident when provider cancellation retries exhaust."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Blueprint provider cancellation timeout requires workload identity",
        )
    submission = await _parse(
        request, DataProductBlueprintProviderCancellationTimeoutRequest
    )
    if isinstance(submission, JSONResponse):
        return submission
    if mismatch := _tenant_matches(request, principal, submission.tenant_id):
        return mismatch
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().record_blueprint_provider_cancellation_timeout,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def retry_data_product_blueprint_test_provider(
    request: Request,
) -> JSONResponse:
    """Schedule a bounded provider retry with an immutable backoff decision."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type != SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Blueprint provider retry requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintProviderRetryRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if mismatch := _tenant_matches(request, principal, submission.tenant_id):
        return mismatch
    try:
        path_run_id = UUID(request.path_params["run_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_run_id", "run_id must be a UUID")
    if submission.run_id != path_run_id:
        return _error(
            request,
            422,
            "run_id_mismatch",
            "Request run_id must match the path run_id",
        )
    try:
        result = await asyncio.to_thread(
            _gateway().retry_blueprint_test_provider,
            submission,
            actor_subject=principal.actor_ref,
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def create_data_product_blueprint_review(request: Request) -> JSONResponse:
    """Compile a Blueprint and admit its exact change set to ApprovalCase."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, DataProductBlueprintReviewRequest)
    if isinstance(submission, JSONResponse):
        return submission
    blueprint = submission.blueprint
    if mismatch := _tenant_matches(request, principal, blueprint.tenant_id):
        return mismatch
    if blueprint.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "created_by must match authenticated actor",
        )
    try:
        predecessor = None
        if blueprint.predecessor_definition_version_id is not None:
            predecessor = await asyncio.to_thread(
                _gateway().get_definition,
                principal.tenant_id,
                blueprint.predecessor_definition_version_id,
            )
        preview = build_data_product_blueprint_preview(
            blueprint,
            predecessor=predecessor,
        )
        approval_case = build_data_product_blueprint_approval_case(
            preview,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            requested_at=submission.requested_at,
            expires_at=submission.expires_at,
        )
        written = await asyncio.to_thread(
            _approval_case_authority().create,
            approval_case,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
        result = DataProductBlueprintReview(
            preview=preview,
            approval_case=written.approval_case,
        )
        return _success(
            request,
            result,
            status_code=201 if written.created else 200,
            created=written.created,
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "blueprint_review_failed",
            str(exc),
            details,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)


async def publish_data_product_blueprint_release(request: Request) -> JSONResponse:
    """Publish an approved Blueprint release through DataProductRegistry."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Blueprint release publication requires workload identity",
        )
    submission = await _parse(request, DataProductBlueprintReleasePublishRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if mismatch := _tenant_matches(request, principal, submission.product.tenant_id):
        return mismatch
    if submission.version.published_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "version.published_by must match authenticated workload",
        )
    if mismatch := _tenant_matches(
        request,
        principal,
        submission.blueprint_release_binding.tenant_id,
    ):
        return mismatch
    try:
        publication = await asyncio.to_thread(
            DataProductRegistry().publish,
            submission.product,
            submission.version,
            idempotency_key=submission.idempotency_key,
            reason=submission.reason,
            blueprint_release_binding=submission.blueprint_release_binding,
        )
        result = DataProductBlueprintReleasePublishResponse(
            product=submission.product,
            version=submission.version,
            blueprint_release_binding=submission.blueprint_release_binding,
            publication=publication,
        )
        replay = bool(publication.get("idempotent_replay"))
        return _success(
            request,
            result,
            status_code=200 if replay else 201,
            created=not replay,
        )
    except DataProductConflictError as exc:
        return _error(
            request,
            409,
            "data_product_blueprint_release_conflict",
            str(exc),
        )
    except DataProductNotFoundError as exc:
        return _error(
            request,
            404,
            "data_product_blueprint_release_not_found",
            str(exc),
        )
    except DataProductRegistryError as exc:
        return _error(
            request,
            503,
            "data_product_registry_unavailable",
            str(exc),
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "data_product_blueprint_release_invalid",
            "Blueprint DataProduct release does not satisfy the platform contract",
            details,
        )


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


async def ingest_entity_authority_batch(request: Request) -> JSONResponse:
    """Ingest one typed authority batch under the authenticated tenant."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        ENTITY_AUTHORITY_BATCH_INGEST,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, EntityAuthorityBatchRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Request tenant_id must match the authenticated tenant",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    actor_field = "created_by" if submission.batch_type == "link_types" else "recorded_by"
    if any(getattr(item, actor_field) != principal.actor_ref for item in submission.items):
        return _error(
            request,
            403,
            "actor_mismatch",
            f"{actor_field} must match the authenticated actor",
        )
    try:
        result = await asyncio.to_thread(execute_entity_authority_batch, submission)
        return _success(request, result)
    except (EntityLinkAuthorityError, TemporalEntityAuthorityError) as exc:
        return _entity_authority_error(request, exc)


async def reconcile_entity_data_package(request: Request) -> JSONResponse:
    """Reconcile one sealed Chongqing package under the tenant authority."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        CHONGQING_DATA_PACKAGE_RECONCILE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(
        request,
        ChongqingDataPackageReconciliationRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    if submission.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Request tenant_id must match the authenticated tenant",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    if submission.recorded_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "recorded_by must match the authenticated actor",
        )
    try:
        result = await asyncio.to_thread(
            execute_chongqing_data_package_reconciliation,
            submission,
        )
        return _success(request, result)
    except ChongqingDataPackageReconciliationServiceError as exc:
        if isinstance(exc, ChongqingDataPackageReconciliationServiceConflictError):
            status = 409
        elif isinstance(exc, ChongqingDataPackageReconciliationServiceForbiddenError):
            status = 403
        elif isinstance(exc, ChongqingDataPackageReconciliationServiceValidationError):
            status = 422
        elif isinstance(
            exc,
            ChongqingDataPackageReconciliationServiceConfigurationError,
        ):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))
    except ChongqingDataPackageReconciliationError as exc:
        return _error(
            request,
            409,
            "chongqing_data_package_reconciliation_conflict",
            str(exc),
        )
    except (EntityLinkAuthorityError, TemporalEntityAuthorityError) as exc:
        return _entity_authority_error(request, exc)


async def execute_postgis_projection_repair_plan(request: Request) -> JSONResponse:
    """Execute one sealed plan against an explicitly configured PostGIS target."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        POSTGIS_PROJECTION_REPAIR_EXECUTE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, PostGISProjectionRepairRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.plan.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Repair plan tenant_id must match the authenticated tenant",
        )
    if submission.checkpointed_by != principal.actor_ref:
        return _error(
            request,
            403,
            "checkpoint_actor_mismatch",
            "checkpointed_by must match the authenticated subject",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.plan.plan_idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the sealed repair plan",
        )
    try:
        result = await asyncio.to_thread(execute_postgis_projection_repair, submission)
        return _success(request, result)
    except PostGISProjectionServiceError as exc:
        if isinstance(exc, PostGISProjectionServiceValidationError):
            status = 422
        elif isinstance(exc, PostGISProjectionServiceForbiddenError):
            status = 403
        elif isinstance(exc, PostGISProjectionServiceConflictError):
            status = 409
        elif isinstance(exc, PostGISProjectionServiceConfigurationError):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))


async def execute_vector_projection_repair_plan(request: Request) -> JSONResponse:
    """Execute one sealed plan against an explicitly configured pgvector target."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        VECTOR_PROJECTION_REPAIR_EXECUTE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, VectorProjectionRepairRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.plan.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Repair plan tenant_id must match the authenticated tenant",
        )
    if submission.checkpointed_by != principal.actor_ref:
        return _error(
            request,
            403,
            "checkpoint_actor_mismatch",
            "checkpointed_by must match the authenticated subject",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.plan.plan_idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the sealed repair plan",
        )
    try:
        result = await asyncio.to_thread(execute_vector_projection_repair, submission)
        return _success(request, result)
    except VectorProjectionServiceError as exc:
        if isinstance(exc, VectorProjectionServiceValidationError):
            status = 422
        elif isinstance(exc, VectorProjectionServiceForbiddenError):
            status = 403
        elif isinstance(exc, VectorProjectionServiceConflictError):
            status = 409
        elif isinstance(exc, VectorProjectionServiceConfigurationError):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))


async def execute_rdf_projection_repair_plan(request: Request) -> JSONResponse:
    """Execute one sealed plan against an explicitly configured Fuseki target."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        RDF_PROJECTION_REPAIR_EXECUTE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, RDFProjectionRepairRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.plan.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Repair plan tenant_id must match the authenticated tenant",
        )
    if submission.checkpointed_by != principal.actor_ref:
        return _error(
            request,
            403,
            "checkpoint_actor_mismatch",
            "checkpointed_by must match the authenticated subject",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.plan.plan_idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the sealed repair plan",
        )
    try:
        result = await asyncio.to_thread(execute_rdf_projection_repair, submission)
        return _success(request, result)
    except RDFProjectionServiceError as exc:
        if isinstance(exc, RDFProjectionServiceValidationError):
            status = 422
        elif isinstance(exc, RDFProjectionServiceForbiddenError):
            status = 403
        elif isinstance(exc, RDFProjectionServiceConflictError):
            status = 409
        elif isinstance(exc, RDFProjectionServiceConfigurationError):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))


async def execute_lakehouse_projection_repair_plan(request: Request) -> JSONResponse:
    """Execute one sealed plan against an explicitly configured Iceberg table."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        LAKEHOUSE_PROJECTION_REPAIR_EXECUTE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, LakehouseProjectionRepairRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.plan.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Repair plan tenant_id must match the authenticated tenant",
        )
    if submission.checkpointed_by != principal.actor_ref:
        return _error(
            request,
            403,
            "checkpoint_actor_mismatch",
            "checkpointed_by must match the authenticated subject",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.plan.plan_idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the sealed repair plan",
        )
    try:
        result = await asyncio.to_thread(execute_lakehouse_projection_repair, submission)
        return _success(request, result)
    except LakehouseProjectionServiceError as exc:
        if isinstance(exc, LakehouseProjectionServiceValidationError):
            status = 422
        elif isinstance(exc, LakehouseProjectionServiceForbiddenError):
            status = 403
        elif isinstance(exc, LakehouseProjectionServiceConflictError):
            status = 409
        elif isinstance(exc, LakehouseProjectionServiceConfigurationError):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))


async def execute_object_projection_repair_plan(request: Request) -> JSONResponse:
    """Execute one sealed plan against an explicitly configured S3 object."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        OBJECT_PROJECTION_REPAIR_EXECUTE,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, ObjectProjectionRepairRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.plan.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Repair plan tenant_id must match the authenticated tenant",
        )
    if submission.checkpointed_by != principal.actor_ref:
        return _error(
            request,
            403,
            "checkpoint_actor_mismatch",
            "checkpointed_by must match the authenticated subject",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.plan.plan_idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the sealed repair plan",
        )
    try:
        result = await asyncio.to_thread(execute_object_projection_repair, submission)
        return _success(request, result)
    except ObjectProjectionServiceError as exc:
        if isinstance(exc, ObjectProjectionServiceValidationError):
            status = 422
        elif isinstance(exc, ObjectProjectionServiceForbiddenError):
            status = 403
        elif isinstance(exc, ObjectProjectionServiceConflictError):
            status = 409
        elif isinstance(exc, ObjectProjectionServiceConfigurationError):
            status = 503
        else:
            status = 500
        return _error(request, status, exc.code, str(exc))


async def submit_entity_data_package_reconciliation_job(
    request: Request,
) -> JSONResponse:
    """Durably enqueue an asynchronous Chongqing package reconciliation job."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, ChongqingDataPackageReconciliationRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Request tenant_id must match the authenticated tenant",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    if submission.recorded_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "recorded_by must match the authenticated actor",
        )
    try:
        result = await asyncio.to_thread(
            submit_chongqing_data_package_reconciliation_job,
            submission,
        )
        return _success(request, result, status_code=202)
    except ChongqingDataPackageReconciliationJobError as exc:
        status = (
            403
            if isinstance(exc, ChongqingDataPackageReconciliationJobForbiddenError)
            else 422
            if isinstance(exc, ChongqingDataPackageReconciliationJobValidationError)
            else 409
            if not isinstance(exc, ChongqingDataPackageReconciliationJobConfigurationError)
            else 503
        )
        return _error(request, status, exc.code, str(exc))


async def get_entity_data_package_reconciliation_job(
    request: Request,
) -> JSONResponse:
    """Read one asynchronous reconciliation job under the authenticated tenant."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET,
    )
    if contract_error is not None:
        return contract_error
    try:
        job_id = UUID(request.path_params["job_id"])
        query = ChongqingDataPackageReconciliationJobQuery(job_id=job_id)
        result = await asyncio.to_thread(
            get_chongqing_data_package_reconciliation_job,
            query,
            tenant_id=principal.tenant_id,
        )
        return _success(request, result)
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_job_id", "job_id must be a UUID")
    except ChongqingDataPackageReconciliationJobNotFoundError as exc:
        return _error(request, 404, exc.code, str(exc))
    except ChongqingDataPackageReconciliationJobError as exc:
        return _error(request, 503, exc.code, str(exc))


async def cancel_entity_data_package_reconciliation_job(
    request: Request,
) -> JSONResponse:
    """Request cooperative cancellation at the next atomic authority boundary."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL,
    )
    if contract_error is not None:
        return contract_error
    try:
        job_id = UUID(request.path_params["job_id"])
    except (KeyError, ValueError):
        return _error(request, 400, "invalid_job_id", "job_id must be a UUID")
    try:
        body = await request.json()
    except Exception:
        return _error(request, 400, "invalid_json", "Request body must be JSON")
    if not isinstance(body, dict):
        return _error(request, 422, "contract_validation_failed", "Request body must be an object")
    try:
        submission = ChongqingDataPackageReconciliationJobCancelRequest.model_validate(
            {**body, "job_id": job_id, "requested_by": principal.actor_ref}
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Request does not satisfy the platform contract",
            _validation_details(exc),
        )
    try:
        result = await asyncio.to_thread(
            cancel_chongqing_data_package_reconciliation_job,
            submission,
            tenant_id=principal.tenant_id,
        )
        status = 202 if result.status == "cancel_requested" else 200
        return _success(request, result, status_code=status)
    except ChongqingDataPackageReconciliationJobNotFoundError as exc:
        return _error(request, 404, exc.code, str(exc))
    except ChongqingDataPackageReconciliationJobError as exc:
        status = (
            503
            if isinstance(exc, ChongqingDataPackageReconciliationJobConfigurationError)
            else 422
            if isinstance(exc, ChongqingDataPackageReconciliationJobValidationError)
            else 403
            if isinstance(exc, ChongqingDataPackageReconciliationJobForbiddenError)
            else 409
        )
        return _error(request, status, exc.code, str(exc))


async def record_entity_lineage_event(request: Request) -> JSONResponse:
    """Record one atomic merge, split, or replacement under the tenant authority."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(request, ENTITY_LINEAGE_RECORD)
    if contract_error is not None:
        return contract_error
    submission = await _parse(request, EntityLineageRequest)
    if isinstance(submission, JSONResponse):
        return submission
    if submission.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Request tenant_id must match the authenticated tenant",
        )
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    if submission.recorded_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "recorded_by must match the authenticated actor",
        )
    try:
        result = await asyncio.to_thread(EntityLineageAuthority().record, submission)
        return _success(request, result)
    except EntityLineageAuthorityError as exc:
        return _entity_authority_error(request, exc)


async def generate_federated_projection_compensation_proposal(
    request: Request,
) -> JSONResponse:
    """Generate a read-only, snapshot-bound compensation proposal.

    This route never persists a proposal, selects a mutating candidate, or
    calls a provider.  A later operator workflow may use the returned
    evidence to request the separately governed action/approval path.
    """

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(
        request,
        FederatedProjectionCompensationProposalRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    if submission.snapshot.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Recovery snapshot tenant_id must match the authenticated tenant",
        )
    try:
        proposal = await asyncio.to_thread(
            build_federated_projection_compensation_proposal,
            submission.plans,
            submission.snapshot,
        )
    except FederatedProjectionCompensationProposalError as exc:
        return _error(
            request,
            422,
            "compensation_proposal_validation_failed",
            str(exc),
        )
    return _success(request, proposal)


async def get_federated_projection_compensation_proposal(
    request: Request,
) -> JSONResponse:
    """Read current and immutable proposal history for one tenant-bound run."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET,
    )
    if contract_error is not None:
        return contract_error
    if request.query_params:
        return _error(
            request,
            422,
            "unexpected_query_parameters",
            "Compensation proposal lookup does not accept query parameters",
        )
    try:
        query = FederatedProjectionCompensationProposalReadRequest.model_validate(
            {"run_id": request.path_params.get("run_id")}
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Request does not satisfy the platform contract",
            _validation_details(exc),
        )
    try:
        result = await asyncio.to_thread(
            _federated_compensation_proposal_store(principal.tenant_id).lookup,
            query.run_id,
        )
    except FederatedProjectionCompensationProposalConfigurationError as exc:
        return _error(
            request,
            503,
            "compensation_proposal_authority_unavailable",
            str(exc),
        )
    except FederatedProjectionCompensationProposalForbiddenError as exc:
        return _error(
            request,
            403,
            "compensation_proposal_authority_forbidden",
            str(exc),
        )
    except FederatedProjectionCompensationProposalValidationError as exc:
        return _error(
            request,
            422,
            "compensation_proposal_lookup_invalid",
            str(exc),
        )
    except FederatedProjectionCompensationProposalAuthorityError as exc:
        return _error(
            request,
            500,
            "compensation_proposal_authority_error",
            str(exc),
        )
    if result is None:
        return _error(
            request,
            404,
            "compensation_proposal_not_found",
            "No persisted compensation proposal exists for this federated run",
        )
    return _success(request, result)


async def assess_federated_projection_compensation_rules(
    request: Request,
) -> JSONResponse:
    """Assess submitted customer rule contracts without authorizing a mutation."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(
        request,
        FederatedProjectionCompensationRuleAssessmentRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    if submission.proposal.tenant_id != principal.tenant_id:
        return _error(
            request,
            403,
            "tenant_mismatch",
            "Compensation proposal tenant_id must match the authenticated tenant",
        )
    try:
        trust_registry = await asyncio.to_thread(
            load_customer_compensation_approval_trust_registry
        )
        assessment = await asyncio.to_thread(
            assess_customer_compensation_rules,
            submission.proposal,
            submission.rules,
            trust_registry,
        )
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return _error(
            request,
            500,
            "customer_approval_trust_registry_configuration_error",
            str(exc),
        )
    except CustomerCompensationRuleError as exc:
        return _error(
            request,
            422,
            "compensation_rule_assessment_failed",
            str(exc),
        )
    return _success(request, assessment)


async def assess_persisted_federated_projection_compensation_rules(
    request: Request,
) -> JSONResponse:
    """Assess persisted proposal/rule current state without caller overrides."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS,
    )
    if contract_error is not None:
        return contract_error
    if request.query_params:
        return _error(
            request,
            422,
            "unexpected_query_parameters",
            "Persisted compensation rule assessment accepts only path run_id",
        )
    try:
        query = (
            FederatedProjectionCompensationRuleAuthorityAssessmentRequest.model_validate(
                {"run_id": request.path_params.get("run_id")}
            )
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Request does not satisfy the platform contract",
            _validation_details(exc),
        )
    try:
        result = await asyncio.to_thread(
            _federated_compensation_rule_store(principal.tenant_id).assess_current,
            query.run_id,
        )
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return _error(
            request,
            500,
            "customer_approval_trust_registry_configuration_error",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return _error(
            request,
            503,
            "customer_compensation_rule_authority_unavailable",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return _error(
            request,
            403,
            "customer_compensation_rule_authority_forbidden",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return _error(
            request,
            422,
            "customer_compensation_rule_assessment_invalid",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return _error(
            request,
            500,
            "customer_compensation_rule_authority_error",
            str(exc),
        )
    if result is None:
        return _error(
            request,
            404,
            "compensation_proposal_not_found",
            "No persisted compensation proposal exists for this federated run",
        )
    return _success(request, result)


async def request_federated_projection_compensation_approval(
    request: Request,
) -> JSONResponse:
    """Create a review-only ApprovalCase for one trusted selected candidate."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(
        request,
        FederatedProjectionCompensationApprovalCaseRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    try:
        result = await asyncio.to_thread(
            _federated_compensation_approval_service(
                principal.tenant_id
            ).request_review,
            submission,
            requester_subject=principal.actor_ref,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
    except FederatedProjectionCompensationApprovalNotFoundError as exc:
        return _error(
            request,
            404,
            "compensation_proposal_not_found",
            str(exc),
        )
    except FederatedProjectionCompensationApprovalError as exc:
        return _error(
            request,
            422,
            "compensation_approval_not_reviewable",
            str(exc),
        )
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return _error(
            request,
            500,
            "customer_approval_trust_registry_configuration_error",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return _error(
            request,
            503,
            "customer_compensation_rule_authority_unavailable",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return _error(
            request,
            403,
            "customer_compensation_rule_authority_forbidden",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return _error(
            request,
            422,
            "customer_compensation_rule_assessment_invalid",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return _error(
            request,
            500,
            "customer_compensation_rule_authority_error",
            str(exc),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)
    return _success(
        request,
        result,
        status_code=201 if result.created else 200,
        created=result.created,
    )


async def request_federated_projection_compensation_execution_approval(
    request: Request,
) -> JSONResponse:
    """Create a separate execution-verdict ApprovalCase without execution."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST,
    )
    if contract_error is not None:
        return contract_error
    submission = await _parse(
        request,
        FederatedProjectionCompensationExecutionApprovalRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    header_key = request.headers.get("idempotency-key")
    if header_key and header_key != submission.idempotency_key:
        return _error(
            request,
            409,
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
        )
    try:
        result = await asyncio.to_thread(
            _federated_compensation_execution_approval_service(
                principal.tenant_id
            ).request_execution_authorization,
            submission,
            requester_subject=principal.actor_ref,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
    except FederatedProjectionCompensationApprovalNotFoundError as exc:
        return _error(
            request,
            404,
            "compensation_proposal_not_found",
            str(exc),
        )
    except FederatedProjectionCompensationApprovalError as exc:
        return _error(
            request,
            422,
            "compensation_execution_approval_not_reviewable",
            str(exc),
        )
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return _error(
            request,
            500,
            "customer_approval_trust_registry_configuration_error",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return _error(
            request,
            503,
            "customer_compensation_rule_authority_unavailable",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return _error(
            request,
            403,
            "customer_compensation_rule_authority_forbidden",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return _error(
            request,
            422,
            "customer_compensation_rule_assessment_invalid",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return _error(
            request,
            500,
            "customer_compensation_rule_authority_error",
            str(exc),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)
    return _success(
        request,
        result,
        status_code=201 if result.created else 200,
        created=result.created,
    )


async def get_federated_projection_compensation_rules(
    request: Request,
) -> JSONResponse:
    """Read tenant-bound current/history customer compensation rule evidence."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    contract_error = _capability_contract_guard(
        request,
        FEDERATED_PROJECTION_COMPENSATION_RULE_GET,
    )
    if contract_error is not None:
        return contract_error
    unexpected = set(request.query_params) - {"rule_id"}
    if unexpected:
        return _error(
            request,
            422,
            "unexpected_query_parameters",
            "Customer compensation rule lookup accepts only rule_id",
        )
    try:
        query = CustomerCompensationRuleAuthorityReadRequest.model_validate(
            {"rule_id": request.query_params.get("rule_id")}
        )
    except ValidationError as exc:
        return _error(
            request,
            422,
            "contract_validation_failed",
            "Request does not satisfy the platform contract",
            _validation_details(exc),
        )
    try:
        result = await asyncio.to_thread(
            _federated_compensation_rule_store(principal.tenant_id).lookup,
            query.rule_id,
        )
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return _error(
            request,
            503,
            "customer_compensation_rule_authority_unavailable",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return _error(
            request,
            403,
            "customer_compensation_rule_authority_forbidden",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return _error(
            request,
            422,
            "customer_compensation_rule_lookup_invalid",
            str(exc),
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return _error(
            request,
            500,
            "customer_compensation_rule_authority_error",
            str(exc),
        )
    if query.rule_id is not None and result.rule_count == 0:
        return _error(
            request,
            404,
            "customer_compensation_rule_not_found",
            "No persisted customer compensation rule exists for this rule_id",
        )
    return _success(request, result)


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


def _incident_notification_ids(
    request: Request,
    *,
    require_notification: bool,
) -> tuple[UUID, UUID | None] | JSONResponse:
    try:
        incident_id = UUID(request.path_params["incident_id"])
        notification_id = (
            UUID(request.path_params["notification_id"])
            if require_notification
            else None
        )
    except (KeyError, ValueError):
        field = "incident_id or notification_id" if require_notification else "incident_id"
        return _error(
            request,
            400,
            "invalid_incident_notification_id",
            f"{field} must be a UUID",
        )
    return incident_id, notification_id


async def list_incident_notifications(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    identifiers = _incident_notification_ids(request, require_notification=False)
    if isinstance(identifiers, JSONResponse):
        return identifiers
    incident_id, _ = identifiers
    try:
        notifications = await asyncio.to_thread(
            _gateway().list_incident_notifications,
            principal.tenant_id,
            incident_id,
        )
        return _success(
            request,
            IncidentNotificationListResponse(
                items=notifications,
                count=len(notifications),
            ),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def list_incident_notification_recoveries(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    identifiers = _incident_notification_ids(request, require_notification=True)
    if isinstance(identifiers, JSONResponse):
        return identifiers
    incident_id, notification_id = identifiers
    assert notification_id is not None
    try:
        recoveries = await asyncio.to_thread(
            _gateway().incident_notification_recoveries,
            principal.tenant_id,
            incident_id,
            notification_id,
        )
        return _success(
            request,
            IncidentNotificationRecoveryListResponse(
                items=recoveries,
                recovery_count=len(recoveries),
            ),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def recover_incident_notification(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    if principal.subject_type is not SubjectType.HUMAN:
        return _error(
            request,
            403,
            "human_identity_required",
            "DataIncident notification recovery requires a human identity",
        )
    if principal.role != "admin":
        return _error(
            request,
            403,
            "incident_notification_recovery_admin_required",
            "DataIncident notification recovery requires an administrator",
        )
    recovery = await _parse(request, IncidentNotificationRecoveryRequest)
    if isinstance(recovery, JSONResponse):
        return recovery
    identifiers = _incident_notification_ids(request, require_notification=True)
    if isinstance(identifiers, JSONResponse):
        return identifiers
    incident_id, notification_id = identifiers
    assert notification_id is not None
    try:
        notification = await asyncio.to_thread(
            _gateway().recover_incident_notification,
            principal.tenant_id,
            incident_id,
            notification_id,
            expected_attempt_count=recovery.expected_attempt_count,
            expected_receipt_sha256=recovery.expected_receipt_sha256,
            actor_subject=principal.actor_ref,
            reason=recovery.reason,
        )
        return _success(request, notification)
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


async def search_metadata_fabric_bindings(request: Request) -> JSONResponse:
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    raw_system = request.query_params.get("system")
    query = request.query_params.get("q")
    try:
        system = MetadataFabricSystem(raw_system) if raw_system else None
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        return _error(
            request,
            400,
            "invalid_metadata_fabric_search_query",
            "system, limit, or offset is invalid",
        )
    if query is not None and len(query.strip()) > 128:
        return _error(
            request,
            400,
            "invalid_metadata_fabric_search_query",
            "q must be at most 128 characters",
        )
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_metadata_fabric_search_query",
            "metadata fabric search is outside the supported range",
        )
    try:
        page: MetadataFabricBindingPage = await asyncio.to_thread(
            _gateway().search_metadata_fabric_bindings,
            principal.tenant_id,
            query=query,
            system=system,
            limit=limit,
            offset=offset,
        )
        return _success(
            request,
            MetadataFabricBindingSearchResponse(
                items=page.items,
                count=len(page.items),
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            ),
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


def _read_metadata_provider_binding(binding: MetadataFabricBinding) -> ProviderReadResult:
    with MetadataProviderReadService.from_env() as service:
        return service.read(binding)


def _search_metadata_provider(
    tenant_id: str,
    *,
    system: MetadataFabricSystem,
    provider_namespace: str,
    object_type: str,
    query: str | None,
    limit: int,
    offset: int,
) -> ProviderSearchPage:
    with MetadataProviderSearchService.from_env() as service:
        return service.search(
            tenant_id,
            system=system,
            provider_namespace=provider_namespace,
            object_type=object_type,
            query=query,
            limit=limit,
            offset=offset,
        )


def _metadata_provider_namespace_is_bound(
    tenant_id: str,
    system: MetadataFabricSystem,
    provider_namespace: str,
) -> bool:
    """Resolve exact namespace binding without trusting one fuzzy page."""
    offset = 0
    while offset <= 10_000:
        page = _gateway().search_metadata_fabric_bindings(
            tenant_id,
            query=provider_namespace,
            system=system,
            limit=100,
            offset=offset,
        )
        if any(
            binding.external_namespace == provider_namespace for binding in page.items
        ):
            return True
        if not page.has_more:
            return False
        offset += page.limit
    return False


async def read_metadata_fabric_provider_binding(request: Request) -> JSONResponse:
    """Read one provider object through an authenticated GDA crosswalk.

    The provider remains the metadata authority. GDA returns only the typed
    observation contract and never persists or echoes the provider document.
    """
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    resource_urn = request.query_params.get("resource_urn", "")
    raw_system = request.query_params.get("system")
    try:
        urn_tenant = parse_resource_urn(resource_urn)["tenant_id"]
        system = MetadataFabricSystem(raw_system) if raw_system else None
    except ValueError:
        return _error(
            request,
            400,
            "invalid_metadata_fabric_provider_read_query",
            "resource_urn and system must identify a valid Metadata Fabric binding",
        )
    if system is None:
        return _error(
            request,
            400,
            "invalid_metadata_fabric_provider_read_query",
            "system is required for provider read",
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
        if not bindings:
            return _error(
                request,
                404,
                "metadata_fabric_binding_not_found",
                "No Metadata Fabric binding exists for the requested resource and system",
            )
        if len(bindings) != 1:
            return _error(
                request,
                409,
                "metadata_fabric_binding_ambiguous",
                "Provider read requires exactly one binding for the resource and system",
            )
        result = await asyncio.to_thread(_read_metadata_provider_binding, bindings[0])
        return _success(request, MetadataProviderReadResponse(result=result))
    except MetadataProviderReadError as exc:
        status = 503 if exc.retryable or exc.code == "provider_read_configuration_error" else 502
        return _error(request, status, exc.code, str(exc))
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)


async def search_metadata_fabric_provider(request: Request) -> JSONResponse:
    """Discover candidates inside an already-bound provider namespace."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    provider_namespace = request.query_params.get("provider_namespace", "").strip()
    raw_system = request.query_params.get("system")
    object_type = request.query_params.get("object_type", "table").strip()
    query = request.query_params.get("q")
    try:
        system = MetadataFabricSystem(raw_system) if raw_system else None
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        return _error(
            request,
            400,
            "invalid_metadata_provider_search_query",
            "system, limit, or offset is invalid",
        )
    if system not in {
        MetadataFabricSystem.GRAVITINO,
        MetadataFabricSystem.OPENMETADATA,
    }:
        return _error(
            request,
            400,
            "unsupported_metadata_provider_search",
            "provider-backed search does not support this provider",
        )
    if not provider_namespace or len(provider_namespace) > 512:
        return _error(
            request,
            400,
            "invalid_metadata_provider_search_query",
            "provider_namespace is required and must be at most 512 characters",
        )
    if query is not None and len(query.strip()) > 128:
        return _error(
            request,
            400,
            "invalid_metadata_provider_search_query",
            "q must be at most 128 characters",
        )
    if system is MetadataFabricSystem.OPENMETADATA and (
        query is None or not query.strip()
    ):
        return _error(
            request,
            400,
            "invalid_metadata_provider_search_query",
            "OpenMetadata provider search requires q",
        )
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        return _error(
            request,
            400,
            "invalid_metadata_provider_search_query",
            "provider search is outside the supported range",
        )
    try:
        namespace_bound = await asyncio.to_thread(
            _metadata_provider_namespace_is_bound,
            principal.tenant_id,
            system,
            provider_namespace,
        )
        if not namespace_bound:
            return _error(
                request,
                404,
                "metadata_provider_namespace_not_bound",
                "Provider search requires an existing same-tenant binding",
            )
        page = await asyncio.to_thread(
            _search_metadata_provider,
            principal.tenant_id,
            system=system,
            provider_namespace=provider_namespace,
            object_type=object_type,
            query=query,
            limit=limit,
            offset=offset,
        )
        return _success(request, MetadataProviderSearchResponse(page=page))
    except MetadataProviderReadError as exc:
        if exc.code == "provider_search_query_invalid":
            status = 400
        elif exc.code.endswith("configuration_error"):
            status = 503
        else:
            status = 503 if exc.retryable else 502
        return _error(request, status, exc.code, str(exc))
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


async def create_resource_version_postgis_architecture_assessment(
    request: Request,
) -> JSONResponse:
    """Admit a compatibility- and lineage-bound schema drift review."""
    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, ArchitectureChangeAssessmentRequest)
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
            _architecture_change_assessment_service().request_review,
            tenant_id=principal.tenant_id,
            resource_version_id=resource_version_id,
            baseline_snapshot=submission.baseline_schema_snapshot,
            candidate_snapshot=submission.candidate_schema_snapshot,
            baseline_schema_artifact_id=submission.baseline_schema_artifact_id,
            candidate_schema_artifact_id=submission.candidate_schema_artifact_id,
            requester_subject=principal.actor_ref,
            request_reason=submission.request_reason,
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
            requested_at=requested_at,
            expires_at=requested_at + timedelta(hours=submission.expires_in_hours),
            evaluated_at=requested_at,
            max_lineage_depth=submission.max_lineage_depth,
            max_lineage_edges=submission.max_lineage_edges,
        )
        return _success(
            request,
            ArchitectureChangeAssessmentResponse(
                base_review=result.base_review,
                compatibility=result.compatibility,
                impact=result.impact,
                review=result.review,
                approval_case=result.approval_case,
            ),
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ArchitectureChangeAssessmentError as exc:
        return _error(
            request,
            422,
            "architecture_change_assessment_failed",
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
            "architecture_change_assessment_invalid",
            "Architecture change assessment does not satisfy the platform contract",
            details,
        )


def _successor_adoption_actor_error(
    request: Request,
    principal: GatewayPrincipal,
    successor: ResourceVersion,
    architecture: DataArchitectureRegistration,
) -> JSONResponse | None:
    """Ensure the authenticated workload owns the final successor authority."""

    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Architecture successor adoption requires a workload identity",
        )
    if successor.created_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "successor created_by must match authenticated actor",
        )
    if architecture.binding.bound_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "successor architecture bound_by must match authenticated actor",
        )
    return None


async def create_resource_version_architecture_successor_adoption_approval(
    request: Request,
) -> JSONResponse:
    """Build a successor plan and create its second, adoption-specific ApprovalCase."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, ArchitectureSuccessorAdoptionApprovalRequest)
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
    successor = submission.successor_resource_version
    architecture = submission.successor_architecture
    if mismatch := _tenant_matches(request, principal, successor.tenant_id):
        return mismatch
    if successor.predecessor_version_id != resource_version_id:
        return _error(
            request,
            422,
            "successor_predecessor_mismatch",
            "successor predecessor_version_id must match resource_version_id",
        )
    if actor_error := _successor_adoption_actor_error(
        request,
        principal,
        successor,
        architecture,
    ):
        return actor_error
    requested_at = _utc_now()
    try:
        result = await asyncio.to_thread(
            _architecture_successor_adoption_service().request_adoption,
            tenant_id=principal.tenant_id,
            assessed_approval_case_ref=submission.assessed_approval_case_ref,
            successor_resource_version=successor,
            successor_architecture=architecture,
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
            ArchitectureSuccessorAdoptionApprovalResponse(
                plan=result.plan,
                approval_case=result.approval_case,
            ),
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ArchitectureSuccessorAdoptionError as exc:
        return _error(
            request,
            422,
            "architecture_successor_adoption_invalid",
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
            "architecture_successor_adoption_invalid",
            "Architecture successor adoption does not satisfy the platform contract",
            details,
        )


async def adopt_resource_version_architecture_successor(request: Request) -> JSONResponse:
    """Atomically adopt an approved, immutable successor plan."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(request, ArchitectureSuccessorAdoptionExecuteRequest)
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
    plan = submission.plan
    if mismatch := _tenant_matches(request, principal, plan.tenant_id):
        return mismatch
    if plan.predecessor_resource_version_id != resource_version_id:
        return _error(
            request,
            422,
            "successor_predecessor_mismatch",
            "successor plan predecessor must match resource_version_id",
        )
    if actor_error := _successor_adoption_actor_error(
        request,
        principal,
        plan.successor_resource_version,
        plan.successor_architecture,
    ):
        return actor_error
    try:
        result = await asyncio.to_thread(
            _architecture_successor_adoption_service().adopt,
            plan,
            adoption_approval_case_ref=submission.adoption_approval_case_ref,
            evaluated_at=_utc_now(),
        )
        return _success(
            request,
            result.value,
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except PlatformGatewayError as exc:
        return _gateway_error(request, exc)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "architecture_successor_adoption_invalid",
            "Architecture successor adoption does not satisfy the platform contract",
            details,
        )


def _successor_data_product_release_actor_error(
    request: Request,
    principal: GatewayPrincipal,
    plan: ArchitectureSuccessorDataProductReleasePlan,
) -> JSONResponse | None:
    """Keep release authority with the workload named by the product version."""

    if principal.subject_type is not SubjectType.WORKLOAD:
        return _error(
            request,
            403,
            "workload_identity_required",
            "Architecture successor product release requires a workload identity",
        )
    if plan.successor_data_product_version.published_by != principal.actor_ref:
        return _error(
            request,
            403,
            "actor_mismatch",
            "successor product published_by must match authenticated actor",
        )
    return None


async def create_architecture_successor_data_product_release_approval(
    request: Request,
) -> JSONResponse:
    """Create the independent ApprovalCase required before product publication."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(
        request,
        ArchitectureSuccessorDataProductReleaseApprovalRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    plan = submission.plan
    if mismatch := _tenant_matches(request, principal, plan.tenant_id):
        return mismatch
    if actor_error := _successor_data_product_release_actor_error(
        request,
        principal,
        plan,
    ):
        return actor_error
    requested_at = _utc_now()
    try:
        result = await asyncio.to_thread(
            _architecture_successor_data_product_release_service().request_release,
            plan,
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
            ArchitectureSuccessorDataProductReleaseApprovalResponse(
                plan=result.plan,
                approval_case=result.approval_case,
            ),
            status_code=201 if result.created else 200,
            created=result.created,
        )
    except ArchitectureSuccessorDataProductReleaseError as exc:
        return _error(
            request,
            422,
            "architecture_successor_data_product_release_invalid",
            str(exc),
        )
    except ApprovalCaseAuthorityError as exc:
        return _approval_case_error(request, exc)
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "architecture_successor_data_product_release_invalid",
            "Architecture successor product release does not satisfy the platform contract",
            details,
        )


async def publish_architecture_successor_data_product_release(
    request: Request,
) -> JSONResponse:
    """Atomically publish an approved successor DataProduct release plan."""

    principal = _principal(request)
    if isinstance(principal, JSONResponse):
        return principal
    submission = await _parse(
        request,
        ArchitectureSuccessorDataProductReleasePublishRequest,
    )
    if isinstance(submission, JSONResponse):
        return submission
    plan = submission.plan
    if mismatch := _tenant_matches(request, principal, plan.tenant_id):
        return mismatch
    if actor_error := _successor_data_product_release_actor_error(
        request,
        principal,
        plan,
    ):
        return actor_error
    try:
        publication = await asyncio.to_thread(
            _architecture_successor_data_product_release_service().publish,
            plan,
            release_approval_case_ref=submission.release_approval_case_ref,
            idempotency_key=submission.idempotency_key,
            reason=submission.reason,
        )
        return _success(
            request,
            ArchitectureSuccessorDataProductReleasePublishResponse(
                plan=plan,
                publication=publication,
            ),
            status_code=201 if not publication.get("idempotent_replay") else 200,
            created=not publication.get("idempotent_replay"),
        )
    except DataProductConflictError as exc:
        return _error(
            request,
            409,
            "architecture_successor_data_product_release_conflict",
            str(exc),
        )
    except DataProductNotFoundError as exc:
        return _error(
            request,
            404,
            "architecture_successor_data_product_release_not_found",
            str(exc),
        )
    except DataProductRegistryError as exc:
        return _error(
            request,
            503,
            "data_product_registry_unavailable",
            str(exc),
        )
    except ArchitectureSuccessorDataProductReleaseError as exc:
        return _error(
            request,
            422,
            "architecture_successor_data_product_release_invalid",
            str(exc),
        )
    except (ValidationError, ValueError) as exc:
        details = _validation_details(exc) if isinstance(exc, ValidationError) else None
        return _error(
            request,
            422,
            "architecture_successor_data_product_release_invalid",
            "Architecture successor product release does not satisfy the platform contract",
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
            f"{base}/approval-cases/escalation-batches",
            schedule_approval_case_batch_escalation,
            method="POST",
            operation_id="platform_schedule_approval_case_batch_escalation",
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
            f"{base}/data-product-blueprints",
            create_data_product_blueprint,
            method="POST",
            operation_id="platform_create_data_product_blueprint",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/preview",
            preview_data_product_blueprint,
            method="POST",
            operation_id="platform_preview_data_product_blueprint",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/tests",
            test_data_product_blueprint,
            method="POST",
            operation_id="platform_test_data_product_blueprint",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs",
            admit_data_product_blueprint_test_run,
            method="POST",
            operation_id="platform_admit_data_product_blueprint_test_run",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/execute",
            execute_data_product_blueprint_test_run,
            method="POST",
            operation_id="platform_execute_data_product_blueprint_test_run",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/providers/duckdb/execute",
            execute_data_product_blueprint_duckdb_test_run,
            method="POST",
            operation_id="platform_execute_data_product_blueprint_duckdb_test_run",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/fail",
            fail_data_product_blueprint_test_run,
            method="POST",
            operation_id="platform_fail_data_product_blueprint_test_run",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/cancel",
            cancel_data_product_blueprint_test_run,
            method="POST",
            operation_id="platform_cancel_data_product_blueprint_test_run",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/reconcile",
            reconcile_data_product_blueprint_test_provider,
            method="POST",
            operation_id="platform_reconcile_data_product_blueprint_test_provider",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/cancel-timeout",
            record_data_product_blueprint_provider_cancellation_timeout,
            method="POST",
            operation_id="platform_record_data_product_blueprint_provider_cancellation_timeout",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/test-runs/{{run_id}}/retry",
            retry_data_product_blueprint_test_provider,
            method="POST",
            operation_id="platform_retry_data_product_blueprint_test_provider",
        ),
        _platform_route(
            f"{base}/data-product-blueprints/reviews",
            create_data_product_blueprint_review,
            method="POST",
            operation_id="platform_create_data_product_blueprint_review",
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
            f"{base}/entity-authority/batches",
            ingest_entity_authority_batch,
            method="POST",
            operation_id="platform_ingest_entity_authority_batch",
        ),
        _platform_route(
            f"{base}/entity-authority/reconciliations",
            reconcile_entity_data_package,
            method="POST",
            operation_id="platform_reconcile_entity_data_package",
        ),
        _platform_route(
            f"{base}/projections/postgis/repairs",
            execute_postgis_projection_repair_plan,
            method="POST",
            operation_id="platform_execute_postgis_projection_repair",
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-proposals",
            generate_federated_projection_compensation_proposal,
            method="POST",
            operation_id="platform_generate_federated_compensation_proposal",
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-proposals/{{run_id}}",
            get_federated_projection_compensation_proposal,
            method="GET",
            operation_id="platform_get_federated_compensation_proposal",
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-rule-assessments",
            assess_federated_projection_compensation_rules,
            method="POST",
            operation_id="platform_assess_federated_compensation_rules",
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-rule-assessments/{{run_id}}",
            assess_persisted_federated_projection_compensation_rules,
            method="GET",
            operation_id=(
                "platform_assess_persisted_federated_compensation_rules"
            ),
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-approval-cases",
            request_federated_projection_compensation_approval,
            method="POST",
            operation_id="platform_request_federated_compensation_approval",
        ),
        _platform_route(
            f"{base}/projections/federated/"
            "compensation-execution-approval-cases",
            request_federated_projection_compensation_execution_approval,
            method="POST",
            operation_id=(
                "platform_request_federated_compensation_execution_approval"
            ),
        ),
        _platform_route(
            f"{base}/projections/federated/compensation-rules",
            get_federated_projection_compensation_rules,
            method="GET",
            operation_id="platform_get_federated_compensation_rules",
        ),
        _platform_route(
            f"{base}/projections/vector/repairs",
            execute_vector_projection_repair_plan,
            method="POST",
            operation_id="platform_execute_vector_projection_repair",
        ),
        _platform_route(
            f"{base}/projections/rdf/repairs",
            execute_rdf_projection_repair_plan,
            method="POST",
            operation_id="platform_execute_rdf_projection_repair",
        ),
        _platform_route(
            f"{base}/projections/lakehouse/repairs",
            execute_lakehouse_projection_repair_plan,
            method="POST",
            operation_id="platform_execute_lakehouse_projection_repair",
        ),
        _platform_route(
            f"{base}/projections/object-store/repairs",
            execute_object_projection_repair_plan,
            method="POST",
            operation_id="platform_execute_object_projection_repair",
        ),
        _platform_route(
            f"{base}/entity-authority/reconciliation-jobs",
            submit_entity_data_package_reconciliation_job,
            method="POST",
            operation_id="platform_submit_entity_data_package_reconciliation_job",
        ),
        _platform_route(
            f"{base}/entity-authority/reconciliation-jobs/{{job_id}}",
            get_entity_data_package_reconciliation_job,
            method="GET",
            operation_id="platform_get_entity_data_package_reconciliation_job",
        ),
        _platform_route(
            f"{base}/entity-authority/reconciliation-jobs/{{job_id}}/cancel",
            cancel_entity_data_package_reconciliation_job,
            method="POST",
            operation_id="platform_cancel_entity_data_package_reconciliation_job",
        ),
        _platform_route(
            f"{base}/entity-authority/lineage-events",
            record_entity_lineage_event,
            method="POST",
            operation_id="platform_record_entity_lineage_event",
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
            f"{base}/incidents/{{incident_id}}/notifications",
            list_incident_notifications,
            method="GET",
            operation_id="platform_list_incident_notifications",
        ),
        _platform_route(
            f"{base}/incidents/{{incident_id}}/notifications/{{notification_id}}/recoveries",
            list_incident_notification_recoveries,
            method="GET",
            operation_id="platform_list_incident_notification_recoveries",
        ),
        _platform_route(
            f"{base}/incidents/{{incident_id}}/notifications/{{notification_id}}/recoveries",
            recover_incident_notification,
            method="POST",
            operation_id="platform_recover_incident_notification",
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
            f"{base}/metadata-fabric/bindings/search",
            search_metadata_fabric_bindings,
            method="GET",
            operation_id="platform_search_metadata_fabric_bindings",
        ),
        _platform_route(
            f"{base}/metadata-fabric/provider-read",
            read_metadata_fabric_provider_binding,
            method="GET",
            operation_id="platform_read_metadata_fabric_provider",
        ),
        _platform_route(
            f"{base}/metadata-fabric/provider-search",
            search_metadata_fabric_provider,
            method="GET",
            operation_id="platform_search_metadata_fabric_provider",
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
            f"{base}/resource-versions/{{resource_version_id}}/architecture/reconciliation/postgis-assessments/approval-cases",
            create_resource_version_postgis_architecture_assessment,
            method="POST",
            operation_id="platform_create_resource_version_postgis_architecture_assessment",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/architecture/successor-adoptions/approval-cases",
            create_resource_version_architecture_successor_adoption_approval,
            method="POST",
            operation_id="platform_create_resource_version_architecture_successor_adoption_approval",
        ),
        _platform_route(
            f"{base}/resource-versions/{{resource_version_id}}/architecture/successor-adoptions",
            adopt_resource_version_architecture_successor,
            method="POST",
            operation_id="platform_adopt_resource_version_architecture_successor",
        ),
        _platform_route(
            f"{base}/data-products/architecture-successor-releases/approval-cases",
            create_architecture_successor_data_product_release_approval,
            method="POST",
            operation_id="platform_create_architecture_successor_data_product_release_approval",
        ),
        _platform_route(
            f"{base}/data-products/architecture-successor-releases",
            publish_architecture_successor_data_product_release,
            method="POST",
            operation_id="platform_publish_architecture_successor_data_product_release",
        ),
        _platform_route(
            f"{base}/data-products/blueprint-releases",
            publish_data_product_blueprint_release,
            method="POST",
            operation_id="platform_publish_data_product_blueprint_release",
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
            f"{base}/gis/services/{{service_id}}/control-projection",
            get_gis_service_control_projection,
            method="GET",
            operation_id="platform_get_gis_service_control_projection",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/slo",
            get_gis_service_slo,
            method="GET",
            operation_id="platform_get_gis_service_slo",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/slo-binding",
            bind_gis_service_slo,
            method="POST",
            operation_id="platform_bind_gis_service_slo",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}",
            get_gis_service_deployment,
            method="GET",
            operation_id="platform_get_gis_service_deployment",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}/events",
            list_gis_service_deployment_events,
            method="GET",
            operation_id="platform_list_gis_service_deployment_events",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}/observations",
            record_gis_service_deployment_observation,
            method="POST",
            operation_id="platform_record_gis_service_deployment_observation",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}/terminal-settlements",
            settle_gis_service_deployment_terminal,
            method="POST",
            operation_id="platform_settle_gis_service_deployment_terminal",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments",
            register_gis_service_deployment,
            method="POST",
            operation_id="platform_register_gis_service_deployment",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}/transitions",
            transition_gis_service_deployment,
            method="POST",
            operation_id="platform_transition_gis_service_deployment",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/deployments/{{deployment_revision_id}}/endpoints",
            register_gis_service_endpoint,
            method="POST",
            operation_id="platform_register_gis_service_endpoint",
        ),
        _platform_route(
            f"{base}/gis/services/{{service_id}}/activation",
            activate_gis_service_endpoint,
            method="POST",
            operation_id="platform_activate_gis_service_endpoint",
        ),
        _platform_route(
            f"{base}/gis/tiles/{{release_key}}/{{z:int}}/{{x:int}}/{{y:int}}.pbf",
            get_gis_mvt_tile,
            method="GET",
            operation_id="platform_get_gis_mvt_tile",
        ),
        _platform_route(
            f"{base}/gis/features/{{release_key}}/collections/{{collection_id}}/items",
            get_gis_ogc_api_features_items,
            method="GET",
            operation_id="platform_get_gis_ogc_api_features_items",
        ),
    ]
