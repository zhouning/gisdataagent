"""Least-privilege transaction scripts for the AR-1 platform control gateway."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .consumer_binding import (
    ConsumerBinding,
    ConsumerBindingMigrationNotification,
    ConsumerBindingMigrationNotificationEnvelope,
    ConsumerBindingMigrationNotificationSettlement,
    ConsumerBindingMigrationState,
    ConsumerMigrationNotificationDeliveryStatus,
    build_consumer_binding_notification_terminal_state,
)
from .data_architecture_ledger import (
    ArchitectureProviderObservation,
    ArchitectureReconciliationStatus,
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitecture,
    ResourceVersionArchitectureBinding,
    ResourceVersionArchitectureReconciliation,
    SchemaVersion,
)
from .data_product_blueprint import (
    DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA,
    DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA,
    DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA,
    DataProductBlueprintProviderCancellationTimeout,
    DataProductBlueprintProviderCancellationTimeoutRequest,
    DataProductBlueprintProviderReconcileRequest,
    DataProductBlueprintProviderReconciliation,
    DataProductBlueprintProviderRetry,
    DataProductBlueprintProviderRetryRequest,
    DataProductBlueprintTestCancellationRequest,
    DataProductBlueprintTestExecution,
    DataProductBlueprintTestExecutionFailureRequest,
    DataProductBlueprintTestExecutionRequest,
    DataProductBlueprintTestRunAdmission,
    DataProductBlueprintTestRunRequest,
    build_data_product_blueprint_test_report,
    compile_data_product_blueprint,
    data_product_blueprint_provider_retry_backoff_seconds,
)
from .dataops_cancel import (
    DataOpsCancelSpec,
    DataOpsCancelWriteResult,
    build_dataops_cancel_submission,
    dataops_cancel_command_id,
    dataops_cancel_lock_keys,
)
from .dataops_invocation import parse_dataops_invocation_version
from .dataops_manual import (
    DataOpsManualTriggerSpec,
    ManualTriggerWriteResult,
    build_manual_dataops_submission,
    dataops_manual_lock_keys,
    dataops_manual_run_id,
)
from .dataops_schedule import (
    DataOpsScheduleWindowSpec,
    ScheduleWindowWriteResult,
    build_scheduled_dataops_submission,
    dataops_schedule_idempotency_key,
    dataops_schedule_lock_keys,
)
from .db_engine import get_engine
from .duckdb_blueprint_object_store import (
    DuckDBBlueprintObjectStore,
    S3ObjectVersionEvidence,
    blueprint_s3_input_allowed,
    blueprint_s3_output_uri,
    parse_blueprint_s3_uri,
    validate_blueprint_s3_input_prefixes,
    validate_blueprint_s3_location,
)
from .duckdb_blueprint_provider import (
    DUCKDB_BLUEPRINT_PROVIDER_RECEIPT_SCHEMA,
    DUCKDB_BLUEPRINT_WORKLOAD,
    DuckDBBlueprintExecutionRequest,
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
    DuckDBBlueprintProviderError,
    DuckDBBlueprintProviderReceipt,
    DuckDBBlueprintProviderUnavailableError,
    verify_duckdb_blueprint_output,
)
from .gis_mvt_cache_purge import (
    GISMVTCachePurgeStatus,
    GISMVTCachePurgeTask,
)
from .gis_provider_runtime import martin_mvt_warmup_sample_set_fingerprint
from .gis_service_consumer_binding_migration import (
    GISServiceConsumerBindingMigrationImpact,
)
from .gis_service_control_plane import (
    CachePolicyVersion,
    EndpointProtocol,
    EndpointRevision,
    GISServiceControlProjection,
    GISServiceDefinitionVersion,
    GISServiceDeploymentTerminalSettlement,
    GISServiceSLOBinding,
    GISServiceType,
    LayerDefinitionVersion,
    MVTServingProjectionVersion,
    MVTServingRelationAttestation,
    ServiceDeploymentEvent,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    ServicePolicyBinding,
    ServiceReleaseBinding,
    StyleDefinitionVersion,
    TileMatrixSetDefinitionVersion,
    service_deployment_terminal_state,
)
from .gis_service_endpoint_warmup import (
    GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA,
    GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
    GISServiceEndpointWarmupExecutionPlan,
    GISServiceEndpointWarmupReceipt,
    GISServiceEndpointWarmupRunAdmission,
    GISServiceEndpointWarmupRunRequest,
    GISServiceEndpointWarmupSettlement,
    gis_service_endpoint_warmup_fingerprint,
    gis_service_endpoint_warmup_plan_fingerprint,
)
from .gis_service_migration_cutover import (
    GISServiceMigrationCutover,
    GISServiceMigrationCutoverRequest,
)
from .gis_service_migration_rollback import (
    GISServiceMigrationRollback,
    GISServiceMigrationRollbackRequest,
)
from .gis_service_slo_reconciliation import (
    GISServiceSLOReconciliationTask,
)
from .jqdltb_serving_release import JqdltbServingReleaseBinding
from .master_data_authority import MasterEntityVersion
from .metadata_fabric import (
    METADATA_FABRIC_MIGRATION,
    MasterMetadataProjectionChange,
    MasterMetadataProjectionEnvelope,
    MetadataChange,
    MetadataFabricBinding,
    MetadataFabricSystem,
    MetadataLineageProjectionEnvelope,
)
from .platform_authorization import (
    AuthorizationEvidenceError,
    parse_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    TERMINAL_RUN_STATUSES,
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    DataIncident,
    DataIncidentEvent,
    FrameworkAttemptObservation,
    FrameworkKind,
    IncidentNotification,
    IncidentNotificationEnvelope,
    IncidentNotificationRecoveryEvent,
    IncidentSeverity,
    IncidentStatus,
    LineageEvent,
    LineageEventType,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    PlatformDefinitionVersion,
    PlatformRun,
    PlatformRunEvent,
    PolicyDecision,
    QualityResult,
    QualityVerdict,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunStatus,
    RunSuccessEvidence,
    SubjectContext,
    SubjectType,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    data_incident_fingerprint,
    parse_resource_urn,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from .platform_lineage import (
    ImpactChangeType,
    ImpactDisposition,
    ImpactedDataProduct,
    ImpactQualitySignal,
    ImpactReviewReason,
    LineageDirection,
    LineageGraph,
    LineageGraphEdge,
    LineageGraphNode,
    LineageImpactAssessment,
    LineageQuerySpec,
    LineageTruncationReason,
    lineage_impact_fingerprint,
)
from .platform_openlineage import MAX_GENERATED_EDGES
from .platform_run_events import (
    PlatformRunEventDelivery,
    PlatformRunEventEnvelope,
)
from .service_consumer_binding import ServiceConsumerBinding
from .service_consumer_binding_renewal import ServiceConsumerBindingRenewal
from .service_consumer_binding_revocation import ServiceConsumerBindingRevocation
from .spatial_anonymization_run import (
    SPATIAL_ANONYMIZATION_SEMANTIC_TYPE,
    SpatialAnonymizationRunSpec,
    SpatialAnonymizationRunWriteResult,
    build_spatial_anonymization_submission,
    parse_spatial_anonymization_version,
    spatial_anonymization_lock_keys,
)

if TYPE_CHECKING:
    from .architecture_successor_adoption import ArchitectureSuccessorPlan
    from .postgresql_cdc_recovery_controller import (
        PostgresqlCdcRecoveryObservationRecord,
    )

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
GATEWAY_SCHEMA_VERSION = "gda.platform_gateway.v1"
GATEWAY_ROLE_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "094_platform_control_gateway.sql"
)
COMMAND_OUTBOX_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "095_platform_command_outbox.sql"
)
SUCCESS_VERDICT_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "096_platform_success_verdict.sql"
)
BLUEPRINT_TEST_SUCCESS_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "197_blueprint_test_execution_success.sql"
)
CANCEL_COMMAND_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "097_platform_cancel_command.sql"
)
DATA_INCIDENT_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "098_platform_data_incident.sql"
)
INCIDENT_NOTIFICATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "099_platform_incident_notification_outbox.sql"
)
INCIDENT_NOTIFICATION_RECEIPT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "226_incident_notification_provider_receipt.sql"
)
INCIDENT_NOTIFICATION_RECEIPT_STRICT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "227_incident_notification_receipt_strict_authority.sql"
)
INCIDENT_NOTIFICATION_RECOVERY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "228_incident_notification_governed_recovery.sql"
)
CONSUMER_BINDING_NOTIFICATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "152_consumer_binding_migration_notification_outbox.sql"
)
GIS_SERVICE_CONSUMER_MIGRATION_IMPACT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "217_gis_service_consumer_binding_migration_impact.sql"
)
GIS_SERVICE_MIGRATION_CUTOVER_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "218_gis_service_migration_cutover.sql"
)
GIS_SERVICE_MIGRATION_ROLLBACK_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "219_gis_service_migration_rollback.sql"
)
GIS_SERVICE_ENDPOINT_WARMUP_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "220_gis_service_endpoint_warmup.sql"
)
GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "221_gis_service_endpoint_warmup_command.sql"
)
GIS_MVT_CACHE_PURGE_OUTBOX_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "222_gis_mvt_cache_purge_outbox.sql"
)
GIS_SERVICE_SLO_BINDING_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "223_gis_service_slo_binding.sql"
)
GIS_SERVICE_SLO_RECONCILIATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "224_gis_service_slo_reconciliation_outbox.sql"
)
GIS_SERVICE_SLO_INCIDENT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "225_gis_service_slo_incident_authority.sql"
)
GIS_SERVICE_SLO_RECONCILIATION_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "gis_service_slo_reconciliation_worker.py"
)
GIS_SERVICE_CONTROL_PLANE_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "153_gis_service_control_plane.sql"
)
JQDLTB_SERVING_RELEASE_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "235_jqdltb_serving_release_binding.sql"
)
JQDLTB_SERVING_ENDPOINT_PROMOTION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "236_jqdltb_serving_endpoint_promotion_gate.sql"
)
MVT_SERVING_RELATION_ATTESTATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "237_mvt_serving_relation_attestation.sql"
)
OGC_API_FEATURES_ENDPOINT_CONTRACT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "238_ogc_api_features_endpoint_contract.sql"
)
RUN_EVENT_DELIVERY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "129_platform_run_event_delivery_outbox.sql"
)
INCIDENT_SUBJECT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "123_resource_bound_data_incident.sql"
)
MASTER_DATA_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "124_reference_master_data_authority.sql"
)
MASTER_RESOURCE_PROJECTION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "125_master_data_resource_projection.sql"
)
MASTER_METADATA_PROJECTION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "126_master_metadata_projection_outbox.sql"
)
USER_TENANT_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "093_app_user_tenant_context.sql"
)
GATEWAY_ROUTES_SOURCE = Path(__file__).resolve().parent / "api" / "platform_gateway_routes.py"
COMMAND_CONSUMER_SOURCE = Path(__file__).resolve().parent / "dolphinscheduler_command_consumer.py"
COMMAND_WORKER_SOURCE = Path(__file__).resolve().parent / "dolphinscheduler_command_worker.py"
GIS_SERVICE_ENDPOINT_WARMUP_CONSUMER_SOURCE = (
    Path(__file__).resolve().parent / "gis_service_endpoint_warmup_consumer.py"
)
GIS_SERVICE_ENDPOINT_WARMUP_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "gis_service_endpoint_warmup_worker.py"
)
INCIDENT_NOTIFICATION_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "incident_notification_worker.py"
)
CONSUMER_BINDING_NOTIFICATION_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "consumer_binding_notification_worker.py"
)
RUN_EVENT_DELIVERY_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "platform_run_event_worker.py"
)
MASTER_METADATA_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "openmetadata_master_data_worker.py"
)
SCHEDULE_CONTROLLER_SOURCE = Path(__file__).resolve().parent / "dataops_schedule.py"
MANUAL_CONTROLLER_SOURCE = Path(__file__).resolve().parent / "dataops_manual.py"
CANCEL_CONTROLLER_SOURCE = Path(__file__).resolve().parent / "dataops_cancel.py"
_TENANT_ADAPTER = TypeAdapter(TenantId)


class PlatformGatewayError(RuntimeError):
    code = "platform_gateway_error"


class GatewayConfigurationError(PlatformGatewayError):
    code = "gateway_configuration_error"


class GatewayConflictError(PlatformGatewayError):
    code = "platform_conflict"


class GatewayNotFoundError(PlatformGatewayError):
    code = "platform_not_found"


class GatewayForbiddenError(PlatformGatewayError):
    code = "platform_forbidden"


class GatewayValidationError(PlatformGatewayError):
    code = "platform_validation_error"


class GatewayTraversalLimitError(GatewayValidationError):
    code = "lineage_traversal_incomplete"


class GatewayUnavailableError(PlatformGatewayError):
    code = "platform_unavailable"


@dataclass(frozen=True)
class GatewayWriteResult:
    value: BaseModel
    created: bool


@dataclass(frozen=True)
class PostgresqlCdcRecoveryWriteResult:
    artifact: Artifact
    artifact_created: bool
    ledger_created: bool


@dataclass(frozen=True)
class GatewayResourceVersionPage:
    items: tuple[ResourceVersion, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class MetadataFabricBindingPage:
    items: tuple[MetadataFabricBinding, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class CallbackWriteResult:
    observation: FrameworkAttemptObservation
    command: PlatformCommand | None
    observation_created: bool
    command_created: bool
    ignored_terminal: bool


@dataclass(frozen=True)
class CancellationIncidentWriteResult:
    run: PlatformRun
    incident: DataIncident
    incident_created: bool


@dataclass(frozen=True)
class GISServiceEndpointWarmupSettlementResult:
    run: PlatformRun
    receipt: GISServiceEndpointWarmupReceipt
    evidence_created: bool
    receipt_created: bool


class DefinitionRegistration(BaseModel):
    """Atomic Resource + ResourceVersion + logical definition registration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource: Resource
    resource_version: ResourceVersion
    definition: PlatformDefinitionVersion

    @model_validator(mode="after")
    def _consistent_definition_identity(self) -> DefinitionRegistration:
        resource = self.resource
        version = self.resource_version
        definition = self.definition
        if resource.resource_kind != "definition":
            raise ValueError("definition resource must use kind 'definition'")
        if len({resource.tenant_id, version.tenant_id, definition.tenant_id}) != 1:
            raise ValueError("definition registration tenants must match")
        if resource.resource_urn != version.resource_urn:
            raise ValueError("definition ResourceVersion must bind the Resource")
        if version.resource_urn != definition.definition_urn:
            raise ValueError("definition URN must bind the ResourceVersion")
        if version.resource_version_id != definition.definition_version_id:
            raise ValueError("definition version IDs must match")
        if version.content_sha256 != definition.definition_sha256:
            raise ValueError("definition hashes must match")
        return self


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _as_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class PlatformGateway:
    """Synchronous PostgreSQL gateway with transaction-local role and tenant."""

    def __init__(
        self,
        engine=None,
        *,
        blueprint_duckdb_output_root: str | Path | None = None,
        blueprint_duckdb_result_backend: str | None = None,
        blueprint_duckdb_output_s3_bucket: str | None = None,
        blueprint_duckdb_output_s3_prefix: str | None = None,
        blueprint_duckdb_input_s3_prefixes: tuple[str, ...] | None = None,
        blueprint_duckdb_object_store: DuckDBBlueprintObjectStore | None = None,
    ):
        self._engine = engine
        configured_root = blueprint_duckdb_output_root or os.environ.get(
            "GDA_BLUEPRINT_DUCKDB_OUTPUT_ROOT"
        )
        self._blueprint_duckdb_output_root = (
            None if configured_root is None else Path(configured_root).expanduser()
        )
        self._blueprint_duckdb_result_backend = str(
            blueprint_duckdb_result_backend
            or os.environ.get("GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND")
            or "local"
        ).strip()
        if self._blueprint_duckdb_result_backend not in {"local", "s3"}:
            raise GatewayConfigurationError(
                "DuckDB Blueprint result backend must be local or s3"
            )
        self._blueprint_duckdb_output_s3_bucket = str(
            blueprint_duckdb_output_s3_bucket
            or os.environ.get("GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_BUCKET")
            or ""
        ).strip()
        self._blueprint_duckdb_output_s3_prefix = str(
            blueprint_duckdb_output_s3_prefix
            or os.environ.get("GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_PREFIX")
            or "blueprint-duckdb-results/v1"
        ).strip()
        configured_input_prefixes = blueprint_duckdb_input_s3_prefixes
        if configured_input_prefixes is None:
            configured_input_prefixes = tuple(
                item.strip()
                for item in str(
                    os.environ.get("GDA_BLUEPRINT_DUCKDB_INPUT_S3_PREFIXES") or ""
                ).split(",")
                if item.strip()
            )
        self._blueprint_duckdb_input_s3_prefixes = configured_input_prefixes
        if self._blueprint_duckdb_result_backend == "s3":
            try:
                validate_blueprint_s3_location(
                    self._blueprint_duckdb_output_s3_bucket,
                    self._blueprint_duckdb_output_s3_prefix,
                )
                self._blueprint_duckdb_input_s3_prefixes = (
                    validate_blueprint_s3_input_prefixes(
                        self._blueprint_duckdb_input_s3_prefixes
                    )
                )
            except ValueError as exc:
                raise GatewayConfigurationError(
                    "DuckDB Blueprint S3 result location is invalid"
                ) from exc
        self._blueprint_duckdb_object_store = blueprint_duckdb_object_store

    def _blueprint_duckdb_output_uri(self, tenant_id: str, run_id: UUID) -> str:
        if self._blueprint_duckdb_result_backend == "s3":
            return blueprint_s3_output_uri(
                self._blueprint_duckdb_output_s3_bucket,
                self._blueprint_duckdb_output_s3_prefix,
                tenant_id,
                run_id,
            )
        root = self._blueprint_duckdb_output_root
        if root is None:
            raise GatewayConfigurationError(
                "GDA_BLUEPRINT_DUCKDB_OUTPUT_ROOT is required for DuckDB Blueprint admission"
            )
        if not root.is_absolute():
            raise GatewayConfigurationError(
                "DuckDB Blueprint output root must be an absolute path"
            )
        return (root.resolve() / f"{run_id}.parquet").as_uri()

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None:
            raise GatewayUnavailableError("platform database is not configured")
        if engine.dialect.name != "postgresql":
            raise GatewayConfigurationError("platform gateway requires PostgreSQL")
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        engine = self._get_engine()
        try:
            with engine.connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise GatewayConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except PlatformGatewayError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise GatewayConflictError("platform state conflict") from exc
            if state == "P0002":
                raise GatewayNotFoundError("platform object was not found") from exc
            if state == "42501":
                raise GatewayForbiddenError("platform tenant access was denied") from exc
            if state in {"22023", "22P02", "23502", "23503", "23514", "55000"}:
                raise GatewayValidationError("platform contract was rejected") from exc
            raise GatewayUnavailableError("platform database operation failed") from exc
        except SQLAlchemyError as exc:
            raise GatewayUnavailableError("platform database operation failed") from exc

    @staticmethod
    def _load_resource(connection, tenant_id: str, resource_urn: str) -> Resource | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, resource_urn, resource_kind, authority_system,
                       authority_locator, owner_ref, governance_ref, technical_refs
                FROM gda_control.resource
                WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn
                """
                ),
                {"tenant_id": tenant_id, "resource_urn": resource_urn},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["governance_ref"] = _as_json(value["governance_ref"])
        value["technical_refs"] = _as_json(value["technical_refs"])
        return Resource.model_validate(value)

    def _put_resource(self, connection, resource: Resource) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref, governance_ref, technical_refs
                ) VALUES (
                    :tenant_id, :resource_urn, :resource_kind, :authority_system,
                    :authority_locator, :owner_ref,
                    CAST(:governance_ref AS jsonb), CAST(:technical_refs AS jsonb)
                )
                ON CONFLICT DO NOTHING
                RETURNING resource_urn
                """
            ),
            {
                **resource.model_dump(mode="json", exclude={"governance_ref", "technical_refs"}),
                "governance_ref": _json(resource.governance_ref),
                "technical_refs": _json(list(resource.technical_refs)),
            },
        ).first()
        stored = self._load_resource(connection, resource.tenant_id, resource.resource_urn)
        if stored is None or stored != resource:
            raise GatewayConflictError("Resource identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    def register_resource(self, resource: Resource) -> GatewayWriteResult:
        with self._transaction(resource.tenant_id) as connection:
            return self._put_resource(connection, resource)

    def get_resource(self, tenant_id: str, resource_urn: str) -> Resource:
        """Return one tenant-scoped resource through the gateway role."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            resource = self._load_resource(connection, tenant, resource_urn)
            if resource is None:
                raise GatewayNotFoundError("Resource was not found")
            return resource

    @staticmethod
    def _load_metadata_fabric_binding(
        connection,
        tenant_id: str,
        binding_id: UUID,
    ) -> MetadataFabricBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, resource_urn, system,
                           binding_kind, external_namespace, external_object_id,
                           external_object_type, external_version_ref,
                           binding_sha256, created_by, created_at
                    FROM gda_control.metadata_fabric_binding
                    WHERE tenant_id = :tenant_id AND binding_id = :binding_id
                    """
                ),
                {"tenant_id": tenant_id, "binding_id": binding_id},
            )
            .mappings()
            .one_or_none()
        )
        return MetadataFabricBinding.model_validate(dict(row)) if row is not None else None

    @staticmethod
    def _load_openmetadata_binding(
        connection,
        tenant_id: str,
        resource_urn: str,
    ) -> MetadataFabricBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, resource_urn, system,
                           binding_kind, external_namespace, external_object_id,
                           external_object_type, external_version_ref,
                           binding_sha256, created_by, created_at
                    FROM gda_control.metadata_fabric_binding
                    WHERE tenant_id = :tenant_id
                      AND resource_urn = :resource_urn
                      AND system = 'openmetadata'
                    """
                ),
                {"tenant_id": tenant_id, "resource_urn": resource_urn},
            )
            .mappings()
            .one_or_none()
        )
        return MetadataFabricBinding.model_validate(dict(row)) if row is not None else None

    def _put_metadata_fabric_binding(
        self,
        connection,
        binding: MetadataFabricBinding,
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.metadata_fabric_binding (
                    tenant_id, binding_id, resource_urn, system,
                    binding_kind, external_namespace, external_object_id,
                    external_object_type, external_version_ref,
                    binding_sha256, created_by, created_at
                ) VALUES (
                    :tenant_id, :binding_id, :resource_urn, :system,
                    :binding_kind, :external_namespace, :external_object_id,
                    :external_object_type, :external_version_ref,
                    :binding_sha256, :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING binding_id
                """
            ),
            {
                **binding.model_dump(mode="python"),
                "system": binding.system.value,
                "binding_kind": binding.binding_kind.value,
            },
        ).first()
        stored = self._load_metadata_fabric_binding(
            connection,
            binding.tenant_id,
            binding.binding_id,
        )
        if stored is None or stored != binding:
            raise GatewayConflictError(
                "MetadataFabricBinding identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_metadata_fabric_binding(
        self,
        binding: MetadataFabricBinding,
    ) -> GatewayWriteResult:
        with self._transaction(binding.tenant_id) as connection:
            resource = self._load_resource(
                connection,
                binding.tenant_id,
                binding.resource_urn,
            )
            if resource is None:
                raise GatewayNotFoundError("Metadata Fabric Resource was not found")
            return self._put_metadata_fabric_binding(connection, binding)

    def list_metadata_fabric_bindings(
        self,
        tenant_id: str,
        resource_urn: str,
        *,
        system: MetadataFabricSystem | str | None = None,
    ) -> tuple[MetadataFabricBinding, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        resolved_system = MetadataFabricSystem(system).value if system is not None else None
        with self._transaction(tenant) as connection:
            resource = self._load_resource(connection, tenant, resource_urn)
            if resource is None:
                raise GatewayNotFoundError("Metadata Fabric Resource was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, binding_id, resource_urn, system,
                               binding_kind, external_namespace, external_object_id,
                               external_object_type, external_version_ref,
                               binding_sha256, created_by, created_at
                        FROM gda_control.metadata_fabric_binding
                        WHERE tenant_id = :tenant_id
                          AND resource_urn = :resource_urn
                          AND (CAST(:system AS TEXT) IS NULL OR system = :system)
                        ORDER BY system, external_namespace,
                                 external_object_type, external_object_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "resource_urn": resource_urn,
                        "system": resolved_system,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                MetadataFabricBinding.model_validate(dict(row)) for row in rows
            )

    def search_metadata_fabric_bindings(
        self,
        tenant_id: str,
        *,
        query: str | None = None,
        system: MetadataFabricSystem | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> MetadataFabricBindingPage:
        """Search only the tenant-scoped GDA crosswalk, never provider catalogs.

        This is the read bridge's deterministic discovery surface. OpenMetadata
        and Gravitino remain authoritative for their own metadata; this query
        searches the immutable external references that GDA is allowed to own.
        """
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
            raise GatewayValidationError(
                "metadata fabric search is outside the supported range"
            )
        normalized_query = query.strip() if query is not None else None
        if normalized_query == "":
            normalized_query = None
        if normalized_query is not None and len(normalized_query) > 128:
            raise GatewayValidationError(
                "metadata fabric search query must be at most 128 characters"
            )
        try:
            resolved_system = (
                MetadataFabricSystem(system).value if system is not None else None
            )
        except ValueError as exc:
            raise GatewayValidationError(
                "metadata fabric system is invalid"
            ) from exc
        escaped_query = (
            normalized_query.replace("!", "!!")
            .replace("%", "!%")
            .replace("_", "!_")
            if normalized_query is not None
            else None
        )
        query_pattern = (
            f"%{escaped_query}%" if escaped_query is not None else None
        )
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, binding_id, resource_urn, system,
                               binding_kind, external_namespace, external_object_id,
                               external_object_type, external_version_ref,
                               binding_sha256, created_by, created_at
                        FROM gda_control.metadata_fabric_binding
                        WHERE tenant_id = :tenant_id
                          AND (
                              CAST(:system AS TEXT) IS NULL
                              OR system = :system
                          )
                          AND (
                              CAST(:query_pattern AS TEXT) IS NULL
                              OR resource_urn ILIKE :query_pattern ESCAPE '!'
                              OR external_namespace ILIKE :query_pattern ESCAPE '!'
                              OR external_object_id ILIKE :query_pattern ESCAPE '!'
                              OR external_object_type ILIKE :query_pattern ESCAPE '!'
                          )
                        ORDER BY resource_urn, system, external_namespace,
                                 external_object_type, external_object_id,
                                 binding_id
                        LIMIT :page_limit OFFSET :page_offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "system": resolved_system,
                        "query_pattern": query_pattern,
                        "page_limit": limit + 1,
                        "page_offset": offset,
                    },
                )
                .mappings()
                .all()
            )
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            return MetadataFabricBindingPage(
                items=tuple(
                    MetadataFabricBinding.model_validate(dict(row))
                    for row in page_rows
                ),
                offset=offset,
                limit=limit,
                has_more=has_more,
            )

    @staticmethod
    def _load_consumer_binding(
        connection,
        tenant_id: str,
        binding_id: UUID,
    ) -> ConsumerBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, product_urn, consumer_ref,
                           purpose, scope, min_product_version,
                           max_product_version, credential_ref, quota,
                           expires_at, compatibility_fingerprint,
                           compatibility_evidence, binding_sha256,
                           created_by, created_at
                      FROM gda_control.consumer_binding
                     WHERE tenant_id = :tenant_id AND binding_id = :binding_id
                    """
                ),
                {"tenant_id": tenant_id, "binding_id": binding_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        for key in ("scope", "quota", "compatibility_evidence"):
            value[key] = _as_json(value[key])
        return ConsumerBinding.model_validate(value)

    def register_consumer_binding(
        self,
        binding: ConsumerBinding,
    ) -> GatewayWriteResult:
        """Record one immutable binding through the SECURITY DEFINER recorder."""
        with self._transaction(binding.tenant_id) as connection:
            product_exists = connection.execute(
                text(
                    """
                    SELECT EXISTS(
                        SELECT 1
                          FROM gda_control.data_product
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                    )
                    """
                ),
                {
                    "tenant_id": binding.tenant_id,
                    "product_urn": binding.product_urn,
                },
            ).scalar_one()
            if not product_exists:
                raise GatewayNotFoundError("DataProduct was not found")
            result = connection.execute(
                text(
                    """
                    SELECT binding_id, created
                      FROM gda_control.record_consumer_binding(
                          :tenant_id,
                          CAST(:binding_id AS uuid),
                          :product_urn,
                          :consumer_ref,
                          :purpose,
                          CAST(:scope AS jsonb),
                          :min_product_version,
                          :max_product_version,
                          :credential_ref,
                          CAST(:quota AS jsonb),
                          :expires_at,
                          CAST(:compatibility_fingerprint AS char(64)),
                          CAST(:compatibility_evidence AS jsonb),
                          CAST(:binding_sha256 AS char(64)),
                          :created_by,
                          :created_at
                      )
                    """
                ),
                {
                    **binding.model_dump(
                        mode="python",
                        exclude={
                            "scope",
                            "quota",
                            "compatibility_evidence",
                        },
                    ),
                    "scope": _json(binding.scope),
                    "quota": _json(binding.quota),
                    "compatibility_evidence": _json(binding.compatibility_evidence),
                    "compatibility_fingerprint": binding.compatibility_fingerprint,
                    "binding_sha256": binding.binding_sha256,
                },
            ).mappings().one()
            stored = self._load_consumer_binding(
                connection, binding.tenant_id, binding.binding_id
            )
            if stored is None or stored != binding:
                raise GatewayConflictError(
                    "ConsumerBinding identity already has a different payload"
                )
            return GatewayWriteResult(stored, bool(result["created"]))

    def list_consumer_bindings(
        self,
        tenant_id: str,
        product_urn: str,
        *,
        include_expired: bool = False,
    ) -> tuple[ConsumerBinding, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, binding_id, product_urn, consumer_ref,
                               purpose, scope, min_product_version,
                               max_product_version, credential_ref, quota,
                               expires_at, compatibility_fingerprint,
                               compatibility_evidence, binding_sha256,
                               created_by, created_at
                          FROM gda_control.consumer_binding
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND (
                               :include_expired
                               OR expires_at > clock_timestamp()
                           )
                         ORDER BY consumer_ref, binding_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "product_urn": product_urn,
                        "include_expired": include_expired,
                    },
                )
                .mappings()
                .all()
            )
            values = []
            for row in rows:
                value = dict(row)
                for key in ("scope", "quota", "compatibility_evidence"):
                    value[key] = _as_json(value[key])
                values.append(ConsumerBinding.model_validate(value))
            return tuple(values)

    def get_active_consumer_binding_for_product_version(
        self,
        tenant_id: str,
        product_urn: str,
        product_version_id: UUID,
        consumer_ref: str,
    ) -> ConsumerBinding | None:
        """Resolve one active binding for an exact product version and subject.

        Version and expiry checks stay in the gateway transaction so protocol
        routes never need to read the control tables directly or duplicate the
        database authority's tenant policy.
        """
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT binding.tenant_id, binding.binding_id,
                               binding.product_urn, binding.consumer_ref,
                               binding.purpose, binding.scope,
                               binding.min_product_version,
                               binding.max_product_version,
                               binding.credential_ref, binding.quota,
                               binding.expires_at,
                               binding.compatibility_fingerprint,
                               binding.compatibility_evidence,
                               binding.binding_sha256, binding.created_by,
                               binding.created_at
                          FROM gda_control.consumer_binding AS binding
                          JOIN gda_control.data_product_version AS version
                            ON version.tenant_id = binding.tenant_id
                           AND version.product_urn = binding.product_urn
                           AND version.data_product_version_id = :product_version_id
                         WHERE binding.tenant_id = :tenant_id
                           AND binding.product_urn = :product_urn
                           AND binding.consumer_ref = :consumer_ref
                           AND binding.expires_at > clock_timestamp()
                           AND (
                               binding.min_product_version IS NULL
                               OR string_to_array(substr(version.version_key, 2), '.')::numeric[]
                                    >= string_to_array(
                                        substr(binding.min_product_version, 2), '.'
                                    )::numeric[]
                           )
                           AND (
                               binding.max_product_version IS NULL
                               OR string_to_array(substr(version.version_key, 2), '.')::numeric[]
                                    <= string_to_array(
                                        substr(binding.max_product_version, 2), '.'
                                    )::numeric[]
                           )
                         ORDER BY binding.binding_id
                         LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "product_urn": product_urn,
                        "product_version_id": product_version_id,
                        "consumer_ref": consumer_ref,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            value = dict(row)
            for key in ("scope", "quota", "compatibility_evidence"):
                value[key] = _as_json(value[key])
            return ConsumerBinding.model_validate(value)

    @staticmethod
    def _load_consumer_binding_migration_state(
        connection,
        tenant_id: str,
        migration_state_id: UUID,
    ) -> ConsumerBindingMigrationState | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, migration_state_id, binding_id,
                           product_urn, from_product_version_id,
                           to_product_version_id, state_version,
                           compatibility_conclusion, compatibility_evidence,
                           notification_status, notification_evidence,
                           migration_deadline, consumer_acknowledgement,
                           previous_state_sha256, recorded_by, recorded_at,
                           state_sha256
                      FROM gda_control.consumer_binding_migration_state
                     WHERE tenant_id = :tenant_id
                       AND migration_state_id = :migration_state_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "migration_state_id": migration_state_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        for key in (
            "compatibility_evidence",
            "notification_evidence",
            "consumer_acknowledgement",
        ):
            if value[key] is not None:
                value[key] = _as_json(value[key])
        return ConsumerBindingMigrationState.model_validate(value)

    def record_consumer_binding_migration_state(
        self,
        state: ConsumerBindingMigrationState,
    ) -> GatewayWriteResult:
        """Append a CAS-linked migration state through its guarded recorder."""
        with self._transaction(state.tenant_id) as connection:
            return self._record_consumer_binding_migration_state(connection, state)

    @classmethod
    def _record_consumer_binding_migration_state(
        cls,
        connection,
        state: ConsumerBindingMigrationState,
    ) -> GatewayWriteResult:
        acknowledgement = (
            state.consumer_acknowledgement.model_dump(mode="json")
            if state.consumer_acknowledgement is not None
            else None
        )
        result = connection.execute(
            text(
                """
                SELECT migration_state_id, created
                  FROM gda_control.record_consumer_binding_migration_state(
                      :tenant_id,
                      CAST(:migration_state_id AS uuid),
                      CAST(:binding_id AS uuid),
                      :product_urn,
                      CAST(:from_product_version_id AS uuid),
                      CAST(:to_product_version_id AS uuid),
                      :state_version,
                      :compatibility_conclusion,
                      CAST(:compatibility_evidence AS jsonb),
                      :notification_status,
                      CAST(:notification_evidence AS jsonb),
                      :migration_deadline,
                      CAST(:consumer_acknowledgement AS jsonb),
                      CAST(:previous_state_sha256 AS char(64)),
                      :recorded_by,
                      :recorded_at,
                      CAST(:state_sha256 AS char(64))
                  )
                """
            ),
            {
                **state.model_dump(
                    mode="python",
                    exclude={
                        "compatibility_evidence",
                        "notification_evidence",
                        "consumer_acknowledgement",
                    },
                ),
                "compatibility_conclusion": state.compatibility_conclusion.value,
                "compatibility_evidence": _json(state.compatibility_evidence),
                "notification_status": state.notification_status.value,
                "notification_evidence": _json(state.notification_evidence),
                "consumer_acknowledgement": (
                    _json(acknowledgement) if acknowledgement is not None else None
                ),
            },
        ).mappings().one()
        stored = cls._load_consumer_binding_migration_state(
            connection,
            state.tenant_id,
            state.migration_state_id,
        )
        if stored is None or stored != state:
            raise GatewayConflictError(
                "ConsumerBinding migration state has a different payload"
            )
        return GatewayWriteResult(stored, bool(result["created"]))

    def list_consumer_binding_migration_states(
        self,
        tenant_id: str,
        product_urn: str,
        *,
        binding_id: UUID | None = None,
    ) -> tuple[ConsumerBindingMigrationState, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, migration_state_id, binding_id,
                               product_urn, from_product_version_id,
                               to_product_version_id, state_version,
                               compatibility_conclusion,
                               compatibility_evidence, notification_status,
                               notification_evidence, migration_deadline,
                               consumer_acknowledgement, previous_state_sha256,
                               recorded_by, recorded_at, state_sha256
                          FROM gda_control.consumer_binding_migration_state
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND (
                               CAST(:binding_id AS uuid) IS NULL
                               OR binding_id = CAST(:binding_id AS uuid)
                           )
                         ORDER BY binding_id, from_product_version_id,
                                  to_product_version_id, state_version
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "product_urn": product_urn,
                        "binding_id": binding_id,
                    },
                )
                .mappings()
                .all()
            )
            values: list[ConsumerBindingMigrationState] = []
            for row in rows:
                value = dict(row)
                for key in (
                    "compatibility_evidence",
                    "notification_evidence",
                    "consumer_acknowledgement",
                ):
                    if value[key] is not None:
                        value[key] = _as_json(value[key])
                values.append(ConsumerBindingMigrationState.model_validate(value))
            return tuple(values)

    def record_gis_service_consumer_binding_migration_impact(
        self,
        impact: GISServiceConsumerBindingMigrationImpact,
    ) -> GatewayWriteResult:
        """Record one exact GIS release impact through the guarded recorder."""
        with self._transaction(impact.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT impact_id, created
                      FROM gda_control.record_gis_service_consumer_binding_migration_impact(
                          :tenant_id,
                          CAST(:impact_id AS uuid),
                          CAST(:source_service_consumer_binding_id AS uuid),
                          CAST(:source_binding_sha256 AS char(64)),
                          :service_urn, :consumer_ref,
                          CAST(:source_service_definition_version_id AS uuid),
                          CAST(:source_service_release_binding_id AS uuid),
                          CAST(:target_service_definition_version_id AS uuid),
                          CAST(:target_service_release_binding_id AS uuid),
                          :source_product_urn,
                          CAST(:from_product_version_id AS uuid),
                          CAST(:to_product_version_id AS uuid),
                          CAST(:migration_state_id AS uuid),
                          CAST(:notification_id AS uuid),
                          :recorded_by, :recorded_at,
                          CAST(:impact_sha256 AS char(64))
                      )
                    """
                ),
                impact.model_dump(mode="python"),
            ).mappings().one()
            stored = self._load_gis_service_consumer_binding_migration_impacts(
                connection, impact.tenant_id, impact.notification_id
            )
            matching = next(
                (item for item in stored if item.impact_id == impact.impact_id),
                None,
            )
            if matching is None or matching != impact:
                raise GatewayConflictError(
                    "GIS service migration impact identity has different content"
                )
            return GatewayWriteResult(matching, bool(result["created"]))

    def list_gis_service_consumer_binding_migration_impacts(
        self,
        tenant_id: str,
        incident_id: UUID,
        notification_id: UUID,
    ) -> tuple[GISServiceConsumerBindingMigrationImpact, ...]:
        """List exact GIS release impacts attached to one product notice."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            return self._load_gis_service_consumer_binding_migration_impacts(
                connection, tenant, notification_id
            )

    @staticmethod
    def _gis_service_migration_cutover_from_row(
        row,
    ) -> GISServiceMigrationCutover:
        return GISServiceMigrationCutover.model_validate(dict(row))

    def cutover_gis_service_migration(
        self,
        request: GISServiceMigrationCutoverRequest,
    ) -> GISServiceMigrationCutover:
        """Atomically move one service after every source consumer is ready."""
        with self._transaction(request.tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.cutover_gis_service_migration(
                              :tenant_id, CAST(:cutover_id AS uuid), :service_urn,
                              CAST(:source_endpoint_revision_id AS uuid),
                              CAST(:target_endpoint_revision_id AS uuid),
                              CAST(:source_service_definition_version_id AS uuid),
                              CAST(:source_service_release_binding_id AS uuid),
                              CAST(:target_service_definition_version_id AS uuid),
                              CAST(:target_service_release_binding_id AS uuid),
                              :source_product_urn,
                              CAST(:from_product_version_id AS uuid),
                              CAST(:to_product_version_id AS uuid),
                              :expected_state_version, :actor_subject, :reason,
                              :idempotency_key, :occurred_at
                          )
                        """
                    ),
                    request.model_dump(mode="python"),
                )
                .mappings()
                .one()
            )
            return self._gis_service_migration_cutover_from_row(row)

    def list_gis_service_migration_cutovers(
        self,
        tenant_id: str,
        service_urn: str,
    ) -> tuple[GISServiceMigrationCutover, ...]:
        """List immutable migration cutovers for one governed GIS service."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, cutover_id, service_urn,
                               source_endpoint_revision_id,
                               target_endpoint_revision_id,
                               source_service_definition_version_id,
                               source_service_release_binding_id,
                               target_service_definition_version_id,
                               target_service_release_binding_id,
                               source_product_urn, from_product_version_id,
                               to_product_version_id, source_binding_count,
                               impact_count, acknowledged_count,
                               target_binding_count, impact_set_sha256,
                               acknowledgement_set_sha256,
                               target_binding_set_sha256, from_state_version,
                               to_state_version, activation_event_id,
                               cache_transition_mode, actor_subject, reason,
                               idempotency_key, occurred_at, cutover_sha256
                          FROM gda_control.gis_service_migration_cutover
                         WHERE tenant_id = :tenant_id
                           AND service_urn = :service_urn
                         ORDER BY occurred_at, cutover_id
                        """
                    ),
                    {"tenant_id": tenant, "service_urn": service_urn},
                )
                .mappings()
                .all()
            )
            return tuple(
                self._gis_service_migration_cutover_from_row(row) for row in rows
            )

    @staticmethod
    def _gis_service_migration_rollback_from_row(
        row,
    ) -> GISServiceMigrationRollback:
        return GISServiceMigrationRollback.model_validate(dict(row))

    def rollback_gis_service_migration(
        self,
        request: GISServiceMigrationRollbackRequest,
    ) -> GISServiceMigrationRollback:
        """Atomically restore a cutover source under Incident or approval authority."""
        with self._transaction(request.tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.rollback_gis_service_migration(
                              :tenant_id, CAST(:rollback_id AS uuid),
                              CAST(:cutover_id AS uuid), :cutover_sha256,
                              :service_urn,
                              CAST(:from_endpoint_revision_id AS uuid),
                              CAST(:to_endpoint_revision_id AS uuid),
                              :expected_state_version, :authorization_kind,
                              :authorization_ref, :actor_subject, :reason,
                              :idempotency_key, :occurred_at
                          )
                        """
                    ),
                    request.model_dump(mode="python"),
                )
                .mappings()
                .one()
            )
            return self._gis_service_migration_rollback_from_row(row)

    def list_gis_service_migration_rollbacks(
        self,
        tenant_id: str,
        service_urn: str,
    ) -> tuple[GISServiceMigrationRollback, ...]:
        """List immutable migration rollback receipts for one GIS service."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, rollback_id, cutover_id,
                               cutover_sha256, service_urn,
                               from_endpoint_revision_id,
                               to_endpoint_revision_id,
                               from_service_definition_version_id,
                               from_service_release_binding_id,
                               to_service_definition_version_id,
                               to_service_release_binding_id,
                               source_product_urn, from_product_version_id,
                               to_product_version_id, current_binding_count,
                               current_consumer_count, rollback_binding_count,
                               rollback_consumer_count,
                               rollback_binding_set_sha256,
                               from_state_version, to_state_version,
                               activation_event_id, cache_transition_mode,
                               authorization_kind, authorization_ref,
                               authorization_sha256, authorization_status,
                               authorization_state_version, actor_subject,
                               reason, idempotency_key, occurred_at,
                               rollback_sha256
                          FROM gda_control.gis_service_migration_rollback
                         WHERE tenant_id = :tenant_id
                           AND service_urn = :service_urn
                         ORDER BY occurred_at, rollback_id
                        """
                    ),
                    {"tenant_id": tenant, "service_urn": service_urn},
                )
                .mappings()
                .all()
            )
            return tuple(
                self._gis_service_migration_rollback_from_row(row) for row in rows
            )

    @staticmethod
    def _gis_service_endpoint_warmup_from_row(
        row,
    ) -> GISServiceEndpointWarmupReceipt:
        return GISServiceEndpointWarmupReceipt.model_validate(dict(row))

    def record_gis_service_endpoint_warmup(
        self,
        receipt: GISServiceEndpointWarmupReceipt,
    ) -> GatewayWriteResult:
        """Record Run-bound warmup evidence for one immutable endpoint release."""
        with self._transaction(receipt.tenant_id) as connection:
            return self._record_gis_service_endpoint_warmup(connection, receipt)

    @classmethod
    def _record_gis_service_endpoint_warmup(
        cls,
        connection,
        receipt: GISServiceEndpointWarmupReceipt,
    ) -> GatewayWriteResult:
        result = (
            connection.execute(
                text(
                    """
                    SELECT warmup_id, created
                      FROM gda_control.record_gis_service_endpoint_warmup(
                          :tenant_id, CAST(:warmup_id AS uuid), :service_urn,
                          CAST(:endpoint_revision_id AS uuid),
                          CAST(:deployment_revision_id AS uuid),
                          CAST(:service_definition_version_id AS uuid),
                          CAST(:service_release_binding_id AS uuid),
                          CAST(:cache_policy_version_id AS uuid),
                          :cache_namespace, CAST(:run_id AS uuid),
                          CAST(:evidence_artifact_id AS uuid),
                          :requested_sample_count, :successful_sample_count,
                          CAST(:sample_set_sha256 AS char(64)),
                          CAST(:provider_receipt_sha256 AS char(64)),
                          :started_at, :completed_at, :valid_until,
                          :recorded_by, :recorded_at,
                          CAST(:warmup_sha256 AS char(64))
                      )
                    """
                ),
                receipt.model_dump(mode="python"),
            )
            .mappings()
            .one()
        )
        stored = cls._load_gis_service_endpoint_warmups(
            connection,
            receipt.tenant_id,
            receipt.service_urn,
            receipt.endpoint_revision_id,
        )
        matching = next(
            (item for item in stored if item.warmup_id == receipt.warmup_id),
            None,
        )
        if matching is None or matching != receipt:
            raise GatewayConflictError(
                "GIS endpoint warmup identity has different content"
            )
        return GatewayWriteResult(matching, bool(result["created"]))

    def admit_gis_service_endpoint_warmup_run(
        self,
        request: GISServiceEndpointWarmupRunRequest,
        *,
        subject_context: SubjectContext,
    ) -> GISServiceEndpointWarmupRunAdmission:
        """Atomically bind an exact Martin warmup plan to Run and outbox."""
        actor_subject = (
            f"{subject_context.subject_type.value}:{subject_context.subject_id}"
        )
        if subject_context.tenant_id != request.tenant_id:
            raise GatewayForbiddenError("warmup subject tenant does not match request")
        if (
            subject_context.subject_type is not SubjectType.WORKLOAD
            or actor_subject != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
            or subject_context.purpose != GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE
        ):
            raise GatewayForbiddenError(
                "GIS endpoint warmup admission requires its dedicated workload"
            )

        with self._transaction(request.tenant_id) as connection:
            definition = self._load_definition(
                connection, request.tenant_id, request.definition_version_id
            )
            if definition is None:
                raise GatewayNotFoundError("warmup PlatformDefinitionVersion was not found")
            if definition.capability_id != "gis-service-endpoint-warmup":
                raise GatewayValidationError(
                    "Run definition does not provide GIS endpoint warmup"
                )
            endpoint = self._load_endpoint_revision(
                connection, request.tenant_id, request.endpoint_revision_id
            )
            if endpoint is None or endpoint.service_urn != request.service_urn:
                raise GatewayNotFoundError("exact GIS endpoint revision was not found")
            deployment = self._load_service_deployment_revision(
                connection, request.tenant_id, endpoint.deployment_revision_id
            )
            if (
                deployment is None
                or deployment.state is not ServiceDeploymentState.READY
                or deployment.provider_system != "martin"
                or deployment.service_release_binding_id is None
            ):
                raise GatewayValidationError(
                    "warmup requires an exact ready Martin deployment"
                )
            service_definition = self._load_gis_service_definition_version(
                connection,
                request.tenant_id,
                deployment.service_definition_version_id,
            )
            if (
                service_definition is None
                or service_definition.service_urn != request.service_urn
                or service_definition.service_type is not GISServiceType.VECTOR_TILE
            ):
                raise GatewayValidationError(
                    "warmup endpoint does not bind a vector-tile service definition"
                )
            release = self._load_service_release_binding(
                connection,
                request.tenant_id,
                deployment.service_release_binding_id,
            )
            if (
                release is None
                or release.service_definition_version_id
                != service_definition.service_definition_version_id
                or release.cache_policy_version_id is None
                or release.tile_matrix_set_definition_version_id is None
                or release.mvt_serving_projection_version_id is None
            ):
                raise GatewayValidationError(
                    "Martin deployment lacks a complete immutable release binding"
                )
            cache_policy = self._load_cache_policy_version(
                connection, request.tenant_id, release.cache_policy_version_id
            )
            tile_matrix_set = self._load_tile_matrix_set_definition_version(
                connection,
                request.tenant_id,
                release.tile_matrix_set_definition_version_id,
            )
            serving_projection = self._load_mvt_serving_projection_version(
                connection,
                request.tenant_id,
                release.mvt_serving_projection_version_id,
            )
            if cache_policy is None or tile_matrix_set is None or serving_projection is None:
                raise GatewayNotFoundError("warmup release components were not found")
            if (
                cache_policy.service_definition_version_id
                != service_definition.service_definition_version_id
                or tile_matrix_set.service_definition_version_id
                != service_definition.service_definition_version_id
                or tile_matrix_set.layer_definition_version_id
                != release.layer_definition_version_id
                or serving_projection.service_definition_version_id
                != service_definition.service_definition_version_id
                or serving_projection.layer_definition_version_id
                != release.layer_definition_version_id
            ):
                raise GatewayValidationError(
                    "warmup release components do not share one exact service lineage"
                )
            expected_endpoint_contract = {
                "schema": "gda.mvt_endpoint.v1",
                "provider_layer_ref": "gda_mvt_serving_projection",
                "provider_query": {
                    "serving_projection_version_id": str(
                        serving_projection.mvt_serving_projection_version_id
                    )
                },
            }
            if (
                endpoint.endpoint_protocol is not EndpointProtocol.MVT
                or endpoint.endpoint_contract != expected_endpoint_contract
                or any(
                    sample.z < tile_matrix_set.min_zoom
                    or sample.z > tile_matrix_set.max_zoom
                    for sample in request.samples
                )
            ):
                raise GatewayValidationError(
                    "endpoint contract or samples do not match the release tile matrix"
                )
            source_output_resource_version_id = connection.execute(
                text(
                    """
                    SELECT output_resource_version_id
                      FROM gda_control.data_product_version
                     WHERE tenant_id = :tenant_id
                       AND product_urn = :product_urn
                       AND data_product_version_id = :product_version_id
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "product_urn": service_definition.source_product_urn,
                    "product_version_id": (
                        service_definition.source_data_product_version_id
                    ),
                },
            ).scalar_one_or_none()
            if source_output_resource_version_id is None:
                raise GatewayNotFoundError(
                    "warmup source DataProduct output ResourceVersion was not found"
                )
            if (
                serving_projection.source_output_resource_version_id
                != source_output_resource_version_id
            ):
                raise GatewayValidationError(
                    "serving projection does not read the service source product output"
                )

            plan_values = {
                "schema": "gda.gis_service_endpoint_warmup_execution_plan.v1",
                "tenant_id": request.tenant_id,
                "run_id": request.run_id,
                "definition_version_id": request.definition_version_id,
                "definition_sha256": definition.definition_sha256,
                "service_urn": request.service_urn,
                "service_definition_version_id": (
                    service_definition.service_definition_version_id
                ),
                "endpoint_revision_id": endpoint.endpoint_revision_id,
                "endpoint_sha256": endpoint.endpoint_sha256,
                "consumer_endpoint_uri": endpoint.endpoint_uri,
                "deployment_revision_id": deployment.deployment_revision_id,
                "deployment_sha256": deployment.deployment_sha256,
                "service_release_binding_id": release.service_release_binding_id,
                "release_binding_sha256": release.binding_sha256,
                "cache_policy_version_id": cache_policy.cache_policy_version_id,
                "cache_policy_sha256": cache_policy.policy_sha256,
                "cache_namespace": cache_policy.cache_namespace,
                "cache_max_age_seconds": cache_policy.cache_max_age_seconds,
                "tile_matrix_set_definition_version_id": (
                    tile_matrix_set.tile_matrix_set_definition_version_id
                ),
                "tile_matrix_set_sha256": tile_matrix_set.definition_sha256,
                "mvt_serving_projection_version_id": (
                    serving_projection.mvt_serving_projection_version_id
                ),
                "serving_projection_sha256": serving_projection.projection_sha256,
                "source_output_resource_version_id": (
                    source_output_resource_version_id
                ),
                "provider_system": "martin",
                "provider_layer_ref": "gda_mvt_serving_projection",
                "samples": request.samples,
                "sample_set_sha256": martin_mvt_warmup_sample_set_fingerprint(
                    request.samples
                ),
            }
            execution_plan = GISServiceEndpointWarmupExecutionPlan(
                **plan_values,
                plan_sha256=gis_service_endpoint_warmup_plan_fingerprint(plan_values),
            )
            run = PlatformRun(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                definition_version_id=request.definition_version_id,
                orchestration_class=definition.orchestration_class,
                subject_context=subject_context,
                input_bindings=(
                    ResourceBinding(
                        binding_name="source_product_output",
                        resource_version_id=source_output_resource_version_id,
                        semantic_type="gda.gis_service.warmup_source",
                    ),
                ),
                idempotency_key=request.idempotency_key,
                config_fingerprint=execution_plan.plan_sha256,
                submitted_at=request.submitted_at,
            )
            run_result, _ = self._put_run(connection, run, request_dispatch=False)
            plan_manifest = execution_plan.model_dump(mode="json", by_alias=True)
            plan_payload = json.dumps(
                plan_manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            plan_artifact = Artifact(
                tenant_id=request.tenant_id,
                artifact_id=uuid5(
                    request.run_id,
                    f"gda.gis-service-warmup.plan:{execution_plan.plan_sha256}",
                ),
                artifact_key=f"gis-warmup-plan-{request.run_id.hex}",
                artifact_role=ArtifactRole.EXECUTION_PLAN,
                storage_uri=(
                    f"s3://gda-control/gis-service-warmup-plans/{request.run_id}.json"
                ),
                media_type="application/json",
                content_sha256=canonical_json_fingerprint(plan_manifest),
                size_bytes=len(plan_payload),
                run_id=request.run_id,
                manifest=plan_manifest,
                created_by=actor_subject,
                created_at=request.submitted_at,
            )
            artifact_result = self._put_artifact(connection, plan_artifact)
            dedupe_key = (
                f"gis_service.endpoint_warmup:{request.tenant_id}:"
                f"{request.run_id}:{execution_plan.plan_sha256}"
            )
            command = PlatformCommand(
                tenant_id=request.tenant_id,
                command_id=uuid5(request.run_id, dedupe_key),
                run_id=request.run_id,
                command_type=PlatformCommandType.GIS_SERVICE_ENDPOINT_WARMUP,
                execution_plan_artifact_id=plan_artifact.artifact_id,
                dedupe_key=dedupe_key,
                actor_subject=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
                payload={
                    "schema": GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA,
                    "run_id": str(request.run_id),
                    "execution_plan_artifact_id": str(plan_artifact.artifact_id),
                    "execution_plan_sha256": execution_plan.plan_sha256,
                    "sample_set_sha256": execution_plan.sample_set_sha256,
                    "endpoint_revision_id": str(endpoint.endpoint_revision_id),
                    "service_release_binding_id": str(
                        release.service_release_binding_id
                    ),
                    "provider_system": "martin",
                },
                max_attempts=5,
                available_at=request.submitted_at,
                created_at=request.submitted_at,
            )
            command_result = self._put_command(connection, command)
            return GISServiceEndpointWarmupRunAdmission(
                run=run_result.value,
                execution_plan=execution_plan,
                execution_plan_artifact=artifact_result.value,
                command=command_result.value,
                run_created=run_result.created,
                artifact_created=artifact_result.created,
                command_created=command_result.created,
            )

    def get_gis_service_endpoint_warmup_execution_plan(
        self,
        tenant_id: str,
        artifact_id: UUID,
    ) -> GISServiceEndpointWarmupExecutionPlan:
        artifact = self.get_artifact(tenant_id, artifact_id)
        if artifact.artifact_role is not ArtifactRole.EXECUTION_PLAN:
            raise GatewayValidationError("warmup plan Artifact has the wrong role")
        try:
            plan = GISServiceEndpointWarmupExecutionPlan.model_validate(
                artifact.manifest
            )
        except ValueError as exc:
            raise GatewayValidationError("warmup execution plan is invalid") from exc
        if artifact.content_sha256 != canonical_json_fingerprint(artifact.manifest):
            raise GatewayValidationError("warmup plan Artifact content hash is invalid")
        return plan

    def settle_gis_service_endpoint_warmup_success(
        self,
        settlement: GISServiceEndpointWarmupSettlement,
        *,
        actor_subject: str = GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
        reason: str = "Martin origin warmup samples passed",
    ) -> GISServiceEndpointWarmupSettlementResult:
        """Atomically commit evidence, Run success, and migration 220 receipt."""
        plan = settlement.execution_plan
        if actor_subject != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD:
            raise GatewayForbiddenError("warmup settlement actor is not authorized")
        with self._transaction(plan.tenant_id) as connection:
            plan_artifact_id = settlement.observation.evidence.get(
                "execution_plan_artifact_id"
            )
            try:
                plan_artifact_uuid = UUID(str(plan_artifact_id))
            except ValueError as exc:
                raise GatewayValidationError(
                    "warmup observation lacks its execution plan Artifact"
                ) from exc
            stored_plan_artifact = self._load_artifact(
                connection, plan.tenant_id, plan_artifact_uuid
            )
            if (
                stored_plan_artifact is None
                or stored_plan_artifact.manifest
                != plan.model_dump(mode="json", by_alias=True)
                or stored_plan_artifact.content_sha256
                != canonical_json_fingerprint(stored_plan_artifact.manifest)
            ):
                raise GatewayValidationError(
                    "settlement does not match the admitted execution plan"
                )
            created = False
            for result in (
                self._put_observation(connection, settlement.observation),
                self._put_artifact(connection, settlement.evidence_artifact),
                self._put_quality_result(connection, settlement.quality_result),
                self._put_lineage(connection, settlement.lineage_event),
            ):
                created = created or result.created
            details = {
                "schema": "gda.run_success_evidence.v1",
                **settlement.success_evidence.model_dump(mode="json"),
            }
            connection.execute(
                text(
                    """
                    SELECT gda_control.finalize_gis_service_endpoint_warmup_success(
                        :tenant_id, :run_id, :expected_state_version,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": plan.tenant_id,
                    "run_id": plan.run_id,
                    "expected_state_version": settlement.expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details),
                },
            ).scalar_one()
            recorded_at = connection.execute(
                text("SELECT clock_timestamp()")
            ).scalar_one()
            receipt_values = {
                "tenant_id": plan.tenant_id,
                "warmup_id": settlement.warmup_id,
                "service_urn": plan.service_urn,
                "endpoint_revision_id": plan.endpoint_revision_id,
                "deployment_revision_id": plan.deployment_revision_id,
                "service_definition_version_id": (
                    plan.service_definition_version_id
                ),
                "service_release_binding_id": plan.service_release_binding_id,
                "cache_policy_version_id": plan.cache_policy_version_id,
                "cache_namespace": plan.cache_namespace,
                "run_id": plan.run_id,
                "evidence_artifact_id": settlement.evidence_artifact.artifact_id,
                "requested_sample_count": (
                    settlement.provider_receipt.requested_sample_count
                ),
                "successful_sample_count": (
                    settlement.provider_receipt.successful_sample_count
                ),
                "sample_set_sha256": settlement.provider_receipt.sample_set_sha256,
                "provider_receipt_sha256": (
                    settlement.provider_receipt.receipt_sha256
                ),
                "started_at": settlement.provider_receipt.started_at,
                "completed_at": settlement.provider_receipt.completed_at,
                "valid_until": settlement.valid_until,
                "recorded_by": actor_subject,
            }
            existing_receipt = next(
                (
                    item
                    for item in self._load_gis_service_endpoint_warmups(
                        connection,
                        plan.tenant_id,
                        plan.service_urn,
                        plan.endpoint_revision_id,
                    )
                    if item.warmup_id == settlement.warmup_id
                ),
                None,
            )
            if existing_receipt is not None:
                expected_existing = {
                    **receipt_values,
                    "recorded_at": existing_receipt.recorded_at,
                }
                expected_existing["warmup_sha256"] = (
                    gis_service_endpoint_warmup_fingerprint(expected_existing)
                )
                if existing_receipt != GISServiceEndpointWarmupReceipt(
                    **expected_existing
                ):
                    raise GatewayConflictError(
                        "GIS warmup replay differs from its settled receipt"
                    )
                run = self._load_run(connection, plan.tenant_id, plan.run_id)
                if run is None:
                    raise GatewayNotFoundError(
                        "settled warmup PlatformRun was not found"
                    )
                return GISServiceEndpointWarmupSettlementResult(
                    run=run,
                    receipt=existing_receipt,
                    evidence_created=created,
                    receipt_created=False,
                )
            receipt_values["recorded_at"] = recorded_at
            receipt = GISServiceEndpointWarmupReceipt(
                **receipt_values,
                warmup_sha256=gis_service_endpoint_warmup_fingerprint(
                    receipt_values
                ),
            )
            receipt_result = self._record_gis_service_endpoint_warmup(
                connection, receipt
            )
            run = self._load_run(connection, plan.tenant_id, plan.run_id)
            if run is None:
                raise GatewayNotFoundError("settled warmup PlatformRun was not found")
            return GISServiceEndpointWarmupSettlementResult(
                run=run,
                receipt=receipt_result.value,
                evidence_created=created,
                receipt_created=receipt_result.created,
            )

    def list_gis_service_endpoint_warmups(
        self,
        tenant_id: str,
        service_urn: str,
        endpoint_revision_id: UUID | None = None,
    ) -> tuple[GISServiceEndpointWarmupReceipt, ...]:
        """List immutable warmup receipts for one service or exact endpoint."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            return self._load_gis_service_endpoint_warmups(
                connection, tenant, service_urn, endpoint_revision_id
            )

    @classmethod
    def _load_gis_service_endpoint_warmups(
        cls,
        connection,
        tenant_id: str,
        service_urn: str,
        endpoint_revision_id: UUID | None,
    ) -> tuple[GISServiceEndpointWarmupReceipt, ...]:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, warmup_id, service_urn,
                           endpoint_revision_id, deployment_revision_id,
                           service_definition_version_id,
                           service_release_binding_id, cache_policy_version_id,
                           cache_namespace, run_id, evidence_artifact_id,
                           requested_sample_count, successful_sample_count,
                           sample_set_sha256, provider_receipt_sha256,
                           started_at, completed_at, valid_until, recorded_by,
                           recorded_at, warmup_sha256
                      FROM gda_control.gis_service_endpoint_warmup
                     WHERE tenant_id = :tenant_id
                       AND service_urn = :service_urn
                       AND (
                           CAST(:endpoint_revision_id AS uuid) IS NULL
                           OR endpoint_revision_id =
                              CAST(:endpoint_revision_id AS uuid)
                       )
                     ORDER BY completed_at, warmup_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_urn": service_urn,
                    "endpoint_revision_id": endpoint_revision_id,
                },
            )
            .mappings()
            .all()
        )
        return tuple(cls._gis_service_endpoint_warmup_from_row(row) for row in rows)

    @staticmethod
    def _consumer_binding_notification_from_row(
        row,
    ) -> ConsumerBindingMigrationNotification:
        value = dict(row)
        value["provider_receipt"] = _as_json(value["provider_receipt"])
        return ConsumerBindingMigrationNotification.model_validate(value)

    @staticmethod
    def _gis_service_consumer_binding_migration_impact_from_row(
        row,
    ) -> GISServiceConsumerBindingMigrationImpact:
        return GISServiceConsumerBindingMigrationImpact.model_validate(dict(row))

    @classmethod
    def _load_gis_service_consumer_binding_migration_impacts(
        cls,
        connection,
        tenant_id: str,
        notification_id: UUID,
    ) -> tuple[GISServiceConsumerBindingMigrationImpact, ...]:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, impact_id,
                           source_service_consumer_binding_id,
                           source_binding_sha256, service_urn, consumer_ref,
                           source_service_definition_version_id,
                           source_service_release_binding_id,
                           target_service_definition_version_id,
                           target_service_release_binding_id,
                           source_product_urn, from_product_version_id,
                           to_product_version_id, migration_state_id,
                           notification_id, recorded_by, recorded_at,
                           impact_sha256
                      FROM gda_control.gis_service_consumer_binding_migration_impact
                     WHERE tenant_id = :tenant_id
                       AND notification_id = :notification_id
                     ORDER BY recorded_at, impact_id
                    """
                ),
                {"tenant_id": tenant_id, "notification_id": notification_id},
            )
            .mappings()
            .all()
        )
        return tuple(
            cls._gis_service_consumer_binding_migration_impact_from_row(row)
            for row in rows
        )

    @classmethod
    def _consumer_binding_notification_envelope(
        cls,
        connection,
        notification: ConsumerBindingMigrationNotification,
    ) -> ConsumerBindingMigrationNotificationEnvelope:
        binding = cls._load_consumer_binding(
            connection,
            notification.tenant_id,
            notification.binding_id,
        )
        migration_state = cls._load_consumer_binding_migration_state(
            connection,
            notification.tenant_id,
            notification.migration_state_id,
        )
        if binding is None or migration_state is None:
            raise GatewayNotFoundError(
                "ConsumerBinding notification source was not found"
            )
        return ConsumerBindingMigrationNotificationEnvelope(
            notification=notification,
            binding=binding,
            migration_state=migration_state,
            gis_service_impacts=cls._load_gis_service_consumer_binding_migration_impacts(
                connection, notification.tenant_id, notification.notification_id
            ),
        )

    @classmethod
    def _settle_consumer_binding_notification(
        cls,
        connection,
        notification: ConsumerBindingMigrationNotification,
        *,
        recorded_by: str,
    ) -> ConsumerBindingMigrationNotificationSettlement:
        if notification.status not in {
            ConsumerMigrationNotificationDeliveryStatus.DONE,
            ConsumerMigrationNotificationDeliveryStatus.FAILED,
        }:
            return ConsumerBindingMigrationNotificationSettlement(
                notification=notification,
                migration_state=None,
            )
        source_state = cls._load_consumer_binding_migration_state(
            connection,
            notification.tenant_id,
            notification.migration_state_id,
        )
        if source_state is None:
            raise GatewayNotFoundError(
                "ConsumerBinding notification source state was not found"
            )
        terminal_state = build_consumer_binding_notification_terminal_state(
            notification,
            source_state,
            recorded_by=recorded_by,
        )
        cls._record_consumer_binding_migration_state(connection, terminal_state)
        return ConsumerBindingMigrationNotificationSettlement(
            notification=notification,
            migration_state=terminal_state,
        )

    def claim_consumer_binding_migration_notifications(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        recorded_by: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[ConsumerBindingMigrationNotificationEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.claim_consumer_binding_migration_notifications(
                              :tenant_id, :worker_id, :limit, :lease_seconds
                          )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            terminal_rows = (
                connection.execute(
                    text(
                        """
                        SELECT notification.*
                          FROM gda_control.consumer_binding_migration_notification_outbox
                               AS notification
                          JOIN gda_control.consumer_binding_migration_state AS source
                            ON source.tenant_id = notification.tenant_id
                           AND source.migration_state_id = notification.migration_state_id
                         WHERE notification.tenant_id = :tenant_id
                           AND notification.status IN ('done', 'failed')
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM gda_control.consumer_binding_migration_state AS state
                                WHERE state.tenant_id = notification.tenant_id
                                  AND state.notification_evidence->>'notification_id'
                                      = notification.notification_id::text
                                  AND state.notification_evidence->>'receipt_sha256'
                                      = notification.receipt_sha256
                           )
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM gda_control.consumer_binding_migration_state AS newer
                                WHERE newer.tenant_id = source.tenant_id
                                  AND newer.binding_id = source.binding_id
                                  AND newer.from_product_version_id
                                      = source.from_product_version_id
                                  AND newer.to_product_version_id
                                      = source.to_product_version_id
                                  AND newer.state_version > source.state_version
                           )
                         ORDER BY notification.completed_at, notification.notification_id
                        """
                    ),
                    {"tenant_id": tenant},
                )
                .mappings()
                .all()
            )
            for row in terminal_rows:
                self._settle_consumer_binding_notification(
                    connection,
                    self._consumer_binding_notification_from_row(row),
                    recorded_by=recorded_by,
                )
            return tuple(
                self._consumer_binding_notification_envelope(
                    connection,
                    self._consumer_binding_notification_from_row(row),
                )
                for row in rows
            )

    def complete_consumer_binding_migration_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
        recorded_by: str,
        provider_receipt: dict[str, Any],
    ) -> ConsumerBindingMigrationNotificationSettlement:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.complete_consumer_binding_migration_notification(
                              :tenant_id, CAST(:notification_id AS uuid),
                              :worker_id, CAST(:provider_receipt AS jsonb)
                          )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                        "provider_receipt": _json(provider_receipt),
                    },
                )
                .mappings()
                .one()
            )
            notification = self._consumer_binding_notification_from_row(row)
            return self._settle_consumer_binding_notification(
                connection,
                notification,
                recorded_by=recorded_by,
            )

    def fail_consumer_binding_migration_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
        recorded_by: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> ConsumerBindingMigrationNotificationSettlement:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.fail_consumer_binding_migration_notification(
                              :tenant_id, CAST(:notification_id AS uuid),
                              :worker_id, :error, :retry_delay_seconds
                          )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            notification = self._consumer_binding_notification_from_row(row)
            return self._settle_consumer_binding_notification(
                connection,
                notification,
                recorded_by=recorded_by,
            )

    def list_consumer_binding_migration_notifications(
        self,
        tenant_id: str,
        product_urn: str,
        *,
        binding_id: UUID | None = None,
        status: ConsumerMigrationNotificationDeliveryStatus | str | None = None,
    ) -> tuple[ConsumerBindingMigrationNotification, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        resolved_status = (
            ConsumerMigrationNotificationDeliveryStatus(status).value
            if status is not None
            else None
        )
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.consumer_binding_migration_notification_outbox
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND (
                               CAST(:binding_id AS uuid) IS NULL
                               OR binding_id = CAST(:binding_id AS uuid)
                           )
                           AND (:status IS NULL OR status = :status)
                         ORDER BY created_at, notification_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "product_urn": product_urn,
                        "binding_id": binding_id,
                        "status": resolved_status,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._consumer_binding_notification_from_row(row) for row in rows
            )

    @staticmethod
    def _load_resource_version(
        connection, tenant_id: str, version_id: UUID
    ) -> ResourceVersion | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, resource_urn, resource_version_id, version_key,
                       predecessor_version_id, content_sha256,
                       authority_version_ref, created_by, created_at
                FROM gda_control.resource_version
                WHERE tenant_id = :tenant_id
                  AND resource_version_id = :resource_version_id
                """
                ),
                {"tenant_id": tenant_id, "resource_version_id": version_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["authority_version_ref"] = _as_json(value["authority_version_ref"])
        return ResourceVersion.model_validate(value)

    def _put_resource_version(self, connection, version: ResourceVersion) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    predecessor_version_id, content_sha256,
                    authority_version_ref, created_by, created_at
                ) VALUES (
                    :tenant_id, :resource_version_id, :resource_urn, :version_key,
                    :predecessor_version_id, :content_sha256,
                    CAST(:authority_version_ref AS jsonb), :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING resource_version_id
                """
            ),
            {
                **version.model_dump(mode="python", exclude={"authority_version_ref"}),
                "authority_version_ref": _json(version.authority_version_ref),
            },
        ).first()
        stored = self._load_resource_version(
            connection, version.tenant_id, version.resource_version_id
        )
        if stored is None or stored != version:
            raise GatewayConflictError("ResourceVersion identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    @staticmethod
    def _load_approval_case(
        connection,
        tenant_id: str,
        approval_case_ref: str,
    ) -> ApprovalCase | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, approval_case_ref, target_resource_urn,
                           target_fingerprint, action, requester_subject,
                           request_reason, request_context, status, state_version,
                           requested_at, expires_at, decided_by,
                           decision_reason, decided_at
                    FROM gda_control.approval_case
                    WHERE tenant_id = :tenant_id
                      AND approval_case_ref = :approval_case_ref
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "approval_case_ref": approval_case_ref,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["request_context"] = _as_json(value["request_context"])
        return ApprovalCase.model_validate(value)

    @staticmethod
    def _lock_architecture_resource_version(
        connection,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> None:
        connection.execute(
            text(
                """
                SELECT pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(
                        :tenant_id || ':' || CAST(:resource_version_id AS text),
                        0
                    )
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "resource_version_id": resource_version_id,
            },
        ).scalar_one()

    def register_resource_version(self, version: ResourceVersion) -> GatewayWriteResult:
        with self._transaction(version.tenant_id) as connection:
            if version.predecessor_version_id is not None:
                self._lock_architecture_resource_version(
                    connection,
                    version.tenant_id,
                    version.predecessor_version_id,
                )
            return self._put_resource_version(connection, version)

    def get_resource_version(self, tenant_id: str, resource_version_id: UUID) -> ResourceVersion:
        """Return one immutable resource version through the gateway role."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            version = self._load_resource_version(connection, tenant, resource_version_id)
            if version is None:
                raise GatewayNotFoundError("ResourceVersion was not found")
            return version

    def list_resource_versions(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> GatewayResourceVersionPage:
        """Return one bounded, tenant-scoped page ordered newest first."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 100:
            raise GatewayValidationError(
                "resource version query limit must be between 1 and 100"
            )
        if not 0 <= offset <= 10_000:
            raise GatewayValidationError(
                "resource version query offset must be between 0 and 10000"
            )
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, resource_urn, resource_version_id,
                               version_key, predecessor_version_id, content_sha256,
                               authority_version_ref, created_by, created_at
                        FROM gda_control.resource_version
                        WHERE tenant_id = :tenant_id
                        ORDER BY created_at DESC, resource_version_id DESC
                        LIMIT :row_limit OFFSET :offset
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "row_limit": limit + 1,
                        "offset": offset,
                    },
                )
                .mappings()
                .all()
            )
        values = []
        for row in rows[:limit]:
            value = dict(row)
            value["authority_version_ref"] = _as_json(value["authority_version_ref"])
            values.append(ResourceVersion.model_validate(value))
        return GatewayResourceVersionPage(
            items=tuple(values),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
        )

    @staticmethod
    def _load_schema_version(
        connection,
        tenant_id: str,
        *,
        schema_version_id: UUID | None = None,
        resource_version_id: UUID | None = None,
    ) -> SchemaVersion | None:
        if (schema_version_id is None) == (resource_version_id is None):
            raise ValueError("exactly one SchemaVersion lookup identity is required")
        clause = (
            "schema_version_id = :identity"
            if schema_version_id is not None
            else "resource_version_id = :identity"
        )
        row = (
            connection.execute(
                text(
                    f"""
                    SELECT tenant_id, schema_version_id, resource_version_id,
                           schema_format, authority_system, authority_namespace,
                           authority_object_id, authority_version_ref,
                           schema_sha256, created_by, created_at
                    FROM gda_control.schema_version
                    WHERE tenant_id = :tenant_id AND {clause}
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "identity": schema_version_id or resource_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return SchemaVersion.model_validate(dict(row)) if row is not None else None

    def _put_schema_version(
        self, connection, value: SchemaVersion
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.schema_version (
                    tenant_id, schema_version_id, resource_version_id,
                    schema_format, authority_system, authority_namespace,
                    authority_object_id, authority_version_ref, schema_sha256,
                    created_by, created_at
                ) VALUES (
                    :tenant_id, :schema_version_id, :resource_version_id,
                    :schema_format, :authority_system, :authority_namespace,
                    :authority_object_id, :authority_version_ref, :schema_sha256,
                    :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING schema_version_id
                """
            ),
            value.model_dump(mode="python"),
        ).first()
        stored = self._load_schema_version(
            connection,
            value.tenant_id,
            schema_version_id=value.schema_version_id,
        )
        if stored is None or stored != value:
            raise GatewayConflictError(
                "SchemaVersion identity already has a different immutable binding"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_schema_version(self, value: SchemaVersion) -> GatewayWriteResult:
        with self._transaction(value.tenant_id) as connection:
            return self._put_schema_version(connection, value)

    @staticmethod
    def _load_data_contract_version(
        connection,
        tenant_id: str,
        *,
        data_contract_version_id: UUID | None = None,
        resource_version_id: UUID | None = None,
    ) -> DataContractVersion | None:
        if (data_contract_version_id is None) == (resource_version_id is None):
            raise ValueError("exactly one DataContractVersion lookup identity is required")
        clause = (
            "data_contract_version_id = :identity"
            if data_contract_version_id is not None
            else "resource_version_id = :identity"
        )
        row = (
            connection.execute(
                text(
                    f"""
                    SELECT tenant_id, data_contract_version_id,
                           resource_version_id, contract_kind,
                           enforcement_mode, authority_system,
                           authority_namespace, authority_object_id,
                           authority_version_ref, contract_sha256,
                           created_by, created_at
                    FROM gda_control.data_contract_version
                    WHERE tenant_id = :tenant_id AND {clause}
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "identity": data_contract_version_id or resource_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return (
            DataContractVersion.model_validate(dict(row))
            if row is not None
            else None
        )

    def _put_data_contract_version(
        self, connection, value: DataContractVersion
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.data_contract_version (
                    tenant_id, data_contract_version_id, resource_version_id,
                    contract_kind, enforcement_mode, authority_system,
                    authority_namespace, authority_object_id,
                    authority_version_ref, contract_sha256, created_by, created_at
                ) VALUES (
                    :tenant_id, :data_contract_version_id, :resource_version_id,
                    :contract_kind, :enforcement_mode, :authority_system,
                    :authority_namespace, :authority_object_id,
                    :authority_version_ref, :contract_sha256, :created_by,
                    :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING data_contract_version_id
                """
            ),
            value.model_dump(mode="python"),
        ).first()
        stored = self._load_data_contract_version(
            connection,
            value.tenant_id,
            data_contract_version_id=value.data_contract_version_id,
        )
        if stored is None or stored != value:
            raise GatewayConflictError(
                "DataContractVersion identity already has a different immutable binding"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_data_contract_version(
        self, value: DataContractVersion
    ) -> GatewayWriteResult:
        with self._transaction(value.tenant_id) as connection:
            return self._put_data_contract_version(connection, value)

    @staticmethod
    def _load_physical_location(
        connection,
        tenant_id: str,
        *,
        physical_location_id: UUID | None = None,
        resource_version_id: UUID | None = None,
    ) -> PhysicalLocation | None:
        if (physical_location_id is None) == (resource_version_id is None):
            raise ValueError("exactly one PhysicalLocation lookup identity is required")
        clause = (
            "physical_location_id = :identity"
            if physical_location_id is not None
            else "resource_version_id = :identity"
        )
        row = (
            connection.execute(
                text(
                    f"""
                    SELECT tenant_id, physical_location_id, resource_version_id,
                           location_kind, provider_system, provider_namespace,
                           provider_locator, snapshot_ref, revision_ref,
                           checksum_algorithm, content_checksum, location_sha256,
                           created_by, created_at
                    FROM gda_control.physical_location
                    WHERE tenant_id = :tenant_id AND {clause}
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "identity": physical_location_id or resource_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return PhysicalLocation.model_validate(dict(row)) if row is not None else None

    def _put_physical_location(
        self, connection, value: PhysicalLocation
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.physical_location (
                    tenant_id, physical_location_id, resource_version_id,
                    location_kind, provider_system, provider_namespace,
                    provider_locator, snapshot_ref, revision_ref,
                    checksum_algorithm, content_checksum, location_sha256,
                    created_by, created_at
                ) VALUES (
                    :tenant_id, :physical_location_id, :resource_version_id,
                    :location_kind, :provider_system, :provider_namespace,
                    :provider_locator, :snapshot_ref, :revision_ref,
                    :checksum_algorithm, :content_checksum, :location_sha256,
                    :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING physical_location_id
                """
            ),
            value.model_dump(mode="python"),
        ).first()
        stored = self._load_physical_location(
            connection,
            value.tenant_id,
            physical_location_id=value.physical_location_id,
        )
        if stored is None or stored != value:
            raise GatewayConflictError(
                "PhysicalLocation identity already has a different immutable binding"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_physical_location(
        self, value: PhysicalLocation
    ) -> GatewayWriteResult:
        with self._transaction(value.tenant_id) as connection:
            return self._put_physical_location(connection, value)

    @staticmethod
    def _load_architecture_binding(
        connection,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> ResourceVersionArchitectureBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, resource_version_id, schema_version_id,
                           data_contract_version_id, physical_location_id,
                           binding_sha256, bound_by, bound_at
                    FROM gda_control.resource_version_architecture_binding
                    WHERE tenant_id = :tenant_id
                      AND resource_version_id = :resource_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "resource_version_id": resource_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return (
            ResourceVersionArchitectureBinding.model_validate(dict(row))
            if row is not None
            else None
        )

    def _put_architecture_binding(
        self,
        connection,
        value: ResourceVersionArchitectureBinding,
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version_architecture_binding (
                    tenant_id, resource_version_id, schema_version_id,
                    data_contract_version_id, physical_location_id,
                    binding_sha256, bound_by, bound_at
                ) VALUES (
                    :tenant_id, :resource_version_id, :schema_version_id,
                    :data_contract_version_id, :physical_location_id,
                    :binding_sha256, :bound_by, :bound_at
                )
                ON CONFLICT DO NOTHING
                RETURNING resource_version_id
                """
            ),
            value.model_dump(mode="python"),
        ).first()
        stored = self._load_architecture_binding(
            connection, value.tenant_id, value.resource_version_id
        )
        if stored is None or stored != value:
            raise GatewayConflictError(
                "ResourceVersion architecture already has a different immutable binding"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def bind_resource_version_architecture(
        self, value: ResourceVersionArchitectureBinding
    ) -> GatewayWriteResult:
        with self._transaction(value.tenant_id) as connection:
            return self._put_architecture_binding(connection, value)

    def register_resource_version_architecture(
        self, registration: DataArchitectureRegistration
    ) -> GatewayWriteResult:
        """Atomically register all architecture facts and their complete binding."""
        tenant_id = registration.binding.tenant_id
        with self._transaction(tenant_id) as connection:
            schema = self._put_schema_version(connection, registration.schema_version)
            contract = self._put_data_contract_version(
                connection, registration.data_contract_version
            )
            location = self._put_physical_location(
                connection, registration.physical_location
            )
            binding = self._put_architecture_binding(connection, registration.binding)
            return GatewayWriteResult(
                registration,
                any(
                    result.created
                    for result in (schema, contract, location, binding)
                ),
            )

    def adopt_architecture_successor(
        self,
        plan: ArchitectureSuccessorPlan,
        *,
        adoption_approval_case_ref: str,
        evaluated_at: datetime,
    ) -> GatewayWriteResult:
        """Atomically recheck approvals/evidence and write one successor version."""

        from .architecture_successor_adoption import (
            ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION,
            ArchitectureSuccessorAdoptionError,
            build_architecture_successor_adoption_case,
            validate_architecture_successor_plan_against_facts,
        )

        tenant = _TENANT_ADAPTER.validate_python(plan.tenant_id)
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise GatewayValidationError("architecture adoption time requires a timezone")
        evaluated = evaluated_at.astimezone(UTC)
        successor = plan.successor_resource_version
        registration = plan.successor_architecture
        successor_timestamps = (
            successor.created_at,
            registration.schema_version.created_at,
            registration.data_contract_version.created_at,
            registration.physical_location.created_at,
            registration.binding.bound_at,
        )
        if any(value > evaluated for value in successor_timestamps):
            raise GatewayValidationError(
                "successor authority time cannot be in the future"
            )
        with self._transaction(tenant) as connection:
            self._lock_architecture_resource_version(
                connection,
                tenant,
                plan.predecessor_resource_version_id,
            )
            predecessor = self._load_resource_version(
                connection,
                tenant,
                plan.predecessor_resource_version_id,
            )
            if predecessor is None:
                raise GatewayNotFoundError("Architecture predecessor was not found")
            architecture = self._load_resource_version_architecture_projection(
                connection,
                tenant,
                plan.predecessor_resource_version_id,
            )
            planned_observation = self._load_architecture_provider_observation(
                connection,
                tenant,
                plan.observation_id,
            )
            if planned_observation is None:
                raise GatewayNotFoundError("Planned provider observation was not found")
            artifact = self._load_artifact(
                connection,
                tenant,
                plan.candidate_schema_artifact_id,
            )
            if artifact is None:
                raise GatewayNotFoundError("Candidate schema Artifact was not found")
            assessed_case = self._load_approval_case(
                connection,
                tenant,
                plan.assessed_approval_case_ref,
            )
            if assessed_case is None:
                raise GatewayNotFoundError("Assessed architecture ApprovalCase was not found")
            adoption_case = self._load_approval_case(
                connection,
                tenant,
                adoption_approval_case_ref,
            )
            if adoption_case is None:
                raise GatewayNotFoundError("Successor adoption ApprovalCase was not found")
            try:
                validate_architecture_successor_plan_against_facts(
                    plan,
                    predecessor=predecessor,
                    predecessor_architecture=architecture,
                    observation=planned_observation,
                    candidate_schema_artifact=artifact,
                    assessed_case=assessed_case,
                )
            except ArchitectureSuccessorAdoptionError as exc:
                raise GatewayValidationError(str(exc)) from exc
            expected_adoption_case = build_architecture_successor_adoption_case(
                plan,
                requester_subject=adoption_case.requester_subject,
                request_reason=adoption_case.request_reason,
                requested_at=adoption_case.requested_at,
                expires_at=adoption_case.expires_at,
            )
            if (
                adoption_case.status is not ApprovalCaseStatus.APPROVED
                or adoption_case.action != ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION
                or adoption_case.approval_case_ref
                != expected_adoption_case.approval_case_ref
                or adoption_case.target_resource_urn
                != expected_adoption_case.target_resource_urn
                or adoption_case.target_fingerprint
                != expected_adoption_case.target_fingerprint
                or adoption_case.request_context
                != expected_adoption_case.request_context
            ):
                raise GatewayValidationError(
                    "successor adoption ApprovalCase is not an approved plan binding"
                )
            conflicting_successor = connection.execute(
                text(
                    """
                    SELECT resource_version_id
                    FROM gda_control.resource_version
                    WHERE tenant_id = :tenant_id
                      AND resource_urn = :resource_urn
                      AND predecessor_version_id = :predecessor_version_id
                      AND resource_version_id <> :successor_version_id
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant,
                    "resource_urn": plan.target_resource_urn,
                    "predecessor_version_id": plan.predecessor_resource_version_id,
                    "successor_version_id": successor.resource_version_id,
                },
            ).first()
            if conflicting_successor is not None:
                raise GatewayConflictError(
                    "architecture predecessor already has another adopted successor"
                )
            stored_successor = self._load_resource_version(
                connection,
                tenant,
                successor.resource_version_id,
            )
            if stored_successor is not None:
                if stored_successor != successor:
                    raise GatewayConflictError(
                        "Successor ResourceVersion already has a different payload"
                    )
                stored_architecture = (
                    self._load_resource_version_architecture_projection(
                        connection,
                        tenant,
                        successor.resource_version_id,
                    )
                )
                stored_lineage = self._load_lineage(
                    connection,
                    tenant,
                    plan.lineage_event.lineage_event_id,
                )
                if (
                    stored_architecture.schema_version_record
                    == registration.schema_version
                    and stored_architecture.data_contract_version_record
                    == registration.data_contract_version
                    and stored_architecture.physical_location
                    == registration.physical_location
                    and stored_architecture.binding == registration.binding
                    and stored_lineage == plan.lineage_event
                ):
                    return GatewayWriteResult(value=plan, created=False)
            latest_observation = self._load_latest_architecture_provider_observation(
                connection,
                tenant,
                plan.predecessor_resource_version_id,
            )
            if latest_observation != planned_observation:
                raise GatewayValidationError(
                    "architecture successor observation is no longer latest"
                )
            if planned_observation.fresh_until <= evaluated:
                raise GatewayValidationError("architecture successor observation is stale")
            if successor.created_at < planned_observation.observed_at:
                raise GatewayValidationError(
                    "successor creation time cannot predate its provider observation"
                )
            results = (
                self._put_resource_version(connection, successor),
                self._put_schema_version(connection, registration.schema_version),
                self._put_data_contract_version(
                    connection,
                    registration.data_contract_version,
                ),
                self._put_physical_location(
                    connection,
                    registration.physical_location,
                ),
                self._put_architecture_binding(connection, registration.binding),
                self._put_lineage(connection, plan.lineage_event),
            )
            return GatewayWriteResult(
                value=plan,
                created=any(result.created for result in results),
            )

    def _load_resource_version_architecture_projection(
        self,
        connection,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> ResourceVersionArchitecture:
        version = self._load_resource_version(connection, tenant_id, resource_version_id)
        if version is None:
            raise GatewayNotFoundError("ResourceVersion was not found")
        schema = self._load_schema_version(
            connection, tenant_id, resource_version_id=resource_version_id
        )
        contract = self._load_data_contract_version(
            connection, tenant_id, resource_version_id=resource_version_id
        )
        location = self._load_physical_location(
            connection, tenant_id, resource_version_id=resource_version_id
        )
        binding = self._load_architecture_binding(
            connection, tenant_id, resource_version_id
        )
        missing = []
        if schema is None:
            missing.append("schema_version")
        if contract is None:
            missing.append("data_contract_version")
        if location is None:
            missing.append("physical_location")
        if binding is None:
            missing.append("architecture_binding")
        return ResourceVersionArchitecture(
            tenant_id=tenant_id,
            resource_version_id=resource_version_id,
            architecture_ready=binding is not None and not missing,
            missing_components=tuple(missing),
            schema_version_record=schema,
            data_contract_version_record=contract,
            physical_location=location,
            binding=binding,
        )

    def get_resource_version_architecture(
        self, tenant_id: str, resource_version_id: UUID
    ) -> ResourceVersionArchitecture:
        """Return complete facts or an explicit fail-closed readiness projection."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            return self._load_resource_version_architecture_projection(
                connection, tenant, resource_version_id
            )

    @staticmethod
    def _architecture_observation_from_row(row) -> ArchitectureProviderObservation:
        return ArchitectureProviderObservation.model_validate(dict(row))

    @classmethod
    def _load_architecture_provider_observation(
        cls,
        connection,
        tenant_id: str,
        observation_id: UUID,
    ) -> ArchitectureProviderObservation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, observation_id, resource_version_id,
                           provider_system, provider_namespace,
                           provider_object_id, object_state, source_revision,
                           schema_content_sha256, schema_version_sha256,
                           physical_location_sha256, observed_at, fresh_until,
                           observation_sha256, observed_by, recorded_at
                    FROM gda_control.architecture_provider_observation
                    WHERE tenant_id = :tenant_id
                      AND observation_id = :observation_id
                    """
                ),
                {"tenant_id": tenant_id, "observation_id": observation_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._architecture_observation_from_row(row) if row is not None else None

    @classmethod
    def _load_latest_architecture_provider_observation(
        cls,
        connection,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> ArchitectureProviderObservation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, observation_id, resource_version_id,
                           provider_system, provider_namespace,
                           provider_object_id, object_state, source_revision,
                           schema_content_sha256, schema_version_sha256,
                           physical_location_sha256, observed_at, fresh_until,
                           observation_sha256, observed_by, recorded_at
                    FROM gda_control.architecture_provider_observation
                    WHERE tenant_id = :tenant_id
                      AND resource_version_id = :resource_version_id
                    ORDER BY observed_at DESC, observation_id DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "resource_version_id": resource_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._architecture_observation_from_row(row) if row is not None else None

    def _put_architecture_provider_observation(
        self,
        connection,
        value: ArchitectureProviderObservation,
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.architecture_provider_observation (
                    tenant_id, observation_id, resource_version_id,
                    provider_system, provider_namespace, provider_object_id,
                    object_state, source_revision, schema_content_sha256,
                    schema_version_sha256, physical_location_sha256,
                    observed_at, fresh_until, observation_sha256,
                    observed_by, recorded_at
                ) VALUES (
                    :tenant_id, :observation_id, :resource_version_id,
                    :provider_system, :provider_namespace, :provider_object_id,
                    :object_state, :source_revision, :schema_content_sha256,
                    :schema_version_sha256, :physical_location_sha256,
                    :observed_at, :fresh_until, :observation_sha256,
                    :observed_by, :recorded_at
                )
                ON CONFLICT DO NOTHING
                RETURNING observation_id
                """
            ),
            value.model_dump(mode="python"),
        ).first()
        stored = self._load_architecture_provider_observation(
            connection, value.tenant_id, value.observation_id
        )
        if stored is None or stored != value:
            raise GatewayConflictError(
                "Architecture provider observation identity already has a "
                "different immutable payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def record_architecture_provider_observation(
        self,
        value: ArchitectureProviderObservation,
    ) -> GatewayWriteResult:
        with self._transaction(value.tenant_id) as connection:
            self._lock_architecture_resource_version(
                connection,
                value.tenant_id,
                value.resource_version_id,
            )
            return self._put_architecture_provider_observation(connection, value)

    def get_latest_architecture_provider_observation(
        self,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> ArchitectureProviderObservation:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load_resource_version(
                connection, tenant, resource_version_id
            ) is None:
                raise GatewayNotFoundError("ResourceVersion was not found")
            observation = self._load_latest_architecture_provider_observation(
                connection, tenant, resource_version_id
            )
            if observation is None:
                raise GatewayNotFoundError("Architecture provider observation was not found")
            return observation

    def get_architecture_provider_observation(
        self,
        tenant_id: str,
        observation_id: UUID,
    ) -> ArchitectureProviderObservation:
        """Return one immutable provider observation through tenant RLS."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            observation = self._load_architecture_provider_observation(
                connection,
                tenant,
                observation_id,
            )
            if observation is None:
                raise GatewayNotFoundError(
                    "Architecture provider observation was not found"
                )
            return observation

    def reconcile_resource_version_architecture(
        self,
        tenant_id: str,
        resource_version_id: UUID,
        *,
        evaluated_at: datetime | None = None,
    ) -> ResourceVersionArchitectureReconciliation:
        """Compare the immutable binding with the latest successful observation."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        evaluated = evaluated_at or datetime.now(UTC)
        if evaluated.tzinfo is None or evaluated.utcoffset() is None:
            raise GatewayValidationError("architecture evaluation time requires a timezone")
        evaluated = evaluated.astimezone(UTC)
        with self._transaction(tenant) as connection:
            architecture = self._load_resource_version_architecture_projection(
                connection, tenant, resource_version_id
            )
            observation = self._load_latest_architecture_provider_observation(
                connection, tenant, resource_version_id
            )
        status = ArchitectureReconciliationStatus.UNOBSERVED
        actions = ("harvest_provider",)
        schema_matches = None
        location_matches = None
        if observation is not None:
            if observation.object_state.value == "tombstoned":
                status = ArchitectureReconciliationStatus.TOMBSTONED
                actions = ("investigate_tombstone",)
            elif observation.fresh_until <= evaluated:
                status = ArchitectureReconciliationStatus.STALE
                actions = ("refresh_observation",)
            elif not architecture.architecture_ready:
                status = ArchitectureReconciliationStatus.UNBOUND
                actions = ("register_architecture",)
            else:
                assert architecture.schema_version_record is not None
                assert architecture.physical_location is not None
                schema_matches = (
                    observation.schema_version_sha256
                    == architecture.schema_version_record.schema_sha256
                )
                location_matches = (
                    observation.physical_location_sha256
                    == architecture.physical_location.location_sha256
                )
                if schema_matches and location_matches:
                    status = ArchitectureReconciliationStatus.IN_SYNC
                    actions = ()
                elif not schema_matches and not location_matches:
                    status = ArchitectureReconciliationStatus.SCHEMA_AND_LOCATION_DRIFT
                    actions = ("review_schema_drift", "review_location_drift")
                elif not schema_matches:
                    status = ArchitectureReconciliationStatus.SCHEMA_DRIFT
                    actions = ("review_schema_drift",)
                else:
                    status = ArchitectureReconciliationStatus.LOCATION_DRIFT
                    actions = ("review_location_drift",)
        return ResourceVersionArchitectureReconciliation(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            status=status,
            architecture=architecture,
            latest_observation=observation,
            schema_matches=schema_matches,
            location_matches=location_matches,
            evaluated_at=evaluated,
            required_actions=actions,
        )

    @staticmethod
    def _load_definition(
        connection, tenant_id: str, definition_version_id: UUID
    ) -> PlatformDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, definition_urn, definition_version_id,
                       orchestration_class, capability_id, portability_class,
                       definition_document, input_contract, output_contract,
                       definition_sha256
                FROM gda_control.platform_definition_version
                WHERE tenant_id = :tenant_id
                  AND definition_version_id = :definition_version_id
                """
                ),
                {
                    "tenant_id": tenant_id,
                    "definition_version_id": definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        for field in ("definition_document", "input_contract", "output_contract"):
            value[field] = _as_json(value[field])
        return PlatformDefinitionVersion.model_validate(value)

    def _put_definition(
        self, connection, definition: PlatformDefinitionVersion
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_definition_version (
                    tenant_id, definition_urn, definition_version_id,
                    orchestration_class, capability_id, portability_class,
                    definition_document, input_contract, output_contract,
                    definition_sha256
                ) VALUES (
                    :tenant_id, :definition_urn, :definition_version_id,
                    :orchestration_class, :capability_id, :portability_class,
                    CAST(:definition_document AS jsonb),
                    CAST(:input_contract AS jsonb),
                    CAST(:output_contract AS jsonb), :definition_sha256
                )
                ON CONFLICT DO NOTHING
                RETURNING definition_version_id
                """
            ),
            {
                **definition.model_dump(
                    mode="json",
                    exclude={"definition_document", "input_contract", "output_contract"},
                ),
                "definition_document": _json(definition.definition_document),
                "input_contract": _json(definition.input_contract),
                "output_contract": _json(definition.output_contract),
            },
        ).first()
        stored = self._load_definition(
            connection, definition.tenant_id, definition.definition_version_id
        )
        if stored is None or stored != definition:
            raise GatewayConflictError(
                "PlatformDefinitionVersion identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_definition(self, registration: DefinitionRegistration) -> GatewayWriteResult:
        with self._transaction(registration.resource.tenant_id) as connection:
            resource_result = self._put_resource(connection, registration.resource)
            version_result = self._put_resource_version(connection, registration.resource_version)
            definition_result = self._put_definition(connection, registration.definition)
            return GatewayWriteResult(
                registration,
                resource_result.created or version_result.created or definition_result.created,
            )

    def get_definition(
        self,
        tenant_id: str,
        definition_version_id: UUID,
    ) -> PlatformDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            definition = self._load_definition(
                connection,
                tenant,
                definition_version_id,
            )
            if definition is None:
                raise GatewayNotFoundError("PlatformDefinitionVersion was not found")
            return definition

    @staticmethod
    def _load_run(connection, tenant_id: str, run_id: UUID) -> PlatformRun | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, run_id, definition_version_id,
                       orchestration_class, subject_context, idempotency_key, policy_refs,
                       config_fingerprint, status, state_version, submitted_at
                FROM gda_control.platform_run
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        bindings = (
            connection.execute(
                text(
                    """
                SELECT binding_name, resource_version_id, semantic_type
                FROM gda_control.platform_run_input_binding
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                ORDER BY binding_name
                """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .all()
        )
        value = dict(row)
        value["subject_context"] = _as_json(value["subject_context"])
        value["policy_refs"] = _as_json(value["policy_refs"]) or None
        value["input_bindings"] = [dict(binding) for binding in bindings]
        return PlatformRun.model_validate(value)

    @staticmethod
    def _run_event_from_row(row) -> PlatformRunEvent:
        value = dict(row)
        value["details"] = _as_json(value["details"])
        return PlatformRunEvent.model_validate(value)

    @classmethod
    def _load_platform_run_event(
        cls, connection, tenant_id: str, event_id: UUID
    ) -> PlatformRunEvent | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, event_id, run_id, sequence_no,
                           from_status, to_status, actor_subject, reason,
                           details, occurred_at
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id AND event_id = :event_id
                    """
                ),
                {"tenant_id": tenant_id, "event_id": event_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._run_event_from_row(row) if row is not None else None

    @staticmethod
    def _run_event_delivery_from_row(row) -> PlatformRunEventDelivery:
        return PlatformRunEventDelivery.model_validate(dict(row))

    @classmethod
    def _run_event_envelope(
        cls, connection, delivery: PlatformRunEventDelivery
    ) -> PlatformRunEventEnvelope:
        event = cls._load_platform_run_event(
            connection, delivery.tenant_id, delivery.run_event_id
        )
        if event is None:
            raise GatewayNotFoundError("PlatformRun event delivery binding was not found")
        return PlatformRunEventEnvelope(delivery=delivery, event=event)

    @classmethod
    def _load_run_by_idempotency(
        cls,
        connection,
        tenant_id: str,
        definition_version_id: UUID,
        idempotency_key: str,
    ) -> PlatformRun | None:
        run_id = connection.execute(
            text(
                """
                SELECT run_id
                FROM gda_control.platform_run
                WHERE tenant_id = :tenant_id
                  AND definition_version_id = :definition_version_id
                  AND idempotency_key = :idempotency_key
                """
            ),
            {
                "tenant_id": tenant_id,
                "definition_version_id": definition_version_id,
                "idempotency_key": idempotency_key,
            },
        ).scalar_one_or_none()
        return cls._load_run(connection, tenant_id, run_id) if run_id is not None else None

    @staticmethod
    def _run_binding(run: PlatformRun) -> dict[str, Any]:
        binding = run.model_dump(
            mode="json",
            exclude={"status", "state_version"},
        )
        binding["input_bindings"] = sorted(
            binding["input_bindings"], key=lambda item: item["binding_name"]
        )
        return binding

    @staticmethod
    def _run_actor(run: PlatformRun) -> str:
        return f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"

    def _validate_run_policy_references(
        self, connection, run: PlatformRun
    ) -> tuple[PolicyDecision | None, Artifact | None]:
        references = run.policy_refs
        if references is None:
            return None, None
        decision_artifact = self._load_artifact(
            connection, run.tenant_id, references.policy_decision_artifact_id
        )
        if decision_artifact is None:
            raise GatewayValidationError("Policy decision artifact was not found")
        try:
            decision = parse_policy_decision_artifact(decision_artifact)
        except AuthorizationEvidenceError as exc:
            raise GatewayValidationError(str(exc)) from exc
        execution_plan_artifact = self._load_artifact(
            connection, run.tenant_id, decision.execution_plan_artifact_id
        )
        if execution_plan_artifact is None:
            raise GatewayValidationError("Execution plan artifact was not found")
        approval_artifact = None
        if references.approval_artifact_id is not None:
            approval_artifact = self._load_artifact(
                connection, run.tenant_id, references.approval_artifact_id
            )
            if approval_artifact is None:
                raise GatewayValidationError("Approval artifact was not found")
        try:
            validate_run_authorization_evidence(
                run,
                decision_artifact,
                approval_artifact,
                execution_plan_artifact,
                at=run.submitted_at,
            )
        except AuthorizationEvidenceError as exc:
            raise GatewayValidationError(str(exc)) from exc
        return decision, execution_plan_artifact

    @staticmethod
    def _command_from_row(row) -> PlatformCommand:
        value = dict(row)
        value["payload"] = _as_json(value["payload"])
        return PlatformCommand.model_validate(value)

    @staticmethod
    def _command_binding(command: PlatformCommand) -> dict[str, Any]:
        """Return fields that identify a logical command, not its delivery state."""
        return command.model_dump(
            mode="json",
            exclude={
                "status",
                "attempt_count",
                "available_at",
                "claimed_by",
                "claimed_until",
                "last_error",
                "created_at",
                "completed_at",
            },
        )

    @classmethod
    def _load_command(cls, connection, tenant_id: str, command_id: UUID) -> PlatformCommand | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, command_id, run_id, command_type,
                       execution_plan_artifact_id, trigger_observation_id,
                       dedupe_key, actor_subject, payload, status,
                       attempt_count, max_attempts, available_at,
                       claimed_by, claimed_until, last_error,
                       created_at, completed_at
                FROM gda_control.platform_command_outbox
                WHERE tenant_id = :tenant_id AND command_id = :command_id
                """
                ),
                {"tenant_id": tenant_id, "command_id": command_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._command_from_row(row) if row is not None else None

    @classmethod
    def _put_command(cls, connection, command: PlatformCommand) -> GatewayWriteResult:
        if command.status != PlatformCommandStatus.PENDING:
            raise GatewayValidationError("new platform command must be pending")
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_command_outbox (
                    tenant_id, command_id, run_id, command_type,
                    execution_plan_artifact_id, trigger_observation_id,
                    dedupe_key, actor_subject, payload, status,
                    attempt_count, max_attempts, available_at,
                    claimed_by, claimed_until, last_error,
                    created_at, completed_at
                ) VALUES (
                    :tenant_id, :command_id, :run_id, :command_type,
                    :execution_plan_artifact_id, :trigger_observation_id,
                    :dedupe_key, :actor_subject, CAST(:payload AS jsonb), :status,
                    :attempt_count, :max_attempts, :available_at,
                    :claimed_by, :claimed_until, :last_error,
                    :created_at, :completed_at
                )
                ON CONFLICT DO NOTHING
                RETURNING command_id
                """
            ),
            {
                **command.model_dump(mode="python", exclude={"payload"}),
                "command_type": command.command_type.value,
                "status": command.status.value,
                "payload": _json(command.payload),
            },
        ).first()
        stored = cls._load_command(connection, command.tenant_id, command.command_id)
        if stored is None or cls._command_binding(stored) != cls._command_binding(command):
            raise GatewayConflictError("platform command identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    @classmethod
    def _dispatch_command(
        cls,
        run: PlatformRun,
        decision: PolicyDecision | None,
        execution_plan: Artifact | None,
        *,
        enqueued_at: datetime | None = None,
    ) -> PlatformCommand:
        if decision is None or execution_plan is None:
            raise GatewayValidationError("dispatch request requires immutable policy references")
        if run.orchestration_class.value != "dataops":
            raise GatewayValidationError("dispatch request requires a dataops Run")
        if run.subject_context.subject_type.value != "workload":
            raise GatewayValidationError("dispatch request requires workload SubjectContext")
        if decision.action != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH.value:
            raise GatewayValidationError("policy decision action does not authorize dispatch")
        dedupe_key = f"dolphinscheduler.dispatch:{run.run_id}:{execution_plan.artifact_id}"
        enqueued = enqueued_at or datetime.now(UTC)
        return PlatformCommand(
            tenant_id=run.tenant_id,
            command_id=uuid5(run.run_id, dedupe_key),
            run_id=run.run_id,
            command_type=PlatformCommandType.DOLPHINSCHEDULER_DISPATCH,
            execution_plan_artifact_id=execution_plan.artifact_id,
            dedupe_key=dedupe_key,
            actor_subject=cls._run_actor(run),
            payload={
                "schema": "gda.dolphinscheduler_dispatch_command.v1",
                "policy_decision_artifact_id": str(run.policy_refs.policy_decision_artifact_id),
            },
            available_at=enqueued,
            created_at=enqueued,
        )

    def _put_run(
        self,
        connection,
        run: PlatformRun,
        *,
        request_dispatch: bool,
    ) -> tuple[GatewayWriteResult, GatewayWriteResult | None]:
        decision, execution_plan = self._validate_run_policy_references(connection, run)
        actor = self._run_actor(run)
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_run (
                    tenant_id, run_id, definition_version_id,
                    orchestration_class, subject_context, idempotency_key,
                    policy_refs, config_fingerprint, submitted_by, submitted_at
                ) VALUES (
                    :tenant_id, :run_id, :definition_version_id,
                    :orchestration_class, CAST(:subject_context AS jsonb),
                    :idempotency_key, CAST(:policy_refs AS jsonb), :config_fingerprint,
                    :submitted_by, :submitted_at
                )
                ON CONFLICT DO NOTHING
                RETURNING run_id
                """
            ),
            {
                "tenant_id": run.tenant_id,
                "run_id": run.run_id,
                "definition_version_id": run.definition_version_id,
                "orchestration_class": run.orchestration_class.value,
                "subject_context": _json(run.subject_context.model_dump(mode="json")),
                "idempotency_key": run.idempotency_key,
                "policy_refs": _json(
                    run.policy_refs.model_dump(mode="json") if run.policy_refs is not None else {}
                ),
                "config_fingerprint": run.config_fingerprint,
                "submitted_by": actor,
                "submitted_at": run.submitted_at,
            },
        ).first()
        if inserted is not None:
            for binding in sorted(run.input_bindings, key=lambda item: item.binding_name):
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.platform_run_input_binding (
                            tenant_id, run_id, binding_name,
                            resource_version_id, semantic_type
                        ) VALUES (
                            :tenant_id, :run_id, :binding_name,
                            :resource_version_id, :semantic_type
                        )
                        """
                    ),
                    {
                        "tenant_id": run.tenant_id,
                        "run_id": run.run_id,
                        **binding.model_dump(mode="python"),
                    },
                )
            stored = self._load_run(connection, run.tenant_id, run.run_id)
        else:
            stored = self._load_run_by_idempotency(
                connection,
                run.tenant_id,
                run.definition_version_id,
                run.idempotency_key,
            )
        if stored is None or self._run_binding(stored) != self._run_binding(run):
            raise GatewayConflictError(
                "Run idempotency key already has a different immutable binding"
            )
        command_result = None
        if request_dispatch:
            enqueued_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            command_result = self._put_command(
                connection,
                self._dispatch_command(
                    stored,
                    decision,
                    execution_plan,
                    enqueued_at=enqueued_at,
                ),
            )
        return GatewayWriteResult(stored, inserted is not None), command_result

    def submit_run(self, run: PlatformRun, *, request_dispatch: bool = False) -> GatewayWriteResult:
        with self._transaction(run.tenant_id) as connection:
            result, _command = self._put_run(
                connection,
                run,
                request_dispatch=request_dispatch,
            )
            return result

    def admit_blueprint_test_run(
        self,
        request: DataProductBlueprintTestRunRequest,
        *,
        subject_context: SubjectContext,
    ) -> GatewayWriteResult:
        """Admit a Blueprint test as an immutable PlatformRun plus plan Artifact.

        This is intentionally an admission boundary. It does not invoke a
        provider, create a product version, or claim that the test succeeded.
        The server recompiles the definition and report, then binds every
        supplied input version into the durable execution plan.
        """
        blueprint = request.blueprint
        if subject_context.tenant_id != blueprint.tenant_id:
            raise GatewayForbiddenError("test admission subject tenant does not match Blueprint")
        registration = compile_data_product_blueprint(blueprint)
        report = build_data_product_blueprint_test_report(
            blueprint,
            definition=registration.definition,
        )
        if report.verdict != "passed":
            raise GatewayValidationError("Blueprint contract tests did not pass")

        with self._transaction(blueprint.tenant_id) as connection:
            stored_definition = self._load_definition(
                connection,
                blueprint.tenant_id,
                blueprint.definition_version_id,
            )
            if stored_definition is None:
                raise GatewayNotFoundError(
                    "Blueprint definition must be registered before test admission"
                )
            if stored_definition != registration.definition:
                raise GatewayConflictError(
                    "stored definition differs from the server-rebuilt Blueprint definition"
                )

            source_refs = set(blueprint.source_refs)
            resolved_inputs: list[tuple[ResourceBinding, ResourceVersion]] = []
            resolved_resource_urns: set[str] = set()
            for binding in request.input_bindings:
                version = self._load_resource_version(
                    connection,
                    blueprint.tenant_id,
                    binding.resource_version_id,
                )
                if version is None:
                    raise GatewayNotFoundError(
                        "Blueprint test input ResourceVersion "
                        f"{binding.resource_version_id} was not found"
                    )
                if version.resource_urn not in source_refs:
                    raise GatewayValidationError(
                        "test input ResourceVersion is not one of the Blueprint sources"
                    )
                if version.resource_urn in resolved_resource_urns:
                    raise GatewayValidationError(
                        "each Blueprint source must have exactly one test input binding"
                    )
                resolved_resource_urns.add(version.resource_urn)
                resolved_inputs.append((binding, version))
            resolved_refs = {version.resource_urn for _, version in resolved_inputs}
            if resolved_refs != source_refs:
                missing = sorted(source_refs - resolved_refs)
                raise GatewayValidationError(
                    f"test admission must bind every Blueprint source; missing: {missing}"
                )

            duckdb_pipeline = None
            provider_contract: dict[str, Any] = {
                "schema": "gda.data_product_blueprint_provider_binding.v1",
                "engine": str(blueprint.pipeline.get("engine") or "unspecified"),
                "pipeline_sha256": canonical_json_fingerprint(blueprint.pipeline),
            }
            if blueprint.pipeline.get("engine") == "duckdb":
                try:
                    duckdb_pipeline = DuckDBBlueprintPipeline.model_validate(
                        blueprint.pipeline
                    )
                except ValueError as exc:
                    raise GatewayValidationError(
                        "Blueprint DuckDB pipeline contract is invalid"
                    ) from exc
                if (
                    subject_context.subject_type is not SubjectType.WORKLOAD
                    or (
                        f"{subject_context.subject_type.value}:"
                        f"{subject_context.subject_id}"
                    )
                    != DUCKDB_BLUEPRINT_WORKLOAD
                ):
                    raise GatewayForbiddenError(
                        "DuckDB Blueprint admission requires its dedicated workload identity"
                    )
                provider_contract.update(
                    {
                        "workload_subject": DUCKDB_BLUEPRINT_WORKLOAD,
                        "output_uri": self._blueprint_duckdb_output_uri(
                            blueprint.tenant_id,
                            request.run_id,
                        ),
                    }
                )

            input_manifest = []
            for binding, version in sorted(
                resolved_inputs, key=lambda item: item[0].binding_name
            ):
                item: dict[str, Any] = {
                    "binding_name": binding.binding_name,
                    "resource_version_id": str(version.resource_version_id),
                    "resource_urn": version.resource_urn,
                    "version_key": version.version_key,
                    "content_sha256": version.content_sha256,
                    "semantic_type": binding.semantic_type,
                }
                if duckdb_pipeline is not None:
                    architecture = self._load_resource_version_architecture_projection(
                        connection,
                        blueprint.tenant_id,
                        version.resource_version_id,
                    )
                    if not architecture.architecture_ready:
                        raise GatewayValidationError(
                            "DuckDB Blueprint inputs require a complete architecture binding"
                        )
                    location = architecture.physical_location
                    schema = architecture.schema_version_record
                    contract = architecture.data_contract_version_record
                    architecture_binding = architecture.binding
                    assert location is not None
                    assert schema is not None
                    assert contract is not None
                    assert architecture_binding is not None
                    local_location = location.provider_system == "duckdb"
                    object_location = location.provider_system == "s3"
                    try:
                        if local_location:
                            parts = urlsplit(location.provider_locator)
                            valid_locator = (
                                parts.scheme == "file"
                                and not parts.netloc
                                and parts.path.startswith("/")
                                and not parts.query
                                and not parts.fragment
                                and location.revision_ref is None
                            )
                        elif object_location:
                            parse_blueprint_s3_uri(location.provider_locator)
                            S3ObjectVersionEvidence(
                                version_id=str(location.revision_ref or ""),
                                etag="admitted",
                            )
                            valid_locator = bool(location.revision_ref) and (
                                self._blueprint_duckdb_result_backend == "s3"
                                and blueprint_s3_input_allowed(
                                    location.provider_locator,
                                    self._blueprint_duckdb_input_s3_prefixes,
                                )
                            )
                        else:
                            valid_locator = False
                        if local_location:
                            valid_locator = valid_locator and (
                                self._blueprint_duckdb_result_backend == "local"
                            )
                    except ValueError:
                        valid_locator = False
                    if (
                        not valid_locator
                        or location.location_kind != "parquet"
                        or location.checksum_algorithm != "sha256"
                        or location.content_checksum != version.content_sha256
                    ):
                        raise GatewayValidationError(
                            "DuckDB Blueprint inputs require an immutable, content-bound "
                            "Parquet location"
                        )
                    item["physical_location"] = {
                        "physical_location_id": str(location.physical_location_id),
                        "location_kind": location.location_kind,
                        "provider_system": location.provider_system,
                        "provider_namespace": location.provider_namespace,
                        "provider_locator": location.provider_locator,
                        "snapshot_ref": location.snapshot_ref,
                        "revision_ref": location.revision_ref,
                        "checksum_algorithm": location.checksum_algorithm,
                        "content_checksum": location.content_checksum,
                        "object_version_id": location.revision_ref,
                        "location_sha256": location.location_sha256,
                        "schema_version_id": str(schema.schema_version_id),
                        "schema_sha256": schema.schema_sha256,
                        "data_contract_version_id": str(
                            contract.data_contract_version_id
                        ),
                        "contract_sha256": contract.contract_sha256,
                        "architecture_binding_sha256": (
                            architecture_binding.binding_sha256
                        ),
                    }
                input_manifest.append(item)
            plan_manifest = {
                "schema": "gda.data_product_blueprint_test_execution_plan.v1",
                "execution_mode": "admission_only",
                "provider_execution_required": True,
                "tenant_id": blueprint.tenant_id,
                "product_urn": blueprint.product_urn,
                "version_key": blueprint.version_key,
                "definition_version_id": str(blueprint.definition_version_id),
                "blueprint_sha256": blueprint.blueprint_sha256,
                "definition_sha256": registration.definition.definition_sha256,
                "test_report_sha256": report.test_report_sha256,
                "inputs": input_manifest,
                "provider_contract": provider_contract,
            }
            plan_fingerprint = canonical_json_fingerprint(plan_manifest)
            plan_manifest["plan_sha256"] = plan_fingerprint
            run = PlatformRun(
                tenant_id=blueprint.tenant_id,
                run_id=request.run_id,
                definition_version_id=blueprint.definition_version_id,
                orchestration_class=registration.definition.orchestration_class,
                subject_context=subject_context,
                input_bindings=tuple(
                    binding for binding, _ in resolved_inputs
                ),
                idempotency_key=request.idempotency_key,
                config_fingerprint=plan_fingerprint,
                submitted_at=blueprint.created_at,
            )
            run_result, _ = self._put_run(
                connection,
                run,
                request_dispatch=False,
            )
            stored_run = run_result.value
            plan_id = uuid5(
                stored_run.run_id,
                f"gda.data_product_blueprint.test.plan:{report.test_report_sha256}",
            )
            plan_payload = json.dumps(
                plan_manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            execution_plan = Artifact(
                tenant_id=blueprint.tenant_id,
                artifact_id=plan_id,
                artifact_key=f"blueprint-test-plan-{stored_run.run_id.hex}",
                artifact_role=ArtifactRole.EXECUTION_PLAN,
                storage_uri=(
                    f"s3://gda-control/test-plans/{stored_run.run_id}.json"
                ),
                media_type="application/json",
                content_sha256=canonical_json_fingerprint(plan_manifest),
                size_bytes=len(plan_payload),
                run_id=stored_run.run_id,
                manifest=plan_manifest,
                created_by=subject_context.subject_type.value + ":" + subject_context.subject_id,
                created_at=blueprint.created_at,
            )
            artifact_result = self._put_artifact(connection, execution_plan)
            provider_command_result = None
            if duckdb_pipeline is not None:
                command_dedupe_key = (
                    "blueprint-provider.execute:"
                    f"{stored_run.run_id}:{plan_fingerprint}"
                )
                provider_command = PlatformCommand(
                    tenant_id=blueprint.tenant_id,
                    command_id=uuid5(stored_run.run_id, command_dedupe_key),
                    run_id=stored_run.run_id,
                    command_type=PlatformCommandType.BLUEPRINT_PROVIDER_EXECUTE,
                    execution_plan_artifact_id=artifact_result.value.artifact_id,
                    dedupe_key=command_dedupe_key,
                    actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
                    payload={
                        "schema": (
                            "gda.data_product_blueprint_duckdb_execute_command.v1"
                        ),
                        "run_id": str(stored_run.run_id),
                        "execution_plan_artifact_id": str(
                            artifact_result.value.artifact_id
                        ),
                        "execution_plan_sha256": plan_fingerprint,
                        "definition_version_id": str(
                            blueprint.definition_version_id
                        ),
                        "definition_sha256": (
                            registration.definition.definition_sha256
                        ),
                        "engine": "duckdb",
                        "attempt_no": 1,
                    },
                    max_attempts=5,
                    available_at=blueprint.created_at,
                    created_at=blueprint.created_at,
                )
                provider_command_result = self._put_command(
                    connection,
                    provider_command,
                )
            admission = DataProductBlueprintTestRunAdmission(
                tenant_id=blueprint.tenant_id,
                definition_version_id=blueprint.definition_version_id,
                definition_sha256=registration.definition.definition_sha256,
                test_report=report,
                run=stored_run,
                execution_plan=artifact_result.value,
                provider_command=(
                    provider_command_result.value
                    if provider_command_result is not None
                    else None
                ),
            )
            return GatewayWriteResult(
                admission,
                run_result.created
                or artifact_result.created
                or (
                    provider_command_result is not None
                    and provider_command_result.created
                ),
            )

    @staticmethod
    def _load_blueprint_test_plan(connection, tenant_id: str, run_id: UUID) -> Artifact:
        plan_id = connection.execute(
            text(
                """
                SELECT artifact_id
                FROM gda_control.artifact
                WHERE tenant_id = :tenant_id
                  AND run_id = :run_id
                  AND artifact_role = 'execution_plan'
                  AND manifest ->> 'schema' =
                      'gda.data_product_blueprint_test_execution_plan.v1'
                ORDER BY created_at, artifact_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).scalar_one_or_none()
        if plan_id is None:
            raise GatewayNotFoundError("Blueprint test execution plan was not found")
        plan = PlatformGateway._load_artifact(connection, tenant_id, plan_id)
        if plan is None:
            raise GatewayNotFoundError("Blueprint test execution plan was not found")
        manifest = plan.manifest
        claimed_plan_sha256 = manifest.get("plan_sha256")
        fingerprint_input = dict(manifest)
        fingerprint_input.pop("plan_sha256", None)
        if (
            manifest.get("execution_mode") != "admission_only"
            or manifest.get("provider_execution_required") is not True
            or claimed_plan_sha256 != canonical_json_fingerprint(fingerprint_input)
            or plan.content_sha256 != canonical_json_fingerprint(manifest)
        ):
            raise GatewayConflictError(
                "Blueprint test execution plan is not an intact executable admission"
            )
        return plan

    @staticmethod
    def _blueprint_duckdb_ids(run_id: UUID, plan_sha256: str) -> dict[str, UUID]:
        return {
            "output_version": uuid5(
                run_id,
                f"gda.blueprint-duckdb.output-resource-version:{plan_sha256}",
            ),
            "output_artifact": uuid5(
                run_id,
                f"gda.blueprint-duckdb.output-artifact:{plan_sha256}",
            ),
            "quality_evidence": uuid5(
                run_id,
                f"gda.blueprint-duckdb.quality-evidence:{plan_sha256}",
            ),
            "quality_result": uuid5(
                run_id,
                f"gda.blueprint-duckdb.quality-result:{plan_sha256}",
            ),
            "observation": uuid5(
                run_id,
                f"gda.blueprint-duckdb.attempt:{plan_sha256}:1",
            ),
        }

    def _build_blueprint_duckdb_spec(
        self,
        connection,
        run: PlatformRun,
        plan: Artifact,
    ) -> DuckDBBlueprintExecutionSpec:
        manifest = plan.manifest
        definition = self._load_definition(
            connection,
            run.tenant_id,
            run.definition_version_id,
        )
        if definition is None:
            raise GatewayNotFoundError("Blueprint definition was not found")
        if definition.definition_sha256 != manifest.get("definition_sha256"):
            raise GatewayConflictError(
                "Blueprint execution plan definition binding has changed"
            )
        try:
            pipeline = DuckDBBlueprintPipeline.model_validate(
                definition.definition_document.get("pipeline")
            )
        except ValueError as exc:
            raise GatewayValidationError(
                "Blueprint definition does not contain a valid DuckDB pipeline"
            ) from exc
        provider_contract = manifest.get("provider_contract") or {}
        if (
            provider_contract.get("engine") != "duckdb"
            or provider_contract.get("workload_subject") != DUCKDB_BLUEPRINT_WORKLOAD
            or provider_contract.get("pipeline_sha256")
            != canonical_json_fingerprint(
                definition.definition_document.get("pipeline")
            )
            or not provider_contract.get("output_uri")
        ):
            raise GatewayConflictError(
                "Blueprint execution plan does not bind the DuckDB provider"
            )

        inputs = []
        for item in manifest.get("inputs") or ():
            location = item.get("physical_location") or {}
            try:
                inputs.append(
                    DuckDBBlueprintInput(
                        binding_name=item["binding_name"],
                        resource_version_id=UUID(item["resource_version_id"]),
                        resource_urn=item["resource_urn"],
                        content_sha256=item["content_sha256"],
                        physical_location_id=UUID(
                            location["physical_location_id"]
                        ),
                        location_sha256=location["location_sha256"],
                        provider_system=location["provider_system"],
                        provider_locator=location["provider_locator"],
                        content_checksum=location["content_checksum"],
                        checksum_algorithm=location["checksum_algorithm"],
                        object_version_id=location.get("object_version_id"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise GatewayConflictError(
                    "Blueprint execution plan has an invalid DuckDB input binding"
                ) from exc
        return DuckDBBlueprintExecutionSpec(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            execution_plan_artifact_id=plan.artifact_id,
            execution_plan_sha256=manifest["plan_sha256"],
            definition_version_id=definition.definition_version_id,
            definition_sha256=definition.definition_sha256,
            attempt_no=1,
            pipeline=pipeline,
            inputs=tuple(inputs),
            output_uri=provider_contract["output_uri"],
            admitted_at=plan.created_at,
        )

    def prepare_blueprint_duckdb_test_run(
        self,
        tenant_id: str,
        request: DuckDBBlueprintExecutionRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Fence a DuckDB attempt and return only its immutable execution package."""
        if actor_subject != DUCKDB_BLUEPRINT_WORKLOAD:
            raise GatewayForbiddenError(
                "DuckDB Blueprint execution requires its dedicated workload identity"
            )
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "DuckDB provider actor does not match the admitted Run workload"
                )
            if run.status == RunStatus.SUCCEEDED:
                raise GatewayConflictError("DuckDB Blueprint test Run already succeeded")
            plan = self._load_blueprint_test_plan(connection, tenant_id, run.run_id)
            spec = self._build_blueprint_duckdb_spec(connection, run, plan)
            created = False
            for from_status, to_status, schema, reason in (
                (
                    RunStatus.ACCEPTED,
                    RunStatus.DISPATCHING,
                    "gda.blueprint_duckdb_provider_dispatch.v1",
                    "dispatch admitted Blueprint to DuckDB provider",
                ),
                (
                    RunStatus.DISPATCHING,
                    RunStatus.RUNNING,
                    "gda.blueprint_duckdb_provider_start.v1",
                    "start admitted Blueprint in DuckDB provider",
                ),
            ):
                if run.status != from_status:
                    continue
                connection.execute(
                    text(
                        """
                        SELECT gda_control.transition_platform_run(
                            :tenant_id, :run_id, :expected_state_version,
                            :to_status, :actor_subject, :reason,
                            CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": run.run_id,
                        "expected_state_version": run.state_version,
                        "to_status": to_status.value,
                        "actor_subject": actor_subject,
                        "reason": reason,
                        "details": _json(
                            {
                                "schema": schema,
                                "execution_plan_artifact_id": str(plan.artifact_id),
                                "execution_plan_sha256": spec.execution_plan_sha256,
                                "attempt_no": spec.attempt_no,
                            }
                        ),
                    },
                ).scalar_one()
                run = self._load_run(connection, tenant_id, run.run_id)
                if run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                created = True
            if run.status not in {RunStatus.RUNNING, RunStatus.RECONCILING}:
                raise GatewayConflictError(
                    f"Blueprint test Run in {run.status.value} cannot execute in DuckDB"
                )
            return GatewayWriteResult(spec, created)

    def _load_blueprint_duckdb_execution(
        self,
        connection,
        run: PlatformRun,
        plan: Artifact,
    ) -> DataProductBlueprintTestExecution:
        plan_sha256 = str(plan.manifest["plan_sha256"])
        ids = self._blueprint_duckdb_ids(run.run_id, plan_sha256)
        output_version = self._load_resource_version(
            connection,
            run.tenant_id,
            ids["output_version"],
        )
        output_artifact = self._load_artifact(
            connection,
            run.tenant_id,
            ids["output_artifact"],
        )
        quality_evidence = self._load_artifact(
            connection,
            run.tenant_id,
            ids["quality_evidence"],
        )
        quality_result = self._load_quality_result(
            connection,
            run.tenant_id,
            ids["quality_result"],
        )
        observation = self._load_observation(
            connection,
            run.tenant_id,
            ids["observation"],
        )
        if any(
            item is None
            for item in (
                output_version,
                output_artifact,
                quality_evidence,
                quality_result,
                observation,
            )
        ):
            raise GatewayConflictError(
                "succeeded DuckDB Blueprint Run has incomplete evidence"
            )
        lineage_events = []
        for item in plan.manifest.get("inputs") or ():
            source_id = UUID(item["resource_version_id"])
            lineage_id = uuid5(
                run.run_id,
                f"gda.blueprint-duckdb.lineage:{source_id}:{plan_sha256}",
            )
            event = self._load_lineage(connection, run.tenant_id, lineage_id)
            if event is None:
                raise GatewayConflictError(
                    "succeeded DuckDB Blueprint Run has incomplete lineage"
                )
            lineage_events.append(event)
        assert output_version is not None
        assert output_artifact is not None
        assert quality_evidence is not None
        assert quality_result is not None
        assert observation is not None
        success_evidence = RunSuccessEvidence(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            attempt_observation_id=observation.observation_id,
            output_artifact_id=output_artifact.artifact_id,
            quality_result_id=quality_result.quality_result_id,
            lineage_event_id=lineage_events[0].lineage_event_id,
            evidence_sha256=run_success_evidence_fingerprint(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                attempt_observation_id=observation.observation_id,
                output_artifact_id=output_artifact.artifact_id,
                quality_result_id=quality_result.quality_result_id,
                lineage_event_id=lineage_events[0].lineage_event_id,
            ),
        )
        return DataProductBlueprintTestExecution(
            tenant_id=run.tenant_id,
            run=run,
            output_resource_version=output_version,
            attempt_observation=observation,
            output_artifact=output_artifact,
            quality_evidence_artifact=quality_evidence,
            quality_result=quality_result,
            lineage_events=tuple(lineage_events),
            success_evidence=success_evidence,
            executor_mode="duckdb_provider",
        )

    def complete_blueprint_duckdb_test_run(
        self,
        receipt: DuckDBBlueprintProviderReceipt,
        *,
        actor_subject: str,
        reason: str,
    ) -> GatewayWriteResult:
        """Atomically project a verified DuckDB receipt into shared success evidence."""
        if actor_subject != DUCKDB_BLUEPRINT_WORKLOAD:
            raise GatewayForbiddenError(
                "DuckDB Blueprint completion requires its dedicated workload identity"
            )
        try:
            verify_duckdb_blueprint_output(
                receipt,
                object_store=self._blueprint_duckdb_object_store,
            )
        except DuckDBBlueprintProviderError as exc:
            raise GatewayValidationError(str(exc)) from exc
        with self._transaction(receipt.tenant_id) as connection:
            run = self._load_run(connection, receipt.tenant_id, receipt.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "DuckDB provider actor does not match the admitted Run workload"
                )
            plan = self._load_blueprint_test_plan(
                connection,
                receipt.tenant_id,
                receipt.run_id,
            )
            spec = self._build_blueprint_duckdb_spec(connection, run, plan)
            if (
                receipt.execution_plan_artifact_id
                != spec.execution_plan_artifact_id
                or receipt.execution_plan_sha256 != spec.execution_plan_sha256
                or receipt.definition_version_id != spec.definition_version_id
                or receipt.definition_sha256 != spec.definition_sha256
                or receipt.attempt_no != spec.attempt_no
                or receipt.output_uri != spec.output_uri
            ):
                raise GatewayConflictError(
                    "DuckDB provider receipt does not bind the admitted execution spec"
                )
            spatial_output = receipt.spatial_output_evidence
            if spec.pipeline.require_spatial:
                if (
                    not receipt.spatial_extension_loaded
                    or receipt.spatial_extension_evidence is None
                    or spatial_output is None
                    or spatial_output.srid != spec.pipeline.spatial_output_srid
                ):
                    raise GatewayConflictError(
                        "DuckDB spatial receipt does not satisfy the admitted pipeline"
                    )
            elif (
                receipt.spatial_extension_loaded
                or receipt.spatial_extension_evidence is not None
                or spatial_output is not None
            ):
                raise GatewayConflictError(
                    "non-spatial DuckDB pipeline cannot submit spatial evidence"
                )
            if run.status == RunStatus.SUCCEEDED:
                existing = self._load_blueprint_duckdb_execution(
                    connection,
                    run,
                    plan,
                )
                if (
                    existing.attempt_observation.evidence.get("receipt_sha256")
                    != receipt.receipt_sha256
                ):
                    raise GatewayConflictError(
                        "DuckDB Blueprint Run already has a different provider receipt"
                    )
                return GatewayWriteResult(existing, False)
            if run.status not in {RunStatus.RUNNING, RunStatus.RECONCILING}:
                raise GatewayConflictError(
                    f"Blueprint test Run in {run.status.value} cannot accept DuckDB success"
                )

            ids = self._blueprint_duckdb_ids(
                run.run_id,
                spec.execution_plan_sha256,
            )
            output_resource_urn = build_resource_urn(
                receipt.tenant_id,
                "dataset",
                f"blueprint-duckdb-output-{run.run_id.hex}",
            )
            output_resource = Resource(
                tenant_id=receipt.tenant_id,
                resource_urn=output_resource_urn,
                resource_kind="dataset",
                authority_system="gda-duckdb-provider",
                authority_locator=f"blueprint-test:{run.run_id}",
                owner_ref=actor_subject,
                governance_ref={
                    "schema": "gda.blueprint_duckdb_output.v1",
                    "definition_version_id": str(run.definition_version_id),
                    "execution_plan_sha256": spec.execution_plan_sha256,
                },
            )
            output_version = ResourceVersion(
                tenant_id=receipt.tenant_id,
                resource_urn=output_resource_urn,
                resource_version_id=ids["output_version"],
                version_key=f"duckdb-test-{run.run_id.hex[:16]}",
                content_sha256=receipt.output_content_sha256,
                authority_version_ref={
                    "schema": DUCKDB_BLUEPRINT_PROVIDER_RECEIPT_SCHEMA,
                    "receipt_sha256": receipt.receipt_sha256,
                    "provider_version": receipt.provider_version,
                },
                created_by=actor_subject,
                created_at=receipt.observed_at,
            )
            receipt_document = receipt.model_dump(mode="json", by_alias=True)
            output_manifest = {
                "schema": "gda.blueprint_duckdb_output.v1",
                "executor_mode": "duckdb_provider",
                "provider_receipt": receipt_document,
                "execution_plan_sha256": spec.execution_plan_sha256,
                "output_rows": receipt.output_rows,
                "output_columns": list(receipt.output_columns),
            }
            if receipt.output_storage_evidence is not None:
                output_manifest["storage_evidence"] = (
                    receipt.output_storage_evidence.model_dump(
                        mode="json",
                        by_alias=True,
                    )
                )
            output_artifact = Artifact(
                tenant_id=receipt.tenant_id,
                artifact_id=ids["output_artifact"],
                artifact_key=f"blueprint-duckdb-output-{run.run_id.hex}",
                artifact_role=ArtifactRole.OUTPUT,
                storage_uri=receipt.output_uri,
                media_type="application/vnd.apache.parquet",
                content_sha256=receipt.output_content_sha256,
                size_bytes=receipt.output_size_bytes,
                run_id=run.run_id,
                resource_version_id=output_version.resource_version_id,
                manifest=output_manifest,
                created_by=actor_subject,
                created_at=receipt.observed_at,
            )
            quality_evaluator = "workload:blueprint-quality-evaluator"
            quality_metrics = {
                "schema": "gda.blueprint_duckdb_quality.v1",
                "executor_mode": "duckdb_provider",
                "execution_plan_sha256": spec.execution_plan_sha256,
                "receipt_sha256": receipt.receipt_sha256,
                "input_count": len(spec.inputs),
                "input_rows": receipt.input_rows,
                "input_bytes": receipt.input_bytes,
                "output_rows": receipt.output_rows,
                "output_size_bytes": receipt.output_size_bytes,
                "output_content_sha256": receipt.output_content_sha256,
                "source_checksums_verified": True,
                "external_access_disabled": receipt.external_access == "disabled",
                "row_limit_satisfied": (
                    receipt.output_rows <= spec.pipeline.max_output_rows
                ),
                "spatial_requirement_satisfied": (
                    not spec.pipeline.require_spatial
                    or (
                        receipt.spatial_extension_loaded
                        and receipt.spatial_extension_evidence is not None
                        and spatial_output is not None
                        and spatial_output.srid
                        == spec.pipeline.spatial_output_srid
                    )
                ),
                "spatial_extension_evidence": (
                    None
                    if receipt.spatial_extension_evidence is None
                    else receipt.spatial_extension_evidence.model_dump(
                        mode="json", by_alias=True
                    )
                ),
                "spatial_output_evidence": (
                    None
                    if spatial_output is None
                    else spatial_output.model_dump(mode="json", by_alias=True)
                ),
                "checks_passed": True,
            }
            quality_evidence = Artifact(
                tenant_id=receipt.tenant_id,
                artifact_id=ids["quality_evidence"],
                artifact_key=f"blueprint-duckdb-quality-{run.run_id.hex}",
                artifact_role=ArtifactRole.EVIDENCE,
                storage_uri=(
                    f"s3://gda-control/duckdb-test-quality/{run.run_id}.json"
                ),
                media_type="application/json",
                content_sha256=canonical_json_fingerprint(quality_metrics),
                size_bytes=len(_json(quality_metrics).encode("utf-8")),
                run_id=run.run_id,
                resource_version_id=output_version.resource_version_id,
                manifest=quality_metrics,
                created_by=quality_evaluator,
                created_at=receipt.observed_at,
            )
            quality_result = QualityResult(
                tenant_id=receipt.tenant_id,
                quality_result_id=ids["quality_result"],
                run_id=run.run_id,
                resource_version_id=output_version.resource_version_id,
                rule_version_ref="gda:blueprint-duckdb-conformance/v1",
                verdict=QualityVerdict.PASSED,
                metrics=quality_metrics,
                evidence_artifact_id=quality_evidence.artifact_id,
                result_sha256=quality_result_fingerprint(
                    tenant_id=receipt.tenant_id,
                    run_id=run.run_id,
                    resource_version_id=output_version.resource_version_id,
                    rule_version_ref="gda:blueprint-duckdb-conformance/v1",
                    verdict=QualityVerdict.PASSED,
                    metrics=quality_metrics,
                    evidence_artifact_id=quality_evidence.artifact_id,
                    evaluated_by=quality_evaluator,
                    evaluated_at=receipt.observed_at,
                ),
                evaluated_by=quality_evaluator,
                evaluated_at=receipt.observed_at,
            )
            observation_evidence = {
                **receipt_document,
                "executor_mode": "duckdb_provider",
                "output_artifact_id": str(output_artifact.artifact_id),
                "quality_result_id": str(quality_result.quality_result_id),
            }
            observation = FrameworkAttemptObservation(
                tenant_id=receipt.tenant_id,
                observation_id=ids["observation"],
                run_id=run.run_id,
                attempt_no=receipt.attempt_no,
                framework_kind=FrameworkKind.DUCKDB,
                external_namespace="gda-blueprint-duckdb",
                external_run_id=str(run.run_id),
                external_attempt_id=f"attempt-{receipt.attempt_no}",
                observed_state="success",
                observation_sha256=canonical_json_fingerprint(
                    observation_evidence
                ),
                evidence=observation_evidence,
                observed_at=receipt.observed_at,
            )

            created = False
            for result in (
                self._put_resource(connection, output_resource),
                self._put_resource_version(connection, output_version),
                self._put_artifact(connection, output_artifact),
                self._put_artifact(connection, quality_evidence),
                self._put_quality_result(connection, quality_result),
                self._put_observation(connection, observation),
            ):
                created = created or result.created

            lineage_events = []
            for item in spec.inputs:
                lineage_id = uuid5(
                    run.run_id,
                    "gda.blueprint-duckdb.lineage:"
                    f"{item.resource_version_id}:{spec.execution_plan_sha256}",
                )
                facets = {
                    "schema": "gda.blueprint_duckdb_lineage.v1",
                    "executor_mode": "duckdb_provider",
                    "binding_name": item.binding_name,
                    "execution_plan_sha256": spec.execution_plan_sha256,
                    "receipt_sha256": receipt.receipt_sha256,
                }
                event = LineageEvent(
                    tenant_id=receipt.tenant_id,
                    lineage_event_id=lineage_id,
                    event_type=LineageEventType.DERIVE,
                    source_resource_version_id=item.resource_version_id,
                    target_resource_version_id=output_version.resource_version_id,
                    producer=actor_subject,
                    event_sha256=canonical_json_fingerprint(
                        {
                            "schema": "gda.blueprint_duckdb_lineage.v1",
                            "lineage_event_id": str(lineage_id),
                            "source_resource_version_id": str(
                                item.resource_version_id
                            ),
                            "target_resource_version_id": str(
                                output_version.resource_version_id
                            ),
                            "run_id": str(run.run_id),
                            "definition_version_id": str(
                                run.definition_version_id
                            ),
                            "artifact_id": str(output_artifact.artifact_id),
                            "facets": facets,
                        }
                    ),
                    run_id=run.run_id,
                    definition_version_id=run.definition_version_id,
                    artifact_id=output_artifact.artifact_id,
                    facets=facets,
                    occurred_at=receipt.observed_at,
                )
                lineage_events.append(event)
                lineage_result = self._put_lineage(connection, event)
                created = created or lineage_result.created

            success_evidence = RunSuccessEvidence(
                tenant_id=receipt.tenant_id,
                run_id=run.run_id,
                attempt_observation_id=observation.observation_id,
                output_artifact_id=output_artifact.artifact_id,
                quality_result_id=quality_result.quality_result_id,
                lineage_event_id=lineage_events[0].lineage_event_id,
                evidence_sha256=run_success_evidence_fingerprint(
                    tenant_id=receipt.tenant_id,
                    run_id=run.run_id,
                    attempt_observation_id=observation.observation_id,
                    output_artifact_id=output_artifact.artifact_id,
                    quality_result_id=quality_result.quality_result_id,
                    lineage_event_id=lineage_events[0].lineage_event_id,
                ),
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.finalize_blueprint_test_run_success(
                        :tenant_id, :run_id, :expected_state_version,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": receipt.tenant_id,
                    "run_id": run.run_id,
                    "expected_state_version": run.state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(
                        {
                            "schema": "gda.run_success_evidence.v1",
                            **success_evidence.model_dump(mode="json"),
                        }
                    ),
                },
            ).scalar_one()
            completed_run = self._load_run(
                connection,
                receipt.tenant_id,
                run.run_id,
            )
            if completed_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return GatewayWriteResult(
                DataProductBlueprintTestExecution(
                    tenant_id=receipt.tenant_id,
                    run=completed_run,
                    output_resource_version=output_version,
                    attempt_observation=observation,
                    output_artifact=output_artifact,
                    quality_evidence_artifact=quality_evidence,
                    quality_result=quality_result,
                    lineage_events=tuple(lineage_events),
                    success_evidence=success_evidence,
                    executor_mode="duckdb_provider",
                ),
                created,
            )

    def execute_blueprint_duckdb_test_run(
        self,
        tenant_id: str,
        request: DuckDBBlueprintExecutionRequest,
        *,
        actor_subject: str,
        provider: DuckDBBlueprintProvider | None = None,
    ) -> GatewayWriteResult:
        """Run the local DuckDB provider outside control-plane transactions."""
        if (
            provider is None
            and self._blueprint_duckdb_result_backend == "s3"
            and self._blueprint_duckdb_object_store is None
        ):
            raise GatewayConfigurationError(
                "S3 DuckDB Blueprint execution requires the managed worker"
            )
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if actor_subject != DUCKDB_BLUEPRINT_WORKLOAD:
                raise GatewayForbiddenError(
                    "DuckDB Blueprint execution requires its dedicated workload identity"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "DuckDB provider actor does not match the admitted Run workload"
                )
            if run.status == RunStatus.SUCCEEDED:
                plan = self._load_blueprint_test_plan(
                    connection,
                    tenant_id,
                    run.run_id,
                )
                return GatewayWriteResult(
                    self._load_blueprint_duckdb_execution(
                        connection,
                        run,
                        plan,
                    ),
                    False,
                )
        prepared = self.prepare_blueprint_duckdb_test_run(
            tenant_id,
            request,
            actor_subject=actor_subject,
        )
        executor = provider or DuckDBBlueprintProvider(
            object_store=self._blueprint_duckdb_object_store,
            workspace_root=self._blueprint_duckdb_output_root,
        )
        try:
            receipt = executor.execute(prepared.value)
        except DuckDBBlueprintProviderUnavailableError as exc:
            raise GatewayUnavailableError(
                "DuckDB Blueprint provider dependency is unavailable"
            ) from exc
        except DuckDBBlueprintProviderError as exc:
            self.fail_blueprint_test_run(
                tenant_id,
                DataProductBlueprintTestExecutionFailureRequest(
                    run_id=request.run_id,
                    error_code=exc.code,
                    reason="DuckDB Blueprint provider execution failed",
                ),
                actor_subject=actor_subject,
            )
            raise GatewayValidationError(str(exc)) from exc
        return self.complete_blueprint_duckdb_test_run(
            receipt,
            actor_subject=actor_subject,
            reason=request.reason,
        )

    def execute_blueprint_test_run(
        self,
        tenant_id: str,
        request: DataProductBlueprintTestExecutionRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Execute one admitted Blueprint test through a deterministic local provider.

        The executor emits a provider receipt and all evidence required by the
        shared success authority. It is intentionally named and marked as a
        local deterministic executor; it is not a production provider
        conformance result and never publishes a DataProductVersion.
        """
        quality_evaluator = "workload:blueprint-quality-evaluator"
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "deterministic Blueprint test execution requires workload identity"
            )
        if actor_subject == quality_evaluator:
            raise GatewayForbiddenError(
                "test executor and quality evaluator must be independent workloads"
            )

        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "deterministic Blueprint test requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "test executor actor does not match the admitted Run workload"
                )

            plan_id = connection.execute(
                text(
                    """
                    SELECT artifact_id
                    FROM gda_control.artifact
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND artifact_role = 'execution_plan'
                      AND manifest ->> 'schema' =
                          'gda.data_product_blueprint_test_execution_plan.v1'
                    ORDER BY created_at, artifact_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "run_id": request.run_id},
            ).scalar_one_or_none()
            if plan_id is None:
                raise GatewayNotFoundError(
                    "Blueprint test execution plan was not found"
                )
            plan = self._load_artifact(connection, tenant_id, plan_id)
            if plan is None:
                raise GatewayNotFoundError(
                    "Blueprint test execution plan was not found"
                )
            manifest = plan.manifest
            if (
                manifest.get("execution_mode") != "admission_only"
                or manifest.get("provider_execution_required") is not True
                or not manifest.get("plan_sha256")
            ):
                raise GatewayConflictError(
                    "Blueprint test execution plan is not an executable admission"
                )
            input_manifest = tuple(manifest.get("inputs") or ())
            if not input_manifest:
                raise GatewayValidationError(
                    "Blueprint test execution plan has no admitted inputs"
                )

            created = False
            if run.status == RunStatus.ACCEPTED:
                connection.execute(
                    text(
                        """
                        SELECT gda_control.transition_platform_run(
                            :tenant_id, :run_id, :expected_state_version,
                            'dispatching', :actor_subject, :reason,
                            CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": run.run_id,
                        "expected_state_version": run.state_version,
                        "actor_subject": actor_subject,
                        "reason": "admit deterministic local Blueprint executor",
                        "details": _json(
                            {
                                "schema": "gda.blueprint_test_executor_admission.v1",
                                "execution_plan_artifact_id": str(plan.artifact_id),
                            }
                        ),
                    },
                ).scalar_one()
                run = self._load_run(connection, tenant_id, run.run_id)
                if run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                created = True
            if run.status == RunStatus.DISPATCHING:
                connection.execute(
                    text(
                        """
                        SELECT gda_control.transition_platform_run(
                            :tenant_id, :run_id, :expected_state_version,
                            'running', :actor_subject, :reason,
                            CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": run.run_id,
                        "expected_state_version": run.state_version,
                        "actor_subject": actor_subject,
                        "reason": "start deterministic local Blueprint executor",
                        "details": _json(
                            {
                                "schema": "gda.blueprint_test_executor_start.v1",
                                "execution_plan_artifact_id": str(plan.artifact_id),
                            }
                        ),
                    },
                ).scalar_one()
                run = self._load_run(connection, tenant_id, run.run_id)
                if run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                created = True
            if run.status not in {
                RunStatus.RUNNING,
                RunStatus.RECONCILING,
                RunStatus.SUCCEEDED,
            }:
                raise GatewayConflictError(
                    f"Blueprint test Run in {run.status.value} cannot be executed"
                )

            output_resource_urn = build_resource_urn(
                tenant_id,
                "dataset",
                f"blueprint-test-output-{run.run_id.hex}",
            )
            output_resource = Resource(
                tenant_id=tenant_id,
                resource_urn=output_resource_urn,
                resource_kind="dataset",
                authority_system="gda-deterministic-local",
                authority_locator=f"blueprint-test:{run.run_id}",
                owner_ref=actor_subject,
                governance_ref={
                    "schema": "gda.blueprint_test_output.v1",
                    "definition_version_id": str(run.definition_version_id),
                },
            )
            output_manifest = {
                "schema": "gda.blueprint_test_output.v1",
                "executor_mode": "deterministic_local",
                "execution_plan_sha256": manifest["plan_sha256"],
                "definition_version_id": str(run.definition_version_id),
                "test_report_sha256": manifest["test_report_sha256"],
                "input_content_sha256": [
                    item["content_sha256"] for item in input_manifest
                ],
                "verdict": "passed",
            }
            output_content_sha256 = canonical_json_fingerprint(output_manifest)
            output_version_id = uuid5(
                run.run_id,
                f"gda.blueprint-test.output-resource-version:{manifest['plan_sha256']}",
            )
            output_version = ResourceVersion(
                tenant_id=tenant_id,
                resource_urn=output_resource_urn,
                resource_version_id=output_version_id,
                version_key=f"blueprint-test-{run.run_id.hex[:16]}",
                content_sha256=output_content_sha256,
                authority_version_ref={
                    "schema": "gda.blueprint_test_output.v1",
                    "execution_plan_sha256": manifest["plan_sha256"],
                },
                created_by=actor_subject,
                created_at=plan.created_at,
            )
            resource_result = self._put_resource(connection, output_resource)
            version_result = self._put_resource_version(connection, output_version)
            created = created or resource_result.created or version_result.created

            output_artifact_id = uuid5(
                run.run_id,
                f"gda.blueprint-test.output-artifact:{manifest['plan_sha256']}",
            )
            output_artifact = Artifact(
                tenant_id=tenant_id,
                artifact_id=output_artifact_id,
                artifact_key=f"blueprint-test-output-{run.run_id.hex}",
                artifact_role=ArtifactRole.OUTPUT,
                storage_uri=f"s3://gda-control/test-outputs/{run.run_id}.json",
                media_type="application/json",
                content_sha256=output_content_sha256,
                size_bytes=len(
                    json.dumps(output_manifest, sort_keys=True, separators=(",", ":"))
                ),
                run_id=run.run_id,
                resource_version_id=output_version_id,
                manifest=output_manifest,
                created_by=actor_subject,
                created_at=plan.created_at,
            )
            output_result = self._put_artifact(connection, output_artifact)
            created = created or output_result.created

            quality_metrics = {
                "schema": "gda.blueprint_test_quality.v1",
                "executor_mode": "deterministic_local",
                "test_report_sha256": manifest["test_report_sha256"],
                "input_count": len(input_manifest),
                "output_content_sha256": output_content_sha256,
                "checks_passed": True,
            }
            quality_evidence_id = uuid5(
                run.run_id,
                f"gda.blueprint-test.quality-evidence:{manifest['plan_sha256']}",
            )
            quality_evidence = Artifact(
                tenant_id=tenant_id,
                artifact_id=quality_evidence_id,
                artifact_key=f"blueprint-test-quality-{run.run_id.hex}",
                artifact_role=ArtifactRole.EVIDENCE,
                storage_uri=f"s3://gda-control/test-quality/{run.run_id}.json",
                media_type="application/json",
                content_sha256=canonical_json_fingerprint(quality_metrics),
                size_bytes=len(
                    json.dumps(quality_metrics, sort_keys=True, separators=(",", ":"))
                ),
                run_id=run.run_id,
                resource_version_id=output_version_id,
                manifest=quality_metrics,
                created_by=quality_evaluator,
                created_at=plan.created_at,
            )
            quality_evidence_result = self._put_artifact(connection, quality_evidence)
            created = created or quality_evidence_result.created
            quality_result_id = uuid5(
                run.run_id,
                f"gda.blueprint-test.quality-result:{manifest['plan_sha256']}",
            )
            quality_result = QualityResult(
                tenant_id=tenant_id,
                quality_result_id=quality_result_id,
                run_id=run.run_id,
                resource_version_id=output_version_id,
                rule_version_ref="gda:blueprint-test-contract/v1",
                verdict=QualityVerdict.PASSED,
                metrics=quality_metrics,
                evidence_artifact_id=quality_evidence_id,
                result_sha256=quality_result_fingerprint(
                    tenant_id=tenant_id,
                    run_id=run.run_id,
                    resource_version_id=output_version_id,
                    rule_version_ref="gda:blueprint-test-contract/v1",
                    verdict=QualityVerdict.PASSED,
                    metrics=quality_metrics,
                    evidence_artifact_id=quality_evidence_id,
                    evaluated_by=quality_evaluator,
                    evaluated_at=plan.created_at,
                ),
                evaluated_by=quality_evaluator,
                evaluated_at=plan.created_at,
            )
            quality_result_write = self._put_quality_result(connection, quality_result)
            created = created or quality_result_write.created

            observation_id = uuid5(
                run.run_id,
                f"gda.blueprint-test.attempt:{manifest['plan_sha256']}",
            )
            observation_evidence = {
                "schema": "gda.blueprint_test_executor_receipt.v1",
                "executor_mode": "deterministic_local",
                "execution_plan_sha256": manifest["plan_sha256"],
                "test_report_sha256": manifest["test_report_sha256"],
                "output_artifact_id": str(output_artifact_id),
                "quality_result_id": str(quality_result_id),
            }
            observation = FrameworkAttemptObservation(
                tenant_id=tenant_id,
                observation_id=observation_id,
                run_id=run.run_id,
                attempt_no=1,
                framework_kind=FrameworkKind.DUCKDB,
                external_namespace="gda-deterministic-local",
                external_run_id=str(run.run_id),
                observed_state="success",
                observation_sha256=canonical_json_fingerprint(observation_evidence),
                evidence=observation_evidence,
                observed_at=plan.created_at,
            )
            observation_result = self._put_observation(connection, observation)
            created = created or observation_result.created

            lineage_events: list[LineageEvent] = []
            for item in input_manifest:
                source_id = UUID(item["resource_version_id"])
                lineage_id = uuid5(
                    run.run_id,
                    f"gda.blueprint-test.lineage:{source_id}:{manifest['plan_sha256']}",
                )
                lineage_facets = {
                    "schema": "gda.blueprint_test_lineage.v1",
                    "executor_mode": "deterministic_local",
                    "binding_name": item["binding_name"],
                    "execution_plan_sha256": manifest["plan_sha256"],
                }
                lineage_events.append(
                    LineageEvent(
                        tenant_id=tenant_id,
                        lineage_event_id=lineage_id,
                        event_type=LineageEventType.DERIVE,
                        source_resource_version_id=source_id,
                        target_resource_version_id=output_version_id,
                        producer=actor_subject,
                        event_sha256=canonical_json_fingerprint(
                            {
                                "schema": "gda.blueprint_test_lineage.v1",
                                "lineage_event_id": str(lineage_id),
                                "source_resource_version_id": str(source_id),
                                "target_resource_version_id": str(output_version_id),
                                "run_id": str(run.run_id),
                                "definition_version_id": str(run.definition_version_id),
                                "artifact_id": str(output_artifact_id),
                                "facets": lineage_facets,
                            }
                        ),
                        run_id=run.run_id,
                        definition_version_id=run.definition_version_id,
                        artifact_id=output_artifact_id,
                        facets=lineage_facets,
                        occurred_at=plan.created_at,
                    )
                )
            for event in lineage_events:
                lineage_result = self._put_lineage(connection, event)
                created = created or lineage_result.created

            success_evidence = RunSuccessEvidence(
                tenant_id=tenant_id,
                run_id=run.run_id,
                attempt_observation_id=observation_id,
                output_artifact_id=output_artifact_id,
                quality_result_id=quality_result_id,
                lineage_event_id=lineage_events[0].lineage_event_id,
                evidence_sha256=run_success_evidence_fingerprint(
                    tenant_id=tenant_id,
                    run_id=run.run_id,
                    attempt_observation_id=observation_id,
                    output_artifact_id=output_artifact_id,
                    quality_result_id=quality_result_id,
                    lineage_event_id=lineage_events[0].lineage_event_id,
                ),
            )
            details = {
                "schema": "gda.run_success_evidence.v1",
                **success_evidence.model_dump(mode="json"),
            }
            connection.execute(
                text(
                    """
                    SELECT gda_control.finalize_blueprint_test_run_success(
                        :tenant_id, :run_id, :expected_state_version,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "expected_state_version": run.state_version,
                    "actor_subject": actor_subject,
                    "reason": request.reason,
                    "details": _json(details),
                },
            ).scalar_one()
            completed_run = self._load_run(connection, tenant_id, run.run_id)
            if completed_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            execution = DataProductBlueprintTestExecution(
                tenant_id=tenant_id,
                run=completed_run,
                output_resource_version=output_version,
                attempt_observation=observation_result.value,
                output_artifact=output_result.value,
                quality_evidence_artifact=quality_evidence_result.value,
                quality_result=quality_result_write.value,
                lineage_events=tuple(lineage_events),
                success_evidence=success_evidence,
            )
            return GatewayWriteResult(execution, created)

    def fail_blueprint_test_run(
        self,
        tenant_id: str,
        request: DataProductBlueprintTestExecutionFailureRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Record an idempotent failure for an admitted deterministic test Run."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "deterministic Blueprint test failure requires workload identity"
            )

        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "deterministic Blueprint test requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "test failure actor does not match the admitted Run workload"
                )

            plan_id = connection.execute(
                text(
                    """
                    SELECT artifact_id
                    FROM gda_control.artifact
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND artifact_role = 'execution_plan'
                      AND manifest ->> 'schema' =
                          'gda.data_product_blueprint_test_execution_plan.v1'
                    ORDER BY created_at, artifact_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "run_id": request.run_id},
            ).scalar_one_or_none()
            if plan_id is None:
                raise GatewayNotFoundError(
                    "Blueprint test execution plan was not found"
                )

            details = {
                "schema": "gda.blueprint_test_executor_failure.v1",
                "execution_plan_artifact_id": str(plan_id),
                "error_code": request.error_code,
            }
            if run.status == RunStatus.FAILED:
                event = connection.execute(
                    text(
                        """
                        SELECT actor_subject, reason, details
                        FROM gda_control.platform_run_event
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND sequence_no = :sequence_no
                          AND to_status = 'failed'
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": request.run_id,
                        "sequence_no": run.state_version,
                    },
                ).mappings().one_or_none()
                if event is not None and (
                    event["actor_subject"] == actor_subject
                    and event["reason"] == request.reason
                    and _as_json(event["details"]) == details
                ):
                    return GatewayWriteResult(run, False)
                raise GatewayConflictError(
                    "failed Blueprint test Run has a different terminal verdict"
                )
            if run.status in {
                RunStatus.SUCCEEDED,
                RunStatus.CANCELLED,
                RunStatus.TIMED_OUT,
            }:
                raise GatewayConflictError(
                    f"Blueprint test Run in {run.status.value} cannot be failed"
                )

            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        'failed', :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": request.run_id,
                    "expected_state_version": run.state_version,
                    "actor_subject": actor_subject,
                    "reason": request.reason,
                    "details": _json(details),
                },
            ).scalar_one()
            failed_run = self._load_run(connection, tenant_id, request.run_id)
            if failed_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return GatewayWriteResult(failed_run, True)

    def complete_blueprint_test_run_cancellation(
        self,
        tenant_id: str,
        request: DataProductBlueprintTestCancellationRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Converge a governed cancellation through the shared Run authority."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "deterministic Blueprint test cancellation requires workload identity"
            )

        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "deterministic Blueprint test requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "test cancellation actor does not match the admitted Run workload"
                )
            plan_id = connection.execute(
                text(
                    """
                    SELECT artifact_id
                    FROM gda_control.artifact
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND artifact_role = 'execution_plan'
                      AND manifest ->> 'schema' =
                          'gda.data_product_blueprint_test_execution_plan.v1'
                    ORDER BY created_at, artifact_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "run_id": request.run_id},
            ).scalar_one_or_none()
            if plan_id is None:
                raise GatewayNotFoundError(
                    "Blueprint test execution plan was not found"
                )

            details = {
                "schema": "gda.blueprint_test_executor_cancel.v1",
                "execution_plan_artifact_id": str(plan_id),
                "external_cancel_ref": request.external_cancel_ref,
            }
            if run.status == RunStatus.CANCELLED:
                event = connection.execute(
                    text(
                        """
                        SELECT actor_subject, reason, details
                        FROM gda_control.platform_run_event
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND sequence_no = :sequence_no
                          AND to_status = 'cancelled'
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": request.run_id,
                        "sequence_no": run.state_version,
                    },
                ).mappings().one_or_none()
                if event is not None and (
                    event["actor_subject"] == actor_subject
                    and event["reason"] == request.reason
                    and _as_json(event["details"]) == details
                ):
                    return GatewayWriteResult(run, False)
                raise GatewayConflictError(
                    "cancelled Blueprint test Run has a different terminal verdict"
                )
            if run.status not in {RunStatus.CANCELLING, RunStatus.RECONCILING}:
                raise GatewayConflictError(
                    "Blueprint test cancellation requires a cancelling or reconciling Run"
                )

            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        'cancelled', :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": request.run_id,
                    "expected_state_version": run.state_version,
                    "actor_subject": actor_subject,
                    "reason": request.reason,
                    "details": _json(details),
                },
            ).scalar_one()
            cancelled_run = self._load_run(connection, tenant_id, request.run_id)
            if cancelled_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return GatewayWriteResult(cancelled_run, True)

    def reconcile_blueprint_test_provider(
        self,
        request: DataProductBlueprintProviderReconcileRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Atomically apply a content-bound provider receipt to a reconciling Run."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "Blueprint provider reconciliation requires workload identity"
            )

        tenant_id = request.tenant_id
        observation = request.attempt_observation
        converged_status = RunStatus(request.provider_state)
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "Blueprint provider reconciliation requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "provider reconcile actor does not match the admitted Run workload"
                )

            plan = self._load_artifact(
                connection,
                tenant_id,
                request.execution_plan_artifact_id,
            )
            if plan is None:
                raise GatewayNotFoundError("Blueprint test execution plan was not found")
            plan_manifest = plan.manifest
            if (
                plan.run_id != run.run_id
                or plan.artifact_role != ArtifactRole.EXECUTION_PLAN
                or plan_manifest.get("schema")
                != "gda.data_product_blueprint_test_execution_plan.v1"
                or plan_manifest.get("plan_sha256") != run.config_fingerprint
            ):
                raise GatewayValidationError(
                    "provider reconciliation plan does not match the admitted Blueprint Run"
                )

            observation_result = self._put_observation(connection, observation)
            event = connection.execute(
                text(
                    """
                    SELECT to_status, details
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND details ->> 'schema' = :schema
                      AND details ->> 'observation_id' = :observation_id
                    ORDER BY sequence_no
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA,
                    "observation_id": str(observation.observation_id),
                },
            ).mappings().one_or_none()
            if event is not None:
                details = _as_json(event["details"])
                if (
                    event["to_status"] != converged_status.value
                    or details.get("reconcile_receipt_sha256")
                    != request.reconcile_receipt_sha256
                ):
                    raise GatewayConflictError(
                        "provider observation already has a different reconciliation verdict"
                    )
                current_run = self._load_run(connection, tenant_id, run.run_id)
                if current_run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                reconciliation = DataProductBlueprintProviderReconciliation(
                    tenant_id=tenant_id,
                    run=current_run,
                    execution_plan=plan,
                    attempt_observation=observation_result.value,
                    provider_state=request.provider_state,
                    converged_status=converged_status,
                    reconcile_receipt_sha256=request.reconcile_receipt_sha256,
                    observation_created=observation_result.created,
                    transitioned=False,
                )
                return GatewayWriteResult(reconciliation, observation_result.created)

            if run.status != RunStatus.RECONCILING:
                raise GatewayConflictError(
                    "provider reconciliation requires a reconciling Blueprint Run"
                )
            details = {
                "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA,
                "execution_plan_artifact_id": str(plan.artifact_id),
                "observation_id": str(observation.observation_id),
                "reconcile_receipt_sha256": request.reconcile_receipt_sha256,
                "provider_state": request.provider_state,
                "framework_kind": observation.framework_kind.value,
                "external_namespace": observation.external_namespace,
                "external_run_id": observation.external_run_id,
                "external_attempt_id": observation.external_attempt_id,
            }
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        :to_status, :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "expected_state_version": run.state_version,
                    "to_status": converged_status.value,
                    "actor_subject": actor_subject,
                    "reason": request.reason,
                    "details": _json(details),
                },
            ).scalar_one()
            current_run = self._load_run(connection, tenant_id, run.run_id)
            if current_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            reconciliation = DataProductBlueprintProviderReconciliation(
                tenant_id=tenant_id,
                run=current_run,
                execution_plan=plan,
                attempt_observation=observation_result.value,
                provider_state=request.provider_state,
                converged_status=converged_status,
                reconcile_receipt_sha256=request.reconcile_receipt_sha256,
                observation_created=observation_result.created,
                transitioned=True,
            )
            return GatewayWriteResult(reconciliation, True)

    def record_blueprint_provider_cancellation_timeout(
        self,
        request: DataProductBlueprintProviderCancellationTimeoutRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Open a DataIncident and fail a Blueprint Run after cancel retries exhaust."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "Blueprint provider cancellation timeout requires workload identity"
            )

        tenant_id = request.tenant_id
        observation = request.attempt_observation
        dedupe_key = f"blueprint-cancel-timeout:{observation.observation_id}"
        incident_id = uuid5(request.run_id, dedupe_key)
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "Blueprint provider cancellation timeout requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "provider timeout actor does not match the admitted Run workload"
                )

            plan = self._load_artifact(
                connection,
                tenant_id,
                request.execution_plan_artifact_id,
            )
            if plan is None:
                raise GatewayNotFoundError("Blueprint test execution plan was not found")
            plan_manifest = plan.manifest
            if (
                plan.run_id != run.run_id
                or plan.artifact_role != ArtifactRole.EXECUTION_PLAN
                or plan_manifest.get("schema")
                != "gda.data_product_blueprint_test_execution_plan.v1"
                or plan_manifest.get("plan_sha256") != run.config_fingerprint
            ):
                raise GatewayValidationError(
                    "provider timeout plan does not match the admitted Blueprint Run"
                )

            observation_result = self._put_observation(connection, observation)
            event = connection.execute(
                text(
                    """
                    SELECT to_status, details
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND details ->> 'schema' = 'gda.data_incident_run_failure.v1'
                      AND details ->> 'incident_id' = :incident_id
                    ORDER BY sequence_no
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "incident_id": str(incident_id),
                },
            ).mappings().one_or_none()
            if event is not None:
                if event["to_status"] != RunStatus.FAILED.value:
                    raise GatewayConflictError(
                        "provider timeout observation already has a different verdict"
                    )
                incident = self._load_incident(connection, tenant_id, incident_id)
                if incident is None:
                    raise GatewayConflictError(
                        "provider timeout event is missing its DataIncident"
                    )
                if incident.details.get("timeout_receipt_sha256") != (
                    request.timeout_receipt_sha256
                ):
                    raise GatewayConflictError(
                        "provider timeout observation already has a different verdict"
                    )
                current_run = self._load_run(connection, tenant_id, run.run_id)
                if current_run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                timeout = DataProductBlueprintProviderCancellationTimeout(
                    tenant_id=tenant_id,
                    run=current_run,
                    execution_plan=plan,
                    attempt_observation=observation_result.value,
                    provider_state=request.provider_state,
                    reconcile_attempt=request.reconcile_attempt,
                    max_reconcile_attempts=request.max_reconcile_attempts,
                    incident=incident,
                    timeout_receipt_sha256=request.timeout_receipt_sha256,
                    observation_created=observation_result.created,
                    incident_created=False,
                    transitioned=False,
                )
                return GatewayWriteResult(timeout, False)

            if run.status not in {RunStatus.CANCELLING, RunStatus.RECONCILING}:
                raise GatewayConflictError(
                    "provider cancellation timeout requires a cancelling or reconciling Run"
                )
            details = {
                "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA,
                "execution_plan_artifact_id": str(plan.artifact_id),
                "observation_id": str(observation.observation_id),
                "timeout_receipt_sha256": request.timeout_receipt_sha256,
                "provider_state": request.provider_state,
                "reconcile_attempt": request.reconcile_attempt,
                "max_reconcile_attempts": request.max_reconcile_attempts,
                "framework_kind": observation.framework_kind.value,
                "external_namespace": observation.external_namespace,
                "external_run_id": observation.external_run_id,
                "external_attempt_id": observation.external_attempt_id,
            }
            incident_result = self._open_incident(
                connection,
                tenant_id=tenant_id,
                run_id=run.run_id,
                subject_resource_urn=None,
                incident_id=incident_id,
                dedupe_key=dedupe_key,
                incident_type="blueprint_provider_cancellation_timeout",
                severity=IncidentSeverity.HIGH,
                summary=(
                    "Blueprint provider cancellation did not converge before retry exhaustion"
                ),
                trigger_observation_id=observation.observation_id,
                details=details,
                detected_by=actor_subject,
            )
            current_run = self._load_run(connection, tenant_id, run.run_id)
            if current_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            failed_run = self._fail_run_for_incident(
                connection,
                current_run,
                incident_result.value,
                actor_subject=actor_subject,
                reason="Blueprint provider cancellation retries exhausted",
            )
            timeout = DataProductBlueprintProviderCancellationTimeout(
                tenant_id=tenant_id,
                run=failed_run,
                execution_plan=plan,
                attempt_observation=observation_result.value,
                provider_state=request.provider_state,
                reconcile_attempt=request.reconcile_attempt,
                max_reconcile_attempts=request.max_reconcile_attempts,
                incident=incident_result.value,
                timeout_receipt_sha256=request.timeout_receipt_sha256,
                observation_created=observation_result.created,
                incident_created=incident_result.created,
                transitioned=True,
            )
            return GatewayWriteResult(timeout, True)

    def retry_blueprint_test_provider(
        self,
        request: DataProductBlueprintProviderRetryRequest,
        *,
        actor_subject: str,
    ) -> GatewayWriteResult:
        """Record a bounded provider retry and schedule the next dispatch attempt."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "Blueprint provider retry requires workload identity"
            )

        tenant_id = request.tenant_id
        observation = request.attempt_observation
        backoff_seconds = data_product_blueprint_provider_retry_backoff_seconds(
            request.retry_attempt
        )
        retry_after = observation.observed_at + timedelta(seconds=backoff_seconds)
        command_dedupe_key = (
            f"blueprint-provider.retry:{request.run_id}:{observation.observation_id}"
        )
        retry_command = PlatformCommand(
            tenant_id=tenant_id,
            command_id=uuid5(request.run_id, command_dedupe_key),
            run_id=request.run_id,
            command_type=PlatformCommandType.BLUEPRINT_PROVIDER_RETRY,
            execution_plan_artifact_id=request.execution_plan_artifact_id,
            trigger_observation_id=observation.observation_id,
            dedupe_key=command_dedupe_key,
            actor_subject=actor_subject,
            payload={
                "schema": "gda.data_product_blueprint_provider_retry_command.v1",
                "run_id": str(request.run_id),
                "execution_plan_artifact_id": str(
                    request.execution_plan_artifact_id
                ),
                "observation_id": str(observation.observation_id),
                "provider_state": request.provider_state,
                "retry_attempt": request.retry_attempt,
                "max_retry_attempts": request.max_retry_attempts,
                "backoff_seconds": backoff_seconds,
                "retry_receipt_sha256": request.retry_receipt_sha256,
            },
            max_attempts=1,
            available_at=retry_after,
            created_at=observation.observed_at,
        )
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, request.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if run.subject_context.subject_type != SubjectType.WORKLOAD:
                raise GatewayValidationError(
                    "Blueprint provider retry requires a workload-admitted Run"
                )
            if self._run_actor(run) != actor_subject:
                raise GatewayForbiddenError(
                    "provider retry actor does not match the admitted Run workload"
                )

            plan = self._load_artifact(
                connection,
                tenant_id,
                request.execution_plan_artifact_id,
            )
            if plan is None:
                raise GatewayNotFoundError("Blueprint test execution plan was not found")
            plan_manifest = plan.manifest
            if (
                plan.run_id != run.run_id
                or plan.artifact_role != ArtifactRole.EXECUTION_PLAN
                or plan_manifest.get("schema")
                != "gda.data_product_blueprint_test_execution_plan.v1"
                or plan_manifest.get("plan_sha256") != run.config_fingerprint
            ):
                raise GatewayValidationError(
                    "provider retry plan does not match the admitted Blueprint Run"
                )

            observation_result = self._put_observation(connection, observation)
            command_result = self._put_command(connection, retry_command)
            event = connection.execute(
                text(
                    """
                    SELECT to_status, details
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND details ->> 'schema' = :schema
                      AND details ->> 'observation_id' = :observation_id
                    ORDER BY sequence_no
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA,
                    "observation_id": str(observation.observation_id),
                },
            ).mappings().one_or_none()
            if event is not None:
                details = _as_json(event["details"])
                if (
                    event["to_status"] != RunStatus.DISPATCHING.value
                    or details.get("retry_receipt_sha256")
                    != request.retry_receipt_sha256
                ):
                    raise GatewayConflictError(
                        "provider retry observation already has a different verdict"
                    )
                current_run = self._load_run(connection, tenant_id, run.run_id)
                if current_run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                retry = DataProductBlueprintProviderRetry(
                    tenant_id=tenant_id,
                    run=current_run,
                    execution_plan=plan,
                    attempt_observation=observation_result.value,
                    provider_state=request.provider_state,
                    retry_attempt=request.retry_attempt,
                    max_retry_attempts=request.max_retry_attempts,
                    backoff_seconds=backoff_seconds,
                    retry_after=retry_after,
                    retry_command=command_result.value,
                    retry_receipt_sha256=request.retry_receipt_sha256,
                    observation_created=observation_result.created,
                    command_created=command_result.created,
                    transitioned=False,
                )
                return GatewayWriteResult(retry, False)

            if run.status != RunStatus.RECONCILING:
                raise GatewayConflictError(
                    "provider retry requires a reconciling Blueprint Run"
                )
            details = {
                "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA,
                "execution_plan_artifact_id": str(plan.artifact_id),
                "observation_id": str(observation.observation_id),
                "retry_receipt_sha256": request.retry_receipt_sha256,
                "provider_state": request.provider_state,
                "retry_attempt": request.retry_attempt,
                "max_retry_attempts": request.max_retry_attempts,
                "backoff_seconds": backoff_seconds,
                "retry_after": retry_after.astimezone(UTC).isoformat().replace(
                    "+00:00", "Z"
                ),
                "framework_kind": observation.framework_kind.value,
                "external_namespace": observation.external_namespace,
                "external_run_id": observation.external_run_id,
                "external_attempt_id": observation.external_attempt_id,
            }
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        'dispatching', :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run.run_id,
                    "expected_state_version": run.state_version,
                    "actor_subject": actor_subject,
                    "reason": request.reason,
                    "details": _json(details),
                },
            ).scalar_one()
            current_run = self._load_run(connection, tenant_id, run.run_id)
            if current_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            retry = DataProductBlueprintProviderRetry(
                tenant_id=tenant_id,
                run=current_run,
                execution_plan=plan,
                attempt_observation=observation_result.value,
                provider_state=request.provider_state,
                retry_attempt=request.retry_attempt,
                max_retry_attempts=request.max_retry_attempts,
                backoff_seconds=backoff_seconds,
                retry_after=retry_after,
                retry_command=command_result.value,
                retry_receipt_sha256=request.retry_receipt_sha256,
                observation_created=observation_result.created,
                command_created=command_result.created,
                transitioned=True,
            )
            return GatewayWriteResult(retry, True)

    def _load_existing_schedule_window(
        self,
        connection,
        spec: DataOpsScheduleWindowSpec,
        stored_run: PlatformRun,
    ) -> ScheduleWindowWriteResult:
        invocation_bindings = [
            binding for binding in stored_run.input_bindings if binding.binding_name == "invocation"
        ]
        if len(invocation_bindings) != 1:
            raise GatewayConflictError("existing schedule Run does not bind exactly one invocation")
        invocation_version = self._load_resource_version(
            connection,
            spec.tenant_id,
            invocation_bindings[0].resource_version_id,
        )
        if invocation_version is None:
            raise GatewayConflictError("existing schedule Run invocation version is missing")
        try:
            invocation = parse_dataops_invocation_version(invocation_version)
        except Exception as exc:
            raise GatewayConflictError("existing schedule Run invocation is invalid") from exc
        expected = build_scheduled_dataops_submission(
            spec,
            admitted_at=invocation.requested_at,
        )
        invocation_resource = self._load_resource(
            connection,
            spec.tenant_id,
            expected.invocation_resource.resource_urn,
        )
        policy_artifact = (
            self._load_artifact(
                connection,
                spec.tenant_id,
                stored_run.policy_refs.policy_decision_artifact_id,
            )
            if stored_run.policy_refs is not None
            else None
        )
        if (
            invocation != expected.invocation
            or invocation_resource != expected.invocation_resource
            or invocation_version != expected.invocation_version
            or policy_artifact != expected.policy_artifact
            or self._run_binding(stored_run) != self._run_binding(expected.run)
        ):
            raise GatewayConflictError(
                "schedule window identity already has a different immutable binding"
            )
        decision = parse_policy_decision_artifact(expected.policy_artifact)
        execution_plan = self._load_artifact(
            connection,
            spec.tenant_id,
            spec.execution_plan_artifact_id,
        )
        if execution_plan is None:
            raise GatewayConflictError("existing schedule window execution plan is missing")
        expected_command = self._dispatch_command(
            stored_run,
            decision,
            execution_plan,
        )
        command = self._load_command(
            connection,
            spec.tenant_id,
            expected_command.command_id,
        )
        if command is None or self._command_binding(command) != self._command_binding(
            expected_command
        ):
            raise GatewayConflictError(
                "existing schedule window dispatch command is missing or inconsistent"
            )
        return ScheduleWindowWriteResult(
            window_sha256=expected.window_sha256,
            admitted_at=expected.admitted_at,
            invocation=invocation,
            run=stored_run,
            command=command,
            invocation_resource_created=False,
            invocation_version_created=False,
            policy_artifact_created=False,
            run_created=False,
            command_created=False,
        )

    def submit_schedule_window(
        self,
        spec: DataOpsScheduleWindowSpec,
    ) -> ScheduleWindowWriteResult:
        """Atomically admit one exact window and enqueue its provider dispatch."""
        with self._transaction(spec.tenant_id) as connection:
            lock_class, lock_object = dataops_schedule_lock_keys(spec)
            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(:lock_class, :lock_object)
                    """
                ),
                {
                    "lock_class": lock_class,
                    "lock_object": lock_object,
                },
            )
            stored_run = self._load_run_by_idempotency(
                connection,
                spec.tenant_id,
                spec.definition_version_id,
                dataops_schedule_idempotency_key(spec),
            )
            if stored_run is not None:
                return self._load_existing_schedule_window(
                    connection,
                    spec,
                    stored_run,
                )

            admitted_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            submission = build_scheduled_dataops_submission(
                spec,
                admitted_at=admitted_at,
            )
            resource_result = self._put_resource(
                connection,
                submission.invocation_resource,
            )
            version_result = self._put_resource_version(
                connection,
                submission.invocation_version,
            )
            policy_result = self._put_artifact(
                connection,
                submission.policy_artifact,
            )
            run_result, command_result = self._put_run(
                connection,
                submission.run,
                request_dispatch=True,
            )
            if command_result is None:
                raise GatewayConflictError("schedule window did not create a dispatch command")
            return ScheduleWindowWriteResult(
                window_sha256=submission.window_sha256,
                admitted_at=submission.admitted_at,
                invocation=submission.invocation,
                run=run_result.value,
                command=command_result.value,
                invocation_resource_created=resource_result.created,
                invocation_version_created=version_result.created,
                policy_artifact_created=policy_result.created,
                run_created=run_result.created,
                command_created=command_result.created,
            )

    def _load_existing_manual_trigger(
        self,
        connection,
        spec: DataOpsManualTriggerSpec,
        stored_run: PlatformRun,
    ) -> ManualTriggerWriteResult:
        invocation_bindings = [
            binding for binding in stored_run.input_bindings if binding.binding_name == "invocation"
        ]
        if len(invocation_bindings) != 1:
            raise GatewayConflictError("existing manual Run does not bind exactly one invocation")
        invocation_version = self._load_resource_version(
            connection,
            spec.tenant_id,
            invocation_bindings[0].resource_version_id,
        )
        if invocation_version is None:
            raise GatewayConflictError("existing manual Run invocation version is missing")
        try:
            invocation = parse_dataops_invocation_version(invocation_version)
        except Exception as exc:
            raise GatewayConflictError("existing manual Run invocation is invalid") from exc
        expected = build_manual_dataops_submission(
            spec,
            admitted_at=invocation.requested_at,
        )
        invocation_resource = self._load_resource(
            connection,
            spec.tenant_id,
            expected.invocation_resource.resource_urn,
        )
        policy_artifact = (
            self._load_artifact(
                connection,
                spec.tenant_id,
                stored_run.policy_refs.policy_decision_artifact_id,
            )
            if stored_run.policy_refs is not None
            else None
        )
        if (
            invocation != expected.invocation
            or invocation_resource != expected.invocation_resource
            or invocation_version != expected.invocation_version
            or policy_artifact != expected.policy_artifact
            or self._run_binding(stored_run) != self._run_binding(expected.run)
        ):
            raise GatewayConflictError(
                "manual request identity already has a different immutable binding"
            )
        decision = parse_policy_decision_artifact(expected.policy_artifact)
        execution_plan = self._load_artifact(
            connection,
            spec.tenant_id,
            spec.execution_plan_artifact_id,
        )
        if execution_plan is None:
            raise GatewayConflictError("existing manual request execution plan is missing")
        expected_command = self._dispatch_command(
            stored_run,
            decision,
            execution_plan,
        )
        command = self._load_command(
            connection,
            spec.tenant_id,
            expected_command.command_id,
        )
        if command is None or self._command_binding(command) != self._command_binding(
            expected_command
        ):
            raise GatewayConflictError(
                "existing manual request dispatch command is missing or inconsistent"
            )
        return ManualTriggerWriteResult(
            request_sha256=expected.request_sha256,
            admitted_at=expected.admitted_at,
            invocation=invocation,
            run=stored_run,
            command=command,
            invocation_resource_created=False,
            invocation_version_created=False,
            policy_artifact_created=False,
            run_created=False,
            command_created=False,
        )

    def submit_manual_trigger(
        self,
        spec: DataOpsManualTriggerSpec,
    ) -> ManualTriggerWriteResult:
        """Atomically admit one human request and enqueue workload dispatch."""
        with self._transaction(spec.tenant_id) as connection:
            lock_class, lock_object = dataops_manual_lock_keys(spec)
            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(:lock_class, :lock_object)
                    """
                ),
                {
                    "lock_class": lock_class,
                    "lock_object": lock_object,
                },
            )
            return self._submit_manual_trigger_in_transaction(connection, spec)

    def _submit_manual_trigger_in_transaction(
        self,
        connection,
        spec: DataOpsManualTriggerSpec,
        *,
        admitted_at: datetime | None = None,
    ) -> ManualTriggerWriteResult:
        """Write manual admission objects inside an already-scoped transaction."""
        run_id = dataops_manual_run_id(spec)
        stored_run = self._load_run(connection, spec.tenant_id, run_id)
        if stored_run is not None:
            return self._load_existing_manual_trigger(
                connection,
                spec,
                stored_run,
            )

        admitted = admitted_at
        if admitted is None:
            admitted = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        submission = build_manual_dataops_submission(
            spec,
            admitted_at=admitted,
        )
        resource_result = self._put_resource(
            connection,
            submission.invocation_resource,
        )
        version_result = self._put_resource_version(
            connection,
            submission.invocation_version,
        )
        policy_result = self._put_artifact(
            connection,
            submission.policy_artifact,
        )
        run_result, command_result = self._put_run(
            connection,
            submission.run,
            request_dispatch=True,
        )
        if command_result is None:
            raise GatewayConflictError("manual request did not create a dispatch command")
        return ManualTriggerWriteResult(
            request_sha256=submission.request_sha256,
            admitted_at=submission.admitted_at,
            invocation=submission.invocation,
            run=run_result.value,
            command=command_result.value,
            invocation_resource_created=resource_result.created,
            invocation_version_created=version_result.created,
            policy_artifact_created=policy_result.created,
            run_created=run_result.created,
            command_created=command_result.created,
        )

    def submit_spatial_anonymization_run(
        self,
        spec: SpatialAnonymizationRunSpec,
    ) -> SpatialAnonymizationRunWriteResult:
        """Atomically bind an immutable anonymization request to a DataOps Run."""
        tenant_id = spec.request.tenant_id
        with self._transaction(tenant_id) as connection:
            lock_class, lock_object = spatial_anonymization_lock_keys(spec.request)
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_class, :lock_object)"),
                {"lock_class": lock_class, "lock_object": lock_object},
            )
            admitted_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            submission = build_spatial_anonymization_submission(
                spec,
                admitted_at=admitted_at,
            )
            stored_run = self._load_run(connection, tenant_id, submission.run.run_id)
            if stored_run is not None:
                invocation_bindings = [
                    binding
                    for binding in stored_run.input_bindings
                    if binding.binding_name == "invocation"
                ]
                if len(invocation_bindings) != 1:
                    raise GatewayConflictError(
                        "existing spatial anonymization Run has no valid invocation"
                    )
                invocation_version = self._load_resource_version(
                    connection,
                    tenant_id,
                    invocation_bindings[0].resource_version_id,
                )
                if invocation_version is None:
                    raise GatewayConflictError(
                        "existing spatial anonymization invocation version is missing"
                    )
                try:
                    invocation = parse_dataops_invocation_version(invocation_version)
                except Exception as exc:
                    raise GatewayConflictError(
                        "existing spatial anonymization invocation is invalid"
                    ) from exc
                submission = build_spatial_anonymization_submission(
                    spec,
                    admitted_at=invocation.requested_at,
                )
                request_bindings = [
                    binding
                    for binding in stored_run.input_bindings
                    if binding.binding_name == "anonymization_request"
                ]
                if (
                    len(request_bindings) != 1
                    or request_bindings[0].semantic_type
                    != SPATIAL_ANONYMIZATION_SEMANTIC_TYPE
                ):
                    raise GatewayConflictError(
                        "existing spatial anonymization Run has no valid request binding"
                    )
                stored_request_version = self._load_resource_version(
                    connection,
                    tenant_id,
                    request_bindings[0].resource_version_id,
                )
                stored_request_resource = self._load_resource(
                    connection,
                    tenant_id,
                    submission.request_resource.resource_urn,
                )
                try:
                    stored_request = (
                        parse_spatial_anonymization_version(stored_request_version)
                        if stored_request_version is not None
                        else None
                    )
                except ValueError as exc:
                    raise GatewayConflictError(
                        "existing spatial anonymization request version is invalid"
                    ) from exc
                if (
                    stored_request != spec.request
                    or stored_request_resource != submission.request_resource
                    or stored_request_version != submission.request_version
                ):
                    raise GatewayConflictError(
                        "spatial anonymization request identity already has a different "
                        "immutable binding"
                    )
                manual_result = self._load_existing_manual_trigger(
                    connection,
                    submission.manual_spec,
                    stored_run,
                )
                return SpatialAnonymizationRunWriteResult.from_manual_result(
                    submission=submission,
                    manual_result=manual_result,
                    request_resource_created=False,
                    request_version_created=False,
                )

            request_resource_result = self._put_resource(
                connection,
                submission.request_resource,
            )
            request_version_result = self._put_resource_version(
                connection,
                submission.request_version,
            )
            manual_result = self._submit_manual_trigger_in_transaction(
                connection,
                submission.manual_spec,
                admitted_at=submission.admitted_at,
            )
            return SpatialAnonymizationRunWriteResult.from_manual_result(
                submission=submission,
                manual_result=manual_result,
                request_resource_created=request_resource_result.created,
                request_version_created=request_version_result.created,
            )

    def get_run(self, tenant_id: str, run_id: UUID) -> PlatformRun:
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return run

    def admit_dataops_cancel(
        self,
        spec: DataOpsCancelSpec,
    ) -> DataOpsCancelWriteResult:
        """Atomically authorize cancellation, transition the Run, and enqueue it."""
        with self._transaction(spec.tenant_id) as connection:
            lock_class, lock_object = dataops_cancel_lock_keys(spec)
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_class, :lock_object)"),
                {"lock_class": lock_class, "lock_object": lock_object},
            )
            run = self._load_run(connection, spec.tenant_id, spec.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            decision, execution_plan = self._validate_run_policy_references(connection, run)
            if decision is None or execution_plan is None:
                raise GatewayValidationError(
                    "DataOps cancellation requires immutable execution plan references"
                )

            stored_command = self._load_command(
                connection,
                spec.tenant_id,
                dataops_cancel_command_id(spec),
            )
            if stored_command is not None:
                try:
                    expected = build_dataops_cancel_submission(
                        spec,
                        run,
                        execution_plan,
                        admitted_at=stored_command.created_at,
                    )
                except ValueError as exc:
                    raise GatewayConflictError(str(exc)) from exc
                stored_policy = self._load_artifact(
                    connection,
                    spec.tenant_id,
                    expected.policy_artifact.artifact_id,
                )
                if (
                    self._command_binding(stored_command) != self._command_binding(expected.command)
                    or stored_policy != expected.policy_artifact
                ):
                    raise GatewayConflictError(
                        "cancel request identity already has a different immutable binding"
                    )
                return DataOpsCancelWriteResult(
                    request_sha256=expected.request_sha256,
                    admitted_at=expected.admitted_at,
                    run=run,
                    policy_artifact=stored_policy,
                    command=stored_command,
                    policy_artifact_created=False,
                    command_created=False,
                )

            if run.state_version != spec.expected_state_version:
                raise GatewayConflictError(
                    "PlatformRun state version changed before cancellation admission"
                )
            if run.status not in {
                RunStatus.DISPATCHING,
                RunStatus.RUNNING,
                RunStatus.RECONCILING,
            }:
                raise GatewayValidationError(
                    f"Run in {run.status.value} cannot admit provider cancellation"
                )
            admitted_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            try:
                submission = build_dataops_cancel_submission(
                    spec,
                    run,
                    execution_plan,
                    admitted_at=admitted_at,
                )
                validate_run_authorization_evidence(
                    run,
                    submission.policy_artifact,
                    None,
                    execution_plan,
                    at=admitted_at,
                    expected_action=PlatformCommandType.DOLPHINSCHEDULER_CANCEL.value,
                )
            except (ValueError, AuthorizationEvidenceError) as exc:
                raise GatewayValidationError(str(exc)) from exc

            policy_result = self._put_artifact(connection, submission.policy_artifact)
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        'cancelling', :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": spec.tenant_id,
                    "run_id": spec.run_id,
                    "expected_state_version": spec.expected_state_version,
                    "actor_subject": spec.requester_subject,
                    "reason": spec.reason,
                    "details": _json(
                        {
                            "schema": "gda.dataops_cancel_admission.v1",
                            "client_request_id": spec.client_request_id,
                            "request_sha256": submission.request_sha256,
                            "policy_decision_artifact_id": str(
                                submission.policy_artifact.artifact_id
                            ),
                        }
                    ),
                },
            ).scalar_one()
            command_result = self._put_command(connection, submission.command)
            transitioned = self._load_run(connection, spec.tenant_id, spec.run_id)
            if transitioned is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return DataOpsCancelWriteResult(
                request_sha256=submission.request_sha256,
                admitted_at=submission.admitted_at,
                run=transitioned,
                policy_artifact=submission.policy_artifact,
                command=command_result.value,
                policy_artifact_created=policy_result.created,
                command_created=command_result.created,
            )

    def transition_run(
        self,
        tenant_id: str,
        run_id: UUID,
        expected_state_version: int,
        to_status: RunStatus | str,
        actor_subject: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> PlatformRun:
        status = RunStatus(to_status)
        if status == RunStatus.SUCCEEDED:
            raise GatewayValidationError("succeeded requires evidence-gated Run finalization")
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_platform_run(
                        :tenant_id, :run_id, :expected_state_version,
                        :to_status, :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "expected_state_version": expected_state_version,
                    "to_status": status.value,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details or {}),
                },
            ).scalar_one()
            run = self._load_run(connection, tenant_id, run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return run

    def claim_platform_run_event_deliveries(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[PlatformRunEventEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_platform_run_event_deliveries(
                            :tenant_id, :worker_id, :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._run_event_envelope(
                    connection, self._run_event_delivery_from_row(row)
                )
                for row in rows
            )

    def complete_platform_run_event_delivery(
        self, tenant_id: str, delivery_id: UUID, *, worker_id: str
    ) -> PlatformRunEventDelivery:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.complete_platform_run_event_delivery(
                            :tenant_id, :delivery_id, :worker_id
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "delivery_id": delivery_id,
                        "worker_id": worker_id,
                    },
                )
                .mappings()
                .one()
            )
            return self._run_event_delivery_from_row(row)

    def fail_platform_run_event_delivery(
        self,
        tenant_id: str,
        delivery_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> PlatformRunEventDelivery:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.fail_platform_run_event_delivery(
                            :tenant_id, :delivery_id, :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "delivery_id": delivery_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._run_event_delivery_from_row(row)

    @staticmethod
    def _load_observation(
        connection, tenant_id: str, observation_id: UUID
    ) -> FrameworkAttemptObservation | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, observation_id, run_id, attempt_no,
                       framework_kind, external_namespace, external_run_id,
                       external_attempt_id, observed_state,
                       observation_sha256, evidence, observed_at
                FROM gda_control.framework_attempt_observation
                WHERE tenant_id = :tenant_id AND observation_id = :observation_id
                """
                ),
                {"tenant_id": tenant_id, "observation_id": observation_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["evidence"] = _as_json(value["evidence"])
        return FrameworkAttemptObservation.model_validate(value)

    def _put_observation(
        self, connection, observation: FrameworkAttemptObservation
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.framework_attempt_observation (
                    tenant_id, observation_id, run_id, attempt_no,
                    framework_kind, external_namespace, external_run_id,
                    external_attempt_id, observed_state,
                    observation_sha256, evidence, observed_at
                ) VALUES (
                    :tenant_id, :observation_id, :run_id, :attempt_no,
                    :framework_kind, :external_namespace, :external_run_id,
                    :external_attempt_id, :observed_state,
                    :observation_sha256, CAST(:evidence AS jsonb), :observed_at
                )
                ON CONFLICT DO NOTHING
                RETURNING observation_id
                """
            ),
            {
                **observation.model_dump(mode="python", exclude={"evidence"}),
                "framework_kind": observation.framework_kind.value,
                "evidence": _json(observation.evidence),
            },
        ).first()
        stored = self._load_observation(
            connection, observation.tenant_id, observation.observation_id
        )
        if stored is None or stored != observation:
            raise GatewayConflictError(
                "attempt observation identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def record_attempt(self, observation: FrameworkAttemptObservation) -> GatewayWriteResult:
        with self._transaction(observation.tenant_id) as connection:
            return self._put_observation(connection, observation)

    def get_attempt_observation(
        self, tenant_id: str, observation_id: UUID
    ) -> FrameworkAttemptObservation:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            observation = self._load_observation(connection, tenant, observation_id)
            if observation is None:
                raise GatewayNotFoundError("FrameworkAttemptObservation was not found")
            return observation

    @staticmethod
    def _incident_from_row(row) -> DataIncident:
        value = dict(row)
        value["details"] = _as_json(value["details"])
        return DataIncident.model_validate(value)

    @staticmethod
    def _incident_event_from_row(row) -> DataIncidentEvent:
        value = dict(row)
        value["details"] = _as_json(value["details"])
        return DataIncidentEvent.model_validate(value)

    @staticmethod
    def _notification_from_row(row) -> IncidentNotification:
        value = dict(row)
        value["provider_receipt"] = _as_json(value.get("provider_receipt", {}))
        return IncidentNotification.model_validate(value)

    @classmethod
    def _load_incident(
        cls, connection, tenant_id: str, incident_id: UUID
    ) -> DataIncident | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, incident_id, run_id, subject_resource_urn, dedupe_key,
                       incident_type, severity, summary,
                       trigger_observation_id, details, incident_sha256,
                       detected_by, status, state_version, opened_at, updated_at
                FROM gda_control.data_incident
                WHERE tenant_id = :tenant_id AND incident_id = :incident_id
                """
                ),
                {"tenant_id": tenant_id, "incident_id": incident_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._incident_from_row(row) if row is not None else None

    @classmethod
    def _put_incident(cls, connection, incident: DataIncident) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.data_incident (
                    tenant_id, incident_id, run_id, subject_resource_urn, dedupe_key,
                    incident_type, severity, summary,
                    trigger_observation_id, details, incident_sha256,
                    detected_by, status, state_version, opened_at, updated_at
                ) VALUES (
                    :tenant_id, :incident_id, :run_id, :subject_resource_urn, :dedupe_key,
                    :incident_type, :severity, :summary,
                    :trigger_observation_id, CAST(:details AS jsonb), :incident_sha256,
                    :detected_by, :status, :state_version, :opened_at, :updated_at
                )
                ON CONFLICT DO NOTHING
                RETURNING incident_id
                """
            ),
            {
                **incident.model_dump(mode="python", exclude={"details"}),
                "severity": incident.severity.value,
                "status": incident.status.value,
                "details": _json(incident.details),
            },
        ).first()
        stored = cls._load_incident(connection, incident.tenant_id, incident.incident_id)
        if stored is None or stored != incident:
            raise GatewayConflictError("DataIncident identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    @classmethod
    def _open_incident(
        cls,
        connection,
        *,
        tenant_id: str,
        run_id: UUID | None,
        subject_resource_urn: str | None,
        incident_id: UUID,
        dedupe_key: str,
        incident_type: str,
        severity: IncidentSeverity,
        summary: str,
        trigger_observation_id: UUID | None,
        details: dict[str, Any],
        detected_by: str,
    ) -> GatewayWriteResult:
        existing = cls._load_incident(connection, tenant_id, incident_id)
        if existing is not None:
            binding = (
                existing.run_id,
                existing.subject_resource_urn,
                existing.dedupe_key,
                existing.incident_type,
                existing.severity,
                existing.summary,
                existing.trigger_observation_id,
                existing.details,
                existing.detected_by,
            )
            expected = (
                run_id,
                subject_resource_urn,
                dedupe_key,
                incident_type,
                severity,
                summary,
                trigger_observation_id,
                details,
                detected_by,
            )
            if binding != expected:
                raise GatewayConflictError(
                    "DataIncident identity already has a different immutable binding"
                )
            return GatewayWriteResult(existing, False)

        opened_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        incident = DataIncident(
            tenant_id=tenant_id,
            incident_id=incident_id,
            run_id=run_id,
            subject_resource_urn=subject_resource_urn,
            dedupe_key=dedupe_key,
            incident_type=incident_type,
            severity=severity,
            summary=summary,
            trigger_observation_id=trigger_observation_id,
            details=details,
            incident_sha256=data_incident_fingerprint(
                tenant_id=tenant_id,
                run_id=run_id,
                dedupe_key=dedupe_key,
                incident_type=incident_type,
                severity=severity,
                summary=summary,
                trigger_observation_id=trigger_observation_id,
                details=details,
                detected_by=detected_by,
                opened_at=opened_at,
                subject_resource_urn=subject_resource_urn,
            ),
            detected_by=detected_by,
            opened_at=opened_at,
            updated_at=opened_at,
        )
        return cls._put_incident(connection, incident)

    def open_resource_incident(
        self,
        *,
        tenant_id: str,
        subject_resource_urn: str,
        incident_id: UUID,
        dedupe_key: str,
        incident_type: str,
        severity: IncidentSeverity,
        summary: str,
        details: dict[str, Any],
        detected_by: str,
    ) -> GatewayWriteResult:
        """Open one idempotent incident bound to a governed non-Run resource."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        subject = parse_resource_urn(subject_resource_urn)
        if subject["tenant_id"] != tenant:
            raise GatewayForbiddenError("incident subject tenant does not match tenant context")
        with self._transaction(tenant) as connection:
            return self._open_incident(
                connection,
                tenant_id=tenant,
                run_id=None,
                subject_resource_urn=subject_resource_urn,
                incident_id=incident_id,
                dedupe_key=dedupe_key,
                incident_type=incident_type,
                severity=severity,
                summary=summary,
                trigger_observation_id=None,
                details=details,
                detected_by=detected_by,
            )

    def open_gis_service_slo_incident(
        self,
        *,
        tenant_id: str,
        service_urn: str,
        slo_definition_ref: str,
        active_version_ref: str,
        definition_fingerprint: str,
        approval_case_ref: str,
        activation_version: int,
        incident_id: UUID,
        dedupe_key: str,
        incident_type: str,
        severity: IncidentSeverity,
        summary: str,
        details: dict[str, Any],
        detected_by: str,
    ) -> GatewayWriteResult:
        """Open an incident only while the exact active GIS ServiceSLO is locked."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        subject = parse_resource_urn(service_urn)
        if subject["tenant_id"] != tenant or subject["resource_kind"] != "gis_service":
            raise GatewayForbiddenError("GIS ServiceSLO incident subject is invalid")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.assert_gis_service_slo_incident_authority(
                        :tenant_id, :service_urn, :slo_definition_ref,
                        :active_version_ref, :definition_fingerprint,
                        :approval_case_ref, :activation_version
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "service_urn": service_urn,
                    "slo_definition_ref": slo_definition_ref,
                    "active_version_ref": active_version_ref,
                    "definition_fingerprint": definition_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "activation_version": activation_version,
                },
            ).scalar_one()
            return self._open_incident(
                connection,
                tenant_id=tenant,
                run_id=None,
                subject_resource_urn=service_urn,
                incident_id=incident_id,
                dedupe_key=dedupe_key,
                incident_type=incident_type,
                severity=severity,
                summary=summary,
                trigger_observation_id=None,
                details=details,
                detected_by=detected_by,
            )

    @classmethod
    def _load_delivered_cancel(
        cls, connection, tenant_id: str, run_id: UUID
    ) -> PlatformCommand | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, command_id, run_id, command_type,
                           execution_plan_artifact_id, trigger_observation_id,
                           dedupe_key, actor_subject, payload, status,
                           attempt_count, max_attempts, available_at,
                           claimed_by, claimed_until, last_error,
                           created_at, completed_at
                    FROM gda_control.platform_command_outbox
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND command_type = 'dolphinscheduler.cancel'
                      AND status = 'done'
                    ORDER BY completed_at DESC, command_id DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._command_from_row(row) if row is not None else None

    @classmethod
    def _has_governed_cancel(cls, connection, tenant_id: str, run_id: UUID) -> bool:
        return cls._load_delivered_cancel(connection, tenant_id, run_id) is not None

    @classmethod
    def _load_cancel_requested_at(
        cls, connection, tenant_id: str, run_id: UUID
    ) -> datetime | None:
        """Return the immutable PlatformRun time at which cancellation was admitted."""
        return connection.execute(
            text(
                """
                SELECT occurred_at
                FROM gda_control.platform_run_event
                WHERE tenant_id = :tenant_id
                  AND run_id = :run_id
                  AND to_status = 'cancelling'
                  AND details ->> 'schema' = 'gda.dataops_cancel_admission.v1'
                ORDER BY occurred_at DESC, sequence_no DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).scalar_one_or_none()

    @staticmethod
    def _cancel_terminal_evidence_is_current(
        observed_at: datetime, cancel_requested_at: datetime
    ) -> bool:
        """Account only for DolphinScheduler 3.4's whole-second timestamps."""
        return observed_at + timedelta(seconds=1) >= cancel_requested_at

    @classmethod
    def _fail_run_for_incident(
        cls,
        connection,
        run: PlatformRun,
        incident: DataIncident,
        *,
        actor_subject: str,
        reason: str,
    ) -> PlatformRun:
        if run.status == RunStatus.FAILED:
            return run
        if run.status in TERMINAL_RUN_STATUSES:
            raise GatewayConflictError(
                "DataIncident cannot rewrite an independently terminal PlatformRun"
            )
        connection.execute(
            text(
                """
                SELECT gda_control.transition_platform_run(
                    :tenant_id, :run_id, :expected_state_version,
                    'failed', :actor_subject, :reason, CAST(:details AS jsonb)
                )
                """
            ),
            {
                "tenant_id": run.tenant_id,
                "run_id": run.run_id,
                "expected_state_version": run.state_version,
                "actor_subject": actor_subject,
                "reason": reason,
                "details": _json(
                    {
                        "schema": "gda.data_incident_run_failure.v1",
                        "incident_id": str(incident.incident_id),
                        "incident_type": incident.incident_type,
                        "incident_sha256": incident.incident_sha256,
                    }
                ),
            },
        ).scalar_one()
        transitioned = cls._load_run(connection, run.tenant_id, run.run_id)
        if transitioned is None:
            raise GatewayNotFoundError("PlatformRun was not found")
        return transitioned

    def record_cancellation_terminal_mismatch(
        self,
        observation: FrameworkAttemptObservation,
        *,
        actor_subject: str,
    ) -> CancellationIncidentWriteResult:
        """Fail a cancelled Run when provider evidence reaches a non-STOP terminal state."""
        with self._transaction(observation.tenant_id) as connection:
            self._put_observation(connection, observation)
            run = self._load_run(connection, observation.tenant_id, observation.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if actor_subject != self._run_actor(run):
                raise GatewayForbiddenError(
                    "cancellation incident actor does not match Run workload identity"
                )
            provider_state = str(observation.evidence.get("provider_state") or "").upper()
            if (
                observation.framework_kind.value != "dolphinscheduler"
                or observation.observed_state.upper() != provider_state
                or provider_state not in {"FAILURE", "SUCCESS", "PAUSE"}
            ):
                raise GatewayValidationError(
                    "cancellation terminal mismatch requires non-STOP provider terminal evidence"
                )
            if run.status not in {
                RunStatus.CANCELLING,
                RunStatus.RECONCILING,
                RunStatus.FAILED,
            }:
                raise GatewayValidationError(
                    f"Run in {run.status.value} cannot record a cancellation terminal mismatch"
                )
            cancel_command = self._load_delivered_cancel(
                connection, run.tenant_id, run.run_id
            )
            if cancel_command is None or cancel_command.completed_at is None:
                raise GatewayValidationError(
                    "cancellation terminal mismatch requires a delivered governed cancel command"
                )
            cancel_requested_at = self._load_cancel_requested_at(
                connection, run.tenant_id, run.run_id
            )
            if cancel_requested_at is None:
                raise GatewayValidationError(
                    "cancellation terminal mismatch requires an immutable cancel admission event"
                )
            if not self._cancel_terminal_evidence_is_current(
                observation.observed_at, cancel_requested_at
            ):
                raise GatewayValidationError(
                    "cancellation terminal evidence predates governed cancel admission"
                )

            dedupe_key = f"cancel-terminal:{observation.observation_id}"
            incident_id = uuid5(run.run_id, dedupe_key)
            details = {
                "schema": "gda.dataops_cancel_terminal_mismatch.v1",
                "provider_state": provider_state,
                "observation_id": str(observation.observation_id),
                "external_namespace": observation.external_namespace,
                "external_run_id": observation.external_run_id,
            }
            incident_result = self._open_incident(
                connection,
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                subject_resource_urn=None,
                incident_id=incident_id,
                dedupe_key=dedupe_key,
                incident_type="provider_cancel_terminal_mismatch",
                severity=IncidentSeverity.HIGH,
                summary=(
                    "DolphinScheduler reached a non-STOP terminal state after governed cancellation"
                ),
                trigger_observation_id=observation.observation_id,
                details=details,
                detected_by=actor_subject,
            )
            current_run = self._load_run(connection, run.tenant_id, run.run_id)
            if current_run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            failed_run = self._fail_run_for_incident(
                connection,
                current_run,
                incident_result.value,
                actor_subject=actor_subject,
                reason="provider cancellation did not converge to STOP",
            )
            return CancellationIncidentWriteResult(
                run=failed_run,
                incident=incident_result.value,
                incident_created=incident_result.created,
            )

    def get_incident(self, tenant_id: str, incident_id: UUID) -> DataIncident:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            incident = self._load_incident(connection, tenant, incident_id)
            if incident is None:
                raise GatewayNotFoundError("DataIncident was not found")
            return incident

    def list_incidents(
        self,
        tenant_id: str,
        *,
        status: IncidentStatus | str | None = None,
        run_id: UUID | None = None,
        subject_resource_urn: str | None = None,
        limit: int = 100,
    ) -> tuple[DataIncident, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if not 1 <= limit <= 500:
            raise GatewayValidationError("incident query limit must be between 1 and 500")
        normalized_status = IncidentStatus(status).value if status is not None else None
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, incident_id, run_id, subject_resource_urn, dedupe_key,
                               incident_type, severity, summary,
                               trigger_observation_id, details, incident_sha256,
                               detected_by, status, state_version, opened_at, updated_at
                        FROM gda_control.data_incident
                        WHERE tenant_id = :tenant_id
                          AND (CAST(:status AS TEXT) IS NULL OR status = CAST(:status AS TEXT))
                          AND (CAST(:run_id AS UUID) IS NULL OR run_id = CAST(:run_id AS UUID))
                          AND (
                              CAST(:subject_resource_urn AS TEXT) IS NULL
                              OR subject_resource_urn = CAST(:subject_resource_urn AS TEXT)
                          )
                        ORDER BY
                            CASE severity
                                WHEN 'critical' THEN 0
                                WHEN 'high' THEN 1
                                WHEN 'medium' THEN 2
                                ELSE 3
                            END,
                            opened_at DESC,
                            incident_id
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "status": normalized_status,
                        "run_id": run_id,
                        "subject_resource_urn": subject_resource_urn,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(self._incident_from_row(row) for row in rows)

    def transition_incident(
        self,
        tenant_id: str,
        incident_id: UUID,
        expected_state_version: int,
        to_status: IncidentStatus | str,
        actor_subject: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> DataIncident:
        status = IncidentStatus(to_status)
        if status == IncidentStatus.OPEN:
            raise GatewayValidationError("resolved incidents cannot be reopened")
        with self._transaction(tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_data_incident(
                        :tenant_id, :incident_id, :expected_state_version,
                        :to_status, :actor_subject, :reason,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "incident_id": incident_id,
                    "expected_state_version": expected_state_version,
                    "to_status": status.value,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details or {}),
                },
            ).scalar_one()
            incident = self._load_incident(connection, tenant_id, incident_id)
            if incident is None:
                raise GatewayNotFoundError("DataIncident was not found")
            return incident

    @classmethod
    def _load_incident_event(
        cls, connection, tenant_id: str, event_id: UUID
    ) -> DataIncidentEvent | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, event_id, incident_id, sequence_no,
                           from_status, to_status, actor_subject, reason,
                           details, occurred_at
                    FROM gda_control.data_incident_event
                    WHERE tenant_id = :tenant_id AND event_id = :event_id
                    """
                ),
                {"tenant_id": tenant_id, "event_id": event_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._incident_event_from_row(row) if row is not None else None

    @classmethod
    def _notification_envelope(
        cls, connection, notification: IncidentNotification
    ) -> IncidentNotificationEnvelope:
        incident = cls._load_incident(
            connection, notification.tenant_id, notification.incident_id
        )
        event = cls._load_incident_event(
            connection, notification.tenant_id, notification.incident_event_id
        )
        if incident is None or event is None:
            raise GatewayNotFoundError("Incident notification binding was not found")
        return IncidentNotificationEnvelope(
            notification=notification,
            incident=incident,
            event=event,
        )

    def claim_incident_notifications(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[IncidentNotificationEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_data_incident_notifications(
                            :tenant_id, :worker_id, :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._notification_envelope(
                    connection, self._notification_from_row(row)
                )
                for row in rows
            )

    def list_incident_notifications(
        self,
        tenant_id: str,
        incident_id: UUID,
    ) -> tuple[IncidentNotification, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load_incident(connection, tenant, incident_id) is None:
                raise GatewayNotFoundError("DataIncident was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM gda_control.data_incident_notification_outbox
                        WHERE tenant_id = :tenant_id AND incident_id = :incident_id
                        ORDER BY incident_sequence_no, created_at, notification_id
                        """
                    ),
                    {"tenant_id": tenant, "incident_id": incident_id},
                )
                .mappings()
                .all()
            )
            return tuple(self._notification_from_row(row) for row in rows)

    def complete_incident_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
        provider_receipt: dict[str, Any],
    ) -> IncidentNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.complete_data_incident_notification(
                            :tenant_id, :notification_id, :worker_id,
                            CAST(:provider_receipt AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                        "provider_receipt": _json(provider_receipt),
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)

    def fail_incident_notification(
        self,
        tenant_id: str,
        notification_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> IncidentNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.fail_data_incident_notification(
                            :tenant_id, :notification_id, :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)

    def recover_incident_notification(
        self,
        tenant_id: str,
        incident_id: UUID,
        notification_id: UUID,
        *,
        expected_attempt_count: int,
        expected_receipt_sha256: str,
        actor_subject: str,
        reason: str,
    ) -> IncidentNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if expected_attempt_count < 1:
            raise GatewayValidationError(
                "expected notification attempt count must be positive"
            )
        if not actor_subject.startswith("human:"):
            raise GatewayForbiddenError(
                "incident notification recovery requires a human identity"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha256 or ""):
            raise GatewayValidationError("expected failure receipt hash is required")
        if not reason.strip() or len(reason.strip()) > 512:
            raise GatewayValidationError("notification recovery reason is required")
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.recover_data_incident_notification(
                            :tenant_id, :incident_id, :notification_id,
                            :expected_attempt_count, :expected_receipt_sha256,
                            :actor_subject, :reason
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "incident_id": incident_id,
                        "notification_id": notification_id,
                        "expected_attempt_count": expected_attempt_count,
                        "expected_receipt_sha256": expected_receipt_sha256,
                        "actor_subject": actor_subject,
                        "reason": reason,
                    },
                )
                .mappings()
                .one()
            )
            return self._notification_from_row(row)

    def incident_notification_recoveries(
        self,
        tenant_id: str,
        incident_id: UUID,
        notification_id: UUID,
    ) -> tuple[IncidentNotificationRecoveryEvent, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, recovery_event_id, notification_id,
                               incident_id, incident_event_id, recovery_no,
                               actor_subject, reason, previous_status,
                               previous_attempt_count, previous_max_attempts,
                               previous_last_error, previous_provider_receipt,
                               previous_receipt_sha256, previous_terminal_worker_id,
                               previous_completed_at, occurred_at
                        FROM gda_control.data_incident_notification_recovery_event
                        WHERE tenant_id = :tenant_id
                          AND incident_id = :incident_id
                          AND notification_id = :notification_id
                        ORDER BY recovery_no, recovery_event_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "incident_id": incident_id,
                        "notification_id": notification_id,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                IncidentNotificationRecoveryEvent.model_validate(
                    {
                        **dict(row),
                        "previous_provider_receipt": _as_json(
                            row["previous_provider_receipt"]
                        ),
                    }
                )
                for row in rows
            )

    @staticmethod
    def _load_quality_result(
        connection, tenant_id: str, quality_result_id: UUID
    ) -> QualityResult | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, quality_result_id, run_id,
                       resource_version_id, rule_version_ref, verdict,
                       metrics, evidence_artifact_id, result_sha256,
                       evaluated_by, evaluated_at
                FROM gda_control.quality_result
                WHERE tenant_id = :tenant_id
                  AND quality_result_id = :quality_result_id
                """
                ),
                {
                    "tenant_id": tenant_id,
                    "quality_result_id": quality_result_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["metrics"] = _as_json(value["metrics"])
        return QualityResult.model_validate(value)

    def _put_quality_result(
        self, connection, quality: QualityResult
    ) -> GatewayWriteResult:
        inserted = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.quality_result (
                        tenant_id, quality_result_id, run_id,
                        resource_version_id, rule_version_ref, verdict,
                        metrics, evidence_artifact_id, result_sha256,
                        evaluated_by, evaluated_at
                    ) VALUES (
                        :tenant_id, :quality_result_id, :run_id,
                        :resource_version_id, :rule_version_ref, :verdict,
                        CAST(:metrics AS jsonb), :evidence_artifact_id,
                        :result_sha256, :evaluated_by, :evaluated_at
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING quality_result_id
                    """
                ),
                {
                    **quality.model_dump(mode="python", exclude={"metrics"}),
                    "verdict": quality.verdict.value,
                    "metrics": _json(quality.metrics),
                },
            ).first()
        stored = self._load_quality_result(
            connection,
            quality.tenant_id,
            quality.quality_result_id,
        )
        if stored is None or stored != quality:
            raise GatewayConflictError("QualityResult identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    def record_quality_result(self, quality: QualityResult) -> GatewayWriteResult:
        with self._transaction(quality.tenant_id) as connection:
            return self._put_quality_result(connection, quality)

    def get_quality_result(self, tenant_id: str, quality_result_id: UUID) -> QualityResult:
        with self._transaction(tenant_id) as connection:
            quality = self._load_quality_result(connection, tenant_id, quality_result_id)
            if quality is None:
                raise GatewayNotFoundError("QualityResult was not found")
            return quality

    def finalize_run_success(
        self,
        evidence: RunSuccessEvidence,
        *,
        expected_state_version: int,
        actor_subject: str,
        reason: str,
    ) -> PlatformRun:
        details = {
            "schema": "gda.run_success_evidence.v1",
            **evidence.model_dump(mode="json"),
        }
        with self._transaction(evidence.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.finalize_platform_run_success(
                        :tenant_id, :run_id, :expected_state_version,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": evidence.tenant_id,
                    "run_id": evidence.run_id,
                    "expected_state_version": expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "details": _json(details),
                },
            ).scalar_one()
            run = self._load_run(connection, evidence.tenant_id, evidence.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return run

    @classmethod
    def _reconcile_command(
        cls,
        run: PlatformRun,
        execution_plan: Artifact,
        *,
        source_id: UUID,
        trigger_observation_id: UUID | None,
        created_at: datetime,
        reason: str,
    ) -> PlatformCommand:
        dedupe_key = (
            f"dolphinscheduler.reconcile:{run.run_id}:{execution_plan.artifact_id}:{source_id}"
        )
        return PlatformCommand(
            tenant_id=run.tenant_id,
            command_id=uuid5(source_id, dedupe_key),
            run_id=run.run_id,
            command_type=PlatformCommandType.DOLPHINSCHEDULER_RECONCILE,
            execution_plan_artifact_id=execution_plan.artifact_id,
            trigger_observation_id=trigger_observation_id,
            dedupe_key=dedupe_key,
            actor_subject=cls._run_actor(run),
            payload={
                "schema": "gda.dolphinscheduler_reconcile_command.v1",
                "reason": reason,
            },
            available_at=created_at,
            created_at=created_at,
        )

    def record_attempt_and_enqueue_reconcile(
        self,
        observation: FrameworkAttemptObservation,
        *,
        actor_subject: str,
    ) -> CallbackWriteResult:
        with self._transaction(observation.tenant_id) as connection:
            run = self._load_run(connection, observation.tenant_id, observation.run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if observation.framework_kind.value != "dolphinscheduler":
                raise GatewayValidationError(
                    "provider callback must use DolphinScheduler framework kind"
                )
            if run.subject_context.subject_type.value != "workload":
                raise GatewayForbiddenError("provider callback requires workload SubjectContext")
            if actor_subject != self._run_actor(run):
                raise GatewayForbiddenError("callback actor does not match Run workload identity")
            decision, execution_plan = self._validate_run_policy_references(connection, run)
            if decision is None or execution_plan is None:
                raise GatewayValidationError(
                    "provider callback requires immutable execution plan references"
                )
            if decision.action != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH.value:
                raise GatewayValidationError(
                    "Run policy action does not match DolphinScheduler dispatch"
                )
            observation_result = self._put_observation(connection, observation)
            if run.status in TERMINAL_RUN_STATUSES:
                return CallbackWriteResult(
                    observation=observation_result.value,
                    command=None,
                    observation_created=observation_result.created,
                    command_created=False,
                    ignored_terminal=True,
                )
            enqueued_at = datetime.now(UTC)
            command = self._reconcile_command(
                run,
                execution_plan,
                source_id=observation.observation_id,
                trigger_observation_id=observation.observation_id,
                created_at=enqueued_at,
                reason="provider_callback",
            )
            command_result = self._put_command(connection, command)
            return CallbackWriteResult(
                observation=observation_result.value,
                command=command_result.value,
                observation_created=observation_result.created,
                command_created=command_result.created,
                ignored_terminal=False,
            )

    def get_command(self, tenant_id: str, command_id: UUID) -> PlatformCommand:
        with self._transaction(tenant_id) as connection:
            command = self._load_command(connection, tenant_id, command_id)
            if command is None:
                raise GatewayNotFoundError("Platform command was not found")
            return command

    def claim_commands(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        actor_subject: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> list[PlatformCommand]:
        with self._transaction(tenant_id) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM gda_control.claim_platform_commands(
                        :tenant_id, :actor_subject, :worker_id,
                        :limit, :lease_seconds
                    )
                    """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "actor_subject": actor_subject,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return [self._command_from_row(row) for row in rows]

    @staticmethod
    def _gis_mvt_cache_purge_from_row(row) -> GISMVTCachePurgeTask:
        return GISMVTCachePurgeTask.model_validate(dict(row))

    def claim_gis_mvt_cache_purges(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        actor_subject: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[GISMVTCachePurgeTask, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_gis_mvt_cache_purges(
                            :tenant_id, :actor_subject, :worker_id,
                            :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "actor_subject": actor_subject,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(self._gis_mvt_cache_purge_from_row(row) for row in rows)

    def complete_gis_mvt_cache_purge(
        self,
        tenant_id: str,
        purge_task_id: UUID,
        *,
        worker_id: str,
        matched_keys: int,
        deleted_keys: int,
        remaining_keys: int,
    ) -> GISMVTCachePurgeTask:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.complete_gis_mvt_cache_purge(
                              :tenant_id, CAST(:purge_task_id AS uuid),
                              :worker_id, :matched_keys, :deleted_keys,
                              :remaining_keys
                          )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "purge_task_id": purge_task_id,
                        "worker_id": worker_id,
                        "matched_keys": matched_keys,
                        "deleted_keys": deleted_keys,
                        "remaining_keys": remaining_keys,
                    },
                )
                .mappings()
                .one()
            )
            task = self._gis_mvt_cache_purge_from_row(row)
            if task.status != GISMVTCachePurgeStatus.DONE:
                raise GatewayValidationError("cache purge did not reach done")
            return task

    def fail_gis_mvt_cache_purge(
        self,
        tenant_id: str,
        purge_task_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> GISMVTCachePurgeTask:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.fail_gis_mvt_cache_purge(
                            :tenant_id, CAST(:purge_task_id AS uuid),
                            :worker_id, :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "purge_task_id": purge_task_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._gis_mvt_cache_purge_from_row(row)

    def complete_command(
        self, tenant_id: str, command_id: UUID, *, worker_id: str
    ) -> PlatformCommand:
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM gda_control.complete_platform_command(
                        :tenant_id, :command_id, :worker_id
                    )
                    """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "command_id": command_id,
                        "worker_id": worker_id,
                    },
                )
                .mappings()
                .one()
            )
            return self._command_from_row(row)

    def fail_command(
        self,
        tenant_id: str,
        command_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> PlatformCommand:
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM gda_control.fail_platform_command(
                        :tenant_id, :command_id, :worker_id,
                        :error, :retry_delay_seconds
                    )
                    """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "command_id": command_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            command = self._command_from_row(row)
            if (
                command.status == PlatformCommandStatus.FAILED
                and command.command_type == PlatformCommandType.DOLPHINSCHEDULER_RECONCILE
                and command.payload.get("reason") == "provider_cancel_requested"
            ):
                run = self._load_run(connection, tenant_id, command.run_id)
                if run is None:
                    raise GatewayNotFoundError("PlatformRun was not found")
                if run.status in {RunStatus.CANCELLING, RunStatus.RECONCILING}:
                    if not self._has_governed_cancel(connection, tenant_id, run.run_id):
                        raise GatewayValidationError(
                            "cancellation convergence timeout has no delivered cancel command"
                        )
                    dedupe_key = f"cancel-timeout:{command.command_id}"
                    incident_result = self._open_incident(
                        connection,
                        tenant_id=tenant_id,
                        run_id=run.run_id,
                        subject_resource_urn=None,
                        incident_id=uuid5(run.run_id, dedupe_key),
                        dedupe_key=dedupe_key,
                        incident_type="cancellation_convergence_timeout",
                        severity=IncidentSeverity.HIGH,
                        summary=(
                            "DolphinScheduler cancellation did not converge before retry exhaustion"
                        ),
                        trigger_observation_id=command.trigger_observation_id,
                        details={
                            "schema": "gda.dataops_cancel_convergence_timeout.v1",
                            "command_id": str(command.command_id),
                            "attempt_count": command.attempt_count,
                            "max_attempts": command.max_attempts,
                            "last_error": command.last_error,
                        },
                        detected_by=self._run_actor(run),
                    )
                    self._fail_run_for_incident(
                        connection,
                        run,
                        incident_result.value,
                        actor_subject=self._run_actor(run),
                        reason="provider cancellation convergence retries exhausted",
                    )
            return command

    def fail_gis_service_endpoint_warmup_command_terminal(
        self,
        tenant_id: str,
        command_id: UUID,
        *,
        worker_id: str,
        error: str,
    ) -> PlatformCommand:
        """Fail one claimed warmup command and its Run without retrying."""
        with self._transaction(tenant_id) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                          FROM gda_control.
                               fail_gis_service_endpoint_warmup_command_terminal(
                                   :tenant_id, :command_id, :worker_id, :error
                               )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "command_id": command_id,
                        "worker_id": worker_id,
                        "error": error,
                    },
                )
                .mappings()
                .one()
            )
            return self._command_from_row(row)

    def defer_dispatch_to_reconcile(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
    ) -> PlatformCommand:
        with self._transaction(command.tenant_id) as connection:
            stored = self._load_command(connection, command.tenant_id, command.command_id)
            if stored != command:
                raise GatewayConflictError("platform command claim changed")
            if (
                command.command_type != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH
                or command.status != PlatformCommandStatus.IN_FLIGHT
                or command.claimed_by != worker_id
            ):
                raise GatewayValidationError("only the dispatch claim owner can defer to reconcile")
            run = self._load_run(connection, command.tenant_id, command.run_id)
            execution_plan = self._load_artifact(
                connection,
                command.tenant_id,
                command.execution_plan_artifact_id,
            )
            if run is None or execution_plan is None:
                raise GatewayNotFoundError("dispatch command binding was not found")
            reconcile = self._reconcile_command(
                run,
                execution_plan,
                source_id=command.command_id,
                trigger_observation_id=None,
                created_at=datetime.now(UTC),
                reason="dispatch_outcome_unknown",
            )
            result = self._put_command(connection, reconcile)
            connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.complete_platform_command(
                        :tenant_id, :command_id, :worker_id
                    )
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "command_id": command.command_id,
                    "worker_id": worker_id,
                },
            ).mappings().one()
            return result.value

    def complete_cancel_and_enqueue_reconcile(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
    ) -> PlatformCommand:
        """Atomically acknowledge STOP delivery and schedule provider convergence."""
        with self._transaction(command.tenant_id) as connection:
            stored = self._load_command(connection, command.tenant_id, command.command_id)
            if stored != command:
                raise GatewayConflictError("platform command claim changed")
            if (
                command.command_type != PlatformCommandType.DOLPHINSCHEDULER_CANCEL
                or command.status != PlatformCommandStatus.IN_FLIGHT
                or command.claimed_by != worker_id
            ):
                raise GatewayValidationError(
                    "only the cancel claim owner can enqueue reconciliation"
                )
            run = self._load_run(connection, command.tenant_id, command.run_id)
            execution_plan = self._load_artifact(
                connection,
                command.tenant_id,
                command.execution_plan_artifact_id,
            )
            if run is None or execution_plan is None:
                raise GatewayNotFoundError("cancel command binding was not found")
            reconcile = self._reconcile_command(
                run,
                execution_plan,
                source_id=command.command_id,
                trigger_observation_id=None,
                created_at=datetime.now(UTC),
                reason="provider_cancel_requested",
            )
            result = self._put_command(connection, reconcile)
            connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.complete_platform_command(
                        :tenant_id, :command_id, :worker_id
                    )
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "command_id": command.command_id,
                    "worker_id": worker_id,
                },
            ).mappings().one()
            return result.value

    @staticmethod
    def _load_artifact(connection, tenant_id: str, artifact_id: UUID) -> Artifact | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, artifact_id, artifact_key, artifact_role,
                       storage_uri, media_type, content_sha256, size_bytes,
                       run_id, resource_version_id, manifest, created_by, created_at
                FROM gda_control.artifact
                WHERE tenant_id = :tenant_id AND artifact_id = :artifact_id
                """
                ),
                {"tenant_id": tenant_id, "artifact_id": artifact_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["manifest"] = _as_json(value["manifest"])
        return Artifact.model_validate(value)

    def get_artifact(self, tenant_id: str, artifact_id: UUID) -> Artifact:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            artifact = self._load_artifact(connection, tenant, artifact_id)
            if artifact is None:
                raise GatewayNotFoundError("Artifact was not found")
            return artifact

    def _put_artifact(self, connection, artifact: Artifact) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.artifact (
                    tenant_id, artifact_id, artifact_key, artifact_role,
                    storage_uri, media_type, content_sha256, size_bytes,
                    run_id, resource_version_id, manifest, created_by, created_at
                ) VALUES (
                    :tenant_id, :artifact_id, :artifact_key, :artifact_role,
                    :storage_uri, :media_type, :content_sha256, :size_bytes,
                    :run_id, :resource_version_id,
                    CAST(:manifest AS jsonb), :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING artifact_id
                """
            ),
            {
                **artifact.model_dump(mode="python", exclude={"manifest"}),
                "artifact_role": artifact.artifact_role.value,
                "manifest": _json(artifact.manifest),
            },
        ).first()
        stored = self._load_artifact(connection, artifact.tenant_id, artifact.artifact_id)
        if stored is None or stored != artifact:
            raise GatewayConflictError("Artifact identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    def record_artifact(self, artifact: Artifact) -> GatewayWriteResult:
        with self._transaction(artifact.tenant_id) as connection:
            return self._put_artifact(connection, artifact)

    def record_postgresql_cdc_recovery_observation(
        self,
        artifact: Artifact,
        *,
        recovery_plan_sha256: str,
        observation: Any,
        decision: Any,
    ) -> PostgresqlCdcRecoveryWriteResult:
        """Atomically project controller evidence into Artifact and its ledger."""

        observation_document = observation.model_dump(mode="json", by_alias=True)
        decision_document = decision.model_dump(mode="json", by_alias=True)
        with self._transaction(artifact.tenant_id) as connection:
            artifact_write = self._put_artifact(connection, artifact)
            row = connection.execute(
                text(
                    """
                    SELECT result_artifact_id, result_created
                    FROM gda_control.record_postgresql_cdc_recovery_observation(
                        :tenant_id, :artifact_id, :recovery_plan_sha256,
                        CAST(:observation AS jsonb), CAST(:decision AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": artifact.tenant_id,
                    "artifact_id": artifact.artifact_id,
                    "recovery_plan_sha256": recovery_plan_sha256,
                    "observation": _json(observation_document),
                    "decision": _json(decision_document),
                },
            ).mappings().one()
            if row["result_artifact_id"] != artifact.artifact_id:
                raise GatewayConflictError(
                    "recovery controller ledger returned a different Artifact"
                )
            stored = self._load_artifact(
                connection, artifact.tenant_id, artifact.artifact_id
            )
            if stored is None:
                raise GatewayNotFoundError(
                    "recovery controller Artifact was not persisted"
                )
            return PostgresqlCdcRecoveryWriteResult(
                artifact=stored,
                artifact_created=artifact_write.created,
                ledger_created=bool(row["result_created"]),
            )

    def get_postgresql_cdc_recovery_observation(
        self, tenant_id: str, artifact_id: UUID
    ) -> PostgresqlCdcRecoveryObservationRecord:
        """Load one tenant-scoped durable controller observation projection."""

        from .postgresql_cdc_recovery_controller import (
            PostgresqlCdcRecoveryObservationRecord,
        )

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, artifact_id, sync_definition_version_id,
                           run_id, sync_definition_urn, checkpoint_state_version,
                           checkpoint_cursor, observation_sha256, decision_sha256,
                           disposition, reason_codes, recovery_plan_sha256,
                           observation, decision, observed_at, decided_at,
                           recorded_by, recorded_at
                    FROM gda_control.postgresql_cdc_recovery_observation
                    WHERE tenant_id = :tenant_id AND artifact_id = :artifact_id
                    """
                ),
                {"tenant_id": tenant, "artifact_id": artifact_id},
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError(
                    "PostgreSQL CDC recovery observation was not found"
                )
            value = dict(row)
            value["checkpoint_cursor"] = _as_json(value["checkpoint_cursor"])
            value["observation"] = _as_json(value["observation"])
            value["decision"] = _as_json(value["decision"])
            return PostgresqlCdcRecoveryObservationRecord.model_validate(value)

    @staticmethod
    def _load_lineage(connection, tenant_id: str, lineage_event_id: UUID) -> LineageEvent | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, lineage_event_id, event_type,
                       source_resource_version_id, target_resource_version_id,
                       producer, event_sha256, run_id, definition_version_id,
                       artifact_id, facets, occurred_at
                FROM gda_control.lineage_event
                WHERE tenant_id = :tenant_id
                  AND lineage_event_id = :lineage_event_id
                """
                ),
                {"tenant_id": tenant_id, "lineage_event_id": lineage_event_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["facets"] = _as_json(value["facets"])
        return LineageEvent.model_validate(value)

    def _put_lineage(self, connection, event: LineageEvent) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.lineage_event (
                    tenant_id, lineage_event_id, event_type,
                    source_resource_version_id, target_resource_version_id,
                    producer, event_sha256, run_id, definition_version_id,
                    artifact_id, facets, occurred_at
                ) VALUES (
                    :tenant_id, :lineage_event_id, :event_type,
                    :source_resource_version_id, :target_resource_version_id,
                    :producer, :event_sha256, :run_id, :definition_version_id,
                    :artifact_id, CAST(:facets AS jsonb), :occurred_at
                )
                ON CONFLICT DO NOTHING
                RETURNING lineage_event_id
                """
            ),
            {
                **event.model_dump(mode="python", exclude={"facets"}),
                "event_type": event.event_type.value,
                "facets": _json(event.facets),
            },
        ).first()
        stored = self._load_lineage(connection, event.tenant_id, event.lineage_event_id)
        if stored is None or stored != event:
            raise GatewayConflictError("LineageEvent identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    def record_lineage(self, event: LineageEvent) -> GatewayWriteResult:
        with self._transaction(event.tenant_id) as connection:
            return self._put_lineage(connection, event)

    @classmethod
    def _validate_lineage_batch_bindings(
        cls,
        connection,
        events: tuple[LineageEvent, ...],
    ) -> None:
        first = events[0]
        required = (first.run_id, first.definition_version_id, first.artifact_id)
        if any(value is None for value in required):
            raise GatewayValidationError(
                "batched lineage requires run, definition, and artifact bindings"
            )
        if any(
            event.tenant_id != first.tenant_id
            or event.run_id != first.run_id
            or event.definition_version_id != first.definition_version_id
            or event.artifact_id != first.artifact_id
            or event.producer != first.producer
            for event in events
        ):
            raise GatewayValidationError(
                "batched lineage must share tenant, run, definition, artifact, and producer"
            )
        event_ids = [event.lineage_event_id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise GatewayValidationError("batched lineage event identities must be unique")

        run = cls._load_run(connection, first.tenant_id, first.run_id)
        artifact = cls._load_artifact(connection, first.tenant_id, first.artifact_id)
        if run is None:
            raise GatewayNotFoundError("OpenLineage PlatformRun was not found")
        if artifact is None:
            raise GatewayNotFoundError("OpenLineage Artifact was not found")
        if run.definition_version_id != first.definition_version_id:
            raise GatewayValidationError(
                "OpenLineage definition does not match the immutable PlatformRun"
            )
        subject = run.subject_context
        run_producer = f"{subject.subject_type.value}:{subject.subject_id}"
        if subject.subject_type != SubjectType.WORKLOAD or run_producer != first.producer:
            raise GatewayForbiddenError(
                "authenticated producer does not own the OpenLineage PlatformRun"
            )
        if artifact.run_id != run.run_id:
            raise GatewayValidationError(
                "OpenLineage artifact does not belong to the PlatformRun"
            )

        source_ids = {event.source_resource_version_id for event in events}
        target_ids = {event.target_resource_version_id for event in events}
        bound_input_ids = {
            binding.resource_version_id for binding in run.input_bindings
        }
        if not source_ids.issubset(bound_input_ids):
            raise GatewayValidationError(
                "OpenLineage inputs are not admitted PlatformRun bindings"
            )
        if (
            artifact.resource_version_id is not None
            and artifact.resource_version_id not in target_ids
        ):
            raise GatewayValidationError(
                "OpenLineage artifact resource version is not an event output"
            )
        for resource_version_id in source_ids | target_ids:
            if (
                cls._load_resource_version(
                    connection,
                    first.tenant_id,
                    resource_version_id,
                )
                is None
            ):
                raise GatewayNotFoundError(
                    "OpenLineage ResourceVersion was not found"
                )

    def record_lineage_batch(
        self,
        events: tuple[LineageEvent, ...],
    ) -> tuple[GatewayWriteResult, ...]:
        """Atomically validate and record one correlated lineage event batch."""
        if not events:
            raise GatewayValidationError("lineage batch must not be empty")
        if len(events) > MAX_GENERATED_EDGES:
            raise GatewayValidationError(
                f"lineage batch exceeds {MAX_GENERATED_EDGES} events"
            )
        with self._transaction(events[0].tenant_id) as connection:
            self._validate_lineage_batch_bindings(connection, events)
            return tuple(self._put_lineage(connection, event) for event in events)

    @staticmethod
    def _metadata_change_from_row(row) -> MetadataChange:
        return MetadataChange.model_validate(dict(row))

    @classmethod
    def _metadata_projection_envelope(
        cls,
        connection,
        change: MetadataChange,
    ) -> MetadataLineageProjectionEnvelope:
        event = cls._load_lineage(
            connection,
            change.tenant_id,
            change.aggregate_id,
        )
        if event is None:
            raise GatewayNotFoundError("Metadata change LineageEvent was not found")
        source = cls._load_resource_version(
            connection,
            change.tenant_id,
            event.source_resource_version_id,
        )
        target = cls._load_resource_version(
            connection,
            change.tenant_id,
            event.target_resource_version_id,
        )
        if source is None or target is None:
            raise GatewayNotFoundError(
                "Metadata change ResourceVersion binding was not found"
            )
        return MetadataLineageProjectionEnvelope(
            change=change,
            lineage_event=event,
            source_resource_version=source,
            target_resource_version=target,
            source_binding=cls._load_openmetadata_binding(
                connection,
                change.tenant_id,
                source.resource_urn,
            ),
            target_binding=cls._load_openmetadata_binding(
                connection,
                change.tenant_id,
                target.resource_urn,
            ),
        )

    def claim_metadata_changes(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[MetadataLineageProjectionEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_metadata_changes(
                            :tenant_id, :worker_id, :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._metadata_projection_envelope(
                    connection,
                    self._metadata_change_from_row(row),
                )
                for row in rows
            )

    def complete_metadata_change(
        self,
        tenant_id: str,
        change_id: UUID,
        *,
        worker_id: str,
    ) -> MetadataChange:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.complete_metadata_change(
                            :tenant_id, :change_id, :worker_id
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "change_id": change_id,
                        "worker_id": worker_id,
                    },
                )
                .mappings()
                .one()
            )
            return self._metadata_change_from_row(row)

    def fail_metadata_change(
        self,
        tenant_id: str,
        change_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> MetadataChange:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.fail_metadata_change(
                            :tenant_id, :change_id, :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "change_id": change_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._metadata_change_from_row(row)

    @staticmethod
    def _master_metadata_change_from_row(row) -> MasterMetadataProjectionChange:
        return MasterMetadataProjectionChange.model_validate(dict(row))

    @staticmethod
    def _load_master_entity_version(
        connection,
        tenant_id: str,
        entity_version_ref: str,
    ) -> MasterEntityVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, entity_ref, entity_version_ref,
                           entity_version AS version, domain, business_key,
                           canonical_name, parent_entity_ref, attributes,
                           source_record_refs, match_candidate_refs,
                           valid_from, valid_to, owner_subject, created_by,
                           creation_reason, created_at, entity_fingerprint
                    FROM gda_control.master_entity_version
                    WHERE tenant_id = :tenant_id
                      AND entity_version_ref = :entity_version_ref
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "entity_version_ref": entity_version_ref,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["attributes"] = _as_json(value["attributes"])
        value["source_record_refs"] = tuple(_as_json(value["source_record_refs"]))
        value["match_candidate_refs"] = tuple(
            _as_json(value["match_candidate_refs"])
        )
        return MasterEntityVersion.model_validate(value)

    @classmethod
    def _master_metadata_projection_envelope(
        cls,
        connection,
        change: MasterMetadataProjectionChange,
    ) -> MasterMetadataProjectionEnvelope:
        resource_version = cls._load_resource_version(
            connection,
            change.tenant_id,
            change.resource_version_id,
        )
        if resource_version is None:
            raise GatewayNotFoundError(
                "Master metadata projection ResourceVersion was not found"
            )
        entity_version_ref = resource_version.authority_version_ref.get(
            "entity_version_ref"
        )
        if not isinstance(entity_version_ref, str):
            raise GatewayValidationError(
                "Master ResourceVersion has no entity version authority"
            )
        master_version = cls._load_master_entity_version(
            connection,
            change.tenant_id,
            entity_version_ref,
        )
        if master_version is None:
            raise GatewayNotFoundError(
                "Master metadata projection entity version was not found"
            )
        return MasterMetadataProjectionEnvelope(
            change=change,
            master_version=master_version,
            resource_version=resource_version,
            openmetadata_binding=cls._load_openmetadata_binding(
                connection,
                change.tenant_id,
                change.entity_ref,
            ),
        )

    def claim_master_metadata_projections(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[MasterMetadataProjectionEnvelope, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_master_metadata_projections(
                            :tenant_id, :worker_id, :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._master_metadata_projection_envelope(
                    connection,
                    self._master_metadata_change_from_row(row),
                )
                for row in rows
            )

    def complete_master_metadata_projection(
        self,
        tenant_id: str,
        projection_change_id: UUID,
        *,
        worker_id: str,
    ) -> MasterMetadataProjectionChange:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM gda_control.complete_master_metadata_projection(
                            :tenant_id, :projection_change_id, :worker_id
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "projection_change_id": projection_change_id,
                        "worker_id": worker_id,
                    },
                )
                .mappings()
                .one()
            )
            return self._master_metadata_change_from_row(row)

    def fail_master_metadata_projection(
        self,
        tenant_id: str,
        projection_change_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> MasterMetadataProjectionChange:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM gda_control.fail_master_metadata_projection(
                            :tenant_id, :projection_change_id, :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "projection_change_id": projection_change_id,
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._master_metadata_change_from_row(row)

    @staticmethod
    def _lineage_version_from_row(row: dict[str, Any], prefix: str) -> ResourceVersion:
        value = {
            "tenant_id": row[f"{prefix}_tenant_id"],
            "resource_urn": row[f"{prefix}_resource_urn"],
            "resource_version_id": row[f"{prefix}_resource_version_id"],
            "version_key": row[f"{prefix}_version_key"],
            "predecessor_version_id": row[f"{prefix}_predecessor_version_id"],
            "content_sha256": row[f"{prefix}_content_sha256"],
            "authority_version_ref": _as_json(row[f"{prefix}_authority_version_ref"]),
            "created_by": row[f"{prefix}_created_by"],
            "created_at": row[f"{prefix}_created_at"],
        }
        return ResourceVersion.model_validate(value)

    @staticmethod
    def _lineage_event_from_row(row: dict[str, Any]) -> LineageEvent:
        value = {
            key: row[key]
            for key in (
                "tenant_id",
                "lineage_event_id",
                "event_type",
                "source_resource_version_id",
                "target_resource_version_id",
                "producer",
                "event_sha256",
                "run_id",
                "definition_version_id",
                "artifact_id",
                "occurred_at",
            )
        }
        value["facets"] = _as_json(row["facets"])
        return LineageEvent.model_validate(value)

    def _query_lineage_in_transaction(
        self,
        connection,
        tenant: str,
        root_resource_version_id: UUID,
        query: LineageQuerySpec,
    ) -> LineageGraph:
        """Build a lineage projection inside the caller's read transaction."""

        with nullcontext(connection) as connection:
            root = self._load_resource_version(connection, tenant, root_resource_version_id)
            if root is None:
                raise GatewayNotFoundError("ResourceVersion was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        WITH RECURSIVE adjacency(
                            lineage_event_id, from_version_id, to_version_id
                        ) AS (
                            SELECT lineage_event_id,
                                   source_resource_version_id,
                                   target_resource_version_id
                              FROM gda_control.lineage_event
                             WHERE tenant_id = :tenant_id
                               AND :direction IN ('downstream', 'both')
                            UNION ALL
                            SELECT lineage_event_id,
                                   target_resource_version_id,
                                   source_resource_version_id
                              FROM gda_control.lineage_event
                             WHERE tenant_id = :tenant_id
                               AND :direction IN ('upstream', 'both')
                        ),
                        walk(resource_version_id, depth) AS (
                            SELECT CAST(:root_resource_version_id AS uuid), 0
                            UNION
                            SELECT adjacency.to_version_id, walk.depth + 1
                              FROM walk
                              JOIN adjacency
                                ON adjacency.from_version_id = walk.resource_version_id
                             WHERE walk.depth < :search_depth
                        ),
                        traversed AS (
                            SELECT DISTINCT ON (adjacency.lineage_event_id)
                                   adjacency.lineage_event_id,
                                   adjacency.from_version_id,
                                   adjacency.to_version_id,
                                   walk.depth + 1 AS depth
                              FROM walk
                              JOIN adjacency
                                ON adjacency.from_version_id = walk.resource_version_id
                             WHERE walk.depth < :search_depth
                             ORDER BY adjacency.lineage_event_id,
                                      walk.depth + 1,
                                      adjacency.from_version_id,
                                      adjacency.to_version_id
                        )
                        SELECT event.tenant_id, event.lineage_event_id, event.event_type,
                               event.source_resource_version_id,
                               event.target_resource_version_id, event.producer,
                               event.event_sha256, event.run_id,
                               event.definition_version_id, event.artifact_id,
                               event.facets, event.occurred_at,
                               traversed.from_version_id,
                               traversed.to_version_id,
                               traversed.depth,
                               source.tenant_id AS source_tenant_id,
                               source.resource_urn AS source_resource_urn,
                               source.resource_version_id AS source_resource_version_id_value,
                               source.version_key AS source_version_key,
                               source.predecessor_version_id AS source_predecessor_version_id,
                               source.content_sha256 AS source_content_sha256,
                               source.authority_version_ref AS source_authority_version_ref,
                               source.created_by AS source_created_by,
                               source.created_at AS source_created_at,
                               target.tenant_id AS target_tenant_id,
                               target.resource_urn AS target_resource_urn,
                               target.resource_version_id AS target_resource_version_id_value,
                               target.version_key AS target_version_key,
                               target.predecessor_version_id AS target_predecessor_version_id,
                               target.content_sha256 AS target_content_sha256,
                               target.authority_version_ref AS target_authority_version_ref,
                               target.created_by AS target_created_by,
                               target.created_at AS target_created_at
                          FROM traversed
                          JOIN gda_control.lineage_event AS event
                            ON event.tenant_id = :tenant_id
                           AND event.lineage_event_id = traversed.lineage_event_id
                          JOIN gda_control.resource_version AS source
                            ON source.tenant_id = event.tenant_id
                           AND source.resource_version_id = event.source_resource_version_id
                          JOIN gda_control.resource_version AS target
                            ON target.tenant_id = event.tenant_id
                           AND target.resource_version_id = event.target_resource_version_id
                         ORDER BY traversed.depth, event.occurred_at, event.lineage_event_id
                         LIMIT :row_limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "root_resource_version_id": root_resource_version_id,
                        "direction": query.direction.value,
                        "search_depth": query.max_depth + 1,
                        "row_limit": query.max_edges + 1,
                    },
                )
                .mappings()
                .all()
            )

        row_values = [dict(row) for row in rows]
        within_depth = [row for row in row_values if int(row["depth"]) <= query.max_depth]
        edge_limited = len(within_depth) > query.max_edges
        depth_limited = any(int(row["depth"]) > query.max_depth for row in row_values)
        selected = within_depth[: query.max_edges]

        versions: dict[UUID, tuple[ResourceVersion, int]] = {
            root.resource_version_id: (root, 0)
        }
        edges: list[LineageGraphEdge] = []
        for row in selected:
            depth = int(row["depth"])
            source = self._lineage_version_from_row(row, "source")
            target = self._lineage_version_from_row(row, "target")
            from_id = UUID(str(row["from_version_id"]))
            to_id = UUID(str(row["to_version_id"]))
            for version, node_depth in (
                (source, depth - 1 if source.resource_version_id == from_id else depth),
                (target, depth - 1 if target.resource_version_id == from_id else depth),
            ):
                previous = versions.get(version.resource_version_id)
                if previous is None or node_depth < previous[1]:
                    versions[version.resource_version_id] = (version, node_depth)
            edges.append(
                LineageGraphEdge(
                    event=self._lineage_event_from_row(row),
                    depth=depth,
                    traversal_from_resource_version_id=from_id,
                    traversal_to_resource_version_id=to_id,
                )
            )

        reasons: list[LineageTruncationReason] = []
        if edge_limited:
            reasons.append(LineageTruncationReason.EDGE_LIMIT)
        if depth_limited:
            reasons.append(LineageTruncationReason.DEPTH_LIMIT)
        graph = LineageGraph(
            tenant_id=tenant,
            root_resource_version_id=root_resource_version_id,
            direction=query.direction,
            requested_max_depth=query.max_depth,
            requested_max_edges=query.max_edges,
            reached_depth=max((edge.depth for edge in edges), default=0),
            complete=not reasons,
            truncation_reasons=tuple(reasons),
            nodes=tuple(
                LineageGraphNode(
                    resource_version=version,
                    min_depth=depth,
                    is_root=version_id == root_resource_version_id,
                )
                for version_id, (version, depth) in sorted(
                    versions.items(), key=lambda item: (item[1][1], str(item[0]))
                )
            ),
            edges=tuple(edges),
            node_count=len(versions),
            edge_count=len(edges),
        )
        if query.require_complete and not graph.complete:
            reasons_text = ", ".join(reason.value for reason in graph.truncation_reasons)
            raise GatewayTraversalLimitError(
                f"lineage traversal is incomplete because of: {reasons_text}"
            )
        return graph

    def query_lineage(
        self,
        tenant_id: str,
        root_resource_version_id: UUID,
        *,
        direction: LineageDirection | str = LineageDirection.BOTH,
        max_depth: int = 6,
        max_edges: int = 500,
        require_complete: bool = False,
    ) -> LineageGraph:
        """Traverse immutable version lineage without mutating catalog projections."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        query = LineageQuerySpec(
            direction=direction,
            max_depth=max_depth,
            max_edges=max_edges,
            require_complete=require_complete,
        )
        with self._transaction(tenant) as connection:
            return self._query_lineage_in_transaction(
                connection,
                tenant,
                root_resource_version_id,
                query,
            )

    def assess_lineage_impact(
        self,
        tenant_id: str,
        root_resource_version_id: UUID,
        *,
        change_type: ImpactChangeType | str,
        max_depth: int = 6,
        max_edges: int = 500,
    ) -> LineageImpactAssessment:
        """Assess downstream ledger impact from one immutable resource version."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        change = ImpactChangeType(change_type)
        query = LineageQuerySpec(
            direction=LineageDirection.DOWNSTREAM,
            max_depth=max_depth,
            max_edges=max_edges,
            require_complete=True,
        )
        with self._transaction(tenant) as connection:
            lineage = self._query_lineage_in_transaction(
                connection,
                tenant,
                root_resource_version_id,
                query,
            )
            version_depths = {
                node.resource_version.resource_version_id: node.min_depth
                for node in lineage.nodes
            }
            version_ids = list(version_depths)
            product_rows = (
                connection.execute(
                    text(
                        """
                        SELECT product.tenant_id, product.product_urn,
                               product.product_slug, product.title, product.domain,
                               product.owner_ref, product.governance_ref,
                               version.data_product_version_id, version.version_key,
                               version.source_resource_version_id,
                               version.output_resource_version_id,
                               version.quality_verdict, version.manifest_sha256,
                               version.published_at
                          FROM gda_control.data_product AS product
                          JOIN gda_control.data_product_version AS version
                            ON version.tenant_id = product.tenant_id
                           AND version.product_urn = product.product_urn
                           AND version.data_product_version_id = product.current_version_id
                         WHERE product.tenant_id = :tenant_id
                           AND (
                               version.source_resource_version_id = ANY(
                                   CAST(:version_ids AS uuid[])
                               )
                               OR version.output_resource_version_id = ANY(
                                   CAST(:version_ids AS uuid[])
                               )
                           )
                         ORDER BY product.product_urn,
                                  version.data_product_version_id
                        """
                    ),
                    {"tenant_id": tenant, "version_ids": version_ids},
                )
                .mappings()
                .all()
            )
            quality_rows = (
                connection.execute(
                    text(
                        """
                        SELECT DISTINCT ON (
                                   quality.resource_version_id,
                                   quality.rule_version_ref
                               )
                               quality.tenant_id, quality.quality_result_id,
                               quality.run_id, quality.resource_version_id,
                               quality.rule_version_ref, quality.verdict,
                               quality.metrics, quality.evidence_artifact_id,
                               quality.result_sha256, quality.evaluated_by,
                               quality.evaluated_at
                          FROM gda_control.quality_result AS quality
                         WHERE quality.tenant_id = :tenant_id
                           AND quality.resource_version_id = ANY(
                               CAST(:version_ids AS uuid[])
                           )
                         ORDER BY quality.resource_version_id,
                                  quality.rule_version_ref,
                                  quality.evaluated_at DESC,
                                  quality.quality_result_id DESC
                        """
                    ),
                    {"tenant_id": tenant, "version_ids": version_ids},
                )
                .mappings()
                .all()
            )

        impacted_products: list[ImpactedDataProduct] = []
        version_id_set = set(version_ids)
        for raw_row in product_rows:
            row = dict(raw_row)
            source_id = UUID(str(row["source_resource_version_id"]))
            output_id = UUID(str(row["output_resource_version_id"]))
            matched = tuple(
                sorted(
                    {source_id, output_id} & version_id_set,
                    key=str,
                )
            )
            impacted_products.append(
                ImpactedDataProduct(
                    **{
                        **row,
                        "governance_ref": _as_json(row["governance_ref"]),
                        "matched_resource_version_ids": matched,
                    }
                )
            )

        quality_signals: list[ImpactQualitySignal] = []
        for raw_row in quality_rows:
            row = dict(raw_row)
            row["metrics"] = _as_json(row["metrics"])
            result = QualityResult.model_validate(row)
            quality_signals.append(
                ImpactQualitySignal(
                    result=result,
                    resource_min_depth=version_depths[result.resource_version_id],
                )
            )

        reasons: list[ImpactReviewReason] = []
        if change in {
            ImpactChangeType.SCHEMA,
            ImpactChangeType.CRS,
            ImpactChangeType.GEOMETRY,
            ImpactChangeType.POLICY,
            ImpactChangeType.CLASSIFICATION,
            ImpactChangeType.DEPRECATION,
        }:
            reasons.append(ImpactReviewReason.CHANGE_TYPE_REQUIRES_REVIEW)
        if lineage.edges:
            reasons.append(ImpactReviewReason.DOWNSTREAM_LINEAGE_PRESENT)
        if impacted_products:
            reasons.append(ImpactReviewReason.CURRENT_DATA_PRODUCT_AFFECTED)
        if any(signal.result.verdict.value == "failed" for signal in quality_signals):
            reasons.append(ImpactReviewReason.FAILED_QUALITY_EVIDENCE)

        if ImpactReviewReason.FAILED_QUALITY_EVIDENCE in reasons:
            disposition = ImpactDisposition.QUALITY_ATTENTION_REQUIRED
        elif reasons:
            disposition = ImpactDisposition.REVIEW_REQUIRED
        else:
            disposition = ImpactDisposition.NO_RECORDED_DOWNSTREAM_IMPACT

        root_version = next(
            node.resource_version for node in lineage.nodes if node.is_root
        )
        products_tuple = tuple(impacted_products)
        signals_tuple = tuple(quality_signals)
        reasons_tuple = tuple(reasons)
        assessment_sha256 = lineage_impact_fingerprint(
            tenant_id=tenant,
            root_resource_version=root_version,
            change_type=change,
            lineage=lineage,
            impacted_data_products=products_tuple,
            quality_signals=signals_tuple,
            disposition=disposition,
            review_reasons=reasons_tuple,
        )
        return LineageImpactAssessment(
            tenant_id=tenant,
            root_resource_version=root_version,
            change_type=change,
            lineage=lineage,
            impacted_data_products=products_tuple,
            quality_signals=signals_tuple,
            disposition=disposition,
            review_reasons=reasons_tuple,
            impacted_resource_version_count=lineage.node_count,
            impacted_data_product_count=len(products_tuple),
            quality_signal_count=len(signals_tuple),
            assessment_sha256=assessment_sha256,
        )

    @staticmethod
    def _gis_service_definition_from_row(row) -> GISServiceDefinitionVersion:
        value = dict(row)
        value["service_contract"] = _as_json(value["service_contract"])
        return GISServiceDefinitionVersion.model_validate(value)

    @classmethod
    def _load_gis_service_definition_version(
        cls,
        connection,
        tenant_id: str,
        service_definition_version_id: UUID,
    ) -> GISServiceDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_definition_version_id,
                           service_urn, version_key, predecessor_version_id,
                           platform_definition_version_id, source_product_urn,
                           source_data_product_version_id,
                           source_manifest_sha256, service_type,
                           service_contract, definition_sha256,
                           created_by, created_at
                      FROM gda_control.gis_service_definition_version
                     WHERE tenant_id = :tenant_id
                       AND service_definition_version_id =
                            :service_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_definition_version_id": service_definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._gis_service_definition_from_row(row) if row is not None else None

    def register_gis_service_definition_version(
        self,
        definition: GISServiceDefinitionVersion,
    ) -> GatewayWriteResult:
        with self._transaction(definition.tenant_id) as connection:
            existing = self._load_gis_service_definition_version(
                connection,
                definition.tenant_id,
                definition.service_definition_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_gis_service_definition_version(
                        :tenant_id, :service_definition_version_id,
                        :service_urn, :version_key, :predecessor_version_id,
                        :platform_definition_version_id, :source_product_urn,
                        :source_data_product_version_id,
                        :source_manifest_sha256, :service_type,
                        CAST(:service_contract AS jsonb), :definition_sha256,
                        :created_by, :created_at
                    )
                    """
                ),
                {
                    **definition.model_dump(
                        mode="json",
                        exclude={"service_contract", "service_type"},
                    ),
                    "service_type": definition.service_type.value,
                    "service_contract": _json(definition.service_contract),
                },
            ).scalar_one()
            stored = self._load_gis_service_definition_version(
                connection,
                definition.tenant_id,
                definition.service_definition_version_id,
            )
            if stored is None or stored != definition:
                raise GatewayConflictError(
                    "GISServiceDefinitionVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_gis_service_definition_version(
        self,
        tenant_id: str,
        service_definition_version_id: UUID,
    ) -> GISServiceDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_gis_service_definition_version(
                connection, tenant, service_definition_version_id
            )
            if stored is None:
                raise GatewayNotFoundError("GISServiceDefinitionVersion was not found")
            return stored

    @staticmethod
    def _layer_definition_from_row(row) -> LayerDefinitionVersion:
        value = dict(row)
        value["schema_contract"] = _as_json(value["schema_contract"])
        return LayerDefinitionVersion.model_validate(value)

    @classmethod
    def _load_layer_definition_version(
        cls,
        connection,
        tenant_id: str,
        layer_definition_version_id: UUID,
    ) -> LayerDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, layer_definition_version_id,
                           service_definition_version_id, layer_key,
                           version_key, predecessor_version_id,
                           source_output_resource_version_id, geometry_type,
                           geometry_column, schema_contract, crs_uri,
                           spatial_extent, definition_sha256,
                           created_by, created_at
                      FROM gda_control.layer_definition_version
                     WHERE tenant_id = :tenant_id
                       AND layer_definition_version_id =
                            :layer_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "layer_definition_version_id": layer_definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._layer_definition_from_row(row) if row is not None else None

    def register_layer_definition_version(
        self,
        definition: LayerDefinitionVersion,
    ) -> GatewayWriteResult:
        with self._transaction(definition.tenant_id) as connection:
            existing = self._load_layer_definition_version(
                connection,
                definition.tenant_id,
                definition.layer_definition_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_layer_definition_version(
                        :tenant_id, :layer_definition_version_id,
                        :service_definition_version_id, :layer_key,
                        :version_key, :predecessor_version_id,
                        :source_output_resource_version_id, :geometry_type,
                        :geometry_column, CAST(:schema_contract AS jsonb),
                        :crs_uri,
                        CAST(:spatial_extent AS double precision[]),
                        :definition_sha256, :created_by, :created_at
                    )
                    """
                ),
                {
                    **definition.model_dump(
                        mode="json",
                        exclude={
                            "geometry_type",
                            "schema_contract",
                            "spatial_extent",
                        },
                    ),
                    "geometry_type": definition.geometry_type.value,
                    "schema_contract": _json(definition.schema_contract),
                    "spatial_extent": list(definition.spatial_extent),
                },
            ).scalar_one()
            stored = self._load_layer_definition_version(
                connection,
                definition.tenant_id,
                definition.layer_definition_version_id,
            )
            if stored is None or stored != definition:
                raise GatewayConflictError(
                    "LayerDefinitionVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_layer_definition_version(
        self,
        tenant_id: str,
        layer_definition_version_id: UUID,
    ) -> LayerDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_layer_definition_version(
                connection, tenant, layer_definition_version_id
            )
            if stored is None:
                raise GatewayNotFoundError("LayerDefinitionVersion was not found")
            return stored

    @staticmethod
    def _style_definition_from_row(row) -> StyleDefinitionVersion:
        value = dict(row)
        value["style_document"] = _as_json(value["style_document"])
        return StyleDefinitionVersion.model_validate(value)

    @classmethod
    def _load_style_definition_version(
        cls,
        connection,
        tenant_id: str,
        style_definition_version_id: UUID,
    ) -> StyleDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, style_definition_version_id,
                           service_definition_version_id,
                           layer_definition_version_id, style_key,
                           version_key, predecessor_version_id, style_format,
                           style_document, style_sha256, created_by, created_at
                      FROM gda_control.style_definition_version
                     WHERE tenant_id = :tenant_id
                       AND style_definition_version_id =
                            :style_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "style_definition_version_id": style_definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._style_definition_from_row(row) if row is not None else None

    def register_style_definition_version(
        self,
        definition: StyleDefinitionVersion,
    ) -> GatewayWriteResult:
        with self._transaction(definition.tenant_id) as connection:
            existing = self._load_style_definition_version(
                connection,
                definition.tenant_id,
                definition.style_definition_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_style_definition_version(
                        :tenant_id, :style_definition_version_id,
                        :service_definition_version_id,
                        :layer_definition_version_id, :style_key,
                        :version_key, :predecessor_version_id, :style_format,
                        CAST(:style_document AS jsonb), :style_sha256,
                        :created_by, :created_at
                    )
                    """
                ),
                {
                    **definition.model_dump(
                        mode="json",
                        exclude={"style_format", "style_document"},
                    ),
                    "style_format": definition.style_format.value,
                    "style_document": _json(definition.style_document),
                },
            ).scalar_one()
            stored = self._load_style_definition_version(
                connection,
                definition.tenant_id,
                definition.style_definition_version_id,
            )
            if stored is None or stored != definition:
                raise GatewayConflictError(
                    "StyleDefinitionVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_style_definition_version(
        self,
        tenant_id: str,
        style_definition_version_id: UUID,
    ) -> StyleDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_style_definition_version(
                connection, tenant, style_definition_version_id
            )
            if stored is None:
                raise GatewayNotFoundError("StyleDefinitionVersion was not found")
            return stored

    @staticmethod
    def _tile_matrix_set_definition_from_row(
        row,
    ) -> TileMatrixSetDefinitionVersion:
        return TileMatrixSetDefinitionVersion.model_validate(dict(row))

    @classmethod
    def _load_tile_matrix_set_definition_version(
        cls,
        connection,
        tenant_id: str,
        tile_matrix_set_definition_version_id: UUID,
    ) -> TileMatrixSetDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, tile_matrix_set_definition_version_id,
                           service_definition_version_id,
                           layer_definition_version_id, tile_matrix_set_key,
                           version_key, predecessor_version_id, crs_uri,
                           tile_width, tile_height, min_zoom, max_zoom,
                           scale_denominators, spatial_extent,
                           definition_sha256, created_by, created_at
                      FROM gda_control.tile_matrix_set_definition_version
                     WHERE tenant_id = :tenant_id
                       AND tile_matrix_set_definition_version_id =
                            :tile_matrix_set_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "tile_matrix_set_definition_version_id": (
                        tile_matrix_set_definition_version_id
                    ),
                },
            )
            .mappings()
            .one_or_none()
        )
        return (
            cls._tile_matrix_set_definition_from_row(row)
            if row is not None
            else None
        )

    def register_tile_matrix_set_definition_version(
        self,
        definition: TileMatrixSetDefinitionVersion,
    ) -> GatewayWriteResult:
        with self._transaction(definition.tenant_id) as connection:
            existing = self._load_tile_matrix_set_definition_version(
                connection,
                definition.tenant_id,
                definition.tile_matrix_set_definition_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_tile_matrix_set_definition_version(
                        :tenant_id, :tile_matrix_set_definition_version_id,
                        :service_definition_version_id,
                        :layer_definition_version_id, :tile_matrix_set_key,
                        :version_key, :predecessor_version_id, :crs_uri,
                        :tile_width, :tile_height, :min_zoom, :max_zoom,
                        CAST(:scale_denominators AS double precision[]),
                        CAST(:spatial_extent AS double precision[]),
                        :definition_sha256, :created_by, :created_at
                    )
                    """
                ),
                {
                    **definition.model_dump(
                        mode="json",
                        exclude={"scale_denominators", "spatial_extent"},
                    ),
                    "scale_denominators": list(definition.scale_denominators),
                    "spatial_extent": list(definition.spatial_extent),
                },
            ).scalar_one()
            stored = self._load_tile_matrix_set_definition_version(
                connection,
                definition.tenant_id,
                definition.tile_matrix_set_definition_version_id,
            )
            if stored is None or stored != definition:
                raise GatewayConflictError(
                    "TileMatrixSetDefinitionVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_tile_matrix_set_definition_version(
        self,
        tenant_id: str,
        tile_matrix_set_definition_version_id: UUID,
    ) -> TileMatrixSetDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_tile_matrix_set_definition_version(
                connection, tenant, tile_matrix_set_definition_version_id
            )
            if stored is None:
                raise GatewayNotFoundError(
                    "TileMatrixSetDefinitionVersion was not found"
                )
            return stored

    @staticmethod
    def _cache_policy_version_from_row(row) -> CachePolicyVersion:
        return CachePolicyVersion.model_validate(dict(row))

    @classmethod
    def _load_cache_policy_version(
        cls,
        connection,
        tenant_id: str,
        cache_policy_version_id: UUID,
    ) -> CachePolicyVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, cache_policy_version_id,
                           service_definition_version_id, cache_policy_key,
                           version_key, predecessor_version_id,
                           cache_namespace, cache_max_age_seconds,
                           cache_key_dimensions, policy_sha256,
                           created_by, created_at
                      FROM gda_control.cache_policy_version
                     WHERE tenant_id = :tenant_id
                       AND cache_policy_version_id = :cache_policy_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "cache_policy_version_id": cache_policy_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._cache_policy_version_from_row(row) if row is not None else None

    def register_cache_policy_version(
        self,
        policy: CachePolicyVersion,
    ) -> GatewayWriteResult:
        with self._transaction(policy.tenant_id) as connection:
            existing = self._load_cache_policy_version(
                connection,
                policy.tenant_id,
                policy.cache_policy_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_cache_policy_version(
                        :tenant_id, :cache_policy_version_id,
                        :service_definition_version_id, :cache_policy_key,
                        :version_key, :predecessor_version_id,
                        :cache_namespace, :cache_max_age_seconds,
                        CAST(:cache_key_dimensions AS text[]),
                        :policy_sha256, :created_by, :created_at
                    )
                    """
                ),
                {
                    **policy.model_dump(
                        mode="json", exclude={"cache_key_dimensions"}
                    ),
                    "cache_key_dimensions": [
                        item.value for item in policy.cache_key_dimensions
                    ],
                },
            ).scalar_one()
            stored = self._load_cache_policy_version(
                connection,
                policy.tenant_id,
                policy.cache_policy_version_id,
            )
            if stored is None or stored != policy:
                raise GatewayConflictError(
                    "CachePolicyVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_cache_policy_version(
        self,
        tenant_id: str,
        cache_policy_version_id: UUID,
    ) -> CachePolicyVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_cache_policy_version(
                connection, tenant, cache_policy_version_id
            )
            if stored is None:
                raise GatewayNotFoundError("CachePolicyVersion was not found")
            return stored

    @staticmethod
    def _service_policy_binding_from_row(row) -> ServicePolicyBinding:
        return ServicePolicyBinding.model_validate(dict(row))

    @classmethod
    def _load_service_policy_binding(
        cls,
        connection,
        tenant_id: str,
        service_policy_binding_id: UUID,
    ) -> ServicePolicyBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_policy_binding_id,
                           service_definition_version_id,
                           service_release_binding_id, policy_key, version_key,
                           predecessor_version_id, action, enforcement_point,
                           allowed_roles, consumer_binding_required_roles,
                           required_consumer_operation, policy_sha256,
                           created_by, created_at
                      FROM gda_control.service_policy_binding
                     WHERE tenant_id = :tenant_id
                       AND service_policy_binding_id = :service_policy_binding_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_policy_binding_id": service_policy_binding_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_policy_binding_from_row(row) if row is not None else None

    @classmethod
    def _load_service_policy_binding_for_release(
        cls,
        connection,
        tenant_id: str,
        service_definition_version_id: UUID,
        service_release_binding_id: UUID,
    ) -> ServicePolicyBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_policy_binding_id,
                           service_definition_version_id,
                           service_release_binding_id, policy_key, version_key,
                           predecessor_version_id, action, enforcement_point,
                           allowed_roles, consumer_binding_required_roles,
                           required_consumer_operation, policy_sha256,
                           created_by, created_at
                      FROM gda_control.service_policy_binding
                     WHERE tenant_id = :tenant_id
                       AND service_definition_version_id =
                            :service_definition_version_id
                       AND service_release_binding_id =
                            :service_release_binding_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_definition_version_id": service_definition_version_id,
                    "service_release_binding_id": service_release_binding_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_policy_binding_from_row(row) if row is not None else None

    def register_service_policy_binding(
        self,
        policy: ServicePolicyBinding,
    ) -> GatewayWriteResult:
        with self._transaction(policy.tenant_id) as connection:
            existing = self._load_service_policy_binding(
                connection,
                policy.tenant_id,
                policy.service_policy_binding_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_service_policy_binding(
                        :tenant_id, :service_policy_binding_id,
                        :service_definition_version_id,
                        :service_release_binding_id, :policy_key, :version_key,
                        :predecessor_version_id, :action, :enforcement_point,
                        CAST(:allowed_roles AS text[]),
                        CAST(:consumer_binding_required_roles AS text[]),
                        :required_consumer_operation, :policy_sha256,
                        :created_by, :created_at
                    )
                    """
                ),
                {
                    **policy.model_dump(
                        mode="json",
                        exclude={
                            "allowed_roles",
                            "consumer_binding_required_roles",
                        },
                    ),
                    "allowed_roles": list(policy.allowed_roles),
                    "consumer_binding_required_roles": list(
                        policy.consumer_binding_required_roles
                    ),
                },
            ).scalar_one()
            stored = self._load_service_policy_binding(
                connection,
                policy.tenant_id,
                policy.service_policy_binding_id,
            )
            if stored is None or stored != policy:
                raise GatewayConflictError(
                    "ServicePolicyBinding identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_service_policy_binding(
        self,
        tenant_id: str,
        service_policy_binding_id: UUID,
    ) -> ServicePolicyBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_service_policy_binding(
                connection, tenant, service_policy_binding_id
            )
            if stored is None:
                raise GatewayNotFoundError("ServicePolicyBinding was not found")
            return stored

    @staticmethod
    def _mvt_serving_projection_from_row(row) -> MVTServingProjectionVersion:
        return MVTServingProjectionVersion.model_validate(dict(row))

    @classmethod
    def _load_mvt_serving_projection_version(
        cls,
        connection,
        tenant_id: str,
        mvt_serving_projection_version_id: UUID,
    ) -> MVTServingProjectionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, mvt_serving_projection_version_id,
                           service_definition_version_id,
                           layer_definition_version_id, projection_key,
                           version_key, predecessor_version_id,
                           source_output_resource_version_id, source_schema,
                           source_table, geometry_column, geometry_srid,
                           feature_id_column, property_allowlist,
                           allowed_spatial_extent, max_features_per_tile,
                           source_content_sha256, projection_sha256,
                           created_by, created_at
                      FROM gda_control.mvt_serving_projection_version
                     WHERE tenant_id = :tenant_id
                       AND mvt_serving_projection_version_id =
                            :mvt_serving_projection_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "mvt_serving_projection_version_id": (
                        mvt_serving_projection_version_id
                    ),
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._mvt_serving_projection_from_row(row) if row is not None else None

    def register_mvt_serving_projection_version(
        self,
        projection: MVTServingProjectionVersion,
    ) -> GatewayWriteResult:
        with self._transaction(projection.tenant_id) as connection:
            existing = self._load_mvt_serving_projection_version(
                connection,
                projection.tenant_id,
                projection.mvt_serving_projection_version_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_mvt_serving_projection_version(
                        :tenant_id, :mvt_serving_projection_version_id,
                        :service_definition_version_id,
                        :layer_definition_version_id, :projection_key,
                        :version_key, :predecessor_version_id,
                        :source_output_resource_version_id, :source_schema,
                        :source_table, :geometry_column, :geometry_srid,
                        :feature_id_column,
                        CAST(:property_allowlist AS text[]),
                        CAST(:allowed_spatial_extent AS double precision[]),
                        :max_features_per_tile, :source_content_sha256,
                        :projection_sha256, :created_by, :created_at
                    )
                    """
                ),
                {
                    **projection.model_dump(
                        mode="json",
                        exclude={"property_allowlist", "allowed_spatial_extent"},
                    ),
                    "property_allowlist": list(projection.property_allowlist),
                    "allowed_spatial_extent": list(projection.allowed_spatial_extent),
                },
            ).scalar_one()
            stored = self._load_mvt_serving_projection_version(
                connection,
                projection.tenant_id,
                projection.mvt_serving_projection_version_id,
            )
            if stored is None or stored != projection:
                raise GatewayConflictError(
                    "MVTServingProjectionVersion identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_mvt_serving_projection_version(
        self,
        tenant_id: str,
        mvt_serving_projection_version_id: UUID,
    ) -> MVTServingProjectionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_mvt_serving_projection_version(
                connection, tenant, mvt_serving_projection_version_id
            )
            if stored is None:
                raise GatewayNotFoundError(
                    "MVTServingProjectionVersion was not found"
                )
            return stored

    def record_mvt_serving_relation_attestation(
        self,
        projection: MVTServingProjectionVersion,
        *,
        attested_by: str,
        attested_at: datetime,
    ) -> GatewayWriteResult:
        """Record a live PostGIS catalog observation for a serving projection."""
        with self._transaction(projection.tenant_id) as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT 1
                      FROM gda_control.mvt_serving_relation_attestation
                     WHERE tenant_id = :tenant_id
                       AND mvt_serving_projection_version_id =
                            :mvt_serving_projection_version_id
                    """
                ),
                {
                    "tenant_id": str(projection.tenant_id),
                    "mvt_serving_projection_version_id": (
                        projection.mvt_serving_projection_version_id
                    ),
                },
            ).first()
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_mvt_serving_relation_attestation(
                        :tenant_id, :mvt_serving_projection_version_id,
                        :attested_by, :attested_at
                    )
                    """
                ),
                {
                    "tenant_id": str(projection.tenant_id),
                    "mvt_serving_projection_version_id": (
                        projection.mvt_serving_projection_version_id
                    ),
                    "attested_by": attested_by,
                    "attested_at": attested_at,
                },
            ).scalar_one()
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, mvt_serving_projection_version_id,
                           source_schema, source_table, relation_oid,
                           relation_kind, geometry_column, geometry_type,
                           geometry_srid, geometry_dimensions,
                           feature_id_column, feature_id_data_type,
                           property_columns, property_column_types,
                           relation_schema_sha256,
                           attested_by, attested_at
                      FROM gda_control.mvt_serving_relation_attestation
                     WHERE tenant_id = :tenant_id
                       AND mvt_serving_projection_version_id =
                            :mvt_serving_projection_version_id
                    """
                ),
                {
                    "tenant_id": str(projection.tenant_id),
                    "mvt_serving_projection_version_id": (
                        projection.mvt_serving_projection_version_id
                    ),
                },
            ).mappings().one()
            stored = MVTServingRelationAttestation.model_validate(dict(row))
            return GatewayWriteResult(stored, existing is None)

    @staticmethod
    def _service_release_binding_from_row(row) -> ServiceReleaseBinding:
        return ServiceReleaseBinding.model_validate(dict(row))

    @classmethod
    def _load_service_release_binding(
        cls,
        connection,
        tenant_id: str,
        service_release_binding_id: UUID,
    ) -> ServiceReleaseBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_release_binding_id,
                           service_definition_version_id,
                           layer_definition_version_id,
                           style_definition_version_id,
                           tile_matrix_set_definition_version_id,
                           cache_policy_version_id,
                           mvt_serving_projection_version_id,
                           release_key, binding_sha256, created_by, created_at
                      FROM gda_control.service_release_binding
                     WHERE tenant_id = :tenant_id
                       AND service_release_binding_id =
                            :service_release_binding_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_release_binding_id": service_release_binding_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_release_binding_from_row(row) if row is not None else None

    def register_service_release_binding(
        self,
        release: ServiceReleaseBinding,
    ) -> GatewayWriteResult:
        with self._transaction(release.tenant_id) as connection:
            existing = self._load_service_release_binding(
                connection,
                release.tenant_id,
                release.service_release_binding_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_service_release_binding(
                        :tenant_id, :service_release_binding_id,
                        :service_definition_version_id,
                        :layer_definition_version_id,
                        :style_definition_version_id,
                        :tile_matrix_set_definition_version_id,
                        :cache_policy_version_id,
                        :mvt_serving_projection_version_id,
                        :release_key, :binding_sha256, :created_by, :created_at
                    )
                    """
                ),
                release.model_dump(mode="json"),
            ).scalar_one()
            stored = self._load_service_release_binding(
                connection,
                release.tenant_id,
                release.service_release_binding_id,
            )
            if stored is None or stored != release:
                raise GatewayConflictError(
                    "ServiceReleaseBinding identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_service_release_binding(
        self,
        tenant_id: str,
        service_release_binding_id: UUID,
    ) -> ServiceReleaseBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_service_release_binding(
                connection, tenant, service_release_binding_id
            )
            if stored is None:
                raise GatewayNotFoundError("ServiceReleaseBinding was not found")
            return stored

    @staticmethod
    def _jqdltb_serving_release_from_row(row: Any) -> dict[str, Any]:
        return dict(row)

    def register_jqdltb_serving_release_binding(
        self,
        binding: JqdltbServingReleaseBinding,
    ) -> GatewayWriteResult:
        values = {
            "tenant_id": str(binding.tenant_id),
            "data_product_version_id": binding.data_product_version_id,
            "product_urn": binding.product_urn,
            "manifest_sha256": binding.manifest_sha256,
            "output_resource_version_id": binding.output_resource_version_id,
            "service_urn": binding.service.service_urn,
            "service_definition_version_id": binding.service.service_definition_version_id,
            "layer_definition_version_id": binding.layer.layer_definition_version_id,
            "mvt_serving_projection_version_id": (
                binding.projection.mvt_serving_projection_version_id
            ),
            "service_release_binding_id": binding.release.service_release_binding_id,
            "slo_binding_id": binding.slo.binding_id,
            "serving_release_binding_sha256": binding.binding_sha256,
            "bound_by": binding.bound_by,
            "bound_at": binding.bound_at,
        }
        with self._transaction(binding.tenant_id) as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT data_product_version_id
                      FROM gda_control.jqdltb_serving_release_binding
                     WHERE tenant_id = :tenant_id
                       AND data_product_version_id = :data_product_version_id
                    """
                ),
                values,
            ).first()
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_jqdltb_serving_release_binding(
                        :tenant_id, :data_product_version_id, :product_urn,
                        :manifest_sha256, :output_resource_version_id,
                        :service_urn, :service_definition_version_id,
                        :layer_definition_version_id,
                        :mvt_serving_projection_version_id,
                        :service_release_binding_id, :slo_binding_id,
                        :serving_release_binding_sha256, :bound_by, :bound_at
                    )
                    """
                ),
                values,
            ).scalar_one()
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, data_product_version_id, product_urn,
                           manifest_sha256, output_resource_version_id,
                           service_urn, service_definition_version_id,
                           layer_definition_version_id,
                           mvt_serving_projection_version_id,
                           service_release_binding_id, slo_binding_id,
                           serving_release_binding_sha256, bound_by, bound_at
                      FROM gda_control.jqdltb_serving_release_binding
                     WHERE tenant_id = :tenant_id
                       AND data_product_version_id = :data_product_version_id
                    """
                ),
                values,
            ).mappings().one()
            stored = self._jqdltb_serving_release_from_row(row)
            expected = values
            if stored != expected:
                raise GatewayConflictError(
                    "JQDLTB serving release identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_jqdltb_serving_release_binding(
        self,
        tenant_id: str,
        data_product_version_id: UUID,
    ) -> dict[str, Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, data_product_version_id, product_urn,
                           manifest_sha256, output_resource_version_id,
                           service_urn, service_definition_version_id,
                           layer_definition_version_id,
                           mvt_serving_projection_version_id,
                           service_release_binding_id, slo_binding_id,
                           serving_release_binding_sha256, bound_by, bound_at
                      FROM gda_control.jqdltb_serving_release_binding
                     WHERE tenant_id = :tenant_id
                       AND data_product_version_id = :data_product_version_id
                    """
                ),
                {
                    "tenant_id": tenant,
                    "data_product_version_id": data_product_version_id,
                },
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError("JQDLTB serving release was not found")
            return self._jqdltb_serving_release_from_row(row)

    @staticmethod
    def _service_consumer_binding_from_row(row) -> ServiceConsumerBinding:
        value = dict(row)
        for key in ("scope", "compatibility_evidence"):
            value[key] = _as_json(value[key])
        return ServiceConsumerBinding.model_validate(value)

    @staticmethod
    def _service_consumer_binding_revocation_from_row(
        row,
    ) -> ServiceConsumerBindingRevocation:
        return ServiceConsumerBindingRevocation.model_validate(dict(row))

    @staticmethod
    def _service_consumer_binding_renewal_from_row(
        row,
    ) -> ServiceConsumerBindingRenewal:
        return ServiceConsumerBindingRenewal.model_validate(dict(row))

    @classmethod
    def _load_service_consumer_binding(
        cls,
        connection,
        tenant_id: str,
        service_consumer_binding_id: UUID,
    ) -> ServiceConsumerBinding | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_consumer_binding_id, service_urn,
                           service_definition_version_id,
                           service_release_binding_id, consumer_ref, action,
                           purpose, scope, credential_ref, expires_at,
                           compatibility_fingerprint, compatibility_evidence,
                           binding_sha256, created_by, created_at,
                           approval_case_ref, grant_plan_sha256,
                           renewal_of_binding_id, renewal_approval_case_ref,
                           renewal_plan_sha256
                      FROM gda_control.service_consumer_binding
                     WHERE tenant_id = :tenant_id
                       AND service_consumer_binding_id =
                            :service_consumer_binding_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_consumer_binding_id": service_consumer_binding_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_consumer_binding_from_row(row) if row is not None else None

    def register_service_consumer_binding(
        self,
        binding: ServiceConsumerBinding,
    ) -> GatewayWriteResult:
        """Record one exact-release MVT consumer grant through its recorder."""

        with self._transaction(binding.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT service_consumer_binding_id, created
                      FROM gda_control.record_service_consumer_binding(
                          :tenant_id,
                          CAST(:service_consumer_binding_id AS uuid),
                          :approval_case_ref,
                          CAST(:grant_plan_sha256 AS char(64)),
                          :service_urn,
                          CAST(:service_definition_version_id AS uuid),
                          CAST(:service_release_binding_id AS uuid),
                          :consumer_ref, :action, :purpose,
                          CAST(:scope AS jsonb), :credential_ref, :expires_at,
                          CAST(:compatibility_fingerprint AS char(64)),
                          CAST(:compatibility_evidence AS jsonb),
                          CAST(:binding_sha256 AS char(64)),
                          :created_by, :created_at
                      )
                    """
                ),
                {
                    **binding.model_dump(
                        mode="python",
                        exclude={"scope", "compatibility_evidence"},
                    ),
                    "scope": _json(binding.scope),
                    "compatibility_evidence": _json(binding.compatibility_evidence),
                },
            ).mappings().one()
            stored = self._load_service_consumer_binding(
                connection,
                binding.tenant_id,
                binding.service_consumer_binding_id,
            )
            if stored is None or stored != binding:
                raise GatewayConflictError(
                    "ServiceConsumerBinding identity has different content"
                )
            return GatewayWriteResult(stored, bool(result["created"]))

    def register_service_consumer_binding_revocation(
        self,
        revocation: ServiceConsumerBindingRevocation,
    ) -> GatewayWriteResult:
        """Record one approved binding revocation through its controlled recorder."""

        with self._transaction(revocation.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT service_consumer_binding_revocation_id, created
                      FROM gda_control.record_service_consumer_binding_revocation(
                          :tenant_id,
                          CAST(:service_consumer_binding_revocation_id AS uuid),
                          CAST(:service_consumer_binding_id AS uuid),
                          CAST(:binding_sha256 AS char(64)),
                          :approval_case_ref,
                          CAST(:revoke_plan_sha256 AS char(64)),
                          :reason, :revoked_by, :revoked_at
                      )
                    """
                ),
                revocation.model_dump(mode="python"),
            ).mappings().one()
            stored = self._load_service_consumer_binding_revocation(
                connection,
                revocation.tenant_id,
                revocation.service_consumer_binding_revocation_id,
            )
            if stored is None or stored != revocation:
                raise GatewayConflictError(
                    "ServiceConsumerBinding revocation identity has different content"
                )
            return GatewayWriteResult(stored, bool(result["created"]))

    def register_service_consumer_binding_renewal(
        self,
        binding: ServiceConsumerBinding,
        renewal: ServiceConsumerBindingRenewal,
    ) -> GatewayWriteResult:
        """Record an approval-bound replacement binding and its renewal fact."""

        if binding.renewal_of_binding_id != renewal.source_binding_id:
            raise GatewayValidationError("renewal target and fact source do not match")
        if binding.service_consumer_binding_id != renewal.target_binding_id:
            raise GatewayValidationError("renewal target and fact target do not match")
        with self._transaction(binding.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT service_consumer_binding_renewal_id, created
                      FROM gda_control.record_service_consumer_binding_renewal(
                          :tenant_id,
                          CAST(:service_consumer_binding_renewal_id AS uuid),
                          CAST(:source_binding_id AS uuid),
                          CAST(:source_binding_sha256 AS char(64)),
                          CAST(:target_binding_id AS uuid),
                          :service_urn,
                          CAST(:service_definition_version_id AS uuid),
                          CAST(:service_release_binding_id AS uuid),
                          :consumer_ref, :action, :purpose,
                          CAST(:scope AS jsonb), :credential_ref, :expires_at,
                          CAST(:compatibility_fingerprint AS char(64)),
                          CAST(:compatibility_evidence AS jsonb),
                          CAST(:target_binding_sha256 AS char(64)),
                          :created_by, :created_at, :approval_case_ref,
                          CAST(:renewal_plan_sha256 AS char(64)),
                          :renewed_by, :renewed_at
                      )
                    """
                ),
                {
                    **binding.model_dump(
                        mode="python",
                        exclude={
                            "scope",
                            "compatibility_evidence",
                            "approval_case_ref",
                            "grant_plan_sha256",
                            "renewal_of_binding_id",
                            "renewal_approval_case_ref",
                            "renewal_plan_sha256",
                        },
                    ),
                    "scope": _json(binding.scope),
                    "compatibility_evidence": _json(binding.compatibility_evidence),
                    "target_binding_sha256": binding.binding_sha256,
                    "approval_case_ref": binding.renewal_approval_case_ref,
                    "renewal_plan_sha256": binding.renewal_plan_sha256,
                    **renewal.model_dump(
                        mode="python",
                        include={
                            "service_consumer_binding_renewal_id",
                            "source_binding_id",
                            "source_binding_sha256",
                            "target_binding_id",
                            "renewed_by",
                            "renewed_at",
                        },
                    ),
                },
            ).mappings().one()
            stored_binding = self._load_service_consumer_binding(
                connection, binding.tenant_id, binding.service_consumer_binding_id
            )
            stored_renewal = self._load_service_consumer_binding_renewal(
                connection,
                binding.tenant_id,
                renewal.service_consumer_binding_renewal_id,
            )
            if stored_binding != binding or stored_renewal != renewal:
                raise GatewayConflictError(
                    "ServiceConsumerBinding renewal identity has different content"
                )
            return GatewayWriteResult(stored_binding, bool(result["created"]))

    @classmethod
    def _load_service_consumer_binding_renewal(
        cls,
        connection,
        tenant_id: str,
        renewal_id: UUID,
    ) -> ServiceConsumerBindingRenewal | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_consumer_binding_renewal_id,
                           source_binding_id, source_binding_sha256,
                           target_binding_id, target_binding_sha256,
                           approval_case_ref, renewal_plan_sha256,
                           renewed_by, renewed_at
                      FROM gda_control.service_consumer_binding_renewal
                     WHERE tenant_id = :tenant_id
                       AND service_consumer_binding_renewal_id = :renewal_id
                    """
                ),
                {"tenant_id": tenant_id, "renewal_id": renewal_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_consumer_binding_renewal_from_row(row) if row is not None else None

    @classmethod
    def _load_service_consumer_binding_revocation(
        cls,
        connection,
        tenant_id: str,
        service_consumer_binding_revocation_id: UUID,
    ) -> ServiceConsumerBindingRevocation | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_consumer_binding_revocation_id,
                           service_consumer_binding_id, binding_sha256,
                           approval_case_ref, revoke_plan_sha256, reason,
                           context, revoked_by, revoked_at
                      FROM gda_control.service_consumer_binding_revocation
                     WHERE tenant_id = :tenant_id
                       AND service_consumer_binding_revocation_id =
                           :service_consumer_binding_revocation_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "service_consumer_binding_revocation_id":
                        service_consumer_binding_revocation_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return (
            cls._service_consumer_binding_revocation_from_row(row)
            if row is not None
            else None
        )

    def get_service_consumer_binding_revocation(
        self,
        tenant_id: str,
        service_consumer_binding_id: UUID,
    ) -> ServiceConsumerBindingRevocation | None:
        """Return the append-only revoke fact for one binding, if present."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, service_consumer_binding_revocation_id,
                               service_consumer_binding_id, binding_sha256,
                               approval_case_ref, revoke_plan_sha256, reason,
                               context, revoked_by, revoked_at
                          FROM gda_control.service_consumer_binding_revocation
                         WHERE tenant_id = :tenant_id
                           AND service_consumer_binding_id =
                               :service_consumer_binding_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "service_consumer_binding_id": service_consumer_binding_id,
                    },
                )
                .mappings()
                .one_or_none()
            )
            return (
                self._service_consumer_binding_revocation_from_row(row)
                if row is not None
                else None
            )

    def get_active_service_consumer_binding_for_release(
        self,
        tenant_id: str,
        service_urn: str,
        service_definition_version_id: UUID,
        service_release_binding_id: UUID,
        consumer_ref: str,
    ) -> ServiceConsumerBinding | None:
        """Resolve the one currently active MVT grant for an exact release."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT binding.tenant_id, binding.service_consumer_binding_id,
                               binding.service_urn,
                               service_definition_version_id,
                               service_release_binding_id, consumer_ref, action,
                               purpose, scope, credential_ref, expires_at,
                               compatibility_fingerprint, compatibility_evidence,
                               binding_sha256, created_by, created_at,
                               approval_case_ref, grant_plan_sha256,
                               renewal_of_binding_id, renewal_approval_case_ref,
                               renewal_plan_sha256
                          FROM gda_control.service_consumer_binding AS binding
                         WHERE binding.tenant_id = :tenant_id
                           AND binding.service_urn = :service_urn
                           AND binding.service_definition_version_id =
                                :service_definition_version_id
                           AND binding.service_release_binding_id =
                                :service_release_binding_id
                           AND binding.consumer_ref = :consumer_ref
                           AND binding.expires_at > clock_timestamp()
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM gda_control.service_consumer_binding_revocation
                                WHERE tenant_id =
                                      binding.tenant_id
                                  AND service_consumer_binding_id =
                                      binding.service_consumer_binding_id
                           )
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM gda_control.service_consumer_binding_renewal
                                WHERE tenant_id = binding.tenant_id
                                  AND source_binding_id =
                                      binding.service_consumer_binding_id
                           )
                         ORDER BY binding.created_at DESC,
                                  binding.service_consumer_binding_id
                         LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "service_urn": service_urn,
                        "service_definition_version_id": service_definition_version_id,
                        "service_release_binding_id": service_release_binding_id,
                        "consumer_ref": consumer_ref,
                    },
                )
                .mappings()
                .one_or_none()
            )
            return (
                self._service_consumer_binding_from_row(row)
                if row is not None
                else None
            )

    @staticmethod
    def _service_deployment_from_row(row) -> ServiceDeploymentRevision:
        return ServiceDeploymentRevision.model_validate(dict(row))

    @classmethod
    def _load_service_deployment_revision(
        cls,
        connection,
        tenant_id: str,
        deployment_revision_id: UUID,
    ) -> ServiceDeploymentRevision | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, deployment_revision_id,
                           service_definition_version_id,
                           service_release_binding_id, run_id, revision_key,
                           provider_system, provider_namespace,
                           provider_deployment_id, provider_revision_ref,
                           config_sha256, deployment_sha256, state,
                           state_version, terminal_observation_id,
                           created_by, created_at, updated_at, terminal_at
                      FROM gda_control.service_deployment_revision
                     WHERE tenant_id = :tenant_id
                       AND deployment_revision_id = :deployment_revision_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "deployment_revision_id": deployment_revision_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._service_deployment_from_row(row) if row is not None else None

    def register_service_deployment_revision(
        self,
        deployment: ServiceDeploymentRevision,
    ) -> GatewayWriteResult:
        if (
            deployment.service_release_binding_id is None
            or deployment.state != ServiceDeploymentState.PLANNED
            or deployment.state_version != 0
            or deployment.terminal_observation_id is not None
            or deployment.terminal_at is not None
            or deployment.updated_at != deployment.created_at
        ):
            raise GatewayValidationError(
                "new ServiceDeploymentRevision must bind a release and start planned"
            )
        with self._transaction(deployment.tenant_id) as connection:
            existing = self._load_service_deployment_revision(
                connection,
                deployment.tenant_id,
                deployment.deployment_revision_id,
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_service_deployment_revision(
                        :tenant_id, :deployment_revision_id,
                        :service_definition_version_id,
                        :service_release_binding_id, :run_id,
                        :revision_key, :provider_system, :provider_namespace,
                        :provider_deployment_id, :provider_revision_ref,
                        :config_sha256, :deployment_sha256,
                        :created_by, :created_at
                    )
                    """
                ),
                deployment.model_dump(
                    mode="json",
                    exclude={
                        "state",
                        "state_version",
                        "terminal_observation_id",
                        "updated_at",
                        "terminal_at",
                    },
                ),
            ).scalar_one()
            stored = self._load_service_deployment_revision(
                connection,
                deployment.tenant_id,
                deployment.deployment_revision_id,
            )
            if stored is None or stored != deployment:
                raise GatewayConflictError(
                    "ServiceDeploymentRevision identity has different content"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_service_deployment_revision(
        self,
        tenant_id: str,
        deployment_revision_id: UUID,
    ) -> ServiceDeploymentRevision:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_service_deployment_revision(
                connection, tenant, deployment_revision_id
            )
            if stored is None:
                raise GatewayNotFoundError("ServiceDeploymentRevision was not found")
            return stored

    @staticmethod
    def _validate_gis_service_deployment_observation(
        deployment: ServiceDeploymentRevision,
        observation: FrameworkAttemptObservation,
    ) -> None:
        evidence = observation.evidence
        expected = {
            "schema": "gda.gis_service_deployment_observation.v2",
            "deployment_revision_id": str(deployment.deployment_revision_id),
            "service_definition_version_id": str(
                deployment.service_definition_version_id
            ),
            "service_release_binding_id": str(
                deployment.service_release_binding_id
            ),
            "provider_system": deployment.provider_system,
            "provider_namespace": deployment.provider_namespace,
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
            "config_sha256": deployment.config_sha256,
        }
        if deployment.service_release_binding_id is None:
            raise GatewayValidationError(
                "GIS deployment observation requires a release-bound deployment"
            )
        if observation.run_id != deployment.run_id:
            raise GatewayValidationError(
                "GIS deployment observation must bind the deployment PlatformRun"
            )
        if any(evidence.get(key) != value for key, value in expected.items()):
            raise GatewayValidationError(
                "GIS deployment observation does not bind the deployment identity"
            )
        if (
            observation.external_namespace != deployment.provider_namespace
            or observation.external_run_id != deployment.provider_deployment_id
            or observation.external_attempt_id != deployment.provider_revision_ref
        ):
            raise GatewayValidationError(
                "GIS deployment observation external identity does not match placement"
            )
        if observation.observed_state.lower() not in {
            "success",
            "succeeded",
            "ready",
            "completed",
            "failed",
            "error",
            "cancelled",
            "timed_out",
        }:
            raise GatewayValidationError(
                "GIS deployment observation must be a terminal provider state"
            )
        endpoint_uri = evidence.get("endpoint_uri")
        if not isinstance(endpoint_uri, str):
            raise GatewayValidationError(
                "GIS deployment observation requires a stable provider endpoint URI"
            )
        parsed_endpoint = urlsplit(endpoint_uri)
        if (
            parsed_endpoint.scheme != "https"
            or not parsed_endpoint.hostname
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise GatewayValidationError(
                "GIS deployment observation endpoint URI must be credential-free HTTPS"
            )
        if (
            not isinstance(evidence.get("provider_version"), str)
            or not evidence["provider_version"].strip()
            or not isinstance(evidence.get("health_evidence_sha256"), str)
            or len(evidence["health_evidence_sha256"]) != 64
            or not isinstance(evidence.get("provider_receipt"), dict)
            or not evidence["provider_receipt"]
        ):
            raise GatewayValidationError(
                "GIS deployment observation is missing provider readiness evidence"
            )

    def record_gis_service_deployment_observation(
        self,
        deployment_revision_id: UUID,
        observation: FrameworkAttemptObservation,
    ) -> GatewayWriteResult:
        """Record terminal provider evidence only for one deploying GIS revision."""
        with self._transaction(observation.tenant_id) as connection:
            deployment = self._load_service_deployment_revision(
                connection,
                observation.tenant_id,
                deployment_revision_id,
            )
            if deployment is None:
                raise GatewayNotFoundError("ServiceDeploymentRevision was not found")
            if deployment.state is not ServiceDeploymentState.DEPLOYING:
                raise GatewayConflictError(
                    "GIS deployment can record terminal evidence only while deploying"
                )
            if observation.observed_at < deployment.updated_at:
                raise GatewayValidationError(
                    "GIS deployment observation predates the deploying transition"
                )
            self._validate_gis_service_deployment_observation(
                deployment,
                observation,
            )
            connection.execute(
                text(
                    "SELECT set_config("
                    "'gda.gis_service_deployment_observation_allowed', '1', true)"
                )
            )
            return self._put_observation(connection, observation)

    def settle_gis_service_deployment_terminal(
        self,
        deployment_revision_id: UUID,
        observation: FrameworkAttemptObservation,
        *,
        expected_state_version: int,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> GISServiceDeploymentTerminalSettlement:
        """Atomically record release-bound terminal evidence and settle its revision."""
        if not actor_subject.startswith("workload:"):
            raise GatewayForbiddenError(
                "GIS deployment terminal settlement requires workload identity"
            )
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise GatewayValidationError("deployment settlement time requires a timezone")
        if occurred_at < observation.observed_at:
            raise GatewayValidationError(
                "deployment settlement cannot precede provider observation"
            )
        try:
            target_state = service_deployment_terminal_state(observation.observed_state)
        except ValueError as exc:
            raise GatewayValidationError(str(exc)) from exc

        with self._transaction(observation.tenant_id) as connection:
            deployment = self._load_service_deployment_revision(
                connection,
                observation.tenant_id,
                deployment_revision_id,
            )
            if deployment is None:
                raise GatewayNotFoundError("ServiceDeploymentRevision was not found")
            if deployment.state not in {
                ServiceDeploymentState.DEPLOYING,
                target_state,
            }:
                raise GatewayConflictError(
                    "GIS deployment terminal settlement requires deploying revision "
                    "or an exact terminal replay"
                )
            if (
                deployment.state is ServiceDeploymentState.DEPLOYING
                and observation.observed_at < deployment.updated_at
            ):
                raise GatewayValidationError(
                    "GIS deployment observation predates the deploying transition"
                )
            self._validate_gis_service_deployment_observation(deployment, observation)
            connection.execute(
                text(
                    "SELECT set_config("
                    "'gda.gis_service_deployment_observation_allowed', '1', true)"
                )
            )
            observation_result = self._put_observation(connection, observation)
            settled = self._transition_service_deployment_revision(
                connection,
                observation.tenant_id,
                deployment_revision_id,
                expected_state_version=expected_state_version,
                to_state=target_state,
                provider_observation_id=observation.observation_id,
                actor_subject=actor_subject,
                reason=reason,
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
            )
            return GISServiceDeploymentTerminalSettlement(
                tenant_id=observation.tenant_id,
                deployment=settled,
                observation=observation_result.value,
                observation_created=observation_result.created,
            )

    @staticmethod
    def _service_deployment_event_from_row(row) -> ServiceDeploymentEvent:
        return ServiceDeploymentEvent.model_validate(dict(row))

    def list_service_deployment_events(
        self,
        tenant_id: str,
        deployment_revision_id: UUID,
    ) -> tuple[ServiceDeploymentEvent, ...]:
        """Read the immutable, tenant-scoped transition timeline for one revision."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if (
                self._load_service_deployment_revision(
                    connection,
                    tenant,
                    deployment_revision_id,
                )
                is None
            ):
                raise GatewayNotFoundError("ServiceDeploymentRevision was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, event_id, deployment_revision_id,
                               sequence_no, from_state, to_state,
                               provider_observation_id, actor_subject, reason,
                               idempotency_key, event_sha256, occurred_at
                          FROM gda_control.service_deployment_event
                         WHERE tenant_id = :tenant_id
                           AND deployment_revision_id = :deployment_revision_id
                         ORDER BY sequence_no ASC, event_id ASC
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "deployment_revision_id": deployment_revision_id,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(self._service_deployment_event_from_row(row) for row in rows)

    def _transition_service_deployment_revision(
        self,
        connection,
        tenant_id: str,
        deployment_revision_id: UUID,
        *,
        expected_state_version: int,
        to_state: ServiceDeploymentState | str,
        provider_observation_id: UUID | None,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> ServiceDeploymentRevision:
        state = ServiceDeploymentState(to_state)
        connection.execute(
            text(
                """
                SELECT gda_control.transition_service_deployment_revision(
                    :tenant_id, :deployment_revision_id,
                    :expected_state_version, :to_state,
                    :provider_observation_id, :actor_subject, :reason,
                    :idempotency_key, :occurred_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "deployment_revision_id": deployment_revision_id,
                "expected_state_version": expected_state_version,
                "to_state": state.value,
                "provider_observation_id": provider_observation_id,
                "actor_subject": actor_subject,
                "reason": reason,
                "idempotency_key": idempotency_key,
                "occurred_at": occurred_at.astimezone(UTC),
            },
        ).scalar_one()
        stored = self._load_service_deployment_revision(
            connection, tenant_id, deployment_revision_id
        )
        if stored is None:
            raise GatewayNotFoundError("ServiceDeploymentRevision was not found")
        return stored

    def transition_service_deployment_revision(
        self,
        tenant_id: str,
        deployment_revision_id: UUID,
        *,
        expected_state_version: int,
        to_state: ServiceDeploymentState | str,
        provider_observation_id: UUID | None,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> ServiceDeploymentRevision:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise GatewayValidationError("deployment transition time requires a timezone")
        with self._transaction(tenant) as connection:
            return self._transition_service_deployment_revision(
                connection,
                tenant,
                deployment_revision_id,
                expected_state_version=expected_state_version,
                to_state=to_state,
                provider_observation_id=provider_observation_id,
                actor_subject=actor_subject,
                reason=reason,
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
            )

    @staticmethod
    def _endpoint_revision_from_row(row) -> EndpointRevision:
        value = dict(row)
        value["endpoint_contract"] = _as_json(value["endpoint_contract"])
        return EndpointRevision.model_validate(value)

    @classmethod
    def _load_endpoint_revision(
        cls,
        connection,
        tenant_id: str,
        endpoint_revision_id: UUID,
    ) -> EndpointRevision | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, endpoint_revision_id, service_urn,
                           deployment_revision_id, endpoint_protocol,
                           endpoint_uri, endpoint_contract, endpoint_sha256,
                           created_by, created_at
                      FROM gda_control.endpoint_revision
                     WHERE tenant_id = :tenant_id
                       AND endpoint_revision_id = :endpoint_revision_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "endpoint_revision_id": endpoint_revision_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._endpoint_revision_from_row(row) if row is not None else None

    def register_endpoint_revision(
        self,
        endpoint: EndpointRevision,
    ) -> GatewayWriteResult:
        with self._transaction(endpoint.tenant_id) as connection:
            existing = self._load_endpoint_revision(
                connection, endpoint.tenant_id, endpoint.endpoint_revision_id
            )
            connection.execute(
                text(
                    """
                    SELECT gda_control.record_endpoint_revision(
                        :tenant_id, :endpoint_revision_id, :service_urn,
                        :deployment_revision_id, :endpoint_protocol,
                        :endpoint_uri, CAST(:endpoint_contract AS jsonb),
                        :endpoint_sha256, :created_by, :created_at
                    )
                    """
                ),
                {
                    **endpoint.model_dump(
                        mode="json",
                        exclude={"endpoint_protocol", "endpoint_contract"},
                    ),
                    "endpoint_protocol": endpoint.endpoint_protocol.value,
                    "endpoint_contract": _json(endpoint.endpoint_contract),
                },
            ).scalar_one()
            stored = self._load_endpoint_revision(
                connection, endpoint.tenant_id, endpoint.endpoint_revision_id
            )
            if stored is None or stored != endpoint:
                raise GatewayConflictError("EndpointRevision identity has different content")
            return GatewayWriteResult(stored, existing is None)

    def get_endpoint_revision(
        self,
        tenant_id: str,
        endpoint_revision_id: UUID,
    ) -> EndpointRevision:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_endpoint_revision(
                connection, tenant, endpoint_revision_id
            )
            if stored is None:
                raise GatewayNotFoundError("EndpointRevision was not found")
            return stored

    @classmethod
    def _load_gis_service_control_projection(
        cls,
        connection,
        tenant_id: str,
        service_urn: str,
    ) -> GISServiceControlProjection | None:
        root = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, service_urn,
                           active_endpoint_revision_id,
                           endpoint_state_version, created_at, updated_at
                      FROM gda_control.gis_service
                     WHERE tenant_id = :tenant_id AND service_urn = :service_urn
                    """
                ),
                {"tenant_id": tenant_id, "service_urn": service_urn},
            )
            .mappings()
            .one_or_none()
        )
        if root is None:
            return None
        active_endpoint = None
        active_deployment = None
        active_definition = None
        active_release = None
        active_layer = None
        active_style = None
        active_tile_matrix_set = None
        active_cache_policy = None
        active_service_policy = None
        active_mvt_serving_projection = None
        if root["active_endpoint_revision_id"] is not None:
            active_endpoint = cls._load_endpoint_revision(
                connection,
                tenant_id,
                root["active_endpoint_revision_id"],
            )
            if active_endpoint is None:
                raise GatewayConflictError("active EndpointRevision is missing")
            active_deployment = cls._load_service_deployment_revision(
                connection,
                tenant_id,
                active_endpoint.deployment_revision_id,
            )
            if active_deployment is None:
                raise GatewayConflictError("active ServiceDeploymentRevision is missing")
            active_definition = cls._load_gis_service_definition_version(
                connection,
                tenant_id,
                active_deployment.service_definition_version_id,
            )
            if active_definition is None:
                raise GatewayConflictError("active GISServiceDefinitionVersion is missing")
            if active_deployment.service_release_binding_id is not None:
                active_release = cls._load_service_release_binding(
                    connection,
                    tenant_id,
                    active_deployment.service_release_binding_id,
                )
                if active_release is None:
                    raise GatewayConflictError("active ServiceReleaseBinding is missing")
                active_layer = cls._load_layer_definition_version(
                    connection,
                    tenant_id,
                    active_release.layer_definition_version_id,
                )
                if active_layer is None:
                    raise GatewayConflictError("active LayerDefinitionVersion is missing")
                active_style = cls._load_style_definition_version(
                    connection,
                    tenant_id,
                    active_release.style_definition_version_id,
                )
                if active_style is None:
                    raise GatewayConflictError("active StyleDefinitionVersion is missing")
                if active_release.tile_matrix_set_definition_version_id is not None:
                    active_tile_matrix_set = (
                        cls._load_tile_matrix_set_definition_version(
                            connection,
                            tenant_id,
                            active_release.tile_matrix_set_definition_version_id,
                        )
                    )
                    if active_tile_matrix_set is None:
                        raise GatewayConflictError(
                            "active TileMatrixSetDefinitionVersion is missing"
                        )
                if active_release.cache_policy_version_id is not None:
                    active_cache_policy = cls._load_cache_policy_version(
                        connection,
                        tenant_id,
                        active_release.cache_policy_version_id,
                    )
                    if active_cache_policy is None:
                        raise GatewayConflictError("active CachePolicyVersion is missing")
                if active_release.mvt_serving_projection_version_id is not None:
                    active_mvt_serving_projection = (
                        cls._load_mvt_serving_projection_version(
                            connection,
                            tenant_id,
                            active_release.mvt_serving_projection_version_id,
                        )
                    )
                    if active_mvt_serving_projection is None:
                        raise GatewayConflictError(
                            "active MVTServingProjectionVersion is missing"
                        )
                active_service_policy = cls._load_service_policy_binding_for_release(
                    connection,
                    tenant_id,
                    active_deployment.service_definition_version_id,
                    active_release.service_release_binding_id,
                )
        return GISServiceControlProjection(
            tenant_id=root["tenant_id"],
            service_urn=root["service_urn"],
            endpoint_state_version=root["endpoint_state_version"],
            active_endpoint_revision=active_endpoint,
            active_deployment_revision=active_deployment,
            active_service_definition_version=active_definition,
            active_release_binding=active_release,
            active_layer_definition_version=active_layer,
            active_style_definition_version=active_style,
            active_tile_matrix_set_definition_version=active_tile_matrix_set,
            active_cache_policy_version=active_cache_policy,
            active_service_policy_binding=active_service_policy,
            active_mvt_serving_projection_version=active_mvt_serving_projection,
            created_at=root["created_at"],
            updated_at=root["updated_at"],
        )

    def get_gis_service_control_projection(
        self,
        tenant_id: str,
        service_urn: str,
    ) -> GISServiceControlProjection:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            projection = self._load_gis_service_control_projection(
                connection, tenant, service_urn
            )
            if projection is None:
                raise GatewayNotFoundError("GIS service was not found")
            return projection

    @staticmethod
    def _gis_service_slo_binding_from_row(row: Any) -> GISServiceSLOBinding:
        return GISServiceSLOBinding.model_validate(dict(row))

    def bind_gis_service_slo(
        self,
        binding: GISServiceSLOBinding,
    ) -> GatewayWriteResult:
        with self._transaction(binding.tenant_id) as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT binding_id
                    FROM gda_control.gis_service_slo_binding
                    WHERE tenant_id = :tenant_id AND service_urn = :service_urn
                      AND slo_definition_ref = :slo_definition_ref
                      AND activation_version = :activation_version
                    """
                ),
                {
                    "tenant_id": binding.tenant_id,
                    "service_urn": binding.service_urn,
                    "slo_definition_ref": binding.slo_definition_ref,
                    "activation_version": binding.activation_version,
                },
            ).first()
            connection.execute(
                text(
                    """
                    SELECT gda_control.bind_gis_service_slo(
                        :tenant_id, :binding_id, :service_urn,
                        :slo_definition_ref, :active_version_ref,
                        :definition_fingerprint, :approval_case_ref,
                        :activation_version, :bound_by, :binding_reason,
                        :bound_at
                    )
                    """
                ),
                binding.model_dump(mode="json"),
            ).scalar_one()
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, service_urn,
                           slo_definition_ref, active_version_ref,
                           definition_fingerprint, approval_case_ref,
                           activation_version, bound_by, binding_reason, bound_at
                    FROM gda_control.gis_service_slo_binding
                    WHERE tenant_id = :tenant_id AND binding_id = :binding_id
                    """
                ),
                {"tenant_id": binding.tenant_id, "binding_id": binding.binding_id},
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError("GIS ServiceSLO binding was not visible")
            stored = self._gis_service_slo_binding_from_row(row)
            if stored.model_copy(update={"bound_at": binding.bound_at}) != binding:
                raise GatewayConflictError(
                    "GIS ServiceSLO binding identity already has different evidence"
                )
            return GatewayWriteResult(stored, existing is None)

    def get_gis_service_slo_binding(
        self,
        tenant_id: str,
        service_urn: str,
    ) -> GISServiceSLOBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, service_urn,
                           slo_definition_ref, active_version_ref,
                           definition_fingerprint, approval_case_ref,
                           activation_version, bound_by, binding_reason, bound_at
                    FROM gda_control.gis_service_slo_binding b
                    JOIN gda_control.slo_definition_activation a
                      ON a.tenant_id = b.tenant_id
                     AND a.slo_definition_ref = b.slo_definition_ref
                     AND a.active_version_ref = b.active_version_ref
                     AND a.active_fingerprint = b.definition_fingerprint
                     AND a.approval_case_ref = b.approval_case_ref
                     AND a.activation_version = b.activation_version
                    WHERE b.tenant_id = :tenant_id AND b.service_urn = :service_urn
                    ORDER BY bound_at DESC, binding_id DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant, "service_urn": service_urn},
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError("GIS ServiceSLO binding was not found")
            return self._gis_service_slo_binding_from_row(row)

    def get_active_gis_service_slo_binding(
        self,
        tenant_id: str,
        service_urn: str,
        *,
        slo_definition_ref: str,
        active_version_ref: str,
        definition_fingerprint: str,
        approval_case_ref: str,
        activation_version: int,
    ) -> GISServiceSLOBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT b.tenant_id, b.binding_id, b.service_urn,
                           b.slo_definition_ref, b.active_version_ref,
                           b.definition_fingerprint, b.approval_case_ref,
                           b.activation_version, b.bound_by, b.binding_reason,
                           b.bound_at
                    FROM gda_control.gis_service_slo_binding b
                    JOIN gda_control.slo_definition_activation a
                      ON a.tenant_id = b.tenant_id
                     AND a.slo_definition_ref = b.slo_definition_ref
                     AND a.active_version_ref = b.active_version_ref
                     AND a.active_fingerprint = b.definition_fingerprint
                     AND a.approval_case_ref = b.approval_case_ref
                     AND a.activation_version = b.activation_version
                    WHERE b.tenant_id = :tenant_id
                      AND b.service_urn = :service_urn
                      AND b.slo_definition_ref = :slo_definition_ref
                      AND b.active_version_ref = :active_version_ref
                      AND b.definition_fingerprint = :definition_fingerprint
                      AND b.approval_case_ref = :approval_case_ref
                      AND b.activation_version = :activation_version
                    """
                ),
                {
                    "tenant_id": tenant,
                    "service_urn": service_urn,
                    "slo_definition_ref": slo_definition_ref,
                    "active_version_ref": active_version_ref,
                    "definition_fingerprint": definition_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "activation_version": activation_version,
                },
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError(
                    "GIS ServiceSLO binding is absent or no longer active"
                )
            return self._gis_service_slo_binding_from_row(row)

    def get_gis_service_slo_binding_for_authority(
        self,
        tenant_id: str,
        service_urn: str,
        *,
        slo_definition_ref: str,
        active_version_ref: str,
        definition_fingerprint: str,
        approval_case_ref: str,
        activation_version: int,
    ) -> GISServiceSLOBinding:
        """Return the immutable binding for an exact activation, including history."""
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, binding_id, service_urn,
                           slo_definition_ref, active_version_ref,
                           definition_fingerprint, approval_case_ref,
                           activation_version, bound_by, binding_reason, bound_at
                    FROM gda_control.gis_service_slo_binding
                    WHERE tenant_id = :tenant_id AND service_urn = :service_urn
                      AND slo_definition_ref = :slo_definition_ref
                      AND active_version_ref = :active_version_ref
                      AND definition_fingerprint = :definition_fingerprint
                      AND approval_case_ref = :approval_case_ref
                      AND activation_version = :activation_version
                    """
                ),
                {
                    "tenant_id": tenant,
                    "service_urn": service_urn,
                    "slo_definition_ref": slo_definition_ref,
                    "active_version_ref": active_version_ref,
                    "definition_fingerprint": definition_fingerprint,
                    "approval_case_ref": approval_case_ref,
                    "activation_version": activation_version,
                },
            ).mappings().one_or_none()
            if row is None:
                raise GatewayNotFoundError(
                    "GIS ServiceSLO binding for the SLO authority was not found"
                )
            return self._gis_service_slo_binding_from_row(row)

    @staticmethod
    def _gis_service_slo_reconciliation_from_row(
        row: Any,
    ) -> GISServiceSLOReconciliationTask:
        return GISServiceSLOReconciliationTask.model_validate(dict(row))

    def claim_gis_service_slo_reconciliations(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        actor_subject: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> tuple[GISServiceSLOReconciliationTask, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.claim_gis_service_slo_reconciliations(
                            :tenant_id, :actor_subject, :worker_id,
                            :limit, :lease_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "actor_subject": actor_subject,
                        "worker_id": worker_id,
                        "limit": limit,
                        "lease_seconds": lease_seconds,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(
                self._gis_service_slo_reconciliation_from_row(row) for row in rows
            )

    def complete_gis_service_slo_reconciliation(
        self,
        tenant_id: str,
        task_id: UUID,
        *,
        worker_id: str,
        bound_at: datetime | None = None,
    ) -> GISServiceSLOReconciliationTask:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM gda_control.complete_gis_service_slo_reconciliation(
                            :tenant_id, CAST(:task_id AS uuid), :worker_id,
                            :bound_at
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "task_id": str(task_id),
                        "worker_id": worker_id,
                        "bound_at": bound_at,
                    },
                )
                .mappings()
                .one()
            )
            return self._gis_service_slo_reconciliation_from_row(row)

    def fail_gis_service_slo_reconciliation(
        self,
        tenant_id: str,
        task_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> GISServiceSLOReconciliationTask:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM gda_control.fail_gis_service_slo_reconciliation(
                            :tenant_id, CAST(:task_id AS uuid), :worker_id,
                            :error, :retry_delay_seconds
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "task_id": str(task_id),
                        "worker_id": worker_id,
                        "error": error,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )
                .mappings()
                .one()
            )
            return self._gis_service_slo_reconciliation_from_row(row)

    def activate_gis_service_endpoint(
        self,
        tenant_id: str,
        service_urn: str,
        endpoint_revision_id: UUID,
        *,
        expected_state_version: int,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> GISServiceControlProjection:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise GatewayValidationError("endpoint activation time requires a timezone")
        with self._transaction(tenant) as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.activate_gis_service_endpoint(
                        :tenant_id, :service_urn, :endpoint_revision_id,
                        :expected_state_version, :actor_subject, :reason,
                        :idempotency_key, :occurred_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "service_urn": service_urn,
                    "endpoint_revision_id": endpoint_revision_id,
                    "expected_state_version": expected_state_version,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "occurred_at": occurred_at.astimezone(UTC),
                },
            ).scalar_one()
            projection = self._load_gis_service_control_projection(
                connection, tenant, service_urn
            )
            if projection is None:
                raise GatewayNotFoundError("GIS service was not found")
            return projection


def build_gateway_report(
    *,
    tenant_migration: Path | None = None,
    role_migration: Path | None = None,
    command_migration: Path | None = None,
    success_migration: Path | None = None,
    blueprint_test_success_migration: Path | None = None,
    cancel_migration: Path | None = None,
    incident_migration: Path | None = None,
    incident_subject_migration: Path | None = None,
    master_data_migration: Path | None = None,
    master_resource_projection_migration: Path | None = None,
    master_metadata_projection_migration: Path | None = None,
    notification_migration: Path | None = None,
    consumer_binding_notification_migration: Path | None = None,
    gis_service_consumer_migration_impact_migration: Path | None = None,
    gis_service_migration_cutover_migration: Path | None = None,
    gis_service_migration_rollback_migration: Path | None = None,
    gis_service_endpoint_warmup_migration: Path | None = None,
    gis_service_endpoint_warmup_command_migration: Path | None = None,
    gis_mvt_cache_purge_outbox_migration: Path | None = None,
    gis_service_slo_binding_migration: Path | None = None,
    gis_service_slo_reconciliation_migration: Path | None = None,
    gis_service_slo_incident_migration: Path | None = None,
    jqdltb_serving_release_migration: Path | None = None,
    jqdltb_serving_endpoint_promotion_migration: Path | None = None,
    ogc_api_features_endpoint_contract_migration: Path | None = None,
    run_event_delivery_migration: Path | None = None,
    metadata_fabric_migration: Path | None = None,
    gateway_source: Path | None = None,
    routes_source: Path | None = None,
    command_consumer_source: Path | None = None,
    command_worker_source: Path | None = None,
    gis_service_endpoint_warmup_consumer_source: Path | None = None,
    gis_service_endpoint_warmup_worker_source: Path | None = None,
    gis_service_slo_reconciliation_worker_source: Path | None = None,
    notification_worker_source: Path | None = None,
    consumer_binding_notification_worker_source: Path | None = None,
    run_event_delivery_worker_source: Path | None = None,
    master_metadata_worker_source: Path | None = None,
    schedule_controller_source: Path | None = None,
    manual_controller_source: Path | None = None,
    cancel_controller_source: Path | None = None,
) -> dict[str, Any]:
    """Validate the static role, transaction, and HTTP boundary markers."""
    paths = {
        "tenant_migration": (tenant_migration or USER_TENANT_MIGRATION).resolve(),
        "role_migration": (role_migration or GATEWAY_ROLE_MIGRATION).resolve(),
        "command_migration": (command_migration or COMMAND_OUTBOX_MIGRATION).resolve(),
        "success_migration": (success_migration or SUCCESS_VERDICT_MIGRATION).resolve(),
        "blueprint_test_success_migration": (
            blueprint_test_success_migration or BLUEPRINT_TEST_SUCCESS_MIGRATION
        ).resolve(),
        "cancel_migration": (cancel_migration or CANCEL_COMMAND_MIGRATION).resolve(),
        "incident_migration": (incident_migration or DATA_INCIDENT_MIGRATION).resolve(),
        "incident_subject_migration": (
            incident_subject_migration or INCIDENT_SUBJECT_MIGRATION
        ).resolve(),
        "master_data_migration": (
            master_data_migration or MASTER_DATA_MIGRATION
        ).resolve(),
        "master_resource_projection_migration": (
            master_resource_projection_migration
            or MASTER_RESOURCE_PROJECTION_MIGRATION
        ).resolve(),
        "master_metadata_projection_migration": (
            master_metadata_projection_migration
            or MASTER_METADATA_PROJECTION_MIGRATION
        ).resolve(),
        "notification_migration": (
            notification_migration or INCIDENT_NOTIFICATION_MIGRATION
        ).resolve(),
        "notification_receipt_migration": (
            INCIDENT_NOTIFICATION_RECEIPT_MIGRATION
        ).resolve(),
        "notification_receipt_strict_migration": (
            INCIDENT_NOTIFICATION_RECEIPT_STRICT_MIGRATION
        ).resolve(),
        "notification_recovery_migration": (
            INCIDENT_NOTIFICATION_RECOVERY_MIGRATION
        ).resolve(),
        "consumer_binding_notification_migration": (
            consumer_binding_notification_migration
            or CONSUMER_BINDING_NOTIFICATION_MIGRATION
        ).resolve(),
        "gis_service_consumer_migration_impact_migration": (
            gis_service_consumer_migration_impact_migration
            or GIS_SERVICE_CONSUMER_MIGRATION_IMPACT_MIGRATION
        ).resolve(),
        "gis_service_migration_cutover_migration": (
            gis_service_migration_cutover_migration
            or GIS_SERVICE_MIGRATION_CUTOVER_MIGRATION
        ).resolve(),
        "gis_service_migration_rollback_migration": (
            gis_service_migration_rollback_migration
            or GIS_SERVICE_MIGRATION_ROLLBACK_MIGRATION
        ).resolve(),
        "gis_service_endpoint_warmup_migration": (
            gis_service_endpoint_warmup_migration
            or GIS_SERVICE_ENDPOINT_WARMUP_MIGRATION
        ).resolve(),
        "gis_service_endpoint_warmup_command_migration": (
            gis_service_endpoint_warmup_command_migration
            or GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_MIGRATION
        ).resolve(),
        "gis_mvt_cache_purge_outbox_migration": (
            gis_mvt_cache_purge_outbox_migration
            or GIS_MVT_CACHE_PURGE_OUTBOX_MIGRATION
        ).resolve(),
        "gis_service_slo_binding_migration": (
            gis_service_slo_binding_migration
            or GIS_SERVICE_SLO_BINDING_MIGRATION
        ).resolve(),
        "gis_service_slo_reconciliation_migration": (
            gis_service_slo_reconciliation_migration
            or GIS_SERVICE_SLO_RECONCILIATION_MIGRATION
        ).resolve(),
        "gis_service_slo_incident_migration": (
            gis_service_slo_incident_migration or GIS_SERVICE_SLO_INCIDENT_MIGRATION
        ).resolve(),
        "jqdltb_serving_release_migration": (
            jqdltb_serving_release_migration or JQDLTB_SERVING_RELEASE_MIGRATION
        ).resolve(),
        "jqdltb_serving_endpoint_promotion_migration": (
            jqdltb_serving_endpoint_promotion_migration
            or JQDLTB_SERVING_ENDPOINT_PROMOTION_MIGRATION
        ).resolve(),
        "mvt_serving_relation_attestation_migration": (
            MVT_SERVING_RELATION_ATTESTATION_MIGRATION
        ).resolve(),
        "ogc_api_features_endpoint_contract_migration": (
            ogc_api_features_endpoint_contract_migration
            or OGC_API_FEATURES_ENDPOINT_CONTRACT_MIGRATION
        ).resolve(),
        "run_event_delivery_migration": (
            run_event_delivery_migration or RUN_EVENT_DELIVERY_MIGRATION
        ).resolve(),
        "metadata_fabric_migration": (
            metadata_fabric_migration or METADATA_FABRIC_MIGRATION
        ).resolve(),
        "gateway_source": (gateway_source or Path(__file__)).resolve(),
        "routes_source": (routes_source or GATEWAY_ROUTES_SOURCE).resolve(),
        "command_consumer_source": (command_consumer_source or COMMAND_CONSUMER_SOURCE).resolve(),
        "command_worker_source": (command_worker_source or COMMAND_WORKER_SOURCE).resolve(),
        "gis_service_endpoint_warmup_consumer_source": (
            gis_service_endpoint_warmup_consumer_source
            or GIS_SERVICE_ENDPOINT_WARMUP_CONSUMER_SOURCE
        ).resolve(),
        "gis_service_endpoint_warmup_worker_source": (
            gis_service_endpoint_warmup_worker_source
            or GIS_SERVICE_ENDPOINT_WARMUP_WORKER_SOURCE
        ).resolve(),
        "gis_service_slo_reconciliation_worker_source": (
            gis_service_slo_reconciliation_worker_source
            or GIS_SERVICE_SLO_RECONCILIATION_WORKER_SOURCE
        ).resolve(),
        "notification_worker_source": (
            notification_worker_source or INCIDENT_NOTIFICATION_WORKER_SOURCE
        ).resolve(),
        "consumer_binding_notification_worker_source": (
            consumer_binding_notification_worker_source
            or CONSUMER_BINDING_NOTIFICATION_WORKER_SOURCE
        ).resolve(),
        "run_event_delivery_worker_source": (
            run_event_delivery_worker_source or RUN_EVENT_DELIVERY_WORKER_SOURCE
        ).resolve(),
        "master_metadata_worker_source": (
            master_metadata_worker_source or MASTER_METADATA_WORKER_SOURCE
        ).resolve(),
        "schedule_controller_source": (
            schedule_controller_source or SCHEDULE_CONTROLLER_SOURCE
        ).resolve(),
        "manual_controller_source": (
            manual_controller_source or MANUAL_CONTROLLER_SOURCE
        ).resolve(),
        "cancel_controller_source": (
            cancel_controller_source or CANCEL_CONTROLLER_SOURCE
        ).resolve(),
    }
    texts: dict[str, str] = {}
    errors: list[str] = []
    files: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"{name} is missing")
            files[name] = {"path": path.as_posix(), "sha256": None}
            continue
        raw = path.read_bytes()
        texts[name] = raw.decode("utf-8")
        files[name] = {
            "path": path.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    required = {
        "tenant_migration": (
            "ADD COLUMN IF NOT EXISTS tenant_id",
            "ck_agent_app_users_tenant_id",
        ),
        "role_migration": (
            "CREATE ROLE gda_control_gateway",
            "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS",
            "REVOKE ALL ON ALL TABLES IN SCHEMA gda_control",
            "GRANT EXECUTE ON FUNCTION gda_control.transition_platform_run(",
            "ALTER FUNCTION gda_control.initialize_platform_run_event() SECURITY DEFINER",
        ),
        "command_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.platform_command_outbox",
            "FOR UPDATE SKIP LOCKED",
            "AND actor_subject = p_actor_subject",
            "claimed_until <= clock_timestamp()",
            "REVOKE ALL ON TABLE gda_control.platform_command_outbox",
            "GRANT SELECT, INSERT ON gda_control.platform_command_outbox",
            "claim_platform_commands",
            "complete_platform_command",
            "fail_platform_command",
        ),
        "success_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.quality_result",
            "RENAME TO apply_platform_run_transition",
            "succeeded requires gda_control.finalize_platform_run_success()",
            "DolphinScheduler success observation was not found",
            "content-bound output Artifact was not found",
            "independent passed QualityResult was not found",
            "input-to-output LineageEvent was not found",
            "GRANT SELECT, INSERT ON gda_control.quality_result",
            "finalize_platform_run_success",
        ),
        "blueprint_test_success_migration": (
            "CREATE OR REPLACE FUNCTION gda_control.finalize_blueprint_test_run_success(",
            "framework_kind = 'duckdb'",
            "gda.blueprint_test_executor_receipt.v1",
            "executor_mode' = 'deterministic_local'",
            "GRANT EXECUTE ON FUNCTION gda_control.finalize_blueprint_test_run_success(",
        ),
        "cancel_migration": (
            "ALTER TABLE gda_control.platform_command_outbox",
            "'dolphinscheduler.cancel'",
            "ADD CONSTRAINT ck_gda_command_type",
        ),
        "incident_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.data_incident",
            "CREATE TABLE IF NOT EXISTS gda_control.data_incident_event",
            "transition_data_incident",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT, INSERT ON gda_control.data_incident",
        ),
        "incident_subject_migration": (
            "ADD COLUMN IF NOT EXISTS subject_resource_urn",
            "num_nonnulls(run_id, subject_resource_urn) = 1",
            "idx_gda_data_incident_subject",
            "NEW.subject_resource_urn IS DISTINCT FROM OLD.subject_resource_urn",
        ),
        "master_data_migration": (
            "master_source_record",
            "master_match_candidate",
            "master_entity_version",
            "activate_master_entity_version",
            "master_data.entity.activate",
            "FORCE ROW LEVEL SECURITY",
        ),
        "master_resource_projection_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.master_resource_projection",
            "master_resource_version_id",
            "project_master_activation_to_resource",
            "trg_gda_master_activation_resource_projection",
            "master Resource identity already has different evidence",
            "master ResourceVersion identity already has different evidence",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.master_resource_projection",
        ),
        "master_metadata_projection_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.master_metadata_projection_outbox",
            "enqueue_master_metadata_projection",
            "FOR UPDATE SKIP LOCKED",
            "claim_master_metadata_projections",
            "complete_master_metadata_projection",
            "fail_master_metadata_projection",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.master_metadata_projection_outbox",
        ),
        "notification_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.data_incident_notification_outbox",
            "enqueue_data_incident_notification",
            "FOR UPDATE SKIP LOCKED",
            "claim_data_incident_notifications",
            "complete_data_incident_notification",
            "fail_data_incident_notification",
            "GRANT SELECT ON TABLE gda_control.data_incident_notification_outbox",
        ),
        "notification_receipt_migration": (
            "data_incident_notification_receipt_fingerprint",
            "gda.data_incident_notification_receipt.v1",
            "provider_receipt JSONB NOT NULL DEFAULT '{}'::jsonb",
            "terminal_worker_id TEXT",
            "complete_data_incident_notification(\n    p_tenant_id TEXT,",
            "provider receipt is invalid",
        ),
        "notification_receipt_strict_migration": (
            "complete_data_incident_notification(",
            "gda.alertmanager_provider_receipt.v1",
            "provider receipt is invalid",
            "claimed_until > clock_timestamp()",
        ),
        "notification_recovery_migration": (
            "data_incident_notification_recovery_event",
            "recover_data_incident_notification",
            "previous_receipt_sha256",
            "notification manual recovery limit reached",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.data_incident_notification_recovery_event",
        ),
        "consumer_binding_notification_migration": (
            "consumer_binding_migration_notification_outbox",
            "enqueue_consumer_binding_migration_notification",
            "FOR UPDATE SKIP LOCKED",
            "claim_consumer_binding_migration_notifications",
            "complete_consumer_binding_migration_notification",
            "fail_consumer_binding_migration_notification",
            "consumer_binding_notification_receipt_fingerprint",
            "terminal notification evidence is not backed by a valid outbox receipt",
            "FORCE ROW LEVEL SECURITY",
        ),
        "gis_service_consumer_migration_impact_migration": (
            "gis_service_consumer_binding_migration_impact",
            "guard_gis_service_consumer_binding_migration_impact_insert",
            "record_gis_service_consumer_binding_migration_impact",
            "FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE gda_control.gis_service_consumer_binding_migration_impact",
            (
                "GRANT EXECUTE ON FUNCTION "
                "gda_control.record_gis_service_consumer_binding_migration_impact"
            ),
        ),
        "gis_service_migration_cutover_migration": (
            "gis_service_migration_cutover",
            "cutover_gis_service_migration",
            "activate_gis_service_endpoint_unverified",
            "cross-product GIS endpoint activation requires migration cutover authority",
            "release_namespace_rollover",
            "FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE gda_control.gis_service_migration_cutover",
            "GRANT EXECUTE ON FUNCTION gda_control.cutover_gis_service_migration",
        ),
        "gis_service_migration_rollback_migration": (
            "gis_service_migration_rollback",
            "rollback_gis_service_migration",
            "gis_service_migration_rollback_operation_fingerprint",
            "gda.gis_service_migration.rollback.v1",
            "migration cutover or rollback authority",
            "release_namespace_rollover",
            "FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE gda_control.gis_service_migration_rollback",
            "GRANT EXECUTE ON FUNCTION gda_control.rollback_gis_service_migration",
        ),
        "gis_service_endpoint_warmup_migration": (
            "gis_service_endpoint_warmup",
            "record_gis_service_endpoint_warmup",
            "gis_service_endpoint_warmup_fingerprint",
            "gis-service-endpoint-warmup",
            "warmup Run lacks evidence-gated success",
            "guard_gis_service_migration_destination_warmup",
            "FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE gda_control.gis_service_endpoint_warmup",
            "GRANT EXECUTE ON FUNCTION gda_control.record_gis_service_endpoint_warmup",
        ),
        "gis_service_endpoint_warmup_command_migration": (
            "ALTER TABLE gda_control.platform_command_outbox",
            "'gis_service.endpoint_warmup'",
            "finalize_gis_service_endpoint_warmup_success(",
            "gda.gis_service_endpoint_warmup_execution_plan.v1",
            "gda.gis_service_endpoint_warmup_receipt.v1",
            "gda.gis_service_endpoint_warmup_quality.v1",
            "gda.gis_service_endpoint_warmup_lineage.v1",
            "fail_gis_service_endpoint_warmup_command_terminal(",
            "FROM PUBLIC, gda_control_gateway",
            ") TO gda_control_gateway;",
        ),
        "gis_mvt_cache_purge_outbox_migration": (
            "gis_mvt_cache_purge_outbox",
            "gis_mvt_cache_generation",
            "enqueue_gis_mvt_cache_purge",
            "AFTER INSERT ON gda_control.gis_service_migration_cutover",
            "AFTER INSERT ON gda_control.gis_service_migration_rollback",
            "FOR UPDATE SKIP LOCKED",
            "claim_gis_mvt_cache_purges",
            "complete_gis_mvt_cache_purge",
            "fail_gis_mvt_cache_purge",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.gis_mvt_cache_purge_outbox",
        ),
        "gis_service_slo_binding_migration": (
            "gis_service_slo_binding",
            "bind_gis_service_slo",
            "exact active authority",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.gis_service_slo_binding",
        ),
        "gis_service_slo_reconciliation_migration": (
            "gis_service_slo_reconciliation_outbox",
            "enqueue_slo_activation_gis_service_reconciliation",
            "AFTER INSERT OR UPDATE ON gda_control.slo_definition_activation",
            "FOR UPDATE SKIP LOCKED",
            "claim_gis_service_slo_reconciliations",
            "complete_gis_service_slo_reconciliation",
            "fail_gis_service_slo_reconciliation",
            "activation superseded before reconciliation",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.gis_service_slo_reconciliation_outbox",
        ),
        "gis_service_slo_incident_migration": (
            "assert_gis_service_slo_incident_authority",
            "FOR SHARE",
            "exact active authority",
            "GIS ServiceSLO incident has no exact binding",
            "REVOKE ALL ON FUNCTION gda_control.assert_gis_service_slo_incident_authority",
            "GRANT EXECUTE ON FUNCTION gda_control.assert_gis_service_slo_incident_authority",
        ),
        "jqdltb_serving_release_migration": (
            "jqdltb_serving_release_binding",
            "record_jqdltb_serving_release_binding",
            "JQDLTB serving binding requires the current DataProductVersion",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.jqdltb_serving_release_binding",
            "GRANT EXECUTE ON FUNCTION gda_control.record_jqdltb_serving_release_binding",
        ),
        "jqdltb_serving_endpoint_promotion_migration": (
            "enforce_jqdltb_serving_endpoint_binding",
            "gda.jqdltb_mapping_binding.v1",
            "JQDLTB endpoint promotion requires an exact serving release binding",
            "trg_gda_jqdltb_active_endpoint_serving_binding",
        ),
        "ogc_api_features_endpoint_contract_migration": (
            "validate_ogc_api_features_endpoint_contract",
            "validate_ogc_api_features_activation",
            "gda.ogc_api_features_endpoint.v1",
            "collection_id",
            "BEFORE INSERT ON gda_control.endpoint_revision",
            "BEFORE INSERT ON gda_control.gis_service_endpoint_activation_event",
            "REVOKE ALL ON FUNCTION gda_control.validate_ogc_api_features_activation",
        ),
        "run_event_delivery_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.platform_run_event_delivery_outbox",
            "enqueue_platform_run_event_delivery",
            "AFTER INSERT ON gda_control.platform_run_event",
            "FOR UPDATE SKIP LOCKED",
            "claim_platform_run_event_deliveries",
            "complete_platform_run_event_delivery",
            "fail_platform_run_event_delivery",
            "FORCE ROW LEVEL SECURITY",
            "GRANT SELECT ON TABLE gda_control.platform_run_event_delivery_outbox",
        ),
        "metadata_fabric_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_fabric_binding",
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_change_outbox",
            "enqueue_lineage_metadata_change",
            "FOR UPDATE SKIP LOCKED",
            "claim_metadata_changes",
            "complete_metadata_change",
            "fail_metadata_change",
            "GRANT SELECT, INSERT ON TABLE gda_control.metadata_fabric_binding",
            "GRANT SELECT ON TABLE gda_control.metadata_change_outbox",
        ),
        "gateway_source": (
            'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"',
            "SELECT set_config('app.current_tenant', :tenant, true)",
            "ON CONFLICT DO NOTHING",
            "def get_artifact(",
            "def get_definition(",
            "def submit_schedule_window(",
            "def submit_manual_trigger(",
            "def admit_dataops_cancel(",
            "SELECT pg_advisory_xact_lock(:lock_class, :lock_object)",
            "def _validate_run_policy_references(",
            "def record_attempt_and_enqueue_reconcile(",
            "def record_cancellation_terminal_mismatch(",
            "def transition_incident(",
            "def open_resource_incident(",
            "def open_gis_service_slo_incident(",
            "def claim_incident_notifications(",
            "def list_incident_notifications(",
            "def complete_incident_notification(",
            "def fail_incident_notification(",
            "def recover_incident_notification(",
            "def incident_notification_recoveries(",
            "def claim_platform_run_event_deliveries(",
            "def complete_platform_run_event_delivery(",
            "def fail_platform_run_event_delivery(",
            "def register_metadata_fabric_binding(",
            "def search_metadata_fabric_bindings(",
            "def claim_metadata_changes(",
            "def complete_metadata_change(",
            "def fail_metadata_change(",
            "def register_consumer_binding(",
            "def list_consumer_bindings(",
            "def get_active_consumer_binding_for_product_version(",
            "def record_consumer_binding_migration_state(",
            "def list_consumer_binding_migration_states(",
            "def claim_consumer_binding_migration_notifications(",
            "def complete_consumer_binding_migration_notification(",
            "def fail_consumer_binding_migration_notification(",
            "def list_consumer_binding_migration_notifications(",
            "def record_gis_service_consumer_binding_migration_impact(",
            "def list_gis_service_consumer_binding_migration_impacts(",
            "def record_gis_service_endpoint_warmup(",
            "def list_gis_service_endpoint_warmups(",
            "def admit_gis_service_endpoint_warmup_run(",
            "def settle_gis_service_endpoint_warmup_success(",
            "def fail_gis_service_endpoint_warmup_command_terminal(",
            "def claim_master_metadata_projections(",
            "def complete_master_metadata_projection(",
            "def fail_master_metadata_projection(",
            "def claim_commands(",
            "def claim_gis_mvt_cache_purges(",
            "def complete_gis_mvt_cache_purge(",
            "def fail_gis_mvt_cache_purge(",
            "def claim_gis_service_slo_reconciliations(",
            "def complete_gis_service_slo_reconciliation(",
            "def fail_gis_service_slo_reconciliation(",
            "def record_quality_result(",
            "def finalize_run_success(",
            "def reconcile_blueprint_test_provider(",
            "def execute_blueprint_duckdb_test_run(",
            "def record_lineage_batch(",
            "def query_lineage(",
            "def assess_lineage_impact(",
        ),
        "routes_source": (
            'base = "/api/platform/v1"',
            'frozenset({"admin", "platform_operator"})',
            "_gis_mvt_principal",
            "consumer_binding_required",
            '"tenant_context_required"',
            '"actor_mismatch"',
            '"capability_contract_mismatch"',
            "_capability_contract_guard",
            "create_data_product_blueprint",
            "preview_data_product_blueprint",
            "reconcile_data_product_blueprint_test_provider",
            "execute_data_product_blueprint_duckdb_test_run",
            "create_data_product_blueprint_review",
            "platform_create_data_product_blueprint",
            "platform_preview_data_product_blueprint",
            "platform_reconcile_data_product_blueprint_test_provider",
            "platform_execute_data_product_blueprint_duckdb_test_run",
            "platform_create_data_product_blueprint_review",
            "create_dolphinscheduler_callback",
            "create_quality_result",
            "finalize_run_success",
            "create_manual_dataops_run",
            "create_dataops_cancel",
            "list_data_incidents",
            "list_incident_notifications",
            "list_incident_notification_recoveries",
            "recover_incident_notification",
            "transition_data_incident",
            "reconcile_slo_alertmanager_webhook",
            "create_approval_case",
            "list_approval_case_events",
            "decide_approval_case",
            "create_openlineage_event",
            "create_metadata_fabric_binding",
            "list_metadata_fabric_bindings",
            "search_metadata_fabric_bindings",
            "get_resource_version_lineage",
            "get_resource_version_impact",
            "observe_master_source_record",
            "propose_master_source_matches",
            "stage_master_entity_version",
            "activate_master_entity_version",
            "get_active_master_entity",
            "list_master_data_events",
            "list_master_resource_projections",
            "platform_observe_master_source_record",
            "platform_propose_master_source_matches",
            "platform_stage_master_entity_version",
            "platform_activate_master_entity_version",
            "platform_get_active_master_entity",
            "platform_list_master_data_events",
            "platform_list_master_resource_projections",
        ),
        "command_consumer_source": (
            "class DolphinSchedulerCommandConsumer",
            "self.gateway.claim_commands(",
            "self.gateway.defer_dispatch_to_reconcile(",
            "self.gateway.complete_cancel_and_enqueue_reconcile(",
            "self.gateway.complete_command(",
            "self.gateway.fail_command(",
        ),
        "command_worker_source": (
            "class DolphinSchedulerCommandWorker",
            "DolphinSchedulerCommandConsumer",
            "signal.SIGTERM",
            "stop_event.wait(",
            "evaluate_worker_health",
            "evaluate_worker_liveness",
            "DOLPHINSCHEDULER_TOKEN_FILE",
        ),
        "gis_service_endpoint_warmup_consumer_source": (
            "class GISServiceEndpointWarmupConsumer",
            "class LocalWarmupReceiptStore",
            "class S3WarmupReceiptStore",
            'IfNoneMatch="*"',
            "VersionId=version_id",
            "get_object_lock_configuration",
            '"storage_evidence": publication.storage_evidence',
            "MartinVectorTileProvider",
            "self.gateway.claim_commands(",
            "self.gateway.settle_gis_service_endpoint_warmup_success(",
            "self.gateway.complete_command(",
            "self.gateway.fail_gis_service_endpoint_warmup_command_terminal(",
        ),
        "gis_service_endpoint_warmup_worker_source": (
            "class GISServiceEndpointWarmupWorker",
            "class GISServiceEndpointWarmupWorkerConfig",
            "GISServiceEndpointWarmupConsumer",
            "MartinVectorTileProvider",
            "LocalWarmupReceiptStore",
            "build_s3_warmup_receipt_store",
            'receipt_backend: Literal["local", "s3"]',
            "receipt_store.probe()",
            "self.stop_event.wait(",
            "signal.SIGTERM",
        ),
        "gis_service_slo_reconciliation_worker_source": (
            "class GISServiceSLOReconciliationWorker",
            "class GISServiceSLOReconciliationWorkerConfig",
            "self.gateway.claim_gis_service_slo_reconciliations(",
            "self.gateway.complete_gis_service_slo_reconciliation(",
            "self.gateway.fail_gis_service_slo_reconciliation(",
            "signal.SIGTERM",
            "stop_event.wait(",
        ),
        "notification_worker_source": (
            "class IncidentNotificationWorker",
            "class AlertmanagerV2Client",
            "self.gateway.claim_incident_notifications(",
            "self.gateway.complete_incident_notification(",
            "self.gateway.fail_incident_notification(",
            "provider_receipt=provider_receipt",
        ),
        "consumer_binding_notification_worker_source": (
            "class ConsumerBindingNotificationWorker",
            "self.gateway.claim_consumer_binding_migration_notifications(",
            "self.gateway.complete_consumer_binding_migration_notification(",
            "self.gateway.fail_consumer_binding_migration_notification(",
            "alertmanager:consumer-binding-default",
            "GDA_CONSUMER_BINDING_NOTIFICATION_RECORDED_BY",
        ),
        "run_event_delivery_worker_source": (
            "class PlatformRunEventWorker",
            "self.gateway.claim_platform_run_event_deliveries(",
            "self.gateway.complete_platform_run_event_delivery(",
            "self.gateway.fail_platform_run_event_delivery(",
            '"Content-Type": "application/cloudevents+json"',
            "bearer_token_file",
            "follow_redirects=False",
        ),
        "master_metadata_worker_source": (
            "class OpenMetadataMasterDataWorker",
            "external_object_type != \"glossaryTerm\"",
            '"Content-Type": "application/json-patch+json"',
            "self._get_term(envelope)",
            "self.gateway.complete_master_metadata_projection(",
            "self.gateway.fail_master_metadata_projection(",
            "follow_redirects=False",
            "GDA_OPENMETADATA_BEARER_TOKEN_FILE",
        ),
        "schedule_controller_source": (
            "class DataOpsScheduleWindowSpec",
            "def dataops_schedule_window_fingerprint(",
            "class DataOpsScheduleController",
            "def recover_windows(",
        ),
        "manual_controller_source": (
            "class DataOpsManualTriggerSpec",
            "def dataops_manual_request_identity(",
            "def dataops_manual_request_fingerprint(",
            "def build_manual_dataops_submission(",
        ),
        "cancel_controller_source": (
            "class DataOpsCancelSpec",
            "def dataops_cancel_request_identity(",
            "def dataops_cancel_request_fingerprint(",
            "def build_dataops_cancel_submission(",
        ),
    }
    missing_markers: dict[str, list[str]] = {}
    for name, markers in required.items():
        source = texts.get(name, "")
        missing = [marker for marker in markers if marker not in source]
        if missing:
            missing_markers[name] = missing
            errors.append(f"{name} is missing required gateway markers")

    role_sql = texts.get("role_migration", "")
    insert_grant = re.search(
        r"GRANT INSERT ON(?P<relations>.*?)TO gda_control_gateway;",
        role_sql,
        re.DOTALL,
    )
    if insert_grant is None:
        errors.append("gateway INSERT grant is missing")
    elif "platform_run_event" in insert_grant.group("relations"):
        errors.append("gateway role must not INSERT platform_run_event directly")
    for forbidden in ("GRANT UPDATE ON", "GRANT DELETE ON"):
        if (
            forbidden in role_sql
            or forbidden in texts.get("command_migration", "")
            or forbidden in texts.get("success_migration", "")
            or forbidden in texts.get("cancel_migration", "")
            or forbidden in texts.get("incident_migration", "")
            or forbidden in texts.get("incident_subject_migration", "")
            or forbidden in texts.get("master_data_migration", "")
            or forbidden
            in texts.get("master_resource_projection_migration", "")
            or forbidden
            in texts.get("master_metadata_projection_migration", "")
            or forbidden in texts.get("notification_migration", "")
            or forbidden in texts.get("notification_receipt_migration", "")
            or forbidden in texts.get("notification_receipt_strict_migration", "")
            or forbidden in texts.get("notification_recovery_migration", "")
            or forbidden in texts.get("gis_service_endpoint_warmup_migration", "")
            or forbidden
            in texts.get("gis_service_endpoint_warmup_command_migration", "")
            or forbidden in texts.get("metadata_fabric_migration", "")
        ):
            errors.append(f"gateway role contains forbidden privilege: {forbidden}")
    consumer_source = texts.get("command_consumer_source", "")
    for forbidden in ("while True", "asyncio.create_task", "start_workflow("):
        if forbidden in consumer_source:
            errors.append(f"command consumer contains forbidden runtime marker: {forbidden}")
    worker_source = texts.get("command_worker_source", "")
    for forbidden in (
        "start_workflow(",
        ".transition_run(",
        ".finalize_run_success(",
    ):
        if forbidden in worker_source:
            errors.append(f"command worker contains forbidden authority marker: {forbidden}")
    warmup_consumer_source = texts.get(
        "gis_service_endpoint_warmup_consumer_source", ""
    )
    for forbidden in (
        ".activate_gis_service_endpoint(",
        ".cutover_gis_service_migration(",
        ".rollback_gis_service_migration(",
        ".finalize_run_success(",
    ):
        if forbidden in warmup_consumer_source:
            errors.append(
                "GIS warmup consumer contains forbidden authority marker: "
                f"{forbidden}"
            )
    schedule_source = texts.get("schedule_controller_source", "")
    for forbidden in ("croniter", "APScheduler", "while True", "start_workflow("):
        if forbidden in schedule_source:
            errors.append(f"schedule controller contains forbidden scheduler marker: {forbidden}")
    manual_source = texts.get("manual_controller_source", "")
    for forbidden in ("croniter", "APScheduler", "while True", "start_workflow("):
        if forbidden in manual_source:
            errors.append(f"manual controller contains forbidden runtime marker: {forbidden}")

    cancel_source = texts.get("cancel_controller_source", "")
    for forbidden in ("croniter", "APScheduler", "while True", "start_workflow("):
        if forbidden in cancel_source:
            errors.append(f"cancel controller contains forbidden runtime marker: {forbidden}")

    return {
        "schema": GATEWAY_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "database_role": GATEWAY_DATABASE_ROLE,
        "route_count": 29,
        "files": files,
        "missing_markers": missing_markers,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--output")
    args = parser.parse_args(argv)

    report = build_gateway_report()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
