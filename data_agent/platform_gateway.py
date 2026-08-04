"""Least-privilege transaction scripts for the AR-1 platform control gateway."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

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
from .metadata_fabric import (
    METADATA_FABRIC_MIGRATION,
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
    DataIncident,
    DataIncidentEvent,
    FrameworkAttemptObservation,
    IncidentNotification,
    IncidentNotificationEnvelope,
    IncidentSeverity,
    IncidentStatus,
    LineageEvent,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    QualityResult,
    Resource,
    ResourceVersion,
    RunStatus,
    RunSuccessEvidence,
    SubjectType,
    TenantId,
    data_incident_fingerprint,
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
USER_TENANT_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "093_app_user_tenant_context.sql"
)
GATEWAY_ROUTES_SOURCE = Path(__file__).resolve().parent / "api" / "platform_gateway_routes.py"
COMMAND_CONSUMER_SOURCE = Path(__file__).resolve().parent / "dolphinscheduler_command_consumer.py"
COMMAND_WORKER_SOURCE = Path(__file__).resolve().parent / "dolphinscheduler_command_worker.py"
INCIDENT_NOTIFICATION_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "incident_notification_worker.py"
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

    def __init__(self, engine=None):
        self._engine = engine

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
            if state in {"22023", "22P02", "23502", "23503", "23514"}:
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
        return IncidentNotification.model_validate(dict(row))

    @classmethod
    def _load_incident(
        cls, connection, tenant_id: str, incident_id: UUID
    ) -> DataIncident | None:
        row = (
            connection.execute(
                text(
                    """
                SELECT tenant_id, incident_id, run_id, dedupe_key,
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
                    tenant_id, incident_id, run_id, dedupe_key,
                    incident_type, severity, summary,
                    trigger_observation_id, details, incident_sha256,
                    detected_by, status, state_version, opened_at, updated_at
                ) VALUES (
                    :tenant_id, :incident_id, :run_id, :dedupe_key,
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
        run_id: UUID,
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
            ),
            detected_by=detected_by,
            opened_at=opened_at,
            updated_at=opened_at,
        )
        return cls._put_incident(connection, incident)

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
            if observation.observed_at < cancel_command.completed_at:
                raise GatewayValidationError(
                    "cancellation terminal evidence predates governed cancel delivery"
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
                        SELECT tenant_id, incident_id, run_id, dedupe_key,
                               incident_type, severity, summary,
                               trigger_observation_id, details, incident_sha256,
                               detected_by, status, state_version, opened_at, updated_at
                        FROM gda_control.data_incident
                        WHERE tenant_id = :tenant_id
                          AND (CAST(:status AS TEXT) IS NULL OR status = CAST(:status AS TEXT))
                          AND (CAST(:run_id AS UUID) IS NULL OR run_id = CAST(:run_id AS UUID))
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

    def complete_incident_notification(
        self, tenant_id: str, notification_id: UUID, *, worker_id: str
    ) -> IncidentNotification:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.complete_data_incident_notification(
                            :tenant_id, :notification_id, :worker_id
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "notification_id": notification_id,
                        "worker_id": worker_id,
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

    def record_quality_result(self, quality: QualityResult) -> GatewayWriteResult:
        with self._transaction(quality.tenant_id) as connection:
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


def build_gateway_report(
    *,
    tenant_migration: Path | None = None,
    role_migration: Path | None = None,
    command_migration: Path | None = None,
    success_migration: Path | None = None,
    cancel_migration: Path | None = None,
    incident_migration: Path | None = None,
    notification_migration: Path | None = None,
    metadata_fabric_migration: Path | None = None,
    gateway_source: Path | None = None,
    routes_source: Path | None = None,
    command_consumer_source: Path | None = None,
    command_worker_source: Path | None = None,
    notification_worker_source: Path | None = None,
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
        "cancel_migration": (cancel_migration or CANCEL_COMMAND_MIGRATION).resolve(),
        "incident_migration": (incident_migration or DATA_INCIDENT_MIGRATION).resolve(),
        "notification_migration": (
            notification_migration or INCIDENT_NOTIFICATION_MIGRATION
        ).resolve(),
        "metadata_fabric_migration": (
            metadata_fabric_migration or METADATA_FABRIC_MIGRATION
        ).resolve(),
        "gateway_source": (gateway_source or Path(__file__)).resolve(),
        "routes_source": (routes_source or GATEWAY_ROUTES_SOURCE).resolve(),
        "command_consumer_source": (command_consumer_source or COMMAND_CONSUMER_SOURCE).resolve(),
        "command_worker_source": (command_worker_source or COMMAND_WORKER_SOURCE).resolve(),
        "notification_worker_source": (
            notification_worker_source or INCIDENT_NOTIFICATION_WORKER_SOURCE
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
        "notification_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.data_incident_notification_outbox",
            "enqueue_data_incident_notification",
            "FOR UPDATE SKIP LOCKED",
            "claim_data_incident_notifications",
            "complete_data_incident_notification",
            "fail_data_incident_notification",
            "GRANT SELECT ON TABLE gda_control.data_incident_notification_outbox",
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
            "def submit_schedule_window(",
            "def submit_manual_trigger(",
            "def admit_dataops_cancel(",
            "SELECT pg_advisory_xact_lock(:lock_class, :lock_object)",
            "def _validate_run_policy_references(",
            "def record_attempt_and_enqueue_reconcile(",
            "def record_cancellation_terminal_mismatch(",
            "def transition_incident(",
            "def claim_incident_notifications(",
            "def complete_incident_notification(",
            "def fail_incident_notification(",
            "def register_metadata_fabric_binding(",
            "def claim_metadata_changes(",
            "def complete_metadata_change(",
            "def fail_metadata_change(",
            "def claim_commands(",
            "def record_quality_result(",
            "def finalize_run_success(",
            "def record_lineage_batch(",
            "def query_lineage(",
            "def assess_lineage_impact(",
        ),
        "routes_source": (
            'base = "/api/platform/v1"',
            'frozenset({"admin", "platform_operator"})',
            '"tenant_context_required"',
            '"actor_mismatch"',
            "create_dolphinscheduler_callback",
            "create_quality_result",
            "finalize_run_success",
            "create_manual_dataops_run",
            "create_dataops_cancel",
            "list_data_incidents",
            "transition_data_incident",
            "create_approval_case",
            "list_approval_case_events",
            "decide_approval_case",
            "create_openlineage_event",
            "create_metadata_fabric_binding",
            "list_metadata_fabric_bindings",
            "get_resource_version_lineage",
            "get_resource_version_impact",
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
        "notification_worker_source": (
            "class IncidentNotificationWorker",
            "class AlertmanagerV2Client",
            "self.gateway.claim_incident_notifications(",
            "self.gateway.complete_incident_notification(",
            "self.gateway.fail_incident_notification(",
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
            or forbidden in texts.get("notification_migration", "")
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
        "route_count": 23,
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
