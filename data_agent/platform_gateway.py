"""Least-privilege transaction scripts for the AR-1 platform control gateway."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .metadata_fabric_binding_contract import (
    MetadataFabricApplyPlan,
    MetadataFabricBindingContractError,
    MetadataFabricBindingRecord,
    parse_metadata_fabric_execution_plan_artifact,
    parse_metadata_fabric_provider_evidence_artifact,
)
from .metadata_fabric_bridge import (
    MetadataFabricConfigurationError,
    build_metadata_fabric_binding,
)
from .platform_authorization import (
    AuthorizationEvidenceError,
    parse_approval_artifact,
    parse_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
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
    RunSuccessEvidence,
    RunStatus,
    TenantId,
)


GATEWAY_DATABASE_ROLE = "gda_control_gateway"
GATEWAY_SCHEMA_VERSION = "gda.platform_gateway.v1"
GATEWAY_ROLE_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "094_platform_control_gateway.sql"
)
COMMAND_OUTBOX_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "095_platform_command_outbox.sql"
)
SUCCESS_VERDICT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "096_platform_success_verdict.sql"
)
METADATA_FABRIC_BINDING_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "097_metadata_fabric_binding_ledger.sql"
)
USER_TENANT_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "093_app_user_tenant_context.sql"
)
GATEWAY_ROUTES_SOURCE = (
    Path(__file__).resolve().parent / "api" / "platform_gateway_routes.py"
)
COMMAND_CONSUMER_SOURCE = (
    Path(__file__).resolve().parent / "dolphinscheduler_command_consumer.py"
)
COMMAND_WORKER_SOURCE = (
    Path(__file__).resolve().parent / "dolphinscheduler_command_worker.py"
)
_TENANT_ADAPTER = TypeAdapter(TenantId)
METADATA_FABRIC_APPLY_ACTION = "metadata_fabric.apply"


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


class GatewayUnavailableError(PlatformGatewayError):
    code = "platform_unavailable"


@dataclass(frozen=True)
class GatewayWriteResult:
    value: BaseModel
    created: bool


class DefinitionRegistration(BaseModel):
    """Atomic Resource + ResourceVersion + logical definition registration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource: Resource
    resource_version: ResourceVersion
    definition: PlatformDefinitionVersion

    @model_validator(mode="after")
    def _consistent_definition_identity(self) -> "DefinitionRegistration":
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
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
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
        row = connection.execute(
            text(
                """
                SELECT tenant_id, resource_urn, resource_kind, authority_system,
                       authority_locator, owner_ref, governance_ref, technical_refs
                FROM gda_control.resource
                WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn
                """
            ),
            {"tenant_id": tenant_id, "resource_urn": resource_urn},
        ).mappings().one_or_none()
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
        stored = self._load_resource(
            connection, resource.tenant_id, resource.resource_urn
        )
        if stored is None or stored != resource:
            raise GatewayConflictError("Resource identity already has a different payload")
        return GatewayWriteResult(stored, inserted is not None)

    def register_resource(self, resource: Resource) -> GatewayWriteResult:
        with self._transaction(resource.tenant_id) as connection:
            return self._put_resource(connection, resource)

    @staticmethod
    def _load_resource_version(
        connection, tenant_id: str, version_id: UUID
    ) -> ResourceVersion | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["authority_version_ref"] = _as_json(value["authority_version_ref"])
        return ResourceVersion.model_validate(value)

    def _put_resource_version(
        self, connection, version: ResourceVersion
    ) -> GatewayWriteResult:
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
            raise GatewayConflictError(
                "ResourceVersion identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def register_resource_version(
        self, version: ResourceVersion
    ) -> GatewayWriteResult:
        with self._transaction(version.tenant_id) as connection:
            return self._put_resource_version(connection, version)

    @staticmethod
    def _load_definition(
        connection, tenant_id: str, definition_version_id: UUID
    ) -> PlatformDefinitionVersion | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
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

    def register_definition(
        self, registration: DefinitionRegistration
    ) -> GatewayWriteResult:
        with self._transaction(registration.resource.tenant_id) as connection:
            resource_result = self._put_resource(connection, registration.resource)
            version_result = self._put_resource_version(
                connection, registration.resource_version
            )
            definition_result = self._put_definition(
                connection, registration.definition
            )
            return GatewayWriteResult(
                registration,
                resource_result.created
                or version_result.created
                or definition_result.created,
            )

    @staticmethod
    def _load_run(connection, tenant_id: str, run_id: UUID) -> PlatformRun | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
        if row is None:
            return None
        bindings = connection.execute(
            text(
                """
                SELECT binding_name, resource_version_id, semantic_type
                FROM gda_control.platform_run_input_binding
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                ORDER BY binding_name
                """
            ),
            {"tenant_id": tenant_id, "run_id": run_id},
        ).mappings().all()
        value = dict(row)
        value["subject_context"] = _as_json(value["subject_context"])
        value["policy_refs"] = _as_json(value["policy_refs"]) or None
        value["input_bindings"] = [dict(binding) for binding in bindings]
        return PlatformRun.model_validate(value)

    @staticmethod
    def _run_binding(run: PlatformRun) -> dict[str, Any]:
        return run.model_dump(
            mode="json",
            exclude={"status", "state_version"},
        )

    @staticmethod
    def _run_actor(run: PlatformRun) -> str:
        return (
            f"{run.subject_context.subject_type.value}:"
            f"{run.subject_context.subject_id}"
        )

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
    def _load_command(
        cls, connection, tenant_id: str, command_id: UUID
    ) -> PlatformCommand | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
        return cls._command_from_row(row) if row is not None else None

    @classmethod
    def _put_command(
        cls, connection, command: PlatformCommand
    ) -> GatewayWriteResult:
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
        stored = cls._load_command(
            connection, command.tenant_id, command.command_id
        )
        if (
            stored is None
            or cls._command_binding(stored) != cls._command_binding(command)
        ):
            raise GatewayConflictError(
                "platform command identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    @classmethod
    def _dispatch_command(
        cls,
        run: PlatformRun,
        decision: PolicyDecision | None,
        execution_plan: Artifact | None,
    ) -> PlatformCommand:
        if decision is None or execution_plan is None:
            raise GatewayValidationError(
                "dispatch request requires immutable policy references"
            )
        if run.orchestration_class.value != "dataops":
            raise GatewayValidationError("dispatch request requires a dataops Run")
        if run.subject_context.subject_type.value != "workload":
            raise GatewayValidationError(
                "dispatch request requires workload SubjectContext"
            )
        if decision.action != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH.value:
            raise GatewayValidationError(
                "policy decision action does not authorize dispatch"
            )
        dedupe_key = (
            f"dolphinscheduler.dispatch:{run.run_id}:"
            f"{execution_plan.artifact_id}"
        )
        enqueued_at = datetime.now(UTC)
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
                "policy_decision_artifact_id": str(
                    run.policy_refs.policy_decision_artifact_id
                ),
            },
            available_at=enqueued_at,
            created_at=enqueued_at,
        )

    def submit_run(
        self, run: PlatformRun, *, request_dispatch: bool = False
    ) -> GatewayWriteResult:
        with self._transaction(run.tenant_id) as connection:
            decision, execution_plan = self._validate_run_policy_references(
                connection, run
            )
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
                    "subject_context": _json(
                        run.subject_context.model_dump(mode="json")
                    ),
                    "idempotency_key": run.idempotency_key,
                    "policy_refs": _json(
                        run.policy_refs.model_dump(mode="json")
                        if run.policy_refs is not None
                        else {}
                    ),
                    "config_fingerprint": run.config_fingerprint,
                    "submitted_by": actor,
                    "submitted_at": run.submitted_at,
                },
            ).first()
            if inserted is not None:
                for binding in sorted(
                    run.input_bindings, key=lambda item: item.binding_name
                ):
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
                existing_id = connection.execute(
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
                        "tenant_id": run.tenant_id,
                        "definition_version_id": run.definition_version_id,
                        "idempotency_key": run.idempotency_key,
                    },
                ).scalar_one_or_none()
                stored = (
                    self._load_run(connection, run.tenant_id, existing_id)
                    if existing_id is not None
                    else None
                )
            if stored is None or self._run_binding(stored) != self._run_binding(run):
                raise GatewayConflictError(
                    "Run idempotency key already has a different immutable binding"
                )
            if request_dispatch:
                self._put_command(
                    connection,
                    self._dispatch_command(stored, decision, execution_plan),
                )
            return GatewayWriteResult(stored, inserted is not None)

    def get_run(self, tenant_id: str, run_id: UUID) -> PlatformRun:
        with self._transaction(tenant_id) as connection:
            run = self._load_run(connection, tenant_id, run_id)
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            return run

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
            raise GatewayValidationError(
                "succeeded requires evidence-gated Run finalization"
            )
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
        row = connection.execute(
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
        ).mappings().one_or_none()
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

    def record_attempt(
        self, observation: FrameworkAttemptObservation
    ) -> GatewayWriteResult:
        with self._transaction(observation.tenant_id) as connection:
            return self._put_observation(connection, observation)

    @staticmethod
    def _load_quality_result(
        connection, tenant_id: str, quality_result_id: UUID
    ) -> QualityResult | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["metrics"] = _as_json(value["metrics"])
        return QualityResult.model_validate(value)

    def record_quality_result(
        self, quality: QualityResult
    ) -> GatewayWriteResult:
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
                raise GatewayConflictError(
                    "QualityResult identity already has a different payload"
                )
            return GatewayWriteResult(stored, inserted is not None)

    def get_quality_result(
        self, tenant_id: str, quality_result_id: UUID
    ) -> QualityResult:
        with self._transaction(tenant_id) as connection:
            quality = self._load_quality_result(
                connection, tenant_id, quality_result_id
            )
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
            run = self._load_run(
                connection, evidence.tenant_id, evidence.run_id
            )
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
            f"dolphinscheduler.reconcile:{run.run_id}:"
            f"{execution_plan.artifact_id}:{source_id}"
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
    ) -> GatewayWriteResult:
        with self._transaction(observation.tenant_id) as connection:
            run = self._load_run(
                connection, observation.tenant_id, observation.run_id
            )
            if run is None:
                raise GatewayNotFoundError("PlatformRun was not found")
            if observation.framework_kind.value != "dolphinscheduler":
                raise GatewayValidationError(
                    "provider callback must use DolphinScheduler framework kind"
                )
            if run.subject_context.subject_type.value != "workload":
                raise GatewayForbiddenError(
                    "provider callback requires workload SubjectContext"
                )
            if actor_subject != self._run_actor(run):
                raise GatewayForbiddenError(
                    "callback actor does not match Run workload identity"
                )
            decision, execution_plan = self._validate_run_policy_references(
                connection, run
            )
            if decision is None or execution_plan is None:
                raise GatewayValidationError(
                    "provider callback requires immutable execution plan references"
                )
            if decision.action != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH.value:
                raise GatewayValidationError(
                    "Run policy action does not match DolphinScheduler dispatch"
                )
            self._put_observation(connection, observation)
            enqueued_at = datetime.now(UTC)
            command = self._reconcile_command(
                run,
                execution_plan,
                source_id=observation.observation_id,
                trigger_observation_id=observation.observation_id,
                created_at=enqueued_at,
                reason="provider_callback",
            )
            return self._put_command(connection, command)

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
            rows = connection.execute(
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
            ).mappings().all()
            return [self._command_from_row(row) for row in rows]

    def complete_command(
        self, tenant_id: str, command_id: UUID, *, worker_id: str
    ) -> PlatformCommand:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
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
            ).mappings().one()
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
            row = connection.execute(
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
            ).mappings().one()
            return self._command_from_row(row)

    def defer_dispatch_to_reconcile(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
    ) -> PlatformCommand:
        with self._transaction(command.tenant_id) as connection:
            stored = self._load_command(
                connection, command.tenant_id, command.command_id
            )
            if stored != command:
                raise GatewayConflictError("platform command claim changed")
            if (
                command.command_type
                != PlatformCommandType.DOLPHINSCHEDULER_DISPATCH
                or command.status != PlatformCommandStatus.IN_FLIGHT
                or command.claimed_by != worker_id
            ):
                raise GatewayValidationError(
                    "only the dispatch claim owner can defer to reconcile"
                )
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

    @staticmethod
    def _load_artifact(
        connection, tenant_id: str, artifact_id: UUID
    ) -> Artifact | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
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

    def record_artifact(self, artifact: Artifact) -> GatewayWriteResult:
        with self._transaction(artifact.tenant_id) as connection:
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
            stored = self._load_artifact(
                connection, artifact.tenant_id, artifact.artifact_id
            )
            if stored is None or stored != artifact:
                raise GatewayConflictError(
                    "Artifact identity already has a different payload"
                )
            return GatewayWriteResult(stored, inserted is not None)

    @staticmethod
    def _metadata_fabric_binding_from_row(row) -> MetadataFabricBindingRecord:
        value = dict(row)
        value["binding"] = _as_json(value.pop("binding_document"))
        return MetadataFabricBindingRecord.model_validate(value)

    @classmethod
    def _load_metadata_fabric_binding(
        cls, connection, tenant_id: str, resource_version_id: UUID
    ) -> MetadataFabricBindingRecord | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, binding_id, binding_document,
                       execution_plan_artifact_id,
                       policy_decision_artifact_id, approval_artifact_id,
                       provider_evidence_artifact_id, recorded_by, recorded_at,
                       record_sha256
                FROM gda_control.metadata_fabric_binding
                WHERE tenant_id = :tenant_id
                  AND resource_version_id = :resource_version_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "resource_version_id": resource_version_id,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        return cls._metadata_fabric_binding_from_row(row)

    def get_metadata_fabric_binding(
        self, tenant_id: str, resource_version_id: UUID
    ) -> MetadataFabricBindingRecord:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            record = self._load_metadata_fabric_binding(
                connection, tenant, resource_version_id
            )
            if record is None:
                raise GatewayNotFoundError("Metadata Fabric binding was not found")
            return record

    @staticmethod
    def _parse_metadata_fabric_execution_plan(
        artifact: Artifact,
    ) -> MetadataFabricApplyPlan:
        try:
            return parse_metadata_fabric_execution_plan_artifact(artifact)
        except MetadataFabricBindingContractError as exc:
            raise GatewayValidationError(str(exc)) from exc

    def _validate_metadata_fabric_binding_record(
        self, connection, record: MetadataFabricBindingRecord
    ) -> None:
        binding = record.binding
        resource = self._load_resource(
            connection, record.tenant_id, binding.resource_urn
        )
        version = self._load_resource_version(
            connection, record.tenant_id, binding.resource_version_id
        )
        if resource is None or version is None:
            raise GatewayValidationError(
                "Metadata Fabric binding ResourceVersion was not found"
            )
        try:
            expected_binding = build_metadata_fabric_binding(
                resource,
                version,
                openmetadata=binding.openmetadata,
                gravitino=binding.gravitino,
            )
        except MetadataFabricConfigurationError as exc:
            raise GatewayValidationError(str(exc)) from exc
        if binding != expected_binding:
            raise GatewayValidationError(
                "Metadata Fabric binding does not match immutable platform identity"
            )

        artifact_ids = {
            "execution plan": record.execution_plan_artifact_id,
            "policy decision": record.policy_decision_artifact_id,
            "approval": record.approval_artifact_id,
            "provider evidence": record.provider_evidence_artifact_id,
        }
        artifacts: dict[str, Artifact] = {}
        for name, artifact_id in artifact_ids.items():
            artifact = self._load_artifact(
                connection, record.tenant_id, artifact_id
            )
            if artifact is None:
                raise GatewayValidationError(
                    f"Metadata Fabric {name} Artifact was not found"
                )
            artifacts[name] = artifact

        plan = self._parse_metadata_fabric_execution_plan(
            artifacts["execution plan"]
        )
        definition = self._load_definition(
            connection, record.tenant_id, plan.definition_version_id
        )
        source_version = self._load_resource_version(
            connection, record.tenant_id, plan.source_resource_version_id
        )
        if definition is None or source_version is None:
            raise GatewayValidationError(
                "Metadata Fabric authorization scope contains unknown platform versions"
            )
        try:
            decision = parse_policy_decision_artifact(
                artifacts["policy decision"]
            )
            approval = parse_approval_artifact(artifacts["approval"])
            provider_evidence = parse_metadata_fabric_provider_evidence_artifact(
                artifacts["provider evidence"]
            )
        except (AuthorizationEvidenceError, MetadataFabricBindingContractError) as exc:
            raise GatewayValidationError(str(exc)) from exc

        executor = (
            f"{decision.subject_context.subject_type.value}:"
            f"{decision.subject_context.subject_id}"
        )
        expected_scope = tuple(
            sorted(
                {
                    plan.definition_version_id,
                    plan.source_resource_version_id,
                    plan.resource_version_id,
                },
                key=str,
            )
        )
        exact_scope = (
            plan.tenant_id == record.tenant_id == decision.tenant_id
            and plan.run_id == decision.run_id == approval.run_id
            and plan.resource_urn == binding.resource_urn
            and plan.resource_version_id == binding.resource_version_id
            and plan.content_sha256 == binding.content_sha256
            and decision.action == METADATA_FABRIC_APPLY_ACTION
            and decision.definition_version_id == plan.definition_version_id
            and decision.resource_version_ids == expected_scope
            and decision.execution_plan_artifact_id
            == record.execution_plan_artifact_id
            and decision.subject_context.tenant_id == record.tenant_id
            and artifacts["execution plan"].created_by == executor
            and record.recorded_by == executor
        )
        if not exact_scope:
            raise GatewayValidationError(
                "Metadata Fabric authorization does not match the exact binding scope"
            )
        if decision.effect.value != "allow" or decision.obligations:
            raise GatewayValidationError(
                "Metadata Fabric policy decision does not allow binding"
            )
        if not decision.requires_approval:
            raise GatewayValidationError(
                "Metadata Fabric binding requires independent approval"
            )
        if decision.evaluator_subject == executor:
            raise GatewayValidationError(
                "Metadata Fabric policy evaluator is not independent"
            )

        observed_at = provider_evidence.observed_at
        approval_matches = (
            approval.tenant_id == record.tenant_id
            and approval.definition_version_id == plan.definition_version_id
            and approval.policy_decision_artifact_id
            == record.policy_decision_artifact_id
            and approval.policy_decision_sha256
            == artifacts["policy decision"].content_sha256
            and approval.verdict.value == "approved"
            and approval.approver_subject
            not in {executor, decision.evaluator_subject}
            and decision.decided_at <= approval.decided_at <= observed_at
            and observed_at < approval.expires_at <= decision.expires_at
        )
        if not approval_matches:
            raise GatewayValidationError(
                "Metadata Fabric approval does not authorize provider apply"
            )
        if not (decision.decided_at <= observed_at < decision.expires_at):
            raise GatewayValidationError(
                "Metadata Fabric policy was not active at provider observation"
            )
        evidence_matches = (
            provider_evidence.binding == binding
            and artifacts["provider evidence"].created_by == executor
            and record.recorded_at >= observed_at
        )
        if not evidence_matches:
            raise GatewayValidationError(
                "Metadata Fabric provider evidence does not match the binding"
            )

    def commit_metadata_fabric_binding(
        self, record: MetadataFabricBindingRecord
    ) -> GatewayWriteResult:
        with self._transaction(record.tenant_id) as connection:
            self._validate_metadata_fabric_binding_record(connection, record)
            binding = record.binding
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.metadata_fabric_binding (
                        tenant_id, binding_id, resource_urn,
                        resource_version_id, content_sha256, binding_document,
                        binding_sha256, execution_plan_artifact_id,
                        policy_decision_artifact_id, approval_artifact_id,
                        provider_evidence_artifact_id, record_sha256,
                        recorded_by, recorded_at
                    ) VALUES (
                        :tenant_id, :binding_id, :resource_urn,
                        :resource_version_id, :content_sha256,
                        CAST(:binding_document AS jsonb), :binding_sha256,
                        :execution_plan_artifact_id,
                        :policy_decision_artifact_id, :approval_artifact_id,
                        :provider_evidence_artifact_id, :record_sha256,
                        :recorded_by, :recorded_at
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING binding_id
                    """
                ),
                {
                    **record.model_dump(
                        mode="python",
                        exclude={"record_schema", "binding"},
                    ),
                    "resource_urn": binding.resource_urn,
                    "resource_version_id": binding.resource_version_id,
                    "content_sha256": binding.content_sha256,
                    "binding_document": _json(
                        binding.model_dump(mode="json", by_alias=True)
                    ),
                    "binding_sha256": binding.binding_sha256,
                },
            ).first()
            stored = self._load_metadata_fabric_binding(
                connection, record.tenant_id, binding.resource_version_id
            )
            if stored is None or stored != record:
                raise GatewayConflictError(
                    "Metadata Fabric ResourceVersion already has a different binding"
                )
            return GatewayWriteResult(stored, inserted is not None)

    @staticmethod
    def _load_lineage(
        connection, tenant_id: str, lineage_event_id: UUID
    ) -> LineageEvent | None:
        row = connection.execute(
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
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["facets"] = _as_json(value["facets"])
        return LineageEvent.model_validate(value)

    def record_lineage(self, event: LineageEvent) -> GatewayWriteResult:
        with self._transaction(event.tenant_id) as connection:
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
            stored = self._load_lineage(
                connection, event.tenant_id, event.lineage_event_id
            )
            if stored is None or stored != event:
                raise GatewayConflictError(
                    "LineageEvent identity already has a different payload"
                )
            return GatewayWriteResult(stored, inserted is not None)


def build_gateway_report(
    *,
    tenant_migration: Path | None = None,
    role_migration: Path | None = None,
    command_migration: Path | None = None,
    success_migration: Path | None = None,
    binding_migration: Path | None = None,
    gateway_source: Path | None = None,
    routes_source: Path | None = None,
    command_consumer_source: Path | None = None,
    command_worker_source: Path | None = None,
) -> dict[str, Any]:
    """Validate the static role, transaction, and HTTP boundary markers."""
    paths = {
        "tenant_migration": (tenant_migration or USER_TENANT_MIGRATION).resolve(),
        "role_migration": (role_migration or GATEWAY_ROLE_MIGRATION).resolve(),
        "command_migration": (
            command_migration or COMMAND_OUTBOX_MIGRATION
        ).resolve(),
        "success_migration": (
            success_migration or SUCCESS_VERDICT_MIGRATION
        ).resolve(),
        "binding_migration": (
            binding_migration or METADATA_FABRIC_BINDING_MIGRATION
        ).resolve(),
        "gateway_source": (gateway_source or Path(__file__)).resolve(),
        "routes_source": (routes_source or GATEWAY_ROUTES_SOURCE).resolve(),
        "command_consumer_source": (
            command_consumer_source or COMMAND_CONSUMER_SOURCE
        ).resolve(),
        "command_worker_source": (
            command_worker_source or COMMAND_WORKER_SOURCE
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
            (
                "ALTER FUNCTION gda_control.initialize_platform_run_event() "
                "SECURITY DEFINER"
            ),
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
        "binding_migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_fabric_binding",
            "FOREIGN KEY (tenant_id, execution_plan_artifact_id)",
            "FOREIGN KEY (tenant_id, provider_evidence_artifact_id)",
            "ALTER TABLE gda_control.metadata_fabric_binding FORCE ROW LEVEL SECURITY",
            "GRANT SELECT, INSERT ON gda_control.metadata_fabric_binding",
        ),
        "gateway_source": (
            'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"',
            "SELECT set_config('app.current_tenant', :tenant, true)",
            "ON CONFLICT DO NOTHING",
            "def get_artifact(",
            "def _validate_run_policy_references(",
            "def record_attempt_and_enqueue_reconcile(",
            "def claim_commands(",
            "def record_quality_result(",
            "def finalize_run_success(",
            "def commit_metadata_fabric_binding(",
            "def get_metadata_fabric_binding(",
        ),
        "routes_source": (
            'base = "/api/platform/v1"',
            'frozenset({"admin", "platform_operator"})',
            '"tenant_context_required"',
            '"actor_mismatch"',
            "create_dolphinscheduler_callback",
            "create_quality_result",
            "finalize_run_success",
        ),
        "command_consumer_source": (
            "class DolphinSchedulerCommandConsumer",
            "self.gateway.claim_commands(",
            "self.gateway.defer_dispatch_to_reconcile(",
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
            or forbidden in texts.get("binding_migration", "")
        ):
            errors.append(f"gateway role contains forbidden privilege: {forbidden}")
    consumer_source = texts.get("command_consumer_source", "")
    for forbidden in ("while True", "asyncio.create_task", "start_workflow("):
        if forbidden in consumer_source:
            errors.append(
                f"command consumer contains forbidden runtime marker: {forbidden}"
            )
    worker_source = texts.get("command_worker_source", "")
    for forbidden in (
        "start_workflow(",
        ".transition_run(",
        ".finalize_run_success(",
    ):
        if forbidden in worker_source:
            errors.append(
                f"command worker contains forbidden authority marker: {forbidden}"
            )

    return {
        "schema": GATEWAY_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "database_role": GATEWAY_DATABASE_ROLE,
        "route_count": 12,
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
